# Flatpak

`flatpak/` packages the same script as a Flatpak (`com.jgbmichalski.BfmeInstaller`) with a setup wizard (see [wizard.md](wizard.md)) in front of it. It adds three menu entries: **BFME Installer** (the wizard, and the app's default command), **BFME All-in-One Launcher** and **BFME Online Arena**. Inside the sandbox the script uses Proton only. The graphics and 32-bit libraries come from the Flatpak runtime.

The app runs on the GNOME runtime (`org.gnome.Platform` 49), which provides GTK4, libadwaita and PyGObject for the wizard. It is based on freedesktop 25.08, so the 32-bit extensions below stay the same. The script is still available with `flatpak run --command=bfme-linux-setup com.jgbmichalski.BfmeInstaller <command>`.

## Build locally

Needs `flatpak`, `flatpak-builder`, and the Flathub remote for the runtimes.

```
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
cd flatpak
flatpak-builder --user --install --install-deps-from=flathub --force-clean build-dir com.jgbmichalski.BfmeInstaller.yml
```

## The install script

`flatpak/install-flatpak.sh` is what the one-line install in the README runs. The copy attached to each release has two things filled in: the Flatpak repository on GitHub Pages, and the project's public signing key. It:

1. Adds the Flathub remote, for the runtime and the extensions.
2. Installs the 32-bit extensions. These are required, and Flatpak does **not** install them for apps outside Flathub: not with `flatpak-builder`, not from a self-hosted repo, and not with a `.flatpakref`. The script also picks the 32-bit NVIDIA driver that matches your card.
3. Installs the app from the Pages repository, so `flatpak update` finds new versions. The repository is signed, and the script only accepts software signed with the project's public key, which is built into it. If the repository cannot be reached, the install stops with a message and you can try again later.
4. Opens the setup wizard. With no display (SSH, a text console) it runs the terminal setup instead.

If Flatpak is missing, it prints the install command for your distribution (apt, dnf, pacman or zypper) and stops. It never runs `sudo`. It is safe to run again.

Without the extensions the app detects the problem, `doctor` fails, and every start command exits with the command to run.

### Options

Pass options after `bash -s --` when piping, for example `curl -fsSL <address> | bash -s -- --uninstall`.

| Option | Effect |
| --- | --- |
| `--no-setup` | Install only. Do not open the wizard. |
| `--uninstall` | Remove the app and its Flatpak repository. Keeps your data and the shared 32-bit extensions. |
| `--purge` | Uninstall and also delete the app's data: the setup, Proton and any installed games. |

`flatpak uninstall --unused` removes extensions that nothing else uses.

### A specific version

Each release attaches its own copy of the script:

```
curl -fsSL https://github.com/JGBMichalski/bfme-installer/releases/download/<tag>/install-flatpak.sh | bash
```

## Releasing

The git tag is the only place the version lives. To release:

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z]` (the section becomes the release notes).
2. Commit, then tag and push: `git tag vx.y.z && git push origin vx.y.z`.

The build stamps `x.y.z` into the setup script and the Flatpak metainfo. It fails early if the changelog has no `## [x.y.z]` section.

## Repository and updates

Tagged releases (`v*`) publish a Flatpak repository to GitHub Pages, so `flatpak update` finds new versions. The address is `https://<owner>.github.io/<repo>` unless the repository variable `FLATPAK_REPO_BASE_URL` is set.

One-time setup:

1. **Settings > Pages > Source: GitHub Actions**.
2. **Settings > Environments > github-pages > Deployment branches and tags > Add rule > Tag `v*`**. The environment allows only the default branch at first, so a tagged run is rejected with "Tag ... is not allowed to deploy to github-pages".

The Pages site also serves a copy of the script that follows the newest release (`<address>/install-flatpak.sh`), with a short page that shows the install command.

Tagged releases are signed with a project key kept in the `FLATPAK_GPG_PRIVATE_KEY` repository secret. The matching public key is `flatpak/signing-key.gpg`. The setup commands are in a comment in `.github/workflows/build-linux.yml`.

## Data location

`~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer`
