from __future__ import annotations

import unittest

import common  # noqa: F401
from plexvlc import __version__


class SmokeTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
