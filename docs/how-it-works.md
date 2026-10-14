# How it works

`scripts/bfme-linux-setup.sh` creates one shared Wine prefix and installs the programs you choose into it: the AIO Launcher and Arena, Age of the Ring, or both. Preparing the prefix is its own job (`prepare`), so no program needs the others.

## What it sets up

- A prefix under `~/.local/share/bfme-installer` (change with `BFME_HOME`).
- Proton through `umu-launcher` (checksum-verified), or system Wine 10.0 plus winetricks (`BFME_RUNNER=wine`).
- The AIO Launcher and Arena, in the same folders as on Windows (`AppData/Roaming/...`). The script downloads and updates the Arena with an MD5 check.
- Age of the Ring in `C:\AgeoftheRing`, from the file you download from ModDB.
- A menu shortcut for each installed program, and none for the rest.
- Prefix settings, applied once per version:
  - `mfc71`, `msvcp71`, `msvcr71`, `dinput8` = `native,builtin`, which stops the multiplayer "Out of Sync" error between Linux and Windows players.
  - `DisableHWAcceleration = 1`, so the AIO Launcher repaints tabs.
  - Proton: `d3d8`, `d3d9`, `d3d11`, `dxgi` = `native,builtin` (DXVK).
  - Wine: `corefonts`, `win10`, `dxvk`, `d3dx9`, `LogPixels = 96`, and a `dxvk.conf` (the game closes at map load without it).

## Configuration

Set these in `<data dir>/config.env` or the environment.

| Variable | Purpose |
| --- | --- |
| `BFME_HOME` | Data directory |
| `BFME_RUNNER` | `proton` (default) or `wine` |
| `BFME_PROTONPATH` | Proton to use (default: a pinned UMU-Proton) |
| `BFME_ARENA_BRANCH` | Arena release branch |
| `BFME_NVIDIA` | `auto`, `1` or `0` |
| `BFME_EXTRA_ENV` | Extra environment for the game |
| `BFME_UMU_RUN` | Path to `umu-run` |

## Notes

- Use one runner and one Wine version per prefix.
- Don't switch patches in the AIO Launcher once a game is installed. It once broke BFME 2 on Wine.
- x86_64 only.
- `doctor` reports a firewall (`ufw`, `firewalld`). The script never changes it.
- Start the Arena from its own shortcut. Opened from the Multiplayer tab it draws outside the AIO Launcher frame.
