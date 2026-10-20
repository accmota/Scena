"""
Collision system: opt-in colliders, snapshot broad phase, layered narrow phase.

Frame phase (owned by ScenaFramework):
  proxy AABB (cheap closed-form when possible) → broad phase
  → lazy world prims (exact) → prim AABB reject → narrow
  → enter/stay/exit events → sweep-and-slide resolve (declared pairs).

Proxy AABBs prefer a cheap, never-too-tight bound (`_proxy_aabb_for_shape`) so
rotation does not force a full prim rebuild every frame; translation-only still
mutates four floats in place. Exact world prims are built only for overlapping
pairs. Math runs on plain floats / NumPy, never on live Attributes.
Resolution helpers on CollisionInfo remain author-triggered for the manual ladder;
standing ``resolve()`` uses sweep-and-slide, not end-of-frame MTV.
"""

from __future__ import annotations

import inspect
import math
import os
import time
import warnings
import weakref
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

import numpy as np
import skia

from .scenamath import Vec2
from .validate import call_truncated as _call
from .validate import finite as _finite
from .validate import fixed_magnitude as _fixed_magnitude
from .validate import magnitude as _magnitude
from .validate import number as _number
from .validate import refuse_async as _refuse_async
from .closed import ClosedSurface
from .state import DIRTY_POSE_CELLS, probe_private


from .purity_check import _READING as _SOLVER_READING, check_read_only, refuse_if_solver_reading


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

# ---------------------------------------------------------------------------
# Kinds / constants
# ---------------------------------------------------------------------------

class PrimKind(IntEnum):
    CIRCLE = 0
    AABB = 1
    OBB = 2
    ELLIPSE = 3
    POLY = 4


# Packed params layout (max 8 floats per primitive):
# CIRCLE:  cx, cy, r
# AABB:    minx, miny, maxx, maxy
# OBB:     cx, cy, hw, hh, angle_rad
# ELLIPSE: cx, cy, rx, ry, angle_rad
# POLY:    offset into vertex buffer, vertex count, (unused…)

_ANGLE_EPS = 1e-6
# Tiny pad on collider proxy AABBs for float robustness (not a fat/rotation proxy).
_PROXY_EPS = 0.5
# Sweep-and-slide skin (Godot safe_margin): resolve() stops a body this far
# short of the contact, so a resting pair is a small gap, not an overlap.
_RESOLVE_SLOP = 0.08
# Detection skin for standing resolve() pairs: a gap this small still counts as
# a contact for @collide / stay / exit, so a body resting ``_RESOLVE_SLOP`` above
# a floor does not flicker with frame time (F1, Collision Design § Resting
# contact). Twice the slop: margin for the gap settle / snap actually leave.
_CONTACT_SKIN = 2.0 * _RESOLVE_SLOP
_MAX_SLIDES = 4
# Simultaneous contacts (Collision Design § Joint stop, LW2): the partners a
# sweep reaches within the contact skin of its earliest hit are answered
# together (velocity and leftover), not one after the other in partner order.
# At most this many in one stop; more answer one at a time. False is the old
# one-at-a-time stop (A/B, canary).
_JOINT_RESPONSE = True
_JOINT_MAX = 4
# Bounce sub-step (Collision Design § Resolution, step 3; LW7): after a stop,
# the closing part of the frame's leftover gets the restitution the velocity
# got, so a bounce keeps the rest of its travel (``bounce=0``: the slide, as
# before). False drops it, as before (A/B, canary).
_BOUNCE_SUBSTEP = True
# A resolve partner a handler removed this step is a still wall for its
# survivor's sweep, for this step only (Collision Design § Partner removed by a
# handler; PE5). False: the velocity-only ghost response (A/B, canary).
_GHOST_WALLS = True
# A resting-skin contact the handlers saw, that the sweep never reached, is
# answered this step for an airborne body on a ``bounce > 0`` pair (Collision
# Design § Resting contact (skin); LW8). False: not answered (A/B, canary).
_SKIN_ANSWER = True
# Seam lip (Collision Design § Seam lips): a grounded body that walks into the
# side face of a still partner whose top is at most this far above its feet
# steps onto it instead of stopping (solid) or passing into it (one-way). Two
# tiles placed a hair apart (a rotated row, integer coordinates, a scaled hull)
# leave such a lip at the seam. 0 turns the rule off (bench A/B).
_SEAM_STEP = 2.0
# Swept detection (Collision Design § Swept detection): a collider whose
# motion-channel travel this frame exceeds this fraction of its thickness
# (smaller proxy side, pad removed) is detected along its path. Below it two
# bodies cannot pass through each other within one frame (relative travel <
# thick_a + thick_b, with room for a rotated proxy's sqrt(2)). ``math.inf``
# restores end-pose-only detection (bench A/B, canary tests).
_FAST_MOTION_FRACTION = 0.5
_SETTLE_BIAS = 0.5
_SETTLE_MAX = 8.0
_SETTLE_ITERS = 4
# A box whose every edge moved with this frame's motion channel, within this
# tolerance, is a swept translation. Larger than skin and proxy noise; smaller
# than a real resize. Unswept recovery does not run for that case.
_UNSWEPT_MOTION_TOL = 0.75
_FLOOR_SNAP_MIN = 16.0
# ``floor_below``: sideways sub-step of the up / across / drop march (DU), and
# the extra lift over a 45° rise so a cast along the steepest floor does not
# graze it as a wall.
_FLOOR_PROBE_STEP = 8.0
_FLOOR_PROBE_LIFT_MARGIN = 1.0
# ``floor_below`` fast path (Collision Design, "floor_below: cost"): trust the
# partners' world prims for the march and drop partners outside the march
# envelope once. False is the plain march (the oracle in
# tests/test_floor_below_fast.py and the bench A/B switch).
_FLOOR_PROBE_FAST = True
# A Sprite hull (or SpatialFx "poly" spec) that is exactly an axis-aligned
# rectangle becomes an AABB prim, like an unrotated Rect, so it takes the
# closed-form narrow phase and sweep instead of SAT / GJK (Collision Design,
# "Axis-aligned hulls"). False keeps the POLY (oracle, bench A/B).
_HULL_AABB = True
# Resolve partner lists are dropped only by an event that can change one: a
# member joining / leaving a tag that is a resolve() side, or an enroll /
# leave while a side expands by identity (ANYTHING, an object, a part, a
# snapshot group). Pair edits always drop them. False drops them on every
# enroll and tag change (the old rule; oracle and bench A/B). Collision
# Design, "Partners".
_PARTNER_CACHE_SELECTIVE = True
# A Sprite's pose key read straight from its fields where a field read would
# return the stored value anyway (no anchor, no link, classified bare); any
# other state takes the generic key. Same tuple either way (Collision
# Design, "World prims / pose keys"). False: always generic (oracle, A/B).
_SPRITE_POSE_KEY_FAST = True
# query_shape rejects a candidate whose proxy box misses the probe's before
# building world prims, as the other queries do (games.md B3). False: the old
# walk (oracle).
_QUERY_SHAPE_REJECT = True
# Pose revision (Collision Design, "Pose revision"): a trusted body whose
# ``_pose_rev`` has not moved since its proxy was built keeps it without a
# pose key. False: always the key (oracle, A/B).
_POSE_REV_SKIP = True
# Test / debug mode: every skip also builds the key and raises when they
# disagree (a pose writer that forgot ``bump_pose_rev``). run_tiers sets it.
_POSE_REV_VERIFY = os.environ.get("SCENA_VERIFY_POSE_REV") == "1"
# Vectorized query candidates (Collision Design, "Moved set and vectorized
# candidates"): between steps only moved / untrusted proxies are refreshed,
# and a group's candidates are masked against the query box in numpy. False:
# every candidate is refreshed and tested in Python (oracle, A/B).
_QUERY_VECTOR = True
# One convex polygon (box, turned box, hull) swept against another takes the
# closed-form swept SAT instead of conservative advancement (Collision Design,
# "Polygon sweeps"). False: GJK advancement (oracle, A/B).
_SWEEP_SAT = True
# A sweep stop between two movable bodies splits the leftover approach by
# inverse mass, as settle does (Collision Design, "Relative-frame sweep"): the
# body takes its share and the partner is pushed by the rest. False: the body
# swept first takes it all, whatever the masses (the old rule; A/B).
_SWEEP_MASS_SPLIT = True
# Settle with no remembered contact normal pushes a pair apart along the
# minimum-overlap axis (PE1). False: the old rule, which flipped that axis
# when the pair's velocities separated along it, so two overlapping bodies
# moving apart (or a ball spawned in a wall, moving into the room) were
# pushed through each other (oracle, canary).
_SETTLE_MIN_OVERLAP = True
# A body standing on a moving resolve partner moves with it (PB2, Collision
# Design "Riders"): ``_carry_riders`` adds the partner's displacement to the
# rider's motion before the sweeps. False: the old rule, where the only carry
# was the relative sweep's leftover ``d_other x (1 - t)``, so a sideways lift
# carried its rider 97 % at 30 fps and 1 % at 240 (oracle, A/B).
_RIDER_CARRY = True
# Riders stacked on riders deeper than this are not carried (a guard, not a
# limit any game meets).
_CARRY_DEPTH = 16
# A body that stops on a floor (no sideways intent) or is snapped onto one
# backs off along its own motion, not the normal, so an idle body on a slope
# does not creep downhill by ``slop * sin(slope)`` a frame (PE2). Only when the
# motion meets the surface within 60 degrees of its normal (a walkable floor
# under a fall always does). False: always along the normal (oracle, A/B).
_SKIN_ALONG_MOTION = True
_SKIN_MOTION_COS = 0.5
# Settle and unswept recovery split a correction between two movable bodies
# without pushing either into a STATIC partner of its own (PE3,
# ``_nudge_pair_along``); the other takes the rest. False: the plain mass
# split, which pressed a light crate under a heavy one into the floor
# (oracle, A/B).
_SETTLE_STATIC_CLAMP = True
# A sweep stop between two movable bodies sweeps the body's unswept travel
# (the leftover it inherits from the partner, plus its follow) against its own
# STATIC partners, and the partner takes back what it could not travel (PE4,
# ``_share_sweep_stop``). False: that travel is placed (oracle, A/B).
_SWEEP_INHERIT_CLAMP = True
# Resolve partner scans (sweep casts, settle and recovery passes, floor_below
# without group=) prefilter a large pool on the proxy mirror, then run the
# same exact test on what is left (Collision Design, "Moved set and
# vectorized candidates"). False: every partner in Python (oracle, A/B).
_RESOLVE_VECTOR = True
_POOL_VECTOR_MIN = 128
# The resolve pass reads one partner list per signature (the on-side flags of
# a body per registration), shared by every body with it and skipping the body
# itself: a crowd's lists and rows are built once, not once per body, when
# the crowd changes (Collision Design, "Shared partner lists"). False: one
# list per body (oracle, A/B).
_SHARED_PARTNERS = True
# One prefilter query per body's resolve turn (``_PartnerPool.localize``): its
# frame box padded by ``_LOCAL_PAD`` DU. False: every pass asks numpy (A/B).
_LOCAL_PREFILTER = True
_LOCAL_PAD = 8.0
# The step skips still bodies where the answer is already in place: stored
# resolve bounds of a collider whose pose key is the same object, and
# touching_* of bodies that touch nothing now and did not before (Collision
# Design, "Step cost"). False: the full walks (oracle, A/B).
_STEP_SKIP_STILL = True
_INF_BOX = (-math.inf, -math.inf, math.inf, math.inf)


def _mirror_row(c) -> Tuple[float, ...]:
    """One proxy-mirror row: the proxy (infinite when invalid), this frame's
    motion, and the box over the frame (start and end proxy), with the same
    arithmetic as ``_earliest_toi``'s partner reject."""
    p = c._proxy if c._proxy_valid else _INF_BOX
    odx = c._motion_dx
    ody = c._motion_dy
    if odx > 0.0:
        lox, hix = p[0] - odx, p[2]
    else:
        lox, hix = p[0], p[2] - odx
    if ody > 0.0:
        loy, hiy = p[1] - ody, p[3]
    else:
        loy, hiy = p[1], p[3] - ody
    return (p[0], p[1], p[2], p[3], odx, ody, lox, loy, hix, hiy)


def _rows_meeting(b, rows, c0: int, x0, y0, x1, y1) -> List[int]:
    """Positions in ``rows`` whose box (columns ``c0``..``c0+3`` of the mirror
    ``b``) meets ``(x0, y0, x1, y1)``, inclusive like ``_proxy_aabb_overlap``.

    A pool much smaller than the mirror copies its rows; a large one masks
    whole columns (contiguous) and then picks its rows.
    """
    if len(rows) * 4 < b.shape[0]:
        b = b[rows]
        mask = ~((b[:, c0] > x1) | (x0 > b[:, c0 + 2]) | (b[:, c0 + 1] > y1) | (y0 > b[:, c0 + 3]))
    else:
        mask = ~((b[:, c0] > x1) | (x0 > b[:, c0 + 2]) | (b[:, c0 + 1] > y1)
                 | (y0 > b[:, c0 + 3]))[rows]
    return np.flatnonzero(mask).tolist()


class _SharedPartners:
    """One signature's partner list (``CollisionSystem._shared_partners``)."""

    __slots__ = ("ident", "only", "conflicts", "rows", "_pos")

    def __init__(self, ident, only, conflicts):
        self.ident = ident
        self.only = only
        self.conflicts = conflicts
        self.rows = None           # (ident, struct version, rows, member ids)
        self._pos = None

    def position(self, c) -> int:
        """``c``'s index in the list, or -1."""
        pos = self._pos
        if pos is None:
            pos = self._pos = {id(x): i for i, (x, _t) in enumerate(self.ident)}
        return pos.get(id(c), -1)


class _PartnerPool:
    """A body's resolve partners as rows of the proxy mirror (B2).

    Iterates as the plain list would, ``(collider, token, odx, ody)`` in
    partner order (``still``: motion 0, the seam step's casts). The ``near``
    methods give the positions whose mirror row passes the same test the
    scan applies; the scan still applies it (the mirror is a prefilter).
    """

    __slots__ = ("cs", "ident", "rows", "members", "still", "owner", "local")

    def __init__(self, cs, ident, rows, members, still=False, owner=-1):
        self.cs = cs
        self.ident = ident
        self.rows = rows
        self.members = members        # ids of the partner colliders
        self.still = still
        # ``ident`` may be a shared list (every body of one signature): the
        # body's own position, skipped by every view, or -1.
        self.owner = owner
        # ``(x0, y0, x1, y1, positions)`` once ``localize`` ran: the partners
        # whose frame box meets that box (a superset for any query inside it).
        self.local = None

    def localize(self, ca) -> None:
        """One query for the body's whole turn: the partners near its box over
        the frame, padded by ``_LOCAL_PAD``. A later query whose box fits
        inside reads them (``_local``); one that does not asks numpy again.

        Exact: during the turn only the body and the partner being handled
        move, and that partner is already in the list (it passed a test).
        """
        if not ca._proxy_valid:
            return
        row = _mirror_row(ca)
        m = _LOCAL_PAD
        x0, y0, x1, y1 = row[6] - m, row[7] - m, row[8] + m, row[9] + m
        got = _rows_meeting(self.cs._box_array(), self.rows, 6, x0, y0, x1, y1)
        if self.owner >= 0 and self.owner in got:
            got.remove(self.owner)
        self.local = (x0, y0, x1, y1, got)

    def _local(self, x0, y0, x1, y1):
        loc = self.local
        if loc is not None and loc[0] <= x0 and loc[1] <= y0 and loc[2] >= x1 and loc[3] >= y1:
            return list(loc[4])
        return None

    def __len__(self):
        return len(self.ident) - (self.owner >= 0)

    def __bool__(self):
        return len(self) > 0

    def __iter__(self):
        own = self.owner
        if self.still:
            for i, (c, tok) in enumerate(self.ident):
                if i != own:
                    yield (c, tok, 0.0, 0.0)
        else:
            for i, (c, tok) in enumerate(self.ident):
                if i != own:
                    yield (c, tok, c._motion_dx, c._motion_dy)

    def item(self, i):
        c, tok = self.ident[i]
        if self.still:
            return (c, tok, 0.0, 0.0)
        return (c, tok, c._motion_dx, c._motion_dy)

    def as_still(self):
        p = _PartnerPool(self.cs, self.ident, self.rows, self.members, True, self.owner)
        p.local = self.local            # frame boxes hold the proxies: still a superset
        return p

    def moves(self) -> bool:
        """Any partner with motion this frame (the sweep's idle test)."""
        if self.still:
            return False
        loc = self.local
        if loc is not None:
            # The idle sweep this answers can only hit partners near the body
            # (its prims sit in its proxy, inside the local box): a far mover
            # changes nothing it would find.
            ident = self.ident
            for i in loc[4]:
                c = ident[i][0]
                if abs(c._motion_dx) > 1e-12 or abs(c._motion_dy) > 1e-12:
                    return True
            return False
        m = np.abs(self.cs._box_array()[self.rows, 4:6]) > 1e-12
        if self.owner >= 0:
            m[self.owner] = False
        return bool(np.any(m))

    def near_box(self, x0, y0, x1, y1):
        """Positions whose proxy meets the box (``_proxy_aabb_overlap``), or a
        superset (the local list); the caller runs its own test."""
        got = self._local(x0, y0, x1, y1)
        if got is None:
            got = _rows_meeting(self.cs._box_array(), self.rows, 0, x0, y0, x1, y1)
            if self.owner >= 0 and self.owner in got:
                got.remove(self.owner)
        if _POSE_REV_VERIFY:
            self._verify(got, lambda p, _odx, _ody: not (
                p[0] > x1 or x0 > p[2] or p[1] > y1 or y0 > p[3]))
        return got

    def near_swept(self, sx0, sy0, sx1, sy1):
        """Positions whose box over the frame (start and end proxy) meets the
        swept box: ``_earliest_toi``'s reject, row for row."""
        got = self._local(sx0, sy0, sx1, sy1)
        if got is None:
            got = _rows_meeting(self.cs._box_array(), self.rows, 0 if self.still else 6,
                                sx0, sy0, sx1, sy1)
            if self.owner >= 0 and self.owner in got:
                got.remove(self.owner)
        if _POSE_REV_VERIFY:
            def keeps(pb, odx, ody):
                if odx > 0.0:
                    if pb[0] - odx > sx1 or sx0 > pb[2]:
                        return False
                elif pb[0] > sx1 or sx0 > pb[2] - odx:
                    return False
                if ody > 0.0:
                    if pb[1] - ody > sy1 or sy0 > pb[3]:
                        return False
                elif pb[1] > sy1 or sy0 > pb[3] - ody:
                    return False
                return True
            self._verify(got, keeps)
        return got

    def _verify(self, got, keeps) -> None:
        """Verify mode: every partner the Python test keeps is in ``got``."""
        have = set(got)
        for i, (c, _tok) in enumerate(self.ident):
            if i == self.owner:
                continue
            odx, ody = (0.0, 0.0) if self.still else (c._motion_dx, c._motion_dy)
            p = c._proxy if c._proxy_valid else _INF_BOX
            if keeps(p, odx, ody) and i not in have:
                raise AssertionError(
                    f"partner prefilter lost row {i} ({c!r}): the proxy mirror is stale"
                )


class _Pool(list):
    """A candidate list that also says whether the group had any (B2)."""
    has_others = False


# floor_below: "the group has ground, none near" — march with no partners.
_EMPTY_MARCH: list = []
# The Sprite pose hooks a fast key mirrors: a class that overrides any of
# them keeps the generic key.
_SPRITE_POSE_HOOKS = (
    "_collision_pose_extra", "_collision_pose_anchor", "_hitbox_pose_wh",
    "_hitbox_pose_src", "_du_per_px", "_draw_angle", "_flipped_art_angle",
    "_pull_property_anchors", "_is_hitbox_part", "_has_domain_frame",
)
# Probes kept for ``show_colliders`` when nothing draws (headless).
_FLOOR_PROBE_DEBUG_CAP = 256
# ``show_colliders`` outline colours (RGBA).
_DEBUG_RESOLVE_RGBA = (1.0, 0.85, 0.2, 1.0)    # gold: in a resolve() pair
_DEBUG_PART_RGBA = (0.2, 0.8, 1.0, 1.0)        # cyan: hitbox part (detect-only)
_DEBUG_DETECT_RGBA = (0.196, 0.804, 0.196, 1.0)  # green: detect-only body
_DEBUG_PROBE_FLOOR_RGBA = (1.0, 0.35, 0.9, 1.0)  # magenta: floor_below found a floor
_DEBUG_PROBE_NONE_RGBA = (1.0, 0.25, 0.2, 1.0)   # red: floor_below found none

# Chord-to-arc gap for a query_sector wedge. Past this, split the arc.
_SECTOR_ARC_ERROR = 0.25
_SECTOR_MAX_STEPS = 64
# Refuse floor snap only when the body is clearly jumping / bouncing away
# from the candidate floor. World-Y alone is wrong (rising rides).
# Normal-speed alone is also wrong for walkers: authors often set world-axis
# ``vel.x`` on slopes, which can look like tens of DU/s of "leave" while this
# frame's motion barely separates — snap must still run.
# Elastic pairs (``bounce > 0.5``) trust leave speed: last frame's impulse
# already wrote an honest separating ``.vel``, and ``leave_d`` in DU is
# ``~|vy|×dt`` so a 2 DU conjunct glues bounces at high FPS / moderate speed.
# Walkers still need displacement *or* a motion that is clearly along the
# normal (high-FPS jump: leave_d < 2 DU but leave_frac ≈ 1).
_FLOOR_SNAP_LEAVE_VY = 8.0
_FLOOR_SNAP_LEAVE_DIST = 2.0
_FLOOR_SNAP_ELASTIC_BOUNCE = 0.5
_FLOOR_SNAP_LEAVE_FRAC = 0.85
_SLIDE_EPS = 1e-7
# Stop-on-slope discards the post-contact slide only when this frame's own
# horizontal motion is about 0 (no walk intent). An absolute DU/frame cutoff
# ate real walk speed whenever gravity closed the floor slop.
_STOP_ON_SLOPE_INTENT = 1e-3
_TOI_ADVANCE_ITERS = 32
_TOI_BISECT_CAP = 96
_TOI_UNRESOLVED = object()

# Immovable mass sentinel for ``Graphic.mass`` / ``mtv_split`` / ``velocity_split``.
STATIC = float("inf")

# Sentinel: ``add_resolve_pair`` stores this when only position correction is wanted.
_RESOLVE_POSITION_ONLY = object()


def _resolve_token_is_elastic(token: Any) -> bool:
    """True when this pair's ``bounce=`` is elastic enough to trust leave speed."""
    if token is _RESOLVE_POSITION_ONLY or token is None:
        return False
    try:
        return float(token) > _FLOOR_SNAP_ELASTIC_BOUNCE
    except (TypeError, ValueError):
        return False


def _floor_snap_should_refuse(
    *,
    leave_v: float,
    leave_d: float,
    rel_motion_len: float,
    token: Any,
) -> bool:
    """Whether floor snap must stand down (body is leaving the candidate floor)."""
    if leave_v <= _FLOOR_SNAP_LEAVE_VY:
        return False
    if _resolve_token_is_elastic(token):
        return True
    if leave_d > _FLOOR_SNAP_LEAVE_DIST:
        return True
    if (
        rel_motion_len > _SLIDE_EPS
        and (leave_d / rel_motion_len) > _FLOOR_SNAP_LEAVE_FRAC
    ):
        return True
    return False


def _aabb_overlap_tuple(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    return not (a[0] > b[2] or b[0] > a[2] or a[1] > b[3] or b[1] > a[3])


def _is_fast_narrow(pa: "Prim", pb: "Prim") -> bool:
    """True when narrow_phase uses a dedicated non-SAT path."""
    ka, kb = pa.kind, pb.kind
    return (
        (ka == PrimKind.CIRCLE and kb == PrimKind.CIRCLE)
        or (ka == PrimKind.AABB and kb == PrimKind.AABB)
        or (ka == PrimKind.CIRCLE and kb == PrimKind.AABB)
        or (ka == PrimKind.AABB and kb == PrimKind.CIRCLE)
    )


class _AnythingType:
    """Sentinel: collide with every other participant (``@collide(x, ANYTHING)``)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ANYTHING"

    def __hash__(self) -> int:
        return id(self)


ANYTHING = _AnythingType()

# Phase names for pair handlers / dispatch
_PHASE_ENTER = "enter"
_PHASE_STAY = "stay"
_PHASE_EXIT = "exit"

# One-shot warning when bounce= resolve hits a body without ``.vel``.
_vel_missing_warned: Set[int] = set()

def _vec2_components(v: Union[Vec2, Tuple[float, float], Sequence[float]]) -> Tuple[float, float]:
    if isinstance(v, Vec2):
        vx = float(v.x.value) if hasattr(v.x, "value") else float(v.x)
        vy = float(v.y.value) if hasattr(v.y, "value") else float(v.y)
        return vx, vy
    return float(v[0]), float(v[1])


def _normal_components(normal: Vec2) -> Tuple[float, float]:
    nx = float(normal.x.value) if hasattr(normal.x, "value") else float(normal.x)
    ny = float(normal.y.value) if hasattr(normal.y, "value") else float(normal.y)
    return nx, ny


def _slide_along(
    tangent: Union[Vec2, Tuple[float, float], Sequence[float]],
    velocity: Union[Vec2, Tuple[float, float], Sequence[float]],
) -> Vec2:
    """Project ``velocity`` onto ``tangent`` (walk/slide along a ramp)."""
    vx, vy = _vec2_components(velocity)
    tx, ty = _vec2_components(tangent)
    dot = vx * tx + vy * ty
    return Vec2.temp(dot * tx, dot * ty)


def _validate_mass(name: str, mass: float) -> float:
    ma = float(mass)
    if math.isnan(ma) or (not math.isfinite(ma) and ma != STATIC):
        raise ValueError(f"{name} must be positive or STATIC, got {mass!r}")
    if ma <= 0.0 and ma != STATIC:
        raise ValueError(f"{name} must be positive or STATIC, got {mass!r}")
    return ma


def _validate_bounce(bounce: float) -> float:
    """Finite restitution ``>= 0``. Rejects bools, strings, NaN, and negatives."""
    if isinstance(bounce, bool) or not isinstance(bounce, (int, float)):
        raise TypeError(
            f"bounce= must be a number >= 0 or omitted, got {bounce!r}"
        )
    b = float(bounce)
    if not math.isfinite(b) or b < 0.0:
        raise ValueError(f"bounce= must be a finite number >= 0, got {bounce!r}")
    return b


_ONLY_SIDES = ("top", "bottom", "left", "right")
_MIRROR_SIDE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
# Words authors reach for instead of a side. Sides are the first body's own
# sides (``touching_sides``), so a floor under it is "bottom".
_ONLY_SIDE_HINTS = {
    "floor": "bottom", "ground": "bottom", "feet": "bottom", "above": "bottom",
    "ceiling": "top", "head": "top", "below": "top",
}


def _normalize_only(only: Any) -> Any:
    """``only=`` for ``resolve()``: None, a frozenset of sides, or a callable.

    Sides are the first argument's sides, the same words as its
    ``touching_sides``. A list, tuple, set or frozenset is an OR (order does
    not matter, like ``group=``). All four sides is no filter (None).
    """
    if only is None:
        return None
    if isinstance(only, str):
        items: Tuple[Any, ...] = (only,)
    elif isinstance(only, (list, tuple, set, frozenset)):
        items = tuple(only)
        if not items:
            raise ValueError(
                "only= is empty, so the pair would never block. "
                "Use unresolve(...) to drop the pair."
            )
    elif callable(only):
        # An async only= returns a (truthy) coroutine: every contact would block.
        from .validate import refuse_async
        refuse_async(only, what="resolve() only=")
        return only
    else:
        raise TypeError(
            "only= takes a side (\"bottom\"), a list/tuple/set of sides, or a "
            f"function of the contact; got {type(only).__name__}"
        )
    for side in items:
        if not isinstance(side, str):
            raise TypeError(
                f"only= sides are strings (\"top\", \"bottom\", \"left\", "
                f"\"right\"); got {side!r}"
            )
        if side not in _ONLY_SIDES:
            hint = _ONLY_SIDE_HINTS.get(side.strip().lower())
            if hint is not None:
                extra = f' Did you mean "{hint}"?'
            elif "," in side or " " in side.strip():
                extra = ' For several sides use a set: only={"bottom", "left"}.'
            else:
                extra = ""
            raise ValueError(
                f"only={side!r} is not a side. Sides are the first body's own "
                'sides, as in its touching_sides: "top", "bottom", "left", '
                f'"right" ("bottom" = standing on it).{extra}'
            )
    sides = frozenset(items)
    if len(sides) == len(_ONLY_SIDES):
        return None
    return sides


def _mirror_only(spec: Any) -> Any:
    """The same ``only=`` sides seen from the second body (top↔bottom, left↔right)."""
    return frozenset(_MIRROR_SIDE[side] for side in spec)


def _only_code(spec: Any) -> str:
    if spec is None:
        return "no only="
    if isinstance(spec, frozenset):
        inner = ", ".join(f'"{side}"' for side in _ONLY_SIDES if side in spec)
        return f"only={{{inner}}}"
    return f"only={getattr(spec, '__name__', type(spec).__name__)}"


def _is_static_mass(mass: float) -> bool:
    ma = float(mass)
    return not math.isfinite(ma) or ma == STATIC


def _seam_candidate(hit: Tuple[float, float, float, Any, Any, float, float]) -> bool:
    """A sweep hit that a seam step may climb: a side face of a still partner."""
    _t, nx, ny, _cb, _tok, odx, ody = hit
    if odx or ody:
        return False
    return abs(nx) > abs(ny)


def _side_from_normal(nx: float, ny: float) -> Optional[str]:
    """Categorical contact side for body ``a`` (normal points from ``a`` toward ``b``).

    Design space is y-up: ``+x`` is ``right``, ``+y`` is ``top``. ``bottom`` means
    ``other`` is below ``a`` (standing on a floor).
    """
    if abs(nx) < 1e-12 and abs(ny) < 1e-12:
        return None
    # Ties (exact 45°) are top/bottom so a ramp at the walkability limit
    # still counts as a floor for snap, stop-on-slope, and tilt="ground".
    if abs(nx) > abs(ny):
        return "right" if nx > 0.0 else "left"
    return "top" if ny > 0.0 else "bottom"


@dataclass(frozen=True)
class TouchingContact:
    """Read-only per-pair contact summary for ``Graphic.touching_contacts``.

    Attributes:
        other: What this body touches.
        side: This body's side in contact: ``"top"`` · ``"bottom"`` · ``"left"`` ·
            ``"right"``.
        slope_angle: Surface slope in degrees (0 = flat floor).
        normal: Unit contact normal.
        tangent: Unit direction along the surface.
        point: Contact point, if known.
    """

    other: Any
    side: Optional[str]
    slope_angle: float
    normal: Vec2
    tangent: Vec2
    point: Optional[Tuple[float, float]] = None

    def slide_along(
        self,
        velocity: Union[Vec2, Tuple[float, float], Sequence[float]],
    ) -> Vec2:
        """Project ``velocity`` onto ``tangent`` (walk/slide along a ramp)."""
        return _slide_along(self.tangent, velocity)


def _only_contact(other: Any, nx: float, ny: float, points: Any) -> TouchingContact:
    """The contact an ``only=`` function sees, in the first argument's view.

    ``(nx, ny)`` already points from that body toward ``other`` (a Collider).
    ``point`` is the centroid of ``points`` when the solver has them, else
    None (a sweep contact is not settled yet).
    """
    n = math.hypot(nx, ny)
    if n > 1e-12:
        ux, uy = nx / n, ny / n
        tx, ty = -uy, ux
        slope = math.degrees(math.atan2(ty, tx))
    else:
        ux = uy = 0.0
        tx, ty = 1.0, 0.0
        slope = 0.0
    point = None
    if points:
        k = len(points)
        point = (
            sum(float(p[0]) for p in points) / k,
            sum(float(p[1]) for p in points) / k,
        )
    return TouchingContact(
        other=other._identity,
        side=_side_from_normal(ux, uy),
        slope_angle=slope,
        normal=Vec2(ux, uy),
        tangent=Vec2(tx, ty),
        point=point,
    )


class _OnlyGate:
    """``only=`` filter for one body's solve this frame (``_only_view``).

    ``ok`` answers whether the solver may make this contact; it never changes
    state. ``mark`` starts a pass. Callers mark only a contact the body really
    reaches: a rejected sweep hit earlier than any accepted one, or a rejected
    overlap in settle / unswept recovery. (A floor-snap probe may mark too; a
    pass with no overlap ends at the body's next solve.) Unfiltered partners
    of the same body always pass ``ok``.
    """

    __slots__ = ("_sys", "_ca", "_map", "_passing")

    def __init__(self, system: Any, ca: Any, only_map: Dict[int, Tuple[Any, bool]],
                 passing: Dict[int, Any]) -> None:
        self._sys = system
        self._ca = ca
        self._map = only_map
        self._passing = passing

    def ok(self, cb: Any, nx: float, ny: float, points: Any = None) -> bool:
        pid = id(cb)
        if self._passing.get(pid) is cb:
            return False
        entry = self._map.get(pid)
        if entry is None:
            return True
        spec, flip = entry
        if isinstance(spec, frozenset):
            # Set specs are stored in ``ca``'s view already (mirrored if needed).
            return _side_from_normal(nx, ny) in spec
        if flip:
            # ``ca`` is the second argument: the function sees the first's view.
            contact = _only_contact(self._ca, -nx, -ny, points)
        else:
            contact = _only_contact(cb, nx, ny, points)
        # Solver lock: cold-path writes inside the function raise
        # (``purity_check``). Only this branch pays for it.
        _SOLVER_READING.append(spec)
        try:
            return bool(spec(contact))
        finally:
            _SOLVER_READING.pop()

    def mark(self, cb: Any) -> None:
        self._sys._begin_passing(self._ca, cb)


class _QueryOnlyGate(_OnlyGate):
    """``only=`` filter for ``floor_below``: same answers, never starts a pass.

    A query reads the world; it must not change which one-way partners the
    solver lets the body through next step.
    """

    __slots__ = ()

    def mark(self, cb: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# CollisionInfo
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CollisionInfo:
    """Ephemeral contact payload for one overlapping pair (one frame).

    Slotted: a closed surface at no per-write cost (``info.nromal = …`` raises).

    Attributes:
        a: The first body of the pair.
        b: The second body.
        normal: Unit vector from ``a`` toward ``b``.
        depth: Overlap depth in design units.
        points: Contact points.
        a_hitbox: The Hitbox part of ``a`` that touched, or ``None`` (the body).
        b_hitbox: The Hitbox part of ``b`` that touched, or ``None``.
    """

    a: Any  # identity (Shape or Collider)
    b: Any
    normal: Vec2  # from a toward b (unit), or zero if unavailable
    depth: float
    points: List[Tuple[float, float]] = field(default_factory=list)
    a_hitbox: Any = None  # ``Hitbox`` part on a's side, or None (the body)
    b_hitbox: Any = None

    def _refuse_part_resolution(self, what: str) -> None:
        if self.a_hitbox is not None or self.b_hitbox is not None:
            part = self.a_hitbox if self.a_hitbox is not None else self.b_hitbox
            raise TypeError(
                f"info.{what}() on a hitbox-part contact ({part!r}); parts only "
                f"detect. Move the sprite yourself (knockback), or resolve bodies."
            )

    @property
    def point(self) -> Optional[Tuple[float, float]]:
        """One usable contact location: centroid of ``points``, or ``None`` if empty.

        Prefer this for VFX (explosion, marker). Face manifolds with two clip
        points yield the segment midpoint. Enter / stay fill ``points`` from the
        clip list, or a prim-support witness when the clip is empty, so
        ``point`` is a tuple while the pair overlaps. Exit keeps ``points``
        empty (no current contact — not last stay's locus).
        """
        pts = self.points
        n = len(pts)
        if n == 0:
            return None
        if n == 1:
            return pts[0]
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)

    @property
    def side(self) -> Optional[str]:
        """Which side of ``a`` is in contact (``top``/``bottom``/``left``/``right``)."""
        nx, ny = _normal_components(self.normal)
        return _side_from_normal(nx, ny)

    @property
    def slope_angle(self) -> float:
        """Surface angle in degrees from horizontal (0 = flat floor)."""
        nx, ny = _normal_components(self.normal)
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return 0.0
        tx, ty = -ny / nlen, nx / nlen
        return math.degrees(math.atan2(ty, tx))

    @property
    def tangent(self) -> Vec2:
        """Unit vector along the contact surface (perpendicular to ``normal``)."""
        nx, ny = _normal_components(self.normal)
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return Vec2.temp(1.0, 0.0)
        return Vec2.temp(-ny / nlen, nx / nlen)

    def slide_along(
        self,
        velocity: Union[Vec2, Tuple[float, float], Sequence[float]],
    ) -> Vec2:
        """Project ``velocity`` onto ``tangent`` (walk/slide along a ramp)."""
        return _slide_along(self.tangent, velocity)

    def mtv_split(
        self,
        *,
        mass_a: float = 1.0,
        mass_b: float = 1.0,
        slop: float = 0.0,
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Return (dx,dy) push for a and for b along the MTV.

        ``STATIC`` / infinite mass on one side takes the full push on the other.
        ``slop`` subtracts from ``depth`` before splitting (resolve skin epsilon).
        """
        nx, ny = _normal_components(self.normal)
        nlen = math.hypot(nx, ny)
        depth = max(0.0, float(self.depth) - float(slop))
        if depth <= 0.0 or nlen < 1e-12:
            return (0.0, 0.0), (0.0, 0.0)
        nx /= nlen
        ny /= nlen

        ma = _validate_mass("mass_a", mass_a)
        mb = _validate_mass("mass_b", mass_b)
        a_inf = _is_static_mass(ma)
        b_inf = _is_static_mass(mb)
        if a_inf and b_inf:
            return (0.0, 0.0), (0.0, 0.0)
        if a_inf:
            return (0.0, 0.0), (nx * depth, ny * depth)
        if b_inf:
            return (-nx * depth, -ny * depth), (0.0, 0.0)
        inv_a = 1.0 / ma
        inv_b = 1.0 / mb
        total = inv_a + inv_b
        wa = inv_a / total
        wb = inv_b / total
        return (-nx * depth * wa, -ny * depth * wa), (nx * depth * wb, ny * depth * wb)

    def velocity_split(
        self,
        *,
        mass_a: float = 1.0,
        mass_b: float = 1.0,
        bounce: float = 1.0,
        vel_a: Union[Vec2, Tuple[float, float], Sequence[float], None] = None,
        vel_b: Union[Vec2, Tuple[float, float], Sequence[float], None] = None,
    ) -> Tuple[Vec2, Vec2]:
        """Two-body impulse along ``normal``; returns ``(new_vel_a, new_vel_b)``."""
        ma = _validate_mass("mass_a", mass_a)
        mb = _validate_mass("mass_b", mass_b)
        if vel_a is None or vel_b is None:
            raise ValueError("velocity_split requires vel_a and vel_b")
        vax, vay = _vec2_components(vel_a)
        vbx, vby = _vec2_components(vel_b)
        nx, ny = _normal_components(self.normal)
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return Vec2.temp(vax, vay), Vec2.temp(vbx, vby)
        nx /= nlen
        ny /= nlen
        rvx, rvy = vax - vbx, vay - vby
        vn = rvx * nx + rvy * ny
        if vn <= 0.0:
            return Vec2.temp(vax, vay), Vec2.temp(vbx, vby)
        e = max(0.0, float(bounce))
        if _is_static_mass(ma) and _is_static_mass(mb):
            return Vec2.temp(vax, vay), Vec2.temp(vbx, vby)
        if _is_static_mass(ma):
            j = -(1.0 + e) * vn / (1.0 / mb)
            vbx -= (j / mb) * nx
            vby -= (j / mb) * ny
        elif _is_static_mass(mb):
            j = -(1.0 + e) * vn / (1.0 / ma)
            vax += (j / ma) * nx
            vay += (j / ma) * ny
        else:
            inv_sum = (1.0 / ma) + (1.0 / mb)
            j = -(1.0 + e) * vn / inv_sum
            vax += (j / ma) * nx
            vay += (j / ma) * ny
            vbx -= (j / mb) * nx
            vby -= (j / mb) * ny
        return Vec2.temp(vax, vay), Vec2.temp(vbx, vby)

    def push_apart(
        self,
        *,
        mass_a: Optional[float] = None,
        mass_b: Optional[float] = None,
        slop: float = _RESOLVE_SLOP,
    ) -> None:
        """Apply ``mtv_split`` via ``move_by`` on ``a`` and ``b``."""
        self._refuse_part_resolution("push_apart")
        a, b = self.a, self.b
        ma = _mass_or_static(a, mass_a)
        mb = _mass_or_static(b, mass_b)
        (dxa, dya), (dxb, dyb) = self.mtv_split(mass_a=ma, mass_b=mb, slop=slop)
        if dxa or dya:
            a.move_by(dxa, dya)
        if dxb or dyb:
            b.move_by(dxb, dyb)

    def bounce_apart(
        self,
        *,
        mass_a: Optional[float] = None,
        mass_b: Optional[float] = None,
        bounce: float = 1.0,
    ) -> None:
        """Apply ``velocity_split`` and write ``.vel`` on both bodies."""
        self._refuse_part_resolution("bounce_apart")
        a, b = self.a, self.b
        ma = _mass_or_static(a, mass_a)
        mb = _mass_or_static(b, mass_b)
        va = getattr(a, "_vel", None)
        vb = getattr(b, "_vel", None)
        # A side with no ``.vel`` is immovable (same as STATIC), not mass-1 at rest.
        a_static = _is_static_mass(ma) or va is None
        b_static = _is_static_mass(mb) or vb is None
        if a_static and b_static:
            if va is None and vb is None and not (
                _is_static_mass(ma) and _is_static_mass(mb)
            ):
                _warn_missing_vel_once(a, b)
            return
        writable_a = (not a_static) and va is not None
        writable_b = (not b_static) and vb is not None
        if not writable_a and not writable_b:
            _warn_missing_vel_once(a, b)
            return
        vel_a = va if va is not None else (0.0, 0.0)
        vel_b = vb if vb is not None else (0.0, 0.0)
        ma_imp = STATIC if va is None else ma
        mb_imp = STATIC if vb is None else mb
        nva, nvb = self.velocity_split(
            mass_a=ma_imp, mass_b=mb_imp, bounce=bounce, vel_a=vel_a, vel_b=vel_b,
        )
        if not a_static and va is not None:
            va.x, va.y = float(nva.x), float(nva.y)
        if not b_static and vb is not None:
            vb.x, vb.y = float(nvb.x), float(nvb.y)

    def resolve(self, *, bounce: Optional[float] = None, slop: float = _RESOLVE_SLOP) -> None:
        """Position split + optional velocity split for this pair."""
        self._refuse_part_resolution("resolve")
        self.push_apart(slop=slop)
        if bounce is not None:
            self.bounce_apart(bounce=bounce)

    def reflect_velocity(
        self,
        velocity: Union[Vec2, Tuple[float, float], Sequence[float]],
        *,
        restitution: float = 1.0,
    ) -> Vec2:
        """Reflect ``velocity`` about ``normal`` with restitution in [0, 1+]."""
        if isinstance(velocity, Vec2):
            vx = float(velocity.x.value) if hasattr(velocity.x, "value") else float(velocity.x)
            vy = float(velocity.y.value) if hasattr(velocity.y, "value") else float(velocity.y)
        else:
            vx, vy = float(velocity[0]), float(velocity[1])
        nx = float(self.normal.x.value) if hasattr(self.normal.x, "value") else float(self.normal.x)
        ny = float(self.normal.y.value) if hasattr(self.normal.y, "value") else float(self.normal.y)
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return Vec2.temp(vx, vy)
        nx /= nlen
        ny /= nlen
        e = max(0.0, float(restitution))
        # Only reflect the approaching component (v · n < 0 means moving into the surface
        # when normal points from a→b and velocity is of a… callers pass the moving body's
        # velocity; convention: normal points from other→me when reflecting me? We use
        # info.normal as stored (a→b). Reflecting a's velocity: if v·n > 0, a is moving
        # toward b's half-space along the separation normal — bounce by reflecting about n.
        # Standard: reflect v about n: v' = v - (1+e)(v·n)n when v·n > 0 (approaching along n
        # from a's side toward b). Actually separation normal from a to b: if a is penetrating
        # into b, we push a along -n. Approaching: v_a · n > 0.
        dot = vx * nx + vy * ny
        if dot > 0.0:
            factor = (1.0 + e) * dot
            vx -= factor * nx
            vy -= factor * ny
        return Vec2.temp(vx, vy)


def _warn_missing_vel_once(a: Any, b: Any) -> None:
    for body in (a, b):
        bid = id(body)
        if bid in _vel_missing_warned:
            continue
        if getattr(body, "_vel", None) is None:
            _vel_missing_warned.add(bid)
            warnings.warn(
                f"{body!r} has no .vel set; skipping velocity resolution for this pair. "
                f"Assign .vel before using bounce= on resolve().",
                stacklevel=4,
            )


_mass_missing_warned: Set[int] = set()


def _mass_or_static(body: Any, override: Optional[float]) -> float:
    """Mass for a push. A body with no ``mass`` attribute is immovable."""
    if override is not None:
        return float(override)
    mass = getattr(body, "mass", None)
    if mass is None:
        bid = id(body)
        if bid not in _mass_missing_warned:
            _mass_missing_warned.add(bid)
            warnings.warn(
                f"{body!r} has no .mass; treating it as STATIC for this push.",
                stacklevel=4,
            )
        return STATIC
    return float(mass)


# ---------------------------------------------------------------------------
# Snapshot primitives (plain data)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Prim:
    kind: PrimKind
    aabb: Tuple[float, float, float, float]  # minx, miny, maxx, maxy
    params: Tuple[float, ...] = ()
    verts: Optional[List[Tuple[float, float]]] = None  # world verts for POLY


def _aabb_from_circle(cx: float, cy: float, r: float) -> Tuple[float, float, float, float]:
    return (cx - r, cy - r, cx + r, cy + r)


def _aabb_from_obb(cx: float, cy: float, hw: float, hh: float, ang: float) -> Tuple[float, float, float, float]:
    c, s = math.cos(ang), math.sin(ang)
    # extents of rotated box
    ex = abs(c) * hw + abs(s) * hh
    ey = abs(s) * hw + abs(c) * hh
    return (cx - ex, cy - ey, cx + ex, cy + ey)


def _obb_corners(cx: float, cy: float, hw: float, hh: float, ang: float) -> List[Tuple[float, float]]:
    c, s = math.cos(ang), math.sin(ang)
    local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    out = []
    for lx, ly in local:
        out.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return out


# ---------------------------------------------------------------------------
# Shape → Prim snapshot
# ---------------------------------------------------------------------------

def _aabb_from_verts(verts: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    return (min(xs), min(ys), max(xs), max(ys))


def _stroke_half_width(shape) -> float:
    """Half-thickness for Line / Track stroke colliders (matches Line snapshot)."""
    thick = getattr(shape, "line_width", None)
    try:
        return max(0.5, abs(float(thick)) * 0.5) if thick is not None else 0.5
    except Exception:
        return 0.5


def _thin_obb_prim(
    x1: float, y1: float, x2: float, y2: float, half: float,
) -> List[Prim]:
    """One thin OBB (or degenerate circle) along a stroke segment."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return [Prim(PrimKind.CIRCLE, _aabb_from_circle(x1, y1, half), (x1, y1, half))]
    ang = math.atan2(dy, dx)
    cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
    hw, hh = length * 0.5, half
    aabb = _aabb_from_obb(cx, cy, hw, hh, ang)
    return [Prim(PrimKind.OBB, aabb, (cx, cy, hw, hh, ang))]


def _track_stroke_contours(
    shape,
) -> Tuple[List[List[Tuple[float, float]]], bool, float]:
    """World stroke contours + ring-close flag + half-width.

    Full window: one contour; ``ring_closed`` matches ``shape._closed`` (emit
    last→first for a ring). Trimmed window: open contours from
    ``_window_contours`` (never a gap-closing chord). Empty when nothing to stroke.
    """
    # Host tables: a reversed() view does not keep its own polyline after rebake.
    xs, ys, _s, closed, _rev = shape._tables()
    half = _stroke_half_width(shape)
    n = len(xs)
    if n < 2:
        return [], False, half
    _a, _b, full = shape._draw_window()
    if full:
        pts = [shape._world_of(xs[i], ys[i]) for i in range(n)]
        return [pts], bool(closed), half
    out: List[List[Tuple[float, float]]] = []
    for contour in shape._window_contours():
        if len(contour) < 2:
            continue
        out.append([shape._world_of(lx, ly) for lx, ly in contour])
    return out, False, half


def _track_stroke_world(shape) -> Tuple[List[Tuple[float, float]], bool, float]:
    """World polyline samples + closed flag + half-width for a Track stroke.

    For proxy AABB: flattens window contours into one point list. ``closed`` is
    True only for a full closed window (ring). Trimmed windows report
    ``closed=False`` so callers must not invent a last→first segment.
    """
    contours, closed, half = _track_stroke_contours(shape)
    if not contours:
        return [], False, half
    if len(contours) == 1:
        return contours[0], closed, half
    pts: List[Tuple[float, float]] = []
    for c in contours:
        pts.extend(c)
    return pts, False, half


def _track_stroke_prims(shape) -> List[Prim]:
    """Chain of thin OBBs along a Track polyline (stroke collider, not filled area).

    Honors ``begin``/``end``: trimmed stroke = open OBB chains only (no chord
    across the invisible gap). Full closed window keeps the ring close.
    """
    contours, ring_closed, half = _track_stroke_contours(shape)
    out: List[Prim] = []
    for pts in contours:
        n = len(pts)
        if n < 2:
            continue
        segs = n if ring_closed else n - 1
        for i in range(segs):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            out.extend(_thin_obb_prim(ax, ay, bx, by, half))
    return out


_proxy_kinds: Optional[tuple] = None


def _load_proxy_kinds() -> tuple:
    """Kinds ``_proxy_aabb_for_shape`` dispatches on, imported once (cycles)."""
    global _proxy_kinds
    from .shapes import (
        Circle, Ellipse, Line, Point, Polygon, _RectBody, _RadialPolygon,
        get_xy, _bare_num,
    )
    from .sprite import Sprite
    from .track import Track
    _proxy_kinds = (
        Circle, Ellipse, Line, Point, Polygon, _RectBody, _RadialPolygon,
        get_xy, _bare_num, Sprite, Track,
    )
    return _proxy_kinds


def _proxy_aabb_for_shape(shape) -> Optional[Tuple[float, float, float, float]]:
    """Cheap, possibly-loose (never-too-tight) bound for the broad-phase proxy.

    Uses cached local extents / circumradius so rotation never forces a
    vertex or sub-shape rebuild. Returns ``None`` for kinds without a cheap
    closed form; caller unions exact prims for those.
    """
    # Runs for every collider whose pose is not a pure translation (every
    # spinner, every frame): a per-call ``from … import`` block costs about
    # as much as the bound itself.
    (
        Circle, Ellipse, Line, Point, Polygon, _RectBody, _RadialPolygon,
        get_xy, _bare_num, Sprite, Track,
    ) = _proxy_kinds or _load_proxy_kinds()

    if getattr(type(shape), "_is_hitbox_part", False):
        # Body extents placed by the paint transform (tilt, seat); no prims.
        return shape._proxy_aabb()

    if getattr(shape, "_main_hitbox_off", False):
        return None   # the caller finds no prims: the proxy goes invalid

    if isinstance(shape, Sprite):
        shape._ensure_auto_baked()
        if (
            float(getattr(shape, "_hitbox_extent_x", 0.0) or 0.0) > 0.0
            or float(getattr(shape, "_hitbox_extent_y", 0.0) or 0.0) > 0.0
        ):
            # Every baked prim, and its own AABB, sits in ``|lx| <= ex*w,
            # |ly| <= ey*h`` about ``center``; ``_collision_specs`` turns it by
            # the same ``_draw_angle()``. The AABB of that turned box holds
            # every prim AABB. Extents follow the pose box (near-circle and
            # turned-ellipse bounds depend on its aspect). Offset is
            # rotation-free.
            w, h = shape._hitbox_pose_wh()
            w, h = abs(float(w)), abs(float(h))
            ex, ey = shape._hitbox_extents_for_pose(w, h)
            exw = ex * w
            eyh = ey * h
            rad = math.radians(float(shape._draw_angle()))
            c = abs(math.cos(rad))
            sn = abs(math.sin(rad))
            hx = c * exw + sn * eyh
            hy = sn * exw + c * eyh
            ox = float(shape._offset_x)
            oy = float(shape._offset_y)
            if ox or oy:
                pad = math.hypot(ox, oy)
                hx += pad
                hy += pad
            cx, cy = get_xy(shape.center, bare=True)
            return (cx - hx, cy - hy, cx + hx, cy + hy)
        cx, cy, w, h, ang_deg = shape._collision_frame()
        w, h = abs(float(w)), abs(float(h))
        ang = math.radians(float(ang_deg))
        hw, hh = w * 0.5, h * 0.5
        if abs(ang) < _ANGLE_EPS or abs(abs(ang) - math.pi) < _ANGLE_EPS:
            return (cx - hw, cy - hh, cx + hw, cy + hh)
        return _aabb_from_obb(cx, cy, hw, hh, ang)

    if isinstance(shape, Circle):
        if shape.model is _circle_center_radius():   # common case: direct Defining reads
            cx, cy = get_xy(shape.center, bare=True)
            r = abs(_bare_num(shape.radius))
        else:
            cx, cy = shape._center_xy()      # Defining only (D3)
            r = abs(shape._radius_value())
        return _aabb_from_circle(cx, cy, r)

    if isinstance(shape, Point):
        cx, cy = get_xy(shape, bare=True)
        return _aabb_from_circle(cx, cy, 0.0)

    if isinstance(shape, Ellipse):
        cx, cy, w_e, h_e, rot_e = shape._oriented_frame()   # Defining only (D3)
        rx = w_e * 0.5
        ry = h_e * 0.5
        ang = math.radians(rot_e)
        return _aabb_from_obb(cx, cy, rx, ry, ang)

    if isinstance(shape, _RectBody):        # Rect / Square / Concave: the box
        oriented = getattr(shape, "_oriented_frame", None)
        if callable(oriented):
            cx, cy, w, h, ang_deg = oriented()
        else:
            cx, cy = get_xy(shape.center, bare=True)
            w = abs(_bare_num(shape.width))
            h = abs(_bare_num(shape.height))
            ang_deg = shape._rotation_value()
        w, h = abs(float(w)), abs(float(h))
        ang = math.radians(float(ang_deg))
        hw, hh = w * 0.5, h * 0.5
        if abs(ang) < _ANGLE_EPS or abs(abs(ang) - math.pi) < _ANGLE_EPS:
            return (cx - hw, cy - hh, cx + hw, cy + hh)
        return _aabb_from_obb(cx, cy, hw, hh, ang)

    if isinstance(shape, _RadialPolygon):   # RegularPolygon / Triangle
        cx, cy, r, _phi0 = shape._placement_params()
        r = abs(float(r))
        reach = type(shape)._reach_factor
        if reach is not None:               # Triangle: base corners past radius
            r *= reach(shape)
        return _aabb_from_circle(cx, cy, r)

    if isinstance(shape, Line):
        # Closed-form thin OBB from Defining endpoints — same math as exact
        # snapshot, without materializing Derivate p2/center/vec.
        x1, y1, x2, y2 = shape._segment_xy()
        half = _stroke_half_width(shape)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return _aabb_from_circle(x1, y1, half)
        ang = math.atan2(dy, dx)
        cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        return _aabb_from_obb(cx, cy, length * 0.5, half, ang)

    if isinstance(shape, Track):
        # Union of baked samples + stroke half-width (never tighter than prims).
        pts, _closed, half = _track_stroke_world(shape)
        if len(pts) < 2:
            return None
        minx, miny, maxx, maxy = _aabb_from_verts(pts)
        return (minx - half, miny - half, maxx + half, maxy + half)

    if isinstance(shape, Polygon):
        verts = [get_xy(v, bare=True) for v in shape.points]
        if len(verts) < 3:
            return None
        return _aabb_from_verts(verts)

    from .spatial_fx import SpatialFx
    if isinstance(shape, SpatialFx):
        # Cull AABB is a bloom pad — never tighter than collision_specs.
        return shape._domain_aabb()

    return None


def _prims_from_collision_specs(specs: Sequence) -> List[Prim]:
    """Build Prim list from SpatialFx.collision_specs() tuples."""
    out: List[Prim] = []
    for spec in specs or ():
        if not spec:
            continue
        kind = spec[0]
        if kind == "circle":
            _, cx, cy, r = spec
            cx, cy = float(cx), float(cy)
            r = max(0.0, abs(float(r)))
            out.append(Prim(PrimKind.CIRCLE, _aabb_from_circle(cx, cy, r), (cx, cy, r)))
        elif kind == "aabb":
            _, minx, miny, maxx, maxy = spec
            minx, miny, maxx, maxy = float(minx), float(miny), float(maxx), float(maxy)
            out.append(Prim(PrimKind.AABB, (minx, miny, maxx, maxy), (minx, miny, maxx, maxy)))
        elif kind == "obb":
            _, cx, cy, hw, hh, ang = spec
            cx, cy = float(cx), float(cy)
            hw, hh = max(0.0, abs(float(hw))), max(0.0, abs(float(hh)))
            ang = float(ang)
            aabb = _aabb_from_obb(cx, cy, hw, hh, ang)
            out.append(Prim(PrimKind.OBB, aabb, (cx, cy, hw, hh, ang)))
        elif kind == "ellipse":
            _, cx, cy, rx, ry, ang = spec
            cx, cy = float(cx), float(cy)
            rx, ry = max(0.0, abs(float(rx))), max(0.0, abs(float(ry)))
            ang = float(ang)
            aabb = _aabb_from_obb(cx, cy, rx, ry, ang)
            out.append(Prim(PrimKind.ELLIPSE, aabb, (cx, cy, rx, ry, ang)))
        elif kind == "poly":
            verts = spec[1]
            if not verts or len(verts) < 3:
                continue
            vlist = [(float(x), float(y)) for x, y in verts]
            aabb = _aabb_from_verts(vlist)
            if _HULL_AABB and len(vlist) == 4 and _is_axis_rect(vlist, aabb):
                out.append(Prim(PrimKind.AABB, aabb, aabb))
                continue
            out.append(Prim(PrimKind.POLY, aabb, (), list(vlist)))
    return out


def _is_axis_rect(
    verts: Sequence[Tuple[float, float]], aabb: Tuple[float, float, float, float],
) -> bool:
    """True when four vertices are exactly the four corners of ``aabb``.

    "Exactly" up to float noise (1e-9 of the coordinate scale): a hull turned
    by any real angle keeps its POLY. Zero area stays a POLY too.
    """
    minx, miny, maxx, maxy = aabb
    if not (maxx > minx and maxy > miny):
        return False
    tol = 1e-9 * max(1.0, abs(minx), abs(miny), abs(maxx), abs(maxy))
    corners = set()
    for x, y in verts:
        if abs(x - minx) <= tol:
            cx = 0
        elif abs(x - maxx) <= tol:
            cx = 1
        else:
            return False
        if abs(y - miny) <= tol:
            cy = 0
        elif abs(y - maxy) <= tol:
            cy = 1
        else:
            return False
        corners.add((cx, cy))
    return len(corners) == 4


_get_xy = None
_bare_attr = None


def _sync_auto_hitbox_frame(shape) -> bool:
    """If a Sprite clip frame left the baked auto hull, bump epoch and rebake."""
    # Class lookup: instance getattr("_play_frames") raises via Entity.__getattr__
    # on Circle/Shape (no such slot). Sprite still syncs clip frames.
    fn = getattr(type(shape), "_sync_auto_hitbox_frame", None)
    if fn is not None:
        fn(shape)
        # ``"clip"`` rebakes when the playing clip changes, which time alone
        # can do (a clip end with ``next=``): the step visits it every frame.
        return probe_private(shape, "_hitbox_from", None) == "clip"
    return False


def _ensure_pose_converters() -> None:
    global _get_xy, _bare_attr
    if _bare_attr is None:
        from .shapes import _bare_attr as _ba, get_xy as _gxy
        _bare_attr = _ba
        _get_xy = _gxy


def _pose_xy_of(obj) -> Optional[Tuple[float, float]]:
    """Bare (x, y) from a Point / Vec2 / 2-tuple, or None if it is not pose-like."""
    if obj is None:
        return None
    x = getattr(obj, "x", None)
    y = getattr(obj, "y", None)
    if x is not None and y is not None:
        try:
            return _bare_attr(x), _bare_attr(y)
        except Exception:
            pass
    try:
        return _get_xy(obj, bare=True)
    except Exception:
        return None


_CIRCLE_CR = None


def _circle_center_radius():
    """``CircleModel.CENTER_RADIUS`` (resolved once; shapes imports stay local)."""
    global _CIRCLE_CR
    if _CIRCLE_CR is None:
        from .shapes import CircleModel
        _CIRCLE_CR = CircleModel.CENTER_RADIUS
    return _CIRCLE_CR


def _collision_pose_xy(shape) -> Tuple[float, float]:
    """Translation anchor for the snapshot cache.

    Shapes use ``center``. Beam SpatialFx (Jet) use ``origin`` / ``p1`` instead —
    never treat the emitter itself as a Point. Kinds may override with
    ``_collision_pose_anchor`` when ``center`` would materialize a Derivate
    (Line: segment midpoint from Defining endpoints).
    """
    _ensure_pose_converters()
    anchor_fn = getattr(type(shape), "_collision_pose_anchor", None)
    if anchor_fn is not None:
        try:
            xy = anchor_fn(shape)
            if xy is not None:
                return (float(xy[0]), float(xy[1]))
        except Exception:
            pass
    # Graphics: Defining-only center. ``getattr(shape, "center")`` materializes
    # a cold Derivate center on non-center models (Rect corners, Polygon,
    # Ellipse foci …) and knocks the shape off the pose fast path for good (D3).
    center_fn = getattr(type(shape), "_center_xy", None)
    if center_fn is not None:
        xy = center_fn(shape)
        return (float(xy[0]), float(xy[1]))
    for name in ("center", "origin", "p1"):
        pt = getattr(shape, name, None)
        if pt is None or pt is shape:
            continue
        xy = _pose_xy_of(pt)
        if xy is not None:
            return xy
    aabb_fn = getattr(shape, "_domain_aabb", None)
    if callable(aabb_fn):
        try:
            minx, miny, maxx, maxy = aabb_fn()
            return (0.5 * (minx + maxx), 0.5 * (miny + maxy))
        except Exception:
            pass
    return (0.0, 0.0)


def _extra_slot_names(cls) -> Tuple[str, ...]:
    # Made with the class (entity._cache_class_tables), stored on it: never a
    # dict keyed by the class, which would keep an author's class alive (AC1).
    names = getattr(cls, "_scena_extra_slots", None)
    if names is None:
        from .entity import GRAPHIC_EXTRA_SLOTS
        names = tuple(
            n for n in GRAPHIC_EXTRA_SLOTS
            if getattr(getattr(cls, n, None), "_is_field_slot", False)
        )
    return names


def _live_scalar(shape, name: str) -> float:
    """Defining / live scalar from ``__dict__``, refreshing linked anchors."""
    d = shape.__dict__
    anchors = d.get("_field_anchors")
    if anchors:
        anchor = anchors.get(name)
        if anchor is not None:
            anchor._ensure_fresh()
    else:
        bare_ok = d.get("_scalar_bare_ok")
        if bare_ok is not None and bare_ok.get(name) is False:
            shape._refresh_scalar(name)
    val = d.get(name)
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _collision_graphic_extra(shape) -> tuple:
    """Live non-translational pose so ``.angle =`` / ``.radius =`` rebuild.

    ``_collision_epoch`` is bumped by ``rotate_to`` / ``scale=`` / hitbox writes,
    but Defining slot assigns (``rect.angle = …``, ``hex.angle = …``) often
    skip that path when no live Derivates force ``_update_impl``. Extra must read
    the slots themselves or the translate fast-path slides a stale hull.
    """
    cls = type(shape)
    extra_fn = getattr(cls, "_collision_pose_extra", None)
    if extra_fn is not None:
        try:
            extra = extra_fn(shape)
            if extra:
                return extra if type(extra) is tuple else tuple(float(v) for v in extra)
        except (TypeError, ValueError, AttributeError, ArithmeticError):
            pass
    d = shape.__dict__
    try:
        rot = float(object.__getattribute__(shape, "_rotation"))
    except (TypeError, ValueError, AttributeError):
        rot = 0.0
    try:
        scale = float(object.__getattribute__(shape, "_scale"))
    except (TypeError, ValueError, AttributeError):
        scale = 1.0
    parts = [rot, scale]
    names = _extra_slot_names(cls)
    for name in names:
        parts.append(_live_scalar(shape, name))
    if "spread" in names:
        # Pie (1) vs chord segment (0). Read the instance dict so other
        # Graphics do not pay Entity.__getattr__ on a missing name.
        parts.append(1.0 if d.get("_use_center") else 0.0)
    return tuple(parts)


def _raw_bare_scalar(d: dict, name: str) -> Optional[float]:
    """``d[name]`` when ``ScalarSlot.__get__`` would return it stored, else None.

    Mirrors the descriptor's own fast branch: no anchor on the owner, no
    link, the field already classified bare. A plain float / int only.
    """
    if d.get("_field_anchors") or d.get("_link") is not None:
        return None
    bare = d.get("_scalar_bare_ok")
    if bare is None or bare.get(name) is not True:
        return None
    v = d.get(name)
    t = type(v)
    if t is float:
        return v
    if t is int:
        return float(v)
    return None


def _sprite_pose_fast_class(cls) -> bool:
    """True when ``cls`` uses Sprite's own pose hooks (cached on the class)."""
    ok = cls.__dict__.get("_scena_pose_key_fast")
    if ok is None:
        from .sprite import Sprite
        ok = issubclass(cls, Sprite) and all(
            getattr(cls, n, None) is getattr(Sprite, n, None) for n in _SPRITE_POSE_HOOKS
        )
        type.__setattr__(cls, "_scena_pose_key_fast", ok)
    return ok


def _sprite_pose_key_fast(s) -> Optional[tuple]:
    """``_collision_pose_key`` of a plain Sprite, or None (take the generic one).

    The same tuple, built from the fields: ``(epoch, x, y, draw angle, scale,
    hitbox scale x / y, hitbox w / h, flip x / y, offset x / y)``.
    """
    d = s.__dict__
    if d.get("_field_anchors"):
        return None
    if s._hitbox_from == "each" and s._play_frames:
        return None
    w = _raw_bare_scalar(d, "width")
    h = _raw_bare_scalar(d, "height")
    p = d.get("center")
    if w is None or h is None or p is None:
        return None
    pd = p.__dict__
    cx = _raw_bare_scalar(pd, "x")
    cy = _raw_bare_scalar(pd, "y")
    if cx is None or cy is None:
        return None
    scale = float(s._scale)
    sa = abs(scale)
    px_w = float(s._hitbox_ref_src_w) or 1.0
    px_h = float(s._hitbox_ref_src_h) or 1.0
    rw = float(getattr(s, "_ref_src_w", 0.0) or 0.0)
    rh = float(getattr(s, "_ref_src_h", 0.0) or 0.0)
    kx = abs(w) / rw if rw else 1.0
    ky = abs(h) / rh if rh else 1.0
    flip_x = s._flip_x
    flip_y = s._flip_y
    a = float(s._art_angle)
    if flip_x:
        a = 180.0 - a
    if flip_y:
        a = -a
    hs = s._hitbox_scale
    return (
        int(getattr(s, "_collision_epoch", 0) or 0),
        cx, cy,
        float(float(s._rotation) - a),
        scale,
        float(hs[0]), float(hs[1]),
        float(px_w * kx * sa), float(px_h * ky * sa),
        1.0 if flip_x else 0.0,
        1.0 if flip_y else 0.0,
        float(s._offset_x), float(s._offset_y),
    )


def _pose_rev_kind(cls) -> int:
    """0: not trusted; 1: Rect / Square, Circle, Ellipse; 2: a plain Sprite.

    Kinds whose every pose input is written through a bumping path. Cached
    on the class."""
    ok = cls.__dict__.get("_scena_pose_rev_kind")
    if ok is None:
        from .shapes import Circle, Ellipse, Rect
        ok = 2 if _sprite_pose_fast_class(cls) else 0
        if not ok:
            for base in (Rect, Circle, Ellipse):
                if issubclass(cls, base):
                    same = all(getattr(cls, n, None) is getattr(base, n, None)
                               for n in ("_collision_pose_extra", "_collision_pose_anchor",
                                         "_center_xy", "_oriented_frame", "_pull_property_anchors",
                                         "_has_domain_frame", "_is_hitbox_part"))
                    ok = 1 if same else 0
                    break
        type.__setattr__(cls, "_scena_pose_rev_kind", ok)
    return ok


def _pose_untrusted_part(d: dict) -> bool:
    return bool(d.get("_field_anchors")) or d.get("_link") is not None or "_pull_owner" in d


def _pose_rev_of(shape) -> Optional[int]:
    """``shape``'s pose revision when it can be trusted, else None.

    Trusted: a kind whose writers all bump (``_pose_rev_kind``), with no link,
    anchor or pull owner on it or on its Defining parts (a linked value
    changes on a pull, with no write), and no per-frame hitbox
    (``hitbox_source="each"``). Links, anchors and pull owners move the trust
    epoch when they come or go (``state.bump_pose_trust``), so the check is
    cached per trust epoch: a move does not re-check it.
    """
    kind = _pose_rev_kind(type(shape))
    if not kind:
        return None
    d = shape.__dict__
    cell = d.get("_pose_cell")
    if cell is None:
        rev = epoch = 0
    else:
        rev = cell[0]
        epoch = cell[3]
    if kind == 2 and shape._hitbox_from == "each":
        return None
    cached = d.get("_pose_rev_trust")
    if cached is not None and cached[0] == epoch:
        return rev if cached[1] else None
    trusted = not _pose_untrusted_part(d)
    if trusted:
        parts = d.get("_defining_part_names") or ("center",)
        for name in parts:
            part = d.get(name)
            pd = getattr(part, "__dict__", None)
            if pd is not None and _pose_untrusted_part(pd):
                trusted = False
                break
    d["_pose_rev_trust"] = (epoch, trusted)
    return rev if trusted else None


def _collider_pose_revs(shapes) -> Optional[tuple]:
    """Every shape's trusted revision, or None if any is untrusted."""
    out = []
    for s in shapes:
        r = _pose_rev_of(s)
        if r is None:
            return None
        out.append(r)
    return tuple(out)


def _collision_pose_key(shape) -> tuple:
    """Cache key: collision epoch + world position + non-translational pose.

    Keys are ``(epoch, x, y, *extra)``. ``extra`` must stay identical for the
    translate fast-path (formation sway). SpatialFx put direction and size
    there (``_beam_frame`` / ``_pad_frame`` / ``_point_frame``) so rotate/stretch
    rebuilds instead of sliding a stale hull. Graphics put live angle / size
    (and Sprite current-frame source size) in extra so slot assigns that never
    bump ``_collision_epoch`` still rebuild.

    Frame methods are resolved on ``type(shape)`` — instance getattr would
    raise through ``Entity.__getattr__`` on every Sprite/Shape miss. Graphics
    skip those lookups via ``_has_domain_frame`` on SpatialFx domain bases.
    """
    cls = type(shape)
    if _SPRITE_POSE_KEY_FAST and cls.__dict__.get("_scena_pose_key_fast") is not False \
            and _sprite_pose_fast_class(cls):
        key = _sprite_pose_key_fast(shape)
        if key is not None:
            return key
    if getattr(cls, "_is_hitbox_part", False):
        return shape._pose_key()  # paint pose in one pass (hitbox.py)
    pull = getattr(cls, "_pull_property_anchors", None)
    if pull is not None:
        pull(shape)
    epoch = int(getattr(shape, "_collision_epoch", 0) or 0)
    if getattr(cls, "_has_domain_frame", False):
        beam_frame = getattr(cls, "_beam_frame", None)
        if beam_frame is not None:
            try:
                x0, y0, x1, y1, _length, width = beam_frame(shape)
                return (
                    epoch,
                    float(x0), float(y0),
                    float(x1) - float(x0), float(y1) - float(y0),
                    float(width),
                )
            except (TypeError, ValueError, AttributeError, ArithmeticError):
                pass
        pad_frame = getattr(cls, "_pad_frame", None)
        if pad_frame is not None:
            try:
                cx, cy, w, h = pad_frame(shape)
                return (epoch, float(cx), float(cy), float(w), float(h))
            except (TypeError, ValueError, AttributeError, ArithmeticError):
                pass
        point_frame = getattr(cls, "_point_frame", None)
        if point_frame is not None:
            try:
                parts = point_frame(shape)
                return (epoch,) + tuple(float(v) for v in parts)
            except (TypeError, ValueError, AttributeError, ArithmeticError):
                pass
    cx, cy = _collision_pose_xy(shape)
    return (epoch, cx, cy) + _collision_graphic_extra(shape)


def _translation_delta(old_key: tuple, new_key: tuple) -> Optional[Tuple[float, float]]:
    """``(dx, dy)`` when keys share epoch + extra pose; else None (rebuild)."""
    if (
        old_key is None
        or new_key is None
        or len(old_key) < 3
        or len(old_key) != len(new_key)
        or old_key[0] != new_key[0]
        or old_key[3:] != new_key[3:]
    ):
        return None
    return (new_key[1] - old_key[1], new_key[2] - old_key[2])


def _keys_uniform_translation(
    old_keys: Optional[tuple], new_keys: tuple
) -> Optional[Tuple[float, float]]:
    """Shared (dx, dy) if every shape key is a translation of the previous."""
    if old_keys is None or len(old_keys) != len(new_keys):
        return None
    delta: Optional[Tuple[float, float]] = None
    for ok, nk in zip(old_keys, new_keys):
        d = _translation_delta(ok, nk)
        if d is None:
            return None
        if delta is None:
            delta = d
        elif d != delta:
            return None
    return delta if delta is not None else (0.0, 0.0)


def _shift_pose_key_bundle(
    keys: Optional[tuple], dx: float, dy: float
) -> Optional[tuple]:
    """Translate ``(epoch, x, y, *extra)`` pose keys by ``(dx, dy)``.

    Used by solver nudges so ``_world_prims`` can keep a cache hit without
    rebuilding extras. Returns None when a key is not shift-shaped.
    """
    if keys is None:
        return None
    out = []
    for k in keys:
        if not isinstance(k, tuple) or len(k) < 3:
            return None
        out.append((k[0], k[1] + dx, k[2] + dy) + k[3:])
    return tuple(out)


def _floor_probe_envelope(
    pas: Sequence["Prim"], dx: float, step_max: float, reach: float,
) -> Tuple[float, float, float, float]:
    """A box no cast of one ``floor_below`` march can leave (conservative).

    The march has at most ``ceil(|dx| / step_max)`` sub-steps, plus one drop
    for ``dx == 0`` and one after a wall rewind. Each lifts at most
    ``step_max + margin`` and drops at most that plus ``reach``; sideways it
    stays inside ``[0, dx]``. One extra sub-step of slack on each side.
    """
    minx = min(p.aabb[0] for p in pas)
    miny = min(p.aabb[1] for p in pas)
    maxx = max(p.aabb[2] for p in pas)
    maxy = max(p.aabb[3] for p in pas)
    lift = step_max + _FLOOR_PROBE_LIFT_MARGIN
    n = math.ceil(abs(dx) / step_max) + 3 if step_max > 0.0 else 3
    pad = 1.0 + _RESOLVE_SLOP
    return (
        minx + min(0.0, dx) - pad,
        miny - n * (lift + reach) - pad,
        maxx + max(0.0, dx) + pad,
        maxy + n * lift + pad,
    )


def _proxy_aabb_overlap(ca: "Collider", cb: "Collider") -> bool:
    """True when proxy AABBs overlap, or either proxy is invalid (conservative)."""
    if not ca._proxy_valid or not cb._proxy_valid:
        return True
    a = ca._proxy
    b = cb._proxy
    return not (a[0] > b[2] or b[0] > a[2] or a[1] > b[3] or b[1] > a[3])


def _unpadded_proxy_aabb(
    collider: "Collider",
) -> Optional[Tuple[float, float, float, float]]:
    """Proxy AABB with ``_PROXY_EPS`` removed. ``None`` when the proxy is invalid."""
    if not collider._proxy_valid:
        return None
    p = collider._proxy
    if p is None or len(p) < 4:
        return None
    eps = _PROXY_EPS
    return (p[0] + eps, p[1] + eps, p[2] - eps, p[3] - eps)


def _prims_bounds_aabb(
    prims: Sequence[Prim],
) -> Optional[Tuple[float, float, float, float]]:
    """Tight AABB of collision prims. Not the broad-phase proxy."""
    if not prims:
        return None
    minx = min(p.aabb[0] for p in prims)
    miny = min(p.aabb[1] for p in prims)
    maxx = max(p.aabb[2] for p in prims)
    maxy = max(p.aabb[3] for p in prims)
    return (minx, miny, maxx, maxy)


def _aabb_overlaps_box(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    """Closed intervals: equal edges overlap (a touch counts as contact)."""
    return not (a[0] > b[2] or b[0] > a[2] or a[1] > b[3] or b[1] > a[3])


def _aabb_matches_motion(
    prev: Tuple[float, float, float, float],
    curr: Tuple[float, float, float, float],
    dx: float,
    dy: float,
    tol: float = _UNSWEPT_MOTION_TOL,
) -> bool:
    """True when ``curr`` is ``prev`` shifted by ``(dx, dy)`` on every edge."""
    return (
        abs((curr[0] - prev[0]) - dx) <= tol
        and abs((curr[1] - prev[1]) - dy) <= tol
        and abs((curr[2] - prev[2]) - dx) <= tol
        and abs((curr[3] - prev[3]) - dy) <= tol
    )


def _aabb_entry_normal(
    prev_a: Tuple[float, float, float, float],
    curr_a: Tuple[float, float, float, float],
    prev_b: Tuple[float, float, float, float],
    curr_b: Tuple[float, float, float, float],
) -> Optional[Tuple[float, float]]:
    """Latest face ``A`` crossed into ``B``. Normal points from ``A`` toward ``B``.

    Both boxes are interpolated. A side counts only when ``A`` was clear of
    that face and the other axis overlaps at the crossing. ``None`` when no
    face can be named.
    """
    best_t = -1.0
    best: Optional[Tuple[float, float]] = None

    def _x_overlap(t: float) -> bool:
        a0 = prev_a[0] + (curr_a[0] - prev_a[0]) * t
        a1 = prev_a[2] + (curr_a[2] - prev_a[2]) * t
        b0 = prev_b[0] + (curr_b[0] - prev_b[0]) * t
        b1 = prev_b[2] + (curr_b[2] - prev_b[2]) * t
        return a0 <= b1 and b0 <= a1

    def _y_overlap(t: float) -> bool:
        a0 = prev_a[1] + (curr_a[1] - prev_a[1]) * t
        a1 = prev_a[3] + (curr_a[3] - prev_a[3]) * t
        b0 = prev_b[1] + (curr_b[1] - prev_b[1]) * t
        b1 = prev_b[3] + (curr_b[3] - prev_b[3]) * t
        return a0 <= b1 and b0 <= a1

    def _consider(
        clear: bool,
        crossed: bool,
        t_num: float,
        t_den: float,
        nx: float,
        ny: float,
        other_overlaps,
    ) -> None:
        nonlocal best_t, best
        if not clear or not crossed or t_den <= 1e-12:
            return
        t = t_num / t_den
        if t < -1e-4 or t > 1.0 + 1e-4:
            return
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        if not other_overlaps(t):
            return
        if t > best_t + 1e-9:
            best_t = t
            best = (nx, ny)

    # From below: A's top against B's bottom. Normal +Y.
    _consider(
        prev_a[3] <= prev_b[1] + 1e-6,
        curr_a[3] > curr_b[1],
        prev_b[1] - prev_a[3],
        (curr_a[3] - prev_a[3]) - (curr_b[1] - prev_b[1]),
        0.0, 1.0, _x_overlap,
    )
    # From above: A's bottom against B's top. Normal −Y.
    _consider(
        prev_a[1] >= prev_b[3] - 1e-6,
        curr_a[1] < curr_b[3],
        prev_a[1] - prev_b[3],
        (curr_b[3] - prev_b[3]) - (curr_a[1] - prev_a[1]),
        0.0, -1.0, _x_overlap,
    )
    # From the left: A's right against B's left. Normal +X.
    _consider(
        prev_a[2] <= prev_b[0] + 1e-6,
        curr_a[2] > curr_b[0],
        prev_b[0] - prev_a[2],
        (curr_a[2] - prev_a[2]) - (curr_b[0] - prev_b[0]),
        1.0, 0.0, _y_overlap,
    )
    # From the right: A's left against B's right. Normal −X.
    _consider(
        prev_a[0] >= prev_b[2] - 1e-6,
        curr_a[0] < curr_b[2],
        prev_a[0] - prev_b[2],
        (curr_b[2] - prev_b[2]) - (curr_a[0] - prev_a[0]),
        -1.0, 0.0, _y_overlap,
    )
    return best


def _prims_penetration(
    pas: Sequence[Prim], pbs: Sequence[Prim], nx: float, ny: float,
) -> float:
    """How far ``pas`` extends past ``pbs`` along ``n`` (from pas toward pbs)."""
    nlen = math.hypot(nx, ny)
    if nlen < 1e-12 or not pas or not pbs:
        return 0.0
    nx /= nlen
    ny /= nlen
    sa = _prims_support(pas, nx, ny)
    sb = _prims_support(pbs, -nx, -ny)
    if sa is None or sb is None:
        return 0.0
    return (sa[0] - sb[0]) * nx + (sa[1] - sb[1]) * ny


def _aabb_support_gap(
    body: Tuple[float, float, float, float],
    obs: Tuple[float, float, float, float],
    nx: float,
    ny: float,
) -> float:
    """How far ``body`` extends past ``obs`` along ``n`` (from body toward obs)."""
    if ny > 0.5:
        return body[3] - obs[1]
    if ny < -0.5:
        return obs[3] - body[1]
    if nx > 0.5:
        return body[2] - obs[0]
    if nx < -0.5:
        return obs[2] - body[0]
    return 0.0


def _translate_prims(prims: List[Prim], dx: float, dy: float) -> List[Prim]:
    """Shift prims in place when only the center moved (same collision epoch)."""
    if dx == 0.0 and dy == 0.0:
        return prims
    for p in prims:
        aabb = (p.aabb[0] + dx, p.aabb[1] + dy, p.aabb[2] + dx, p.aabb[3] + dy)
        p.aabb = aabb
        kind = p.kind
        if kind == PrimKind.CIRCLE:
            cx, cy, r = p.params
            p.params = (cx + dx, cy + dy, r)
        elif kind == PrimKind.AABB:
            p.params = aabb
        elif kind in (PrimKind.OBB, PrimKind.ELLIPSE):
            p.params = (p.params[0] + dx, p.params[1] + dy) + p.params[2:]
        elif kind == PrimKind.POLY:
            p.verts = [(x + dx, y + dy) for x, y in (p.verts or ())]
        else:
            return []
    return prims


def _copy_prim(p: Prim) -> Prim:
    verts = list(p.verts) if p.verts is not None else None
    return Prim(p.kind, p.aabb, p.params, verts)


def _copy_prims(prims: Sequence[Prim]) -> List[Prim]:
    return [_copy_prim(p) for p in prims]


def _copy_translate(prims: Sequence[Prim], dx: float, dy: float) -> List[Prim]:
    out = _copy_prims(prims)
    if dx or dy:
        _translate_prims(out, dx, dy)
    return out


def _swept_aabb(
    box: Sequence[float], dx: float, dy: float
) -> Tuple[float, float, float, float]:
    if dx >= 0.0:
        minx, maxx = box[0], box[2] + dx
    else:
        minx, maxx = box[0] + dx, box[2]
    if dy >= 0.0:
        miny, maxy = box[1], box[3] + dy
    else:
        miny, maxy = box[1] + dy, box[3]
    return (minx, miny, maxx, maxy)


def _prim_extent_along(prim: Prim, dx: float, dy: float) -> float:
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return 0.0
    ux, uy = dx / length, dy / length
    a = prim.aabb
    return abs(ux) * (a[2] - a[0]) * 0.5 + abs(uy) * (a[3] - a[1]) * 0.5


def _prims_extent_along(prims: Sequence[Prim], dx: float, dy: float) -> float:
    if not prims:
        return 0.0
    return min(_prim_extent_along(p, dx, dy) for p in prims)


def _aabb_near_tuple(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    pad: float,
) -> bool:
    """``_aabb_overlap_tuple`` with ``a`` grown by ``pad`` on every side."""
    return not (a[0] - pad > b[2] or b[0] > a[2] + pad
                or a[1] - pad > b[3] or b[1] > a[3] + pad)


def _prim_gap(pa: Prim, pb: Prim) -> Tuple[float, float, float]:
    """``(gap, nx, ny)`` between two prims that do not overlap, normal A → B.

    Closed form for AABB / circle pairs (the tile-game case); GJK otherwise.
    """
    ka, kb = pa.kind, pb.kind
    if ka == PrimKind.AABB and kb == PrimKind.AABB:
        a, b = pa.params, pb.params
        gx = max(b[0] - a[2], a[0] - b[2], 0.0)
        gy = max(b[1] - a[3], a[1] - b[3], 0.0)
        gap = math.hypot(gx, gy)
        if gap > 0.0:
            sx = 1.0 if b[0] - a[2] > 0.0 else -1.0
            sy = 1.0 if b[1] - a[3] > 0.0 else -1.0
            return gap, sx * gx / gap, sy * gy / gap
    elif ka == PrimKind.CIRCLE and kb in (PrimKind.AABB, PrimKind.CIRCLE):
        cx, cy, r = pa.params[0], pa.params[1], pa.params[2]
        if kb == PrimKind.AABB:
            b = pb.params
            qx, qy, rb = min(max(cx, b[0]), b[2]), min(max(cy, b[1]), b[3]), 0.0
        else:
            qx, qy, rb = pb.params[0], pb.params[1], pb.params[2]
        dist = math.hypot(qx - cx, qy - cy)
        if dist > 1e-12:
            return dist - r - rb, (qx - cx) / dist, (qy - cy) / dist
    elif kb == PrimKind.CIRCLE and ka == PrimKind.AABB:
        gap, nx, ny = _prim_gap(pb, pa)
        return gap, -nx, -ny
    return _gjk_distance((pa,), (pb,))


def _skin_contact(
    pas: Sequence[Prim], pbs: Sequence[Prim], skin: float,
    ox: float = 0.0, oy: float = 0.0, floor_sign: float = 0.0,
) -> Optional[Contact]:
    """Resting contact for prims that do not overlap: the closest prim pair
    within ``skin``, as a zero-depth contact (normal A → B, witness filled by
    ``_points_or_witness``). ``None`` when every gap is larger.

    ``(ox, oy, floor_sign)`` is the frame's carry opening (``_carry_opening``):
    a floor gap (``n · floor_sign >= |nx|``, 45° included) counts up to
    ``skin`` plus the opening along its normal, never less than ``skin``.
    """
    best: Optional[Tuple[float, float, float]] = None
    pad = skin + abs(ox) + abs(oy)
    for pa in pas:
        for pb in pbs:
            if not _aabb_near_tuple(pa.aabb, pb.aabb, pad):
                continue
            gap, nx, ny = _prim_gap(pa, pb)
            limit = skin
            if floor_sign and ny * floor_sign >= abs(nx):
                opening = ox * nx + oy * ny
                if opening > 0.0:
                    limit += opening
            if gap <= limit and (best is None or gap < best[0]):
                best = (gap, nx, ny)
    if best is None:
        return None
    return Contact((best[1], best[2]), 0.0, [])


def _immovable(c: "Collider") -> bool:
    ident = c._identity
    mass = getattr(ident, "_mass", None)
    if mass is None:
        mass = getattr(ident, "mass", 1.0)
    return _is_static_mass(mass)


def _carry_opening(ca: "Collider", cb: "Collider") -> Tuple[float, float, float]:
    """How far floor snap's floor moved away from its rider this frame, for
    the resting skin (PB4): ``(ox, oy, sign)``.

    Only an immovable (``STATIC``) side's motion-channel travel, and only
    when the other side is movable and was grounded at the start of the
    frame — exactly the case floor snap pulls back onto the floor. A gap
    normal ``n`` (A → B) opened by ``(ox, oy) · n``; ``sign`` is ``-1`` when
    A is the rider (``n`` must point down) and ``+1`` when B is (``n`` must
    point up). ``(0, 0, 0)`` otherwise: a rider's own motion (a jump off the
    lift) and a wall moving away are not a carry.
    """
    if ca._motion_translation and _immovable(ca):
        floor, rider, sign = ca, cb, 1.0
    elif cb._motion_translation and _immovable(cb):
        floor, rider, sign = cb, ca, -1.0
    else:
        return 0.0, 0.0, 0.0
    if _immovable(rider):
        return 0.0, 0.0, 0.0
    sides = getattr(rider._identity, "touching_sides", None)
    if not sides or "bottom" not in sides:
        return 0.0, 0.0, 0.0
    if floor is cb:
        return floor._motion_dx, floor._motion_dy, sign
    return -floor._motion_dx, -floor._motion_dy, sign


def _prims_near(pas: Sequence[Prim], pbs: Sequence[Prim], pad: float) -> bool:
    for pa in pas:
        for pb in pbs:
            if _aabb_near_tuple(pa.aabb, pb.aabb, pad):
                return True
    return False


def _narrow_any(pas: Sequence[Prim], pbs: Sequence[Prim]) -> Optional[Contact]:
    best: Optional[Contact] = None
    for pa in pas:
        for pb in pbs:
            if not _aabb_overlap_tuple(pa.aabb, pb.aabb):
                continue
            c = narrow_phase(pa, pb)
            if c is not None and (best is None or c.depth > best.depth):
                best = c
    return best


def _axis_penetration(
    amin: float, amax: float, bmin: float, bmax: float,
) -> Optional[float]:
    """Minimum translation along one axis to separate two intervals.

    ``None`` when the intervals are disjoint. When one interval contains the
    other this is the distance to the nearer end, not the contained length.
    Partial overlaps match ``hi - lo``.
    """
    to_neg = amax - bmin
    to_pos = bmax - amin
    if to_neg < 0.0 or to_pos < 0.0:
        return None
    return to_neg if to_neg < to_pos else to_pos


def _aabb_toi(
    a: Sequence[float], b: Sequence[float], dx: float, dy: float
) -> Optional[Tuple[float, float, float]]:
    """Entry time and normal (a→b) for moving AABB ``a`` vs stationary ``b``."""
    aminx, aminy, amaxx, amaxy = a[0], a[1], a[2], a[3]
    bminx, bminy, bmaxx, bmaxy = b[0], b[1], b[2], b[3]
    currently = not (
        aminx > bmaxx or bminx > amaxx or aminy > bmaxy or bminy > amaxy
    )

    def _axis(amin: float, amax: float, bmin: float, bmax: float, d: float):
        if abs(d) < 1e-18:
            if amax < bmin or amin > bmax:
                return None
            return (-1e30, 1e30)
        t1 = (bmin - amax) / d
        t2 = (bmax - amin) / d
        return (min(t1, t2), max(t1, t2))

    x = _axis(aminx, amaxx, bminx, bmaxx, dx)
    y = _axis(aminy, amaxy, bminy, bmaxy, dy)
    if x is None or y is None:
        return None
    t_enter = max(x[0], y[0])
    t_exit = min(x[1], y[1])
    if t_enter > t_exit or t_exit < 0.0 or t_enter > 1.0:
        return None
    if t_enter < 0.0:
        if not currently:
            return None
        t = 0.0
        pen_x = _axis_penetration(aminx, amaxx, bminx, bmaxx)
        pen_y = _axis_penetration(aminy, amaxy, bminy, bmaxy)
        acx = (aminx + amaxx) * 0.5
        bcx = (bminx + bmaxx) * 0.5
        acy = (aminy + amaxy) * 0.5
        bcy = (bminy + bmaxy) * 0.5
        if pen_y is None or (pen_x is not None and pen_x < pen_y):
            nx = 1.0 if bcx >= acx else -1.0
            ny = 0.0
        else:
            nx = 0.0
            ny = 1.0 if bcy >= acy else -1.0
        return (t, nx, ny)
    t = t_enter
    if x[0] > y[0]:
        nx = 1.0 if dx > 0.0 else -1.0
        ny = 0.0
    else:
        nx = 0.0
        ny = 1.0 if dy > 0.0 else -1.0
    return (t, nx, ny)


def _circle_circle_toi(
    ax: float, ay: float, ar: float, bx: float, by: float, br: float,
    dx: float, dy: float,
) -> Optional[Tuple[float, float, float]]:
    rx, ry = ax - bx, ay - by
    rsum = ar + br
    c0 = rx * rx + ry * ry - rsum * rsum
    a = dx * dx + dy * dy
    if c0 <= 0.0:
        dist = math.hypot(rx, ry)
        if dist < 1e-12:
            return (0.0, 1.0, 0.0)
        return (0.0, -rx / dist, -ry / dist)
    if a < 1e-18:
        return None
    b = 2.0 * (rx * dx + ry * dy)
    disc = b * b - 4.0 * a * c0
    if disc < 0.0:
        return None
    sqrt_d = math.sqrt(disc)
    t = (-b - sqrt_d) / (2.0 * a)
    if t < 0.0 or t > 1.0:
        t2 = (-b + sqrt_d) / (2.0 * a)
        if t2 < 0.0 or t2 > 1.0:
            return None
        t = t2
    cx = ax + dx * t
    cy = ay + dy * t
    hx, hy = bx - cx, by - cy
    dist = math.hypot(hx, hy)
    if dist < 1e-12:
        return (t, 1.0, 0.0)
    return (t, hx / dist, hy / dist)


def _circle_aabb_toi(
    cx: float, cy: float, r: float, box: Sequence[float], dx: float, dy: float,
) -> Optional[Tuple[float, float, float]]:
    """Entry time of a moving circle against an AABB (rounded Minkowski sum).

    The expanded box has square corners. A hit that lands in a corner square
    is retested against the circle of radius ``r`` on that corner, so a pass
    that misses the round corner is not a contact. Already-overlapping uses
    the same normal as :func:`_circle_aabb`.
    """
    minx, miny, maxx, maxy = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    qx = min(max(cx, minx), maxx)
    qy = min(max(cy, miny), maxy)
    vx, vy = cx - qx, cy - qy
    if vx * vx + vy * vy <= r * r + 1e-9:
        contact = _circle_aabb((cx, cy, r), (minx, miny, maxx, maxy))
        if contact is None:
            return (0.0, 1.0, 0.0)
        return (0.0, contact.normal[0], contact.normal[1])
    expanded = (minx - r, miny - r, maxx + r, maxy + r)
    t = _ray_aabb(cx, cy, dx, dy, expanded)
    if t is None:
        return None
    px, py = cx + dx * t, cy + dy * t
    left = px < minx
    right = px > maxx
    below = py < miny
    above = py > maxy
    if (left or right) and (below or above):
        corner_x = minx if left else maxx
        corner_y = miny if below else maxy
        t_c = _ray_circle(cx, cy, dx, dy, corner_x, corner_y, r)
        if t_c is None:
            return None
        t = t_c
        px = cx + dx * t
        py = cy + dy * t
        hx, hy = corner_x - px, corner_y - py
        dist = math.hypot(hx, hy)
        if dist < 1e-12:
            return (t, 1.0, 0.0)
        return (t, hx / dist, hy / dist)
    qx = min(max(px, minx), maxx)
    qy = min(max(py, miny), maxy)
    hx, hy = qx - px, qy - py
    dist = math.hypot(hx, hy)
    if dist < 1e-12:
        left_d = px - minx
        right_d = maxx - px
        bottom_d = py - miny
        top_d = maxy - py
        m = min(left_d, right_d, bottom_d, top_d)
        if m == left_d:
            return (t, 1.0, 0.0)
        if m == right_d:
            return (t, -1.0, 0.0)
        if m == bottom_d:
            return (t, 0.0, 1.0)
        return (t, 0.0, -1.0)
    return (t, hx / dist, hy / dist)


def _toi_fast(
    pa: Prim, pb: Prim, dx: float, dy: float
) -> Optional[Tuple[float, Contact]]:
    ka, kb = pa.kind, pb.kind
    if ka == PrimKind.AABB and kb == PrimKind.AABB:
        hit = _aabb_toi(pa.params, pb.params, dx, dy)
        if hit is None:
            return None
        t, nx, ny = hit
        return (t, Contact((nx, ny), 0.0, []))
    if ka == PrimKind.CIRCLE and kb == PrimKind.CIRCLE:
        ax, ay, ar = pa.params[0], pa.params[1], pa.params[2]
        bx, by, br = pb.params[0], pb.params[1], pb.params[2]
        hit = _circle_circle_toi(ax, ay, ar, bx, by, br, dx, dy)
        if hit is None:
            return None
        t, nx, ny = hit
        return (t, Contact((nx, ny), 0.0, []))
    if ka == PrimKind.CIRCLE and kb == PrimKind.AABB:
        cx, cy, r = pa.params[0], pa.params[1], pa.params[2]
        hit = _circle_aabb_toi(cx, cy, r, pb.params, dx, dy)
        if hit is None:
            return None
        t, nx, ny = hit
        return (t, Contact((nx, ny), 0.0, []))
    if ka == PrimKind.AABB and kb == PrimKind.CIRCLE:
        cx, cy, r = pb.params[0], pb.params[1], pb.params[2]
        hit = _circle_aabb_toi(cx, cy, r, pa.params, -dx, -dy)
        if hit is None:
            return None
        t, nx, ny = hit
        return (t, Contact((-nx, -ny), 0.0, []))
    return None


def _convex_ring(verts: Sequence[Tuple[float, float]]) -> bool:
    """True for a strictly convex, simple vertex ring with area (either winding).

    One turn sign at every corner, and the edges' x direction changes
    exactly twice round the ring: a ring that turns one way and changes more
    often winds round more than once (a star). Collinear runs are allowed; a
    zero-area ring is not.
    """
    n = len(verts)
    if n < 3:
        return False
    sign = 0.0
    area = 0.0
    flips = 0
    first_dir = last_dir = 0.0
    px, py = verts[-1]
    pex, pey = px - verts[-2][0], py - verts[-2][1]
    for qx, qy in verts:
        ex, ey = qx - px, qy - py
        cross = pex * ey - pey * ex
        if cross > 1e-12:
            if sign < 0.0:
                return False
            sign = 1.0
        elif cross < -1e-12:
            if sign > 0.0:
                return False
            sign = -1.0
        if ex != 0.0:
            d = 1.0 if ex > 0.0 else -1.0
            if not first_dir:
                first_dir = d
            elif d != last_dir:
                flips += 1
            last_dir = d
        area += px * qy - qx * py
        px, py, pex, pey = qx, qy, ex, ey
    if last_dir != first_dir:
        flips += 1                        # the change across the wrap
    return sign != 0.0 and abs(area) > 1e-12 and flips == 2


def _sat_ring(p: Prim) -> Optional[Sequence[Tuple[float, float]]]:
    """``p``'s vertex ring when it is one convex polygon, else None."""
    k = p.kind
    if k == PrimKind.AABB:
        x0, y0, x1, y1 = p.params[0], p.params[1], p.params[2], p.params[3]
        if not (x1 > x0 and y1 > y0):
            return None
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    if k == PrimKind.OBB:
        cx, cy, hw, hh, ang = p.params
        if not (hw > 0.0 and hh > 0.0):
            return None
        return _obb_corners(cx, cy, hw, hh, ang)
    if k == PrimKind.POLY:
        v = p.verts
        if v and _convex_ring(v):
            return v
    return None


def _toi_sat(pa: Prim, pb: Prim, dx: float, dy: float):
    """Swept SAT: convex polygon ``pa`` moving by ``(dx, dy)`` against still ``pb``.

    Same contract as ``_toi_advance`` on one prim each: a start overlap is
    ``(0, narrow contact)``; otherwise the exact entry time and the normal
    (a → b) of the face it enters through, with no contact points. Returns
    ``_TOI_UNRESOLVED`` when either prim is not one convex polygon (circle,
    ellipse, capsule, a ring that is not convex): the caller advances.
    """
    va = _sat_ring(pa)
    if va is None:
        return _TOI_UNRESOLVED
    vb = _sat_ring(pb)
    if vb is None:
        return _TOI_UNRESOLVED
    length = math.hypot(dx, dy)
    t_enter = -math.inf
    t_exit = math.inf
    bnx = bny = 0.0
    for ring in (va, vb):
        px, py = ring[-1]
        for qx, qy in ring:
            ex, ey = qx - px, qy - py
            px, py = qx, qy
            el = math.hypot(ex, ey)
            if el < 1e-12:
                continue
            nx, ny = ey / el, -ex / el
            amin = amax = va[0][0] * nx + va[0][1] * ny
            for x, y in va:
                d = x * nx + y * ny
                if d < amin:
                    amin = d
                elif d > amax:
                    amax = d
            bmin = bmax = vb[0][0] * nx + vb[0][1] * ny
            for x, y in vb:
                d = x * nx + y * ny
                if d < bmin:
                    bmin = d
                elif d > bmax:
                    bmax = d
            v = dx * nx + dy * ny
            if -1e-15 < v < 1e-15:
                if amax < bmin or amin > bmax:
                    return None
                continue
            if v > 0.0:
                te = (bmin - amax) / v
                tx = (bmax - amin) / v
                sx, sy = nx, ny
            else:
                te = (bmax - amin) / v
                tx = (bmin - amax) / v
                sx, sy = -nx, -ny
            if te > t_enter:
                t_enter = te
                bnx, bny = sx, sy
            if tx < t_exit:
                t_exit = tx
            if t_enter > t_exit or t_exit < 0.0 or t_enter > 1.0:
                return None
    if t_enter == -math.inf:
        # No motion across any face and overlapping on every axis: a start
        # overlap under float-residue motion. Advancement answers it (0, contact).
        return _TOI_UNRESOLVED
    if t_enter * length <= 1e-6:
        # Touching or overlapping at the start: the narrow phase decides, as
        # in conservative advancement (its depth and points, its normal).
        if _aabb_overlap_tuple(pa.aabb, pb.aabb):
            c = narrow_phase(pa, pb)
            if c is not None:
                return (0.0, c)
        return (max(0.0, t_enter), Contact((bnx, bny), 0.0, []))
    return (t_enter, Contact((bnx, bny), 0.0, []))


def _toi_bisect(
    pas: Sequence[Prim], pbs: Sequence[Prim], dx: float, dy: float
) -> Optional[Tuple[float, Contact]]:
    start = _narrow_any(pas, pbs)
    if start is not None:
        return (0.0, start)
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return None
    ux, uy = dx / length, dy / length

    def _thickness(prims: Sequence[Prim]) -> float:
        s1 = _prims_support(prims, ux, uy)
        s2 = _prims_support(prims, -ux, -uy)
        if s1 is None or s2 is None:
            return 1.0
        return abs((s1[0] - s2[0]) * ux + (s1[1] - s2[1]) * uy)

    min_ext = min(_thickness(pas), _thickness(pbs))
    if min_ext < 1e-6:
        min_ext = 1e-3
    step = min(1.0, 0.9 * min_ext / length)
    if step * _TOI_BISECT_CAP < 1.0:
        step = 1.0 / float(_TOI_BISECT_CAP)
    prev_t = 0.0
    t = step
    hit_t: Optional[float] = None
    while t < 1.0 - 1e-12:
        moved = _copy_translate(pas, dx * t, dy * t)
        if _narrow_any(moved, pbs) is not None:
            hit_t = t
            break
        prev_t = t
        t += step
    if hit_t is None:
        moved = _copy_translate(pas, dx, dy)
        if _narrow_any(moved, pbs) is None:
            return None
        hit_t = 1.0
    lo, hi = prev_t, hit_t
    contact: Optional[Contact] = None
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        moved = _copy_translate(pas, dx * mid, dy * mid)
        c = _narrow_any(moved, pbs)
        if c is not None:
            hi = mid
            contact = c
        else:
            lo = mid
    if contact is None:
        moved = _copy_translate(pas, dx * hi, dy * hi)
        contact = _narrow_any(moved, pbs)
    if contact is None:
        return None
    return (hi, contact)


def _toi_prim_sets(
    pas: Sequence[Prim], pbs: Sequence[Prim], dx: float, dy: float
) -> Optional[Tuple[float, Contact]]:
    if not pas or not pbs:
        return None
    all_fast = True
    for pa in pas:
        for pb in pbs:
            if not _is_fast_narrow(pa, pb):
                all_fast = False
                break
        if not all_fast:
            break
    if all_fast:
        best: Optional[Tuple[float, Contact]] = None
        for pa in pas:
            for pb in pbs:
                hit = _toi_fast(pa, pb, dx, dy)
                if hit is None:
                    continue
                if best is None or hit[0] < best[0]:
                    best = hit
        return best
    if len(pas) > 1 or len(pbs) > 1:
        return _toi_prim_pairs(pas, pbs, dx, dy)
    if _SWEEP_SAT and (dx or dy):
        hit = _toi_sat(pas[0], pbs[0], dx, dy)
        if hit is not _TOI_UNRESOLVED:
            return hit
    advanced = _toi_advance(pas, pbs, dx, dy)
    if advanced is not _TOI_UNRESOLVED:
        return advanced
    return _toi_bisect(pas, pbs, dx, dy)


def _toi_prim_pairs(
    pas: Sequence[Prim], pbs: Sequence[Prim], dx: float, dy: float
) -> Optional[Tuple[float, Contact]]:
    """Earliest hit over the prim pairs of two sets, each pair swept alone.

    A set's GJK distance is the distance between the sets' convex hulls, so
    advancing two sets at once stopped a body on the hull of a concave
    partner: a ball rolling into a ``Concave`` scoop (or an ear-clipped
    ``Polygon``) met the hull's chord and was thrown off it (CV1 in Testing
    Design). The union's first contact is the earliest pair's. Pairs whose
    swept boxes miss are skipped.
    """
    best: Optional[Tuple[float, Contact]] = None
    for pa in pas:
        sx0, sy0, sx1, sy1 = _swept_aabb(pa.aabb, dx, dy)
        one_a = (pa,)
        for pb in pbs:
            b = pb.aabb
            if b[0] > sx1 or sx0 > b[2] or b[1] > sy1 or sy0 > b[3]:
                continue
            hit = _toi_prim_sets(one_a, (pb,), dx, dy)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = hit
    return best


def _skin_back_off(
    nx: float, ny: float, mx: float, my: float, along_motion: bool,
) -> Tuple[float, float]:
    """The offset that leaves ``_RESOLVE_SLOP`` of skin after a stop.

    ``(nx, ny)`` is the unit contact normal (body toward partner), ``(mx, my)``
    the motion that met it. A body that stops there (a floor met with no
    sideways intent, a floor snap) backs off along its own motion, by the
    length that opens the skin along the normal: an idle body on a slope
    then ends exactly where its fall met the surface. Backing off along the
    normal moved it downhill by ``slop * sin(slope)`` every frame, and the
    next fall kept it: the idle creep (PE2). A body that slides on backs off
    along the normal, which leaves its slide untouched.
    """
    if along_motion and _SKIN_ALONG_MOTION:
        m = math.hypot(mx, my)
        if m > 1e-12:
            c = (mx * nx + my * ny) / m
            if c >= _SKIN_MOTION_COS:
                k = _RESOLVE_SLOP / (c * m)
                return -mx * k, -my * k
    return -nx * _RESOLVE_SLOP, -ny * _RESOLVE_SLOP


def _remove_normal_component(
    rx: float, ry: float, nx: float, ny: float
) -> Tuple[float, float]:
    nlen = math.hypot(nx, ny)
    if nlen < 1e-12:
        return rx, ry
    nx /= nlen
    ny /= nlen
    dot = rx * nx + ry * ny
    return rx - dot * nx, ry - dot * ny


def _cone_split(
    vx: float, vy: float, ns: Sequence[Tuple[float, float]],
) -> Tuple[float, float, List[float]]:
    """The inelastic answer of ``(vx, vy)`` to the contacts ``ns`` (unit
    normals, body toward partner): ``(px, py, js)``, ``p`` the nearest vector
    to ``v`` that approaches no contact, ``v - p = sum js[i] * ns[i]`` with
    every ``js[i] >= 0``.

    In 2D ``p`` lies on one contact's face or is zero (two contacts block
    every direction ``v`` could keep). ``p`` and ``v - p`` are orthogonal
    (Moreau), so answering with a uniform restitution adds no energy.
    """
    k = len(ns)
    js = [0.0] * k
    dots = [vx * n[0] + vy * n[1] for n in ns]
    if max(dots) <= 1e-12:
        return vx, vy, js
    best = None
    for i in range(k):
        d = dots[i]
        if d <= 1e-12:
            continue
        px, py = vx - d * ns[i][0], vy - d * ns[i][1]
        if all(px * m[0] + py * m[1] <= 1e-9 for m in ns):
            if best is None or d > best[0]:
                best = (d, i, px, py)
    if best is not None:
        js[best[1]] = best[0]
        return best[2], best[3], js
    for i in range(k):
        for j in range(i + 1, k):
            a0, a1 = ns[i]
            b0, b1 = ns[j]
            det = a0 * b1 - a1 * b0
            if abs(det) < 1e-12:
                continue
            ci = (vx * b1 - vy * b0) / det
            cj = (a0 * vy - a1 * vx) / det
            if ci >= -1e-12 and cj >= -1e-12:
                js[i] = max(ci, 0.0)
                js[j] = max(cj, 0.0)
                return 0.0, 0.0, js
    return vx, vy, js                       # degenerate (float): answer nothing


def _cone_response(
    vx: float, vy: float, ns: Sequence[Tuple[float, float]], es: Sequence[float],
) -> Tuple[float, float]:
    """``(vx, vy)`` answered by the contacts ``ns`` together: each contact's
    inelastic impulse (``_cone_split``) times ``1 + es[i]`` (Collision Design,
    "Joint stop"). One contact: ``velocity_split`` against a still partner.
    Mixed restitutions that would add energy (obtuse normals) take the
    smallest one for all."""
    px, py, js = _cone_split(vx, vy, ns)
    ox, oy = vx, vy
    for (nx, ny), j, e in zip(ns, js, es):
        ox -= (1.0 + e) * j * nx
        oy -= (1.0 + e) * j * ny
    if ox * ox + oy * oy > vx * vx + vy * vy + 1e-9:
        e = min(es)
        ox, oy = px - e * (vx - px), py - e * (vy - py)
    return ox, oy


class _GhostPartner:
    """A resolve partner a handler removed this step, frozen where it was:
    a still wall for its survivor's sweep, for this step only (PE5). It is
    pushed by nothing, and is in no contact (``touching_*``, settle, snap)."""

    __slots__ = ("dead", "prims", "_proxy", "mass", "vel", "info", "only_entry")

    def __init__(self, dead, prims, mass, vel, info, only_entry):
        self.dead = dead                    # the removed Collider (for ``only=``)
        self.prims = prims
        self._proxy = (
            min(q.aabb[0] for q in prims) - _PROXY_EPS,
            min(q.aabb[1] for q in prims) - _PROXY_EPS,
            max(q.aabb[2] for q in prims) + _PROXY_EPS,
            max(q.aabb[3] for q in prims) + _PROXY_EPS,
        )
        self.mass = mass
        self.vel = vel                      # (vx, vy) or None
        self.info = info                    # the contact the handlers saw
        self.only_entry = only_entry


def _gate_body(cb: Any) -> Any:
    """The collider an ``only=`` gate judges and marks for a partner."""
    return cb.dead if type(cb) is _GhostPartner else cb


def _partner_mass_vel(cb: Any) -> Tuple[float, Optional[Tuple[float, float]]]:
    """``(mass, (vx, vy) or None)`` of a resolve partner, live or a ghost."""
    if type(cb) is _GhostPartner:
        return cb.mass, cb.vel
    ib = cb._identity
    if ib is None:
        return 1.0, None
    v = getattr(ib, "_vel", None)
    return float(getattr(ib, "mass", 1.0)), None if v is None else (float(v.x), float(v.y))


def _aabb_support(
    box: Sequence[float], dx: float, dy: float,
) -> Tuple[float, float]:
    x = box[2] if dx > 0.0 else (box[0] if dx < 0.0 else 0.5 * (box[0] + box[2]))
    y = box[3] if dy > 0.0 else (box[1] if dy < 0.0 else 0.5 * (box[1] + box[3]))
    return float(x), float(y)


def _synthesize_contact_point(
    box_a: Sequence[float],
    box_b: Sequence[float],
    nx: float,
    ny: float,
) -> Tuple[float, float]:
    """Midpoint of AABB supports along ``normal`` (from a toward b).

    Prefer ``_synthesize_contact_point_from_prims`` for rotated bodies — a
    proxy AABB around an OBB is fat and the midpoint drifts off the surface.
    """
    sa = _aabb_support(box_a, nx, ny)
    sb = _aabb_support(box_b, -nx, -ny)
    return (0.5 * (sa[0] + sb[0]), 0.5 * (sa[1] + sb[1]))


def _prim_support(prim: Prim, dx: float, dy: float) -> Tuple[float, float]:
    """Furthest point of ``prim`` in direction ``(dx, dy)``."""
    pt, _ties = _prim_support_ex(prim, dx, dy)
    return pt


def _support_and_ties(verts, dx: float, dy: float, tie_eps: float, fallback):
    """The furthest vertex along ``(dx, dy)``, and how many vertices are within
    ``tie_eps`` of it (feature type: 1 = vertex, >= 2 = edge / face).

    The point is always the true argmax. ``tie_eps`` only widens the COUNT —
    returning "the first vertex within tie_eps" made the support up to
    ``tie_eps`` short of the furthest point, and GJK / EPA / projections read
    it (D5 in Testing Design).
    """
    best = None
    best_d = -1e300
    dots = []
    for x, y in verts:
        d = x * dx + y * dy
        dots.append(d)
        if d > best_d:
            best_d = d
            best = (float(x), float(y))
    if best is None:
        return (float(fallback[0]), float(fallback[1])), 1
    ties = sum(1 for d in dots if d >= best_d - tie_eps)
    return best, max(ties, 1)


def _prim_support_ex(
    prim: Prim, dx: float, dy: float,
) -> Tuple[Tuple[float, float], int]:
    """Support point plus how many feature vertices share that support value.

    ``ties == 1`` → vertex feature; ``ties >= 2`` → edge/face feature. Used to
    pick a witness when averaging two supports would drift along a long face.
    """
    # Sweep TOI normals are close to, but not exactly, a face normal — allow a
    # small absolute slack so both endpoints of a supporting edge still tie.
    tie_eps = 0.5

    if prim.kind == PrimKind.CIRCLE:
        cx, cy, r = float(prim.params[0]), float(prim.params[1]), float(prim.params[2])
        ln = math.hypot(dx, dy)
        if ln < 1e-12:
            return (cx, cy), 1
        return (cx + r * dx / ln, cy + r * dy / ln), 1
    if prim.kind == PrimKind.AABB:
        box = prim.params
        # Axis-aligned box: one corner unless dx or dy is ~0 (then a full edge).
        pt = _aabb_support(box, dx, dy)
        ties = 1
        if abs(dx) < 1e-9:
            ties = 2
        if abs(dy) < 1e-9:
            ties = 2 if ties == 1 else 4
        # Near-axis normals (ramp rest) still have a unique corner — keep ties=1.
        return pt, ties
    if prim.kind == PrimKind.OBB:
        cx, cy, hw, hh, ang = (
            float(prim.params[0]), float(prim.params[1]),
            float(prim.params[2]), float(prim.params[3]), float(prim.params[4]),
        )
        return _support_and_ties(_obb_corners(cx, cy, hw, hh, ang), dx, dy, tie_eps, (cx, cy))
    if prim.kind == PrimKind.ELLIPSE:
        cx, cy, rx, ry, ang = (
            float(prim.params[0]), float(prim.params[1]),
            float(prim.params[2]), float(prim.params[3]), float(prim.params[4]),
        )
        # Support of axis-aligned ellipse in local frame, then rotate.
        c, s = math.cos(ang), math.sin(ang)
        lx, ly = c * dx + s * dy, -s * dx + c * dy
        den = math.sqrt(max(rx * rx * lx * lx + ry * ry * ly * ly, 1e-24))
        plx, ply = (rx * rx * lx) / den, (ry * ry * ly) / den
        return (cx + plx * c - ply * s, cy + plx * s + ply * c), 1
    if prim.kind == PrimKind.POLY and prim.verts:
        return _support_and_ties(prim.verts, dx, dy, tie_eps, prim.verts[0])
    # Fallback: AABB of the prim.
    return _aabb_support(prim.aabb, dx, dy), 1


def _prims_support(
    prims: Sequence[Prim], dx: float, dy: float,
) -> Optional[Tuple[float, float]]:
    got = _prims_support_ex(prims, dx, dy)
    return None if got is None else got[0]


def _prims_support_ex(
    prims: Sequence[Prim], dx: float, dy: float,
) -> Optional[Tuple[Tuple[float, float], int]]:
    if not prims:
        return None
    tie_eps = 0.5
    best, ties = _prim_support_ex(prims[0], dx, dy)
    best_d = best[0] * dx + best[1] * dy
    for p in prims[1:]:
        s, t = _prim_support_ex(p, dx, dy)
        d = s[0] * dx + s[1] * dy
        if d > best_d + tie_eps:
            best_d = d
            best = s
            ties = t
        elif abs(d - best_d) <= tie_eps:
            ties += t
    return best, ties


def _synthesize_contact_point_from_prims(
    pas: Sequence[Prim],
    pbs: Sequence[Prim],
    nx: float,
    ny: float,
) -> Tuple[float, float]:
    """Witness along ``normal`` (from a toward b) from exact prim supports.

    Averaging the two supports drifts along long faces (ramp corner rest picks
    opposite ends of the top edge). Prefer a unique vertex witness when the
    other feature is an edge/face.
    """
    a = _prims_support_ex(pas, nx, ny)
    b = _prims_support_ex(pbs, -nx, -ny)
    if a is None and b is None:
        return (0.0, 0.0)
    if a is None:
        return b[0]  # type: ignore[index]
    if b is None:
        return a[0]
    sa, ta = a
    sb, tb = b
    if ta == 1 and tb >= 2:
        return sa
    if tb == 1 and ta >= 2:
        return sb
    return (0.5 * (sa[0] + sb[0]), 0.5 * (sa[1] + sb[1]))


def _points_or_witness(
    points: Optional[Sequence[Tuple[float, float]]],
    pas: Sequence[Prim],
    pbs: Sequence[Prim],
    nx: float,
    ny: float,
) -> List[Tuple[float, float]]:
    """Clip manifold, or a prim-support witness when the clip list is empty.

    Enter / stay use this so ``CollisionInfo.point`` is a tuple while the pair
    overlaps. Exit keeps ``points`` empty. Does not invent a body-center locus.
    """
    pts = list(points) if points else []
    if pts:
        return pts
    if not pas or not pbs:
        return pts
    if math.hypot(float(nx), float(ny)) < 1e-12:
        return pts
    return [_synthesize_contact_point_from_prims(pas, pbs, nx, ny)]


def _collision_info_from_contact(ca, cb, contact, pas, pbs) -> CollisionInfo:
    """Canonical (lo-id, hi-id) payload; empty clips get a support witness."""
    ida, idb = id(ca), id(cb)
    nx, ny = float(contact.normal[0]), float(contact.normal[1])
    if ida < idb:
        a, b = ca, cb
        wpas, wpbs = pas, pbs
    else:
        a, b = cb, ca
        nx, ny = -nx, -ny
        wpas, wpbs = pbs, pas
    return CollisionInfo(
        a=a._identity,
        b=b._identity,
        normal=Vec2.temp(nx, ny),
        depth=contact.depth,
        points=_points_or_witness(contact.points, wpas, wpbs, nx, ny),
    )


def snapshot_shape(shape, *, cache_owner: Optional["Collider"] = None) -> List[Prim]:
    """Extract world-space collision primitives from a Shape / SpatialFx (pulls Attributes)."""
    if cache_owner is not None:
        key = _collision_pose_key(shape)
        cached = cache_owner._snap_cache.get(id(shape))
        if cached is not None:
            old_key, old_prims = cached
            if old_key == key:
                return old_prims
            # Same epoch + extra pose, new position → translate (formation sway).
            delta = _translation_delta(old_key, key) if old_prims else None
            if delta is not None:
                dx, dy = delta
                translated = _translate_prims(old_prims, dx, dy)
                if translated:
                    cache_owner._snap_cache[id(shape)] = (key, translated)
                    return translated
        prims = _snapshot_shape_uncached(shape, cache_owner=cache_owner)
        cache_owner._snap_cache[id(shape)] = (key, prims)
        return prims
    return _snapshot_shape_uncached(shape, cache_owner=None)


def _snapshot_shape_uncached(
    shape, *, cache_owner: Optional["Collider"] = None, include_off: bool = False,
) -> List[Prim]:
    """Extract world-space collision primitives (no pose cache).

    A Graphic whose main hitbox is switched off (``g.hitbox.active = False``)
    has no prims: the proxy goes invalid, so pairs, queries, ``resolve`` and
    ``touching_*`` all skip it (its parts are separate colliders).
    ``include_off`` measures it anyway (``hitbox.box``).
    """
    if not include_off and getattr(shape, "_main_hitbox_off", False):
        return []
    sys = _collision_system
    if sys is not None:
        sys._debug_hull_builds += 1
    from .shapes import (
        Circle, Concave, Ellipse, Line, Point, Polygon, Rect, _RadialPolygon, Square,
        get_xy, _bare_num, _clamped_spread, _is_full_turn,
    )
    from .spatial_fx import PointDomainFx, PadDomainFx, BeamDomainFx
    from .sprite import Sprite

    if getattr(type(shape), "_is_hitbox_part", False):
        return _prims_from_collision_specs(shape._collision_specs())

    # Lazy imports to avoid cycles; isinstance works across aliases.
    if isinstance(shape, Sprite):
        specs = getattr(shape, "_collision_specs", None)
        if callable(specs):
            return _prims_from_collision_specs(specs())
        cx, cy, w, h, ang_deg = shape._collision_frame()
        w, h = abs(float(w)), abs(float(h))
        ang = math.radians(float(ang_deg))
        hw, hh = w * 0.5, h * 0.5
        if abs(ang) < _ANGLE_EPS or abs(abs(ang) - math.pi) < _ANGLE_EPS:
            return [Prim(
                PrimKind.AABB,
                (cx - hw, cy - hh, cx + hw, cy + hh),
                (cx - hw, cy - hh, cx + hw, cy + hh),
            )]
        aabb = _aabb_from_obb(cx, cy, hw, hh, ang)
        return [Prim(PrimKind.OBB, aabb, (cx, cy, hw, hh, ang))]

    if isinstance(shape, Circle):
        if shape.model is _circle_center_radius():   # common case: direct Defining reads
            cx, cy = get_xy(shape.center, bare=True)
            r = abs(_bare_num(shape.radius))
        else:
            cx, cy = shape._center_xy()      # Defining only (D3)
            r = abs(shape._radius_value())
        # Full turn: the same CIRCLE prim as a disk. Narrow phase and sweep
        # stay on the circle formulas. Only a shorter opening builds arc prims.
        spread = _clamped_spread(_bare_num(shape.spread))
        if _is_full_turn(spread):
            return [Prim(PrimKind.CIRCLE, _aabb_from_circle(cx, cy, r), (cx, cy, r))]
        if spread <= 0.0 or r <= 0.0:
            return []
        return _partial_circle_prims(
            cx, cy, r, shape._arc_angle(), spread,        # Defining only (D3)
            bool(shape.__dict__.get("_use_center", True)),
        )

    if isinstance(shape, Point):
        cx, cy = get_xy(shape, bare=True)
        return [Prim(PrimKind.CIRCLE, _aabb_from_circle(cx, cy, 0.0), (cx, cy, 0.0))]

    if isinstance(shape, Ellipse):
        cx, cy, w_e, h_e, rot_e = shape._oriented_frame()   # Defining only (D3)
        rx = w_e * 0.5
        ry = h_e * 0.5
        ang = math.radians(rot_e)
        aabb = _aabb_from_obb(cx, cy, rx, ry, ang)
        return [Prim(PrimKind.ELLIPSE, aabb, (cx, cy, rx, ry, ang))]

    if isinstance(shape, Concave):
        # Convex pieces (a fan under the curve, strips for the rim): chords
        # within 0.25 DU of the drawn arc, as a partial Circle's wedges.
        return _concave_prims(shape)

    if isinstance(shape, (Rect, Square)):
        oriented = getattr(shape, "_oriented_frame", None)
        if callable(oriented):
            cx, cy, w, h, ang_deg = oriented()
        else:
            cx, cy = get_xy(shape.center, bare=True)
            w = abs(_bare_num(shape.width))
            h = abs(_bare_num(shape.height))
            ang_deg = shape._rotation_value()
        w, h = abs(float(w)), abs(float(h))
        ang = math.radians(float(ang_deg))
        hw, hh = w * 0.5, h * 0.5
        if abs(ang) < _ANGLE_EPS or abs(abs(ang) - math.pi) < _ANGLE_EPS:
            return [Prim(PrimKind.AABB, (cx - hw, cy - hh, cx + hw, cy + hh), (cx - hw, cy - hh, cx + hw, cy + hh))]
        aabb = _aabb_from_obb(cx, cy, hw, hh, ang)
        return [Prim(PrimKind.OBB, aabb, (cx, cy, hw, hh, ang))]

    if isinstance(shape, Line):
        # Defining-only endpoints — same geometry as getattr p1/p2, without
        # waking Derivate p2/center on angle-length models.
        x1, y1, x2, y2 = shape._segment_xy()
        return _thin_obb_prim(x1, y1, x2, y2, _stroke_half_width(shape))

    from .track import Track
    if isinstance(shape, Track):
        # Stroke tube: one thin OBB per baked segment (open or closed ring).
        # Interior stays empty — not a filled disk/polygon.
        return _track_stroke_prims(shape)

    # SpatialFx placement domains (soft emitters). Point domains publish tight
    # collision_specs (main paint circles / emission OBBs), separate from loose
    # domain_aabb cull pads. Pad/Beam keep pad_frame / beam_frame duals.
    if isinstance(shape, PointDomainFx):
        return _prims_from_collision_specs(shape._collision_specs())

    if isinstance(shape, PadDomainFx):
        # Pads are axis-aligned (no angle), so the hull is the pad box.
        cx, cy, w, h = shape._pad_frame()
        hw, hh = abs(float(w)) * 0.5, abs(float(h)) * 0.5
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        return [Prim(PrimKind.AABB, box, box)]

    if isinstance(shape, BeamDomainFx):
        return _prims_from_collision_specs(shape._collision_specs())

    # RegularPolygon / Triangle: closed-form verts from the Defining inputs.
    # Avoid shape.points — that materializes Derivate vertex Points via the reactive
    # graph (~10× slower than reading Defining params once). The shape owns the
    # formula (``_world_verts``): a Triangle is not a regular n-gon.
    if isinstance(shape, _RadialPolygon):
        cx, cy, r, phi0 = shape._placement_params()
        r = abs(float(r))
        n = int(shape._n)
        if n < 3 or r <= 0.0:
            return []
        if type(shape)._reach_factor is not None:     # Triangle: not a regular n-gon
            verts = shape._world_verts(cx, cy, r, phi0)
        else:
            phi0_rad = math.radians(float(phi0))
            delta = 2.0 * math.pi / n
            verts = [
                (cx + r * math.cos(phi0_rad + i * delta),
                 cy + r * math.sin(phi0_rad + i * delta))
                for i in range(n)
            ]
        return _snapshot_polygon_verts(verts, cache_owner=cache_owner, shape_id=id(shape))

    if isinstance(shape, Polygon):
        verts = []
        for v in shape.points:
            verts.append(get_xy(v, bare=True))
        if len(verts) < 3:
            return []
        return _snapshot_polygon_verts(verts, cache_owner=cache_owner, shape_id=id(shape))

    return []


def _concave_prims(shape) -> List[Prim]:
    """One POLY prim per convex piece of a Concave (``Concave._world_pieces``)."""
    prims = []
    for poly in shape._world_pieces():
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        prims.append(Prim(PrimKind.POLY, (min(xs), min(ys), max(xs), max(ys)), (), poly))
    return prims


def _clone_prims(prims: List[Prim]) -> List[Prim]:
    """Independent copies: a cache must never hand out objects it keeps.

    ``_translate_prims`` shifts prims **in place** (formation-sway fast path).
    A cache that returned its stored Prim objects would be moved along with the
    caller's copy while still filed under the old key (D2 in Testing Design).
    """
    return [
        Prim(p.kind, p.aabb, p.params, None if p.verts is None else list(p.verts))
        for p in prims
    ]


def _snapshot_polygon_verts(
    verts: List[Tuple[float, float]],
    *,
    cache_owner: Optional["Collider"] = None,
    shape_id: int = 0,
) -> List[Prim]:
    """Convex hull as one POLY, or ear-clipped triangles if concave."""
    key = tuple((round(x, 6), round(y, 6)) for x, y in verts)
    if cache_owner is not None and shape_id:
        cached = cache_owner._poly_cache.get(shape_id)
        if cached is not None and cached[0] == key:
            return _clone_prims(cached[1])

    if _is_convex(verts):
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        aabb = (min(xs), min(ys), max(xs), max(ys))
        prims = [Prim(PrimKind.POLY, aabb, (), list(verts))]
    else:
        tris = _ear_clip(verts)
        prims = []
        for tri in tris:
            xs = [p[0] for p in tri]
            ys = [p[1] for p in tri]
            aabb = (min(xs), min(ys), max(xs), max(ys))
            prims.append(Prim(PrimKind.POLY, aabb, (), list(tri)))
        if not prims:
            return []

    if cache_owner is not None and shape_id:
        cache_owner._poly_cache[shape_id] = (key, _clone_prims(prims))
    return prims


def _signed_area(verts: Sequence[Tuple[float, float]]) -> float:
    n = len(verts)
    a = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def _is_convex(verts: Sequence[Tuple[float, float]]) -> bool:
    n = len(verts)
    if n < 3:
        return False
    # Ensure consistent winding for cross-product sign.
    prev = 0.0
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        x2, y2 = verts[(i + 2) % n]
        cross = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(cross) < 1e-12:
            continue
        if prev == 0.0:
            prev = cross
        elif cross * prev < 0.0:
            return False
    # A regular star keeps a consistent turn and still self-intersects.
    for i in range(n):
        a = verts[i]
        b = verts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == (i + 1) % n or (j + 1) % n == i:
                continue
            c = verts[j]
            d = verts[(j + 1) % n]
            if _segments_properly_intersect(a, b, c, d):
                return False
    return True


def _orient(p, q, r) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _segments_properly_intersect(a, b, c, d) -> bool:
    """True when open segments ab and cd cross (shared endpoints do not count)."""
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    return o1 * o2 < 0.0 and o3 * o4 < 0.0


def _point_in_tri(p, a, b, c) -> bool:
    # Barycentric
    ax, ay = a
    bx, by = b
    cx, cy = c
    px, py = p
    v0x, v0y = cx - ax, cy - ay
    v1x, v1y = bx - ax, by - ay
    v2x, v2y = px - ax, py - ay
    dot00 = v0x * v0x + v0y * v0y
    dot01 = v0x * v1x + v0y * v1y
    dot02 = v0x * v2x + v0y * v2y
    dot11 = v1x * v1x + v1y * v1y
    dot12 = v1x * v2x + v1y * v2y
    denom = dot00 * dot11 - dot01 * dot01
    if abs(denom) < 1e-18:
        return False
    u = (dot11 * dot02 - dot01 * dot12) / denom
    v = (dot00 * dot12 - dot01 * dot02) / denom
    return u >= -1e-9 and v >= -1e-9 and (u + v) <= 1.0 + 1e-9


def _ear_clip(verts: Sequence[Tuple[float, float]]) -> List[List[Tuple[float, float]]]:
    """Ear clipping → list of triangles. Handles CCW and CW."""
    pts = list(verts)
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [pts]
    # Work on indices; flip to CCW if needed.
    if _signed_area(pts) < 0:
        pts = list(reversed(pts))
    idx = list(range(len(pts)))
    tris: List[List[Tuple[float, float]]] = []
    guard = 0
    max_guard = len(pts) * len(pts)
    while len(idx) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        m = len(idx)
        for i in range(m):
            i0, i1, i2 = idx[(i - 1) % m], idx[i], idx[(i + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            # Convex tip (CCW)
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 1e-12:
                continue
            # No other points inside
            empty = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                if _point_in_tri(pts[j], a, b, c):
                    empty = False
                    break
            if not empty:
                continue
            tris.append([a, b, c])
            del idx[i]
            ear_found = True
            break
        if not ear_found:
            break
    if len(idx) == 3:
        tris.append([pts[idx[0]], pts[idx[1]], pts[idx[2]]])
        return tris
    warnings.warn(
        "polygon ear clip did not finish; skipping this triangulation",
        RuntimeWarning,
        stacklevel=2,
    )
    return []


# ---------------------------------------------------------------------------
# Narrow phase
# ---------------------------------------------------------------------------


def _dot2(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _md_support(
    pas: Sequence[Prim], pbs: Sequence[Prim], dx: float, dy: float,
) -> Tuple[float, float]:
    """Support of the Minkowski difference A − B."""
    sa = _prims_support(pas, dx, dy)
    sb = _prims_support(pbs, -dx, -dy)
    if sa is None or sb is None:
        return (0.0, 0.0)
    return (sa[0] - sb[0], sa[1] - sb[1])


def _triple2(
    a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float],
) -> Tuple[float, float]:
    """``(a × b) × c`` in 2D."""
    ac = _dot2(a, c)
    bc = _dot2(b, c)
    return (ac * b[0] - bc * a[0], ac * b[1] - bc * a[1])


def _gjk_evolve(
    simplex: List[Tuple[float, float]],
) -> Tuple[bool, Tuple[float, float]]:
    """One GJK simplex step. Returns ``(contains_origin, search_direction)``."""
    a = simplex[-1]
    ao = (-a[0], -a[1])
    if len(simplex) == 2:
        b = simplex[0]
        ab = (b[0] - a[0], b[1] - a[1])
        if _dot2(ab, ao) > 0.0:
            return False, _triple2(ab, ao, ab)
        simplex[:] = [a]
        return False, ao
    c = simplex[0]
    b = simplex[1]
    ab = (b[0] - a[0], b[1] - a[1])
    ac = (c[0] - a[0], c[1] - a[1])
    ab_perp = _triple2(ac, ab, ab)
    ac_perp = _triple2(ab, ac, ac)
    if _dot2(ab_perp, ao) > 0.0:
        simplex[:] = [b, a]
        return False, ab_perp
    if _dot2(ac_perp, ao) > 0.0:
        simplex[:] = [c, a]
        return False, ac_perp
    return True, (0.0, 0.0)


def _closest_on_simplex(
    simplex: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """Point of ``simplex`` closest to the origin."""
    if not simplex:
        return (0.0, 0.0)
    if len(simplex) == 1:
        return simplex[0]
    a, b = simplex[0], simplex[-1]
    ab = (b[0] - a[0], b[1] - a[1])
    denom = _dot2(ab, ab)
    if denom < 1e-18:
        return a
    t = max(0.0, min(1.0, _dot2((-a[0], -a[1]), ab) / denom))
    return (a[0] + ab[0] * t, a[1] + ab[1] * t)


def _gjk(
    pas: Sequence[Prim], pbs: Sequence[Prim],
) -> Tuple[bool, List[Tuple[float, float]], Tuple[float, float], Tuple[float, float]]:
    """Intersection test.

    The third value is the closest Minkowski point when the shapes are
    separated. The fourth is the last search direction, pointing from that
    point toward the origin (from A toward B).
    """
    d = (1.0, 0.0)
    simplex: List[Tuple[float, float]] = [_md_support(pas, pbs, d[0], d[1])]
    d = (-simplex[0][0], -simplex[0][1])
    prev = d
    for _ in range(_TOI_ADVANCE_ITERS):
        if _dot2(d, d) < 1e-24:
            return True, simplex, (0.0, 0.0), prev
        prev = d
        a = _md_support(pas, pbs, d[0], d[1])
        if _dot2(a, d) < 0.0:
            return False, simplex, _closest_on_simplex(simplex), d
        simplex.append(a)
        contains, d = _gjk_evolve(simplex)
        if _dot2(d, d) < 1e-24 and len(simplex) == 2:
            # Supports landed on one line through the origin, so the next
            # search direction vanished before a triangle existed. Probe the
            # perpendicular or EPA never runs and the normal stays on that axis.
            ex = simplex[1][0] - simplex[0][0]
            ey = simplex[1][1] - simplex[0][1]
            px, py = -ey, ex
            ln = math.hypot(px, py)
            if ln >= 1e-12:
                px, py = px / ln, py / ln
                simplex.append(_md_support(pas, pbs, px, py))
                contains, d = _gjk_evolve(simplex)
                prev = (px, py)
        if contains or _dot2(d, d) < 1e-24:
            return True, simplex, (0.0, 0.0), prev
    return False, simplex, _closest_on_simplex(simplex), d


def _epa(
    pas: Sequence[Prim], pbs: Sequence[Prim], simplex: List[Tuple[float, float]],
) -> Optional[Tuple[Tuple[float, float], float]]:
    """Penetration normal (from A toward B) and depth. ``None`` if it does not converge."""
    poly = [p for p in simplex if p is not None]
    if len(poly) < 3:
        return None
    if _signed_area(poly) < 0.0:
        poly.reverse()
    best_n = (1.0, 0.0)
    best_d = 0.0
    for _ in range(_TOI_ADVANCE_ITERS):
        n = len(poly)
        best_d = 1e300
        best_i = 0
        best_n = (1.0, 0.0)
        for i in range(n):
            a = poly[i]
            b = poly[(i + 1) % n]
            ex, ey = b[0] - a[0], b[1] - a[1]
            nx, ny = ey, -ex
            ln = math.hypot(nx, ny)
            if ln < 1e-12:
                continue
            nx /= ln
            ny /= ln
            dist = a[0] * nx + a[1] * ny
            if dist < best_d:
                best_d = dist
                best_i = i
                best_n = (nx, ny)
        if best_d >= 1e299:
            return None
        support = _md_support(pas, pbs, best_n[0], best_n[1])
        if support[0] * best_n[0] + support[1] * best_n[1] - best_d < 1e-4:
            return best_n, max(0.0, best_d)
        poly.insert(best_i + 1, support)
    if best_d < 1e299:
        return best_n, max(0.0, best_d)
    return None


def _gjk_epa_contact(pas: Sequence[Prim], pbs: Sequence[Prim]) -> Optional[Contact]:
    """Overlap and penetration for any pair that includes an ellipse."""
    if not pas or not pbs:
        return None
    hit, simplex, _closest, direction = _gjk(pas, pbs)
    if not hit:
        return None
    pen = _epa(pas, pbs, simplex)
    if pen is None:
        # Overlapping but EPA did not finish: depth along the search direction
        # (from A toward B). ``closest`` is the origin once GJK has entered.
        nx, ny = direction
        ln = math.hypot(nx, ny)
        if ln < 1e-12:
            nx, ny = 0.0, -1.0
        else:
            nx, ny = nx / ln, ny / ln
        amin, amax = _project_prims(pas, nx, ny)
        bmin, bmax = _project_prims(pbs, nx, ny)
        depth = _axis_penetration(amin, amax, bmin, bmax)
        if depth is None:
            return None
        pen = ((nx, ny), depth)
    (nx, ny), depth = pen
    pt = _synthesize_contact_point_from_prims(pas, pbs, nx, ny)
    return Contact((nx, ny), depth, [pt])


def _project_prims(
    prims: Sequence[Prim], ax: float, ay: float,
) -> Tuple[float, float]:
    s_max = _prims_support(prims, ax, ay)
    s_min = _prims_support(prims, -ax, -ay)
    if s_max is None or s_min is None:
        return 0.0, 0.0
    return (
        s_min[0] * ax + s_min[1] * ay,
        s_max[0] * ax + s_max[1] * ay,
    )


def _gjk_epa_prims(pa: Prim, pb: Prim) -> Optional[Contact]:
    return _gjk_epa_contact((pa,), (pb,))


def _unit_direction(d: Tuple[float, float]) -> Tuple[float, float, float]:
    """``(0, nx, ny)`` for a search direction. Down if the direction vanished."""
    ln = math.hypot(d[0], d[1])
    if ln < 1e-12:
        return 0.0, 0.0, -1.0
    return 0.0, d[0] / ln, d[1] / ln


def _closest_on_hull_2d(
    pts: List[Tuple[float, float]],
) -> Tuple[Tuple[float, float], List[Tuple[float, float]]]:
    """Closest point to the origin on the hull of <= 3 points, and the minimal
    subset (vertex or edge) that carries it. Origin inside a triangle → (0, 0)."""
    best = None
    best_set: List[Tuple[float, float]] = []
    for p in pts:
        d = _dot2(p, p)
        if best is None or d < best[0]:
            best, best_set = (d, p), [p]
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = pts[i], pts[j]
            ab = (b[0] - a[0], b[1] - a[1])
            den = _dot2(ab, ab)
            if den < 1e-18:
                continue
            t = _dot2((-a[0], -a[1]), ab) / den
            if 0.0 < t < 1.0:
                q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
                d = _dot2(q, q)
                if d < best[0]:
                    best, best_set = (d, q), [a, b]
    if n == 3:
        a, b, c = pts
        s1 = (b[0] - a[0]) * (-a[1]) - (b[1] - a[1]) * (-a[0])
        s2 = (c[0] - b[0]) * (-b[1]) - (c[1] - b[1]) * (-b[0])
        s3 = (a[0] - c[0]) * (-c[1]) - (a[1] - c[1]) * (-c[0])
        if (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0):
            return (0.0, 0.0), list(pts)
    return best[1], best_set


def _gjk_refine_closest(
    pas: Sequence[Prim], pbs: Sequence[Prim],
    simplex: Sequence[Tuple[float, float]], start: Tuple[float, float],
) -> Tuple[float, float]:
    """GJK distance loop: closest point of A − B to the origin (separated case)."""
    pts = [p for p in simplex if p is not None][-2:] or [start]
    v, pts = _closest_on_hull_2d(pts)
    for _ in range(_TOI_ADVANCE_ITERS):
        vv = _dot2(v, v)
        if vv < 1e-24:
            return (0.0, 0.0)
        w = _md_support(pas, pbs, -v[0], -v[1])
        # No support point is closer along -v: v is the minimum (to tolerance).
        if vv - _dot2(v, w) <= 1e-9 * max(vv, 1.0):
            break
        v, pts = _closest_on_hull_2d(pts + [w])
    return v


def _gjk_distance(
    pas: Sequence[Prim], pbs: Sequence[Prim],
) -> Tuple[float, float, float]:
    """``(distance, nx, ny)`` with the normal pointing from A toward B.

    Distance is 0 when the shapes overlap. The normal is still the penetration
    direction: a sweep that steps just inside the surface has to slide on that
    face, and a stand-in ``(1, 0)`` reads a floor as a wall.
    """
    hit, simplex, closest, direction = _gjk(pas, pbs)
    if hit:
        pen = _epa(pas, pbs, simplex)
        if pen is not None:
            (nx, ny), _depth = pen
            return 0.0, nx, ny
        return _unit_direction(direction)
    # ``_gjk`` stops as soon as separation is PROVEN; its closest point belongs
    # to an unfinished simplex and overestimates the gap. Conservative
    # advancement needs a lower bound, so refine to the true minimum (D4).
    closest = _gjk_refine_closest(pas, pbs, simplex, closest)
    dist = math.hypot(closest[0], closest[1])
    if dist < 1e-12:
        return _unit_direction(direction)
    # ``closest`` is a point of A−B, so it points from B toward A.
    return dist, -closest[0] / dist, -closest[1] / dist


def _toi_advance(
    pas: Sequence[Prim], pbs: Sequence[Prim], dx: float, dy: float,
):
    """Conservative advancement for convex prims. ``_TOI_UNRESOLVED`` if it gives up."""
    start = _narrow_any(pas, pbs)
    if start is not None:
        return (0.0, start)
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return None
    ux, uy = dx / length, dy / length
    traveled = 0.0
    for _ in range(_TOI_ADVANCE_ITERS):
        moved = pas if traveled < 1e-12 else _copy_translate(pas, ux * traveled, uy * traveled)
        dist, nx, ny = _gjk_distance(moved, pbs)
        if dist < 1e-3:
            t = min(1.0, traveled / length)
            return (t, Contact((nx, ny), 0.0, []))
        closing = ux * nx + uy * ny
        if closing <= 1e-6:
            return None
        advance = 0.8 * dist / closing
        if advance < 1e-4:
            t = min(1.0, traveled / length)
            return (t, Contact((nx, ny), 0.0, []))
        if traveled + advance >= length - 1e-6:
            end = _copy_translate(pas, dx, dy)
            if _narrow_any(end, pbs) is None and _gjk_distance(end, pbs)[0] > 1e-3:
                return None
            return _TOI_UNRESOLVED
        traveled += advance
    return _TOI_UNRESOLVED


@dataclass
class Contact:
    normal: Tuple[float, float]  # from a → b
    depth: float
    points: List[Tuple[float, float]]


def narrow_phase(pa: Prim, pb: Prim) -> Optional[Contact]:
    ka, kb = pa.kind, pb.kind

    # --- Layer 1 fast paths ---
    if ka == PrimKind.CIRCLE and kb == PrimKind.CIRCLE:
        return _circle_circle(pa.params, pb.params)
    if ka == PrimKind.CIRCLE and kb == PrimKind.AABB:
        return _circle_aabb(pa.params, pb.params)
    if ka == PrimKind.AABB and kb == PrimKind.CIRCLE:
        c = _circle_aabb(pb.params, pa.params)
        return _flip_contact(c) if c else None
    if ka == PrimKind.AABB and kb == PrimKind.AABB:
        return _aabb_aabb(pa.params, pb.params)

    # --- Layer 2: promote to polygon (or circle/ellipse support) via SAT ---
    return _sat_prims(pa, pb)


def _flip_contact(c: Optional[Contact]) -> Optional[Contact]:
    if c is None:
        return None
    return Contact((-c.normal[0], -c.normal[1]), c.depth, list(c.points))


def _circle_circle(a, b) -> Optional[Contact]:
    ax, ay, ar = a[0], a[1], a[2]
    bx, by, br = b[0], b[1], b[2]
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    rsum = ar + br
    if dist > rsum + 1e-9:
        return None
    if dist < 1e-12:
        # Concentric — pick +x
        return Contact((1.0, 0.0), rsum, [(ax, ay)])
    nx, ny = dx / dist, dy / dist
    depth = rsum - dist
    px = ax + nx * ar
    py = ay + ny * ar
    return Contact((nx, ny), depth, [(px, py)])


def _circle_aabb(cparams, bparams) -> Optional[Contact]:
    cx, cy, r = cparams[0], cparams[1], cparams[2]
    minx, miny, maxx, maxy = bparams[0], bparams[1], bparams[2], bparams[3]
    qx = min(max(cx, minx), maxx)
    qy = min(max(cy, miny), maxy)
    dx, dy = cx - qx, cy - qy
    d2 = dx * dx + dy * dy
    if d2 > r * r + 1e-9:
        return None
    if d2 > 1e-12:
        dist = math.sqrt(d2)
        # Normal from AABB toward circle center (circle is A in circle_aabb call —
        # wait: narrow_phase calls _circle_aabb(pa, pb) with pa=circle, pb=aabb.
        # Normal should be from a(circle) → b(aabb), i.e. from circle into box =
        # toward the box from circle = -direction from closest to center.
        nx, ny = -dx / dist, -dy / dist
        depth = r - dist
        return Contact((nx, ny), depth, [(qx, qy)])
    # Center inside AABB: push out along smallest penetration
    left = cx - minx
    right = maxx - cx
    bottom = cy - miny
    top = maxy - cy
    m = min(left, right, bottom, top)
    if m == left:
        return Contact((1.0, 0.0), r + left, [(minx, cy)])
    if m == right:
        return Contact((-1.0, 0.0), r + right, [(maxx, cy)])
    if m == bottom:
        return Contact((0.0, 1.0), r + bottom, [(cx, miny)])
    return Contact((0.0, -1.0), r + top, [(cx, maxy)])


def _aabb_aabb(a, b) -> Optional[Contact]:
    aminx, aminy, amaxx, amaxy = a[0], a[1], a[2], a[3]
    bminx, bminy, bmaxx, bmaxy = b[0], b[1], b[2], b[3]
    if aminx > bmaxx or bminx > amaxx or aminy > bmaxy or bminy > amaxy:
        return None
    pen_x = _axis_penetration(aminx, amaxx, bminx, bmaxx)
    pen_y = _axis_penetration(aminy, amaxy, bminy, bmaxy)
    if pen_x is None or pen_y is None:
        return None
    acx = (aminx + amaxx) * 0.5
    bcx = (bminx + bmaxx) * 0.5
    acy = (aminy + amaxy) * 0.5
    bcy = (bminy + bmaxy) * 0.5
    va = [(aminx, aminy), (amaxx, aminy), (amaxx, amaxy), (aminx, amaxy)]
    vb = [(bminx, bminy), (bmaxx, bminy), (bmaxx, bmaxy), (bminx, bmaxy)]
    if pen_x < pen_y:
        nx = 1.0 if bcx >= acx else -1.0
        return Contact((nx, 0.0), pen_x, _poly_contact_points(va, vb, nx, 0.0))
    ny = 1.0 if bcy >= acy else -1.0
    return Contact((0.0, ny), pen_y, _poly_contact_points(va, vb, 0.0, ny))


def _prim_as_poly(p: Prim) -> List[Tuple[float, float]]:
    if p.kind == PrimKind.POLY and p.verts:
        return list(p.verts)
    if p.kind == PrimKind.AABB:
        minx, miny, maxx, maxy = p.params[0], p.params[1], p.params[2], p.params[3]
        return [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    if p.kind == PrimKind.OBB:
        cx, cy, hw, hh, ang = p.params[0], p.params[1], p.params[2], p.params[3], p.params[4]
        return _obb_corners(cx, cy, hw, hh, ang)
    if p.kind == PrimKind.CIRCLE:
        # Approximate only if forced into SAT with non-circle; prefer support-based.
        return []
    if p.kind == PrimKind.ELLIPSE:
        return []
    return []


def _project_poly(verts: Sequence[Tuple[float, float]], ax: float, ay: float) -> Tuple[float, float]:
    dots = [vx * ax + vy * ay for vx, vy in verts]
    return min(dots), max(dots)


def _project_circle(cx: float, cy: float, r: float, ax: float, ay: float) -> Tuple[float, float]:
    c = cx * ax + cy * ay
    return c - r, c + r


def _project_ellipse(cx: float, cy: float, rx: float, ry: float, ang: float, ax: float, ay: float) -> Tuple[float, float]:
    # Support: transform axis into ellipse local frame, then rx/ry scale.
    c, s = math.cos(ang), math.sin(ang)
    # World axis (ax, ay) → local: R^T * axis
    lx = ax * c + ay * s
    ly = -ax * s + ay * c
    # Support extent in local = hypot(rx*lx, ry*ly) for unit direction of (lx,ly) scaled
    extent = math.hypot(rx * lx, ry * ly)
    mid = cx * ax + cy * ay
    return mid - extent, mid + extent


def _orient_sat_axis(ax: float, ay: float, dx: float, dy: float) -> Tuple[float, float]:
    """Point ``(ax, ay)`` from a toward b using center delta ``(dx, dy)``."""
    if dx * ax + dy * ay < 0.0:
        return (-ax, -ay)
    return (ax, ay)


def _select_sat_mtv(
    scored: Sequence[Tuple[float, float, float]],
    acx: float,
    acy: float,
    bcx: float,
    bcy: float,
) -> Tuple[Tuple[float, float], float]:
    """Classic SAT: the axis with the smallest overlap is the MTV."""
    if not scored:
        return (1.0, 0.0), 0.0
    merged: Dict[Tuple[float, float], float] = {}
    for ax, ay, ov in scored:
        nlen = math.hypot(ax, ay)
        if nlen < 1e-12:
            continue
        ax /= nlen
        ay /= nlen
        if ax < 0.0 or (ax == 0.0 and ay < 0.0):
            ax, ay = -ax, -ay
        key = (round(ax, 5), round(ay, 5))
        prev = merged.get(key)
        if prev is None or ov < prev:
            merged[key] = ov
    items = [(k[0], k[1], ov) for k, ov in merged.items()]
    if not items:
        return (1.0, 0.0), 0.0
    dx, dy = bcx - acx, bcy - acy
    ax, ay, ov = min(items, key=lambda t: t[2])
    return _orient_sat_axis(ax, ay, dx, dy), ov


def _axes_from_poly(verts: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    axes = []
    n = len(verts)
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        # outward normal (perpendicular)
        nx, ny = -ey, ex
        length = math.hypot(nx, ny)
        if length < 1e-12:
            continue
        axes.append((nx / length, ny / length))
    return axes


def _sat_prims(pa: Prim, pb: Prim) -> Optional[Contact]:
    """SAT between two prims; circle/ellipse use closed-form projection."""
    if pa.kind == PrimKind.ELLIPSE or pb.kind == PrimKind.ELLIPSE:
        return _gjk_epa_prims(pa, pb)
    # Special: circle vs anything poly-like
    if pa.kind == PrimKind.CIRCLE and pb.kind in (PrimKind.OBB, PrimKind.POLY, PrimKind.AABB, PrimKind.ELLIPSE):
        return _sat_circle_vs(pa, pb)
    if pb.kind == PrimKind.CIRCLE and pa.kind in (PrimKind.OBB, PrimKind.POLY, PrimKind.AABB, PrimKind.ELLIPSE):
        return _flip_contact(_sat_circle_vs(pb, pa))

    if pa.kind == PrimKind.ELLIPSE or pb.kind == PrimKind.ELLIPSE:
        return _sat_with_ellipse(pa, pb)

    va = _prim_as_poly(pa)
    vb = _prim_as_poly(pb)
    if len(va) < 3 or len(vb) < 3:
        return None
    return _sat_polygons(va, vb)


def _sat_circle_vs(circle: Prim, other: Prim) -> Optional[Contact]:
    cx, cy, r = circle.params[0], circle.params[1], circle.params[2]
    if other.kind == PrimKind.ELLIPSE:
        return _circle_ellipse(circle.params, other.params)
    verts = _prim_as_poly(other)
    if len(verts) < 3:
        return None
    axes = _axes_from_poly(verts)
    # Also axis from closest vertex / closest point toward center
    closest = min(verts, key=lambda p: _sq(p[0] - cx) + _sq(p[1] - cy))
    dx, dy = cx - closest[0], cy - closest[1]
    dlen = math.hypot(dx, dy)
    if dlen > 1e-12:
        axes.append((dx / dlen, dy / dlen))

    scored: List[Tuple[float, float, float]] = []
    ocx = sum(v[0] for v in verts) / len(verts)
    ocy = sum(v[1] for v in verts) / len(verts)
    for ax, ay in axes:
        amin, amax = _project_circle(cx, cy, r, ax, ay)
        bmin, bmax = _project_poly(verts, ax, ay)
        pen = _axis_penetration(amin, amax, bmin, bmax)
        if pen is None:
            return None
        scored.append((ax, ay, pen))
    best_axis, min_overlap = _select_sat_mtv(scored, cx, cy, ocx, ocy)

    # Contact point: closest point on polygon to circle center, clamped
    qx, qy = _closest_point_on_poly(cx, cy, verts)
    return Contact(best_axis, min_overlap, [(qx, qy)])


def _closest_point_on_poly(px: float, py: float, verts: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Closest point on the polygon *boundary* (never an interior point)."""
    best = verts[0]
    best_d = float("inf")
    n = len(verts)
    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]
        qx, qy = _closest_point_on_segment(px, py, ax, ay, bx, by)
        d = _sq(qx - px) + _sq(qy - py)
        if d < best_d:
            best_d = d
            best = (qx, qy)
    return best


def _closest_point_on_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    t = ((px - ax) * abx + (py - ay) * aby)
    denom = abx * abx + aby * aby
    if denom < 1e-18:
        return ax, ay
    t /= denom
    t = max(0.0, min(1.0, t))
    return ax + t * abx, ay + t * aby


def _point_in_polygon_xy(x: float, y: float, verts: Sequence[Tuple[float, float]]) -> bool:
    inside = False
    n = len(verts)
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _circle_ellipse(cparams, eparams) -> Optional[Contact]:
    # Approximate via SAT with ellipse support + circle; axes from ellipse local x/y.
    cx, cy, r = cparams[0], cparams[1], cparams[2]
    ex, ey, rx, ry, ang = eparams[0], eparams[1], eparams[2], eparams[3], eparams[4]
    c, s = math.cos(ang), math.sin(ang)
    axes = [(c, s), (-s, c)]
    # Also axis between centers
    dx, dy = ex - cx, ey - cy
    dlen = math.hypot(dx, dy)
    if dlen > 1e-12:
        axes.append((dx / dlen, dy / dlen))
    scored: List[Tuple[float, float, float]] = []
    for ax, ay in axes:
        amin, amax = _project_circle(cx, cy, r, ax, ay)
        bmin, bmax = _project_ellipse(ex, ey, rx, ry, ang, ax, ay)
        pen = _axis_penetration(amin, amax, bmin, bmax)
        if pen is None:
            return None
        scored.append((ax, ay, pen))
    best, min_overlap = _select_sat_mtv(scored, cx, cy, ex, ey)
    # Point on the circle, then back along the MTV onto the ellipse surface.
    reach = max(0.0, r - min_overlap)
    return Contact(best, min_overlap, [(cx + best[0] * reach, cy + best[1] * reach)])


def _sat_with_ellipse(pa: Prim, pb: Prim) -> Optional[Contact]:
    def project(p: Prim, ax: float, ay: float):
        if p.kind == PrimKind.ELLIPSE:
            return _project_ellipse(p.params[0], p.params[1], p.params[2], p.params[3], p.params[4], ax, ay)
        if p.kind == PrimKind.CIRCLE:
            return _project_circle(p.params[0], p.params[1], p.params[2], ax, ay)
        verts = _prim_as_poly(p)
        return _project_poly(verts, ax, ay)

    def center(p: Prim):
        if p.kind in (PrimKind.ELLIPSE, PrimKind.CIRCLE, PrimKind.OBB):
            return p.params[0], p.params[1]
        if p.kind == PrimKind.AABB:
            return (p.params[0] + p.params[2]) * 0.5, (p.params[1] + p.params[3]) * 0.5
        verts = _prim_as_poly(p)
        return sum(v[0] for v in verts) / len(verts), sum(v[1] for v in verts) / len(verts)

    acx, acy = center(pa)
    bcx, bcy = center(pb)

    # Build candidate axes from the non-ellipse side's edge normals (or both
    # ellipses' local axes), plus a closest-vertex axis toward the opposite
    # body's center for each polygon side — same corner-detection technique
    # used in `_sat_circle_vs`. Without it, a rounded body (ellipse) near a
    # box corner/end only has the two face normals as candidates, so SAT can
    # pick a face axis whose overlap happens to be smaller than the true
    # corner overlap (thin-slab side hit mistaken for a face hit).
    axes: List[Tuple[float, float]] = []
    for p, (ox, oy) in ((pa, (bcx, bcy)), (pb, (acx, acy))):
        if p.kind == PrimKind.ELLIPSE:
            ang = p.params[4]
            c, s = math.cos(ang), math.sin(ang)
            axes.append((c, s))
            axes.append((-s, c))
        else:
            if p.kind == PrimKind.CIRCLE:
                return _sat_circle_vs(p if p is pa else pb, pb if p is pa else pa)
            verts = _prim_as_poly(p)
            axes.extend(_axes_from_poly(verts))
            if verts:
                closest = min(verts, key=lambda v: _sq(v[0] - ox) + _sq(v[1] - oy))
                dx, dy = ox - closest[0], oy - closest[1]
                dlen = math.hypot(dx, dy)
                if dlen > 1e-12:
                    axes.append((dx / dlen, dy / dlen))

    scored: List[Tuple[float, float, float]] = []
    for ax, ay in axes:
        amin, amax = project(pa, ax, ay)
        bmin, bmax = project(pb, ax, ay)
        pen = _axis_penetration(amin, amax, bmin, bmax)
        if pen is None:
            return None
        scored.append((ax, ay, pen))
    best, min_overlap = _select_sat_mtv(scored, acx, acy, bcx, bcy)
    pts = _ellipse_contact_points(pa, pb, best[0], best[1])
    return Contact(best, min_overlap, pts)


def _ellipse_support(
    cx: float, cy: float, rx: float, ry: float, ang: float, ax: float, ay: float,
) -> Tuple[float, float]:
    c, s = math.cos(ang), math.sin(ang)
    lx = ax * c + ay * s
    ly = -ax * s + ay * c
    denom = math.hypot(rx * lx, ry * ly)
    if denom < 1e-12:
        return cx, cy
    slx = (rx * rx * lx) / denom
    sly = (ry * ry * ly) / denom
    return cx + slx * c - sly * s, cy + slx * s + sly * c


def _ellipse_contact_points(
    pa: Prim, pb: Prim, nx: float, ny: float,
) -> List[Tuple[float, float]]:
    """Contact on a polygon face when one exists; else ellipse support along MTV."""
    for poly, ellipse in ((pa, pb), (pb, pa)):
        if poly.kind in (PrimKind.AABB, PrimKind.OBB, PrimKind.POLY) and ellipse.kind == PrimKind.ELLIPSE:
            verts = _prim_as_poly(poly)
            if len(verts) >= 3:
                ecx, ecy = ellipse.params[0], ellipse.params[1]
                return [_closest_point_on_poly(ecx, ecy, verts)]
    # Two ellipses (or degenerate): support of A along n, on A's skin.
    if pa.kind == PrimKind.ELLIPSE:
        p = pa.params
        return [_ellipse_support(p[0], p[1], p[2], p[3], p[4], nx, ny)]
    if pb.kind == PrimKind.ELLIPSE:
        p = pb.params
        return [_ellipse_support(p[0], p[1], p[2], p[3], p[4], -nx, -ny)]
    return [((pa.params[0] + pb.params[0]) * 0.5, (pa.params[1] + pb.params[1]) * 0.5)]


def _support_face(verts: Sequence[Tuple[float, float]], nx: float, ny: float) -> int:
    """Index of the edge that lies on the supporting plane in direction ``n``."""
    n = len(verts)
    dots = [vx * nx + vy * ny for vx, vy in verts]
    imax = 0
    best = dots[0]
    for i in range(1, n):
        if dots[i] > best:
            best = dots[i]
            imax = i
    i_prev = (imax - 1) % n
    i_next = (imax + 1) % n
    if dots[i_prev] > dots[i_next]:
        return i_prev
    return imax


def _clip_segment(
    pts: Sequence[Tuple[float, float]],
    nx: float,
    ny: float,
    offset: float,
) -> List[Tuple[float, float]]:
    """Keep the portion of a 1- or 2-point chain where ``n·p <= offset``."""
    if not pts:
        return []
    if len(pts) == 1:
        d = nx * pts[0][0] + ny * pts[0][1] - offset
        return list(pts) if d <= 1e-9 else []
    p1, p2 = pts[0], pts[1]
    d1 = nx * p1[0] + ny * p1[1] - offset
    d2 = nx * p2[0] + ny * p2[1] - offset
    out: List[Tuple[float, float]] = []
    if d1 <= 0.0:
        out.append(p1)
    if d1 * d2 < 0.0:
        t = d1 / (d1 - d2)
        out.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    if d2 <= 0.0:
        out.append(p2)
    return out


def _project_on_plane(
    p: Tuple[float, float],
    origin: Tuple[float, float],
    nx: float,
    ny: float,
) -> Tuple[float, float]:
    sep = nx * (p[0] - origin[0]) + ny * (p[1] - origin[1])
    return (p[0] - sep * nx, p[1] - sep * ny)


def _poly_contact_points(
    va: Sequence[Tuple[float, float]],
    vb: Sequence[Tuple[float, float]],
    nx: float,
    ny: float,
) -> List[Tuple[float, float]]:
    """Incident-face clip: contact(s) on the reference face, not body centers.

    The more-aligned SAT face is the reference. The incident edge is clipped
    against that face's side planes and projected onto it — a face-face hit
    yields two clip points whose centroid (``CollisionInfo.point``) sits on
    the shared surface. Side hits on a wide rect land on the vertical face
    instead of halfway between the two centroids.
    """
    if len(va) < 2 or len(vb) < 2:
        return [((va[0][0] + vb[0][0]) * 0.5, (va[0][1] + vb[0][1]) * 0.5)]

    ia = _support_face(va, nx, ny)
    ib = _support_face(vb, -nx, -ny)

    def _align(verts, i, ax, ay) -> float:
        n = len(verts)
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        fnx, fny = ey, -ex
        ln = math.hypot(fnx, fny)
        if ln < 1e-12:
            return 0.0
        fnx /= ln
        fny /= ln
        return abs(fnx * ax + fny * ay)

    da = _align(va, ia, nx, ny)
    db = _align(vb, ib, -nx, -ny)
    if da >= db:
        ref, inc = va, vb
        ref_i = ia
        rnx, rny = nx, ny
    else:
        ref, inc = vb, va
        ref_i = ib
        rnx, rny = -nx, -ny

    nref = len(ref)
    ninc = len(inc)
    v1 = ref[ref_i]
    v2 = ref[(ref_i + 1) % nref]
    inc_i = _support_face(inc, -rnx, -rny)
    i1 = inc[inc_i]
    i2 = inc[(inc_i + 1) % ninc]

    tx, ty = v2[0] - v1[0], v2[1] - v1[1]
    tlen = math.hypot(tx, ty)
    if tlen < 1e-12:
        return [_project_on_plane(i1, v1, rnx, rny)]
    tx /= tlen
    ty /= tlen

    pts = _clip_segment((i1, i2), -tx, -ty, -tx * v1[0] - ty * v1[1])
    pts = _clip_segment(pts, tx, ty, tx * v2[0] + ty * v2[1])

    out: List[Tuple[float, float]] = []
    offset = rnx * v1[0] + rny * v1[1]
    for p in pts:
        sep = rnx * p[0] + rny * p[1] - offset
        if sep <= 1e-4:
            out.append((p[0] - sep * rnx, p[1] - sep * rny))
    if out:
        return out
    return [_project_on_plane(i1, v1, rnx, rny)]


def _sat_polygons(va: Sequence[Tuple[float, float]], vb: Sequence[Tuple[float, float]]) -> Optional[Contact]:
    axes = _axes_from_poly(va) + _axes_from_poly(vb)
    scored: List[Tuple[float, float, float]] = []
    acx = sum(v[0] for v in va) / len(va)
    acy = sum(v[1] for v in va) / len(va)
    bcx = sum(v[0] for v in vb) / len(vb)
    bcy = sum(v[1] for v in vb) / len(vb)
    for ax, ay in axes:
        amin, amax = _project_poly(va, ax, ay)
        bmin, bmax = _project_poly(vb, ax, ay)
        pen = _axis_penetration(amin, amax, bmin, bmax)
        if pen is None:
            return None
        scored.append((ax, ay, pen))
    best, min_overlap = _select_sat_mtv(scored, acx, acy, bcx, bcy)
    return Contact(best, min_overlap, _poly_contact_points(va, vb, best[0], best[1]))


# ---------------------------------------------------------------------------
# Collider
# ---------------------------------------------------------------------------

def _shape_layer_name(shape) -> Optional[Union[str, int]]:
    name = getattr(shape, "layer", None)
    if name is None:
        name = getattr(shape, "_layer", None)
    return name


def _collision_layer_error(shape):
    """``(exception class, message)`` when ``shape`` cannot enroll, else None.

    A missing layer is allowed (same as enrollment, which only rejects a layer
    it can see). Does not follow a hitbox part to its host — callers that
    name the host pass the host.
    """
    try:
        from .canvas import ScenaCanvas
        from .registry import ParallaxLayerError, UiLayerError, normalize_layer_name, UI_LAYER

        registry = ScenaCanvas.get_current().registry
    except Exception:
        return None
    raw = _shape_layer_name(shape)
    name = normalize_layer_name(raw)
    if name is None:
        return None
    if name == UI_LAYER:
        return (
            UiLayerError,
            f"Cannot enroll {shape!r} in collision: layer 'ui' is "
            f"view-space (no collision)",
        )
    layer = registry.layers.get(name)
    if layer is not None and not layer._is_neutral_response:
        return (
            ParallaxLayerError,
            f"Cannot enroll {shape!r} in collision: layer {name!r} is a "
            f"parallax layer (decoration-only; no hit-testing or collision)",
        )
    return None


def _on_collision_layer(shape) -> bool:
    """False for ``ui`` and parallax. A hitbox part follows its host's layer."""
    subject = shape
    if getattr(type(shape), "_is_hitbox_part", False):
        ref = getattr(shape, "_host_ref", None)
        host = ref() if callable(ref) else None
        if host is not None:
            subject = host
    return _collision_layer_error(subject) is None


def _assert_shapes_not_parallax(shapes: Sequence[Any]) -> None:
    """Raise :class:`ParallaxLayerError` if any shape lives on a non-neutral layer.

    Validation only — no registry or collider mutation. Used before any
    enrollment so mixed lists / @collide decoration stay all-or-nothing.
    """
    for shape in shapes:
        if shape is None:
            continue
        problem = _collision_layer_error(shape)
        if problem is not None:
            exc, msg = problem
            raise exc(msg)


def _has_query_geometry(item) -> bool:
    """True when ``item`` can produce collision prims.

    A bare ``Entity`` (director, spawner) has no body. Enrollment does not
    filter those either — it just builds an empty proxy — but a named query
    should not allocate a collider for one. ``Text`` is a Graphic with empty
    prims; it is allowed through and then fails the proxy refresh.
    """
    if getattr(type(item), "_is_hitbox_part", False):
        return True
    from .entity import Graphic
    from .spatial_fx import SpatialFx
    return isinstance(item, (Graphic, SpatialFx))


def _is_query_actor(atom) -> bool:
    """An object atom of the query ``group=`` grammar (not a tag string)."""
    if isinstance(atom, Collider):
        return True
    if getattr(type(atom), "_is_hitbox_part", False):
        return True
    from .registry import GroupOperator
    if isinstance(atom, GroupOperator):
        return True
    from .entity import Entity
    return isinstance(atom, Entity)


def _query_group_type_error(value) -> TypeError:
    return TypeError(
        "group= must be a tag string, group['tag'], an actor, ANYTHING, "
        f"or a list of those; got {type(value).__name__} {value!r}. "
        'Write group="enemies" or group=["enemies", "rocks"].'
    )


def _parse_query_atom(item):
    """One ``group=`` atom. ``ANYTHING`` stays the sentinel."""
    if item is ANYTHING:
        return item
    if isinstance(item, str):
        if item == "":
            raise ValueError(
                'group= must be a non-empty tag. Write group="enemies".'
            )
        return item
    if _is_query_actor(item):
        return item
    raise _query_group_type_error(item)


def _parse_query_group(group) -> Optional[List[Any]]:
    """Expand ``group=`` for queries.

    ``None`` means the enrolled collision world (``group`` omitted, ``None``,
    or ``ANYTHING``). A list — possibly empty — is the atoms to test.
    ``list`` / ``tuple`` / ``set`` / ``frozenset`` are the same grammar.
    """
    if group is None or group is ANYTHING:
        return None
    if isinstance(group, str):
        return [_parse_query_atom(group)]
    if isinstance(group, (list, tuple, set, frozenset)):
        return [_parse_query_atom(item) for item in group]
    return [_parse_query_atom(group)]


def _collect_entities_from_target(target) -> List[Any]:
    """Collect Entity shapes implied by a pair-handler target (no enrollment)."""
    if target is ANYTHING or isinstance(target, str):
        # Tags / ANYTHING: members known at decorate time via group map is
        # incomplete for live groups; tags are re-checked when members appear.
        # Still validate currently-known group members for string tags.
        if isinstance(target, str):
            try:
                from .canvas import ScenaCanvas
                registry = ScenaCanvas.get_current().registry
                return list(registry.list_by_groupid(target))
            except Exception:
                return []
        return []
    if isinstance(target, Collider):
        return list(target.shapes)
    from .registry import GroupOperator
    from .entity import Entity
    if isinstance(target, GroupOperator):
        return list(target)
    if isinstance(target, Entity):
        return [target]
    return []


def _side_code(side) -> str:
    """A resolve side as the author would type it in ``unresolve(...)``."""
    if isinstance(side, str):
        return f'"{side}"'
    if side is ANYTHING:
        return "ANYTHING"
    if isinstance(side, Collider):
        side = side._identity
    from .entity import entity_label
    return f"<{entity_label(side)}>"


def resolve_calls_for(shape) -> List[str]:
    """Argument lists of the standing ``resolve()`` pairs that enroll ``shape``.

    Grouped by the side ``shape`` is on: ``('("heroi", ["plataforma", "parede"])',)``.
    Feeds ``resolve…`` / ``unresolve…`` hints, which must name **every** pair —
    ``unresolve("heroi", "plataforma")`` alone leaves a member enrolled via
    ``"parede"``.
    """
    sys = _collision_system
    c = getattr(shape, "_collider", None)
    if sys is None or c is None:
        return []
    by_side: Dict[str, List[str]] = {}
    for ta, tb, _tok, _only in sys._resolve_pairs:
        for own, other in ((ta, tb), (tb, ta)):
            if sys._collider_on_resolve_side(c, own):
                partners = by_side.setdefault(_side_code(own), [])
                code = _side_code(other)
                if code not in partners:
                    partners.append(code)
    out = []
    for own, partners in by_side.items():
        rhs = partners[0] if len(partners) == 1 else "[" + ", ".join(partners) + "]"
        out.append(f"({own}, {rhs})")
    return out


def _note_resolve_enroll_shapes(shapes) -> None:
    """Eager persistent-driver enroll for standing ``resolve()`` sides."""
    for shape in shapes:
        note = getattr(shape, "_note_resolve_enroll", None)
        if callable(note):
            note()


def _note_resolve_unenroll_shapes(shapes) -> None:
    for shape in shapes:
        note = getattr(shape, "_note_resolve_unenroll", None)
        if callable(note):
            note()


def _sync_resolve_driver_for_collider(
    sys: "CollisionSystem", collider: "Collider", group: Optional[str] = None,
) -> None:
    """Set/clear ``_resolve_enrolled`` from current resolve-pair membership.

    ``group`` is the tag being joined (late join), named in a formula refusal.
    """
    want = sys._collider_in_resolve(collider)
    for shape in collider.shapes:
        have = getattr(shape, "_resolve_enrolled", False)
        if want and not have:
            note = getattr(shape, "_note_resolve_enroll", None)
            if callable(note):
                if group is not None:
                    note(group)
                else:
                    note()
        elif not want and have:
            note = getattr(shape, "_note_resolve_unenroll", None)
            if callable(note):
                note()


def _refuse_part_resolve_side(sys: "CollisionSystem", side) -> None:
    """``resolve()`` moves bodies: a ``Hitbox`` part only detects.

    A *group* a part answers for is fine — resolve uses its members' bodies.
    """
    if _is_part_side(side):
        raise TypeError(
            f"resolve() does not take a hitbox part ({side!r}); parts only detect. "
            f"Resolve the sprite itself: resolve(sprite, ...) uses its body hitbox."
        )


def _tag_is_resolve_side(sys: "CollisionSystem", tag: str) -> bool:
    for a, b, _tok, _only in sys._resolve_pairs:
        if sys._pair_tag_of(a) == tag or sys._pair_tag_of(b) == tag:
            return True
    return False


def _named_side_entities(side) -> List[Any]:
    """The actors a side names directly (an actor, a ``Collider``'s pieces).
    Members reached through a group (a tag, ``group[...]``, a snapshot of
    groups) are not named: one on ``ui`` or a parallax layer has no body and
    is skipped, whatever the order of the tag and the rule (review 2026-10-09
    S9-1, decided)."""
    from .entity import Entity
    if isinstance(side, Collider):
        return list(side.shapes)
    if isinstance(side, Entity):
        return [side]
    return []


def _assert_named_sides_not_parallax(sides) -> None:
    items: List[Any] = []
    for side in sides:
        items.extend(_named_side_entities(side))
    _assert_shapes_not_parallax(items)


def _assert_target_not_parallax(target) -> None:
    """Validate all Entities currently implied by a pair target."""
    _assert_shapes_not_parallax(_collect_entities_from_target(target))


def _is_multi_body(c) -> bool:
    """An author ``Collider([a, b, ...])`` of several pieces (not a shape's
    own implicit body, not a single-shape Collider)."""
    return c._identity_shape is None and len(c._shapes) > 1


def _bodies_first(colliders) -> List[Any]:
    """Query hits as identities, multi-piece bodies first (each group in
    registration order). A piece that is also a body of its own answers
    after the body it belongs to, whatever line ran first (AC10)."""
    if any(_is_multi_body(c) for c in colliders):
        colliders = sorted(colliders, key=lambda c: 0 if _is_multi_body(c) else 1)
    return [c._identity for c in colliders]


class Collider:
    """Several shapes that collide as one body.

    ``body = Collider([torso, head])`` makes one collision participant out of
    the pieces: ``@collide(body, "bolt")`` fires once for the body, and the
    handler's ``me`` is the Collider, not the piece that was hit. The pieces
    keep drawing and moving on their own; the Collider only joins them for
    collision. A single shape needs no Collider: name it in ``@collide`` /
    ``resolve`` directly.

    Engine notes: overlap tests run only for declared relations (``@collide`` /
    ``resolve`` pair targets, or ``ANYTHING``); categories are the shapes'
    ``group`` tags; parallax layers are refused before any registry change.
    Enrollment builds an implicit Collider per shape (engine keywords
    ``_identity_shape`` / ``_register`` / ``_bind``, not author API).

    Args:
        shapes: The shapes that make up the body (a list; one shape is accepted
            too).

    Attributes:
        shapes: The live pieces (destroyed ones drop out).
        on_collide: Called on the first frame of contact with anything:
            ``fn(me, other, info)``.
        on_collide_stay: Called on each following frame of contact.
        on_collide_exit: Called when the contact ends.
    """

    __slots__ = (
        "_shapes",
        "_pair_targets",
        "_on_collide",
        "_on_collide_stay",
        "_on_collide_exit",
        "_identity_shape",
        "_system",
        "_born",
        "_poly_cache",
        "_snap_cache",
        "_tags_cache",
        "_proxy",
        "_proxy_key",
        "_proxy_revs",
        "_proxy_valid",
        "_world_prims",
        "_world_key",
        "_motion_dx",
        "_motion_dy",
        "_motion_translation",
        "_pending_motion_dx",
        "_pending_motion_dy",
        "_proxy_start",
        "_pending_path",
        "_motion_path",
        "_thick2",
        "_resolved_aabb",
        "_resolved_key",
        "_in_resolve",
        "_part",
        "_end_cx",
        "_end_cy",
        "__weakref__",
    )

    def __init_subclass__(cls, **kwargs) -> None:
        # A callback method (``def on_collide``) is refused at the class line
        # when async, as ``on_collide =`` refuses it at the assignment.
        super().__init_subclass__(**kwargs)
        for name in ("on_collide", "on_collide_stay", "on_collide_exit"):
            fn = cls.__dict__.get(name)
            if fn is not None and not isinstance(fn, property):
                _refuse_async(fn, what=f"class {cls.__name__}: def")

    def __init__(
        self,
        shapes,
        *,
        _identity_shape=None,
        _register: bool = True,
        _bind: bool = True,
    ):
        identity = _identity_shape
        if shapes is None:
            raise TypeError("Collider requires at least one shape")
        if not isinstance(shapes, (list, tuple)):
            shapes = [shapes]
        if not shapes:
            raise TypeError("Collider requires at least one shape")
        # Validate *before* any mutation (all-or-nothing).
        from .entity import Entity
        for s in shapes:
            if not (isinstance(s, Entity) or getattr(type(s), "_is_hitbox_part", False)):
                # Value shown only for None / numbers (no object reprs in messages).
                simple = s is None or isinstance(s, (int, float, complex))
                shown = f" {s!r}" if simple else ""
                raise TypeError(
                    "Collider pieces must be shapes or sprites; "
                    f"got {type(s).__name__}{shown}. Write Collider([torso, head])."
                )
        if _register:
            # A registered collider is a body; an unregistered one is a query
            # probe (``test_collision`` / ``collides_with`` on a part are fine).
            from .entity import refuse_part_as_actor
            for s in shapes:
                refuse_part_as_actor(s, "Collider([...])", "body")
        to_check = list(shapes)
        if identity is not None and identity not in to_check:
            to_check.append(identity)
        _assert_shapes_not_parallax(to_check)
        self._shapes = [weakref.ref(s) for s in shapes]
        # Targets from @collide / resolve: Shape | Collider | GroupOperator | str | ANYTHING
        self._pair_targets: List[Any] = []
        self._on_collide = None
        self._on_collide_stay = None
        self._on_collide_exit = None
        self._identity_shape = weakref.ref(identity) if identity is not None else None
        self._system = get_collision_system()
        # The commit serial at creation: a collider made since the last
        # commit is in no contact, so its tag or hook changes note nothing
        # (``_note_flux``; a body spawned with two pair tags stays free).
        self._born = self._system._commit_serial
        # shape id → (verts_key, prims) for concave decomposition reuse
        self._poly_cache: Dict[int, Tuple[tuple, List[Prim]]] = {}
        # shape id → (pose_key, prims) — skip rebuild when pose/hitbox unchanged
        self._snap_cache: Dict[int, Tuple[tuple, List[Prim]]] = {}
        self._tags_cache: Optional[frozenset] = None
        self._proxy = [0.0, 0.0, 0.0, 0.0]
        self._proxy_key: Optional[tuple] = None
        self._proxy_revs: Optional[tuple] = None   # shapes' pose revisions at the last key
        self._proxy_valid = False
        self._world_prims: Optional[List[Prim]] = None
        self._world_key: Optional[tuple] = None
        self._motion_dx = 0.0
        self._motion_dy = 0.0
        self._motion_translation = True
        self._pending_motion_dx = 0.0
        self._pending_motion_dy = 0.0
        self._proxy_start: Optional[List[float]] = None
        # Waypoints of this frame's motion when it is not one straight chord
        # (a fast orbit: W-T5): cumulative offsets from the frame's start.
        self._pending_path: Optional[List[Tuple[float, float]]] = None
        self._motion_path: Optional[List[Tuple[float, float]]] = None
        # Squared thickness (smaller proxy side, pad removed), refreshed when
        # the proxy is rebuilt; the swept-detection gate reads it.
        self._thick2 = 0.0
        # Unpadded proxy at the end of the previous step. None until a step
        # has stored one. Unswept-bounds recovery reads this; it is not motion.
        self._resolved_aabb: Optional[Tuple[float, float, float, float]] = None
        # The ``_proxy_key`` object ``_resolved_aabb`` was built from: a new
        # pose or a nudge assigns a new key, so the same object is the same box.
        self._resolved_key = None
        self._in_resolve = False
        # The Hitbox when this collider is a sprite's hitbox part (else None).
        self._part = None
        # Proxy center at the end of the last step it moved in (None: never):
        # this step's placement is the proxy's shift since, less its motion
        # (``_placement_of``; swept detection, R2-2).
        self._end_cx: Optional[float] = None
        self._end_cy: Optional[float] = None
        if _register:
            self._system.register(self)
        # Single-shape explicit Collider: bind so shape.collidable / @collide
        # reuse this instance instead of creating a second one. Queries pass
        # _bind=False so a probe does not become an ANYTHING partner.
        if _bind:
            bound = shapes[0] if identity is None and len(shapes) == 1 else identity
            prev = getattr(bound, "_collider", None) if bound is not None else None
            if prev is not None and prev is not self:
                sysm = prev._system
                if id(prev) in sysm._collider_index:
                    sysm._unbound.add(prev)     # still registered, now unreachable
            if identity is None and len(shapes) == 1:
                shapes[0]._collider = self
                shapes[0]._collidable = True
            elif identity is not None:
                identity._collider = self
                identity._collidable = True
        if type(self) is not Collider:
            # A subclass may define ``on_collide`` & co. as methods (they
            # override the properties): they count as set callbacks, with
            # ANYTHING interest, as an assignment would.
            self._sync_anything_interest()

    __init__.__signature__ = inspect.Signature([
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("shapes", inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ])

    @property
    def shapes(self) -> List[Any]:
        """The live pieces of this body (a destroyed piece drops out)."""
        out = []
        for ref in self._shapes:
            s = ref()
            # After Shape.destroy()/clean_up(), node_id is cleared — treat as gone
            # even if a Python strong reference keeps the weakref alive.
            if s is not None and getattr(s, "_node_id", None) is not None:
                out.append(s)
        return out

    @property
    def _identity(self):
        if self._identity_shape is not None:
            s = self._identity_shape()
            if s is not None:
                return s
        return self

    def _group_tags(self) -> frozenset:
        """Union of ``group`` on live shapes (cached until cleared each step)."""
        cached = self._tags_cache
        if cached is not None:
            return cached
        tags: Set[str] = set()
        for s in self.shapes:
            gids = getattr(s, "group", None)
            if gids:
                tags.update(gids)
                if self._part is None:
                    claims = getattr(s, "_hitbox_claims", None)
                    if claims:
                        tags.difference_update(claims)
        self._tags_cache = frozenset(tags)
        return self._tags_cache

    def _add_pair_target(self, target) -> None:
        if target not in self._pair_targets:
            self._pair_targets.append(target)

    def _remove_pair_target(self, target) -> None:
        try:
            self._pair_targets.remove(target)
        except ValueError:
            pass

    def _sync_anything_interest(self) -> None:
        """Keep ``ANYTHING`` in ``_pair_targets`` iff callbacks or handlers need it."""
        from_callbacks = (
            self.on_collide is not None
            or self.on_collide_stay is not None
            or self.on_collide_exit is not None
        )
        from_handlers = self._system._collider_has_handler_anything(self)
        if from_callbacks or from_handlers:
            self._add_pair_target(ANYTHING)
        else:
            self._remove_pair_target(ANYTHING)

    def _wants(self, other: "Collider") -> bool:
        """True if this collider declared interest in ``other`` (one-sided OK).

        String pair-targets (group tags) are O(tags): membership on ``other``,
        not an expansion of the whole group. Object / GroupOperator targets still
        resolve to colliders.
        """
        if not self._pair_targets:
            return False
        other_tags = None
        sys = self._system
        for t in self._pair_targets:
            if t is ANYTHING:
                return True
            if isinstance(t, str):
                if other_tags is None:
                    other_tags = other._group_tags()
                if t in other_tags:
                    return True
                continue
            for c in sys._resolve_target_to_colliders(t):
                if c is other:
                    return True
        return False

    # The three callbacks are properties so that setting one keeps ANYTHING
    # interest in sync; every other attribute is a plain slot write (a
    # ``__setattr__`` hook taxed the step's ~10 writes per collider).
    @property
    def on_collide(self):
        """Called on the first frame of contact with anything, or None."""
        return self._on_collide

    @on_collide.setter
    def on_collide(self, value) -> None:
        if value is not None:
            _refuse_async(value, what="on_collide =")
            if value is not self._on_collide:
                self._note_new_hook(value)
        self._on_collide = value
        self._sync_anything_interest()

    @property
    def on_collide_stay(self):
        """Called on each following frame of contact, or None."""
        return self._on_collide_stay

    @on_collide_stay.setter
    def on_collide_stay(self, value) -> None:
        if value is not None:
            _refuse_async(value, what="on_collide_stay =")
            if value is not self._on_collide_stay:
                self._note_new_hook(value)
        self._on_collide_stay = value
        self._sync_anything_interest()

    @property
    def on_collide_exit(self):
        """Called when the contact ends, or None."""
        return self._on_collide_exit

    @on_collide_exit.setter
    def on_collide_exit(self, value) -> None:
        if value is not None:
            _refuse_async(value, what="on_collide_exit =")
        self._on_collide_exit = value
        self._sync_anything_interest()

    def _note_new_hook(self, fn) -> None:
        """An enter / stay hook set while this body may touch something: a
        rule its touching pairs gain (CD3)."""
        sys = self._system
        if sys._prev_contacts and self._born < sys._commit_serial:
            sys._new_rules[(0, id(self), id(fn))] = id(self)

    def _unregister(self) -> None:
        self._system.unregister(self)


# ---------------------------------------------------------------------------
# CollisionSystem / World
# ---------------------------------------------------------------------------

class CollisionSystem:
    """Owns the collider registry and runs one collision step per frame."""

    def __init__(self):
        self._colliders: List[Collider] = []
        # Registered multi-piece bodies (``Collider([a, b])``), so the broad
        # phase finds a body / own-piece pair without walking every collider.
        self._multi_bodies: Dict[int, Collider] = {}
        self._prev_contacts: Set[Tuple[int, int]] = set()
        # The step's enters / exits not dispatched yet. A body destroyed (or
        # parked) mid-step: a pending enter is dropped with no exit (its enter
        # never ran, S8-3); a pending exit fires at that moment, while the
        # body still exists, instead of on a dead body later (X-life-2).
        self._enter_pending: Set[Tuple[int, int]] = set()
        # ``_phase_handlers`` snapshot: ((epoch, len), {phase: handlers}).
        self._phase_cache = None
        # An author handler ran in this step's dispatch (W-G1).
        self._author_ran = False
        self._exit_pending: Set[Tuple[int, int]] = set()
        # Per-rule contacts (CD3). A rule's contact with a touching pair is
        # read at each commit (``_prev_contacts = …`` in ``step``): it begins
        # where a commit first finds the rule matching, ends where one finds
        # it not matching. ``_rule_flux`` holds the tag changes of colliders
        # that may be touching since the last commit: {id(collider):
        # (collider, {tag: [member at that commit, {partner ids it touched
        # when it left}]})} (the first change sets the flag; a tag left
        # counts only for a contact that had entered: PB1). ``_new_rules``
        # holds the handlers and ``on_collide*`` hooks set since the last
        # commit, as rule keys (``_rule_key``) → the hook's collider id, or
        # None for a pair handler. The commit moves both to ``_flux_now`` /
        # ``_new_rules_now``, read by that step's dispatch.
        self._rule_flux: Dict[int, Tuple[Collider, Dict[str, list]]] = {}
        self._new_rules: Dict[tuple, Optional[int]] = {}
        self._flux_now: Dict[int, Tuple[Collider, Dict[str, list]]] = {}
        self._new_rules_now: Dict[tuple, Optional[int]] = {}
        self._commit_serial = 0
        # This step's touching keys whose rules changed: ``_gain_pending``
        # {key: enter rule keys gained} until the key's slot in the enter
        # loop (an exit before it runs no gained rule: S8-3 per rule);
        # ``_stay_skip`` {key: stay rule keys gained} (they stay from the
        # next step, C1); ``_lost_pending`` {key: (exit runs, epoch)}
        # until the exit loop (or an exit at a destroy) runs them;
        # ``_exited_now`` the keys the commit found apart (their exits read
        # the rules as of the commit before).
        self._gain_pending: Dict[Tuple[int, int], Set[tuple]] = {}
        self._stay_skip: Dict[Tuple[int, int], Set[tuple]] = {}
        self._lost_pending: Dict[Tuple[int, int], tuple] = {}
        self._exited_now: Set[Tuple[int, int]] = set()
        # Bumped when a collider leaves or a pair handler is removed: a
        # dispatch whose epoch moved re-checks registration before each later
        # exit handler (S4-1); the ``_phase_handlers`` snapshot is keyed by it.
        self._dispatch_epoch = 0
        # Bumped on every act change (``drop_act_pair_handlers``): an enter /
        # stay dispatch that saw it stops on a dead side and skips handlers
        # the act took with it (S4-1). A destroy alone does not (PB5).
        self._act_change_epoch = 0
        # This step's detection contacts while its handlers run (enter / stay
        # / exit loops), else None: a resolve partner a handler removes there
        # leaves a ghost contact for the survivor's velocity response (PE5).
        self._dispatch_current: Optional[Dict[Tuple[int, int], "CollisionInfo"]] = None
        self._dispatch_ids: Optional[Dict[int, Collider]] = None
        # The contact whose enter / stay handlers are running (its key), and
        # the exit a destroy or park of one of its sides owes it: deferred to
        # after that contact's last handler, so a contact's handlers always
        # read enter, then exit (PB5 follow-up).
        self._contact_key: Optional[Tuple[int, int]] = None
        self._deferred_exit: Optional[Tuple[Any, ...]] = None
        self._ghost_contacts: List[Tuple[Any, ...]] = []
        # This step's removed partners as still walls, by survivor id
        # (``_apply_ghost_contacts``), and those the survivor's sweep met.
        self._ghost_walls: Dict[int, List[Tuple["_GhostPartner", Any, float, float]]] = {}
        self._ghosts_met: Set[int] = set()
        # This step's resting-skin contact keys (``_answer_unreached``).
        self._skin_keys: List[Tuple[int, int]] = []
        self._show = False
        self._debug_shapes: List[Any] = []  # legacy shape-based overlay (cleared on disable)
        self._debug_overlay: List[Tuple[Any, Prim]] = ()
        # ``floor_below`` probes since the last debug draw: id(body) → (prims, found).
        self._debug_probes: Dict[int, Tuple[List[Prim], bool]] = {}
        self._debug_paint: Optional[skia.Paint] = None
        # Pair handlers: (target_a, target_b, callback, phase)
        self._pair_handlers: List[Tuple[Any, Any, Callable, str]] = []
        # Script-level ``@collide`` entries made after the top level ended
        # (inside an act): removed on an act change (``drop_act_pair_handlers``).
        self._act_pair_handlers: List[Tuple[Any, Any, Callable, str]] = []
        # Colliders a real bounce impulse sent off a partner in the last step
        # and in this one (``_respond_velocity``): floor snap lets them leave
        # (persona probes round 2, R2-1). Cleared and rotated by ``step()``.
        self._bounced_prev: Set[int] = set()
        self._bounced_now: Set[int] = set()
        # Colliders whose proxy changed this step (snapshot or a solver nudge):
        # their end-of-step centers are stored (``_store_end_centers``).
        self._moved_now: Set["Collider"] = set()
        # ``resolve`` pairs at the seal (``run()`` ended the top level): an act
        # change puts them back (``restore_sealed_resolve_pairs``). Owned here
        # so a destroyed side leaves it like every other pair list (HD2).
        self._sealed_resolve_pairs: Optional[List[Tuple[Any, Any, Any, Any]]] = None
        # Standing resolve pairs: (target_a, target_b, bounce_token, only)
        # bounce_token is _RESOLVE_POSITION_ONLY or a float restitution.
        # only is None (every side blocks), a frozenset of target_a's sides,
        # or a callable of a TouchingContact (see ``_normalize_only``).
        self._resolve_pairs: List[Tuple[Any, Any, Any, Any]] = []
        # Any pair with ``only=``. False keeps the solver on the unfiltered
        # path: one bool read per body per frame (``_apply_auto_resolve``).
        self._has_only = False
        # Incremental @collide tag index (enroll on membership, not each step).
        # Not group membership — declared pair tags only. Named queries walk
        # the registry group instead (see ``_candidates_for_group``).
        self._pair_tags: Set[str] = set()
        self._tag_colliders: Dict[str, List[Collider]] = {}
        # Unregistered colliders for named queries. Keyed by the body or part
        # so a per-frame ``collides_with`` reuses world prims. Dropped when
        # the item enrolls for real, leaves play, or is collected.
        self._query_colliders: "weakref.WeakKeyDictionary[Any, Collider]" = (
            weakref.WeakKeyDictionary()
        )
        self._tag_index: Dict[str, Dict[int, int]] = {}
        # Bodies of sprites whose hitbox part answers for a tag that is a
        # resolve() side. ``resolve`` moves bodies; ``_tag_colliders`` lists
        # who *answers* (the part), so these bodies live here instead.
        self._claimed_bodies: Dict[str, List[Collider]] = {}
        self._claimed_body_index: Dict[str, Dict[int, int]] = {}
        self._collider_index: Dict[int, int] = {}
        self._debug_enroll_count = 0
        self._debug_hull_builds = 0
        # Last world snapshot (for queries)
        self._last_prims: List[Tuple[Collider, Prim]] = []
        self._last_groups: List[Collider] = []
        self._last_aabb: Optional[np.ndarray] = None  # collider proxy AABBs
        # Cleared at the start of each step — caches object-literal expansions.
        self._resolve_cache: Dict[Any, List[Collider]] = {}
        # Moved set (B2): colliders whose pose moved since their proxy was
        # built (drained from state.DIRTY_POSE_CELLS), colliders whose pose can
        # change with no write (links, Text, parts...: refreshed every time),
        # and colliders whose proxy box changed since the numpy mirror.
        self._stale: Set["Collider"] = set()
        self._untrusted: Set["Collider"] = set()
        self._row_dirty: Set["Collider"] = set()
        self._boxes = None                   # numpy (n, 4), row i = _colliders[i]
        self._boxes_version = -1
        self._struct_version = 0             # _colliders order / membership
        self._tag_version = 0                # tag index membership
        self._group_rows_cache: Dict[Any, tuple] = {}
        # Object-literal @collide targets that were already warned as destroyed.
        self._dead_target_warned: Set[int] = set()
        # Last-step contacts from sweep/settle (feeds touching_*).
        self._solve_contacts: Dict[Tuple[int, int], CollisionInfo] = {}
        self._contact_memory: Dict[Tuple[int, int], Tuple[float, float]] = {}
        # Per-pair contact sides (canonical lo→hi) + bottom refcounts for O(1)
        # floor-snap early-out (avoids scanning ``_solve_contacts``).
        self._solve_contact_sides: Dict[Tuple[int, int], Tuple[Optional[str], Optional[str]]] = {}
        self._solve_bottom_count: Dict[int, int] = {}
        # Bodies whose resolve turn began this pass, and the pass's STATIC
        # resolve bodies (``_share_sweep_stop``, ``_push_reach``).
        self._swept_ids: Set[int] = set()
        self._pass_statics: List["Collider"] = []
        self._pass_static_rows = None
        self._push_wall_normal = (0.0, 0.0)     # the last clamped push's wall
        self._pass_members: Dict[int, Any] = {}   # _push_reach: partner ids per body
        # This pass's riders (PB2): id(rider) -> (carrier, carry_x, carry_y),
        # or None when nobody is carried (``_carry_riders``).
        self._pass_carry: Optional[Dict[int, Tuple["Collider", float, float]]] = None
        # Standing resolve on/off. Detection, queries, and @collide stay live.
        self._resolve_enabled = True
        # Fast colliders of the current step (swept detection). Filled by
        # ``_commit_pending_motion`` only during the proxy loop of ``step()``
        # (``_fast_k2`` is the squared fraction there and ``inf`` elsewhere,
        # so a commit outside it never lists), emptied when the narrow phase
        # ends.
        self._fast_colliders: List[Collider] = []
        self._fast_k2 = math.inf
        # True after a frame that published non-empty ``touching_*``.
        # @collide-only scenes skip the Graphic walk until a leftover must clear.
        self._touching_published = False
        # When True, ``_world_prims`` may reuse proxy-synced caches. Only set
        # during standing resolve, after ``_update_proxy`` — queries in
        # ``update()`` still read live pose.
        self._trust_proxy_world = False
        # Cross-frame partner identity cache: ca_id → [(partner, bounce_token)].
        # Motion deltas are refreshed each read. Cleared on enroll / pair edits.
        self._partner_ident_cache: Dict[int, List[Tuple[Collider, Any]]] = {}
        # Resolve partners shared by every body of one signature (its on-side
        # flags per registration): ``_shared_partners``. ``_partner_sig_cache``
        # is each body's signature. Dropped with the per-body lists.
        self._shared_pools: Dict[tuple, "_SharedPartners"] = {}
        self._partner_sig_cache: Dict[int, tuple] = {}
        # Colliders whose body read a non-empty touching_* at the last publish.
        self._touching_live: Dict[int, "Collider"] = {}
        # The step's snapshot visits, besides moved (``_stale``), untrusted and
        # compound colliders: those with motion to commit or to reset
        # (``_snap_hot``) and those a clock can rebake (``_timed``).
        self._snap_hot: Set["Collider"] = set()
        self._timed: Set["Collider"] = set()
        # Registered colliders no revision cell reaches: a shape's implicit
        # collider after ``Collider([shape])`` took its ``_collider`` (the
        # drain maps a moved root to ``root._collider`` only). Visited always.
        self._unbound: Set["Collider"] = set()
        # id(body) → (ident list, struct version, mirror rows, member ids).
        self._partner_rows_cache: Dict[int, Tuple[Any, int, Any, Set[int]]] = {}
        # Same lifetime: ca_id → {partner_id: (spec, flip)} for ``only=``
        # partners, or None when no partner of ``ca`` is filtered. A set spec
        # is already in ``ca``'s view; a callable spec keeps ``flip``.
        self._partner_only_cache: Dict[int, Optional[Dict[int, Tuple[Any, bool]]]] = {}
        # Passing ``only=`` pairs: body_id → {partner_id: partner}. Stored on
        # both bodies. A passing pair is invisible to sweep, settle and snap
        # until the two stop overlapping (``_only_view``).
        self._passing: Dict[int, Dict[int, Collider]] = {}
        # Last-step counters / timings (ms); for benches and profiling.
        self.last_stats: Dict[str, float] = {
            "proxies": 0,
            "prims": 0,
            "proxy_pairs": 0,
            "narrow": 0,
            "sat": 0,
            "skin": 0,
            "ms_snapshot": 0.0,
            "ms_broad": 0.0,
            "ms_narrow": 0.0,
            "ms_resolve": 0.0,
            "ms_total": 0.0,
        }

    @property
    def resolve_enabled(self) -> bool:
        """When False, skip sweep/settle/floor snap. Detection stays on."""
        return self._resolve_enabled

    @resolve_enabled.setter
    def resolve_enabled(self, value: bool) -> None:
        self._resolve_enabled = bool(value)

    # -- registration -------------------------------------------------------

    def register(self, collider: Collider) -> None:
        cid = id(collider)
        if cid in self._collider_index:
            return
        self._collider_index[cid] = len(self._colliders)
        self._colliders.append(collider)
        self._struct_version += 1
        if _is_multi_body(collider):
            self._multi_bodies[cid] = collider
        # An ANYTHING / object expansion cached by a query earlier in this
        # update must include the newcomer, as leaving drops it
        # (``_swap_remove_collider``): a partner list rebuilt from a stale
        # expansion outlives the frame (PF1).
        if self._resolve_cache:
            self._resolve_cache.clear()
        self._invalidate_partner_cache_for_enroll()
        self._update_proxy(collider)

    def unregister(self, collider: Collider) -> None:
        """Leave the collision system (``collidable = False``, destroy).

        Ends the collider's contacts first: fires ``@collide_exit`` for each
        pair it was touching and drops those keys, so the survivor is told
        and a later collider reusing this ``id()`` cannot inherit them.
        """
        try:
            self._end_contacts_of(collider)  # author exit handlers may raise
        finally:
            self._swap_remove_collider(collider)
            self._forget_collider_tags(collider)
            self._forget_partner_entry(collider)
            self._invalidate_partner_cache_for_enroll()
            if self._rule_flux or self._flux_now:
                # Its exits ran above; hold no dead body (a registry keeps
                # a dead owner).
                self._rule_flux.pop(id(collider), None)
                self._flux_now.pop(id(collider), None)

    def _invalidate_partner_cache(self) -> None:
        """Drop cached resolve partner identities (enroll / pair graph changed)."""
        if self._partner_ident_cache:
            self._partner_ident_cache.clear()
        if self._partner_only_cache:
            self._partner_only_cache.clear()
        if self._shared_pools:
            self._shared_pools.clear()
        if self._partner_sig_cache:
            self._partner_sig_cache.clear()

    def _verify_pose_rev(self, collider: Collider, shapes) -> None:
        """``SCENA_VERIFY_POSE_REV``: the skipped key must equal the stored one."""
        keys = tuple(_collision_pose_key(s) for s in shapes)
        if keys != collider._proxy_key:
            raise AssertionError(
                f"pose revision unchanged but the pose key moved (a writer did not "
                f"bump_pose_rev): {[type(s).__name__ for s in shapes]} "
                f"{collider._proxy_key} -> {keys}"
            )

    def _forget_partner_entry(self, collider: Collider) -> None:
        """A leaving collider's own lists: a later collider reusing its id()
        must not inherit them."""
        cid = id(collider)
        self._partner_ident_cache.pop(cid, None)
        self._partner_only_cache.pop(cid, None)
        self._partner_rows_cache.pop(cid, None)
        self._partner_sig_cache.pop(cid, None)

    def _partner_cache_touched_by_tag(self, tag) -> bool:
        """Can a member joining / leaving ``tag`` change some partner list?

        Only when ``tag`` is a tag side of a resolve() pair. Identity sides
        (ANYTHING, objects, parts, snapshot groups) do not read tags: their
        lists change on enroll / leave (``_invalidate_partner_cache_for_enroll``).
        """
        if not _PARTNER_CACHE_SELECTIVE:
            return True
        pair_tag_of = self._pair_tag_of
        for a, b, _tok, _only in self._resolve_pairs:
            if pair_tag_of(a) == tag or pair_tag_of(b) == tag:
                return True
            # A formula group (``group["x"] @= …``) reads other groups' tags:
            # a retag can move a body in or out of it with no enroll.
            if (getattr(a, "_formula_name", None) is not None
                    or getattr(b, "_formula_name", None) is not None):
                return True
        return False

    def _invalidate_partner_cache_for_enroll(self) -> None:
        """An enroll / leave: drop every list only if a side expands by identity.

        The collider's tags reach the cache through ``_tag_add`` /
        ``_tag_remove``; this covers the sides that do not read tags.
        """
        if not (self._partner_ident_cache or self._partner_only_cache or self._shared_pools):
            return
        if _PARTNER_CACHE_SELECTIVE:
            pair_tag_of = self._pair_tag_of
            for a, b, _tok, _only in self._resolve_pairs:
                if pair_tag_of(a) is None or pair_tag_of(b) is None:
                    break
            else:
                return
        self._invalidate_partner_cache()

    def _invalidate_partner_cache_for_tag(self, tag) -> None:
        if (self._partner_ident_cache or self._partner_only_cache or self._shared_pools) and \
                self._partner_cache_touched_by_tag(tag):
            self._invalidate_partner_cache()

    def _forget_step_sets(self, c: Collider) -> None:
        """A leaving collider out of every per-step set: none may hold a body
        the world let go (the holders guard, ``test_sys_holders``)."""
        self._stale.discard(c)
        self._untrusted.discard(c)
        self._row_dirty.discard(c)
        self._snap_hot.discard(c)
        self._timed.discard(c)
        self._unbound.discard(c)
        if self._group_rows_cache:
            self._group_rows_cache.clear()  # its candidate lists may hold c
        self._touching_live.pop(id(c), None)

    def _swap_remove_collider(self, collider: Collider) -> None:
        idx_map = self._collider_index
        cid = id(collider)
        self._multi_bodies.pop(cid, None)
        self._forget_step_sets(collider)
        i = idx_map.pop(cid, None)
        if i is None:
            return
        self._struct_version += 1
        self._dispatch_epoch += 1
        self._phase_cache = None          # holds the dropped entries' sides
        if self._resolve_cache:
            self._resolve_cache.clear()     # an expansion may hold this collider
        lst = self._colliders
        last = lst.pop()
        if i != len(lst):
            lst[i] = last
            idx_map[id(last)] = i

    def _prune_dead(self) -> None:
        lst = self._colliders
        idx_map = self._collider_index
        i = 0
        while i < len(lst):
            c = lst[i]
            if c.shapes:
                i += 1
                continue
            self._forget_collider_tags(c)
            self._forget_partner_entry(c)
            self._invalidate_partner_cache_for_enroll()
            if c._identity is c:
                # A compound ``Collider([a, b])`` is its own identity, still
                # held by the author and its handlers: its survivors get their
                # exits and its pair handlers leave (review 2026-10-09 S8-9).
                self._end_contacts_of(c, emit=True)
                self.drop_pair_handlers_for(c)
                self._forget_pair_target(c)
            else:
                # A body's pieces died with it: no identity to report an exit
                # with; just drop the keys so a reused id() cannot inherit them.
                self._end_contacts_of(c, emit=False)
            self._dispatch_epoch += 1
            self._phase_cache = None          # holds the dropped entries' sides
            self._struct_version += 1
            self._forget_step_sets(c)
            last = lst.pop()
            idx_map.pop(id(c), None)
            if i != len(lst):
                lst[i] = last
                idx_map[id(last)] = i

    @staticmethod
    def _pair_tag_of(target) -> Optional[str]:
        """String group tag, or a live GroupOperator's group id."""
        if isinstance(target, str):
            return target
        gid = getattr(target, "_group_id", None)
        if gid is not None and getattr(target, "is_live", False):
            return gid
        return None

    def _note_pair_tag(self, target) -> None:
        tag = self._pair_tag_of(target)
        if tag is None:
            return
        self._pair_tags.add(tag)
        self._tag_colliders.setdefault(tag, [])
        self._tag_index.setdefault(tag, {})
        self._tag_version += 1

    def _tag_add(self, tag: str, collider: Collider) -> None:
        lst = self._tag_colliders.get(tag)
        if lst is None:
            lst = []
            self._tag_colliders[tag] = lst
            self._tag_index[tag] = {}
        idx_map = self._tag_index[tag]
        cid = id(collider)
        if cid in idx_map:
            return
        idx_map[cid] = len(lst)
        lst.append(collider)
        self._tag_version += 1
        self._invalidate_partner_cache_for_tag(tag)

    def _tag_remove(self, tag: str, collider: Collider) -> None:
        idx_map = self._tag_index.get(tag)
        if not idx_map:
            return
        cid = id(collider)
        i = idx_map.pop(cid, None)
        if i is None:
            return
        lst = self._tag_colliders[tag]
        last = lst.pop()
        if i != len(lst):
            lst[i] = last
            idx_map[id(last)] = i
        self._tag_version += 1
        self._invalidate_partner_cache_for_tag(tag)

    def _forget_collider_tags(self, collider: Collider) -> None:
        for tag in list(self._tag_index):
            self._tag_remove(tag, collider)
        for tag in list(self._claimed_body_index):
            self._claimed_body_remove(tag, collider)

    def _claimed_body_add(self, tag: str, collider: Collider) -> None:
        lst = self._claimed_bodies.get(tag)
        if lst is None:
            lst = []
            self._claimed_bodies[tag] = lst
            self._claimed_body_index[tag] = {}
        idx_map = self._claimed_body_index[tag]
        cid = id(collider)
        if cid in idx_map:
            return
        idx_map[cid] = len(lst)
        lst.append(collider)
        self._tag_version += 1
        self._invalidate_partner_cache_for_tag(tag)

    def _claimed_body_remove(self, tag: str, collider: Collider) -> None:
        idx_map = self._claimed_body_index.get(tag)
        if not idx_map:
            return
        i = idx_map.pop(id(collider), None)
        if i is None:
            return
        lst = self._claimed_bodies[tag]
        last = lst.pop()
        if i != len(lst):
            lst[i] = last
            idx_map[id(last)] = i
        if not lst:
            del self._claimed_bodies[tag]
            del self._claimed_body_index[tag]
        self._tag_version += 1
        self._invalidate_partner_cache_for_tag(tag)

    def _enroll_claimed_body(self, host, tag: str) -> None:
        """A part answers for resolve-side ``tag``: its host's body resolves."""
        if not self._item_in_play(host) or _collision_layer_error(host) is not None:
            return                      # no body on ui / parallax (S9-1)
        c = ensure_collider(host)
        self._claimed_body_add(tag, c)
        for a, b, _tok, _only in self._resolve_pairs:
            if self._pair_tag_of(a) == tag:
                c._add_pair_target(b)
            if self._pair_tag_of(b) == tag:
                c._add_pair_target(a)
        _sync_resolve_driver_for_collider(self, c, tag)

    def _resolve_side_colliders(self, target) -> Sequence[Collider]:
        """Bodies on a ``resolve()`` side (a claiming part → its host's body)."""
        tag = self._pair_tag_of(target)
        if tag is not None:
            lst = self._tag_colliders.get(tag) or ()
            extra = self._claimed_bodies.get(tag)
            if not extra:
                return lst  # hot path: no part claims this tag
            return [c for c in lst if c._part is None] + extra
        return self._resolve_target_to_colliders(target)

    def _resolve_now_colliders(self, target) -> List[Collider]:
        """``resolve_now`` partners: resolve-side bodies, plus the hosts of any
        part that answers for this tag (the tag need not be a resolve side)."""
        out: List[Collider] = []
        seen: Set[int] = set()
        for c in self._resolve_side_colliders(target):
            if c._part is None and id(c) not in seen:
                seen.add(id(c))
                out.append(c)
        tag = self._pair_tag_of(target)
        if tag is not None:
            for c in self._tag_colliders.get(tag) or ():
                if c._part is None:
                    continue
                host = c._identity
                if host is None or not self._item_in_play(host):
                    continue
                body = ensure_collider(host)
                if id(body) not in seen:
                    seen.add(id(body))
                    out.append(body)
        return out

    def _collider_on_resolve_side(self, collider: Collider, target) -> bool:
        """``_collider_on_side`` for ``resolve()``: bodies only, claims included."""
        if collider._part is not None:
            return False
        tag = self._pair_tag_of(target)
        if tag is not None:
            cid = id(collider)
            idx = self._tag_index.get(tag)
            if idx is not None and cid in idx:
                return True
            idx = self._claimed_body_index.get(tag)
            return idx is not None and cid in idx
        return self._collider_on_side(collider, target)

    def _resolve_pair_matches(self, ta, tb, ca: Collider, cb: Collider):
        if self._collider_on_resolve_side(ca, ta) and self._collider_on_resolve_side(cb, tb):
            return ca, cb
        if self._collider_on_resolve_side(cb, ta) and self._collider_on_resolve_side(ca, tb):
            return cb, ca
        return None

    def _apply_handler_targets(self, collider: Collider, tag: str) -> None:
        for a, b, _cb, _phase in self._pair_handlers:
            a_tag = self._pair_tag_of(a)
            b_tag = self._pair_tag_of(b)
            if a_tag == tag:
                collider._add_pair_target(b)
            if b_tag == tag:
                collider._add_pair_target(a)
        for a, b, _tok, _only in self._resolve_pairs:
            a_tag = self._pair_tag_of(a)
            b_tag = self._pair_tag_of(b)
            if a_tag == tag:
                collider._add_pair_target(b)
            if b_tag == tag:
                collider._add_pair_target(a)

    def _try_enroll_item(self, item, *, tag: str) -> Optional[Collider]:
        """Ensure collider + tag index for one in-play group member (once).

        A hitbox part that claims ``tag`` enrolls in place of its host.
        """
        routed = _tag_item(item, tag)
        if routed is not item and _tag_is_resolve_side(self, tag):
            self._enroll_claimed_body(item, tag)
        item = routed
        if item is None or not self._item_in_play(item):
            return None
        if _collision_layer_error(item) is not None:
            return None                 # a group member on ui / parallax: no body (S9-1)
        existing = getattr(item, "_collider", None)
        idx_map = self._tag_index.get(tag)
        already = (
            existing is not None
            and idx_map is not None
            and id(existing) in idx_map
        )
        if not already:
            self._debug_enroll_count += 1
        c = ensure_collider(item)
        if not already:
            bake = getattr(item, "_ensure_auto_baked", None)
            if callable(bake):
                bake()
            if existing is not None:
                self._note_flux(existing, tag, False)   # a tag joined mid-contact (CD3)
            self._tag_add(tag, c)
        self._apply_handler_targets(c, tag)
        if _tag_is_resolve_side(self, tag):
            _sync_resolve_driver_for_collider(
                self, c, tag if isinstance(tag, str) else None,
            )
        return c

    def _enroll_target_now(self, target) -> List[Collider]:
        """Decorate-time / recovery: scan a live group once and enroll members."""
        tag = self._pair_tag_of(target)
        if tag is None:
            return list(self._resolve_target_to_colliders(target))
        try:
            from .canvas import ScenaCanvas
            shapes = list(ScenaCanvas.get_current().registry.list_by_groupid(tag))
        except Exception:
            shapes = []
        result: List[Collider] = []
        for shape in shapes:
            c = self._try_enroll_item(shape, tag=tag)
            if c is not None:
                result.append(c)
        return result

    def _handler_colliders(self, target) -> Sequence[Collider]:
        tag = self._pair_tag_of(target)
        if tag is not None:
            return self._tag_colliders.get(tag) or ()
        return self._resolve_target_to_colliders(target)

    @staticmethod
    def _item_in_play(item) -> bool:
        """True when the item can participate in collision this frame.

        ``collidable = False`` sets ``_collision_opt_out`` so
        ``@collide`` group refresh does not re-enroll the item next step.
        """
        if not getattr(item, "is_alive", True):
            return False
        # The stored flag, not the public ``active``: on a hitbox part with a
        # linked ``active`` the getter runs the link, once per contact (HP5).
        # ``_refresh_linked_parts`` already applied it at the start of the step.
        if getattr(item, "_active", True) is False:
            return False
        if getattr(item, "_collision_opt_out", False):
            return False
        return True

    def _warn_dead_object_target(self, target) -> None:
        tid = id(target)
        if tid in self._dead_target_warned:
            return
        self._dead_target_warned.add(tid)
        warnings.warn(
            f"@collide object target {target!r} is destroyed (is_alive=False). "
            f"Object registrations keep the old Python instance — after "
            f"destroy/recreate they never see the new actor. Prefer group "
            f"tags: @collide(\"player\", \"star\").",
            stacklevel=3,
        )

    def _colliders_for_shapes(self, shapes: List[Any]) -> List[Collider]:
        # A snapshot group's members: one on ui / parallax is skipped (S9-1).
        live = [s for s in shapes if self._item_in_play(s)
                and _collision_layer_error(s) is None]
        if not live:
            return []
        return [ensure_collider(shape) for shape in live]

    def _resolve_target_to_colliders(self, target) -> List[Collider]:
        """Expand a pair-handler target to live Collider instances (step-cached)."""
        # Cache key: strings by value; objects by identity.
        if isinstance(target, str) or target is ANYTHING:
            cache_key = target
        else:
            cache_key = ("obj", id(target))
        cached = self._resolve_cache.get(cache_key)
        if cached is not None:
            return cached

        if target is ANYTHING:
            result = [c for c in self._colliders if c._part is None]
        elif isinstance(target, Collider):
            result = [target] if any(self._item_in_play(s) for s in target.shapes) else []
        elif isinstance(target, str):
            result = self._tag_colliders.get(target) or ()
        elif _is_part_side(target):
            result = self._part_target_colliders(target)
        else:
            from .registry import GroupOperator
            from .entity import Entity
            if isinstance(target, GroupOperator):
                tag = target._group_id
                if tag is not None:
                    result = self._tag_colliders.get(tag) or ()
                else:
                    result = self._colliders_for_shapes(list(target))
            elif isinstance(target, Entity):
                if not getattr(target, "is_alive", True):
                    self._warn_dead_object_target(target)
                    result = []
                elif not self._item_in_play(target):
                    result = []
                else:
                    _assert_shapes_not_parallax([target])
                    result = [ensure_collider(target)]
            else:
                result = []

        self._resolve_cache[cache_key] = result
        return result

    def add_pair_handler(self, a, b, callback: Callable, phase: str = _PHASE_ENTER) -> None:
        """Register a pair handler. One call opts both sides in (no mirror needed).

        Pre-validates both sides for parallax-layer members **before** appending
        the handler or creating colliders, so a ``ParallaxLayerError`` leaves
        ``_pair_handlers`` and enrollments unchanged for that failed decoration.
        """
        if _SOLVER_READING:
            refuse_if_solver_reading('@collide registration')
        # A side named directly refuses a ui / parallax actor; a group's
        # member there is skipped (S9-1).
        _assert_named_sides_not_parallax((a, b))
        entry = (a, b, callback, phase)
        self._pair_handlers.append(entry)
        self._note_pair_tag(a)
        self._note_pair_tag(b)
        # Decorate-time: enroll members already living in tagged groups.
        lefts = self._enroll_target_now(a)
        rights = self._enroll_target_now(b)
        for left in lefts:
            left._add_pair_target(b)
        for right in rights:
            right._add_pair_target(a)
        if self._prev_contacts:
            self._note_new_rule(entry)
        return entry

    def _drop_pair_entries(self, entries) -> None:
        """Undo ``add_pair_handler`` for ``entries`` (a refused decoration)."""
        if not entries:
            return
        ids = {id(e) for e in entries}
        self._pair_handlers[:] = [e for e in self._pair_handlers if id(e) not in ids]
        self._act_pair_handlers[:] = [
            e for e in self._act_pair_handlers if id(e) not in ids]
        self._dispatch_epoch += 1
        self._phase_cache = None          # holds the dropped entries' sides
        for c in list(self._colliders):
            self._prune_pair_targets(c)
        self._invalidate_partner_cache()
        self.retire_unused_pair_tags()

    def drop_act_pair_handlers(self) -> int:
        """Remove script-level ``@collide`` entries an act registered.

        Called on an act change. Top-level (game) entries stay. Pair targets
        the removed entries implied are pruned from the surviving colliders.
        """
        self._act_change_epoch += 1
        # A ghost contact (PE5) of the leaving act's bodies does not reach
        # the new act's step.
        self._ghost_contacts = []
        self._ghost_walls = {}
        doomed = self._act_pair_handlers
        if not doomed:
            return 0
        ids = {id(e) for e in doomed}
        self._pair_handlers[:] = [e for e in self._pair_handlers if id(e) not in ids]
        self._dispatch_epoch += 1
        self._phase_cache = None          # holds the dropped entries' sides
        n = len(doomed)
        self._act_pair_handlers = []
        for c in list(self._colliders):
            self._prune_pair_targets(c)
        self._invalidate_partner_cache()
        return n

    def add_resolve_pair(
        self, a, b, bounce: Optional[float] = None, only: Any = None,
    ) -> None:
        """Register a standing auto-resolve relationship.

        ``only`` is in ``a``'s view. Re-registering an equal pair replaces its
        bounce token and its ``only`` (last call wins), in the new call's order.
        """
        if _SOLVER_READING:
            refuse_if_solver_reading('resolve()')
        _refuse_part_resolve_side(self, a)
        _refuse_part_resolve_side(self, b)
        items: List[Any] = []
        items.extend(_collect_entities_from_target(a))
        items.extend(_collect_entities_from_target(b))
        _assert_named_sides_not_parallax((a, b))
        items = [i for i in items if _collision_layer_error(i) is None]
        if bounce is not None:
            bounce = _validate_bounce(bounce)
        token: Any = _RESOLVE_POSITION_ONLY if bounce is None else bounce
        only = _normalize_only(only)
        for i, (pa, pb, _tok, _only) in enumerate(self._resolve_pairs):
            if _resolve_pair_equal(pa, pb, a, b):
                # The new call's order: ``only`` sides are read from ``a``.
                self._resolve_pairs[i] = (a, b, token, only)
                self._invalidate_partner_cache()
                self._refresh_has_only()
                return
        # Eager writability before committing the pair (no silent default).
        for shape in items:
            ensure = getattr(shape, "_ensure_resolve_parts_writable", None)
            if callable(ensure):
                ensure()
        self._resolve_pairs.append((a, b, token, only))
        self._invalidate_partner_cache()
        self._refresh_has_only()
        self._note_pair_tag(a)
        self._note_pair_tag(b)
        self._enroll_target_now(a)
        self._enroll_target_now(b)
        # Bodies, not the parts that may answer these tags for @collide.
        for left in self._resolve_side_colliders(a):
            left._add_pair_target(b)
            _sync_resolve_driver_for_collider(self, left)
        for right in self._resolve_side_colliders(b):
            right._add_pair_target(a)
            _sync_resolve_driver_for_collider(self, right)
        _note_resolve_enroll_shapes(items)

    def _refresh_has_only(self) -> None:
        self._has_only = any(p[3] is not None for p in self._resolve_pairs)
        if not self._has_only and self._passing:
            self._passing.clear()

    def _begin_passing(self, ca: Collider, cb: Collider) -> None:
        """``ca`` and ``cb`` pass through each other until they separate."""
        self._passing.setdefault(id(ca), {})[id(cb)] = cb
        self._passing.setdefault(id(cb), {})[id(ca)] = ca

    def _end_passing(self, ca: Collider, pid: int) -> None:
        mine = self._passing.get(id(ca))
        if mine is not None:
            mine.pop(pid, None)
        theirs = self._passing.get(pid)
        if theirs is not None:
            theirs.pop(id(ca), None)

    def remove_resolve_pair(self, a, b) -> None:
        """Cancel a standing ``resolve(a, b)`` registration."""
        if _SOLVER_READING:
            refuse_if_solver_reading('unresolve()')
        i = 0
        removed = False
        while i < len(self._resolve_pairs):
            pa, pb, _tok, _only = self._resolve_pairs[i]
            if _resolve_pair_equal(pa, pb, a, b):
                last = self._resolve_pairs.pop()
                if i != len(self._resolve_pairs):
                    self._resolve_pairs[i] = last
                removed = True
                continue
            i += 1
        if removed:
            self._refresh_has_only()
            # Claimed bodies only resolve while their tag is a resolve side.
            for tag in list(self._claimed_bodies):
                if not _tag_is_resolve_side(self, tag):
                    for c in list(self._claimed_bodies.get(tag, ())):
                        self._claimed_body_remove(tag, c)
                        _sync_resolve_driver_for_collider(self, c)
            # Sync after pair is gone so _collider_in_resolve is False.
            for shape in _collect_entities_from_target(a):
                c = getattr(shape, "_collider", None)
                if c is not None:
                    _sync_resolve_driver_for_collider(self, c)
                elif getattr(shape, "_resolve_enrolled", False):
                    _note_resolve_unenroll_shapes([shape])
            for shape in _collect_entities_from_target(b):
                c = getattr(shape, "_collider", None)
                if c is not None:
                    _sync_resolve_driver_for_collider(self, c)
                elif getattr(shape, "_resolve_enrolled", False):
                    _note_resolve_unenroll_shapes([shape])
            # The other side no pair implies any more leaves the targets
            # (``ANYTHING`` included: S8-4).
            for side in (a, b):
                if side is ANYTHING:
                    continue
                for c in list(self._resolve_side_colliders(side)):
                    if c._pair_targets:
                        self._prune_pair_targets(c)
            self._invalidate_partner_cache()
            self.retire_unused_pair_tags()
        else:
            warnings.warn(
                f"unresolve({a!r}, {b!r}) matched no standing resolve() pair",
                RuntimeWarning,
                stacklevel=3,
            )

    def _collider_on_side(self, collider: Collider, target) -> bool:
        """True when ``collider`` is a member of a resolve / @collide side."""
        if collider._part is not None:
            # Parts answer for their groups and for their own Hitbox only.
            if target is ANYTHING or target is collider._identity:
                return False
            if target is collider or target is collider._part:
                return True
        elif target is ANYTHING:
            return True
        elif target is collider or target is collider._identity:
            return True
        tag = self._pair_tag_of(target)
        if tag is not None:
            idx = self._tag_index.get(tag)
            return idx is not None and id(collider) in idx
        if isinstance(target, Collider):
            return target is collider
        for c in self._resolve_target_to_colliders(target):
            if c is collider:
                return True
        return False

    def _same_resolve_side(self, ta, tb) -> bool:
        if ta is tb:
            return True
        tag_a = self._pair_tag_of(ta)
        tag_b = self._pair_tag_of(tb)
        return tag_a is not None and tag_a == tag_b

    def _resolve_bounce_for(self, ca: Collider, cb: Collider) -> Optional[Any]:
        """Return bounce token for this collider pair, or None if not registered."""
        for ta, tb, token, _only in self._resolve_pairs:
            if self._resolve_pair_matches(ta, tb, ca, cb):
                return token
        return None

    def _collider_in_resolve(self, collider: Collider) -> bool:
        if collider._part is not None:
            return False
        for ta, tb, _tok, _only in self._resolve_pairs:
            if (
                self._collider_on_resolve_side(collider, ta)
                or self._collider_on_resolve_side(collider, tb)
            ):
                return True
        return False

    @staticmethod
    def _side_is_identity(side, identity) -> bool:
        """True when a pair-handler side is this destroyed actor (not a tag)."""
        if side is identity:
            return True
        if isinstance(side, Collider):
            return side._identity is identity
        if _is_part_side(side):
            return side._host_ref() is identity
        return False

    def seal_resolve_pairs(self) -> None:
        """Remember the ``resolve`` pairs of the game (the act manager's seal)."""
        self._sealed_resolve_pairs = list(self._resolve_pairs)

    def restore_sealed_resolve_pairs(self) -> None:
        """An act change: the game's ``resolve`` pairs come back, the act's go."""
        _restore_resolve_pairs(self._sealed_resolve_pairs or [])

    def _prune_dead_side(self, identity, entries: list, *, swap: bool) -> bool:
        """Drop every entry of ``entries`` (tuples whose first two items are
        pair sides) with ``identity`` as a side, and ``identity`` out of every
        group-operator snapshot side (``group["a"] | group["b"]`` copies its
        members at the call: HD1). Returns True when an entry went."""
        dropped = False
        i = 0
        while i < len(entries):
            a, b = entries[i][0], entries[i][1]
            if self._side_is_identity(a, identity) or self._side_is_identity(b, identity):
                if swap:
                    last = entries.pop()
                    if i != len(entries):
                        entries[i] = last
                else:
                    del entries[i]
                dropped = True
                continue
            for side in (a, b):
                snap = getattr(side, "_snapshot", None)
                if snap and any(m is identity for m in snap):
                    snap[:] = [m for m in snap if m is not identity]
            i += 1
        return dropped

    def drop_pair_handlers_for(self, identity) -> None:
        """Remove ``identity`` from every pair list: a handler or ``resolve``
        side (swap-removed), the act-level handler list, the sealed game
        pairs, and every group-operator snapshot side.

        Tag × tag handlers are untouched. Object-literal ``@collide(player, …)``
        after ``player.destroy()`` must not linger (leak + dead-target warnings).
        """
        self._prune_dead_side(identity, self._act_pair_handlers, swap=False)
        if self._sealed_resolve_pairs:
            self._prune_dead_side(identity, self._sealed_resolve_pairs, swap=False)
        lst = self._pair_handlers
        dropped = self._prune_dead_side(identity, lst, swap=True)
        if dropped:
            self._dispatch_epoch += 1
            self._phase_cache = None          # holds the dropped entries' sides
        resolve_changed = self._prune_dead_side(identity, self._resolve_pairs, swap=True)
        if dropped or resolve_changed:
            # The other side of each dropped pair holds ``identity`` in its
            # ``_pair_targets`` (``@collide_with("wall")`` on a bullet puts the
            # bullet on the wall). Left there, every bullet ever fired stays
            # reachable from the wall — a leak, and a broad phase that grows.
            self._forget_pair_target(identity)
        if resolve_changed:
            self._invalidate_partner_cache()
            self._refresh_has_only()
        if dropped or resolve_changed:
            # ``@collide(boss, "bullet")``: with the boss gone, "bullet" stops
            # enrolling (every door that drops a declaration, S8-7).
            self.retire_unused_pair_tags()
        self._dead_target_warned.discard(id(identity))
        col = getattr(identity, "_collider", None)
        if col is not None:
            self._dead_target_warned.discard(id(col))

    def _forget_pair_target(self, identity) -> None:
        """Remove ``identity`` (or its collider / parts) from every ``_pair_targets``."""
        side_is = self._side_is_identity
        for c in self._colliders:
            targets = c._pair_targets
            if any(side_is(t, identity) for t in targets):
                targets[:] = [t for t in targets if not side_is(t, identity)]

    def forget_destroyed_item(self, item) -> None:
        """Destroy-time: fire ``@collide_exit`` for the survivor, then drop handlers."""
        col = getattr(item, "_collider", None)
        parts = getattr(item, "_hitbox_parts", None) or ()
        first_error = None
        try:
            # Every exit fires, each with its own error: a raising body exit
            # skipped the part exits and left their keys behind (review
            # 2026-10-09 S8-10). The first error is raised after the cleanup.
            for c in ([col] if col is not None else []) + [
                    p._collider for p in parts if p._collider is not None]:
                try:
                    self._fire_exit_for_destroyed(c)   # author handlers may raise
                except BaseException as exc:            # noqa: BLE001
                    if first_error is None:
                        first_error = exc
        finally:
            if parts:
                from .hitbox import _LINKED_PARTS
                for part in parts:
                    _LINKED_PARTS.discard(part)
            for part in parts:
                pc = part._collider
                part._collider = None
                part._collidable = False
                if pc is not None:
                    # No key may outlive the collider (an id() a new collider
                    # could reuse before the next step).
                    self._end_contacts_of(pc, emit=False)
                    self._swap_remove_collider(pc)
                    self._forget_collider_tags(pc)
            self._drop_destroyed_collider(item, col)
        if first_error is not None:
            raise first_error

    def _drop_destroyed_collider(self, item, col) -> None:
        self.drop_pair_handlers_for(item)
        if col is not None:
            self.unregister(col)
            try:
                object.__setattr__(item, "_collider", None)
            except Exception:
                try:
                    item._collider = None
                except Exception:
                    pass

    def _fire_exit_for_destroyed(self, col: Collider) -> None:
        """Tell the surviving partner this contact ended because ``col`` is gone."""
        self._end_contacts_of(col)

    def _end_contacts_of(self, col: Collider, *, emit: bool = True) -> None:
        """Drop ``col``'s contact keys; with ``emit``, fire exit for each pair.

        Keys go before any handler runs (a raising exit handler cannot leave
        them behind to fire again).
        """
        cid = id(col)
        if emit and col._in_resolve and self._dispatch_current is not None:
            self._note_ghost_contacts(col)
        keys = [k for k in self._prev_contacts if cid in k]
        # This step's enters not dispatched yet: no enter ran, so no exit.
        if self._enter_pending:
            for k in [k for k in self._enter_pending if cid in k]:
                self._enter_pending.discard(k)
                if k in keys:
                    keys.remove(k)
                    self._prev_contacts.discard(k)
        # This step's exits not dispatched yet: they fire now, while the body
        # still exists, and not again from the step's exit loop.
        if self._exit_pending:
            for k in [k for k in self._exit_pending if cid in k]:
                self._exit_pending.discard(k)
                keys.append(k)
        if not keys:
            return
        for key in keys:
            self._prev_contacts.discard(key)
        try:
            if emit:
                self._emit_ended(col, keys)
        finally:
            if self._gain_pending or self._stay_skip or self._lost_pending:
                # Their rules' enter / exit ran above or is owed no more.
                for key in keys:
                    self._gain_pending.pop(key, None)
                    self._stay_skip.pop(key, None)
                    self._lost_pending.pop(key, None)

    def _emit_ended(self, col: Collider, keys) -> None:
        """The exits of ``col``'s contacts ``keys``, which it ends now."""
        cid = id(col)
        id_to = {id(c): c for c in self._colliders}
        id_to[cid] = col
        current = self._contact_key
        for key in keys:
            ca = id_to.get(key[0])
            cb = id_to.get(key[1])
            if ca is None or cb is None:
                continue
            info = CollisionInfo(
                a=ca._identity, b=cb._identity, normal=Vec2.temp(0, 0), depth=0.0,
            )
            if key == current and self._deferred_exit is None and not _act_manager().changing:
                # The contact whose handlers are running: its exit waits for
                # them. Its handlers are chosen now, while the leaving side
                # still has its tags and handlers (what an exit fired here
                # would have run). The leaving body's own exit hooks run now,
                # while it exists (a dead actor runs no hook of its own).
                runs = self._exit_runs(ca, cb)
                own = [r for r in runs if self._own_hook_of(col, r)]
                rest = [r for r in runs if not self._own_hook_of(col, r)]
                if own:
                    self._run_exit(ca, info, own, None)
                if rest:
                    was = [ta is None or self._handler_registered(ta, tb, fn)
                           for ta, tb, fn, _m, _o in rest]
                    self._deferred_exit = (ca, cb, info, rest, was, self._act_change_epoch)
                continue
            self._dispatch(ca, cb, info, _PHASE_EXIT)

    @staticmethod
    def _own_hook_of(col: Collider, run) -> bool:
        """An exit run that belongs to ``col``'s body: its ``on_collide_exit``
        or a handler with that body (or part) as a side (``@collide_with_exit``
        methods, ``@collide_exit(body, …)``)."""
        ta, tb, _fn, me, _other = run
        if ta is None:
            return me is col
        targets = (col, col._identity) if col._part is None else (col, col._part)
        return any(t is x for t in (ta, tb) for x in targets)

    def _note_ghost_contacts(self, col: Collider) -> None:
        """``col`` leaves collision from a handler of this step (destroy, park,
        ``collidable = False``): keep what each resolve partner it touched
        this frame needs for its velocity response (PE5).

        Handlers run before resolve, so a brick destroyed in ``@collide``
        was gone when the solver ran, and a ``bounce=`` ball ploughed through
        every brick it broke. The survivor still gets this contact's velocity
        response; a dead body pushes nothing. Read here, while ``col`` still
        has its tags and its pose: the registration, its detection prims, its
        frame motion, its mass and velocity.
        """
        current = self._dispatch_current
        ids = self._dispatch_ids
        cid = id(col)
        for key, info in current.items():
            if cid != key[0] and cid != key[1]:
                continue
            surv = ids.get(key[1] if key[0] == cid else key[0])
            if surv is None or not surv._in_resolve:
                continue
            reg = self._resolve_reg_for(surv, col)
            if reg is None:
                continue
            token, only_entry = reg
            if token is _RESOLVE_POSITION_ONLY or token is None:
                continue
            ident = col._identity
            try:
                mass = float(getattr(ident, "mass", STATIC))
            except Exception:                  # noqa: BLE001
                mass = STATIC
            vb = getattr(ident, "_vel", None)
            vel = None if vb is None else (float(vb.x), float(vb.y))
            moving = col._motion_translation
            self._ghost_contacts.append((
                surv, col, info, col._world_prims, token, only_entry, mass, vel,
                col._motion_dx if moving else 0.0, col._motion_dy if moving else 0.0,
            ))

    def _resolve_reg_for(self, ca: Collider, cb: Collider):
        """``(bounce token, only entry in ca's view)`` of the first standing
        registration pairing ``ca`` with ``cb`` (as ``_resolve_partners``
        reads it), or None."""
        for ta, tb, token, only in self._resolve_pairs:
            if self._collider_on_resolve_side(ca, ta) and self._collider_on_resolve_side(cb, tb):
                return token, None if only is None else (only, False)
            if self._collider_on_resolve_side(ca, tb) and self._collider_on_resolve_side(cb, ta):
                if only is None:
                    return token, None
                if isinstance(only, frozenset):
                    return token, (_mirror_only(only), False)
                return token, (only, True)
        return None

    def _answer_unreached(
        self,
        ca: Collider,
        skins: Optional[List[Tuple[Tuple[int, int], CollisionInfo]]],
        ghosts: Optional[List[Tuple[_GhostPartner, Any, float, float]]],
        grounded: bool,
        id_to_collider: Dict[int, Collider],
    ) -> None:
        """Answer the contacts the handlers saw that this body's sweep never
        reached (LW8): the body made no stop this step, and its velocity
        approaches a partner within the resting skin. Without this, a brick
        broken the frame after its ``@collide`` let the ball through (it was
        gone before the sweep that would have bounced the ball).

        Which: a live skin contact on a ``bounce > 0`` pair, for a body that
        was airborne at the start of the frame (a resting body is the floor
        snap's; a ``bounce=0`` pair is answered by the next sweep, and
        answering it here turned an idle body's fall into a slide down a ramp:
        P5), and a removed partner (``ghosts``) the sweep did not meet. The
        normal is a short cast along the velocity, the sweep's own question;
        the detection's gap normal at a seam is a corner-to-corner artefact.
        Answered together (``_cone_response``); a live contact is recorded,
        so ``touching_*`` agrees with what ``@collide`` saw.
        """
        ident = ca._identity
        vel = getattr(ident, "_vel", None)
        if vel is None:
            return
        vx, vy = float(vel.x), float(vel.y)
        vl = math.hypot(vx, vy)
        if vl < 1e-9:
            return
        pas = self._world_prims(ca)
        if not pas:
            return
        reach = 2.0 * _CONTACT_SKIN / vl
        ux, uy = vx * reach, vy * reach
        cid = id(ca)
        passing = self._passing.get(cid) or {}
        ns: List[Tuple[float, float]] = []
        es: List[float] = []
        recs: List[Tuple[Collider, float, float]] = []

        def cast(pbs):
            hit = _toi_prim_sets(pas, pbs, ux, uy)
            if hit is None or hit[1] is None:
                return None
            nx, ny = float(hit[1].normal[0]), float(hit[1].normal[1])
            nl = math.hypot(nx, ny)
            if nl < 1e-12 or vx * nx + vy * ny <= 0.0:
                return None
            return nx / nl, ny / nl

        if skins and not grounded:
            gate = None
            if self._has_only:
                only_map = self._resolve_only_map(ca)
                if only_map:
                    gate = _OnlyGate(self, ca, only_map, passing)
            for key, _info in skins:
                if key in self._solve_contacts:
                    continue
                other = id_to_collider.get(key[1] if key[0] == cid else key[0])
                if other is None or passing.get(id(other)) is other:
                    continue
                _mb, ov = _partner_mass_vel(other)
                if ov is not None and (ov[0] or ov[1]):
                    continue                # a moving partner: its sweep's business
                token = self._resolve_bounce_for(ca, other)
                if token is _RESOLVE_POSITION_ONLY or token is None or float(token) <= 0.0:
                    continue
                n = cast(self._world_prims(other))
                if n is None or (gate is not None and not gate.ok(other, n[0], n[1])):
                    continue
                ns.append(n)
                es.append(float(token))
                recs.append((other, n[0], n[1]))
        if ghosts:
            met = self._ghosts_met
            for g, token, _odx, _ody in ghosts:
                if id(g) in met or token is _RESOLVE_POSITION_ONLY or token is None:
                    continue
                if g.vel is not None and not _is_static_mass(g.mass):
                    continue                # a movable body: no wall to answer here
                n = cast(g.prims)
                if n is None:
                    continue
                if g.only_entry is not None and not _OnlyGate(
                        self, ca, {id(g.dead): g.only_entry}, passing).ok(g.dead, n[0], n[1]):
                    continue
                ns.append(n)
                es.append(float(token))
        if not ns:
            return
        vel.x, vel.y = _cone_response(vx, vy, ns, es)
        for (nx, ny), e in zip(ns, es):
            self._note_bounce(ca, vx, vy, 0.0, 0.0, nx, ny, e)
        for other, nx, ny in recs:
            self._record_solve_contact(ca, other, nx, ny, 0.0)

    def _apply_ghost_contacts(self) -> None:
        """Velocity response of each survivor to a resolve partner a handler
        removed this step (PE5): ``bounce=`` as if the partner were still
        there for this contact, written on the survivor only, no push.

        The contact the handlers saw answers, along the normal of the hit on
        the frame's relative path when the survivor reached the partner this
        frame (as the sweep would), else the detection normal (an end-pose
        overlap, or a resting-skin gap: touching, F1). ``velocity_split``
        changes only an approaching velocity, so a body moving away from or
        along the removed partner keeps its speed, and an ``only=`` pair
        answers only on a side it blocks.
        """
        ghosts = self._ghost_contacts
        self._ghost_contacts = []
        if _GHOST_WALLS:
            # Each removed partner becomes a still wall for its survivor's
            # sweep this step (``_sweep_and_slide``), once per survivor.
            by: Dict[int, List[Tuple[_GhostPartner, Any, float, float]]] = {}
            for surv, dead, info, pbs, token, only_entry, mb, vel_b, _ddx, _ddy in ghosts:
                ident = surv._identity
                if getattr(ident, "_vel", None) is None or not self._collider_in_play(surv):
                    continue
                if _is_static_mass(float(getattr(ident, "mass", 1.0))) or not pbs:
                    continue
                walls = by.setdefault(id(surv), [])
                if any(w[0].dead is dead for w in walls):
                    continue                # one contact each side: one wall
                walls.append((_GhostPartner(dead, pbs, mb, vel_b, info, only_entry),
                              token, 0.0, 0.0))
            self._ghost_walls = by
            return
        for surv, dead, info, pbs, token, only_entry, mb, vel_b, ddx, ddy in ghosts:
            ident = surv._identity
            va = getattr(ident, "_vel", None)
            if va is None or not self._collider_in_play(surv):
                continue
            ma = float(getattr(ident, "mass", 1.0))
            if _is_static_mass(ma):
                continue
            nx = ny = None
            pas = self._world_prims(surv)
            if pas and pbs:
                sdx = surv._motion_dx if surv._motion_translation else 0.0
                sdy = surv._motion_dy if surv._motion_translation else 0.0
                rdx, rdy = sdx - ddx, sdy - ddy
                if rdx or rdy:
                    hit = _toi_prim_sets(_copy_translate(pas, -rdx, -rdy), pbs, rdx, rdy)
                    if hit is not None and hit[1] is not None and hit[0] > 1e-12:
                        nx, ny = float(hit[1].normal[0]), float(hit[1].normal[1])
            if nx is None:
                inx, iny = _normal_components(info.normal)
                if info.a is ident:
                    nx, ny = inx, iny
                else:
                    nx, ny = -inx, -iny
            if only_entry is not None:
                gate = _OnlyGate(self, surv, {id(dead): only_entry},
                                 self._passing.get(id(surv)) or {})
                if not gate.ok(dead, nx, ny):
                    continue
            contact = CollisionInfo(a=ident, b=dead._identity,
                                    normal=Vec2.temp(nx, ny), depth=0.0)
            nva, _nvb = contact.velocity_split(
                mass_a=ma, mass_b=STATIC if vel_b is None else mb,
                bounce=float(token), vel_a=va,
                vel_b=(0.0, 0.0) if vel_b is None else vel_b,
            )
            va.x, va.y = float(nva.x), float(nva.y)

    def _prune_pair_targets(self, collider: "Collider") -> None:
        """Drop targets no registered pair implies for ``collider`` any more
        (after it left a tag). ``ANYTHING`` has its own sync; left alone."""
        if not collider._pair_targets:
            return
        implied = set()
        for a, b, *_rest in self._pair_handlers:
            if collider in self._handler_colliders(a):
                implied.add(id(b) if not isinstance(b, str) else b)
            if collider in self._handler_colliders(b):
                implied.add(id(a) if not isinstance(a, str) else a)
        for a, b, _tok, _only in self._resolve_pairs:
            if collider in self._resolve_side_colliders(a):
                implied.add(id(b) if not isinstance(b, str) else b)
            if collider in self._resolve_side_colliders(b):
                implied.add(id(a) if not isinstance(a, str) else a)
        anything = False
        for t in list(collider._pair_targets):
            if t is ANYTHING:
                anything = True
                continue
            key = t if isinstance(t, str) else id(t)
            if key not in implied:
                collider._remove_pair_target(t)
        if anything:
            # Callbacks and pairs both imply ANYTHING: its own sync decides
            # (review 2026-10-09 S8-4: it was never removed).
            collider._sync_anything_interest()

    def _pair_tags_in_use(self) -> Set[str]:
        out: Set[str] = set()
        for a, b, *_rest in self._pair_handlers:
            for side in (a, b):
                tag = self._pair_tag_of(side)
                if tag is not None:
                    out.add(tag)
        for a, b, _tok, _only in self._resolve_pairs:
            for side in (a, b):
                tag = self._pair_tag_of(side)
                if tag is not None:
                    out.add(tag)
        return out

    def _collider_still_declared(self, c: "Collider") -> bool:
        """A body some declaration still names: its own switch or callbacks,
        a live pair tag, an instance side, or a registered hitbox part."""
        item = c._identity
        if getattr(item, "_collision_opt_in", False):
            return True
        if (c.on_collide is not None or c.on_collide_stay is not None
                or c.on_collide_exit is not None
                or getattr(item, "_collide_cbs", None)):
            return True
        cid = id(c)
        for idx in self._tag_index.values():
            if cid in idx:
                return True
        for idx in self._claimed_body_index.values():
            if cid in idx:
                return True
        for parts in (getattr(item, "_hitbox_parts", None) or ()):
            if getattr(parts, "_collider", None) is not None:
                return True
        for entries in (self._pair_handlers, self._resolve_pairs):
            for a, b, *_rest in entries:
                for side in (a, b):
                    if side is ANYTHING or self._pair_tag_of(side) is not None:
                        continue
                    if c in self._handler_colliders(side):
                        return True
        return False

    def retire_unused_pair_tags(self) -> None:
        """An act change: a tag no surviving ``@collide`` / ``resolve`` names
        stops enrolling members, and a body enrolled only through it leaves
        collision (review 2026-10-09 S8-7). Without this, every later member
        of an act-only tag got a collider and answered unnamed queries."""
        gone = self._pair_tags - self._pair_tags_in_use()
        if not gone:
            return
        left: List[Collider] = []
        for tag in gone:
            self._pair_tags.discard(tag)
            left.extend(self._tag_colliders.pop(tag, ()) or ())
            self._tag_index.pop(tag, None)
            left.extend(self._claimed_bodies.pop(tag, ()) or ())
            self._claimed_body_index.pop(tag, None)
        self._invalidate_partner_cache()
        seen: Set[int] = set()
        for c in left:
            if id(c) in seen or c._part is not None:
                continue
            seen.add(id(c))
            if c not in self._colliders:
                continue
            self._prune_pair_targets(c)
            if self._collider_still_declared(c):
                continue
            item = c._identity
            leave = getattr(item, "_leave_collision", None)
            if callable(leave) and getattr(item, "_collider", None) is c:
                leave()

    def _refresh_pair_enrollments(self) -> None:
        """Full rebuild of tag indexes (audit / desync recovery). Not the hot path."""
        self._tag_colliders.clear()
        self._tag_index.clear()
        self._claimed_bodies.clear()
        self._claimed_body_index.clear()
        self._invalidate_partner_cache()
        for a, b, _cb, _phase in self._pair_handlers:
            self._note_pair_tag(a)
            self._note_pair_tag(b)
            self._enroll_target_now(a)
            self._enroll_target_now(b)
            for left in self._handler_colliders(a):
                left._add_pair_target(b)
            for right in self._handler_colliders(b):
                right._add_pair_target(a)
        for a, b, _tok, _only in self._resolve_pairs:
            self._note_pair_tag(a)
            self._note_pair_tag(b)
            self._enroll_target_now(a)
            self._enroll_target_now(b)
            for left in self._resolve_side_colliders(a):
                left._add_pair_target(b)
            for right in self._resolve_side_colliders(b):
                right._add_pair_target(a)

    # -- interest -----------------------------------------------------------

    def _collider_has_handler_anything(self, collider: Collider) -> bool:
        """True when a registered ``@collide`` / ``resolve`` pair names ``ANYTHING`` for ``collider``."""
        for a, b, _cb, _phase in self._pair_handlers:
            if b is ANYTHING:
                for c in self._handler_colliders(a):
                    if c is collider:
                        return True
            if a is ANYTHING:
                for c in self._handler_colliders(b):
                    if c is collider:
                        return True
        for a, b, _tok, _only in self._resolve_pairs:
            if b is ANYTHING:
                for c in self._resolve_side_colliders(a):
                    if c is collider:
                        return True
            if a is ANYTHING:
                for c in self._resolve_side_colliders(b):
                    if c is collider:
                        return True
        return False

    def _interested(self, ca: Collider, cb: Collider) -> bool:
        """Either side declaring interest is enough (one registration)."""
        return ca._wants(cb) or cb._wants(ca)

    def _pose_keys(self, collider: Collider) -> tuple:
        return tuple(_collision_pose_key(s) for s in collider.shapes)

    def _commit_pending_motion(self, collider: Collider) -> None:
        """Consume motion-channel deltas; placement (no pending) is not swept."""
        dx = collider._pending_motion_dx
        dy = collider._pending_motion_dy
        collider._pending_motion_dx = 0.0
        collider._pending_motion_dy = 0.0
        if dx != collider._motion_dx or dy != collider._motion_dy:
            self._row_dirty.add(collider)          # the mirror's motion columns
        collider._motion_dx = dx
        collider._motion_dy = dy
        collider._motion_translation = True
        path = collider._pending_path
        if path is not None:
            collider._pending_path = None
        collider._motion_path = path
        if path is None:
            if dx == 0.0 and dy == 0.0:
                collider._proxy_start = None
            elif collider._proxy_valid:
                p = collider._proxy
                collider._proxy_start = [p[0] - dx, p[1] - dy, p[2] - dx, p[3] - dy]
                # Swept-detection gate, on moving colliders only (still ones never
                # reach this branch): travel > fraction x thickness. One multiply
                # and one compare; ``inf * 0`` is NaN, which compares False.
                if dx * dx + dy * dy > self._fast_k2 * collider._thick2:
                    self._fast_colliders.append(collider)
            else:
                collider._proxy_start = None
        elif collider._proxy_valid:
            # A curved path (a fast orbit, W-T5): the swept box covers every
            # waypoint, and the gate reads the path's length, not its chord
            # (a full turn ends where it began).
            p = collider._proxy
            box = [p[0] - dx, p[1] - dy, p[2] - dx, p[3] - dy]
            length = 0.0
            px = py = 0.0
            for wx, wy in path + [(dx, dy)]:
                ox, oy = wx - dx, wy - dy
                if p[0] + ox < box[0]:
                    box[0] = p[0] + ox
                if p[1] + oy < box[1]:
                    box[1] = p[1] + oy
                if p[2] + ox > box[2]:
                    box[2] = p[2] + ox
                if p[3] + oy > box[3]:
                    box[3] = p[3] + oy
                length += math.hypot(wx - px, wy - py)
                px, py = wx, wy
            collider._proxy_start = box
            if length * length > self._fast_k2 * collider._thick2:
                self._fast_colliders.append(collider)
        else:
            collider._proxy_start = None
            collider._motion_path = None
        if dx != 0.0 or dy != 0.0 or path is not None:
            self._snap_hot.add(collider)        # next step resets this motion

    def _update_proxy(self, collider: Collider, *, commit_motion: bool = True) -> bool:
        """Refresh collider proxy AABB. Translation-only mutates four floats.

        ``commit_motion=False`` (queries) leaves the motion channel untouched so
        a ``collides_with`` / ``raycast`` during ``update()`` does not erase the
        sweep ``step()`` still has to consume.
        """
        shapes = collider.shapes
        if not shapes:
            collider._proxy_valid = False
            self._untrusted.add(collider)
            self._row_dirty.add(collider)
            if commit_motion:
                collider._motion_dx = 0.0
                collider._motion_dy = 0.0
                collider._motion_translation = True
                collider._pending_motion_dx = 0.0
                collider._pending_motion_dy = 0.0
                collider._proxy_start = None
                collider._pending_path = None
                collider._motion_path = None
            return False
        timed = False
        for s in shapes:
            if _sync_auto_hitbox_frame(s):
                timed = True
        if timed:
            self._timed.add(collider)
        elif self._timed:
            self._timed.discard(collider)
        if _POSE_REV_SKIP and collider._proxy_valid:
            stored = collider._proxy_revs
            if stored is not None and stored == _collider_pose_revs(shapes):
                if _POSE_REV_VERIFY:
                    self._verify_pose_rev(collider, shapes)
                if commit_motion:
                    self._commit_pending_motion(collider)
                return True
        keys = tuple(_collision_pose_key(s) for s in shapes)
        old = collider._proxy_key
        revs = _collider_pose_revs(shapes) if _POSE_REV_SKIP else None
        collider._proxy_revs = revs
        if revs is None:
            self._untrusted.add(collider)
        elif self._untrusted:
            self._untrusted.discard(collider)
        if old == keys and collider._proxy_valid:
            if commit_motion:
                self._commit_pending_motion(collider)
            return True
        delta = _keys_uniform_translation(old, keys) if collider._proxy_valid else None
        self._row_dirty.add(collider)
        if delta is not None:
            dx, dy = delta
            p = collider._proxy
            p[0] += dx
            p[1] += dy
            p[2] += dx
            p[3] += dy
            collider._proxy_key = keys
            if commit_motion:
                self._commit_pending_motion(collider)
            return True
        minx = miny = 1e300
        maxx = maxy = -1e300
        any_prim = False
        for s in shapes:
            cheap = _proxy_aabb_for_shape(s)
            if cheap is not None:
                any_prim = True
                a = cheap
                if a[0] < minx:
                    minx = a[0]
                if a[1] < miny:
                    miny = a[1]
                if a[2] > maxx:
                    maxx = a[2]
                if a[3] > maxy:
                    maxy = a[3]
                continue
            for prim in _snapshot_shape_uncached(s, cache_owner=collider):
                any_prim = True
                a = prim.aabb
                if a[0] < minx:
                    minx = a[0]
                if a[1] < miny:
                    miny = a[1]
                if a[2] > maxx:
                    maxx = a[2]
                if a[3] > maxy:
                    maxy = a[3]
        if not any_prim:
            collider._proxy_valid = False
            collider._world_prims = None
            collider._world_key = None
            if commit_motion:
                collider._pending_motion_dx = 0.0
                collider._pending_motion_dy = 0.0
                collider._motion_dx = 0.0
                collider._motion_dy = 0.0
                collider._motion_translation = True
                collider._proxy_start = None
                collider._pending_path = None
                collider._motion_path = None
            return False
        eps = _PROXY_EPS
        p = collider._proxy
        p[0] = minx - eps
        p[1] = miny - eps
        p[2] = maxx + eps
        p[3] = maxy + eps
        thick = (maxx - minx if maxx - minx < maxy - miny else maxy - miny)
        collider._thick2 = thick * thick
        collider._proxy_key = keys
        collider._proxy_valid = True
        collider._world_prims = None
        collider._world_key = None
        if commit_motion:
            self._commit_pending_motion(collider)
        return True

    def _world_prims(self, collider: Collider) -> List[Prim]:
        """World prims for narrow phase — built only when AABBs overlap."""
        shapes = collider.shapes
        if not shapes:
            return []
        cached = collider._world_prims
        old = collider._world_key
        proxy_keys = collider._proxy_key
        # After _update_proxy / a solver nudge, proxy_key matches world_key and
        # extras do not need another pose-key walk (the settle inner loop).
        if (
            self._trust_proxy_world
            and cached is not None
            and old is not None
            and proxy_keys is not None
            and old == proxy_keys
        ):
            return cached
        keys = tuple(_collision_pose_key(s) for s in shapes)
        if cached is not None and old == keys:
            collider._proxy_key = keys
            return cached
        delta = _keys_uniform_translation(old, keys) if cached is not None else None
        if delta is not None:
            dx, dy = delta
            translated = _translate_prims(cached, dx, dy)
            if translated:
                collider._world_key = keys
                collider._proxy_key = keys
                return translated
        prims: List[Prim] = []
        for s in shapes:
            prims.extend(_snapshot_shape_uncached(s, cache_owner=collider))
        collider._world_prims = prims
        collider._world_key = keys
        collider._proxy_key = keys
        return prims

    def _declared_broad_pairs(
        self,
        colliders: List[Collider],
        proxy: np.ndarray,
    ) -> List[Tuple[int, int]]:
        """AABB pairs from declared relations only (@collide, resolve, ANYTHING).

        Walks each registered (a, b) once and crosses resolved colliders —
        O(declarations × |A| × |B|) instead of O(n²) over all proxies.
        Self-paired tags (``resolve("ball", "ball")``) iterate ``i < j`` and
        vectorize the AABB test when the pool is large. Cross-tag pools of
        8+ on both sides use the same numpy AABB on the swept array.
        """
        idx = {id(c): i for i, c in enumerate(colliders)}
        n = len(colliders)
        swept = proxy.copy()
        for i, c in enumerate(colliders):
            start = c._proxy_start
            if c._in_resolve and start is not None:
                row = swept[i]
                s0, s1, s2, s3 = start[0], start[1], start[2], start[3]
                if s0 < row[0]:
                    row[0] = s0
                if s1 < row[1]:
                    row[1] = s1
                if s2 > row[2]:
                    row[2] = s2
                if s3 > row[3]:
                    row[3] = s3
        # Fast colliders (swept detection) widen the same way; resolve bodies
        # already did above. Empty list on a scene with no fast body.
        for c in self._fast_colliders:
            i = idx.get(id(c))
            if i is None or c._in_resolve:
                continue
            start = c._proxy_start
            row = swept[i]
            if start[0] < row[0]:
                row[0] = start[0]
            if start[1] < row[1]:
                row[1] = start[1]
            if start[2] > row[2]:
                row[2] = start[2]
            if start[3] > row[3]:
                row[3] = start[3]

        pairs: List[Tuple[int, int]] = []
        seen: Set[Tuple[int, int]] = set()
        # Hosts of hitbox parts: a body and its parts (or two parts of one
        # sprite) never pair. ``None`` when no part is registered (hot path).
        owner: Optional[List[int]] = None
        is_part: Optional[List[bool]] = None
        if any(c._part is not None for c in colliders):
            owner = [id(c._identity) for c in colliders]
            is_part = [c._part is not None for c in colliders]
        # A body and the own body of one of its pieces never pair either
        # (``torso.collidable`` + ``Collider([torso, head])``: the boss touched
        # its own torso; AC10), nor do two pieces that are bodies of their own
        # (two weak points of one boss). ``None`` when no multi-piece body is live.
        kin: Optional[Set[Tuple[int, int]]] = None
        for c in self._multi_bodies.values() if self._multi_bodies else ():
            ic = idx.get(id(c))
            if ic is not None:
                own_bodies: List[int] = []
                for ref in c._shapes:
                    piece = ref()
                    own = getattr(piece, "_collider", None) if piece is not None else None
                    if own is None or own is c:
                        continue
                    io = idx.get(id(own))
                    if io is not None:
                        if kin is None:
                            kin = set()
                        kin.add((ic, io) if ic < io else (io, ic))
                        for jo in own_bodies:
                            kin.add((jo, io) if jo < io else (io, jo))
                        own_bodies.append(io)

        def _try_pair(i: int, j: int) -> None:
            if i == j:
                return
            lo, hi = (i, j) if i < j else (j, i)
            key = (lo, hi)
            if key in seen:
                return
            seen.add(key)
            if owner is not None and owner[lo] == owner[hi]:
                return
            if kin is not None and key in kin:
                return
            a = swept[lo]
            b = swept[hi]
            if a[0] > b[2] or b[0] > a[2] or a[1] > b[3] or b[1] > a[3]:
                return
            pairs.append(key)

        def _cross_same(members: Sequence[Collider]) -> None:
            ids: List[int] = []
            for c in members:
                i = idx.get(id(c))
                if i is not None:
                    ids.append(i)
            m = len(ids)
            if m < 2:
                return
            if m >= 8:
                arr = swept[ids]
                minx = arr[:, 0]
                miny = arr[:, 1]
                maxx = arr[:, 2]
                maxy = arr[:, 3]
                no_x = (minx[:, None] > maxx[None, :]) | (minx[None, :] > maxx[:, None])
                no_y = (miny[:, None] > maxy[None, :]) | (miny[None, :] > maxy[:, None])
                overlap = ~(no_x | no_y)
                ii, jj = np.nonzero(np.triu(overlap, k=1))
                for a, b in zip(ii.tolist(), jj.tolist()):
                    _try_pair(ids[a], ids[b])
                return
            for a in range(m):
                ia = ids[a]
                for b in range(a + 1, m):
                    _try_pair(ia, ids[b])

        def _cross_targets(ta, tb, members=self._handler_colliders) -> None:
            tag_a = self._pair_tag_of(ta)
            tag_b = self._pair_tag_of(tb)
            if ta is tb or (tag_a is not None and tag_a == tag_b):
                _cross_same(members(ta))
                return
            left_ids: List[int] = []
            for c in members(ta):
                i = idx.get(id(c))
                if i is not None:
                    left_ids.append(i)
            right_ids: List[int] = []
            for c in members(tb):
                j = idx.get(id(c))
                if j is not None:
                    right_ids.append(j)
            na, nb = len(left_ids), len(right_ids)
            if na == 0 or nb == 0:
                return
            if na >= 8 and nb >= 8:
                a_arr = swept[left_ids]
                b_arr = swept[right_ids]
                aminx, aminy = a_arr[:, 0], a_arr[:, 1]
                amaxx, amaxy = a_arr[:, 2], a_arr[:, 3]
                bminx, bminy = b_arr[:, 0], b_arr[:, 1]
                bmaxx, bmaxy = b_arr[:, 2], b_arr[:, 3]
                no_x = (aminx[:, None] > bmaxx[None, :]) | (bminx[None, :] > amaxx[:, None])
                no_y = (aminy[:, None] > bmaxy[None, :]) | (bminy[None, :] > amaxy[:, None])
                ii, jj = np.nonzero(~(no_x | no_y))
                for a, b in zip(ii.tolist(), jj.tolist()):
                    _try_pair(left_ids[a], right_ids[b])
                return
            for ia in left_ids:
                for jb in right_ids:
                    _try_pair(ia, jb)

        for a, b, _cb, _phase in self._pair_handlers:
            _cross_targets(a, b)
        for a, b, _tok, _only in self._resolve_pairs:
            _cross_targets(a, b, self._resolve_side_colliders)

        anything_ids = [
            i for i, ca in enumerate(colliders)
            if any(t is ANYTHING for t in ca._pair_targets)
        ]
        if anything_ids:
            # ``ANYTHING`` means bodies: a hitbox part is reached by its groups.
            if n >= 8:
                minx = swept[:, 0]
                miny = swept[:, 1]
                maxx = swept[:, 2]
                maxy = swept[:, 3]
                no_x = (minx[:, None] > maxx[None, :]) | (minx[None, :] > maxx[:, None])
                no_y = (miny[:, None] > maxy[None, :]) | (miny[None, :] > maxy[:, None])
                overlap = ~(no_x | no_y)
                np.fill_diagonal(overlap, False)
                for i in anything_ids:
                    hits = np.nonzero(overlap[i])[0]
                    for j in hits.tolist():
                        if is_part is None or not is_part[j]:
                            _try_pair(i, j)
            else:
                for i in anything_ids:
                    for j in range(n):
                        if i != j and (is_part is None or not is_part[j]):
                            _try_pair(i, j)

        return pairs

    # -- step ---------------------------------------------------------------

    def step(self) -> None:
        t_total0 = time.perf_counter()
        self._prune_dead()
        # Linked hitbox ``active`` (``hb["active"] @= fn``): evaluated here, after
        # update / on_update / play(), so collision sees this frame's value.
        from .hitbox import _LINKED_PARTS, _refresh_linked_parts
        if _LINKED_PARTS:
            _refresh_linked_parts()
        self._resolve_cache.clear()
        self._solve_contacts.clear()
        self._solve_contact_sides.clear()
        self._solve_bottom_count.clear()
        self._bounced_prev, self._bounced_now = self._bounced_now, self._bounced_prev
        self._bounced_now.clear()
        for c in self._colliders:
            c._tags_cache = None
            c._in_resolve = False
        for ta, tb, _tok, _only in self._resolve_pairs:
            for c in self._resolve_side_colliders(ta):
                c._in_resolve = True
            for c in self._resolve_side_colliders(tb):
                c._in_resolve = True

        # Snapshot → in-place proxy AABBs (world prims are lazy, on overlap).
        # ``_fast_k2`` lets ``_commit_pending_motion`` list this step's fast
        # colliders (swept detection); a commit outside this loop never does.
        t0 = time.perf_counter()
        # Every proxy is refreshed below; what moved before now is consumed.
        # Drained here, not at the top: the prune's exit handlers and the
        # linked hitbox refresh above write poses too (their bumps belong to
        # this snapshot, not the next one).
        self._drain_pose_cells()
        stale = self._stale
        self._stale = set()
        live: List[Collider] = []
        fast = self._fast_colliders
        fast.clear()
        self._fast_k2 = _FAST_MOTION_FRACTION * _FAST_MOTION_FRACTION
        try:
            if _STEP_SKIP_STILL:
                self._snapshot_moved(stale)
                live = [c for c in self._colliders if c._proxy_valid]
            else:
                for c in self._colliders:
                    if self._update_proxy(c):
                        live.append(c)
                self._moved_now.update(self._colliders)
        finally:
            self._fast_k2 = math.inf
        ms_snapshot = (time.perf_counter() - t0) * 1000.0

        self._last_groups = live
        n_proxy = len(live)
        if n_proxy == 0:
            self._store_resolved_aabbs()
            self._last_prims = []
            self._emit_exit_keys(self._prev_contacts)
            self._prev_contacts = set()
            self._commit_rules()
            self._flux_now = {}
            self._new_rules_now = {}
            self._last_aabb = None
            self.last_stats = {
                "proxies": 0,
                "prims": 0,
                "proxy_pairs": 0,
                "narrow": 0,
                "sat": 0,
                "skin": 0,
                "fast": 0,
                "swept": 0,
                "swept_hits": 0,
                "ms_snapshot": ms_snapshot,
                "ms_broad": 0.0,
                "ms_narrow": 0.0,
                "ms_resolve": 0.0,
                "ms_bounds": 0.0,
                "ms_total": (time.perf_counter() - t_total0) * 1000.0,
            }
            # No body in play: no settle normal or one-way pass can outlive
            # this (the last pair's bodies left collision: S8-6 / S8-7).
            if self._contact_memory:
                self._contact_memory.clear()
            if self._passing:
                self._passing.clear()
            if self._show:
                self._update_debug_draw([])
            return

        proxy = np.zeros((n_proxy, 4), dtype=np.float64)
        for i, c in enumerate(live):
            p = c._proxy
            proxy[i, 0] = p[0]
            proxy[i, 1] = p[1]
            proxy[i, 2] = p[2]
            proxy[i, 3] = p[3]
        self._last_aabb = proxy

        # Broad phase: declared pairs only (@collide, resolve, ANYTHING).
        t0 = time.perf_counter()
        ii_jj = self._declared_broad_pairs(live, proxy)
        ms_broad = (time.perf_counter() - t0) * 1000.0

        current: Dict[Tuple[int, int], CollisionInfo] = {}
        contact_keys: Set[Tuple[int, int]] = set()
        proxy_pairs = 0
        narrow_n = 0
        sat_n = 0
        skin_n = 0
        n_prims = 0
        self._skin_keys = []

        t0 = time.perf_counter()
        # ``_update_proxy`` just refreshed every live ``_proxy_key`` and no user
        # code runs until dispatch, so a hull whose ``_world_key`` matches it is
        # current. A collider in k pairs walks its pose keys once, not k times.
        self._trust_proxy_world = True
        try:
            for i, j in ii_jj:
                ca = live[i]
                cb = live[j]
                if ca is cb:
                    continue
                proxy_pairs += 1
                pas = self._world_prims(ca)
                pbs = self._world_prims(cb)
                n_prims += len(pas) + len(pbs)
                for pa in pas:
                    for pb in pbs:
                        if not _aabb_overlap_tuple(pa.aabb, pb.aabb):
                            continue
                        narrow_n += 1
                        if not _is_fast_narrow(pa, pb):
                            sat_n += 1
                        contact = narrow_phase(pa, pb)
                        if contact is None:
                            continue
                        ida, idb = id(ca), id(cb)
                        key = (ida, idb) if ida < idb else (idb, ida)
                        if key in current and current[key].depth >= contact.depth:
                            pass
                        else:
                            current[key] = _collision_info_from_contact(
                                ca, cb, contact, pas, pbs,
                            )
                        contact_keys.add(key)
                # Resting contact (F1): resolve() parks a body ``_RESOLVE_SLOP``
                # short of its partner, so a standing resolve pair within the
                # skin is still a contact. Otherwise @collide on a resting body
                # flickers with frame time. Sensors stay strict overlap.
                # An immovable partner that moved away this frame (a lift going
                # down) opened the gap by up to its travel before resolve, and
                # floor snap keeps the rider on it: the skin widens by that
                # opening along the gap normal (PB4). Still pairs: no extra.
                if ca._in_resolve and cb._in_resolve and self._resolve_enabled:
                    ida, idb = id(ca), id(cb)
                    key = (ida, idb) if ida < idb else (idb, ida)
                    if key not in contact_keys:
                        if ca._motion_translation or cb._motion_translation:
                            ox, oy, floor_sign = _carry_opening(ca, cb)
                        else:
                            ox = oy = floor_sign = 0.0
                        if (
                            _prims_near(pas, pbs, _CONTACT_SKIN + abs(ox) + abs(oy))
                            and self._resolve_bounce_for(ca, cb) is not None
                        ):
                            contact = _skin_contact(pas, pbs, _CONTACT_SKIN,
                                                    ox, oy, floor_sign)
                        else:
                            contact = None
                        if contact is not None:
                            skin_n += 1
                            self._skin_keys.append(key)
                            current[key] = _collision_info_from_contact(
                                ca, cb, contact, pas, pbs,
                            )
                            contact_keys.add(key)
            # Swept detection: only on a step with a fast collider.
            n_fast = len(fast)
            if n_fast:
                t_enter, swept_n, swept_hits = self._swept_contacts(
                    live, ii_jj, current, contact_keys,
                )
            else:
                t_enter, swept_n, swept_hits = None, 0, 0
        finally:
            self._trust_proxy_world = False
            fast.clear()
        ms_narrow = (time.perf_counter() - t0) * 1000.0

        last_prims: List[Tuple[Collider, Prim]] = []
        if self._show:
            prim_flat = []
            for c in live:
                for prim in self._world_prims(c):
                    last_prims.append((c, prim))
                    prim_flat.append((c, prim, len(prim_flat)))
            self._update_debug_draw(prim_flat)
        else:
            for c in live:
                cached = c._world_prims
                if cached:
                    for prim in cached:
                        last_prims.append((c, prim))
        self._last_prims = last_prims

        self.last_stats = {
            "proxies": float(n_proxy),
            "prims": float(n_prims),
            "proxy_pairs": float(proxy_pairs),
            "narrow": float(narrow_n),
            "sat": float(sat_n),
            "skin": float(skin_n),
            "fast": float(n_fast),
            "swept": float(swept_n),
            "swept_hits": float(swept_hits),
            "ms_snapshot": ms_snapshot,
            "ms_broad": ms_broad,
            "ms_narrow": ms_narrow,
            "ms_resolve": 0.0,
            "ms_bounds": 0.0,
            "ms_total": (time.perf_counter() - t_total0) * 1000.0,
        }

        # Enter / stay / exit. Commit this frame's contacts *before* handlers
        # run: a handler that destroys a partner then finds the new pair and
        # fires its exit (also for a pair entered this frame), and a raising
        # handler cannot leave stale contacts that re-fire ``enter``.
        prev = self._prev_contacts
        entered = contact_keys - prev
        stayed = contact_keys & prev
        exited = prev - contact_keys
        self._prev_contacts = contact_keys
        self._commit_rules()

        id_to_collider = {id(c): c for c in self._colliders}
        gained = None
        if self._flux_now or self._new_rules_now:
            # A rule that began or stopped matching a pair that keeps touching
            # (a tag gained or left, a handler set): its enter or exit (CD3).
            gained = self._rule_changes(stayed, id_to_collider)
            if exited:
                self._exited_now = exited

        def colliders_for_key(key: Tuple[int, int]) -> Tuple[Collider, Collider]:
            return id_to_collider[key[0]], id_to_collider[key[1]]

        def _sort_keys(keys: Set[Tuple[int, int]]) -> List[Tuple[int, int]]:
            idx_map = self._collider_index
            ordered = []
            for key in keys:
                ia = idx_map.get(key[0], key[0])
                ib = idx_map.get(key[1], key[1])
                ordered.append((min(ia, ib), max(ia, ib), key))
            ordered.sort()
            return [key for _a, _b, key in ordered]

        # A ``change_act`` from a handler tears the world down mid-step. No
        # extra guard: the rest of the step's old-act pairs are dropped by the
        # dead-pair rules (enter/stay skip bodies not in play; a destroyed body
        # has no tags for a handler to match and no hooks), and new-act bodies
        # are not in this step's contacts. Game pairs keep dispatching.
        # A rule a touching pair gained enters among this step's enters, in
        # the order the pair would have if it had just begun touching (CD3:
        # alone or beside another rule, the same order).
        enter_keys = (entered | gained) if gained else entered
        if t_enter:
            # Nearest hit first: a fast body's enters run in time-of-impact
            # order, so a shot that destroys itself hits the enemy it reached
            # first (``_dispatch`` skips enters for a body already destroyed).
            # Keys without a time (slow pairs) keep their order, after them.
            entered_order = sorted(
                _sort_keys(enter_keys), key=lambda k: t_enter.get(k, 1.0),
            )
        else:
            entered_order = _sort_keys(enter_keys)
        self._enter_pending = set(entered)
        self._exit_pending = set(exited)
        self._author_ran = False
        # A resolve partner a handler removes from here to the exit loop's
        # end leaves a ghost contact for the survivor's velocity (PE5).
        self._ghost_contacts = []
        self._dispatch_current = current
        self._dispatch_ids = id_to_collider
        try:
            self._dispatch_step(current, entered_order, stayed, exited,
                                colliders_for_key, _sort_keys, id_to_collider)
        finally:
            self._dispatch_current = None
            self._dispatch_ids = None
            if self._flux_now or self._new_rules_now or gained is not None:
                self._flux_now = {}
                self._new_rules_now = {}
                self._gain_pending = {}
                self._stay_skip = {}
                self._lost_pending = {}
                self._exited_now = set()

        t0 = time.perf_counter()
        if self._resolve_enabled:
            if self._ghost_contacts:
                self._apply_ghost_contacts()      # handlers ran: poses validated
            self._trust_proxy_world = True
            try:
                self._apply_auto_resolve(current, id_to_collider)
            finally:
                self._trust_proxy_world = False
        elif self._ghost_contacts:
            self._ghost_contacts = []
        if self._ghost_walls:
            self._ghost_walls = {}          # walls for this step's sweeps only
        self.last_stats["ms_resolve"] = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        # No author code runs between resolve and here, so proxies still match
        # the solver's nudges and world prims can skip the pose-key walk.
        self._trust_proxy_world = True
        try:
            self._store_resolved_aabbs()
        finally:
            self._trust_proxy_world = False
        self._store_end_centers()
        self.last_stats["ms_bounds"] = (time.perf_counter() - t0) * 1000.0
        self.last_stats["ms_total"] = (time.perf_counter() - t_total0) * 1000.0
        self._update_touching_state(self._solve_contacts, id_to_collider)
        # The step's group / object expansions are this step's: a query in the
        # next update() must not test a body parked or opted out meanwhile
        # (review 2026-10-09 S8-8).
        if self._resolve_cache:
            self._resolve_cache.clear()

    def _dispatch_step(self, current, entered_order, stayed, exited,
                       colliders_for_key, _sort_keys, id_to_collider) -> None:
        """This step's enter, stay and exit loops (``step()``)."""
        gain_pending = self._gain_pending
        for key in entered_order:
            if key not in self._enter_pending:
                if gain_pending and key in gain_pending:
                    # A rule this touching pair gained: its enter only.
                    rules = gain_pending.pop(key)
                    if rules and key in current and key in self._prev_contacts:
                        ca, cb = colliders_for_key(key)
                        self._dispatch(ca, cb, current[key], _PHASE_ENTER, only=rules)
                continue                  # its body left mid-step: no enter, no exit
            self._enter_pending.discard(key)
            if key not in current:
                continue
            info = current[key]
            ca, cb = colliders_for_key(key)
            self._dispatch(ca, cb, info, _PHASE_ENTER)
        stay_skip = self._stay_skip
        for key in _sort_keys(stayed):
            if key not in current:
                continue
            info = current[key]
            ca, cb = colliders_for_key(key)
            if stay_skip and key in stay_skip:
                # A rule gained this step stays from the next one (C1).
                self._dispatch(ca, cb, info, _PHASE_STAY, skip=stay_skip[key])
                continue
            self._dispatch(ca, cb, info, _PHASE_STAY)
        self._enter_pending = set()
        for key in _sort_keys(exited):
            if key not in self._exit_pending:
                continue                  # already fired when a body left
            self._exit_pending.discard(key)
            ca, cb = colliders_for_key(key) if key[0] in id_to_collider and key[1] in id_to_collider else (None, None)
            if ca is None:
                continue
            info = CollisionInfo(a=ca._identity, b=cb._identity, normal=Vec2.temp(0, 0), depth=0.0)
            self._dispatch(ca, cb, info, _PHASE_EXIT)
        if self._lost_pending:
            # A rule a touching pair lost (a tag left): its exit, after the
            # step's own exits. One a destroy already ran is gone from here.
            for key in _sort_keys(set(self._lost_pending)):
                lost = self._lost_pending.pop(key, None)
                if lost is None or key not in self._prev_contacts:
                    continue
                ca, cb = colliders_for_key(key)
                info = CollisionInfo(a=ca._identity, b=cb._identity, normal=Vec2.temp(0, 0), depth=0.0)
                self._run_lost_exit(ca, cb, info, lost)

    def _store_end_centers(self) -> None:
        """Where each collider that moved this step ended (its proxy center):
        next step's placement is measured from here. O(moved)."""
        moved = self._moved_now
        if not moved:
            return
        for c in moved:
            if c._proxy_valid:
                p = c._proxy
                c._end_cx = (p[0] + p[2]) * 0.5
                c._end_cy = (p[1] + p[3]) * 0.5
        moved.clear()

    @staticmethod
    def _placement_of(c: Collider, mx: float, my: float) -> Tuple[float, float]:
        """This step's placement of ``c``: its proxy's shift since the end of
        the last step it moved in, less its motion ``(mx, my)``. ``(0, 0)``
        for a collider that has no stored end (new) or did not move."""
        ex = c._end_cx
        if ex is None or not c._proxy_valid:
            return 0.0, 0.0
        p = c._proxy
        return (p[0] + p[2]) * 0.5 - ex - mx, (p[1] + p[3]) * 0.5 - c._end_cy - my

    def _swept_contacts(
        self,
        live: List[Collider],
        ii_jj: List[Tuple[int, int]],
        current: Dict[Tuple[int, int], CollisionInfo],
        contact_keys: Set[Tuple[int, int]],
    ) -> Tuple[Dict[Tuple[int, int], float], int, int]:
        """Contacts along a fast collider's path this frame (swept detection).

        Runs after the end-pose narrow phase, on broad pairs with a fast side
        (their swept boxes were widened in ``_declared_broad_pairs``). A pair
        with no end-pose contact whose relative path hits is a contact this
        frame: depth 0, normal and ``point`` at the time of impact, bodies left
        where they ended. Returns ``(t_enter, swept, hits)``: the impact time
        of each new contact with a fast side (nearest-first enter order), the
        number of exact sweeps, and the swept-only contacts added.
        """
        fast_ids = {id(c) for c in self._fast_colliders}
        prev = self._prev_contacts
        t_enter: Dict[Tuple[int, int], float] = {}
        seen: Set[Tuple[int, int]] = set()
        swept_n = 0
        hits = 0
        for i, j in ii_jj:
            ca = live[i]
            cb = live[j]
            if ca is cb:
                continue
            ida, idb = id(ca), id(cb)
            if ida not in fast_ids and idb not in fast_ids:
                continue
            key = (ida, idb) if ida < idb else (idb, ida)
            if key in seen:
                continue
            seen.add(key)
            overlapping = key in contact_keys
            if overlapping and key in prev:
                continue                       # an open contact: end pose decides
            dax = ca._motion_dx if ca._motion_translation else 0.0
            day = ca._motion_dy if ca._motion_translation else 0.0
            dbx = cb._motion_dx if cb._motion_translation else 0.0
            dby = cb._motion_dy if cb._motion_translation else 0.0
            if ca._motion_path is not None or cb._motion_path is not None:
                pas = self._world_prims(ca)
                pbs = self._world_prims(cb)
                if not pas or not pbs:
                    continue
                swept_n += 1
                found = _toi_along_paths(ca, cb, pas, pbs)
                if found is None:
                    continue
                t, contact, (oax, oay), (obx, oby) = found
                if overlapping:
                    t_enter[key] = t
                    continue
                if t <= 1e-12 and key in prev:
                    continue
                current[key] = _collision_info_from_contact(
                    ca, cb, Contact((contact.normal[0], contact.normal[1]), 0.0, []),
                    _copy_translate(pas, oax, oay), _copy_translate(pbs, obx, oby),
                )
                contact_keys.add(key)
                t_enter[key] = t
                hits += 1
                continue
            # A placement on the scale of a frame's travel is motion for this
            # pair's sweep (a follower placed behind a fast body moves with it;
            # an enemy on a formula slides); a larger one is a teleport, not
            # swept (a respawn is no ghost path). R2-2: the placed side counted
            # as standing at its end pose all frame, where the traveller had
            # just been, so a trailing follower touched every other frame.
            pax, pay = self._placement_of(ca, dax, day)
            pbx, pby = self._placement_of(cb, dbx, dby)
            if pax or pay or pbx or pby:
                scale = max(math.sqrt(ca._thick2), math.sqrt(cb._thick2),
                            math.hypot(dax, day), math.hypot(dbx, dby))
                if pax * pax + pay * pay <= scale * scale:
                    dax += pax
                    day += pay
                if pbx * pbx + pby * pby <= scale * scale:
                    dbx += pbx
                    dby += pby
            # In b's end frame, a travels the relative motion.
            rdx = dax - dbx
            rdy = day - dby
            if rdx == 0.0 and rdy == 0.0:
                continue
            pa = ca._proxy
            if _aabb_toi(
                (pa[0] - rdx, pa[1] - rdy, pa[2] - rdx, pa[3] - rdy),
                cb._proxy, rdx, rdy,
            ) is None:
                continue
            pas = self._world_prims(ca)
            pbs = self._world_prims(cb)
            if not pas or not pbs:
                continue
            swept_n += 1
            hit = _toi_prim_sets(_copy_translate(pas, -rdx, -rdy), pbs, rdx, rdy)
            if hit is None or hit[1] is None:
                continue
            t = hit[0]
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            if overlapping:
                t_enter[key] = t               # new end-pose contact: when it began
                continue
            if t <= 1e-12 and key in prev:
                continue                       # already reported; it has ended
            nx, ny = hit[1].normal[0], hit[1].normal[1]
            back = 1.0 - t
            current[key] = _collision_info_from_contact(
                ca, cb, Contact((nx, ny), 0.0, []),
                _copy_translate(pas, -dax * back, -day * back),
                _copy_translate(pbs, -dbx * back, -dby * back),
            )
            contact_keys.add(key)
            t_enter[key] = t
            hits += 1
        return t_enter, swept_n, hits

    def _apply_auto_resolve(
        self,
        current: Dict[Tuple[int, int], CollisionInfo],
        id_to_collider: Dict[int, Collider],
    ) -> None:
        if not self._resolve_pairs:
            # No resolve pair: no memory of a settle normal or a one-way pass
            # may outlive it (a pair resolved again later used the old normal
            # and pushed a body through the platform: review 2026-10-09 S8-6).
            if self._contact_memory:
                self._contact_memory.clear()
            if self._passing:
                self._passing.clear()
            return
        # Walk declared resolve members only (not every enrolled collider).
        bodies: List[Collider] = []
        statics: List[Collider] = []
        grounded_at_start: Dict[int, bool] = {}
        grounded: List[Collider] = []
        seen: Set[int] = set()
        for ta, tb, _tok, _only in self._resolve_pairs:
            for side in (ta, tb):
                for c in self._resolve_side_colliders(side):
                    cid = id(c)
                    if cid in seen:
                        continue
                    seen.add(cid)
                    ident = c._identity
                    mass = float(getattr(ident, "mass", 1.0)) if ident is not None else 1.0
                    sides = getattr(ident, "touching_sides", frozenset()) or frozenset()
                    on_floor = "bottom" in sides
                    grounded_at_start[cid] = on_floor
                    if _is_static_mass(mass):
                        statics.append(c)
                        continue
                    bodies.append(c)
                    if on_floor:
                        grounded.append(c)
        bodies.sort(key=lambda c: self._collider_index.get(id(c), id(c)))
        if self._author_ran:
            # A handler may have moved or grown a body (a respawn in a hazard
            # handler): resolve sees it, not the proxy built before dispatch
            # (review 2026-10-09 W-G1). Only after author code ran, only the
            # movable bodies (a STATIC partner a handler moves is the rare case
            # left: its proxy follows next step).
            for c in bodies:
                self._update_proxy(c, commit_motion=False)
        # ``only=`` costs nothing here unless some pair has it: one bool per
        # body, and the gate is read only after a hit or an overlap is found.
        has_only = self._has_only
        swept = self._swept_ids
        swept.clear()
        self._pass_statics = statics
        self._pass_static_rows = None
        self._pass_members = {}
        self._pass_carry = (
            self._carry_riders(grounded, grounded_at_start)
            if _RIDER_CARRY and grounded else None
        )
        # Resting-skin contacts the handlers saw, by body (``_answer_unreached``).
        skin_by: Optional[Dict[int, List[Tuple[Tuple[int, int], CollisionInfo]]]] = None
        if _SKIN_ANSWER and self._skin_keys and any(
            tok is not _RESOLVE_POSITION_ONLY and tok is not None and float(tok) > 0.0
            for _a, _b, tok, _o in self._resolve_pairs
        ):                                  # only a bouncy pair answers a skin contact
            skin_by = {}
            for key in self._skin_keys:
                info = current.get(key)
                if info is not None:
                    skin_by.setdefault(key[0], []).append((key, info))
                    skin_by.setdefault(key[1], []).append((key, info))
        walls = self._ghost_walls
        self._ghosts_met.clear()
        for ca in bodies:
            cid = id(ca)
            swept.add(cid)
            partners = self._resolve_pool(ca)
            ghosts = walls.get(cid) if walls else None
            if not partners and not ghosts:
                continue
            gate = None
            if has_only:
                only_map = self._resolve_only_map(ca)
                if only_map is not None:
                    gate, partners = self._only_view(ca, partners, only_map)
                    if not partners and not ghosts:
                        continue
            if _LOCAL_PREFILTER and type(partners) is _PartnerPool:
                partners.localize(ca)
            grounded = bool(grounded_at_start.get(cid))
            stopped = self._sweep_and_slide(ca, partners, gate, grounded, ghosts)
            skins = skin_by.get(cid) if skin_by is not None and not stopped else None
            if ghosts or skins:
                # A removed partner the sweep did not meet still answers what
                # the handler saw (PE5); a live skin contact, for a body that
                # made no stop, only with ``_SKIN_ANSWER`` (LW8).
                self._answer_unreached(ca, skins, ghosts, grounded, id_to_collider)
            if not partners:
                continue
            self._settle_body(ca, partners, gate)
            if grounded:
                self._floor_snap(ca, partners, gate)
        if self._passing:
            # Drop bodies and partners that left the resolve world (a body
            # with no partners left never reaches ``_only_view``), then
            # empty entries.
            for bid in list(self._passing):
                inner = self._passing[bid]
                if bid in seen:
                    for pid in [k for k in inner if k not in seen]:
                        del inner[pid]
                if not inner or bid not in seen:
                    del self._passing[bid]
        live = set(self._solve_contacts)
        self._contact_memory = {
            k: v for k, v in self._contact_memory.items() if k in live
        }

    def _resolve_partners(
        self, ca: Collider
    ) -> List[Tuple[Collider, Any, float, float]]:
        """``(collider, token, odx, ody)`` for each resolve partner of ``ca``."""
        return [(c, token, c._motion_dx, c._motion_dy)
                for c, token in self._resolve_partner_idents(ca)]

    def _resolve_pool(self, ca: Collider):
        """``ca``'s partners for a resolve pass: a ``_PartnerPool`` for a
        large pool of indexed colliders, else the plain list."""
        if not _SHARED_PARTNERS:
            ident = self._resolve_partner_idents(ca)
            own = -1
            rows_key = id(ca)
        else:
            sh = self._shared_partners(ca)
            ident = sh.ident
            own = sh.position(ca)
            rows_key = sh
        n = len(ident) - (own >= 0)
        if not _RESOLVE_VECTOR or n < _POOL_VECTOR_MIN:
            return [(c, token, c._motion_dx, c._motion_dy) for c, token in ident if c is not ca]
        ver = self._struct_version
        hit = rows_key.rows if _SHARED_PARTNERS else self._partner_rows_cache.get(rows_key)
        if hit is not None and hit[0] is ident and hit[1] == ver:
            rows, members = hit[2], hit[3]
        else:
            idx = self._collider_index
            try:
                rows = np.fromiter((idx[id(c)] for c, _t in ident), dtype=np.intp,
                                   count=len(ident))
            except KeyError:
                return [(c, token, c._motion_dx, c._motion_dy) for c, token in ident
                        if c is not ca]
            members = {id(c) for c, _t in ident}
            if _SHARED_PARTNERS:
                rows_key.rows = (ident, ver, rows, members)
            else:
                self._partner_rows_cache[rows_key] = (ident, ver, rows, members)
        return _PartnerPool(self, ident, rows, members, owner=own)

    def _resolve_only_map(self, ca: Collider):
        """``ca``'s ``only=`` map (partner id → entry), or None."""
        if _SHARED_PARTNERS:
            return self._shared_partners(ca).only
        self._resolve_partner_idents(ca)
        return self._partner_only_cache.get(id(ca))

    def _iter_near(self, ca: Collider, partners):
        """``partners`` a pass over ``ca``'s proxy may keep, in order.

        A ``_PartnerPool`` yields only rows whose proxy meets ``ca``'s, and
        asks again (later positions only) when ``ca`` moved under the pass;
        a list is yielded whole. The pass still runs its own test.
        """
        if type(partners) is not _PartnerPool or not ca._proxy_valid:
            yield from partners
            return
        p = ca._proxy
        box = (p[0], p[1], p[2], p[3])
        cands = partners.near_box(*box)
        k = 0
        while k < len(cands):
            i = cands[k]
            k += 1
            yield partners.item(i)
            if (p[0], p[1], p[2], p[3]) != box or not ca._proxy_valid:
                if not ca._proxy_valid:
                    own = partners.owner      # a shared list holds the body too
                    for j in range(i + 1, len(partners.ident)):
                        if j != own:
                            yield partners.item(j)
                    return
                box = (p[0], p[1], p[2], p[3])
                cands = [j for j in partners.near_box(*box) if j > i]
                k = 0

    def _resolve_partner_idents(self, ca: Collider) -> List[Tuple[Collider, Any]]:
        """Partners of ``ca`` from standing ``resolve()`` registrations.

        Tag sides walk ``_tag_colliders`` (O(declared members)), not every
        enrolled collider. Partner *identities* are cached across frames and
        refreshed only on enroll / pair-graph edits; motion deltas are read
        live each call. First matching registration wins the bounce token.
        The resolve pass reads the shared list instead (``_shared_partners``).
        """
        cid = id(ca)
        cached = self._partner_ident_cache.get(cid)
        if cached is None:
            out_ids, only_map, _conflicts = self._build_partner_list(ca, skip=ca)
            self._partner_ident_cache[cid] = out_ids
            self._partner_only_cache[cid] = only_map or None
            cached = out_ids
        return cached

    def _build_partner_list(self, ca: Collider, skip):
        """``(identities, only map, conflicts)`` for a body with ``ca``'s sides.

        ``skip`` is left out (the body itself) and a conflict on another
        partner raises. With ``skip=None`` (a list shared by every body of
        ``ca``'s signature) nothing is left out and conflicts are recorded
        per partner instead, ``{pid: (partner, first, second)}``: the body
        reading the list raises one about any partner but itself.
        """
        out_ids: List[Tuple[Collider, Any]] = []
        # partner id → (only entry in ca's view, registration) for the
        # first registration that reached it; a second one must agree.
        seen: Dict[int, Tuple[Any, Tuple[Any, Any, Any]]] = {}
        only_map: Dict[int, Tuple[Any, bool]] = {}
        conflicts: Dict[int, tuple] = {}

        def _append_side(target, token, entry, reg) -> None:
            for c in self._resolve_side_colliders(target):
                if c is skip:
                    continue
                pid = id(c)
                first = seen.get(pid)
                if first is not None:
                    if first[0] != entry:
                        if skip is None:
                            conflicts.setdefault(pid, (c, first, (entry, reg)))
                        else:
                            self._raise_only_conflict(ca, c, first, (entry, reg))
                    continue
                seen[pid] = (entry, reg)
                out_ids.append((c, token))
                if entry is not None:
                    only_map[pid] = entry

        for ta, tb, token, only in self._resolve_pairs:
            on_a = self._collider_on_resolve_side(ca, ta)
            on_b = self._collider_on_resolve_side(ca, tb)
            reg = (ta, tb, only)
            if on_a:
                _append_side(tb, token, None if only is None else (only, False), reg)
            if on_b and not (on_a and self._same_resolve_side(ta, tb)):
                if only is None:
                    entry = None
                elif isinstance(only, frozenset):
                    entry = (_mirror_only(only), False)
                else:
                    entry = (only, True)
                _append_side(ta, token, entry, reg)
        return out_ids, only_map, conflicts

    def _partner_signature(self, ca: Collider) -> tuple:
        """``ca``'s on-side flags per registration: bodies with equal flags
        have the same partners, but for themselves."""
        cid = id(ca)
        sig = self._partner_sig_cache.get(cid)
        if sig is None:
            sig = tuple(
                (self._collider_on_resolve_side(ca, ta), self._collider_on_resolve_side(ca, tb))
                for ta, tb, _token, _only in self._resolve_pairs
            )
            self._partner_sig_cache[cid] = sig
        return sig

    def _shared_partners(self, ca: Collider) -> "_SharedPartners":
        """The partner list every body of ``ca``'s signature shares (``ca``
        in it too: views skip it), built once per signature per invalidation.
        Raises an ``only=`` conflict about any partner but ``ca``.
        """
        sig = self._partner_signature(ca)
        sh = self._shared_pools.get(sig)
        if sh is None:
            ident, only_map, conflicts = self._build_partner_list(ca, skip=None)
            sh = _SharedPartners(ident, only_map or None, conflicts)
            self._shared_pools[sig] = sh
        if sh.conflicts:
            for pid, (cb, first, second) in sh.conflicts.items():
                if cb is not ca:
                    self._raise_only_conflict(ca, cb, first, second)
        return sh

    def _raise_only_conflict(self, ca: Collider, cb: Collider, first, second) -> None:
        """Two registrations reach one body pair with different ``only=``.

        First-wins would drop a filter depending on declaration order, so this
        raises instead (at ``resolve()``, or on the first step after a tag join).
        """
        from .entity import entity_label

        def _reg(item) -> str:
            ta, tb, only = item[1]
            return f"resolve({_side_code(ta)}, {_side_code(tb)}, {_only_code(only)})"

        raise ValueError(
            f"{entity_label(ca._identity)} and {entity_label(cb._identity)} are paired by "
            f"{_reg(first)} and by {_reg(second)}, which disagree on only=. "
            "Keep one registration per body pair (e.g. give one-way platforms "
            "their own tag), or pass the same only= to both."
        )

    def _only_view(
        self, ca: Collider, partners: List[Tuple[Collider, Any, float, float]],
        only_map: Dict[int, Tuple[Any, bool]],
    ) -> Tuple[_OnlyGate, List[Tuple[Collider, Any, float, float]]]:
        """Gate for ``ca``'s filtered partners; passing partners left out.

        A pass ends when the pair no longer overlaps (or is no longer
        filtered). Only called for bodies with an ``only=`` partner.
        """
        cid = id(ca)
        passing = self._passing.setdefault(cid, {})
        if passing:
            for pid, cb in list(passing.items()):
                if (
                    only_map.get(pid) is None
                    or not _proxy_aabb_overlap(ca, cb)
                    or self._collision_info_for_colliders(ca, cb) is None
                ):
                    self._end_passing(ca, pid)
            if passing:
                # ``ok`` rejects them too; dropping them here only saves the
                # TOI / overlap work for the whole pass.
                partners = [p for p in partners if passing.get(id(p[0])) is not p[0]]
        return _OnlyGate(self, ca, only_map, passing), partners

    def _nudge_collider(self, collider: Collider, dx: float, dy: float) -> None:
        if abs(dx) < 1e-18 and abs(dy) < 1e-18:
            return
        self._moved_now.add(collider)
        ident = collider._identity
        # The shifted key below is the pose only if the stored key was the
        # pose before the move: a shape this collider shares with another
        # body may have moved since (the other body's nudge).
        stored_revs = collider._proxy_revs
        revs_before = _collider_pose_revs(collider.shapes) if stored_revs is not None else None
        key_was_fresh = stored_revs is not None and stored_revs == revs_before
        moved = False
        if ident is not None and ident is not collider:
            mb = getattr(ident, "_move_by", None)
            if callable(mb):
                mb(dx, dy)
                moved = True
        if not moved:
            for s in collider.shapes:
                mb = getattr(s, "_move_by", None)
                if callable(mb):
                    mb(dx, dy)
        p = collider._proxy
        p[0] += dx
        p[1] += dy
        p[2] += dx
        p[3] += dy
        self._row_dirty.add(collider)
        shapes = collider.shapes
        shifted = _shift_pose_key_bundle(collider._proxy_key, dx, dy)
        if collider._world_prims:
            translated = _translate_prims(collider._world_prims, dx, dy)
            if not translated:
                collider._world_prims = None
                collider._world_key = None
            elif shifted is not None:
                collider._world_key = shifted
            elif shapes:
                collider._world_key = tuple(_collision_pose_key(s) for s in shapes)
        if shifted is not None:
            collider._proxy_key = shifted
        elif shapes:
            collider._proxy_key = tuple(_collision_pose_key(s) for s in shapes)
        # A move bumped the revisions and the key above follows it. A refused
        # move (a piece of another body) left them: the shifted key is then
        # not the pose, so the next refresh must build it (no skip).
        revs_after = _collider_pose_revs(shapes) if _POSE_REV_SKIP and key_was_fresh else None
        collider._proxy_revs = revs_after if revs_after != revs_before else None
        if collider._proxy_revs is None:
            self._untrusted.add(collider)       # the next refresh builds the key
        collider._proxy_valid = True

    def _bump_solve_bottom(self, cid: int, delta: int) -> None:
        n = self._solve_bottom_count.get(cid, 0) + delta
        if n <= 0:
            self._solve_bottom_count.pop(cid, None)
        else:
            self._solve_bottom_count[cid] = n

    @staticmethod
    def _pair_key(ca: Collider, cb: Collider) -> Tuple[int, int]:
        ia, ib = id(ca), id(cb)
        return (ia, ib) if ia < ib else (ib, ia)

    def _record_solve_contact(
        self,
        ca: Collider,
        cb: Collider,
        nx_self_to_other: float,
        ny_self_to_other: float,
        depth: float,
        points: Optional[List[Tuple[float, float]]] = None,
    ) -> None:
        if type(cb) is _GhostPartner:
            self._ghosts_met.add(id(cb))    # a removed partner is in no contact
            return
        ia, ib = id(ca), id(cb)
        if ia < ib:
            nx, ny = nx_self_to_other, ny_self_to_other
            a_id, b_id = ca, cb
        else:
            nx, ny = -nx_self_to_other, -ny_self_to_other
            a_id, b_id = cb, ca
        pts = list(points or [])
        if not pts:
            pts = _points_or_witness(
                pts, self._world_prims(a_id), self._world_prims(b_id), nx, ny,
            )
            if not pts and ca._proxy_valid and cb._proxy_valid:
                # Canonical key order: normal already points a→b for the stored info.
                if ia < ib:
                    pts = [_synthesize_contact_point(ca._proxy, cb._proxy, nx, ny)]
                else:
                    pts = [_synthesize_contact_point(cb._proxy, ca._proxy, nx, ny)]
        info = CollisionInfo(
            a=a_id._identity,
            b=b_id._identity,
            normal=Vec2.temp(nx, ny),
            depth=float(depth),
            points=pts,
        )
        key = (min(ia, ib), max(ia, ib))
        prev = self._solve_contacts.get(key)
        if prev is None or info.depth >= prev.depth:
            self._solve_contacts[key] = info
            side_lo = _side_from_normal(nx, ny)
            side_hi = _side_from_normal(-nx, -ny)
            old_sides = self._solve_contact_sides.get(key)
            if old_sides is not None:
                if old_sides[0] == "bottom":
                    self._bump_solve_bottom(key[0], -1)
                if old_sides[1] == "bottom":
                    self._bump_solve_bottom(key[1], -1)
            self._solve_contact_sides[key] = (side_lo, side_hi)
            if side_lo == "bottom":
                self._bump_solve_bottom(key[0], 1)
            if side_hi == "bottom":
                self._bump_solve_bottom(key[1], 1)
        nlen = math.hypot(nx, ny)
        if nlen > 1e-12:
            self._contact_memory[key] = (nx / nlen, ny / nlen)

    def _respond_velocity(
        self,
        ca: Collider,
        cb: Collider,
        token: Any,
        nx: float,
        ny: float,
    ) -> None:
        if token is _RESOLVE_POSITION_ONLY or token is None:
            return
        if type(cb) is _GhostPartner:
            self._ghost_velocity(ca, cb, token, nx, ny)
            return
        bounce = float(token)
        if bounce > 0.0:
            va = getattr(ca._identity, "_vel", None)
            if va is not None:
                vbv = getattr(cb._identity, "_vel", None) if cb._identity is not None else None
                ax, ay = _vec2_components(va)
                bx, by = (0.0, 0.0) if vbv is None else _vec2_components(vbv)
                self._note_bounce(ca, ax, ay, bx, by, nx, ny, bounce)
        info = CollisionInfo(
            a=ca._identity,
            b=cb._identity,
            normal=Vec2.temp(nx, ny),
            depth=0.0,
        )
        info.bounce_apart(bounce=bounce)

    def _note_bounce(self, ca: Collider, ax: float, ay: float, bx: float, by: float,
                     nx: float, ny: float, bounce: float) -> None:
        """A real bounce: the impulse sends ``ca`` off at more than the leave
        speed (approach × ``bounce``). Resting and walking contacts approach at
        ``g · dt``, far under it, so the walker leave gate still holds them
        (Collision Design, "Leave gate"; R2-1). Every velocity response calls
        this: the sweep's, the unreached contact's, a removed partner's."""
        if bounce > 0.0 and bounce * ((ax - bx) * nx + (ay - by) * ny) > _FLOOR_SNAP_LEAVE_VY:
            self._bounced_now.add(id(ca))

    def _ghost_velocity(
        self, ca: Collider, g: "_GhostPartner", token: Any, nx: float, ny: float,
    ) -> None:
        """A stop at a removed partner: ``velocity_split`` with its mass and
        ``.vel`` as they were (none: immovable), written on the survivor only."""
        ident = ca._identity
        va = getattr(ident, "_vel", None)
        if va is None:
            return
        gvx, gvy = (0.0, 0.0) if g.vel is None else _vec2_components(g.vel)
        self._note_bounce(ca, float(va.x), float(va.y), gvx, gvy, nx, ny, float(token))
        contact = CollisionInfo(a=ident, b=g.dead._identity, normal=Vec2.temp(nx, ny), depth=0.0)
        nva, _nvb = contact.velocity_split(
            mass_a=float(getattr(ident, "mass", 1.0)),
            mass_b=STATIC if g.vel is None else g.mass,
            bounce=float(token), vel_a=va,
            vel_b=(0.0, 0.0) if g.vel is None else g.vel,
        )
        va.x, va.y = float(nva.x), float(nva.y)

    def _earliest_toi(
        self,
        pas: List[Prim],
        rdx: float,
        rdy: float,
        partners: Sequence[Tuple[Collider, Any, float, float]],
        *,
        relative: bool = False,
        gate: Optional[_OnlyGate] = None,
        deferred: Optional[List[Tuple[float, float, float, Collider, Any, float, float]]] = None,
        ties: Optional[list] = None,
        ghosts: Optional[List[Tuple["_GhostPartner", Any, float, float]]] = None,
    ) -> Optional[Tuple[float, float, float, Collider, Any, float, float]]:
        """Earliest accepted hit of ``pas`` moving by ``(rdx, rdy)``, or None.

        A hit the ``only=`` gate rejects, reached before any accepted one,
        starts a pass. With ``deferred`` (the sweep of a grounded body) those
        hits are appended there instead, and the caller marks them unless a
        seam step makes them moot.

        ``ties`` (a list) receives every accepted hit within the contact skin
        of the earliest whose normal differs from it, the earliest included,
        as ``(t, nx, ny, partner, token, odx, ody, mdx, mdy)`` (the pair's
        motion); it is left
        empty when there is no such second hit (Collision Design, "Joint
        stop"). ``ghosts``: this step's removed partners of the body, still
        walls (``_GhostPartner``), walked after the pool.
        """
        if not pas:
            return None
        minx = min(p.aabb[0] for p in pas)
        miny = min(p.aabb[1] for p in pas)
        maxx = max(p.aabb[2] for p in pas)
        maxy = max(p.aabb[3] for p in pas)
        sx0, sy0, sx1, sy1 = _swept_aabb((minx, miny, maxx, maxy), rdx, rdy)
        if type(partners) is _PartnerPool:
            partners = [partners.item(i) for i in partners.near_swept(sx0, sy0, sx1, sy1)]
        best: Optional[Tuple[float, float, float, Collider, Any, float, float]] = None
        rejected: Optional[List[Tuple[float, float, float, Collider, Any, float, float]]] = None
        # Ties are listed only from a second accepted hit on: the first (and
        # its motion) is kept by reference, so a lone hit costs nothing.
        first = None
        fmx = fmy = 0.0
        for cb, token, odx, ody in partners:
            # Partner box over the frame: union of its start (proxy - motion)
            # and end proxy, inlined — this loop visits the whole partner pool.
            pb = cb._proxy
            if odx > 0.0:
                if pb[0] - odx > sx1 or sx0 > pb[2]:
                    continue
            elif pb[0] > sx1 or sx0 > pb[2] - odx:
                continue
            if ody > 0.0:
                if pb[1] - ody > sy1 or sy0 > pb[3]:
                    continue
            elif pb[1] > sy1 or sy0 > pb[3] - ody:
                continue
            pbs_end = self._world_prims(cb)
            if not pbs_end:
                continue
            if relative and (odx or ody):
                pbs = _copy_translate(pbs_end, -odx, -ody)
                mdx = rdx - odx
                mdy = rdy - ody
                hit = _toi_prim_sets(pas, pbs, mdx, mdy)
            else:
                mdx = rdx
                mdy = rdy
                hit = _toi_prim_sets(pas, pbs_end, mdx, mdy)
            if hit is None:
                continue
            t, contact = hit
            if contact is None:
                continue
            # TOI at t=0 means "already overlapping". Do not let a separating
            # or purely tangential motion clamp this frame's motion to zero;
            # that overlap is a settle concern, not a sweep blocker.
            if t <= 1e-12:
                nx0, ny0 = contact.normal[0], contact.normal[1]
                if (mdx * nx0 + mdy * ny0) <= 0.0:
                    continue
            if gate is not None and not gate.ok(
                cb, contact.normal[0], contact.normal[1], contact.points,
            ):
                if rejected is None:
                    rejected = []
                rejected.append((
                    t, contact.normal[0], contact.normal[1], cb, token, odx, ody,
                ))
                continue
            if ties is not None and best is not None:
                if not ties:
                    ties.append(first + (fmx, fmy))
                ties.append((t, contact.normal[0], contact.normal[1], cb, token, odx, ody,
                             mdx, mdy))
            if best is None or t < best[0] - 1e-12:
                best = (
                    t, contact.normal[0], contact.normal[1],
                    cb, token, odx, ody,
                )
                if first is None:
                    first, fmx, fmy = best, mdx, mdy
        if ghosts:
            # A removed partner is still and pushes nothing: a plain sweep
            # against its frozen prims (PE5).
            for g, token, _odx, _ody in ghosts:
                pb = g._proxy
                if pb[0] > sx1 or sx0 > pb[2] or pb[1] > sy1 or sy0 > pb[3]:
                    continue
                hit = _toi_prim_sets(pas, g.prims, rdx, rdy)
                if hit is None or hit[1] is None:
                    continue
                t, contact = hit
                gnx, gny = contact.normal[0], contact.normal[1]
                if t <= 1e-12 and rdx * gnx + rdy * gny <= 0.0:
                    continue
                if gate is not None and not gate.ok(g.dead, gnx, gny, contact.points):
                    self._ghosts_met.add(id(g))     # passed through: nothing to answer
                    if rejected is None:
                        rejected = []
                    rejected.append((t, gnx, gny, g, token, 0.0, 0.0))
                    continue
                if ties is not None and best is not None:
                    if not ties:
                        ties.append(first + (fmx, fmy))
                    ties.append((t, gnx, gny, g, token, 0.0, 0.0, rdx, rdy))
                if best is None or t < best[0] - 1e-12:
                    best = (t, gnx, gny, g, token, 0.0, 0.0)
                    if first is None:
                        first, fmx, fmy = best, rdx, rdy
        if ties and best is not None:
            # The same stop, another face: a hit parallel to the earliest (a
            # flat seam) answers alike, so only a different normal joins.
            t0, bx, by = best[0], best[1], best[2]
            bl = math.hypot(bx, by)
            if bl < 1e-12:
                ties.clear()
            else:
                ties[:] = [
                    h for h in ties
                    if (h[0] - t0) * math.hypot(h[7], h[8]) <= _CONTACT_SKIN and (
                        h[3] is best[3]
                        or h[1] * bx + h[2] * by < (1.0 - 1e-9) * bl * math.hypot(h[1], h[2]))
                ]
                if len(ties) < 2:
                    ties.clear()
        if rejected is not None:
            # The body crosses into a rejected partner only if nothing
            # accepted stops it first; a later rejected hit is re-judged on
            # the next slide (from where the body really is).
            stop = best[0] - 1e-12 if best is not None else math.inf
            for rej in rejected:
                if rej[0] < stop:
                    if deferred is not None:
                        deferred.append(rej)
                    else:
                        gate.mark(_gate_body(rej[3]))
        return best

    def _sweep_and_slide(
        self,
        ca: Collider,
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate] = None,
        grounded: bool = False,
        ghosts: Optional[List[Tuple["_GhostPartner", Any, float, float]]] = None,
    ) -> bool:
        """Sweep ``ca``'s frame motion against its partners and slide (steps
        2-3 of Resolution); ``ghosts``: its removed partners this step, still
        walls. True when the sweep stopped somewhere (a contact, a ghost, a
        seam step)."""
        dx = ca._motion_dx if ca._motion_translation else 0.0
        dy = ca._motion_dy if ca._motion_translation else 0.0
        pas_end = self._world_prims(ca)
        if not pas_end:
            return False
        if ghosts:
            extra = {id(g.dead): g.only_entry for g, _tok, _a, _b in ghosts
                     if g.only_entry is not None}
            if extra:
                # The removed partners' ``only=`` entries join this sweep's gate.
                only_map = dict(gate._map) if gate is not None else {}
                only_map.update(extra)
                gate = _OnlyGate(self, ca, only_map,
                                 gate._passing if gate is not None
                                 else self._passing.setdefault(id(ca), {}))
        stopped = False
        seam = _SEAM_STEP > 0.0
        cid = id(ca)
        # A rider's motion channel holds its carry (``_carry_riders``); the
        # stop-on-slope intent is its own motion, and its carrier's hit leaves
        # the relative leftover (the carry is already travelled).
        carry = self._pass_carry.get(cid) if self._pass_carry else None
        if carry is None:
            carrier = None
            own_dx = dx
        else:
            carrier = carry[0]
            own_dx = dx - carry[1]
        if type(partners) is _PartnerPool:
            partner_moves = partners.moves()
        else:
            partner_moves = any(
                abs(odx) > 1e-12 or abs(ody) > 1e-12 for _cb, _tok, odx, ody in partners
            )
        if math.hypot(dx, dy) < _SLIDE_EPS:
            if partner_moves:
                return self._sweep_idle_against_partner(ca, pas_end, partners, gate)
            return False
        pas = _copy_translate(pas_end, -dx, -dy)
        ox = 0.0
        oy = 0.0
        remaining = (dx, dy)
        # A rider's carry still to travel (None: not a rider).
        carry_left = (carry[1], carry[2]) if carry is not None else None
        for slide in range(_MAX_SLIDES):
            rdx, rdy = remaining
            if math.hypot(rdx, rdy) < _SLIDE_EPS:
                break
            moved = _copy_translate(pas, ox, oy)
            # Only the first slide is relative. Not "the body has not moved":
            # a stop whose unswept travel a wall cut to nothing (PE4) leaves
            # it where it started, and the next slide is still a later one.
            first = slide == 0
            # Standing (last frame, or on a floor met earlier this frame):
            # a side face with a small lip above the feet may be a seam step.
            ground = seam and (grounded or self._solve_bottom_count.get(cid, 0) > 0)
            deferred = [] if ground and gate is not None else None
            ties = [] if _JOINT_RESPONSE else None
            hit = self._earliest_toi(
                moved, rdx, rdy, partners, relative=first, gate=gate, deferred=deferred,
                ties=ties, ghosts=ghosts,
            )
            if deferred:
                # One-way: a rejected side hit at a seam lip is a step, not a
                # pass. Anything else is marked exactly as without the step.
                deferred.sort(key=lambda h: h[0])
                rej = deferred[0]
                step = None
                if _seam_candidate(rej) and type(rej[3]) is not _GhostPartner:
                    step = self._try_seam_step(ca, moved, rdx, rdy, rej, partners, gate)
                if step is None:
                    for rej_hit in deferred:
                        gate.mark(_gate_body(rej_hit[3]))
                else:
                    ox, oy, remaining = self._take_seam_step(ca, rej, step, ox, oy)
                    stopped = True
                    continue
            if hit is None:
                ox += rdx
                oy += rdy
                remaining = (0.0, 0.0)
                break
            t, nx, ny, other, token, odx, ody = hit
            t = max(0.0, min(1.0, t))
            nlen = math.hypot(nx, ny)
            if nlen > 1e-12:
                nx /= nlen
                ny /= nlen
            if ground and _seam_candidate(hit) and type(other) is not _GhostPartner:
                step = self._try_seam_step(ca, moved, rdx, rdy, hit, partners, gate)
                if step is not None:
                    ox, oy, remaining = self._take_seam_step(ca, hit, step, ox, oy)
                    stopped = True
                    continue
            stopped = True
            if ties:
                # Two partners or more at this stop (LW2): answered together.
                joint = self._joint_stop(ca, ties, t, rdx, rdy, own_dx, carry_left, moved,
                                         other, grounded)
                if joint is not None:
                    ox += joint[0]
                    oy += joint[1]
                    remaining = joint[2]
                    continue
            side = _side_from_normal(nx, ny)
            # Bounce sub-step (LW7): the restitution this stop's velocity
            # response applies, for the leftover below. Not for a body that
            # started the frame on the floor it meets: one frame's gravity
            # kick reflected as travel would keep it hopping (rest).
            e_sub = 0.0
            if _BOUNCE_SUBSTEP and not (grounded and side == "bottom"):
                e_sub = self._substep_restitution(ca, other, token, nx, ny)
            ox += rdx * t
            oy += rdy * t
            stop = side == "bottom" and abs(own_dx) < _STOP_ON_SLOPE_INTENT
            if first:
                mx, my = rdx - odx, rdy - ody
            else:
                mx, my = rdx, rdy
            bx = by = 0.0
            if nlen > 1e-12:
                bx, by = _skin_back_off(nx, ny, mx, my, stop)
                ox += bx
                oy += by
            self._record_solve_contact(ca, other, nx, ny, 0.0)
            self._respond_velocity(ca, other, token, nx, ny)
            # What the body slides on: this slide's motion past the stop, its
            # part along the normal removed (stop-on-slope: nothing), and with
            # a bounce the closing part reflected by the same restitution.
            leftover_x = mx * (1.0 - t) if first else rdx * (1.0 - t)
            leftover_y = my * (1.0 - t) if first else rdy * (1.0 - t)
            if first and other is carrier:
                # A rider meeting its carrier (PB2): the slide is the motion
                # relative to it (a walk on the lift), and the carrier's own
                # leftover is travelled on the next slides, not placed, so a
                # wall on the lift's path stops the rider.
                remaining = (0.0, 0.0) if stop else _remove_normal_component(
                    leftover_x, leftover_y, nx, ny)
                carry_left = (odx * (1.0 - t), ody * (1.0 - t))
                remaining = (remaining[0] + carry_left[0], remaining[1] + carry_left[1])
                inherit = False
            else:
                inherit = first and (odx or ody)
                shared = (inherit and carry_left is not None
                          and self._pass_carry.get(id(other)) is not None)
                if first:
                    leftover_x = rdx * (1.0 - t)
                    leftover_y = rdy * (1.0 - t)
                    if shared:
                        # Both ride: the partner's leftover, inherited below,
                        # already holds the carry; slide on by the own motion.
                        leftover_x -= carry_left[0] * (1.0 - t)
                        leftover_y -= carry_left[1] * (1.0 - t)
                remaining = (0.0, 0.0) if stop else _remove_normal_component(
                    leftover_x, leftover_y, nx, ny)
                # The closing gap left after the stop, relative to the partner.
                g_sub = (mx * nx + my * ny) * (1.0 - t)
                if g_sub > 0.0:
                    # The pair separates by ``e * gap`` over the rest of the
                    # frame (a movable partner's share is ``(1 + e) * gap``,
                    # in ``_share_sweep_stop``); bounce=0: nothing, the slide.
                    k = -e_sub * g_sub
                    if type(other) is _GhostPartner and other.vel is not None \
                            and not _is_static_mass(other.mass):
                        # A removed movable body is not pushed; the survivor
                        # still travels as if it had pushed it.
                        ma = float(getattr(ca._identity, "mass", 1.0))
                        k += (1.0 + e_sub) * g_sub * (1.0 / other.mass) / (
                            1.0 / ma + 1.0 / other.mass)
                    if k:
                        remaining = (remaining[0] + k * nx, remaining[1] + k * ny)
                else:
                    e_sub = 0.0
                if shared:
                    carry_left = None               # delivered by the inheritance
                if carry_left is not None:
                    # The part of this slide that is still the carry: a stop
                    # on a floor ends the rider's own motion, not the ride.
                    carry_left = _remove_normal_component(
                        carry_left[0] * (1.0 - t), carry_left[1] * (1.0 - t), nx, ny)
                    if stop:
                        remaining = carry_left
            # Relative-frame TOI is against the partner's start-of-frame pose.
            # Convert back to world space by inheriting the partner's leftover
            # displacement — every contact side, not only a standing rider.
            ix, iy = bx, by                 # what the body travels unswept
            if inherit:
                ox += odx * (1.0 - t)
                oy += ody * (1.0 - t)
                ix += odx * (1.0 - t)
                iy += ody * (1.0 - t)
            if _SWEEP_MASS_SPLIT and nlen > 1e-12:
                if first:
                    gap = ((rdx - odx) * nx + (rdy - ody) * ny) * (1.0 - t)
                else:
                    gap = (rdx * nx + rdy * ny) * (1.0 - t)
                # A closing gap is split; an inheritance alone is still swept
                # against the body's walls (``_share_sweep_stop``).
                if gap > 0.0 or (inherit and _SWEEP_INHERIT_CLAMP):
                    sx, sy = self._share_sweep_stop(
                        ca, other, nx, ny, gap * (1.0 + e_sub) if gap > 0.0 else gap,
                        ix, iy, ox - ix - dx, oy - iy - dy,
                    )
                    ox += sx
                    oy += sy
        self._nudge_collider(ca, ox - dx, oy - dy)
        return stopped

    def _substep_restitution(
        self, ca: Collider, cb: Any, token: Any, nx: float, ny: float,
    ) -> float:
        """The restitution this stop's velocity response applies along the
        unit normal ``(nx, ny)``, for the bounce sub-step: the pair's
        ``bounce=``, or 0 when the response changes nothing (position-only
        pair, no ``.vel`` on the body, a velocity that does not approach: a
        body moved by ``move_by`` alone slides as before)."""
        if token is _RESOLVE_POSITION_ONLY or token is None:
            return 0.0
        e = float(token)
        if e <= 0.0:
            return 0.0
        vel = getattr(ca._identity, "_vel", None)
        if vel is None:
            return 0.0
        _mb, ov = _partner_mass_vel(cb)
        rvx = float(vel.x) - (ov[0] if ov is not None else 0.0)
        rvy = float(vel.y) - (ov[1] if ov is not None else 0.0)
        return e if rvx * nx + rvy * ny > 0.0 else 0.0

    def _joint_stop(
        self,
        ca: Collider,
        ties: List[Tuple[float, float, float, Any, Any, float, float, float, float]],
        t: float,
        rdx: float,
        rdy: float,
        own_dx: float,
        carry_left: Optional[Tuple[float, float]],
        moved: List[Prim],
        best_cb: Any,
        grounded: bool,
    ) -> Optional[Tuple[float, float, Tuple[float, float]]]:
        """One stop against every still, immovable partner the slide reaches
        within the skin (LW2; Collision Design, "Joint stop"): ``(ox, oy,
        remaining)``, the offset from the slide's start and the next slide's
        motion; the contacts are recorded and the velocity answered together.
        None: the earliest hit answers alone (a moving or movable partner, a
        rider, normals that turn out parallel, an obtuse wedge, more than
        ``_JOINT_MAX`` contacts).

        ``ties`` come from ``_earliest_toi`` (the earliest and the hits within
        the skin with another normal). A tie joins only when the slide along
        each contact runs into the other at once, both ways: what the next
        slides of the one-at-a-time answer would meet. A tile seam's side face
        that a walker's floor slide passes 0.08 DU above stays out (internal
        edge); a ball's slide along one seam corner meets the other corner.
        """
        if carry_left is not None or len(ties) > _JOINT_MAX:
            return None
        ties = sorted(ties, key=lambda h: h[3] is not best_cb)     # the earliest first
        ns: List[Tuple[float, float]] = []
        parts: List[Tuple[Any, Any]] = []
        for _t, hx, hy, cb, tok, odx, ody, _mx, _my in ties:
            if odx or ody:
                return None
            mb, ov = _partner_mass_vel(cb)
            if ov is not None and (ov[0] or ov[1]):
                return None
            if not _is_static_mass(mb) and not (type(cb) is _GhostPartner and ov is None):
                return None                 # a movable partner takes a share: one at a time
            hl = math.hypot(hx, hy)
            if hl < 1e-12:
                return None
            ns.append((hx / hl, hy / hl))
            parts.append((cb, tok))
        lx, ly = rdx * (1.0 - t), rdy * (1.0 - t)

        def reaches(na, cbb, nb):
            """The slide along contact ``na`` meets ``cbb`` (normal ``nb``)
            within the skin, from the stop backed off along ``na``."""
            tx, ty = _remove_normal_component(lx, ly, na[0], na[1])
            tl = math.hypot(tx, ty)
            if tl < 1e-9:
                return False
            rate = (tx * nb[0] + ty * nb[1]) / tl
            if rate <= 1e-3:
                return False
            k = min(2.0 * _CONTACT_SKIN / rate, 50.0 * _CONTACT_SKIN) / tl
            px, py = tx * k, ty * k
            start = _copy_translate(moved, rdx * t - na[0] * _RESOLVE_SLOP,
                                    rdy * t - na[1] * _RESOLVE_SLOP)
            pbs = cbb.prims if type(cbb) is _GhostPartner else self._world_prims(cbb)
            hh = _toi_prim_sets(start, pbs, px, py)
            if hh is None or hh[1] is None:
                return False
            return hh[0] > 1e-12 or px * hh[1].normal[0] + py * hh[1].normal[1] > 0.0

        n0 = ns[0]
        keep = [0] + [
            i for i in range(1, len(ns))
            if reaches(n0, parts[i][0], ns[i]) and reaches(ns[i], parts[0][0], n0)
        ]
        if len(keep) < 2:
            return None
        ns = [ns[i] for i in keep]
        parts = [parts[i] for i in keep]
        sx = sum(n[0] for n in ns)
        sy = sum(n[1] for n in ns)
        sl = math.hypot(sx, sy)
        if sl < 1e-9:
            return None
        sx /= sl
        sy /= sl
        c = min(sx * n[0] + sy * n[1] for n in ns)
        if c < 0.2:
            return None                     # an obtuse wedge: one at a time
        # The skin: back off along the summed normal, far enough to leave
        # the slop to every contact; a stop with no sideways intent backs off
        # along its own motion instead, as one contact does (PE2: no creep).
        back = min(_RESOLVE_SLOP / c, 3.0 * _RESOLVE_SLOP)
        bx, by = -sx * back, -sy * back
        stop = abs(own_dx) < _STOP_ON_SLOPE_INTENT and any(
            _side_from_normal(n[0], n[1]) == "bottom" for n in ns)
        if stop and _SKIN_ALONG_MOTION:
            ml = math.hypot(rdx, rdy)
            cm = min((rdx * n[0] + rdy * n[1]) / ml for n in ns) if ml > 1e-12 else 0.0
            if cm >= _SKIN_MOTION_COS:
                k = _RESOLVE_SLOP / (cm * ml)
                bx, by = -rdx * k, -rdy * k
        for (cb, _tok), n in zip(parts, ns):
            self._record_solve_contact(ca, cb, n[0], n[1], 0.0)
        answers = [not (tok is _RESOLVE_POSITION_ONLY or tok is None) for _cb, tok in parts]
        es = [max(0.0, float(tok)) if a else 0.0 for (_cb, tok), a in zip(parts, answers)]
        approached = [False] * len(ns)
        vel = getattr(ca._identity, "_vel", None)
        if vel is not None and any(answers):
            vx, vy = float(vel.x), float(vel.y)
            approached = [a and vx * n[0] + vy * n[1] > 0.0 for n, a in zip(ns, answers)]
            vel.x, vel.y = _cone_response(
                vx, vy, [n for n, a in zip(ns, answers) if a],
                [e for e, a in zip(es, answers) if a])
        # The leftover takes the same answer (bounce sub-step), but a body
        # that started the frame grounded does not bounce off its floor.
        les = [
            e if (ap and _BOUNCE_SUBSTEP
                  and not (grounded and _side_from_normal(n[0], n[1]) == "bottom")) else 0.0
            for e, ap, n in zip(es, approached, ns)
        ]
        rx, ry = _cone_response(lx, ly, ns, les)
        if stop:
            px, py, _js = _cone_split(lx, ly, ns)
            rx -= px                        # stop-on-slope: the slide is dropped
            ry -= py
        return rdx * t + bx, rdy * t + by, (rx, ry)

    def _try_seam_step(
        self,
        ca: Collider,
        moved: List[Prim],
        rdx: float,
        rdy: float,
        hit: Tuple[float, float, float, Collider, Any, float, float],
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate],
    ) -> Optional[Tuple[float, float, float, float, float, float]]:
        """Step a grounded body over a seam lip: up, forward, down onto ``hit``'s partner.

        ``moved`` is the body at the start of this slide, ``(rdx, rdy)`` the
        slide's motion, ``hit`` the side contact it met. The lift runs along
        the side face (a rotated tile leans; straight up would scrape it) and
        climbs ``_SEAM_STEP`` (a ceiling clips it); forward redoes the slide
        from there; the drop must land, from above, on the same partner with
        a ``"bottom"`` normal. Casts use a gate that never starts a pass.
        Returns the offset from ``moved``, the landing normal and the forward
        motion left, or None (a wall, a taller lip, a ledge, no room).
        """
        cb = hit[3]
        nx, ny = hit[1], hit[2]
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return None
        nx /= nlen
        ny /= nlen
        tx, ty = -ny, nx
        if ty < 0.0:
            tx, ty = ny, -nx
        if ty < 1e-6:
            return None
        reach = (_SEAM_STEP + _RESOLVE_SLOP) / ty
        lx, ly = tx * reach, ty * reach
        fx, fy = rdx - lx, rdy
        if fx * rdx + fy * rdy <= 0.0:
            return None
        # Cheap refusal first (a wall pressed every frame): from the full
        # lift, does the same face still block? One partner, gate-free (the
        # face is solid for this question either way).
        face = self._earliest_toi(
            _copy_translate(moved, lx, ly), fx, fy, [(cb, hit[4], 0.0, 0.0)],
        )
        if face is not None and abs(face[1]) > abs(face[2]):
            return None
        probe_gate = (
            None if gate is None
            else _QueryOnlyGate(self, ca, gate._map, gate._passing)
        )
        if type(partners) is _PartnerPool:
            still = partners.as_still()
        else:
            still = [(c, tok, 0.0, 0.0) for c, tok, _odx, _ody in partners]
        up = self._earliest_toi(moved, lx, ly, still, gate=probe_gate)
        if up is not None:
            k = max(0.0, min(1.0, up[0]) - _RESOLVE_SLOP / reach)
            lx *= k
            ly *= k
        if ly <= _RESOLVE_SLOP:
            return None
        fx = rdx - lx
        if fx * rdx + fy * rdy <= 0.0:
            return None
        fwd = self._earliest_toi(_copy_translate(moved, lx, ly), fx, fy, still, gate=probe_gate)
        px, py = lx + fx, ly + fy
        rem_x = rem_y = 0.0
        if fwd is not None:
            ft, fnx, fny = max(0.0, min(1.0, fwd[0])), fwd[1], fwd[2]
            flen = math.hypot(fnx, fny)
            if flen > 1e-12:
                fnx /= flen
                fny /= flen
            if fwd[3] is cb and abs(fnx) > abs(fny):
                return None  # the same face again: the lip is taller than the lift
            px = lx + fx * ft - fnx * _RESOLVE_SLOP
            py = ly + fy * ft - fny * _RESOLVE_SLOP
            rem_x, rem_y = fx * (1.0 - ft), fy * (1.0 - ft)
        drop = ly + _SEAM_STEP + _RESOLVE_SLOP
        down = self._earliest_toi(_copy_translate(moved, px, py), 0.0, -drop, still, gate=probe_gate)
        if down is None or down[3] is not cb:
            return None
        td = max(0.0, min(1.0, down[0]))
        if td * drop <= 1e-9:
            return None  # began inside the partner: not above its top
        lnx, lny = down[1], down[2]
        llen = math.hypot(lnx, lny)
        if llen < 1e-12:
            return None
        lnx /= llen
        lny /= llen
        if _side_from_normal(lnx, lny) != "bottom":
            return None  # a face too steep to stand on (a 60° rise is not a step)
        py -= drop * td
        return (
            px - lnx * _RESOLVE_SLOP, py - lny * _RESOLVE_SLOP,
            lnx, lny, rem_x, rem_y,
        )

    def _take_seam_step(
        self,
        ca: Collider,
        hit: Tuple[float, float, float, Collider, Any, float, float],
        step: Tuple[float, float, float, float, float, float],
        ox: float,
        oy: float,
    ) -> Tuple[float, float, Tuple[float, float]]:
        """Commit a seam step: the body stands on the partner (no side contact)."""
        px, py, lnx, lny, rem_x, rem_y = step
        cb, token = hit[3], hit[4]
        self._record_solve_contact(ca, cb, lnx, lny, 0.0)
        self._respond_velocity(ca, cb, token, lnx, lny)
        return ox + px, oy + py, (rem_x, rem_y)

    def _sweep_idle_against_partner(
        self,
        ca: Collider,
        pas: List[Prim],
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate] = None,
    ) -> bool:
        """One relative sweep when only the partner moved this frame.

        A fast floor into a body that did not ``move_by`` never enters the
        slide loop (own motion is 0). The relative TOI still has to run, or
        the pair is left to the capped settle.
        """
        hit = self._earliest_toi(pas, 0.0, 0.0, partners, relative=True, gate=gate)
        if hit is None:
            return False
        t, nx, ny, other, token, odx, ody = hit
        t = max(0.0, min(1.0, t))
        nlen = math.hypot(nx, ny)
        if nlen > 1e-12:
            nx /= nlen
            ny /= nlen
        ox = odx * (1.0 - t) - nx * _RESOLVE_SLOP
        oy = ody * (1.0 - t) - ny * _RESOLVE_SLOP
        if _SWEEP_MASS_SPLIT and nlen > 1e-12:
            gap = -(odx * nx + ody * ny) * (1.0 - t)
            if gap > 0.0 or _SWEEP_INHERIT_CLAMP:
                sx, sy = self._share_sweep_stop(ca, other, nx, ny, gap, ox, oy)
                ox += sx
                oy += sy
        self._record_solve_contact(ca, other, nx, ny, 0.0)
        self._respond_velocity(ca, other, token, nx, ny)
        self._nudge_collider(ca, ox, oy)
        return True

    def _carry_riders(
        self,
        grounded: List[Collider],
        grounded_at_start: Dict[int, bool],
    ) -> Optional[Dict[int, Tuple[Collider, float, float]]]:
        """Move each rider with the partner it stood on (PB2); the carries, or None.

        A body that ended the last step on top of a resolve partner (a
        ``"bottom"`` contact) and is not leaving it moves with that partner's
        displacement this frame, as motion: the carry joins its pose and its
        motion channel before any sweep, so its own sweep travels it (a wall
        on the platform's path stops the rider) and every relative sweep
        against the rider sees it. Collision Design, "Riders".
        """
        carries: Dict[int, Tuple[Collider, float, float]] = {}
        done: Dict[int, Tuple[float, float]] = {}
        for c in grounded:
            self._rider_carry(c, grounded_at_start, carries, done, 0)
        if not carries:
            return None
        for c in grounded:
            got = carries.get(id(c))
            if got is None:
                continue
            _carrier, cx, cy = got
            if c._motion_translation:
                c._motion_dx += cx
                c._motion_dy += cy
            else:
                c._motion_dx = cx
                c._motion_dy = cy
                c._motion_translation = True
            self._nudge_collider(c, cx, cy)
            self._snap_hot.add(c)               # the next step resets this motion
        return carries

    def _rider_carry(
        self,
        c: Collider,
        grounded_at_start: Dict[int, bool],
        carries: Dict[int, Tuple[Collider, float, float]],
        done: Dict[int, Tuple[float, float]],
        depth: int,
    ) -> Tuple[float, float]:
        """The carry of the grounded body ``c`` this frame (memoized in ``done``).

        The carrier is the first ``"bottom"`` contact of the last step whose
        partner moves. What it passes on:

        - a ``STATIC`` partner: its whole displacement (it is never blocked);
        - a movable partner with no ``.vel`` (moved by pose movers or
          ``move_by``): the part of its motion along the contact surface; the
          sweep, settle and floor snap already handle the part along the
          normal, and a blocked push or gravity step there is not travel;
        - a movable partner with ``.vel`` (a physics body): only the carry it
          rides on itself, along the surface (a stack of riders on a lift).
          Its own velocity is not a platform's motion: a crate pushed along a
          floor, or a ball falling with another, carries nothing.

        Not carried: a body leaving the partner, by the floor snap's leave
        gate (a jump, a bounce off a moving paddle).
        """
        cid = id(c)
        got = done.get(cid)
        if got is not None:
            return got
        done[cid] = (0.0, 0.0)              # a contact cycle carries nothing
        if depth > _CARRY_DEPTH:
            return done[cid]
        ident = c._identity
        contacts = getattr(ident, "_touching_contacts", None) if ident is not None else None
        if not contacts:
            return done[cid]
        for tc in contacts:
            if tc.side != "bottom":
                continue
            other = tc.other
            oc = getattr(other, "_collider", None)
            if oc is None or oc is c or not oc._in_resolve or oc._part is not None:
                continue
            omass = float(getattr(other, "mass", 1.0))
            surface = not _is_static_mass(omass)
            if not surface:
                if not oc._motion_translation:
                    continue
                ddx, ddy = oc._motion_dx, oc._motion_dy
            elif getattr(other, "_vel", None) is None:
                ddx = oc._motion_dx if oc._motion_translation else 0.0
                ddy = oc._motion_dy if oc._motion_translation else 0.0
                if grounded_at_start.get(id(oc)):
                    ux, uy = self._rider_carry(oc, grounded_at_start, carries, done, depth + 1)
                    ddx += ux
                    ddy += uy
            elif grounded_at_start.get(id(oc)):
                ddx, ddy = self._rider_carry(oc, grounded_at_start, carries, done, depth + 1)
            else:
                continue
            if ddx == 0.0 and ddy == 0.0:
                continue
            nx, ny = _vec2_components(tc.normal)
            cx, cy = ddx, ddy
            if surface:
                dn = cx * nx + cy * ny
                cx -= dn * nx
                cy -= dn * ny
                if cx * cx + cy * cy < 1e-18:
                    continue
            token = self._resolve_bounce_for(c, oc)
            if token is None:
                continue
            vel = getattr(ident, "_vel", None)
            if vel is not None:
                # The floor snap's leave gate, along last step's normal (body
                # toward partner): a body leaving the partner is not carried.
                vx, vy = _vec2_components(vel)
                ovel = getattr(other, "_vel", None)
                ovx, ovy = (0.0, 0.0) if ovel is None else _vec2_components(ovel)
                own_x = c._motion_dx if c._motion_translation else 0.0
                own_y = c._motion_dy if c._motion_translation else 0.0
                rel_dx = own_x - ddx
                rel_dy = own_y - ddy
                if _floor_snap_should_refuse(
                    leave_v=-((vx - ovx) * nx + (vy - ovy) * ny),
                    leave_d=-(rel_dx * nx + rel_dy * ny),
                    rel_motion_len=math.hypot(rel_dx, rel_dy),
                    token=token,
                ):
                    continue
            carries[cid] = (oc, cx, cy)
            done[cid] = (cx, cy)
            break
        return done[cid]

    def _share_sweep_stop(
        self, ca: Collider, cb: Collider, nx: float, ny: float, gap: float,
        ix: float = 0.0, iy: float = 0.0, at_x: float = 0.0, at_y: float = 0.0,
    ) -> Tuple[float, float]:
        """Push a movable partner by its share of a sweep stop; returns the push.

        ``gap`` is how far the pair would still close along the unit normal
        ``(nx, ny)`` (body toward partner) after the stop. The stop placed the
        body as if it absorbed all of it and the skin; the partner takes
        ``inv_b / (inv_a + inv_b)`` of both instead, and the body follows by
        the same vector, so the contact holds. A partner whose turn is still to
        come carries the push in its motion channel too: its own sweep then
        travels it (a wall behind it stops it) instead of starting past it.
        """
        if type(cb) is _GhostPartner:
            return 0.0, 0.0                 # a removed partner is pushed by nothing
        ib = cb._identity
        mb = float(getattr(ib, "mass", 1.0)) if ib is not None else 1.0
        if _is_static_mass(mb):
            return 0.0, 0.0
        ia = ca._identity
        ma = float(getattr(ia, "mass", 1.0)) if ia is not None else 1.0
        inv_b = 1.0 / mb
        if gap > 0.0:
            k = (gap + _RESOLVE_SLOP) * inv_b / (1.0 / ma + inv_b)
            k *= self._push_reach(ca, cb, nx * k, ny * k)
            if k < 0.0:
                k = 0.0
        else:
            k = 0.0                         # nothing to split: the inheritance only
        fx = nx * k                         # the body follows the push
        fy = ny * k
        if _SWEEP_INHERIT_CLAMP and self._pass_statics:
            # The body's unswept travel (the partner's leftover it inherits,
            # the skin, the follow) is swept against its own STATIC partners
            # (PE4): a light ball hit by a fast heavy one stops at the floor or
            # wall behind it, and the partner comes back by what the body
            # could not travel along the normal, so the contact holds.
            ux = ix + fx
            uy = iy + fy
            if ux or uy:
                ax, ay, cut = self._travel_to_walls(cb, ca, ux, uy, at_x, at_y)
                if cut:
                    short = (ux - ax) * nx + (uy - ay) * ny
                    fx = ax - ix
                    fy = ay - iy
                    k2 = k - short
                    if k2 > k:
                        k2 *= self._push_reach(ca, cb, nx * k2, ny * k2)
                    k = max(0.0, k2)
                    if k <= 0.0:
                        return fx, fy
        if k <= 0.0:
            return fx, fy
        sx = nx * k
        sy = ny * k
        self._push_partner(cb, sx, sy)
        return fx, fy

    def _push_partner(self, cb: Collider, sx: float, sy: float) -> None:
        """Move a partner by a solver push. A partner whose turn is still to
        come carries it in its motion channel too (``_snap_hot`` resets it next
        step): its own sweep travels it from where it started, so a wall behind
        it stops it, instead of starting past it."""
        self._nudge_collider(cb, sx, sy)
        if id(cb) not in self._swept_ids:
            if cb._motion_translation:
                cb._motion_dx += sx
                cb._motion_dy += sy
            else:
                cb._motion_dx = sx
                cb._motion_dy = sy
                cb._motion_translation = True
            self._snap_hot.add(cb)          # the next step resets this motion

    def _travel_to_walls(
        self, ca: Collider, cb: Collider, ux: float, uy: float,
        at_x: float, at_y: float,
    ) -> Tuple[float, float, bool]:
        """``cb``'s travel ``(ux, uy)`` swept against its STATIC partners: up
        to a wall, then along it (only the part into a wall is lost, so a
        rider's carry along the floor it rests on is kept), at most three
        walls. Returns the travel and whether a wall cut it."""
        tx = ty = 0.0
        rx, ry = ux, uy
        cut = False
        for _ in range(3):
            fa = self._push_reach(ca, cb, rx, ry, at_x + tx, at_y + ty)
            tx += fa * rx
            ty += fa * ry
            if fa >= 1.0:
                return tx, ty, cut
            cut = True
            rx *= 1.0 - fa
            ry *= 1.0 - fa
            wx, wy = self._push_wall_normal
            wl = math.hypot(wx, wy)
            if wl < 1e-12:
                return tx, ty, cut
            wx /= wl
            wy /= wl
            into = rx * wx + ry * wy
            if into > 0.0:
                rx -= into * wx
                ry -= into * wy
            if rx * rx + ry * ry < 1e-12:
                return tx, ty, cut
        return tx, ty, cut

    def _push_reach(
        self, ca: Collider, cb: Collider, sx: float, sy: float,
        at_x: float = 0.0, at_y: float = 0.0,
    ) -> float:
        """How much of the push ``(sx, sy)`` the partner ``cb`` travels before a
        STATIC partner of its own stops it (1.0: all of it).

        The push is swept, so a light body shoved toward a thin wall stops at
        it instead of being placed past it. Only STATIC partners clamp: a
        movable one in the way is met by ``cb``'s own sweep (it carries the
        push in its motion channel) or by settle. The pass's STATIC bodies do
        not move during it, so their boxes are tested first and ``cb``'s
        partner list is read only when one is near (a pile's inner pushes
        meet none).
        """
        statics = self._pass_statics
        if not statics:
            return 1.0
        pbs = None
        if cb._proxy_valid:
            # The proxy holds the prims: a reject on it needs no prims (most
            # pushes in a pile meet no wall).
            p = cb._proxy
            box = (p[0] + at_x, p[1] + at_y, p[2] + at_x, p[3] + at_y)
        else:
            pbs = self._world_prims(cb)
            if not pbs:
                return 1.0
            if at_x or at_y:
                pbs = _copy_translate(pbs, at_x, at_y)
            box = (min(q.aabb[0] for q in pbs), min(q.aabb[1] for q in pbs),
                   max(q.aabb[2] for q in pbs), max(q.aabb[3] for q in pbs))
        x0, y0, x1, y1 = _swept_aabb(box, sx, sy)
        rows = self._pass_static_rows
        if rows is None and len(statics) >= _POOL_VECTOR_MIN:
            idx = self._collider_index
            try:
                rows = np.fromiter((idx[id(c)] for c in statics), dtype=np.intp,
                                   count=len(statics))
            except KeyError:
                rows = False                # not all on the mirror: scan them
            self._pass_static_rows = rows
        if rows is None or rows is False:
            near = []
            for c in statics:
                pb = c._proxy
                if not (pb[0] > x1 or x0 > pb[2] or pb[1] > y1 or y0 > pb[3]):
                    near.append(c)
        else:
            near = [statics[i] for i in _rows_meeting(self._box_array(), rows, 0, x0, y0, x1, y1)]
        if not near:
            return 1.0
        members = self._pass_members.get(id(cb))
        if members is None:
            # ``cb``'s partners do not change during the pass: read once.
            pool = self._resolve_pool(cb)
            if type(pool) is _PartnerPool:
                members = pool.members
            else:
                members = {id(c) for c, _tok, _odx, _ody in pool}
            self._pass_members[id(cb)] = members
        walls = [(c, None, 0.0, 0.0) for c in near if c is not ca and id(c) in members]
        if not walls:
            return 1.0
        if pbs is None:
            pbs = self._world_prims(cb)
            if not pbs:
                return 1.0
            if at_x or at_y:
                # ``cb`` is the body in its turn: the sweep has not placed it yet.
                pbs = _copy_translate(pbs, at_x, at_y)
        gate = None
        if self._has_only:
            only_map = self._resolve_only_map(cb)
            if only_map is not None:
                gate = _QueryOnlyGate(self, cb, only_map, self._passing.get(id(cb), {}))
        hit = self._earliest_toi(pbs, sx, sy, walls, gate=gate)
        if hit is None:
            return 1.0
        dist = math.hypot(sx, sy)
        if dist < 1e-12:
            return 1.0
        self._push_wall_normal = (hit[1], hit[2])
        return max(0.0, min(1.0, hit[0]) - _RESOLVE_SLOP / dist)

    def _settle_normal(
        self,
        ca: Collider,
        cb: Collider,
        info: CollisionInfo,
    ) -> Tuple[float, float]:
        nx, ny = _normal_components(info.normal)
        if id(ca) > id(cb):
            nx, ny = -nx, -ny
        key = self._pair_key(ca, cb)
        mem = self._contact_memory.get(key)
        if mem is not None:
            mx, my = mem
            if id(ca) > id(cb):
                mx, my = -mx, -my
            return mx, my
        if not _SETTLE_MIN_OVERLAP:
            ia = ca._identity
            ib = cb._identity
            va = getattr(ia, "_vel", None) if ia is not None else None
            vb = getattr(ib, "_vel", None) if ib is not None else None
            vax, vay = (0.0, 0.0) if va is None else _vec2_components(va)
            vbx, vby = (0.0, 0.0) if vb is None else _vec2_components(vb)
            vn = (vax - vbx) * nx + (vay - vby) * ny
            if vn < 0.0:
                nx, ny = -nx, -ny
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return 0.0, 1.0
        return nx / nlen, ny / nlen

    def _exact_bounds_aabb(
        self, collider: Collider
    ) -> Optional[Tuple[float, float, float, float]]:
        """Collision-prim AABB for unswept recovery.

        The broad-phase proxy for a sprite is its local extent box turned by
        the heading. It extends past the hitbox, so a side correction (motion no longer
        matches the box) would otherwise pull the body onto a shape the
        hitbox does not touch.
        """
        exact = _prims_bounds_aabb(self._world_prims(collider))
        if exact is not None:
            return exact
        return _unpadded_proxy_aabb(collider)

    def _store_resolved_aabbs(self) -> None:
        """Remember collision bounds for next frame's unswept recovery.

        Only ``resolve()`` bodies and partners read them. Everyone else stays
        lazy: world prims are built only for overlapping pairs. A collider that
        joins resolve has no history for one frame, the same as spawn.
        """
        for c in self._colliders:
            if c._in_resolve:
                key = c._proxy_key
                if (_STEP_SKIP_STILL and key is not None and c._resolved_key is key
                        and c._resolved_aabb is not None):
                    continue                    # still body: same pose, same box
                c._resolved_aabb = self._exact_bounds_aabb(c)
                c._resolved_key = c._proxy_key
            elif c._resolved_aabb is not None:
                c._resolved_aabb = None
                c._resolved_key = None

    def _nudge_pair_along(
        self,
        ca: Collider,
        cb: Collider,
        nx: float,
        ny: float,
        corr: float,
    ) -> None:
        """Split ``corr`` along ``n`` (from ``ca`` toward ``cb``) by inverse mass.

        Between two movable bodies, neither share may carry its body into a
        ``STATIC`` partner of its own (PE3, the settle counterpart of
        ``_push_reach``): a share that would is cut where the wall stops it,
        and the other body takes the rest of the correction, up to its own
        wall. A crate under a heavy crate is not pressed into the floor; a body
        squeezed between two walls keeps the overlap (no share can move).
        """
        ia = ca._identity
        ib = cb._identity
        ma = float(getattr(ia, "mass", 1.0)) if ia is not None else 1.0
        mb = float(getattr(ib, "mass", 1.0)) if ib is not None else 1.0
        a_inf = _is_static_mass(ma)
        b_inf = _is_static_mass(mb)
        if b_inf and not a_inf:
            self._nudge_collider(ca, -nx * corr, -ny * corr)
        elif a_inf and not b_inf:
            self._nudge_collider(cb, nx * corr, ny * corr)
        elif not a_inf and not b_inf:
            inv_a = 1.0 / ma
            inv_b = 1.0 / mb
            total = inv_a + inv_b
            da = corr * inv_a / total
            db = corr * inv_b / total
            if not _SETTLE_STATIC_CLAMP:
                self._nudge_collider(ca, -nx * da, -ny * da)
                self._nudge_collider(cb, nx * db, ny * db)
                return
            # A partner whose turn is still to come carries its share in its
            # motion channel: its own sweep travels it from where it started,
            # against its walls. Placed, it moved that start (into a floor).
            later = id(cb) not in self._swept_ids
            if self._pass_statics:
                ra = corr * self._push_reach(cb, ca, -nx * corr, -ny * corr)
                rb = corr if later else corr * self._push_reach(ca, cb, nx * corr, ny * corr)
                if da > ra:
                    da = ra
                    db = min(corr - da, rb)
                elif db > rb:
                    db = rb
                    da = min(corr - db, ra)
            self._nudge_collider(ca, -nx * da, -ny * da)
            if later:
                self._push_partner(cb, nx * db, ny * db)
            else:
                self._nudge_collider(cb, nx * db, ny * db)

    def _recover_unswept_bounds(
        self,
        ca: Collider,
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate] = None,
    ) -> None:
        """Pull a bounds change back across the face it crossed.

        Runs only when the pair's last resolved bounds were clear, the current
        collision-prim bounds overlap, the prims themselves overlap, and this
        frame's motion channel does not already explain the body's box. The
        broad-phase proxy and a rotated body's bounding box are not
        enough. Spawn, an already-overlapping pair, a partner placed into a
        body that only translated, and a hit the sweep stopped stay on the
        capped settle loop.
        """
        prev_a = ca._resolved_aabb
        if prev_a is None:
            return
        # Partners are the whole declared pool (every ball for ball×ball), so
        # the stored-box and proxy rejects run before any prim bounds. Prims
        # sit inside the proxy (``_nudge_collider`` keeps it synced), so a
        # disjoint proxy pair cannot pass the prim-overlap test below.
        curr_a: Optional[Tuple[float, float, float, float]] = None
        for cb, token, _odx, _ody in self._iter_near(ca, partners):
            if not _proxy_aabb_overlap(ca, cb):
                continue
            prev_b = cb._resolved_aabb
            if prev_b is None or _aabb_overlaps_box(prev_a, prev_b):
                continue
            key = self._pair_key(ca, cb)
            if key in self._solve_contacts:
                continue
            if curr_a is None:
                curr_a = self._exact_bounds_aabb(ca)
                if curr_a is None:
                    return
            curr_b = self._exact_bounds_aabb(cb)
            if curr_b is None:
                continue
            if not _aabb_overlaps_box(curr_a, curr_b):
                continue
            if _aabb_matches_motion(prev_a, curr_a, ca._motion_dx, ca._motion_dy):
                continue
            # Prim AABBs of a rotated body are fatter than the body. A wall
            # slide whose pose no longer matches the motion channel must not
            # treat that empty corner as a floor.
            if self._collision_info_for_colliders(ca, cb) is None:
                continue
            entered = _aabb_entry_normal(prev_a, curr_a, prev_b, curr_b)
            if entered is None:
                continue
            nx, ny = entered
            if gate is not None and not gate.ok(cb, nx, ny):
                gate.mark(cb)
                continue
            pas = self._world_prims(ca)
            pbs = self._world_prims(cb)
            gap = _prims_penetration(pas, pbs, nx, ny)
            if gap <= 0.0:
                continue
            self._nudge_pair_along(ca, cb, nx, ny, gap + _RESOLVE_SLOP)
            curr_a = None
            self._record_solve_contact(ca, cb, nx, ny, gap)
            if token is not _RESOLVE_POSITION_ONLY:
                self._respond_velocity(ca, cb, token, nx, ny)

    def _settle_body(
        self,
        ca: Collider,
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate] = None,
    ) -> None:
        self._recover_unswept_bounds(ca, partners, gate)
        for _ in range(_SETTLE_ITERS):
            deepest: Optional[Tuple[Collider, Any, CollisionInfo, float, float, float]] = None
            for cb, token, _odx, _ody in self._iter_near(ca, partners):
                if not _proxy_aabb_overlap(ca, cb):
                    continue
                info = self._collision_info_for_colliders(ca, cb)
                if info is None:
                    continue
                nx, ny = self._settle_normal(ca, cb, info)
                if gate is not None and not gate.ok(cb, nx, ny, info.points):
                    # An overlap this pair may not push out: pass through.
                    gate.mark(cb)
                    continue
                depth = float(info.depth) - _RESOLVE_SLOP
                if deepest is None or float(info.depth) > deepest[2].depth:
                    deepest = (cb, token, info, nx, ny, depth)
            if deepest is None:
                break
            cb, token, info, nx, ny, depth = deepest
            key = self._pair_key(ca, cb)
            had_contact = key in self._solve_contacts
            if depth > 0.0:
                corr = min(_SETTLE_BIAS * depth, _SETTLE_MAX)
                self._nudge_pair_along(ca, cb, nx, ny, corr)
            self._record_solve_contact(
                ca, cb, nx, ny, max(0.0, float(info.depth)), points=list(info.points),
            )
            if not had_contact and token is not _RESOLVE_POSITION_ONLY:
                self._respond_velocity(ca, cb, token, nx, ny)
            if depth <= 0.0:
                break

    def _floor_snap(
        self,
        ca: Collider,
        partners: Sequence[Tuple[Collider, Any, float, float]],
        gate: Optional[_OnlyGate] = None,
    ) -> None:
        ident = ca._identity
        if ident is None:
            return
        # Sweep/settle already recorded a bottom contact for this body.
        if self._solve_bottom_count.get(id(ca), 0) > 0:
            return
        snap = max(_FLOOR_SNAP_MIN, abs(min(0.0, ca._motion_dy)) + 8.0)
        pas = self._world_prims(ca)
        hit = self._earliest_toi(pas, 0.0, -snap, partners, gate=gate)
        if hit is None:
            return
        t, nx, ny, other, token, _odx, _ody = hit
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return
        nx /= nlen
        ny /= nlen
        if _side_from_normal(nx, ny) != "bottom":
            return
        # Leave gate: relative velocity and this frame's relative displacement
        # along the contact normal. Flat floors reduce speed to ``vy - ovy``;
        # ramps ignore tangential climb. Walkers cannot trust speed alone —
        # world-axis ``vel.x`` on a slope looks like tens of DU/s of leave
        # while motion barely separates; snap must still heal short-frame
        # ``_RESOLVE_SLOP`` gaps (closing them takes g·dt², which fails under
        # ~9 ms). Elastic pairs (``bounce > 0.5``) trust ``leave_v``: the
        # impulse already wrote an honest separating velocity, and a 2 DU
        # ``leave_d`` conjunct glues bounces at high FPS.
        vel = getattr(ident, "_vel", None)
        if vel is not None:
            vx, vy = _vec2_components(vel)
            oident = other._identity
            ovel = getattr(oident, "_vel", None) if oident is not None else None
            ovx, ovy = (0.0, 0.0) if ovel is None else _vec2_components(ovel)
            # ``(nx, ny)`` points from body toward other (down into a floor);
            # leaving is motion opposite that normal.
            rel_dx = ca._motion_dx - _odx
            rel_dy = ca._motion_dy - _ody
            leave_v = -((vx - ovx) * nx + (vy - ovy) * ny)
            leave_d = -(rel_dx * nx + rel_dy * ny)
            if leave_v > _FLOOR_SNAP_LEAVE_VY and (
                    id(ca) in self._bounced_prev or id(ca) in self._bounced_now):
                return      # a bounce just sent it off: leaving at any rate (R2-1)
            if _floor_snap_should_refuse(
                leave_v=leave_v,
                leave_d=leave_d,
                rel_motion_len=math.hypot(rel_dx, rel_dy),
                token=token,
            ):
                return
        t = max(0.0, min(1.0, t))
        # The snap is a straight drop: the skin is taken back up it (PE2).
        bx, by = _skin_back_off(nx, ny, 0.0, -1.0, True)
        self._nudge_collider(ca, bx, -snap * t + by)
        self._record_solve_contact(ca, other, nx, ny, 0.0)
        self._respond_velocity(ca, other, token, nx, ny)

    def _update_touching_state(
        self,
        current: Dict[Tuple[int, int], CollisionInfo],
        id_to_collider: Dict[int, Collider],
    ) -> None:
        from .entity import Graphic

        per_collider: Dict[int, List[Tuple[Any, CollisionInfo]]] = {}
        for key, info in current.items():
            ca = id_to_collider.get(key[0])
            cb = id_to_collider.get(key[1])
            if ca is None or cb is None:
                continue
            if self._resolve_bounce_for(ca, cb) is None:
                continue
            for me_c, other_c in ((ca, cb), (cb, ca)):
                oriented = self._oriented_info(me_c, other_c, ca, info, _PHASE_STAY)
                per_collider.setdefault(id(me_c), []).append((other_c._identity, oriented))

        if not per_collider and not self._touching_published:
            return

        published = False
        if _STEP_SKIP_STILL:
            # Only bodies touching now or at the last publish: every other one
            # already reads empty, and writing empty again changes nothing.
            # Collider order, as the full walk (an anchored field notifies).
            idx = self._collider_index
            targets = dict(self._touching_live)
            for cid in per_collider:
                c = id_to_collider.get(cid)
                if c is not None:
                    targets[cid] = c
            visit = sorted((c for cid, c in targets.items() if cid in idx),
                           key=lambda c: idx[id(c)])
        else:
            visit = self._colliders
        live: Dict[int, Collider] = {}
        for c in visit:
            if c._part is not None:
                # A part shares its host's identity; it must not overwrite
                # the body's ``touching_*`` (parts never resolve).
                continue
            ident = c._identity
            if not isinstance(ident, Graphic):
                continue
            raw = per_collider.get(id(c), [])
            sides = frozenset(
                oinfo.side for _other, oinfo in raw if oinfo.side is not None
            )
            contacts = tuple(
                TouchingContact(
                    other=other,
                    side=oinfo.side,
                    slope_angle=oinfo.slope_angle,
                    normal=oinfo.normal,
                    tangent=oinfo.tangent,
                    point=oinfo.point,
                )
                for other, oinfo in raw
            )
            ident._collision_set_touching(sides, contacts)
            if sides or contacts:
                published = True
                live[id(c)] = c
        self._touching_published = published
        self._touching_live = live

    def _collision_info_for_colliders(
        self,
        ca: Collider,
        cb: Collider,
    ) -> Optional[CollisionInfo]:
        pas = self._world_prims(ca)
        pbs = self._world_prims(cb)
        best: Optional[CollisionInfo] = None
        best_depth = -1.0
        for pa in pas:
            for pb in pbs:
                if not _aabb_overlap_tuple(pa.aabb, pb.aabb):
                    continue
                contact = narrow_phase(pa, pb)
                if contact is None:
                    continue
                info = _collision_info_from_contact(ca, cb, contact, pas, pbs)
                if info.depth > best_depth:
                    best_depth = info.depth
                    best = info
        return best

    def test_collision(self, a, b) -> Optional[CollisionInfo]:
        """One-shot narrow-phase test between two targets.

        A shape that is not already enrolled is tested with a temporary probe
        and is not registered as a collider.
        """
        lefts = self._colliders_for_query(a)
        rights = self._colliders_for_query(b)
        best: Optional[CollisionInfo] = None
        best_pair = None
        best_depth = -1.0
        for ca in lefts:
            self._update_proxy(ca, commit_motion=False)
            for cb in rights:
                self._update_proxy(cb, commit_motion=False)
                info = self._collision_info_for_colliders(ca, cb)
                if info is not None and info.depth > best_depth:
                    best_depth = info.depth
                    best = info
                    best_pair = (ca, cb)
        if best is None:
            return None
        # The author's view, as a handler gets it (PM11): a / b are the bodies,
        # the normal points from a to b. The raw info is in canonical order
        # (lower id first, ``_collision_info_from_contact``); a body that is
        # not enrolled was probed through a throwaway Collider whose identity
        # is the probe, so name the body it stands for.
        ca, cb = best_pair
        first = ca if best.a is ca._identity else cb
        oriented = self._oriented_info(ca, cb, first, best, _PHASE_ENTER)
        return replace(oriented, a=self._query_body(ca, a), b=self._query_body(cb, b))

    @staticmethod
    def _query_body(collider: Collider, target):
        """The author object a query collider answers for."""
        ident = collider._identity
        return target if ident is collider and target is not collider \
            and getattr(target, "_collider", None) is not collider else ident

    def _colliders_for_query(self, target) -> List[Collider]:
        """Colliders for a query. Bare shapes that are not enrolled stay ephemeral."""
        if isinstance(target, Collider):
            return [target] if any(self._item_in_play(s) for s in target.shapes) else []
        from .entity import Entity
        if isinstance(target, Entity):
            if not self._item_in_play(target):
                return []
            _assert_shapes_not_parallax([target])
            existing = getattr(target, "_collider", None)
            if existing is not None:
                return [existing]
            return [Collider([target], _register=False, _bind=False)]
        return list(self._enroll_target_now(target))

    def _part_target_colliders(self, part) -> List[Collider]:
        """A ``Hitbox`` named as a side: its collider while it is in play."""
        if not part.is_alive:
            self._warn_dead_object_target(part)
            return []
        if not self._item_in_play(part):
            return []
        _assert_shapes_not_parallax([part])
        return [ensure_collider(part)]

    def _colliders_for_target(self, target) -> List[Collider]:
        if isinstance(target, Collider):
            return [target] if any(self._item_in_play(s) for s in target.shapes) else []
        if _is_part_side(target):
            return self._part_target_colliders(target)
        from .entity import Entity
        if isinstance(target, Entity):
            if not self._item_in_play(target):
                return []
            _assert_shapes_not_parallax([target])
            return [ensure_collider(target)]
        return list(self._enroll_target_now(target))

    def _refresh_live_colliders(self, *, bodies_only: bool = False) -> List[Collider]:
        """Current colliders with proxies refreshed and motion left pending.

        ``bodies_only`` leaves hitbox parts out (queries with no group).
        """
        out: List[Collider] = []
        for c in list(self._colliders):
            if bodies_only and c._part is not None:
                continue
            if self._update_proxy(c, commit_motion=False):
                out.append(c)
        return out

    def _drop_query_collider(self, item) -> None:
        if item is not None:
            self._query_colliders.pop(item, None)

    def _members_named(self, tag: str) -> List[Any]:
        """Live members of ``tag``, including a formula group of that name."""
        try:
            from .canvas import ScenaCanvas
            registry = ScenaCanvas.get_current().registry
        except Exception:
            return []
        if registry.has_group_formula(tag):
            return registry.eval_group_formula(tag)
        return registry.list_by_groupid(tag)

    def _fast_tag_colliders(self, tag: str) -> Optional[List[Collider]]:
        """Declared-tag index, or None when the member walk must run.

        ``_tag_colliders`` is the broad-phase index for pair tags. It matches
        group membership only after ``@collide`` / ``resolve`` enrolled the
        tag, and never for a formula name (those members are not tagged with
        the formula's name).
        """
        if tag not in self._pair_tags:
            return None
        try:
            from .canvas import ScenaCanvas
            registry = ScenaCanvas.get_current().registry
            if registry.has_group_formula(tag):
                return None
        except Exception:
            return None
        return list(self._tag_colliders.get(tag) or ())

    def _query_collider(self, item, tag: Optional[str]) -> Optional[Collider]:
        """Collider that answers for ``item`` in a named query. No enrollment.

        Reuses a registered collider. Otherwise a cached unregistered one
        (``_register=False``, ``_bind=False``) so the query does not opt the
        item into ``ANYTHING`` or ``step()``.
        """
        if isinstance(tag, str):
            _refresh_part_link(item, tag)
            routed = _tag_item(item, tag)
        else:
            routed = item
        if routed is None:
            return None
        if not self._item_in_play(routed):
            self._drop_query_collider(routed)
            return None
        if not _on_collision_layer(routed) or not _has_query_geometry(routed):
            return None
        existing = getattr(routed, "_collider", None)
        if existing is not None:
            self._drop_query_collider(routed)
            return existing
        cached = self._query_colliders.get(routed)
        if cached is not None:
            return cached
        if getattr(type(routed), "_is_hitbox_part", False):
            host_ref = getattr(routed, "_host_ref", None)
            host = host_ref() if callable(host_ref) else None
            if host is None:
                return None
            made = Collider(
                [routed], _identity_shape=host, _register=False, _bind=False,
            )
            made._part = routed
        else:
            made = Collider(
                [routed], _identity_shape=routed, _register=False, _bind=False,
            )
        bake = getattr(routed, "_ensure_auto_baked", None)
        if callable(bake):
            bake()
        self._query_colliders[routed] = made
        return made

    def _colliders_for_members(self, tag: Optional[str], members) -> List[Collider]:
        out: List[Collider] = []
        for member in members:
            collider = self._query_collider(member, tag)
            if collider is not None:
                out.append(collider)
        return out

    def _colliders_for_query_atom(self, atom) -> List[Collider]:
        if atom is ANYTHING:
            return self._refresh_live_colliders(bodies_only=True)
        if isinstance(atom, str):
            fast = self._fast_tag_colliders(atom)
            if fast is not None:
                return fast
            return self._colliders_for_members(atom, self._members_named(atom))
        from .registry import GroupOperator
        if isinstance(atom, GroupOperator):
            if atom._formula_name is not None:
                return self._colliders_for_members(atom._formula_name, list(atom))
            if atom._group_id is not None:
                fast = self._fast_tag_colliders(atom._group_id)
                if fast is not None:
                    return fast
                return self._colliders_for_members(atom._group_id, list(atom))
            return self._colliders_for_members(None, list(atom))
        return list(self._resolve_target_to_colliders(atom))

    # --- moved set and vectorized candidates (B2) ---------------------------

    def _snapshot_moved(self, stale: Set["Collider"]) -> None:
        """The step's proxy refresh, O(moved): every collider that can differ
        from its last refresh, in collider order. The rest already match their
        pose (the revision invariant) and have no motion to commit or reset.

        Verify mode refreshes the rest too and raises if one changed.
        """
        idx = self._collider_index
        visit = set(stale)
        visit |= self._snap_hot
        visit |= self._untrusted
        visit |= self._timed
        visit |= self._unbound
        visit.update(self._multi_bodies.values())
        self._snap_hot = set()                  # commits below refill it
        order = sorted((c for c in visit if id(c) in idx), key=lambda c: idx[id(c)])
        for c in order:
            self._update_proxy(c)
        self._moved_now.update(order)
        if _POSE_REV_VERIFY:
            for c in self._colliders:
                if c in visit:
                    continue
                before = (list(c._proxy), c._proxy_valid, c._motion_dx, c._motion_dy,
                          c._motion_path, c._proxy_start, c._proxy_key)
                self._update_proxy(c)
                after = (list(c._proxy), c._proxy_valid, c._motion_dx, c._motion_dy,
                         c._motion_path, c._proxy_start, c._proxy_key)
                if after != before:
                    raise AssertionError(
                        f"step snapshot skipped {c!r}, whose refresh changed "
                        f"{before} -> {after}: a pose or motion writer did not mark it"
                    )

    def _drain_pose_cells(self) -> None:
        """Move the bumped revision cells into ``_stale`` (their colliders)."""
        cells = DIRTY_POSE_CELLS
        if not cells:
            return
        stale = self._stale
        for cell in cells:
            cell[1] = False
            ref = cell[2]
            root = ref() if ref is not None else None
            if root is None:
                continue
            col = probe_private(root, "_collider", None)
            if col is not None:
                stale.add(col)
            parts = probe_private(root, "_hitbox_parts", None)
            if parts:
                for part in parts:
                    pc = probe_private(part, "_collider", None)
                    if pc is not None:
                        stale.add(pc)
        cells.clear()

    def _fresh_proxies(self, members: Optional[Set[int]] = None) -> None:
        """Between steps: make registered proxies match their pose, touching
        only what moved (``_stale``), what can change with no write
        (``_untrusted``, and ``_timed``: a "clip" hitbox rebakes when time
        switches the clip), what no revision cell reaches (``_unbound``) and
        compound bodies.

        ``members`` (collider ids): only those, for a query that reads no
        other row; the other moved colliders stay in ``_stale`` for the next
        query (``step()`` refreshes every proxy).
        """
        self._drain_pose_cells()
        idx = self._collider_index
        if self._stale:
            if members is None:
                for c in self._stale:
                    if id(c) in idx:
                        self._update_proxy(c, commit_motion=False)
                self._stale.clear()
            else:
                done = [c for c in self._stale if id(c) in members]
                for c in done:
                    if id(c) in idx:
                        self._update_proxy(c, commit_motion=False)
                self._stale.difference_update(done)
        for always in (self._untrusted, self._timed, self._unbound):
            if not always:
                continue
            for c in list(always):
                if members is not None and id(c) not in members:
                    continue
                if id(c) in idx:
                    self._update_proxy(c, commit_motion=False)
                else:
                    always.discard(c)
        for c in list(self._multi_bodies.values()):
            if members is None or id(c) in members:
                self._update_proxy(c, commit_motion=False)

    def _box_array(self):
        """numpy ``(n, 10)``, column-major (``_mirror_row``), row ``i`` =
        ``_colliders[i]``. Every writer of a proxy or a motion marks
        ``_row_dirty``."""
        if self._boxes is None or self._boxes_version != self._struct_version:
            cols = self._colliders
            self._boxes = np.array(
                [_mirror_row(c) for c in cols], dtype=float, order="F",
            ).reshape((len(cols), 10), order="F")
            self._boxes_version = self._struct_version
            self._row_dirty.clear()
        elif self._row_dirty:
            b = self._boxes
            idx = self._collider_index
            for c in self._row_dirty:
                i = idx.get(id(c))
                if i is not None:
                    b[i] = _mirror_row(c)
            self._row_dirty.clear()
        return self._boxes

    def _group_rows(self, group: Any):
        """``(candidates, rows, member ids)`` for a query group of declared
        pair tags, or None when the group is not such an index (the Python
        walk runs).

        Same candidates, in the same order, as ``_candidates_for_group``.
        """
        atoms = _parse_query_group(group)
        if atoms is None:
            return None
        tags = []
        for atom in atoms:
            if isinstance(atom, str):
                tag = atom
            else:
                from .registry import GroupOperator
                if (not isinstance(atom, GroupOperator) or atom._formula_name is not None
                        or atom._group_id is None):
                    return None
                tag = atom._group_id
            if tag not in self._pair_tags:
                return None
            tags.append(tag)
        try:
            from .canvas import ScenaCanvas
            registry = ScenaCanvas.get_current().registry
            if any(registry.has_group_formula(t) for t in tags):
                return None
        except Exception:
            return None
        return self._group_rows_members(tags)

    def _group_rows_members(self, tags):
        """``(candidates, rows, member ids)`` for declared pair tags, cached
        per ``(_struct_version, _tag_version)``; None if a member has no row."""
        key = tuple(tags)
        ver = (self._struct_version, self._tag_version)
        hit = self._group_rows_cache.get(key)
        if hit is not None and hit[0] == ver:
            return hit[1], hit[2], hit[3]
        seen: Set[int] = set()
        cands: List[Collider] = []
        for t in tags:
            for c in self._tag_colliders.get(t) or ():
                cid = id(c)
                if cid not in seen:
                    seen.add(cid)
                    cands.append(c)
        idx = self._collider_index
        try:
            rows = np.fromiter((idx[id(c)] for c in cands), dtype=np.intp, count=len(cands))
        except KeyError:
            return None
        self._group_rows_cache[key] = (ver, cands, rows, seen)
        return cands, rows, seen

    def _candidates_in_box(self, group: Any, box) -> Optional[List[Collider]]:
        """The group's candidates whose fresh proxy meets ``box``, or None
        (the group is not an index: the caller walks it)."""
        got = self._group_rows(group) if _QUERY_VECTOR else None
        if got is None:
            return None
        cands, rows, members = got
        if _linked_parts():
            from .hitbox import _refresh_linked_parts
            _refresh_linked_parts()
        self._fresh_proxies(members)
        if not cands:
            return []
        return [cands[i] for i in _rows_meeting(self._box_array(), rows, 0, *box)]

    def _candidates_for_group(self, group: Any) -> List[Collider]:
        """Colliders a query should test.

        ``None`` / ``ANYTHING`` is the enrolled collision world (bodies only).
        A tag or ``group['name']`` is that group's in-play members, whether
        or not ``@collide`` / ``resolve`` declared the tag. Naming a group
        does not enroll anyone.
        """
        # A linked ``hb["active"]`` is polled: the step reads it at its start,
        # and a query in ``update()`` after the formula changed hit a hitbox
        # it had turned off (review 2026-10-09 W-G2; Reactive Design).
        if _linked_parts():
            from .hitbox import _refresh_linked_parts
            _refresh_linked_parts()
        atoms = _parse_query_group(group)
        if atoms is None:
            return self._refresh_live_colliders(bodies_only=True)
        seen: Set[int] = set()
        candidates: List[Collider] = []
        for atom in atoms:
            for collider in self._colliders_for_query_atom(atom):
                cid = id(collider)
                if cid not in seen:
                    seen.add(cid)
                    candidates.append(collider)
        return candidates

    def query_shape(self, shape, group: Any = None) -> List[Any]:
        """Return identities overlapping ``shape``'s current geometry.

        ``group=`` omitted (or ``ANYTHING``) is the enrolled collision world.
        A tag or a collection of tags (list, tuple, set) tests that group's
        members and does not enroll them. The probe itself is not a hit.
        """
        if not self._item_in_play(shape):
            return []
        _assert_shapes_not_parallax([shape])
        existing = getattr(shape, "_collider", None)
        probe = existing if existing is not None else Collider(
            [shape], _register=False, _bind=False,
        )
        self._update_proxy(probe, commit_motion=False)
        candidates = self._candidates_for_group(group)
        hits: List[Any] = []
        seen_hit: Set[int] = set()
        for cb in candidates:
            # Skip this body and its own hitbox parts. A named query builds a
            # separate unregistered collider, so identity — not ``is probe`` —
            # is what makes the probe not count as a hit against itself.
            if cb is probe or cb._identity is shape:
                continue
            # Nor a body the probe is a piece of (AC10: the boss does not
            # overlap its own torso).
            if _is_multi_body(cb) and any(r() is shape for r in cb._shapes):
                continue
            if not self._update_proxy(cb, commit_motion=False):
                continue
            # Proxies contain their prims and the test is inclusive: a pair
            # whose boxes miss cannot touch.
            if _QUERY_SHAPE_REJECT and not _proxy_aabb_overlap(probe, cb):
                continue
            info = self._collision_info_for_colliders(probe, cb)
            if info is None:
                continue
            hid = id(cb)
            if hid in seen_hit:
                continue
            seen_hit.add(hid)
            hits.append(cb)
        return _bodies_first(hits)

    def floor_below(
        self, body, *, dx: Any = 0.0, depth: Any = None, group: Any = None,
    ) -> Optional[Any]:
        """The floor ``body`` would stand on after stepping ``dx``, or None.

        One question, asked with the solver's own rules: ``body``'s collision
        prims (not its drawn box), a floor is a ``"bottom"`` contact (±45°,
        same as ``touching_sides``), and a drop deeper than ``depth`` is a
        fall (default: the floor-snap reach). The step marches in sub-steps
        of at most ``_FLOOR_PROBE_STEP``: lift (a 45° rise; a ceiling clips
        it), across (a wall stops the march — the answer is the floor there),
        drop. Every sub-step must find a floor within ``depth``.

        Ground is ``body``'s standing ``resolve()`` partners (``only=`` gates
        included), or ``group=`` when given (same grammar as ``query_shape``;
        hitbox parts are never floors). Reads the live pose; consumes no
        motion; enrolls nothing.
        """
        dx = _number(dx, "floor_below(dx=)")
        reach = (
            _FLOOR_SNAP_MIN if depth is None
            else _fixed_magnitude(depth, "floor_below(depth=)")
        )
        if not self._item_in_play(body):
            return None
        _assert_shapes_not_parallax([body])
        existing = getattr(body, "_collider", None)
        in_resolve = existing is not None and self._collider_in_resolve(existing)
        if group is None:
            if not in_resolve:
                from .entity import entity_label
                label = entity_label(body)
                raise ValueError(
                    f"{label}.floor_below() has no ground to look for: {label} is "
                    "in no resolve() pair. Pair it with its ground — "
                    "resolve(hero, \"ground\") — or name the ground: "
                    "floor_below(group=\"ground\")."
                )
            probe = existing
            self._update_proxy(probe, commit_motion=False)
            pool = None
            if _FLOOR_PROBE_FAST:
                rp = self._resolve_pool(probe)
                if type(rp) is _PartnerPool:
                    pool = self._floor_pool_from_partners(probe, rp, dx, reach)
            if pool is None:
                pool = [(c, tok) for c, tok in self._resolve_partner_idents(probe)]
        else:
            probe = existing if existing is not None else Collider(
                [body], _register=False, _bind=False,
            )
            self._update_proxy(probe, commit_motion=False)
            if in_resolve:
                self._resolve_partner_idents(existing)  # fills the only= cache
            pool = None
            if _FLOOR_PROBE_FAST:
                pool = self._floor_pool_near(body, probe, group, dx, reach)
            if pool is None:
                pool = []
                for cb in self._candidates_for_group(group):
                    if cb is probe or cb._part is not None or cb._identity is body:
                        continue
                    pool.append((cb, None))
        partners: List[Tuple[Collider, Any, float, float]] = []
        for cb, tok in pool:
            if self._update_proxy(cb, commit_motion=False):
                partners.append((cb, tok, 0.0, 0.0))
        if not partners and getattr(pool, "has_others", False):
            # The group has ground, none near: march anyway (the end pose the
            # debug draw shows is the march's, as on the Python walk).
            partners = _EMPTY_MARCH
        gate: Optional[_OnlyGate] = None
        if in_resolve and self._has_only:
            only_map = self._resolve_only_map(existing)
            if only_map:
                passing = self._passing.get(id(existing)) or {}
                gate = _QueryOnlyGate(self, existing, only_map, passing)
        pas = list(self._world_prims(probe))
        if not pas or (not partners and partners is not _EMPTY_MARCH):
            self._note_floor_probe(body, pas, False)
            return None

        step_max = min(_FLOOR_PROBE_STEP, max(reach, 1.0))
        if partners is _EMPTY_MARCH:
            partners = []
        fast = _FLOOR_PROBE_FAST
        if fast:
            # Every partner proxy was refreshed above and nothing moves a body
            # until this call returns: reject on the whole march once, and let
            # the casts reuse world prims (the narrow / resolve window).
            ex0, ey0, ex1, ey1 = _floor_probe_envelope(pas, dx, step_max, reach)
            kept = []
            for item in partners:
                pb = item[0]._proxy
                if pb[0] > ex1 or ex0 > pb[2] or pb[1] > ey1 or ey0 > pb[3]:
                    continue
                kept.append(item)
            partners = kept       # may be empty: the march still runs (its end pose)
            trust_before = self._trust_proxy_world
            self._trust_proxy_world = True
        try:
            return self._floor_march(body, pas, partners, gate, dx, reach, step_max)
        finally:
            if fast:
                self._trust_proxy_world = trust_before

    def _floor_pool_from_partners(self, probe, rp, dx, reach):
        """``floor_below()`` ground near the march from ``probe``'s resolve
        partners (a ``_PartnerPool``): fresh proxies, then the mirror rows
        that meet the march envelope. None when the probe has no prims.

        ``has_others``: some partner has a proxy, so an empty pool still
        marches (its end pose), as on the Python walk.
        """
        pas = self._world_prims(probe)
        if not pas:
            return None
        if _linked_parts():
            from .hitbox import _refresh_linked_parts
            _refresh_linked_parts()
        self._fresh_proxies(rp.members)
        step_max = min(_FLOOR_PROBE_STEP, max(reach, 1.0))
        near = rp.near_box(*_floor_probe_envelope(pas, dx, step_max, reach))
        ident = rp.ident
        pool = _Pool(ident[i] for i in near)
        pool.has_others = len(near) < len(rp) or any(c._proxy_valid for c, _t in pool)
        return pool

    def _floor_pool_near(self, body, probe, group, dx, reach):
        """``floor_below(group=)`` ground near the march, from the vectorized
        index (B2), or None when the group is not an index.

        The pool carries ``has_others``: the group has ground somewhere, so an
        empty pool still marches (the end pose), as the Python walk does.
        """
        pas = self._world_prims(probe)
        if not pas:
            return None
        step_max = min(_FLOOR_PROBE_STEP, max(reach, 1.0))
        env = _floor_probe_envelope(pas, dx, step_max, reach)
        near = self._candidates_in_box(group, env)
        if near is None:
            return None
        pool = _Pool((cb, None) for cb in near
                     if not (cb is probe or cb._part is not None or cb._identity is body))
        cands = self._group_rows(group)[0]
        pool.has_others = any(
            not (cb is probe or cb._part is not None or cb._identity is body) for cb in cands
        )
        if _POSE_REV_VERIFY:
            self._verify_near(group, env, probe, body, pool)
        return pool

    def _verify_near(self, group, env, probe, body, pool) -> None:
        """``SCENA_VERIFY_POSE_REV``: the index found what the walk finds."""
        walk = set()
        x0, y0, x1, y1 = env
        for cb in self._candidates_for_group(group):
            if cb is probe or cb._part is not None or cb._identity is body:
                continue
            if not self._update_proxy(cb, commit_motion=False):
                continue
            p = cb._proxy
            if not (p[0] > x1 or x0 > p[2] or p[1] > y1 or y0 > p[3]):
                walk.add(id(cb))
        got = {id(cb) for cb, _t in pool}
        if not walk <= got:
            raise AssertionError(
                f"vectorized candidates missed {len(walk - got)} of {len(walk)} near "
                f"{group!r} (a proxy was stale or a row out of date)"
            )

    def _floor_march(self, body, pas, partners, gate, dx, reach, step_max):
        """The up / across / drop march of ``floor_below`` (see there)."""
        sign = 1.0 if dx >= 0.0 else -1.0
        remaining = abs(dx)
        ox = oy = 0.0
        floor: Optional[Collider] = None
        while True:
            step = min(step_max, remaining)
            x0, y0 = ox, oy
            lift = 0.0
            blocked = False
            if step > 0.0:
                remaining -= step
                lift = step + _FLOOR_PROBE_LIFT_MARGIN
                hit = self._earliest_toi(
                    _copy_translate(pas, ox, oy), 0.0, lift, partners, gate=gate,
                )
                if hit is not None:
                    lift = max(0.0, lift * max(0.0, min(1.0, hit[0])) - _RESOLVE_SLOP)
                run = sign * step
                hit = self._earliest_toi(
                    _copy_translate(pas, ox, oy + lift), run, 0.0, partners, gate=gate,
                )
                if hit is None:
                    ox += run
                    oy += lift
                else:
                    # A wall (or a rise steeper than the lift) stops the
                    # march. Answer for the last pose that stood: dropping
                    # from the lifted, part-advanced pose would scrape a
                    # slanted wall and read it as a missing floor.
                    lift = 0.0
                    blocked = True
            drop = lift + reach
            hit = self._earliest_toi(
                _copy_translate(pas, ox, oy), 0.0, -drop, partners, gate=gate,
            )
            floor = None
            if hit is None:
                break
            t, nx, ny, other = hit[0], hit[1], hit[2], hit[3]
            nlen = math.hypot(nx, ny)
            if nlen < 1e-12 or _side_from_normal(nx / nlen, ny / nlen) != "bottom":
                if step > 0.0 and not blocked and nx * sign > 0.0:
                    # Landed against a too-steep face that rises ahead (the
                    # lift margin cleared its foot): a wall, not a ledge.
                    # Answer for the last pose that stood.
                    ox, oy = x0, y0
                    remaining = 0.0
                    continue
                break
            oy -= drop * max(0.0, min(1.0, t))
            floor = other
            if blocked or remaining <= 1e-9:
                break
        self._note_floor_probe(body, _copy_translate(pas, ox, oy), floor is not None)
        return None if floor is None else floor._identity

    def _note_floor_probe(self, body, prims: List[Prim], found: bool) -> None:
        """Keep the last ``floor_below`` pose per body for ``show_colliders``."""
        if not self._show:
            return
        probes = self._debug_probes
        if len(probes) >= _FLOOR_PROBE_DEBUG_CAP and id(body) not in probes:
            probes.clear()
        probes[id(body)] = (prims, found)

    def _fire_exits(self, contact_keys: Set[Tuple[int, int]]) -> None:
        self._emit_exit_keys(contact_keys)

    def _oriented_info(
        self,
        me_c: Collider,
        other_c: Collider,
        ca: Collider,
        info: CollisionInfo,
        phase: str,
    ) -> CollisionInfo:
        if me_c is ca or phase == _PHASE_EXIT:
            normal = info.normal
        else:
            nx = float(info.normal.x.value) if hasattr(info.normal.x, "value") else float(info.normal.x)
            ny = float(info.normal.y.value) if hasattr(info.normal.y, "value") else float(info.normal.y)
            normal = Vec2.temp(-nx, -ny)
        return CollisionInfo(
            a=me_c._identity,
            b=other_c._identity,
            normal=normal,
            depth=info.depth,
            points=list(info.points),
            a_hitbox=me_c._part,
            b_hitbox=other_c._part,
        )

    def _dispatch(self, ca: Collider, cb: Collider, info: CollisionInfo, phase: str,
                  only=None, skip=None) -> None:
        # Enter/stay must not run for a body destroyed earlier in this loop.
        # Exit still runs: separation, and the destroy-time survivor notification.
        if phase != _PHASE_EXIT:
            if not self._collider_in_play(ca) or not self._collider_in_play(cb):
                return
        acts = _act_manager()
        if acts.changing and self._both_leave_with_act(ca, cb, acts.dying_ids):
            # Act teardown: two bodies leaving together owe each other no exit.
            return
        if phase != _PHASE_EXIT:
            self._dispatch_contact(ca, cb, info, phase, only, skip)
            return
        # Exit handlers are chosen before any of them runs: one that destroys
        # or untags a side must not hide the rest (PB3), and a tag a side left
        # while touching still matches (PB1). A handler dropped meanwhile (an
        # act change, a destroy) does not run (S4-1): checked only after the
        # dispatch epoch moved, by one int compare per handler.
        self._run_exit(ca, info, self._exit_runs(ca, cb), None)

    def _exit_runs(self, ca: Collider, cb: Collider) -> list:
        """The exit of ``ca`` × ``cb`` as ``(ta, tb, fn, me, other)`` runs:
        the ``on_collide_exit`` callbacks (``ta`` None), then the matching
        exit handlers. Empty for two bodies leaving with an act."""
        acts = _act_manager()
        if acts.changing and self._both_leave_with_act(ca, cb, acts.dying_ids):
            return []
        runs = []
        attr = _PHASE_CALLBACK[_PHASE_EXIT]
        for me_c, other_c in ((ca, cb), (cb, ca)):
            cb_fn = getattr(me_c, attr, None)
            if cb_fn is not None and other_c._part is None:
                runs.append((None, None, cb_fn, me_c, other_c))
        runs.extend(self._exit_matches(ca, cb))
        if self._lost_pending:
            key = _pair_key(ca, cb)
            lost = self._lost_pending.pop(key, None)
            if lost is not None and key not in self._gain_pending:
                # The rules this touching pair lost at the commit, whose exit
                # the step's exit loop has not run yet (C5). Before the key's
                # enter slot, ``_exit_matches`` reads them already.
                runs.extend(self._lost_runs(lost))
        return runs

    def _lost_runs(self, lost) -> list:
        runs, epoch = lost
        if epoch != self._dispatch_epoch:
            # A handler dropped since the commit does not run (S4-1).
            runs = [r for r in runs if self._handler_registered(r[0], r[1], r[2])]
        return runs

    def _run_lost_exit(self, ca: Collider, cb: Collider, info: CollisionInfo, lost) -> None:
        """The exit of the rules a touching pair lost (a tag left while
        another rule keeps the two touching: CD3)."""
        acts = _act_manager()
        if acts.changing and self._both_leave_with_act(ca, cb, acts.dying_ids):
            return
        runs = self._lost_runs(lost)
        if runs:
            self._run_exit(ca, info, runs, None)

    def _run_exit(self, ca: Collider, info: CollisionInfo, runs: list, was,
                  act_epoch: Optional[int] = None) -> None:
        """Run an exit's handlers. One that a handler of this exit dropped
        does not run (S4-1); ``was`` (a deferred exit) lists which were still
        registered when it was chosen, so the leaving side's own handlers,
        dropped by its destroy since, still run. ``act_epoch``: the act
        change epoch when the runs were chosen (default: now); after an act
        change a side's own hook runs only if it still is that side's hook
        (CD2: the act took its callable with it)."""
        epoch = self._dispatch_epoch
        act0 = self._act_change_epoch if act_epoch is None else act_epoch
        changed = False
        for i, (ta, tb, fn, me, other) in enumerate(runs):
            if changed and ta is not None and (was is None or was[i]) \
                    and not self._handler_registered(ta, tb, fn):
                continue
            if ta is None and self._act_change_epoch != act0 \
                    and getattr(me, "on_collide_exit", None) is not fn:
                continue
            oriented = self._oriented_info(me, other, ca, info, _PHASE_EXIT)
            self._author_ran = True
            _call(fn, me._identity, other._identity, oriented)
            if self._dispatch_epoch != epoch:
                changed = True

    def _handler_registered(self, ta, tb, handler) -> bool:
        return any(e[2] is handler and e[0] is ta and e[1] is tb for e in self._pair_handlers)

    def _dispatch_contact(self, ca: Collider, cb: Collider, info: CollisionInfo, phase: str,
                          only=None, skip=None) -> None:
        """Enter / stay of one contact: every handler of it runs (PB5).

        The handlers that match are listed *before* the first one runs, so a
        handler that destroys or parks a side does not hide the rest: they run
        with the dead-but-readable partner, and the outcome does not depend on
        which body was made first or whether a rule is a class method or a
        module ``@collide`` (``Tiro`` destroys itself, ``Inimigo`` scores).
        A body destroyed here enters no *other* pair (``_dispatch`` checks play
        before each contact, S8-2). An act change mid-dispatch is the
        exception: the old act is gone, so a dead side ends the contact and a
        handler the act took with it does not run (S4-1).

        Per rule (CD3): ``only`` lists the rules a touching pair gained at
        the commit (their enter alone), ``skip`` the stay rules it gained
        (they stay from the next step); a tag or handler gained after the
        commit, by a handler of this step, waits for the next step (F3).
        """
        flux = self._rule_flux
        if flux and phase == _PHASE_ENTER and only is None:
            self._note_entered_under(ca, cb)
        attr = _PHASE_CALLBACK[phase]
        runs = None
        for me_c, other_c in ((ca, cb), (cb, ca)):
            cb_fn = getattr(me_c, attr, None)
            if cb_fn is not None and other_c._part is None:
                if runs is None:
                    runs = []
                runs.append((None, None, cb_fn, me_c, other_c))
        # This phase's handlers only, from a snapshot rebuilt when the list
        # changes (review 2026-10-09 perf: every contact copied and filtered
        # every handler of every phase).
        tag_index = self._tag_index
        ida, idb = id(ca), id(cb)
        for ta, tb, handler, _phase, key_tag in self._phase_handlers(phase):
            if key_tag is not None:
                # A tag side matches only a collider in that tag's index: two
                # lookups skip a handler that cannot match (``_pair_matches``
                # was 40 % of a step with 30 unrelated handlers).
                idx = tag_index.get(key_tag)
                if not idx or (ida not in idx and idb not in idx):
                    continue
            matched = self._pair_matches(ta, tb, ca, cb)
            if not matched:
                continue
            if runs is None:
                runs = []
            runs.append((ta, tb, handler, matched[0], matched[1]))
        if runs is None:
            return
        if only is not None or skip is not None or flux or self._new_rules:
            runs = self._rule_filter(ca, cb, runs, only, skip)
            if not runs:
                return
        ida, idb = id(ca), id(cb)
        saved = (self._contact_key, self._deferred_exit)
        self._contact_key = (ida, idb) if ida < idb else (idb, ida)
        self._deferred_exit = None
        try:
            act_epoch = self._act_change_epoch
            for ta, tb, fn, me, other in runs:
                if self._act_change_epoch != act_epoch:
                    if not self._collider_in_play(ca) or not self._collider_in_play(cb):
                        break
                    if ta is not None and not self._handler_registered(ta, tb, fn):
                        continue
                    if ta is None and getattr(me, attr, None) is not fn:
                        # A side's own hook the act took with it (CD2: the
                        # act's callable, cleared by ``_drop_act_callables``).
                        continue
                oriented = self._oriented_info(me, other, ca, info, phase)
                self._author_ran = True
                _call(fn, me._identity, other._identity, oriented)
        finally:
            deferred = self._deferred_exit
            self._contact_key, self._deferred_exit = saved
            if deferred is not None:
                # A side left during this contact's handlers: its exit now,
                # after them (enter, then exit), never lost to a raise.
                xa, _xb, xinfo, xruns, was, x_act = deferred
                if self._act_change_epoch != x_act:
                    was = None              # an act change: S4-1 for all
                self._run_exit(xa, xinfo, xruns, was, x_act)

    def _exit_matches(self, ca: Collider, cb: Collider) -> list:
        """The exit handlers matching ``ca`` × ``cb``, as ``(ta, tb, handler,
        me, other)``: the rules its contact is in. A tag a side left while
        touching the other still counts (PB1), one gained since the contact's
        last commit does not (CD3): the tags are read as of that commit."""
        view_a = view_b = None
        if self._rule_flux or self._flux_now:
            key = _pair_key(ca, cb)
            # A pair the commit found apart, or one whose gained rules have
            # not entered yet: its rules as of the commit before.
            both = key in self._exited_now or key in self._gain_pending
            view_a = self._flux_view(ca, cb, both, True)
            view_b = self._flux_view(cb, ca, both, True)
        viewed = view_a is not None or view_b is not None
        tag_index = self._tag_index
        ida, idb = id(ca), id(cb)
        out = []
        for ta, tb, handler, _phase, key_tag in self._phase_handlers(_PHASE_EXIT):
            if key_tag is not None and not viewed:
                idx = tag_index.get(key_tag)
                if not idx or (ida not in idx and idb not in idx):
                    continue
            if viewed:
                matched = self._pair_matches_as_of(ta, tb, ca, cb, view_a, view_b)
            else:
                matched = self._pair_matches(ta, tb, ca, cb)
            if matched:
                out.append((ta, tb, handler, matched[0], matched[1]))
        return out

    def _flux_view(self, c: Collider, partner: Collider, both: bool, exit: bool):
        """``c``'s tag changes since the last commit (``both``: since the one
        before, during a step's dispatch) as {tag: member then}, or None. For
        an exit, a tag left counts only for a partner that had entered under
        it (PB1: a contact begun after the untag does not match it)."""
        view = None
        pid = id(partner)
        gens = (self._flux_now, self._rule_flux) if both else (self._rule_flux,)
        for gen in gens:
            if not gen:
                continue
            entry = gen.get(id(c))
            if entry is None or entry[0] is not c:
                continue
            for tag, rec in entry[1].items():
                if view is None:
                    view = {}
                elif tag in view:
                    continue            # the older change holds the commit's state
                view[tag] = rec[0] and (not exit or pid in rec[1])
        return view

    def _pair_matches_as_of(self, ta, tb, ca, cb, view_a, view_b):
        """``_pair_matches`` with the tags in ``view_a`` / ``view_b`` read as
        they were (a member then, or not)."""
        def on(c, target, view):
            if view:
                tag = self._pair_tag_of(target)
                if tag is not None and tag in view:
                    return view[tag]
            return self._collider_on_side(c, target)
        if on(ca, ta, view_a) and on(cb, tb, view_b):
            return ca, cb
        if on(cb, ta, view_b) and on(ca, tb, view_a):
            return cb, ca
        return None

    def _rule_filter(self, ca: Collider, cb: Collider, runs: list, only, skip) -> list:
        """Drop from an enter / stay the runs this contact does not owe now:
        not in ``only``, in ``skip``, or a rule gained after the commit (a
        handler set, or a tag joined, by a handler of this step: F3)."""
        new = self._new_rules
        view_a = view_b = None
        if self._rule_flux:
            view_a = self._flux_view(ca, cb, False, False)
            view_b = self._flux_view(cb, ca, False, False)
        viewed = view_a is not None or view_b is not None
        out = []
        for run in runs:
            ta, tb, fn, me, _other = run
            rk = _rule_key(ta, tb, fn, me)
            if only is not None and rk not in only:
                continue
            if skip is not None and rk in skip:
                continue
            if new and rk in new:
                continue
            if viewed and ta is not None \
                    and self._pair_matches_as_of(ta, tb, ca, cb, view_a, view_b) is None:
                continue
            out.append(run)
        return out

    def _note_entered_under(self, ca: Collider, cb: Collider) -> None:
        """A contact enters while a side's tag was left and joined again
        since the commit (no change): it enters under that tag, so its exit
        runs that tag's handlers (the partner joins the left tag's record)."""
        for c, other in ((ca, cb), (cb, ca)):
            entry = self._rule_flux.get(id(c))
            if entry is None or entry[0] is not c:
                continue
            idx_of = self._tag_index
            for tag, rec in entry[1].items():
                if rec[0]:
                    idx = idx_of.get(tag)
                    if idx is not None and id(c) in idx:
                        rec[1].add(id(other))

    def _note_left_tag(self, c: Collider, tag: str) -> None:
        """``c`` is leaving ``tag``: its contacts keep that tag's rules until
        the next commit reads the change (their exit runs them: PB1, CD3)."""
        idx = self._tag_index.get(tag)
        if not idx or id(c) not in idx:
            return
        self._note_flux(c, tag, True)

    def _note_flux(self, c: Collider, tag: str, member: bool) -> None:
        """``c`` leaves (``member``: it was in ``tag``) or joins ``tag``.
        Kept only for a collider that may be touching: one made since the
        last commit is in no contact."""
        if c._born >= self._commit_serial or not self._prev_contacts:
            return
        cid = id(c)
        entry = self._rule_flux.get(cid)
        if entry is None or entry[0] is not c:
            entry = self._rule_flux[cid] = (c, {})
        rec = entry[1].get(tag)
        if rec is None:
            rec = entry[1][tag] = [member, set()]
        if member:
            # The partners whose contact entered under the tag: touching at
            # the commit, and not waiting for this step's enter (S8-3).
            pending = self._enter_pending
            partners = rec[1]
            for k in self._prev_contacts:
                if k[0] == cid:
                    other = k[1]
                elif k[1] == cid:
                    other = k[0]
                else:
                    continue
                if pending and k in pending:
                    continue
                partners.add(other)

    def _note_new_rule(self, entry) -> None:
        """A pair handler registered while bodies touch: a rule a touching
        pair it matches gains (its enter at the next step, CD3). A side that
        is a body made since the last commit touches nothing yet."""
        a, b, fn, phase = entry
        if phase == _PHASE_EXIT:
            return                      # an exit set mid-contact runs at its end
        serial = self._commit_serial
        for side in (a, b):
            if side is ANYTHING or self._pair_tag_of(side) is not None:
                continue
            if isinstance(side, Collider):
                col = side
            elif hasattr(side, "_collider"):
                col = side._collider
            else:
                continue                # a formula group: its members may touch
            if col is None or col._born >= serial:
                return
        self._new_rules[(id(a), id(b), id(fn))] = None

    def _commit_rules(self) -> None:
        """A commit: the changes since the last one are this step's to read."""
        self._commit_serial += 1
        if self._rule_flux:
            self._flux_now, self._rule_flux = self._rule_flux, {}
        if self._new_rules:
            self._new_rules_now, self._new_rules = self._new_rules, {}

    def _rule_changes(self, stayed, id_to) -> Optional[Set[Tuple[int, int]]]:
        """The touching pairs (``stayed``) whose rules changed since the last
        commit: a rule gained enters this step (``_gain_pending``) and stays
        from the next (``_stay_skip``); a rule lost exits after the step's
        exits (``_lost_pending``). Returns the keys with a gained rule."""
        flux = self._flux_now
        new = self._new_rules_now
        every = any(v is None for v in new.values())
        watch = set(flux)
        watch.update(v for v in new.values() if v is not None)
        gained = None
        enter_handlers = self._phase_handlers(_PHASE_ENTER)
        stay_handlers = self._phase_handlers(_PHASE_STAY)
        exit_handlers = self._phase_handlers(_PHASE_EXIT)
        for key in stayed:
            if not every and key[0] not in watch and key[1] not in watch:
                continue
            ca = id_to.get(key[0])
            cb = id_to.get(key[1])
            if ca is None or cb is None:
                continue
            va = self._flux_view(ca, cb, True, False)
            vb = self._flux_view(cb, ca, True, False)
            found = [None, None]
            for i, (phase, handlers) in enumerate(((_PHASE_ENTER, enter_handlers),
                                                   (_PHASE_STAY, stay_handlers))):
                attr = _PHASE_CALLBACK[phase]
                for me_c, other_c in ((ca, cb), (cb, ca)):
                    fn = getattr(me_c, attr, None)
                    if fn is not None and other_c._part is None:
                        rk = (0, id(me_c), id(fn))
                        if rk in new:
                            if found[i] is None:
                                found[i] = set()
                            found[i].add(rk)
                for ta, tb, fn, _ph, _kt in handlers:
                    if self._pair_matches(ta, tb, ca, cb) is None:
                        continue
                    rk = (id(ta), id(tb), id(fn))
                    if rk in new or (
                            (va or vb)
                            and self._pair_matches_as_of(ta, tb, ca, cb, va, vb) is None):
                        if found[i] is None:
                            found[i] = set()
                        found[i].add(rk)
            changed = found[0] is not None or found[1] is not None
            lost = None
            if va or vb:
                xa = self._flux_view(ca, cb, True, True)
                xb = self._flux_view(cb, ca, True, True)
                for ta, tb, fn, _ph, _kt in exit_handlers:
                    now = self._pair_matches(ta, tb, ca, cb)
                    if now is None:
                        was = self._pair_matches_as_of(ta, tb, ca, cb, xa, xb)
                        if was is not None:
                            if lost is None:
                                lost = []
                            lost.append((ta, tb, fn, was[0], was[1]))
                    elif not changed and self._pair_matches_as_of(ta, tb, ca, cb, va, vb) is None:
                        changed = True      # an exit rule gained: no exit before its slot
            if changed:
                if gained is None:
                    gained = set()
                gained.add(key)
                self._gain_pending[key] = found[0] or set()
                if found[1]:
                    self._stay_skip[key] = found[1]
            if lost:
                self._lost_pending[key] = (lost, self._dispatch_epoch)
        return gained

    def _phase_handlers(self, phase: str) -> tuple:
        """The pair handlers of ``phase``, as a tuple (a snapshot: a handler
        may register or drop handlers). Keyed by the dispatch epoch (bumped by
        every removal) and the list length (an append changes it)."""
        key = (self._dispatch_epoch, len(self._pair_handlers))
        cache = self._phase_cache
        if cache is None or cache[0] != key:
            by_phase: Dict[str, list] = {_PHASE_ENTER: [], _PHASE_STAY: [], _PHASE_EXIT: []}
            for entry in self._pair_handlers:
                # The prefilter tag: a side that is a tag (both must match,
                # so either one is a necessary condition).
                key_tag = self._pair_tag_of(entry[0])
                if key_tag is None:
                    key_tag = self._pair_tag_of(entry[1])
                by_phase.setdefault(entry[3], []).append((*entry, key_tag))
            cache = self._phase_cache = (key, {k: tuple(v) for k, v in by_phase.items()})
        return cache[1].get(phase, ())

    @staticmethod
    def _both_leave_with_act(ca: Collider, cb: Collider, dying_ids) -> bool:
        def leaving(c: Collider) -> bool:
            ident = c._identity
            if id(ident) in dying_ids:
                return True
            host = getattr(ident, "host", None) if c._part is not None else None
            return host is not None and id(host) in dying_ids
        return leaving(ca) and leaving(cb)

    def _collider_in_play(self, collider: Collider) -> bool:
        shapes = collider.shapes
        if not shapes:
            return False
        return any(self._item_in_play(s) for s in shapes)

    def _emit_exit_keys(self, keys: Set[Tuple[int, int]]) -> None:
        """Dispatch exit for pairs whose colliders are both still registered."""
        id_to = {id(c): c for c in self._colliders}
        for key in list(keys):
            ca = id_to.get(key[0])
            cb = id_to.get(key[1])
            if ca is None or cb is None:
                continue
            info = CollisionInfo(
                a=ca._identity, b=cb._identity, normal=Vec2.temp(0, 0), depth=0.0,
            )
            self._dispatch(ca, cb, info, _PHASE_EXIT)

    def _pair_matches(self, ta, tb, ca: Collider, cb: Collider):
        if self._collider_on_side(ca, ta) and self._collider_on_side(cb, tb):
            return ca, cb
        if self._collider_on_side(cb, ta) and self._collider_on_side(ca, tb):
            return cb, ca
        return None

    # -- queries ------------------------------------------------------------

    def query_point(self, x, y=None, *, group: Any = None, ignore: Any = None) -> List[Any]:
        """Identities whose hitbox contains the point.

        ``query_point(x, y)`` or one point-like: ``query_point(mouse)``.
        ``group=`` omitted (or ``ANYTHING``) is the enrolled collision world.
        A tag or list of tags tests that group's members, enrolled or not.
        A Graphic origin is the caster and is not a hit. ``ignore=`` adds to it.
        """
        caster = _caster_of(x) if y is None else None
        x, y = _locus_xy(x, y)
        return self._point_hits(x, y, group, _ignore_filter(ignore, caster))

    def _point_hits(self, x, y, group, skipped) -> List[Any]:
        hits = []
        seen = set()
        for c in self._candidates_for_group(group):
            if skipped(c):
                continue
            if not self._update_proxy(c, commit_motion=False):
                continue
            p = c._proxy
            if x < p[0] or x > p[2] or y < p[1] or y > p[3]:
                continue
            for prim in self._world_prims(c):
                if id(c) in seen:
                    break
                if _prim_contains_point(prim, x, y):
                    seen.add(id(c))
                    hits.append(c)
        return _bodies_first(hits)

    def query_circle(self, x, y=None, radius=None, *, group: Any = None, ignore: Any = None) -> List[Any]:
        """Identities overlapping a circle.

        ``query_circle(x, y, radius)`` or ``query_circle(p, radius=r)``.
        A positional radius after a point-like raises — pass ``radius=``.
        ``group=`` uses the same grammar as ``query_shape``. A negative
        ``radius`` raises. A Graphic origin is the caster and is not a hit.
        ``ignore=`` adds to that caster.
        """
        if radius is None and y is not None and not _is_coord(x):
            raise TypeError(
                "after a point-like, pass `radius=` by name: "
                "query_circle(p, radius=80)"
            )
        if radius is None:
            raise TypeError("query_circle() missing required argument: 'radius'")
        caster = _caster_of(x) if y is None else None
        x, y = _locus_xy(x, y)
        r = _magnitude(radius, "radius")
        return self._circle_hits(x, y, r, group, _ignore_filter(ignore, caster))

    def _circle_hits(self, x, y, r, group, skipped) -> List[Any]:
        probe = Prim(PrimKind.CIRCLE, _aabb_from_circle(x, y, r), (x, y, r))
        hits = []
        seen = set()
        for c in self._candidates_for_group(group):
            if skipped(c):
                continue
            if not self._update_proxy(c, commit_motion=False):
                continue
            p = c._proxy
            if x + r < p[0] or x - r > p[2] or y + r < p[1] or y - r > p[3]:
                continue
            for prim in self._world_prims(c):
                if id(c) in seen:
                    break
                minx, miny, maxx, maxy = prim.aabb
                if x + r < minx or x - r > maxx or y + r < miny or y - r > maxy:
                    continue
                if narrow_phase(probe, prim) is not None:
                    seen.add(id(c))
                    hits.append(c)
        return _bodies_first(hits)

    def query_sector(
        self, origin, *args,
        angle: Any = None, radius: Any = None, spread: Any = None,
        group: Any = None, ignore: Any = None,
    ) -> List[Any]:
        """Identities overlapping a circular sector (a radar wedge).

        The origin is positional. ``angle=`` (degrees, 0 = +x, CCW) defaults
        to a Graphic origin's heading ``angle``. ``radius=`` is the reach.
        ``spread=`` is the full opening in degrees (``60`` means ±30).
        ``0`` is the center segment (every hit, not the first). ``360`` is
        ``query_circle``. A Graphic origin is the caster and is not a hit.
        """
        if args:
            raise TypeError(
                "query_sector() takes the origin positionally; "
                "pass angle=, radius=, spread=, group=, and ignore= by name. "
                "Write query_sector(guard, radius=300, spread=60)."
            )
        if radius is None:
            raise TypeError("query_sector() missing required argument: 'radius'")
        if spread is None:
            raise TypeError("query_sector() missing required argument: 'spread'")
        caster = _caster_of(origin)
        if angle is None:
            angle = _heading_default(caster, "query_sector")
        else:
            angle = _finite(angle, "angle")
        radius = _magnitude(radius, "radius")
        spread = _magnitude(spread, "spread")
        if spread > 360.0:
            raise ValueError(f"spread must be <= 360, got {spread}")
        x, y = _locus_xy(origin)
        skipped = _ignore_filter(ignore, caster)
        if spread == 360.0:
            return self._circle_hits(x, y, radius, group, skipped)
        if radius == 0.0:
            return self._point_hits(x, y, group, skipped)
        if spread == 0.0:
            rad = math.radians(float(angle))
            return self._segment_hits(
                x, y,
                x + radius * math.cos(rad),
                y + radius * math.sin(rad),
                group, skipped,
            )
        probes = _sector_wedges(x, y, float(angle), radius, spread)
        return self._prim_hits(probes, group, skipped)

    def _segment_hits(self, x1, y1, x2, y2, group, skipped) -> List[Any]:
        """Every collider the segment touches: multi-piece bodies first (AC10)."""
        dx, dy = x2 - x1, y2 - y1
        minx, maxx = (x1, x2) if x1 <= x2 else (x2, x1)
        miny, maxy = (y1, y2) if y1 <= y2 else (y2, y1)
        hits = []
        seen = set()
        for c in self._candidates_for_group(group):
            if skipped(c):
                continue
            if not self._update_proxy(c, commit_motion=False):
                continue
            p = c._proxy
            if maxx < p[0] or minx > p[2] or maxy < p[1] or miny > p[3]:
                continue
            for prim in self._world_prims(c):
                if id(c) in seen:
                    break
                t = _ray_prim(x1, y1, dx, dy, prim)
                if t is not None and 0.0 <= t <= 1.0:
                    seen.add(id(c))
                    hits.append(c)
        return _bodies_first(hits)

    def _prim_hits(self, probes: Sequence[Prim], group, skipped) -> List[Any]:
        """Identities overlapping any probe prim: multi-piece bodies first (AC10)."""
        if not probes:
            return []
        minx = min(p.aabb[0] for p in probes)
        miny = min(p.aabb[1] for p in probes)
        maxx = max(p.aabb[2] for p in probes)
        maxy = max(p.aabb[3] for p in probes)
        hits = []
        seen = set()
        for c in self._candidates_for_group(group):
            if skipped(c):
                continue
            if not self._update_proxy(c, commit_motion=False):
                continue
            proxy = c._proxy
            if maxx < proxy[0] or minx > proxy[2] or maxy < proxy[1] or miny > proxy[3]:
                continue
            for prim in self._world_prims(c):
                if id(c) in seen:
                    break
                pminx, pminy, pmaxx, pmaxy = prim.aabb
                if maxx < pminx or minx > pmaxx or maxy < pminy or miny > pmaxy:
                    continue
                for probe in probes:
                    ax0, ay0, ax1, ay1 = probe.aabb
                    if ax1 < pminx or ax0 > pmaxx or ay1 < pminy or ay0 > pmaxy:
                        continue
                    if narrow_phase(probe, prim) is not None:
                        seen.add(id(c))
                        hits.append(c)
                        break
        return _bodies_first(hits)

    def raycast(
        self, p1, *args,
        p2: Any = None, vec: Any = None, angle: Any = None, length: Any = None,
        group: Any = None, ignore: Any = None,
    ) -> Optional[Tuple[Any, float, Tuple[float, float]]]:
        """First collider hit along a segment.

        The start is positional. The end is one of ``p2=`` (a point),
        ``vec=`` (a displacement), or ``length=`` with optional ``angle=``
        (degrees). ``angle=`` omitted uses a Graphic start's heading ``angle``.
        A positional second argument raises.

        ``group=`` omitted (or ``ANYTHING``) is the enrolled world. A tag, or a
        list / tuple / set of tags, tests those members without enrolling them.
        A Graphic start is the caster and is not a hit. ``ignore=`` adds to
        that caster: a body, a tag, a live group, or a list of those.

        Returns (identity, t in [0,1], point) or None. A start inside a prim
        is t = 0.
        """
        if args:
            raise TypeError(
                "raycast() takes only the start positionally. "
                "Pass the end as p2=, as vec=, or as angle= and length=. "
                "Write raycast(p1, p2=end), raycast(p1, vec=delta), "
                "or raycast(p1, angle=45, length=400)."
            )
        end_forms = []
        if p2 is not None:
            end_forms.append("p2")
        if vec is not None:
            end_forms.append("vec")
        if angle is not None or length is not None:
            end_forms.append("angle")
        if not end_forms:
            raise TypeError(
                "raycast() needs an end: p2=, vec=, or length= "
                "(angle= is optional with length=)"
            )
        if len(end_forms) > 1:
            raise TypeError(
                "raycast() takes one end form: p2=, or vec=, or angle= and length="
            )
        caster = _caster_of(p1)
        x1, y1 = _locus_xy(p1)
        if p2 is not None:
            x2, y2 = _locus_xy(p2)
        elif vec is not None:
            dx, dy = _delta_xy_of(vec)
            x2, y2 = x1 + dx, y1 + dy
        else:
            if length is None:
                raise TypeError("raycast() angle= needs length=")
            length = _magnitude(length, "length")
            if angle is None:
                angle = _heading_default(caster, "raycast")
            else:
                angle = _finite(angle, "angle")
            rad = math.radians(float(angle))
            x2 = x1 + length * math.cos(rad)
            y2 = y1 + length * math.sin(rad)
        best_t = 1.0 + 1e-9
        best_rank = 2
        best = None
        dx, dy = x2 - x1, y2 - y1
        minx, maxx = (x1, x2) if x1 <= x2 else (x2, x1)
        miny, maxy = (y1, y2) if y1 <= y2 else (y2, y1)
        skipped = _ignore_filter(ignore, caster)

        for c in self._candidates_for_group(group):
            if skipped(c):
                continue
            if not self._update_proxy(c, commit_motion=False):
                continue
            p = c._proxy
            if maxx < p[0] or minx > p[2] or maxy < p[1] or miny > p[3]:
                continue
            rank = 0 if _is_multi_body(c) else 1
            for prim in self._world_prims(c):
                t = _ray_prim(x1, y1, dx, dy, prim)
                if t is None or not 0.0 <= t <= 1.0:
                    continue
                # Nearest first; on a tie (a piece that is also a body of its
                # own) the multi-piece body wins, whatever line ran first (AC10).
                if t < best_t - 1e-9 or (t <= best_t + 1e-9 and rank < best_rank):
                    best_t = t
                    best_rank = rank
                    best = (c._identity, t, (x1 + t * dx, y1 + t * dy))
        return best

    # -- debug --------------------------------------------------------------

    def show_colliders(self, enabled: bool = True) -> None:
        self._show = bool(enabled)
        if not self._show:
            self._clear_debug_draw()

    def _clear_debug_draw(self) -> None:
        self._debug_overlay = ()
        self._debug_probes.clear()
        for s in self._debug_shapes:
            try:
                s.destroy()
            except Exception:
                pass
        self._debug_shapes.clear()

    def _update_debug_draw(self, prim_list) -> None:
        """Cache world-space prims for immediate-mode debug_draw (no Shape churn)."""
        self._debug_overlay = tuple((c, p) for c, p, _ in prim_list)

    def _debug_color_for(self, collider: Collider) -> Tuple[float, float, float, float]:
        """``show_colliders`` legend: gold = resolve, cyan = hitbox part, green = detect."""
        if collider._part is not None:
            return _DEBUG_PART_RGBA
        if self._collider_in_resolve(collider):
            return _DEBUG_RESOLVE_RGBA
        return _DEBUG_DETECT_RGBA

    def _debug_paint_for(self, rgba: Tuple[float, float, float, float]) -> skia.Paint:
        paint = self._debug_paint
        if paint is None:
            paint = skia.Paint()
            paint.setStyle(skia.Paint.kStroke_Style)
            paint.setStrokeWidth(1.0)
            paint.setAntiAlias(True)
            self._debug_paint = paint
        paint.setColor4f(skia.Color4f(*rgba))
        return paint

    @staticmethod
    def _debug_outline_verts(prim: Prim) -> Optional[List[Tuple[float, float]]]:
        if prim.kind == PrimKind.CIRCLE:
            return None
        if prim.kind == PrimKind.AABB:
            minx, miny, maxx, maxy = prim.params
            return [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        if prim.kind == PrimKind.OBB:
            return _obb_corners(
                prim.params[0], prim.params[1], prim.params[2], prim.params[3], prim.params[4],
            )
        if prim.kind == PrimKind.ELLIPSE:
            cx, cy, rx, ry, ang = prim.params
            verts: List[Tuple[float, float]] = []
            for i in range(24):
                t = 2 * math.pi * i / 24
                lx, ly = rx * math.cos(t), ry * math.sin(t)
                c_, s_ = math.cos(ang), math.sin(ang)
                verts.append((cx + lx * c_ - ly * s_, cy + lx * s_ + ly * c_))
            return verts
        if prim.kind == PrimKind.POLY and prim.verts:
            return list(prim.verts)
        return None

    def debug_draw(self, skia_canvas) -> None:
        """Draw collider outlines in world space (called from the render loop)."""
        if not self._show:
            return
        for collider, prim in self._debug_overlay:
            self._debug_draw_prim(
                skia_canvas, prim, self._debug_paint_for(self._debug_color_for(collider)),
            )
        if self._debug_probes:
            # ``floor_below`` casts since the last draw: where the step ended.
            for prims, found in self._debug_probes.values():
                paint = self._debug_paint_for(
                    _DEBUG_PROBE_FLOOR_RGBA if found else _DEBUG_PROBE_NONE_RGBA
                )
                for prim in prims:
                    self._debug_draw_prim(skia_canvas, prim, paint)
            self._debug_probes.clear()

    def _debug_draw_prim(self, skia_canvas, prim: Prim, paint) -> None:
        if prim.kind == PrimKind.CIRCLE:
            cx, cy, r = prim.params[0], prim.params[1], prim.params[2]
            skia_canvas.drawCircle(cx, cy, max(r, 1.0), paint)
            return
        verts = self._debug_outline_verts(prim)
        if not verts or len(verts) < 3:
            return
        path = skia.Path()
        path.moveTo(verts[0][0], verts[0][1])
        for x, y in verts[1:]:
            path.lineTo(x, y)
        path.close()
        skia_canvas.drawPath(path, paint)


def _prim_contains_point(prim: Prim, x: float, y: float) -> bool:
    if prim.kind == PrimKind.CIRCLE:
        cx, cy, r = prim.params[0], prim.params[1], prim.params[2]
        return _sq(x - cx) + _sq(y - cy) <= r * r + 1e-9
    if prim.kind == PrimKind.AABB:
        minx, miny, maxx, maxy = prim.params[0], prim.params[1], prim.params[2], prim.params[3]
        return minx <= x <= maxx and miny <= y <= maxy
    if prim.kind == PrimKind.OBB:
        cx, cy, hw, hh, ang = prim.params[0], prim.params[1], prim.params[2], prim.params[3], prim.params[4]
        c, s = math.cos(-ang), math.sin(-ang)
        dx, dy = x - cx, y - cy
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        return abs(lx) <= hw + 1e-9 and abs(ly) <= hh + 1e-9
    if prim.kind == PrimKind.ELLIPSE:
        cx, cy, rx, ry, ang = prim.params
        if rx <= 0 or ry <= 0:
            return False
        c, s = math.cos(-ang), math.sin(-ang)
        dx, dy = x - cx, y - cy
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        return _sq(lx / rx) + _sq(ly / ry) <= 1.0 + 1e-9
    if prim.kind == PrimKind.POLY and prim.verts:
        return _point_in_polygon_xy(x, y, prim.verts)
    return False


def _ray_prim(x1, y1, dx, dy, prim: Prim) -> Optional[float]:
    """Return smallest t in [0,1] where the segment hits ``prim``, or None."""
    if prim.kind == PrimKind.CIRCLE:
        return _ray_circle(x1, y1, dx, dy, prim.params[0], prim.params[1], prim.params[2])
    if prim.kind == PrimKind.AABB:
        return _ray_aabb(x1, y1, dx, dy, prim.params)
    if prim.kind == PrimKind.OBB:
        cx, cy, hw, hh, ang = prim.params
        return _ray_obb(x1, y1, dx, dy, cx, cy, hw, hh, ang)
    if prim.kind == PrimKind.ELLIPSE:
        cx, cy, rx, ry, ang = prim.params
        return _ray_ellipse(x1, y1, dx, dy, cx, cy, rx, ry, ang)
    if prim.kind == PrimKind.POLY and prim.verts:
        if _is_convex(prim.verts):
            return _ray_convex_poly(x1, y1, dx, dy, prim.verts)
        return _ray_sampled(x1, y1, dx, dy, prim)
    return None


def _ray_sampled(x1, y1, dx, dy, prim: Prim) -> Optional[float]:
    """Containment samples spaced about 1 DU apart (non-convex fallback)."""
    length = math.hypot(dx, dy)
    steps = max(1, int(math.ceil(length)))
    if _prim_contains_point(prim, x1, y1):
        return 0.0
    for i in range(1, steps + 1):
        t = i / steps
        if _prim_contains_point(prim, x1 + t * dx, y1 + t * dy):
            lo, hi = (i - 1) / steps, t
            for _ in range(8):
                mid = 0.5 * (lo + hi)
                if _prim_contains_point(prim, x1 + mid * dx, y1 + mid * dy):
                    hi = mid
                else:
                    lo = mid
            return hi
    return None


def _ray_obb(x1, y1, dx, dy, cx, cy, hw, hh, ang) -> Optional[float]:
    """Slab test in the box's local frame."""
    ca, sa = math.cos(float(ang)), math.sin(float(ang))
    ox, oy = x1 - float(cx), y1 - float(cy)
    lx = ca * ox + sa * oy
    ly = -sa * ox + ca * oy
    ldx = ca * dx + sa * dy
    ldy = -sa * dx + ca * dy
    return _ray_aabb(lx, ly, ldx, ldy, (-float(hw), -float(hh), float(hw), float(hh)))


def _ray_ellipse(x1, y1, dx, dy, cx, cy, rx, ry, ang) -> Optional[float]:
    """Map the segment onto the unit circle and solve the quadratic."""
    if rx <= 1e-12 or ry <= 1e-12:
        return None
    ca, sa = math.cos(float(ang)), math.sin(float(ang))
    ox, oy = x1 - float(cx), y1 - float(cy)
    lx = (ca * ox + sa * oy) / float(rx)
    ly = (-sa * ox + ca * oy) / float(ry)
    ldx = (ca * dx + sa * dy) / float(rx)
    ldy = (-sa * dx + ca * dy) / float(ry)
    return _ray_circle(lx, ly, ldx, ldy, 0.0, 0.0, 1.0)


def _ray_convex_poly(x1, y1, dx, dy, verts: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Cyrus–Beck clip against a convex polygon. Inside the polygon returns 0."""
    n = len(verts)
    if n < 3:
        return None
    ccw = _signed_area(verts) >= 0.0
    t_enter, t_leave = 0.0, 1.0
    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        if ccw:
            nx, ny = ey, -ex
        else:
            nx, ny = -ey, ex
        denom = nx * dx + ny * dy
        numer = nx * (ax - x1) + ny * (ay - y1)
        if abs(denom) < 1e-18:
            if numer < 0.0:
                return None
            continue
        t = numer / denom
        if denom < 0.0:
            if t > t_enter:
                t_enter = t
        elif t < t_leave:
            t_leave = t
        if t_enter > t_leave:
            return None
    if t_enter < 0.0:
        return 0.0 if t_leave >= 0.0 else None
    return t_enter if t_enter <= 1.0 else None


def _ray_circle(x1, y1, dx, dy, cx, cy, r) -> Optional[float]:
    # |o + t d - c|^2 = r^2. A start inside the circle is t = 0, matching other prims.
    fx, fy = x1 - cx, y1 - cy
    if fx * fx + fy * fy <= r * r + 1e-9:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-18:
        return None
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    sd = math.sqrt(disc)
    t0 = (-b - sd) / (2 * a)
    t1 = (-b + sd) / (2 * a)
    for t in (t0, t1):
        if 0.0 <= t <= 1.0:
            return t
    return None


def _ray_aabb(x1, y1, dx, dy, box) -> Optional[float]:
    minx, miny, maxx, maxy = box
    tmin, tmax = 0.0, 1.0
    for origin, d, mn, mx in ((x1, dx, minx, maxx), (y1, dy, miny, maxy)):
        if abs(d) < 1e-18:
            if origin < mn or origin > mx:
                return None
            continue
        t1 = (mn - origin) / d
        t2 = (mx - origin) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin if 0.0 <= tmin <= 1.0 else (0.0 if tmin < 0 <= tmax else None)


# ---------------------------------------------------------------------------
# Shape helpers / global system
# ---------------------------------------------------------------------------

_collision_system: Optional[CollisionSystem] = None


def get_collision_system() -> CollisionSystem:
    global _collision_system
    if _collision_system is None:
        _collision_system = CollisionSystem()
    return _collision_system


def reset_collision_system() -> None:
    """Test helper: clear the global system."""
    global _collision_system
    if _collision_system is not None:
        _collision_system._clear_debug_draw()
    _collision_system = CollisionSystem()
    # ScenaFramework caches this at bootstrap; keep the pointer current.
    from .orchestration import ScenaFramework
    fw = ScenaFramework._instance
    if fw is not None:
        fw.collision_system = _collision_system


def _is_coord(value) -> bool:
    """A bare number (not a point-like, not ``bool``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _locus_xy(p, y=None):
    """``(x, y)`` numbers, or one point-like when ``y`` is omitted.

    One point-like goes through ``_xy_of`` (the one reading): exactly two
    numbers, Point, Vec2, Graphic ``.center``, mouse.
    """
    if y is not None:
        return float(p), float(y)
    from .shapes import _xy_of
    return _xy_of(p, required=True)


def _caster_of(origin):
    """Graphic or SpatialFx origin, or None for a plain position.

    A ``Point``, ``Vec2``, ``(x, y)``, or ``mouse`` is only a location.
    The caster is excluded from query and raycast hits.
    """
    if origin is None or _is_coord(origin) or isinstance(origin, (tuple, list)):
        return None
    from .input import Mouse
    from .shapes import Point
    if isinstance(origin, (Point, Vec2, Mouse)):
        return None
    from .entity import Graphic
    from .spatial_fx import SpatialFx
    if isinstance(origin, (Graphic, SpatialFx)):
        return origin
    return None


def _heading_default(caster, what: str) -> float:
    """``caster.angle`` (the heading) when ``angle=`` is omitted. A plain position raises."""
    from .entity import Graphic
    if not isinstance(caster, Graphic):
        raise TypeError(
            f"{what}() pass angle= (a plain position has no heading)"
        )
    return float(caster.angle)


def _delta_xy_of(vec) -> Tuple[float, float]:
    """Displacement for ``raycast(vec=)``. A location is not a delta."""
    from .input import Mouse
    from .shapes import Point, _xy_of
    if isinstance(vec, (Point, Mouse)) or getattr(vec, "center", None) is not None:
        raise TypeError(
            "vec= does not accept a Point, Graphic, or mouse (those are locations). "
            "Use p2=, or pass a Vec2 or (dx, dy)."
        )
    return _xy_of(vec, required=True)


def _ignore_type_error(value) -> TypeError:
    return TypeError(
        "ignore= must be a body, a tag, a live group, or a list of those; "
        f"got {type(value).__name__} {value!r}. "
        'Write ignore="allies" or ignore=["allies", shield].'
    )


def _ignore_members(tag: str) -> List[Any]:
    """Registry members of ``tag``, including a formula group of that name."""
    try:
        from .canvas import ScenaCanvas
        registry = ScenaCanvas.get_current().registry
    except Exception:
        return []
    if registry.has_group_formula(tag):
        return registry.eval_group_formula(tag)
    return registry.list_by_groupid(tag)


def _ignore_filter(ignore: Any, caster: Any) -> Callable[[Any], bool]:
    """``collider -> True`` when the query must skip it.

    The caster is always skipped. ``ignore=`` adds bodies (by identity),
    tags, and live groups (by registry membership). A tag with no members
    matches nothing. ``ANYTHING`` and other types raise.
    """
    body_ids: Set[int] = set()
    member_ids: Set[int] = set()
    if caster is not None:
        body_ids.add(id(caster))

    def add(item) -> None:
        if item is ANYTHING:
            raise ValueError(
                "ignore= cannot be ANYTHING. Omit it to test everyone, "
                "or pass the bodies and tags to skip."
            )
        if isinstance(item, str):
            if item == "":
                raise ValueError(
                    'ignore= must be a non-empty tag. Write ignore="allies".'
                )
            for member in _ignore_members(item):
                member_ids.add(id(member))
            return
        if isinstance(item, Collider):
            body_ids.add(id(item))
            if item._identity is not None:
                body_ids.add(id(item._identity))
            return
        from .registry import GroupOperator
        if isinstance(item, GroupOperator):
            for member in list(item):
                member_ids.add(id(member))
            return
        if _is_coord(item) or isinstance(item, (tuple, list)):
            raise _ignore_type_error(item)
        from .entity import Entity
        if isinstance(item, Entity) or getattr(type(item), "_is_hitbox_part", False):
            body_ids.add(id(item))
            return
        raise _ignore_type_error(item)

    if ignore is None:
        pass
    elif isinstance(ignore, (list, tuple, set, frozenset)):
        for item in ignore:
            add(item)
    else:
        add(ignore)

    def skipped(collider: Collider) -> bool:
        ident = collider._identity
        if id(collider) in body_ids or (ident is not None and id(ident) in body_ids):
            return True
        if ident is not None and id(ident) in member_ids:
            return True
        for shape in collider.shapes:
            if id(shape) in body_ids or id(shape) in member_ids:
                return True
        return False

    return skipped


def _arc_steps(radius: float, span_rad: float) -> int:
    """Chord count so the arc sits within ``_SECTOR_ARC_ERROR`` of each chord."""
    if radius <= _SECTOR_ARC_ERROR or span_rad <= 0.0:
        return 1
    ratio = 1.0 - (_SECTOR_ARC_ERROR / radius)
    if ratio <= -1.0:
        return 1
    half = math.acos(min(1.0, ratio))
    dtheta = 2.0 * half
    if dtheta <= 1e-9:
        return _SECTOR_MAX_STEPS
    return max(1, min(_SECTOR_MAX_STEPS, int(math.ceil(span_rad / dtheta))))


def _segment_prim(
    x: float, y: float, angle_deg: float, radius: float, spread_deg: float,
) -> List[Prim]:
    """One convex polygon for the chord-closed segment (``use_center=False``).

    Arc samples use the same chord error as :func:`_sector_wedges`. The closing
    edge is the chord. A circular segment stays convex at every opening below
    a full turn, so this is a single polygon rather than 90° wedges.
    """
    span = math.radians(spread_deg)
    n_wedges = max(1, int(math.ceil((spread_deg - 1e-9) / 90.0)))
    steps = max(2, _arc_steps(radius, span / n_wedges) * n_wedges)
    start = math.radians(angle_deg - spread_deg / 2.0)
    verts = []
    for step in range(steps + 1):
        a = start + span * (step / steps)
        verts.append((x + radius * math.cos(a), y + radius * math.sin(a)))
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    aabb = (min(xs), min(ys), max(xs), max(ys))
    return [Prim(PrimKind.POLY, aabb, (), verts)]


def _partial_circle_prims(
    cx: float, cy: float, radius: float, angle_deg: float, spread_deg: float,
    use_center: bool,
) -> List[Prim]:
    """Filled body of a partial circle. Callers keep the full-turn fast path."""
    if use_center:
        return _sector_wedges(cx, cy, angle_deg, radius, spread_deg)
    return _segment_prim(cx, cy, angle_deg, radius, spread_deg)


def _sector_wedges(x: float, y: float, angle_deg: float, radius: float, spread_deg: float) -> List[Prim]:
    """Convex polygon wedges covering the sector. Each wedge is at most 90°."""
    n_wedges = max(1, int(math.ceil((spread_deg - 1e-9) / 90.0)))
    wedge_spread = spread_deg / n_wedges
    start = angle_deg - spread_deg / 2.0
    prims: List[Prim] = []
    for i in range(n_wedges):
        a0 = start + i * wedge_spread
        span = math.radians(wedge_spread)
        steps = _arc_steps(radius, span)
        verts = [(x, y)]
        for step in range(steps + 1):
            a = math.radians(a0) + span * (step / steps)
            verts.append((x + radius * math.cos(a), y + radius * math.sin(a)))
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        aabb = (min(xs), min(ys), max(xs), max(ys))
        prims.append(Prim(PrimKind.POLY, aabb, (), verts))
    return prims


# Facade used as ``collision`` in author scripts
class _CollisionFacade(ClosedSurface):
    _closed_who = "collision"

    def __init__(self) -> None:
        pass  # closed surface: the seal needs a constructor to wrap

    def _step(self) -> None:
        get_collision_system().step()

    def show_colliders(self, enabled: bool = True) -> None:
        """Draw every hitbox as an overlay (``False`` hides them)."""
        get_collision_system().show_colliders(enabled)

    def show_tracks(self, enabled: bool = True) -> None:
        """Draw every Track as an overlay (``False`` hides them)."""
        from .track import show_tracks as _show
        _show(enabled)

    @property
    def resolve_enabled(self) -> bool:
        """When False, skip sweep/settle/floor snap. ``@collide`` / queries stay on."""
        return get_collision_system().resolve_enabled

    @resolve_enabled.setter
    def resolve_enabled(self, value: bool) -> None:
        get_collision_system().resolve_enabled = bool(value)

    def query_point(self, x, y=None, *, group=None, ignore=None):
        """Hitboxes containing ``(x, y)`` or one point-like.

        ``group=`` omitted is the enrolled world. A tag (or a list of tags)
        tests that group's members without enrolling them. A Graphic origin
        is not a hit; ``ignore=`` adds to that caster.
        """
        return get_collision_system().query_point(x, y, group=group, ignore=ignore)

    def query_circle(self, x, y=None, radius=None, *, group=None, ignore=None):
        """Hitboxes overlapping a circle. See :meth:`CollisionSystem.query_circle`."""
        return get_collision_system().query_circle(
            x, y, radius, group=group, ignore=ignore,
        )

    def query_sector(
        self, origin, *args,
        angle=None, radius=None, spread=None, group=None, ignore=None,
    ):
        """Hitboxes overlapping a sector. See :meth:`CollisionSystem.query_sector`."""
        return get_collision_system().query_sector(
            origin, *args,
            angle=angle, radius=radius, spread=spread, group=group, ignore=ignore,
        )

    def raycast(
        self, p1, *args,
        p2=None, vec=None, angle=None, length=None, group=None, ignore=None,
    ):
        """First hit along a segment. See :meth:`CollisionSystem.raycast`."""
        return get_collision_system().raycast(
            p1, *args,
            p2=p2, vec=vec, angle=angle, length=length, group=group, ignore=ignore,
        )

    def query_shape(self, shape, group=None):
        """Bodies whose hitbox overlaps ``shape`` (optionally only those in ``group``). A list."""
        return get_collision_system().query_shape(shape, group=group)


collision = _CollisionFacade()


def _resolve_target_equal(x, y) -> bool:
    """Tags compare by name, ``"walls"`` and a live ``group["walls"]`` alike
    (``unresolve(a, group["walls"])`` never matched its own ``resolve``:
    review 2026-10-09 S9-7); every other target compares by identity."""
    if x is y:
        return True
    tx = CollisionSystem._pair_tag_of(x)
    if tx is None:
        return False
    return tx == CollisionSystem._pair_tag_of(y)


def _resolve_pair_equal(pa, pb, a, b) -> bool:
    """True when ``(pa, pb)`` is the same registration as ``(a, b)``, either order."""
    return (
        (_resolve_target_equal(pa, a) and _resolve_target_equal(pb, b))
        or (_resolve_target_equal(pa, b) and _resolve_target_equal(pb, a))
    )


def resolve(a, b, bounce: Optional[float] = None, only: Any = None) -> None:
    """Register standing auto-resolution for overlapping ``a`` and ``b`` each frame.

    Same side grammar as ``@collide``: a tag, a body, ``ANYTHING``, or a
    list/tuple (cross-product). ``resolve("bola", ["plataforma", "parede"])``
    is both pairs.

    ``only=`` limits which of ``a``'s sides this pair may produce in
    ``a.touching_sides``: ``only="bottom"`` is a one-way (jump-through)
    platform. A side, a list/tuple/set of sides, or a function of the
    ``TouchingContact`` (``a``'s view) returning True to block. Any other first
    contact makes the pair pass through until the two stop overlapping.

    Args:
        a: The side that gets pushed out (an actor, tag, ``group['tag']``, list).
        b: What it stands on / bumps into (same forms).
        bounce: ``None`` = position only; a number = restitution along the normal (0 =
            stop).
        only: Sides of ``a`` this pair may block (one-way platforms): a side, a set of
            sides, or ``fn(contact)``.
    """
    sys = get_collision_system()
    lefts = _normalize_side(a)
    rights = _normalize_side(b)
    if not lefts or not rights:
        raise TypeError("resolve() sides must not be empty")
    _check_pair_sides("resolve()", 'resolve(player, "walls")', lefts, rights)
    from .registry import declare_group_names
    declare_group_names(lefts + rights)
    only = _normalize_only(only)
    if only is not None and not isinstance(only, frozenset):
        # The function runs inside the solver: refuse visible writes now.
        check_read_only(only)
    if isinstance(only, frozenset) and only != _mirror_only(only):
        for left in lefts:
            for right in rights:
                if sys._same_resolve_side(left, right):
                    raise ValueError(
                        f"resolve({_side_code(left)}, {_side_code(right)}, "
                        f"{_only_code(only)}): a group resolved against itself "
                        "sees each contact from both bodies, so only= must read "
                        'the same from both. Use {"top", "bottom"}, '
                        '{"left", "right"}, or a function of the contact.'
                    )
    # All-or-nothing: refuse a hitbox-part side, or a member whose resolved
    # part has an ``@=`` formula, before any pair registers. The formula check
    # runs here (not only per pair in ``add_resolve_pair``) so it can name the
    # group that pulled the member in.
    for side in lefts + rights:
        _refuse_part_resolve_side(sys, side)
    for side in lefts + rights:
        group = side if isinstance(side, str) else None
        for shape in _collect_entities_from_target(side):
            if getattr(shape, "_resolve_enrolled", False):
                continue
            ensure = getattr(shape, "_ensure_resolve_parts_writable", None)
            if callable(ensure):
                if group is not None:
                    ensure(group)
                else:
                    ensure()
    # The layer refusal for every named member, before any pair (S8-1, S9-1).
    _assert_named_sides_not_parallax(lefts + rights)
    if bounce is not None:
        _validate_bounce(bounce)
    before = list(sys._resolve_pairs)
    try:
        for left in lefts:
            for right in rights:
                sys.add_resolve_pair(left, right, bounce=bounce, only=only)
    except BaseException:
        _restore_resolve_pairs(before)
        raise
    if sys._has_only:
        # Eager: a body pair reached by two registrations that disagree on
        # only= raises here, not on the next frame. Undo this call first.
        try:
            for side in lefts + rights:
                for c in sys._resolve_side_colliders(side):
                    sys._resolve_partners(c)
        except ValueError:
            _restore_resolve_pairs(before)
            raise


def _resolve_side_alive(side) -> bool:
    if side is ANYTHING or isinstance(side, str):
        return True
    return bool(getattr(side, "is_alive", True))


_LINKED_PARTS_SET = None


def _linked_parts():
    """``hitbox._LINKED_PARTS`` (imported once; hitbox imports this module)."""
    global _LINKED_PARTS_SET
    if _LINKED_PARTS_SET is None:
        from .hitbox import _LINKED_PARTS
        _LINKED_PARTS_SET = _LINKED_PARTS
    return _LINKED_PARTS_SET



_PHASE_CALLBACK = {
    _PHASE_ENTER: "on_collide",
    _PHASE_STAY: "on_collide_stay",
    _PHASE_EXIT: "on_collide_exit",
}
_ACT_MANAGER = None


def _pair_key(ca, cb) -> Tuple[int, int]:
    """The contact key of two colliders (lower ``id()`` first)."""
    ida, idb = id(ca), id(cb)
    return (ida, idb) if ida < idb else (idb, ida)


def _rule_key(ta, tb, fn, me) -> tuple:
    """A contact rule's identity: a pair handler's sides and function, or a
    side's own ``on_collide*`` hook (``ta`` None) and its collider."""
    if ta is None:
        return (0, id(me), id(fn))
    return (id(ta), id(tb), id(fn))


def _act_manager():
    """The act manager (one object for the process; imported once, not per
    contact)."""
    global _ACT_MANAGER
    if _ACT_MANAGER is None:
        from .act import get_act_manager
        _ACT_MANAGER = get_act_manager()
    return _ACT_MANAGER


def _restore_resolve_pairs(snapshot) -> None:
    """Put ``resolve`` pairs back to ``snapshot`` (an act change).

    Pairs an act added are removed; game pairs an act removed or re-tuned
    (``bounce=``) come back. A side that is a dead actor is not revived.
    """
    sys = get_collision_system()
    for a, b, _tok, _only in list(sys._resolve_pairs):
        if not any(_resolve_pair_equal(pa, pb, a, b) for pa, pb, _t, _o in snapshot):
            sys.remove_resolve_pair(a, b)
    for a, b, tok, only in snapshot:
        if not (_resolve_side_alive(a) and _resolve_side_alive(b)):
            continue
        now = [
            (pa, t, o) for pa, pb, t, o in sys._resolve_pairs
            if _resolve_pair_equal(pa, pb, a, b)
        ]
        if (
            now and now[0][1] == tok and now[0][2] == only
            # ``only`` sides are read from the first argument: same order too.
            and (only is None or _resolve_target_equal(now[0][0], a))
        ):
            continue
        sys.add_resolve_pair(
            a, b, bounce=None if tok is _RESOLVE_POSITION_ONLY else tok, only=only,
        )


def unresolve(a, b) -> None:
    """Cancel a standing ``resolve(a, b)`` registration."""
    sys = get_collision_system()
    lefts = _normalize_side(a)
    rights = _normalize_side(b)
    if not lefts or not rights:
        raise TypeError("unresolve() sides must not be empty")
    _check_pair_sides("unresolve()", 'unresolve(player, "walls")', lefts, rights)
    for left in lefts:
        for right in rights:
            sys.remove_resolve_pair(left, right)


def test_collision(a, b) -> Optional[CollisionInfo]:
    """One-shot overlap test; returns ``CollisionInfo`` or ``None``.

    Args:
        a: An actor or collider.
        b: Another one.
    """
    return get_collision_system().test_collision(a, b)


def notify_group_add(item, tag: str) -> None:
    """Registry hook: a constructed item joined a group. Enroll if the tag is a pair side."""
    sys = _collision_system
    if sys is None or tag not in sys._pair_tags:
        return
    sys._try_enroll_item(item, tag=tag)


def notify_group_remove(item, tag: str) -> None:
    """Registry hook: item left a group. Drop from that tag's collider list."""
    sys = _collision_system
    if sys is None:
        return
    routed = _tag_item(item, tag)
    body = getattr(item, "_collider", None)
    if body is not None:
        # A part may have answered for ``tag``; its host body resolved there.
        sys._claimed_body_remove(tag, body)
    c = getattr(routed if routed is not None else item, "_collider", None)
    if c is None:
        return
    sys._note_left_tag(c, tag)
    sys._tag_remove(tag, c)
    sys._prune_pair_targets(c)  # D6: targets that tag implied go too
    if getattr(item, "_resolve_enrolled", False):
        # The body carries the resolve driver, even when a part answered.
        _sync_resolve_driver_for_collider(sys, body if body is not None else c)


def enroll_item_groups(item) -> None:
    """Enroll ``item`` into every pair-handler tag it currently belongs to.

    Called after construct (hitbox/frame exist) and when ``collidable = True``.
    """
    sys = _collision_system
    if sys is None or not sys._pair_tags:
        return
    groups = getattr(item, "group", None)
    if not groups:
        return
    for tag in list(groups):
        if tag in sys._pair_tags:
            sys._try_enroll_item(item, tag=tag)


def _collider_of(shape) -> Optional[Collider]:
    """Enrolled collider for ``shape``, or None if not in the system."""
    return getattr(shape, "_collider", None)


_motion_nonfinite_warned = False


def note_collider_path(shape, offsets) -> None:
    """Waypoints of a curved motion about to be noted (a fast orbit, W-T5):
    ``offsets`` are cumulative from this motion's start; they are stored from
    the frame's start (after any motion already pending)."""
    col = _collider_of(shape)
    if col is None or not offsets:
        return
    targets = [col]
    parts = shape._hitbox_parts
    if parts:
        targets.extend(p._collider for p in parts if p._collider is not None)
    for c in targets:
        c._system._snap_hot.add(c)
        bx, by = c._pending_motion_dx, c._pending_motion_dy
        path = c._pending_path
        if path is None:
            path = c._pending_path = []
            if bx != 0.0 or by != 0.0:
                path.append((bx, by))         # the straight motion before it
        path.extend((bx + ox, by + oy) for ox, oy in offsets)


def _path_breaks(c) -> List[Tuple[float, float, float]]:
    """``(fraction, x, y)`` along a collider's motion this frame, from
    ``(0, 0, 0)`` to ``(1, total)``; fractions by length (a straight motion
    is one segment)."""
    tx, ty = (c._motion_dx, c._motion_dy) if c._motion_translation else (0.0, 0.0)
    path = c._motion_path
    if not path:
        return [(0.0, 0.0, 0.0), (1.0, tx, ty)]
    pts = [(0.0, 0.0)] + list(path) + [(tx, ty)]
    lens = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        lens.append(lens[-1] + math.hypot(x1 - x0, y1 - y0))
    total = lens[-1] or 1.0
    return [(lens[k] / total, pts[k][0], pts[k][1]) for k in range(len(pts))]


def _path_at(breaks, f: float) -> Tuple[float, float]:
    for (f0, x0, y0), (f1, x1, y1) in zip(breaks, breaks[1:]):
        if f <= f1 or f1 >= 1.0:
            u = 0.0 if f1 <= f0 else (f - f0) / (f1 - f0)
            u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
            return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
    return breaks[-1][1], breaks[-1][2]


def _toi_along_paths(ca, cb, pas, pbs):
    """Earliest contact of ``ca`` and ``cb`` along this frame's motion when
    either moved along a polyline (W-T5), segment by segment in ``cb``'s end
    frame. Returns ``(t, contact, a_offset, b_offset)`` (offsets from the end
    poses at ``t``) or None."""
    ba, bb = _path_breaks(ca), _path_breaks(cb)
    tax, tay = ba[-1][1], ba[-1][2]
    tbx, tby = bb[-1][1], bb[-1][2]
    fs = sorted({f for f, _x, _y in ba} | {f for f, _x, _y in bb})

    def rel(f):
        ax, ay = _path_at(ba, f)
        bx, by = _path_at(bb, f)
        return (ax - tax) - (bx - tbx), (ay - tay) - (by - tby)

    for f0, f1 in zip(fs, fs[1:]):
        if f1 <= f0:
            continue
        r0x, r0y = rel(f0)
        r1x, r1y = rel(f1)
        mx, my = r1x - r0x, r1y - r0y
        if mx == 0.0 and my == 0.0:
            continue
        hit = _toi_prim_sets(_copy_translate(pas, r0x, r0y), pbs, mx, my)
        if hit is None or hit[1] is None:
            continue
        ts = hit[0]
        ts = 0.0 if ts < 0.0 else (1.0 if ts > 1.0 else ts)
        t = f0 + (f1 - f0) * ts
        ax, ay = _path_at(ba, t)
        bx, by = _path_at(bb, t)
        return t, hit[1], (ax - tax, ay - tay), (bx - tbx, by - tby)
    return None


def note_collider_motion(shape, dx: float, dy: float) -> None:
    """Mark this frame's translation as motion (swept). No-op if not enrolled.

    A host's hitbox parts travel with it: each registered part's collider gets
    the same delta, so a fast sprite's part is swept too (swept detection). A
    host with a registered part always has a collider (``_ensure_part_collider``
    enrolls it), so an unenrolled shape still returns at once.
    """
    global _motion_nonfinite_warned
    col = _collider_of(shape)
    if col is None:
        return
    try:
        fx = 0.0 if dx is None else float(dx)
        fy = 0.0 if dy is None else float(dy)
    except (TypeError, ValueError):
        fx, fy = float("nan"), float("nan")
    if not math.isfinite(fx) or not math.isfinite(fy):
        if not _motion_nonfinite_warned:
            _motion_nonfinite_warned = True
            warnings.warn(
                f"note_collider_motion ignored non-finite delta ({dx!r}, {dy!r})",
                RuntimeWarning,
                stacklevel=2,
            )
        return
    if fx == 0.0 and fy == 0.0:
        return
    col._pending_motion_dx += fx
    col._pending_motion_dy += fy
    hot = col._system._snap_hot
    hot.add(col)
    parts = shape._hitbox_parts     # ``Entity`` class default ``()``
    if parts:
        for part in parts:
            pc = part._collider
            if pc is not None:
                pc._pending_motion_dx += fx
                pc._pending_motion_dy += fy
                hot.add(pc)


def note_collider_placement(shape) -> None:
    """Clear pending motion so this pose write is not swept (teleport / set)."""
    col = _collider_of(shape)
    if col is None:
        return
    col._pending_motion_dx = 0.0
    col._pending_motion_dy = 0.0
    col._pending_path = None
    parts = shape._hitbox_parts
    if parts:
        for part in parts:
            pc = part._collider
            if pc is not None:
                pc._pending_motion_dx = 0.0
                pc._pending_motion_dy = 0.0
                pc._pending_path = None


def _ensure_part_collider(part) -> Collider:
    """Register a hitbox part: its own prims, its host as identity (never bound)."""
    host = part._host_ref()
    # A sprite with a hitbox in play is collidable: its body registers too
    # (no tags it does not own — it answers ``ANYTHING`` and object sides).
    if getattr(host, "_collider", None) is None:
        ensure_collider(host)
    c = Collider(part, _identity_shape=host, _register=False, _bind=False)
    c._part = part
    part._collider = c
    part._collidable = True
    c._system.register(c)
    part._ensure_auto_baked()
    return c


def _refresh_part_link(item, tag: str) -> None:
    """A named query reads a linked part's ``active`` fresh (as ``step()`` does)."""
    claims = getattr(item, "_hitbox_claims", None)
    if not claims:
        return
    part = claims.get(tag)
    if part is not None and part._active_link is not None:
        part._refresh_link()


def _tag_item(item, tag: str):
    """Who answers for ``tag`` on ``item``: a claiming hitbox part, or ``item``.

    ``None`` when a part claims the tag but is switched off (the body must
    not stand in for it).
    """
    claims = getattr(item, "_hitbox_claims", None)
    if not claims:
        return item
    part = claims.get(tag)
    if part is None:
        return item
    return part if part._active else None


def _is_part_side(target) -> bool:
    return getattr(type(target), "_is_hitbox_part", False)


def ensure_collider(shape) -> Collider:
    """Return shape's implicit collider, creating one if needed.

    Raises ``RuntimeError`` if the shape opted out via ``collidable = False``
    (sticky until ``collidable = True``). Callers that expand group tags must
    filter with ``_item_in_play`` first so opted-out members stay out.
    """
    # Backstop: every author path refuses a part earlier with its own verb.
    from .entity import refuse_part_as_actor
    refuse_part_as_actor(shape, "collision", "body")
    if getattr(shape, "_destroyed", False):
        # A destroyed actor never re-enters the index (A6: resolve_now on a
        # dead actor re-enrolled it; same class as H2 / S5 / S9).
        from .entity import _destroyed_access_message
        from .state import DestroyedError
        raise DestroyedError(_destroyed_access_message(shape, "collision"))
    if getattr(shape, "_collision_opt_out", False):
        raise RuntimeError(
            f"{shape!r} has collidable=False (collision opt-out); "
            f"set collidable=True before ensure_collider"
        )
    existing = getattr(shape, "_collider", None)
    if existing is not None:
        return existing
    if getattr(type(shape), "_is_hitbox_part", False):
        return _ensure_part_collider(shape)
    if getattr(shape, "_active", True) is False:
        # Backstop: author paths stash while parked (Actors Design — active).
        raise RuntimeError(
            f"{shape!r} is parked (active = False): it joins collision on active = True"
        )
    c = Collider(
        shape,
        _identity_shape=shape,
        _register=True,
    )
    shape._collider = c
    shape._collidable = True
    # Callbacks belong to the actor and outlive any Collider (E1).
    cbs = getattr(shape, "_collide_cbs", None)
    if cbs:
        for name, fn in cbs.items():
            setattr(c, name, fn)
    ensure_auto = getattr(shape, "_ensure_auto_baked", None)
    if callable(ensure_auto):
        ensure_auto()
    return c


def _normalize_side(side) -> List[Any]:
    """Expand one @collide side into atomic targets.

    A side is one Shape / Collider / group tag / GroupOperator / ANYTHING,
    or a list/tuple of those (one team). Strings are tags, not character sequences.
    """
    if side is ANYTHING or isinstance(side, str):
        return [side]
    if isinstance(side, (list, tuple)):
        return list(side)
    return [side]


def _is_main_hitbox(atom) -> bool:
    """``graphic.hitbox`` (the main view) — named by its Graphic, never itself."""
    from .hitbox import _MainHitbox
    return isinstance(atom, _MainHitbox)


def _is_pair_side_atom(atom) -> bool:
    """One atom of a pair side: an actor, a tag, ``group['tag']``, ``ANYTHING``."""
    if atom is ANYTHING or isinstance(atom, str):
        return True
    if isinstance(atom, bool):
        return False
    from .registry import GroupOperator
    from .entity import Entity
    from .hitbox import Hitbox
    return isinstance(atom, (Collider, GroupOperator, Entity, Hitbox))


def _check_pair_sides(call: str, example: str, *sides) -> None:
    """Refuse a side atom that names no body (``5``, ``None``, a post effect).

    Shared by ``@collide`` / ``resolve`` / ``unresolve``: a junk side would
    register a pair nothing can ever match — a silent no-op.
    """
    from .entity import refuse_part_as_actor
    for atoms in sides:
        for atom in atoms:
            refuse_part_as_actor(atom, f"a {call} side", "body")
            if _is_main_hitbox(atom):
                verb = call[:-2] if call.endswith("()") else call
                raise TypeError(
                    f"{verb}(): name the actor, not its main hitbox — {verb}(hero, …), "
                    "not hero.hitbox. The actor itself answers with its main "
                    "hitbox; an extra hitbox is named by the group it claims."
                )
            if not _is_pair_side_atom(atom):
                simple = atom is None or isinstance(atom, (int, float, complex))
                shown = f" {atom!r}" if simple else ""
                raise TypeError(
                    f"{call} side must be an actor, a group tag string, "
                    f"group['tag'], ANYTHING, or a list of those; got "
                    f"{type(atom).__name__}{shown}. Write {example}."
                )


def _collide_decorator(phase: str, left, right):
    """Shared implementation for @collide / @collide_stay / @collide_exit.

    Exactly two sides. Each may be a single target or a list/tuple
    (cross-product between the two sides).
    """
    lefts = _normalize_side(left)
    rights = _normalize_side(right)
    if not lefts or not rights:
        raise TypeError(f"@{_decorator_name(phase)} sides must not be empty")
    _check_pair_sides(
        f"@{_decorator_name(phase)}",
        f'@{_decorator_name(phase)}(player, "enemies")',
        lefts, rights,
    )
    from .registry import declare_group_names
    declare_group_names(lefts + rights)

    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role, _in_executing_class_body
        if _in_executing_class_body():
            raise TypeError(
                f"@{_decorator_name(phase)} is for script-level pairs; "
                f"use @{_with_decorator_name(phase)} on a class method "
                f"(self is the left side). In an Act class: put "
                f"@{_decorator_name(phase)} at the top of the file for the whole "
                f"game, or inside setup() for this act only."
            )
        from .validate import check_handler_arity
        check_handler_arity(func, ("me", "other", "info"), what=f"@{_decorator_name(phase)}")
        _claim_decorator_role(func, "collide")
        sys = get_collision_system()
        from . import process as _process
        in_act = _process._top_level_ended
        # All-or-nothing: every member of every side passes the layer check
        # before the first pair registers (a ui member in the last list slot
        # left the earlier pairs live: review 2026-10-09 S8-1).
        _assert_named_sides_not_parallax(lefts + rights)
        added: List[Any] = []
        try:
            for a in lefts:
                for b in rights:
                    if a is b and a is not ANYTHING and not isinstance(a, str):
                        continue
                    entry = sys.add_pair_handler(a, b, func, phase=phase)
                    added.append(entry)
                    if in_act:
                        sys._act_pair_handlers.append(entry)
        except BaseException:
            sys._drop_pair_entries(added)
            raise
        return func

    return decorator


def _decorator_name(phase: str) -> str:
    return {
        _PHASE_ENTER: "collide",
        _PHASE_STAY: "collide_stay",
        _PHASE_EXIT: "collide_exit",
    }.get(phase, "collide")


def collide(left, right):
    """Decorator: fire on collision **enter** between two sides.

    One registration opts both sides in — no need to mirror filters.

    Each side may be a Shape, Collider, ``group['name']``, a group-id ``str``,
    ``ANYTHING``, or a ``list`` / ``tuple`` of those (cross-product)::

        @collide(player, enemy)
        @collide(player, "enemies")
        @collide("player_bullets", "enemies")
        @collide(player, ANYTHING)
        @collide(player, ["enemy", "wall"])
        @collide([a1, a2], [b1, b2])
        @collide((a1, a2), (b1, b2))   # tuples work the same as lists

    Handler: ``func(me, other, info)`` with ``me`` from the left side.
    Shape-level ``on_collide`` runs first, then pair handlers.
    See also ``collide_stay``, ``collide_exit``.

    Args:
        left: An actor, tag, ``group["tag"]``, ``ANYTHING``, or a list of those.
        right: The other side, same forms.
    """
    return _collide_decorator(_PHASE_ENTER, left, right)


def collide_stay(left, right):
    """Decorator: fire every frame while sides overlap. See ``collide``.

    Args:
        left: An actor, tag, ``group["tag"]``, ``ANYTHING``, or a list of those.
        right: The other side, same forms.
    """
    return _collide_decorator(_PHASE_STAY, left, right)


def collide_exit(left, right):
    """Decorator: fire when an overlapping pair separates. See ``collide``.

    Args:
        left: An actor, tag, ``group["tag"]``, ``ANYTHING``, or a list of those.
        right: The other side, same forms.
    """
    return _collide_decorator(_PHASE_EXIT, left, right)


# Alias: explicit enter name (same as @collide)
collide_enter = collide


def _pair_method_adapter(bound: Callable) -> Callable:
    """Pair dispatch is ``(me, other, info)``; a bound method already has ``me`` as ``self``.

    Author surface is ``def fn(self, other)`` / ``fn(self, other, info)`` — not a
    second ``me`` argument. Classless ``@collide`` callbacks stay unbound.
    """
    def handler(me, other, info):
        _call(bound, other, info)
    handler._scena_collide_with = bound
    return handler


def _collide_with_decorator(phase: str, target):
    """Tag a method; construct registers ``add_pair_handler(item, target, …)``."""
    rights = _normalize_side(target)
    if not rights:
        raise TypeError(f"@{_with_decorator_name(phase)} target must not be empty")
    from .registry import declare_group_names
    declare_group_names(rights)

    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role, _in_executing_class_body
        if not _in_executing_class_body():
            raise TypeError(
                f"{_with_decorator_name(phase)} is for class methods; "
                f"use @collide(a, b) at script level."
            )
        from .validate import check_handler_arity
        check_handler_arity(
            func, ("self", "other", "info"), what=f"@{_with_decorator_name(phase)}",
        )
        _claim_decorator_role(func, "collide")
        specs = getattr(func, "_collide_with_specs", None)
        if specs is None:
            func._collide_with_specs = []
            specs = func._collide_with_specs
        specs.append((target, phase))
        return func

    return decorator


def _with_decorator_name(phase: str) -> str:
    return {
        _PHASE_ENTER: "collide_with",
        _PHASE_STAY: "collide_with_stay",
        _PHASE_EXIT: "collide_with_exit",
    }.get(phase, "collide_with")


def collide_with(target):
    """Method decorator: this instance collides **with** ``target`` (enter).

    ``target`` is one side of classless ``@collide``: tag ``str``, shape,
    ``ANYTHING``, or a ``list`` / ``tuple`` (cross-product with ``self``).
    Handler: ``fn(self, other)`` / ``fn(self, other, info)``.
    See also ``collide_with_stay``, ``collide_with_exit``.
    """
    return _collide_with_decorator(_PHASE_ENTER, target)


def collide_with_stay(target):
    """Method decorator: fire every frame while overlapping ``target``."""
    return _collide_with_decorator(_PHASE_STAY, target)


def collide_with_exit(target):
    """Method decorator: fire when overlap with ``target`` ends."""
    return _collide_with_decorator(_PHASE_EXIT, target)
