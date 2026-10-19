# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""FreeDM entry point.

Usage:
    FreeDM.exe                          -> launch the GUI
    FreeDM.exe URL [-o DIR] [-t N]      -> command-line download
    FreeDM.exe --selftest URL DIR       -> headless engine check (writes a log)
    FreeDM.exe --browser-selftest [DIR] -> headless control-server check
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from engine import Download, human_size, human_speed, human_time, DONE, ERROR, CANCELED


def _emit(text: str) -> None:
    """Write to stdout safely (windowed builds have stdout == None)."""
    if sys.stdout is not None:
        sys.stdout.write(text)
        sys.stdout.flush()


def cli_download(args: argparse.Namespace) -> int:
    dl = Download(
        args.url,
        dest_dir=args.output,
        num_threads=args.threads,
        speed_limit=args.limit,
    )
    dl.start()

    try:
        while dl.status not in (DONE, ERROR, CANCELED):
            time.sleep(0.4)
            if dl.total_size:
                pct = dl.progress * 100
                line = (f"\r  {pct:5.1f}%  {human_size(dl.downloaded)}/{human_size(dl.total_size)}"
                        f"  {human_speed(dl.speed)}  ETA {human_time(dl.eta)}   ")
            else:
                line = f"\r  {human_size(dl.downloaded)}  {human_speed(dl.speed)}   "
            _emit(line)
    except KeyboardInterrupt:
        dl.pause()
        _emit("\nInterrupted - partial file kept for resume.\n")
        return 130

    _emit("\n")
    if dl.status == DONE:
        _emit(f"Done: {dl.path}\n")
        return 0
    _emit(f"Failed ({dl.status}): {dl.error}\n")
    return 1


def _selftest(argv: list[str]) -> int:
    """Verify a frozen build works: download a URL and log the result."""
    import hashlib

    url = argv[0] if argv else "https://example.com/"
    outdir = argv[1] if len(argv) > 1 else os.path.join(os.environ.get("TEMP", "."), "freedm_selftest")
    log = os.path.join(outdir, "selftest_result.txt")
    os.makedirs(outdir, exist_ok=True)

    lines = [f"frozen={getattr(sys, 'frozen', False)}", f"python={sys.version}", f"url={url}"]
    try:
        dl = Download(url, dest_dir=outdir, num_threads=8)
        dl.start()
        t0 = time.time()
        while dl.status not in (DONE, ERROR, CANCELED) and time.time() - t0 < 120:
            time.sleep(0.3)
        lines.append(f"status={dl.status}")
        lines.append(f"error={dl.error}")
        lines.append(f"size={dl.total_size}")
        lines.append(f"supports_range={dl.supports_range}")
        lines.append(f"path={dl.path}")
        if dl.status == DONE and dl.path and os.path.exists(dl.path):
            h = hashlib.sha256()
            with open(dl.path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            lines.append(f"sha256={h.hexdigest()}")
            lines.append("RESULT=PASS")
        else:
            lines.append("RESULT=FAIL")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"exception={exc!r}")
        lines.append("RESULT=FAIL")

    with open(log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0


def _browser_selftest(argv: list[str]) -> int:
    """Headless check of the W1 browser-handoff path (usable in a frozen exe)."""
    import json
    import tempfile
    import urllib.request

    outdir = argv[0] if argv else os.path.join(
        os.environ.get("TEMP", "."), "freedm_browser_selftest")
    log = os.path.join(outdir, "browser_selftest_result.txt")
    os.makedirs(outdir, exist_ok=True)

    lines = [f"frozen={getattr(sys, 'frozen', False)}", f"python={sys.version}"]
    try:
        from control_server import ControlServer, export_extension
        received: list[dict] = []
        srv = ControlServer(on_add=lambda job: (received.append(job), 1)[1],
                            token="selftest-token", port=0)
        ok = srv.start()
        lines.append(f"server_started={ok}")
        lines.append(f"port={srv.port}")
        if not ok:
            lines.append("RESULT=FAIL")
        else:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{srv.port}/ping", timeout=5) as r:
                body = json.loads(r.read())
                lines.append(f"ping_app={body.get('app')}")
            req = urllib.request.Request(
                f"http://127.0.0.1:{srv.port}/add",
                data=json.dumps({"url": "http://example.com/x.bin"}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer selftest-token"})
            with urllib.request.urlopen(req, timeout=5) as r:
                lines.append(f"add_status={r.status}")
            lines.append(f"job_received={len(received) == 1}")
            dest = export_extension(os.path.join(outdir, "extension"))
            lines.append(f"extension_manifest="
                         f"{os.path.exists(os.path.join(dest, 'manifest.json'))}")
            srv.stop()
            good = (body.get("app") == "FreeDM" and len(received) == 1
                    and os.path.exists(os.path.join(dest, "manifest.json")))
            lines.append("RESULT=" + ("PASS" if good else "FAIL"))
    except Exception as exc:      # noqa: BLE001
        lines.append(f"exception={exc!r}")
        lines.append("RESULT=FAIL")
    with open(log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    _emit("\n".join(lines) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--selftest":
        return _selftest(argv[1:])

    if argv and argv[0] == "--browser-selftest":
        return _browser_selftest(argv[1:])

    if not argv:
        from gui import run_gui
        run_gui()
        return 0

    parser = argparse.ArgumentParser(prog="FreeDM", description="Free download manager")
    parser.add_argument("url", help="URL to download")
    parser.add_argument("-o", "--output", default=None, help="output directory")
    parser.add_argument("-t", "--threads", type=int, default=8, help="number of threads")
    parser.add_argument("--limit", type=float, default=0.0, help="speed limit in bytes/s (0=off)")
    args = parser.parse_args(argv)
    return cli_download(args)


if __name__ == "__main__":
    raise SystemExit(main())
