#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="human-brain"
SERVICE_NAME="human-brain"
INSTALL_USER="${SUDO_USER:-${USER}}"
INSTALL_GROUP=""
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"
PORT=""
WORKERS=""
THREADS=""
SKIP_DEPS=0
SKIP_MIGRATIONS=0
SKIP_START=0
ENABLE_NOW=1

bold="$(printf '\033[1m')"
dim="$(printf '\033[2m')"
red="$(printf '\033[31m')"
green="$(printf '\033[32m')"
yellow="$(printf '\033[33m')"
blue="$(printf '\033[34m')"
reset="$(printf '\033[0m')"

usage() {
  cat <<USAGE
${bold}Human-Brain systemd installer${reset}

Usage:
  scripts/install_systemd.sh [options]

Options:
  --service-name NAME    systemd service name (default: human-brain)
  --user USER            Linux user that runs the service (default: current user)
  --group GROUP          Linux group that runs the service (default: user's primary group)
  --app-dir PATH         Application directory (default: this repository)
  --env-file PATH        Environment file (default: APP_DIR/.env)
  --port PORT            Override Gunicorn bind port in the unit
  --workers N            Override Gunicorn worker count in the unit
  --threads N            Override Gunicorn thread count in the unit
  --skip-deps            Do not create .venv or install requirements-core.txt
  --skip-migrations      Do not run flask db upgrade
  --no-start             Install/enable service but do not start or restart it
  --no-enable            Install service but do not enable it at boot
  -h, --help             Show this help
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

run() {
  printf '%b\n' "${dim}$ $*${reset}"
  "$@"
}

python_cmd() {
  if command -v python3.11 >/dev/null 2>&1; then
    printf '%s\n' "python3.11"
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  else
    die "python3 was not found"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service-name)
      SERVICE_NAME="${2:?missing value for --service-name}"
      shift 2
      ;;
    --user)
      INSTALL_USER="${2:?missing value for --user}"
      shift 2
      ;;
    --group)
      INSTALL_GROUP="${2:?missing value for --group}"
      shift 2
      ;;
    --app-dir)
      APP_DIR="$(cd "${2:?missing value for --app-dir}" && pwd)"
      ENV_FILE="$APP_DIR/.env"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:?missing value for --env-file}"
      shift 2
      ;;
    --port)
      PORT="${2:?missing value for --port}"
      shift 2
      ;;
    --workers)
      WORKERS="${2:?missing value for --workers}"
      shift 2
      ;;
    --threads)
      THREADS="${2:?missing value for --threads}"
      shift 2
      ;;
    --skip-deps)
      SKIP_DEPS=1
      shift
      ;;
    --skip-migrations)
      SKIP_MIGRATIONS=1
      shift
      ;;
    --no-start)
      SKIP_START=1
      shift
      ;;
    --no-enable)
      ENABLE_NOW=0
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
[[ -f "$APP_DIR/gunicorn.conf.py" ]] || die "gunicorn.conf.py was not found in $APP_DIR"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE does not exist; copy .env.example to .env and edit it first"
command -v systemctl >/dev/null 2>&1 || die "systemctl was not found; this installer requires systemd"
command -v sudo >/dev/null 2>&1 || die "sudo was not found"

if [[ -z "$INSTALL_GROUP" ]]; then
  INSTALL_GROUP="$(id -gn "$INSTALL_USER")"
fi

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TMP_SERVICE="$(mktemp)"
trap 'rm -f "$TMP_SERVICE"' EXIT

log "${bold}$APP_NAME systemd install${reset}"
printf '  %-16s %s\n' "App directory:" "$APP_DIR"
printf '  %-16s %s\n' "Environment:" "$ENV_FILE"
printf '  %-16s %s\n' "Service:" "$SERVICE_FILE"
printf '  %-16s %s:%s\n' "Run as:" "$INSTALL_USER" "$INSTALL_GROUP"

log "Requesting elevated privileges for systemd installation"
sudo -v -p "$(printf '%b' "${bold}sudo password for %u:${reset} ")" || die "sudo authentication failed"

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  log "Preparing Python environment"
  PYTHON_CMD="$(python_cmd)"
  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    run "$PYTHON_CMD" -m venv "$APP_DIR/.venv"
  fi
  run "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
  run "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements-core.txt"
else
  warn "Skipping dependency installation"
fi

if [[ "$SKIP_MIGRATIONS" -eq 0 ]]; then
  log "Applying database migrations"
  (
    cd "$APP_DIR"
    FLASK_ENV=production "$APP_DIR/.venv/bin/flask" --app manage:app db upgrade
  )
else
  warn "Skipping database migrations"
fi

exec_start="$APP_DIR/.venv/bin/gunicorn -c gunicorn.conf.py manage:app"
if [[ -n "$PORT" || -n "$WORKERS" || -n "$THREADS" ]]; then
  exec_start="$APP_DIR/.venv/bin/gunicorn"
  [[ -n "$PORT" ]] && exec_start="$exec_start --bind 0.0.0.0:$PORT"
  [[ -n "$WORKERS" ]] && exec_start="$exec_start --workers $WORKERS"
  [[ -n "$THREADS" ]] && exec_start="$exec_start --threads $THREADS"
  exec_start="$exec_start --timeout 120 --access-logfile - --error-logfile - manage:app"
fi

cat > "$TMP_SERVICE" <<UNIT
[Unit]
Description=Human-Brain memory platform
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=FLASK_ENV=production
ExecStart=$exec_start
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

log "Installing systemd unit"
sudo install -m 0644 "$TMP_SERVICE" "$SERVICE_FILE"
sudo systemctl daemon-reload

if [[ "$ENABLE_NOW" -eq 1 ]]; then
  run sudo systemctl enable "$SERVICE_NAME"
else
  warn "Service was not enabled at boot"
fi

if [[ "$SKIP_START" -eq 0 ]]; then
  log "Starting service"
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
else
  warn "Service was not started"
fi

ok "Installed $SERVICE_NAME"
printf '%b\n' "${dim}Useful commands:${reset}"
printf '  sudo systemctl status %s\n' "$SERVICE_NAME"
printf '  sudo journalctl -u %s -f\n' "$SERVICE_NAME"
printf '  sudo systemctl restart %s\n' "$SERVICE_NAME"
