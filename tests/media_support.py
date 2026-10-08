"""Repo media for tests: the tracked, licensed files under ``examples/media/``.

Not a test module (no ``test_`` prefix). Tests that read a real image, sheet,
sound or SVG take its path from ``media(...)`` / ``smoke(...)``. Both
**assert** the file exists. The media is tracked, so a missing file is a
broken test, never a ``skipTest`` (bug class: Testing Design.md, "A media
path is dead and nothing says so").
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "examples", "media")
SMOKE = os.path.join(ROOT, "scripts", "smoke")


def _existing(path: str) -> str:
    assert os.path.isfile(path), f"tracked media file missing: {os.path.relpath(path, ROOT)}"
    return path


def media(*parts: str) -> str:
    """Absolute path of ``examples/media/<parts>``; asserts it exists."""
    return _existing(os.path.join(MEDIA, *parts))


def smoke(*parts: str) -> str:
    """Absolute path of ``scripts/smoke/<parts>``; asserts it exists."""
    return _existing(os.path.join(SMOKE, *parts))
