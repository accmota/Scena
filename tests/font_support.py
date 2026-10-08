"""A font *file* every test machine has, for tests of ``font="….ttf"``.

Not a test module (no ``test_`` prefix). The tests once read
``media/fonts/Tiny5-Regular.ttf``, a file that was never tracked: they failed
on every other checkout. A monospace system face differs in width from the
default UI font, which is all those tests need.

Only explicit paths are checked (no directory scan: see
``test_platform_portability.TestSourceScansUseTheHelper``).
"""
from __future__ import annotations

import os
from typing import Optional

_WINDIR = os.environ.get("WINDIR", r"C:\Windows")

# First hit wins. One monospace family per platform's default install, then
# common alternates (Linux distributions ship DejaVu or Liberation).
FONT_FILE_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Courier New.ttf",      # macOS
    "/Library/Fonts/Courier New.ttf",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    os.path.join(_WINDIR, "Fonts", "cour.ttf"),                # Windows: Courier New
    os.path.join(_WINDIR, "Fonts", "consola.ttf"),
    os.path.join(_WINDIR, "Fonts", "lucon.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",     # Debian / Ubuntu
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",                 # Arch
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",  # Fedora
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
)


def system_font_file() -> Optional[str]:
    """Path of a monospace ``.ttf`` installed with the OS, or ``None``."""
    for path in FONT_FILE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None
