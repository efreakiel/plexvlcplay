from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import common  # noqa: F401
from plexvlc.windows_vlc import discover_vlc


class WindowsVlcTests(unittest.TestCase):
    def test_configured_absolute(self):
        if os.name != "nt":
            self.skipTest("windows")
        vlc = Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe")
        if vlc.is_file():
            self.assertEqual(discover_vlc(str(vlc)), vlc)

    def test_registry_or_program_files(self):
        found = discover_vlc()
        if os.name == "nt" and Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe").is_file():
            self.assertIsNotNone(found)
            self.assertEqual(found.name.lower(), "vlc.exe")

    def test_which_fallback_non_windows(self):
        with mock.patch("plexvlc.windows_vlc.os.name", "posix"):
            with mock.patch("plexvlc.windows_vlc.shutil.which", return_value=None):
                self.assertIsNone(discover_vlc())


if __name__ == "__main__":
    unittest.main()
