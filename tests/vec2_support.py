"""Shared machinery for the Vec2 battery (``tests/test_vec2_*.py``).

Not a test module. Testing Design, "Vec2 battery": every bug in the VI / SV10
series sat on a door the tests never sent that operand through, so the battery
names its axes here once and the modules cross them:

* **kinds** — every way an author holds a Vec2 (``KINDS``): a free vector, an
  arithmetic result, an actor's ``vel``, the vector an st cell holds (alone, or
  saved into a second cell), an ink field's vector, a shape's Defining and
  Derivate ``vec``, a formula-linked vector (whole, one axis), a dead actor's
  ``vel``.
* **doors** — every author spelling that writes x / y (``DOORS``).
* **operands** — the values a door takes (``OPERANDS``): good, edge, non-finite,
  overflowing, wrongly typed.
* **contexts** — where the door runs (``CONTEXTS``): plain, a frame batch, an
  ``on_change`` callback, a frame.

``run_cell`` runs one (kind, door, operand, context) and returns the generic
oracle's violations; nothing in it predicts a value per cell.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scena import Circle, Line, Rect, State, Vec2, on_change  # noqa: E402
from scena.events import unregister_event  # noqa: E402
from scena.shapes import Point  # noqa: E402
from scena.state import DestroyedError  # noqa: E402

import hypothesis_support  # noqa: E402
from diff_support import in_batch, in_frame  # noqa: E402

INF, NAN = math.inf, math.nan

# A refusal an author may see: Scena's own errors, plus the held-cell guard
# (AttributeError, CS4) and a dead actor's part (DestroyedError).
AUTHOR_ERRORS = hypothesis_support.AUTHOR_ERRORS + (AttributeError, DestroyedError)


# --------------------------------------------------------------------------
# Reading a vector
# --------------------------------------------------------------------------

def raw_xy(v) -> Tuple[Any, Any]:
    """x / y as stored, without coercion (a giant int stays an int)."""
    return (v.x, v.y)


def same_value(a, b) -> bool:
    """Equal, NaN equal to NaN, and the same type (int 3 is not float 3.0).

    The sign of a zero is not compared: the engine promises no bit-exactness
    there (Testing Design, "An oracle is stricter than the contract")."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and a != a:
        return b != b
    return a == b


def same_xy(a, b) -> bool:
    return len(a) == len(b) and all(same_value(p, q) for p, q in zip(a, b))


def heading(y, x) -> float:
    """``angle`` of a vector: degrees in (-180, 180], -0.0 read as 0 (VB7),
    and a zero vector reads 0 whatever the signs of its zeros (F12)."""
    if x == 0 and y == 0:
        return 0.0
    a = math.degrees(math.atan2(y, x)) + 0.0
    return 180.0 if a == -180.0 else a


def _holds_number(x) -> bool:
    if type(x) is float:
        return True
    return type(x) is int and -1e308 < x < 1e308


def derived_ok(v) -> Optional[str]:
    """None when ``length`` / ``angle`` are what x / y give now (two reads agree)."""
    x, y = raw_xy(v)
    try:
        want_len = math.sqrt(x * x + y * y)
        want_ang = heading(y, x)
    except (OverflowError, TypeError):
        return f"x, y = {x!r:.40}, {y!r:.40} give no length"
    try:
        got_len, got_ang = v.length, v.angle
    except Exception as exc:  # noqa: BLE001 — the read itself failing is the finding
        return f"reading length / angle raised {type(exc).__name__}: {exc!s:.80}"
    if not (same_value(float(got_len), want_len) and same_value(float(got_ang), want_ang)):
        return f"length, angle = {got_len!r}, {got_ang!r}; x, y give {want_len!r}, {want_ang!r}"
    return None


# --------------------------------------------------------------------------
# Kinds
# --------------------------------------------------------------------------

class Subject:
    """One vector an author holds, and what must follow or keep it.

    ``v`` — the vector the doors write; ``holder`` — ``(obj, attr)`` the author
    assigns through (``c.vel = …``), or None; ``watch`` — what a formula reading
    the holder shows now, and ``source`` the value it must show (both tuples);
    ``keep`` — a value no door on ``v`` may change (a copy saved elsewhere);
    ``owned`` — objects to destroy afterwards.
    """

    def __init__(self, kind: str, v, *, holder=None, watch=None, source=None,
                 keep=None, owned=()):
        self.kind = kind
        self.v = v
        self.holder = holder
        self.watch = watch
        self.source = source
        self.keep = keep
        self.owned = list(owned)
        self.after = None       # a link door's next source change (a later pull)
        self.cleanup = []       # undo what outlives the cell (a link to a fresh source)

    def current(self):
        """The vector the holder holds now (a whole assignment may replace it)."""
        if self.holder is None:
            return self.v
        obj, attr = self.holder
        return getattr(obj, attr)

    def teardown(self) -> None:
        for undo in self.cleanup:
            try:
                undo()
            except Exception:  # noqa: BLE001
                pass
        for obj in reversed(self.owned):
            try:
                obj.destroy()
            except Exception:  # noqa: BLE001
                pass


def _watcher(read: Callable[[], Any], owned: list):
    """A shape whose center is a formula reading ``read()``; returns its reader."""
    probe = Circle(center=lambda: read(), radius=1)
    owned.append(probe)
    return lambda: (probe.center.x, probe.center.y)


def _xy_tuple(v) -> Tuple[float, float]:
    """x, y of what a holder holds now (a Vec2, a Point, or a pair)."""
    if isinstance(v, (tuple, list)):
        return (float(v[0]), float(v[1]))
    return (float(v.x), float(v.y))


def _k_free():
    v = Vec2(1, 2)
    return Subject("free", v)


def _k_temp():
    v = Vec2(1, 1) + (0, 1)          # an arithmetic result (Vec2.temp fast path)
    return Subject("temp", v)


def _k_vel():
    owned: list = []
    c = Circle(center=(100, 100), radius=5)
    owned.append(c)
    c.vel = (1, 2)
    watch = _watcher(lambda: c.vel, owned)
    return Subject("vel", c.vel, holder=(c, "vel"), watch=watch,
                   source=lambda: _xy_tuple(c.vel), owned=owned)


def _k_st():
    owned: list = []
    st = State(name="vb_st")
    st.pos = Vec2(1, 2)
    watch = _watcher(lambda: st.pos, owned)
    return Subject("st", st.pos, holder=(st, "pos"), watch=watch,
                   source=lambda: _xy_tuple(st.pos), owned=owned)


def _k_st_saved():
    # ``st.start = st.pos``: a cell holds a Vec2 by value (Reactive Design),
    # so the saved start keeps (1, 2) whatever happens to st.pos.
    owned: list = []
    st = State(name="vb_saved")
    st.pos = Vec2(1, 2)
    st.start = st.pos
    watch = _watcher(lambda: st.pos, owned)
    return Subject("st_saved", st.pos, holder=(st, "pos"), watch=watch,
                   source=lambda: _xy_tuple(st.pos),
                   keep=lambda: _xy_tuple(st.start), owned=owned)


def _k_ink():
    owned: list = []
    ship = Circle(center=(100, 100), radius=5)
    owned.append(ship)
    ship.aim = Vec2(1, 2)
    watch = _watcher(lambda: ship.aim, owned)
    return Subject("ink", ship.aim, holder=(ship, "aim"), watch=watch,
                   source=lambda: _xy_tuple(ship.aim), owned=owned)


def _k_ink_saved():
    # ``st.v0 = ship.aim``: the cell snapshots the ink field's vector; the
    # field stays writable in place (ink takes every in-place spelling).
    owned: list = []
    ship = Circle(center=(100, 100), radius=5)
    owned.append(ship)
    ship.aim = Vec2(1, 2)
    st = State(name="vb_ink_saved")
    watch = _watcher(lambda: ship.aim, owned)
    st.v0 = ship.aim
    return Subject("ink_saved", ship.aim, holder=(ship, "aim"), watch=watch,
                   source=lambda: _xy_tuple(ship.aim),
                   keep=lambda: _xy_tuple(st.v0), owned=owned)


def _k_ink_saved_unwatched():
    # The same with no formula reading ``ship.aim``: nothing marks the vector
    # as held by the field, so the cell cannot tell it is shared (VB2b).
    owned: list = []
    ship = Circle(center=(100, 100), radius=5)
    owned.append(ship)
    ship.aim = Vec2(1, 2)
    st = State(name="vb_ink_unwatched")
    st.v0 = ship.aim
    return Subject("ink_saved_unwatched", ship.aim, holder=(ship, "aim"),
                   keep=lambda: _xy_tuple(st.v0), owned=owned)


def _k_line_vec():
    owned: list = []
    line = Line(p1=(0, 0), vec=(1, 2))
    owned.append(line)
    return Subject("line_vec", line.vec, holder=(line, "vec"), owned=owned)


def _k_rect_vec():
    owned: list = []
    rect = Rect(p1=(0, 0), vec=(1, 2))
    owned.append(rect)
    return Subject("rect_vec", rect.vec, holder=(rect, "vec"), owned=owned)


def _k_box_vec():
    from scena.box import Box
    box = Box(p1=(0, 0), vec=(1, 2))
    return Subject("box_vec", box.vec, holder=(box, "vec"))


def _k_concave_rim():
    from scena.shapes import Concave
    owned: list = []
    shape = Concave(center=(50, 50), width=40, height=30, rim=(1, 2))
    owned.append(shape)
    return Subject("concave_rim", shape.rim, holder=(shape, "rim"), owned=owned)


def _k_line_derived():
    owned: list = []
    line = Line(p1=(0, 0), p2=(1, 2))
    owned.append(line)
    return Subject("line_derived", line.vec, owned=owned)


def _k_linked():
    st = State(name="vb_src")
    st.k = 1.0
    v = Vec2(0, 0)
    v @= lambda: Vec2(st.k, 2)
    return Subject("linked", v)


def _k_axis_linked():
    st = State(name="vb_axis")
    st.k = 1.0
    v = Vec2(0, 2)
    v["x"] @= lambda: st.k
    return Subject("axis_linked", v)


def _k_dead_vel():
    c = Circle(center=(100, 100), radius=5)
    c.vel = (1, 2)
    v = c.vel
    c.destroy()
    return Subject("dead_vel", v, holder=(c, "vel"))


KINDS: Dict[str, Callable[[], Subject]] = {
    "free": _k_free,
    "temp": _k_temp,
    "vel": _k_vel,
    "st": _k_st,
    "st_saved": _k_st_saved,
    "ink": _k_ink,
    "ink_saved": _k_ink_saved,
    "ink_saved_unwatched": _k_ink_saved_unwatched,
    "line_vec": _k_line_vec,
    "rect_vec": _k_rect_vec,
    "box_vec": _k_box_vec,
    "concave_rim": _k_concave_rim,
    "line_derived": _k_line_derived,
    "linked": _k_linked,
    "axis_linked": _k_axis_linked,
    "dead_vel": _k_dead_vel,
}

# Every Vec2 part an engine class declares (``ContainerSlot(Vec2)``), and the
# kind that drives it (completeness: test_vec2_guards).
PART_KINDS = {("Line", "vec"): "line_vec", ("_RectBody", "vec"): "rect_vec",
              ("Box", "vec"): "box_vec", ("Concave", "rim"): "concave_rim"}

# Writes a refusing kind takes by design: a new ``@=`` replaces a vector's own
# link, with a warning (Reactive Design, "On link / unlink", step 4).
DESIGNED_ACCEPTS = {("linked", "@= whole")}

# Operand-specific refusals by design: ``Concave.rim =`` takes ``>= 0`` (an
# in-place write below 0 counts as 0 at use; Shapes Design, the ``rim`` row).
DESIGNED_OPERAND_REFUSALS = {("concave_rim", "= whole", "(3.5, -4.25)")}

# Kinds whose vector refuses every author write (derived, linked, dead).
REFUSING_KINDS = {"line_derived", "linked", "dead_vel"}

# Refusals by design on a writable kind, as (kind, door): the vector an st cell
# holds refuses an axis write (CS4, Reactive Design "The payload changes by
# whole-value assignment"); a vector whose x is linked refuses what writes x.
DESIGNED_REFUSALS = {
    *(((k, d) for k in ("st", "st_saved") for d in (".x =", ".y =", ".x +="))),
    ("vel", "@= whole"), ("vel", '["y"] @='),    # Graphic.vel is never linked
    ("st", "@= whole"), ("st_saved", "@= whole"),  # the cell is linked, not its payload
    ("st", '["y"] @='), ("st_saved", '["y"] @='),  # nor one axis of it (VB3)
    *((("axis_linked", d) for d in (".x =", ".x +=", "+=", "-=", "alias +=",
                                    "<<", "do_rotation", "@= whole", "*=", "/="))),
}


# --------------------------------------------------------------------------
# Operands
# --------------------------------------------------------------------------

def _cell_holding(pair):
    st = State(name="vb_operand")
    st.p = pair
    return st["p"]


OPERANDS: Dict[str, Callable[[], Any]] = {
    "(3.5, -4.25)": lambda: (3.5, -4.25),
    "(3, 4) ints": lambda: (3, 4),
    "(-0.0, 0.0)": lambda: (-0.0, 0.0),
    "(1e308, 1e308)": lambda: (1e308, 1e308),
    "(10**400, 0)": lambda: (10 ** 400, 0),
    "(inf, 0)": lambda: (INF, 0),
    "(0, nan)": lambda: (0, NAN),
    "(True, 0)": lambda: (True, 0),
    "[3, 4] list": lambda: [3, 4],
    "(1, 2, 3)": lambda: (1, 2, 3),
    "Vec2(3, 4)": lambda: Vec2(3, 4),
    "Point(3, 4)": lambda: Point(3, 4),
    "None": lambda: None,
    "'ab'": lambda: "ab",
}

# Operands a correct door accepts; the rest must be refused by every door.
GOOD_OPERANDS = {"(3.5, -4.25)", "(3, 4) ints", "(-0.0, 0.0)", "[3, 4] list",
                 "Vec2(3, 4)", "(1e308, 1e308)"}
# Good operands no door may refuse on a writable kind (``1e308`` may overflow
# to inf through ``*=``, so it is left out).
NEVER_REFUSED = GOOD_OPERANDS - {"(1e308, 1e308)"}


def scalar_of(o):
    """The number a one-number door takes from a pair operand."""
    if isinstance(o, (tuple, list)) and o:
        return o[0]
    if isinstance(o, (Vec2, Point)):
        return o.x
    return o


# --------------------------------------------------------------------------
# Doors
# --------------------------------------------------------------------------

def _holder_or_none(s: Subject):
    return s.holder


def _d_set_x(s, o):
    s.v.x = scalar_of(o)


def _d_set_y(s, o):
    s.v.y = scalar_of(o)


def _d_aug_x(s, o):
    s.v.x += scalar_of(o)


def _d_iadd(s, o):
    if s.holder is None:
        v = s.v
        v += o
        return
    obj, attr = s.holder
    v = getattr(obj, attr)
    v += o
    setattr(obj, attr, v)     # what ``obj.attr += o`` runs


def _d_isub(s, o):
    if s.holder is None:
        v = s.v
        v -= o
        return
    obj, attr = s.holder
    v = getattr(obj, attr)
    v -= o
    setattr(obj, attr, v)


def _d_alias_iadd(s, o):
    alias = s.v               # another name; nothing is assigned back
    alias += o


def _d_lshift(s, o):
    s.v << o


def _d_rotate(s, o):
    s.v.do_rotation(scalar_of(o))


def _d_assign(s, o):
    obj, attr = s.holder
    setattr(obj, attr, o)


def _d_imul(s, o):
    if s.holder is None:
        v = s.v
        v *= scalar_of(o)     # in place, as += (VB9)
        return
    obj, attr = s.holder
    v = getattr(obj, attr)
    v *= scalar_of(o)
    setattr(obj, attr, v)     # what ``obj.attr *= k`` runs


def _d_idiv(s, o):
    if s.holder is None:
        v = s.v
        v /= scalar_of(o)
        return
    obj, attr = s.holder
    v = getattr(obj, attr)
    v /= scalar_of(o)
    setattr(obj, attr, v)


def _d_link_whole(s, o):
    src = State(name="vb_link_src")
    src.p = o
    v = s.v
    v @= lambda: src.p
    s.cleanup.append(v.unlink)
    s.after = lambda: setattr(src, "p", (5.5, 6.5))


def _d_link_axis(s, o):
    src = State(name="vb_link_axis")
    src.k = scalar_of(o)
    v = s.v
    v["y"] @= lambda: src.k
    s.cleanup.append(lambda: v._unlink_field("y"))
    s.after = lambda: setattr(src, "k", 7.5)


DOORS: Dict[str, Callable[[Subject, Any], None]] = {
    ".x =": _d_set_x,
    ".y =": _d_set_y,
    ".x +=": _d_aug_x,
    "+=": _d_iadd,
    "-=": _d_isub,
    "alias +=": _d_alias_iadd,
    "<<": _d_lshift,
    "do_rotation": _d_rotate,
    "= whole": _d_assign,
    "*=": _d_imul,
    "/=": _d_idiv,
    "@= whole": _d_link_whole,
    '["y"] @=': _d_link_axis,
}

# Doors that need a holder to assign through.
HOLDER_DOORS = {"= whole"}
# Doors that install a link (the value arrives by a pull).
LINK_DOORS = {"@= whole", '["y"] @='}
# Doors that take one number from the operand.
SCALAR_DOORS = {".x =", ".y =", ".x +=", "do_rotation", "*=", "/=", '["y"] @='}
# Doors whose operand the author combines with Python first (``v.x + o``): an
# operand Python itself refuses there never reaches a Scena door.
AUTHOR_EXPRESSION_DOORS = {".x +="}

# The method each Vec2 spelling is found under (completeness: test_vec2_guards).
DOOR_METHODS = {"__iadd__": "+=", "__isub__": "-=", "__lshift__": "<<",
                "do_rotation": "do_rotation", "__imatmul__": "@= whole",
                "__imul__": "*=", "__itruediv__": "/="}


def door_valid(kind: str, door: str) -> bool:
    if door in HOLDER_DOORS and kind in ("free", "temp", "linked", "axis_linked",
                                         "line_derived"):
        return False
    return True


# --------------------------------------------------------------------------
# Contexts
# --------------------------------------------------------------------------

def _plain(step):
    return step()


def _in_callback(step):
    """Run ``step`` inside an ``on_change`` callback (the update manager busy)."""
    trig = State(name="vb_trig")
    trig.go = 0
    box: dict = {}

    def cb(value):
        box["ran"] = True
        try:
            box["out"] = step()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            box["exc"] = exc

    on_change(trig["go"])(cb)
    try:
        trig.go = 1
        if "ran" not in box:
            in_frame(lambda: None)
    finally:
        unregister_event(cb)          # the handler would keep the subject alive
    if "ran" not in box:
        raise AssertionError("the on_change callback never ran (vacuous context)")
    if "exc" in box:
        raise box["exc"]
    return box.get("out")


CONTEXTS: Dict[str, Callable[[Callable[[], Any]], Any]] = {
    "plain": _plain,
    "batch": in_batch,
    "callback": _in_callback,
    "frame": in_frame,
}


# --------------------------------------------------------------------------
# One cell
# --------------------------------------------------------------------------

# The invariants ``run_cell`` checks (each has a canary: test_vec2_doors).
INVARIANTS = ("leak", "partial", "number", "finite", "derived", "follow", "kept",
              "twin", "bad", "refused", "accepted")

# Whether length / angle were read before the door (a read moves the vector
# off its lazy path: the door must then refresh what is cached).
READS = ("cold", "warm")


def run_cell(kind: str, door: str, operand: str, context: str,
             read: str = "cold") -> Dict[str, str]:
    """Run one cell; return ``{invariant: detail}`` for each invariant it broke.

    Invariants (Testing Design, "Vec2 battery"):

    * ``leak`` — a refusal is a Scena error with a Scena message.
    * ``partial`` — a refused write changed nothing (check before write).
    * ``number`` — an accepted write leaves x / y numbers a float holds (an int
      is legal: ``v.x = 4`` keeps it, and ``tuple(v)`` reads floats).
    * ``finite`` — an accepted write leaves x / y finite.
    * ``derived`` — length / angle agree with x / y.
    * ``follow`` — a formula reading the holder shows the holder's value.
    * ``kept`` — a copy saved elsewhere did not move.
    * ``twin`` — a free twin given the same start and the same write agrees.
    * ``bad`` — an operand no door may take was taken.
    * ``refused`` — a good operand was refused on a writable kind, outside the
      designed refusals (``DESIGNED_REFUSALS``).
    * ``accepted`` — a derived, linked or dead vector took a write.
    """
    found: Dict[str, str] = {}
    o = None
    s = KINDS[kind]()
    try:
        before = raw_xy(s.v)
        kept0 = s.keep() if s.keep else None
        if read == "warm":
            s.v.length, s.v.angle
        o = OPERANDS[operand]()
        if door in AUTHOR_EXPRESSION_DOORS:
            try:
                float(s.v.x) + scalar_of(o)
            except (TypeError, OverflowError):
                return {}             # Python refuses the author's own expression
        exc = None
        try:
            with hypothesis_support.quiet():
                CONTEXTS[context](lambda: DOORS[door](s, o))
        except BaseException as e:  # noqa: BLE001 — classified below
            if isinstance(e, (KeyboardInterrupt, SystemExit, AssertionError)):
                raise
            exc = e
        target = s.current()
        if not isinstance(target, Vec2):
            # ``st.pos = (3, 4)`` / ``ship.aim = None``: the holder holds another
            # value now (a cell and an ink field hold any value); no vector to check.
            return found
        if exc is not None:
            if not isinstance(exc, AUTHOR_ERRORS):
                found["leak"] = f"{type(exc).__name__}: {exc!s:.120}"
            elif hypothesis_support.leak_message(exc):
                found["leak"] = f"{type(exc).__name__}: {exc!s:.120}"
            if (kind not in REFUSING_KINDS and operand in NEVER_REFUSED
                    and (kind, door) not in DESIGNED_REFUSALS
                    and (kind, door, operand) not in DESIGNED_OPERAND_REFUSALS):
                found["refused"] = f"{type(exc).__name__}: {exc!s:.120}"
            if not same_xy(raw_xy(s.v), before):
                found["partial"] = (f"refused ({type(exc).__name__}) but x, y went "
                                    f"{before!r:.60} -> {raw_xy(s.v)!r:.60}")
        else:
            x, y = raw_xy(target)
            if not (_holds_number(x) and _holds_number(y)):
                found["number"] = (f"x, y stored as {type(x).__name__} {x!r:.30}, "
                                   f"{type(y).__name__} {y!r:.30}")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                try:
                    finite = math.isfinite(x) and math.isfinite(y)
                except OverflowError:
                    finite = False
                if not finite:
                    found["finite"] = f"x, y = {x!r:.40}, {y!r:.40}"
            bad = derived_ok(target)
            if bad:
                found["derived"] = bad
            if operand not in GOOD_OPERANDS and door not in SCALAR_DOORS:
                found["bad"] = f"took {operand}: x, y = {raw_xy(target)!r:.60}"
            if (kind in REFUSING_KINDS and operand in NEVER_REFUSED
                    and (kind, door) not in DESIGNED_ACCEPTS):
                found["accepted"] = f"a {kind} vector took {door} {operand}: {raw_xy(target)!r:.60}"
        if s.watch is not None and kind not in REFUSING_KINDS:
            bad = _follow_bad(s)
            if bad is None and exc is None and s.after is not None and not found:
                s.after()                       # the link's source changes: a pull
                bad = _follow_bad(s)
                if bad is not None:
                    bad = "after the link's source changed: " + bad
            if bad is not None:
                found["follow"] = bad
        if s.keep is not None:
            kept = s.keep()
            if not same_xy(kept, kept0):
                found["kept"] = f"saved copy moved {kept0} -> {kept}"
        if exc is None and kind not in REFUSING_KINDS:
            twin_bad = _twin_check(door, operand, before, raw_xy(target))
            if twin_bad:
                found["twin"] = twin_bad
    finally:
        s.teardown()
        if isinstance(o, Point) and not o.__dict__.get("_ephemeral"):
            o.destroy()             # a Point operand is registered like any shape
    return found


def _follow_bad(s: Subject) -> Optional[str]:
    """None when a formula reading the holder shows what the holder holds."""
    try:
        got, want = s.watch(), s.source()
    except Exception as e:  # noqa: BLE001
        return f"reading raised {type(e).__name__}: {e!s:.80}"
    if not all(abs(a - b) <= 1e-9 * max(1.0, abs(b)) or (a != a and b != b)
               for a, b in zip(got, want)):
        return f"formula shows {got}, holder holds {want}"
    return None


_TWIN_DOORS = {
    ".x =": lambda t, o: setattr(t, "x", scalar_of(o)),
    ".y =": lambda t, o: setattr(t, "y", scalar_of(o)),
    ".x +=": lambda t, o: setattr(t, "x", t.x + scalar_of(o)),
    "+=": lambda t, o: t.__iadd__(o),
    "-=": lambda t, o: t.__isub__(o),
    "alias +=": lambda t, o: t.__iadd__(o),
    "<<": lambda t, o: t << o,
    "do_rotation": lambda t, o: t.do_rotation(scalar_of(o)),
    "= whole": lambda t, o: t << o,
    "*=": lambda t, o: t << t * scalar_of(o),
    "/=": lambda t, o: t << t / scalar_of(o),
}


def _num_eq(a, b) -> bool:
    """Same number (an int and its float are equal; NaN equals NaN)."""
    try:
        return a == b or (a != a and b != b)
    except Exception:  # noqa: BLE001
        return False


def _twin_check(door: str, operand: str, start, got) -> Optional[str]:
    """A free Vec2 at the same start, written the plain way, must agree."""
    write = _TWIN_DOORS.get(door)
    if write is None:
        return None
    try:
        twin = Vec2(*(float(c) for c in start))
    except (TypeError, ValueError, OverflowError):
        return None
    o = OPERANDS[operand]()
    try:
        with hypothesis_support.quiet():
            write(twin, o)
    except Exception as e:  # noqa: BLE001
        return f"accepted here; a free twin refuses ({type(e).__name__}: {e!s:.80})"
    finally:
        if isinstance(o, Point) and not o.__dict__.get("_ephemeral"):
            o.destroy()
    want = raw_xy(twin)
    if not all(_num_eq(a, b) for a, b in zip(got, want)):
        return f"x, y = {got!r:.60}; a free twin gives {want!r:.60}"
    return None


def axes(kinds=None, doors=None, operands=None, contexts=None, reads=None):
    return [
        ("kind", list(kinds or KINDS)),
        ("door", list(doors or DOORS)),
        ("operand", list(operands or OPERANDS)),
        ("context", list(contexts or CONTEXTS)),
        ("read", list(reads or READS)),
    ]


def valid(partial: Dict) -> bool:
    kind, door = partial.get("kind"), partial.get("door")
    if kind is not None and door is not None:
        return door_valid(kind, door)
    return True
