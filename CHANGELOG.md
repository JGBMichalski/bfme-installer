# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0]

### Added

- A home screen replaces the "You're all set" page: two cards for the Launcher and the Arena, a line showing which games are installed, and a Troubleshoot button. A card shows "Running" while its program is open, and a program that ends within 15 seconds gets a soft "closed after a few seconds" note.
- A Troubleshoot page, from the home screen and from the header menu on every page: the system checks (problems first, passing checks folded, with Check again), a "Can't be checked from here" section for the firewall and the graphics drivers, Copy diagnostics, Open logs folder, and Reset game environment behind a confirmation.
- A quiet system check when the window opens with the setup complete. A failed check shows a banner on the home screen with the fix one click away.
- `status` reports which games are installed (`STATUS bfme1`, `bfme2` and `rotwk`).

### Changed

- The wizard registers under the app ID Flatpak gives it, so a copy built under another ID runs beside the release app. `dev/install-local.sh` builds and installs such a copy from a checkout, and `dev/uninstall-local.sh` removes it.
- The Launcher and Arena menu entries start the app at once when the setup is complete, with no window, and open the wizard first when it is not (`bfme-installer --open launcher|arena`). Before, an unfinished setup ran silently from the menu entry for minutes.
- `reset-prefix` ends the Wine session before it deletes the prefix, so a running program is not deleted from under itself.

## [0.2.3]

### Added

- The wizard tells you when a newer release exists and can install it. A banner at the top of the window shows "Version x is available" with an Update button, and afterwards asks you to close and reopen the app. The update is installed by Flatpak's update portal from the repository the app came from, so the signature check applies, and it needs no extra permission. If the portal refuses (for example when a release asks for new permissions), the banner shows the `flatpak update` command to copy instead.

## [0.2.2]

### Changed

- The version now comes from the git tag alone. The release build stamps it into the setup script and the Flatpak metainfo, so a release no longer needs those edited by hand. The script reports `dev` when run from a checkout. The build fails early if the changelog has no section for the tag.

## [0.2.1]

### Fixed

- A setup that was stopped or killed no longer blocks the next one with "Another setup is already running". The download it had started kept running and held the setup lock. Programs the script starts, including its waiting loops, no longer inherit the lock.
- Every command that can change the setup now takes the lock, including `install` when the prefix already exists and `reset-prefix`. Before, a resumed install ran without it, so two could write the same downloads.
- The lock is released before the launcher, the Arena or a game starts. Before, a first start from a menu entry kept it for as long as the app stayed open, which blocked the wizard.
- A prefix or a launcher install that was interrupted is no longer mistaken for a finished one. Both now leave a marker until they complete, and an unfinished step is redone on the next run.
- Proton is unpacked into a temporary folder and renamed into place, so an interrupted extraction cannot leave a folder that looks complete but is missing files. A failed unpack stops with a clear message.
- A download that stalls now times out and retries (resuming where it left off) instead of hanging forever.
- Closing the wizard with "Stop and close" now ends everything the setup started, including the download and the Proton processes, not only the script.
- The "already running" message inside the Flatpak says how to clear a stuck setup (`flatpak kill`).

## [0.2.0]

### Added

- The Flatpak repository is signed. On a `v*` tag, the build imports the project key from the `FLATPAK_GPG_PRIVATE_KEY` secret and signs with the Flatpak builder action's `gpg-sign` input, then checks that a client with the project key accepts the result before anything is published.
- The public signing key (`flatpak/signing-key.gpg`) is built into the release copy of `install-flatpak.sh` and  into `bfme-installer.flatpakrepo`. The Pages site shows its fingerprint.

### Changed

- `install-flatpak.sh` verifies every download against the signing key. Running it again turns verification on for an install from an earlier release, which was added without it.
- `install-flatpak.sh` is simpler: it uses `flatpak install --or-update`, and stops with a message when the Pages repository cannot be reached.
- The Pages repository is the one the Flatpak build produces, with no separate import step.
- The release workflow uses Node 24 versions of its actions (`checkout`, `download-artifact`, `upload-artifact`, `configure-pages`, `upload-pages-artifact`, `deploy-pages` and `action-gh-release`), which removes the Node.js 20   deprecation warnings.

### Removed

- `install-flatpak.sh` no longer has `--bundle`, `--terminal`, `--repo`, `--gpg-key` or the `BFME_FLATPAK_*` environment overrides, and no longer falls back to the release bundle when the Pages repository cannot be reached. Flatpak 1.16 cannot check a bundle against a pinned key, so that fallback could not be verified. The bundle is still attached to each release and installs with `flatpak install`.

### Security

- Downloads are no longer accepted without a valid signature.

## [0.1.1] - 2026-10-05

### Fixed

- The launcher step no longer waits until you close the launcher window. The launcher's setup starts the launcher when it finishes, and Proton does not return until every program in the Wine session has ended. The script now waits for the installed launcher file, ends the Wine session, and carries on.

## [0.1.0] - 2026-10-05

### Added

- Setup script (`scripts/bfme-linux-setup.sh`) that sets up one shared Proton or Wine environment and runs the BFME All-in-One Launcher and Online Arena under it, with `doctor`, `install`, `launcher`, `arena`, `game`, `shortcuts`, `status` and `reset-prefix` commands.
- Flatpak (`com.jgbmichalski.BfmeInstaller`) on the GNOME 49 runtime, with three menu entries: BFME Installer, BFME All-in-One Launcher and BFME Online Arena.
- Setup wizard (GTK4/libadwaita) that checks the system, shows install progress, offers Retry and Resume, and shows copyable fix commands for problems only the system can fix. With no display it runs the terminal setup.
- Machine-readable status lines (`--machine`) that the wizard reads, documented in `docs/status-lines.md`.
- One-command install (`install-flatpak.sh`) that installs the 32-bit Flatpak extensions, installs the app from a Flatpak repository on GitHub Pages, falls back to the checksum-verified release bundle, and opens the wizard. Supports `--uninstall`, `--purge`, `--no-setup` and `--terminal`.
- GitHub Actions workflow that checks the scripts, tests the wizard, builds the Flatpak, and publishes the release and the Flatpak repository on `v*` tags.