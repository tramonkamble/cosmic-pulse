#!/usr/bin/env bash
# Build a noarch .deb from the current tree (no dh/debhelper required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/deb"
STAGE="$BUILD/root"
PKG=cosmic-pulse
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$ROOT/pyproject.toml','rb'))['project']['version'])")"
DEB="${BUILD}/${PKG}_${VERSION}_all.deb"

command -v dpkg-deb >/dev/null || { echo "error: dpkg-deb not found" >&2; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/lib/cosmic-pulse"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/lib/systemd/user"
mkdir -p "$STAGE/usr/share/doc/cosmic-pulse"
mkdir -p "$STAGE/usr/share/applications"
mkdir -p "$STAGE/usr/share/icons/hicolor/256x256/apps"

cp "$ROOT/deploy/debian/control" "$STAGE/DEBIAN/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$STAGE/DEBIAN/control"
printf '\n' >>"$STAGE/DEBIAN/control"

if [[ -d "$ROOT/.git" ]] && command -v git >/dev/null 2>&1; then
  git -C "$ROOT" archive HEAD | tar -x -C "$STAGE/usr/lib/cosmic-pulse"
else
  echo "error: build-deb.sh needs a git checkout (packs tracked files only)" >&2
  exit 1
fi
rm -rf "$STAGE/usr/lib/cosmic-pulse/tests" "$STAGE/usr/lib/cosmic-pulse/.github"

install -m 755 "$ROOT/deploy/cosmic-pulse.wrapper" "$STAGE/usr/bin/cosmic-pulse"
install -m 644 "$ROOT/deploy/cosmic-pulse.service" "$STAGE/usr/lib/systemd/user/cosmic-pulse.service"
install -m 644 "$ROOT/deploy/cosmic-pulse.desktop" "$STAGE/usr/share/applications/cosmic-pulse.desktop"
install -m 644 "$ROOT/assets/brand/pulse-mark-256.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/cosmic-pulse.png"
install -m 644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/cosmic-pulse/copyright"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/cosmic-pulse/README.md"

cat >"$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  echo "Cosmic Pulse installed."
  echo "  systemctl --user enable --now cosmic-pulse"
  echo "  cosmic-pulse --open"
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat >"$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/postrm"

if dpkg-deb --help 2>&1 | grep -q root-owner-group; then
  dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
else
  dpkg-deb --build "$STAGE" "$DEB"
fi
echo "Built: $DEB"
echo "Install: sudo apt install ./$(basename "$DEB")"
