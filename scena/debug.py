"""Engine probes that are not part of the author star-import.

Import from here instead of the defining module:

    from scena.debug import set_leak_detector, set_sync_watchdog
"""
from .orchestration import set_leak_detector
from .process import set_sync_watchdog
from .recipes import (
    get_extrude_focus,
    get_metal_light,
    set_extrude_focus,
    set_metal_light,
)

__all__ = (
    "set_leak_detector",
    "set_sync_watchdog",
    "set_extrude_focus",
    "get_extrude_focus",
    "set_metal_light",
    "get_metal_light",
)
