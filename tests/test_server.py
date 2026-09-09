from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import common  # noqa: F401
from plexvlc.config import Config, Paths, PlayerConfig, save_config
from plexvlc.server import App, make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paths = Paths.from_root(root)
        self.cfg = Config(
            listen_port=0,
            helper_secret="a" * 64,
            client_identifier="test-client",
            player=PlayerConfig(),
            allowed_extension_ids=["hpdhegbljejbmohafhhgdkmbhonodpal"],
        )
        save_config(self.paths, self.cfg)
        self.app = App(self.cfg, self.paths)
        self.httpd = make_server(self.app)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.origin = "chrome-extension://hpdhegbljejbmohafhhgdkmbhonodpal"
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _req(self, method, path, *, headers=None, data=None, origin=None):
        h = {"Host": f"127.0.0.1:{self.port}"}
        if origin:
            h["Origin"] = origin
        if headers:
            h.update(headers)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read()
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def test_health_no_secret(self):
        status, body, _ = self._req("GET", "/v1/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["service"], "plexvlc")
        self.assertIn("logPath", data)
        self.assertIn("listen", data)

    def test_launch_without_origin_requires_secret(self):
        payload = json.dumps({"ratingKey": "1", "plexToken": "tokentoken"}).encode()
        status, body, _ = self._req(
            "POST",
            "/v1/launch",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"], "unauthorized")

    def test_launch_pinned_origin_no_secret(self):
        payload = json.dumps({"ratingKey": "abc", "plexToken": "tokentoken"}).encode()
        status, body, _ = self._req(
            "POST",
            "/v1/launch",
            data=payload,
            headers={"Content-Type": "application/json"},
            origin=self.origin,
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "bad_request")

    def test_launch_foreign_origin_forbidden(self):
        payload = json.dumps({"ratingKey": "1", "plexToken": "tokentoken"}).encode()
        status, body, headers = self._req(
            "POST",
            "/v1/launch",
            data=payload,
            headers={"Content-Type": "application/json"},
            origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(status, 403)
        acao = headers.get("Access-Control-Allow-Origin") or headers.get("access-control-allow-origin")
        self.assertTrue(not acao)

    def test_foreign_origin_no_acao(self):
        status, body, headers = self._req(
            "GET",
            "/v1/health",
            origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(status, 200)
        acao = headers.get("Access-Control-Allow-Origin") or headers.get("access-control-allow-origin")
        self.assertTrue(not acao)

    def test_pinned_origin_cors(self):
        status, body, headers = self._req("GET", "/v1/health", origin=self.origin)
        self.assertEqual(status, 200)
        acao = headers.get("Access-Control-Allow-Origin") or headers.get("access-control-allow-origin")
        self.assertEqual(acao, self.origin)

    def test_pair_flow(self):
        code = self.app.mint_pairing_code()
        payload = json.dumps({"code": code}).encode()
        status, body, _ = self._req(
            "POST",
            "/v1/pair",
            data=payload,
            headers={"Content-Type": "application/json"},
            origin=self.origin,
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["secret"], self.cfg.helper_secret)
        status2, body2, _ = self._req(
            "POST",
            "/v1/pair",
            data=payload,
            headers={"Content-Type": "application/json"},
            origin=self.origin,
        )
        self.assertEqual(status2, 401)

    def test_get_pair_is_404(self):
        status, body, _ = self._req("GET", "/v1/pair", origin=self.origin)
        self.assertEqual(status, 404)

    def test_launch_with_secret_bad_rating(self):
        payload = json.dumps({"ratingKey": "abc", "plexToken": "tokentoken"}).encode()
        status, body, _ = self._req(
            "POST",
            "/v1/launch",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-PlexVLC-Secret": self.cfg.helper_secret,
            },
            origin=self.origin,
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
