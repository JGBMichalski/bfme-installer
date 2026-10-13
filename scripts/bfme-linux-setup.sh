#!/usr/bin/env bash
# BFME Foundation Project - Linux setup (runs the Windows apps under Proton).
#
# Sets up one shared Proton environment (a "prefix") and installs what you choose into it:
#   - All-in-One Launcher, with the Online Arena (started on its own, not from the launcher's Multiplayer tab)
#   - Age of the Ring (optional)
#
# It never uses sudo and never installs system packages. If something is
# missing, "doctor" tells you what to install.
#
# Usage: bfme-linux-setup.sh [--machine] <command>
#   doctor              Check system requirements for the chosen runner.
#   prepare             Set up the game environment only (runner, prefix, settings). Installs no program.
#   launcher-install    Install the All-in-One Launcher and the Arena, and their shortcuts.
#   install             Everything for the Launcher and the Arena: prepare, then launcher-install.
#   launcher            Start the All-in-One Launcher (installs it first if needed).
#   arena               Start the Online Arena (downloads or updates it first).
#   game bfme1|bfme2|rotwk   Start a game without the Arena.
#   aotr-install <zip>  Install Age of the Ring (needs prepare first) from the zip you downloaded from ModDB.
#   aotr                Start the Age of the Ring Launcher.
#   shortcuts           Bring the menu shortcuts in line with what is installed: add the missing ones, remove the others.
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

# CI replaces the placeholder with the release version. A repository copy reports "dev".
SCRIPT_VERSION="@BFME_VERSION@"
case "$SCRIPT_VERSION" in "@"*) SCRIPT_VERSION="dev" ;; esac
readonly SCRIPT_VERSION
# Pinned: "UMU-Latest" moves, which re-downloads Proton and can change game behaviour (risking "Out of Sync").
# Raise it together with a release.
# umu downloads only "latest" builds by name, so this build is fetched and verified here.
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
readonly AOTR_INSTALL_RATIO_PERCENT=160 # Estimated installed size ratio for Age of the Ring
readonly AOTR_PAGE_URL="https://www.moddb.com/mods/the-horse-lords-a-total-modification-for-bfme/downloads/age-of-the-ring-version-90"

BASE="${BFME_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/bfme-installer}"
DOWNLOADS="$BASE/downloads"
LOGS="$BASE/logs"
BIN="$BASE/bin"

# shellcheck disable=SC1091
[ -f "$BASE/config.env" ] && . "$BASE/config.env"

# Inside the Flatpak: no system Wine, system requirements come from the runtime, menu entries come from the Flatpak.
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
AOTR_DIR="$PREFIX/drive_c/AgeoftheRing"
AOTR_EXE="$AOTR_DIR/AotR_Launcher.exe"
AOTR_UNPACK="$DOWNLOADS/aotr"
# Inside the Flatpak XDG_DATA_HOME is the app's own folder, but the menu is the host's.
# The manifest makes that one folder writable (--filesystem=xdg-data/applications:create).
if [ "$IN_FLATPAK" = "1" ]; then
  APPS_DIR="$HOME/.local/share/applications"
else
  APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
fi

say()  { printf '%s\n' "$*"; }

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
# SIGUSR1 only sets a flag. Bash runs the trap after the current command, so an install stops between steps.
check_cancel() {
  [ "$CANCEL_REQUESTED" = "1" ] || return 0
  CANCELLED=1
  machine CANCELLED
  say "Stopped before the next step."
  exit 130
}
trap 'CANCEL_REQUESTED=1' USR1
# Failures that skip die() (a failed download, say) still report an error.
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

DOCTOR_FAILS=0
DOCTOR_WARNS=0
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

  # The 32-bit loader matters because the games are 32-bit.
  # Inside a Flatpak ldconfig sees the runtime, not the host, so the check would be wrong.
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

  # A Flatpak cannot see the host's firewall services.
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

# Inside the Flatpak the 32-bit libraries come from two extensions that Flatpak does not install
# for apps outside Flathub. Without them Proton's container fails silently.
FLATPAK_RUNTIME_VERSION="25.08"
flatpak_32bit_missing() {
  [ ! -e /usr/lib/i386-linux-gnu/ld-linux.so.2 ] && return 0
  local d name found_gl32=0
  # Each 64-bit GL driver (nvidia-550-107-02, say) needs the same 32-bit one.
  # A host driver update changes the name and flatpak update does not fetch the 32-bit match.
  for d in /usr/lib/x86_64-linux-gnu/GL/nvidia-*; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    [ -d "/usr/lib/i386-linux-gnu/GL/$name" ] || return 0
    found_gl32=1
  done
  [ "$found_gl32" = "1" ] || [ -d /usr/lib/i386-linux-gnu/GL/default ] || return 0
  return 1
}
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

download() {
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

# Without a size from the server there are no PROGRESS lines, so the reader shows "working".
download_with_progress() {
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
  local got
  got="$(sha256sum "$1" | awk '{print $1}')"
  if [ "$got" != "$2" ]; then
    rm -f "$1"
    die "Checksum mismatch for $(basename "$1") (expected $2, got $got)."
  fi
}


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
  command -v lspci >/dev/null 2>&1 || return 1
  local cards
  cards="$(lspci 2>/dev/null | grep -iE 'vga|3d' || true)"
  [ "$(printf '%s\n' "$cards" | grep -c .)" -gt 1 ] && printf '%s\n' "$cards" | grep -qi nvidia
}

ensure_proton() {
  [ "$PROTONPATH_VALUE" = "$DEFAULT_PROTONPATH" ] || return 0
  local dir="$BASE/proton/$DEFAULT_PROTONPATH"
  if [ ! -f "$dir/toolmanifest.vdf" ]; then
    local tarball="$DOWNLOADS/$DEFAULT_PROTONPATH.tar.gz"
    download "$PROTON_URL" "$tarball"
    verify_sha256 "$tarball" "$PROTON_SHA256"
    # Extract beside the final place and rename when done, so an interrupted extraction
    # cannot leave a Proton that looks installed but is missing files.
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

run_in_runner() {
  local mode="$1"
  shift
  (
    exec 9>&-   # the setup lock (acquire_setup_lock) must not follow the programs we start
    export WINEPREFIX="$PREFIX"
    mkdir -p "$BASE/dxvk-cache"
    export DXVK_STATE_CACHE_PATH="$BASE/dxvk-cache"
    if use_nvidia; then
      export __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only
    fi
    if [ "$RUNNER" = "proton" ]; then
      export PROTONPATH="$PROTONPATH_VALUE" GAMEID=0
      # runinprefix stops umu from waiting for another Wine session. Do not use it on the first start.
      if [ "$mode" = "inprefix" ]; then export PROTON_VERB=runinprefix; fi
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

reg_add() {
  if [ "$RUNNER" = "proton" ]; then
    run_in_runner inprefix reg add "$1" /v "$2" /t "$3" /d "$4" /f >>"$LOGS/prefix-settings.log" 2>&1 \
      || warn "Could not set $2. See $LOGS/prefix-settings.log"
  else
    run_in_runner inprefix wine reg add "$1" /v "$2" /t "$3" /d "$4" /f >>"$LOGS/prefix-settings.log" 2>&1 \
      || warn "Could not set $2. See $LOGS/prefix-settings.log"
  fi
}

prefix_dirs_exist() {
  [ -d "$PREFIX/drive_c/windows" ] && [ -d "$PREFIX/drive_c/users/$WINE_USER" ]
}

# create_prefix leaves .bfme-creating behind until it finishes, so a killed creation is redone.
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
    # "umu-run ''" builds the prefix, then exits with an error because there is nothing to run.
    # That is expected, so check the files it created.
    run_in_runner create "" >"$LOGS/prefix-create.log" 2>&1 || true
  else
    say "Creating the Wine prefix."
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

# SETTINGS_VERSION: raise it to roll out a new setting.
SETTINGS_VERSION=3
apply_prefix_settings() {
  local marker="$PREFIX/.bfme-settings-v$SETTINGS_VERSION"
  [ -f "$marker" ] && return
  say "Applying prefix settings."
  : >"$LOGS/prefix-settings.log"
  local dll

  # Use the games' own Microsoft C++ runtime. The runner's copy rounds numbers slightly differently,
  # so Linux and Windows players drift apart and the match ends in "Out of Sync".
  for dll in mfc71 msvcp71 msvcr71 dinput8; do
    reg_add 'HKCU\Software\Wine\DllOverrides' "$dll" REG_SZ 'native,builtin'
  done

  # Without this the launcher does not repaint a tab after you leave the Multiplayer tab.
  reg_add 'HKCU\Software\Microsoft\Avalon.Graphics' DisableHWAcceleration REG_DWORD 1

  if [ "$RUNNER" = "proton" ]; then
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
    reg_add 'HKCU\Control Panel\Desktop' LogPixels REG_DWORD 96
  fi

  : >"$marker"
}

# One setup at a time, so two never write the same files. start_app releases the lock before an app starts.
# The lock is fd 9. Programs started here must close it (9>&-), or a download left by a killed script keeps the lock.
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

# Ends every program in the Wine session. The runner waits for the whole session, not just its program.
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

# install_launcher leaves .bfme-launcher-installing behind until it finishes, so a half-copied file is not taken for a launcher.
launcher_installed() {
  [ -f "$LAUNCHER_EXE" ] && [ ! -e "$PREFIX/.bfme-launcher-installing" ]
}

install_launcher() {
  ensure_prefix
  launcher_installed && return
  local setup="$DOWNLOADS/AllInOneLauncherSetup.exe"
  [ -f "$setup" ] || download "$LAUNCHER_SETUP_URL" "$setup"
  say "Installing the launcher. It may open for a moment; the setup closes it again."
  # A leftover half-copied file would look finished to wait_for_stable_file.
  rm -f "$LAUNCHER_EXE"
  : >"$PREFIX/.bfme-launcher-installing"
  # The first start of the setup must not use runinprefix.
  # 9>&- because a function run with & copies this shell and would hold the lock.
  run_in_runner create "$setup" >"$LOGS/launcher-setup.log" 2>&1 9>&- &
  local setup_pid=$! installed=0
  # The setup starts the launcher, and Proton does not return until every program in the session ends.
  # Wait for the installed file to appear and stop growing, then end the session.
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

arena_installed() {
  [ -f "$ARENA_EXE" ]
}

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

# ModDB only lets a browser download the installer, so the player gives us the zip's path.

aotr_installed() {
  [ -f "$AOTR_EXE" ] && [ ! -e "$PREFIX/.bfme-aotr-installing" ]
}

dir_bytes() {
  # du exits non-zero when a file vanishes mid-count (the installer deletes temp files) but still prints a size.
  # Take the first number and ignore the exit status.
  local n
  n="$(du -sb "$1" 2>/dev/null | awk 'NR == 1 {print $1}' || true)"
  case "$n" in ""|*[!0-9]*) n=0 ;; esac
  printf '%s' "$n"
}

# Print PROGRESS while process $1 runs. $2 prints the percent done (or nothing). Capped at 99: only the process ending means done.
# A cancel request stops the process; $3 cleans up after it.
watch_progress() {
  local pid="$1" measure="$2" stop="${3:-}" pct last=-1
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$CANCEL_REQUESTED" = "1" ]; then
      kill "$pid" 2>/dev/null || true
      [ -n "$stop" ] && $stop
      wait "$pid" 2>/dev/null || true
      check_cancel
    fi
    pct="$($measure)" || pct=""
    case "$pct" in
      ""|*[!0-9]*) ;;
      *)
        [ "$pct" -gt 99 ] && pct=99
        if [ "$pct" != "$last" ]; then machine PROGRESS "$pct"; last="$pct"; fi ;;
    esac
    sleep 2 9>&-
  done
}

aotr_unpack_percent() {
  [ "$AOTR_UNPACKED_BYTES" -gt 0 ] || return 0
  echo $(( $(dir_bytes "$AOTR_UNPACK") * 100 / AOTR_UNPACKED_BYTES ))
}

# Percent of the installer's .bin files read. It reads them in order, so position in them is progress.
# Found by open files, matched by inode (same inside and outside the Wine container).
# Prints nothing when it cannot see them yet.
aotr_install_percent() {
  local -A start=()
  local total=0 best=-1 key size path fd pos line
  while IFS=' ' read -r key size; do
    start[$key]=$total
    total=$(( total + size ))
  done < <(find "$AOTR_UNPACK" -maxdepth 1 -type f -name '*-[0-9]*[a-z].bin' -printf '%f\n' 2>/dev/null \
    | sed -E 's/^(.*-)([0-9]+)([a-z])\.bin$/\2 \3 &/' | sort -k1,1n -k2,2 | cut -d' ' -f3- \
    | while IFS= read -r name; do stat -c '%d:%i %s' -- "$AOTR_UNPACK/$name"; done)
  [ "$total" -gt 0 ] || return 0
  while IFS=' ' read -r key path; do
    [ -n "${start[$key]+x}" ] || continue
    fd="${path#/proc/}"
    pos=""
    while IFS= read -r line; do
      case "$line" in pos:*) pos="${line#pos:}"; pos="${pos//[[:space:]]/}"; break ;; esac
    done 2>/dev/null <"/proc/${fd%%/*}/fdinfo/${fd##*/}" || continue
    [ -n "$pos" ] || continue
    if [ $(( start[$key] + pos )) -gt "$best" ]; then best=$(( start[$key] + pos )); fi
  done < <(stat -L -c '%d:%i %n' /proc/[0-9]*/fd/* 2>/dev/null)
  [ "$best" -ge 0 ] || return 0
  pos=$(( best * 100 / total ))
  echo $(( pos > 100 ? 100 : pos ))
}

# The download is a ZIP64 archive (~14 GB, Deflate64). The Flatpak runtime's unzip and bsdtar cannot open it, so 7-Zip lists and unpacks it.
# Prints "<size>\t<name>" per entry. Fails on an incomplete zip (an unfinished browser download has no directory).
aotr_zip_entries() {
  local sevenzip="$1" zip="$2" out
  out="$("$sevenzip" l -slt -ba -- "$zip" 2>/dev/null)" || return 1
  printf '%s\n' "$out" | awk '
    /^Path = /   { if (path != "") print size "\t" path; path = substr($0, 8); size = 0 }
    /^Size = /   { size = substr($0, 8) + 0 }
    END          { if (path != "") print size "\t" path }'
}

# Not called as $(...): a die there would lose its status line.
AOTR_EXE_NAME=""
AOTR_UNPACKED_BYTES=0
aotr_check_zip() {
  local zip="$1" listing names parts sevenzip
  [ -f "$zip" ] || die "The file '$zip' was not found."
  case "$(basename "$zip")" in
    *.part|*.crdownload|*.download) die "This download is not finished yet. Wait until your browser has finished, then choose the file again." ;;
    AotR_Standalone_*_Installer.zip) ;;
    *) die "This is not the Age of the Ring installer. Choose the file named like AotR_Standalone_9.3.0_Installer.zip." ;;
  esac
  sevenzip="$(aotr_sevenzip)" || die "$AOTR_NEED_7ZIP"
  listing="$(aotr_zip_entries "$sevenzip" "$zip")" \
    || die "This file is incomplete or damaged. Download it again from ModDB."
  names="$(printf '%s\n' "$listing" | cut -f2-)"
  AOTR_EXE_NAME="$(printf '%s\n' "$names" | grep -E '^AotR_Standalone_[^/]*_Installer\.exe$' | head -n 1 || true)"
  [ -n "$AOTR_EXE_NAME" ] || die "The installer program is missing from this file. Download it again from ModDB."
  parts="$(printf '%s\n' "$names" | grep -c -E "^${AOTR_EXE_NAME%.exe}-[0-9]+[a-z]\.bin$" || true)"
  [ "$parts" -gt 0 ] || die "The installer's data files are missing from this file. Download it again from ModDB."
  AOTR_UNPACKED_BYTES="$(printf '%s\n' "$listing" | awk -F'\t' '{s += $1} END {printf "%d", s}')"
}

aotr_check_space() {
  local need free
  need=$(( AOTR_UNPACKED_BYTES + AOTR_UNPACKED_BYTES * AOTR_INSTALL_RATIO_PERCENT / 100 - $(dir_bytes "$AOTR_UNPACK") - $(dir_bytes "$AOTR_DIR") ))
  mkdir -p "$BASE"
  free="$(df -PB1 "$BASE" | awk 'NR == 2 {print $4}')"
  if [ -n "$free" ] && [ "$need" -gt "$free" ]; then
    die "Not enough free space: Age of the Ring needs $(( need / 1000000000 + 1 )) GB more, but only $(( free / 1000000000 )) GB is free."
  fi
}

readonly AOTR_NEED_7ZIP="7-Zip is needed to read the download. Install it (Debian/Ubuntu: p7zip-full, Fedora: 7zip, Arch: 7zip) and try again."

aotr_sevenzip() {
  local c
  for c in 7zz 7z 7za; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
  done
  return 1
}

# A finished unpack leaves .complete, so a resumed install skips it.
aotr_unpack() {
  local zip="$1" pid rc=0 sevenzip
  if [ -f "$AOTR_UNPACK/.complete" ] && [ "$(cat "$AOTR_UNPACK/.complete")" = "$(basename "$zip")" ]; then return 0; fi
  sevenzip="$(aotr_sevenzip)" || die "$AOTR_NEED_7ZIP"
  rm -rf -- "$AOTR_UNPACK"
  mkdir -p "$AOTR_UNPACK"
  # 7-Zip checks every file's CRC, so a damaged download fails here, not in the installer.
  "$sevenzip" x -y -bd -bso0 -bsp0 -o"$AOTR_UNPACK" "$zip" >"$LOGS/aotr-unpack.log" 2>&1 9>&- &
  pid=$!
  watch_progress "$pid" aotr_unpack_percent
  wait "$pid" || rc=$?
  [ "$rc" -eq 0 ] || die "The file could not be unpacked. It may be damaged: download it again from ModDB. See $LOGS/aotr-unpack.log"
  basename "$zip" >"$AOTR_UNPACK/.complete"
  machine PROGRESS 100
}

aotr_run_installer() {
  local exe="$1" pid rc=0
  : >"$PREFIX/.bfme-aotr-installing"
  (cd "$AOTR_UNPACK" && run_in_runner inprefix "./$exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART '/LOG=C:\aotr-install.log') \
    >"$LOGS/aotr-install.log" 2>&1 9>&- &
  pid=$!
  watch_progress "$pid" aotr_install_percent stop_wine_session
  wait "$pid" || rc=$?
  if [ -f "$PREFIX/drive_c/aotr-install.log" ]; then
    mv -f "$PREFIX/drive_c/aotr-install.log" "$LOGS/aotr-installer.log"
  fi
  if [ "$rc" -ne 0 ] || [ ! -f "$AOTR_EXE" ]; then
    die "Age of the Ring was not installed (exit $rc). See $LOGS/aotr-installer.log"
  fi
  rm -f "$PREFIX/.bfme-aotr-installing"
  machine PROGRESS 100
}

cmd_aotr_install() {
  local zip="${1:-}"
  [ -n "$zip" ] || die "Use: aotr-install <path to AotR_Standalone_..._Installer.zip>. Download it from $AOTR_PAGE_URL"
  prefix_ready || die "Set up the game environment first. Run: prepare"
  acquire_setup_lock
  mkdir -p "$LOGS"
  step_start aotr-check
  aotr_check_zip "$zip"
  aotr_check_space
  ensure_runner
  prepare_prefix
  step_done aotr-check
  step_start aotr-unpack
  aotr_unpack "$zip"
  step_done aotr-unpack
  step_start aotr-install
  aotr_run_installer "$AOTR_EXE_NAME"
  step_done aotr-install
  step_start aotr-settings
  rm -rf -- "$AOTR_UNPACK"
  step_done aotr-settings
  cmd_shortcuts || true
  report_status
  machine DONE
  say ""
  say "Age of the Ring is installed. You can delete $(basename "$zip") now."
}

cmd_aotr() {
  aotr_installed || die "Age of the Ring is not installed. Run: aotr-install <zip>"
  ensure_prefix
  start_app "aotr" "$AOTR_DIR" "$AOTR_EXE"
}

cmd_game() {
  local dir exe
  case "${1:-}" in
    bfme1) dir=BFME1; exe=lotrbfme.exe ;;
    bfme2) dir=BFME2; exe=lotrbfme2.exe ;;
    rotwk) dir=RotWK; exe=lotrbfme2ep1.exe ;;
    *) die "Use: game bfme1|bfme2|rotwk" ;;
  esac
  # A game can only exist in a prefix that is already set up, so build nothing here.
  prefix_ready || die "Nothing is set up yet. Run: install"
  ensure_prefix   # applies newer prefix settings
  [ -d "$PREFIX/drive_c/$dir" ] || die "$dir is not installed. Install it in the Launcher first."
  start_app "$dir" "$PREFIX/drive_c/$dir" "$PREFIX/drive_c/$dir/$exe"
}

start_app() {
  local name="$1" dir="$2" exe="$3"
  release_setup_lock
  mkdir -p "$LOGS"
  local log
  log="$LOGS/$name-$(date +%Y%m%d-%H%M%S).log"
  say "Starting $name. Log: $log"
  cd "$dir"
  run_in_runner inprefix "$exe" >"$log" 2>&1 || true
  # shellcheck disable=SC2012
  ls -1t "$LOGS/$name-"*.log 2>/dev/null | tail -n +11 | while IFS= read -r old; do rm -f "$old"; done
}

# Inside the Flatpak the shortcuts run the app (`flatpak run`) and go in the host's menu folder.
# The Flatpak exports no entry of its own: one for an uninstalled program would lead nowhere.

readonly RELEASE_FLATPAK_ID="com.jgbmichalski.BfmeInstaller"
readonly SHORTCUT_PROGRAMS=(launcher arena aotr)

program_installed() {
  case "$1" in
    launcher) launcher_installed ;;
    arena)    arena_installed ;;
    aotr)     aotr_installed ;;
    *)        return 1 ;;
  esac
}

shortcut_name() {
  case "$1" in
    launcher) printf 'BFME All-in-One Launcher' ;;
    arena)    printf 'BFME Online Arena' ;;
    aotr)     printf 'Age of the Ring' ;;
  esac
}

shortcut_comment() {
  case "$1" in
    launcher) printf 'Install, mod and manage the Battle for Middle-earth games' ;;
    arena)    printf 'Play Battle for Middle-earth online' ;;
    aotr)     printf 'Play the Age of the Ring mod for Battle for Middle-earth 2' ;;
  esac
}

# The Flatpak's shortcuts keep the names of the entries the app used to export, so panel pins still work.
shortcut_file() {
  if [ "$IN_FLATPAK" != "1" ]; then printf 'bfme-%s.desktop' "$1"; return 0; fi
  case "$1" in
    launcher) printf '%s.Launcher.desktop' "$FLATPAK_ID" ;;
    arena)    printf '%s.Arena.desktop' "$FLATPAK_ID" ;;
    aotr)     printf '%s.Aotr.desktop' "$FLATPAK_ID" ;;
  esac
}

# The wrapper Flatpak exports for this app. It makes the right TryExec: a desktop hides a shortcut whose TryExec is gone.
# BFME_FLATPAK_INFO and BFME_MOUNTINFO exist only so tests can stand in for a sandbox.
flatpak_wrapper() {
  local info="${BFME_FLATPAK_INFO:-/.flatpak-info}" app_path
  [ -r "$info" ] || return 0
  app_path="$(awk '/^original-app-path=/ {orig = substr($0, 19)} /^app-path=/ {app = substr($0, 10)} END {print (orig != "" ? orig : app)}' "$info")"
  case "$app_path" in
    *"app/$FLATPAK_ID/"*) printf '%sexports/bin/%s' "${app_path%%app/"$FLATPAK_ID"/*}" "$FLATPAK_ID" ;;
  esac
}

# Whether the host's menu folder is really shared into the sandbox. Without the permission (a `flatpak override`, Flatseal)
# writes land in sandbox scratch space and never reach the menu. A shared folder has its own mount or sits under a bigger share;
# an unshared one sits under `/` only. Resolve the path first: the list has real paths and /home links to /var/home on some systems.
menu_folder_reachable() {
  [ "$IN_FLATPAK" = "1" ] || return 0
  local real
  real="$(realpath -m -- "$APPS_DIR" 2>/dev/null)" || real="$APPS_DIR"
  awk -v dir="$real" '{
    mount_point = $5; gsub(/\\040/, " ", mount_point)   # a space in a path is written \040
    if (mount_point != "/" && (mount_point == dir || index(dir, mount_point "/") == 1)) found = 1
  } END { exit !found }' "${BFME_MOUNTINFO:-/proc/self/mountinfo}"
}

self_path() {
  local src="${BASH_SOURCE[0]}"
  [ -n "$src" ] || die "Cannot work out where this script is."
  (cd "$(dirname "$src")" && printf '%s/%s' "$(pwd)" "$(basename "$src")")
}

shortcut_text() {
  local program="$1" name comment wrapper
  name="$(shortcut_name "$program")"
  comment="$(shortcut_comment "$program")"
  if [ "$IN_FLATPAK" = "1" ]; then
    # A copy built under another app ID (dev/install-local.sh) says so, so it can sit beside the release.
    [ "$FLATPAK_ID" = "$RELEASE_FLATPAK_ID" ] || name="$name (Dev)"
    wrapper="$(flatpak_wrapper)"
    printf '%s\n' '[Desktop Entry]' 'Type=Application' "Name=$name" "Comment=$comment" \
      "Exec=flatpak run --command=bfme-installer $FLATPAK_ID --open $program"
    [ -z "$wrapper" ] || printf '%s\n' "TryExec=$wrapper"
    printf '%s\n' "Icon=$FLATPAK_ID" 'Terminal=false' 'Categories=Game;' 'StartupNotify=true' "X-Flatpak=$FLATPAK_ID"
  else
    cat <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec=env BFME_HOME="$BASE" BFME_RUNNER="$RUNNER" "$BIN/bfme-linux-setup.sh" $program
Icon=applications-games
Terminal=false
Categories=Game;
StartupNotify=true
EOF
  fi
}

# Leave a correct shortcut alone, so the desktop does not rebuild its menu on every wizard start.
sync_shortcut() {
  local program="$1" file text
  file="$APPS_DIR/$(shortcut_file "$program")"
  if ! program_installed "$program"; then
    rm -f "$file" || return 1
    return 0
  fi
  text="$(shortcut_text "$program")"
  if [ -f "$file" ] && [ "$(cat "$file")" = "$text" ]; then return 0; fi
  mkdir -p "$APPS_DIR" || return 1
  if ! { printf '%s\n' "$text" >"$file.new" && mv -f "$file.new" "$file"; }; then
    rm -f "$file.new"
    return 1
  fi
}

cmd_shortcuts() {
  local program any=0 failed=0
  for program in "${SHORTCUT_PROGRAMS[@]}"; do
    if program_installed "$program"; then any=1; fi
  done
  # With nothing installed, create nothing (a first start leaves no folders). Leftover entries are still removed below.
  if [ "$any" = "1" ]; then
    if [ "$IN_FLATPAK" = "1" ]; then
      if ! menu_folder_reachable; then
        warn "This app cannot reach your menu folder ($APPS_DIR), so there are no shortcuts. To give it access: flatpak override --user --filesystem=xdg-data/applications:create $FLATPAK_ID"
        return 1
      fi
    else
      # The shortcuts run this script, so a copy of it must stay where they point.
      local me
      mkdir -p "$BIN"
      me="$(self_path)"
      if [ "$me" != "$BIN/bfme-linux-setup.sh" ]; then cp -f "$me" "$BIN/bfme-linux-setup.sh"; fi
      chmod +x "$BIN/bfme-linux-setup.sh"
    fi
  fi
  for program in "${SHORTCUT_PROGRAMS[@]}"; do
    sync_shortcut "$program" || failed=1
  done
  if [ "$failed" = "1" ]; then
    warn "Could not update the shortcuts in $APPS_DIR."
    return 1
  fi
  if [ "$IN_FLATPAK" != "1" ] && [ "$any" = "1" ] && command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  fi
  say "Shortcuts are up to date in $APPS_DIR"
}

# Each job reports its steps as status lines and ends with DONE. Rerunning skips what is done.
#   prepare           steps: doctor, runner, prefix            (the game environment)
#   launcher-install  steps: launcher, arena, shortcuts        (the Launcher and the Arena)
#   aotr-install      steps: aotr-check, aotr-unpack, aotr-install, aotr-settings
#   install           prepare, then launcher-install           (what the terminal setup does)

prepare_environment() {
  step_start doctor
  cmd_doctor || die "Fix the problems above, then run $1 again."
  step_done doctor
  say ""
  acquire_setup_lock
  step_start runner
  ensure_runner
  step_done runner
  step_start prefix
  prepare_prefix
  step_done prefix
}

install_launcher_and_arena() {
  acquire_setup_lock
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
  step_start shortcuts
  cmd_shortcuts || true   # the programs are installed whatever happens here, and cmd_shortcuts says what went wrong
  step_done shortcuts
}

cmd_prepare() {
  prepare_environment prepare
  report_status
  machine DONE
  say ""
  say "The game environment is ready. Install a program into it: launcher-install or aotr-install <zip>."
}

cmd_launcher_install() {
  prefix_ready || die "Set up the game environment first. Run: prepare"
  install_launcher_and_arena
  report_status
  machine DONE
  say ""
  say "Done. Start 'BFME All-in-One Launcher' to install the games, and 'BFME Online Arena' to play online."
  say "Do not switch patches in the launcher after a game is installed. On Wine this once broke the BFME 2 files."
}

cmd_install() {
  prepare_environment install
  install_launcher_and_arena
  report_status
  machine DONE
  say ""
  say "Done. Start 'BFME All-in-One Launcher' to install the games, and 'BFME Online Arena' to play online."
  say "Do not switch patches in the launcher after a game is installed. On Wine this once broke the BFME 2 files."
}

report_status() {
  [ "$MACHINE" = "1" ] || return 0
  # Complete means the game environment is ready and at least one program is installed.
  local p="missing" l="missing" a="missing" o="missing" done_all="no"
  prefix_ready && p="ready"
  launcher_installed && l="installed"
  arena_installed && a="installed"
  aotr_installed && o="installed"
  if [ "$p" = "ready" ] && { [ "$l" = "installed" ] || [ "$a" = "installed" ] || [ "$o" = "installed" ]; }; then done_all="yes"; fi
  machine STATUS runner "$RUNNER"
  machine STATUS prefix "$p"
  machine STATUS launcher "$l"
  machine STATUS arena "$a"
  machine STATUS aotr "$o"
  local game
  for game in bfme1:BFME1/lotrbfme.exe bfme2:BFME2/lotrbfme2.exe rotwk:RotWK/lotrbfme2ep1.exe; do
    if [ -f "$PREFIX/drive_c/${game#*:}" ]; then machine STATUS "${game%%:*}" installed; else machine STATUS "${game%%:*}" missing; fi
  done
  machine STATUS complete "$done_all"
}

cmd_status() {
  say "Runner:     $RUNNER$([ "$RUNNER" = proton ] && printf ' (%s)' "$PROTONPATH_VALUE")"
  say "Data dir:   $BASE"
  say "Prefix:     $PREFIX $(prefix_ready && echo '(ready)' || echo '(not created)')"
  say "Launcher:   $(launcher_installed && echo installed || echo 'not installed')"
  say "Arena:      $(arena_installed && echo installed || echo 'not installed')"
  say "Age of the Ring: $(aotr_installed && echo installed || echo 'not installed')"
  local g
  for g in BFME1 BFME2 RotWK; do
    say "$(printf '%-11s' "$g:") $([ -d "$PREFIX/drive_c/$g" ] && echo 'folder present' || echo 'not installed')"
  done
  report_status
}

cmd_reset_prefix() {
  [ "${1:-}" = "--yes" ] || die "This deletes the prefix at $PREFIX, including any installed games. Run 'reset-prefix --yes' to confirm."
  case "$PREFIX" in
    ""|"/"|"$HOME") die "Refusing to delete '$PREFIX'." ;;
  esac
  acquire_setup_lock
  # End the Wine session first: a running program would lose its files, and Wine would write its registry back afterwards.
  if [ "$RUNNER" = "proton" ] && [ "$PROTONPATH_VALUE" = "$DEFAULT_PROTONPATH" ] && [ -d "$BASE/proton/$DEFAULT_PROTONPATH" ]; then
    PROTONPATH_VALUE="$BASE/proton/$DEFAULT_PROTONPATH"
  fi
  if [ -d "$PREFIX" ]; then stop_wine_session || true; fi
  rm -rf -- "$PREFIX"
  cmd_shortcuts || true
  say "Prefix deleted."
}

cmd_help() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

main() {
  if [ "${1:-}" = "--machine" ]; then MACHINE=1; shift; fi
  local cmd="${1:-help}"
  if [ $# -gt 0 ]; then shift; fi
  case "$cmd" in
    doctor)            cmd_doctor ;;
    prepare)           cmd_prepare ;;
    launcher-install)  cmd_launcher_install ;;
    install)           cmd_install ;;
    launcher)          cmd_launcher ;;
    arena)             cmd_arena ;;
    game)              cmd_game "$@" ;;
    aotr-install)      cmd_aotr_install "$@" ;;
    aotr)              cmd_aotr ;;
    shortcuts)         cmd_shortcuts ;;
    status)            cmd_status ;;
    reset-prefix)      cmd_reset_prefix "$@" ;;
    help|-h|--help)    cmd_help ;;
    version|--version) say "$SCRIPT_VERSION" ;;
    *)                 die "Unknown command '$cmd'. Run with 'help'." ;;
  esac
}

main "$@"
