#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
DATABASE_URL="${DATABASE_URL:-}"
S3_BACKUP_BUCKET="${S3_BACKUP_BUCKET:-payment-platform-backups}"
AWS_REGION="${AWS_REGION:-us-east-1}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

check_prerequisites() {
    if [ -z "$DATABASE_URL" ]; then
        error "DATABASE_URL environment variable not set"
        exit 1
    fi
    
    command -v psql > /dev/null || {
        error "psql command not found"
        exit 1
    }
}

list_available_backups() {
    log "Available backups:"
    log "=================="
    
    echo ""
    echo "Local backups:"
    find "$BACKUP_DIR" -name "*.sql.gz*" -type f -mtime -30 2>/dev/null | sort -r | head -20 || true
    
    echo ""
    echo "S3 backups:"
    aws s3 ls "s3://${S3_BACKUP_BUCKET}/database/" --region "$AWS_REGION" 2>/dev/null | grep ".sql.gz" | tail -20 || true
}

download_from_s3() {
    local s3_key="$1"
    local local_path="${2:-${BACKUP_DIR}/$(basename "$s3_key")}"
    
    log "Downloading backup from S3: s3://${S3_BACKUP_BUCKET}/${s3_key}"
    
    aws s3 cp "s3://${S3_BACKUP_BUCKET}/${s3_key}" "$local_path" --region "$AWS_REGION"
    
    log "Download completed: $local_path"
    echo "$local_path"
}

decrypt_backup() {
    local backup_path="$1"
    
    if [[ "$backup_path" != *.enc ]]; then
        echo "$backup_path"
        return
    fi
    
    if [ -z "${ENCRYPTION_KEY:-}" ]; then
        error "ENCRYPTION_KEY not set for encrypted backup"
        exit 1
    fi
    
    log "Decrypting backup..."
    
    local decrypted_path="${backup_path%.enc}"
    
    openssl enc -aes-256-cbc -d \
        -pbkdf2 \
        -iter 100000 \
        -in "$backup_path" \
        -out "$decrypted_path" \
        -pass pass:"$ENCRYPTION_KEY"
    
    log "Backup decrypted: $decrypted_path"
    echo "$decrypted_path"
}

verify_backup_integrity() {
    local backup_path="$1"
    
    log "Verifying backup integrity..."
    
    local checksum_file="${backup_path}.sha256"
    
    if [ -f "$checksum_file" ]; then
        if sha256sum -c "$checksum_file" --quiet 2>/dev/null; then
            log "Checksum verification passed"
        else
            error "Checksum verification failed"
            return 1
        fi
    fi
    
    if ! gzip -t "$backup_path" 2>/dev/null; then
        error "Backup file is corrupted"
        return 1
    fi
    
    log "Backup integrity verified"
    return 0
}

create_database_backup() {
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_path="${BACKUP_DIR}/pre_restore_${timestamp}.sql.gz"
    
    log "Creating safety backup before restore..."
    
    pg_dump "$DATABASE_URL" --format=plain --no-owner --no-acl 2>/dev/null | gzip > "$backup_path"
    
    log "Safety backup created: $backup_path"
}

disable_connections() {
    log "Disabling new connections..."
    
    local db_name
    db_name=$(echo "$DATABASE_URL" | sed 's/.*\/\([^/]*\)$/\1/')
    
    psql "$DATABASE_URL" -c "
        UPDATE pg_database SET datallowconn = false WHERE datname = '$db_name';
    " > /dev/null 2>&1 || true
    
    log "Terminating existing connections..."
    psql "$DATABASE_URL" -c "
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = '$db_name' AND pid <> pg_backend_pid();
    " > /dev/null 2>&1 || true
}

enable_connections() {
    log "Enabling connections..."
    
    local db_name
    db_name=$(echo "$DATABASE_URL" | sed 's/.*\/\([^/]*\)$/\1/')
    
    psql "$DATABASE_URL" -c "
        UPDATE pg_database SET datallowconn = true WHERE datname = '$db_name';
    " > /dev/null 2>&1 || true
}

drop_existing_objects() {
    log "Dropping existing database objects..."
    
    psql "$DATABASE_URL" -c "
        DO \$\$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
            
            FOR r IN (SELECT sequencename FROM pg_sequences WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP SEQUENCE IF EXISTS ' || quote_ident(r.sequencename) || ' CASCADE';
            END LOOP;
            
            FOR r IN (SELECT viewname FROM pg_views WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP VIEW IF EXISTS ' || quote_ident(r.viewname) || ' CASCADE';
            END LOOP;
            
            FOR r IN (SELECT matviewname FROM pg_matviews WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP MATERIALIZED VIEW IF EXISTS ' || quote_ident(r.matviewname) || ' CASCADE';
            END LOOP;
            
            FOR r IN (SELECT proname, oidvectortypes(proargtypes) as args 
                      FROM pg_proc WHERE pronamespace = 'public'::regnamespace) LOOP
                EXECUTE 'DROP FUNCTION IF EXISTS ' || quote_ident(r.proname) || '(' || r.args || ') CASCADE';
            END LOOP;
        END \$\$;
    " > /dev/null 2>&1
}

restore_database() {
    local backup_path="$1"
    
    log "Restoring database from: $backup_path"
    
    if [[ "$backup_path" == *.enc ]]; then
        backup_path=$(decrypt_backup "$backup_path")
    fi
    
    verify_backup_integrity "$backup_path"
    
    create_database_backup
    
    log "Starting restore process..."
    
    local start_time
    start_time=$(date +%s)
    
    zcat "$backup_path" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q 2>&1 | while read -r line; do
        [ -n "$line" ] && log "$line"
    done
    
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Restore completed in ${duration}s"
}

validate_restore() {
    log "Validating restore..."
    
    local table_count
    table_count=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'" | tr -d ' ')
    
    log "Tables restored: $table_count"
    
    local schema_migrations_count
    schema_migrations_count=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM schema_migrations" 2>/dev/null | tr -d ' ' || echo "0")
    
    log "Migrations applied: $schema_migrations_count"
    
    psql "$DATABASE_URL" -c "SELECT version FROM schema_migrations ORDER BY id DESC LIMIT 5" 2>/dev/null || true
    
    log "Restore validation completed"
}

send_notification() {
    local status="$1"
    local backup_path="$2"
    local message
    
    if [ "$status" = "success" ]; then
        message="Database restore completed successfully from: $(basename "$backup_path")"
    else
        message="Database restore failed"
    fi
    
    if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
        curl -sf -X POST "$SLACK_WEBHOOK_URL" \
            -H 'Content-Type: application/json' \
            -d "{\"text\":\"$message\"}" \
            > /dev/null 2>&1 || true
    fi
    
    log "$message"
}

run_analysis() {
    log "Running database analysis..."
    
    psql "$DATABASE_URL" -c "VACUUM ANALYZE;" > /dev/null 2>&1
    
    log "Database analysis completed"
}

main() {
    local backup_source="${1:-}"
    local backup_path=""
    
    check_prerequisites
    
    if [ -z "$backup_source" ]; then
        list_available_backups
        echo ""
        echo "Usage: $0 <backup_file_or_s3_key>"
        exit 1
    fi
    
    log "========================================"
    log "Database Restore Started"
    log "Source: $backup_source"
    log "========================================"
    
    trap 'error "Restore interrupted"; enable_connections; exit 1' INT TERM
    
    if [[ "$backup_source" == s3://* ]]; then
        local s3_key
        s3_key=$(echo "$backup_source" | sed "s|s3://${S3_BACKUP_BUCKET}/||")
        backup_path=$(download_from_s3 "$s3_key")
    elif [ -f "$backup_source" ]; then
        backup_path="$backup_source"
    else
        backup_path=$(download_from_s3 "$backup_source")
    fi
    
    if restore_database "$backup_path"; then
        validate_restore
        run_analysis
        send_notification "success" "$backup_path"
        
        log "========================================"
        log "Database Restore Completed Successfully"
        log "========================================"
        exit 0
    else
        send_notification "failed" "$backup_path"
        
        log "========================================"
        log "Database Restore Failed"
        log "========================================"
        exit 1
    fi
}

case "${1:-}" in
    list)
        check_prerequisites
        list_available_backups
        ;;
    download)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 download <s3_key>"
            exit 1
        fi
        check_prerequisites
        download_from_s3 "$2"
        ;;
    verify)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 verify <backup_path>"
            exit 1
        fi
        check_prerequisites
        verify_backup_integrity "$2"
        ;;
    decrypt)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 decrypt <backup_path>"
            exit 1
        fi
        decrypt_backup "$2"
        ;;
    restore)
        main "${2:-}"
        ;;
    "")
        list_available_backups
        ;;
    *)
        main "$1"
        ;;
esac
