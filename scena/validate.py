"""Author-facing type and name checks for the effect / look API.

Used at write time (constructors and setters). Unknown discrete names and
wrong families raise with the expected options / the right slot.

Numeric sign contract (magnitudes, unit amounts, finite numbers) lives here
too. Author writes raise; formula and tween results clamp magnitudes to 0.
"""
from __future__ import annotations

import math
from types import CoroutineType as _CoroutineType, FunctionType as _FunctionType
from collections.abc import Mapping
import numbers
from enum import Enum
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple, Type, Union

from .state import as_payload

# Geometry baked under a collapsed scale / zoom. The stored value stays exact
# (including 0); only the draw multiplier uses this floor.
MIN_SCALE = 1e-6

HINT_EXTENT = "use `p1`/`p2` or `p1` + `vec` to grow the other way"
HINT_SCALE = "use `flip_x` / `flip_y` to mirror, `rotate_by(180)` to turn"


def _is_formula(value: Any) -> bool:
    """True for a link / formula callable. Types (classes) are not formulas."""
    return callable(value) and not isinstance(value, type)


def finite(value: Any, what: str) -> Any:
    """Finite float for an author write. Formulas and links pass through.

    ``TypeError`` when the concrete value is not a number.
    ``ValueError`` when it is NaN or infinite.
    """
    # Hot path (per-frame verbs: move_by, rotate_by, …): an exact float / int
    # skips the callable probes and the ABC ``numbers.Real`` check. Same
    # result as below; NaN / inf and every other type take the full path.
    t = type(value)
    if t is float:
        if math.isfinite(value):
            return value
    elif t is int:
        if -1e308 < value < 1e308:      # 10**400 overflows float(): refuse it below
            return float(value)
    if _is_formula(value):
        return value
    raw = as_payload(value)
    if _is_formula(raw):
        return value
    if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
        raise TypeError(
            f"{what} expected a number, got {type(raw).__name__} {_short_repr(raw)}"
        )
    try:
        n = float(raw)
    except OverflowError:
        raise ValueError(f"{what} must be a finite number, got {_short_repr(raw)}") from None
    if not math.isfinite(n):
        raise ValueError(f"{what} must be a finite number, got {n}")
    return n


def number(value: Any, what: str) -> float:
    """Finite float for a knob that takes a FIXED number (no live formula).

    Like :func:`finite`, but a function raises instead of passing through —
    for constructor knobs and pure functions that would otherwise feed it to
    ``float()`` (A3 / A4 in Testing Design).
    """
    if _is_formula(value) or _is_formula(as_payload(value)):
        raise TypeError(f"{what} expected a number, got a function")
    return float(finite(value, what))


def seconds(value: Any, what: str) -> float:
    """Finite float for a duration / delay / interval. Callables are not durations."""
    if _is_formula(value):
        raise TypeError(f"{what} expected a number of seconds, got a function")
    return finite(value, what)


def _short_repr(value: Any, limit: int = 40) -> str:
    r = repr(value)
    return r if len(r) <= limit else r[: limit - 1] + "…"


def magnitude(
    value: Any,
    what: str,
    *,
    positive: bool = False,
    hint: Optional[str] = None,
) -> Any:
    """Author write of a size. Formulas pass through; negatives raise.

    Only for values that can become a link (slot writes). A knob or verb that
    takes a fixed number uses :func:`fixed_magnitude` — a formula stored there
    crashes later in a frame (A8; ``TestBareMagnitudeOnlyOnReactivePaths``).

    ``positive=True`` also rejects 0 (wrap width, gradient size, mass).
    """
    n = finite(value, what)
    if _is_formula(n):
        return n
    if positive:
        if n <= 0.0:
            msg = f"{what} must be > 0, got {n}"
            if hint:
                msg += f". {hint}"
            raise ValueError(msg)
    elif n < 0.0:
        msg = f"{what} must be >= 0, got {n}"
        if hint:
            msg += f". {hint}"
        raise ValueError(msg)
    return n


def alpha01(value: Any, what: str) -> float:
    """Opacity for ``set_alpha`` / ``alpha =``: a fixed number, clamped to
    ``[0, 1]`` (Scena Design — amounts in [0, 1] are clamped)."""
    a = number(value, what)
    return 0.0 if a < 0.0 else 1.0 if a > 1.0 else a


def fixed_magnitude(
    value: Any,
    what: str,
    *,
    positive: bool = False,
    hint: Optional[str] = None,
) -> float:
    """:func:`magnitude` for a knob that takes a FIXED number: a function
    raises (``magnitude`` lets formulas through for reactive writes, and
    ``float()`` around it leaked Python's message — A7)."""
    return magnitude(number(value, what), what, positive=positive, hint=hint)


def clamp_magnitude(value: Any) -> float:
    """Formula or tween result: negative reads as 0. NaN and inf raise."""
    raw = as_payload(value)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        try:
            n = float(raw)
        except (TypeError, ValueError):
            raise TypeError(
                f"magnitude expected a number, got {type(raw).__name__}"
            ) from None
    else:
        n = float(raw)
    if not math.isfinite(n):
        raise ValueError(f"magnitude must be a finite number, got {n}")
    if n < 0.0:
        return 0.0
    return n


def unit(value: Any, what: str = "value") -> float:
    """Clamp a concrete amount into ``[0, 1]``. NaN and inf raise."""
    n = finite(value, what)
    if _is_formula(n):
        raise TypeError(f"{what} expected a number, got a formula")
    if n < 0.0:
        return 0.0
    if n > 1.0:
        return 1.0
    return n


def pair(value: Any, what: str) -> Tuple[float, float]:
    """``(x, y)`` from a 2-sequence of finite numbers (A4: offsets, radii,
    directions, scroll). Anything else raises with the spelling that works."""
    raw = as_payload(value)
    if (isinstance(raw, (str, bytes, Mapping, set, frozenset))
            or not hasattr(raw, "__len__") or not hasattr(raw, "__getitem__")):
        # A dict has len and [] but indexes by key (KeyError: 0).
        raise TypeError(
            f"{what} expected a pair (x, y), got {type(raw).__name__} {_short_repr(raw)}. "
            + (f"Write {what}=(2, -1)." if what.isidentifier() else "Pass a pair such as (2, -1).")
        )
    if len(raw) != 2:
        raise TypeError(f"{what} expected a pair (x, y), got {len(raw)} values")
    return number(raw[0], what), number(raw[1], what)



def scroll_rate(value: Any, what: str = "scroll") -> Tuple[float, float]:
    """``(x, y)`` scroll rate in design units/sec: a pair of finite numbers.

    One check for every scroll write (``BackgroundField.scroll``,
    ``canvas.layers.create(scroll=)``, ``layer.scroll``). A scalar raises
    ``TypeError`` naming the pair form; NaN / inf raise ``ValueError``.
    """
    if isinstance(value, (bool, int, float)):
        raise TypeError(
            f"{what} must be (x, y) design units/sec, not a scalar. "
            f"Write {what}=(0, -40)."
        )
    return pair(value, what)


def filter_input(value: Any, what: str):
    """``None`` or a filter (``Blur(...)``, ``Dilate(...)`` …) for ``input=``."""
    if value is None:
        return None
    from .filters import FilterEffect
    if not isinstance(value, FilterEffect):
        raise TypeError(
            f"{what} input= expected a filter such as Blur(2), got "
            f"{type(value).__name__} {_short_repr(value)}"
        )
    return value


def count(value: Any, what: str, minimum: int) -> int:
    """Structural integer ``>= minimum``. Bool is not an int here."""
    raw = as_payload(value)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(
            f"{what} expected an int, got {type(raw).__name__}"
        )
    if raw < minimum:
        raise ValueError(f"{what} must be >= {minimum}, got {raw}")
    return raw


def _type_names(types: Union[type, Tuple[type, ...]]) -> str:
    if not isinstance(types, tuple):
        types = (types,)
    return ", ".join(t.__name__ for t in types)


def expect_type(
    value: Any,
    types: Union[type, Tuple[type, ...]],
    *,
    none: bool = False,
    what: str,
    hint: Optional[str] = None,
) -> Any:
    """Return ``value`` if it is an instance of ``types`` (or ``None`` when allowed)."""
    if value is None:
        if none:
            return None
        msg = f"{what} expected {_type_names(types)}, got None"
        if hint:
            msg += f". {hint}"
        raise TypeError(msg)
    if not isinstance(value, types):
        msg = (
            f"{what} expected {_type_names(types)}, "
            f"got {type(value).__name__}"
        )
        if hint:
            msg += f". {hint}"
        raise TypeError(msg)
    return value


class _NoFunction:
    """The omitted ``fn`` of ``after`` / ``every`` (the decorator form). An
    explicit ``None`` is a call's result, ``every(0.6, spawn())``: it ran
    ``spawn`` once and returned the decorator, silently (persona probes
    round 2, R2-8). Shown as ``None`` in signatures."""

    def __repr__(self) -> str:
        return "None"


NO_FN = _NoFunction()


def refuse_called_function(verb: str, fn) -> None:
    """``after`` / ``every`` given ``None`` where the function goes."""
    if fn is None:
        raise TypeError(
            f"{verb}() got None where the function goes: a call such as "
            f"{verb}(0.6, spawn()) runs spawn now and passes what it returns. "
            f"Pass the function itself, without parentheses: {verb}(0.6, spawn)."
        )


def did_you_mean(
    name: Any, candidates: Iterable[str], *, n: int = 3, cutoff: float = 0.7,
) -> str:
    """`` Did you mean 'a', 'b'?`` for close matches of ``name``, else ``""``."""
    import difflib

    if not isinstance(name, str):
        return ""
    pool = {str(c).lower(): str(c) for c in candidates}
    hits = difflib.get_close_matches(name.lower(), list(pool), n=n, cutoff=cutoff)
    if not hits:
        return ""
    return " Did you mean " + ", ".join(repr(pool[h]) for h in hits) + "?"


def expect_choice(value: Any, allowed: Iterable[str], *, what: str) -> str:
    """Case-insensitive membership in ``allowed``. Returns the canonical name.

    ``allowed`` order is preserved in the error message. No aliases.
    """
    value = as_payload(value)
    names = tuple(str(a) for a in allowed)
    if not names:
        raise ValueError(f"{what}: empty choice list")
    if value is None:
        listed = ", ".join(repr(n) for n in names)
        raise ValueError(f"{what} expected one of {listed}, got None")
    key = str(value).strip().lower()
    for name in names:
        if name.lower() == key:
            return name
    listed = ", ".join(repr(n) for n in names)
    raise ValueError(
        f"{what}={value!r}; expected one of {listed}.{did_you_mean(str(value), names)}"
    )


def expect_bool(value: Any, what: str) -> bool:
    """Strict flag: ``True`` / ``False`` (``0`` / ``1`` also read as a flag).

    A string such as ``"no"`` is truthy in Python; Scena refuses it instead of
    silently turning it into ``True``.
    """
    raw = as_payload(value)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if type(raw).__name__ == "bool_":  # exact-type: numpy.bool_
        return bool(raw)
    raise TypeError(
        f"{what} expected True or False, got {type(raw).__name__} {raw!r}"
    )


def required_positional_count(fn: Callable) -> Optional[int]:
    """Positional parameters ``fn`` needs (no default), or ``None`` if unknown.

    ``*args`` makes the count unknowable (returns ``None``). Bound methods do
    not count ``self``.
    """
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    needed = 0
    for p in sig.parameters.values():
        if p.kind is p.VAR_POSITIONAL:
            return None
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty:
            needed += 1
        if p.kind is p.KEYWORD_ONLY and p.default is p.empty:
            return None
    return needed


def check_handler_arity(fn: Callable, passes: Sequence[str], *, what: str) -> None:
    """Raise now if ``fn`` needs more positional args than Scena will pass.

    ``passes`` names the payload Scena calls the handler with, in order
    (empty for a no-argument handler). A handler may take fewer (truncated
    call) but not more — otherwise the ``TypeError`` would surface frames
    later, far from the decorator. An async handler raises too
    (``refuse_async``): Scena calls handlers, it does not drive them.
    """
    refuse_async(fn, what=what)
    needed = required_positional_count(fn)
    if needed is None or needed <= len(passes):
        return
    fname = getattr(fn, "__name__", "handler")
    if passes:
        given = f"at most {len(passes)} ({', '.join(passes)})"
    else:
        given = "no arguments"
    raise TypeError(
        f"{what} handler {fname}() needs {needed} positional argument(s), "
        f"but Scena calls it with {given}. Remove the extra parameters "
        f"(or give them defaults)."
    )


# Constructor knobs checked from the signature (post, background, SpatialFx,
# audio effects). A parameter whose default is a number takes a number; the
# names below also follow the "Numbers and signs" size contract.
_NONNEG_PARAMS = frozenset({
    "radius", "width", "height", "length", "size", "scale",
    "sigma", "sigmaX", "sigmaY", "thickness", "tile_size",
    "amount", "intensity", "density", "rate", "softness", "spread",
    "glow", "bloom", "opacity", "exposure", "weight", "twinkle", "streak",
    "cone_angle", "drive", "delay", "mix", "decay",
})
_POSITIVE_PARAMS = frozenset({"cell", "res_scale", "cutoff"})
_COUNT_PARAMS = {"segments": 1, "spokes": 1, "points": 2, "layers": 1, "rings": 1}


def _is_plain_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_NUMERIC_ANNOTATIONS = frozenset({
    "float", "int", "Optional[float]", "Optional[int]", "float | None", "int | None",
    "Union[float, None]", "Union[int, None]", "Number", "Optional[Number]",
})


def _numeric_annotation(annotation) -> bool:
    """A parameter annotated as a (possibly optional) number."""
    if annotation in (float, int):
        return True
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", None) or str(annotation)
    text = str(text).replace("typing.", "")
    return text in _NUMERIC_ANNOTATIONS


_SIG_INFO: dict = {}


def _sig_info(sig):
    """Per-signature facts for :func:`_numbers_fast_ok` (cached by identity)."""
    info = _SIG_INFO.get(id(sig))
    if info is not None and info[0] is sig:
        return info
    params = sig.parameters
    positional = [n for n, p in params.items()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    has_var_pos = any(p.kind is p.VAR_POSITIONAL for p in params.values())
    has_var_kw = any(p.kind is p.VAR_KEYWORD for p in params.values())
    numeric = {}
    for n, p in params.items():
        d = p.default
        if isinstance(d, bool):
            numeric[n] = ("flag", None)
            continue
        if _is_plain_number(d) or (d is None and _numeric_annotation(p.annotation)):
            if n in _COUNT_PARAMS and isinstance(d, int):
                numeric[n] = ("count", _COUNT_PARAMS[n])
            elif n in _POSITIVE_PARAMS:
                numeric[n] = ("pos", None)
            elif n in _NONNEG_PARAMS:
                numeric[n] = ("nonneg", None)
            else:
                numeric[n] = ("any", None)
    info = (sig, positional, has_var_pos, has_var_kw, numeric, frozenset(params))
    _SIG_INFO[id(sig)] = info
    return info


def _numbers_fast_ok(sig, args: tuple, kwargs: dict) -> bool:
    """True when every numeric knob got a plain finite number in range and no
    keyword is unknown — the common call. Anything else (a function, a Scena
    value, a string, an error) takes the full :func:`check_numeric_params`
    path, which owns every message. Skips ``bind_partial`` (~4 µs a call)."""
    _s, positional, has_var_pos, has_var_kw, numeric, names = _sig_info(sig)
    # args exclude the receiver; positional[0] is self / cls / klass.
    if len(args) > len(positional) - 1:
        if not has_var_pos:
            return False
    for i, v in enumerate(args[: len(positional) - 1]):
        rule = numeric.get(positional[i + 1])
        if rule is not None and not _fast_number(v, rule):
            return False
    for k, v in kwargs.items():
        if k not in names and not has_var_kw:
            return False
        rule = numeric.get(k)
        if rule is not None and not _fast_number(v, rule):
            return False
    return True


def _fast_number(v, rule) -> bool:
    t = type(v)
    if rule[0] == "flag":
        return t is bool   # 0 / 1 and everything else take the full check
    if t is float:
        if not math.isfinite(v):
            return False
    elif t is not int:
        return False
    kind, lo = rule
    if kind == "any":
        return True
    if kind == "nonneg":
        return v >= 0
    if kind == "pos":
        return v > 0
    return t is int and v >= lo   # count


def check_numeric_params(owner: str, sig, args: tuple, kwargs: dict,
                         formula_knobs=()) -> None:
    """Validate constructor knobs against ``sig`` (an unbound ``__init__``).

    - Unknown keywords raise with the valid list and a did-you-mean.
    - A knob whose default is a number rejects strings, NaN, and inf.
    - Size / amount knobs reject negatives; ``cell`` / ``cutoff`` reject 0.
    - Count knobs (``segments``, ``spokes``, ``points``, …) need an int.

    - ``bool`` is never a number (TypeError).
    - Any other non-number (object, list, dict, set, complex) raises TypeError
      instead of leaking ``float()``'s message from deep inside the class (A3).

    - ``None`` raises: the default is a number, so None means nothing (knobs
      that use None as "preset" default to None and are not checked).

    - A tuple / list raises too: a number default takes one number (per-axis
      knobs declare a tuple default and are not checked here).

    - A function raises unless the knob is in ``formula_knobs(cls)``: a
      declared reactive field, or listed in ``_formula_knobs``
      (``Tail(amount=lambda: ...)``).
    - A knob that defaults to ``None`` but is annotated as a number is checked
      the same way (``None`` stays legal: it is the default).

    Scena values pass through (their payload is checked).
    """
    if _numbers_fast_ok(sig, args, kwargs):
        return
    params = sig.parameters
    has_var_kw = any(p.kind is p.VAR_KEYWORD for p in params.values())
    if not has_var_kw:
        named = [
            n for n, p in params.items()
            if n not in ("self", "cls") and p.kind is not p.VAR_POSITIONAL
        ]
        extra = [k for k in kwargs if k not in params]
        if extra:
            hint = " ".join(
                s for s in (did_you_mean(k, named) for k in extra) if s
            )
            raise TypeError(
                f"{owner}() got unexpected keyword argument(s): "
                f"{', '.join(sorted(extra))}.{(' ' + hint.strip()) if hint else ''} "
                f"Valid: {', '.join(sorted(named))}."
            )
    try:
        bound = sig.bind_partial(None, *args, **kwargs)
    except TypeError:
        return
    for name, value in bound.arguments.items():
        p = params.get(name)
        if p is None or name in ("self", "cls"):
            continue
        default = p.default
        if isinstance(default, bool):
            # A flag (default True / False): a real bool, or 0 / 1. "no" is
            # truthy in Python and silently switched Stars(enabled="no") on
            # (A12). A reactive knob may still take a formula.
            if callable(value) and name in formula_knobs:
                continue
            expect_bool(value, f"{owner} {name}=")
            continue
        numeric_default = _is_plain_number(default)
        if not numeric_default and not (default is None and _numeric_annotation(p.annotation)):
            continue
        if isinstance(value, bool):
            raise TypeError(
                f"{owner} {name}= expected a number, got bool {value!r} "
                f"(bool is never a number)"
            )
        if value is None:
            if not numeric_default:
                continue  # None is this knob's own default ("preset" / auto)
            # The default is a number, so None has no meaning here (knobs that
            # use None as "preset" default to None and are not checked).
            raise TypeError(
                f"{owner} {name}= expected a number, got None "
                f"(omit {name}= for the default {default!r})"
            )
        if callable(value):
            if name in formula_knobs:
                continue  # this class evaluates a live formula for the knob
            raise TypeError(
                f"{owner} {name}= expected a number, got a function "
                f"(this knob takes a fixed number)"
            )
        raw = as_payload(value)
        if isinstance(raw, str):
            raise TypeError(
                f"{owner} {name}= expected a number, got str {raw!r}"
            )
        if not _is_plain_number(raw):
            raise TypeError(
                f"{owner} {name}= expected a number, got {type(raw).__name__} "
                f"{_short_repr(raw)}"
            )
        n = float(raw)
        if not math.isfinite(n):
            raise ValueError(f"{owner} {name}= must be a finite number, got {n}")
        if name in _COUNT_PARAMS and isinstance(default, int):
            lo = _COUNT_PARAMS[name]
            if not isinstance(raw, int) and not n.is_integer():
                raise TypeError(f"{owner} {name}= expected a whole number, got {raw!r}")
            if n < lo:
                raise ValueError(f"{owner} {name}= must be >= {lo}, got {raw!r}")
        elif name in _POSITIVE_PARAMS and n <= 0.0:
            raise ValueError(f"{owner} {name}= must be > 0, got {raw!r}")
        elif name in _NONNEG_PARAMS and n < 0.0:
            raise ValueError(f"{owner} {name}= must be >= 0, got {raw!r}")


def formula_knobs(cls) -> frozenset:
    """Knobs of ``cls`` that take a function (a live formula).

    A declared reactive field (``ScalarSlot`` / ``ContainerSlot`` anywhere in
    the MRO: pad ``width``, shape ``radius``, …) always does — the constructor
    links it. Other knobs opt in through ``_formula_knobs`` (``Tail.amount``).
    Derived from the class, so a new reactive field needs no second list (R8).
    """
    cached = cls.__dict__.get("_formula_knob_cache")
    if cached is not None:
        return cached
    names = set(getattr(cls, "_formula_knobs", ()) or ())
    for base in cls.__mro__:
        for n, v in base.__dict__.items():
            if getattr(v, "_is_field_slot", False):
                names.add(n)
    out = frozenset(names)
    try:
        cls._formula_knob_cache = out
    except (TypeError, AttributeError):
        pass
    return out


def guard_init_numbers(cls) -> None:
    """Wrap ``cls.__init__`` so author knobs pass :func:`check_numeric_params`.

    Must run before any other ``__init__`` wrapper (actor finish, construct-
    to-place): those wrappers identify themselves by identity / flags.
    Only the outermost constructor call is checked (``type(self) is cls``),
    so ``super().__init__`` chains pay nothing extra.
    """
    import functools
    import inspect

    orig = cls.__dict__.get("__init__")
    if orig is None or getattr(orig, "_scena_numbers_guarded", False):
        return
    if getattr(orig, "_scena_actor_init", False) or getattr(orig, "_scena_place_wrapped", False):
        raise RuntimeError(f"guard_init_numbers({cls.__name__}) must run before other init wrappers")
    try:
        sig = inspect.signature(inspect.unwrap(orig))
    except (TypeError, ValueError):
        return
    owner = cls.__name__

    @functools.wraps(orig)
    def wrapped(self, *args, **kwargs):
        if type(self) is cls:
            check_numeric_params(owner, sig, args, kwargs, formula_knobs(cls))
        orig(self, *args, **kwargs)

    wrapped._scena_numbers_guarded = True
    cls.__init__ = wrapped


def guard_new_numbers(cls) -> None:
    """``__new__`` counterpart of :func:`guard_init_numbers` for classes that
    build (or intern) themselves in ``__new__`` — filters, interned looks. The
    knobs are checked against ``__new__``'s own signature before any
    ``float()`` there (A3)."""
    import functools
    import inspect

    orig = cls.__dict__.get("__new__")
    if orig is None:
        return
    raw = orig.__func__ if isinstance(orig, staticmethod) else orig
    if getattr(raw, "_scena_numbers_guarded", False):
        return
    try:
        sig = inspect.signature(raw)
    except (TypeError, ValueError):
        return
    owner = cls.__name__

    @functools.wraps(raw)
    def wrapped(klass, *args, **kwargs):
        if klass is cls:
            check_numeric_params(owner, sig, args, kwargs, formula_knobs(cls))
        return raw(klass, *args, **kwargs)

    wrapped._scena_numbers_guarded = True
    cls.__new__ = staticmethod(wrapped)


def coerce_enum(value: Any, enum_cls: Type[Enum], *, what: str) -> Enum:
    """Accept an enum member or a lowercase name / value string."""
    value = as_payload(value)
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        for member in enum_cls:
            if member.name.lower() == key or str(member.value).lower() == key:
                return member
    options = ", ".join(repr(m.value) for m in enum_cls)
    raise TypeError(
        f"{what} expected {enum_cls.__name__} or one of {options}, "
        f"got {type(value).__name__} {value!r}"
    )


def expect_callable(
    value: Any,
    *,
    none: bool = True,
    what: str = "on_done",
) -> Any:
    """Return ``value`` if it is callable (or ``None`` when allowed)."""
    if value is None:
        if none:
            return None
        raise TypeError(f"{what} expected a callable, got None")
    if not callable(value):
        raise TypeError(
            f"{what} expected a callable, got {type(value).__name__}"
        )
    refuse_async(value, what=what)
    return value


_CO_VARARGS = 0x04
_MISS = object()


def payload_arity(fn: Callable) -> Optional[int]:
    """How many payload values Scena passes ``fn``: its parameters with no default.

    The one rule for every author hook (pointer handlers, ``@collide``,
    timers, ``on_update``, ``@on_change``, ``on_done``). A parameter with a
    default is the author's own: ``lambda tool=tool: ...`` and
    ``save(then=None)`` get nothing, ``def pressed(b):`` gets the payload.
    ``None`` means every value offered: ``*args``, or a signature that cannot
    be read. A bound method does not count ``self``.

    Plain functions and bound methods read ``__code__`` (cheap, no cache).
    Other callables (``functools.partial``, objects with ``__call__``) go
    through ``inspect.signature`` once; the count is cached in the object's
    own ``__dict__``. Never on a class (subclasses would inherit it) or on a
    bound method (``setattr`` falls through to ``__func__``).
    """
    func = getattr(fn, "__func__", fn)
    if type(func) is _FunctionType:
        code = func.__code__
        if code.co_flags & _CO_VARARGS:
            return None
        n = code.co_argcount - len(func.__defaults__ or ())
        return max(0, n - 1) if func is not fn else n
    cache = None if isinstance(fn, type) else getattr(fn, "__dict__", None)
    if cache is not None:
        hit = cache.get("_scena_payload_arity", _MISS)
        if hit is not _MISS:
            return hit
    n = _signature_payload_arity(fn)
    if cache is not None:
        try:
            cache["_scena_payload_arity"] = n
        except TypeError:  # read-only mapping
            pass
    return n


def _signature_payload_arity(fn: Callable) -> Optional[int]:
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    n = 0
    for p in sig.parameters.values():
        if p.kind is p.VAR_POSITIONAL:
            return None
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty:
            n += 1
    return n


def call_truncated(callback: Optional[Callable], *args) -> None:
    """Call ``callback`` with the prefix of ``args`` it asks for (``payload_arity``).

    Payload order is the documented positional list (``on_done``: shape;
    ``@collide``: me, other, info). Only parameters without a default
    receive a value; ``*args`` (or an unreadable signature) gets all of them.
    A callback that hands back a coroutine raises (``refuse_coroutine_result``).
    """
    if callback is None:
        return
    n = payload_arity(callback)
    result = callback(*(args if n is None else args[:n]))
    if result is not None and type(result) is _CoroutineType:
        refuse_coroutine_result(result, callback)


# ``async def`` / ``async def`` + ``yield`` code flags (``inspect.CO_COROUTINE`` /
# ``CO_ASYNC_GENERATOR``).
_CO_ASYNC = 0x80 | 0x200

_ASYNC_FIX = (
    "Scena calls it without driving it, so its body would never run. "
    "Write a plain def, and start the sequence of waits from it as a task "
    "(`self.run_task(self.intro)`, or `run_task(intro)`) or as an async mode "
    "(`self.mode = self.intro`)."
)


def is_async_callable(fn: Any) -> bool:
    """True for an ``async def`` (or async generator) function, bound method or partial."""
    if fn is None:
        return False
    func = getattr(fn, "__func__", fn)
    if type(func) is _FunctionType:
        return bool(func.__code__.co_flags & _CO_ASYNC)
    import inspect

    return inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)


def refuse_async(fn: Any, *, what: str) -> None:
    """Raise if ``fn`` is async where Scena calls it synchronously.

    Only an async **mode** is driven as a script (``e.mode = fn``, ``then=``).
    Anywhere else the call makes a coroutine and drops it: the body never
    runs and Python only prints "coroutine ... was never awaited".
    Plain functions and bound methods read one code flag (``after`` pays it).
    """
    func = getattr(fn, "__func__", fn)
    if type(func) is _FunctionType:
        if not func.__code__.co_flags & _CO_ASYNC:
            return
    elif not is_async_callable(fn):
        return
    name = getattr(fn, "__name__", None) or type(fn).__name__
    raise TypeError(f"{what} {name}() cannot be async: {_ASYNC_FIX}")


def refuse_coroutine_result(result: Any, callback: Any) -> None:
    """The backstop: a sync callback returned a coroutine (``lambda: self.intro()``).

    Closes it (no "never awaited" noise) and raises naming the callback.
    Also the check for an ``async def`` handed to ``after`` / ``every`` /
    ``on_done=``, which skip the registration check (hot calls).
    """
    result.close()
    if is_async_callable(callback):
        refuse_async(callback, what="callback")
    name = getattr(callback, "__name__", None) or type(callback).__name__
    inner = getattr(getattr(result, "cr_code", None), "co_name", "?")
    raise TypeError(
        f"callback {name}() called the async function {inner}() without await, "
        f"so nothing in {inner}() ran. Scena does not run coroutines from "
        f"callbacks: start it as a task (run_task({inner}), or "
        f"self.run_task(self.{inner})) or switch to it as an async mode "
        f"(self.mode = self.{inner})."
    )


def check_pointer_handler(fn: Any, passes: Sequence[str], *, what: str) -> Any:
    """Validate a pointer handler at registration (setter, constructor, decorator).

    ``None`` clears. Otherwise ``fn`` must be callable and need at most the
    positional payload Scena passes (``call_truncated`` drops the rest), so a
    two-parameter ``on_click`` raises here, not frames later at the click.
    """
    if fn is None:
        return None
    expect_callable(fn, what=what)
    check_handler_arity(fn, passes, what=what)
    return fn


def family_hint(value: Any) -> Optional[str]:
    """One-line redirect naming the Scena family of ``value``, or ``None``."""
    name = type(value).__name__
    try:
        from .style import FilterEffect, Gradient, Texture, ProceduralFill

        if isinstance(value, FilterEffect):
            return (
                f"{name} is a filter — use fill_filter / line_filter, "
                "not wallpaper or canvas.effects."
            )
        if isinstance(value, (Gradient, Texture, ProceduralFill)):
            return (
                f"{name} is a paint material — use shape.fill / shape.visual "
                f"or Wallpaper({name}(...))."
            )
    except ImportError:
        pass
    try:
        from .visuals import Visual

        if isinstance(value, Visual):
            return f"{name} is a look — assign with shape.visual = {name}()."
    except ImportError:
        pass
    try:
        from .spatial_fx import SpatialFx

        if isinstance(value, SpatialFx):
            return (
                f"{name} is SpatialFx — construct it to place ({name}()), "
                "not canvas.effects or wallpaper."
            )
    except ImportError:
        pass
    try:
        from .postfx import PostEffect

        if isinstance(value, PostEffect):
            return (
                f"{name} is a canvas post effect — construct it "
                "(Vignette(), Bloom(), …)."
            )
    except ImportError:
        pass
    try:
        from .background import BackgroundField

        if isinstance(value, BackgroundField):
            return (
                f"{name} is a background field — construct it onto "
                "canvas.background."
            )
    except ImportError:
        pass
    try:
        from .shapes import Shape
        from .sprite import Sprite
        from .text import Text

        if isinstance(value, Sprite):
            return f"{name} is a Sprite, not a look, post effect, or wallpaper."
        if isinstance(value, Text):
            return f"{name} is Text (caption), not a look, post effect, or wallpaper."
        if isinstance(value, Shape):
            return f"{name} is a shape, not a look, post effect, or wallpaper."
    except ImportError:
        pass
    return None


_FAMILY_KWARG_HINTS = {
    # Physics words given to a constructor (persona probes round 3, R3-13).
    "mass": "mass is a property: ball.mass = 10 (STATIC for a wall)",
    "bounce": "bounce= belongs to the pair: resolve(ball, \"chao\", bounce=0.5)",
    "friction": "Scena has no friction: slow vel.x yourself in update",
    "velocity": "velocity is ball.vel = (vx, vy), set after making it",
    "vel": "vel is set after making it: ball.vel = (vx, vy)",
    # Persona probes round 5, R5-6: the spelling matcher offered side=, the
    # edge length, a different quantity (following it was silently wrong).
    "sides": "n= is the number of sides (side= is the length of one edge)",
    # Persona probes round 4, R4-2: "create hidden, show later".
    "visible": (
        "visible is set after making it: obj.visible = False on the next line, "
        "obj.visible = True to show it (only Point, Track and layers take visible=)"
    ),
    "radius": "radius= is Circle",
    "width": "width= is Rect/Ellipse/Sprite (Line uses length=)",
    "height": "height= is Rect/Ellipse/Sprite",
    "frame": "frame= is Sprite",
    "source": "source= is Sprite",
    "color": "color= is Shape/Text; use visual= on a Sprite",
    "text": "text= is Text",
    "font_size": "font_size= is Text",
    "background": "background= is Text plate (or widget chrome)",
    "rotation": (
        "angle= is the heading (rotation= was renamed; angle= keeps the point the "
        "graphic is placed by; turn it later with rotate_to / rotate_by)"
    ),
    "id": (
        "Scena has no ids: keep the actor in a variable (player = …), or tag it "
        "with group=\"player\" and read group[\"player\"]"
    ),
}


# Construction plumbing the engine passes; never shown to authors as "Valid:".
_ENGINE_ONLY_KWARGS = frozenset({"attr_name", "owner", "register"})


def reject_unexpected_kwargs(
    cls_name: str,
    extra: dict,
    *,
    valid: Iterable[str],
    where: str = "constructor",
    hints: Optional[dict] = None,
) -> None:
    """Raise ``TypeError`` listing unknown keyword arguments (Sprite / Shape / SpatialFx)."""
    if not extra:
        return
    names = ", ".join(sorted(extra))
    hint_parts: list = []
    merged = dict(_FAMILY_KWARG_HINTS)
    if hints:
        merged.update(hints)
    for key, text in merged.items():
        text = text.rstrip(".")                       # the join adds the period
        if key in extra and text not in hint_parts:   # one hint for x1 and y1
            hint_parts.append(text)
    hint = (" " + "; ".join(hint_parts) + ".") if hint_parts else ""
    valid = [v for v in valid if v not in _ENGINE_ONLY_KWARGS]
    if not hint_parts:
        for key in sorted(extra):
            hint += did_you_mean(key, valid)
    valid_s = ", ".join(sorted(valid))
    raise TypeError(
        f"{cls_name} {where} got unexpected keyword argument(s): {names}.{hint} "
        f"Valid: {valid_s}."
    )


def _call_shape(name: str, sig) -> str:
    """``Grid(parent, cols, rows, gap=0)`` — the author's view of ``sig``."""
    parts = []
    starred = False
    for p in sig.parameters.values():
        if p.name in ("self", "cls") or p.name in _ENGINE_ONLY_KWARGS or p.name.startswith("_"):
            continue
        if p.kind is p.VAR_POSITIONAL:
            parts.append(f"*{p.name}")
            starred = True
            continue
        if p.kind is p.VAR_KEYWORD:
            continue
        if p.kind is p.KEYWORD_ONLY and not starred:
            parts.append("*")
            starred = True
        if p.default is p.empty:
            parts.append(p.name)
        elif isinstance(p.default, (int, float, str, bool, type(None))):
            parts.append(f"{p.name}={p.default!r}")
        else:
            parts.append(f"{p.name}=…")
    return f"{name}({', '.join(parts)})"


def explain_call_error(
    name: str, sig, args: tuple, kwargs: dict, *, method: bool = True,
    example: Optional[str] = None, hints: Optional[dict] = None,
) -> None:
    """Raise an author ``TypeError`` when ``args`` / ``kwargs`` do not fit ``sig``.

    Returns quietly when they fit (the caller re-raises its own error then).
    Unknown keywords get "Did you mean" and the valid list; a missing or
    extra positional gets the call shape, never ``__init__()``.
    ``method=False`` for a plain function (no ``self`` slot to fill).
    ``example`` replaces the generated call shape (``Color("red")``);
    ``hints`` maps a wrong keyword to its family hint (``x=`` → "use center=").
    """
    params = sig.parameters
    has_var_kw = any(p.kind is p.VAR_KEYWORD for p in params.values())
    named = [
        n for n, p in params.items()
        if n not in ("self", "cls") and not n.startswith("_")
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.POSITIONAL_ONLY)
    ]
    extra = [k for k in kwargs if k not in named] if not has_var_kw else []
    if extra:
        if not named:
            raise TypeError(
                f"{name}() takes no keyword arguments; got "
                f"{', '.join(sorted(extra))}=. Write {example or _call_shape(name, sig)}."
            )
        reject_unexpected_kwargs(name, dict.fromkeys(extra), valid=named, hints=hints)
    shape = example or _call_shape(name, sig)
    try:
        if method:
            sig.bind(None, *args, **kwargs)
        else:
            sig.bind(*args, **kwargs)
    except TypeError as exc:
        import re

        text = str(exc)
        missing = re.search(r"missing a required (?:keyword-only )?argument: '(\w+)'", text)
        if missing:
            reason = f"{name}() needs {missing.group(1)}"
        elif "too many positional" in text:
            reason = f"{name}() got {len(args)} positional value(s), more than it takes"
        else:
            reason = f"{name}(): {text}"
        raise TypeError(f"{reason}. Write {shape}.") from None


def explain_raw_call_error(
    fn: Callable, name: str, args: tuple, kwargs: dict, exc: TypeError,
    *, example: Optional[str] = None, hints: Optional[dict] = None,
) -> None:
    """Rewrite Python's own binding error for ``fn`` into an author error.

    Acts only when ``exc`` is Python's message for ``fn`` itself
    (``Polygon.__init__() got an unexpected keyword argument …``); a
    ``TypeError`` the body raised passes through (returns quietly).
    """
    import inspect

    if not str(exc).startswith(f"{getattr(fn, '__qualname__', '')}()"):
        return
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return
    explain_call_error(name, sig, args, kwargs, example=example, hints=hints)


def install_friendly_constructor(cls: type) -> type:
    """Turn Python's "``__init__()`` got an unexpected keyword" into an author error.

    Zero cost on a good call: the check runs only after the constructor
    raised ``TypeError``, and only rewrites Python's own binding message
    (unknown keyword, missing / extra positional). A ``TypeError`` raised
    inside the body passes through. Subclass calls (``super().__init__``)
    pass through too — the message names the class the author wrote. A
    class may set ``_call_example`` (a string) when its signature says
    little (``Color(*args)``), and ``_call_hints`` (wrong keyword → hint,
    as ``reject_unexpected_kwargs`` takes) for family advice (``x=`` on Text).

    Entity subclasses are skipped: their actor wrapper
    (``entity._wrap_actor_init``) does the same rewrite, because ``setup()``
    timing depends on that wrapper staying outermost.
    """
    import functools

    orig = cls.__dict__.get("__init__")
    if orig is None or getattr(orig, "_scena_friendly", False):
        return cls
    if getattr(orig, "_scena_actor_init", False):
        return cls

    @functools.wraps(orig)
    def __init__(self, *args, **kwargs):
        try:
            orig(self, *args, **kwargs)
        except TypeError as exc:
            if type(self).__init__ is __init__:
                explain_raw_call_error(
                    orig, type(self).__name__, args, kwargs, exc,
                    example=getattr(cls, "_call_example", None),
                    hints=getattr(type(self), "_call_hints", None),
                )
            raise

    __init__._scena_friendly = True
    cls.__init__ = __init__
    return cls
