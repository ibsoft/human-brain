#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="Human-Brain"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

bold="$(printf '\033[1m')"
dim="$(printf '\033[2m')"
red="$(printf '\033[31m')"
green="$(printf '\033[32m')"
yellow="$(printf '\033[33m')"
blue="$(printf '\033[34m')"
magenta="$(printf '\033[35m')"
cyan="$(printf '\033[36m')"
reset="$(printf '\033[0m')"

MODE=""
YES=0
SKIP_DEPS=0
SKIP_SYSTEMD=0
ENV_WRITTEN=0

usage() {
  cat <<USAGE
${bold}${APP_NAME} interactive setup${reset}

Usage:
  scripts/setup.sh [options]

Options:
  --mode MODE       development, production, or docker
  --yes             Accept defaults for yes/no prompts
  --skip-deps       Do not create .venv or install Python dependencies
  --skip-systemd    Do not offer native production systemd installation
  -h, --help        Show this help
USAGE
}

log() {
  printf '%b\n' "${blue}==>${reset} $*"
}

ok() {
  printf '%b\n' "${green}OK${reset} $*"
}

warn() {
  printf '%b\n' "${yellow}!${reset} $*"
}

die() {
  printf '%b\n' "${red}error:${reset} $*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

spin() {
  local message="$1"
  shift
  local log_file
  log_file="$(mktemp)"
  printf '%b' "${cyan}${message}${reset} "
  "$@" >"$log_file" 2>&1 &
  local pid=$!
  local frames='|/-\'
  local i=0
  while kill -0 "$pid" >/dev/null 2>&1; do
    printf '\r%b %s' "${cyan}${message}${reset}" "${frames:i++%4:1}"
    sleep 0.12
  done
  if wait "$pid"; then
    printf '\r%b %b\n' "${cyan}${message}${reset}" "${green}done${reset}"
    rm -f "$log_file"
  else
    printf '\r%b %b\n' "${cyan}${message}${reset}" "${red}failed${reset}"
    sed -n '1,160p' "$log_file" >&2
    rm -f "$log_file"
    return 1
  fi
}

prompt() {
  local label="$1"
  local default="$2"
  local value
  if [[ "$YES" -eq 1 ]]; then
    printf '%s\n' "$default"
    return
  fi
  if [[ -n "$default" ]]; then
    read -r -p "$(printf '%b' "${bold}${label}${reset} [${default}]: ")" value
    printf '%s\n' "${value:-$default}"
  else
    read -r -p "$(printf '%b' "${bold}${label}${reset}: ")" value
    printf '%s\n' "$value"
  fi
}

prompt_secret() {
  local label="$1"
  local value
  read -r -s -p "$(printf '%b' "${bold}${label}${reset}: ")" value
  printf '\n' >&2
  printf '%s\n' "$value"
}

confirm() {
  local label="$1"
  local default="${2:-y}"
  local suffix answer
  if [[ "$YES" -eq 1 ]]; then
    [[ "$default" =~ ^[Yy]$ ]]
    return
  fi
  if [[ "$default" =~ ^[Yy]$ ]]; then
    suffix="Y/n"
  else
    suffix="y/N"
  fi
  read -r -p "$(printf '%b' "${bold}${label}${reset} [$suffix]: ")" answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]$ ]]
}

random_secret() {
  if have openssl; then
    openssl rand -hex 32
  else
    date +%s%N | sha256sum | awk '{print $1}'
  fi
}

sql_quote() {
  printf "%s" "$1" | sed "s/'/''/g"
}

validate_identifier() {
  local label="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "$label must start with a letter or underscore and contain only letters, numbers, and underscores"
}

url_quote() {
  local value="$1"
  if have python3.11; then
    python3.11 -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "$value"
  elif have python3; then
    python3 -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "$value"
  else
    [[ "$value" != *[':@/?#[]']* ]] || die "database password contains URL-special characters; install python3.11 so setup can encode it"
    printf '%s\n' "$value"
  fi
}

write_env() {
  local flask_env="$1"
  local human_brain_url="$2"
  local secret_key="$3"
  local database_url="$4"
  local redis_host="$5"
  local ratelimit_uri="$6"
  local secure_cookie="$7"
  local faiss_dir="$8"
  local snapshot_dir="$9"

  if [[ -f "$ENV_FILE" ]] && ! confirm "$ENV_FILE exists. Overwrite it?" n; then
    warn "Keeping existing $ENV_FILE"
    ENV_WRITTEN=0
    return
  fi

  cat >"$ENV_FILE" <<ENV
FLASK_ENV=$flask_env
HUMAN_BRAIN_URL=$human_brain_url
SECRET_KEY=$secret_key
DATABASE_URL=$database_url
REDIS_URL=redis://$redis_host/2
CELERY_BROKER_URL=redis://$redis_host/0
CELERY_RESULT_BACKEND=redis://$redis_host/1
RATELIMIT_STORAGE_URI=$ratelimit_uri
SESSION_COOKIE_SECURE=$secure_cookie
CORS_ENABLED=false
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
VECTOR_STARTUP_WARMUP=true
VECTOR_AUTO_REPAIR_ON_WARMUP=true
FAISS_INDEX_DIR=$faiss_dir
SNAPSHOT_DIR=$snapshot_dir
LOG_LEVEL=INFO
HUMAN_BRAIN_VERSION=
HUMAN_BRAIN_GIT_BRANCH=
HUMAN_BRAIN_GIT_COMMIT=
RERANKER_ENABLED=false
RERANKER_PROVIDER=none
RERANKER_DEFAULT_MODE=conditional
RERANKER_CROSS_ENCODER_MODEL=BAAI/bge-reranker-base
RERANKER_OLLAMA_BASE_URL=http://localhost:11434
RERANKER_OLLAMA_MODEL=qwen2.5:7b
RERANKER_TOP_N=5
RERANKER_RETURN_K=5
RERANKER_TIMEOUT_MS=5000
RERANKER_MODEL_LOAD_TIMEOUT_MS=30000
RERANKER_WEIGHT=0.70
FAISS_WEIGHT=0.30
TRUST_WEIGHT=0.05
IMPORTANCE_WEIGHT=0.05
RERANKER_CONDITIONAL_THRESHOLD=0.08
RERANKER_MAX_TEXT_CHARS=1500
RERANKER_DEVICE=cpu
ENV
  ENV_WRITTEN=1
  ok "Wrote $ENV_FILE"
}

append_postgres_compose_env() {
  local db_name="$1"
  local db_user="$2"
  local db_password="$3"
  [[ "$ENV_WRITTEN" -eq 1 ]] || return
  cat >>"$ENV_FILE" <<ENV
POSTGRES_USER=$db_user
POSTGRES_PASSWORD=$db_password
POSTGRES_DB=$db_name
ENV
}

prepare_dirs() {
  mkdir -p "$APP_DIR/faiss_indexes" "$APP_DIR/uploads/snapshots" "$APP_DIR/uploads/memory_uploads" "$APP_DIR/logs" "$APP_DIR/backups"
}

prepare_python() {
  if [[ "$SKIP_DEPS" -eq 1 ]]; then
    warn "Skipping Python dependency setup"
    return
  fi
  have python3.11 || die "python3.11 was not found"
  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    spin "Creating virtualenv" python3.11 -m venv "$APP_DIR/.venv"
  fi
  spin "Installing core Python dependencies" "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements-core.txt"
  if confirm "Install optional ML and vision dependencies?" n; then
    spin "Installing ML dependencies" "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements-ml.txt"
  fi
}

run_migrations() {
  if confirm "Apply database migrations now?" y; then
    spin "Applying database migrations" bash -lc "cd '$APP_DIR' && '$APP_DIR/.venv/bin/flask' --app manage:app db upgrade"
  fi
}

seed_demo() {
  if confirm "Create demo workspace, demo agent, and API key?" y; then
    (cd "$APP_DIR" && "$APP_DIR/.venv/bin/python" manage.py seed-demo-data)
  fi
}

create_postgres_database() {
  local db_name="$1"
  local db_user="$2"
  local db_password="$3"
  local password_sql
  validate_identifier "database name" "$db_name"
  validate_identifier "database user" "$db_user"
  password_sql="$(sql_quote "$db_password")"

  have sudo || die "sudo was not found"
  have psql || warn "psql was not found in PATH; continuing through sudo -u postgres psql"

  if ! confirm "Create/update PostgreSQL role '$db_user' and database '$db_name'?" y; then
    return
  fi

  local sql_file
  sql_file="$(mktemp)"
  trap 'rm -f "$sql_file"' RETURN
  cat >"$sql_file" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$db_user') THEN
    CREATE ROLE "$db_user" LOGIN PASSWORD '$password_sql';
  ELSE
    ALTER ROLE "$db_user" WITH LOGIN PASSWORD '$password_sql';
  END IF;
END
\$\$;
SELECT format('CREATE DATABASE %I OWNER %I', '$db_name', '$db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db_name')\\gexec
GRANT ALL PRIVILEGES ON DATABASE "$db_name" TO "$db_user";
SQL
  log "Requesting sudo for PostgreSQL administration"
  sudo -v
  spin "Creating PostgreSQL user and database" sudo -u postgres psql -v ON_ERROR_STOP=1 -f "$sql_file"
  rm -f "$sql_file"
  trap - RETURN
}

setup_development() {
  log "${bold}Development setup${reset}"
  local url secret
  url="$(prompt "Application URL" "http://localhost:5000")"
  secret="$(random_secret)"
  write_env "development" "$url" "$secret" "sqlite:///human_brain_dev.sqlite3" "localhost:6379" "memory://" "false" "faiss_indexes" "uploads/snapshots"
  prepare_dirs
  prepare_python
  run_migrations
  seed_demo
  ok "Development setup complete"
  printf '%b\n' "${dim}Run:${reset} source .venv/bin/activate && python manage.py"
}

setup_production() {
  log "${bold}Native production setup${reset}"
  local url db_host db_port db_name db_user db_password secret secure redis_host
  local db_password_url
  url="$(prompt "Public application URL" "http://localhost:5000")"
  db_host="$(prompt "PostgreSQL host" "localhost")"
  db_port="$(prompt "PostgreSQL port" "5432")"
  db_name="$(prompt "PostgreSQL database name" "human_brain")"
  db_user="$(prompt "PostgreSQL application user" "human_brain")"
  db_password="$(prompt_secret "PostgreSQL password for $db_user")"
  [[ -n "$db_password" ]] || die "database password cannot be empty"
  validate_identifier "database name" "$db_name"
  validate_identifier "database user" "$db_user"
  db_password_url="$(url_quote "$db_password")"
  secret="$(prompt "Flask SECRET_KEY" "$(random_secret)")"
  redis_host="$(prompt "Redis host:port" "localhost:6379")"
  if [[ "$url" == https://* ]]; then
    secure="true"
  else
    secure="false"
  fi
  secure="$(prompt "Secure cookies? true requires HTTPS" "$secure")"

  create_postgres_database "$db_name" "$db_user" "$db_password"
  write_env \
    "production" \
    "$url" \
    "$secret" \
    "postgresql+psycopg://$db_user:$db_password_url@$db_host:$db_port/$db_name" \
    "$redis_host" \
    "redis://$redis_host/3" \
    "$secure" \
    "faiss_indexes" \
    "uploads/snapshots"
  prepare_dirs
  prepare_python
  run_migrations
  seed_demo

  if [[ "$SKIP_SYSTEMD" -eq 0 ]] && confirm "Install and start systemd service?" y; then
    "$APP_DIR/scripts/install_systemd.sh" --skip-deps --skip-migrations
  fi
  ok "Native production setup complete"
}

setup_docker() {
  log "${bold}Docker Compose setup${reset}"
  have docker || die "docker was not found"
  local url db_name db_user db_password secret secure
  local db_password_url
  url="$(prompt "Application URL" "http://localhost:5000")"
  db_name="$(prompt "PostgreSQL database name" "human_brain")"
  db_user="$(prompt "PostgreSQL application user" "human_brain")"
  db_password="$(prompt_secret "PostgreSQL password for $db_user")"
  [[ -n "$db_password" ]] || die "database password cannot be empty"
  validate_identifier "database name" "$db_name"
  validate_identifier "database user" "$db_user"
  db_password_url="$(url_quote "$db_password")"
  secret="$(prompt "Flask SECRET_KEY" "$(random_secret)")"
  if [[ "$url" == https://* ]]; then
    secure="true"
  else
    secure="false"
  fi
  secure="$(prompt "Secure cookies? true requires HTTPS" "$secure")"

  write_env \
    "production" \
    "$url" \
    "$secret" \
    "postgresql+psycopg://$db_user:$db_password_url@postgres:5432/$db_name" \
    "redis:6379" \
    "redis://redis:6379/3" \
    "$secure" \
    "/app/faiss_indexes" \
    "/app/uploads/snapshots"
  append_postgres_compose_env "$db_name" "$db_user" "$db_password"

  warn "If an old postgres_data volume already exists, PostgreSQL will keep its original user/password/database."

  if confirm "Build and start Docker Compose services now?" y; then
    spin "Starting Docker Compose" docker compose up --build -d
    spin "Applying Docker database migrations" docker compose exec -T web flask --app manage:app db upgrade
    if confirm "Create Docker demo workspace, demo agent, and API key?" y; then
      docker compose exec web python manage.py seed-demo-data
    fi
  fi
  ok "Docker setup complete"
}

banner() {
  printf '%b\n' "${magenta}"
  printf '  __  __                         ____            _       \n'
  printf ' |  \\/  | ___ _ __ ___   ___   | __ ) _ __ __ _(_)_ __  \n'
  printf ' | |\\/| |/ _ \\  _   _ \\ / _ \\  |  _ \\|  __/ _  | |  _ \\ \n'
  printf ' | |  | |  __/ | | | | | (_) | | |_) | | | (_| | | | | |\n'
  printf ' |_|  |_|\\___|_| |_| |_|\\___/  |____/|_|  \\__,_|_|_| |_|\n'
  printf '%b\n' "${reset}"
}

choose_mode() {
  if [[ -n "$MODE" ]]; then
    printf '%s\n' "$MODE"
    return
  fi
  printf '%b\n' "${bold}Choose setup mode:${reset}" >&2
  printf '  1) development  SQLite, local paths, Flask dev server\n' >&2
  printf '  2) production   Native PostgreSQL, Redis, Gunicorn, optional systemd\n' >&2
  printf '  3) docker       Docker Compose PostgreSQL, Redis, web, Celery\n' >&2
  local choice
  choice="$(prompt "Mode" "development")"
  case "$choice" in
    1|dev|development) printf 'development\n' ;;
    2|prod|production) printf 'production\n' ;;
    3|docker|compose) printf 'docker\n' ;;
    *) die "unknown mode: $choice" ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:?missing value for --mode}"
      shift 2
      ;;
    --yes)
      YES=1
      shift
      ;;
    --skip-deps)
      SKIP_DEPS=1
      shift
      ;;
    --skip-systemd)
      SKIP_SYSTEMD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

[[ -f "$APP_DIR/manage.py" ]] || die "manage.py was not found in $APP_DIR"
banner
mode="$(choose_mode)"
case "$mode" in
  development) setup_development ;;
  production) setup_production ;;
  docker) setup_docker ;;
  *) die "unknown mode: $mode" ;;
esac
