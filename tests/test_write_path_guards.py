"""Static guards on the write paths (Track A item 6; Track C item 5 closed as guards).

The reactive bugs D12-D25 came from writes that skipped something: a raw
``__dict__`` store that left a computed field or a link reader stale, a dirty
bit cleared on a node that was not recomputed, a pose fast path that skipped
the notification its readers needed, a private point reader with its own
rules. The write paths stay separate (they exist for speed); these guards make
every new bypass a test failure that names the rule, instead of the next
stale-read bug.

Each allowlist entry is (file, function) -> why it may bypass. Add an entry
only with a reason that holds; otherwise route the write through the slot /
``_takein`` / ``_xy_of``.

    python tests/run_tiers.py focused test_write_path_guards
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from source_support import iter_files  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scena")


def _functions():
    """(file, qualname, FunctionDef) for every function in scena/."""
    for path in iter_files(ROOT, ".py"):
        fname = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        def walk(node, stack):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield fname, ".".join(stack + [ch.name]), ch
                    yield from walk(ch, stack + [ch.name])
                elif isinstance(ch, ast.ClassDef):
                    yield from walk(ch, stack + [ch.name])
                else:
                    yield from walk(ch, stack)
        yield from walk(tree, [])


def _slot_names():
    import importlib
    import inspect
    import pkgutil
    import scena
    from scena.state import ContainerSlot, ScalarSlot
    names = set()
    for m in pkgutil.iter_modules(scena.__path__):
        try:
            mod = importlib.import_module("scena." + m.name)
        except Exception:
            continue
        for obj in vars(mod).values():
            if inspect.isclass(obj):
                for k, v in vars(obj).items():
                    if isinstance(v, (ScalarSlot, ContainerSlot)):
                        names.add(k)
    return names


class TestRawFieldStoresAreAllowlisted(unittest.TestCase):
    """``obj.__dict__[field] = v`` skips the slot's rules and every notification."""

    ALLOWED = {
        ("closed.py", "seal"): "closed-surface sealing (instance bookkeeping, not a field value)",
        ("closed.py", "seal_after_init"): "closed-surface sealing",
        ("closed.py", "seal_after_init.__init__"): "closed-surface sealing",
        ("scenamath.py", "Vec2.__init__"): "construction, before any reader exists",
        ("scenamath.py", "Vec2._sync_computed"): "brings computed length / angle in step after a raw x / y store (D12)",
        ("scenamath.py", "Vec2._takein_impl"): "the pull's raw store (the caller notifies; Reactive Design, 'Pull stores raw')",
        ("shapes.py", "Point._takein_impl"): "the pull's raw store (the caller notifies)",
        ("shapes.py", "_takein_xy_float"): "the A1 pose fast path itself (gated: TestPoseFastPathsAreGated)",
        ("shapes.py", "Circle.rotate_by"): "A1 fast turn, only when not _requires_pull_invalidate()",
        ("shapes.py", "RegularPolygon.rotate_by"): "A1 fast turn, only when not _requires_pull_invalidate()",
        ("shapes.py", "_DerivedRotationRoute._write_field"): "the model's own refresh of a derived heading, inside the update batch",
        ("state.py", "Container._write_field"): "the base write path (after the slot's coercion)",
        ("state.py", "ContainerSlot.__get__"): "lazy part creation",
        ("state.py", "ScalarAnchor._takein_impl"): "the link pull's raw store (after the slot's coercion)",
        ("state.py", "_init_scalar"): "construction (after the slot's coercion)",
        ("text.py", "Text.__init__"): "construction",
        ("uiwidget.py", "UIWidget._bind_data"): "binds the data cell (the part itself, not a value)",
    }

    def test_every_raw_store_is_allowlisted(self):
        slots = _slot_names()
        found = set()
        for fname, qual, fn in _functions():
            aliases = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute) \
                        and n.value.attr == "__dict__":
                    aliases.update(t.id for t in n.targets if isinstance(t, ast.Name))
            for n in ast.walk(fn):
                if not isinstance(n, (ast.Assign, ast.AugAssign)):
                    continue
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if not isinstance(t, ast.Subscript):
                        continue
                    base = t.value
                    if not ((isinstance(base, ast.Attribute) and base.attr == "__dict__")
                            or (isinstance(base, ast.Name) and base.id in aliases)):
                        continue
                    key = t.slice
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if key.value in slots:
                            found.add((fname, qual))
                    else:
                        found.add((fname, qual))       # a variable key may be a field
        self.assertEqual(sorted(found - set(self.ALLOWED)), [],
                         "raw field store: write through the slot or _takein, or allowlist with a reason")
        self.assertEqual(sorted(set(self.ALLOWED) - found), [], "stale allowlist entry")


class TestDirtyBitWritesAreAllowlisted(unittest.TestCase):
    """Clearing ``_dirty`` on a node that was not recomputed freezes it (D13, D19)."""

    ALLOWED = {
        ("state.py", "Container.__init__"): "initial state",
        ("state.py", "Container._clear_subtree_dirty"): "after a refresh; skips parts with their own link (D13)",
        ("state.py", "Container._recalculate_formula"): "passthrough / no structural root: nothing to recompute",
        ("state.py", "Container._resolve_link"): "after the link's value was stored (and the owner refreshed, D19)",
        ("state.py", "Container.update"): "sets dirty before an immediate resolve (ephemeral nodes)",
        ("state.py", "FormulaLink.evaluate_and_update"): "after the value was applied (and the owner refreshed, D19)",
        ("state.py", "UpdateManager.mark_clean"): "teardown",
        ("state.py", "UpdateManager.mark_dirty"): "the one place that sets dirty along a cone",
        ("track.py", "Track._invalidate_bake"): "sets dirty (re-bake)",
        ("track.py", "Track._takein_impl"): "sets dirty after a copy",
    }

    def test_every_dirty_write_is_allowlisted(self):
        found = set()
        for fname, qual, fn in _functions():
            for n in ast.walk(fn):
                if not isinstance(n, (ast.Assign, ast.AugAssign)):
                    continue
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Attribute) and t.attr == "_dirty":
                        found.add((fname, qual))
                    if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "_dirty"):
                        found.add((fname, qual))
        self.assertEqual(sorted(found - set(self.ALLOWED)), [],
                         "a _dirty write: use mark_dirty / _clear_subtree_dirty, or allowlist with a reason")
        self.assertEqual(sorted(set(self.ALLOWED) - found), [], "stale allowlist entry")


class TestPoseFastPathsAreGated(unittest.TestCase):
    """A raw float pose write skips the graph: allowed only while nothing reads
    the points through a link (``_pose_fast_ok`` / ``_requires_pull_invalidate``,
    or the per-node ``_link_source`` flag set when a link first reads a node;
    Reactive Design hazard #8). Text's moves were not gated (D25)."""

    FAST = {"_takein_xy_float", "_translate_point_float", "_translate_points_float", "_takein_float"}
    GATES = {"_pose_fast_ok", "_requires_pull_invalidate"}
    ALLOWED = {
        ("text.py", "Text._materialize_derivate_part"): "first fill of a part on its first read: no reader yet",
    }

    def test_every_fast_write_sits_behind_the_gate(self):
        ungated = set()
        for fname, qual, fn in _functions():
            if fn.name in self.FAST:
                continue
            calls_fast = gated = False
            for n in ast.walk(fn):
                if isinstance(n, ast.Constant) and n.value == "_link_source":
                    gated = True          # a link reads this point: notify
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                    if name in self.FAST:
                        calls_fast = True
                    if name in self.GATES:
                        gated = True
            if calls_fast and not gated:
                ungated.add((fname, qual))
        self.assertEqual(sorted(ungated - set(self.ALLOWED)), [],
                         "gate the raw pose write on _pose_fast_ok (else _takein)")
        self.assertEqual(sorted(set(self.ALLOWED) - ungated), [], "stale allowlist entry")


class TestPointReadersDelegate(unittest.TestCase):
    """Every point reader goes through ``shapes._xy_of`` / ``_read_xy`` (D24)."""

    NAME = re.compile(r"(^|_)as_xy$|_xy_of$|_xy_static$|^_locus_xy$|^_xy_destination$|"
                      r"^_anchor_xy$|^_xy_of_point$|^_?to_xy$|^_?as_point$")
    CORE = {("shapes.py", "_xy_of"), ("shapes.py", "_read_xy")}
    DELEGATES = {"_xy_of", "_read_xy", "_as_xy"}
    EXEMPT = {
        ("curves.py", "_as_xy"): "spline math on any indexable (numpy rows); not an author entry",
        ("collision.py", "_pose_xy_of"): "broad-phase pose key over built parts (get_xy, None on failure); not an author entry",
    }

    def test_point_readers_call_the_core(self):
        bad = []
        for fname, qual, fn in _functions():
            if not self.NAME.search(fn.name) or (fname, qual) in self.CORE | set(self.EXEMPT):
                continue
            calls = {getattr(n.func, "id", getattr(n.func, "attr", None))
                     for n in ast.walk(fn) if isinstance(n, ast.Call)}
            if not calls & self.DELEGATES:
                bad.append((fname, qual))
        self.assertEqual(bad, [], "a point reader with its own rules: delegate to _xy_of / _read_xy")


class TestTextLinksFollowAMove(unittest.TestCase):
    """D25: a direct link to a centred Text's ``center`` stayed put after
    ``move_by`` / ``move_to`` (a raw float write, no notification). D26: an
    anchored caption's ``center`` (written by the lazy layout) read the old
    centre after a move or a new string until something read the caption."""

    def test_every_placement_part_and_change_with_the_link_read_first(self):
        from scena import Point, Text, st
        st.wpg_caption = "hi"
        for place in ("center", "top_left", "top_right", "top_center"):
            for part in ("center", "top_left", "top_right", "top_center"):
                for change in ("move_by", "move_to", "text", "formula"):
                    with self.subTest(place=place, part=part, change=change):
                        t = Text("hi", **{place: (10, 10)})
                        if change == "formula":
                            t["text"] @= (lambda: st.wpg_caption)
                            st.wpg_caption = "hi"
                        q = Point(0, 0)
                        q @= getattr(t, part)
                        float(q.x)
                        if change == "move_by":
                            t.move_by(5, 7)
                        elif change == "move_to":
                            t.move_to(50, 60)
                        elif change == "text":
                            t.text = "a longer caption"
                        else:
                            st.wpg_caption = "a much longer caption"
                        got = (round(float(q.x), 6), round(float(q.y), 6))   # the link first
                        p = getattr(t, part)
                        self.assertEqual(got, (round(float(p.x), 6), round(float(p.y), 6)))

    def test_direct_link_to_a_centred_caption(self):
        from scena import Point, Text
        for verb in ("move_by", "move_to"):
            with self.subTest(verb=verb):
                t = Text("hi", center=(10, 10))
                q = Point(0, 0)
                q @= t.center
                float(q.x)
                if verb == "move_by":
                    t.move_by(5, 7)
                else:
                    t.move_to(50, 60)
                self.assertEqual((float(q.x), float(q.y)), (float(t.center.x), float(t.center.y)))


# ---------------------------------------------------------------------------
# Engine readers stay cold, statically (graphics review R6)
# ---------------------------------------------------------------------------

# Per-frame engine readers (pointer hit test, collapse check) must read
# Defining inputs (``_segment_xy``, ``_center_xy``, ``_radius_value``,
# closed-form vertices). A plain ``self.<derivate>`` here materializes the
# Derivate and drops the shape off the pose fast path for good.
_COLD_METHODS = re.compile(r"^(_hit_test\w*|is_collapsed)$")
# ``_update_impl_*`` are not listed: they guard each Derivate write with
# ``_is_derivate_live()`` (a static read is not a warm-up there), and they run
# only on a shape that is already pulled. The run-time reader matrix
# (``test_diff_pose.TestEngineReadersStayCold``) judges what reaches them.


def _derivate_names_by_class():
    """class name -> fields that are a Derivate in at least one model (from KINDS)."""
    import warnings
    import geometry_support as G
    out = {}
    for kind in G.KINDS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            obj = G.build(kind)
        if not hasattr(obj, "_field_slots"):
            continue
        names = out.setdefault(type(obj).__name__, set())
        for name, slot in obj._field_slots().items():
            if obj._field_is_derivate(name, slot):
                names.add(name)
        if type(obj).__name__ == "RegularPolygon":
            names.add("points")         # lazy: builds a Point per vertex
    return out


def cold_reader_violations() -> dict:
    derived = _derivate_names_by_class()
    # A subclass inherits its parents' rule (EquilateralTriangle reads like RegularPolygon).
    import scena
    out = {}
    for fname, qual, fn in _functions():
        if fname != "shapes.py" or "." not in qual:
            continue
        cls_name, meth = qual.split(".")[0], qual.split(".")[-1]
        if not _COLD_METHODS.match(meth):
            continue
        cls = getattr(scena, cls_name, None)
        names = set()
        for c in (cls.__mro__ if isinstance(cls, type) else ()):
            names |= derived.get(c.__name__, set())
        for sub, ns in derived.items():
            sc = getattr(scena, sub, None)
            if isinstance(sc, type) and isinstance(cls, type) and issubclass(sc, cls):
                names |= ns
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self" and node.attr in names):
                out[f"{qual} | self.{node.attr}"] = f"shapes.py:{node.lineno}"
    return out


class TestEngineReadersReadDefiningInputs(unittest.TestCase):
    def test_no_public_derivate_in_a_cold_method(self):
        from graphics_known import shrink_only
        shrink_only(self, cold_reader_violations(), "COLD_READS")


# ---------------------------------------------------------------------------
# Deadlines on summed time go through ``process.reached`` (PM8, graphics PB3)
# ---------------------------------------------------------------------------

def _names_in(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr


def truncated_time_sites() -> dict:
    """``int(t * fps)`` / ``math.floor(t * fps)``: a frame count from summed
    time. Summed ``1/60`` steps land a hair under a whole frame, so the count
    is one short on the frame it is due (PM8). Compare through ``reached``."""
    out = {}
    for fname, qual, fn in _functions():
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.BinOp)
                    and isinstance(node.args[0].op, ast.Mult)):
                continue
            callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if callee not in ("int", "floor"):
                continue
            if any("fps" in n.lower() for n in _names_in(node.args[0])):
                out[f"{fname}:{qual}"] = f"line {node.lineno}"
    return out


class TestFrameCountsGoThroughReached(unittest.TestCase):
    def test_no_frame_count_truncates_summed_time(self):
        from graphics_known import shrink_only
        shrink_only(self, truncated_time_sites(), "TRUNCATED_TIME")


if __name__ == "__main__":
    unittest.main(verbosity=2)
