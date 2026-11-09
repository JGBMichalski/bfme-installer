"""engine.paths: where everything lives."""

from pathlib import Path

from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.programs import AIO_LAUNCHER, AOTR, ARENA, program


def test_data_dir():
    assert Paths.data_dir({"BFME_HOME": "/x/y", "XDG_DATA_HOME": "/d"}) == Path("/x/y")
    assert Paths.data_dir({"XDG_DATA_HOME": "/d"}) == Path("/d/bfme-installer")
    assert Paths.data_dir({"HOME": "/h"}) == Path("/h/.local/share/bfme-installer")


def test_the_menu_folder_is_the_hosts_even_in_the_flatpak():
    assert Paths.menu_dir({"HOME": "/h", "XDG_DATA_HOME": "/h/.var/app/x/data"}) == Path("/h/.local/share/applications")


def test_proton_layout():
    p = Paths.of({"BFME_HOME": "/b"})
    assert p.config == Path("/b/config.env")
    assert p.downloads == Path("/b/downloads")
    assert p.logs == Path("/b/logs")
    assert p.prefix == Path("/b/prefix")
    assert AOTR.unpack_dir(p) == Path("/b/downloads/aotr")
    roaming = "/b/prefix/drive_c/users/steamuser/AppData/Roaming"
    assert AIO_LAUNCHER.exe(p) == Path(f"{roaming}/BFME All In One Launcher/AllInOneLauncher.exe")
    assert ARENA.exe(p) == Path(f"{roaming}/BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe")
    assert AOTR.exe(p) == Path("/b/prefix/drive_c/AgeoftheRing/AotR_Launcher.exe")
    assert program("workshop").exe(p) == Path("/b/prefix/drive_c/BFME Tools/Workshop Studio/WorkshopStudio.exe")
    assert program("mission-control").exe(p) == Path("/b/prefix/drive_c/BFME Tools/Mission Control/MissionControl.exe")
