"""Loopback HTTP helper."""

from __future__ import annotations

import json
import logging
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from plexvlc import __version__
from plexvlc.auth import (
    PAIR_ALPHABET,
    PairingStore,
    host_header_ok,
    origin_is_pinned,
    peer_is_loopback,
    redact,
    secrets_equal,
)
from plexvlc.config import Config, Paths
from plexvlc.player import ExpandContext, PlayerError, build_argv, launch, resolve_executable
from plexvlc.plex import PlexError, fetch_metadata, pick_stream_base, plex_int
from plexvlc.resolve import LaunchPlan, ResolveError, resolve_launch

log = logging.getLogger("plexvlc")

MAX_BODY = 64 * 1024
LAUNCH_KEYS = {
    "ratingKey",
    "plexToken",
    "pmsBaseUrl",
    "machineIdentifier",
    "mediaId",
    "partId",
    "offsetMs",
    "titleHint",
}


class App:
    def __init__(self, cfg: Config, paths: Paths):
        self.cfg = cfg
        self.paths = paths
        self.pairing = PairingStore()
        self.listen = f"127.0.0.1:{cfg.listen_port}"

    def mint_pairing_code(self) -> str:
        code = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(8))
        self.pairing.generate(code)
        try:
            self.paths.pair_code.write_text(code + "\n", encoding="utf-8")
        except OSError:
            pass
        return code


def _json_error(error: str) -> bytes:
    return json.dumps({"ok": False, "error": error}).encode("utf-8")


def _json_ok(payload: dict) -> bytes:
    body = {"ok": True, **payload}
    return json.dumps(body).encode("utf-8")


def validate_launch_body(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ResolveError("bad_request")
    extra = set(data) - LAUNCH_KEYS
    if extra:
        raise ResolveError("bad_request")
    rating = data.get("ratingKey")
    token = data.get("plexToken")
    if not isinstance(rating, str) or not rating.isdigit():
        raise ResolveError("bad_request")
    if not isinstance(token, str) or not (8 <= len(token) <= 512):
        raise ResolveError("bad_request")
    pms = data.get("pmsBaseUrl")
    if pms is not None and not isinstance(pms, str):
        raise ResolveError("bad_request")
    if isinstance(pms, str) and len(pms) > 256:
        raise ResolveError("bad_request")
    mid = data.get("machineIdentifier")
    if mid is not None and (not isinstance(mid, str) or len(mid) > 128):
        raise ResolveError("bad_request")
    for key in ("mediaId", "partId", "offsetMs"):
        val = data.get(key, None)
        if val is not None and not isinstance(val, int):
            # JSON numbers only; coerce string digits from sloppy clients
            if isinstance(val, str) and val.isdigit():
                data[key] = int(val)
            else:
                raise ResolveError("bad_request")
    title = data.get("titleHint")
    if title is not None and (not isinstance(title, str) or len(title) > 512):
        raise ResolveError("bad_request")
    return data


class Handler(BaseHTTPRequestHandler):
    app: App
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        try:
            msg = fmt % args
        except Exception:
            msg = fmt
        log.info("%s", redact(msg))

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin_is_pinned(origin, self.app.cfg.allowed_extension_ids):
            return origin
        return None

    def _send(self, status: int, body: bytes, origin: str | None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-PlexVLC-Secret")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _gate(self) -> bool:
        if not peer_is_loopback(self.client_address[0]):
            self._send(403, _json_error("forbidden_origin"), None)
            return False
        if not host_header_ok(self.headers.get("Host"), self.app.cfg.listen_port):
            self._send(403, _json_error("forbidden_origin"), None)
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._gate():
            return
        origin = self._cors_origin()
        self._send(204, b"", origin)

    def do_GET(self) -> None:  # noqa: N802
        if not self._gate():
            return
        path = urlparse(self.path).path
        origin = self._cors_origin()
        if path == "/v1/health":
            self._send(200, self._health(), origin)
            return
        if path == "/v1/config":
            if not self._require_auth(origin):
                return
            payload = self.app.cfg.to_public_dict()
            payload["logPath"] = str(self.app.paths.log)
            payload["listen"] = self.app.listen
            self._send(200, json.dumps(payload).encode("utf-8"), origin)
            return
        self._send(404, _json_error("not_found"), origin)

    def do_POST(self) -> None:  # noqa: N802
        if not self._gate():
            return
        path = urlparse(self.path).path
        origin_header = self.headers.get("Origin")
        cors = self._cors_origin()
        if path == "/v1/pair":
            self._pair(origin_header, cors)
            return
        if path == "/v1/launch":
            if not self._require_auth(cors):
                return
            self._launch(cors)
            return
        self._send(404, _json_error("not_found"), cors)

    def _require_auth(self, cors: str | None) -> bool:
        """Pinned chrome-extension Origin is enough. CLI (no Origin) needs the secret."""
        origin_header = self.headers.get("Origin")
        if origin_header:
            if not cors:
                self._send(403, _json_error("forbidden_origin"), None)
                return False
            return True
        provided = self.headers.get("X-PlexVLC-Secret") or ""
        if not self.app.cfg.helper_secret or not secrets_equal(provided, self.app.cfg.helper_secret):
            self._send(401, _json_error("unauthorized"), cors)
            return False
        return True

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > MAX_BODY:
            raise ResolveError("bad_request")
        return self.rfile.read(length) if length else b""

    def _health(self) -> bytes:
        return _json_ok(
            {
                "service": "plexvlc",
                "version": __version__,
                "player": self.app.cfg.player.name,
                "listen": self.app.listen,
                "logPath": str(self.app.paths.log),
            }
        )

    def _pair(self, origin_header: str | None, cors: str | None) -> None:
        if not origin_header:
            self._send(403, _json_error("forbidden_origin"), None)
            return
        if not cors:
            self._send(403, _json_error("forbidden_origin"), None)
            return
        if self.app.pairing.rate_limited():
            self._send(401, _json_error("bad_pair_code"), cors)
            return
        try:
            raw = self._read_body()
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError, ResolveError):
            self._send(400, _json_error("bad_request"), cors)
            return
        code = (data or {}).get("code") if isinstance(data, dict) else None
        if not isinstance(code, str) or not self.app.pairing.consume(code):
            self._send(401, _json_error("bad_pair_code"), cors)
            return
        body = _json_ok({"secret": self.app.cfg.helper_secret, "port": self.app.cfg.listen_port})
        self._send(200, body, cors)

    def _launch(self, cors: str | None) -> None:
        try:
            raw = self._read_body()
            data = json.loads(raw.decode("utf-8"))
            req = validate_launch_body(data)
        except (ValueError, UnicodeDecodeError, ResolveError) as exc:
            err = getattr(exc, "error", "bad_request")
            self._send(400, _json_error(err), cors)
            return
        try:
            plan = self._resolve(req)
            exe = resolve_executable(self.app.cfg.player)
            ctx = ExpandContext(
                paths=plan.paths,
                urls=plan.urls,
                title=plan.title,
                start_seconds=plan.start_seconds,
                sub_file=plan.sub_file,
            )
            argv = build_argv(self.app.cfg.player, ctx, exe)
            launch(argv)
        except ResolveError as exc:
            self._send(exc.http, _json_error(exc.error), cors)
            return
        except PlexError as exc:
            self._send(exc.http, _json_error(exc.error), cors)
            return
        except PlayerError as exc:
            self._send(exc.http, _json_error(exc.error), cors)
            return
        except Exception:
            log.exception("unexpected launch failure")
            self._send(500, _json_error("player_launch_failed"), cors)
            return
        self._send(200, _success(plan, str(exe), self.app.cfg.player.name), cors)

    def _resolve(self, req: dict) -> LaunchPlan:
        from plexvlc.auth import SsrfError, coerce_pms_base_url

        token = req["plexToken"]
        pms = coerce_pms_base_url(req.get("pmsBaseUrl") or None)
        try:
            origin = pick_stream_base(
                req.get("machineIdentifier") or None,
                pms,
                token,
                self.app.cfg.client_identifier,
            )
            log.info("resolved PMS origin %s for ratingKey %s", origin, req["ratingKey"])
            payload = fetch_metadata(origin, req["ratingKey"], token, self.app.cfg.client_identifier)
        except SsrfError as exc:
            raise ResolveError(exc.error, 400) from exc
        return resolve_launch(
            payload,
            stream_base=origin,
            token=token,
            media_id=plex_int(req.get("mediaId")),
            part_id=plex_int(req.get("partId")),
            offset_ms=plex_int(req.get("offsetMs")) if req.get("offsetMs") is not None else None,
            client_id=self.app.cfg.client_identifier,
        )


def _success(plan: LaunchPlan, executable: str, player: str) -> bytes:
    return _json_ok(
        {
            "mode": plan.mode,
            "player": player,
            "title": plan.title,
            "itemType": plan.item_type,
            "ratingKey": plan.rating_key,
            "parts": len(plan.part_ids) or (len(plan.paths) or len(plan.urls)),
            "startSeconds": plan.start_seconds,
            "executable": executable,
            "pathHint": plan.path_hint,
        }
    )


def make_server(app: App, port: int | None = None) -> ThreadingHTTPServer:
    Handler.app = app
    bind_port = app.cfg.listen_port if port is None else port
    httpd = ThreadingHTTPServer(("127.0.0.1", bind_port), Handler)
    actual = httpd.server_address[1]
    app.cfg.listen_port = actual
    app.listen = f"127.0.0.1:{actual}"
    return httpd
