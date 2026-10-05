"""Entry point: `python3 -m bfme_wizard` (the Flatpak runs this as `bfme-installer`)."""
from __future__ import annotations

import os
import sys

from .runner import ScriptRunner, find_script


def has_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def main() -> int:
    script = find_script()
    if script is None:
        print("ERROR: bfme-linux-setup.sh was not found. Set BFME_SETUP_SCRIPT to its path.", file=sys.stderr)
        return 1
    if not has_display():
        # Over SSH or on a text console there is no window to show: run the terminal setup instead.
        print("No display found, so the setup wizard cannot open. Running the setup in this terminal instead.")
        sys.stdout.flush()
        os.execv(script, [script, "install"])
    from .ui import WizardApp  # imported late so the terminal path needs no GTK
    return WizardApp(ScriptRunner(script)).run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
