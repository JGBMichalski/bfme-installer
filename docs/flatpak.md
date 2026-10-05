# Flatpak

`flatpak/` packages the same script as a Flatpak (`com.jgbmichalski.BfmeInstaller`) with two menu entries, **BFME All-in-One Launcher** and **BFME Online Arena**. Inside the sandbox the script uses Proton only. The graphics and 32-bit libraries come from the Flatpak runtime.

## Build locally

Needs `flatpak`, `flatpak-builder`, and the Flathub remote for the runtimes.

```
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
cd flatpak
flatpak-builder --user --install --install-deps-from=flathub --force-clean build-dir com.jgbmichalski.BfmeInstaller.yml
```

## 32-bit extensions

The 32-bit extensions are required. Flatpak does **not** install them for apps outside Flathub: not with `flatpak-builder`, not from a self-hosted repo, and not with a `.flatpakref`. Use the helper, which also picks the 32-bit NVIDIA driver that matches your card:

```
flatpak/install-flatpak.sh --repo <repo URL or path>    # or: --bundle file.flatpak
```

Add `--no-setup` to skip the first-time Proton download.

Without the extensions the app detects the problem, `doctor` fails, and every start command exits with the command to run.

## Repository and updates

Tagged releases (`linux-v*`) publish a Flatpak repository to GitHub Pages, so `flatpak update` finds new versions. The address is `https://<owner>.github.io/<repo>` unless the repository variable `FLATPAK_REPO_BASE_URL` is set.

One-time setup:

1. **Settings > Pages > Source: GitHub Actions**.
2. **Settings > Environments > github-pages > Deployment branches and tags > Add rule > Tag `linux-v*`**. The environment allows only the default branch at first, so a tagged run is rejected with "Tag ... is not allowed to deploy to github-pages".

Install from the repository, and update later:

```
curl -fLO https://<owner>.github.io/<repo>/install-flatpak.sh && bash install-flatpak.sh
flatpak update
```

The repository is not signed yet, so Flatpak adds it with signature checking off.

## Data location

`~/.var/app/com.jgbmichalski.BfmeInstaller/data/bfme-installer`
