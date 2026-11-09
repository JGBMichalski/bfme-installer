"""The Troubleshoot page: system checks, graphics, tools and reset."""

from tests.fake_jobs import idle_controller
from tests.helpers import buttons, descendants, status


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# Troubleshoot page


def test_the_advice_about_graphics_drivers_names_the_chosen_backend(gtk):
    from bfme_wizard.ui.pages.troubleshoot import cant_check

    vulkan = {title: text for title, text, _command in cant_check("vulkan")}
    opengl = {title: text for title, text, _command in cant_check("opengl")}
    assert "working Vulkan drivers" in vulkan["Graphics drivers"]
    assert "working OpenGL drivers" in opengl["Graphics drivers"]
    assert "switch to OpenGL" in vulkan["Graphics drivers"]
    assert "switch back to Vulkan" in opengl["Graphics drivers"]


class RecordedActions:
    """A stand-in for the window's actions (ui/actions.py) that only writes down what the page asked for."""

    def __init__(self, asked):
        self.asked = asked

    def copy(self, text, toast):
        self.asked.append(("copy", text))

    def copy_diagnostics(self):
        self.asked.append(("copy_diagnostics",))

    def open_logs(self):
        self.asked.append(("open_logs",))

    def open_config(self):
        self.asked.append(("open_config",))

    def confirm_reset(self):
        self.asked.append(("confirm_reset",))

    def change_graphics(self, backend):
        self.asked.append(("change_graphics", backend))

    def change_option(self, option, value):
        self.asked.append(("change_option", option, value))


def troubleshoot_button_labels(Gtk, graphics):
    from bfme_wizard.ui.pages.troubleshoot import TroubleshootPage

    c = idle_controller()
    c.model.state = "idle"
    c.model.status = status(graphics=graphics)
    page = TroubleshootPage(c, RecordedActions([]))
    return [b.get_label() for b in buttons(page.view, Gtk)]


def test_the_row_offers_the_other_backend(gtk):
    assert "Use OpenGL" in troubleshoot_button_labels(gtk, "vulkan")
    assert "Use Vulkan" in troubleshoot_button_labels(gtk, "opengl")


# Troubleshoot: the graphics card and the FPS counter


def troubleshoot(installed, state="done"):
    from bfme_wizard.ui.pages.troubleshoot import TroubleshootPage

    c = idle_controller()
    c.model.state = state
    c.model.status = installed
    asked = []
    page = TroubleshootPage(c, RecordedActions(asked))
    return page, asked


def rows_titled(page, kind):
    found = {}

    for widget in descendants(page.view):
        if isinstance(widget, kind):
            found[widget.get_title()] = widget

    return found


def test_the_choice_of_card_is_only_there_with_two_cards(gtk):
    from gi.repository import Adw

    one, _ = troubleshoot(status(graphics_cards=1))
    two, _ = troubleshoot(status(graphics_cards=2))

    assert "Graphics card" not in rows_titled(one, Adw.ComboRow)
    assert "Graphics card" in rows_titled(two, Adw.ComboRow)


def test_the_rows_show_what_is_saved_and_building_them_saves_nothing(gtk):
    from gi.repository import Adw

    page, asked = troubleshoot(status(graphics_cards=2, gpu="integrated", fps_counter=True))
    combos = rows_titled(page, Adw.ComboRow)

    assert combos["Graphics card"].get_selected_item().get_string() == "Built-in card"
    assert rows_titled(page, Adw.SwitchRow)["Show FPS"].get_active()
    assert asked == []


def test_changing_a_row_saves_that_setting(gtk):
    from gi.repository import Adw

    page, asked = troubleshoot(status(graphics_cards=2))
    combos = rows_titled(page, Adw.ComboRow)

    combos["Graphics card"].set_selected(1)
    rows_titled(page, Adw.SwitchRow)["Show FPS"].set_active(True)

    assert asked == [("change_option", "gpu", "dedicated"), ("change_option", "fps-counter", 1)]


def test_the_rows_wait_while_the_setup_runs(gtk):
    from gi.repository import Adw

    page, _ = troubleshoot(status(graphics_cards=2), state="running")

    for row in [*rows_titled(page, Adw.ComboRow).values(), *rows_titled(page, Adw.SwitchRow).values()]:
        assert not row.get_sensitive(), row.get_title()


def test_the_settings_file_row_opens_it(gtk):
    from gi.repository import Adw

    page, asked = troubleshoot(status())

    rows_titled(page, Adw.ActionRow)["Open settings file"].emit("activated")

    assert asked == [("open_config",)]
