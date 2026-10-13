#!/usr/bin/env bash
# Removes the local build from dev/install-local.sh and its data. A release install is not touched.

set -euo pipefail

readonly NEW="com.jgbmichalski.BfmeInstallerDev"

flatpak kill "$NEW" 2>/dev/null || true
flatpak uninstall --user -y --noninteractive --delete-data "$NEW" "$NEW.Debug" 2>/dev/null || echo "Not installed."
rm -rf "${HOME:?}/.var/app/$NEW" "${TMPDIR:-/tmp}/bfme-dev"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$NEW".{Launcher,Arena,Aotr}.desktop
echo "Removed $NEW."
