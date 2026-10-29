import pytest


@pytest.fixture
def gtk():
    """The Gtk module, or skip: the CI job has only the GLib bindings and no display."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk
    except (ValueError, ImportError):
        pytest.skip("GTK is not installed")
    if not Gtk.init_check():
        pytest.skip("no display")
    return Gtk
