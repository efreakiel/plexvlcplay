from __future__ import annotations

import json
import unittest

import common
from plexvlc.plex import (
    device_is_server,
    dashed_to_ipv4,
    metadata_url,
    pick_stream_base,
    plex_bool,
    plex_int,
    PlexError,
)


class PlexTests(unittest.TestCase):
    def test_metadata_url_has_checkfiles_not_includeelements(self):
        url = metadata_url("http://127.0.0.1:32400", "65547")
        self.assertIn("checkFiles=1", url)
        self.assertNotIn("includeElements", url)
        self.assertTrue(url.startswith("http://127.0.0.1:32400/library/metadata/65547"))

    def test_coercion(self):
        self.assertTrue(plex_bool(1))
        self.assertTrue(plex_bool("1"))
        self.assertTrue(plex_bool(True))
        self.assertFalse(plex_bool(0))
        self.assertEqual(plex_int("73681"), 73681)
        self.assertEqual(plex_int(73681), 73681)

    def test_provides_strips(self):
        self.assertTrue(device_is_server({"provides": "server, player"}))
        self.assertTrue(device_is_server({"provides": "server"}))
        self.assertFalse(device_is_server({"provides": "player"}))

    def test_dashed_ip(self):
        self.assertEqual(dashed_to_ipv4("192-168-1-50.abc.plex.direct"), "192.168.1.50")

    def test_pick_stream_base_loopback(self):
        def probe(origin, token):
            if origin == "http://127.0.0.1:32400":
                return {"machineIdentifier": "abc", "claimed": True}
            return None

        base = pick_stream_base("abc", None, "tok", "cid", probe=probe, resources=lambda: [])
        self.assertEqual(base, "http://127.0.0.1:32400")

    def test_pick_stream_base_dashed(self):
        hits = []

        def probe(origin, token):
            hits.append(origin)
            if origin == "http://192.168.1.50:32400":
                return {"machineIdentifier": "abc"}
            return None

        base = pick_stream_base(
            "abc",
            "https://192-168-1-50.abc.plex.direct:32400",
            "tok",
            "cid",
            probe=probe,
            resources=lambda: [],
        )
        self.assertEqual(base, "http://192.168.1.50:32400")

    def test_resources_local_http(self):
        devices = json.loads((common.FIXTURES / "plex_tv_resources.json").read_text(encoding="utf-8"))

        def probe(origin, token):
            if origin == "http://192.168.1.50:32400":
                self.assertEqual(token, "server-token-value")
                return {"machineIdentifier": "6a646027a56abb6dbdf72484564db8567c737430"}
            return None

        base = pick_stream_base(
            "6a646027a56abb6dbdf72484564db8567c737430",
            None,
            "web-token",
            "cid",
            probe=probe,
            resources=lambda: devices,
        )
        self.assertEqual(base, "http://192.168.1.50:32400")

    def test_unreachable(self):
        with self.assertRaises(PlexError) as ctx:
            pick_stream_base("nope", None, "tok", "cid", probe=lambda o, t: None, resources=lambda: [])
        self.assertEqual(ctx.exception.error, "plex_unreachable")


if __name__ == "__main__":
    unittest.main()
