# Setup wizard

`wizard/` is a GTK4/libadwaita app (Python) that runs `scripts/bfme-linux-setup.sh --machine` and shows its progress. It is meant to run inside the Flatpak. Without a display it runs the terminal setup instead.

## Screens

1. **Checking your setup**: asks the script what is installed (`status`).
2. **Start page**: choose what to install. Nothing is ticked at first and **Install** stays inactive until something is.
   - **All-in-One Launcher** installs the Launcher and the Arena. The Arena only plays games the Launcher installs, so it is not a choice of its own.
   - **Age of the Ring** needs neither the Launcher nor the Arena.
   - After a stop the page reads **Setup paused** and offers **Resume**. Choosing something else starts a new plan.
3. **Running**: step *n* of *N* for the whole plan, and a progress bar. Cancel stops after the current step.
4. **Download Age of the Ring**: only when chosen. The setup waits here.
5. **Your system needs a change**: a failed system check, with a copyable fix and **Recheck**. A passing recheck continues the setup.
6. **Something went wrong**: a failed step, with **Retry** and **Copy log**.
7. **Home screen**: once the setup is complete, and the first screen when something is already installed.

## The plan

| Chosen | Steps |
| --- | --- |
| Launcher | Check your system, Get Proton, Create the game environment, Download the launcher, Download the Arena, Add menu shortcuts (6) |
| Age of the Ring | The first three above, then Download Age of the Ring, Check the download, Unpack the download, Install Age of the Ring, Finish up (8) |
| Both | All of the above (11) |

## Age of the Ring

The page shows the size (about 14 GB to download, 40 GB of free space), **Open ModDB** in the player's browser (ModDB's bot check blocks scripts), and **Choose file...**, which opens the file chooser in Downloads.

## Home screen

Cards for **Launcher**, **Arena** and **Age of the Ring**. Each shows **Open** or **Install**. **Install** on the Launcher or the Arena installs both. On Age of the Ring it goes to the download step. A line above the cards names the installed games, and is omitted when the Launcher is not installed. **Game folders** and **Troubleshoot** buttons sit below.

- The window stays open when a program starts. The card shows "Running" until it ends, and programs can run at once. A program that ends within 15 seconds gets a note pointing to Troubleshoot, because the script returns 0 either way.
- When the window opens with the setup complete, the system checks run in the background. A **failed** check (not a warning) shows a banner linking to Troubleshoot.
- Each installed program has a menu shortcut running `bfme-installer --open launcher|arena|aotr`. It exists only while the program is installed.

## Troubleshoot

Reachable from the home screen and from the header menu on every page, even while the setup runs.

- **System checks:** failures and warnings first, passing checks folded into one row. The firewall check is left out because the sandbox cannot see it.
- **Can't be checked from here:** the firewall and graphics drivers, with advice and a command to copy.
- **Copy diagnostics:** version, runner, setup state, check results, and the end of the latest logs. It can contain your home folder and user name.
- **Open logs folder**
- **Reset game environment:** deletes the game environment and every installed game after a confirmation, removes every shortcut, then shows the start page. Disabled while the setup or a program is running.

## Updating the app

On start the wizard reads the latest release tag from `github.com/.../releases/latest` and compares it with the installed version. If it is newer, a banner offers **Update**, hidden while a setup runs. Pressing it asks Flatpak's update portal (`org.freedesktop.portal.Flatpak`) to install from the app's own repository, keeping the signature check. The new version is used after a restart.

- The portal cannot say whether an update exists, so the release check is separate.
- If the release exists on GitHub but not yet on Pages, the banner says to try again later.
- The portal refuses updates that add permissions. The banner then shows `flatpak update --user com.jgbmichalski.BfmeInstaller` to copy.
- Development builds (version `dev`) and runs outside a Flatpak never check.

Closing the window during an install asks first. Stopping keeps what was done, and the next start offers Resume.

## Code

| File | Job |
| --- | --- |
| `bfme_wizard/protocol.py` | Parses the [status lines](status-lines.md). |
| `bfme_wizard/model.py` | Setup state and the plan. |
| `bfme_wizard/runner.py` | Starts the script, streams output, sends the cancel signal. |
| `bfme_wizard/controller.py` | Runs the plan one job at a time: retry, resume, recheck, cancel. |
| `bfme_wizard/updater.py` | Release check and portal update. |
| `bfme_wizard/apps.py` | Starts programs and watches whether they still run. |
| `bfme_wizard/diagnostics.py` | The diagnostics report and logs folder. |
| `bfme_wizard/start.py` | Start page. |
| `bfme_wizard/home.py` | Home screen, Game folders page, Troubleshoot page. |
| `bfme_wizard/aotr.py` | Age of the Ring download step. |
| `bfme_wizard/widgets.py` | Shared GTK helpers. |
| `bfme_wizard/ui.py` | The window. Renders the model and calls the controller. |
| `bfme_wizard/__main__.py` | Entry point, script lookup, no-display fallback. |

The pages and window (`ui.py`, `start.py`, `home.py`, `aotr.py`, `widgets.py`) need GTK. The rest runs without a display, and page tests skip themselves where GTK is missing. `tests/test_script.py` runs the real setup script against a fake `curl` and `umu-run`.

## Build a local copy

To test the whole app without a release, build it under a different app ID. It installs beside a release install with its own data, Proton download, and "(Dev)" shortcuts.

```
dev/install-local.sh --run      # build from this checkout, install, start (--run is optional)
dev/uninstall-local.sh          # remove it and its data
```

The 32-bit extensions are shared with the release app, so only a first-ever install needs `install-flatpak.sh`. Dev builds never show the update banner.

## Run and test

```
cd wizard
BFME_SETUP_SCRIPT=../scripts/bfme-linux-setup.sh python3 -m bfme_wizard    # needs PyGObject, GTK 4, libadwaita
python3 -m unittest discover -s tests -t .                                  # needs PyGObject
```

The script is found through `BFME_SETUP_SCRIPT`, then the `bfme-linux-setup` command, then `../scripts/`.

To avoid a real install, put a fake `curl` and `umu-run` first on `PATH`, set `BFME_UMU_RUN` to the fake, and set `BFME_HOME` and `XDG_DATA_HOME` away from your real setup.
