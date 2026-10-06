# Setup wizard

`wizard/` is the first-run window: a GTK4/libadwaita app (Python) that runs `scripts/bfme-linux-setup.sh --machine` and shows its progress. It is meant to run inside the Flatpak. Without a display (SSH, a text console) it runs the terminal setup instead.

## Screens

One thing on screen at a time:

1. **Checking your setup**: asks the script what is already installed (`status`).
2. **Set up BFME on Linux** (or **Setup paused**, with Resume): the Install button.
3. **Running**: step *n* of 6, a plain-language description and a progress bar. Cancel stops after the current step.
4. **Your system needs a change**: a failed system check. Shows each problem with a copyable command and a Recheck button. A passing recheck continues the install.
5. **Something went wrong**: a failed step, with Retry and Copy log.
6. **You're all set**: Open the Launcher, Open the Arena. Also the first screen when everything is already installed.

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
| `bfme_wizard/ui.py` | The window. Only renders the model and calls the controller. |
| `bfme_wizard/__main__.py` | Entry point, script lookup, no-display fallback. |

Only `ui.py` needs GTK. The rest is testable without a display.

## Run and test

```
cd wizard
BFME_SETUP_SCRIPT=../scripts/bfme-linux-setup.sh python3 -m bfme_wizard    # needs PyGObject, GTK 4 and libadwaita
python3 -m unittest discover -s tests -t .                                  # needs PyGObject only
```

The script is found through `BFME_SETUP_SCRIPT`, then the `bfme-linux-setup` command (the Flatpak), then `../scripts/` in a checkout.

To try the wizard without installing anything real, put a fake `curl` and `umu-run` first on `PATH` and point `BFME_UMU_RUN` at the fake; use `BFME_HOME` and `XDG_DATA_HOME` to keep it away from your real setup.
