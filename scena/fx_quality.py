"""
FX quality presets for Scena.

Two orthogonal product axes (fidelity vs presentation rate). Fidelity is
this module; rate is framerate / VSync (see orchestration).

Fidelity levels (shipping):
  high    — post ½; shape filters full res; batch on; full recipes (**default**)
  medium  — post ½; shape full; batch on; **lite** multipass / SpatialFx (promoted former low)
  low     — post ¼; shape full; batch on; **survival** substitutes (bench-driven)
  max     — full res; batch **off** (strict z-order / diagnostic reference)

Draw-path selection uses module slots updated only in ``activate_quality``:
O(1) loads of ``fidelity_tier()``, ``hero_fx_lod()``, ``particle_scale()`` —
no framework lookup, dict copies, or ``_from_value`` on the hot path.

Composition always uses the hybrid strategy (sharp geometry + scaled FX).
There is no soft mode and no product draw-cache.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, NamedTuple, Optional, Tuple


# Hot-path recipe tier (compare as int; max quality maps to HIGH).
TIER_LOW = 0
TIER_MED = 1
TIER_HIGH = 2

# Short author alias for the medium product tier.
_ALIASES: Dict[str, str] = {
    "med": "medium",
}


class FxQuality(Enum):
    """Effect fidelity preset for ``canvas.fx_quality`` (a string works too).

    ``LOW`` / ``MEDIUM`` / ``HIGH`` (default) / ``MAX`` trade effect detail
    (blur passes, particle counts, SDF resolution) for frame time.
    ``"med"`` is accepted for ``MEDIUM``.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"

    @classmethod
    def _from_value(cls, value) -> "FxQuality":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return QUALITY_ORDER[max(0, min(len(QUALITY_ORDER) - 1, value))]
        s = str(value).strip().lower()
        s = _ALIASES.get(s, s)
        for q in cls:
            if q.value == s or q.name.lower() == s:
                return q
        raise ValueError(
            f"Unknown FxQuality {value!r}; expected one of "
            + ", ".join(q.value for q in cls)
            + " (alias: med→medium)"
        )


# Full enum order (int parse / completeness). ``max`` is API/diagnostic only.
QUALITY_ORDER: Tuple[FxQuality, ...] = (
    FxQuality.LOW,
    FxQuality.MEDIUM,
    FxQuality.HIGH,
    FxQuality.MAX,
)

# Product ladder for Ctrl+Shift+3 / ``next_quality`` (no ``max``).
QUALITY_CYCLE: Tuple[FxQuality, ...] = (
    FxQuality.LOW,
    FxQuality.MEDIUM,
    FxQuality.HIGH,
)

# Product / framework default (post ½, shape full, batch on).
DEFAULT_FX_QUALITY = FxQuality.HIGH


# batch_shared_filters: on for shipping qualities; off only at ``max``.
_PRESETS: Dict[FxQuality, Dict[str, object]] = {
    FxQuality.MAX: {
        "post_scale": 1.0,
        "shape_scale": 1.0,
        "batch_shared_filters": False,
    },
    FxQuality.HIGH: {
        "post_scale": 0.5,
        "shape_scale": 1.0,
        "batch_shared_filters": True,
    },
    FxQuality.MEDIUM: {
        "post_scale": 0.5,
        "shape_scale": 1.0,
        "batch_shared_filters": True,
    },
    FxQuality.LOW: {
        "post_scale": 0.25,
        # Full-res shape filters: half-res RT path is a net loss on multi-key
        # sparse batches (e.g. app_effects mixed); survival glow already skips IF.
        "shape_scale": 1.0,
        "batch_shared_filters": True,
    },
}


class RenderProfile(NamedTuple):
    """Coordinated render settings for Ctrl+Shift+3 product cycling.

    ``label`` is shown in the system HUD feedback. Composition stays hybrid
    (sharp geometry + scaled FX). Batch matches the quality preset.
    ``max`` is not on this ladder (API / diagnostic only).
    """

    label: str
    quality: FxQuality
    batch_shared_filters: bool


def _batch_for(q: FxQuality) -> bool:
    return bool(_PRESETS[q]["batch_shared_filters"])


# Perf → fidelity product ladder. Default authoring spot is ``high``.
RENDER_PROFILES: Tuple[RenderProfile, ...] = (
    RenderProfile("low", FxQuality.LOW, _batch_for(FxQuality.LOW)),
    RenderProfile("medium", FxQuality.MEDIUM, _batch_for(FxQuality.MEDIUM)),
    RenderProfile("high", FxQuality.HIGH, _batch_for(FxQuality.HIGH)),
)


def preset_for(quality: FxQuality) -> Dict[str, object]:
    return dict(_PRESETS[FxQuality._from_value(quality)])


def next_quality(current) -> FxQuality:
    """Advance low → medium → high → low. ``max`` steps to ``low``."""
    q = FxQuality._from_value(current)
    if q is FxQuality.MAX:
        return QUALITY_CYCLE[0]
    i = QUALITY_CYCLE.index(q)
    return QUALITY_CYCLE[(i + 1) % len(QUALITY_CYCLE)]


def profile_index_for_quality(quality) -> int:
    """Best matching ``RENDER_PROFILES`` index for an ``FxQuality`` value.

    ``max`` maps to the ``high`` rung so a subsequent product cycle continues
    low → medium → high without exposing the diagnostic profile.
    """
    q = FxQuality._from_value(quality)
    if q is FxQuality.MAX:
        q = FxQuality.HIGH
    for i, profile in enumerate(RENDER_PROFILES):
        if profile.quality == q:
            return i
    return QUALITY_CYCLE.index(DEFAULT_FX_QUALITY)


class HeroLod(NamedTuple):
    """Shared multipass budget for hero energy looks (Neon, Laser, Electric*, …)."""

    passes: int
    mask: bool
    pe_hz: float


# --- Activate-once slots (draw path: load only; never lookup framework) -----

_HERO_LOD_TABLE: Dict[FxQuality, HeroLod] = {
    FxQuality.MAX: HeroLod(3, True, 24.0),
    FxQuality.HIGH: HeroLod(3, True, 18.0),
    FxQuality.MEDIUM: HeroLod(2, False, 8.0),
    FxQuality.LOW: HeroLod(1, False, 4.0),
}

_PARTICLE_TABLE: Dict[FxQuality, float] = {
    FxQuality.MAX: 1.0,
    FxQuality.HIGH: 1.0,
    FxQuality.MEDIUM: 0.75,
    FxQuality.LOW: 0.5,
}

_TIER_TABLE: Dict[FxQuality, int] = {
    FxQuality.MAX: TIER_HIGH,
    FxQuality.HIGH: TIER_HIGH,
    FxQuality.MEDIUM: TIER_MED,
    FxQuality.LOW: TIER_LOW,
}

# Module slots — default HIGH; rewritten only in activate_quality.
_active_quality: FxQuality = DEFAULT_FX_QUALITY
_tier: int = TIER_HIGH
_hero_lod: HeroLod = _HERO_LOD_TABLE[DEFAULT_FX_QUALITY]
_particle: float = 1.0
_outer_glow_scale_cap: float = 1.0


def activate_quality(quality) -> FxQuality:
    """Single writer for all draw-path globals. Call from orchestration only."""
    global _active_quality, _tier, _hero_lod, _particle, _outer_glow_scale_cap
    q = FxQuality._from_value(quality)
    _active_quality = q
    _tier = _TIER_TABLE[q]
    _hero_lod = _HERO_LOD_TABLE[q]
    _particle = float(_PARTICLE_TABLE[q])
    # HIGH/MED: GlowFilter filter DAG. LOW uses filterless radial survival.
    _outer_glow_scale_cap = 1.0
    return q


def fidelity_tier() -> int:
    """Active recipe tier (``TIER_LOW`` / ``TIER_MED`` / ``TIER_HIGH``). Hot path."""
    return _tier


def fidelity_is_lite() -> bool:
    """True when lite or survival multipass should run (not full HIGH recipes)."""
    return _tier <= TIER_MED


def fidelity_is_survival() -> bool:
    """True when survival (distinct, cheapest) paths should run."""
    return _tier == TIER_LOW


def particle_scale(quality=None) -> float:
    """Relative particle budget for SpatialFx (1.0 = high/max).

    When ``quality`` is omitted, returns the activate-slot value (hot path).
    """
    if quality is None:
        return _particle
    q = FxQuality._from_value(quality)
    return float(_PARTICLE_TABLE.get(q, 1.0))


def active_fx_quality() -> FxQuality:
    """Current activated ``FxQuality`` (slot; no framework lookup)."""
    return _active_quality


def fidelity_is_max(quality=None) -> bool:
    """True when diagnostic max fidelity is active (batch off, full scales)."""
    if quality is None:
        return _active_quality is FxQuality.MAX
    return FxQuality._from_value(quality) is FxQuality.MAX


def hero_fx_lod(quality=None) -> HeroLod:
    """Pass count / MaskFilter / PE cap for multipass energy looks.

    Hot path (no arg): returns the cached slot object — do not mutate.
    With ``quality=``: returns the preset for that level (for tests / tools).
    """
    if quality is None:
        return _hero_lod
    q = FxQuality._from_value(quality)
    return _HERO_LOD_TABLE.get(q, _HERO_LOD_TABLE[DEFAULT_FX_QUALITY])


def outer_glow_scale_cap() -> float:
    """Extra GlowFilter blur clamp multiplier for filter_at_scale (usually 1.0)."""
    return _outer_glow_scale_cap


# Ensure cold import matches HIGH default slots.
activate_quality(DEFAULT_FX_QUALITY)
