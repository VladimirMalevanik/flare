"""Temporary operator-only 503 endpoint; no authentication or DB access."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os


class Maintenance(BaseHTTPRequestHandler):
    def respond(self):
        body = b"Flare maintenance: OPS-002\n"
        self.send_response(503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "300")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = respond

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Maintenance).serve_forever()
