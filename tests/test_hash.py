from __future__ import annotations

import unittest

from hashutil import parse_plex_location

MID = "6a646027a56abb6dbdf72484564db8567c737430"


class HashTests(unittest.TestCase):
    def test_encoded_details(self):
        href = f"https://app.plex.tv/desktop/#!/server/{MID}/details?key=%2Flibrary%2Fmetadata%2F65547"
        r = parse_plex_location(href)
        self.assertEqual(r["ratingKey"], "65547")
        self.assertEqual(r["machineIdentifier"], MID)

    def test_decoded_with_context(self):
        href = (
            f"https://app.plex.tv/desktop/#!/server/{MID}/details"
            f"?key=/library/metadata/65547&context=source%3Acontent.library~0~2"
        )
        r = parse_plex_location(href)
        self.assertEqual(r["ratingKey"], "65547")
        self.assertEqual(r["machineIdentifier"], MID)

    def test_media_alias(self):
        href = f"https://app.plex.tv/desktop/#!/media/{MID}/details?key=/library/metadata/65547"
        r = parse_plex_location(href)
        self.assertEqual(r["ratingKey"], "65547")
        self.assertEqual(r["machineIdentifier"], MID)

    def test_preplay_and_player(self):
        for kind in ("preplay", "player"):
            href = f"https://app.plex.tv/desktop/#!/server/{MID}/{kind}?key=%2Flibrary%2Fmetadata%2F65547"
            r = parse_plex_location(href)
            self.assertEqual(r["ratingKey"], "65547")

    def test_query_server(self):
        href = f"https://app.plex.tv/desktop/#!/details?key=%2Flibrary%2Fmetadata%2F65547&server={MID}"
        r = parse_plex_location(href)
        self.assertEqual(r["ratingKey"], "65547")
        self.assertEqual(r["machineIdentifier"], MID)

    def test_local_web(self):
        href = f"http://127.0.0.1:32400/web/index.html#!/server/{MID}/details?key=%2Flibrary%2Fmetadata%2F65547"
        r = parse_plex_location(href)
        self.assertEqual(r["ratingKey"], "65547")

    def test_discover_hex(self):
        href = (
            "https://app.plex.tv/desktop/#!/provider/tv.plex.provider.metadata/details"
            "?key=/library/metadata/5d776827eb5d26001f1ddab7"
        )
        r = parse_plex_location(href)
        self.assertEqual(r["error"], "unsupported_discover")

    def test_no_key(self):
        r = parse_plex_location("https://app.plex.tv/desktop/#!/server/abc/details")
        self.assertEqual(r["error"], "no_key")


if __name__ == "__main__":
    unittest.main()
