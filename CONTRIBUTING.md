# Contributing

Bug reports and pull requests are welcome.

## Reporting a problem

Open an issue and paste the report from **Copy diagnostics** in Settings.

## Working on the code

- `dev/install-local.sh --run` builds your checkout as a Flatpak beside the release app, with its own app ID and data, and starts it. `dev/uninstall-local.sh` removes it.
- `dev/screenshots.py` regenerates the README screenshots. It needs a desktop session.
- In the repository root, run the tests (`python3 -m pytest`), the linter (`ruff check .`) and the formatter (`ruff format .`). CI fails on lint or format errors. Without ruff installed, use `uvx ruff` or `pipx run ruff`.

## Before you open a pull request

- Keep the change small and say why you made it.
- Add or update a test for any logic you change.
- Add a line under **Unreleased** in the [changelog](CHANGELOG.md) for anything a player would notice.

## Releasing

The git tag is the version. Rename `## [Unreleased]` in the changelog to `## [x.y.z]`, then run `git tag vx.y.z && git push origin vx.y.z`. CI builds and signs the Flatpak, publishes the release with that changelog section as its notes, and updates the Flatpak repository on GitHub Pages.

By contributing, you agree that your work is released under the [GPL-3.0-or-later license](LICENSE).
