"""Turn PMS metadata into a local-file or stream LaunchPlan."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from plexvlc.plex import PlexError, plex_bool, plex_int, plex_str

log = logging.getLogger("plexvlc")

SUPPORTED_TYPES = {"movie", "episode", "clip"}
TEXT_SUB_CODECS = {"srt", "ass", "ssa", "vtt", "webvtt", "mov_text", "smi", "subrip"}
IMAGE_SUB_CODECS = {"pgs", "vobsub", "dvbsub", "dvd", "idx"}
SUB_EXT = {"srt": "srt", "ass": "ass", "ssa": "ass", "vtt": "vtt", "webvtt": "vtt", "mov_text": "srt", "smi": "srt", "subrip": "srt"}
MAX_SUB_BYTES = 4 * 1024 * 1024


class ResolveError(Exception):
    def __init__(self, error: str, http: int = 400):
        super().__init__(error)
        self.error = error
        self.http = http


@dataclass
class LaunchPlan:
    mode: str
    paths: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    title: str = ""
    start_seconds: int = 0
    sub_file: str | None = None
    media_id: int | None = None
    part_ids: list[int] = field(default_factory=list)
    path_hint: str = ""
    item_type: str = ""
    rating_key: str = ""


FetchFn = Callable[[str, dict[str, str], float], tuple[int, bytes]]


def metadata_item(payload: dict) -> dict:
    mc = payload.get("MediaContainer") if isinstance(payload, dict) else None
    if not isinstance(mc, dict):
        raise ResolveError("no_media")
    items = mc.get("Metadata")
    if not isinstance(items, list) or not items:
        raise ResolveError("no_media")
    item = items[0]
    if not isinstance(item, dict):
        raise ResolveError("no_media")
    return item


def format_title(md: dict) -> str:
    title = plex_str(md.get("title")) or "Plex item"
    if plex_str(md.get("type")) == "episode" and md.get("grandparentTitle"):
        gp = plex_str(md["grandparentTitle"])
        pi = plex_int(md.get("parentIndex"))
        idx = plex_int(md.get("index"))
        if pi is not None and idx is not None:
            return f"{gp} - s{pi:02d}e{idx:02d} - {title}"
        return f"{gp} - {title}"
    return title


def start_seconds_for(md: dict, offset_ms: int | None) -> int:
    offset = offset_ms if offset_ms is not None else (plex_int(md.get("viewOffset")) or 0)
    duration = plex_int(md.get("duration")) or 0
    if duration and 0 < offset < 0.9 * duration:
        return offset // 1000
    return 0


def _select_media(md: dict, media_id: int | None) -> dict:
    media_list = md.get("Media") or []
    if not isinstance(media_list, list) or not media_list:
        raise ResolveError("no_media")
    if media_id is not None:
        for m in media_list:
            if isinstance(m, dict) and plex_int(m.get("id")) == media_id:
                return m
        raise ResolveError("not_found", 502)
    first = media_list[0]
    if not isinstance(first, dict):
        raise ResolveError("no_media")
    return first


def _select_parts(media: dict, part_id: int | None) -> list[dict]:
    parts = media.get("Part") or []
    if not isinstance(parts, list):
        raise ResolveError("no_playable_part")
    cleaned = [p for p in parts if isinstance(p, dict)]
    if part_id is not None:
        for p in cleaned:
            if plex_int(p.get("id")) == part_id:
                return [p]
        raise ResolveError("not_found", 502)
    if not cleaned:
        raise ResolveError("no_playable_part")
    return cleaned


def _stream_url(stream_base: str, part_key: str, token: str) -> str:
    base = stream_base.rstrip("/")
    key = part_key if part_key.startswith("/") else "/" + part_key
    sep = "&" if "?" in key else "?"
    return f"{base}{key}{sep}X-Plex-Token={token}"


def _hint_from_url(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "x-plex-token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def _cleanup_temp_subs(temp_dir: Path) -> None:
    if not temp_dir.is_dir():
        return
    for pattern in ("*.srt", "*.ass", "*.vtt"):
        for p in temp_dir.glob(pattern):
            try:
                p.unlink()
            except OSError:
                pass


def _download_sub(
    stream_base: str,
    token: str,
    rating_key: str,
    streams: list[dict],
    *,
    fetch: FetchFn | None,
    temp_dir: Path,
    client_id: str,
) -> str | None:
    selected = None
    for s in streams:
        if plex_int(s.get("streamType")) == 3 and plex_bool(s.get("selected")):
            selected = s
            break
    if not selected:
        return None
    codec = plex_str(selected.get("codec")).lower()
    if codec in IMAGE_SUB_CODECS:
        return None
    if codec not in TEXT_SUB_CODECS:
        return None
    key = plex_str(selected.get("key"))
    if not key:
        return None
    url = stream_base.rstrip("/") + (key if key.startswith("/") else "/" + key)
    from plexvlc.plex import _headers

    headers = _headers(token, client_id)
    try:
        if fetch is not None:
            status, body = fetch(url, headers, 10.0)
        else:
            from plexvlc.plex import http_get

            status, body = http_get(url, headers, 10.0, max_bytes=MAX_SUB_BYTES, ssrf=True)
    except Exception:
        log.warning("subtitle download failed; continuing without --sub-file")
        return None
    if status != 200 or not body or len(body) > MAX_SUB_BYTES:
        log.warning("subtitle download status=%s size=%s; continuing without --sub-file", status, len(body) if body else 0)
        return None
    _cleanup_temp_subs(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    lang = plex_str(selected.get("languageCode")) or "und"
    ext = SUB_EXT.get(codec, "srt")
    dest = temp_dir / f"{rating_key}.{lang}.{ext}"
    try:
        dest.write_bytes(body)
    except OSError:
        log.warning("could not write subtitle temp file; continuing without --sub-file")
        return None
    return str(dest)


def resolve_launch(
    payload: dict,
    *,
    stream_base: str,
    token: str,
    media_id: int | None = None,
    part_id: int | None = None,
    offset_ms: int | None = None,
    fetch: FetchFn | None = None,
    temp_dir: Path | None = None,
    client_id: str = "plexvlc",
) -> LaunchPlan:
    md = metadata_item(payload)
    item_type = plex_str(md.get("type"))
    if item_type not in SUPPORTED_TYPES:
        raise ResolveError("unsupported_type")
    rating_key = plex_str(md.get("ratingKey"))
    media = _select_media(md, media_id)
    parts = _select_parts(media, part_id)

    file_paths: list[str] = []
    urls: list[str] = []
    part_ids: list[int] = []
    streams_for_sub: list[dict] = []

    for part in parts:
        pid = plex_int(part.get("id"))
        if pid is not None:
            part_ids.append(pid)
        file_attr = plex_str(part.get("file"))
        key = plex_str(part.get("key"))
        if file_attr and Path(file_attr).is_file() and os.access(file_attr, os.R_OK):
            file_paths.append(file_attr)
        elif key and stream_base:
            urls.append(_stream_url(stream_base, key, token))
        streams = part.get("Stream") or []
        if isinstance(streams, list):
            streams_for_sub.extend(s for s in streams if isinstance(s, dict))

    if file_paths:
        mode = "file"
        urls = []
    elif urls:
        mode = "url"
    else:
        raise ResolveError("no_playable_part")

    title = format_title(md)
    start = start_seconds_for(md, offset_ms)
    tdir = temp_dir if temp_dir is not None else Path(tempfile.gettempdir()) / "plexvlc"
    sub_file = _download_sub(
        stream_base,
        token,
        rating_key or "item",
        streams_for_sub,
        fetch=fetch,
        temp_dir=tdir,
        client_id=client_id,
    )
    if mode == "file":
        hint = file_paths[0]
    else:
        hint = _hint_from_url(urls[0])
    return LaunchPlan(
        mode=mode,
        paths=file_paths if mode == "file" else [],
        urls=urls if mode == "url" else [],
        title=title,
        start_seconds=start,
        sub_file=sub_file,
        media_id=plex_int(media.get("id")),
        part_ids=part_ids,
        path_hint=hint,
        item_type=item_type,
        rating_key=rating_key,
    )
