# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Local control server for browser handoff (W1).

Listens only on 127.0.0.1 and accepts small JSON requests from the FreeDM
browser extension. Every state-changing request needs the per-user token
stored in ``%APPDATA%\\FreeDM\\control_token.txt``.

Endpoints:
    GET  /ping  -> {"ok": true, "app": "FreeDM", "port": N}
    POST /add   -> queue a download (Bearer token required)

The server never downloads anything itself: ``on_add(payload)`` hands the
normalised job to the GUI, which creates a regular ``Download``.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from freedm.store import app_data_dir

CONTROL_PORT = 6801
TOKEN_FILE = "control_token.txt"
MAX_BODY = 1 << 20                 # 1 MiB is plenty for a job payload

#: Only these origins may talk to the control server. The extension is a
#: browser extension, so its origin is `chrome-extension://<id>` (Chrome,
#: Edge) or `moz-extension://<id>` (Firefox). Ordinary web pages are NOT
#: allowed: a site must not be able to reach into the app on localhost.
ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://",
                           "safari-web-extension://")

#: Host names the server answers to. A request addressed to any other name
#: (a DNS-rebinding attempt) is refused.
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")


def _host_allowed(host_header: str | None) -> bool:
    """True when the Host header names the loopback interface."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):            # [::1]:6801
        host = host[1:].split("]", 1)[0]
    elif host.count(":") > 1:           # a bare IPv6 address, e.g. ::1
        pass
    else:
        host = host.split(":", 1)[0]    # 127.0.0.1:6801
    return host in ALLOWED_HOSTS


def token_path() -> str:
    return os.path.join(app_data_dir(), TOKEN_FILE)


def load_or_create_token(path: str | None = None) -> str:
    """Read the control token, creating it atomically on first use."""
    path = path or token_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(token)
        os.replace(tmp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def extension_source_dir() -> str:
    """Where the bundled extension lives (PyInstaller temp dir when frozen)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # The package lives in freedm/; the extension sits next to it.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "extension")


def export_extension(dest: str | None = None, browser: str = "chrome") -> str:
    """Copy the bundled extension to a stable folder and return its path.

    ``browser`` is ``"chrome"`` (the default) or ``"firefox"``. The Firefox
    build uses a different manifest: an event page instead of a service
    worker, an options *tab* instead of a page, and the gecko add-on id.
    """
    src = extension_source_dir()
    if not os.path.isdir(src):
        raise FileNotFoundError(f"extension folder not found: {src}")
    dest = dest or os.path.join(app_data_dir(), "extension")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    if browser == "firefox":
        firefox_manifest = os.path.join(dest, "manifest.firefox.json")
        if os.path.exists(firefox_manifest):
            shutil.copyfile(firefox_manifest,
                            os.path.join(dest, "manifest.json"))
            os.remove(firefox_manifest)
    else:
        # A Firefox export left behind must not confuse a Chrome install.
        stray = os.path.join(dest, "manifest.firefox.json")
        if os.path.exists(stray):
            os.remove(stray)
    return dest


def _normalise(payload: dict) -> dict:
    """Validate/normalise an extension payload; raise ValueError if invalid."""
    url = str(payload.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("url must be http(s)")

    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("headers must be an object")
    headers = {str(k): str(v) for k, v in headers.items()
               if isinstance(k, str) and isinstance(v, (str, int, float))}

    cookies = payload.get("cookies")
    if cookies is not None and not isinstance(cookies, (dict, list, str)):
        raise ValueError("cookies must be an object, list or string")

    try:
        threads = int(payload.get("threads") or 0)
    except (TypeError, ValueError):
        threads = 0

    filename = payload.get("filename")
    if filename is not None:
        filename = str(filename).strip() or None

    # The destination must be a folder that really exists; a payload cannot
    # point a download at an arbitrary path.
    dest_dir = str(payload.get("dest_dir") or "").strip()
    if dest_dir and not os.path.isdir(dest_dir):
        dest_dir = None

    return {
        "url": url,
        "cookies": cookies,
        "referer": str(payload.get("referer") or "") or None,
        "user_agent": str(payload.get("user_agent") or "") or None,
        "filename": filename,
        "threads": max(1, min(threads, 32)) if threads else None,
        "headers": headers,
        "dest_dir": dest_dir or None,
    }


class ControlServer:
    def __init__(self, on_add: Callable[[dict], Any],
                 token: str | None = None, port: int = CONTROL_PORT,
                 host: str = "127.0.0.1"):
        self.on_add = on_add
        self.token = token or load_or_create_token()
        self.host = host
        self.port = int(port)
        self.last_error: str | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> bool:
        control = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FreeDMControl/1.0"

            def log_message(self, *_args) -> None:   # keep the console quiet
                return

            # -- helpers ---------------------------------------------------
            def _origin_allowed(self) -> bool:
                """True for a browser extension origin, false for a web page."""
                origin = (self.headers.get("Origin") or "").strip().lower()
                return origin.startswith(ALLOWED_ORIGIN_PREFIXES)

            def _cors(self) -> None:
                """CORS headers for the extension only.

                A normal web page must not be able to read anything from
                this server, so the headers are only sent for an extension
                origin. The extension itself does not need CORS: an MV3
                service worker with `host_permissions` may talk to loopback
                directly."""
                if not self._origin_allowed():
                    return
                self.send_header("Access-Control-Allow-Origin",
                                 self.headers.get("Origin"))
                self.send_header("Vary", "Origin")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, Authorization, X-FreeDM-Token")
                self.send_header(
                    "Access-Control-Allow-Methods", "GET, POST, OPTIONS")

            def _host_ok(self) -> bool:
                """Refuse a request addressed to a name other than loopback."""
                return _host_allowed(self.headers.get("Host"))

            def _json(self, code: int, obj: dict) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _drain(self) -> None:
                """Read and discard the request body.

                The client is still writing its payload when we want to
                answer with 403/404. If we respond and close without reading,
                the socket dies mid-write and the client sees a connection
                reset (WinError 10053) instead of our response. Draining the
                body first lets the client finish sending.
                """
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length <= 0:
                    return
                remaining = min(length, MAX_BODY + 1024)
                try:
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except OSError:
                    pass

            def _authorised(self) -> bool:
                header = self.headers.get("Authorization", "")
                token = header[7:].strip() if header.lower().startswith(
                    "bearer ") else ""
                token = token or self.headers.get("X-FreeDM-Token", "").strip()
                return bool(token) and hmac.compare_digest(
                    token, control.token)

            # -- verbs -----------------------------------------------------
            def do_OPTIONS(self) -> None:  # noqa: N802
                if not self._host_ok():
                    self._json(403, {"ok": False, "error": "forbidden"})
                    return
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if not self._host_ok():
                    self._json(403, {"ok": False, "error": "forbidden"})
                    return
                path = self.path.split("?", 1)[0]
                if path in ("/ping", "/health"):
                    self._json(200, {
                        "ok": True,
                        "app": "FreeDM",
                        "port": control.port,
                        "version": "1.0",
                    })
                    return
                self._json(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._host_ok():
                    self._drain()
                    self._json(403, {"ok": False, "error": "forbidden"})
                    return
                path = self.path.split("?", 1)[0]
                if path != "/add":
                    self._drain()
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                if not self._authorised():
                    self._drain()
                    self._json(403, {"ok": False, "error": "invalid token"})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_BODY:
                    self._drain()
                    self._json(400, {"ok": False, "error": "bad body"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(payload, dict):
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                try:
                    job = _normalise(payload)
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                try:
                    job_id = control.on_add(job)
                except Exception:       # noqa: BLE001
                    # Never leak an internal error message to the client.
                    self._json(500, {"ok": False, "error": "internal error"})
                    return
                self._json(200, {"ok": True, "id": job_id})

        try:
            httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            self.last_error = str(exc)
            self._httpd = None
            return False
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
            except OSError:
                pass
            try:
                httpd.server_close()
            except OSError:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
