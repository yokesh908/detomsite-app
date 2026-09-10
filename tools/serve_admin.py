#!/usr/bin/env python3
"""
Serve the DETOMSITE Admin Portal locally.

Serves frontend/admin/dist as a single-page app on http://127.0.0.1:8766.
All unknown routes fall back to index.html (SPA routing).

Usage:
    python tools/serve_admin.py          # default port 8766
    python tools/serve_admin.py 3000     # custom port
"""
import os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.join(os.path.dirname(__file__), "..", "frontend", "admin", "dist")

class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        # If the path matches a real file, serve it.
        path = self.translate_path(self.path)
        if os.path.isfile(path):
            return super().do_GET()
        # Otherwise serve index.html (SPA fallback).
        self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *a):
        pass

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    srv = HTTPServer(("127.0.0.1", port), SPAHandler)
    print(f"DETOMSITE ADMIN → http://127.0.0.1:{port}")
    print(f"  serving dist from {os.path.abspath(ROOT)}")
    print("  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()