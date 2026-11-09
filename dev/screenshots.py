#!/usr/bin/env python3
"""Regenerates the README screenshots in docs/images/ from the real wizard.

Runs the wizard against stand-in jobs and a throwaway game environment. Needs a desktop session.
Usage: dev/screenshots.py [output-dir]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = ("start", "running", "home", "programs", "folders", "settings", "aotr-running", "aotr-home")

class StubJobs:
    """A stand-in for engine/jobs.py's Engine. The scene says what is installed:
      start, running                  nothing is set up yet
      aotr-running                    the game environment is ready, no program is installed
      aotr-home                       only Age of the Ring is installed
      home                            the AIO Launcher, the Arena and Age of the Ring are installed
      anything else                   the AIO Launcher and the Arena are installed (the Programs page shows Age of the Ring
                                      as missing)
    """
    def __init__(self, scene: str) -> None:
        self.scene = scene

    def status(self, emit, cancel=None) -> int:
        """Report what the scene has installed."""
        from bfme_wizard.engine.events import SetupStatus

        prefix_ready = self.scene not in ("start", "running")
        programs = set()
        games = set()

        if self.scene == "aotr-home":
            programs = {"aotr"}
            games = {"aotr-games"}
        elif self.scene not in ("start", "running", "aotr-running"):
            programs = {"aio-launcher", "arena"}
            games = {"bfme1", "bfme2", "rotwk"}

            if self.scene == "home":
                programs.add("aotr")
                games.add("aotr-games")

        emit(
            SetupStatus(
                prefix_ready=prefix_ready,
                programs=frozenset(programs),
                games=frozenset(games),
                complete=prefix_ready and bool(programs),
            )
        )
        return 0

    def check(self, emit, cancel=None) -> int:
        """Check the system for required components, emitting Check events for each check."""
        from bfme_wizard.engine.events import Check

        emit(Check("cpu", "ok", "x86_64 processor"))
        emit(Check("flatpak-32bit", "ok", "32-bit Flatpak extensions installed"))
        emit(Check("graphics", "ok", "Graphics: Vulkan 1.4 on a graphics card. Using Vulkan (DXVK)."))
        emit(Check("d3d9", "ok", "d3d9.dll: DXVK's, ready for the Arena's in-game overlay."))
        emit(Check("disk", "ok", "free disk space: 120 GB (need about 30 GB)"))
        return 0

    def sync_shortcuts(self, emit, cancel=None) -> int:
        """Synchronize the system shortcuts for the installed programs."""
        return 0

    def prepare(self, emit, cancel=None) -> int:
        """Prepare the system for installation, emitting Progress and Step events."""
        from bfme_wizard.engine.events import Progress, Step

        emit(Step("doctor", "start"))
        emit(Step("doctor", "done"))
        emit(Step("runner", "start"))
        emit(Progress(62))
        time.sleep(30)
        return 0

    def install(self, key, emit, cancel=None) -> int:
        """Install a program: a download that stays at its first step, for the running page."""
        from bfme_wizard.engine.events import Progress, Step

        emit(Step("aotr-download" if key == "aotr" else key, "start"))
        emit(Progress(38))
        time.sleep(30)
        return 0

    def open_program(self, program, emit, cancel=None) -> int:
        """Open the specified program, emitting Progress and Step events as needed."""
        return 0


def capture(window, path: str) -> None:
    """Capture the current appearance of the given window and save it as a PNG at the specified path."""
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
    """Run the specified scene and save a screenshot to the given output path."""
    sys.path.insert(0, str(ROOT))
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib, Gtk
    from bfme_wizard.ui import app as ui_app
    from bfme_wizard.ui import window as ui
    from bfme_wizard.control.runner import JobRunner

    # No animations: a crossfade or a page sliding in needs a frame for every step, so a display that paints slowly (a headless
    # one paints about once a second) would leave a photograph in the middle of one. GTK jumps to the end state without them.
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)

    if scene in ("folders", "settings"):                     # tall window
        init = ui.WizardWindow.__init__
        def tall(self, *args, **kwargs):
            init(self, *args, **kwargs)
            self.set_default_size(640, 700)
        ui.WizardWindow.__init__ = tall

    app = ui_app.WizardApp(JobRunner(), jobs=StubJobs(scene))

    def act(window):
        """Put the window in the state this scene shows."""
        window.updater.local = re.search(r"^## \[(\d[^\]]*)\]", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        window.render()
        if scene == "start":                              # start page, both ticked
            for check in window.start._checks.values():
                check.set_active(True)
        elif scene == "running":
            window.controller.install(["aio-launcher"])
        elif scene == "programs":                         # the AIO Launcher and the Arena are installed, Age of the Ring is not
            window.show_programs()
        elif scene == "folders":
            window.show_game_folders()
        elif scene == "settings":
            window.show_settings()
        elif scene == "aotr-running":                     # the app downloading it
            window.controller.install(["aotr"])

    # What each scene waits for before it is photographed. A scene that is not listed is just the window once the setup has
    # been looked at. (Fixed delays do not work: how long the first status check takes depends on the machine and the display.)
    ready = {
        "start": lambda w: w.stack.get_visible_child_name() == "start",
        "running": lambda w: w.model.state == "running" and w.model.progress is not None,
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
        """Poll the window's state and capture a screenshot when it is ready, or give up after a timeout."""
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
        """Watch the window until it is ready for a screenshot or a timeout occurs, handling any exceptions."""
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
        home = Path(tmp) / "home"
        roaming = home / "prefix/drive_c/users/steamuser/AppData/Roaming"
        for folder in ("BFME2", "RotWK"):      # BFME 1 is left out: it is not listed, and four groups would not fit a short screen
            (home / "prefix/drive_c" / folder).mkdir(parents=True)
        for folder in ("My Battle for Middle-earth II Files", "My Rise of the Witch-king Files"):
            (roaming / folder / "Maps").mkdir(parents=True)
        (home / "prefix/drive_c/AgeoftheRing").mkdir(parents=True)        # Age of the Ring keeps its own copies and its own user data
        (roaming / "Age of the Ring" / "maps").mkdir(parents=True)
        for scene in SCENES:
            env = dict(os.environ, BFME_HOME=str(home),
                       FLATPAK_ID="", GSK_RENDERER="cairo")
            target = out / f"{scene}.png"
            subprocess.run([sys.executable, __file__, "--scene", scene, str(target)], env=env, check=True, timeout=60)
            print("wrote", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
