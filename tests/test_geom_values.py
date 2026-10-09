"""Value edges and refusal atomicity through every path (geometry campaign, H8).

``test_value_validation`` checks each value door once; ``test_refusal_atomic``
checks each refusal once. This module puts the geometric edges into every
write path and into sequences:

* ``TestEdgeValuesAgreeOnEveryPath`` — every Defining field of every kind ×
  an edge value (0, -0.0, ±180, 360k, 1e6, ``MIN_SCALE``, and the junk pools of
  ``test_value_validation``) × every path (``=``, a link, a write inside a
  batch, ``part << xy``): every path refuses alike or stores alike, and a
  refusal is an author error that changes nothing.
* ``TestLinkSourceTurnsBad`` — a linked field whose source turns NaN / inf /
  a bool / a huge int mid-run refuses at the read with an author error,
  leaves the geometry as it was, and follows again once the source is valid.
* ``TestRefusalsInsideBatchesAndFrames`` — a refused verb inside a frame batch
  or inside a scheduled callback changes nothing (``test_refusal_atomic``
  checks direct calls only).

Tolerance is relative to the magnitude (far coordinates). Known divergences:
``geom_campaign_known.VALUES``.

    python tests/run_tiers.py focused test_geom_values
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
from hypothesis_support import fresh_world, quiet  # noqa: E402

import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402
from scena import State  # noqa: E402
from scena.state import ContainerSlot, LinkedAttributeError, ScalarSlot  # noqa: E402
from scena.validate import MIN_SCALE  # noqa: E402
from test_value_validation import NUM_JUNK, POINT_JUNK, _author_error  # noqa: E402

DEEP = hypothesis_support.PROFILE in ("ci", "deep")
EDGE_NUMS = (0.0, -0.0, 1e-9, -3.5, 180.0, -180.0, 360.0, 720.5, -1080.0, 1e6, -1e6, MIN_SCALE)
EDGE_POINTS = ((0.0, -0.0), (1e6, -1e6), (-1e6, 3.0), (1e-9, 1e-9))
PATHS = ("=", "link", "batch", "<<")


def _fields(obj):
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    out = []
    for name in sorted(A._defining(obj)):
        slot = slots.get(name)
        if isinstance(slot, ScalarSlot):
            out.append((name, False))
        elif isinstance(slot, ContainerSlot) and slot.container_class.__name__ in ("Point", "Vec2"):
            out.append((name, True))
    return out


def _write(obj, name, is_pair, v, path):
    if path == "=":
        setattr(obj, name, v)
    elif path == "batch":
        from diff_support import in_batch
        in_batch(lambda: setattr(obj, name, v))
    elif path == "<<":
        getattr(obj, name) << v
    elif path == "link":
        st = State(name="h8link")
        if is_pair:
            st.x, st.y = v[0], v[1]
            obj[name] @= lambda: (st.x, st.y)
        else:
            st.v = v
            obj[name] @= lambda: st.v
        getattr(obj, name)                      # the pull applies the slot's rules


def _read(obj, name, is_pair):
    v = getattr(obj, name)
    if is_pair:
        return ("pt", round(float(v.x), 6) + 0.0, round(float(v.y), 6) + 0.0)
    return ("num", round(float(v), 6) + 0.0)


def outcome(w, kind, name, is_pair, v, path):
    """('refused', author_error, changed) or ('ok', read, drawn)."""
    G.reset_clock()
    obj = w.track(A.build(kind))
    if getattr(obj, "_ref", None) is not None:
        w.track(obj._ref)
    before = S.snapshot(obj)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _write(obj, name, is_pair, v, path)
            got = _read(obj, name, is_pair)
            drawn = G.as_set(G.drawn(obj), 4)
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        changed = S.compare_snapshots(before, S.snapshot(obj)) if path != "link" else []
        return ("refused", _author_error(exc), tuple(changed))
    return ("ok", got, drawn)


def _num_same(x, y) -> bool:
    if math.isinf(x) or math.isinf(y) or math.isnan(x) or math.isnan(y):
        return repr(x) == repr(y)
    return A.close_num(x, y, 1e-6)


def _bad_number(v) -> bool:
    """NaN, inf, a bool or an int no float holds (the Numbers rule's refusals)."""
    items = v if isinstance(v, tuple) else (v,)
    for x in items:
        if isinstance(x, bool) or (isinstance(x, int) and abs(x) > 2 ** 1023):
            return True
        if isinstance(x, float) and not math.isfinite(x):
            return True
    return False


def _same_ok(a, b) -> bool:
    if a[1] != b[1] and not (a[1][0] == b[1][0] and all(
            _num_same(x, y) for x, y in zip(a[1][1:], b[1][1:]))):
        return False
    return G.same_set(a[2], b[2], 1e-4 * max([1.0] + [abs(c) for q in a[2] for c in q]))


def _cells():
    kinds = sorted(k for k in A.K if not k.endswith("reversed"))
    if not DEEP:
        fams = {}
        for k in kinds:
            fams.setdefault(A.family(k), k)
        kinds = sorted(set(fams.values()) | {"Rect spine cap", "Circle center_perimeter",
                                             "Line point_point", "Ellipse focal_points", "Track circle"})
    for kind in kinds:
        obj = A.build(kind)
        fields = _fields(obj)
        A._destroy(obj)
        for name, is_pair in fields:
            values = (EDGE_POINTS + POINT_JUNK) if is_pair else (EDGE_NUMS + NUM_JUNK)
            for v in values:
                yield kind, name, is_pair, v


def _known(key):
    return any(fnmatch.fnmatch(key, p) for p in KNOWN.VALUES)


class TestEdgeValuesAgreeOnEveryPath(unittest.TestCase):
    def test_every_field_value_and_path(self):
        found, ran = {}, 0
        with fresh_world() as w:
            for kind, name, is_pair, v in _cells():
                outs = {}
                for path in PATHS:
                    if path == "<<" and not is_pair:
                        continue
                    outs[path] = outcome(w, kind, name, is_pair, v, path)
                ran += 1
                tag = repr(v) if not isinstance(v, int) or abs(v) < 1e9 else "10**400"
                for path, o in outs.items():
                    if o[0] == "ok" and _bad_number(v) and any(
                            isinstance(c, float) and not math.isfinite(c) for c in o[1][1:]):
                        found[f"{kind} | {name} | {path} | stores a non-finite value"] = tag
                    if o[0] == "refused" and not o[1]:
                        found[f"{kind} | {name} | {path} | not an author error"] = tag
                    if o[0] == "refused" and o[2]:
                        found[f"{kind} | {name} | {path} | refusal changed {o[2][0]}"] = tag
                ref = outs["="]
                for path, o in outs.items():
                    if o[0] != ref[0]:
                        found[f"{kind} | {name} | {path} vs = | {o[0]} vs {ref[0]}"] = tag
                    elif o[0] == "ok" and not _same_ok(o, ref):
                        found[f"{kind} | {name} | {path} vs = | stores another value"] = f"{tag}: {o[1]} vs {ref[1]}"
        self.assertGreater(ran, 100)
        new = sorted(k for k in found if not _known(k))
        self.assertFalse(new, "paths disagree on a value:\n  " + "\n  ".join(
            f"{k}  {found[k]}"[:240] for k in new[:40]))
        if DEEP:
            stale = sorted(p for p in KNOWN.VALUES if not any(fnmatch.fnmatch(k, p) for k in found))
            self.assertFalse(stale, f"VALUES patterns nothing matches (fixed: remove): {stale}")


class TestLinkSourceTurnsBad(unittest.TestCase):
    BAD = (float("nan"), float("inf"), True, 10 ** 400)

    def test_refuse_at_the_read_keep_the_geometry_then_follow(self):
        wrong = []
        with fresh_world() as w:
            for kind in sorted(k for k in A.K if not k.endswith("reversed")):
                obj0 = A.build(kind)
                fields = [(n, p) for n, p in _fields(obj0) if not p]
                A._destroy(obj0)
                for name, _ in fields[:2]:
                    for bad in self.BAD:
                        G.reset_clock()
                        obj = w.track(A.build(kind))
                        if getattr(obj, "_ref", None) is not None:
                            w.track(obj._ref)
                        st = State(name="h8bad")
                        v0 = float(getattr(obj, name))
                        st.v = v0
                        try:
                            with quiet():       # a relational input relinks with a warning
                                obj[name] @= lambda: st.v
                        except (LinkedAttributeError, TypeError):
                            continue
                        import geom_sentinel as GS
                        root = obj._ownership_root()
                        good = GS.raw_state(root)
                        st.v = bad
                        try:
                            with quiet():
                                getattr(obj, name)
                            refused = None
                        except Exception as exc:  # noqa: BLE001
                            refused = exc
                        if refused is None:
                            # A clamp is allowed for a ranged field; anything else must refuse.
                            slot = obj._field_slots().get(name)
                            if not (getattr(slot, "minimum", None) is not None and isinstance(bad, float)
                                    and math.isinf(bad)):
                                wrong.append(f"{kind}.{name} <- {bad!r}: accepted")
                            continue
                        if not _author_error(refused):
                            wrong.append(f"{kind}.{name} <- {bad!r}: {type(refused).__name__} is not an author error")
                        # While the source is bad every public read re-pulls and
                        # refuses again: compare the raw state instead (the linked
                        # field itself is not settled and is left out).
                        changed = GS.atomic_diff(good, GS.raw_state(root))
                        if changed:
                            wrong.append(f"{kind}.{name} <- {bad!r}: the geometry changed {changed}")
                        st.v = v0 * 0.5 + 1.0
                        try:
                            with quiet():
                                back = float(getattr(obj, name))
                        except Exception as exc:  # noqa: BLE001
                            wrong.append(f"{kind}.{name}: stays broken after a valid value ({type(exc).__name__})")
                            continue
                        slot = obj._field_slots().get(name)
                        want = v0 * 0.5 + 1.0
                        lo, hi = getattr(slot, "minimum", None), getattr(slot, "maximum", None)
                        if lo is not None:
                            want = max(lo, want)
                        if hi is not None:
                            want = min(hi, want)
                        if not A.close_num(back, want, 1e-6):
                            wrong.append(f"{kind}.{name}: does not follow again ({back} vs {want})")
        new = sorted(x for x in wrong
                     if not any(fnmatch.fnmatch(f"bad source | {x}", p) for p in KNOWN.BAD_SOURCE))
        self.assertEqual(new, [], "\n".join(new[:20]))


class TestRefusalsInsideBatchesAndFrames(unittest.TestCase):
    VERBS = {
        "move_by": lambda o: o.move_by(7, -3),
        "rotate_by": lambda o: o.rotate_by(33),
        "scale_by": lambda o: o.scale_by(1.5),
        "flip_x": lambda o: setattr(o, "flip_x", not o.flip_x),
    }

    def test_a_refused_verb_changes_nothing_anywhere(self):
        from diff_support import in_batch
        from scena import after
        from scena.process import tick_processes
        from scena import clock
        wrong, refused = [], 0
        with fresh_world() as w:
            for kind in sorted(k for k in A.K if not k.endswith("reversed") and not k.startswith("Box")):
                for link in ("field", "part", "whole"):
                    for vname, verb in self.VERBS.items():
                        for where in ("batch", "frame"):
                            G.reset_clock()
                            obj = w.track(A.build(kind))
                            if A.apply_link(link, obj, w) is None:
                                continue
                            before = S.snapshot(obj)
                            try:
                                with quiet():
                                    if where == "batch":
                                        in_batch(lambda: verb(obj))
                                    else:
                                        after(0.0, lambda: verb(obj))
                                        clock.advance(1 / 60)
                                        tick_processes()
                                continue
                            except LinkedAttributeError:
                                refused += 1
                            except Exception:  # noqa: BLE001  (other refusals: H8 value doors)
                                continue
                            diff = S.compare_snapshots(before, S.snapshot(obj))
                            if diff:
                                wrong.append(f"{kind} | {link} | {vname} in a {where} | changed {diff}")
        self.assertGreater(refused, 50, "vacuous: nothing was refused")
        new = sorted(x for x in wrong if not _known(x))
        self.assertEqual(new, [])


if __name__ == "__main__":
    unittest.main()
