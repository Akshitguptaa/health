"""Serve frontend/ locally with single-page-app fallback (so /facility/IN... and /stats work on reload).

    python scripts/serve_frontend.py [port]        # default 8090
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = (Path(__file__).resolve().parent.parent / "frontend").resolve()
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def do_GET(self):
        requested = (ROOT / unquote(urlparse(self.path).path).lstrip("/")).resolve()
        # never serve anything outside frontend/; unknown paths fall back to the app shell
        if not requested.is_file() or ROOT not in requested.parents:
            requested = ROOT / "index.html"
        body = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(requested.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"Frontend: http://localhost:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
