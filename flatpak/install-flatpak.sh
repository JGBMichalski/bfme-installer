#!/usr/bin/env bash
# BFME Installer for Linux: installs the Flatpak and the 32-bit Flatpak extensions it needs, then opens the
# setup wizard. Flatpak does not install those extensions for apps outside Flathub, so this does it for you.
# Runs as your user. No sudo. Safe to run again: it updates an existing install.
# The app comes from a signed Flatpak repository. This script carries the project's public signing key and only
# accepts software signed with it.
#
# Install:   curl -fsSL <release or site address>/install-flatpak.sh | bash
# Options go after "bash -s --", for example:   ... | bash -s -- --uninstall
#
# This file is short on purpose. Read it before you run it.

set -euo pipefail

readonly APP_ID="com.jgbmichalski.BfmeInstaller"
readonly RUNTIME_VERSION="25.08"
readonly REMOTE_NAME="bfme-installer"
# CI replaces these placeholders in the copy it publishes: the Flatpak repository on GitHub Pages, and the
# project's public signing key (base64). A copy straight from the repository still has the placeholders.
readonly REPO="@BFME_DEFAULT_REPO@"
readonly SIGNING_KEY="@BFME_SIGNING_KEY@"

OPEN_WIZARD=1
UNINSTALL=0
PURGE=0

say()  { printf '%s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: install-flatpak.sh [options]
  --no-setup          Install only. Do not open the setup wizard.
  --uninstall         Remove the app and its Flatpak repository. Keeps your data and the shared 32-bit extensions.
  --purge             Uninstall and also delete the app's data: the setup, Proton and any installed games.
  -h, --help          Show this help.
EOF
}

has_display() { [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; }

no_flatpak() {
  local id="" like="" cmd=""
  if [ -r /etc/os-release ]; then
    id="$(. /etc/os-release; printf '%s' "${ID:-}")"
    like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
  fi
  case " $id $like " in
    *" debian "*|*" ubuntu "*) cmd="sudo apt install flatpak" ;;
    *" fedora "*|*" rhel "*)   cmd="sudo dnf install flatpak" ;;
    *" arch "*)                cmd="sudo pacman -S flatpak" ;;
    *" suse "*|*" opensuse "*) cmd="sudo zypper install flatpak" ;;
  esac
  say "Flatpak is not installed."
  say ""
  if [ -n "$cmd" ]; then
    say "Install it with this command, then run the BFME Installer command again:"
    say "  $cmd"
  else
    say "Install it for your distribution (https://flatpak.org/setup/), then run the BFME Installer command again."
  fi
  say "On some distributions you must log out and back in after installing Flatpak."
  exit 1
}

install_extensions() {
  local ext=("org.freedesktop.Platform.Compat.i386//${RUNTIME_VERSION}" "org.freedesktop.Platform.GL32.default//${RUNTIME_VERSION}")
  # NVIDIA: the 32-bit driver must match the 64-bit one Flatpak already installed for your card.
  local nvidia line
  nvidia="$(flatpak list --runtime --columns=application,branch 2>/dev/null \
    | awk '$1 ~ /^org\.freedesktop\.Platform\.GL\.nvidia-/ {print $1 "//" $2}' | sort -u || true)"
  if [ -n "$nvidia" ]; then
    while IFS= read -r line; do
      ext+=("${line/Platform.GL.nvidia/Platform.GL32.nvidia}")
    done <<<"$nvidia"
  fi
  flatpak install --user -y --noninteractive flathub "${ext[@]}"
}

# Point the app's remote at the repository, with the signing key: the remote checks every download against it.
# This also switches checking on for a remote that an older version of this script added without it.
# The commands are chained with && on purpose: this runs under "|| die", where "set -e" does not stop at a failure,
# and the install must never go ahead from a remote that did not get checking switched on.
add_remote() {
  local key ok=0
  key="$(mktemp)"
  if printf '%s' "$SIGNING_KEY" | base64 -d > "$key" \
     && flatpak remote-add --user --if-not-exists --gpg-import="$key" "$REMOTE_NAME" "$REPO" \
     && flatpak remote-modify --user --gpg-import="$key" --gpg-verify --url="$REPO" "$REMOTE_NAME"; then
    ok=1
  fi
  rm -f "$key"
  [ "$ok" = "1" ]
}

install_app() {
  add_remote && flatpak install --user -y --noninteractive --or-update "$REMOTE_NAME" "$APP_ID"
}

start_setup() {
  say ""
  if [ "$OPEN_WIZARD" = "0" ]; then
    say "Installed. Open 'BFME Installer' from your application menu to finish the setup."
  elif has_display; then
    say "Step 4: opening the setup wizard. If it does not appear, open 'BFME Installer' from your application menu."
    nohup flatpak run --user "$APP_ID" >/dev/null 2>&1 &
    disown || true
  else
    # No window is possible (SSH, a text console). The app notices this itself and runs the setup right here.
    say "Step 4: no display found, so the setup runs in this terminal."
    flatpak run --user "$APP_ID" || say "Setup did not finish. Run it again with: flatpak run --command=bfme-linux-setup $APP_ID install"
  fi
}

do_uninstall() {
  say "Removing the BFME Installer"
  flatpak uninstall --user -y --noninteractive "$APP_ID" || say "The app is not installed."
  flatpak remote-delete --user --force "$REMOTE_NAME" >/dev/null 2>&1 || true
  if [ "$PURGE" = "1" ]; then
    local data="${HOME:-}/.var/app/$APP_ID"
    if [ -n "${HOME:-}" ] && [ -d "$data" ]; then
      say "Deleting $data (the setup, Proton and any games installed through it)"
      rm -rf -- "$data"
    fi
  else
    say "Your data is kept in ~/.var/app/$APP_ID. Add --purge to delete it, games included."
  fi
  say "Left in place: Flathub and the shared 32-bit extensions. Remove what nothing uses with: flatpak uninstall --unused"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --no-setup)  OPEN_WIZARD=0; shift ;;
      --uninstall) UNINSTALL=1; shift ;;
      --purge)     UNINSTALL=1; PURGE=1; shift ;;
      -h|--help)   usage; exit 0 ;;
      *)           die "Unknown option '$1'. Run with --help." ;;
    esac
  done

  command -v flatpak >/dev/null 2>&1 || no_flatpak

  if [ "$UNINSTALL" = "1" ]; then
    do_uninstall
    return
  fi

  case "$REPO$SIGNING_KEY" in
    *"@BFME_"*) die "This is not a release copy of the script, so it does not know where the app is or which key to trust. Use the install command from the README." ;;
  esac

  say "Step 1: make sure Flathub is available for the runtime and the 32-bit extensions"
  if ! flatpak remotes --user --columns=name | grep -qx flathub; then
    flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
  fi

  say "Step 2: install the 32-bit extensions"
  install_extensions

  say "Step 3: install the app"
  install_app || die "Could not install the app from $REPO. If the site is down, try again later. If Flatpak says the app is
already installed from another source (for example a downloaded bundle), run 'flatpak uninstall $APP_ID' (your data is kept) and then this command again."

  start_setup
}

main "$@"
