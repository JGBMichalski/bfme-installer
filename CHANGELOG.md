# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-10-05

### Fixed

- The launcher step no longer waits until you close the launcher window. The launcher's setup starts the
  launcher when it finishes, and Proton does not return until every program in the Wine session has ended.
  The script now waits for the installed launcher file, ends the Wine session, and carries on.

## [0.1.0] - 2026-10-05

### Added

- Setup script (`scripts/bfme-linux-setup.sh`) that sets up one shared Proton or Wine environment and runs the
  BFME All-in-One Launcher and Online Arena under it, with `doctor`, `install`, `launcher`, `arena`, `game`,
  `shortcuts`, `status` and `reset-prefix` commands.
- Flatpak (`com.jgbmichalski.BfmeInstaller`) on the GNOME 49 runtime, with three menu entries: BFME Installer,
  BFME All-in-One Launcher and BFME Online Arena.
- Setup wizard (GTK4/libadwaita) that checks the system, shows install progress, offers Retry and Resume, and
  shows copyable fix commands for problems only the system can fix. With no display it runs the terminal setup.
- Machine-readable status lines (`--machine`) that the wizard reads, documented in `docs/status-lines.md`.
- One-command install (`install-flatpak.sh`) that installs the 32-bit Flatpak extensions, installs the app from a
  Flatpak repository on GitHub Pages, falls back to the checksum-verified release bundle, and opens the wizard.
  Supports `--uninstall`, `--purge`, `--no-setup` and `--terminal`.
- GitHub Actions workflow that checks the scripts, tests the wizard, builds the Flatpak, and publishes the release
  and the Flatpak repository on `v*` tags.