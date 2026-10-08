"""Shared helpers for the signature-driven API fuzzer (``tests/test_hyp_surface.py``).

Not a test module. Walks ``scena.__all__`` and gives every export a family,
a way to construct / remove it, and a census of every registry a public call
can touch. See ``design/Testing Design.md`` — Strategy.

* ``FAMILIES`` / ``family_of(name)`` — runtime classification of the exports.
* ``EXCLUDED`` — exports the fuzzer does not call, each with the reason. The
  coverage guard (``test_every_export_is_fuzzed_or_excluded``) fails on a new
  export that is neither fuzzed nor listed here.
* ``ctor_params(cls)`` — author keywords of a constructor (engine keys, private
  names, ``*args`` / ``**kwargs`` dropped).
* ``surface_census()`` — ``system_support.census()`` plus the post stack,
  background stack, widgets, hitbox parts, cover, capture devices, and the
  last author error.
* ``remove(obj)`` — undo a construction (``destroy`` / ``remove``).
"""
from __future__ import annotations

import enum
import gc
import inspect
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot, quiet  # noqa: E402
from system_support import census  # noqa: E402

import scena  # noqa: E402

ENGINE_KEYS = frozenset({"attr_name", "owner", "register", "self", "cls"})

# name -> reason. Keep reasons short; they are printed by the coverage guard.
EXCLUDED: Dict[str, str] = {
    "run": "opens a window and blocks",
    "init": "changes the design size for the whole process",
    "Microphone": "opens the OS input device (fuzz with a NULL backend later)",
    "Handle": "engine-built (after / every / tween return it); not author-constructed",
    "Shape": "abstract base; its kinds are fuzzed",
    "SpatialFx": "abstract base; its kinds are fuzzed",
    "Visual": "abstract base; its looks are fuzzed",
    "Hitbox": "engine-built by sprite.add_hitbox(); direct construction raises by design",
    "Act": "base class; acts are entered with change_act / run(Titulo), never "
             "constructed (Act() raises by design); its verbs are Entity's, "
             "act-only refusals are covered in test_act",
    "ColorNames": "namespace of colour name constants; not constructed",
    "flush": "no parameters (nothing to fuzz)",
}


def _bases():
    from scena.postfx import PostEffect
    from scena.background import BackgroundField
    from scena.spatial_fx import SpatialFx
    from scena.audio_effects import AudioEffect
    from scena.uiwidget import UIWidget
    from scena.visuals import Visual
    from scena.filters import FilterEffect
    from scena.entity import Entity
    return (
        (BaseException, "error"), (enum.Enum, "enum"), (PostEffect, "post"),
        (BackgroundField, "background"), (SpatialFx, "spatialfx"),
        (AudioEffect, "audiofx"), (UIWidget, "widget"), (Visual, "visual"),
        (FilterEffect, "filter"), (Entity, "entity"),
    )


def family_of(name: str) -> str:
    obj = getattr(scena, name)
    if isinstance(obj, type):
        for base, label in _bases():
            if issubclass(obj, base):
                return label
        return "class"
    return "callable" if callable(obj) else "value"


def families() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name in scena.__all__:
        out.setdefault(family_of(name), []).append(name)
    return out


CONSTRUCTIBLE = ("post", "background", "spatialfx", "audiofx", "widget", "visual",
                 "filter", "entity", "class")


def constructor_names() -> List[str]:
    return sorted(n for n in scena.__all__
                  if family_of(n) in CONSTRUCTIBLE and n not in EXCLUDED)


def ctor_params(cls) -> List[Tuple[str, Any]]:
    """``(name, default)`` of the author keywords of ``cls(...)``."""
    try:
        sig = inspect.signature(cls)
    except (TypeError, ValueError):
        return []
    out = []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name in ENGINE_KEYS or p.name.startswith("_"):
            continue
        out.append((p.name, p.default))
    return out


# A usable instance for classes with no no-argument form, so the methods
# phase still fuzzes them (Color was missed until A9). name -> factory.
def _representatives():
    return {
        "Box": lambda: scena.Box(center=(0, 0), width=40, height=20),
        "Color": lambda: scena.Color("red"),
        "Colormap": lambda: scena.Colormap([(0, "navy"), (1, "gold")]),
        "ComposeFx": lambda: scena.ComposeFx(scena.Blur(1), scena.Blur(2)),
        "Grid": lambda: scena.Grid(scena.Box(center=(0, 0), width=40, height=20), 2, 2),
        "Menu": lambda: scena.Menu(options=["a", "b"]),
        "Level": lambda: scena.Level(sample_level_path()),
        "Endless": _sample_endless,
    }


def _sample_endless():
    """An ``Endless`` on a layer of its own (the reserved layers raise by design)."""
    if "fuzz_pista" not in scena.canvas.layers:
        scena.canvas.layers.create("fuzz_pista", below="default")
    return scena.Endless("fuzz_pista", lambda slot: [], step=100)


_SAMPLE_LEVEL = {}


def sample_level_path() -> str:
    """A small level file (one item of each kind) in a temp folder, made once."""
    if "path" not in _SAMPLE_LEVEL:
        import json
        import tempfile
        folder = tempfile.mkdtemp(prefix="scena_level_")
        doc = {"format": "scena-level", "version": 1, "size": [800, 600], "items": [
            {"kind": "rect", "name": "chao", "groups": ["plataforma"],
             "center": [400, 20], "width": 800, "height": 40},
            {"kind": "ellipse", "center": [100, 100], "width": 60, "height": 30, "angle": 15},
            {"kind": "circle", "center": [200, 200], "radius": 12},
            {"kind": "line", "p1": [0, 0], "p2": [50, 50]},
            {"kind": "polygon", "points": [[0, 0], [40, 0], [20, 30]]},
            {"kind": "track", "name": "rota", "points": [[10, 300], [700, 300]]},
            {"kind": "point", "name": "inicio", "groups": ["spawn"], "center": [60, 80]},
            {"kind": "image", "file": "missing.png", "center": [400, 300],
             "width": 80, "height": 80},
        ]}
        path = os.path.join(folder, "sample_level.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        _SAMPLE_LEVEL["path"] = path
    return _SAMPLE_LEVEL["path"]


REPRESENTATIVES = _representatives()
# Engine-built values: the author reads them, never calls their methods with
# author data.
ENGINE_BUILT = {"CollisionInfo", "TouchingContact"}


def make_instance(name: str):
    """A fresh instance of ``scena.<name>`` for the methods phase."""
    factory = REPRESENTATIVES.get(name)
    return factory() if factory is not None else getattr(scena, name)()


# --------------------------------------------------------------------------
# Global setters: snapshot / restore
# --------------------------------------------------------------------------

# Exports that change process-wide state. The fuzzer calls them inside
# ``global_snapshot()`` / ``global_restore()`` so a call cannot leak into the
# next test, and checks that a REJECTED call changed nothing.
GLOBAL_SETTERS = frozenset({
    "set_fx_auto", "set_watchdog", "set_defaults",
    "show_tracks", "set_extrude_focus",
})

_FW_ATTRS = (
    "_fx_auto", "_fx_auto_ctrl", "_fx_auto_applying", "_monitor_refresh_hz",
    "_framerate", "_fx_quality",
    "post_fx_scale", "shape_fx_scale", "batch_shared_filters", "_render_profile_index",
)
_CANVAS_ATTRS = ("batch_shared_filters", "shape_fx_scale")
_MODULE_GLOBALS = (
    ("scena.fx_quality", ("_active_quality", "_tier", "_hero_lod", "_particle",
                          "_outer_glow_scale_cap")),
    ("scena.process", ("WATCHDOG_ENABLED",)),
    ("scena.track", ("_show_tracks",)),
    ("scena.recipes", ("_EXTRUDE_FOCUS",)),
)
_MISSING = object()


def _draw_target(fw):
    return fw._canvas if getattr(fw, "_canvas", None) is not None else getattr(fw, "_scena_draw", None)


def global_snapshot() -> Dict[Tuple[str, str], Any]:
    """Every piece of process-wide state a global setter may write."""
    import importlib
    from scena.style import PaintState
    fw = _fw()
    out: Dict[Tuple[str, str], Any] = {}
    for a in _FW_ATTRS:
        out[("fw", a)] = getattr(fw, a, _MISSING)
    target = _draw_target(fw)
    for a in _CANVAS_ATTRS:
        out[("draw", a)] = getattr(target, a, _MISSING) if target is not None else _MISSING
    for mod, names in _MODULE_GLOBALS:
        m = importlib.import_module(mod)
        for n in names:
            out[(mod, n)] = getattr(m, n, _MISSING)
    out[("PaintState", "_default_instance")] = PaintState._default_instance
    return out


def global_restore(snap: Dict[Tuple[str, str], Any]) -> None:
    import importlib
    from scena.style import PaintState
    fw = _fw()
    target = _draw_target(fw)
    for (where, name), value in snap.items():
        if value is _MISSING:
            continue
        if where == "fw":
            setattr(fw, name, value)
        elif where == "draw":
            if target is not None:
                setattr(target, name, value)
        elif where == "PaintState":
            PaintState._default_instance = value
        else:
            setattr(importlib.import_module(where), name, value)
    refresh = getattr(fw, "_refresh_fidelity_sensitive_visuals", None)
    if callable(refresh):
        with quiet():
            refresh()


def global_diff(before, after) -> Dict[Tuple[str, str], Tuple[Any, Any]]:
    return {k: (before.get(k), after.get(k)) for k in set(before) | set(after)
            if before.get(k) is not after.get(k) and before.get(k) != after.get(k)}


def required_params(cls) -> List[str]:
    return [n for n, d in ctor_params(cls) if d is inspect.Parameter.empty]


# --------------------------------------------------------------------------
# Census and removal
# --------------------------------------------------------------------------

def _fw():
    from scena.orchestration import ScenaFramework
    return ScenaFramework.get_instance()


def surface_census(*, collect: bool = True) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(census(collect=collect))
    fw = _fw()
    try:
        out["post.effects"] = len(list(scena.canvas.effects))
    except Exception:
        out["post.effects"] = -1
    bs = getattr(fw, "background_stack", None)
    if bs is not None:
        out["background.items"] = len(getattr(bs, "_items", ()) or ())
        # By kind, not identity: removing a base installs a fresh default of
        # the same kind.
        out["background.base"] = type(getattr(bs, "_base", None)).__name__
    wm = getattr(fw, "widget_manager", None)
    if wm is not None:
        for attr in ("_stack_x", "_stack_bottom", "_column_top"):
            if hasattr(wm, attr):
                v = getattr(wm, attr)
                out["widgets." + attr] = v if isinstance(v, (int, float, type(None))) else repr(v)
    try:
        from scena import hitbox as _hb
        out["hitbox.live_parts"] = len(_hb._LIVE_PARTS)
        out["hitbox.linked_parts"] = len(_hb._LINKED_PARTS)
    except Exception:
        pass
    try:
        from scena import cover as _cv
        out["cover.active"] = _cv._cover is not None
    except Exception:
        pass
    try:
        from scena.audio_capture import capture_devices_open
        out["capture.open"] = capture_devices_open()
    except Exception:
        pass
    return out


def census_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    keys = set(before) | set(after)
    return {k: (before.get(k), after.get(k)) for k in sorted(keys)
            if before.get(k) != after.get(k)}


def remove(obj) -> None:
    """Undo a construction: ``destroy()`` an Entity, ``remove()`` a post / background."""
    with quiet():
        if getattr(obj, "_place", None) == "base":
            # The base background cannot be removed (raises by design); the
            # undo is reset_base() (Effect Handles).
            reset_background_base()
            return
        if hasattr(obj, "destroy"):
            if getattr(obj, "is_alive", True):
                obj.destroy()
            return
        rm = getattr(obj, "remove", None)
        if callable(rm):
            try:
                rm()
            except Exception:
                pass


def reset_background_base() -> None:
    """Start each check from the default base (a base ``Wallpaper`` /
    ``SkyGradient`` replaces it; ``remove()`` restores the default)."""
    bs = getattr(_fw(), "background_stack", None)
    reset = getattr(bs, "reset_base", None)
    if callable(reset):
        with quiet():
            reset()


# Layout cursors advance when a widget is placed and are not rewound by
# destroy() (a cursor, not a registry). Only a REJECTED call must not move them.
CURSOR_KEYS = frozenset({"widgets._stack_x", "widgets._stack_bottom", "widgets._column_top"})


def settle() -> None:
    gc.collect()
    gc.collect()


boot()
