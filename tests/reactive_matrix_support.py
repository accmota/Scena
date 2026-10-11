"""Metadata-driven reactive matrix: field x write path x read order x model.

Oracle: a plain-write twin. The subject links ``field`` to a source, moves the
source, and every readable name must equal the twin's, whatever was read before
the move. Fields come from the ``ScalarSlot``/``ContainerSlot`` descriptors of
the class, never from a hand-kept list; the only hand-kept table is SUBJECTS
(one factory per construction model), and ``test_reactive_matrix`` fails when a
reactive class has no subject.

Invariants checked per cell:
  I1  freshness: every readable name equals the twin's after the source moves
  I5  unlink freezes the current value; a later source move changes nothing
  I6  two reads in a row agree
Cells the model forbids (linking a Derivate part, a write the twin refuses) are
not applicable and are skipped, so no per-class exemption list is needed.
"""
from __future__ import annotations

import inspect
import itertools
import math
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import warnings

import geometry_support as G
import scena
from media_support import media
from scena import Box, Circle, Ellipse, EquilateralTriangle, Line, Point, Polygon
from scena import Rect, RegularPolygon, Sprite, Square, State, Svg, Text, Track, Vec2
from scena.state import ContainerSlot, ScalarSlot

_COUNTER = itertools.count()


def _tri():
    return Polygon(points=[(0, 0), (10, 0), (5, 8)])


def _sprite():
    return Sprite(media("space", "enemyGreen1.png"), center=(0, 0), height=20)


def _svg():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Svg(G.SVG, center=(0, 0))


# (label, factory). One entry per construction model that changes which
# parts are Defining and which are Derivate.
SUBJECTS: List[Tuple[str, Callable[[], object]]] = [
    ("Vec2", lambda: Vec2(1, 2)),
    ("Point", lambda: Point(1, 2)),
    ("Line p1,p2", lambda: Line(p1=(0, 0), p2=(3, 4))),
    ("Line p1,vec", lambda: Line(p1=(0, 0), vec=(3, 4))),
    ("Line p1,length,angle", lambda: Line(p1=(0, 0), length=5, angle=30)),
    ("Circle", lambda: Circle(center=(0, 0), radius=10)),
    ("Circle spread", lambda: Circle(center=(0, 0), radius=10, spread=270)),
    ("Ellipse", lambda: Ellipse(center=(0, 0), width=20, height=10)),
    ("Rect corner_corner", lambda: Rect(p1=(0, 0), p2=(4, 3), angle=30)),
    ("Rect center", lambda: Rect(center=(0, 0), width=4, height=3, angle=30)),
    ("Rect top_left", lambda: Rect(top_left=(0, 0), width=4, height=3, angle=30)),
    ("Rect p1,vec", lambda: Rect(p1=(0, 0), vec=(4, 3), angle=30)),
    ("Square", lambda: Square(center=(0, 0), length=10, angle=30)),
    ("Box corner_corner", lambda: Box(p1=(0, 0), p2=(4, 3), angle=30)),
    ("Box center", lambda: Box(center=(0, 0), width=4, height=3, angle=30)),
    ("Polygon", _tri),
    ("RegularPolygon", lambda: RegularPolygon(n=5, center=(0, 0), radius=10)),
    ("EquilateralTriangle", lambda: EquilateralTriangle(center=(0, 0), radius=10)),
    ("Track", lambda: Track(points=[(0, 0), (10, 0), (10, 10)])),
    # Derived headings (angle read off the points): a linked angle drives rotate_to.
    ("Line p1,dx,dy", lambda: G.build("Line point_dx_dy")),
    ("Circle two_points", lambda: G.build("Circle two_points")),
    ("Circle perimeter_point", lambda: G.build("Circle center_perimeter")),
    ("Ellipse focal_points", lambda: G.build("Ellipse focal_points")),
    ("Rect spine cap", lambda: G.build("Rect spine cap")),
    ("Rect spine square", lambda: G.build("Rect spine square")),
    # Families the matrix left out until the geometry campaign (H6): pose kept
    # as a zoom on top of size knobs, and a caption laid out from font metrics.
    ("Sprite", _sprite),
    ("Svg", _svg),
    ("Text center", lambda: Text("geo", center=(0, 0))),
    ("Text top_left", lambda: Text("geo", top_left=(0, 0))),
]

# Classes whose reactive slots are covered by a subject above (guard).
COVERED = frozenset({
    "Vec2", "Point", "Line", "Circle", "Ellipse", "Rect", "Square", "Box",
    "Polygon", "RegularPolygon", "EquilateralTriangle", "Track", "Sprite", "Svg", "Text",
})
# Reactive classes the matrix does not drive, each with the reason.
NOT_DRIVEN = {
    "Anchor": "a refusal subject: every inbound link is refused, atomically "
              "(test_reactive_matrix.TestAnchorRefusesEveryLink)",
    "SpriteButton": "a widget sprite; its reactive slots are Sprite's (the Sprite subject)",
    "Menu": "a widget container; its ContainerSlots are `data` aliases",
    "Button": "UI widget; `data` is an alias of the payload (uiwidget._DataAlias)",
    "TextInput": "UI widget; `data` alias", "DropDown": "UI widget; `data` alias",
    "Slider": "UI widget; `data` alias", "CheckBox": "UI widget; `data` alias",
    "Fire": "Fx domain; radius only (a plain ScalarSlot, covered by the scalar cells of Circle)",
    "Sunburst": "Fx domain", "Starburst": "Fx domain", "Rain": "Fx domain",
    "Jet": "Fx domain", "Sparks": "Fx domain", "GlowSpot": "Fx domain",
    "Orb": "Fx domain", "Warp": "Fx domain", "Portal": "Fx domain",
}


def reactive_classes() -> Dict[str, type]:
    """Every exported class that declares a ScalarSlot or ContainerSlot."""
    out = {}
    for name in scena.__all__:
        cls = getattr(scena, name)
        if inspect.isclass(cls) and any(
                isinstance(v, (ScalarSlot, ContainerSlot))
                for _, v in inspect.getmembers(cls)):
            out[name] = cls
    return out


def field_names(obj) -> List[Tuple[str, bool]]:
    """(name, is_pair) for every slot descriptor plus the class part names."""
    cls = type(obj)
    names: Dict[str, bool] = {}
    for k, v in inspect.getmembers(cls):
        if isinstance(v, ScalarSlot):
            names[k] = False
        elif isinstance(v, ContainerSlot):
            names[k] = True
    for k in getattr(cls, "_PART_NAMES", ()):
        names.setdefault(k, hasattr(getattr(obj, k, None), "x"))
    return sorted(names.items())


def values_for(name: str, slot, is_pair: bool):
    """Two source values (v0, v1) for a field, honoring its constraints."""
    if is_pair:
        return (3.0, 4.0), (-5.0, 9.0)
    if name == "angle":
        return 40.0, 70.0
    if name == "spread":
        return 90.0, 180.0
    if name in ("begin", "end", "u"):
        return 0.2, 0.6
    if getattr(slot, "magnitude", False):
        return 5.0, 9.0
    return 2.0, 7.0


def _flat(v):
    if hasattr(v, "x") and hasattr(v, "y"):
        return (round(float(v.x), 6), round(float(v.y), 6))
    if hasattr(v, "value"):
        v = v.value
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 6)
    return v


def snapshot(obj, reverse: bool = False) -> Dict[str, object]:
    out = {}
    names = field_names(obj)
    for name, _ in (names[::-1] if reverse else names):
        try:
            out[name] = _flat(getattr(obj, name))
        except Exception as e:  # an error is a value: both sides must agree
            out[name] = "!" + type(e).__name__
    return out


def _same(a, b) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return (a != a and b != b) or math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)
    return a == b


def diff(a: Dict[str, object], b: Dict[str, object]) -> Dict[str, tuple]:
    return {k: (a[k], b[k]) for k in a if not _same(a[k], b.get(k))}


READS = (False, True)       # post-move read order: sorted, reversed
ORDERS = ("cold", "warm_self", "warm_all", "warm_all_reversed")
PATHS = ("lambda", "cell", "whole")  # whole: ``part @= fn`` on the pair part itself


def _source(path: str, is_pair: bool, v0):
    st = State(name=f"rm{next(_COUNTER)}")
    st.v = v0
    if path == "cell":
        return st, (lambda: st.v)
    return st, (lambda: (st.v[0], st.v[1])) if is_pair else (lambda: st.v + 0.0)


def _warm(obj, order: str, name: str, names: List[str]) -> None:
    """Read before the source moves. ``names`` comes from a throwaway probe."""
    if order == "cold":
        return
    if order == "warm_self":
        names = [name]
    elif order == "warm_all_reversed":
        names = names[::-1]
    for n in names:
        try:
            getattr(obj, n)
        except Exception:
            pass


def run_cell(factory, name: str, path: str, order: str,
             reverse: bool = False) -> Optional[object]:
    """None = pass or not applicable; otherwise a description of the failure."""
    # The field list is read from a throwaway instance: reading a named point
    # names the corners, and the subject must not be read before the link.
    probe = field_names(factory())
    all_names = [n for n, _ in probe]
    is_pair = dict(probe).get(name, False)
    subject = factory()
    slot = getattr(type(subject), name, None)
    v0, v1 = values_for(name, slot, is_pair)
    if path == "whole" and not is_pair:
        return None
    st, fn = _source("lambda" if path == "whole" else path, is_pair, v0)
    try:
        if path == "whole":
            part = getattr(subject, name)
            part @= fn
        else:
            subject[name] @= fn
    except Exception:
        return None  # e.g. DerivedAttributeError: linking a Derivate is refused
    # A Rect names its corners at first use, so both sides are read at the
    # same moments or the oracle would compare two namings (Shapes Design,
    # "Named points").
    twin_v0 = factory()
    try:
        setattr(twin_v0, name, v0) if not is_pair else getattr(twin_v0, name)._takein(v0)
    except Exception:
        return None
    _warm(subject, order, name, all_names)
    twin = twin_v0
    _warm(twin, order, name, all_names)
    try:
        setattr(twin, name, v1) if not is_pair else getattr(twin, name)._takein(v1)
    except Exception:
        return None
    st.v = v1
    got, want = snapshot(subject, reverse), snapshot(twin, reverse)
    bad = diff(got, want)
    if bad:
        return ("I1", bad)
    if diff(snapshot(subject), got):
        return ("I6", diff(snapshot(subject), got))
    (getattr(subject, name) if path == "whole" else subject[name]).unlink()
    frozen = snapshot(subject)
    st.v = v0
    after = diff(snapshot(subject), frozen)
    if after:
        return ("I5", after)
    return None


def cells(factory) -> Iterator[Tuple[str, str, str]]:
    obj = factory()
    for name, _ in field_names(obj):
        for path in PATHS:
            for order in ORDERS:
                yield name, path, order


# --------------------------------------------------------------------------
# I2: constraint parity between a link and a plain write
# --------------------------------------------------------------------------

def scalar_fields(factory) -> List[Tuple[str, object]]:
    obj = factory()
    return [(n, getattr(type(obj), n)) for n, pair in field_names(obj)
            if not pair and isinstance(getattr(type(obj), n, None), ScalarSlot)]


def _clamped(slot, v: float) -> float:
    """What a plain write would hold for ``v`` once the slot's limits apply."""
    lo = getattr(slot, "minimum", None)
    hi = getattr(slot, "maximum", None)
    if lo is None and getattr(slot, "magnitude", False):
        lo = 0.0
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def run_range_cell(factory, name: str, slot, kind: str) -> Optional[object]:
    """Link ``name`` to an out-of-range or non-finite source (I2).

    ``below`` / ``above``: the link must read what the slot's limits give (a
    negative magnitude reads 0, ``spread`` stops at 360, Track ``begin`` at 1).
    ``nan``: a plain write raises ValueError, so the link must refuse too, at
    install or on the read that pulls it; storing NaN is the failure.
    """
    lo = getattr(slot, "minimum", None)
    hi = getattr(slot, "maximum", None)
    if kind == "below":
        if lo is None and not getattr(slot, "magnitude", False):
            return None
        bad = -3.25
    elif kind == "above":
        if hi is None:
            return None
        bad = hi + 3.25
    else:
        bad = float("nan")
    obj = factory()
    st = State(name=f"rm{next(_COUNTER)}")
    st.v = 0.5 if hi is not None and hi <= 1.0 else 5.0
    try:
        obj[name] @= (lambda: st.v + 0.0)
    except Exception:
        return None
    st.v = bad
    try:
        got = getattr(obj, name)
        got = float(got.value if hasattr(got, "value") else got)
    except ValueError:
        return None if kind == "nan" else ("I2", f"{kind}: raised")
    except Exception:
        return None
    if kind == "nan":
        return ("I2", f"nan: link stored {got!r}; a plain write raises ValueError")
    want = _clamped(slot, bad)
    if not _same(got, float(want)):
        return ("I2", f"{kind}: link read {got!r}, limits give {want!r}")
    return None


def run_self_cell(factory, order: str) -> Optional[object]:
    """``v @= lambda: pair`` on a Vec2 / Point itself (D12: length/angle stale)."""
    all_names = [n for n, _ in field_names(factory())]
    subject, twin = factory(), factory()
    st = State(name=f"rm{next(_COUNTER)}")
    st.v = (3.0, 4.0)
    subject @= (lambda: (st.v[0], st.v[1]))
    twin << (3.0, 4.0)
    _warm(subject, order, "x", all_names)
    _warm(twin, order, "x", all_names)
    st.v = (-5.0, 12.0)
    twin << (-5.0, 12.0)
    bad = diff(snapshot(subject), snapshot(twin))
    return ("I1", bad) if bad else None


def snapshot_names(obj, names: List[str]) -> Dict[str, object]:
    """Read ``names`` in order; an error is a value."""
    out = {}
    for n in names:
        try:
            out[n] = _flat(getattr(obj, n))
        except Exception as e:
            out[n] = "!" + type(e).__name__
    return out


# --------------------------------------------------------------------------
# Whole-object links: ``d @= s`` (a DirectLink) and ``d @= lambda: s``
# --------------------------------------------------------------------------

WHOLE_PATHS = ("direct", "formula")


def run_whole_cell(factory, name: str, path: str, order: str) -> Optional[object]:
    """Link a whole object to a source of the same kind, then write the
    source's ``name`` with ``=``. Every readable name of the linked object must
    equal the source's (D19: a pull stored the Defining parts and marked the
    subtree clean without refreshing the live Derivates). Both are read at the
    same moments; a copy carries the source's corner names."""
    probe = field_names(factory())
    all_names = [n for n, _ in probe]
    is_pair = dict(probe).get(name, False)
    slot = getattr(type(factory()), name, None)
    _, v1 = values_for(name, slot, is_pair)
    source, linked = factory(), factory()
    try:
        if path == "direct":
            linked @= source
        else:
            linked @= (lambda: source)
    except Exception:
        return None
    _warm(source, order, name, all_names)
    _warm(linked, order, name, all_names)
    try:
        setattr(source, name, v1)   # ``=``: a Derivate refuses (``_takein`` would not)
    except Exception:
        return None          # not a plain-writable field on this model
    bad = diff(snapshot(linked), snapshot(source))
    return ("I1", bad) if bad else None


def freshness_failures(subjects, reverse=False):
    """Every ``cells`` row of ``subjects`` that reads unlike ``=`` (I1 / I6)."""
    bad = []
    for label, factory in subjects:
        for name, path, order in cells(factory):
            r = run_cell(factory, name, path, order, reverse)
            if r:
                bad.append((label, name, path, order, r))
    return bad


def whole_failures(subjects):
    """Every whole-object link (``WHOLE_PATHS``) of ``subjects`` that reads unlike its source."""
    bad = []
    for label, factory in subjects:
        for name, _ in field_names(factory()):
            for path in WHOLE_PATHS:
                for order in ORDERS:
                    r = run_whole_cell(factory, name, path, order)
                    if r:
                        bad.append((label, name, path, order, r))
    return bad
