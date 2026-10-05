# BFME Installer

Runs the BFME All-in-One Launcher and Online Arena on Linux under Proton (default) or Wine. No sudo, and it never installs system packages: `doctor` tells you what is missing.

## Install

Copy this into a terminal:

```
curl -fsSL https://github.com/JGBMichalski/bfme-installer/releases/latest/download/install-flatpak.sh | bash
```

It installs the app as a Flatpak, adds the 32-bit parts Flatpak needs, and opens a setup wizard that walks you through the rest. No `sudo`. If Flatpak is missing it tells you the command to install it. The script is short, so you can read it first: [flatpak/install-flatpak.sh](flatpak/install-flatpak.sh). Each release lists checksums in `SHA256SUMS`.

Run the same command again to update. To remove it, see [Flatpak](docs/flatpak.md#options).

## Without Flatpak

Run the setup script in a terminal. It does the same setup without the wizard.

```
./scripts/bfme-linux-setup.sh doctor     # check requirements
./scripts/bfme-linux-setup.sh install    # set up the runner, launcher, Arena and menu shortcuts
```

Then open **BFME All-in-One Launcher** from your menu and install the games. Start the Arena from its own **BFME Online Arena** shortcut, not from the launcher's Multiplayer tab.

Other commands: `launcher`, `arena`, `game bfme1|bfme2|rotwk`, `shortcuts`, `status`, `reset-prefix --yes`, `help`.

## Docs

- [How it works](docs/how-it-works.md): what gets set up, configuration, notes.
- [Flatpak](docs/flatpak.md): the install script, its options, building, and publishing updates.
- [Setup wizard](docs/wizard.md): the first-run window.
- [Status lines](docs/status-lines.md): how the wizard reads the script's progress.
