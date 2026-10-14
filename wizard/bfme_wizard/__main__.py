"""Entry point: `python3 -m bfme_wizard` (the Flatpak runs this as `bfme-installer`).

  bfme-installer                     the wizard
  bfme-installer --open launcher     the "BFME All-in-One Launcher" shortcut
  bfme-installer --open arena        the "BFME Online Arena" shortcut
  bfme-installer --open aotr         the "Age of the Ring" shortcut

A shortcut starts its program without a window. If the program is gone, the wizard opens and removes the shortcut.
"""
from __future__ import annotations

import os
import sys

from .runner import ScriptRunner, app_is_ready, find_script

OPENABLE = ("launcher", "arena", "aotr")


def has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def parse_args(argv: list[str]) -> str | None:
    """The program named by --open, or None. GTK has its own options, so others are ignored."""
    for i, arg in enumerate(argv):
        if arg == "--open" and i + 1 < len(argv) and argv[i + 1] in OPENABLE:
            return argv[i + 1]
    return None


def main() -> int:
    script = find_script()
    if script is None:
        print("ERROR: bfme-linux-setup.sh was not found. Set BFME_SETUP_SCRIPT to its path.", file=sys.stderr)
        return 1
    offer = parse_args(sys.argv[1:])
    if offer and app_is_ready(script, offer):
        os.execv(script, [script, offer])   # no window needed
    if not has_display():
        # No display: install the AIO Launcher and the Arena in this terminal.
        # Age of the Ring alone: `bfme-linux-setup prepare`, then `aotr-install <file>`.
        print("No display found, so the setup wizard cannot open. Installing the AIO Launcher and the Arena in this terminal instead.")
        sys.stdout.flush()
        os.execv(script, [script, "install"])
    from .ui import WizardApp  # late, so the terminal path needs no GTK
    return WizardApp(ScriptRunner(script), offer=offer).run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
