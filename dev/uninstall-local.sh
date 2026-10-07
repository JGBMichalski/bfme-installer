#!/usr/bin/env bash
# Removes the local build made by dev/install-local.sh, and its data (setup, Proton, games installed through it).
# A release install is not touched.

set -euo pipefail

readonly NEW="com.jgbmichalski.BfmeInstallerDev"

flatpak kill "$NEW" 2>/dev/null || true
flatpak uninstall --user -y --noninteractive --delete-data "$NEW" "$NEW.Debug" 2>/dev/null || echo "Not installed."
rm -rf "${HOME:?}/.var/app/$NEW" "${TMPDIR:-/tmp}/bfme-dev"
echo "Removed $NEW."
