# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Test helper: start a download, pause, then abruptly exit the process
(simulates a crash / force-close so OS releases file handles)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import Download  # noqa: E402

out = sys.argv[1]
url = sys.argv[2]
dl = Download(url, dest_dir=out, num_threads=8, speed_limit=6 * 1024 * 1024)
dl.start()
time.sleep(1.5)
dl.pause()
time.sleep(0.4)
sys.stdout.write(f"SESSION1 paused at {dl.downloaded}\n")
sys.stdout.flush()
os._exit(0)   # abrupt exit: no cleanup, like a crash
