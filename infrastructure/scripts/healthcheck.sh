#!/bin/bash
set -euo pipefail

HEALTH_CHECK_PORT="${HEALTH_CHECK_PORT:-8000}"
HEALTH_CHECK_PATH="${HEALTH_CHECK_PATH:-/health}"
HEALTH_CHECK_TIMEOUT="${HEALTH_CHECK_TIMEOUT:-5}"
DATABASE_URL="${DATABASE_URL:-}"
REDIS_URL="${REDIS_URL:-}"
EXTERNAL_DEPENDENCIES="${EXTERNAL_DEPENDENCIES:-true}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

check_http_endpoint() {
    local url="$1"
    local timeout="${2:-$HEALTH_CHECK_TIMEOUT}"
    
    if curl -sf --max-time "$timeout" "$url" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

check_database() {
    log "Checking database connection..."
    
    if [ -z "$DATABASE_URL" ]; then
        error "DATABASE_URL not set"
        return 1
    fi
    
    if pg_isready -d "$DATABASE_URL" > /dev/null 2>&1; then
        log "Database connection: OK"
        return 0
    fi
    
    if psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
        log "Database connection: OK"
        return 0
    fi
    
    error "Database connection: FAILED"
    return 1
}

check_redis() {
    log "Checking Redis connection..."
    
    if [ -z "$REDIS_URL" ]; then
        error "REDIS_URL not set"
        return 1
    fi
    
    if redis-cli -u "$REDIS_URL" ping > /dev/null 2>&1; then
        log "Redis connection: OK"
        return 0
    fi
    
    error "Redis connection: FAILED"
    return 1
}

check_application() {
    log "Checking application health..."
    
    local url="http://localhost:${HEALTH_CHECK_PORT}${HEALTH_CHECK_PATH}"
    
    local response
    local http_code
    
    response=$(curl -sf --max-time "$HEALTH_CHECK_TIMEOUT" -w "\n%{http_code}" "$url" 2>/dev/null) || {
        error "Application health check failed: Unable to connect"
        return 1
    }
    
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ]; then
        log "Application health: OK"
        return 0
    fi
    
    error "Application health check failed: HTTP $http_code"
    error "Response: $body"
    return 1
}

check_disk_space() {
    log "Checking disk space..."
    
    local threshold=90
    local usage
    
    usage=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
    
    if [ "$usage" -lt "$threshold" ]; then
        log "Disk space: OK (${usage}% used)"
        return 0
    fi
    
    error "Disk space: WARNING (${usage}% used, threshold: ${threshold}%)"
    return 1
}

check_memory() {
    log "Checking memory..."
    
    local threshold=90
    local mem_total
    local mem_available
    local mem_usage
    
    if [ -f /proc/meminfo ]; then
        mem_total=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
        mem_available=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
        
        if [ -n "$mem_total" ] && [ -n "$mem_available" ]; then
            mem_usage=$((100 - (mem_available * 100 / mem_total)))
            
            if [ "$mem_usage" -lt "$threshold" ]; then
                log "Memory: OK (${mem_usage}% used)"
                return 0
            fi
            
            error "Memory: WARNING (${mem_usage}% used, threshold: ${threshold}%)"
            return 1
        fi
    fi
    
    log "Memory check: SKIPPED (unable to read /proc/meminfo)"
    return 0
}

check_cpu_load() {
    log "Checking CPU load..."
    
    local threshold=8
    local load
    
    load=$(awk '{print $1}' /proc/loadavg | cut -d. -f1)
    
    if [ "$load" -lt "$threshold" ]; then
        log "CPU load: OK (${load})"
        return 0
    fi
    
    error "CPU load: WARNING (${load}, threshold: ${threshold})"
    return 1
}

check_ssl_certificates() {
    log "Checking SSL certificates..."
    
    local cert_dir="${SSL_CERT_DIR:-/etc/nginx/ssl}"
    
    if [ -d "$cert_dir" ]; then
        local cert_file
        for cert_file in "$cert_dir"/*.crt; do
            [ -f "$cert_file" ] || continue
            
            local expiry
            expiry=$(openssl x509 -in "$cert_file" -noout -enddate 2>/dev/null | cut -d= -f2)
            
            if [ -n "$expiry" ]; then
                local expiry_epoch
                local current_epoch
                
                expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$expiry" +%s 2>/dev/null)
                current_epoch=$(date +%s)
                
                local days_remaining=$(( (expiry_epoch - current_epoch) / 86400 ))
                
                if [ "$days_remaining" -gt 7 ]; then
                    log "SSL certificate $(basename "$cert_file"): OK (${days_remaining} days remaining)"
                else
                    error "SSL certificate $(basename "$cert_file"): WARNING (${days_remaining} days remaining)"
                    return 1
                fi
            fi
        done
    fi
    
    return 0
}

run_comprehensive_check() {
    local failures=0
    
    log "Starting comprehensive health check..."
    log "======================================"
    
    check_application || failures=$((failures + 1))
    
    if [ "$EXTERNAL_DEPENDENCIES" = "true" ]; then
        check_database || failures=$((failures + 1))
        check_redis || failures=$((failures + 1))
    fi
    
    check_disk_space || failures=$((failures + 1))
    check_memory || failures=$((failures + 1))
    check_cpu_load || failures=$((failures + 1))
    check_ssl_certificates || failures=$((failures + 1))
    
    log "======================================"
    
    if [ "$failures" -eq 0 ]; then
        log "Health check passed: All systems operational"
        return 0
    else
        error "Health check failed: $failures issue(s) detected"
        return 1
    fi
}

run_liveness_check() {
    local url="http://localhost:${HEALTH_CHECK_PORT}${HEALTH_CHECK_PATH}"
    check_http_endpoint "$url" "$HEALTH_CHECK_TIMEOUT"
}

run_readiness_check() {
    check_application || return 1
    
    if [ "$EXTERNAL_DEPENDENCIES" = "true" ]; then
        check_database || return 1
        check_redis || return 1
    fi
    
    return 0
}

case "${1:-full}" in
    full)
        run_comprehensive_check
        ;;
    liveness)
        run_liveness_check
        ;;
    readiness)
        run_readiness_check
        ;;
    database)
        check_database
        ;;
    redis)
        check_redis
        ;;
    app)
        check_application
        ;;
    quick)
        run_liveness_check
        ;;
    *)
        echo "Usage: $0 {full|liveness|readiness|database|redis|app|quick}"
        exit 1
        ;;
esac
