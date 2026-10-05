# BFME Installer

Runs the BFME All-in-One Launcher and Online Arena on Linux under Proton (default) or Wine. No sudo, and it never installs system packages: `doctor` tells you what is missing.

## Quick start

```
./scripts/bfme-linux-setup.sh doctor     # check requirements
./scripts/bfme-linux-setup.sh install    # set up the runner, launcher, Arena and menu shortcuts
```

Then open **BFME All-in-One Launcher** from your menu and install the games. Start the Arena from its own **BFME Online Arena** shortcut, not from the launcher's Multiplayer tab.

Other commands: `launcher`, `arena`, `game bfme1|bfme2|rotwk`, `shortcuts`, `status`, `reset-prefix --yes`, `help`.

## Docs

- [How it works](docs/how-it-works.md): what gets set up, configuration, notes.
- [Flatpak](docs/flatpak.md): building, installing, and publishing updates.
