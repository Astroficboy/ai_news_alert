"""Local web UI: serves the reader page and a small JSON API over the SQLite store."""
import fcntl
import json
import re
import socket
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .store import Store

STATIC = Path(__file__).parent / "static"
ID_RE = re.compile(r"[0-9a-f]{40}")


def run_in_progress(lock_path):
    """True if some `ainews.py run` (UI-started or scheduled) holds the run lock."""
    try:
        with open(lock_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except BlockingIOError:
        return True


def is_serving(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Runner:
    """Starts `ainews.py run` in the background and keeps its recent output for the UI."""

    def __init__(self, root):
        self.root = root
        self.proc = None
        self.lines = deque(maxlen=40)
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return False
            self.lines.clear()
            # The UI is open, so desktop alerts would just be noise.
            self.proc = subprocess.Popen(
                [sys.executable, str(self.root / "ainews.py"), "run", "--no-notify"],
                cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
            return True

    def _pump(self, proc):
        for line in proc.stdout:
            self.lines.append(line.rstrip())
        proc.wait()

    @property
    def running(self):
        return bool(self.proc and self.proc.poll() is None)


def make_handler(root, cfg, runner):
    db_path = root / "data" / "news.db"
    lock_path = root / "data" / "run.lock"
    allowed_hosts = {f"127.0.0.1:{cfg['ui_port']}", f"localhost:{cfg['ui_port']}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _guard(self):
            # Block DNS-rebinding and cross-site requests: localhost Host only, and POSTs need a custom header
            # (which other sites can't send without a CORS preflight we never answer).
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, b"forbidden", "text/plain")
                return False
            if self.command == "POST" and self.headers.get("X-AINews") != "1":
                self._send(403, b"forbidden", "text/plain")
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if not self._guard():
                return
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            store = Store(db_path)
            try:
                if path == "/api/items":
                    days = max(1, min(30, int(parse_qs(query).get("days", ["3"])[0])))
                    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                    return self._json(store.ui_items(since))
                if path == "/api/status":
                    return self._json({
                        "running": runner.running or run_in_progress(lock_path),
                        "ui_run": runner.running,
                        "log": list(runner.lines)[-6:],
                        "last_run": store.get_meta("last_run"),
                        "last_run_new": int(store.get_meta("last_run_new") or 0),
                        "pending": store.pending_count(),
                        "model": cfg["model"],
                    })
            finally:
                store.close()
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._guard():
                return
            if self.path == "/api/refresh":
                if run_in_progress(lock_path) and not runner.running:
                    return self._json({"started": False, "reason": "A scheduled update is already running."})
                return self._json({"started": runner.start()})
            m = re.fullmatch(r"/api/(read|saved)", self.path)
            if m:
                body = self._body()
                ids = [i for i in body.get("ids", []) if ID_RE.fullmatch(str(i))]
                store = Store(db_path)
                try:
                    store.set_flag(ids, "is_" + m[1], bool(body.get("value", True)))
                finally:
                    store.close()
                return self._json({"ok": True, "count": len(ids)})
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(root, cfg, open_browser=True):
    port = cfg["ui_port"]
    url = f"http://localhost:{port}/"
    if is_serving(port):
        print(f"UI already running at {url}")
    else:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root, cfg, Runner(root)))
        print(f"AI News UI running at {url}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            threading.Timer(0.5, lambda: subprocess.run(["open", url])).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if open_browser:
        subprocess.run(["open", url])
    return 0
