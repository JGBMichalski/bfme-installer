# Setup wizard

`wizard/` is a GTK4/libadwaita app (Python) that runs `scripts/bfme-linux-setup.sh --machine` and shows its progress. It is meant to run inside the Flatpak. Without a display it runs the terminal setup instead.

## Screens

1. **Checking your setup**: asks the script what is installed (`status`).
2. **Start page**: choose what to install. Nothing is ticked at first and **Install** stays inactive until something is.
   - **All-in-One Launcher**, the AIO Launcher for short, comes with the Arena. The Arena only plays games the AIO Launcher installs, so it is not a choice of its own.
   - **Age of the Ring** needs neither the AIO Launcher nor the Arena.
   - After a stop the page reads **Setup paused** and offers **Resume**. Choosing something else starts a new plan.
3. **Running**: step *n* of *N* for the whole plan, and a progress bar. Cancel stops after the current step.
4. **Download Age of the Ring**: only when chosen. The setup waits here.
5. **Your system needs a change**: a failed system check, with a copyable fix and **Recheck**. A passing recheck continues the setup.
6. **Something went wrong**: a failed step, with **Retry** and **Copy log**.
7. **Home screen**: once the setup is complete, and the first screen when something is already installed.
8. **Programs**: install a program that is missing or remove one that is installed. Reached from the home screen.

## The plan

| Chosen | Steps |
| --- | --- |
| AIO Launcher | Check your system, Get Proton, Create the game environment, Download the AIO Launcher, Download the Arena, Add menu shortcuts (6) |
| Age of the Ring | The first three above, then Download Age of the Ring, Check the download, Unpack the download, Install Age of the Ring, Finish up (8) |
| Both | All of the above (11) |

## Age of the Ring

The page shows the size (about 14 GB to download, 40 GB of free space), **Open ModDB** in the player's browser (ModDB's bot check blocks scripts), and **Choose file...**, which opens the file chooser in Downloads.

## Home screen

A card for each program that is **installed**, with its picture and an **Open** button, and nothing for the others. A line above the cards names the installed games, and is omitted when the AIO Launcher is not installed. Everything else is a button in the top right corner of the page, under the header bar. The buttons float over the page and not above it, so the page keeps all its room, and the cards keep clear of them: that is why the window cannot be made shorter than about 445 pixels.

| Icon | Tooltip | Opens | Where it shows |
| --- | --- | --- | --- |
| download arrow | Install or remove programs | Programs | Home screen only |
| folder | Game folders | Game folders | Home screen only |
| lifebuoy | Troubleshoot | Troubleshoot | Every page |

The lifebuoy is Troubleshoot's icon because it says "help when something goes wrong". A gear would read as Settings, and a warning sign would read as an alarm. The old three-dot menu is gone: it only held Troubleshoot. The icons are chosen from the ones the Flatpak's GNOME runtime has, and a test checks that.

- The window stays open when a program starts. The card shows "Running" until it ends, and programs can run at once. A program that ends within 15 seconds gets a note pointing to Troubleshoot, because the script returns 0 either way.
- When the window opens with the setup complete, the system checks run in the background. A **failed** check (not a warning) shows a banner linking to Troubleshoot.
- Each installed program has a shortcut running `bfme-installer --open launcher|arena|aotr`, with the program's own picture as its icon. It exists only while the program is installed.

## Programs

One row for each program, **AIO Launcher**, **Arena** and **Age of the Ring**, each with its picture. A row says whether the program is installed. It has **Install** when it is not and **Remove** when it is.

- **Install** goes back to the main page and runs the setup for that program. **Install** on the AIO Launcher or the Arena installs both, because the Arena only plays what the AIO Launcher installs, and the row says so. On Age of the Ring it ends at the download step.
- **Remove** asks first. The dialog says what is deleted and what is not touched, and defaults to **Cancel**. Confirming runs `bfme-linux-setup remove <program>`, which ends the Wine session, deletes the program's folder and its shortcut, and leaves the games, the other programs and the settings Age of the Ring keeps in the player's own folder. The window shows "Removing..." and cannot be closed or left meanwhile, then looks at the setup again and says "The AIO Launcher was removed." If it was the last program, the start page comes back with the game environment still ready.
- **Remove** is inactive while any program is running, because ending the Wine session closes them all, and the rows name what to close. Install is not affected.
- Both buttons are inactive while the script is busy, because it would ignore a click.

## Program pictures

The AIO Launcher, the Arena and Age of the Ring each have a picture: a PNG in `bfme_wizard/icons/` that ships with the wizard, so nothing is downloaded and it shows with no network. The pictures are not this project's: they belong to their owners.

- **In the window**, the home screen cards (64 px) and the Programs rows (40 px) draw each one as a circle with `Adw.Avatar`, so the square Age of the Ring picture sits well beside the two round ones. If a file is missing or damaged the circle shows the program's initials, never a broken image.
- **In the menu**, each shortcut uses its program's picture as its icon, unchanged. In the Flatpak, the manifest exports each one as an icon of the app, named `<app id>.Launcher`, `<app id>.Arena` and `<app id>.Aotr` (an icon, not a menu entry), and the shortcut's `Icon=` is that name, so the pictures go when the app is uninstalled. Without the Flatpak the script copies them to `<data dir>/icons` and the shortcuts point at the copies, so they keep working if the checkout moves.

## Troubleshoot

Reachable with the lifebuoy button in the top right corner of every page, even while the setup runs.

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
| `bfme_wizard/controller.py` | Runs the plan one job at a time: retry, resume, recheck, cancel. Removes programs. |
| `bfme_wizard/updater.py` | Release check and portal update. |
| `bfme_wizard/apps.py` | Starts programs and watches whether they still run. |
| `bfme_wizard/diagnostics.py` | The diagnostics report and logs folder. |
| `bfme_wizard/catalog.py` | The programs, with their names, pictures and what removing each deletes. |
| `bfme_wizard/icons/` | The programs' pictures, and where each came from. |
| `bfme_wizard/start.py` | Start page. |
| `bfme_wizard/home.py` | Home screen, Game folders page, Troubleshoot page. |
| `bfme_wizard/programs.py` | The Programs page. |
| `bfme_wizard/aotr.py` | Age of the Ring download step. |
| `bfme_wizard/widgets.py` | Shared GTK helpers. |
| `bfme_wizard/ui.py` | The window. Renders the model and calls the controller. |
| `bfme_wizard/__main__.py` | Entry point, script lookup, no-display fallback. |

The pages and window (`ui.py`, `start.py`, `home.py`, `programs.py`, `aotr.py`, `widgets.py`) need GTK. The rest runs without a display, and page tests skip themselves where GTK is missing. `tests/test_script.py` runs the real setup script against a fake `curl` and `umu-run`.

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
