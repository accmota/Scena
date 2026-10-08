from typing import Optional, Union, Tuple, List, NamedTuple, Dict, overload
from enum import Enum
import colorsys
import difflib
import random
import re
import warnings
import skia

from .state import as_payload, as_payload_all
from .closed import ClosedSurface

# Oklab conversions (_linear_srgb_to_oklab / _oklab_to_linear_srgb) follow
# Björn Ottosson's reference code, which he placed in the public domain (MIT
# as a fallback): https://bottosson.github.io/posts/oklab/

class ColorSpace(Enum):
    """Space two colors are blended in (``Color.interpolate``, ``Colormap``, ``Palette``).

    ``OKLAB`` (default) is perceptually even — no grey / brown dip mid-way.
    ``RGB`` is the plain channel mix; ``HSL`` / ``HSV`` travel the hue wheel
    the short way.
    """

    RGB = "rgb"
    HSL = "hsl"
    HSV = "hsv"
    OKLAB = "oklab"


class ColorResolveKind(Enum):
    """How a color name was resolved."""
    EXACT = "exact"           # exact or equivalent spelling (hyphens, camelCase, compact)
    MODIFIER = "modifier"     # dark/light/faded + resolved base
    SUFFIX = "suffix"         # query ends with a known color name
    FUZZY = "fuzzy"           # close edit-distance match
    FALLBACK = "fallback"     # no match; sentinel color used


class ColorResolveResult(NamedTuple):
    rgb: Tuple[float, float, float]
    resolved_name: str
    kind: ColorResolveKind
    suggestions: Tuple[str, ...]


class ColorNames:
    """Dictionary of common color names to RGB values"""

    # Loud sentinel so unknown names are obvious on canvas, not a quiet gray.
    _FALLBACK_RGB: Tuple[float, float, float] = (1.0, 0.0, 1.0)
    _FALLBACK_NAME = "magenta"
    _FUZZY_CUTOFF = 0.75
    _MODIFIERS = ("dark", "light", "faded")

    _COLORS = {
        # Basic Colors
        'black': (0, 0, 0),
        'white': (1, 1, 1),
        'red': (1, 0, 0),
        'green': (0, 1, 0),
        'blue': (0, 0, 1),
        'yellow': (1, 1, 0),
        'cyan': (0, 1, 1),
        'magenta': (1, 0, 1),
        
        # Grays
        'gray': (0.5, 0.5, 0.5),
        'grey': (0.5, 0.5, 0.5),
        'dim gray': (0.412, 0.412, 0.412),
        'dim grey': (0.412, 0.412, 0.412),
        'silver': (0.753, 0.753, 0.753),
        
        # Reds
        'indian red': (0.804, 0.361, 0.361),
        'salmon': (0.98, 0.502, 0.447),
        'crimson': (0.863, 0.078, 0.235),
        'firebrick': (0.698, 0.133, 0.133),
        'maroon': (0.502, 0, 0),
        'coral': (1, 0.498, 0.314),
        
        # Pinks
        'pink': (1, 0.753, 0.796),
        'hot pink': (1, 0.412, 0.706),
        'deep pink': (1, 0.078, 0.576),
        
        # Oranges
        'orange': (1, 0.647, 0),
        'peach': (1, 0.855, 0.725),
        'tomato': (1.0, 0.388, 0.278),
        
        # Browns
        'brown': (0.647, 0.165, 0.165),
        'chocolate': (0.824, 0.412, 0.118),
        'sienna': (0.627, 0.322, 0.176),
        'tan': (0.824, 0.706, 0.549),
        'sandybrown': (0.957, 0.643, 0.376),
        'sandy brown': (0.957, 0.643, 0.376),
        'peru': (0.804, 0.522, 0.247),
        
        # Yellows
        'gold': (1, 0.843, 0),
        'goldenrod': (0.855, 0.647, 0.125),
        'khaki': (0.941, 0.902, 0.549),
        'lemonchiffon': (1, 0.98, 0.804),
        'green yellow': (0.678, 1.0, 0.184),
        
        # Greens
        'forest green': (0.133, 0.545, 0.133),
        'lime': (0.196, 0.804, 0.196),
        'lime green': (0.196, 0.804, 0.196),
        'lawn green': (0.486, 0.988, 0.0),
        'yellow green': (0.604, 0.804, 0.196),
        'sea green': (0.18, 0.545, 0.341),
        'olive': (0.502, 0.502, 0),
        'teal': (0, 0.502, 0.502),
        'sage': (0.737, 0.867, 0.686),
        'emerald': (0.314, 0.784, 0.471),
        'aqua': (0, 1, 1),
        
        # Blues
        'navy': (0, 0, 0.502),
        'royal blue': (0.255, 0.412, 0.882),
        'sky blue': (0.529, 0.808, 0.922),
        'deep sky blue': (0.0, 0.749, 1.0),
        'dodger blue': (0.118, 0.565, 1.0),
        'steel blue': (0.275, 0.51, 0.706),
        'cadet blue': (0.373, 0.620, 0.627),
        'cornflower blue': (0.392, 0.584, 0.929),
        'turquoise': (0.251, 0.878, 0.816),
        
        # Purples
        'purple': (0.502, 0, 0.502),
        'violet': (0.933, 0.51, 0.933),
        'blue violet': (0.541, 0.169, 0.886),
        'indigo': (0.294, 0, 0.51),
        'lavender': (0.902, 0.902, 0.98),
        'plum': (0.867, 0.627, 0.867),
        'orchid': (0.855, 0.439, 0.839),
        'medium orchid': (0.729, 0.333, 0.827),
        
        # Metallics
        'silver': (0.753, 0.753, 0.753),
        'bronze': (0.804, 0.498, 0.196),
        'copper': (0.722, 0.451, 0.2),
    }

    _compact_to_name: Optional[Dict[str, str]] = None
    _names_by_length: Optional[List[str]] = None

    @classmethod
    def names(cls) -> List[str]:
        """Return sorted list of known color names (for discovery / docs)."""
        return sorted(cls._COLORS.keys())

    @classmethod
    def normalize(cls, name: str) -> str:
        """Normalize a color name: camelCase, hyphens, underscores, punctuation."""
        s = name.strip()
        s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
        s = s.lower()
        s = re.sub(r'[-_]+', ' ', s)
        s = re.sub(r'[^a-z0-9\s]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    @classmethod
    def _ensure_indexes(cls) -> None:
        if cls._compact_to_name is None:
            compact: Dict[str, str] = {}
            for key in cls._COLORS:
                compact.setdefault(key.replace(' ', ''), key)
            cls._compact_to_name = compact
        if cls._names_by_length is None:
            cls._names_by_length = sorted(cls._COLORS.keys(), key=len, reverse=True)

    @classmethod
    def _peel_modifiers(cls, name: str) -> Tuple[List[str], str]:
        """Peel leading dark/light/faded prefixes. Returns (modifiers, base)."""
        modifiers: List[str] = []
        rest = name
        while True:
            matched = False
            for mod in cls._MODIFIERS:
                prefix = mod + ' '
                if rest.startswith(prefix):
                    modifiers.append(mod)
                    rest = rest[len(prefix):]
                    matched = True
                    break
            if not matched:
                break
        return modifiers, rest

    @classmethod
    def _lookup_base(cls, base: str) -> Tuple[Optional[str], ColorResolveKind, Tuple[str, ...]]:
        """
        Resolve a base color name (no modifiers).
        Returns (resolved_name or None, kind, suggestions).
        """
        cls._ensure_indexes()
        assert cls._compact_to_name is not None
        assert cls._names_by_length is not None

        if base in cls._COLORS:
            return base, ColorResolveKind.EXACT, ()

        compact = base.replace(' ', '')
        if compact in cls._compact_to_name:
            return cls._compact_to_name[compact], ColorResolveKind.EXACT, ()

        # Longest known name that is a trailing token sequence: "super blue" → "blue"
        for color_name in cls._names_by_length:
            if base == color_name:
                return color_name, ColorResolveKind.EXACT, ()
            if base.endswith(' ' + color_name):
                suggestions = tuple(
                    difflib.get_close_matches(base, cls._COLORS.keys(), n=3, cutoff=0.5)
                )
                return color_name, ColorResolveKind.SUFFIX, suggestions

        matches = difflib.get_close_matches(
            base, cls._COLORS.keys(), n=3, cutoff=cls._FUZZY_CUTOFF
        )
        if matches:
            return matches[0], ColorResolveKind.FUZZY, tuple(matches)

        # Also try fuzzy against compact keys (deepskyblu → deepskyblue)
        compact_keys = list(cls._compact_to_name.keys())
        compact_matches = difflib.get_close_matches(
            compact, compact_keys, n=3, cutoff=cls._FUZZY_CUTOFF
        )
        if compact_matches:
            resolved = cls._compact_to_name[compact_matches[0]]
            suggestions = tuple(
                cls._compact_to_name[m] for m in compact_matches
            )
            return resolved, ColorResolveKind.FUZZY, suggestions

        near = tuple(difflib.get_close_matches(base, cls._COLORS.keys(), n=3, cutoff=0.5))
        return None, ColorResolveKind.FALLBACK, near

    @classmethod
    def _apply_modifiers(
        cls, rgb: Tuple[float, float, float], modifiers: List[str]
    ) -> Tuple[float, float, float]:
        color = Color(rgb)
        for mod in modifiers:
            if mod == 'dark':
                color = color.darker(0.2)
            elif mod == 'light':
                color = color.lighter(0.2)
            elif mod == 'faded':
                color = color.desaturate(0.4)
        return color.rgb[:3]

    @classmethod
    def resolve(cls, name: str) -> ColorResolveResult:
        """
        Resolve a color name without raising.
        Unknown names fall back to a loud magenta sentinel.
        """
        if not isinstance(name, str) or not name.strip():
            return ColorResolveResult(
                cls._FALLBACK_RGB,
                cls._FALLBACK_NAME,
                ColorResolveKind.FALLBACK,
                (),
            )

        normalized = cls.normalize(name)
        modifiers, base = cls._peel_modifiers(normalized)

        if not base:
            return ColorResolveResult(
                cls._FALLBACK_RGB,
                cls._FALLBACK_NAME,
                ColorResolveKind.FALLBACK,
                (),
            )

        resolved_name, kind, suggestions = cls._lookup_base(base)

        if resolved_name is None:
            return ColorResolveResult(
                cls._FALLBACK_RGB,
                cls._FALLBACK_NAME,
                ColorResolveKind.FALLBACK,
                suggestions,
            )

        rgb = cls._COLORS[resolved_name]
        if modifiers:
            rgb = cls._apply_modifiers(rgb, modifiers)
            display = ' '.join(modifiers + [resolved_name])
            # Modifier on an exact/normalized base is still the happy path.
            if kind == ColorResolveKind.EXACT:
                kind = ColorResolveKind.MODIFIER
            return ColorResolveResult(rgb, display, kind, suggestions)

        return ColorResolveResult(rgb, resolved_name, kind, suggestions)

    @classmethod
    def is_known(cls, name: str) -> bool:
        """True if the name resolves to a real color (not the fallback sentinel)."""
        return cls.resolve(name).kind != ColorResolveKind.FALLBACK

    @classmethod
    def get(cls, name: str) -> Tuple[float, float, float]:
        """
        Get RGB values for a color name.

        Exact and normalized names (including dark/light/faded) resolve silently.
        Approximate matches and unknown names warn and still return a color
        (fuzzy/suffix match, or hot magenta fallback).
        """
        result = cls.resolve(name)
        if result.kind in (ColorResolveKind.SUFFIX, ColorResolveKind.FUZZY):
            hint = ''
            if result.suggestions:
                hint = f" Did you mean: {', '.join(result.suggestions)}?"
            warnings.warn(
                f"Unknown color {name!r}. Using {result.resolved_name!r}.{hint}",
                RuntimeWarning,
                stacklevel=2,
            )
        elif result.kind == ColorResolveKind.FALLBACK:
            hint = ''
            if result.suggestions:
                hint = f" Did you mean: {', '.join(result.suggestions)}?"
            warnings.warn(
                f"Unknown color {name!r}. Using {cls._FALLBACK_NAME!r} fallback.{hint}",
                RuntimeWarning,
                stacklevel=2,
            )
        return result.rgb


def _range_error(value: float) -> str:
    """Message for an RGB(A) channel outside ``[0, 1]``."""
    msg = f"Color components must be in range [0, 1], got {value:g}"
    if value > 1:
        msg += ". Scena uses 0–1 (for 0–255 values, divide by 255)"
    return msg


def _is_channel_number(value) -> bool:
    """True for int/float, excluding bool (which is a subclass of int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _scalar_or_uniform(spec, *, name: str) -> float:
    """Resolve a fixed float or ``(lo, hi)`` range into one random sample."""
    spec = as_payload(spec)
    if isinstance(spec, (tuple, list)):
        if len(spec) != 2:
            raise TypeError(
                f"{name} expected a number or (lo, hi), got sequence of length {len(spec)}"
            )
        lo = float(as_payload(spec[0]))
        hi = float(as_payload(spec[1]))
        return random.uniform(lo, hi)
    try:
        return float(spec)
    except (TypeError, ValueError):
        raise TypeError(
            f"{name} expected a number or (lo, hi), got {type(spec).__name__}"
        ) from None


class Color(ClosedSurface):
    """An immutable RGBA color (components 0–1), or "no color".

    Forms::

        Color("red")              # a name (unknown names warn and use the closest)
        Color("#FF8800")          # hex, #RGB / #RRGGBB / #RRGGBBAA
        Color(1, 0.5, 0)          # r, g, b in 0–1 (for 0–255, divide by 255)
        Color(1, 0.5, 0, 0.5)     # r, g, b, alpha
        Color((1, 0.5, 0))        # a 3- or 4-tuple
        Color(other)              # copy
        Color(None)               # "no color" (nothing drawn)

    Derive new colors with ``with_alpha``, ``lighter`` / ``darker``,
    ``saturate`` / ``desaturate``, ``hue_cycle``, ``Color.interpolate``.
    """

    _call_example = 'Color("red"), Color(1, 0.5, 0) or Color("#FF8800")'

    @overload
    def __init__(self, name: str, /) -> None: ...
    @overload
    def __init__(self, r: float, g: float, b: float, a: float = 1.0, /) -> None: ...
    @overload
    def __init__(self, rgba: Tuple[float, ...], /) -> None: ...
    @overload
    def __init__(self, color: "Color", /) -> None: ...
    @overload
    def __init__(self, none: None, /) -> None: ...

    def __init__(self, *args):
        args = as_payload_all(*args)
        # Handle None case
        if len(args) == 1 and args[0] is None:
            object.__setattr__(self, '_is_none', True)
            object.__setattr__(self, '_r', 0)
            object.__setattr__(self, '_g', 0)
            object.__setattr__(self, '_b', 0)
            object.__setattr__(self, '_a', 0)
            return

        # Normal color initialization
        object.__setattr__(self, '_is_none', False)
        r, g, b, a = self._parse_color_args(*args)
        object.__setattr__(self, '_r', r)
        object.__setattr__(self, '_g', g)
        object.__setattr__(self, '_b', b)
        object.__setattr__(self, '_a', a)

    def is_none(self) -> bool:
        """Check if this is a 'no color' instance"""
        return getattr(self, '_is_none', False)

    def __bool__(self) -> bool:
        """Allow direct boolean testing"""
        return not self.is_none()

    def __str__(self) -> str:
        if self.is_none():
            return "Color(none)"
        return f"Color(r={self._r:.3f}, g={self._g:.3f}, b={self._b:.3f}, a={self._a:.3f})"

    # Private methods, used in __init__ -----------------------------------------------------------------

    @classmethod
    def _validate_color_components(cls, *components) -> List[float]:
        """Helper method to validate and convert color components to floats"""
        components = as_payload_all(*components)
        if len(components) not in (3, 4):
            raise ValueError(f"Color must have 3 or 4 components, got {len(components)}")

        if any(isinstance(x, bool) for x in components):
            raise TypeError("Color components must be numbers, not bool")
        if not all(isinstance(x, (int, float)) for x in components):
            raise ValueError("All color components must be numbers")

        result = []
        for i, x in enumerate(components):
            x_float = float(x)
            if i == 3:
                # Alpha matches the setter / with_alpha: clamp, do not raise.
                result.append(_clamp01(x_float))
                continue
            if not 0 <= x_float <= 1:
                raise ValueError(_range_error(x_float))
            result.append(x_float)

        if len(result) == 3:
            result.append(1.0)

        return result
    
    @classmethod
    def _parse_color_args(cls, *args) -> Tuple[float, float, float, float]:
        """
        Parse color arguments and return normalized RGBA values.
        Internal method used by both __init__ and read().
        """
        args = as_payload_all(*args)
        # Case 0: None
        if len(args) == 1 and args[0] is None:
            raise ValueError("Cannot create color from None")

        # Case 1: Multiple direct arguments
        if len(args) in (3, 4):
            return cls._validate_color_components(*args)
        
        # Case 2: Single argument
        if len(args) != 1:
            raise ValueError("Invalid number of arguments")
        
        arg = args[0]
        
        # Already a Color object
        if isinstance(arg, cls):
            return arg._r, arg._g, arg._b, arg._a
            
        # Handle tuple/list inputs
        if isinstance(arg, (tuple, list)):
            return cls._validate_color_components(*arg)
                
        # Handle string inputs (color names or hex)
        if isinstance(arg, str):
            # Check if it's a hex color
            if arg.startswith('#'):
                try:
                    # Remove '#' and validate length
                    hex_str = arg[1:]
                    if len(hex_str) not in [6, 8]:  # 6 for RGB, 8 for RGBA
                        raise ValueError(f"Invalid hex color length: {arg}")
                    
                    # Convert hex to RGB(A)
                    r = int(hex_str[0:2], 16) / 255.0
                    g = int(hex_str[2:4], 16) / 255.0
                    b = int(hex_str[4:6], 16) / 255.0
                    a = 1.0 if len(hex_str) == 6 else int(hex_str[6:8], 16) / 255.0
                    
                    return r, g, b, a
                except ValueError:
                    warnings.warn(
                        f"Invalid hex color {arg!r}. Using 'magenta' fallback.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return 1.0, 0.0, 1.0, 1.0
            
            # Named colors: always resolve (warn + fallback on unknown names)
            r, g, b = ColorNames.get(arg)
            return r, g, b, 1.0

        # if format has not been identified, raise an error
        raise TypeError(
            f"Cannot make a Color from {type(arg).__name__}. Write a name "
            f'("red"), hex ("#FF8800"), 0–1 channels (1, 0.5, 0), or a Color.'
        )

    # Factory methods -----------------------------------------------------------------

    @classmethod
    def from_rgb(cls, r: float, g: float, b: float, a: float = 1.0) -> 'Color':
        """Create color from RGB values"""
        return cls(r, g, b, a)

    @classmethod
    def from_hsl(cls, h: float, s: float, l: float, a: float = 1.0) -> 'Color':
        """Create color from HSL values. Hue wraps; S, L, and alpha clamp to ``[0, 1]``."""
        h = float(h) % 1.0
        s = _clamp01(float(s))
        l = _clamp01(float(l))
        a = _clamp01(float(a))
        r, g, b = colorsys.hls_to_rgb(h, l, s)  # Note: HLS uses different order
        return cls(r, g, b, a)

    @classmethod
    def from_hsv(cls, h: float, s: float, v: float, a: float = 1.0) -> 'Color':
        """Create color from HSV values. Hue wraps; S, V, and alpha clamp to ``[0, 1]``."""
        h = float(h) % 1.0
        s = _clamp01(float(s))
        v = _clamp01(float(v))
        a = _clamp01(float(a))
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return cls(r, g, b, a)

    @classmethod
    def from_name(cls, name: str, a: float = 1.0) -> 'Color':
        """Create color from predefined color name"""
        name = as_payload(name)
        r, g, b = ColorNames.get(name)
        return cls(r, g, b, a)

    @classmethod
    def random(
        cls,
        saturation: Union[float, Tuple[float, float]] = 0.65,
        value: Union[float, Tuple[float, float]] = 0.85,
        alpha: float = 1.0,
    ) -> 'Color':
        """Random hue with controlled HSV saturation and value (vivid by default).

        ``saturation`` / ``value`` accept a fixed number or a ``(lo, hi)`` range.
        Hue is always uniform on the wheel.

            Color.random()
            Color.random(saturation=(0.3, 0.9))
            Color.random(value=(0.5, 1.0))
        """
        h = random.random()
        s = _clamp01(_scalar_or_uniform(saturation, name='saturation'))
        v = _clamp01(_scalar_or_uniform(value, name='value'))
        a = _clamp01(float(as_payload(alpha)))
        return cls.from_hsv(h, s, v, a)

    # Color space conversions -----------------------------------------------------------------

    @property
    def rgb(self) -> Tuple[float, float, float, float]:
        """Get RGBA tuple (returns 0,0,0,0 for no color)"""
        return (self._r, self._g, self._b, self._a)

    @property
    def hsl(self) -> Tuple[float, float, float]:
        """Get HSL components"""
        h, l, s = colorsys.rgb_to_hls(self._r, self._g, self._b)
        return (h, s, l, self._a)  # Reorder to match HSL convention

    @property
    def hsv(self) -> Tuple[float, float, float]:
        """Get HSV components"""
        h, s, v = colorsys.rgb_to_hsv(self._r, self._g, self._b)
        return (h, s, v, self._a)

    @property
    def color4f(self) -> skia.Color4f:
        """Get skia.Color4f object"""
        return skia.Color4f(self._r, self._g, self._b, self._a)

    @property
    def alpha(self) -> float:
        """Alpha in ``[0, 1]``. Read-only: a Color is a value (``with_alpha``)."""
        return self._a

    @alpha.setter
    def alpha(self, alpha: float) -> None:
        # A Color is shared by reference (every default shape shares one), so an
        # in-place write faded every shape that used it (graphics review HP1).
        raise AttributeError(
            "Color is immutable: color.alpha = … would change every shape that "
            "shares this colour. Write color.with_alpha(0.5) for a new Color, or "
            "shape.set_alpha(0.5) to fade one shape."
        )

    # Color modification methods (return new instances) -----------------------------------------------------------------

    def with_alpha(self, alpha: float) -> 'Color':
        """Create new color with modified alpha (clamped to [0, 1])."""
        from .validate import alpha01
        a = alpha01(alpha, "Color.with_alpha")
        return Color(self._r, self._g, self._b, a)

    def jitter(
        self,
        hue: float = 0.04,
        saturation: float = 0.12,
        value: float = 0.12,
    ) -> 'Color':
        """Random color near this one (HSV nudge; alpha unchanged).

        Each of ``hue`` / ``saturation`` / ``value`` is a ± half-range.
        Default hue (~±14°) keeps the family (e.g. reds stay reds).

            Color("red").jitter()
            Color("red").jitter(hue=0.1)
        """
        if self.is_none():
            return Color(None)
        h, s, v, a = self.hsv
        from .validate import number
        dh = number(hue, "Color.jitter hue")
        ds = number(saturation, "Color.jitter saturation")
        dv = number(value, "Color.jitter value")
        # A half-range past 1 spans the whole channel; clamp so a huge value
        # cannot overflow uniform() into NaN (A9).
        dh, ds, dv = (min(abs(d), 1.0) for d in (dh, ds, dv))
        h = (h + random.uniform(-dh, dh)) % 1.0
        s = _clamp01(s + random.uniform(-ds, ds))
        v = _clamp01(v + random.uniform(-dv, dv))
        return Color.from_hsv(h, s, v, a)

    def lighter(self, amount: float = 0.1) -> 'Color':
        """Create a lighter version of this color"""
        from .validate import number
        amount = number(amount, "Color.lighter amount")
        h, s, l, a = self.hsl
        return Color.from_hsl(h, s, min(1.0, l + amount), a)

    def darker(self, amount: float = 0.1) -> 'Color':
        """Create a darker version of this color"""
        from .validate import number
        amount = number(amount, "Color.darker amount")
        h, s, l, a = self.hsl
        return Color.from_hsl(h, s, max(0.0, l - amount), a)

    def saturate(self, amount: float = 0.1) -> 'Color':
        """Create a more saturated version of this color"""
        from .validate import number
        amount = number(amount, "Color.saturate amount")
        h, s, l, a = self.hsl
        return Color.from_hsl(h, min(1.0, s + amount), l, a)

    def desaturate(self, amount: float = 0.1) -> 'Color':
        """Create a less saturated version of this color"""
        from .validate import number
        amount = number(amount, "Color.desaturate amount")
        h, s, l, a = self.hsl
        return Color.from_hsl(h, max(0.0, s - amount), l, a)

    def hue_cycle(self, amount: float = 0.1) -> 'Color':
        """Create a new color with hue rotated clockwise"""
        from .validate import number
        amount = number(amount, "Color.hue_cycle amount")
        h, s, l, a = self.hsl
        adj_amount = amount / 1000
        return Color.from_hsl((h + adj_amount) % 1.0, s, l, a)

    def lerp(self, other: 'Color', t: float) -> 'Color':
        """Instance mix used by free ``lerp()`` / ``tween``. Defaults to OKLAB."""
        other = as_payload(other)
        if not isinstance(other, Color):
            raise TypeError(
                f"Color.lerp expected Color, got {type(other).__name__}"
            )
        return Color.interpolate(self, other, t)

    @classmethod
    def interpolate(cls, 
                   color1: 'Color', 
                   color2: 'Color', 
                   t: float, 
                   color_space: ColorSpace = ColorSpace.OKLAB) -> 'Color':
        """
        Interpolate between two colors in specified color space.
        Args:
            color1: First color
            color2: Second color
            t: Interpolation factor (typically 0–1; not clamped — overshoot OK)
            color_space: Color space to perform interpolation in
                (default ``ColorSpace.OKLAB`` — perceptually uniform)
        Returns:
            New interpolated Color
        """
        t = as_payload(t)
        color_space = as_payload(color_space)
        color1 = as_payload(color1)
        color2 = as_payload(color2)
        if not isinstance(color1, cls) or not isinstance(color2, cls):
            raise TypeError(
                "Color.interpolate expects Color endpoints, "
                f"got {type(color1).__name__} and {type(color2).__name__}"
            )
        
        if color_space == ColorSpace.RGB:
            # Linear RGB interpolation (muddy midpoints for distant hues —
            # prefer the OKLAB default unless you need channel-linear RGB)
            r = color1._r + (color2._r - color1._r) * t
            g = color1._g + (color2._g - color1._g) * t
            b = color1._b + (color2._b - color1._b) * t
            a = color1._a + (color2._a - color1._a) * t
            return cls(
                _clamp01(r), _clamp01(g), _clamp01(b), _clamp01(a),
            )
            
        elif color_space == ColorSpace.OKLAB:
            # Convert to Oklab and interpolate
            l1, a1, b1 = cls._rgb_to_oklab(color1._r, color1._g, color1._b)
            l2, a2, b2 = cls._rgb_to_oklab(color2._r, color2._g, color2._b)
            
            l = l1 + (l2 - l1) * t
            a = a1 + (a2 - a1) * t
            b = b1 + (b2 - b1) * t
            
            # Convert back to RGB
            r, g, b = cls._oklab_to_rgb(l, a, b)
            a = _clamp01(color1._a + (color2._a - color1._a) * t)
            return cls(r, g, b, a)
            
        elif color_space in [ColorSpace.HSL, ColorSpace.HSV]:
            # Get colors in target space
            if color_space == ColorSpace.HSL:
                c1 = color1.hsl
                c2 = color2.hsl
            else:  # HSV
                c1 = color1.hsv
                c2 = color2.hsv
            
            # Interpolate hue along shortest path
            h1, s1, x1, a1 = c1
            h2, s2, x2, a2 = c2
            
            # Find shortest path around the hue circle
            dh = h2 - h1
            if dh > 0.5:
                h1 += 1.0
            elif dh < -0.5:
                h2 += 1.0
                
            h = (h1 + (h2 - h1) * t) % 1.0
            s = s1 + (s2 - s1) * t
            x = x1 + (x2 - x1) * t
            a = a1 + (a2 - a1) * t

            # Create new color in target space
            if color_space == ColorSpace.HSL:
                return cls.from_hsl(h, s, x, a)
            else:  # HSV
                return cls.from_hsv(h, s, x, a)
            
        else:
            raise ValueError(
                f"Unsupported color space: {color_space!r}; expected one of "
                f"{', '.join(repr(c.value) for c in ColorSpace)}"
            )

    # Color Theory Methods, returns new Color instances ------------------------------------
    
    def complementary(self) -> 'Color':
        """
        Returns the complementary color (opposite on the color wheel).
        Useful for high contrast and vibrant combinations.
        """
        h, s, l, a = self.hsl
        # Add 0.5 to hue (180 degrees) and wrap around
        return Color.from_hsl((h + 0.5) % 1.0, s, l, a)

    def split_complementary(self) -> Tuple['Color', 'Color']:
        """
        Returns two colors that are adjacent to the complementary color.
        Creates a high contrast scheme that's less intense than complementary.
        """
        h, s, l, a = self.hsl
        # Add/subtract 150/210 degrees (0.42/0.58)
        return (
            Color.from_hsl((h + 0.42) % 1.0, s, l, a),
            Color.from_hsl((h + 0.58) % 1.0, s, l, a)
        )

    def triadic(self) -> Tuple['Color', 'Color']:
        """
        Returns two colors that form a triadic color scheme.
        Creates a balanced and vibrant combination.
        """
        h, s, l, a = self.hsl
        # Add 0.33 and 0.67 to hue (120 and 240 degrees)
        return (
            Color.from_hsl((h + 0.33) % 1.0, s, l, a),
            Color.from_hsl((h + 0.67) % 1.0, s, l, a)
        )

    def analogous(self, angle: float = 0.083) -> Tuple['Color', 'Color']:
        """
        Returns two colors adjacent to the current color on the color wheel.
        Creates a harmonious and serene combination.
        Args:
            angle: Distance between colors (default 0.083 = 30 degrees)
        """
        from .validate import number
        angle = number(angle, "Color.analogous angle")
        h, s, l, a = self.hsl
        return (
            Color.from_hsl((h - angle) % 1.0, s, l, a),
            Color.from_hsl((h + angle) % 1.0, s, l, a)
        )

    def tetradic(self) -> Tuple['Color', 'Color', 'Color']:
        """
        Returns three colors that form a tetradic (double complementary) scheme.
        Creates a rich, complex combination good for bold designs.
        """
        h, s, l, a = self.hsl
        return (
            Color.from_hsl((h + 0.25) % 1.0, s, l, a),  # 90 degrees
            Color.from_hsl((h + 0.5) % 1.0,  s, l, a),   # 180 degrees
            Color.from_hsl((h + 0.75) % 1.0, s, l, a)   # 270 degrees
        )

    def monochromatic(self, steps: int = 5) -> List['Color']:
        """
        Returns a list of colors in the same hue with different brightness/saturation.
        Creates a subtle and sophisticated combination.
        Args:
            steps: Number of colors to generate
        """
        h, s, l, a = self.hsl
        colors = []
        
        for i in range(steps):
            # Vary both saturation and lightness
            new_s = max(0.0, min(1.0, s + (i - steps/2) * 0.15))
            new_l = max(0.0, min(1.0, l + (i - steps/2) * 0.15))
            colors.append(Color.from_hsl(h, new_s, new_l, a))
            
        return colors

    @property
    def brightness(self) -> float:
        """
        Returns the perceived brightness using W3C formula.
        Returns value between 0 (darkest) and 1 (brightest).
        """
        return (self._r * 299 + self._g * 587 + self._b * 114) / 1000

    def contrast_color(self, intensity: float = 0.3) -> 'Color':
        """
        Returns a contrasting color by inverting the RGB values and adjusting based on brightness.
        For better visibility, ensures minimum contrast by checking against original brightness.
        """
        from .validate import number
        intensity = number(intensity, "Color.contrast_color intensity")
        # Create inverted color
        inv_r = 1.0 - self._r
        inv_g = 1.0 - self._g
        inv_b = 1.0 - self._b
        
        # Create contrast color with original alpha
        contrast = Color(inv_r, inv_g, inv_b, self._a)
        
        # If contrast is not strong enough, adjust towards black or white
        if abs(self.brightness - contrast.brightness) < 0.4:
            # If original color is light, make contrast darker
            if self.brightness > 0.5:
                return contrast.darker(intensity)
            # If original color is dark, make contrast lighter
            return contrast.lighter(intensity)
            
        return contrast
        
    def contrast_tone(self, intensity: float = 0.3) -> 'Color':
        """
        Returns a contrasting color suitable for text or overlays.
        Uses W3C guidelines for contrast ratios.
        """
        from .validate import number
        intensity = number(intensity, "Color.contrast_tone intensity")
        # Calculate perceived brightness using W3C formula
        brightness = (self._r * 299 + self._g * 587 + self._b * 114) / 1000
        
        # Return white or black based on brightness
        if brightness > 0.5:
            return self.darker(intensity)
        return self.lighter(intensity)

    def accent_color(self, intensity: float = 0.3) -> 'Color':
        """
        Returns an accent color that works well with the current color.
        Good for highlights, buttons, or important UI elements.
        Args:
            intensity: How different the accent should be (0-1)
        """
        from .validate import number
        intensity = number(intensity, "Color.accent_color intensity")
        h, s, l, a = self.hsl
        
        # Shift hue by golden ratio (creates pleasing combinations)
        golden_ratio = 0.618033988749895
        new_h = (h + golden_ratio) % 1.0
        
        # Increase saturation and adjust lightness for visibility
        new_s = min(1.0, s + intensity * 0.2)
        new_l = max(0.2, min(0.8, l + (0.5 - l) * intensity))
        
        return Color.from_hsl(new_h, new_s, new_l, a)

    def muted_version(self, amount: float = 0.3) -> 'Color':
        """
        Returns a more muted/desaturated version of the color.
        Good for backgrounds or less prominent elements.
        """
        from .validate import number
        amount = number(amount, "Color.muted_version amount")
        h, s, l, a = self.hsl
        return Color.from_hsl(h, max(0, s - amount), l, a)

    def vibrant_version(self, amount: float = 0.5) -> 'Color':
        """
        Returns a more vibrant version of this color (same hue, higher HSV
        saturation, lifted value). Good for neon glows, CTAs, emphasis.
        """
        from .validate import number
        amount = number(amount, "Color.vibrant_version amount")
        h, s, v, a = self.hsv
        amt = max(0.0, float(amount))
        # Additive boost plus a pull toward full saturation so muted colors
        # actually read as neon, not just slightly less gray.
        s_boost = min(1.0, s + amt + (1.0 - s) * amt * 0.65)
        v_boost = min(1.0, max(v, 0.72) + amt * 0.28)
        return Color.from_hsv(h, s_boost, v_boost, a)

    def whiter_version(self, amount: float = 0.4) -> 'Color':
        """Mix this color toward white (same alpha).

        ``amount`` 0 keeps the hue; 1 is white. For hot energy strokes
        without changing blend mode. Distinct from :meth:`lighter` (HSL L)
        and :meth:`vibrant_version` (more saturation).
        """
        from .validate import number
        amount = number(amount, "Color.whiter_version amount")
        amt = min(1.0, max(0.0, float(amount)))
        r, g, b, a = self.rgb
        return Color(
            r + (1.0 - r) * amt,
            g + (1.0 - g) * amt,
            b + (1.0 - b) * amt,
            a,
        )

    # Color list creation based on object color ------------------------------------

    def shades(self, steps: int = 5) -> List['Color']:
        """
        Returns a list of darker shades of the color.
        Useful for creating depth and hierarchy.
        """
        from .validate import count as _count
        n = _count(steps, "steps", 0)
        if n < 2:
            raise ValueError(f"steps must be >= 2, got {steps}")
        return [self.darker(amount=i / (n - 1)) for i in range(n)]

    def tints(self, steps: int = 5) -> List['Color']:
        """
        Returns a list of lighter tints of the color.
        Useful for creating depth and hierarchy.
        """
        from .validate import count as _count
        n = _count(steps, "steps", 0)
        if n < 2:
            raise ValueError(f"steps must be >= 2, got {steps}")
        return [self.lighter(amount=i / (n - 1)) for i in range(n)]

    # Static helper methods for color space conversions
    @staticmethod
    def _gamma_to_linear(x: float) -> float:
        """Convert from gamma to linear color space"""
        if x <= 0.04045:
            return x / 12.92
        return ((x + 0.055) / 1.055) ** 2.4

    @staticmethod
    def _linear_to_gamma(x: float) -> float:
        """Convert from linear to gamma color space"""
        if x <= 0.0031308:
            return x * 12.92
        return 1.055 * (x ** (1.0 / 2.4)) - 0.055

    @staticmethod
    def _linear_srgb_to_oklab(r: float, g: float, b: float) -> Tuple[float, float, float]:
        """Convert linear sRGB to Oklab color space"""
        # Convert to LMS space
        l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
        m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
        s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

        # Non-linear transform
        l_ = l ** (1/3)
        m_ = m ** (1/3)
        s_ = s ** (1/3)

        # Convert to Oklab
        L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
        a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
        b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_

        return L, a, b

    @staticmethod
    def _oklab_to_linear_srgb(L: float, a: float, b: float) -> Tuple[float, float, float]:
        """Convert Oklab to linear sRGB color space"""
        # Convert to LMS space
        l_ = L + 0.3963377774 * a + 0.2158037573 * b
        m_ = L - 0.1055613458 * a - 0.0638541728 * b
        s_ = L - 0.0894841775 * a - 1.2914855480 * b

        # Non-linear transform
        l = l_ * l_ * l_
        m = m_ * m_ * m_
        s = s_ * s_ * s_

        # Convert to linear sRGB
        r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

        return r, g, b

    @classmethod
    def _rgb_to_oklab(cls, r: float, g: float, b: float) -> Tuple[float, float, float]:
        """Convert sRGB to Oklab color space"""
        # Convert to linear sRGB first
        r = cls._gamma_to_linear(r)
        g = cls._gamma_to_linear(g)
        b = cls._gamma_to_linear(b)
        
        return cls._linear_srgb_to_oklab(r, g, b)

    @classmethod
    def _oklab_to_rgb(cls, L: float, a: float, b: float) -> Tuple[float, float, float]:
        """Convert Oklab to sRGB color space"""
        # Convert to linear sRGB
        r, g, b = cls._oklab_to_linear_srgb(L, a, b)
        
        # Convert to gamma-corrected sRGB
        return (
            cls._linear_to_gamma(max(0.0, min(1.0, r))),
            cls._linear_to_gamma(max(0.0, min(1.0, g))),
            cls._linear_to_gamma(max(0.0, min(1.0, b)))
        )


# Author-facing color input (constructors / ``color=``). Not a runtime check.
ColorLike = Union[Color, str, Tuple[float, ...], List[float]]


def _sequence_channels(color, *, min_len: int) -> Tuple[float, ...]:
    """Read at least ``min_len`` numeric channels from a sequence, or raise."""
    try:
        n = len(color)
    except TypeError:
        raise TypeError(
            f"color expected Color, name, or RGB tuple, got {type(color).__name__}"
        ) from None
    if n < min_len:
        raise TypeError(
            f"color expected a sequence of at least {min_len} numbers, got {n}"
        )
    out = []
    for i in range(min_len):
        x = color[i]
        if not _is_channel_number(x):
            raise TypeError(
                f"color component {i} expected a number, "
                f"got {type(x).__name__}"
            )
        out.append(float(x))
    return tuple(out)


def resolve_rgb(
    color,
    default: Tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> Tuple[float, float, float]:
    """
    Resolve an author-facing ``color=`` value to an RGB float triple.

    Accepts ``None``, color-name ``str``, :class:`Color`, or a sequence of at
    least 3 numbers. Alpha on :class:`Color` and 4-tuples is discarded.
    ``None`` (and ``Color(None)``) returns ``default`` unclamped so internal
    HDR tints can stay above 1. Author tuples clamp to ``[0, 1]``. Names go
    through :class:`Color` (unknown names warn). Garbage raises ``TypeError``.
    """
    if color is None:
        return (float(default[0]), float(default[1]), float(default[2]))
    if isinstance(color, Color):
        if color.is_none():
            return (float(default[0]), float(default[1]), float(default[2]))
        rgb = color.rgb
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    if isinstance(color, str):
        rgb = Color(color).rgb
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    ch = _sequence_channels(color, min_len=3)
    return (_clamp01(ch[0]), _clamp01(ch[1]), _clamp01(ch[2]))


def resolve_rgba(
    color,
    default: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
) -> Tuple[float, float, float, float]:
    """
    Resolve an author-facing ``color=`` value to an RGBA float quadruple.

    Accepts ``None``, color-name ``str``, :class:`Color`, or a sequence of at
    least 3 numbers. For ``str`` / :class:`Color`, alpha is always
    ``default[3]`` (Color alpha is ignored). For a 4-tuple (or longer sequence),
    alpha is taken from index 3; for a 3-tuple, alpha is ``default[3]``.
    ``None`` returns ``default`` unclamped. Author tuples clamp to ``[0, 1]``.
    Garbage raises ``TypeError``.
    """
    d0, d1, d2, d3 = (
        float(default[0]),
        float(default[1]),
        float(default[2]),
        float(default[3]),
    )
    if color is None:
        return (d0, d1, d2, d3)
    if isinstance(color, Color):
        if color.is_none():
            return (d0, d1, d2, d3)
        rgb = color.rgb
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), d3)
    if isinstance(color, str):
        rgb = Color(color).rgb
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), d3)
    try:
        n = len(color)
    except TypeError:
        raise TypeError(
            f"color expected Color, name, or RGB tuple, got {type(color).__name__}"
        ) from None
    if n >= 4:
        ch = _sequence_channels(color, min_len=4)
        return (
            _clamp01(ch[0]), _clamp01(ch[1]), _clamp01(ch[2]), _clamp01(ch[3]),
        )
    if n >= 3:
        ch = _sequence_channels(color, min_len=3)
        return (_clamp01(ch[0]), _clamp01(ch[1]), _clamp01(ch[2]), d3)
    raise TypeError(
        f"color expected a sequence of at least 3 numbers, got {n}"
    )


class Colormap(ClosedSurface):
    """
    A linear gradient colormap that can interpolate between multiple color points
    in different color spaces (OKLAB, RGB, HSL, HSV). Default is OKLAB.
    """
    def __init__(self, 
                 colors: List[Tuple[float, Union[Tuple[float, ...], Color, str]]], 
                 color_space: ColorSpace = ColorSpace.OKLAB):
        """
        Initialize with list of (position, color) tuples.
        Args:
            colors: List of tuples, each containing:
                   - position (float 0-1)
                   - color (Color object, tuple of r,g,b floats 0-1, or color name)
            color_space: ColorSpace enum defining interpolation space
        """
        colors = as_payload(colors)
        if isinstance(colors, (str, bytes)) or not isinstance(colors, (list, tuple)):
            raise TypeError(
                f"Colormap colors= expected a list of (position, color) pairs, got "
                f"{type(colors).__name__}. Write Colormap([(0, 'navy'), (1, 'gold')])."
            )
        for entry in colors:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise TypeError(
                    f"Colormap colors= entries are (position, color) pairs, got {entry!r}. "
                    f"Write Colormap([(0, 'navy'), (1, 'gold')])."
                )
        color_space = as_payload(color_space)
        if not colors or len(colors) < 2:
            raise ValueError("Colormap needs at least 2 color points")
            
        if not all(0 <= as_payload(pos) <= 1 for pos, _ in colors):
            raise ValueError("All positions must be between 0-1")
            
        self._color_space = color_space
        
        # Convert all colors to Color objects and store as tuples
        self._colors = [(as_payload(pos), Color(color)) for pos, color in colors]
        
        # Ensure we have colors at 0 and 1
        if self._colors[0][0] != 0.0:
            self._colors.insert(0, (0.0, self._colors[0][1]))
        if self._colors[-1][0] != 1.0:
            self._colors.append((1.0, self._colors[-1][1]))
        
        # Store converted colors in target color space
        self._converted_colors = [
            (pos, self._rgb_to_target_space(color.rgb))
            for pos, color in self._colors
        ]

    @property
    def color_space(self) -> ColorSpace:
        """Returns the color space used for interpolation"""
        return self._color_space

    @color_space.setter 
    def color_space(self, value: ColorSpace) -> None:
        """Sets the color space used for interpolation"""
        self._color_space = as_payload(value)

    def _rgb_to_target_space(self, rgb: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Convert RGB to target color space"""
        if self._color_space == ColorSpace.RGB:
            return rgb
        elif self._color_space == ColorSpace.OKLAB:
            return Color._rgb_to_oklab(rgb[0], rgb[1], rgb[2])
        elif self._color_space == ColorSpace.HSL:
            return colorsys.rgb_to_hls(rgb[0], rgb[1], rgb[2])  # Note: HLS not HSL
        elif self._color_space == ColorSpace.HSV:
            return colorsys.rgb_to_hsv(rgb[0], rgb[1], rgb[2])
        
    def _target_space_to_rgb(self, color: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Convert from target color space back to RGB"""
        if self._color_space == ColorSpace.RGB:
            return color
        elif self._color_space == ColorSpace.OKLAB:
            return Color._oklab_to_rgb(color[0], color[1], color[2])
        elif self._color_space == ColorSpace.HSL:
            return colorsys.hls_to_rgb(color[0], color[1], color[2])  # Note: HLS not HSL
        elif self._color_space == ColorSpace.HSV:
            return colorsys.hsv_to_rgb(color[0], color[1], color[2])

    def get_color(self, t: float) -> Color:
        """The color at position ``t`` along the ramp (0 = first stop, 1 = last).

        ``t`` outside 0–1 clamps.
        """
        from .validate import number
        t = number(t, "Colormap.get_color t")
        t = as_payload(t)
        t = max(0.0, min(1.0, t))

        # Find the two stops around t and blend them.
        for i in range(len(self._colors) - 1):
            pos1, color1 = self._colors[i]
            pos2, color2 = self._colors[i + 1]

            if pos1 <= t <= pos2:
                u = (t - pos1) / (pos2 - pos1) if pos1 != pos2 else 0
                return Color.interpolate(color1, color2, u, self._color_space)

        # Fallback to last color
        return self._colors[-1][1]

    def random(self) -> Color:
        """A random color along this ramp (same as ``get_color(random.random())``)."""
        return self.get_color(random.random())

    @classmethod
    def from_preset(cls, preset: str, color_space: ColorSpace = ColorSpace.OKLAB) -> 'Colormap':
        """
        Create a Colormap from a named preset.
        Args:
            preset: Name of the preset (e.g., 'plasma', 'ocean', 'sunset', etc.)
            color_space: ColorSpace enum defining interpolation space
        Returns:
            Colormap instance
        """
        from .gradient_presets import get_preset, preset_names

        preset = as_payload(preset)
        color_space = as_payload(color_space)
        stops = get_preset(preset)
        if stops is not None:
            return cls(stops, color_space)

        if ColorNames.is_known(preset):
            base_color = Color(preset)
            return cls([
                (0.0, base_color.darker(0.3)),
                (1.0, base_color.lighter(0.2))
            ], color_space)

        from .validate import did_you_mean
        names = list(preset_names())
        raise ValueError(
            f"Invalid preset name: {preset!r}.{did_you_mean(preset, names)} "
            f"Use a color name or one of the {len(names)} presets "
            f"(Guia: Paletas e rampas), e.g. {', '.join(repr(n) for n in names[:6])}."
        )

    @property
    def colors(self) -> List[Tuple[float, Union[Tuple[float, ...], Color, str]]]:
        """Returns the list of (position, color) tuples"""
        return self._colors

    @classmethod
    def from_colors(cls, *colors, color_space: ColorSpace = ColorSpace.OKLAB) -> 'Colormap':
        """
        Create a Colormap from a list of colors or multiple color arguments.
        Colors are evenly distributed across the gradient.
        
        Args:
            *colors: List of colors or multiple color arguments
            color_space: ColorSpace enum defining interpolation space
        
        Examples:
            Colormap.from_colors(['red', 'blue', 'green'])
            Colormap.from_colors('red', 'blue', 'green')
            Colormap.from_colors(Color(1,0,0), Color(0,0,1))
        """
        args = as_payload_all(*colors)
        color_space = as_payload(color_space)
        # Handle single list argument
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            colors = args[0]
        else:
            colors = args
            
        if len(colors) < 2:
            raise ValueError("Colormap needs at least 2 colors")
            
        # Convert colors and create evenly spaced positions
        positions = [i / (len(colors) - 1) for i in range(len(colors))]
        color_pairs = [(pos, Color(color)) for pos, color in zip(positions, colors)]
        
        return cls(color_pairs, color_space)


def _looks_like_stops(seq) -> bool:
    """True when ``seq`` looks like Colormap ``[(t, color), …]`` stops."""
    if not seq:
        return False
    first = seq[0]
    if not isinstance(first, tuple) or len(first) != 2:
        return False
    pos = first[0]
    return isinstance(pos, (int, float)) and not isinstance(pos, bool)


class Palette(ClosedSurface):
    """A fixed set of evenly spaced swatches sampled from a color ramp.

    Palette does not draw or place anything — like Colormap, it only hands
    back Color values. Where Colormap answers "what color at t?" for any
    continuous t, Palette pre-samples a handful of picks and lets you grab
    them by index or sequentially.

        Palette("plasma")                  # 6 default steps
        Palette("plasma", steps=8)
        Palette(["red", "yellow", "blue"])
        Palette("red", "yellow", "blue", steps=5)

    Indexing is cyclic: ``palette[i]`` wraps via modulo for any int, so a
    growing counter (wave number, spawn count, …) always lands on a valid
    color. ``get_next()`` keeps its own cursor and wraps forever.
    ``for color in palette`` is finite (one pass over the swatches).

    Args:
        steps: How many swatches to sample (default 6).
        color_space: Blending space (default ``ColorSpace.OKLAB``).
    """

    def __init__(
        self,
        *colors,
        steps: int = 6,
        color_space: ColorSpace = ColorSpace.OKLAB,
    ):
        args = as_payload_all(*colors)
        steps = as_payload(steps)
        color_space = as_payload(color_space)

        from .validate import count as _count
        n = _count(steps, "steps", 0)
        if n < 1:
            raise ValueError(f"Palette steps must be >= 1, got {steps}")

        colormap = self._resolve_colormap(args, color_space)
        if n == 1:
            self._colors = [colormap.get_color(0.5)]
        else:
            self._colors = [colormap.get_color(i / (n - 1)) for i in range(n)]
        self._cursor = 0

    @staticmethod
    def _resolve_colormap(args, color_space) -> Colormap:
        from .style import Gradient

        if not args:
            return Colormap.from_preset("plasma", color_space)

        if len(args) == 1:
            sole = args[0]
            if isinstance(sole, Colormap):
                return sole
            if isinstance(sole, Gradient):
                return Colormap(
                    list(zip(sole._positions, sole._colors)),
                    color_space,
                )
            if isinstance(sole, str):
                return Colormap.from_preset(sole, color_space)
            if isinstance(sole, Color):
                return Colormap(
                    [
                        (0.0, sole.darker(0.3)),
                        (1.0, sole.lighter(0.2)),
                    ],
                    color_space,
                )
            if isinstance(sole, (list, tuple)):
                if _looks_like_stops(sole):
                    return Colormap(list(sole), color_space)
                return Colormap.from_colors(sole, color_space=color_space)
            raise TypeError(
                "Palette expected a preset name, Colormap, Gradient, "
                f"or colors, got {type(sole).__name__}"
            )

        return Colormap.from_colors(*args, color_space=color_space)

    def __len__(self) -> int:
        return len(self._colors)

    def __iter__(self):
        """One pass over the fixed swatches (finite — not the cyclic cursor)."""
        return iter(self._colors)

    def __getitem__(self, index):
        """Swatch at ``index``. Ints wrap via modulo; slices do not wrap."""
        if isinstance(index, slice):
            return list(self._colors[index])
        return self._colors[int(index) % len(self._colors)]

    def __repr__(self) -> str:
        return f"Palette({len(self._colors)} swatches)"

    def get_next(self) -> Color:
        """Next swatch; own cursor, wraps forever. Call once per event."""
        n = len(self._colors)
        color = self._colors[self._cursor]
        self._cursor = (self._cursor + 1) % n
        return color

    def reset(self, index: int = 0) -> "Palette":
        """Reset ``get_next()``'s cursor (e.g. restarting a run / wave)."""
        index = as_payload(index)
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(f"Palette.reset() index must be a whole number, got {type(index).__name__}")
        n = len(self._colors)
        self._cursor = index % n   # negative counts from the end, like a list
        return self

    def random(self) -> Color:
        """A random swatch (discrete — Colormap.random() samples continuously)."""
        return random.choice(self._colors)

    @property
    def colors(self) -> List[Color]:
        """Copy of the swatches, in order."""
        return list(self._colors)
