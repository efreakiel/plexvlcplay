"""Locate vlc.exe on Windows."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

log = __import__("logging").getLogger("plexvlc")


def _reg_value(hive: int, path: str, name: str = "") -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(hive, path) as key:
            val, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(val) if val else None


def _exe_if_exists(path: str | Path | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if p.is_file():
        return p
    return None


def discover_vlc(configured: str | None = None) -> Path | None:
    if configured:
        p = Path(configured)
        if p.is_absolute() and p.is_file():
            return p

    if os.name == "nt":
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key_path in (
                r"SOFTWARE\VideoLAN\VLC",
                r"SOFTWARE\WOW6432Node\VideoLAN\VLC",
            ):
                install = _reg_value(hive, key_path, "InstallDir")
                hit = _exe_if_exists(Path(install) / "vlc.exe") if install else None
                if hit:
                    return hit
            app = _reg_value(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\vlc.exe")
            hit = _exe_if_exists(app)
            if hit:
                return hit

        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if not root:
                continue
            if env == "LOCALAPPDATA":
                hit = _exe_if_exists(Path(root) / "Programs" / "VideoLAN" / "VLC" / "vlc.exe")
            else:
                hit = _exe_if_exists(Path(root) / "VideoLAN" / "VLC" / "vlc.exe")
            if hit:
                return hit

    which = shutil.which("vlc") or shutil.which("vlc.exe")
    return _exe_if_exists(which)
