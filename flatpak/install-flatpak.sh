#!/usr/bin/env bash
# BFME Installer for Linux: installs the Flatpak and the 32-bit Flatpak extensions it needs, then opens the
# setup wizard. Flatpak does not install those extensions for apps outside Flathub, so this does it for you.
# Runs as your user. No sudo. Safe to run again: it updates an existing install.
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
# .flatpak bundle attached to the same release (used if the repository cannot be reached).
readonly DEFAULT_REPO="@BFME_DEFAULT_REPO@"
readonly DEFAULT_BUNDLE_URL="@BFME_BUNDLE_URL@"

REPO="${BFME_FLATPAK_REPO:-}"
BUNDLE="${BFME_FLATPAK_BUNDLE:-}"
BUNDLE_URL="${BFME_FLATPAK_BUNDLE_URL:-}"
OPEN_WIZARD=1
TERMINAL=0
UNINSTALL=0
PURGE=0

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: install-flatpak.sh [options]
  --repo URL_OR_PATH   Install from this Flatpak repository (default: the project's repository)
  --bundle FILE_OR_URL Install from a single .flatpak file instead
  --no-setup           Install only. Do not open the setup wizard.
  --terminal           Run the setup in this terminal instead of opening the wizard.
  --uninstall          Remove the app and its Flatpak repository. Keeps your data and the shared 32-bit extensions.
  --purge              Uninstall and also delete the app's data: the setup, Proton and any installed games.
  -h, --help           Show this help.
EOF
}

# A placeholder that CI did not replace (a checkout, not a release) starts with "@".
baked() { case "$1" in "@"*|"") return 1 ;; *) return 0 ;; esac; }

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

app_installed() { flatpak info --user "$APP_ID" >/dev/null 2>&1; }

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

# Install or update from the Flatpak repository. Returns non-zero when that does not work.
install_from_repo() {
  local repo="$1"
  case "$repo" in /*) repo="file://$repo" ;; esac
  flatpak remote-add --user --if-not-exists --no-gpg-verify "$REMOTE_NAME" "$repo" || return 1
  # Keep the address current if an older install used a different one.
  flatpak remote-modify --user --no-gpg-verify --url="$repo" "$REMOTE_NAME" || return 1
  if ! app_installed; then
    flatpak install --user -y --noninteractive "$REMOTE_NAME" "$APP_ID" || return 1
  elif [ "$(flatpak info --user --show-origin "$APP_ID" 2>/dev/null)" = "$REMOTE_NAME" ]; then
    say "The app is already installed. Updating it (this also re-checked the extensions above)."
    flatpak update --user -y --noninteractive "$APP_ID" || return 1
  else
    # Installed from a bundle earlier. Switch it to the repository so it can update itself. Your data is kept.
    say "The app was installed from a download. Switching it to the repository so it can update itself."
    flatpak install --user --reinstall -y --noninteractive "$REMOTE_NAME" "$APP_ID" || return 1
  fi
}

# Check a downloaded bundle against the SHA256SUMS file next to it on the release, when there is one.
verify_download() {
  local url="$1" file="$2" dir sums name want got
  dir="${url%/*}"
  name="${url##*/}"
  sums="$(curl -fsSL -m 20 "$dir/SHA256SUMS" 2>/dev/null || true)"
  if [ -z "$sums" ]; then
    warn "Could not fetch SHA256SUMS to check the download. Continuing without the check."
    return 0
  fi
  want="$(printf '%s\n' "$sums" | awk -v n="$name" '$2 == n || $2 == "*" n {print $1; exit}')"
  [ -n "$want" ] || { warn "$name is not listed in SHA256SUMS. Continuing without the check."; return 0; }
  got="$(sha256sum "$file" | awk '{print $1}')"
  [ "$got" = "$want" ] || { warn "The download does not match SHA256SUMS."; return 1; }
  say "Checksum OK."
}

# Install from a .flatpak file, or from a web address that points to one.
install_from_bundle() {
  local src="$1" tmp="" file="$1" rc=0
  case "$src" in
    http://*|https://*|file://*)
      command -v curl >/dev/null 2>&1 || { warn "curl is needed to download the bundle."; return 1; }
      tmp="$(mktemp -d)"
      file="$tmp/${src##*/}"
      say "Downloading ${src##*/}"
      curl -fL --retry 3 --retry-delay 2 -o "$file" "$src" || { rm -rf "$tmp"; return 1; }
      case "$src" in http*) verify_download "$src" "$file" || { rm -rf "$tmp"; return 1; } ;; esac
      ;;
    *) [ -f "$file" ] || die "Bundle '$file' was not found." ;;
  esac
  # --reinstall replaces an existing install (the app's data is kept); without it Flatpak refuses.
  local again=()
  if app_installed; then again=(--reinstall); fi
  flatpak install --user -y --noninteractive "${again[@]}" --bundle "$file" || rc=$?
  [ -z "$tmp" ] || rm -rf "$tmp"
  return "$rc"
}

install_app() {
  if [ -n "$BUNDLE" ]; then
    install_from_bundle "$BUNDLE" || die "Could not install the bundle."
    return
  fi
  if [ -n "$REPO" ]; then
    if install_from_repo "$REPO"; then return; fi
    [ -n "$BUNDLE_URL" ] || die "Could not install from the Flatpak repository $REPO."
    warn "Could not install from the Flatpak repository. Trying the download from the release instead."
    if install_from_bundle "$BUNDLE_URL"; then
      say "Installed from the release download. This copy will not update itself; run this command again to update."
      return
    fi
    die "Could not install from the Flatpak repository or from the release download."
  fi
  if [ -n "$BUNDLE_URL" ]; then
    install_from_bundle "$BUNDLE_URL" || die "Could not install from the release download."
    return
  fi
  die "Give --repo URL or --bundle FILE (or set BFME_FLATPAK_REPO)."
}

start_setup() {
  say ""
  if [ "$OPEN_WIZARD" = "0" ]; then
    say "Installed. Open 'BFME Installer' from your application menu to finish the setup."
    return
  fi
  if [ "$TERMINAL" = "1" ]; then
    say "Step 4: setup in this terminal (downloads Proton and the launcher, a few minutes)"
    flatpak run --user --command=bfme-linux-setup "$APP_ID" install \
      || say "Setup did not finish. Run it again with: flatpak run --command=bfme-linux-setup $APP_ID install"
    return
  fi
  if has_display; then
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
  if app_installed; then
    flatpak uninstall --user -y --noninteractive "$APP_ID"
  else
    say "The app is not installed."
  fi
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
      --repo)      [ $# -ge 2 ] || die "--repo needs a value."; REPO="$2"; shift 2 ;;
      --bundle)    [ $# -ge 2 ] || die "--bundle needs a value."; BUNDLE="$2"; shift 2 ;;
      --no-setup)  OPEN_WIZARD=0; shift ;;
      --terminal)  TERMINAL=1; shift ;;
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

  # Defaults from the release build, unless a command-line option or an environment variable chose a source.
  if [ -z "$REPO" ] && [ -z "$BUNDLE" ] && baked "$DEFAULT_REPO"; then REPO="$DEFAULT_REPO"; fi
  if [ -z "$BUNDLE_URL" ] && baked "$DEFAULT_BUNDLE_URL"; then BUNDLE_URL="$DEFAULT_BUNDLE_URL"; fi

  say "Step 1: make sure Flathub is available for the runtime and the 32-bit extensions"
  if ! flatpak remotes --user --columns=name | grep -qx flathub; then
    flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
  fi

  say "Step 2: install the 32-bit extensions"
  install_extensions

  say "Step 3: install the app"
  install_app

  start_setup
}

main "$@"
