#!/usr/bin/env python3
"""Regenerates the README screenshots in docs/images/ from the real wizard.

Runs the wizard against a stub setup script and a throwaway game environment, so it changes nothing on your
computer. Needs a desktop session (it opens a window). Usage: dev/screenshots.py [output-dir]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ("welcome", "running", "home", "folders", "troubleshoot")

STUB = r"""#!/bin/bash
# Pretends to be bfme-linux-setup.sh. STUB_SCENE picks the story.
[ "$1" = "--machine" ] && shift
case "$1" in
  status)
    if [ "$STUB_SCENE" = welcome ] || [ "$STUB_SCENE" = running ]; then
      echo "@bfme STATUS prefix missing"; echo "@bfme STATUS complete no"
    else
      for k in prefix launcher arena bfme1 bfme2 rotwk; do
        [ "$k" = prefix ] && v=ready || v=installed; echo "@bfme STATUS $k $v"
      done
      echo "@bfme STATUS complete yes"
    fi ;;
  doctor)
    echo "@bfme CHECK cpu ok x86_64 processor"
    echo "@bfme CHECK flatpak-32bit ok the 32-bit Flatpak extensions are installed"
    echo "@bfme CHECK vulkan64 ok 64-bit Vulkan works"
    echo "@bfme CHECK vulkan32 ok 32-bit Vulkan works"
    echo "@bfme CHECK disk ok enough free disk space" ;;
  install)
    echo "@bfme STEP doctor start"; echo "@bfme STEP doctor done"
    echo "@bfme STEP runner start"; echo "@bfme PROGRESS 62"; sleep 30 ;;
esac
"""


def capture(window, path: str) -> None:
    from gi.repository import Gtk
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)


def run_scene(scene: str, out: str) -> None:
    sys.path.insert(0, str(ROOT / "wizard"))
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib
    from bfme_wizard import ui
    from bfme_wizard.runner import ScriptRunner

    if scene in ("folders", "troubleshoot"):                 # tall enough to show every group
        init = ui.WizardWindow.__init__
        def tall(self, *args, **kwargs):
            init(self, *args, **kwargs)
            self.set_default_size(640, 700)
        ui.WizardWindow.__init__ = tall

    app = ui.WizardApp(ScriptRunner(os.environ["BFME_SETUP_SCRIPT"]))

    def step(window, n=[0]):
        n[0] += 1
        if n[0] == 1:                                    # let the status check finish
            window.updater.local = re.search(r"^## \[(\d[^\]]*)\]", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
            window.render()
            if scene == "running":
                window.controller.install()
            elif scene == "folders":
                window.show_game_folders()
            elif scene == "troubleshoot":
                window.show_troubleshoot()
            return True
        capture(window, out)
        app.quit()
        return False

    def activated(_app):
        window = app.props.active_window
        GLib.timeout_add(1500, step, window)
        GLib.timeout_add(3000, step, window)

    app.connect("activate", activated)
    app.run([sys.argv[0]])


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--scene":
        run_scene(sys.argv[2], sys.argv[3])
        return 0
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "images")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "bfme-linux-setup.sh"
        stub.write_text(STUB)
        stub.chmod(0o755)
        home = Path(tmp) / "home"
        roaming = home / "prefix/drive_c/users/steamuser/AppData/Roaming"
        for folder in ("BFME1", "BFME2", "RotWK"):
            (home / "prefix/drive_c" / folder).mkdir(parents=True)
        for folder in ("My Battle for Middle-earth Files", "My Battle for Middle-earth II Files", "My Rise of the Witch-king Files"):
            (roaming / folder / "Maps").mkdir(parents=True)
        for scene in SCENES:
            env = dict(os.environ, BFME_SETUP_SCRIPT=str(stub), BFME_HOME=str(home), STUB_SCENE=scene,
                       FLATPAK_ID="", GSK_RENDERER="cairo")
            target = out / f"{scene}.png"
            subprocess.run([sys.executable, __file__, "--scene", scene, str(target)], env=env, check=True, timeout=60)
            print("wrote", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
