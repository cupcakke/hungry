#!/bin/bash
set -euo pipefail

MIGRATION_DIR="${MIGRATION_DIR:-/app/backend/migrations}"
DATABASE_URL="${DATABASE_URL:-}"
MIGRATION_TABLE="${MIGRATION_TABLE:-schema_migrations}"
LOCK_TIMEOUT="${LOCK_TIMEOUT:-300}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_DELAY="${RETRY_DELAY:-5}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

check_database_connection() {
    log "Checking database connection..."
    
    for i in $(seq 1 "$MAX_RETRIES"); do
        if psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
            log "Database connection successful"
            return 0
        fi
        
        log "Database connection attempt $i failed, retrying in ${RETRY_DELAY}s..."
        sleep "$RETRY_DELAY"
    done
    
    error "Failed to connect to database after $MAX_RETRIES attempts"
    return 1
}

acquire_migration_lock() {
    log "Acquiring migration lock..."
    
    psql "$DATABASE_URL" -c "SELECT pg_advisory_lock(12345)" > /dev/null 2>&1
    LOCK_ACQUIRED=true
    log "Migration lock acquired"
}

release_migration_lock() {
    if [ "${LOCK_ACQUIRED:-false}" = "true" ]; then
        log "Releasing migration lock..."
        psql "$DATABASE_URL" -c "SELECT pg_advisory_unlock(12345)" > /dev/null 2>&1 || true
        LOCK_ACQUIRED=false
        log "Migration lock released"
    fi
}

create_migration_table() {
    log "Creating migration table if not exists..."
    
    psql "$DATABASE_URL" -c "
        CREATE TABLE IF NOT EXISTS $MIGRATION_TABLE (
            id SERIAL PRIMARY KEY,
            version VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            checksum VARCHAR(64),
            execution_time_ms INTEGER
        )
    " > /dev/null 2>&1
    
    log "Migration table ready"
}

get_applied_migrations() {
    psql "$DATABASE_URL" -t -c "SELECT version FROM $MIGRATION_TABLE ORDER BY version" | tr -d ' '
}

get_pending_migrations() {
    local applied_migrations="$1"
    
    find "$MIGRATION_DIR/versions" -name "*.py" -type f 2>/dev/null | sort | while read -r file; do
        local version
        version=$(basename "$file" .py)
        
        if ! echo "$applied_migrations" | grep -q "^$version$"; then
            echo "$file"
        fi
    done
}

apply_migration() {
    local migration_file="$1"
    local version
    version=$(basename "$migration_file" .py)
    
    log "Applying migration: $version"
    
    local start_time
    start_time=$(date +%s%3N)
    
    local checksum
    checksum=$(sha256sum "$migration_file" | awk '{print $1}')
    
    if ! python "$migration_file" 2>&1; then
        error "Migration $version failed"
        return 1
    fi
    
    local end_time
    end_time=$(date +%s%3N)
    local execution_time=$((end_time - start_time))
    
    psql "$DATABASE_URL" -c "
        INSERT INTO $MIGRATION_TABLE (version, checksum, execution_time_ms)
        VALUES ('$version', '$checksum', $execution_time)
    " > /dev/null 2>&1
    
    log "Migration $version applied successfully (${execution_time}ms)"
}

rollback_migration() {
    local version="$1"
    local migration_file="$MIGRATION_DIR/versions/$version.py"
    
    log "Rolling back migration: $version"
    
    if [ ! -f "$migration_file" ]; then
        error "Migration file not found: $migration_file"
        return 1
    fi
    
    if ! python -c "import sys; sys.path.insert(0, '$MIGRATION_DIR'); from versions.$version import downgrade; downgrade()" 2>&1; then
        error "Rollback of $version failed"
        return 1
    fi
    
    psql "$DATABASE_URL" -c "DELETE FROM $MIGRATION_TABLE WHERE version = '$version'" > /dev/null 2>&1
    
    log "Migration $version rolled back successfully"
}

validate_migrations() {
    log "Validating migrations..."
    
    local applied_migrations
    applied_migrations=$(get_applied_migrations)
    
    while IFS= read -r migration_file; do
        [ -z "$migration_file" ] && continue
        
        local version
        version=$(basename "$migration_file" .py)
        
        local current_checksum
        current_checksum=$(sha256sum "$migration_file" | awk '{print $1}')
        
        local stored_checksum
        stored_checksum=$(psql "$DATABASE_URL" -t -c "SELECT checksum FROM $MIGRATION_TABLE WHERE version = '$version'" | tr -d ' ')
        
        if [ -n "$stored_checksum" ] && [ "$current_checksum" != "$stored_checksum" ]; then
            error "Migration checksum mismatch for $version"
            error "Stored: $stored_checksum, Current: $current_checksum"
            return 1
        fi
    done <<< "$(find "$MIGRATION_DIR/versions" -name "*.py" -type f 2>/dev/null | sort)"
    
    log "Migration validation passed"
}

run_migrations() {
    log "Starting migration process..."
    
    check_database_connection
    create_migration_table
    acquire_migration_lock
    
    local applied_migrations
    applied_migrations=$(get_applied_migrations)
    
    local pending_migrations
    pending_migrations=$(get_pending_migrations "$applied_migrations")
    
    if [ -z "$pending_migrations" ]; then
        log "No pending migrations found"
        release_migration_lock
        return 0
    fi
    
    local count
    count=$(echo "$pending_migrations" | wc -l)
    log "Found $count pending migrations"
    
    while IFS= read -r migration_file; do
        [ -z "$migration_file" ] && continue
        
        if ! apply_migration "$migration_file"; then
            error "Migration failed, stopping"
            release_migration_lock
            return 1
        fi
    done <<< "$pending_migrations"
    
    log "All migrations applied successfully"
    release_migration_lock
}

status() {
    log "Migration status:"
    
    check_database_connection
    
    local applied_count
    applied_count=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM $MIGRATION_TABLE" | tr -d ' ')
    
    local pending_count
    pending_count=$(get_pending_migrations "$(get_applied_migrations)" | wc -l)
    
    echo "Applied: $applied_count"
    echo "Pending: $pending_count"
    
    if [ "$pending_count" -gt 0 ]; then
        echo ""
        echo "Pending migrations:"
        get_pending_migrations "$(get_applied_migrations)" | while read -r file; do
            echo "  - $(basename "$file" .py)"
        done
    fi
}

cleanup() {
    release_migration_lock
}

trap cleanup EXIT

case "${1:-migrate}" in
    migrate)
        run_migrations
        ;;
    rollback)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 rollback <version>"
            exit 1
        fi
        check_database_connection
        acquire_migration_lock
        rollback_migration "$2"
        release_migration_lock
        ;;
    status)
        status
        ;;
    validate)
        check_database_connection
        validate_migrations
        ;;
    *)
        echo "Usage: $0 {migrate|rollback <version>|status|validate}"
        exit 1
        ;;
esac
