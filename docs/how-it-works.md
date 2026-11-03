# How it works

The app sets up one shared Wine prefix (the game environment) and installs the programs you choose into it: the
AIO Launcher with the Arena, Age of the Ring, or both. It runs everything through Proton (`umu-launcher`) inside the
Flatpak.

## What it sets up

- **Data folder:** `~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer`, with the prefix, downloads, logs and
  `config.env`.
- **Proton:** a pinned UMU-Proton, downloaded once and checksum-verified.
- **AIO Launcher and Arena:** in the same folders as on Windows (`AppData/Roaming/...`). The Arena is updated when the
  server has a newer build (MD5 check).
- **Age of the Ring:** in `C:\AgeoftheRing`. The app downloads it from ModDB (about 19 GB, MD5 check) and deletes the zip
  once it is unpacked. If it cannot, you download it in your browser and choose the file.
- **Menu shortcuts:** one for each installed program, and none for the rest.
- **Prefix settings,** applied once per version:
  - `mfc71`, `msvcp71`, `msvcr71`, `dinput8` = `native,builtin`. Stops the multiplayer "Out of Sync" error between Linux
    and Windows players.
  - `DisableHWAcceleration = 1`, so the AIO Launcher repaints its tabs.
  - Vulkan (DXVK): `d3d8`, `d3d9`, `d3d10core`, `d3d11`, `dxgi` = `native,builtin`.
  - OpenGL (WineD3D): the same DLLs = `builtin`, plus `PROTON_USE_WINED3D=1` and `WINE_D3D_CONFIG=renderer=gl`.

## Configuration

Set these in `config.env` in the data folder. The file wins over the environment.

| Variable | Purpose |
| --- | --- |
| `BFME_GRAPHICS` | `vulkan` or `opengl`. Picked on the first setup; the Troubleshoot switch changes it. |
| `BFME_PROTONPATH` | Another Proton to use instead of the pinned one. |
| `BFME_GPU` | `auto`, `dedicated` or `integrated`: which card runs the games on a computer with two. |
| `BFME_EXTRA_ENV` | Extra environment for the programs. Troubleshoot's **Show FPS** adds or removes `DXVK_HUD=fps` here. |
| `BFME_KEEP_AOTR_DOWNLOAD` | `1` keeps the Age of the Ring zip after unpacking it. |
| `BFME_HOME` | Another data folder (for development). |

## Notes

- The first setup picks OpenGL if no graphics card supports Vulkan 1.3 (DXVK's minimum). A choice you made is never
  changed.
- DXVK's fix for slowdowns in BFME 2 and Rise of the Witch-king (`d3d9.cachedWriteOnlyBuffers`) is always on.
- Don't switch patches in the AIO Launcher once a game is installed. It once broke BFME 2 on Wine.
- Start the Arena from its own shortcut. Opened from the AIO Launcher's Multiplayer tab it draws outside the window.
- x86_64 only.

## Code

`wizard/bfme_wizard/engine/` is the setup, with no GTK. `jobs.py` holds the jobs: a `Job` base class (setup lock,
steps, errors, exit status) with one subclass per job, and `Engine`, the jobs the window runs (prepare, install,
remove, ...). `Proton` (`proton.py`) gets the pinned Proton and runs programs in the game environment through umu;
`GameEnvironment` (`prefix.py`) creates the Wine prefix, applies its registry and graphics settings, and deletes it.
They are built from `prefix.py`, `proton.py`, `programs/`, `moddb.py`, `shortcuts.py` and `doctor.py`.

`engine/programs/` has one class per program. The base class `Program` (`base.py`) holds what they share: where the
program is, whether it is installed, opening it with a log of its own, and removing it. Each subclass fills in its own
facts (names, install-page steps, shortcut) and overrides what it does differently, starting with `run_install`, the
steps of its install job: `AioLauncher` runs a setup,
`Arena` updates itself by checksum, `AgeOfTheRing` downloads, unpacks and runs an installer, and `Tool`
(`WorkshopStudio`, `MissionControl`) is a single download. `programs/__init__.py` lists them; everything else in the
wizard gets its programs from there.
The rest of `wizard/bfme_wizard/` is the window. See [the wizard](wizard.md).
