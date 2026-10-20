"""pytest configuration.

Makes the project importable (``freedm.*``) no matter where pytest is
started from, and lets the GUI suites be skipped on a machine without a
display."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
