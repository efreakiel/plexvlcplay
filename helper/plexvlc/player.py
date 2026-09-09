"""Argument templates and process launch."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from plexvlc.config import PlayerConfig
from plexvlc.windows_vlc import discover_vlc

log = logging.getLogger("plexvlc")

CONTROL_RE = re.compile(r"[\x00-\x1f]")


class PlayerError(Exception):
    def __init__(self, error: str, http: int = 503):
        super().__init__(error)
        self.error = error
        self.http = http


@dataclass
class ExpandContext:
    paths: list[str]
    urls: list[str]
    title: str
    start_seconds: int
    sub_file: str | None = None
    sub_url: str | None = None


def sanitize_title(title: str) -> str:
    s = CONTROL_RE.sub("", title or "")
    s = s.lstrip("-").strip()
    return s[:200]


def expand(template: list[str], ctx: ExpandContext, player_name: str) -> list[str]:
    out: list[str] = []
    for arg in template:
        if arg in ("{path}", "{paths}"):
            out.extend(ctx.paths)
            continue
        if arg in ("{url}", "{urls}"):
            out.extend(ctx.urls)
            continue
        if "{sub_file}" in arg and not ctx.sub_file:
            continue
        if "{sub_url}" in arg and not ctx.sub_url:
            continue
        s = arg
        s = s.replace("{start_seconds}", str(ctx.start_seconds))
        s = s.replace("{title}", sanitize_title(ctx.title))
        s = s.replace("{sub_file}", ctx.sub_file or "")
        s = s.replace("{sub_url}", ctx.sub_url or "")
        s = s.replace("{path}", ctx.paths[0] if ctx.paths else "")
        s = s.replace("{url}", ctx.urls[0] if ctx.urls else "")
        out.append(s)

    if player_name.strip().lower() in {"vlc", "mpv"}:
        media = set(ctx.paths) | set(ctx.urls)
        for i, a in enumerate(out):
            if a in media:
                out.insert(i, "--")
                break
    return out


def resolve_executable(player: PlayerConfig) -> Path:
    configured = player.executable.strip()
    name = player.name.strip().lower()
    if name == "vlc":
        found = discover_vlc(configured or None)
        if found:
            return found
        raise PlayerError("player_not_found", 503)
    if configured:
        p = Path(configured)
        if p.is_file():
            return p
        raise PlayerError("player_not_found", 503)
    raise PlayerError("player_not_found", 503)


def build_argv(player: PlayerConfig, ctx: ExpandContext, executable: Path) -> list[str]:
    template = player.args_file if ctx.paths else player.args_url
    expanded = expand(template, ctx, player.name)
    extra = list(player.args_extra or [])
    return [str(executable), *extra, *expanded]


def launch(argv: list[str]) -> None:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen(argv, close_fds=True, creationflags=flags)
    except FileNotFoundError as exc:
        raise PlayerError("player_not_found", 503) from exc
    except OSError as exc:
        raise PlayerError("player_launch_failed", 500) from exc
