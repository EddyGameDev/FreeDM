"""Split freedm/engine.py into the freedm/engine/ package (Milestone 3, G3).

The split is mechanical: the same code, moved into focused modules. The
Download class becomes a set of mixins, one per concern, and the public API
is re-exported from freedm/engine/__init__.py so nothing outside has to
change.
"""
from __future__ import annotations

import ast
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "freedm", "engine.py")
TARGET = os.path.join(ROOT, "freedm", "engine")
HEADER = "# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash\n"

# Which methods of Download go into which mixin.
MIXINS = {
    "streaming": [
        "_looks_like_playlist", "_fetch_playlist", "_load_playlist",
        "_run_stream", "_read_stream_state", "_save_stream_state",
        "_stream_headers", "_check_stream_url", "_fetch_segment",
        "_fetch_key",
    ],
    "verification": [
        "_check_complete", "_verify_result", "verify_now", "set_checksum",
    ],
    "segments": [
        "_prepare_pending", "_piece_target", "_note_piece_speed",
        "_split_piece", "_claim_piece", "_make_segments", "_pieces_are_valid",
    ],
    "network": [
        "_session_headers", "_proxies_for", "set_mirrors", "_source_count",
        "_advance_source", "_source_url", "_request_url", "_apply_cookies",
        "_apply_cookie_header", "_validator_changed", "_source_base_url",
    ],
    "files": [
        "_prepare_files", "_filename_from_headers", "_guess_filename",
        "_apply_existing_policy", "_unique_path",
        "_preallocate", "_check_disk_space", "_save_state", "_load_state",
        "_load_db_segments", "_finalize", "_cleanup_partial",
    ],
    "workers": [
        "_run", "_run_once", "_probe", "_reset_for_restart", "_start_monitor",
        "_download_segmented", "_worker", "_download_segment",
        "_download_single",
    ],
}

# The methods that stay in the Download class itself.
CORE = [
    "__init__", "start", "pause", "resume", "abandon", "cancel", "progress",
    "eta", "name", "apply_record", "_store_save", "set_speed_limit",
    "snapshot", "set_start_at", "mark_queued", "mark_scheduled",
    "_parse_retry_after", "_sleep_cancelable",
]

MIXIN_DOCS = {
    "streaming": ("Streaming media: HLS and DASH playlists (N10).\n\n"
                  "A playlist is data from a third party, so this is also where\n"
                  "the URL policy lives: only http(s) is allowed, private\n"
                  "addresses need the user's permission, and the user's own\n"
                  "headers never follow the playlist to another host."),
    "verification": ("Integrity checks: the size and the optional checksum of\n"
                     "the finished file (N3, N10)."),
    "segments": ("The work queue of pieces (N4).\n\n"
                 "The pending work is kept in a queue and re-divided as workers\n"
                 "finish, so the piece size follows the slowest connection."),
    "network": ("The HTTP side: the session, the cookies, the user's headers,\n"
                "the proxy and the alternative sources (mirrors)."),
    "files": ("The destination file and the resume state (W3, W5).\n\n"
              "The state sidecar lives next to the file; the overwrite policy\n"
              "and the disk-space check live here too."),
    "workers": ("The download loops: the probe, the workers and the monitor\n"
                "that keeps the progress and the speed up to date."),
}


def read_lines() -> list[str]:
    with open(SOURCE, "r", encoding="utf-8", newline="") as fh:
        return fh.read().split("\n")


def block(lines: list[str], node) -> list[str]:
    """The source of an ast node, decorators included."""
    start = node.lineno - 1
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno - 1)
    end = getattr(node, "end_lineno", node.lineno)
    return lines[start:end]


def main() -> int:
    lines = read_lines()
    tree = ast.parse("\n".join(lines))

    # --- the top level pieces -------------------------------------------
    constants, errors, formatting, limits, segment_class = [], [], [], [], []
    download_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name == "Download":
                download_class = node
            elif node.name == "Segment":
                segment_class = [block(lines, node)]
            elif node.name in ("RateLimiter", "GlobalRateLimiter"):
                limits.append(block(lines, node))
            elif node.name.endswith("Error") or node.name == "DownloadCanceled":
                errors.append(block(lines, node))
            else:
                constants.append(block(lines, node))
        elif isinstance(node, ast.FunctionDef):
            if node.name in ("human_size", "human_speed", "human_time",
                             "sanitize_filename"):
                formatting.append(block(lines, node))
            elif node.name in ("set_global_speed_limit", "global_speed_limit"):
                limits.append(block(lines, node))
            else:
                constants.append(block(lines, node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # The shared limiter belongs with the limiters.
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "GLOBAL_LIMITER"
                    for t in node.targets):
                limits.append(block(lines, node))
            else:
                constants.append(block(lines, node))

    # --- the methods of Download ----------------------------------------
    methods = {}
    for node in download_class.body:
        if isinstance(node, ast.FunctionDef):
            methods[node.name] = block(lines, node)

    missing = []
    for name in CORE + sum(MIXINS.values(), []):
        if name not in methods:
            missing.append(name)
    if missing:
        print("methods not found:", missing)
        return 1

    def write(name: str, text: str) -> None:
        path = os.path.join(TARGET, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    os.makedirs(TARGET)

    # --- constants.py ---------------------------------------------------
    write("constants.py", HEADER + '"""The tunables and the status strings of the engine."""\n'
          "from __future__ import annotations\n\n\n"
          + "\n\n".join("\n".join(b).rstrip() for b in constants) + "\n")

    # --- errors.py -------------------------------------------------------
    write("errors.py", HEADER + '"""The exceptions the engine raises."""\n'
          "from __future__ import annotations\n\n\n"
          + "\n\n\n".join("\n".join(b).rstrip() for b in errors) + "\n")

    # --- formatting.py ---------------------------------------------------
    write("formatting.py", HEADER + '"""Human readable sizes, speeds and times."""\n'
          "from __future__ import annotations\n\nimport re\n\n\n"
          + "\n\n\n".join("\n".join(b).rstrip() for b in formatting) + "\n")

    # --- limits.py -------------------------------------------------------
    write("limits.py", HEADER + '"""The speed limiters: one per download, one for all."""\n'
          "from __future__ import annotations\n\nimport threading\nimport time\n\n\n"
          + "\n\n\n".join("\n".join(b).rstrip() for b in limits) + "\n")

    # --- segments.py -----------------------------------------------------
    segment_body = "\n".join(segment_class[0]).rstrip()
    mixin_body = []
    for name in MIXINS["segments"]:
        mixin_body.append("\n".join(methods[name]).rstrip())
    write("segments.py", HEADER +
          '"""The pieces of a file and the work queue that hands them out."""\n'
          "from __future__ import annotations\n\n"
          "from freedm.engine.constants import (DYNAMIC_SPLITTING,\n"
          "                                   MAX_PIECE_SIZE, MAX_SEGMENTS,\n"
          "                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,\n"
          "                                   MIN_SPLIT_SIZE, PIECE_SPEED_SAMPLES,\n"
          "                                   SPLIT_TARGET_SECONDS)\n\n\n"
          + segment_body + "\n\n\nclass SegmentsMixin:\n    \"\"\""
          + MIXIN_DOCS["segments"] + "\"\"\"\n\n"
          + "\n\n".join(mixin_body) + "\n")

    # --- the other mixins -----------------------------------------------
    IMPORTS = {
        "streaming": (
            "from __future__ import annotations\n\nimport os\nimport time\n\n"
            "from freedm.engine.constants import (CONNECT_TIMEOUT,\n"
            "                                   MAX_RETRIES, READ_TIMEOUT)\n"
            "from freedm.stream import (StreamError, check_segment_url,\n"
            "                           decrypt_aes128, host_of as stream_host_of,\n"
            "                           is_stream_url, key_from_data, parse_m3u8,\n"
            "                           parse_mpd)\n"),
        "verification": (
            "from __future__ import annotations\n\nimport os\n\n"
            "from freedm.engine.constants import DONE, ERROR\n"
            "from freedm.engine.errors import VerificationError\n"
            "from freedm.verify import parse_checksum, verify_checksum, "
            "verify_size\n"),
        "network": (
            "from __future__ import annotations\n\nimport json\nimport os\n"
            "import re\nfrom urllib.parse import urlparse\n\n"
            "import requests\n\n"
            "from freedm.engine.constants import (CONNECT_TIMEOUT,\n"
            "                                   READ_TIMEOUT, USER_AGENT)\n"
            "from freedm.network import PROXY, mirror_path\n"),
        "files": (
            "from __future__ import annotations\n\nimport json\nimport os\n"
            "import shutil\nimport time\n\n"
            "from freedm.engine.constants import DISK_MARGIN, DONE\n"
            "from urllib.parse import unquote, urlparse\n"
            "import re\n"
            "from freedm.engine.errors import DownloadCanceled\n"
            "from freedm.engine.formatting import human_size, sanitize_filename\n"
            "from freedm.engine.segments import Segment\n"),
        "workers": (
            "from __future__ import annotations\n\nimport os\nimport threading\n"
            "import time\n\nimport requests\n\n"
            "from freedm.engine.constants import (CANCELED, CHUNK,\n"
            "                                   CONNECT_TIMEOUT, DONE,\n"
            "                                   DOWNLOADING, ERROR, PAUSED,\n"
            "                                   PROBING, MAX_RETRIES, READ_TIMEOUT)\n"
            "from freedm.engine.limits import GLOBAL_LIMITER\n"
            "from freedm.engine.formatting import sanitize_filename\n"
            "from freedm.stream import output_name as stream_output_name\n"
            "from freedm.engine.errors import (AuthRequiredError,\n"
            "                                       DownloadCanceled,\n"
            "                                       FileChangedError,\n"
            "                                       RangeNotSupportedError)\n"
            "from freedm.engine.segments import Segment\n"),
    }

    for name, names in MIXINS.items():
        if name == "segments":
            continue
        body = []
        for method in names:
            body.append("\n".join(methods[method]).rstrip())
        write(f"{name}.py", HEADER
              + f'"""Part of the Download class: {MIXIN_DOCS[name].splitlines()[0]}"""'
              + "\n" + IMPORTS[name] + "\n\nclass "
              + name.capitalize().replace("streaming", "streaming")
              + "Mixin:\n    \"\"\""
              + MIXIN_DOCS[name] + "\"\"\"\n\n"
              + "\n\n".join(body) + "\n")

    # --- download.py ----------------------------------------------------
    core_body = []
    for method in CORE:
        core_body.append("\n".join(methods[method]).rstrip())
    write("download.py", HEADER
          + '"""The Download class: one job."""\n'
          "from __future__ import annotations\n\nimport json\nimport os\n"
          "import shutil\nimport threading\nimport time\nfrom urllib.parse "
          "import urlparse\n\n"
          "import requests\n\n"
          "from freedm.engine.constants import (CANCELED, CHUNK,\n"
          "                                   CONNECT_TIMEOUT,\n"
          "                                   DISK_MARGIN, DOWNLOADING, DONE,\n"
          "                                   ERROR, IDLE, MAX_PIECE_SIZE,\n"
          "                                   MAX_RETRIES, MAX_SEGMENTS,\n"
          "                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,\n"
          "                                   MIN_SPLIT_SIZE, PAUSED, PROBING,\n"
          "                                   QUEUED, READ_TIMEOUT, SCHEDULED,\n"
          "                                   USER_AGENT)\n"
          "from freedm.engine.errors import (AuthRequiredError,\n"
          "                                   DownloadCanceled, FileChangedError,\n"
          "                                   RangeNotSupportedError,\n"
          "                                   VerificationError)\n"
          "from freedm.engine.files import FilesMixin\n"
          "from freedm.engine.formatting import (human_size, human_speed,\n"
          "                                     human_time, sanitize_filename)\n"
          "from freedm.engine.limits import (GLOBAL_LIMITER, GlobalRateLimiter,\n"
          "                                  RateLimiter, global_speed_limit,\n"
          "                                  set_global_speed_limit)\n"
          "from freedm.engine.network import NetworkMixin\n"
          "from freedm.engine.segments import SegmentsMixin, Segment\n"
          "from freedm.engine.streaming import StreamingMixin\n"
          "from freedm.engine.verification import VerificationMixin\n"
          "from freedm.engine.workers import WorkersMixin\n"
          "from freedm.network import PROXY, mirror_path\n"
          "from freedm.stream import (check_segment_url, is_stream_url,\n"
          "                           output_name as stream_output_name)\n\n\n"
          "class Download(FilesMixin, NetworkMixin, SegmentsMixin,\n"
          "             StreamingMixin, VerificationMixin, WorkersMixin):\n"
          '    """One download job.\n\n'
          "    The class is split over several mixins, one per concern; this is\n"
          "    the part that holds them together: the constructor, the public\n"
          "    API and the bookkeeping.\n    \"\"\"\n\n"
          + "\n\n".join(core_body) + "\n")

    # --- __init__.py ----------------------------------------------------
    write("__init__.py", HEADER
          + '"""The FreeDM download engine.\n\n'
          "The public API lives here, so ``from freedm.engine import Download``\n"
          "keeps working no matter how the code is split up inside.\n"
          '"""\n'
          "from __future__ import annotations\n\n"
          "from freedm.engine.constants import (CHUNK, CONNECT_TIMEOUT,\n"
          "                                   CANCELED, DISK_MARGIN, DONE,\n"
          "                                   DOWNLOADING, DYNAMIC_SPLITTING,\n"
          "                                   ERROR, IDLE, MAX_PIECE_SIZE,\n"
          "                                   MAX_RETRIES, MAX_SEGMENTS,\n"
          "                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,\n"
          "                                   MIN_SPLIT_SIZE, PAUSED,\n"
          "                                   PIECE_SPEED_SAMPLES, PROBING, QUEUED,\n"
          "                                   READ_TIMEOUT, SCHEDULED,\n"
          "                                   SPLIT_TARGET_SECONDS, USER_AGENT)\n"
          "from freedm.engine.download import Download\n"
          "from freedm.engine.errors import (AuthRequiredError,\n"
          "                                   DownloadCanceled, FileChangedError,\n"
          "                                   RangeNotSupportedError,\n"
          "                                   VerificationError)\n"
          "from freedm.engine.formatting import (human_size, human_speed,\n"
          "                                     human_time, sanitize_filename)\n"
          "from freedm.engine.limits import (GLOBAL_LIMITER, GlobalRateLimiter,\n"
          "                                  RateLimiter, global_speed_limit,\n"
          "                                  set_global_speed_limit)\n"
          "from freedm.engine.segments import Segment\n\n"
          "__all__ = [\n"
          '    "Download", "Segment", "RateLimiter", "GlobalRateLimiter",\n'
          '    "GLOBAL_LIMITER", "set_global_speed_limit", "global_speed_limit",\n'
          '    "human_size", "human_speed", "human_time", "sanitize_filename",\n'
          '    "DownloadCanceled", "FileChangedError", "RangeNotSupportedError",\n'
          '    "AuthRequiredError", "VerificationError",\n'
          '    "IDLE", "QUEUED", "SCHEDULED", "PROBING", "DOWNLOADING",\n'
          '    "PAUSED", "DONE", "ERROR", "CANCELED",\n'
          '    "CHUNK", "MIN_SEGMENT_SIZE", "MAX_RETRIES", "CONNECT_TIMEOUT",\n'
          '    "READ_TIMEOUT", "USER_AGENT", "DISK_MARGIN",\n'
          '    "MAX_PIECE_SIZE", "MIN_PIECE_SIZE", "MIN_SPLIT_SIZE",\n'
          '    "MAX_SEGMENTS", "SPLIT_TARGET_SECONDS", "PIECE_SPEED_SAMPLES",\n'
          '    "DYNAMIC_SPLITTING",\n'
          "]\n")
    print("the engine package is written")
    # The old module would shadow the package: remove it.
    if os.path.exists(SOURCE):
        os.remove(SOURCE)
        print(f"removed {os.path.relpath(SOURCE, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
