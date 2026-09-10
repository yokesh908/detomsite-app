#!/usr/bin/env python3
"""
Serve any DETOMSITE portal dist as a single-page app.

Usage:
    python tools/serve_portal.py student    # → http://127.0.0.1:8766
    python tools/serve_portal.py shopkeeper :8767
    python tools/serve_portal.py admin :8768
    python tools/serve_portal.py student 3000
"""
import os, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORTALS = {
    "student": ("Student Portal", 8766),
    "shopkeeper": ("Shopkeeper Portal", 8767),
    "admin": ("Admin Portal", 8768),
}

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "student"
    if name not in PORTALS:
        sys.exit(f"Unknown portal '{name}'. Choose from: {', '.join(PORTALS)}")
    title, default_port = PORTALS[name]
    port = default_port
    if len(sys.argv) > 2:
        port = int(sys.argv[2].lstrip(":"))
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", name, "dist"))
    if not os.path.isdir(root):
        sys.exit(f"Build not found: {root}\nRun: (cd frontend/{name} && npm run build) first.")

    class SPAHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def do_GET(self):
            if os.path.isfile(self.translate_path(self.path)):
                return super().do_GET()
            self.path = "/index.html"
            return super().do_GET()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), SPAHandler)
    print(f"{title} → http://127.0.0.1:{port}")
    print(f"  serving: {root}")
    print("  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()