from __future__ import annotations

import unittest

import common  # noqa: F401
import socket

from plexvlc.auth import (
    PairingStore,
    check_pms_origin,
    classify_hostname,
    coerce_pms_base_url,
    host_header_ok,
    ip_allowed,
    is_chrome_extension_id,
    origin_is_pinned,
    parse_extension_origin,
    redact,
    SsrfError,
)


class AuthTests(unittest.TestCase):
    def test_chrome_ids_are_a_to_p(self):
        self.assertTrue(is_chrome_extension_id("hpdhegbljejbmohafhhgdkmbhonodpal"))
        self.assertFalse(is_chrome_extension_id("0123456789abcdef0123456789abcdef"))
        self.assertFalse(is_chrome_extension_id("hpdhegbljejbmohafhhgdkmbhonodpaQ"))
        self.assertFalse(is_chrome_extension_id("short"))

    def test_origin_pin(self):
        allowed = ["hpdhegbljejbmohafhhgdkmbhonodpal"]
        origin = "chrome-extension://hpdhegbljejbmohafhhgdkmbhonodpal"
        self.assertTrue(origin_is_pinned(origin, allowed))
        self.assertFalse(origin_is_pinned("chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", allowed))
        self.assertFalse(origin_is_pinned("chrome-extension://0123456789abcdef0123456789abcdef", allowed))
        self.assertIsNone(parse_extension_origin("https://app.plex.tv"))
        self.assertFalse(origin_is_pinned(origin, []))

    def test_host_header(self):
        self.assertTrue(host_header_ok("127.0.0.1:18765", 18765))
        self.assertTrue(host_header_ok("localhost:18765", 18765))
        self.assertFalse(host_header_ok("192.168.1.1:18765", 18765))
        self.assertFalse(host_header_ok("127.0.0.1.evil.com:18765", 18765))

    def test_ssrf_allow_and_deny(self):
        check_pms_origin("http://127.0.0.1:32400")
        check_pms_origin("http://192.168.1.50:32400")
        with self.assertRaises(SsrfError):
            check_pms_origin("http://169.254.169.254/")
        with self.assertRaises(SsrfError):
            check_pms_origin("http://example.com:32400")
        with self.assertRaises(SsrfError):
            check_pms_origin("http://[fe80::1]/")
        self.assertIsNone(classify_hostname("metadata.google.internal"))
        self.assertFalse(ip_allowed("169.254.169.254", plex_direct=True))
        self.assertTrue(ip_allowed("192.168.1.50", plex_direct=False))
        self.assertTrue(classify_hostname("192-168-1-50.abc.plex.direct") == "plex_direct")
        self.assertEqual(
            classify_hostname("192-168-1-50.nothexzzzz.plex.direct"),
            "plex_direct",
        )
        check_pms_origin("https://192-168-1-50.nothexzzzz.plex.direct:32400")

    def test_coerce_skips_cloud_and_keeps_local(self):
        self.assertIsNone(coerce_pms_base_url("https://app.plex.tv"))
        self.assertIsNone(coerce_pms_base_url("https://metadata.provider.plex.tv"))
        self.assertIsNone(coerce_pms_base_url("https://example.com:32400"))
        self.assertEqual(
            coerce_pms_base_url("http://127.0.0.1:32400/library/metadata/1"),
            "http://127.0.0.1:32400",
        )
        self.assertEqual(coerce_pms_base_url("http://192.168.1.50:32400"), "http://192.168.1.50:32400")

    def test_local_machine_hostname_allowed(self):
        host = socket.gethostname()
        self.assertEqual(classify_hostname(host), "local_name")
        origin = f"http://{host}:32400"
        self.assertEqual(coerce_pms_base_url(origin), origin)

    def test_redact(self):
        s = redact("GET /x?X-Plex-Token=secretTOKEN123&y=1")
        self.assertNotIn("secretTOKEN123", s)
        self.assertIn("X-Plex-Token=***", s)
        s = redact('{"plexToken": "abcdefghi"}')
        self.assertNotIn("abcdefghi", s)

    def test_pairing_single_use(self):
        store = PairingStore(ttl_seconds=60)
        store.generate("7K3Q9M2P")
        self.assertTrue(store.consume("7k3q9m2p"))
        self.assertFalse(store.consume("7K3Q9M2P"))


if __name__ == "__main__":
    unittest.main()
