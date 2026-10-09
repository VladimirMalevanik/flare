"""Minimal health endpoint for the continuously running Azure worker."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
from pathlib import Path
import stat
import time


def import_consumers_ready(*, now: float | None = None) -> bool:
    """Recent completed DB polls, not proof of a particular package outcome.

    The supervisor stops this server if any child exits. Consumer stamps expire
    after the bounded job deadline plus slack, or 30 seconds for cleanup. They
    contain only a local monotonic timestamp and are renewed after the matching
    PostgreSQL consumer heartbeat succeeds.
    """
    enabled = os.getenv('FLARE_IMPORT_ENABLED', 'false')
    if enabled == 'false':
        return True
    if enabled != 'true':
        return False
    directory = os.getenv('FLARE_WORKER_HEARTBEAT_DIR')
    if not directory:
        return False
    private = Path(directory)
    try:
        info = private.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return False
        current = time.monotonic() if now is None else now
        for mode, max_age in (('jobs', 240), ('cleanup', 30)):
            path = private / f'{mode}.json'
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 128):
                return False
            with path.open() as stream:
                stamp = json.loads(stream.read(129))
            checked = stamp.get('checked_at') if isinstance(stamp, dict) else None
            if type(checked) not in (int, float) or not math.isfinite(checked):
                return False
            age = current - checked
            if age < 0 or age > max_age:
                return False
    except (OSError, ValueError):
        return False
    return True


class HealthHandler(BaseHTTPRequestHandler):
    """Expose only bounded liveness responses and keep request data out of logs."""

    def do_GET(self) -> None:  # noqa: N802; BaseHTTPRequestHandler contract
        if self.path not in {"/", "/health", "/ready"}:
            self.send_response(404)
            self.end_headers()
            return
        ready = import_consumers_ready()
        body = (b'{"status":"ready","role":"worker"}' if ready
                else b'{"status":"unavailable","role":"worker"}')
        self.send_response(200 if ready else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    try:
        port = int(os.getenv("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid worker health port')
        with ThreadingHTTPServer(("0.0.0.0", port), HealthHandler) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError):
        logging.error('worker_health startup_or_runtime_failure')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
