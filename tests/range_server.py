# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Minimal HTTP server with HTTP Range support, for testing FreeDM.

Usage:  python tests/range_server.py [port] [file_size_mb]
Serves a generated file at /test.bin and honours Range headers.

Extra endpoints (used by tests):
    GET /hash     -> sha256 of the current served file (hex)
    GET /mutate   -> rewrites the file with new bytes (simulates a changed remote file)
    GET /size     -> current file size in bytes
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA_DIR = tempfile.mkdtemp(prefix="freedm_srv_")
TEST_FILE = os.path.join(DATA_DIR, "test.bin")

_lock = threading.Lock()
_generation = 0
RETRY_REMAINING = 0        # /retry/test.bin returns 429 this many times

# --- N4: connection throttling -------------------------------------------
# The first client connection that asks for /throttle/test.bin is slowed down
# for its whole life, like a real server that hands one client a bad pipe.
THROTTLE_BPS = 0           # bytes/s for the throttled connection (0 = off)
_throttled_ports: set[int] = set()
_throttled_bytes = 0       # bytes served on the throttled connection
_throttled_first_range = 0  # size of the first piece the slow pipe received


def set_throttle(bps: int) -> None:
    """Throttle the first connection to /throttle/test.bin to ``bps``."""
    global THROTTLE_BPS, _throttled_bytes, _throttled_first_range
    with _lock:
        THROTTLE_BPS = int(bps)
        _throttled_ports.clear()
        _throttled_bytes = 0
        _throttled_first_range = 0


def throttled_stats() -> tuple[int, int]:
    """(bytes served on the slow pipe, size of the first piece it got)."""
    with _lock:
        return _throttled_bytes, _throttled_first_range


def reset_retry(times: int = 1) -> None:
    """Make /retry/test.bin answer 429 (Retry-After: 1) `times` times."""
    global RETRY_REMAINING
    RETRY_REMAINING = int(times)


def _write_random(size: int) -> None:
    with open(TEST_FILE, "wb") as f:
        remaining = size
        while remaining > 0:
            block = os.urandom(min(1024 * 1024, remaining))
            f.write(block)
            remaining -= len(block)
        # nudge mtime forward so Last-Modified changes between generations
        future = time.time() + 1 + _generation
        os.utime(TEST_FILE, (future, future))



# --- N10: streaming media fixtures ----------------------------------------
# A tiny HLS stream: three segments that together make one file.
HLS_SEGMENTS = [b"SEGMENT-ONE-" * 8, b"SEGMENT-TWO-" * 8, b"SEGMENT-THREE-" * 8]
HLS_KEY = bytes(range(16))
HLS_IV = bytes(range(16, 32))


def hls_master() -> bytes:
    return ("#EXTM3U\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
            "media.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720\n"
            "media.m3u8\n").encode()


def hls_media() -> bytes:
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:4", "#EXT-X-MEDIA-SEQUENCE:0"]
    for index, _segment in enumerate(HLS_SEGMENTS):
        lines.append("#EXTINF:4.0,")
        lines.append(f"seg{index}.ts")
    lines.append("#EXT-X-ENDLIST")
    return ("\n".join(lines) + "\n").encode()


def hls_encrypted() -> bytes:
    """The same stream, encrypted with AES-128 (the HLS default)."""
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:4",
             '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x'
             + HLS_IV.hex(), "#EXT-X-MEDIA-SEQUENCE:0"]
    for index, _segment in enumerate(HLS_SEGMENTS):
        lines.append("#EXTINF:4.0,")
        lines.append(f"enc{index}.ts")
    lines.append("#EXT-X-ENDLIST")
    return ("\n".join(lines) + "\n").encode()


def hls_encrypted_segment(index: int) -> bytes:
    """One encrypted segment (AES-128-CBC, PKCS#7 padded)."""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    plain = HLS_SEGMENTS[index]
    cipher = AES.new(HLS_KEY, AES.MODE_CBC, HLS_IV)
    return cipher.encrypt(pad(plain, 16))


def dash_manifest() -> bytes:
    return ("""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
     mediaPresentationDuration="PT12S" minBufferTime="PT2S">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <Representation id="1" bandwidth="1200000" codecs="avc1">
        <SegmentTemplate media="seg-$Number$.ts" duration="4"
                         timescale="1" startNumber="1" segmentCount="3"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
""").encode()

def ensure_file(size_mb: float) -> int:
    size = int(size_mb * 1024 * 1024)
    if not os.path.exists(TEST_FILE) or os.path.getsize(TEST_FILE) != size:
        _write_random(size)
    return size


def mutate_file() -> None:
    """Rewrite the served file with different bytes of the same size."""
    global _generation
    with _lock:
        size = os.path.getsize(TEST_FILE)
        _generation += 1
        _write_random(size)


def file_hash() -> str:
    h = hashlib.sha256()
    with open(TEST_FILE, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _etag() -> str:
    st = os.stat(TEST_FILE)
    return f'"g{_generation}-{st.st_size}-{int(st.st_mtime)}"'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_meta(self) -> None:
        st = os.stat(TEST_FILE)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", _etag())
        self.send_header("Last-Modified", formatdate(st.st_mtime, usegmt=True))

    # Paths that serve the test file, with optional gates.
    FILE_PATHS = ("/test.bin", "/protected/test.bin", "/cookie/test.bin",
                  "/retry/test.bin", "/throttle/test.bin", "/movie.mp4")

    def _gate_ok(self, path: str) -> bool:
        if path == "/protected/test.bin":
            return "freedm-test" in (self.headers.get("Referer") or "")
        if path == "/cookie/test.bin":
            return "auth=secret" in (self.headers.get("Cookie") or "")
        return True

    def _is_throttled_client(self) -> bool:
        """True for the first client socket that asked for the throttled path.

        Models a server that hands one client a slow pipe for its whole life.
        """
        if not THROTTLE_BPS:
            return False
        port = self.client_address[1]
        with _lock:
            if port in _throttled_ports:
                return True
            _throttled_ports.add(port)
            return True

    def _send_status(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_file(self, head: bool) -> None:
        path = urlparse(self.path).path
        size = os.path.getsize(TEST_FILE)
        rng = self.headers.get("Range")
        if_range = self.headers.get("If-Range")
        start, end = 0, size - 1
        partial = False
        force_full = False

        # Enforce If-Range: if the validator does not match, send the whole file.
        if if_range and rng and if_range.strip() != _etag():
            force_full = True
            rng = None

        if rng and not force_full:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            if m:
                start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Type", "application/octet-stream")
        # The file name comes from the path, so a test can ask for a
        # ".mp4" and check how the app categorises it.
        name = os.path.basename(path) or "test.bin"
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._send_meta()
        self.end_headers()

        if head:
            return
        slow = (path == "/throttle/test.bin") and self._is_throttled_client()
        if slow:
            global _throttled_bytes, _throttled_first_range
            with _lock:
                if _throttled_first_range == 0:
                    _throttled_first_range = length
        with open(TEST_FILE, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)
                if slow and THROTTLE_BPS:
                    # Pace this connection so it stays the bottleneck.
                    time.sleep(len(chunk) / float(THROTTLE_BPS))
                    with _lock:
                        _throttled_bytes += len(chunk)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        """Send a small in-memory body (the stream fixtures)."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _stream_fixture(self, path: str) -> bool:
        """Serve the HLS/DASH fixtures. True when the path was handled."""
        if path == "/hls/master.m3u8":
            self._send_bytes(hls_master(), "application/vnd.apple.mpegurl")
            return True
        if path == "/hls/media.m3u8":
            self._send_bytes(hls_media(), "application/vnd.apple.mpegurl")
            return True
        if path == "/hls/enc.m3u8":
            self._send_bytes(hls_encrypted(), "application/vnd.apple.mpegurl")
            return True
        if path == "/hls/key.bin":
            self._send_bytes(HLS_KEY, "application/octet-stream")
            return True
        if path == "/dash/manifest.mpd":
            self._send_bytes(dash_manifest(), "application/dash+xml")
            return True
        if path.startswith("/hls/seg") and path.endswith(".ts"):
            index = int(path[len("/hls/seg"):-len(".ts")])
            if 0 <= index < len(HLS_SEGMENTS):
                self._send_bytes(HLS_SEGMENTS[index], "video/mp2t")
                return True
        if path.startswith("/hls/enc") and path.endswith(".ts"):
            index = int(path[len("/hls/enc"):-len(".ts")])
            if 0 <= index < len(HLS_SEGMENTS):
                self._send_bytes(hls_encrypted_segment(index),
                                 "video/mp2t")
                return True
        if path.startswith("/dash/seg") and path.endswith(".ts"):
            # DASH numbers its segments from startNumber (1 by default).
            number = int(path[len("/dash/seg"):-len(".ts")].lstrip("-"))
            index = number - 1
            if 0 <= index < len(HLS_SEGMENTS):
                self._send_bytes(HLS_SEGMENTS[index], "video/mp2t")
                return True
        return False

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/redirect/test.bin":
            self.send_response(302)
            self.send_header("Location", "/test.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self._stream_fixture(path):
            return
        if path in self.FILE_PATHS:
            if not self._gate_ok(path):
                self._send_status(403)
                return
            self._serve_file(head=True)
            return
        self._send_status(404)

    def do_GET(self) -> None:  # noqa: N802
        global RETRY_REMAINING
        path = urlparse(self.path).path

        if self._stream_fixture(path):
            return

        if path == "/retry/test.bin" and RETRY_REMAINING > 0:
            RETRY_REMAINING -= 1
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/mutate":
            mutate_file()
            body = b"mutated\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/hash":
            body = (file_hash() + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/size":
            body = (str(os.path.getsize(TEST_FILE)) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/redirect/test.bin":
            self.send_response(302)
            self.send_header("Location", "/test.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path in self.FILE_PATHS:
            if not self._gate_ok(path):
                self._send_status(403)
                return
            self._serve_file(head=False)
            return

        self._send_status(404)

    def log_message(self, *args) -> None:  # silence
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # Clients intentionally abort connections during pause/cancel tests.
        pass


def start_server(port: int = 8765, size_mb: float = 20.0) -> ThreadingHTTPServer:
    """Start the server on a background daemon thread; returns the server."""
    ensure_file(size_mb)
    httpd = QuietServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    size_mb = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    size = ensure_file(size_mb)
    httpd = QuietServer(("127.0.0.1", port), Handler)
    print(f"Serving {size} bytes at http://127.0.0.1:{port}/test.bin", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
