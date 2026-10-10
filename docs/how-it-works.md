# How it works

`scripts/bfme-linux-setup.sh` creates one shared Wine prefix and installs the launcher and Arena into it.

## What it sets up

- One shared prefix under `~/.local/share/bfme-installer` (change with `BFME_HOME`).
- Proton through `umu-launcher` (checksum-verified download), or your system Wine 10.0 plus winetricks (`BFME_RUNNER=wine`).
- The launcher and Arena in the same folders as on Windows (`AppData/Roaming/...` in the prefix). The script downloads and updates the Arena, with an MD5 check.
- Prefix settings, applied once per version:
  - `mfc71`, `msvcp71`, `msvcr71`, `dinput8` = `native,builtin`. This stops the multiplayer "Out of Sync" error between Linux and Windows players.
  - `DisableHWAcceleration = 1`, so the launcher repaints tabs correctly.
  - Proton: `d3d8`, `d3d9`, `d3d11`, `dxgi` = `native,builtin` (DXVK).
  - Wine: `corefonts`, `win10`, `dxvk`, `d3dx9`, a `dxvk.conf` (the game closes at map load without it), `LogPixels = 96`.

## Configuration

Set these in `<data dir>/config.env` or the environment.

| Variable | Purpose |
| --- | --- |
| `BFME_HOME` | Data directory |
| `BFME_RUNNER` | `proton` (default) or `wine` |
| `BFME_PROTONPATH` | Proton to use (default: a pinned UMU-Proton) |
| `BFME_ARENA_BRANCH` | Arena release branch |
| `BFME_NVIDIA` | `1` or `0` (default `0`) |
| `BFME_EXTRA_ENV` | Extra environment for the game |
| `BFME_UMU_RUN` | Path to `umu-run` |

## Notes

- Use one runner and one Wine version per prefix.
- Don't switch patches in the launcher once a game is installed. It once broke BFME 2 on Wine.
- x86_64 only.
- A firewall (`ufw`, `firewalld`) is reported by `doctor`. The script never changes it.
- The Arena draws outside the launcher frame when opened from the Multiplayer tab, so start it from its own shortcut.
