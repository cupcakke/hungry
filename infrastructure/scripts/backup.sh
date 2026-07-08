#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
DATABASE_URL="${DATABASE_URL:-}"
S3_BACKUP_BUCKET="${S3_BACKUP_BUCKET:-payment-platform-backups}"
AWS_REGION="${AWS_REGION:-us-east-1}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_NAME="${BACKUP_NAME:-payment_platform}"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_FILE="${BACKUP_NAME}_${TIMESTAMP}.sql.gz"

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
    
    mkdir -p "$BACKUP_DIR"
}

create_backup() {
    log "Starting database backup..."
    
    local backup_path="${BACKUP_DIR}/${BACKUP_FILE}"
    
    log "Creating backup: $backup_path"
    
    pg_dump "$DATABASE_URL" \
        --format=plain \
        --no-owner \
        --no-acl \
        --clean \
        --if-exists \
        --verbose \
        2>/dev/null | gzip > "$backup_path"
    
    if [ ! -f "$backup_path" ]; then
        error "Backup file was not created"
        exit 1
    fi
    
    local size
    size=$(du -h "$backup_path" | awk '{print $1}')
    log "Backup created successfully: $size"
    
    echo "$backup_path"
}

create_backup_with_schema() {
    log "Creating backup with separate schema..."
    
    local backup_path="${BACKUP_DIR}/${BACKUP_NAME}_${TIMESTAMP}.sql.gz"
    local schema_path="${BACKUP_DIR}/${BACKUP_NAME}_${TIMESTAMP}_schema.sql"
    
    log "Dumping schema..."
    pg_dump "$DATABASE_URL" \
        --schema-only \
        --no-owner \
        --no-acl \
        > "$schema_path"
    
    log "Dumping data..."
    pg_dump "$DATABASE_URL" \
        --data-only \
        --no-owner \
        --no-acl \
        --verbose \
        2>/dev/null | gzip > "$backup_path"
    
    log "Compressing schema..."
    gzip "$schema_path"
    
    log "Backup with schema created successfully"
    
    echo "$backup_path"
}

encrypt_backup() {
    local backup_path="$1"
    
    if [ -z "${ENCRYPTION_KEY:-}" ]; then
        log "No encryption key set, skipping encryption"
        echo "$backup_path"
        return
    fi
    
    log "Encrypting backup..."
    
    local encrypted_path="${backup_path}.enc"
    
    openssl enc -aes-256-cbc \
        -salt \
        -pbkdf2 \
        -iter 100000 \
        -in "$backup_path" \
        -out "$encrypted_path" \
        -pass pass:"$ENCRYPTION_KEY"
    
    rm -f "$backup_path"
    
    log "Backup encrypted: $encrypted_path"
    echo "$encrypted_path"
}

upload_to_s3() {
    local backup_path="$1"
    local s3_key="database/$(basename "$backup_path")"
    
    log "Uploading backup to S3: s3://${S3_BACKUP_BUCKET}/${s3_key}"
    
    aws s3 cp "$backup_path" "s3://${S3_BACKUP_BUCKET}/${s3_key}" \
        --storage-class STANDARD_IA \
        --region "$AWS_REGION"
    
    log "Upload completed"
    
    echo "s3://${S3_BACKUP_BUCKET}/${s3_key}"
}

verify_backup() {
    local backup_path="$1"
    
    log "Verifying backup integrity..."
    
    if [[ "$backup_path" == *.enc ]]; then
        if [ -z "${ENCRYPTION_KEY:-}" ]; then
            error "Cannot verify encrypted backup without ENCRYPTION_KEY"
            return 1
        fi
        
        if ! openssl enc -aes-256-cbc -d -pbkdf2 -iter 100000 \
            -in "$backup_path" \
            -pass pass:"$ENCRYPTION_KEY" 2>/dev/null | gzip -t 2>/dev/null; then
            error "Backup verification failed"
            return 1
        fi
    else
        if ! gzip -t "$backup_path" 2>/dev/null; then
            error "Backup verification failed"
            return 1
        fi
    fi
    
    log "Backup verification passed"
    return 0
}

cleanup_old_backups() {
    log "Cleaning up old backups (older than $RETENTION_DAYS days)..."
    
    find "$BACKUP_DIR" -name "${BACKUP_NAME}_*.sql.gz*" -type f -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    if [ -n "$S3_BACKUP_BUCKET" ]; then
        aws s3 ls "s3://${S3_BACKUP_BUCKET}/database/" \
            --region "$AWS_REGION" \
            | awk '{print $4}' \
            | while read -r key; do
                local file_date
                file_date=$(echo "$key" | grep -oE '[0-9]{8}' || true)
                
                if [ -n "$file_date" ]; then
                    local cutoff_date
                    cutoff_date=$(date -d "-$RETENTION_DAYS days" +%Y%m%d)
                    
                    if [ "$file_date" -lt "$cutoff_date" ]; then
                        log "Deleting old S3 backup: $key"
                        aws s3 rm "s3://${S3_BACKUP_BUCKET}/database/$key" --region "$AWS_REGION" || true
                    fi
                fi
            done
    fi
    
    log "Cleanup completed"
}

calculate_checksum() {
    local backup_path="$1"
    
    local checksum
    checksum=$(sha256sum "$backup_path" | awk '{print $1}')
    
    echo "${backup_path}.sha256"
    echo "$checksum  $(basename "$backup_path")" > "${backup_path}.sha256"
    
    log "Checksum: $checksum"
}

send_notification() {
    local status="$1"
    local backup_path="$2"
    local message
    
    if [ "$status" = "success" ]; then
        message="Database backup completed successfully: $(basename "$backup_path")"
    else
        message="Database backup failed"
    fi
    
    if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
        curl -sf -X POST "$SLACK_WEBHOOK_URL" \
            -H 'Content-Type: application/json' \
            -d "{\"text\":\"$message\"}" \
            > /dev/null 2>&1 || true
    fi
    
    log "$message"
}

main() {
    local backup_path=""
    local s3_path=""
    local exit_code=0
    
    check_prerequisites
    
    log "========================================"
    log "Database Backup Started"
    log "Timestamp: $TIMESTAMP"
    log "========================================"
    
    trap 'error "Backup interrupted"; exit 1' INT TERM
    
    if backup_path=$(create_backup); then
        calculate_checksum "$backup_path"
        
        if [ "${ENCRYPT_BACKUP:-false}" = "true" ]; then
            backup_path=$(encrypt_backup "$backup_path")
        fi
        
        if verify_backup "$backup_path"; then
            if [ "${UPLOAD_TO_S3:-true}" = "true" ] && [ -n "$S3_BACKUP_BUCKET" ]; then
                s3_path=$(upload_to_s3 "$backup_path")
                upload_to_s3 "${backup_path}.sha256"
            fi
            
            send_notification "success" "$backup_path"
        else
            error "Backup verification failed"
            exit_code=1
        fi
    else
        error "Backup creation failed"
        exit_code=1
    fi
    
    cleanup_old_backups
    
    log "========================================"
    log "Database Backup Completed"
    log "Local: $backup_path"
    [ -n "$s3_path" ] && log "S3: $s3_path"
    log "========================================"
    
    exit $exit_code
}

case "${1:-backup}" in
    backup)
        main
        ;;
    verify)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 verify <backup_path>"
            exit 1
        fi
        verify_backup "$2"
        ;;
    cleanup)
        cleanup_old_backups
        ;;
    encrypt)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 encrypt <backup_path>"
            exit 1
        fi
        encrypt_backup "$2"
        ;;
    upload)
        if [ -z "${2:-}" ]; then
            error "Usage: $0 upload <backup_path>"
            exit 1
        fi
        upload_to_s3 "$2"
        ;;
    *)
        echo "Usage: $0 {backup|verify <path>|cleanup|encrypt <path>|upload <path>}"
        exit 1
        ;;
esac
