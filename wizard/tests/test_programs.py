"""The Programs page: one row per program, with Install when it is missing and Remove when it is installed."""
import unittest

from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner
from tests.helpers import buttons, descendants, gtk_or_skip, make_script, wait_for

IDLE = "#!/usr/bin/env bash\nexit 0\n"
ALL = {"launcher": "installed", "arena": "installed", "aotr": "installed"}


class ProgramsPage(unittest.TestCase):
    def page(self, installed, **state):
        Gtk = gtk_or_skip(self)
        from gi.repository import Adw
        from bfme_wizard.programs import ProgramsPage as Page
        c = Controller(ScriptRunner(make_script(IDLE)), lambda: None)
        c.model.installed = dict(installed)
        c.model.state = state.get("model_state", "done")
        c.model.removing = state.get("removing")
        for name, value in state.get("apps", {}).items():
            c.apps.state[name] = value
        asked = []
        page = Page(c, install=lambda p: asked.append(("install", p)), remove=lambda p: asked.append(("remove", p)))
        rows = [w for w in descendants(page.view) if isinstance(w, Adw.ActionRow)]
        return Gtk, c, page, rows, asked

    @staticmethod
    def row_buttons(row, Gtk):
        return buttons(row, Gtk)

    @staticmethod
    def rows_of(page):
        """The rows as they are now (a refresh builds new ones)."""
        from gi.repository import Adw
        return [w for w in descendants(page.view) if isinstance(w, Adw.ActionRow)]

    def test_a_row_for_every_program_in_the_order_of_the_home_screen(self):
        _Gtk, _c, _page, rows, _asked = self.page(ALL)
        self.assertEqual([r.get_title() for r in rows], ["AIO Launcher", "Arena", "Age of the Ring"])

    def test_an_installed_program_offers_remove_and_a_missing_one_offers_install(self):
        Gtk, _c, _page, rows, _asked = self.page({"launcher": "installed", "arena": "installed"})
        self.assertEqual([[b.get_label() for b in self.row_buttons(r, Gtk)] for r in rows],
                         [["Remove"], ["Remove"], ["Install"]])

    def test_install_looks_like_the_main_action_and_remove_like_the_dangerous_one(self):
        Gtk, _c, _page, rows, _asked = self.page({"launcher": "installed"})
        remove, = self.row_buttons(rows[0], Gtk)
        install, = self.row_buttons(rows[2], Gtk)
        self.assertTrue(remove.has_css_class("destructive-action") and not remove.has_css_class("suggested-action"))
        self.assertTrue(install.has_css_class("suggested-action") and not install.has_css_class("destructive-action"))

    def test_the_buttons_ask_for_their_own_program(self):
        Gtk, _c, _page, rows, asked = self.page({"launcher": "installed", "aotr": "installed"})
        for row in rows:
            for button in self.row_buttons(row, Gtk):
                button.emit("clicked")
        self.assertEqual(asked, [("remove", "launcher"), ("install", "arena"), ("remove", "aotr")])

    def test_each_row_says_whether_the_program_is_there(self):
        _Gtk, _c, _page, rows, _asked = self.page({"launcher": "installed", "arena": "installed"})
        self.assertEqual(rows[0].get_subtitle(), "Installed")
        self.assertEqual(rows[1].get_subtitle(), "Installed")
        self.assertTrue(rows[2].get_subtitle().startswith("Not installed."))
        self.assertIn("14 GB", rows[2].get_subtitle())       # Age of the Ring is a big download the player makes first

    def test_a_missing_program_says_what_installing_it_installs_with_it(self):
        # The Arena only plays what the AIO Launcher installs, so the setup installs them together.
        _Gtk, _c, _page, rows, _asked = self.page({})
        self.assertIn("Installs the Arena too", rows[0].get_subtitle())
        self.assertIn("Installs the AIO Launcher too", rows[1].get_subtitle())
        _Gtk, _c, _page, rows, _asked = self.page({"launcher": "installed"})
        self.assertNotIn("too", rows[1].get_subtitle())                      # the AIO Launcher is there: nothing else comes
        _Gtk, _c, _page, rows, _asked = self.page({"arena": "installed"})
        self.assertNotIn("too", rows[0].get_subtitle())

    def test_a_program_that_is_open_cannot_be_removed_and_the_others_say_what_to_close(self):
        # Removing one ends the whole Wine session, which would close the open one too: nothing can go until it is closed.
        Gtk, _c, _page, rows, _asked = self.page(ALL, apps={"arena": "running"})
        self.assertEqual(rows[1].get_subtitle(), "Running. Close it to remove it.")
        self.assertEqual(rows[0].get_subtitle(), "Installed. Close the Arena to remove it.")
        self.assertEqual(rows[2].get_subtitle(), "Installed. Close the Arena to remove it.")
        self.assertEqual([[b.get_sensitive() for b in self.row_buttons(r, Gtk)] for r in rows], [[False], [False], [False]])

    def test_with_two_programs_open_it_names_both_in_the_order_of_the_page(self):
        _Gtk, _c, _page, rows, _asked = self.page(ALL, apps={"aotr": "running", "launcher": "running"})
        self.assertEqual(rows[1].get_subtitle(), "Installed. Close the AIO Launcher and Age of the Ring to remove it.")

    def test_a_missing_program_can_still_be_installed_while_another_is_open(self):
        # Only removing is dangerous to what is open.
        Gtk, _c, _page, rows, _asked = self.page({"launcher": "installed", "arena": "installed"}, apps={"launcher": "running"})
        install, = self.row_buttons(rows[2], Gtk)
        self.assertEqual((install.get_label(), install.get_sensitive()), ("Install", True))

    def test_nothing_can_be_changed_while_the_script_is_busy(self):
        Gtk, c, page, _rows, _asked = self.page({"launcher": "installed"})
        self.assertTrue(c.run_checks())
        page.refresh()
        found = [b for r in self.rows_of(page) for b in self.row_buttons(r, Gtk)]
        self.assertEqual(sorted(b.get_label() for b in found), ["Install", "Install", "Remove"])
        self.assertEqual([b.get_sensitive() for b in found], [False, False, False])
        wait_for(8000, lambda: not c.runner.busy)
        page.refresh()
        self.assertTrue(all(b.get_sensitive() for r in self.rows_of(page) for b in self.row_buttons(r, Gtk)))

    def test_the_program_being_removed_shows_it_and_everything_else_waits(self):
        Gtk, _c, _page, rows, _asked = self.page(ALL, model_state="removing", removing="arena")
        self.assertEqual(rows[1].get_subtitle(), "Removing...")
        self.assertEqual(self.row_buttons(rows[1], Gtk), [])                 # no button to press twice
        self.assertTrue(any(isinstance(w, Gtk.Spinner) for w in descendants(rows[1])))
        others = [b for r in (rows[0], rows[2]) for b in self.row_buttons(r, Gtk)]
        self.assertEqual([b.get_sensitive() for b in others], [False, False])

    def test_the_page_says_that_games_are_safe(self):
        Gtk, _c, page, _rows, _asked = self.page(ALL)
        from gi.repository import Adw
        preferences = next(w for w in descendants(page.view) if isinstance(w, Adw.PreferencesPage))
        self.assertIn("games you installed with the AIO Launcher", preferences.get_description())

    def test_it_is_rebuilt_only_when_what_it_shows_has_changed(self):
        # An open dialog or a pressed button must not be pulled away by the window rendering on every line of output.
        Gtk, c, page, rows, _asked = self.page(ALL)
        first = page.view.get_content()
        page.refresh()
        self.assertIs(page.view.get_content(), first)
        c.model.installed["aotr"] = "missing"
        page.refresh()
        self.assertIsNot(page.view.get_content(), first)


class Catalog(unittest.TestCase):
    """The programs are listed in three places that do not import each other. They must agree."""

    def test_it_covers_exactly_the_programs_the_rest_of_the_wizard_knows_in_the_order_it_shows_them(self):
        from bfme_wizard.apps import APPS
        from bfme_wizard.catalog import CATALOG
        from bfme_wizard.model import ALL_PROGRAMS
        self.assertEqual([p.key for p in CATALOG], list(ALL_PROGRAMS))
        self.assertEqual(sorted(APPS), sorted(ALL_PROGRAMS))

    def test_the_programs_that_install_together_are_programs(self):
        from bfme_wizard.catalog import INSTALLED_TOGETHER, program
        for key, partner in INSTALLED_TOGETHER.items():
            self.assertEqual(INSTALLED_TOGETHER[partner], key)    # it goes both ways
            self.assertEqual((program(key).key, program(partner).key), (key, partner))

    def test_every_program_says_what_removing_it_leaves_alone(self):
        from bfme_wizard.catalog import CATALOG
        for info in CATALOG:
            self.assertIn("not touched", info.removal)


if __name__ == "__main__":
    unittest.main()
