"""Age of the Ring: the program (program.py) and where it is downloaded from (moddb.py)."""

from .moddb import ModDB, RemoteFile
from .program import DOWNLOAD_GB, INSTALLED_GB, AgeOfTheRing, ZipContents

__all__ = ["DOWNLOAD_GB", "INSTALLED_GB", "AgeOfTheRing", "ModDB", "RemoteFile", "ZipContents"]
