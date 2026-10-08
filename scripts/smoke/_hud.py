"""Shared HUD chrome for smoke tests.

Layout (design coords, y-up)
----------------------------
System FPS / info lives at bottom-left (~y=16). Smoke chrome stays at the
**top** and never writes below ``SAFE_BOTTOM``.

    ┌─────────────────────────────────────────────┐
    │  TITLE                                      │  top
    │  expect — what you should see               │
    │  keys — controls                            │
    │  status — live feedback                     │
    │  aux — optional 2nd live line (e.g. clock)  │
    │                                             │
    │              (scene content)                │
    │                                             │
    │  FPS: … objs: …          ← framework only   │  bottom (reserved)
    └─────────────────────────────────────────────┘

Navigation convention
---------------------
  Arrows          pan camera / move something on screen
  Shift+← / →     rotate camera (where applicable)
  Shift+↑ / ↓     zoom in / out (where applicable)
  A / S           previous / next **primary** item (mode, page, focus, effect)
  Q / W           previous / next **secondary** item, or paired −/+ (e.g. clock scale)
  E               cycle FX quality (when relevant)
  SPACE           pause **or** clear/baseline — stated in ``keys=``

Do **not** use ``[`` / ``]`` or bare ←/→ for cycling catalogs.
Do **not** add extra title/hint Text that duplicate this chrome.
Section captions stay clear of the top band and the bottom reserved strip.
"""
from __future__ import annotations

from scena import Color, Text

# Framework system caption (FPS line): bottom edge at y=16, x=20, font_size=14 (orchestration).
# SCENA ERROR banner sits above it (y=42, opaque plate) when an author hook raises.
SAFE_BOTTOM = 48.0
# Top chrome occupies roughly this many design units from the top edge.
TOP_BAND = 130.0


def shift_held() -> bool:
    from scena import keyp

    return bool(keyp("SHIFT"))


def apply_camera(
    dt: float,
    *,
    about=(0.0, 0.0),
    pan_speed: float = 280.0,
    zoom_rate: float = 0.6,
    rot_rate: float = 40.0,
) -> None:
    """Arrows pan; Shift+←/→ rotate; Shift+↑/↓ zoom."""
    from scena import canvas, keyp

    if keyp("SHIFT+LEFT"):
        canvas.rotate_by(rot_rate * dt, about=about)
    if keyp("SHIFT+RIGHT"):
        canvas.rotate_by(-rot_rate * dt, about=about)
    if keyp("SHIFT+UP"):
        canvas.zoom_by(1.0 + zoom_rate * dt, about=about)
    if keyp("SHIFT+DOWN"):
        canvas.zoom_by(1.0 / (1.0 + zoom_rate * dt), about=about)
    if keyp("LEFT"):
        canvas.pan_by(-pan_speed * dt, 0)
    if keyp("RIGHT"):
        canvas.pan_by(pan_speed * dt, 0)
    if keyp("UP"):
        canvas.pan_by(0, pan_speed * dt)
    if keyp("DOWN"):
        canvas.pan_by(0, -pan_speed * dt)


def cycle_quality() -> str:
    """Advance canvas.fx_quality; return new value string."""
    from scena import canvas

    ladder = ("low", "medium", "high", "max")
    cur = canvas.fx_quality
    name = cur.value if cur is not None else "high"
    i = ladder.index(name) if name in ladder else 2
    nxt = ladder[(i + 1) % len(ladder)]
    canvas.fx_quality = nxt
    return nxt


class SmokeHud:
    """Stacked Text captions at the top of the design window (view space)."""

    def __init__(
        self,
        *,
        title: str = "",
        expect: str = "",
        keys: str = "",
        status: str = "",
        aux: str = "",
        x: float = 24.0,
        font_size: int = 17,
        show_aux: bool = False,
    ):
        from scena import canvas

        y_top = float(canvas.height) - 28.0
        self._title = Text(
            text=title,
            top_left=(x, y_top + 15),
            font_size=font_size,
            color=Color(0.95, 0.96, 1.0, 1),
        )
        self._expect = Text(
            text=expect,
            top_left=(x, y_top - 24.0 + 15),
            font_size=max(13, font_size - 3),
            color=Color(0.78, 0.84, 0.94, 1),
        )
        self._keys = Text(
            text=keys,
            top_left=(x, y_top - 46.0 + 15),
            font_size=max(12, font_size - 4),
            color=Color(0.55, 0.62, 0.75, 1),
        )
        self._status = Text(
            text=status,
            top_left=(x, y_top - 68.0 + 15),
            font_size=max(12, font_size - 4),
            color=Color(0.92, 0.82, 0.45, 1),
        )
        self._aux = Text(
            text=aux,
            top_left=(x, y_top - 90.0 + 15),
            font_size=max(12, font_size - 4),
            color=Color(0.55, 0.85, 0.75, 1),
        )
        if not show_aux and not aux:
            self._aux.visible = False

    def set_item(
        self,
        title: str,
        expect: str,
        keys: str,
        status: str = "",
    ) -> None:
        self.title = title
        self.expect = expect
        self.keys = keys
        if status:
            self.status = status

    @property
    def title(self) -> str:
        return str(self._title.text)

    @title.setter
    def title(self, value: str) -> None:
        self._title.text = value

    @property
    def expect(self) -> str:
        return str(self._expect.text)

    @expect.setter
    def expect(self, value: str) -> None:
        self._expect.text = value

    @property
    def keys(self) -> str:
        return str(self._keys.text)

    @keys.setter
    def keys(self, value: str) -> None:
        self._keys.text = value

    @property
    def status(self) -> str:
        return str(self._status.text)

    @status.setter
    def status(self, value: str) -> None:
        self._status.text = value

    @property
    def aux(self) -> str:
        return str(self._aux.text)

    @aux.setter
    def aux(self, value: str) -> None:
        self._aux.visible = True
        self._aux.text = value
