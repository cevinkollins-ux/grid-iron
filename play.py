#!/usr/bin/env python3
"""
Start Grid Iron in your browser.

    python3 play.py               # serves the game and opens it
    python3 play.py --port 9000   # pick a port (default: 8744, or the next free one)
    python3 play.py --no-browser  # just serve it

Works from any folder. Press Ctrl+C to stop.
"""

import os
import sys

# This script only needs Python's built-in modules. Relaunch in isolated mode
# (-I: ignore PYTHONPATH and the script's folder; -S: skip site-packages) so
# extra paths an IDE or venv adds can't shadow them. For example, a PyCharm
# source root pointing at the `future` package's backports folder replaces the
# built-in `http` and `socket` modules with incompatible copies.
if not sys.flags.isolated:
    os.execv(sys.executable, [sys.executable, "-I", "-S", os.path.abspath(__file__), *sys.argv[1:]])

import argparse
import functools
import http.server
import socket
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 8744


def free_port(preferred):
    """Return the preferred port if it's free, otherwise the next free one after it.

    Sticking to the same port matters: the browser saves Daily progress per
    address (including the port), so a different port looks like a fresh start.
    """
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Same option the server uses, so a port that was just released counts as free.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    sys.exit(f"No free port found between {preferred} and {preferred + 49}.")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal clean

    def end_headers(self):
        # Always serve the latest index.html / data.js after a rebuild.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description="Serve Grid Iron locally and open it in a browser.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to use (default {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()

    if not (ROOT / "data.js").exists():
        sys.exit("data.js is missing. Build it first: python3 scripts/build_data.py")

    port = free_port(args.port)
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://localhost:{port}/"

    print(f"Grid Iron is running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
