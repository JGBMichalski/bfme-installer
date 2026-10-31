# Setup wizard

`wizard/` is the app: a GTK4/libadwaita window (Python) over the setup in `bfme_wizard/engine/`. It runs inside the Flatpak
and needs a display.

## Screens

1. **Checking your setup**: what is installed.
2. **Start page**: choose what to install. The **AIO Launcher** comes with the Arena; **Age of the Ring** needs neither.
   After a stop it offers **Resume**.
3. **Running**: step *n* of *N* for the whole plan, with progress. **Cancel** stops after the current step, or at once
   during a download or an install.
4. **Download Age of the Ring**: only when the app cannot download it itself. Says why, then offers **Open ModDB** and
   **Choose file...**.
5. **Your system needs a change**: a failed system check, with a fix to copy and **Recheck**.
6. **Something went wrong**: a failed step, with **Retry** and **Copy log**.
7. **Home screen**: a card with **Open** for each installed program.
8. **Programs**: install or remove a program or tool.

## The plan

| Chosen | Steps |
| --- | --- |
| AIO Launcher | Check your system, Get Proton, Create the game environment, Download the AIO Launcher, Download the Arena, Add menu shortcuts |
| Age of the Ring | The first three, then Download Age of the Ring, Check the download, Unpack the download, Install Age of the Ring, Finish up |

The first three are left out when the game environment is ready.

## Pages

- **Home screen:** the window stays open while programs run. A program that closes within 15 seconds gets a note pointing
  to Troubleshoot. A failed background system check shows a banner.
- **Programs:** **Install** on the AIO Launcher or the Arena installs both. **Remove** asks first, ends the Wine session,
  and deletes only that program and its shortcut. It is inactive while a program runs. **Workshop Studio** and **Mission
  Control** are under **Tools**, with **Open**; they have no card and no shortcut.
- **Troubleshoot** (lifebuoy, on every page): system checks; **Graphics**, with the **Vulkan**/**OpenGL** switch, the
  graphics card (only with two) and **Show FPS**; **Copy diagnostics** (can contain your home folder name); **Open logs
  folder**; **Open settings file** (`config.env`); and **Reset game environment**.
- **Shortcuts** run `bfme-installer --open aio-launcher|arena|aotr` and exist only while the program is installed. A
  shortcut whose program is ready opens it without the window.

## Updating

On start the app compares its version with the latest GitHub release. If newer, a banner offers **Update**, which asks
Flatpak's update portal to install it. Then **Restart** starts the new version and closes this one. If the update adds
permissions, the banner shows the `flatpak update` command instead. Development builds never check.

The first start after an update shows the changelog notes since the last version seen (kept in `last-version` in the
data folder), once. A first install and development builds show nothing.

## Code

| File | Job |
| --- | --- |
| `engine/` | The setup, without GTK. See [How it works](how-it-works.md). |
| `runner.py` | Runs one job at a time on a worker thread. |
| `controller.py` | Runs the plan: retry, resume, recheck, cancel, remove. |
| `model.py` | The setup's state and the plan. |
| `apps.py` | Opens programs and watches whether they still run. |
| `catalog.py` | The programs: names, pictures, what removing each deletes. |
| `diagnostics.py`, `updater.py` | Copy diagnostics; the release check and portal update. |
| `ui.py`, `start.py`, `home.py`, `programs.py`, `aotr.py`, `widgets.py` | The window and its pages (need GTK). |
| `__main__.py` | Entry point and `--open`. |

## Build, run and test

```
dev/install-local.sh --run      # build this checkout as a Flatpak with its own app ID and data, and start it
dev/uninstall-local.sh          # remove it and its data
cd wizard && python3 -m pytest  # needs PyGObject; page tests skip without GTK
```

The tests never touch the network: downloads come from a local test server, and Proton and the Wine server are faked.
The Age of the Ring tests use the real 7-Zip and skip without it.
