"""Holder × ender: every engine place that references an actor, after every
way the actor ends or moves.

Interaction campaign, class 2 (design/Testing Design.md, "Interaction
campaign"). ``test_sys_lifetime`` checks a destroyed ``kitchen_sink`` actor
against the census and ``zombies()``, both hand lists of registries. Here the
holders are **found**, not listed: ``scan(target)`` walks the engine's object
graph from its roots (the framework and its managers, the collision,
scheduler, bounds and event systems, the registry, the act manager, the
reactive graph, the module singletons) through attributes, containers, weak
containers, bound methods and closures, and returns every path that reaches
the target, with the kind of reference. A holder path seen on a live, fully
wired subject must be classified in ``HOLDERS`` (a new engine holder fails the
guard until it has a row), and after an ender the scan is the verdict:

* **gone** enders (destroy, destroy after the seal, destroy inside an act,
  act change, hard clear, layer delete, group destroy, an Endless recycle,
  a destroyed widget that had focus / a click / an open menu) — no path may
  reach the subject (``KEEPS``: contracts that keep one, with the reason);
* **partial** enders (park, hide, undraw, collidable off, untag) — each holder
  either keeps or drops the subject per the documented contract (``EXPECT``);
  a holder with no documented rule is an ``UNSETTLED`` cell (shrink-only: a
  settled one must leave the list).

The subject is ``system_support.kitchen_sink`` plus the pointer (hover and a
drag in progress), a resting contact on a static floor with ``resolve``, a
group-operator pair side, and, in act cells, an object-literal pair handler
and widgets with focus, a click and an open menu.

    python -m unittest tests.test_sys_holders -v
"""
from __future__ import annotations

import builtins
import functools
import os
import re
import sys
import types
import unittest
import weakref
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_catches  # noqa: E402
from hypothesis_support import registry  # noqa: E402
from system_support import SystemWorld, kitchen_sink, quiet, system_world  # noqa: E402

import scena  # noqa: E402
import scena.act as _act  # noqa: E402
import scena.cover as _cover  # noqa: E402
import scena.events as _events  # noqa: E402
import scena.history as _history  # noqa: E402
import scena.hitbox as _hitbox  # noqa: E402
import scena.spatial_fx as _spatial_fx  # noqa: E402
import scena.transients as _transients  # noqa: E402
from scena._weakset import OrderedWeakSet  # noqa: E402  (walked like a WeakSet)
from scena import (STATIC, Act, Button, Circle, Menu, Rect, TextInput, canvas, change_act,  # noqa: E402
                   collide, group, resolve, st)
from scena.bounds import get_bounds_system  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.entity import Entity  # noqa: E402
from scena.input import Mouse  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import get_scheduler  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

N_AFTER = 4          # frames stepped after the ender before the scan


# --------------------------------------------------------------------------
# The scanner
# --------------------------------------------------------------------------

_ATOMS = (str, bytes, int, float, complex, bool, type(None), type, types.ModuleType,
          types.CodeType, types.FrameType, range, slice)
_SKIP_MODULES = ("skia", "numpy", "glfw", "OpenGL", "miniaudio", "typing", "enum")


def roots() -> Dict[str, Any]:
    fw = ScenaFramework.get_instance()
    out: Dict[str, Any] = {
        "fw": fw, "canvas": ScenaCanvas.get_current(), "collision": get_collision_system(),
        "sched": get_scheduler(), "bounds": get_bounds_system(),
        "events": _events._global_event_system, "registry": registry(),
        "act": _act._manager, "transients": _transients._active_shapes,
        "spatial": _spatial_fx._active_fx, "histories": _history._active_histories,
        "hitbox.live": _hitbox._LIVE_PARTS, "hitbox.linked": _hitbox._LINKED_PARTS,
        "cover": _cover._cover, "ui": scena.ui,
    }
    ss = get_scena_system()
    if ss is not None:
        out["graph"] = ss.dependency_graph
    for name in ("ready", "recently"):
        mgr = getattr(builtins, name, None)
        if mgr is not None:
            out[name] = mgr
    return out


def _skip(obj) -> bool:
    if isinstance(obj, _ATOMS):
        return True
    mod = type(obj).__module__ or ""
    return mod.split(".")[0] in _SKIP_MODULES


def _children(obj) -> Iterable[Tuple[str, Any, str]]:
    """(edge, child, kind) for every reference ``obj`` holds."""
    if isinstance(obj, weakref.ref):
        child = obj()
        if child is not None:
            yield "()", child, "weak"
        return
    if isinstance(obj, (weakref.WeakSet, OrderedWeakSet)):
        for c in list(obj):
            yield "[*]", c, "weak"
        return
    if isinstance(obj, weakref.WeakKeyDictionary):
        for k, v in list(obj.items()):
            yield "{*}", k, "weak"
            yield "[*]", v, "strong"
        return
    if isinstance(obj, weakref.WeakValueDictionary):
        for k, v in list(obj.items()):
            yield "[*]", v, "weak"
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if not isinstance(k, _ATOMS):
                yield "{*}", k, "strong"
            yield f"[{k!r}]" if isinstance(k, str) else "[*]", v, "strong"
        return
    if isinstance(obj, (list, tuple, set, frozenset, deque)):
        for c in list(obj):
            yield "[*]", c, "strong"
        return
    if isinstance(obj, types.MethodType):
        yield ".__self__", obj.__self__, "strong"
        return
    if isinstance(obj, functools.partial):
        yield ".func", obj.func, "strong"
        for c in obj.args:
            yield ".args[*]", c, "strong"
        for c in obj.keywords.values():
            yield ".keywords[*]", c, "strong"
        return
    if isinstance(obj, types.FunctionType):
        for cell in obj.__closure__ or ():
            try:
                yield ".<closure>", cell.cell_contents, "strong"
            except ValueError:
                pass
        for c in obj.__defaults__ or ():
            yield ".<default>", c, "strong"
        return
    if isinstance(obj, property):
        return
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        for k, v in list(d.items()):
            if not k.startswith("__"):
                yield f".{k}", v, "strong"
    for cls in type(obj).__mro__:
        for name in getattr(cls, "__slots__", ()) or ():
            if name in ("__dict__", "__weakref__"):
                continue
            try:
                v = getattr(obj, name)
            except AttributeError:
                continue
            yield f".{name}", v, "strong"


def scan(target, *, depth: int = 9) -> Dict[str, str]:
    """Every path from an engine root to ``target``: ``{path: kind}``.

    ``kind`` is ``weak`` when the last weak edge on the path is what reaches
    the target (a WeakSet entry, a weakref), else ``strong``.
    """
    found: Dict[str, str] = {}
    seen = {id(target)}
    frontier: deque = deque()
    for name, root in roots().items():
        if root is None:
            continue
        frontier.append((root, name, "strong", 0))
        seen.add(id(root))
    while frontier:
        obj, path, kind, d = frontier.popleft()
        if d >= depth:
            continue
        for edge, child, ekind in _children(obj):
            cpath = path + edge
            ckind = "weak" if ekind == "weak" else kind
            if child is target:
                found[cpath] = min(found.get(cpath, ckind), ckind, key=lambda k: k == "weak")
                continue
            if id(child) in seen or _skip(child):
                continue
            seen.add(id(child))
            frontier.append((child, cpath, ckind, d + 1))
    return found


def generalize(path: str) -> str:
    """One pattern per holder: indices and ids collapse, names stay."""
    return re.sub(r"\[\d+\]", "[*]", path)


# --------------------------------------------------------------------------
# Holder classification (the guard: a new path needs a row here)
# --------------------------------------------------------------------------

# pattern (fnmatch over the generalized path) -> what it is
HOLDERS: Dict[str, str] = {
    "registry.live[*]": "the roster",
    "registry.live[*]._owner": "a part's owner (the subject reached through its own part)",
    "registry.live[*]._ownership_root_cache": "a part's cached ownership root",
    "registry.live[*]._touching_contacts[*].other": "a survivor's touching contact",
    "registry.live[*].*": "reached through another live object",
    "registry.layers.*": "a layer's draw list / interactive list",
    "registry.group_map[*]*": "group membership (weak)",
    "canvas.*registry*": "the registry through the engine canvas",
    "fw.*registry*": "the registry through the framework",
    "collision.*": "the collision system: colliders, tag maps, pair handlers, resolve pairs, caches",
    "sched.*": "the scheduler: handles by owner, dense lists, scripts",
    "bounds.*": "the bounds system: instance handlers, seen-inside",
    "events.*": "method @when registrations and their closures",
    "graph.*": "the reactive graph: nodes, links, parts' owners",
    "transients[*]": "shapes with a running transient (weak)",
    "spatial[*]": "SpatialFx hosts (weak)",
    "hitbox.*": "hitbox parts (weak host)",
    "act.*": "the act manager: current act, game entities, sealed resolve pairs",
    "fw.shape_manager.*": "pointer: hover target, pressed shape, drag",
    "fw.widget_manager.*": "widgets: list, focus, press, hover, modal, menus, last click",
    "fw.canvas_manager.*": "script-level callbacks",
    "fw.background_stack.*": "background fields",
    "fw.post_fx_stack.*": "post effects",
    "fw.*": "another framework attribute",
    "canvas.*": "another engine-canvas attribute",
    "ready.*": "ready slots", "recently.*": "recently slots",
    "histories[*]*": "History / Contrail registry",
    "cover.*": "the cover", "ui.*": "widget chrome",
}

# Paths a gone ender may keep, with the contract (shrink-only).
KEEPS: Dict[Tuple[str, str], str] = {
}

# Partial enders: holder pattern -> "keep" / "drop" (documented), per ender.
# Unlisted (ender, holder) pairs must be in UNSETTLED.
# Pair declarations (@collide / @collide_with / resolve / a group-operator side)
# are reactions on the actor: they survive park and collidable = False and work
# again on the rejoin (Actors Design, park: "collision state belongs to the
# actor, not to its Collider"); the Collider itself and the survivor's contact
# go. A parked or hidden shape stays in its layer's draw list (walks read the
# drawn flag) and leaves the pointer lists.
_LEAVES_COLLISION = {
    "collision._pair_handlers*": "keep",
    "collision._act_pair_handlers*": "keep",
    "collision._resolve_pairs*": "keep",
    "collision._colliders[*]._pair_targets[*]": "keep",
    "collision.*": "drop",
    "registry.live[*]._touching_contacts[*].other": "drop",
}
EXPECT: Dict[str, Dict[str, str]] = {
    "park": {
        **_LEAVES_COLLISION,
        "registry.layers._layers[*]._objects[*]": "keep",
        "registry.layers._layers[*]._interactive[*]": "drop",
        "fw.shape_manager.*": "drop",     # cannot be dragged / hovered
        "*": "keep",                      # owned work paused, @when and transients run
    },
    "hide": {
        "registry.layers._layers[*]._objects[*]": "keep",
        "registry.layers._layers[*]._interactive[*]": "drop",
        "fw.shape_manager.*": "drop",     # a hidden shape is no pointer target (PH1)
        "*": "keep",
    },
    "undraw": {
        "registry.layers.*": "drop",
        "*": "keep",
    },
    "collidable_off": {
        **_LEAVES_COLLISION,
        "*": "keep",
    },
    "untag": {
        "registry.group_map[*]*": "drop",
        "*": "keep",
    },
}

# Shrink-only: "ender | holder pattern" cells with no settled contract yet, or
# known findings ("ender | pattern" -> reason).
UNSETTLED: Dict[str, str] = {
}
KNOWN: Dict[str, str] = {
}


def match(pat: str, path: str) -> bool:
    """``*`` matches anything; every other character is literal (``[`` too)."""
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pat)
    return re.fullmatch(rx, path) is not None


def classify(path: str) -> Optional[str]:
    g = generalize(path)
    for pat in HOLDERS:
        if match(pat, g):
            return pat
    return None


def expect_for(ender: str, path: str) -> Optional[str]:
    g = generalize(path)
    table = EXPECT.get(ender, {})
    for pat, rule in table.items():
        if pat != "*" and match(pat, g):
            return rule
    return table.get("*")


# --------------------------------------------------------------------------
# Subjects and wirings
# --------------------------------------------------------------------------

class Wired:
    """A fully wired subject in ``w``: kitchen sink + pointer + contact + group side."""

    def __init__(self, w: SystemWorld, *, layer=None, pointer: bool = True,
                 contact: bool = True) -> None:
        self.w = w
        fw = w.fw
        self.sink = kitchen_sink(w, center=(100.0, 100.0), layer=layer)
        self.actor = a = self.sink.actor
        self.floor = None
        if contact:
            with quiet():
                self.floor = w.track(Rect(center=(100.0, 100.0 - 6 - 10), width=80,
                                          height=20, group="chao"))
            self.floor.mass = STATIC
            resolve(a, self.floor, bounce=0.0)
            self.other = w.track(Circle(center=(400.0, 100.0), radius=4, group="outro"))

            @collide(group["sink"] | group["outro"], "rock")
            def _side(x, y, info=None):
                pass
        self.sm = fw.shape_manager
        if pointer:
            a.clickable = True
            a.draggable = True
            self.sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(100.0, 100.0))
        w.step(2)
        if pointer:
            self.sm.handle_mouse_down(100.0, 100.0, Mouse.BTN_LEFT)
            self.sm.handle_mouse_move(106.0, 100.0)
            w.step(1)

    def release_pointer(self) -> None:
        with quiet():
            try:
                self.sm.handle_mouse_up(106.0, 100.0, Mouse.BTN_LEFT)
            except Exception:
                pass
            self.sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(-1e6, -1e6))


def _live_paths(target) -> Dict[str, str]:
    return scan(target)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def _report(paths: Dict[str, str]) -> str:
    return "\n".join(f"    {k}  ({v})" for k, v in sorted(paths.items())) or "    (none)"


class HolderCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        # A menu a failed cell left open would refuse the next cell's focus.
        self._close_menus(None)

    @staticmethod
    def _close_menus(w) -> None:
        wm = ScenaFramework.get_instance().widget_manager
        with quiet():
            for m in (wm._open_modal_menu, wm._open_nonmodal_menu):
                if m is not None and getattr(m, "is_alive", False):
                    try:
                        m.destroy()
                    except Exception:
                        pass
            wm._open_modal_menu = wm._open_nonmodal_menu = None
            wm.focused_widget = None

    def check_classified(self, paths: Dict[str, str]) -> None:
        new = sorted({generalize(p) for p in paths if classify(p) is None})
        self.assertFalse(new, "holders with no row in HOLDERS (classify them):\n"
                         + "\n".join(f"    {p}" for p in new))

    def check_gone(self, ender: str, target, label: str = "subject") -> None:
        left = scan(target)
        kept = {}
        for p, kind in left.items():
            g = generalize(p)
            why = KEEPS.get((ender, g))
            # A weak entry (a WeakSet, a weakref) goes with the object itself;
            # assert_collected (test_sys_lifetime) is the check for that side.
            if why is None and kind == "strong":
                kept[p] = kind
        key = f"{ender} | {label}"
        if kept:
            if key in KNOWN:
                self.skipTest(f"known: {KNOWN[key]}")
            self.fail(f"{key}: the engine still reaches the {label} after {ender}:\n"
                      + _report(kept))
        elif key in KNOWN:
            self.fail(f"KNOWN entry no longer fails; remove it: {key!r}")

    def check_partial(self, ender: str, before: Dict[str, str], target) -> None:
        after = scan(target)
        holders = {generalize(p) for p in before} | {generalize(p) for p in after}
        wrong, unsettled = [], []
        for g in sorted(holders):
            rule = expect_for(ender, g)
            held = any(generalize(p) == g for p in after)
            if rule is None:
                unsettled.append(g)
            elif (rule == "keep") != held:
                wrong.append(f"{g}: want {rule}, {'kept' if held else 'dropped'}")
        new_unsettled = [g for g in unsettled if f"{ender} | {g}" not in UNSETTLED]
        stale = [k for k in UNSETTLED if k.startswith(ender + " | ")
                 and k.split(" | ", 1)[1] not in unsettled]
        msgs = []
        if wrong:
            msgs.append("contract violations:\n" + "\n".join(f"    {m}" for m in wrong))
        if new_unsettled:
            msgs.append("holders with no documented rule for this ender (settle in the "
                        "owning design doc, then EXPECT; or list in UNSETTLED):\n"
                        + "\n".join(f"    {ender} | {g}" for g in new_unsettled))
        if stale:
            msgs.append(f"UNSETTLED entries now settled or gone; remove them: {stale}")
        if msgs:
            self.fail(f"{ender}:\n" + "\n".join(msgs))


class TestGoneEnders(HolderCase):
    """After an ender that ends the subject, no engine path reaches it."""

    def _with_world(self, fn):
        with system_world() as w:
            fn(w)

    def test_destroy(self):
        def body(w):
            s = Wired(w)
            live = scan(s.actor)
            self.check_classified(live)
            self.assertTrue(live, "the wired subject is held by nothing: the wiring is broken")
            ref = weakref.ref(s.actor)
            w.on_update(lambda dt: ref().destroy() if ref() is not None and ref().is_alive else None)
            w.step(N_AFTER)
            w.on_update(None)          # the test's own closure is not an engine holder
            s.release_pointer()
            w.step(1)
            self.check_gone("destroy", s.actor)
        self._with_world(body)

    def test_destroy_keeps_the_pointer_released(self):
        """A destroyed shape under a pressed pointer leaves no press or hold."""
        def body(w):
            s = Wired(w)
            s.actor.destroy()
            w.step(N_AFTER)
            self.check_gone("destroy (pointer still down)", s.actor)
        self._with_world(body)

    def test_destroy_after_the_seal(self):
        """A game-level subject with a top-level resolve pair, destroyed after
        ``run()`` sealed the game (``ActManager._game_resolve_pairs``)."""
        def body(w):
            s = Wired(w)

            class Vazia(Act):
                pass
            w.begin_game(Vazia)
            w.step(2)
            s.actor.destroy()
            w.step(N_AFTER)
            s.release_pointer()
            w.step(1)
            self.check_gone("destroy after the seal", s.actor)
        self._with_world(body)

    def test_destroy_inside_an_act(self):
        """An act-made subject with an object-literal pair handler, destroyed
        while its act runs (``CollisionSystem._act_pair_handlers``)."""
        def body(w):
            box = {}

            class Fase(Act):
                def setup(self):
                    box["s"] = s = Wired(w)

                    @collide(s.actor, s.sink.partner)
                    def _lit(a, b, info=None):
                        pass
            w.begin_game(Fase)
            w.step(2)
            s = box["s"]
            s.actor.destroy()
            w.step(N_AFTER)
            s.release_pointer()
            w.step(1)
            self.check_gone("destroy inside an act", s.actor)
        self._with_world(body)

    def test_act_change(self):
        """Everything an act made, pointer, focus, click and menu included."""
        def body(w):
            box = {}

            class Fase(Act):
                def setup(self):
                    box["s"] = s = Wired(w)

                    @collide(s.actor, s.sink.partner)
                    def _lit(a, b, info=None):
                        pass
                    st.nome = ""
                    box["ti"] = TextInput(st["nome"], top_left=(10, 290), width=100)
                    box["bt"] = Button(label="Vai", on_click=lambda: None)

            class Vazia(Act):
                pass
            w.begin_game(Fase)
            w.step(1)
            wm = w.fw.widget_manager
            box["ti"].focus()
            bt = box["bt"]
            cx, cy = (bt._x1 + bt._x2) / 2.0, (bt._y1 + bt._y2) / 2.0
            wm.handle_mouse_down(cx, cy, Mouse.BTN_LEFT)
            wm.handle_mouse_up(cx, cy, Mouse.BTN_LEFT)
            # Made after the seal, inside the act: the act's own (a modal menu
            # refuses focus changes, so it opens last).
            box["menu"] = Menu(options=["um", "dois"], on_choose=lambda v: None)
            w.step(1)
            s = box["s"]
            try:
                change_act(Vazia)
                w.step(N_AFTER)
                s.release_pointer()
                w.step(1)
                for label in ("s", "ti", "bt", "menu"):
                    target = box[label].actor if label == "s" else box[label]
                    with self.subTest(target=label):
                        self.check_gone("act change", target, label)
            finally:
                self._close_menus(w)
        self._with_world(body)

    def test_hard_clear(self):
        def body(w):
            s = Wired(w)
            canvas.layers[s.actor.layer].clear(hard=True)
            w.step(N_AFTER)
            s.release_pointer()
            w.step(1)
            self.check_gone("hard clear", s.actor)
        self._with_world(body)

    def test_layer_delete(self):
        def body(w):
            canvas.layers.create("ilha", below="default")
            try:
                s = Wired(w, layer="ilha")
                canvas.layers["ilha"].delete(destroy_shapes=True)
                w.step(N_AFTER)
                s.release_pointer()
                w.step(1)
                self.check_gone("layer delete", s.actor)
            finally:
                if "ilha" in canvas.layers:
                    with quiet():
                        canvas.layers["ilha"].delete(destroy_shapes=True)
        self._with_world(body)

    def test_group_destroy(self):
        def body(w):
            s = Wired(w)
            group["sink"].destroy()
            w.step(N_AFTER)
            s.release_pointer()
            w.step(1)
            self.check_gone("group destroy", s.actor)
        self._with_world(body)

    def test_widget_destroyed_with_focus_click_and_menu(self):
        def body(w):
            st.nome2 = ""
            ti = w.track(TextInput(st["nome2"], top_left=(10, 290), width=100))
            bt = w.track(Button(label="Vai2", on_click=lambda: None))
            w.step(1)
            wm = w.fw.widget_manager
            ti.focus()
            cx, cy = (bt._x1 + bt._x2) / 2.0, (bt._y1 + bt._y2) / 2.0
            wm.handle_mouse_down(cx, cy, Mouse.BTN_LEFT)
            wm.handle_mouse_up(cx, cy, Mouse.BTN_LEFT)
            menu = w.track(Menu(options=["um", "dois"], on_choose=lambda v: None))
            w.step(1)
            try:
                for label, wd in (("focused TextInput", ti), ("clicked Button", bt),
                                  ("open Menu", menu)):
                    wd.destroy()
                    w.step(N_AFTER)
                    with self.subTest(target=label):
                        self.check_gone("widget destroy", wd, label)
            finally:
                self._close_menus(w)
        self._with_world(body)

    def test_endless_recycle(self):
        def body(w):
            canvas.reset_view()
            canvas.layers.create("pista", below="default")
            first: List[Any] = []

            def piece(slot):
                r = Rect(top_left=(slot.left, 20), width=slot.right - slot.left, height=20)
                if not first:
                    first.append(weakref.ref(r))     # the test holds no strong reference
                return r
            e = None
            try:
                e = Endless("pista", piece, step=100)
                w.step(1)
                p = first[0]()
                self.assertTrue(p.is_alive)
                canvas.pan_to(canvas.pan_x + 5000, canvas.pan_y)
                w.step(N_AFTER)
                self.assertFalse(p.is_alive, "the first piece was not recycled")
                self.check_gone("Endless recycle", p, "piece")
            finally:
                if e is not None and e.is_alive:
                    e.destroy()
                with quiet():
                    canvas.layers["pista"].delete(destroy_shapes=True)
                canvas.reset_view()
        self._with_world(body)

    def test_destroy_on_the_ui_layer_and_a_hidden_layer(self):
        """Census and zombies skip hidden and ``ui`` layers; the scan does not."""
        def body(w):
            canvas.layers.create("escondida", below="default", visible=False)
            try:
                for layer in ("ui", "escondida"):
                    with quiet():
                        c = w.track(Circle(center=(50, 50), radius=5, layer=layer))
                    c.after(1e6, lambda: None)
                    src = w.track(Entity())
                    src.v = 1.0
                    c.r2 = 0.0
                    c["r2"] @= (lambda: src.v * 2)
                    w.step(1)
                    self.assertTrue(scan(c), f"a shape on {layer!r} is held by nothing")
                    c.destroy()
                    w.step(N_AFTER)
                    with self.subTest(layer=layer):
                        self.check_gone("destroy", c, f"shape on {layer!r}")
            finally:
                with quiet():
                    canvas.layers["escondida"].delete(destroy_shapes=True)
        self._with_world(body)


from scena import Endless  # noqa: E402


class TestPartialEnders(HolderCase):
    """Park, hide, undraw, collidable off, untag: each holder per contract."""

    def _cell(self, ender: str, apply: Callable[[Any], None]) -> None:
        with system_world() as w:
            s = Wired(w)
            before = scan(s.actor)
            self.check_classified(before)
            apply(s.actor)
            w.step(N_AFTER)
            try:
                self.check_partial(ender, before, s.actor)
            finally:
                s.release_pointer()

    def test_park(self):
        self._cell("park", lambda a: setattr(a, "active", False))

    def test_hide(self):
        self._cell("hide", lambda a: setattr(a, "visible", False))

    def test_undraw(self):
        self._cell("undraw", lambda a: setattr(a, "layer", None))

    def test_collidable_off(self):
        self._cell("collidable_off", lambda a: setattr(a, "collidable", False))

    def test_untag(self):
        self._cell("untag", lambda a: a.untag("sink"))


class TestScanner(unittest.TestCase):
    """The scanner reaches what it claims to (prove the oracle)."""

    def test_finds_a_shape_through_every_documented_door(self):
        with system_world() as w:
            s = Wired(w)
            paths = {generalize(p) for p in scan(s.actor)}
            for want in ("registry.live[*]", "collision.", "sched.", "events.", "graph.",
                         "fw.shape_manager.", "bounds."):
                self.assertTrue(any(p.startswith(want) for p in paths),
                                f"no path under {want!r}:\n" + "\n".join(sorted(paths)))
            s.release_pointer()

    def test_a_free_shape_is_reached_only_by_the_registry_and_the_draw_list(self):
        with system_world() as w:
            with quiet():
                c = w.track(Circle(center=(50, 50), radius=5))
            w.step(1)
            paths = {generalize(p) for p in scan(c)}
            extra = [p for p in paths if not (p.startswith("registry.") or p.startswith("canvas.")
                                              or p.startswith("fw.") or p.startswith("graph."))]
            self.assertFalse(extra, extra)

    def test_a_closure_and_a_bound_method_count(self):
        with system_world() as w:
            with quiet():
                c = w.track(Circle(center=(50, 50), radius=5))
            c.after(1e6, c.move_by)              # a bound method held by a handle
            w.step(1)
            paths = scan(c)
            self.assertTrue(any("sched." in p for p in paths), paths)


class TestALeftColliderIsLetGo(HolderCase):
    """A collider that left collision (destroy, park, ``collidable = False``)
    is never used again (a rejoin builds a new one), so after the next step
    no engine path may reach it: it still names its partners in
    ``_pair_targets`` (strong), and a holder that keeps it pins them, dead or
    alive (HW1: ``_moved_now`` kept the collider of a shapeless body — a Text,
    an Entity: no valid proxy, the step's early return — and its partner, a
    destroyed actor, was never collected). The subject is found by walking
    the engine graph (``scan``), not by a list of per-step sets."""

    @staticmethod
    def _hunter_class():
        from scena import collide_with

        class Hunter(Circle):
            @collide_with("prey")
            def hit(self, other, info=None):
                pass
        return Hunter

    def _prey(self, w, kind, xy=(50.0, 50.0)):
        from scena import Text
        with quiet():
            if kind == "text":
                return w.track(Text("w", center=xy, group="prey"))
            if kind == "entity":
                return w.track(Entity(group="prey"))
            return w.track(Rect(center=xy, width=8, height=8, group="prey"))

    def test_a_destroyed_hunter_named_by_a_shapeless_prey_is_collected(self):
        """The HW1 game: the hunter leaves collision, the prey (no geometry)
        is alone in it for some frames, then both die."""
        from system_support import assert_collected
        Hunter = self._hunter_class()
        for kind in ("text", "entity"):
            with self.subTest(prey=kind), system_world() as w:
                with quiet():
                    hunter = w.track(Hunter(center=(0.0, 0.0), radius=6))
                prey = self._prey(w, kind)
                w.step(1)
                hunter.collidable = False
                w.step(3)
                ref = weakref.ref(hunter)
                with quiet():
                    prey.destroy()
                    hunter.destroy()
                w.objects.clear()
                del hunter, prey
                w.step(2)
                assert_collected(self, ref, "a destroyed hunter")

    def test_no_engine_path_reaches_a_collider_after_it_left(self):
        Hunter = self._hunter_class()
        enders = {
            "destroy": lambda o: o.destroy(),
            "park": lambda o: setattr(o, "active", False),
            "collidable_off": lambda o: setattr(o, "collidable", False),
        }
        for kind in ("text", "entity", "rect"):
            for ender, end in enders.items():
                for alone in (True, False):
                    label = f"{ender} | {kind} prey{' alone' if alone else ''}"
                    with self.subTest(label), system_world() as w:
                        with quiet():
                            hunter = w.track(Hunter(center=(0.0, 0.0), radius=6))
                            if not alone:   # a body with a valid proxy: the full step
                                w.track(Rect(center=(-200.0, 0.0), width=8, height=8,
                                             group="prey"))
                        prey = self._prey(w, kind)
                        w.step(1)
                        hunter.collidable = False   # the prey may be alone in collision
                        w.step(2)
                        col = getattr(prey, "_collider", None)
                        self.assertIsNotNone(col, f"{label}: the prey never joined collision")
                        with quiet():
                            end(prey)
                        w.step(1)
                        left = {p: k for p, k in scan(col).items() if k == "strong"}
                        self.assertFalse(left, f"{label}: the engine still reaches the left "
                                         f"collider:\n" + _report(left))


class TestCanaries(unittest.TestCase):
    def test_catches_a_step_set_that_keeps_a_left_collider(self):
        from scena.collision import CollisionSystem
        assert_catches(self, "test_sys_holders.TestALeftColliderIsLetGo."
                       "test_no_engine_path_reaches_a_collider_after_it_left",
                       [(CollisionSystem, "_forget_step_sets", lambda self, c: None)],
                       "per-step collision sets that keep a collider that left (HW1)")

    def test_catches_a_destroy_that_skips_the_pointer(self):
        from scena.orchestration import ShapeInteractionManager
        assert_catches(self, "test_sys_holders.TestGoneEnders.test_destroy_keeps_the_pointer_released",
                       [(ShapeInteractionManager, "forget_destroyed", lambda self, obj: None)],
                       "a pointer manager that keeps a destroyed pressed shape")

    def test_catches_a_pair_list_that_keeps_a_dead_side(self):
        from scena.collision import CollisionSystem
        assert_catches(self, "test_sys_holders.TestGoneEnders.test_destroy",
                       [(CollisionSystem, "drop_pair_handlers_for", lambda self, identity: None)],
                       "pair handlers that keep a destroyed side (HD1)")


if __name__ == "__main__":
    unittest.main()
