# Re-export the author API. Engine types stay in their modules
# (``from scena.orchestration import ScenaFramework``, etc.).
# Bench / engine knobs are not author surface; import them from their module:
# ``scena.orchestration.set_leak_detector``, ``scena.process.set_sync_watchdog``,
# ``scena.process.last_author_error`` / ``clear_author_error`` (the SCENA WARNING
# banner's payload; Ctrl+Shift+E dismisses it),
# ``scena.background_kinds.sky_palette``, ``scena.recipes.get_extrude_focus`` /
# ``set_metal_light`` / ``get_metal_light``.

from ._version import __version__
from .orchestration import (
    run, init, set_fx_auto,
    flush,
)
from .act import Act, change_act, RETIRED_NAMES as _ACT_RETIRED_NAMES
from .state import (
    State, remap, lerp, MappingFunctions, Attribute, Container, FieldRef,
    LinkedAttributeError, DerivedAttributeError, CallableAssignError, DestroyedError,
)
from .easing import approach, chase, deadzone
from .process import (
    after, every, tween, Handle, ReadyManager, RememberedManager, Cancelled,
    wait, until, until_empty, parallel, race, set_watchdog,
    on_mode, exit_mode, run_task,
)
from .audio import play_sound, Sound, audio, amp_db
from .audio_capture import Microphone
from .audio_effects import LowPass, HighPass, Echo, Reverb, Distortion, Wavefold
from .canvas import Canvas, VisibleBounds
from .registry import (
    GroupOperator,
    ParallaxLayerError,
    UiLayerError,
    above,
    below,
)
from .uiwidget import UIWidget, Button, TextInput, DropDown, Slider, CheckBox
from .menu import Menu
from .text import Text
from .style import (
    Gradient, Texture,
    ProceduralFill, WaterFill, FlameFill, SwellFill,
    WaveFill, AuroraFill,
    set_defaults,
)
from .color import (
    ColorSpace, ColorNames, Color, Colormap, Palette,
)

from .filters import (
    ComposeFx, Blur, HostGlow, GlowFilter, DropShadow, Dilate, Erode,
    EmissiveFilter,
)
from .visuals import (
    Visual, Paint, Fill, Stroke, Glow, CheapGlow, Shadow,
    Halo, Swell, Flame, HaloStyle,
    HueShift, Grayscale, Aura, EmissiveBloom,
)
from .recipes import (
    Recipe, Neon, MultiBorder, Extrude,
    DashRing, GearShell, ElectricField,
    Shield, ShieldStyle, BoltStyle,
    OrganicOutline, Tracer, ElectricBolt,
    Water, Liquify, Bolt, Metal, Sphere,
    Wave, Aurora,
    Laser, Ink, InkBleed, Rim, Gel,
    Tail, Beat, InsetRim, Recolor,
    set_extrude_focus,
)
from .fx_quality import FxQuality
from .effects import (
    Vignette, Grain, Bloom, Grade, Chroma, Pixelate, Haze, Scanlines, ScreenBlur,
    Prism, Perspective, Lamp, GodRays, Spotlight, DistantLight,
    Kaleidoscope, Wash, MotionTrail,
    Crt, Vortex, ZoomBlur, Fog,
    ColorSweep, ColorWash, CosmicBloom,
)
from .background_kinds import (
    Wallpaper, SkyGradient,
    Clouds,
    Stars, Stardust, Chromadust, Nebuladust, Borealis, Plasma, Mist,
    Debris, Embers, WindStreaks, Ground, Lattice, Nebula,
    Floor, Road,
    Tunnel, StarFly, PlanetFly,
    ChurningClouds, FilamentField,
)
from .spatial_fx import (
    SpatialFx,
    Fire,
    Sparks, GlowSpot, Orb, Warp, Portal,
    Rain, Jet, Sunburst, Starburst,
)
from .spatial_fx_effects import FireStyle

from .scenamath import Vec2, vec_from_angle, chance
from .input import Mouse, KeyPressed, Clock
from .entity import Entity
from .shapes import (
    Shape, Point, Line, Rect, Square, Concave, Circle, Ellipse, Polygon, RegularPolygon,
    Triangle, Anchor, Pos, XPos, middle_point, distance, heading, nearest,
    RETIRED_NAMES as _SHAPES_RETIRED_NAMES,
)
from .box import Box, Grid
from .geom import intersections, intersection, closest_point
from .track import Track, show_tracks
from .process_overlay import show_processes
from .history import History, Contrail
from .sprite import Sprite, Sheet, Svg, AUTO_GROUND
from .sprite_button import SpriteButton
from .level import Level
from .endless import Endless
from .hitbox import Hitbox
from .events import when, on_change, unregister_event
from .bounds import leave_playfield
from .interaction import click, hover, hover_exit, drag_to, drag_over, drop_by
# The documented @collide / @collide_with families (the interaction.py
# wrappers only forward, and their docstrings only say "see collision").
from .collision import (
    Collider, CollisionInfo, TouchingContact, collision, ANYTHING,
    STATIC, resolve, unresolve, test_collision,
    collide, collide_stay, collide_exit,
    collide_with, collide_with_stay, collide_with_exit,
)

# Star-import surface: author types and globals.
FRAMEWORK_EXPORTS = [
    'st', 'group', 'canvas', 'mouse', 'keyp', 'clock', 'ready', 'recently', 'ui',
    'run', 'init', 'set_fx_auto',
    'flush',
    'after', 'every', 'tween', 'run_task', 'Handle', 'Cancelled',
    'wait', 'until', 'until_empty', 'parallel', 'race', 'set_watchdog',
    'on_mode', 'exit_mode',
    'Act', 'change_act',
    'play_sound', 'Sound', 'audio', 'amp_db',
    'Microphone', 'LowPass', 'HighPass', 'Echo', 'Reverb', 'Distortion', 'Wavefold',
    'show_tracks',
    'show_processes',
]

STATE_EXPORTS = [
    "State", "remap", "lerp", "chase", "approach", "deadzone", "Attribute",
    "LinkedAttributeError", "DerivedAttributeError", "CallableAssignError", "DestroyedError",
]

CANVAS_EXPORTS = [
    "ParallaxLayerError", "UiLayerError",
    "above", "below",
]

UI_EXPORTS = [
    "Button", "TextInput", "DropDown", "Slider",
    "Text", "CheckBox", "Menu",
]

STYLE_EXPORTS = [
    "Gradient", "Texture",
    "ProceduralFill", "WaterFill", "FlameFill", "SwellFill",
    "WaveFill", "AuroraFill",
]

STYLE_FILTER_EXPORTS = [
    "ComposeFx",
    "Blur", "HostGlow", "GlowFilter", "DropShadow", "Dilate", "Erode",
    "EmissiveFilter",
    "Visual", "Paint", "Fill", "Stroke", "Glow", "CheapGlow", "Halo",
    "Shadow",
    "HueShift", "Grayscale", "Aura", "EmissiveBloom", "Recolor",
    "Recipe", "Neon", "MultiBorder", "Extrude",
    "DashRing", "GearShell",
    "ElectricField",
    "Shield",
    "OrganicOutline", "Tracer", "ElectricBolt",
    "Swell", "Water", "Flame", "Metal",
    "Wave", "Aurora", "Liquify", "Bolt",
    "Laser",
    "Ink", "InkBleed", "Sphere", "Rim", "Gel",
    "Tail", "Beat", "InsetRim",
    "set_extrude_focus",
    "FxQuality",
    "Vignette", "Grain", "Bloom", "Grade", "Chroma", "Pixelate", "Haze",
    "Scanlines", "ScreenBlur",
    "Prism", "Perspective", "Lamp", "GodRays", "Spotlight", "DistantLight",
    "Kaleidoscope", "Wash", "MotionTrail",
    "Crt", "Vortex", "ZoomBlur", "Fog",
    "ColorSweep", "ColorWash", "CosmicBloom",
    "Wallpaper", "SkyGradient",
    "Clouds",
    "Stars", "Stardust", "Chromadust", "Nebuladust", "Borealis", "Plasma", "Mist",
    "Debris", "Embers", "WindStreaks", "Ground", "Lattice", "Nebula",
    "Floor", "Road",
    "Tunnel", "StarFly", "PlanetFly",
    "ChurningClouds", "FilamentField",
    "SpatialFx",
    "Fire",
    "Sunburst", "Starburst",
    "Rain", "Jet", "Sparks", "GlowSpot", "Orb", "Warp", "Portal",
]

COLOR_EXPORTS = [
    "ColorSpace", "ColorNames", "Color", "Colormap", "Palette",
]

STYLE_API_EXPORTS = [
    "set_defaults",
]

MATH_EXPORTS = ["Vec2", "vec_from_angle", "chance"]

INPUT_EXPORTS = ["Mouse", "KeyPressed", "Clock"]

SHAPES_EXPORTS = [
    "Box", "Grid",
    "Shape", "Point", "Line", "Rect", "Square", "Concave", "Circle", "Ellipse",
    "Polygon", "RegularPolygon", "Triangle", "Anchor",
    "XPos", "middle_point", "distance", "heading", "nearest",
    "intersections", "intersection", "closest_point",
    "Track",
    "History", "Contrail",
    "Entity",
    "Sprite", "Sheet", "Svg", "SpriteButton", "AUTO_GROUND", "Hitbox",
]

EVENT_EXPORTS = ["when", "on_change", "unregister_event"]

INTERACTION_EXPORTS = [
    "click", "hover", "hover_exit", "drag_to", "drag_over", "drop_by",
    "collide", "collide_stay", "collide_exit",
    "collide_with", "collide_with_stay", "collide_with_exit",
    "leave_playfield",
]

LEVEL_EXPORTS = ["Level", "Endless"]

COLLISION_EXPORTS = [
    "Collider", "CollisionInfo", "TouchingContact", "collision", "ANYTHING",
    "STATIC", "resolve", "unresolve", "test_collision",
]

__all__ = (
    FRAMEWORK_EXPORTS +
    STATE_EXPORTS +
    CANVAS_EXPORTS +
    UI_EXPORTS +
    STYLE_EXPORTS +
    STYLE_FILTER_EXPORTS +
    COLOR_EXPORTS +
    STYLE_API_EXPORTS +
    MATH_EXPORTS +
    INPUT_EXPORTS +
    SHAPES_EXPORTS +
    EVENT_EXPORTS +
    INTERACTION_EXPORTS +
    COLLISION_EXPORTS +
    LEVEL_EXPORTS
)

# Python's "Grid.__init__() got an unexpected keyword argument" becomes an
# author error (Did you mean / Valid / call shape) on every exported class.
# The wrapper acts only after a failed call, and only rewrites Python's own
# binding message — a class's own TypeError passes through untouched.
def _install_friendly_constructors() -> None:
    import enum
    import inspect
    from .validate import install_friendly_constructor
    for name in __all__:
        obj = globals().get(name)
        if inspect.isclass(obj) and not issubclass(obj, (enum.Enum, BaseException)):
            install_friendly_constructor(obj)


_install_friendly_constructors()
del _install_friendly_constructors

# Type hints for better linter support
st: State
group: GroupOperator
canvas: Canvas
mouse: Mouse
keyp: KeyPressed
obj: object
ready: ReadyManager
recently: RememberedManager
clock: Clock
ui: object
audio: object

# Bootstrap the framework and get globals from builtins.
#
# init() sets up the singleton, wires up keyp/mouse/st/clock/canvas/obj/
# group/ready/recently/ui, and creates a canvas backed by an in-memory (raster) Skia
# surface -- no OS window is opened here. This lets `from scena import *`
# followed immediately by shape/widget/state creation work (the common
# authoring pattern -- see scripts/app5.py), while leaving the real window
# to be created later, when the script calls run().
#
# Scripts that need a specific design size before run() -- e.g. because
# they read canvas.width/canvas.height, like scripts/sierpinsky.py -- must
# call init(width=.., height=..) themselves as the very first statement,
# before creating any shapes. run() itself does not take size arguments.
import builtins

init()

# ``show()`` without ``await`` becomes a SCENA WARNING naming the line and the
# fix (process.install_unawaited_hook; Actors Design, Protections).
from .process import install_unawaited_hook as _install_unawaited_hook
_install_unawaited_hook()
del _install_unawaited_hook

keyp = builtins.keyp
mouse = builtins.mouse
st = builtins.st
canvas = builtins.canvas
group = builtins.group
ready = builtins.ready
recently = builtins.recently
clock = builtins.clock
ui = builtins.ui
audio = builtins.audio

# Retired author names (``Scene`` → ``Act``, ``change_scene`` → ``change_act``,
# 0.6.0; ``EquilateralTriangle`` → ``Triangle``, 0.9.0): ``scena.Scene`` /
# ``from scena import Scene`` get a stub that raises with the new spelling.
# Not in ``__all__`` and not in builtins: star-import code gets Python's own
# ``NameError``.
_RETIRED_NAMES = {**_ACT_RETIRED_NAMES, **_SHAPES_RETIRED_NAMES}


def __getattr__(name):
    stub = _RETIRED_NAMES.get(name)
    if stub is not None:
        return stub
    raise AttributeError(f"module 'scena' has no attribute {name!r}")
