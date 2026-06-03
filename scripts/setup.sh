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

python_cmd() {
  if have python3.11; then
    printf '%s\n' "python3.11"
  elif have python3; then
    printf '%s\n' "python3"
  else
    die "python3 was not found"
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

run_postgres_sql_file() {
  local sql_file="$1"
  sudo -u postgres psql -v ON_ERROR_STOP=1 <"$sql_file"
}

url_quote() {
  local value="$1"
  "$(python_cmd)" -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "$value"
}

url_component() {
  local url="$1"
  local component="$2"
  "$(python_cmd)" -c 'from urllib.parse import urlparse; import sys; parsed = urlparse(sys.argv[1]); print(getattr(parsed, sys.argv[2]) or "")' "$url" "$component"
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
  local python
  python="$(python_cmd)"
  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    spin "Creating virtualenv" "$python" -m venv "$APP_DIR/.venv"
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

install_nginx_if_missing() {
  if have nginx; then
    return
  fi
  if ! confirm "nginx was not found. Install it now?" y; then
    warn "Skipping nginx installation"
    return 1
  fi
  have sudo || die "sudo was not found"
  sudo -v
  if have apt-get; then
    spin "Updating package lists" sudo apt-get update
    spin "Installing nginx" sudo apt-get install -y nginx
  elif have dnf; then
    spin "Installing nginx" sudo dnf install -y nginx
  elif have yum; then
    spin "Installing nginx" sudo yum install -y nginx
  else
    die "No supported package manager found for nginx installation"
  fi
}

apache_cmd() {
  if have apache2; then
    printf '%s\n' "apache2"
  elif have httpd; then
    printf '%s\n' "httpd"
  else
    return 1
  fi
}

apache_service_name() {
  if have apache2; then
    printf '%s\n' "apache2"
  else
    printf '%s\n' "httpd"
  fi
}

apache_configtest() {
  if have apache2ctl; then
    sudo apache2ctl configtest
  elif have apachectl; then
    sudo apachectl configtest
  else
    local service
    service="$(apache_service_name)"
    sudo "$service" -t
  fi
}

install_apache_site() {
  local url="$1"
  local scheme host site_name upstream cert_path key_path config_file service
  scheme="$(url_component "$url" "scheme")"
  host="$(url_component "$url" "hostname")"
  [[ -n "$host" ]] || host="$(prompt "Apache server name" "human-brain.local")"
  site_name="${host//[^A-Za-z0-9_.-]/_}"
  upstream="$(prompt "Upstream app URL" "http://127.0.0.1:5000")"

  apache_cmd >/dev/null || die "Apache was not found"
  have sudo || die "sudo was not found"
  sudo -v
  service="$(apache_service_name)"
  if [[ -d /etc/apache2/sites-available ]]; then
    config_file="/etc/apache2/sites-available/${site_name}.conf"
  else
    config_file="/etc/httpd/conf.d/${site_name}.conf"
  fi

  if have a2enmod; then
    spin "Enabling Apache proxy modules" sudo a2enmod proxy proxy_http headers rewrite ssl
  fi

  if [[ "$scheme" == "https" ]]; then
    cert_path="$(prompt "TLS certificate path" "/etc/apache2/ssl/${site_name}/${site_name}.crt")"
    key_path="$(prompt "TLS private key path" "/etc/apache2/ssl/${site_name}/${site_name}.key")"
    [[ -n "$cert_path" ]] || die "TLS certificate path cannot be empty"
    [[ -n "$key_path" ]] || die "TLS private key path cannot be empty"
    [[ -f "$cert_path" ]] || warn "Certificate file does not exist yet: $cert_path"
    [[ -f "$key_path" ]] || warn "Private key file does not exist yet: $key_path"
    sudo tee "$config_file" >/dev/null <<APACHE
<VirtualHost *:80>
    ServerName $host
    Redirect permanent / https://$host/
</VirtualHost>

<IfModule mod_ssl.c>
<VirtualHost *:443>
    ServerName $host
    SSLEngine on
    SSLCertificateFile $cert_path
    SSLCertificateKeyFile $key_path

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass / $upstream/
    ProxyPassReverse / $upstream/
</VirtualHost>
</IfModule>
APACHE
  else
    sudo tee "$config_file" >/dev/null <<APACHE
<VirtualHost *:80>
    ServerName $host

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "http"
    ProxyPass / $upstream/
    ProxyPassReverse / $upstream/
</VirtualHost>
APACHE
  fi

  if have a2ensite && [[ "$config_file" == /etc/apache2/sites-available/* ]]; then
    spin "Enabling Apache site" sudo a2ensite "${site_name}.conf"
  fi
  spin "Testing Apache configuration" apache_configtest
  if have systemctl; then
    spin "Enabling Apache" sudo systemctl enable "$service"
    spin "Reloading Apache" sudo systemctl reload "$service"
  else
    spin "Reloading Apache" sudo "$service" -k graceful
  fi
  ok "Installed Apache site $config_file"
}

install_nginx_site() {
  local url="$1"
  local scheme host site_name upstream cert_path key_path config_file enabled_file
  scheme="$(url_component "$url" "scheme")"
  host="$(url_component "$url" "hostname")"
  [[ -n "$host" ]] || host="$(prompt "nginx server name" "human-brain.local")"
  site_name="${host//[^A-Za-z0-9_.-]/_}"
  upstream="$(prompt "Upstream app URL" "http://127.0.0.1:5000")"

  install_nginx_if_missing || return
  have sudo || die "sudo was not found"
  sudo -v
  if [[ -d /etc/nginx/sites-available ]]; then
    config_file="/etc/nginx/sites-available/${site_name}.conf"
    enabled_file="/etc/nginx/sites-enabled/${site_name}.conf"
  else
    config_file="/etc/nginx/conf.d/${site_name}.conf"
    enabled_file=""
  fi

  if [[ "$scheme" == "https" ]]; then
    cert_path="$(prompt "TLS certificate path" "/etc/nginx/ssl/${site_name}/${site_name}.crt")"
    key_path="$(prompt "TLS private key path" "/etc/nginx/ssl/${site_name}/${site_name}.key")"
    [[ -n "$cert_path" ]] || die "TLS certificate path cannot be empty"
    [[ -n "$key_path" ]] || die "TLS private key path cannot be empty"
    [[ -f "$cert_path" ]] || warn "Certificate file does not exist yet: $cert_path"
    [[ -f "$key_path" ]] || warn "Private key file does not exist yet: $key_path"
    sudo tee "$config_file" >/dev/null <<NGINX
server {
    listen 80;
    server_name $host;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $host;
    client_max_body_size 25m;

    ssl_certificate $cert_path;
    ssl_certificate_key $key_path;

    location / {
        proxy_pass $upstream;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
NGINX
  else
    sudo tee "$config_file" >/dev/null <<NGINX
server {
    listen 80;
    server_name $host;
    client_max_body_size 25m;

    location / {
        proxy_pass $upstream;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;
    }
}
NGINX
  fi

  if [[ -n "$enabled_file" && -d /etc/nginx/sites-enabled ]]; then
    sudo ln -sf "$config_file" "$enabled_file"
  fi
  spin "Testing nginx configuration" sudo nginx -t
  if have systemctl; then
    spin "Enabling nginx" sudo systemctl enable nginx
    spin "Reloading nginx" sudo systemctl reload nginx
  else
    spin "Reloading nginx" sudo nginx -s reload
  fi
  ok "Installed nginx site $config_file"
}

install_reverse_proxy_site() {
  local url="$1"
  if have nginx; then
    install_nginx_site "$url"
    return
  fi
  if apache_cmd >/dev/null; then
    warn "Apache is installed and nginx is not installed."
    if confirm "Install Apache reverse proxy config instead of nginx?" y; then
      install_apache_site "$url"
      return
    fi
  fi
  install_nginx_site "$url"
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
  spin "Creating PostgreSQL user and database" run_postgres_sql_file "$sql_file"
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
  if confirm "Install or update web reverse proxy config?" y; then
    install_reverse_proxy_site "$url"
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
  printf '  _   _                         ____            _       \n'
  printf ' | | | |_   _ _ __ ___   __ _  | __ ) _ __ __ _(_)_ __  \n'
  printf ' | |_| | | | |  _   _ \\ / _  | |  _ \\|  __/ _  | |  _ \\ \n'
  printf ' |  _  | |_| | | | | | | (_| | | |_) | | | (_| | | | | |\n'
  printf ' |_| |_|\\__,_|_| |_| |_|\\__,_| |____/|_|  \\__,_|_|_| |_|\n'
  printf '\n'
  printf '                    Human Brain setup\n'
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
