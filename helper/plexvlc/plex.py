"""Plex HTTP client: no redirects, TLS verify on, JSON coercion, stream-base pick."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from plexvlc.auth import SsrfError, assert_resolved_ips_allowed, check_pms_origin, redact

log = logging.getLogger("plexvlc")

PLEX_TV_RESOURCES = "https://plex.tv/api/v2/resources?includeHttps=1&includeRelay=1"
DASHED_PLEX_DIRECT = __import__("re").compile(
    r"^(\d{1,3}(?:-\d{1,3}){3})\.[a-z0-9]+\.plex\.direct$",
    __import__("re").IGNORECASE,
)


class PlexError(Exception):
    def __init__(self, error: str, http: int = 502):
        super().__init__(error)
        self.error = error
        self.http = http


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def plex_bool(v: Any) -> bool:
    return v in (True, 1, "1", "true", "True")


def plex_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def plex_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _headers(token: str | None, client_id: str) -> dict[str, str]:
    from plexvlc import __version__

    h = {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Product": "plexvlc",
        "X-Plex-Version": __version__,
        "X-Plex-Platform": "Windows",
        "X-Plex-Device-Name": "plexvlc",
    }
    if token:
        h["X-Plex-Token"] = token
    return h


def http_get(
    url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    max_bytes: int = 8_000_000,
    ssrf: bool = True,
) -> tuple[int, bytes]:
    if ssrf:
        parsed = check_pms_origin(_origin_of(url))
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        assert_resolved_ips_allowed(parsed.hostname or "", port)
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        NoRedirectHandler,
        urllib.request.HTTPSHandler(context=ctx),
    )
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            body = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        # HTTPError is also the 3xx path when redirects are disabled
        data = b""
        try:
            data = exc.read(max_bytes + 1)
        except Exception:
            data = b""
        if 300 <= exc.code < 400:
            raise PlexError("plex_unreachable", 502) from exc
        return exc.code, data
    except ssl.SSLError as exc:
        raise PlexError("plex_tls_failed", 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PlexError("plex_unreachable", 502) from exc
    if len(body) > max_bytes:
        raise PlexError("plex_unreachable", 502)
    return status, body


def _origin_of(url: str) -> str:
    p = urllib.parse.urlparse(url)
    netloc = p.netloc
    return f"{p.scheme}://{netloc}"


def metadata_url(origin: str, rating_key: str) -> str:
    origin = origin.rstrip("/")
    return f"{origin}/library/metadata/{rating_key}?checkFiles=1"


def identity_url(origin: str) -> str:
    return origin.rstrip("/") + "/identity"


def fetch_json(
    url: str,
    token: str | None,
    client_id: str,
    timeout: float = 10.0,
    *,
    ssrf: bool = True,
) -> Any:
    status, body = http_get(url, _headers(token, client_id), timeout, ssrf=ssrf)
    if status in (401, 403):
        raise PlexError("plex_unauthorized", 502)
    if status == 404:
        raise PlexError("not_found", 502)
    if status != 200:
        raise PlexError("plex_unreachable", 502)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlexError("plex_unreachable", 502) from exc


def probe_identity(
    origin: str,
    token: str | None,
    client_id: str,
    timeout: float = 2.0,
) -> dict | None:
    try:
        data = fetch_json(identity_url(origin), token, client_id, timeout=timeout, ssrf=True)
    except (PlexError, SsrfError) as exc:
        log.debug("identity probe failed for %s: %s", origin, exc)
        return None
    mc = data.get("MediaContainer") if isinstance(data, dict) else None
    if not isinstance(mc, dict):
        return None
    return mc


def fetch_resources(token: str, client_id: str, timeout: float = 10.0) -> list[dict]:
    status, body = http_get(
        PLEX_TV_RESOURCES,
        _headers(token, client_id),
        timeout,
        ssrf=False,
    )
    if status in (401, 403):
        raise PlexError("plex_unauthorized", 502)
    if status != 200:
        log.warning("plex.tv resources returned %s", status)
        return []
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def device_is_server(device: dict) -> bool:
    provides = plex_str(device.get("provides"))
    tokens = {t.strip() for t in provides.split(",")}
    return "server" in tokens


def dashed_to_ipv4(host: str) -> str | None:
    m = DASHED_PLEX_DIRECT.match(host or "")
    if not m:
        return None
    parts = m.group(1).split("-")
    if len(parts) != 4:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n > 255 for n in nums):
        return None
    return ".".join(str(n) for n in nums)


ProbeFn = Callable[[str, str | None], dict | None]
ResourcesFn = Callable[[], list[dict]]


def pick_stream_base(
    machine_id: str | None,
    pms_base_url: str | None,
    token: str,
    client_id: str,
    *,
    probe: ProbeFn | None = None,
    resources: ResourcesFn | None = None,
) -> str:
    """Return a reachable origin for metadata + stream URLs."""

    def _probe(origin: str, tok: str | None) -> dict | None:
        if probe is not None:
            return probe(origin, tok)
        return probe_identity(origin, tok, client_id)

    def match(mc: dict | None) -> bool:
        if not mc:
            return False
        mid = plex_str(mc.get("machineIdentifier"))
        if machine_id:
            return mid == machine_id
        return True

    candidates: list[tuple[str, str | None]] = []

    loopback = "http://127.0.0.1:32400"
    candidates.append((loopback, token))
    if pms_base_url:
        try:
            parsed = urllib.parse.urlparse(pms_base_url)
        except ValueError:
            parsed = None
        if parsed and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port and parsed.port != 32400:
            candidates.append((f"http://127.0.0.1:{parsed.port}", token))

        if parsed and parsed.hostname:
            ipv4 = dashed_to_ipv4(parsed.hostname)
            if ipv4:
                from plexvlc.auth import ip_allowed

                if ip_allowed(ipv4, plex_direct=False):
                    port = parsed.port or 32400
                    candidates.append((f"http://{ipv4}:{port}", token))

    def try_list(items: list[tuple[str, str | None]]) -> str | None:
        seen: set[str] = set()
        for origin, tok in items:
            origin = origin.rstrip("/")
            if origin in seen:
                continue
            seen.add(origin)
            try:
                check_pms_origin(origin)
            except SsrfError:
                continue
            mc = _probe(origin, tok)
            if match(mc):
                return origin
        return None

    hit = try_list(candidates)
    if hit:
        return hit

    devices: list[dict] = []
    try:
        devices = resources() if resources is not None else fetch_resources(token, client_id)
    except PlexError:
        devices = []

    http_local: list[tuple[str, str | None]] = []
    https_local: list[tuple[str, str | None]] = []
    for device in devices:
        if not isinstance(device, dict) or not device_is_server(device):
            continue
        cid = plex_str(device.get("clientIdentifier"))
        if machine_id and cid != machine_id:
            continue
        access = plex_str(device.get("accessToken")) or token
        for conn in device.get("connections") or []:
            if not isinstance(conn, dict):
                continue
            if plex_bool(conn.get("relay")):
                continue
            if not plex_bool(conn.get("local")):
                continue
            uri = plex_str(conn.get("uri")).rstrip("/")
            if not uri:
                proto = plex_str(conn.get("protocol")) or "http"
                addr = plex_str(conn.get("address"))
                port = plex_int(conn.get("port")) or 32400
                if not addr:
                    continue
                uri = f"{proto}://{addr}:{port}"
            if uri.startswith("http://"):
                http_local.append((uri, access))
            elif uri.startswith("https://"):
                https_local.append((uri, access))

    hit = try_list(http_local)
    if hit:
        return hit
    hit = try_list(https_local)
    if hit:
        return hit

    if pms_base_url:
        try:
            parsed = check_pms_origin(pms_base_url if "://" in pms_base_url else "")
            origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        except (SsrfError, ValueError):
            origin = None
        if origin:
            mc = _probe(origin, token)
            if match(mc):
                return origin

    raise PlexError("plex_unreachable", 502)


def fetch_metadata(origin: str, rating_key: str, token: str, client_id: str) -> dict:
    url = metadata_url(origin, rating_key)
    if "includeElements" in url:
        raise RuntimeError("includeElements must not be used")
    data = fetch_json(url, token, client_id, timeout=10.0, ssrf=True)
    log.debug("fetched metadata %s", redact(url))
    return data
