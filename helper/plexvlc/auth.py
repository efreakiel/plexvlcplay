"""Secrets, origin pinning, SSRF allowlist, and log redaction."""

from __future__ import annotations

import hmac
import ipaddress
import logging
import re
import socket
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("plexvlc")

CHROME_ID_RE = re.compile(r"^[a-p]{32}$")
# plex.direct labels are usually hex, but the DNS wildcard accepts any 32-char
# token and IPv6 forms use extra dashed groups. Allow DNS-safe labels only.
PLEX_DIRECT_RE = re.compile(r"^(?:[a-z0-9-]+\.)+plex\.direct$", re.IGNORECASE)
NON_PMS_HOSTS = {
    "app.plex.tv",
    "plex.tv",
    "www.plex.tv",
    "clients.plex.tv",
    "metadata.provider.plex.tv",
    "discover.provider.plex.tv",
    "vod.provider.plex.tv",
    "tv.plex.provider.metadata",
}
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LINK_LOCAL_V4 = ipaddress.ip_network("169.254.0.0/16")
ZERO_V4 = ipaddress.ip_network("0.0.0.0/8")
LINK_LOCAL_V6 = ipaddress.ip_network("fe80::/10")

_TOKEN_QUERY_RE = re.compile(r"(X-Plex-Token=)([^&\s\"']+)", re.IGNORECASE)
_TOKEN_HEADER_RE = re.compile(r"(X-Plex-Token:\s*)(\S+)", re.IGNORECASE)
_SECRET_HEADER_RE = re.compile(r"(X-PlexVLC-Secret:\s*)(\S+)", re.IGNORECASE)
_JSON_TOKEN_RE = re.compile(r'("plexToken"\s*:\s*")[^"]+', re.IGNORECASE)
_JSON_SECRET_RE = re.compile(r'("helper_secret"\s*:\s*")[^"]+', re.IGNORECASE)
_JSON_ACCESS_RE = re.compile(r'("accessToken"\s*:\s*")[^"]+', re.IGNORECASE)


class SsrfError(ValueError):
    error = "ssrf_blocked"


class AuthError(ValueError):
    def __init__(self, error: str, http: int = 401):
        super().__init__(error)
        self.error = error
        self.http = http


def redact(text: str) -> str:
    if not text:
        return text
    s = _TOKEN_QUERY_RE.sub(r"\1***", text)
    s = _TOKEN_HEADER_RE.sub(r"\1***", s)
    s = _SECRET_HEADER_RE.sub(r"\1***", s)
    s = _JSON_TOKEN_RE.sub(r"\1***", s)
    s = _JSON_SECRET_RE.sub(r"\1***", s)
    s = _JSON_ACCESS_RE.sub(r"\1***", s)
    return s


def is_chrome_extension_id(ext_id: str) -> bool:
    return bool(CHROME_ID_RE.fullmatch(ext_id or ""))


def parse_extension_origin(origin: str | None) -> str | None:
    """Return the 32-char Chrome id if origin is a well-formed chrome-extension URL."""
    if not origin:
        return None
    if not origin.startswith("chrome-extension://"):
        return None
    rest = origin[len("chrome-extension://") :]
    ext_id = rest.split("/")[0].split("?")[0].lower()
    if not is_chrome_extension_id(ext_id):
        return None
    return ext_id


def origin_is_pinned(origin: str | None, allowed_ids: list[str]) -> bool:
    ext_id = parse_extension_origin(origin)
    if ext_id is None:
        return False
    allowed = {i.lower() for i in allowed_ids if is_chrome_extension_id(i)}
    return ext_id in allowed


def host_header_ok(host: str | None, port: int) -> bool:
    if not host:
        return False
    value = host.strip().split("%")[0]
    if ".." in value or value.count(":") > 1:
        # IPv6 Host headers are not used; reject extras like 127.0.0.1.evil.com
        if "]" not in value:
            return False
    allowed = {
        f"127.0.0.1:{port}",
        f"localhost:{port}",
        "127.0.0.1",
        "localhost",
    }
    return value.lower() in {a.lower() for a in allowed}


def peer_is_loopback(addr: str) -> bool:
    host = addr.split("%")[0]
    if host.startswith("::ffff:"):
        host = host[7:]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.lower() in {"localhost", "127.0.0.1"}
    return ip.is_loopback


def _ip_from_host(host: str) -> ipaddress._BaseAddress | None:
    h = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


def ip_allowed(ip_str: str, *, plex_direct: bool) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0].strip("[]"))
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    if ip.version == 4 and ip in ZERO_V4:
        return False
    if ip.version == 4 and ip in LINK_LOCAL_V4:
        return False
    if ip.version == 6 and ip in LINK_LOCAL_V6:
        return False
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    if ip.is_link_local:
        return False
    if ip.version == 4 and ip.is_private:
        return True
    if plex_direct and ip.version == 4 and ip.is_global:
        return True
    return False


def this_machine_hostnames() -> set[str]:
    names: set[str] = set()
    try:
        names.add(socket.gethostname().lower())
    except OSError:
        pass
    try:
        names.add(socket.getfqdn().lower())
    except OSError:
        pass
    labels = {n.split(".")[0] for n in names if n}
    names.update(labels)
    names.discard("")
    names.discard("localhost")
    return names


def is_this_machine_hostname(host: str) -> bool:
    h = host.strip().strip("[]").lower()
    if not h or h in ("localhost", "127.0.0.1", "::1"):
        return False
    names = this_machine_hostnames()
    if h in names:
        return True
    return h.split(".")[0] in names


def classify_hostname(host: str) -> str | None:
    """Return 'loopback', 'rfc1918', 'plex_direct', 'local_name', or None (deny)."""
    h = host.strip().strip("[]").lower()
    if h in ("localhost",):
        return "loopback"
    ip = _ip_from_host(h)
    if ip is not None:
        if ip.is_loopback:
            return "loopback"
        if not ip_allowed(str(ip), plex_direct=False):
            return None
        if ip.version == 4 and ip.is_private:
            return "rfc1918"
        return None
    if PLEX_DIRECT_RE.fullmatch(h):
        return "plex_direct"
    if is_this_machine_hostname(h):
        return "local_name"
    return None


def check_pms_origin(url: str) -> urllib.parse.ParseResult:
    """Validate a user-supplied PMS origin. Does not perform DNS.

    Path must be empty or `/`. No userinfo, no fragment.
    """
    if not isinstance(url, str) or len(url) > 256:
        raise SsrfError("ssrf_blocked")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError("ssrf_blocked")
    if parsed.username or parsed.password or parsed.fragment:
        raise SsrfError("ssrf_blocked")
    if parsed.path not in ("", "/"):
        raise SsrfError("ssrf_blocked")
    if parsed.query:
        raise SsrfError("ssrf_blocked")
    host = parsed.hostname
    if not host:
        raise SsrfError("ssrf_blocked")
    kind = classify_hostname(host)
    if kind is None:
        raise SsrfError("ssrf_blocked")
    return parsed


def coerce_pms_base_url(url: str | None) -> str | None:
    """Turn a client-supplied PMS URL into an allowlisted origin, or None.

    Never raises. A weird origin (app.plex.tv, PC hostname we cannot classify,
    URL with a path, …) is skipped so pick_stream_base can still try loopback.
    """
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    if raw.lower() in {"", "null", "undefined", "none"}:
        return None
    if "://" not in raw:
        return None
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if host in NON_PMS_HOSTS or host.endswith(".plex.tv") or host.endswith(".plex.services"):
        log.info("ignoring non-PMS origin host=%s", host)
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if len(origin) > 256:
        log.info("ignoring oversized pmsBaseUrl host=%s", host)
        return None
    try:
        check_pms_origin(origin)
    except SsrfError:
        log.info("ignoring disallowed pmsBaseUrl host=%s", host)
        return None
    return origin


def resolve_host_ips(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def assert_resolved_ips_allowed(host: str, port: int) -> list[str]:
    kind = classify_hostname(host)
    if kind is None:
        raise SsrfError("ssrf_blocked")
    ip_literal = _ip_from_host(host)
    if ip_literal is not None:
        if not ip_allowed(str(ip_literal), plex_direct=False):
            raise SsrfError("ssrf_blocked")
        return [str(ip_literal)]
    try:
        ips = resolve_host_ips(host, port)
    except OSError as exc:
        raise SsrfError("ssrf_blocked") from exc
    if not ips:
        raise SsrfError("ssrf_blocked")
    plex_direct = kind == "plex_direct"
    for ip in ips:
        if not ip_allowed(ip, plex_direct=plex_direct):
            raise SsrfError("ssrf_blocked")
    return ips


def secrets_equal(a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass
class PairingStore:
    ttl_seconds: int = 300
    rate_per_minute: int = 5
    code: str | None = None
    expires_at: float = 0.0
    attempts: deque[float] = field(default_factory=deque)

    def generate(self, code: str) -> str:
        self.code = code
        self.expires_at = time.time() + self.ttl_seconds
        return code

    def active(self) -> bool:
        return bool(self.code) and time.time() < self.expires_at

    def rate_limited(self) -> bool:
        now = time.time()
        while self.attempts and now - self.attempts[0] > 60:
            self.attempts.popleft()
        if len(self.attempts) >= self.rate_per_minute:
            return True
        self.attempts.append(now)
        return False

    def consume(self, submitted: str) -> bool:
        if not self.active() or not submitted:
            return False
        left = self.code or ""
        right = submitted.strip().upper()
        if len(left) != len(right):
            ok = False
        else:
            ok = hmac.compare_digest(left.upper(), right)
        if ok:
            self.code = None
            self.expires_at = 0.0
        return ok
