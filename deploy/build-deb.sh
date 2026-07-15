#!/usr/bin/env bash
# Build a noarch .deb from the current tree (no dh/debhelper required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/deb"
STAGE="$BUILD/root"
PKG=cosmic-pulse
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$ROOT/pyproject.toml','rb'))['project']['version'])")"
DEB="${BUILD}/${PKG}_${VERSION}_all.deb"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/lib/cosmic-pulse"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/lib/systemd/user"
mkdir -p "$STAGE/usr/share/doc/cosmic-pulse"

cp "$ROOT/deploy/debian/control" "$STAGE/DEBIAN/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$STAGE/DEBIAN/control"
printf '\n' >>"$STAGE/DEBIAN/control"

rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
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
  --exclude 'deploy/build-deb.sh' \
  --exclude 'tests/' \
  "$ROOT/" "$STAGE/usr/lib/cosmic-pulse/"

install -m 755 "$ROOT/deploy/cosmic-pulse.wrapper" "$STAGE/usr/bin/cosmic-pulse"
install -m 644 "$ROOT/deploy/cosmic-pulse.service" "$STAGE/usr/lib/systemd/user/cosmic-pulse.service"
install -m 644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/cosmic-pulse/copyright"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/cosmic-pulse/README.md"

cat >"$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  echo "Cosmic Pulse installed."
  echo "  systemctl --user daemon-reload"
  echo "  systemctl --user enable --now cosmic-pulse"
  echo "  xdg-open http://localhost:8765"
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

dpkg-deb --build "$STAGE" "$DEB"
echo "Built: $DEB"
echo "Install: sudo apt install ./$(basename "$DEB")"