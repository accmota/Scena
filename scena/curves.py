"""Pure curve kernels for Track: Catmull-Rom → polyline, arc-length, sample.

No Container / framework imports. Samples are plain Python floats.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from typing import List, Optional, Sequence, Tuple

Point2 = Tuple[float, float]

# Centripetal Catmull-Rom (visually stable, avoids cusps on uneven spacing).
_ALPHA = 0.5

SAMPLES_HIGH = 16
SAMPLES_LOW = 5


def samples_per_segment_for(quality: str) -> int:
    if quality == "low":
        return SAMPLES_LOW
    return SAMPLES_HIGH


def _as_xy(p: Sequence[float]) -> Point2:
    return (float(p[0]), float(p[1]))


def _hypot(dx: float, dy: float) -> float:
    return math.hypot(dx, dy)


def _tj(ti: float, pi: Point2, pj: Point2, alpha: float) -> float:
    d = _hypot(pj[0] - pi[0], pj[1] - pi[1])
    if d <= 0.0:
        return ti + 1e-12
    return ti + d ** alpha


def catmull_rom_to_bezier(
    p0: Point2,
    p1: Point2,
    p2: Point2,
    p3: Point2,
    *,
    smooth: float = 1.0,
    alpha: float = _ALPHA,
) -> Tuple[Point2, Point2, Point2, Point2]:
    """Centripetal Catmull-Rom segment P1→P2 as a cubic Bezier.

    ``smooth`` scales the tangents (0 = straight P1→P2, 1 = standard, >1 = overshoot).
    """
    sm = float(smooth)
    t0 = 0.0
    t1 = _tj(t0, p0, p1, alpha)
    t2 = _tj(t1, p1, p2, alpha)
    t3 = _tj(t2, p2, p3, alpha)
    dt = t2 - t1
    if dt <= 0.0:
        return p1, p1, p2, p2
    d0 = t2 - t0
    d1 = t3 - t1
    if d0 <= 0.0:
        d0 = 1e-12
    if d1 <= 0.0:
        d1 = 1e-12
    k = (dt / 3.0) * sm
    b1 = (
        p1[0] + (p2[0] - p0[0]) / d0 * k,
        p1[1] + (p2[1] - p0[1]) / d0 * k,
    )
    b2 = (
        p2[0] - (p3[0] - p1[0]) / d1 * k,
        p2[1] - (p3[1] - p1[1]) / d1 * k,
    )
    return p1, b1, b2, p2


def eval_cubic(
    b0: Point2, b1: Point2, b2: Point2, b3: Point2, t: float
) -> Point2:
    u = 1.0 - t
    uu = u * u
    tt = t * t
    uuu = uu * u
    ttt = tt * t
    return (
        uuu * b0[0] + 3.0 * uu * t * b1[0] + 3.0 * u * tt * b2[0] + ttt * b3[0],
        uuu * b0[1] + 3.0 * uu * t * b1[1] + 3.0 * u * tt * b2[1] + ttt * b3[1],
    )


def flatten_bezier(
    b0: Point2,
    b1: Point2,
    b2: Point2,
    b3: Point2,
    samples_per_segment: int,
    *,
    include_start: bool,
) -> List[Point2]:
    """Uniform-t samples of a cubic. ``include_start`` emits t=0."""
    n = max(1, int(samples_per_segment))
    out: List[Point2] = []
    start = 0 if include_start else 1
    for i in range(start, n + 1):
        t = i / n
        out.append(eval_cubic(b0, b1, b2, b3, t))
    return out


def _phantom_open(points: Sequence[Point2]) -> Tuple[Point2, Point2]:
    """Reflected endpoints so an open spline meets P0 / P[-1] with a natural tangent."""
    p0, p1 = points[0], points[1]
    pn, pm = points[-1], points[-2]
    before = (2.0 * p0[0] - p1[0], 2.0 * p0[1] - p1[1])
    after = (2.0 * pn[0] - pm[0], 2.0 * pn[1] - pm[1])
    return before, after


def flatten_controls(
    points: Sequence[Sequence[float]],
    *,
    closed: bool,
    smooth: float,
    samples_per_segment: int,
) -> Tuple[List[float], List[float]]:
    """Control points → polyline (still in input coordinates).

    ``smooth=0`` (or False) is the straight polyline; no cubic work.
    """
    pts = [_as_xy(p) for p in points]
    n = len(pts)
    if n == 0:
        return [], []
    if n == 1:
        return [pts[0][0]], [pts[0][1]]

    sm = float(smooth)
    if sm <= 0.0:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return xs, ys

    n_seg = n if closed else n - 1
    sps = max(1, int(samples_per_segment))
    out: List[Point2] = []
    for i in range(n_seg):
        if closed:
            p0 = pts[(i - 1) % n]
            p1 = pts[i]
            p2 = pts[(i + 1) % n]
            p3 = pts[(i + 2) % n]
        else:
            before, after = _phantom_open(pts)
            p1 = pts[i]
            p2 = pts[i + 1]
            p0 = before if i == 0 else pts[i - 1]
            p3 = after if i + 2 >= n else pts[i + 2]
        b0, b1, b2, b3 = catmull_rom_to_bezier(p0, p1, p2, p3, smooth=sm)
        chunk = flatten_bezier(b0, b1, b2, b3, sps, include_start=(i == 0))
        out.extend(chunk)
    return [p[0] for p in out], [p[1] for p in out]


def centroid(xs: Sequence[float], ys: Sequence[float]) -> Point2:
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    return (sum(xs) / n, sum(ys) / n)


def to_local(
    xs: Sequence[float], ys: Sequence[float]
) -> Tuple[List[float], List[float], float, float]:
    """Shift so the vertex-average centroid is the origin. Returns (lxs, lys, cx, cy)."""
    cx, cy = centroid(xs, ys)
    return [float(x) - cx for x in xs], [float(y) - cy for y in ys], cx, cy


def arc_length_table(
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    closed: bool,
) -> List[float]:
    """Cumulative arc length. Closed paths append the wrap-around segment.

    ``s[0] == 0``. ``s[-1]`` is the total travelled length. For a closed path
    with n vertices, ``len(s) == n + 1``.
    """
    n = len(xs)
    if n == 0:
        return [0.0]
    if n == 1:
        return [0.0]
    s: List[float] = [0.0]
    for i in range(1, n):
        s.append(s[-1] + _hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    if closed and n >= 2:
        s.append(s[-1] + _hypot(xs[0] - xs[-1], ys[0] - ys[-1]))
    return s


def _segment_point(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    i: int,
    target: float,
    *,
    closed: bool,
) -> Point2:
    """Lerp on table segment ``i`` (from vertex i-1 to vertex i, or wrap)."""
    n = len(xs)
    s0 = s[i - 1]
    s1 = s[i]
    ds = s1 - s0
    t = 0.0 if ds <= 1e-18 else (target - s0) / ds
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    if closed and i == n:
        x0, y0 = xs[n - 1], ys[n - 1]
        x1, y1 = xs[0], ys[0]
    else:
        x0, y0 = xs[i - 1], ys[i - 1]
        x1, y1 = xs[i], ys[i]
    return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def _locate(s: Sequence[float], target: float) -> int:
    """Smallest i such that s[i] >= target, in 1..len(s)-1."""
    lo = 1
    hi = len(s) - 1
    if hi < 1:
        return 1
    while lo < hi:
        mid = (lo + hi) // 2
        if s[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def wrap_u(u: float, *, closed: bool) -> float:
    u = float(u)
    if closed:
        u = u % 1.0
        if u < 0.0:
            u += 1.0
        return u
    if u < 0.0:
        return 0.0
    if u > 1.0:
        return 1.0
    return u


def sample(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    u: float,
    *,
    closed: bool = False,
    reversed: bool = False,
) -> Point2:
    """Constant-speed sample. ``u`` in [0, 1] (wrapped if closed)."""
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (float(xs[0]), float(ys[0]))
    total = s[-1] if s else 0.0
    u = wrap_u(u, closed=closed)
    if reversed:
        u = wrap_u(1.0 - u, closed=closed)
    if total <= 1e-18:
        return (float(xs[0]), float(ys[0]))
    # Closed: u=1 is the same point as u=0 (end of wrap == start).
    if closed and (u <= 0.0 or u >= 1.0 - 1e-15):
        return (float(xs[0]), float(ys[0]))
    target = u * total
    i = _locate(s, target)
    return _segment_point(xs, ys, s, i, target, closed=closed)


def sample_tangent(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    u: float,
    *,
    closed: bool = False,
    reversed: bool = False,
) -> Point2:
    """Unit tangent in the direction of travel. (0, 0) if degenerate."""
    n = len(xs)
    if n < 2:
        return (0.0, 0.0)
    total = s[-1] if s else 0.0
    if total <= 1e-18:
        return (0.0, 0.0)
    u = wrap_u(u, closed=closed)
    if reversed:
        u = wrap_u(1.0 - u, closed=closed)
    # Finite difference along the table, one step of ~0.5% of length (min 1e-6).
    du = 1.0 / max(32.0, float(len(s)) * 2.0)
    u1 = wrap_u(u + du, closed=closed) if closed else min(1.0, u + du)
    u0 = wrap_u(u - du, closed=closed) if closed else max(0.0, u - du)
    if not closed and u >= 1.0 - 1e-12:
        u0, u1 = max(0.0, 1.0 - du), 1.0
    elif not closed and u <= 1e-12:
        u0, u1 = 0.0, min(1.0, du)
    p0 = sample(xs, ys, s, u0, closed=closed, reversed=False)
    p1 = sample(xs, ys, s, u1, closed=closed, reversed=False)
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    mag = _hypot(tx, ty)
    if mag <= 1e-18:
        return (0.0, 0.0)
    tx, ty = tx / mag, ty / mag
    if reversed:
        tx, ty = -tx, -ty
    return (tx, ty)


def sample_angle(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    u: float,
    *,
    closed: bool = False,
    reversed: bool = False,
) -> float:
    """Travel heading in degrees (CCW from +x). 0 if no tangent."""
    tx, ty = sample_tangent(xs, ys, s, u, closed=closed, reversed=reversed)
    if tx == 0.0 and ty == 0.0:
        return 0.0
    return math.degrees(math.atan2(ty, tx))


def sample_span(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    a: float,
    b: float,
    *,
    closed: bool = False,
    reversed: bool = False,
    n: int = 32,
) -> List[Point2]:
    """``n`` samples from u=a to u=b (inclusive)."""
    n = max(2, int(n))
    out: List[Point2] = []
    for i in range(n):
        t = i / (n - 1)
        u = a + (b - a) * t
        out.append(sample(xs, ys, s, u, closed=closed, reversed=reversed))
    return out


def _clamp01(u: float) -> float:
    u = float(u)
    if u < 0.0:
        return 0.0
    if u > 1.0:
        return 1.0
    return u


def _almost_same(p: Point2, q: Point2, eps: float = 1e-9) -> bool:
    return abs(p[0] - q[0]) <= eps and abs(p[1] - q[1]) <= eps


def _host_span(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    u0: float,
    u1: float,
    *,
    closed: bool,
) -> List[Point2]:
    """Open polyline covering host u in ``[u0, u1]`` with ``u0 < u1``."""
    n = len(xs)
    if n < 2:
        return []
    total = s[-1] if s else 0.0
    if total <= 1e-18:
        return []
    u0 = _clamp01(u0)
    u1 = _clamp01(u1)
    if u1 <= u0 + 1e-15:
        return []
    start = sample(xs, ys, s, u0, closed=closed, reversed=False)
    end = sample(xs, ys, s, u1, closed=closed, reversed=False)
    out: List[Point2] = [start]
    t0 = u0 * total
    t1 = u1 * total
    # Interior vertices whose arc-length is strictly inside (t0, t1), found
    # by bisection and copied in one pass: a growing ``end`` on a long track
    # walked the whole table through a helper call a vertex (~100 µs a
    # frame for 400 points; showcase D7).
    lo = bisect_right(s, t0 + 1e-12, 1)
    hi = bisect_left(s, t1 - 1e-12, lo)
    wrap = closed and hi > n           # k == n is the closing vertex (xs[0])
    px, py = start
    eps = 1e-9
    append = out.append
    for x, y in zip(xs[lo:min(hi, n)], ys[lo:min(hi, n)]):
        x = float(x)
        y = float(y)
        if abs(x - px) > eps or abs(y - py) > eps:
            append((x, y))
            px, py = x, y
    if wrap:
        pt = (float(xs[0]), float(ys[0]))
        if not _almost_same(out[-1], pt):
            append(pt)
    if not _almost_same(out[-1], end):
        out.append(end)
    return out


def subpolyline(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    a: float,
    b: float,
    *,
    closed: bool = False,
    reversed: bool = False,
) -> List[List[Point2]]:
    """Stroke contours for a u-window ``[a, b]`` (clamped to 0..1).

    Each contour is an open polyline in table space. Empty when there is
    nothing to stroke (``a == b``, or ``a > b`` on an open path). Closed
    paths with ``a > b`` wrap: ``[a, 1]`` then ``[0, b]``.
    """
    a = _clamp01(a)
    b = _clamp01(b)
    if abs(a - b) <= 1e-15:
        return []

    def _emit(u0: float, u1: float) -> List[List[Point2]]:
        if reversed:
            pts = _host_span(xs, ys, s, 1.0 - u1, 1.0 - u0, closed=closed)
            pts.reverse()
        else:
            pts = _host_span(xs, ys, s, u0, u1, closed=closed)
        if len(pts) < 2:
            return []
        return [pts]

    if a < b:
        return _emit(a, b)
    if not closed:
        return []
    return _emit(a, 1.0) + _emit(0.0, b)


def build_table(
    points: Sequence[Sequence[float]],
    *,
    closed: bool,
    smooth: float,
    samples_per_segment: int,
) -> Tuple[List[float], List[float], List[float]]:
    """Flatten + arc-length. Returns local-unshifted (xs, ys, s)."""
    xs, ys = flatten_controls(
        points, closed=closed, smooth=smooth, samples_per_segment=samples_per_segment,
    )
    s = arc_length_table(xs, ys, closed=closed)
    return xs, ys, s


def normals_of(
    xs: Sequence[float], ys: Sequence[float], *, closed: bool
) -> List[Point2]:
    """Unit left-normals at each vertex (CCW: (-ty, tx) of the outgoing segment)."""
    n = len(xs)
    out: List[Point2] = []
    if n == 0:
        return out
    if n == 1:
        return [(0.0, 1.0)]
    for i in range(n):
        if closed:
            j = (i + 1) % n
            k = (i - 1) % n
            tx = xs[j] - xs[k]
            ty = ys[j] - ys[k]
        else:
            if i == 0:
                tx, ty = xs[1] - xs[0], ys[1] - ys[0]
            elif i == n - 1:
                tx, ty = xs[n - 1] - xs[n - 2], ys[n - 1] - ys[n - 2]
            else:
                tx = xs[i + 1] - xs[i - 1]
                ty = ys[i + 1] - ys[i - 1]
        mag = _hypot(tx, ty)
        if mag <= 1e-18:
            out.append((0.0, 1.0))
        else:
            # Left normal of travel direction.
            out.append((-ty / mag, tx / mag))
    return out


def apply_offsets(
    xs: Sequence[float],
    ys: Sequence[float],
    offsets: Sequence[float],
    *,
    closed: bool,
) -> Tuple[List[float], List[float]]:
    """Offset each vertex along its left-normal by ``offsets[i]``."""
    nrm = normals_of(xs, ys, closed=closed)
    n = len(xs)
    ox, oy = [], []
    for i in range(n):
        d = float(offsets[i]) if i < len(offsets) else 0.0
        nx, ny = nrm[i]
        ox.append(float(xs[i]) + nx * d)
        oy.append(float(ys[i]) + ny * d)
    return ox, oy


def zigzag_amounts(
    n: int,
    *,
    amount: float,
    waves: float,
    kind: str,
    closed: bool,
) -> List[float]:
    """Per-vertex normal offset: sine (rounded) or saw (sharp)."""
    if n <= 0:
        return []
    amt = float(amount)
    w = float(waves)
    out: List[float] = []
    denom = n if closed else max(1, n - 1)
    for i in range(n):
        t = i / denom
        phase = t * w * 2.0 * math.pi
        if kind == "saw":
            # [-1, 1] sawtooth
            frac = (t * w) % 1.0
            v = 2.0 * frac - 1.0
        else:
            v = math.sin(phase)
        out.append(amt * v)
    return out


def orbit_displacements(
    xs: Sequence[float],
    ys: Sequence[float],
    s: Sequence[float],
    *,
    radius: float,
    laps: float,
    closed: bool,
) -> Tuple[List[float], List[float]]:
    """Add a rotating displacement of ``radius`` that completes ``laps`` over the path."""
    n = len(xs)
    total = s[-1] if s else 0.0
    r = float(radius)
    laps_f = float(laps)
    ox, oy = [], []
    for i in range(n):
        # Parameterize by arc length so the moon stays even-speed on the base.
        if closed:
            # Vertex i maps to s[i] / total, with last vertex not yet the wrap.
            si = s[i] if i < len(s) else total
        else:
            si = s[i] if i < len(s) else total
        u = 0.0 if total <= 1e-18 else si / total
        a = u * laps_f * 2.0 * math.pi
        ox.append(float(xs[i]) + r * math.cos(a))
        oy.append(float(ys[i]) + r * math.sin(a))
    return ox, oy


def wander_offsets(n: int, *, amount: float, seed: int) -> List[float]:
    """Reproducible hashed noise in [-amount, amount] per vertex."""
    amt = float(amount)
    # Tiny integer hash (xorshift-ish) — stable across runs, no random module.
    out: List[float] = []
    h = int(seed) & 0xFFFFFFFF
    for i in range(n):
        h = (h ^ (i * 0x9E3779B9)) & 0xFFFFFFFF
        h = (h * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= (h >> 13)
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= (h >> 16)
        u = (h & 0xFFFFFF) / float(0xFFFFFF)  # [0, 1]
        out.append(amt * (2.0 * u - 1.0))
    return out


def densify_polyline(
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    closed: bool,
    n: int,
) -> Tuple[List[float], List[float]]:
    """Resample a polyline to ``n`` vertices (closed: n unique verts, no dup)."""
    n = max(2, int(n))
    s = arc_length_table(xs, ys, closed=closed)
    if len(xs) >= n:
        return [float(x) for x in xs], [float(y) for y in ys]
    outx: List[float] = []
    outy: List[float] = []
    denom = n if closed else n - 1
    for i in range(n):
        u = 0.0 if denom <= 0 else i / denom
        x, y = sample(xs, ys, s, u, closed=closed)
        outx.append(x)
        outy.append(y)
    return outx, outy


def min_samples_for_modifiers(
    base_sps: int,
    *,
    n_ctrl: int,
    closed: bool,
    zigzag_waves: Optional[float] = None,
    orbit_laps: Optional[float] = None,
) -> int:
    """Raise samples-per-segment so a wiggle is actually resolved."""
    sps = max(1, int(base_sps))
    n_seg = max(1, n_ctrl if closed else max(1, n_ctrl - 1))
    need = 0.0
    if zigzag_waves is not None:
        # ~8 samples per wave across the whole path.
        need = max(need, float(zigzag_waves) * 8.0)
    if orbit_laps is not None:
        need = max(need, abs(float(orbit_laps)) * 8.0)
    if need <= 0.0:
        return sps
    per = int(math.ceil(need / n_seg))
    return max(sps, per)


def apply_pose(
    lx: float,
    ly: float,
    *,
    cx: float,
    cy: float,
    rotation_deg: float,
    scale: float,
) -> Point2:
    """Local (centroid-relative) → world."""
    sc = float(scale)
    x, y = lx * sc, ly * sc
    rot = float(rotation_deg)
    if rot:
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        x, y = x * c - y * s, x * s + y * c
    return (float(cx) + x, float(cy) + y)


def apply_pose_vec(
    vx: float,
    vy: float,
    *,
    rotation_deg: float,
    scale: float,
) -> Point2:
    """Rotate/scale a direction (no translation). Does not re-normalize."""
    sc = float(scale)
    x, y = vx * sc, vy * sc
    rot = float(rotation_deg)
    if rot:
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        x, y = x * c - y * s, x * s + y * c
    return (x, y)
