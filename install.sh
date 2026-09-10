#!/usr/bin/env bash
# Cosmic Pulse — user-local installer (Pop!_OS, Debian, Ubuntu, Fedora, etc.)
# Installs to ~/.local/share/cosmic-pulse with a venv and optional systemd user service.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${PULSE_INSTALL_DIR:-$HOME/.local/share/cosmic-pulse}"
BIN_DIR="${PULSE_BIN_DIR:-$HOME/.local/bin}"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="${SERVICE_DIR}/cosmic-pulse.service"
WRAPPER="${BIN_DIR}/cosmic-pulse"
PORT="${PULSE_PORT:-8765}"
WITH_SERVICE=0
UNINSTALL=0
PURGE=0
USE_SYSTEM_PYTHON=0
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

usage() {
  cat <<'EOF'
Cosmic Pulse installer

Usage:
  ./install.sh [options]

Options:
  --dir PATH       Install location (default: ~/.local/share/cosmic-pulse)
  --service        Enable and start systemd user service
  --port PORT      HTTP port (default: 8765)
  --system-python  Use system python3 + pip --user instead of a venv
  --uninstall      Remove the app, wrapper, desktop entry, and user service
  --purge          With --uninstall, also delete pulse.db and local config
  -h, --help       Show this help

After install:
  cosmic-pulse              # foreground
  systemctl --user start cosmic-pulse   # if --service was used
  xdg-open http://localhost:8765

State files (DB, config) live beside the install when using --dir under your home.
Packaged .deb installs use ~/.local/share/cosmic-pulse for state automatically.
EOF
}

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

python_deps_ok() {
  python3 -c "import psutil, yaml" >/dev/null 2>&1
}

install_python_deps() {
  if python_deps_ok; then
    log "Python deps satisfied (pip or distro packages)"
    return 0
  fi
  if python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install --user -r "$INSTALL_DIR/requirements.txt"
    return 0
  fi
  die "Missing psutil/PyYAML. On Pop!_OS / Ubuntu run:
  sudo apt install python3-psutil python3-yaml python3-venv python3-pip"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || die "--dir requires a path"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --service) WITH_SERVICE=1; shift ;;
    --port)
      [[ $# -ge 2 ]] || die "--port requires a number"
      PORT="$2"
      shift 2
      ;;
    --system-python) USE_SYSTEM_PYTHON=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge) PURGE=1; UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

uninstall() {
  log "Stopping user service (if any)"
  systemctl --user disable --now cosmic-pulse.service 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -f "$WRAPPER"
  rm -f "$DESKTOP_DIR/cosmic-pulse.desktop"
  rm -f "$ICON_DIR/cosmic-pulse.png"
  if [[ -d "$INSTALL_DIR" ]]; then
    if [[ "$PURGE" -eq 1 ]]; then
      log "Removing $INSTALL_DIR (including history)"
      rm -rf "$INSTALL_DIR"
    else
      log "Removing app files; keeping pulse.db / config in $INSTALL_DIR"
      shopt -s dotglob nullglob
      for p in "$INSTALL_DIR"/*; do
        case "$(basename "$p")" in
          pulse.db|pulse.db-wal|pulse.db-shm|.pulse_config.json|.tuning_log.json|.memory_cache.json)
            continue ;;
        esac
        rm -rf "$p"
      done
      shopt -u dotglob nullglob
    fi
  fi
  log "Uninstall complete"
}

if [[ "$UNINSTALL" -eq 1 ]]; then
  uninstall
  exit 0
fi

need_cmd python3

copy_app() {
  # Tracked files only when this is a git checkout; otherwise rsync the tree.
  local dest="$1"
  mkdir -p "$dest"
  shopt -s dotglob nullglob
  for p in "$dest"/*; do
    case "$(basename "$p")" in
      pulse.db|pulse.db-wal|pulse.db-shm|.pulse_config.json|.tuning_log.json|.memory_cache.json)
        continue ;;
    esac
    rm -rf "$p"
  done
  shopt -u dotglob nullglob
  if [[ -d "$SOURCE_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
    git -C "$SOURCE_DIR" archive HEAD | tar -x -C "$dest"
  else
    need_cmd rsync
    rsync -a --delete \
      --exclude '.git/' \
      --exclude '.github/' \
      --exclude '.venv/' \
      --exclude '.hermes/' \
      --exclude '__pycache__/' \
      --exclude '.ruff_cache/' \
      --exclude 'pulse.db' \
      --exclude 'pulse.db-*' \
      --exclude '.pulse_config.json' \
      --exclude '.tuning_log.json' \
      --exclude '.memory_cache.json' \
      --exclude 'backups/' \
      --exclude 'reviews_*' \
      --exclude 'build/' \
      --exclude 'tests/' \
      --exclude '*.log' \
      --exclude '.sample_live.json' \
      --exclude '.sample_worker.pid' \
      --exclude '5-HOUR_*' \
      --exclude 'BUG_*' \
      --exclude 'BugHunt*' \
      --exclude 'UI_*' \
      --exclude 'VERIFICATION_*' \
      --exclude 'PULSE_AGENTS.md' \
      --exclude 'PULSE_REVIEW.md' \
      --exclude 'docs/reviews/' \
      --exclude 'deploy/ab/' \
      --exclude 'assets/brand/placeholders/' \
      "$SOURCE_DIR/" "$dest/"
  fi
  rm -rf "$dest/tests" "$dest/.github" "$dest/.hermes"
}

[[ -f "$SOURCE_DIR/server.py" ]] || die "run install.sh from the Cosmic Pulse repo root"

log "Installing to $INSTALL_DIR"
copy_app "$INSTALL_DIR"

mkdir -p "$BIN_DIR"

if [[ "$USE_SYSTEM_PYTHON" -eq 1 ]]; then
  log "Using system Python"
  install_python_deps
  PYTHON_BIN="$(command -v python3)"
else
  log "Creating virtualenv"
  VENV_OK=0
  if python3 -m venv "$INSTALL_DIR/.venv" >/dev/null 2>&1 \
      && [[ -x "$INSTALL_DIR/.venv/bin/python" ]] \
      && "$INSTALL_DIR/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    VENV_OK=1
  else
    rm -rf "$INSTALL_DIR/.venv"
  fi
  if [[ "$VENV_OK" -eq 1 ]]; then
    "$INSTALL_DIR/.venv/bin/pip" install -U pip
    "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"
  else
    log "venv unavailable — try: sudo apt install python3-venv"
    log "Falling back to system Python"
    install_python_deps
    PYTHON_BIN="$(command -v python3)"
  fi
fi

log "Installing wrapper: $WRAPPER"
cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
# Cosmic Pulse launcher — generated by install.sh
export PULSE_PORT="${PORT}"
exec "${PYTHON_BIN}" "${INSTALL_DIR}/server.py" "\$@"
EOF
chmod +x "$WRAPPER"

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
if [[ -f "$SOURCE_DIR/assets/brand/pulse-mark-256.png" ]]; then
  install -m 644 "$SOURCE_DIR/assets/brand/pulse-mark-256.png" "$ICON_DIR/cosmic-pulse.png"
fi
if [[ -f "$SOURCE_DIR/deploy/cosmic-pulse.desktop" ]]; then
  install -m 644 "$SOURCE_DIR/deploy/cosmic-pulse.desktop" "$DESKTOP_DIR/cosmic-pulse.desktop"
fi

if [[ "$WITH_SERVICE" -eq 1 ]]; then
  need_cmd systemctl
  mkdir -p "$SERVICE_DIR"
  log "Installing systemd user unit: $SERVICE_FILE"
  cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Cosmic Pulse gaming performance dashboard
Documentation=https://github.com/tramonkamble/cosmic-pulse
After=default.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${WRAPPER}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillMode=mixed
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now cosmic-pulse.service
  log "Service running — journal: journalctl --user -u cosmic-pulse -f"
else
  log "Skipped systemd (--service not passed). Run: cosmic-pulse"
fi

log "Done. Open http://localhost:${PORT}"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf 'note: add %s to PATH if cosmic-pulse is not found\n' "$BIN_DIR"
fi