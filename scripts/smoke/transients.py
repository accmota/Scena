"""
Shape transient playground — click a shape to apply the selected effect.

Does not extend app_fx_lab (canvas/look lab stays separate).

Keys
----
    Life (one mutex — spawn cancels death)
    1 / D   dissolve_out (noise)
    2 / B   burn_out (soft-edge production recipe)
    7 / V   dissolve_out vortex
    8 / W   dissolve_out wipe
    9 / I   implode
    0 / U   fade_out
    X       dissolve_in (noise)
    Y       dissolve_in vortex
    T       fade_in
  Hit (stack; pop + knock compose)
    3 / F   flash
    4 / P   pulse_outline  (also toggles stun marker via on_done)
    5 / O   pop
    6 / S   spark_burst
    K       knock
    L       blink
    H       HitStack — flash + pop + knock + spark_burst
  M         Status pulse — longer pulse_outline + stun colour until on_done
  A / SPACE  Apply to all *visible* (or all for spawn/fade_in)
  R         Respawn: clear + show all
  C         clear_transients on all
  Q         Cycle FX quality
"""
from scena import *
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _hud import SmokeHud

init(width=1100, height=720, window_scale=0.72, title="Smoke — transients")
hud = SmokeHud(
    title="Transients",
    expect="Life mutex (spawn cancels death); hits stack (pop+knock); on_done updates status",
    keys="A/S effect  ·  SPACE apply-all  ·  R respawn  ·  C clear  ·  E quality  ·  1–9/letters apply",
    status="on_done: (none yet)",
)
canvas.background = (0.07, 0.08, 0.11, 1)
canvas.fx_quality = "high"

# (id, label, keys) — id used in _apply
EFFECTS = (
    ("dissolve", "Dissolve", "1/D"),
    ("burn", "Burn", "2/B"),
    ("flash", "Flash", "3/F"),
    ("pulse", "Pulse", "4/P"),
    ("pop", "Pop", "5/O"),
    ("spark", "Spark", "6/S"),
    ("vortex_out", "VortexOut", "7/V"),
    ("wipe_out", "WipeOut", "8/W"),
    ("implode", "Implode", "9/I"),
    ("fade_out", "FadeOut", "0/U"),
    ("dissolve_in", "DissolveIn", "X"),
    ("vortex_in", "VortexIn", "Y"),
    ("fade_in", "FadeIn", "T"),
    ("knock", "Knock", "K"),
    ("blink", "Blink", "L"),
    ("status", "StatusPulse", "M"),
    ("hitstack", "HitStack", "H"),
)
_effect_idx = 0

NEON = Neon("cyan")
GLOW = GlowFilter()

shapes = []


def _track(s):
    shapes.append(s)
    return s


def _shape_tag(shape):
    return getattr(shape, "id", None) or type(shape).__name__


_last_done = "on_done: (none yet)"


def _refresh_status(extra: str | None = None):
    global _last_done
    if extra is not None:
        _last_done = extra
    n = sum(1 for s, _, _ in _poses if getattr(s, "_lab_stunned", False))
    hud.status = f"{_last_done}  ·  stun={n}"


def _done(tag: str):
    """Build an on_done that logs finish and clears optional stun marker."""

    def _cb(shape):
        sid = _shape_tag(shape)
        if getattr(shape, "_lab_stunned", False):
            shape._lab_stunned = False
            try:
                base = getattr(shape, "_lab_base_color", None)
                if base is not None:
                    shape.set_color(base)
            except Exception:
                pass
        _refresh_status(f"on_done: {tag} · {sid}")

    return _cb


_track(Circle(center=(120, 520), radius=38).set_color("tomato"))
_track(Rect(center=(260, 520), width=70, height=55).set_color("gold"))
_track(Ellipse(center=(400, 520), width=90, height=50).set_color("medium orchid"))
_track(RegularPolygon(n=6, center=(540, 520), radius=36).set_color("lime"))
_ln1 = Line(p1=(620, 490), p2=(740, 550)).set_color("white")
_ln1.line_width = 5.0
_track(_ln1)

for cx, name, col in (
    (120, "n1", "deep sky blue"),
    (260, "n2", "hot pink"),
    (400, "n3", "lime"),
    (540, "n4", "orange"),
):
    s = _track(Circle(center=(cx, 360), radius=34).set_color(col))
    s.visual = NEON

g1 = _track(Circle(center=(120, 200), radius=32).set_color("cyan"))
g1.fill_filter = GLOW
g2 = _track(Rect(center=(280, 200), width=64, height=48).set_color("coral"))
g2.fill_filter = GLOW
g3 = _track(RegularPolygon(n=5, center=(440, 200), radius=32).set_color("violet"))
g3.visual = NEON
g4 = _track(Ellipse(center=(600, 200), width=80, height=40).set_color("steel blue"))
g4.visual = Neon("magenta")

_poses = []
for s in shapes:
    try:
        cx = s.center.x
        cy = s.center.y
    except Exception:
        try:
            cx = 0.5 * (s.p1.x + s.p2.x)
            cy = 0.5 * (s.p1.y + s.p2.y)
        except Exception:
            cx, cy = 0.0, 0.0
    _poses.append((s, cx, cy))
    s._lab_stunned = False
    s._lab_base_color = None


def _mark_stunned(shape):
    """Visual stand-in for game status while pulse runs."""
    if getattr(shape, "_lab_base_color", None) is None:
        try:
            p = getattr(shape, "fill", None) or getattr(shape, "line", None)
            # best-effort: store a name if set_color was used; else just flag
            shape._lab_base_color = "gold"
        except Exception:
            shape._lab_base_color = "gold"
    shape._lab_stunned = True
    try:
        shape.set_color("red")
    except Exception:
        pass
    _refresh_status()


def _current_name():
    return EFFECTS[_effect_idx][1]


def _refresh_hud():
    keys = EFFECTS[_effect_idx][2]
    hud.title = f"Transients — {_current_name()}"
    hud.expect = f"[{keys}] click a shape to apply · A=all · R=respawn"
    _refresh_status()


def _apply(shape):
    kind = EFFECTS[_effect_idx][0]
    enter_kinds = ("dissolve_in", "vortex_in", "fade_in")
    if not shape.visible and kind not in enter_kinds:
        return
    if kind == "dissolve":
        shape.dissolve_out(0.55, style="noise", on_done=_done("dissolve"))
    elif kind == "burn":
        shape.burn_out(0.65, on_done=_done("burn"))
    elif kind == "flash":
        # slightly longer so on_done is easy to notice in the log
        shape.flash(0.35, intensity=1.0, on_done=_done("flash"))
    elif kind == "pulse":
        _mark_stunned(shape)
        shape.pulse_outline(
            color=(1.0, 1.0, 1.0, 1.0),
            duration=0.6,
            on_done=_done("pulse"),
        )
    elif kind == "pop":
        shape.pop(scale=1.35, duration=0.25, on_done=_done("pop"))
    elif kind == "spark":
        shape.spark_burst(duration=0.4, amount=1.15, on_done=_done("spark"))
    elif kind == "vortex_out":
        shape.dissolve_out(0.6, style="vortex", on_done=_done("vortex"))
    elif kind == "wipe_out":
        shape.dissolve_out(0.45, style="wipe", angle=0.0, on_done=_done("wipe"))
    elif kind == "implode":
        shape.implode(0.32, on_done=_done("implode"))
    elif kind == "fade_out":
        shape.fade_out(0.4, on_done=_done("fade_out"))
    elif kind == "dissolve_in":
        shape.dissolve_in(0.55, style="noise", on_done=_done("dissolve_in"))
    elif kind == "vortex_in":
        shape.dissolve_in(0.6, style="vortex", on_done=_done("vortex_in"))
    elif kind == "fade_in":
        shape.fade_in(0.4, on_done=_done("fade_in"))
    elif kind == "knock":
        shape.knock(distance=18, angle=35, on_done=_done("knock"))
    elif kind == "blink":
        shape.blink(duration=4.0, rate=3.5, on_done=_done("blink"))
    elif kind == "status":
        # Explicit status pattern: marker while outline runs; on_done clears it
        _mark_stunned(shape)
        shape.pulse_outline(
            color=(1.0, 0.55, 0.15, 1.0),
            duration=1.0,
            on_done=_done("status"),
        )
    elif kind == "hitstack":
        shape.flash(0.2, intensity=1.0, on_done=_done("hitstack"))
        shape.pop(scale=1.25, duration=0.22)
        shape.knock(distance=14, angle=40)
        shape.spark_burst(duration=0.4, amount=1.1)


def _respawn_all():
    for s, cx, cy in _poses:
        s.clear_transients()  # no on_done
        s.visible = True
        s._lab_stunned = False
        try:
            s.move_to(cx, cy)
        except Exception:
            pass
    _refresh_status("on_done: (cleared / respawn — no callbacks)")
    _refresh_status()


def _clear_all():
    for s, _, _ in _poses:
        s.clear_transients()
        s._lab_stunned = False
    _refresh_status("on_done: (clear_transients — no callbacks)")
    _refresh_status()


@click(*shapes)
def _on_shape_click(shape):
    _apply(shape)


def setup(canvas):
    _refresh_hud()
    _refresh_status()


def on_key_down(key):
    global _effect_idx
    k = str(key).upper()
    # Nav first (do not steal A/S/E for letter shortcuts).
    if k == "A":
        _effect_idx = (_effect_idx - 1) % len(EFFECTS)
        _refresh_hud()
        return
    if k == "S":
        _effect_idx = (_effect_idx + 1) % len(EFFECTS)
        _refresh_hud()
        return
    if k == "E":
        from _hud import cycle_quality
        hud.status = f"fx_quality={cycle_quality()}"
        return
    mapping = {
        "1": 0, "D": 0,           # dissolve
        "2": 1, "B": 1,           # burn
        "3": 2, "F": 2,           # flash
        "4": 3, "P": 3,           # pulse
        "5": 4, "O": 4,           # pop
        "6": 5,                   # spark
        "7": 6, "V": 6,           # vortex_out
        "8": 7,                   # wipe_out
        "9": 8, "I": 8,           # implode
        "0": 9, "U": 9,           # fade_out
        "X": 10,                  # dissolve_in
        "Y": 11,                  # vortex_in
        "T": 12,                  # fade_in
        "K": 13,                  # knock
        "L": 14,                  # blink
        "M": 15,                  # status
        "H": 16,                  # hitstack
    }
    if k in mapping:
        _effect_idx = mapping[k]
        _refresh_hud()
        return
    if k == "SPACE":
        enter_kinds = {"dissolve_in", "vortex_in", "fade_in"}
        kind = EFFECTS[_effect_idx][0]
        for s, _, _ in _poses:
            if s.visible or kind in enter_kinds:
                _apply(s)
        return
    if k == "R":
        _respawn_all()
        return
    if k == "C":
        _clear_all()
        return


run()
