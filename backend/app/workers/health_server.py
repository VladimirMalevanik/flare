"""Minimal health endpoint for the continuously running Azure worker."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os


class HealthHandler(BaseHTTPRequestHandler):
    """Expose only bounded liveness responses and keep request data out of logs."""

    def do_GET(self) -> None:  # noqa: N802; BaseHTTPRequestHandler contract
        if self.path not in {"/", "/health", "/ready"}:
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"status":"ready","role":"worker"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


if __name__ == "__main__":
    main()
