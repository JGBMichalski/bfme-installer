# Contributing

Bug reports and pull requests are welcome.

## Reporting a problem

Open an issue and fill in the form. Press **Copy diagnostics** on the Troubleshoot page and paste the report into it.
The report can contain your home folder and user name, so read it first.

## Working on the code

Testing your modifications:
- `dev/install-local.sh --run` builds the Flatpak from your checkout and installs it beside the release app, under
  another app ID. `dev/uninstall-local.sh` removes it.
- `dev/screenshots.py` regenerates the README screenshots from the real wizard, against a stub script and a throwaway
  game environment. It needs a desktop session.

## Before you open a pull request

- Keep the change small and say why you made it.
- Add or update a test for any logic you change.
- Add a line under **Unreleased** in the [changelog](CHANGELOG.md) for anything a player would notice.

By contributing, you agree that your work is released under the [MIT license](LICENSE).
