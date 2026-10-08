"""Shim: re-export FrameProfiler from scripts/bench/frame_profile.py."""
from __future__ import annotations

import os
import sys

_BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from frame_profile import *  # noqa: F401,F403,E402
