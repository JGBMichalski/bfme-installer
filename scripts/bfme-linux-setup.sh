#!/usr/bin/env bash
# BFME Foundation Project - Linux setup (runs the Windows apps under Proton).
#
# Sets up one shared Proton environment (a "prefix") and two shortcuts:
#   - All-in-One Launcher
#   - Online Arena (started on its own, not from the launcher's Multiplayer tab)
#
# It never uses sudo and never installs system packages. If something is
# missing, "doctor" tells you what to install.
#
# Usage: bfme-linux-setup.sh [--machine] <command>
#   doctor              Check system requirements for the chosen runner.
#   install             Set up everything (runner, prefix, settings, launcher, Arena, shortcuts).
#   launcher            Start the All-in-One Launcher (installs it first if needed).
#   arena               Start the Online Arena (downloads or updates it first).
#   game bfme1|bfme2|rotwk   Start a game without the Arena.
#   shortcuts           (Re)create the two menu shortcuts.
#   status              Show what is installed and where.
#   reset-prefix --yes  Delete the prefix. This deletes installed games.
#   help                Show this help.
#
# --machine (or BFME_PROGRESS=1) also prints status lines for a program to read, for example the
# setup wizard. Each starts with "@bfme " and is described in docs/status-lines.md. The normal
# text output is unchanged. Send the script SIGUSR1 to stop an install cleanly before the next step.
#
# Two runners are supported. Proton is the default.
#   proton  Proton through umu-launcher. Downloaded for you. Needs no sudo.
#   wine    Your system Wine (tested with Wine 10.0). Needs winetricks, which is downloaded for you.
#
# Settings go in <data dir>/config.env (plain shell variables) or the environment:
#   BFME_RUNNER        proton (default) or wine
#   BFME_PROTONPATH    Proton to use (default pinned UMU-Proton; UMU-Latest, GE-Proton or a path also work)
#   BFME_ARENA_BRANCH  Arena update branch (default main)
#   BFME_NVIDIA        auto (default), 1 or 0. Use the NVIDIA card on a two-card computer.
#   BFME_EXTRA_ENV     Extra environment, e.g. "DXVK_HUD=fps"
#   BFME_UMU_RUN       Path to an existing umu-run (default: download one)
#   BFME_HOME          Data dir (default ~/.local/share/bfme-installer)
# Use one runner per prefix. Wine and Proton prefixes are not interchangeable.

set -euo pipefail

# CI replaces the placeholder with the release version (from the git tag). A copy straight from the repository
# keeps it and reports "dev".
SCRIPT_VERSION="@BFME_VERSION@"
case "$SCRIPT_VERSION" in "@"*) SCRIPT_VERSION="dev" ;; esac
readonly SCRIPT_VERSION
# Pinned on purpose: "UMU-Latest" moves, which re-downloads Proton and can change game behaviour
# (and so risk "Out of Sync" against Windows players). Raise this together with a release.
# umu can only download "latest" builds by name, so this exact build is fetched and verified here.
readonly DEFAULT_PROTONPATH="UMU-Proton-10.0-4"
readonly PROTON_URL="https://github.com/Open-Wine-Components/umu-proton/releases/download/${DEFAULT_PROTONPATH}/${DEFAULT_PROTONPATH}.tar.gz"
readonly PROTON_SHA256="62e99e029a18fa313e6fa63d42390918101730a940e3491c54d9d58cab887c69"
readonly UMU_VERSION="1.4.4"
readonly UMU_URL="https://github.com/Open-Wine-Components/umu-launcher/releases/download/${UMU_VERSION}/umu-launcher-${UMU_VERSION}-zipapp.tar"
readonly UMU_SHA256="eb590691841f7fad3fc3ad8fd5db4ccb87849fe7948e62b28ece7a4ee48cc851"
readonly LAUNCHER_SETUP_URL="https://arena-files.bfmeladder.com/downloads/AllInOneLauncherSetup.exe"
readonly ARENA_FILES_HOST="https://arena-files.bfmeladder.com"
readonly ARENA_SERVER_HOST="https://bfmeladder.com"
readonly WINETRICKS_VERSION="20260125"
readonly WINETRICKS_URL="https://raw.githubusercontent.com/Winetricks/winetricks/${WINETRICKS_VERSION}/src/winetricks"
readonly WINETRICKS_SHA256="431f82fc74000e6c864409f1d8fb495d696c03928808e3e8acffc45179312a7b"
readonly MIN_FREE_GB=30                   # three games plus the Arena

BASE="${BFME_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/bfme-installer}"
DOWNLOADS="$BASE/downloads"
LOGS="$BASE/logs"
BIN="$BASE/bin"

# Optional user settings.
# shellcheck disable=SC1091
[ -f "$BASE/config.env" ] && . "$BASE/config.env"

# Inside the Flatpak, system requirements come from the Flatpak runtime, there is no system Wine,
# and the menu entries are provided by the Flatpak itself.
IN_FLATPAK=0
if [ -n "${FLATPAK_ID:-}" ]; then IN_FLATPAK=1; fi

RUNNER="${BFME_RUNNER:-proton}"
if [ "$IN_FLATPAK" = "1" ] && [ "$RUNNER" != "proton" ]; then
  printf 'ERROR: The Flatpak only supports the proton runner (there is no system Wine in the sandbox).\n' >&2
  exit 1
fi
PROTONPATH_VALUE="${BFME_PROTONPATH:-$DEFAULT_PROTONPATH}"
ARENA_BRANCH="${BFME_ARENA_BRANCH:-main}"
NVIDIA_MODE="${BFME_NVIDIA:-auto}"
UMU_RUN="${BFME_UMU_RUN:-}"

case "$RUNNER" in
  proton) WINE_USER="steamuser"; PREFIX="$BASE/prefix" ;;   # Proton always names the user steamuser
  wine)   WINE_USER="${USER:-$(id -un)}"; PREFIX="$BASE/wineprefix" ;;
  *) printf 'ERROR: BFME_RUNNER must be proton or wine, not "%s".\n' "$RUNNER" >&2; exit 1 ;;
esac

ROAMING="$PREFIX/drive_c/users/$WINE_USER/AppData/Roaming"
LAUNCHER_DIR="$ROAMING/BFME All In One Launcher"
LAUNCHER_EXE="$LAUNCHER_DIR/AllInOneLauncher.exe"
ARENA_DIR="$ROAMING/BFME Competetive Arena"
ARENA_EXE="$ARENA_DIR/BfmeFoundationProject_OnlineArena.exe"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

# ---------------------------------------------------------------- output ----
say()  { printf '%s\n' "$*"; }

# Status lines for programs (--machine). One line each, always starting with "@bfme ".
MACHINE="${BFME_PROGRESS:-0}"
STEP_CURRENT=""
ERROR_REPORTED=0
CANCEL_REQUESTED=0
CANCELLED=0
machine() {
  [ "$MACHINE" = "1" ] || return 0
  local line="$*"
  printf '@bfme %s\n' "${line//$'\n'/ }"
}
step_start() { check_cancel; STEP_CURRENT="$1"; machine STEP "$1" start; }
step_done()  { machine STEP "$1" "done"; STEP_CURRENT=""; }
step_skip()  { check_cancel; machine STEP "$1" skip; }
# SIGUSR1 only sets a flag. Bash runs the trap after the current command ends, so the install
# stops cleanly between steps and a later run carries on where this one stopped.
check_cancel() {
  [ "$CANCEL_REQUESTED" = "1" ] || return 0
  CANCELLED=1
  machine CANCELLED
  say "Stopped before the next step."
  exit 130
}
trap 'CANCEL_REQUESTED=1' USR1
# Any failure that did not go through die() (for example a failed download) still reports an error.
on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$ERROR_REPORTED" = "0" ] && [ "$CANCELLED" = "0" ]; then
    machine ERROR "${STEP_CURRENT:--}" "Failed (exit $rc). See the logs in $LOGS"
  fi
}
trap on_exit EXIT

warn() { printf 'WARNING: %s\n' "$*" >&2; machine WARN "$*"; }
die()  {
  printf 'ERROR: %s\n' "$*" >&2
  machine ERROR "${STEP_CURRENT:--}" "$*"
  ERROR_REPORTED=1
  exit 1
}

# ---------------------------------------------------------------- doctor ----
DOCTOR_FAILS=0
DOCTOR_WARNS=0
# Each check has an id (first argument) so a program can tell the checks apart.
pass()   { local id="$1"; shift; printf '  [ok]   %s\n' "$*"; machine CHECK "$id" ok "$*"; }
fail()   { local id="$1"; shift; printf '  [FAIL] %s\n' "$*"; machine CHECK "$id" fail "$*"; DOCTOR_FAILS=$((DOCTOR_FAILS + 1)); }
notice() { local id="$1"; shift; printf '  [warn] %s\n' "$*"; machine CHECK "$id" warn "$*"; DOCTOR_WARNS=$((DOCTOR_WARNS + 1)); }

distro_family() {
  local id="" like=""
  if [ -r /etc/os-release ]; then
    id="$(. /etc/os-release; printf '%s' "${ID:-}")"
    like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
  fi
  case " $id $like " in
    *" debian "*|*" ubuntu "*) echo debian ;;
    *" fedora "*|*" rhel "*)   echo fedora ;;
    *" arch "*)                echo arch ;;
    *" suse "*|*" opensuse "*) echo suse ;;
    *)                         echo unknown ;;
  esac
}

install_hint() {
  # $1 check id; $2 what is missing; $3 debian packages; $4 fedora/suse packages; $5 arch packages
  local cmd=""
  case "$(distro_family)" in
    debian) cmd="sudo apt install $3" ;;
    fedora) cmd="sudo dnf install $4" ;;
    arch)   cmd="sudo pacman -S $5" ;;
    suse)   cmd="sudo zypper install $4" ;;
  esac
  if [ -n "$cmd" ]; then
    say "         Install: $cmd"
    machine FIX "$1" "$cmd"
  else
    say "         Install $2 with your package manager."
  fi
}

check_cmd() {
  # $1 command; $2 debian pkg; $3 fedora/suse pkg; $4 arch pkg
  if command -v "$1" >/dev/null 2>&1; then
    pass "cmd-$1" "$1 found"
  else
    fail "cmd-$1" "$1 not found"
    install_hint "cmd-$1" "$1" "$2" "$3" "$4"
  fi
}

existing_parent() {
  local p="$1"
  while [ ! -d "$p" ] && [ "$p" != "/" ]; do p="$(dirname "$p")"; done
  printf '%s' "$p"
}

cmd_doctor() {
  DOCTOR_FAILS=0
  DOCTOR_WARNS=0
  say "BFME Linux setup $SCRIPT_VERSION - system check (runner: $RUNNER)"
  say ""

  if [ "$(uname -m)" = "x86_64" ]; then
    pass cpu "x86_64 processor"
  else
    fail cpu "processor is $(uname -m); only x86_64 is supported"
  fi

  check_cmd curl curl curl curl
  check_cmd tar tar tar tar

  if [ "$IN_FLATPAK" = "1" ]; then
    check_cmd python3 python3 python3 python
    pass flatpak "running in a Flatpak: graphics libraries and the Proton container come from the Flatpak, so host checks are skipped"
    if flatpak_32bit_missing; then
      fail flatpak-32bit "the 32-bit Flatpak extensions are not installed"
      flatpak_32bit_message | sed 's/^/         /'
      machine FIX flatpak-32bit "$(flatpak_32bit_fix_command)"
    else
      pass flatpak-32bit "32-bit Flatpak extensions installed"
    fi
  elif [ "$RUNNER" = "proton" ]; then
    check_cmd python3 python3 python3 python
    check_cmd bwrap bubblewrap bubblewrap bubblewrap
    # Proton's container needs bubblewrap to be allowed to create user namespaces.
    if command -v bwrap >/dev/null 2>&1; then
      if bwrap --ro-bind / / --dev /dev true >/dev/null 2>&1; then
        pass bwrap "bubblewrap can start a sandbox"
      else
        fail bwrap "bubblewrap cannot start a sandbox (user namespaces are blocked)"
        say "         On Ubuntu 24.04 and newer, make sure the bubblewrap AppArmor profile is installed."
      fi
    fi
  else
    check_cmd wine "wine wine32:i386" wine wine
    check_cmd cabextract cabextract cabextract cabextract
    if command -v wine >/dev/null 2>&1; then
      pass wine-version "Wine version: $(wine --version 2>/dev/null || echo unknown). Use one Wine version per prefix."
    fi
    # Debian and Ubuntu need the 32-bit architecture enabled for 32-bit Wine.
    if command -v dpkg >/dev/null 2>&1; then
      if dpkg --print-foreign-architectures 2>/dev/null | grep -q i386; then
        pass i386-arch "32-bit (i386) packages enabled"
      else
        fail i386-arch "32-bit (i386) packages are not enabled"
        say "         Run: sudo dpkg --add-architecture i386 && sudo apt update"
        machine FIX i386-arch "sudo dpkg --add-architecture i386 && sudo apt update"
      fi
    fi
  fi

  # Vulkan is needed for DXVK. The 32-bit loader matters because the games are 32-bit.
  # (Inside a Flatpak, ldconfig sees the runtime and not the host, so the check would be wrong.)
  if [ "$IN_FLATPAK" = "0" ] && command -v ldconfig >/dev/null 2>&1; then
    # Capture first: "grep -q" closing the pipe early would make ldconfig fail under pipefail.
    local libs vulkan
    libs="$(ldconfig -p 2>/dev/null || true)"
    vulkan="$(printf '%s\n' "$libs" | grep 'libvulkan\.so\.1 ' || true)"
    if printf '%s\n' "$vulkan" | grep -q 'x86-64'; then
      pass vulkan64 "64-bit Vulkan loader found"
    else
      fail vulkan64 "64-bit Vulkan loader (libvulkan.so.1) not found"
      install_hint vulkan64 "the Vulkan loader" "libvulkan1 mesa-vulkan-drivers" "vulkan-loader mesa-vulkan-drivers" "vulkan-icd-loader"
    fi
    if printf '%s\n' "$vulkan" | grep -v 'x86-64' | grep -q 'libvulkan'; then
      pass vulkan32 "32-bit Vulkan loader found"
    else
      notice vulkan32 "32-bit Vulkan loader not found (the games are 32-bit)"
      install_hint vulkan32 "32-bit graphics libraries" "libvulkan1:i386 mesa-vulkan-drivers:i386" "vulkan-loader.i686 mesa-vulkan-drivers.i686" "lib32-vulkan-icd-loader lib32-vulkan-mesa-layers"
    fi
  fi

  local free_kb
  free_kb="$(df -Pk "$(existing_parent "$BASE")" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -n "$free_kb" ] && [ "$((free_kb / 1024 / 1024))" -ge "$MIN_FREE_GB" ]; then
    pass disk "free disk space: $((free_kb / 1024 / 1024)) GB (need about $MIN_FREE_GB GB)"
  else
    notice disk "less than $MIN_FREE_GB GB free where the data goes ($BASE)"
  fi

  # Firewall: informational only. The script never changes firewall rules.
  # (A Flatpak cannot see the host's firewall services.)
  local fw="" svc
  for svc in ufw firewalld; do
    if [ "$IN_FLATPAK" = "0" ] && command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$svc" 2>/dev/null; then
      fw="$svc"
    fi
  done
  if [ "$IN_FLATPAK" = "1" ]; then
    pass firewall "firewall: not checked from inside a Flatpak. If you cannot host or join games, check ufw or firewalld on your system."
  elif [ -n "$fw" ]; then
    notice firewall "firewall '$fw' is active. If you cannot host or join games, check that it allows the game and Arena traffic."
  else
    pass firewall "no active ufw or firewalld found"
  fi

  say ""
  if [ "$DOCTOR_FAILS" -gt 0 ]; then
    say "$DOCTOR_FAILS problem(s) must be fixed first."
    return 1
  fi
  if [ "$DOCTOR_WARNS" -gt 0 ]; then
    say "Ready, with $DOCTOR_WARNS warning(s) above."
  else
    say "Ready."
  fi
}

# Best-effort desktop notification, used for long steps when started from the menu (no terminal).
notify() {
  [ -t 1 ] && return 0
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -a "BFME" "BFME" "$1" >/dev/null 2>&1 || true
  elif command -v gdbus >/dev/null 2>&1; then
    gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop \
      --method org.freedesktop.portal.Notification.AddNotification bfme-setup \
      "{'title': <'BFME'>, 'body': <'$1'>}" >/dev/null 2>&1 || true
  fi
  return 0
}

# Inside the Flatpak the 32-bit libraries come from two Flatpak extensions that Flatpak does not
# install on its own for apps outside Flathub. Without them Proton's container fails silently.
FLATPAK_RUNTIME_VERSION="25.08"
flatpak_32bit_missing() {
  # Succeeds (returns 0) when something is missing. Markers are the mounted extension files.
  [ ! -e /usr/lib/i386-linux-gnu/ld-linux.so.2 ] && return 0
  local d name found_gl32=0
  # Every GL driver mounted for 64-bit (for example nvidia-550-107-02) needs the same 32-bit one.
  # A host driver update changes this name and flatpak update does not fetch the 32-bit match.
  for d in /usr/lib/x86_64-linux-gnu/GL/nvidia-*; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    [ -d "/usr/lib/i386-linux-gnu/GL/$name" ] || return 0
    found_gl32=1
  done
  [ "$found_gl32" = "1" ] || [ -d /usr/lib/i386-linux-gnu/GL/default ] || return 0
  return 1
}
# The exact command that fixes the above, for a program (such as the wizard) to show.
flatpak_32bit_fix_command() {
  local ext="org.freedesktop.Platform.Compat.i386//${FLATPAK_RUNTIME_VERSION} org.freedesktop.Platform.GL32.default//${FLATPAK_RUNTIME_VERSION}" d
  for d in /usr/lib/x86_64-linux-gnu/GL/nvidia-*; do
    [ -d "$d" ] || continue
    ext="$ext org.freedesktop.Platform.GL32.$(basename "$d")"
  done
  printf 'flatpak install --user flathub %s' "$ext"
}
flatpak_32bit_message() {
  cat <<EOF
The 32-bit parts of the Flatpak runtime are not installed, so the games and apps cannot start.
Easiest fix: run the installer again (it also picks the 32-bit driver that matches your graphics card):
  curl -fLO <repository address>/install-flatpak.sh && bash install-flatpak.sh
Or by hand, then start the app again:
  flatpak install flathub org.freedesktop.Platform.Compat.i386//${FLATPAK_RUNTIME_VERSION} org.freedesktop.Platform.GL32.default//${FLATPAK_RUNTIME_VERSION}
With an NVIDIA graphics card also install the matching 32-bit driver. Find its name with:
  flatpak list | grep nvidia
and install the same name with GL32 in place of GL, for example org.freedesktop.Platform.GL32.nvidia-<version>.
EOF
}

# -------------------------------------------------------------- download ----
download() {
  # $1 url, $2 destination. Resumes a partial download.
  local url="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  say "Downloading $(basename "$dest")"
  if [ "$MACHINE" = "1" ]; then
    download_with_progress "$url" "$dest.part"
  else
    curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --speed-limit 1024 --speed-time 30 -C - --progress-bar \
      -o "$dest.part" "$url" 9>&-
  fi
  mv -f "$dest.part" "$dest"
}

# curl's own progress bar is for people. For programs, watch the growing file and print PROGRESS lines.
# Without a size from the server there are no PROGRESS lines, so the reader shows "working".
download_with_progress() {
  # $1 url, $2 the .part file
  local url="$1" part="$2" total pid rc=0 size pct last=-1
  total="$(curl -fsIL -m 15 "$url" 2>/dev/null | awk 'tolower($1) == "content-length:" {v = $2} END {gsub(/\r/, "", v); print v}')" || total=""
  curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 --speed-limit 1024 --speed-time 30 -C - -o "$part" "$url" 9>&- &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
      size="$(stat -c %s "$part" 2>/dev/null || echo 0)"
      pct=$((size * 100 / total))
      [ "$pct" -gt 100 ] && pct=100
      if [ "$pct" != "$last" ]; then machine PROGRESS "$pct"; last="$pct"; fi
    fi
    sleep 0.5 9>&-
  done
  wait "$pid" || rc=$?
  [ "$rc" -eq 0 ] || return "$rc"
  [ "$last" = "100" ] || [ -z "$total" ] || machine PROGRESS 100
}

verify_sha256() {
  # $1 file; $2 expected hash
  local got
  got="$(sha256sum "$1" | awk '{print $1}')"
  if [ "$got" != "$2" ]; then
    rm -f "$1"
    die "Checksum mismatch for $(basename "$1") (expected $2, got $got)."
  fi
}

# ---------------------------------------------------------------- runner ----
# Everything that differs between Proton and Wine lives in this section.

ensure_umu() {
  if [ -n "$UMU_RUN" ]; then
    [ -x "$UMU_RUN" ] || die "BFME_UMU_RUN is set to '$UMU_RUN' but it is not executable."
    return
  fi
  if command -v umu-run >/dev/null 2>&1; then
    UMU_RUN="$(command -v umu-run)"
    return
  fi
  UMU_RUN="$BASE/umu/umu-run"
  [ -x "$UMU_RUN" ] && return
  local tarball="$DOWNLOADS/umu-launcher-${UMU_VERSION}-zipapp.tar"
  download "$UMU_URL" "$tarball"
  verify_sha256 "$tarball" "$UMU_SHA256"
  tar -xf "$tarball" -C "$BASE" 9>&- || die "umu could not be unpacked. Run install again."
  [ -x "$UMU_RUN" ] || die "umu-run was not found after extracting $tarball."
}

WINETRICKS=""
ensure_winetricks() {
  if command -v winetricks >/dev/null 2>&1; then
    WINETRICKS="$(command -v winetricks)"
    return
  fi
  WINETRICKS="$BIN/winetricks"
  [ -x "$WINETRICKS" ] && return
  mkdir -p "$BIN"
  download "$WINETRICKS_URL" "$WINETRICKS"
  verify_sha256 "$WINETRICKS" "$WINETRICKS_SHA256"
  chmod +x "$WINETRICKS"
}

use_nvidia() {
  case "$NVIDIA_MODE" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  # auto: an NVIDIA card together with another graphics card (laptops with PRIME).
  command -v lspci >/dev/null 2>&1 || return 1
  local cards
  cards="$(lspci 2>/dev/null | grep -iE 'vga|3d' || true)"
  [ "$(printf '%s\n' "$cards" | grep -c .)" -gt 1 ] && printf '%s\n' "$cards" | grep -qi nvidia
}

# Download the pinned Proton build. Other values of BFME_PROTONPATH are passed to umu unchanged.
ensure_proton() {
  [ "$PROTONPATH_VALUE" = "$DEFAULT_PROTONPATH" ] || return 0
  local dir="$BASE/proton/$DEFAULT_PROTONPATH"
  if [ ! -f "$dir/toolmanifest.vdf" ]; then
    local tarball="$DOWNLOADS/$DEFAULT_PROTONPATH.tar.gz"
    download "$PROTON_URL" "$tarball"
    verify_sha256 "$tarball" "$PROTON_SHA256"
    # Extract next to the final place and rename when done. The folder then exists only when it is complete, so
    # an interrupted extraction cannot leave a Proton that looks installed but is missing files.
    local tmp="$BASE/proton/.extracting"
    rm -rf "$dir" "$tmp"
    mkdir -p "$tmp"
    tar -xzf "$tarball" -C "$tmp" 9>&- || die "Proton could not be unpacked. Run install again."
    [ -f "$tmp/$DEFAULT_PROTONPATH/toolmanifest.vdf" ] || die "Proton was not found after extracting $tarball."
    mv "$tmp/$DEFAULT_PROTONPATH" "$dir"
    rm -rf "$tmp"
    rm -f "$tarball"
  fi
  PROTONPATH_VALUE="$dir"
}

# Run a program with the shared prefix.
# $1: "inprefix" (use an existing prefix) or "create" (first start, may create it); the rest is the command.
run_in_runner() {
  local mode="$1"
  shift
  (
    exec 9>&-   # the setup lock (acquire_setup_lock) must not follow the programs we start
    export WINEPREFIX="$PREFIX"
    # DXVK otherwise writes its shader cache into whatever folder the script was started from.
    mkdir -p "$BASE/dxvk-cache"
    export DXVK_STATE_CACHE_PATH="$BASE/dxvk-cache"
    if use_nvidia; then
      export __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only
    fi
    if [ "$RUNNER" = "proton" ]; then
      export PROTONPATH="$PROTONPATH_VALUE" GAMEID=0
      # runinprefix stops umu from waiting for another Wine session. Do not use it on the first start.
      if [ "$mode" = "inprefix" ]; then export PROTON_VERB=runinprefix; fi
      # Anything else in the prefix is kept; umu-run sets up Proton and the runtime on first use.
    else
      export WINEARCH=win64 DXVK_CONFIG_FILE="$BASE/dxvk.conf"
    fi
    if [ -n "${BFME_EXTRA_ENV:-}" ]; then
      # shellcheck disable=SC2163
      for kv in $BFME_EXTRA_ENV; do export "$kv"; done
    fi
    if [ "$RUNNER" = "proton" ]; then
      "$UMU_RUN" "$@"
    else
      case "${1:-}" in
        *.exe|*.EXE) wine "$@" ;;
        *)           "$@" ;;
      esac
    fi
  )
}

# Registry write inside the prefix.
reg_add() {
  # $1 key; $2 value name; $3 type; $4 data
  if [ "$RUNNER" = "proton" ]; then
    run_in_runner inprefix reg add "$1" /v "$2" /t "$3" /d "$4" /f >>"$LOGS/prefix-settings.log" 2>&1 \
      || warn "Could not set $2. See $LOGS/prefix-settings.log"
  else
    run_in_runner inprefix wine reg add "$1" /v "$2" /t "$3" /d "$4" /f >>"$LOGS/prefix-settings.log" 2>&1 \
      || warn "Could not set $2. See $LOGS/prefix-settings.log"
  fi
}

# The folders Wine makes first. They can exist long before the prefix is usable.
prefix_dirs_exist() {
  [ -d "$PREFIX/drive_c/windows" ] && [ -d "$PREFIX/drive_c/users/$WINE_USER" ]
}

# A prefix is ready when it has its folders and its creation was not interrupted: create_prefix leaves
# .bfme-creating behind until it has finished, so a killed creation is redone instead of trusted.
prefix_ready() {
  [ ! -e "$PREFIX/.bfme-creating" ] && prefix_dirs_exist
}

ensure_runner() {
  mkdir -p "$BASE" "$DOWNLOADS" "$LOGS"
  if [ "$IN_FLATPAK" = "1" ] && flatpak_32bit_missing; then
    notify "The 32-bit Flatpak extensions are missing. Open a terminal and run: flatpak run --command=bfme-linux-setup $FLATPAK_ID doctor"
    flatpak_32bit_message >&2
    exit 1
  fi
  if [ "$RUNNER" = "proton" ]; then
    ensure_umu
    ensure_proton
  else
    command -v wine >/dev/null 2>&1 || die "Wine is not installed. Run 'doctor' for what to install."
    ensure_winetricks
  fi
}

create_prefix() {
  mkdir -p "$PREFIX"
  : >"$PREFIX/.bfme-creating"
  if [ "$RUNNER" = "proton" ]; then
    say "Creating the Proton prefix. The first start downloads Proton and takes a few minutes."
    notify "First start: setting up Proton. This takes a few minutes."
    # "umu-run ''" builds the prefix and then exits with an error because there is
    # nothing to run. That is expected, so the result is checked by the files created.
    run_in_runner create "" >"$LOGS/prefix-create.log" 2>&1 || true
  else
    say "Creating the Wine prefix."
    # The Windows 10 setting, DXVK (fast menus), D3DX9 (units in BFME 2 and RotWK) and fonts
    # (the Arena password box) come from winetricks.
    { run_in_runner create wineboot -u \
        && run_in_runner create "$WINETRICKS" -q corefonts win10 dxvk d3dx9; } >"$LOGS/prefix-create.log" 2>&1 || true
  fi
  if ! prefix_dirs_exist; then
    tail -n 20 "$LOGS/prefix-create.log" >&2
    die "Could not create the prefix. See $LOGS/prefix-create.log"
  fi
  if [ "$RUNNER" = "wine" ]; then
    wine --version >"$PREFIX/.bfme-wine-version" 2>/dev/null || true
  fi
  rm -f "$PREFIX/.bfme-creating"
}

# Settings the games and apps need. Tested in both runners (see the project notes).
# They are applied once per SETTINGS_VERSION. Raise it to roll out a new setting.
SETTINGS_VERSION=3
apply_prefix_settings() {
  local marker="$PREFIX/.bfme-settings-v$SETTINGS_VERSION"
  [ -f "$marker" ] && return
  say "Applying prefix settings."
  : >"$LOGS/prefix-settings.log"
  local dll

  # Use the games' own Microsoft C++ runtime, not the runner's. The runner's copy rounds
  # numbers slightly differently, so a Linux player and a Windows player drift apart and
  # the match ends with "Out of Sync". dinput8 is set because the tested setups set it.
  for dll in mfc71 msvcp71 msvcr71 dinput8; do
    reg_add 'HKCU\Software\Wine\DllOverrides' "$dll" REG_SZ 'native,builtin'
  done

  # Without this, the launcher does not repaint a tab correctly after you leave the Multiplayer tab.
  reg_add 'HKCU\Software\Microsoft\Avalon.Graphics' DisableHWAcceleration REG_DWORD 1

  if [ "$RUNNER" = "proton" ]; then
    # Make sure the games use DXVK (Proton's Direct3D to Vulkan layer).
    for dll in d3d8 d3d9 d3d11 dxgi; do
      reg_add 'HKCU\Software\Wine\DllOverrides' "$dll" REG_SZ 'native,builtin'
    done
  else
    # The game closes at map load without this file.
    cat >"$BASE/dxvk.conf" <<'EOF'
d3d9.countLosableResources = False
d3d9.floatEmulation = strict
d3d9.maxFrameLatency = 1
d3d9.presentInterval = 0
EOF
    # Normal 100% text size for the launcher.
    reg_add 'HKCU\Control Panel\Desktop' LogPixels REG_DWORD 96
  fi

  : >"$marker"
}

# Only one setup at a time, so two never write the same files. Everything that can change the setup takes the lock;
# start_app gives it back before an app starts, so a running launcher does not block a later install.
# The lock is file descriptor 9 of this script and ends with it. Programs started from here must close it (9>&-),
# or a download left behind by a killed script would keep the lock and block every later run.
SETUP_LOCK_HELD=0
acquire_setup_lock() {
  [ "$SETUP_LOCK_HELD" = "1" ] && return 0
  command -v flock >/dev/null 2>&1 || return 0
  mkdir -p "$BASE"
  exec 9>"$BASE/.setup.lock"
  if ! flock -n 9; then
    notify "Setup is already running. Please wait, the first start takes a few minutes."
    if [ "$IN_FLATPAK" = "1" ]; then
      die "Another setup is already running. Wait for it to finish. If you stopped one earlier and it is stuck, run: flatpak kill $FLATPAK_ID"
    fi
    die "Another setup is already running. Wait for it to finish."
  fi
  SETUP_LOCK_HELD=1
}

release_setup_lock() {
  [ "$SETUP_LOCK_HELD" = "1" ] || return 0
  exec 9>&-
  SETUP_LOCK_HELD=0
}

# Everything after the runner is in place: create the prefix and apply its settings.
prepare_prefix() {
  prefix_ready || create_prefix
  if [ "$RUNNER" = "wine" ] && [ -f "$PREFIX/.bfme-wine-version" ]; then
    local now was
    now="$(wine --version 2>/dev/null || true)"
    was="$(cat "$PREFIX/.bfme-wine-version")"
    if [ -n "$now" ] && [ "$now" != "$was" ]; then
      warn "This prefix was made with $was but you are running $now. Another Wine version can break the Arena."
      warn "If the Arena fails with 'Could not load ICU data', delete icu.dll, icuin.dll and icuuc.dll from system32 and syswow64 in the prefix."
    fi
  fi
  apply_prefix_settings
}

ensure_prefix() {
  acquire_setup_lock
  ensure_runner
  prepare_prefix
}

wait_for_stable_file() {
  # $1 file; $2 timeout in seconds. Succeeds when the file exists and its size is unchanged for 3 seconds.
  local file="$1" limit="$2" waited=0 last=-1 size
  while [ "$waited" -lt "$limit" ]; do
    if [ -f "$file" ]; then
      size="$(stat -c %s "$file" 2>/dev/null || echo 0)"
      if [ "$size" -gt 0 ] && [ "$size" = "$last" ]; then return 0; fi
      last="$size"
    fi
    sleep 3 9>&-
    waited=$((waited + 3))
  done
  return 1
}

# ----------------------------------------------------------- the launcher ----
# Ends every program in the Wine session (the "Wine server"). Needed because the runner waits for the whole
# session, not just the program it started.
stop_wine_session() {
  local ws="" candidate
  if [ "$RUNNER" = "wine" ]; then
    ws="$(command -v wineserver || true)"
  else
    for candidate in "$PROTONPATH_VALUE/files/bin/wineserver" \
                     "${XDG_DATA_HOME:-$HOME/.local/share}/umu/compatibilitytools/$PROTONPATH_VALUE/files/bin/wineserver"; do
      if [ -x "$candidate" ]; then ws="$candidate"; break; fi
    done
  fi
  if [ -z "$ws" ]; then
    warn "Could not find the Wine server. Close the launcher window to let the setup carry on."
    return 1
  fi
  WINEPREFIX="$PREFIX" "$ws" -k >/dev/null 2>&1 || true
  WINEPREFIX="$PREFIX" timeout 20 "$ws" -w >/dev/null 2>&1 || true   # wait until it has saved and exited
}

# The launcher is installed when its file is there and its setup was not interrupted: install_launcher leaves
# .bfme-launcher-installing behind until it has finished, so a half-copied file is not mistaken for a launcher.
launcher_installed() {
  [ -f "$LAUNCHER_EXE" ] && [ ! -e "$PREFIX/.bfme-launcher-installing" ]
}

install_launcher() {
  ensure_prefix
  launcher_installed && return
  local setup="$DOWNLOADS/AllInOneLauncherSetup.exe"
  [ -f "$setup" ] || download "$LAUNCHER_SETUP_URL" "$setup"
  say "Installing the launcher. It may open for a moment; the setup closes it again."
  # Start clean: a leftover half-copied file would look finished to wait_for_stable_file below.
  rm -f "$LAUNCHER_EXE"
  : >"$PREFIX/.bfme-launcher-installing"
  # The first start of the setup must not use runinprefix.
  # (9>&- because a function started with & runs in a copy of this shell, which would otherwise hold the lock.)
  run_in_runner create "$setup" >"$LOGS/launcher-setup.log" 2>&1 9>&- &
  local setup_pid=$! installed=0
  # When the setup finishes it starts the launcher, and the runner (Proton) does not return until every program
  # in the session has ended, so waiting for the setup would wait until someone closes the launcher.
  # Wait for the installed file to appear and stop growing instead, then end the session.
  wait_for_stable_file "$LAUNCHER_EXE" 180 && installed=1
  stop_wine_session || true
  wait "$setup_pid" 2>/dev/null || true
  [ "$installed" = "1" ] || die "The launcher was not installed. See $LOGS/launcher-setup.log"
  rm -f "$PREFIX/.bfme-launcher-installing" "$setup"
}

cmd_launcher() {
  install_launcher
  start_app "launcher" "$LAUNCHER_DIR" "$LAUNCHER_EXE"
}

# -------------------------------------------------------------- the arena ----
arena_remote_hash() {
  curl -fsS -m 10 "$ARENA_SERVER_HOST/api/applications/versionHash?name=online-arena&version=${ARENA_BRANCH}" 2>/dev/null || true
}

arena_local_hash() {
  [ -f "$ARENA_EXE" ] && md5sum "$ARENA_EXE" | awk '{print $1}'
}

install_or_update_arena() {
  ensure_prefix
  mkdir -p "$ARENA_DIR/Data"
  local remote local_hash=""
  remote="$(arena_remote_hash)"
  local_hash="$(arena_local_hash || true)"

  if [ -f "$ARENA_EXE" ]; then
    if [ -z "$remote" ]; then
      warn "Could not check for Arena updates. Starting the installed version."
      return
    fi
    [ "$local_hash" = "$remote" ] && return
    say "A new Arena version is available."
  else
    say "The Arena is not installed yet."
  fi

  local tmp="$DOWNLOADS/OnlineArena.exe"
  rm -f "$tmp" "$tmp.part"
  download "$ARENA_FILES_HOST/application-builds/online-arena-${ARENA_BRANCH}" "$tmp"
  if [ -n "$remote" ]; then
    local got
    got="$(md5sum "$tmp" | awk '{print $1}')"
    if [ "$got" != "$remote" ]; then
      rm -f "$tmp"
      die "Arena download failed its checksum check (expected $remote, got $got)."
    fi
  fi
  mv -f "$tmp" "$ARENA_EXE"
  chmod +x "$ARENA_EXE"
}

cmd_arena() {
  install_or_update_arena
  start_app "arena" "$ARENA_DIR" "$ARENA_EXE"
}

# ------------------------------------------------------------------ games ----
cmd_game() {
  local dir exe
  case "${1:-}" in
    bfme1) dir=BFME1; exe=lotrbfme.exe ;;
    bfme2) dir=BFME2; exe=lotrbfme2.exe ;;
    rotwk) dir=RotWK; exe=lotrbfme2ep1.exe ;;
    *) die "Use: game bfme1|bfme2|rotwk" ;;
  esac
  # Do not build anything here: a game can only exist in a prefix that is already set up.
  prefix_ready || die "Nothing is set up yet. Run: install"
  [ -d "$PREFIX/drive_c/$dir" ] || die "$dir is not installed. Install it in the Launcher first."
  ensure_prefix   # picks up newer prefix settings; changes nothing if they are current
  start_app "$dir" "$PREFIX/drive_c/$dir" "$PREFIX/drive_c/$dir/$exe"
}

# ------------------------------------------------------------- start apps ----
start_app() {
  # $1 name; $2 working dir; $3 exe
  local name="$1" dir="$2" exe="$3"
  release_setup_lock
  mkdir -p "$LOGS"
  local log
  log="$LOGS/$name-$(date +%Y%m%d-%H%M%S).log"
  say "Starting $name. Log: $log"
  cd "$dir"
  run_in_runner inprefix "$exe" >"$log" 2>&1 || true
  # Keep only the 10 newest logs per app.
  # shellcheck disable=SC2012
  ls -1t "$LOGS/$name-"*.log 2>/dev/null | tail -n +11 | while IFS= read -r old; do rm -f "$old"; done
}

# -------------------------------------------------------------- shortcuts ----
self_path() {
  local src="${BASH_SOURCE[0]}"
  [ -n "$src" ] || die "Cannot work out where this script is."
  (cd "$(dirname "$src")" && printf '%s/%s' "$(pwd)" "$(basename "$src")")
}

write_desktop() {
  # $1 file name; $2 display name; $3 comment; $4 command argument
  cat >"$APPS_DIR/$1" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=env BFME_HOME="$BASE" BFME_RUNNER="$RUNNER" "$BIN/bfme-linux-setup.sh" $4
Icon=applications-games
Terminal=false
Categories=Game;
StartupNotify=true
EOF
}

cmd_shortcuts() {
  if [ "$IN_FLATPAK" = "1" ]; then
    say "The menu entries are provided by the Flatpak. Nothing to do."
    return
  fi
  mkdir -p "$BIN" "$APPS_DIR"
  local me
  me="$(self_path)"
  if [ "$me" != "$BIN/bfme-linux-setup.sh" ]; then
    cp -f "$me" "$BIN/bfme-linux-setup.sh"
  fi
  chmod +x "$BIN/bfme-linux-setup.sh"
  write_desktop "bfme-launcher.desktop" "BFME All-in-One Launcher" "Install, mod and manage the BFME games" "launcher"
  write_desktop "bfme-arena.desktop" "BFME Online Arena" "Play BFME online" "arena"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  fi
  say "Shortcuts written to $APPS_DIR"
}

# ---------------------------------------------------------------- install ----
# The steps are reported as status lines (--machine): doctor, runner, prefix, launcher, arena, shortcuts.
cmd_install() {
  step_start doctor
  cmd_doctor || die "Fix the problems above, then run install again."
  step_done doctor
  say ""
  acquire_setup_lock
  step_start runner
  ensure_runner
  step_done runner
  step_start prefix
  prepare_prefix
  step_done prefix
  if launcher_installed; then
    step_skip launcher
  else
    step_start launcher
    install_launcher
    step_done launcher
  fi
  step_start arena
  install_or_update_arena
  step_done arena
  if [ "$IN_FLATPAK" = "1" ]; then
    step_skip shortcuts
    cmd_shortcuts
  else
    step_start shortcuts
    cmd_shortcuts
    step_done shortcuts
  fi
  machine DONE
  say ""
  say "Done. Start 'BFME All-in-One Launcher' to install the games, and 'BFME Online Arena' to play online."
  say "Do not switch patches in the launcher after a game is installed. On Wine this once broke the BFME 2 files."
}

# ----------------------------------------------------------------- status ----
cmd_status() {
  say "Runner:     $RUNNER$([ "$RUNNER" = proton ] && printf ' (%s)' "$PROTONPATH_VALUE")"
  say "Data dir:   $BASE"
  say "Prefix:     $PREFIX $(prefix_ready && echo '(ready)' || echo '(not created)')"
  say "Launcher:   $(launcher_installed && echo installed || echo 'not installed')"
  say "Arena:      $([ -f "$ARENA_EXE" ] && echo installed || echo 'not installed')"
  local g
  for g in BFME1 BFME2 RotWK; do
    say "$(printf '%-11s' "$g:") $([ -d "$PREFIX/drive_c/$g" ] && echo 'folder present' || echo 'not installed')"
  done
  # For programs: setup is complete when the prefix, launcher and Arena are all there.
  local p="missing" l="missing" a="missing" done_all="no"
  prefix_ready && p="ready"
  launcher_installed && l="installed"
  [ -f "$ARENA_EXE" ] && a="installed"
  if [ "$p" = "ready" ] && [ "$l" = "installed" ] && [ "$a" = "installed" ]; then done_all="yes"; fi
  machine STATUS runner "$RUNNER"
  machine STATUS prefix "$p"
  machine STATUS launcher "$l"
  machine STATUS arena "$a"
  machine STATUS complete "$done_all"
}

cmd_reset_prefix() {
  [ "${1:-}" = "--yes" ] || die "This deletes the prefix at $PREFIX, including any installed games. Run 'reset-prefix --yes' to confirm."
  case "$PREFIX" in
    ""|"/"|"$HOME") die "Refusing to delete '$PREFIX'." ;;
  esac
  acquire_setup_lock
  rm -rf -- "$PREFIX"
  say "Prefix deleted."
}

cmd_help() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

# ------------------------------------------------------------------- main ----
main() {
  if [ "${1:-}" = "--machine" ]; then MACHINE=1; shift; fi
  local cmd="${1:-help}"
  if [ $# -gt 0 ]; then shift; fi
  case "$cmd" in
    doctor)       cmd_doctor ;;
    install)      cmd_install ;;
    launcher)     cmd_launcher ;;
    arena)        cmd_arena ;;
    game)         cmd_game "$@" ;;
    shortcuts)    cmd_shortcuts ;;
    status)       cmd_status ;;
    reset-prefix) cmd_reset_prefix "$@" ;;
    help|-h|--help) cmd_help ;;
    version|--version) say "$SCRIPT_VERSION" ;;
    *) die "Unknown command '$cmd'. Run with 'help'." ;;
  esac
}

main "$@"
