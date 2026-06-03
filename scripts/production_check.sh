#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$APP_DIR/.env}"

green="$(printf '\033[32m')"
yellow="$(printf '\033[33m')"
red="$(printf '\033[31m')"
reset="$(printf '\033[0m')"

failures=0
warnings=0

pass() {
  printf '%b\n' "${green}OK${reset} $*"
}

warn() {
  warnings=$((warnings + 1))
  printf '%b\n' "${yellow}WARN${reset} $*"
}

fail() {
  failures=$((failures + 1))
  printf '%b\n' "${red}FAIL${reset} $*"
}

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    fail "Environment file not found: $ENV_FILE"
    return
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  pass "Loaded $ENV_FILE"
}

check_env() {
  [[ "${FLASK_ENV:-}" == "production" ]] && pass "FLASK_ENV=production" || fail "Set FLASK_ENV=production"
  [[ "${DATABASE_URL:-}" == postgresql* ]] && pass "DATABASE_URL uses PostgreSQL" || fail "DATABASE_URL must use PostgreSQL in production"
  [[ "${DATABASE_URL:-}" != *sqlite* ]] && pass "SQLite is not configured" || fail "SQLite is configured; use PostgreSQL for production"
  [[ "${CELERY_BROKER_URL:-}" == redis://* ]] && pass "Celery broker uses Redis" || fail "CELERY_BROKER_URL must point to Redis"
  [[ "${CELERY_RESULT_BACKEND:-}" == redis://* ]] && pass "Celery result backend uses Redis" || warn "CELERY_RESULT_BACKEND should point to Redis"
  [[ "${REDIS_URL:-}" == redis://* ]] && pass "REDIS_URL uses Redis" || warn "REDIS_URL should point to Redis"
  [[ -n "${SECRET_KEY:-}" && "${SECRET_KEY:-}" != "change-me" && "${#SECRET_KEY}" -ge 32 ]] && pass "SECRET_KEY is set" || fail "SECRET_KEY must be a long random value"
  [[ "${SESSION_COOKIE_SECURE:-}" == "true" ]] && pass "Secure cookies enabled" || warn "Set SESSION_COOKIE_SECURE=true behind HTTPS"
}

check_dirs() {
  local faiss_dir="${FAISS_INDEX_DIR:-$APP_DIR/faiss_indexes}"
  local snapshot_dir="${SNAPSHOT_DIR:-$APP_DIR/uploads/snapshots}"
  for dir in "$faiss_dir" "$snapshot_dir" "$APP_DIR/logs" "$APP_DIR/backups"; do
    if [[ -d "$dir" && -w "$dir" ]]; then
      pass "Writable directory: $dir"
    else
      fail "Directory missing or not writable: $dir"
    fi
  done
}

check_tools() {
  command -v python3.11 >/dev/null 2>&1 && pass "python3.11 found" || fail "python3.11 not found"
  command -v psql >/dev/null 2>&1 && pass "psql found" || warn "psql not found; database checks are limited"
  command -v redis-cli >/dev/null 2>&1 && pass "redis-cli found" || warn "redis-cli not found; Redis checks are limited"
}

check_app() {
  if [[ ! -x "$APP_DIR/.venv/bin/flask" ]]; then
    warn ".venv flask not found; install requirements before migration checks"
    return
  fi
  (
    cd "$APP_DIR"
    "$APP_DIR/.venv/bin/flask" --app manage:app db heads >/dev/null
  ) && pass "Alembic heads are readable" || fail "Alembic cannot read migration heads"
  (
    cd "$APP_DIR"
    "$APP_DIR/.venv/bin/flask" --app manage:app db current >/dev/null
  ) && pass "Database migration state is readable" || warn "Cannot read current database migration state"
}

printf 'Human-Brain production preflight\n'
load_env
check_tools
check_env
check_dirs
check_app

printf '\nSummary: %s failure(s), %s warning(s)\n' "$failures" "$warnings"
if [[ "$failures" -gt 0 ]]; then
  exit 1
fi
