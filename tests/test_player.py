from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import common  # noqa: F401
from plexvlc.config import PlayerConfig
from plexvlc.player import ExpandContext, PlayerError, build_argv, expand, launch, sanitize_title


class PlayerTests(unittest.TestCase):
    def test_two_part_drops_sub_and_inserts_sentinel(self):
        cfg = PlayerConfig()
        ctx = ExpandContext(
            paths=[r"D:\Media\Movie\CD1.mkv", r"D:\Media\Movie\CD2.mkv"],
            urls=[],
            title="Movie",
            start_seconds=120,
            sub_file=None,
        )
        argv = build_argv(cfg, ctx, Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"))
        self.assertEqual(
            argv,
            [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                "--no-video-title-show",
                "--start-time=120",
                "--",
                r"D:\Media\Movie\CD1.mkv",
                r"D:\Media\Movie\CD2.mkv",
            ],
        )
        self.assertNotIn("--sub-file=", " ".join(argv))

    def test_stream_with_sub(self):
        cfg = PlayerConfig()
        ctx = ExpandContext(
            paths=[],
            urls=["http://192.168.1.50:32400/library/parts/1/file.mkv?X-Plex-Token=abc"],
            title="Aladdin",
            start_seconds=0,
            sub_file=r"C:\Users\x\AppData\Local\Temp\plexvlc\65547.eng.srt",
        )
        out = expand(cfg.args_url, ctx, "VLC")
        self.assertIn("--", out)
        self.assertTrue(any(a.startswith("--sub-file=") for a in out))

    def test_path_and_paths_rejected_at_config(self):
        from plexvlc.config import ConfigError, parse_config

        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "version": 1,
                    "listen_port": 18765,
                    "helper_secret": "x",
                    "client_identifier": "y",
                    "player": {
                        "name": "VLC",
                        "executable": "",
                        "args_file": ["{path}", "{paths}"],
                        "args_url": ["{urls}"],
                    },
                    "allowed_extension_ids": [],
                }
            )

    def test_title_sanitized(self):
        self.assertEqual(sanitize_title("--help"), "help")
        self.assertNotIn("\x00", sanitize_title("a\x00b"))

    def test_no_create_no_window(self):
        with mock.patch("plexvlc.player.subprocess.Popen") as popen:
            popen.return_value = mock.Mock()
            launch(["vlc.exe", "file.mkv"])
            kwargs = popen.call_args.kwargs
            flags = kwargs.get("creationflags", 0)
            if os.name == "nt":
                self.assertFalse(flags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                self.assertTrue(flags & subprocess.DETACHED_PROCESS)

    def test_missing_exe(self):
        with mock.patch("plexvlc.player.subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(PlayerError) as ctx:
                launch(["missing-player", "a"])
            self.assertEqual(ctx.exception.error, "player_not_found")


if __name__ == "__main__":
    unittest.main()
