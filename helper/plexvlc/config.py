"""Load and persist %APPDATA%\\plexvlc\\config.json."""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from plexvlc.auth import is_chrome_extension_id

log = logging.getLogger("plexvlc")

CURRENT_VERSION = 1
DEFAULT_PORT = 18765
PLACEHOLDER_ID = "a" * 32

DEFAULT_ARGS_FILE = ["--start-time={start_seconds}", "--sub-file={sub_file}", "{paths}"]
DEFAULT_ARGS_URL = ["--start-time={start_seconds}", "--sub-file={sub_file}", "{urls}"]
DEFAULT_ARGS_EXTRA = ["--no-video-title-show"]


class ConfigError(Exception):
    """Process-start failure; never an HTTP 500."""


@dataclass
class PlayerConfig:
    name: str = "VLC"
    executable: str = ""
    args_file: list[str] = field(default_factory=lambda: list(DEFAULT_ARGS_FILE))
    args_url: list[str] = field(default_factory=lambda: list(DEFAULT_ARGS_URL))
    args_extra: list[str] = field(default_factory=lambda: list(DEFAULT_ARGS_EXTRA))


@dataclass
class Config:
    version: int = CURRENT_VERSION
    listen_port: int = DEFAULT_PORT
    helper_secret: str = ""
    client_identifier: str = ""
    player: PlayerConfig = field(default_factory=PlayerConfig)
    allowed_extension_ids: list[str] = field(default_factory=list)
    log_level: str = "INFO"

    def to_public_dict(self) -> dict:
        d = self.to_dict()
        d["helper_secret"] = "***"
        return d

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "listen_port": self.listen_port,
            "helper_secret": self.helper_secret,
            "client_identifier": self.client_identifier,
            "player": {
                "name": self.player.name,
                "executable": self.player.executable,
                "args_file": list(self.player.args_file),
                "args_url": list(self.player.args_url),
                "args_extra": list(self.player.args_extra),
            },
            "allowed_extension_ids": list(self.allowed_extension_ids),
            "log_level": self.log_level,
        }


@dataclass
class Paths:
    root: Path
    config: Path
    log: Path
    pid: Path
    pair_code: Path

    @classmethod
    def default(cls) -> Paths:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ConfigError("APPDATA is not set; cannot locate config directory")
        return cls.from_root(Path(appdata) / "plexvlc")

    @classmethod
    def from_root(cls, root: Path) -> Paths:
        root = Path(root)
        return cls(
            root=root,
            config=root / "config.json",
            log=root / "plexvlc.log",
            pid=root / "helper.pid",
            pair_code=root / "pair.code",
        )


def repo_root() -> Path:
    # helper/plexvlc/config.py → parents[2] = repo
    return Path(__file__).resolve().parents[2]


def bundled_extension_id() -> str | None:
    path = repo_root() / "extension" / "EXTENSION_ID.txt"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip().lower()
    return value if is_chrome_extension_id(value) else None


def _validate_templates(player: PlayerConfig) -> None:
    for label, args in (("args_file", player.args_file), ("args_url", player.args_url)):
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ConfigError(f"player.{label} must be a list of strings")
        has_path = "{path}" in args
        has_paths = "{paths}" in args
        has_url = "{url}" in args
        has_urls = "{urls}" in args
        if has_path and has_paths:
            raise ConfigError(f"player.{label} must not contain both {{path}} and {{paths}}")
        if has_url and has_urls:
            raise ConfigError(f"player.{label} must not contain both {{url}} and {{urls}}")
    if "{path}" in player.args_extra or "{paths}" in player.args_extra:
        # extra is prepended; allowing media placeholders there is confusing
        pass


def parse_config(data: dict) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("config.json must be a JSON object")
    version = data.get("version")
    if version != CURRENT_VERSION:
        raise ConfigError(f"unknown config.version {version!r}; expected {CURRENT_VERSION}")
    if "listen_host" in data:
        raise ConfigError("listen_host is not supported; bind is hardcoded to 127.0.0.1")
    port = data.get("listen_port", DEFAULT_PORT)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("listen_port must be an integer 1–65535")
    secret = data.get("helper_secret", "")
    if not isinstance(secret, str):
        raise ConfigError("helper_secret must be a string")
    client_id = data.get("client_identifier", "")
    if not isinstance(client_id, str):
        raise ConfigError("client_identifier must be a string")
    raw_player = data.get("player") or {}
    if not isinstance(raw_player, dict):
        raise ConfigError("player must be an object")
    player = PlayerConfig(
        name=str(raw_player.get("name") or "VLC"),
        executable=str(raw_player.get("executable") or ""),
        args_file=list(raw_player.get("args_file") or DEFAULT_ARGS_FILE),
        args_url=list(raw_player.get("args_url") or DEFAULT_ARGS_URL),
        args_extra=list(raw_player.get("args_extra") or DEFAULT_ARGS_EXTRA),
    )
    _validate_templates(player)
    ids = data.get("allowed_extension_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ConfigError("allowed_extension_ids must be a list of strings")
    cleaned: list[str] = []
    for i in ids:
        i = i.strip().lower()
        if i == PLACEHOLDER_ID:
            continue
        if not is_chrome_extension_id(i):
            raise ConfigError(f"invalid Chrome extension id {i!r} (must match ^[a-p]{{32}}$)")
        cleaned.append(i)
    level = str(data.get("log_level") or "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigError("log_level must be DEBUG, INFO, WARNING, or ERROR")
    return Config(
        version=CURRENT_VERSION,
        listen_port=port,
        helper_secret=secret,
        client_identifier=client_id,
        player=player,
        allowed_extension_ids=cleaned,
        log_level=level,
    )


def save_config(paths: Paths, cfg: Config) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    tmp = paths.config.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    tmp.replace(paths.config)


def load_or_create_config(paths: Paths) -> Config:
    paths.root.mkdir(parents=True, exist_ok=True)
    if not paths.config.is_file():
        bundled = bundled_extension_id()
        cfg = Config(
            helper_secret=secrets.token_hex(32),
            client_identifier=str(uuid.uuid4()),
            allowed_extension_ids=[bundled] if bundled else [],
        )
        save_config(paths, cfg)
        return cfg
    try:
        raw = json.loads(paths.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"unreadable config.json: {exc}") from exc
    cfg = parse_config(raw)
    dirty = False
    if not cfg.helper_secret:
        cfg.helper_secret = secrets.token_hex(32)
        dirty = True
    if not cfg.client_identifier:
        cfg.client_identifier = str(uuid.uuid4())
        dirty = True
    bundled = bundled_extension_id()
    if bundled and bundled not in cfg.allowed_extension_ids:
        cfg.allowed_extension_ids.append(bundled)
        dirty = True
    if dirty:
        save_config(paths, cfg)
    return cfg
