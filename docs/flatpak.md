# Flatpak

`flatpak/` packages the script and the [wizard](wizard.md) as `com.jgbmichalski.BfmeInstaller`. It adds one menu entry, **BFME Installer**, which opens the wizard. Inside the sandbox the script uses Proton only, with graphics and 32-bit libraries from the runtime.

The app runs on the GNOME runtime (`org.gnome.Platform` 49) for GTK4, libadwaita and PyGObject. It is based on freedesktop 25.08, which fixes the 32-bit extension versions below. Run the script directly with `flatpak run --command=bfme-linux-setup com.jgbmichalski.BfmeInstaller <command>`.

## Build locally

Needs `flatpak`, `flatpak-builder` and the Flathub remote.

```
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
cd flatpak
flatpak-builder --user --install --install-deps-from=flathub --force-clean build-dir com.jgbmichalski.BfmeInstaller.yml
```

## The install script

`flatpak/install-flatpak.sh` is what the README's one-line install runs. The copy attached to each release has the Pages repository address and the public signing key filled in. It:

1. Adds the Flathub remote.
2. Installs the 32-bit extensions, picking the 32-bit NVIDIA driver that matches your card. Flatpak does not install them for apps outside Flathub, whatever the install method. Without them `doctor` fails and every start command exits with the fix.
3. Installs the app from the Pages repository, accepting only software signed with the project's key.
4. Opens the wizard, or runs the terminal setup when there is no display.

If Flatpak is missing, it prints the install command for your distribution (apt, dnf, pacman or zypper) and stops. It never runs `sudo` and is safe to rerun.

Pass options after `bash -s --` when piping, for example `curl -fsSL <address> | bash -s -- --uninstall`.

| Option | Effect |
| --- | --- |
| `--no-setup` | Install only. |
| `--uninstall` | Remove the app and its Flatpak repository. Keeps your data and the shared 32-bit extensions. |
| `--purge` | Uninstall and delete the app's data, including Proton and installed games. |

`flatpak uninstall --unused` removes extensions nothing else uses.

For a specific version, use that release's copy:

```
curl -fsSL https://github.com/JGBMichalski/bfme-installer/releases/download/<tag>/install-flatpak.sh | bash
```

## Releasing

The git tag is the only place the version lives.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z]`. That section becomes the release notes.
2. Tag and push: `git tag vx.y.z && git push origin vx.y.z`.

The build stamps `x.y.z` into the script and the Flatpak metainfo, and fails if the changelog has no `## [x.y.z]` section.

## Repository and updates

Tagged releases (`v*`) publish a Flatpak repository to GitHub Pages at `https://<owner>.github.io/<repo>`, or at the repository variable `FLATPAK_REPO_BASE_URL` if set. The same site serves `<address>/install-flatpak.sh`, which follows the newest release, and a page with the install command.

One-time setup:

1. **Settings > Pages > Source: GitHub Actions**.
2. **Settings > Environments > github-pages > Deployment branches and tags > Add rule > Tag `v*`**. Without it, tagged runs fail with "Tag ... is not allowed to deploy to github-pages".

Releases are signed with the key in the `FLATPAK_GPG_PRIVATE_KEY` repository secret. The public key is `flatpak/signing-key.gpg`. Setup commands are in a comment in `.github/workflows/build-linux.yml`.

## Data location

`~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer`
