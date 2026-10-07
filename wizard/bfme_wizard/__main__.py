"""Entry point: `python3 -m bfme_wizard` (the Flatpak runs this as `bfme-installer`).

  bfme-installer                     the wizard
  bfme-installer --open launcher     the "BFME All-in-One Launcher" menu entry
  bfme-installer --open arena        the "BFME Online Arena" menu entry

With --open and the setup complete, the app starts at once with no window. With the setup incomplete, the wizard opens
instead and offers that app when the setup is done.
"""
from __future__ import annotations

import os
import sys

from .runner import ScriptRunner, find_script, setup_is_complete

OPENABLE = ("launcher", "arena")


def has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def parse_args(argv: list[str]) -> str | None:
    """The app named by --open, or None. Anything else is ignored (GTK has options of its own)."""
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
    if offer and setup_is_complete(script):
        os.execv(script, [script, offer])   # nothing to show: start the app and be gone
    if not has_display():
        # Over SSH or on a text console there is no window to show: run the terminal setup instead.
        print("No display found, so the setup wizard cannot open. Running the setup in this terminal instead.")
        sys.stdout.flush()
        os.execv(script, [script, "install"])
    from .ui import WizardApp  # imported late so the terminal path needs no GTK
    return WizardApp(ScriptRunner(script), offer=offer).run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
