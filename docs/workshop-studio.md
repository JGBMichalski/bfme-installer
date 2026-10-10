# Workshop Studio

Workshop Studio is integrated as a third Windows application in the BFME Installer Flatpak. It shares the same Proton prefix as the All-in-One Launcher and Online Arena, so it can work with the games installed by the Launcher.

## Source

The executable is downloaded from the BFME Foundation Project:

```text
https://arena-files.bfmeladder.com/downloads/WorkshopStudio.exe
```

The download is approximately 296 MB. It is not included in the Flatpak image and is fetched only the first time Workshop Studio is opened. From a terminal it asks before downloading; from the menu entry or the wizard it downloads without asking.

## Data And Prefix

The executable is kept at:

```text
~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer/downloads/WorkshopStudio.exe
```

It runs with the existing Proton prefix:

```text
~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer/prefix
```

The download is separate from the prefix. Removing the prefix through Troubleshoot removes installed games, but does not remove the Workshop Studio download.

## Opening It

The home screen has a **Workshop Studio** card. The application menu also has **BFME Workshop Studio**.

The command-line equivalent is:

```sh
flatpak run --user com.jgbmichalski.BfmeInstaller --open workshop
```

When the setup is incomplete, this command opens the wizard and highlights Workshop Studio after setup finishes.

## Implementation

- `scripts/bfme-linux-setup.sh` implements the `workshop` command, first-run download and shared-prefix launch.
- `wizard/bfme_wizard/apps.py` and `home.py` expose the third application in the wizard.
- `wizard/bfme_wizard/__main__.py` accepts `--open workshop` from the menu entry.
- `flatpak/com.jgbmichalski.BfmeInstaller.Workshop.desktop` provides the application-menu entry.
- The Flatpak manifest installs that desktop file and keeps the existing network and app-data permissions.

The download endpoint currently does not provide a published SHA-256 in the project repository, so the first-run download uses the HTTPS endpoint without a local checksum comparison.
