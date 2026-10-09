"""Laws and commuting diagrams: many roads, one shape (geometry campaign, H3).

Two programs that must end in the same shape, run on twin subjects:

* ``TestLawArray`` — the law table (``geom_laws.LAWS``: algebra, timed =
  instant, spellings) over kind × law × base state × warmth × execution twin;
  a 2-wise array at family level in ``quick``, every kind × model in ``gate``.
* ``TestCopyCommutes`` — ``clone`` and ``d << s`` commute with every verb:
  the verb **before** the copy equals the verb on the copy, on every kind
  (``sweep_c7`` covers copy-then-act; this is act-then-copy, including the
  kinds it skips for ``<<`` and a source that is mid-tween or flipped).
* ``TestWholeLinkTransparency`` — a verb on the source of ``d @= s`` gives
  ``d`` what the same verb gives a plain twin.
* ``TestHistoryIndependence`` — after any history, a clone and the subject
  stay alike under the same further steps (bisimulation: a sticky flag, a
  stale cache or a leftover name sign shows up as a later divergence).
* ``TestConstructionPaths`` — a built shape moved / scaled / turned about its
  placement equals the shape built from the moved / scaled / turned inputs.

What a law compares follows Q6 (Testing Design — Geometry campaign). Known
violations: ``geom_campaign_known.LAWS`` (shrink-only patterns over
``"law | kind | detail"``).

    python tests/run_tiers.py focused test_geom_laws
"""
from __future__ import annotations

import fnmatch
import os
import random
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis_support import fresh_world  # noqa: E402

import covering  # noqa: E402
import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geom_laws as L  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402

FAMILIES = sorted({A.family(k) for k in A.K})
MODELS = {f: sorted(k for k in A.K if A.family(k) == f) for f in FAMILIES}
LAW_NAMES = [law.name for law in L.LAWS]
LAW_BY_NAME = {law.name: law for law in L.LAWS}
BASES = ["fresh", "flip_x", "flip_xy", "rotated", "scaled", "min_scale", "degenerate",
         "names_crossed", "copied", "cloned", "mid_tween", "collidable", "drawn", "parked"]
XS = ["normal", "forced_slow", "caches_dropped"]
DEEP = hypothesis_support.PROFILE in ("ci", "deep")


def _known(key, table):
    return any(fnmatch.fnmatch(key, p) for p in table)


def _check(tc, found, table, stale_check):
    new = sorted(k for k in found if not _known(k, table))
    tc.assertFalse(new, "new law violations (triage, then fix or list):\n  "
                   + "\n  ".join(f"{k}  {found[k]}"[:240] for k in new[:30]))
    if stale_check:
        stale = sorted(p for p in table if not any(fnmatch.fnmatch(k, p) for k in found))
        tc.assertFalse(stale, f"known patterns nothing matches (fixed: remove): {stale}")


class TestLawArray(unittest.TestCase):
    def _run(self, kinds, family_level, t=2):
        axes = [("K", kinds), ("LAW", LAW_NAMES), ("B", BASES), ("W", list(A.W)), ("X", XS)]
        rows = covering.covering_array(axes, t)
        found, ran = {}, set()
        with fresh_world() as w:
            for n, row in enumerate(rows):
                kind = row["K"]
                if family_level:
                    kind = MODELS[kind][n % len(MODELS[kind])]
                law = LAW_BY_NAME[row["LAW"]]
                out = L.run_law(w, law, kind, row["B"], row["W"], row["X"])
                ran.add(law.name)
                if out:
                    found[f"{law.name} | {kind} | {out}"] = f"{row}"
        return found, ran

    def test_quick_array(self):
        found, ran = self._run(FAMILIES, True)
        self.assertEqual(sorted(ran), sorted(LAW_NAMES))
        _check(self, found, KNOWN.LAWS, stale_check=False)

    def test_every_kind(self):
        if not DEEP:
            self.skipTest("every kind runs in the gate and deep tiers")
        found, _ran = self._run(sorted(A.K), False)
        found.update(_pinned())
        _check(self, found, KNOWN.LAWS, stale_check=True)


# Minimal repros of the listed law findings (always run by the full array).
PINNED = [
    ("rotate_to timed = instant (Q2)", "Rect center_wh", "rotated"),
    ("flip_x then flip_y = rotate_by 180 (geometry)", "Line tangent_angle", "degenerate"),
]


def _pinned():
    found = {}
    with fresh_world() as w:
        for name, kind, base in PINNED:
            out = L.run_law(w, LAW_BY_NAME[name], kind, base)
            if out:
                found[f"{name} | {kind} | {out}"] = base
    return found


VERBS = {
    "move_by": lambda o: o.move_by(7, -3),
    "rotate_by": lambda o: o.rotate_by(33),
    "rotate_by about": lambda o: o.rotate_by(33, about=L.PIVOT),
    "scale_by": lambda o: o.scale_by(1.5),
    "flip_x": lambda o: setattr(o, "flip_x", not o.flip_x),
    "angle =": lambda o: setattr(o, "angle", float(o.angle) + 41),
}


def _try(fn, *a):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fn(*a)
        return None
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return exc


class TestCopyCommutes(unittest.TestCase):
    """``copy ∘ V`` = ``V ∘ copy`` for clone and ``<<``, every kind, every verb."""

    DOORS = ("clone", "<<")

    def _copy(self, w, door, src, kind):
        if door == "clone":
            return w.track(src.clone())
        dst = w.track(A.build(L._free_kind(kind) if hasattr(L, "_free_kind") else kind,
                              dict(G.P0, x=-40.0, y=55.0)))
        dst << src
        return dst

    def _cells(self):
        """Every kind × door × base × verb in gate; one model per family (in
        turn) and one base per verb in quick."""
        bases = ("fresh", "flip_x", "rotated")
        if DEEP:
            for kind in sorted(A.K):
                for door in self.DOORS:
                    for base in bases:
                        for vname in VERBS:
                            yield kind, door, base, vname
            return
        for i, vname in enumerate(VERBS):
            for f in FAMILIES:
                kind = MODELS[f][i % len(MODELS[f])]
                for door in self.DOORS:
                    yield kind, door, bases[i % len(bases)], vname

    def test_act_then_copy_equals_copy_then_act(self):
        found = {}
        with fresh_world() as w:
            for kind, door, base, vname in self._cells():
                if kind.startswith("Box"):
                    continue
                if door == "<<" and kind.endswith("reversed"):
                    continue            # a reversed() view refuses a copy (Tracks Design)
                out = self._cell(w, kind, door, base, vname)
                if out:
                    found[out[0]] = out[1]
        _check(self, found, KNOWN.COPY_LAWS, stale_check=DEEP)

    def _cell(self, w, kind, door, base, vname):
        verb = VERBS[vname]
        G.reset_clock()
        s1, s2 = (w.track(A.build(kind)) for _ in range(2))
        if A.apply_base(base, s1, w) is None or A.apply_base(base, s2, w) is None:
            return None
        if vname == "flip_x" and not G.can_flip(s1):
            return None
        if G.is_relational(s1):
            return None                 # its copy is the free twin: verbs mean other things
        # Names freeze at first use (Shapes Design, Named points): freeze both
        # before acting, so the law is about the verb.
        A.W["all"](s1)
        A.W["all"](s2)
        if _try(verb, s1) is not None:
            return None                 # the source refuses: not this law
        try:
            c1 = self._copy(w, door, s1, kind)
            c2 = self._copy(w, door, s2, kind)
        except (Exception, RecursionError) as exc:  # noqa: BLE001
            return f"{door} | {kind} | copy raises {type(exc).__name__}", str(exc)[:120]
        e2 = _try(verb, c2)
        if e2 is not None:
            return f"{door} after {vname} | {kind} | copy refuses {type(e2).__name__}", base
        # ``point << p`` takes the position only, like a Point's whole link
        # (Shapes Design, C7): its pose is its own.
        pose_only = door == "<<" and A.family(kind) in ("Point", "Anchor")
        d = L.differ(L.observe(c1), L.observe(c2),
                     L.Law("copy", None, None, pose=not pose_only, flags=not pose_only))
        if d:
            return f"{door} after {vname} | {kind} | {d}", base
        return None


class TestWholeLinkTransparency(unittest.TestCase):
    """A verb on ``s`` reaches ``d @= s``: ``d`` reads like ``s`` after it.

    The oracle is the source itself, not a twin built apart: corner names
    freeze at first use, and the link's pull is a use of ``s`` (Testing
    Design, lesson 3 of the reactive campaign). A Point's whole link carries
    its position only (graphics review batch 4), so its pose is not compared."""

    def test_verbs_through_a_whole_link(self):
        found, ran = {}, 0
        with fresh_world() as w:
            for kind in sorted(A.K):
                if kind.startswith("Box") or A.family(kind) in ("Sprite", "Svg", "Text", "Track", "Anchor"):
                    continue
                for vname, verb in VERBS.items():
                    G.reset_clock()
                    s = w.track(A.build(kind))
                    twin = w.track(A.build(kind))
                    d = w.track(A.build(kind, dict(G.P0, x=-40.0, y=55.0)))
                    if G.is_relational(s):
                        continue
                    if _try(lambda: d.__imatmul__(lambda: s)) is not None:
                        break
                    if vname == "flip_x" and not G.can_flip(s):
                        continue
                    if _try(verb, s) is not None or _try(verb, twin) is not None:
                        continue
                    ran += 1
                    law = L.Law("whole", None, None, pose=A.family(kind) != "Point")
                    diff = L.differ(L.observe(d), L.observe(s), law)
                    if diff:
                        found[f"d @= s then {vname} on s | {kind} | {diff}"] = ""
        self.assertGreater(ran, 100)
        _check(self, found, KNOWN.LAWS, stale_check=False)


class TestHistoryIndependence(unittest.TestCase):
    """Bisimulation: a clone made after any history acts like its source."""

    def test_clone_and_source_stay_alike(self):
        rng = random.Random(5)
        found = {}
        steps = [n for n in S.STEP_NAMES]
        with fresh_world() as w:
            for kind in sorted(A.K):
                if kind.startswith("Box"):
                    continue
                for rep in range(3 if DEEP else 1):
                    G.reset_clock()
                    x = w.track(A.build(kind))
                    if getattr(x, "_ref", None) is not None:
                        w.track(x._ref)
                    history = [rng.choice(steps) for _ in range(4)]
                    sh = S.Shadow(x, kind)
                    for st in history:
                        if S.STEP_BY_NAME[st][1](x):
                            _try(lambda: S.step_runner(kind, st, x)(x, sh))
                    A.W[rng.choice(list(A.W))](x)
                    y = w.track(x.clone())
                    if G.is_relational(x):
                        continue                # the clone is free, the source is not
                    for st in [rng.choice(steps) for _ in range(4)]:
                        if not S.STEP_BY_NAME[st][1](x):
                            continue
                        ex = _try(lambda: S.STEP_BY_NAME[st][2](x, S.Shadow(x, kind)))
                        ey = _try(lambda: S.STEP_BY_NAME[st][2](y, S.Shadow(y, kind)))
                        if (ex is None) != (ey is None):
                            found[f"clone after history | {kind} | {st} refused one way"] = str(history)
                            break
                        d = L.differ(L.observe(x), L.observe(y))
                        if d:
                            found[f"clone after history | {kind} | {d} after {st}"] = str(history)
                            break
        _check(self, found, KNOWN.LAWS, stale_check=False)


# Builders whose geometry turns about (x, y) by p["r"] (read from
# geometry_support.KINDS / geom_axes.EXTRA_KINDS): the center-, corner-,
# vertex- and p1-placed models with angle=p["r"], and the polar ones.
ROTATION_EQUIVARIANT = {
    "Line point_point", "Line point_vec", "Line center_length", "Line point_angle_length",
    "Line tangent_angle", "Line tangent_point",
    "Circle center_radius", "Circle center_perimeter", "Circle two_points", "Circle arc",
    "Ellipse center_wh", "Ellipse focal_points", "Ellipse from_rect",
    "RegularPolygon center_radius", "RegularPolygon center_side", "RegularPolygon vertex_side",
    "EquilateralTriangle center_radius", "EquilateralTriangle center_side", "EquilateralTriangle vertex_side",
    "Rect center_wh", "Rect top_left_wh", "Rect point_vec", "Rect point_vec negative",
    "Rect spine cap", "Rect spine square", "Rect spine side_left", "Rect spine side_right",
    "Square center_length", "Square top_left_length",
    "Track line point_point", "Track line length", "Track circle", "Track eight",
    "Sprite", "Svg", "Text center", "Point", "Anchor",
}


class TestConstructionPaths(unittest.TestCase):
    """A shape built at ``p`` then moved / scaled / turned = the shape built there."""

    def _compare(self, w, kind, p2, act, what):
        a = w.track(A.build(kind))
        b = w.track(A.build(kind, p2))
        for o in (a, b):
            if getattr(o, "_ref", None) is not None:
                w.track(o._ref)
        if G.is_relational(a):
            return None                 # its verbs keep the relation (constraint cells)
        e = _try(act, a)
        if e is not None:
            return None
        # Same shape, not the same pose store: ``scale_by(2)`` reads scale 2 on
        # the moved shape and 1 on the one built twice as big.
        d = L.differ(L.observe(a), L.observe(b), L.Law(what, None, None, pose=False, flags=False))
        return d

    def test_translate_scale_turn(self):
        found = {}
        p0 = dict(G.P0)
        with fresh_world() as w:
            for kind in sorted(A.K):
                if kind.endswith("reversed"):
                    continue
                d = self._compare(w, kind, dict(p0, x=p0["x"] + 11, y=p0["y"] - 7),
                                  lambda o: o.move_by(11, -7) if not G.is_box(o) else o.__lshift__(o), "move")
                if d and not G.is_box(A.build(kind)):
                    found[f"build moved | {kind} | {d}"] = ""
                if not G.scale_is_pose(A.build(kind)) and not kind.startswith(("Box", "Point", "Anchor")):
                    d = self._compare(w, kind, dict(p0, s=p0["s"] * 2.0),
                                      lambda o: o.scale_by(2.0, about=(p0["x"], p0["y"])), "scale")
                    if d:
                        found[f"build scaled | {kind} | {d}"] = ""
                if kind in ROTATION_EQUIVARIANT:
                    d = self._compare(w, kind, dict(p0, r=p0["r"] + 25.0),
                                      lambda o: o.rotate_by(25.0, about=(p0["x"], p0["y"])), "turn")
                    if d:
                        found[f"build turned | {kind} | {d}"] = ""
        _check(self, found, KNOWN.LAWS, stale_check=False)


class TestLawCanaries(unittest.TestCase):
    """Planted bugs the law array catches (SCENA_CANARIES)."""

    def _catch(self, patches, what):
        from diff_support import assert_catches
        assert_catches(self, "test_geom_laws.TestLawArray.test_quick_array", patches, what)

    def test_catches_a_move_that_is_not_additive(self):
        from scena.shapes import Shape
        real = Shape.move_by

        def lossy(self, dx, dy=None, *a, **kw):
            if isinstance(dx, (int, float)) and abs(dx) > 6:
                dx = dx + 0.5
            return real(self, dx, dy, *a, **kw)
        self._catch([(Shape, "move_by", lossy)], "a long move adds half a unit")

    def test_catches_a_scale_that_is_not_multiplicative(self):
        def drift(x, y, cx, cy, factor):
            factor = factor + 0.01
            return cx + (x - cx) * factor, cy + (y - cy) * factor
        self._catch([("scena.shapes", "_scale_xy", drift)], "every scale drifts by 0.01")


if __name__ == "__main__":
    unittest.main()
