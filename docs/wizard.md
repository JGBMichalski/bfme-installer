# Setup wizard

`wizard/` is the first-run window: a GTK4/libadwaita app (Python) that runs `scripts/bfme-linux-setup.sh --machine` and shows its progress. It is meant to run inside the Flatpak. Without a display (SSH, a text console) it runs the terminal setup instead.

## Screens

One thing on screen at a time:

1. **Checking your setup**: asks the script what is already installed (`status`).
2. **Set up BFME on Linux** (or **Setup paused**, with Resume): the Install button.
3. **Running**: step *n* of 6, a plain-language description and a progress bar. Cancel stops after the current step.
4. **Your system needs a change**: a failed system check. Shows each problem with a copyable command and a Recheck button. A passing recheck continues the install.
5. **Something went wrong**: a failed step, with Retry and Copy log.
6. **Home screen**: once the setup is complete, and the first screen when everything is already installed. See below.

## Home screen

Three cards, **Launcher**, **Arena** and **Workshop Studio**, each with an Open button, a line above them that says which games are installed (or "No games installed yet. Open the Launcher to install them."), and a **Troubleshoot** button with the version beside it.

- **Opening an app:** the window stays open. The card shows "Running" until the program ends, and all three apps can run at once. A program that ends within 15 seconds gets a soft note, "Closed after a few seconds. If it didn't open, see Troubleshoot.", because the script returns 0 whether or not the program worked.
- **Quiet check:** when the window opens with the setup complete, the system checks run in the background. If one **failed** (a warning does not count), a banner says "Your system needs a change" and links to Troubleshoot.
- **Menu entries:** the Launcher, Arena and Workshop Studio entries run `bfme-installer --open launcher|arena|workshop`. With the setup complete, the app starts at once with no window. With the setup incomplete, the wizard opens, and the offered app is highlighted when the setup finishes.

## Troubleshoot

A second page, reachable from the Troubleshoot button and from the header menu on every page, even while the setup runs.

- **System checks:** failures and warnings first, passing checks folded into one row, and **Check again**. The firewall check is left out, because it cannot be seen from the sandbox.
- **Can't be checked from here:** the firewall and the graphics drivers, with plain advice and a command to copy. This keeps a green list from reading as "everything is fine".
- **Copy diagnostics:** the version, runner, setup state, check results, and the end of the latest launcher, Arena and prefix-creation logs. It can contain your home folder and user name, so check it before you share it.
- **Open logs folder:** shows the logs in your file manager through the portal.
- **Reset game environment:** deletes the game environment, including every installed game, after a confirmation, then shows the setup again. It is disabled while the setup or a tracked app is running. The script ends the Wine session first, so a program started from a menu entry is not deleted from under itself.

## Updating the app

When the window opens, the wizard asks GitHub which release is the latest (`github.com/.../releases/latest`, which redirects to the tag) and compares it with the version stamped into the installed app. If the latest is newer, a banner offers **Update**. The banner stays hidden while a setup is running.

Pressing it asks Flatpak's update portal (`org.freedesktop.portal.Flatpak`) to install the update from the repository the app was installed from. The portal needs no extra permission and keeps the repository's signature check. The new version is used after the app is closed and reopened.

- The portal only installs; it cannot say whether an update exists, and its own notification polls every 30 minutes, so the release check is separate.
- If GitHub has the release but Pages does not have it yet, the banner says to try again in a few minutes.
- The portal refuses an update that adds permissions. The banner then shows `flatpak update --user com.jgbmichalski.BfmeInstaller` to copy.
- Development builds (version `dev`) and runs outside a Flatpak never check.

Closing the window during an install asks first. Stopping keeps what was done, and the next start offers Resume.

## Code

| File | Job |
| --- | --- |
| `bfme_wizard/protocol.py` | Parses the `@bfme` status lines ([status-lines.md](status-lines.md)). |
| `bfme_wizard/model.py` | The setup state, fed one line at a time. |
| `bfme_wizard/runner.py` | Starts the script, streams its output, sends the cancel signal. |
| `bfme_wizard/controller.py` | Connects the two: install, retry, recheck, cancel. |
| `bfme_wizard/updater.py` | Release check and the update through the Flatpak portal. |
| `bfme_wizard/apps.py` | Starts the Launcher and the Arena and watches whether they are still running. |
| `bfme_wizard/diagnostics.py` | The "Copy diagnostics" report and the logs folder. |
| `bfme_wizard/home.py` | The home screen and the Troubleshoot page. |
| `bfme_wizard/ui.py` | The window. Only renders the model and calls the controller. |
| `bfme_wizard/__main__.py` | Entry point, script lookup, no-display fallback. |

Only `ui.py` needs GTK. The rest is testable without a display.

## Build and install a local copy

To test the whole app (Flatpak, wizard, menu entries) without pushing a release, build it under a different app ID. It installs **beside** a release install: separate data (`~/.var/app/<id>`, so a separate setup and Proton download), separate menu entries (named "(Dev)"), and the release app is untouched.

```
dev/install-local.sh --run      # build from this checkout, install, start it (--run is optional)
dev/uninstall-local.sh          # remove it and its data
```

Rerun the first command after a change. It builds from a temporary copy, so the checkout is not modified. The 32-bit extensions are shared with the release app, so only a first-ever install needs `install-flatpak.sh`. The self-update banner never shows in a dev build, because its version is `dev`.

## Run and test

```
cd wizard
BFME_SETUP_SCRIPT=../scripts/bfme-linux-setup.sh python3 -m bfme_wizard    # needs PyGObject, GTK 4 and libadwaita
python3 -m unittest discover -s tests -t .                                  # needs PyGObject only
```

The script is found through `BFME_SETUP_SCRIPT`, then the `bfme-linux-setup` command (the Flatpak), then `../scripts/` in a checkout.

To try the wizard without installing anything real, put a fake `curl` and `umu-run` first on `PATH` and point `BFME_UMU_RUN` at the fake; use `BFME_HOME` and `XDG_DATA_HOME` to keep it away from your real setup.
