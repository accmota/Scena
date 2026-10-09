"""Influence matrix: every cache follows every input it reads (geometry campaign, H4).

For each kind × model, every Defining input and every pose quantity is changed
one at a time, away from its construction value:

* on a **cold** twin (nothing read, nothing cached) — the ground truth of what
  each observable becomes;
* on a **warm** twin (every part and Derivate read, the collision cache filled
  through the collider, the shape drawn, ``.box`` and the cull AABB read, a
  Track baked, a Text laid out) — the same change must give the same reads.

The observables are the ones a cache stands between: point and scalar parts,
the drawn set, collision prims (the collider's pose-keyed cache vs an uncached
rebuild), ``.box``, the cull AABB, the ``geom`` outline, the Track outline and
the hit test. A warm read that differs from the cold one is a cache keyed on
less than it reads (the G5 / G8 / R7 / D12 class).

Two pins on the cache keys themselves:

* when an input changes the uncached prims, ``collision._collision_pose_key``
  must change (else a cache hit serves the old hull);
* the influence matrix itself — which observable each input moves — is
  recorded, and every Defining input moves something (an input that changes
  nothing is a dead input or a missed refresh).

``test_cache_keys`` holds the same oracle for the sprite-sheet bake caches;
this extends it to the geometry caches. Known violations:
``geom_campaign_known.INFLUENCE``.

    python tests/run_tiers.py focused test_geom_influence
"""
from __future__ import annotations

import fnmatch
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis_support import fresh_world  # noqa: E402

import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geometry_support as G  # noqa: E402
from scena.state import ContainerSlot, ScalarSlot  # noqa: E402

DEEP = hypothesis_support.PROFILE in ("ci", "deep")


def _inputs(obj):
    """(name, perturb) for every Defining input and pose quantity of ``obj``."""
    out = []
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    for name in sorted(A._defining(obj)):
        slot = slots.get(name)
        if isinstance(slot, ScalarSlot):
            lo, hi = slot.minimum, slot.maximum

            def bump(o, n=name, lo=lo, hi=hi):
                v = float(getattr(o, n))
                if lo is not None and hi is not None:
                    # A ranged field clamps (Track begin / end / u, Circle spread):
                    # a value inside the range, away from the current one.
                    t = lo + (hi - lo) * 0.37
                    setattr(o, n, t if abs(t - v) > 0.05 * (hi - lo) else lo + (hi - lo) * 0.71)
                else:
                    setattr(o, n, v * 1.3 + 0.7)
            out.append((name, bump))
        elif isinstance(slot, ContainerSlot) and slot.container_class.__name__ in ("Point", "Vec2"):
            def shift(o, n=name):
                p = getattr(o, n)
                setattr(o, n, (float(p.x) + 3.1, float(p.y) - 2.2))
            out.append((name, shift))
    if not G.is_box(obj):
        out.append(("~move", lambda o: o.move_by(4.3, -1.7)))
        out.append(("~turn", lambda o: o.rotate_by(23)))
        out.append(("~scale", lambda o: o.scale_by(1.25)))
        if G.can_flip(obj):
            out.append(("~flip", lambda o: setattr(o, "flip_x", not o.flip_x)))
    else:
        out.append(("~turn", lambda o: o.rotate_by(23)))
    return out


def _uncached_prims(obj):
    from scena.collision import _snapshot_shape_uncached
    try:
        return _snapshot_shape_uncached(obj, cache_owner=None)
    except Exception:  # noqa: BLE001
        return None


def observe(obj, warm_cache: bool) -> dict:
    """What a cache stands between, read the way the engine reads it."""
    from scena.canvas import _approx_draw_aabb
    out = {n: G.safe(f) for n, f in G.point_parts(obj).items()}
    out.update({n: G.safe(f) for n, f in G.scalar_parts(obj).items()})
    out["~drawn"] = G.safe(lambda: G.as_set(G.drawn(obj), 5))
    if not G.is_box(obj):
        out["~aabb"] = G.safe(lambda: tuple(round(v, 5) for v in _approx_draw_aabb(obj)))
        col = getattr(obj, "_collider", None)
        if warm_cache and col is not None:
            from scena.collision import snapshot_shape
            prims = G.safe(lambda: snapshot_shape(obj, cache_owner=col))
        else:
            prims = _uncached_prims(obj)
        out["~prims"] = _prim_rows(prims)
    if type(obj).__name__ in ("Polygon", "RegularPolygon", "EquilateralTriangle", "Rect", "Square"):
        from scena.geom import _outline_verts
        out["~outline"] = G.safe(lambda: G.as_set(list(_outline_verts(obj) or ()), 5))
    if type(obj).__name__ in ("Track", "_ReversedTrack"):
        from scena.track import shape_outline
        out["~track"] = G.safe(lambda: G.as_set([(float(x), float(y)) for x, y in shape_outline(obj, samples=32)[0]], 4))
    return out


def _prim_rows(prims):
    if prims is None or isinstance(prims, G.ReadError):
        return prims
    rows = []
    for p in prims:
        vals = [round(float(v), 5) for v in tuple(p.aabb) + tuple(p.params)]
        for v in (p.verts or ()):
            vals.extend(round(float(c), 5) for c in v)
        rows.append((p.kind.name, tuple(vals)))
    return tuple(sorted(rows))


def _same(a, b) -> bool:
    if isinstance(a, G.ReadError) or isinstance(b, G.ReadError):
        return type(a) is type(b) and getattr(a, "name", None) == getattr(b, "name", None)
    if isinstance(a, tuple) and len(a) == 2 and all(isinstance(v, float) for v in a):
        return A.close_xy(a, b, 1e-6)
    if isinstance(a, float):
        return A.close_num(a, b, 1e-6)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(A.close_xy(p, q, 1e-4) for p, q in zip(a, b))
    if isinstance(a, tuple) and isinstance(b, tuple) and a and isinstance(a[0], tuple) \
            and len(a[0]) == 2 and isinstance(a[0][0], str):
        if len(a) != len(b):
            return False
        for (ka, va), (kb, vb) in zip(a, b):
            if ka != kb or len(va) != len(vb):
                return False
            scale = max([1.0] + [abs(v) for v in va])
            if any(abs(x - y) > 1e-4 * scale for x, y in zip(va, vb)):
                return False
        return True
    return a == b


def warm_up(obj) -> None:
    """Fill every cache the engine keeps for ``obj``."""
    import skia
    A.W["all"](obj)
    if not G.is_box(obj):
        if type(obj).__name__ not in ("Point", "Anchor", "Track", "_ReversedTrack", "Text"):
            try:
                obj.collidable = True
                from scena.collision import snapshot_shape
                snapshot_shape(obj, cache_owner=obj._collider)
            except Exception:  # noqa: BLE001
                pass
        try:
            obj.draw(skia.Surface(64, 64).getCanvas())
        except Exception:  # noqa: BLE001
            pass
    observe(obj, warm_cache=True)


def _kinds():
    return sorted(k for k in A.K if not k.endswith("reversed"))


def run_kind(w, kind):
    """(found violations, influence row) for one kind."""
    from scena.collision import _collision_pose_key
    found, row = {}, {}
    probe = A.build(kind)
    A._destroy(probe)
    for name, perturb in _inputs(A.build(kind)):
        G.reset_clock()
        cold = w.track(A.build(kind))
        warm = w.track(A.build(kind))
        for o in (cold, warm):
            if getattr(o, "_ref", None) is not None:
                w.track(o._ref)
        before = observe(cold, warm_cache=False)
        warm_up(warm)
        key0 = G.safe(lambda: _collision_pose_key(warm)) if getattr(warm, "_collider", None) else None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perturb(cold)
        except Exception as exc:  # noqa: BLE001
            row[name] = f"refused {type(exc).__name__}"
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                perturb(warm)
        except Exception as exc:  # noqa: BLE001
            found[f"{kind} | {name} | warm refuses {type(exc).__name__}"] = ""
            continue
        after_cold = observe(cold, warm_cache=False)
        after_warm = observe(warm, warm_cache=True)
        moved = sorted(k for k in after_cold if not _same(before.get(k), after_cold[k]))
        row[name] = moved
        for k in after_cold:
            if not _same(after_cold[k], after_warm.get(k)):
                found[f"{kind} | {name} | warm {G.part_group(k)} stale"] = f"{after_warm.get(k)} vs {after_cold[k]}"
        if key0 is not None and "~prims" in moved:
            key1 = G.safe(lambda: _collision_pose_key(warm))
            if key1 == key0:
                found[f"{kind} | {name} | collision key unchanged"] = ""
    return found, row


class TestWarmEqualsCold(unittest.TestCase):
    def test_every_input_of_every_kind(self):
        found, matrix = {}, {}
        kinds = _kinds() if DEEP else sorted({min(k for k in _kinds() if A.family(k) == f)
                                              for f in {A.family(k) for k in _kinds()}}
                                             | {"Rect spine cap", "Line point_point", "Circle two_points",
                                                "Ellipse focal_points", "Track circle", "Text top_left"})
        with fresh_world() as w:
            for kind in kinds:
                f, row = run_kind(w, kind)
                found.update(f)
                matrix[kind] = row
        new = sorted(k for k in found if not any(fnmatch.fnmatch(k, p) for p in KNOWN.INFLUENCE))
        self.assertFalse(new, "a warm cache missed an input:\n  "
                         + "\n  ".join(f"{k}  {found[k]}"[:260] for k in new[:30]))
        if DEEP:
            stale = sorted(p for p in KNOWN.INFLUENCE if not any(fnmatch.fnmatch(k, p) for k in found))
            self.assertFalse(stale, f"INFLUENCE patterns nothing matches (fixed: remove): {stale}")
        dead = sorted(f"{k}.{n}" for k, row in matrix.items() for n, moved in row.items()
                      if not n.startswith("~") and moved == [])
        self.assertEqual(dead, [], "a Defining input that changes nothing observable")
        self.assertGreater(sum(len(r) for r in matrix.values()), 40)


class TestInfluenceCanary(unittest.TestCase):
    def test_catches_a_collision_key_that_ignores_the_pose(self):
        from diff_support import assert_catches
        assert_catches(self, "test_geom_influence.TestWarmEqualsCold.test_every_input_of_every_kind",
                       [("scena.collision", "_collision_pose_key", lambda shape: (0,))],
                       "a collision cache keyed on nothing")


if __name__ == "__main__":
    unittest.main()
