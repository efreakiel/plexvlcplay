from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import common
from plexvlc.resolve import ResolveError, resolve_launch


def load(name: str) -> dict:
    return json.loads((common.FIXTURES / name).read_text(encoding="utf-8"))


def with_files(payload: dict, mapping: dict[str, str]) -> dict:
    """Replace Part.file placeholders with real paths."""
    md = payload["MediaContainer"]["Metadata"][0]
    for media in md.get("Media") or []:
        for part in media.get("Part") or []:
            key = part.get("file")
            if key in mapping:
                part["file"] = mapping[key]
    return payload


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, name: str) -> str:
        p = self.dir / name
        p.write_bytes(b"x")
        return str(p)

    def test_file_exists(self):
        path = self._touch("aladdin.mkv")
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": path})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.mode, "file")
        self.assertEqual(plan.paths, [path])
        self.assertEqual(plan.start_seconds, 120)
        self.assertEqual(plan.title, "Aladdin")

    def test_missing_file_streams(self):
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": str(self.dir / "nope.mkv")})
        plan = resolve_launch(
            payload,
            stream_base="http://192.168.1.50:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.mode, "url")
        self.assertTrue(plan.urls[0].startswith("http://192.168.1.50:32400/library/parts/"))
        self.assertIn("X-Plex-Token=tokentok", plan.urls[0])
        self.assertNotIn("tokentok", plan.path_hint)
        self.assertNotIn("X-Plex-Token", plan.path_hint)

    def test_media_id_selects_1080p(self):
        hd = self._touch("hd.mkv")
        sd = self._touch("sd.mkv")
        payload = with_files(load("movie_multiversion.json"), {"SD": sd, "HD": hd})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            media_id=20,
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.paths, [hd])
        plan0 = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan0.paths, [sd])

    def test_multipart_order(self):
        cd1 = self._touch("cd1.mkv")
        cd2 = self._touch("cd2.mkv")
        payload = with_files(load("movie_multipart.json"), {"CD1": cd1, "CD2": cd2})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.paths, [cd1, cd2])

    def test_episode_title(self):
        ep = self._touch("pilot.mkv")
        payload = with_files(load("episode.json"), {"EP": ep})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.title, "Lost - s01e01 - Pilot")
        self.assertEqual(plan.start_seconds, 60)

    def test_show_unsupported(self):
        with self.assertRaises(ResolveError) as ctx:
            resolve_launch(load("show.json"), stream_base="http://127.0.0.1:32400", token="tokentok")
        self.assertEqual(ctx.exception.error, "unsupported_type")

    def test_photo_unsupported(self):
        with self.assertRaises(ResolveError) as ctx:
            resolve_launch(load("photo.json"), stream_base="http://127.0.0.1:32400", token="tokentok")
        self.assertEqual(ctx.exception.error, "unsupported_type")

    def test_viewoffset_near_end_is_zero(self):
        path = self._touch("a.mkv")
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": path})
        payload["MediaContainer"]["Metadata"][0]["viewOffset"] = 5000000
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.start_seconds, 0)

    def test_pgs_selected_skips_download(self):
        path = self._touch("m.mkv")
        payload = with_files(load("streams_external_sub.json"), {"MOV": path})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (500, b"no"),
        )
        self.assertIsNone(plan.sub_file)

    def test_srt_download_success(self):
        path = self._touch("m.mkv")
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": path})
        temp = self.dir / "subs"

        def fetch(url, headers, timeout):
            self.assertIn("/library/streams/40200", url)
            return 200, b"1\n00:00:01,000 --> 00:00:02,000\nhi\n"

        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=fetch,
            temp_dir=temp,
        )
        self.assertIsNotNone(plan.sub_file)
        self.assertTrue(Path(plan.sub_file).is_file())

    def test_subtitle_failure_still_launches(self):
        path = self._touch("m.mkv")
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": path})

        def fetch(url, headers, timeout):
            return 404, b"nope"

        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=fetch,
            temp_dir=self.dir / "subs",
        )
        self.assertEqual(plan.mode, "file")
        self.assertIsNone(plan.sub_file)

    def test_subtitle_oversize_still_launches(self):
        path = self._touch("m.mkv")
        payload = with_files(load("movie_single.json"), {"PLACEHOLDER": path})

        def fetch(url, headers, timeout):
            return 200, b"x" * (4 * 1024 * 1024 + 1)

        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=fetch,
            temp_dir=self.dir / "subs",
        )
        self.assertIsNone(plan.sub_file)
        self.assertEqual(plan.mode, "file")

    def test_mixed_parts_file_only(self):
        cd1 = self._touch("cd1.mkv")
        payload = with_files(load("movie_multipart.json"), {"CD1": cd1, "CD2": str(self.dir / "missing.mkv")})
        plan = resolve_launch(
            payload,
            stream_base="http://127.0.0.1:32400",
            token="tokentok",
            fetch=lambda *a: (404, b""),
        )
        self.assertEqual(plan.mode, "file")
        self.assertEqual(plan.paths, [cd1])
        self.assertEqual(plan.urls, [])


if __name__ == "__main__":
    unittest.main()
