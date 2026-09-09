"""Python port of extension/content.js parsePlexLocation. Keep in sync."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

DISCOVER_RE = re.compile(r"^/library/metadata/([0-9a-f]{20,})$", re.IGNORECASE)
LOCAL_RE = re.compile(r"^/library/metadata/([0-9]+)$")
MACHINE_RE = re.compile(r"/(?:server|media)/([^/]+)/")


def parse_plex_location(href: str) -> dict:
    try:
        url = urlparse(href)
    except ValueError:
        return {"error": "bad_key"}
    hash_part = url.fragment or ""
    if hash_part.startswith("!"):
        hash_part = hash_part[1:]
    if "?" in hash_part:
        path, query = hash_part.split("?", 1)
    else:
        path, query = hash_part, ""
    params = parse_qs(query, keep_blank_values=True)
    key_list = params.get("key")
    if not key_list:
        return {"error": "no_key"}
    key = unquote(key_list[0])
    m = LOCAL_RE.fullmatch(key)
    if m:
        result: dict = {"ratingKey": m.group(1)}
    else:
        d = DISCOVER_RE.fullmatch(key)
        if d:
            return {"error": "unsupported_discover"}
        return {"error": "bad_key"}
    mm = MACHINE_RE.search(path)
    if mm:
        result["machineIdentifier"] = mm.group(1)
    else:
        server = params.get("server")
        if server:
            result["machineIdentifier"] = unquote(server[0])
    return result
