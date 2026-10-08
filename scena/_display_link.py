"""macOS vblank grid from a CoreVideo display link (ctypes, stdlib only).

Used by ``pacing.FramePacer`` (``DISPLAY_LINK`` strategy). CoreVideo calls
``_on_vsync`` on its own thread once per refresh with ``inOutputTime``: the
host time of the vblank the next frame will be shown at. That timestamp is
the display's, so a callback delayed by the GIL still records the right time;
the main thread never waits for the callback, it reads the fitted grid.

Safety (a ctypes callback into a dead interpreter crashes the process):

* the callback object is kept alive for the life of the process;
* ``stop()`` (``run()`` cleanup) and an ``atexit`` hook stop the link;
* the callback only appends under a lock (also safe on free-threaded builds).

``CVDisplayLink`` is a plain C API: failures are error codes, so ``start()``
returns False with ``error`` set and the pacer falls back to a timer. It is
deprecated in macOS 15 in favour of ``CADisplayLink`` (Objective-C only; a
ctypes bridge could segfault with no fallback). OpenGL, which Scena runs on,
is deprecated too, so it would go first.
"""
from __future__ import annotations

import atexit
import ctypes
import ctypes.util
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple

from .pacing import VblankGrid

# Callbacks and links stay referenced until exit (see module docstring).
_KEEPALIVE: List[object] = []
_LIVE_LINKS: "List[DisplayLink]" = []


class _SMPTE(ctypes.Structure):
    _fields_ = [
        ("subframes", ctypes.c_int16), ("subframeDivisor", ctypes.c_int16),
        ("counter", ctypes.c_uint32), ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("hours", ctypes.c_int16),
        ("minutes", ctypes.c_int16), ("seconds", ctypes.c_int16),
        ("frames", ctypes.c_int16),
    ]


class CVTimeStamp(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32), ("videoTimeScale", ctypes.c_int32),
        ("videoTime", ctypes.c_int64), ("hostTime", ctypes.c_uint64),
        ("rateScalar", ctypes.c_double), ("videoRefreshPeriod", ctypes.c_int64),
        ("smpteTime", _SMPTE), ("flags", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64),
    ]


class CVTime(ctypes.Structure):
    _fields_ = [("timeValue", ctypes.c_int64), ("timeScale", ctypes.c_int32),
                ("flags", ctypes.c_int32)]


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


CALLBACK_T = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p,
    ctypes.POINTER(CVTimeStamp), ctypes.POINTER(CVTimeStamp),
    ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_void_p,
)

# How often the pacer re-checks which display the window is on (s).
FOLLOW_EVERY_S = 0.5


def host_time_scale() -> Tuple[float, float]:
    """``(seconds per host tick, perf_counter - host seconds)``.

    ``perf_counter`` is ``mach_absolute_time`` on macOS (3.12 and 3.14), so
    the offset is ~0; it is measured anyway (min of back-to-back reads) rather
    than assumed.
    """
    libc = ctypes.CDLL(None)

    class _TB(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    tb = _TB()
    libc.mach_timebase_info(ctypes.byref(tb))
    scale = tb.numer / tb.denom / 1e9
    libc.mach_absolute_time.restype = ctypes.c_uint64
    best = None
    for _ in range(5):
        a = time.perf_counter()
        h = libc.mach_absolute_time() * scale
        b = time.perf_counter()
        cand = (b - a, (a + b) / 2.0 - h)
        if best is None or cand[0] < best[0]:
            best = cand
    return scale, best[1]


class DisplayLink:
    """A running CVDisplayLink feeding a :class:`VblankGrid`.

    ``window_center`` (optional) returns the window centre in global screen
    points; the link follows the window to the display under it.
    """

    def __init__(self, window_center: Optional[Callable[[], Optional[Tuple[float, float]]]] = None) -> None:
        self.grid = VblankGrid()
        self.nominal_period: Optional[float] = None
        self.available = False
        self.error: Optional[str] = None
        self.display_id: Optional[int] = None
        self._window_center = window_center
        self._lock = threading.Lock()
        self._pending: List[float] = []
        self._link = ctypes.c_void_p()
        self._cv = None
        self._cg = None
        self._scale = 1.0
        self._offset = 0.0
        self._next_follow = 0.0
        self._running = False

    # -- lifetime -----------------------------------------------------------
    def start(self) -> bool:
        if sys.platform != "darwin":
            self.error = "display link needs macOS (CoreVideo)"
            return False
        try:
            self._scale, self._offset = host_time_scale()
            cv = ctypes.CDLL(ctypes.util.find_library("CoreVideo"))
            cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
            cv.CVDisplayLinkCreateWithCGDisplay.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
            cv.CVDisplayLinkCreateWithActiveCGDisplays.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            cv.CVDisplayLinkSetOutputCallback.argtypes = [ctypes.c_void_p, CALLBACK_T, ctypes.c_void_p]
            cv.CVDisplayLinkSetCurrentCGDisplay.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            cv.CVDisplayLinkGetNominalOutputVideoRefreshPeriod.argtypes = [ctypes.c_void_p]
            cv.CVDisplayLinkGetNominalOutputVideoRefreshPeriod.restype = CVTime
            for name in ("CVDisplayLinkStart", "CVDisplayLinkStop", "CVDisplayLinkRelease"):
                getattr(cv, name).argtypes = [ctypes.c_void_p]
            cv.CVDisplayLinkRelease.restype = None
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGGetDisplaysWithPoint.argtypes = [
                CGPoint, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32)]
            self._cv, self._cg = cv, cg

            display = self._display_under_window()
            if display is None:
                display = int(cg.CGMainDisplayID())
            if cv.CVDisplayLinkCreateWithCGDisplay(display, ctypes.byref(self._link)) != 0:
                if cv.CVDisplayLinkCreateWithActiveCGDisplays(ctypes.byref(self._link)) != 0:
                    self.error = "CVDisplayLinkCreate failed"
                    return False
            self.display_id = display
            cb = CALLBACK_T(self._on_vsync)
            _KEEPALIVE.append(cb)
            if cv.CVDisplayLinkSetOutputCallback(self._link, cb, None) != 0:
                self.error = "CVDisplayLinkSetOutputCallback failed"
                return False
            self._read_nominal()
            if cv.CVDisplayLinkStart(self._link) != 0:
                self.error = "CVDisplayLinkStart failed"
                return False
            self._running = True
            self.available = True
            _KEEPALIVE.append(self._link)
            _LIVE_LINKS.append(self)
            return True
        except Exception as exc:  # environment: CoreVideo missing / refused
            self.error = f"display link unavailable: {exc!r}"
            return False

    def stop(self) -> None:
        if not self._running or self._cv is None:
            return
        self._running = False
        try:
            self._cv.CVDisplayLinkStop(self._link)
        except Exception:
            pass
        if self in _LIVE_LINKS:
            _LIVE_LINKS.remove(self)

    # -- CoreVideo thread -----------------------------------------------------
    def _on_vsync(self, _link, _now, out, _flags_in, _flags_out, _ctx) -> int:
        try:
            t = out.contents.hostTime * self._scale + self._offset
            with self._lock:
                self._pending.append(t)
        except Exception:
            pass
        return 0

    # -- main thread ------------------------------------------------------------
    def poll(self, now: float) -> None:
        """Move stamps from the callback into the grid; follow the window."""
        with self._lock:
            pending, self._pending = self._pending, []
        for t in pending:
            self.grid.add(t)
        if self._window_center is not None and now >= self._next_follow:
            self._next_follow = now + FOLLOW_EVERY_S
            self._follow_window()

    def _read_nominal(self) -> None:
        try:
            t = self._cv.CVDisplayLinkGetNominalOutputVideoRefreshPeriod(self._link)
            if t.timeScale > 0 and t.timeValue > 0:
                self.nominal_period = t.timeValue / float(t.timeScale)
                self.grid.period_hint = self.nominal_period
        except Exception:
            pass

    def _display_under_window(self) -> Optional[int]:
        if self._window_center is None or self._cg is None:
            return None
        try:
            c = self._window_center()
            if c is None:
                return None
            ids = (ctypes.c_uint32 * 1)()
            count = ctypes.c_uint32(0)
            if self._cg.CGGetDisplaysWithPoint(CGPoint(float(c[0]), float(c[1])), 1, ids,
                                               ctypes.byref(count)) != 0:
                return None
            return int(ids[0]) if count.value >= 1 else None
        except Exception:
            return None

    def _follow_window(self) -> None:
        display = self._display_under_window()
        if display is None or display == self.display_id:
            return
        if self._cv.CVDisplayLinkSetCurrentCGDisplay(self._link, display) == 0:
            self.display_id = display
            self.grid.clear()
            self._read_nominal()


@atexit.register
def _stop_all_links() -> None:
    for link in list(_LIVE_LINKS):
        link.stop()
