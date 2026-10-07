#!/usr/bin/env bash
# Builds the Flatpak from this checkout and installs it BESIDE a release install, under another app ID
# (com.jgbmichalski.BfmeInstallerDev). It has its own data (~/.var/app/<id>), so it has its own setup and Proton
# download, and its menu entries are named "(Dev)". The release app is not touched.
#
# Usage: dev/install-local.sh [--run]
#   --run   start the app when the build is installed
# Remove it again with dev/uninstall-local.sh.

set -euo pipefail

readonly OLD="com.jgbmichalski.BfmeInstaller"
readonly NEW="com.jgbmichalski.BfmeInstallerDev"
readonly WORK="${TMPDIR:-/tmp}/bfme-dev"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v flatpak-builder >/dev/null 2>&1 || { echo "ERROR: flatpak-builder is not installed." >&2; exit 1; }

# Build from a copy, so the checkout is not modified.
rm -rf "$WORK/src" "$WORK/build"
mkdir -p "$WORK/src"
cp -r "$root/flatpak" "$root/wizard" "$root/scripts" "$WORK/src/"
find "$WORK/src" -name __pycache__ -prune -exec rm -rf {} +
cd "$WORK/src/flatpak"

for f in "$OLD"*; do mv "$f" "${f/$OLD/$NEW}"; done
sed -i -e "s/$OLD/$NEW/g" -e 's/^Name=BFME \(.*\)/Name=BFME \1 (Dev)/' \
  -e 's/@BFME_VERSION@/dev/' -e "s/@BFME_DATE@/$(date +%F)/" "$NEW"*.yml ./*.desktop ./*.xml

flatpak-builder --user --install --force-clean --install-deps-from=flathub \
  --state-dir="$WORK/state" "$WORK/build" "$NEW.yml"

echo
echo "Installed $NEW (version dev). Start it with: flatpak run $NEW"
[ "${1:-}" != "--run" ] || exec flatpak run "$NEW"
