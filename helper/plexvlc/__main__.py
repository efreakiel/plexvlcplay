"""python -m plexvlc / pythonw -m plexvlc"""

from __future__ import annotations

import atexit
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from plexvlc import __version__
from plexvlc.auth import redact
from plexvlc.config import ConfigError, Paths, load_or_create_config
from plexvlc.server import App, make_server


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging(log_path: Path, level: str, to_stderr: bool) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("plexvlc")
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    root.addHandler(fh)
    if to_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.addFilter(RedactFilter())
        root.addHandler(sh)


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def check_single_instance(pid_path: Path) -> int | None:
    if not pid_path.is_file():
        return None
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    if pid_exists(pid):
        return pid
    return None


def write_pid(pid_path: Path) -> None:
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid(pid_path: Path) -> None:
    try:
        pid_path.unlink(missing_ok=True)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        paths = Paths.default()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        cfg = load_or_create_config(paths)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        logging.getLogger("plexvlc").error("%s", exc)
        return 1

    has_console = sys.stderr is not None and sys.stderr.isatty()
    setup_logging(paths.log, cfg.log_level, to_stderr=has_console)
    log = logging.getLogger("plexvlc")

    existing = check_single_instance(paths.pid)
    if existing is not None:
        msg = f"already running pid={existing}"
        print(msg, file=sys.stderr)
        log.info(msg)
        return 2

    app = App(cfg, paths)
    try:
        httpd = make_server(app)
    except OSError as exc:
        msg = (
            f"Port {cfg.listen_port} is in use. If plexvlc is already running, use it. "
            f"Otherwise change listen_port in {paths.config}."
        )
        print(msg, file=sys.stderr)
        log.error("%s (%s)", msg, exc)
        return 2

    write_pid(paths.pid)
    atexit.register(remove_pid, paths.pid)

    app.mint_pairing_code()
    banner = f"plexvlc {__version__} listening on {app.listen}"
    print(banner)
    log.info("listening on %s", app.listen)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
        remove_pid(paths.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
