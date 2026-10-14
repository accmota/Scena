"""The geometry campaign's axes, derived from the code (Testing Design — Geometry campaign).

Not a test module. One table, used by every campaign harness:

====  ==========================================================================
K     kind × model: ``geometry_support.KINDS`` plus a builder for every
      ``_CONSTRUCTOR_SIGNATURES`` row it does not reach (the ``*_angle`` rows
      without ``angle=``, ``from_rect_padding``)
B     base state: fresh, flipped, turned past a full turn, scaled, ``MIN_SCALE``,
      degenerate, names crossed, cross-model copied, cloned, mid-tween,
      parked, collidable with a warm collision cache, drawn once
W     warmth: what was read before the step (none, all, all reversed, one part,
      all but one)
L     link configuration: none, a field linked to a cell, a point part linked to
      a cell, the whole object linked to another shape, the subject as the
      source of another shape's link, a chain from another shape's part, a
      constructor lambda
V     step: every pose verb (the contract's ``VERBS``), plus flips back off
R     read order after the step: cold, sorted, reversed, the link first
X     execution twin: normal, forced slow, bare-read caches dropped, inside a
      ``batch``, inside a frame
====  ==========================================================================

Each axis reads the instance (slots, signatures, model enums) or the engine's
public surface, never a table a fix maintains (lesson 2 of the graphics
review). ``test_geom_axes`` checks that every constructor row, every model
and every public pose verb has a value here, or a reason why not.

``Reach`` counts which value of which axis a harness really ran; a harness
asserts every value was reached (no vacuous pass).
"""
from __future__ import annotations

import collections
import math
import os
import sys
import warnings
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geometry_support as G  # noqa: E402
from scena import (  # noqa: E402
    Box, Circle, Ellipse, Triangle, Line, Point, Rect, RegularPolygon, Square,
    State, Track,
)
from scena.validate import MIN_SCALE  # noqa: E402

XY = Tuple[float, float]


# ---------------------------------------------------------------------------
# K — kind × model × constructor row
# ---------------------------------------------------------------------------

def _q(fn):
    return G._quiet(fn)


# Builders for constructor rows ``geometry_support.KINDS`` does not reach. The
# KINDS builders pass ``angle=`` wherever the model takes it, so the rows
# without it (the shape built level) come from here.
EXTRA_KINDS: Dict[str, Callable] = {
    "Ellipse center_wh noangle": lambda p: Ellipse(center=(p["x"], p["y"]), width=30 * p["s"], height=12 * p["s"]),
    "Ellipse from_rect padding": lambda p: Ellipse(
        from_rect=Rect(center=(p["x"], p["y"]), width=30 * p["s"], height=12 * p["s"], angle=p["r"]),
        padding=3 * p["s"]),
    "Rect center_wh noangle": lambda p: Rect(center=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"]),
    "Rect top_left_wh noangle": lambda p: Rect(top_left=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"]),
    "Rect corner_corner noangle": lambda p: Rect(p1=(p["x"], p["y"]), p2=G._at(p, 40, 16)),
    "Rect point_vec noangle": lambda p: Rect(p1=(p["x"], p["y"]), vec=(40 * p["s"], 16 * p["s"])),
    "Square center_length noangle": lambda p: Square(center=(p["x"], p["y"]), length=20 * p["s"]),
    "Square top_left_length noangle": lambda p: Square(top_left=(p["x"], p["y"]), length=20 * p["s"]),
    "RegularPolygon center_radius noangle": lambda p: RegularPolygon(center=(p["x"], p["y"]), radius=6 * p["s"], n=5),
    "RegularPolygon center_side noangle": lambda p: RegularPolygon(center=(p["x"], p["y"]), side=6 * p["s"], n=4),
    "RegularPolygon vertex_side noangle": lambda p: RegularPolygon(vertex=(p["x"], p["y"]), side=6 * p["s"], n=6),
    "Triangle center_radius noangle": lambda p: Triangle(center=(p["x"], p["y"]), radius=6 * p["s"]),
    "Triangle center_side noangle": lambda p: Triangle(center=(p["x"], p["y"]), side=6 * p["s"]),
    "Triangle vertex_side noangle": lambda p: Triangle(vertex=(p["x"], p["y"]), side=6 * p["s"]),
}

def _sheet_sprite(anchor):
    """A Sprite over real art with a Sheet anchor (its pivot is not the cell's center)."""
    def build_(p):
        from media_support import media
        from scena import Sheet, Sprite
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = Sprite(Sheet(media("space", "enemyGreen1.png"), anchor=anchor),
                       center=(p["x"], p["y"]), height=20 * p["s"])
        return G._rotated(s, p["r"])
    return build_


# Sprite × sheet anchor (H6): the pivot sits off the cell's center, so every
# verb and flip turns the art about a point that is not its middle.
EXTRA_KINDS.update({
    "Sprite sheet bottom": _sheet_sprite("bottom"),
    "Sprite sheet left": _sheet_sprite("left"),
    "Sprite sheet pair": _sheet_sprite((0.3, -0.2)),
})

K: Dict[str, Callable] = {**G.KINDS, **EXTRA_KINDS}

# Constructor rows no K builder reaches, each with its reason.
ROWS_NOT_BUILT: Dict[Tuple[str, str], str] = {
    ("Box", "spine"): "Box shares Rect's table but has no p1=, p2=, height= region",
    ("Box", "corner_corner"): "Box parses its own keywords (box._CONSTRUCTOR_SIGNATURES is Rect's, read for messages)",
    ("Box", "corner_corner_angle"): "same",
    ("Box", "top_left_wh"): "same",
    ("Box", "top_left_wh_angle"): "same",
    ("Box", "center_wh"): "same",
    ("Box", "center_wh_angle"): "same",
    ("Box", "point_vec"): "same",
    ("Box", "point_vec_angle"): "same",
}


def family(kind: str) -> str:
    return kind.split()[0]


def build(kind: str, p: Optional[dict] = None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return K[kind](dict(G.P0) if p is None else dict(p))


def signature_reach() -> Dict[Tuple[str, str], int]:
    """(class, signature) -> builds, over every K builder (a spy on the matcher)."""
    from unittest import mock
    from scena.state import Container
    reached: Dict[Tuple[str, str], int] = collections.Counter()
    owner = next(c for c in Container.__mro__
                 if "_extract_common_params_and_signature" in c.__dict__)
    real = owner.__dict__["_extract_common_params_and_signature"].__func__

    def spy(cls, *a, **kw):
        out = real(cls, *a, **kw)
        reached[(cls.__name__, out[1])] += 1
        return out
    with mock.patch.object(owner, "_extract_common_params_and_signature", classmethod(spy)):
        objs = [build(k) for k in K]
    for o in objs:
        _destroy(o)
    return dict(reached)


def every_signature_row() -> List[Tuple[str, str]]:
    """Every constructor row of every in-scope class, read from the classes."""
    import scena.box as box_mod
    out = []
    for cls in (Line, Circle, Ellipse, Rect, Square, RegularPolygon, Triangle):
        for name, _keys in cls._CONSTRUCTOR_SIGNATURES:
            out.append((cls.__name__, name))
    for name, _keys in box_mod._CONSTRUCTOR_SIGNATURES:
        out.append(("Box", name))
    return out


def _destroy(o):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for x in (getattr(o, "_ref", None), o):
            if x is not None and getattr(x, "is_alive", False) and hasattr(x, "destroy"):
                try:
                    x.destroy()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Subject reads (cold engine readers vs public reads)
# ---------------------------------------------------------------------------

def public_reads(obj) -> Dict[str, Callable]:
    """name -> reader of every public part a test may read (points, scalars, pose)."""
    out: Dict[str, Callable] = {}
    out.update(G.point_parts(obj))
    out.update(G.scalar_parts(obj))
    out.update(G.vector_parts(obj))
    if not isinstance(obj, Point) or True:
        out["angle"] = lambda o=obj: float(o.angle)
    if not G.is_box(obj):
        out["scale"] = lambda o=obj: float(o.scale)
    return out


# ---------------------------------------------------------------------------
# B — base state
# ---------------------------------------------------------------------------

def _defining(obj) -> set:
    names = getattr(obj, "_defining_part_names", ())
    if callable(names):
        names = names()
    return set(names or ())


def _size_field(obj) -> Optional[str]:
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    names = set(slots) & _defining(obj)
    for n in ("width", "radius", "length", "side", "major_axis", "height"):
        if n in names:
            return n
    return None


def _degenerate(obj, w) -> bool:
    if isinstance(obj, Line) and getattr(obj.model, "name", "") == "POINT_POINT":
        obj.p2 = (float(obj.p1.x), float(obj.p1.y))
        return True
    name = _size_field(obj)
    if name is None:
        return False
    setattr(obj, name, 0.0)
    return True


def _names_crossed(obj, w) -> bool:
    model = getattr(getattr(obj, "model", None), "name", None)
    if type(obj).__name__ not in ("Rect", "Concave", "Box") or model != "CORNER_CORNER":
        return False
    obj.top_left                     # names fixed at first use
    p1 = (float(obj.p1.x), float(obj.p1.y))
    p2 = (float(obj.p2.x), float(obj.p2.y))
    obj.p2 = (2 * p1[0] - p2[0], p2[1])     # p2 crosses to the other side of p1
    return True


def _copy_cross_model(obj, w):
    """``d << s`` into a fresh object of another model of the same class."""
    if G.is_box(obj) or isinstance(obj, (Point, Track)) or type(obj).__name__ in ("Sprite", "Svg", "Text"):
        return None
    twin_kind = {
        "Line": "Line center_length", "Circle": "Circle two_points", "Ellipse": "Ellipse focal_points",
        "Rect": "Rect corner_corner", "Square": "Square top_left_length",
        "Concave": "Concave corner_corner reversed",
        "RegularPolygon": "RegularPolygon vertex_side", "Triangle": "Triangle vertex_side",
        "Polygon": "Polygon",
    }.get(type(obj).__name__)
    if twin_kind is None:
        return None
    if type(obj).__name__ == "RegularPolygon":
        # A copy keeps n (a different n refuses: ValueError, by design).
        d = w.track(RegularPolygon(vertex=(-50.0, 60.0), side=5.0, n=int(obj._n)))
        d << obj
        return d
    d = w.track(build(twin_kind, dict(G.P0, x=-50.0, y=60.0)))
    d << obj
    return d


def _mid_tween(obj, w) -> bool:
    if G.is_box(obj):
        return False
    obj.rotate_by(90, time=1.0)
    G.settle(0.5)
    return True


def _collidable(obj, w) -> bool:
    if G.is_box(obj) or isinstance(obj, (Point, Track)) or type(obj).__name__ == "Text":
        return False
    from scena.collision import snapshot_shape
    obj.collidable = True
    col = getattr(obj, "_collider", None)
    snapshot_shape(obj, cache_owner=col)        # the pose-keyed prim cache is warm
    return True


def _drawn(obj, w) -> bool:
    if G.is_box(obj):
        return False
    import skia
    surf = skia.Surface(64, 64)
    obj.draw(surf.getCanvas())
    return True


def _flip(axis):
    def run(obj, w):
        if not G.can_flip(obj):
            return False
        for a in axis:
            setattr(obj, "flip_" + a, True)
        return True
    return run


def _rotated(obj, w):
    obj.rotate_by(400)
    return True


def _scaled(obj, w):
    if G.is_box(obj):
        return False
    obj.scale_by(2.5)
    return True


def _min_scale(obj, w):
    if G.is_box(obj):
        return False
    obj.scale_to(MIN_SCALE)
    return True


def _cloned(obj, w):
    if G.is_box(obj) or not hasattr(obj, "clone"):
        return None
    return w.track(obj.clone())


def _parked(obj, w):
    if G.is_box(obj):
        return False
    obj.active = False
    return True


# name -> apply(obj, world). Returns True (applied in place), False (does not
# apply to this kind), or a new subject that replaces ``obj`` (copy, clone).
B: Dict[str, Callable] = {
    "fresh": lambda obj, w: True,
    "flip_x": _flip("x"),
    "flip_y": _flip("y"),
    "flip_xy": _flip("xy"),
    "rotated": _rotated,
    "scaled": _scaled,
    "min_scale": _min_scale,
    "degenerate": _degenerate,
    "names_crossed": _names_crossed,
    "copied": _copy_cross_model,
    "cloned": _cloned,
    "mid_tween": _mid_tween,
    "parked": _parked,
    "collidable": _collidable,
    "drawn": _drawn,
}


def apply_base(name: str, obj, w):
    """Put ``obj`` in base state ``name``. Returns the subject, or None if N/A.

    A relational shape refuses the base verbs that would move a linked part
    (``LinkedAttributeError``): that base does not apply to it."""
    from scena.state import LinkedAttributeError
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            out = B[name](obj, w)
        except LinkedAttributeError:
            if G.is_relational(obj):
                return None
            raise
    if out is False or out is None and name in ("copied", "cloned"):
        return None
    if out is True:
        return obj
    return out


# ---------------------------------------------------------------------------
# W — warmth (reads before the step)
# ---------------------------------------------------------------------------

def _read_all(obj, names):
    reads = public_reads(obj)
    for n in names:
        G.safe(reads[n]) if n in reads else None


W: Dict[str, Callable] = {
    "cold": lambda obj: None,
    "all": lambda obj: _read_all(obj, sorted(public_reads(obj))),
    "all_reversed": lambda obj: _read_all(obj, sorted(public_reads(obj), reverse=True)),
    "angle_first": lambda obj: _read_all(obj, ["angle"] + sorted(public_reads(obj))),
    "one": lambda obj: _read_all(obj, sorted(public_reads(obj))[:1]),
    "all_but_one": lambda obj: _read_all(obj, sorted(public_reads(obj))[1:]),
}


# ---------------------------------------------------------------------------
# L — link configuration
# ---------------------------------------------------------------------------

class LinkCtx:
    """What a link configuration installed: the cell to move, and readers."""

    def __init__(self, name, cell=None, sink=None, source=None, field=None):
        self.name = name
        self.cell = cell          # State bag driving the subject (``v``, or ``x`` / ``y``)
        self.sink = sink          # another shape linked to the subject
        self.source = source      # another shape the subject is linked to
        self.field = field        # the subject's linked field / part


_BAGS = [0]


def new_bag() -> State:
    """One State per link: a formula reads ``bag.v`` by name (no ``getattr``)."""
    _BAGS[0] += 1
    return State(name=f"geomcampaign{_BAGS[0]}")


def _linkable_scalar(obj) -> Optional[str]:
    """A Defining scalar slot of ``obj`` (from the slots, never a hand list)."""
    from scena.state import ScalarSlot
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    defining = _defining(obj)
    for name, slot in sorted(slots.items()):
        if isinstance(slot, ScalarSlot) and name in defining:
            return name
    return None


def _linkable_point(obj) -> Optional[str]:
    from scena.state import ContainerSlot
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    defining = _defining(obj)
    for name, slot in sorted(slots.items()):
        if (isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Point"
                and name in defining):
            return name
    return None


def linkable_parts(obj) -> List[Tuple[str, bool]]:
    """Every Defining scalar (False) and point (True) a link can drive."""
    from scena.state import ContainerSlot, ScalarSlot
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    defining = _defining(obj)
    out = []
    for name, slot in sorted(slots.items()):
        if name not in defining:
            continue
        if isinstance(slot, ScalarSlot):
            out.append((name, False))
        elif isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Point":
            out.append((name, True))
    return out


def link_part(obj, name: str, is_point: bool) -> Optional[LinkCtx]:
    """Link one named Defining part to a fresh bag (the per-part field / part links)."""
    if G.is_relational(obj) or type(obj).__name__ == "Anchor":
        return None
    st = new_bag()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if is_point:
            pt = getattr(obj, name)
            st.x, st.y = float(pt.x), float(pt.y)
            obj[name] @= lambda: (st.x, st.y)
        else:
            st.v = float(getattr(obj, name))
            obj[name] @= lambda: st.v
    return LinkCtx("part" if is_point else "field", cell=st, field=name)


def _l_none(obj, w):
    return LinkCtx("none")


def _l_field(obj, w):
    name = _linkable_scalar(obj)
    if name is None or G.is_relational(obj):
        return None
    st = new_bag()
    st.v = float(getattr(obj, name))
    obj[name] @= lambda: st.v
    return LinkCtx("field", cell=st, field=name)


def _l_part(obj, w):
    name = _linkable_point(obj)
    if name is None or G.is_relational(obj):
        return None
    st = new_bag()
    pt = getattr(obj, name)
    st.x, st.y = float(pt.x), float(pt.y)
    obj[name] @= lambda: (st.x, st.y)
    return LinkCtx("part", cell=st, field=name)


def _l_source(obj, w):
    """The subject is the source of another shape's link (a pin on its center)."""
    if isinstance(obj, Point) or G.is_box(obj):
        return None
    pin = w.track(Point(0, 0))
    pin @= lambda: obj.center
    return LinkCtx("source", sink=pin)


def _l_chain(obj, w):
    """A point part follows another shape's part (depth 2: cell -> a -> subject)."""
    name = _linkable_point(obj)
    if name is None or G.is_relational(obj):
        return None
    a = w.track(Point(float(getattr(obj, name).x), float(getattr(obj, name).y)))
    obj[name] @= lambda: a
    return LinkCtx("chain", source=a, field=name)


def _l_whole(obj, w):
    """``d @= s``: the subject follows a twin of itself, whole."""
    if G.is_relational(obj) or isinstance(obj, Track) or type(obj).__name__ in ("Sprite", "Svg", "Text"):
        return None
    if G.is_box(obj):
        return None
    src = w.track(obj.clone())
    obj @= lambda: src
    return LinkCtx("whole", source=src)


L: Dict[str, Callable] = {
    "none": _l_none,
    "field": _l_field,
    "part": _l_part,
    "source": _l_source,
    "chain": _l_chain,
    "whole": _l_whole,
}


def apply_link(name: str, obj, w) -> Optional[LinkCtx]:
    """Install link configuration ``name`` on ``obj``; None when it does not apply.

    An Anchor refuses every inbound link (it is dragged: Shapes Design —
    Anchor); it is a refusal subject (H6), never linked here."""
    if name not in ("none", "source") and type(obj).__name__ == "Anchor":
        return None
    from scena.state import LinkedAttributeError
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return L[name](obj, w)
        except LinkedAttributeError as exc:
            # A field a running motion pushes refuses a link ("… pushes it.
            # Call handle.cancel() first"): this base and link do not combine.
            if "pushes it" in str(exc):
                return None
            raise


# ---------------------------------------------------------------------------
# V — pose verbs (the public surface decides the list)
# ---------------------------------------------------------------------------

def public_pose_verbs() -> List[str]:
    """Every public Graphic method that takes ``time=`` (a pose verb), from the class."""
    import inspect
    from scena.entity import Graphic
    out = []
    for name in dir(Graphic):
        if name.startswith("_"):
            continue
        fn = getattr(Graphic, name, None)
        if not callable(fn):
            continue
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            continue
        if "time" in params and name not in ("tween",):
            out.append(name)
    return sorted(out)


# Public pose verbs that are not a V step, each with its reason.
VERBS_NOT_STEPS = {
    "move_along": "travels a Track: Tracks Design owns it (H6)",
    "reset_rotation": "rotate_to(0): covered by rotate_to",
}


# ---------------------------------------------------------------------------
# R — read order after the step
# ---------------------------------------------------------------------------

R = ("cold", "sorted", "reversed", "link_first")


def read_names(obj, order: str, link: Optional[LinkCtx] = None) -> List[str]:
    names = sorted(public_reads(obj))
    if order == "cold":
        return []
    if order == "reversed":
        return names[::-1]
    if order == "link_first" and link is not None and link.field in names:
        return [link.field] + [n for n in names if n != link.field]
    return names


# ---------------------------------------------------------------------------
# X — execution twins
# ---------------------------------------------------------------------------

X = ("normal", "forced_slow", "caches_dropped", "in_batch", "in_frame")


def prepare_twin(obj, x: str) -> None:
    if x == "forced_slow":
        obj._flag_pull_consumers()


from diff_support import invalidate_all_caches  # noqa: E402  (one home for the twin helpers)


@contextmanager
def execution(x: str, obj=None):
    """Run a step under execution twin ``x``."""
    if x == "caches_dropped" and obj is not None:
        invalidate_all_caches(obj)
    if x == "in_batch":
        from scena.state import get_scena_system
        ss = get_scena_system()
        ss.begin_frame_batch()
        try:
            yield
        finally:
            ss.end_frame_batch()
        return
    if x == "in_frame":
        from scena import clock
        from scena.process import tick_processes
        yield
        clock.advance(1 / 60)
        tick_processes()
        return
    yield


# ---------------------------------------------------------------------------
# Reach counters
# ---------------------------------------------------------------------------

class Reach:
    """Counts (axis, value) pairs a harness really ran."""

    def __init__(self):
        self.hits = collections.Counter()

    def hit(self, axis: str, value) -> None:
        self.hits[(axis, value)] += 1

    def missing(self, axes: Dict[str, List]) -> List[Tuple[str, object]]:
        return [(a, v) for a, vals in axes.items() for v in vals if not self.hits[(a, v)]]


def close_xy(a: XY, b: XY, tol: float = 1e-6) -> bool:
    """Equal within a tolerance relative to the magnitude (far coordinates)."""
    scale = max(1.0, abs(a[0]), abs(a[1]), abs(b[0]), abs(b[1]))
    return abs(a[0] - b[0]) <= tol * scale and abs(a[1] - b[1]) <= tol * scale


def close_num(a: float, b: float, tol: float = 1e-6) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
