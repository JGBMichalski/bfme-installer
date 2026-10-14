#!/usr/bin/env python3
"""Regenerates the README screenshots in docs/images/ from the real wizard.

Runs the wizard against a stub script and a throwaway game environment. Needs a desktop session.
Usage: dev/screenshots.py [output-dir]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ("start", "running", "home", "programs", "folders", "troubleshoot", "aotr-download", "aotr-running", "aotr-home")

STUB = r"""#!/bin/bash
# Stub for bfme-linux-setup.sh. STUB_SCENE picks the scene:
#   start, running                  nothing is set up yet
#   aotr-download, aotr-running     the game environment is ready, no program is installed
#   aotr-home                       only Age of the Ring is installed
#   home                            the AIO Launcher, the Arena and Age of the Ring are installed
#   anything else                   the AIO Launcher and the Arena are installed (the Programs page shows Age of the Ring as missing)
[ "$1" = "--machine" ] && shift
case "$1" in
  status)
    case "$STUB_SCENE" in
      start|running)
        echo "@bfme STATUS prefix missing"; echo "@bfme STATUS complete no" ;;
      aotr-download|aotr-running)
        echo "@bfme STATUS prefix ready"; echo "@bfme STATUS launcher missing"; echo "@bfme STATUS arena missing"
        echo "@bfme STATUS aotr missing"; echo "@bfme STATUS complete no" ;;
      aotr-home)
        echo "@bfme STATUS prefix ready"; echo "@bfme STATUS launcher missing"; echo "@bfme STATUS arena missing"
        echo "@bfme STATUS aotr installed"; echo "@bfme STATUS complete yes" ;;
      *)
        for k in prefix launcher arena bfme1 bfme2 rotwk; do
          [ "$k" = prefix ] && v=ready || v=installed; echo "@bfme STATUS $k $v"
        done
        if [ "$STUB_SCENE" = home ]; then echo "@bfme STATUS aotr installed"; else echo "@bfme STATUS aotr missing"; fi
        echo "@bfme STATUS complete yes" ;;
    esac ;;
  aotr-install)
    echo "@bfme STEP aotr-check start"; echo "@bfme STEP aotr-check done"
    echo "@bfme STEP aotr-unpack start"; echo "@bfme STEP aotr-unpack done"
    echo "@bfme STEP aotr-install start"; echo "@bfme PROGRESS 38"; sleep 30 ;;
  doctor)
    echo "@bfme CHECK cpu ok x86_64 processor"
    echo "@bfme CHECK flatpak-32bit ok the 32-bit Flatpak extensions are installed"
    echo "@bfme CHECK vulkan64 ok 64-bit Vulkan works"
    echo "@bfme CHECK vulkan32 ok 32-bit Vulkan works"
    echo "@bfme CHECK disk ok enough free disk space" ;;
  prepare)
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
    if node is None:
        raise RuntimeError("the window has not drawn a frame, so there is nothing to photograph (is the screen locked or off?)")
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)


def run_scene(scene: str, out: str) -> None:
    sys.path.insert(0, str(ROOT / "wizard"))
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib, Gtk
    from bfme_wizard import ui
    from bfme_wizard.runner import ScriptRunner

    # No animations: a crossfade or a page sliding in needs a frame for every step, so a display that paints slowly (a headless
    # one paints about once a second) would leave a photograph in the middle of one. GTK jumps to the end state without them.
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)

    if scene in ("folders", "troubleshoot", "aotr-download"):                 # tall window
        init = ui.WizardWindow.__init__
        def tall(self, *args, **kwargs):
            init(self, *args, **kwargs)
            self.set_default_size(640, 700)
        ui.WizardWindow.__init__ = tall

    app = ui.WizardApp(ScriptRunner(os.environ["BFME_SETUP_SCRIPT"]))

    def act(window):
        """Put the window in the state this scene shows."""
        window.updater.local = re.search(r"^## \[(\d[^\]]*)\]", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        window.render()
        if scene == "start":                              # start page, both ticked
            for check in window.start._checks.values():
                check.set_active(True)
        elif scene == "running":
            window.controller.install(["launcher"])
        elif scene == "programs":                         # the AIO Launcher and the Arena are installed, Age of the Ring is not
            window.show_programs()
        elif scene == "folders":
            window.show_game_folders()
        elif scene == "troubleshoot":
            window.show_troubleshoot()
        elif scene == "aotr-download":                    # environment ready: go to download
            window.controller.install(["aotr"])
        elif scene == "aotr-running":
            window.controller.install(["aotr"])
            window.controller.choose_aotr_file("/tmp/AotR_Standalone_9.3.0_Installer.zip")

    # What each scene waits for before it is photographed. A scene that is not listed is just the window once the setup has
    # been looked at. (Fixed delays do not work: how long the first status check takes depends on the machine and the display.)
    ready = {
        "start": lambda w: w.stack.get_visible_child_name() == "start",
        "running": lambda w: w.model.state == "running" and w.model.progress is not None,
        "aotr-download": lambda w: w.model.state == "waiting",
        "aotr-running": lambda w: w.model.state == "running" and w.model.progress is not None,
    }.get(scene, lambda w: True)
    FRAMES = 2         # frames painted after the scene was set up: the layout of what it changed has happened
    GIVE_UP = 30.0     # seconds before it photographs whatever is there
    failures: list[Exception] = []
    frames = []   # one entry for each frame the window has painted

    def drawn(window):
        """The window has painted a frame. A display only asks for one when the window is really on screen, so on a locked or
        sleeping screen this never becomes true and a photograph would be empty."""
        if not frames and window.get_frame_clock() is not None and not getattr(window, "_watching_frames", False):
            window._watching_frames = True
            window.get_frame_clock().connect("after-paint", lambda *_: frames.append(True))
        return bool(frames) and window.get_width() > 0 and window.get_height() > 0

    def poll(window, clock):
        now = GLib.get_monotonic_time() / 1e6
        if clock["acted"] is None:
            # The status check, the shortcut sync and the quiet system checks run one after the other: wait for all of them.
            if window.model.state != "checking" and not window.controller.runner.busy and drawn(window):
                act(window)
                clock["acted"], clock["frames"] = now, len(frames)
            elif now - clock["begun"] > GIVE_UP:
                raise RuntimeError("the window never got ready: the status check did not end, or no frame was ever painted "
                                   "(is the screen locked or off?)")
            return True
        if (ready(window) and len(frames) >= clock["frames"] + FRAMES) or now - clock["acted"] > GIVE_UP:
            if not ready(window):
                print(f"{scene}: not in the state it should show, photographing it anyway", file=sys.stderr)
            capture(window, out)
            app.quit()
            return False
        return True

    def watch(window, clock={"acted": None, "frames": 0, "begun": GLib.get_monotonic_time() / 1e6}):
        try:
            return poll(window, clock)
        except Exception as error:   # a callback that raises would leave the window open until the caller's timeout
            failures.append(error)
            app.quit()
            return False

    def activated(_app):
        GLib.timeout_add(100, watch, app.props.active_window)

    app.connect("activate", activated)
    app.run([sys.argv[0]])
    if failures:
        raise SystemExit(f"{scene}: {failures[0]}")


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
        for folder in ("BFME2", "RotWK"):      # BFME 1 is left out: it is not listed, and four groups would not fit a short screen
            (home / "prefix/drive_c" / folder).mkdir(parents=True)
        for folder in ("My Battle for Middle-earth II Files", "My Rise of the Witch-king Files"):
            (roaming / folder / "Maps").mkdir(parents=True)
        (home / "prefix/drive_c/AgeoftheRing").mkdir(parents=True)        # Age of the Ring keeps its own copies and its own user data
        (roaming / "Age of the Ring" / "maps").mkdir(parents=True)
        for scene in SCENES:
            env = dict(os.environ, BFME_SETUP_SCRIPT=str(stub), BFME_HOME=str(home), STUB_SCENE=scene,
                       FLATPAK_ID="", GSK_RENDERER="cairo")
            target = out / f"{scene}.png"
            subprocess.run([sys.executable, __file__, "--scene", scene, str(target)], env=env, check=True, timeout=60)
            print("wrote", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
