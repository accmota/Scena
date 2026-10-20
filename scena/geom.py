"""Author geometry queries: outline crossings and filled projection.

Public surface (exported from ``scena``):

- ``intersections(a, b)`` → list of ``(x, y)`` outline crossings (empty if none)
- ``intersection(a, b, i=0)`` → always one ``(x, y)`` (slot for constructors / ``@=``)
- ``closest_point(shape, p)`` → always one ``(x, y)`` on the filled shape

Allowlist: the types returned by ``_allowlist_types()`` (single source — do not
copy the list into this docstring). Math runs on bare floats. Returns tuples —
never Point objects.
Position helpers (``distance``, ``heading``, ``middle_point``, ``nearest``) live in
``scena/shapes.py``.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

Point2 = Tuple[float, float]
Segment = Tuple[float, float, float, float]  # x1, y1, x2, y2

_EPS = 1e-9
_DEDUP_EPS = 1e-6

def _allowlist_types():
    """Shapes ``intersections`` / ``closest_point`` accept.

    Names in ``TypeError`` text, Shapes Design, and the Guia "Permitidos" row
    are checked against this tuple (``tests/test_geom.py``, ``TestAllowlistDocs``).
    """
    from .box import Box
    from .shapes import (
        Circle, Concave, Ellipse, Line, Polygon, Rect,
        RegularPolygon, Square, Triangle,
    )
    return (
        Line, Circle, Ellipse, Rect, Square, Concave,
        Polygon, RegularPolygon, Triangle, Box,
    )


def _require_allowed(obj: Any, *, fn: str) -> None:
    allowed = _allowlist_types()
    if not isinstance(obj, allowed):
        names = ", ".join(t.__name__ for t in allowed)
        hint = ""
        from .track import Track
        if isinstance(obj, Track):
            # A curve (persona probes round 2, R2-5: the message gave no route).
            hint = (". A Track is a path: cross it piece by piece with Lines between "
                    "its points (pts = track.spaced_points(64); "
                    "Line(p1=a, p2=b) for a, b in zip(pts, pts[1:])), or use "
                    "Polygon(points=pts) for a closed one")
        raise TypeError(
            f"{fn}() supports {names}; got {type(obj).__name__}{hint}"
        )


def _bare_xy(obj) -> Point2:
    from .shapes import get_xy
    return get_xy(obj, bare=True)


def _bare_num(v) -> float:
    from .shapes import _bare_num as bn
    return bn(v)


# ---------------------------------------------------------------------------
# Low-level kernels (bare floats)
# ---------------------------------------------------------------------------

def _closest_on_segment(
    px: float, py: float,
    ax: float, ay: float, bx: float, by: float,
) -> Point2:
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom < 1e-18:
        return (ax, ay)
    t = ((px - ax) * abx + (py - ay) * aby) / denom
    t = max(0.0, min(1.0, t))
    return (ax + t * abx, ay + t * aby)


def _point_in_polygon_xy(x: float, y: float, verts: Sequence[Point2]) -> bool:
    inside = False
    n = len(verts)
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def _seg_seg(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> Optional[Point2]:
    """Proper / endpoint segment intersection. Collinear overlap → None."""
    abx, aby = bx - ax, by - ay
    cdx, cdy = dx - cx, dy - cy
    den = abx * cdy - aby * cdx
    acx, acy = cx - ax, cy - ay
    if abs(den) < _EPS:
        # Parallel / collinear — never return a continuum.
        return None
    t = (acx * cdy - acy * cdx) / den
    u = (acx * aby - acy * abx) / den
    if t < -_EPS or t > 1.0 + _EPS or u < -_EPS or u > 1.0 + _EPS:
        return None
    t = max(0.0, min(1.0, t))
    return (ax + t * abx, ay + t * aby)


def _seg_circle(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, r: float,
) -> List[Point2]:
    """Segment × circle intersections; ``t ∈ [0, 1]``."""
    r = abs(r)
    if r < _EPS:
        # Degenerate circle: hit only if the centre lies on the segment.
        qx, qy = _closest_on_segment(cx, cy, ax, ay, bx, by)
        if _sq(qx - cx) + _sq(qy - cy) <= _DEDUP_EPS ** 2:
            return [(cx, cy)]
        return []
    dx, dy = bx - ax, by - ay
    fx, fy = ax - cx, ay - cy
    a = dx * dx + dy * dy
    if a < 1e-18:
        # Degenerate segment → point
        if abs(math.hypot(fx, fy) - r) <= _DEDUP_EPS:
            return [(ax, ay)]
        return []
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4.0 * a * c
    if disc < -_EPS:
        return []
    if disc < 0.0:
        disc = 0.0
    sqrt_d = math.sqrt(disc)
    out: List[Point2] = []
    for sign in (-1.0, 1.0):
        t = (-b + sign * sqrt_d) / (2.0 * a)
        if -_EPS <= t <= 1.0 + _EPS:
            t = max(0.0, min(1.0, t))
            out.append((ax + t * dx, ay + t * dy))
    return _dedupe(out)


def _circle_circle(
    ax: float, ay: float, ar: float,
    bx: float, by: float, br: float,
) -> List[Point2]:
    ar, br = abs(ar), abs(br)
    dx, dy = bx - ax, by - ay
    d = math.hypot(dx, dy)
    if d < _EPS:
        # Concentric — infinitely many or none; never enumerate.
        return []
    if d > ar + br + _DEDUP_EPS:
        return []
    if d < abs(ar - br) - _DEDUP_EPS:
        return []
    # a = distance from a to the chord midline along centres
    a = (ar * ar - br * br + d * d) / (2.0 * d)
    h2 = ar * ar - a * a
    if h2 < -_EPS:
        return []
    if h2 < 0.0:
        h2 = 0.0
    h = math.sqrt(h2)
    ux, uy = dx / d, dy / d
    mx, my = ax + a * ux, ay + a * uy
    if h < _DEDUP_EPS:
        return [(mx, my)]
    px, py = -uy * h, ux * h
    p1 = (mx + px, my + py)
    p2 = (mx - px, my - py)
    # Left then right of a→b (positive cross = left in y-up CCW).
    c1 = ux * (p1[1] - ay) - uy * (p1[0] - ax)
    c2 = ux * (p2[1] - ay) - uy * (p2[0] - ax)
    if c1 >= c2:
        return [p1, p2]
    return [p2, p1]


def _dedupe(pts: Sequence[Point2]) -> List[Point2]:
    out: List[Point2] = []
    for p in pts:
        if any(
            abs(p[0] - q[0]) <= _DEDUP_EPS and abs(p[1] - q[1]) <= _DEDUP_EPS
            for q in out
        ):
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Conics (Circle and Ellipse): (cx, cy, semi_a, semi_b, ang_deg)
# ---------------------------------------------------------------------------

# θ samples for ellipse–ellipse / circle–ellipse. At most four real crossings.
_CONIC_SAMPLES = 96

Conic = Tuple[float, float, float, float, float]


def _is_conic(shape) -> bool:
    from .shapes import Circle, Ellipse
    return isinstance(shape, (Circle, Ellipse))


def _conic_params(shape) -> Conic:
    """``(cx, cy, a, b, ang_deg)`` with non-negative semi-axes.

    Circle is the special case ``a == b == radius``, ``ang == 0``. Ellipse
    reads ``_oriented_frame`` (non-negative extents; ``FROM_RECT`` and a
    negative stored axis are already folded in).
    """
    from .shapes import Circle
    if isinstance(shape, Circle):
        cx, cy, r = _circle_params(shape)
        return (cx, cy, r, r, 0.0)
    cx, cy, w, h, ang = shape._oriented_frame()
    return (cx, cy, abs(w) * 0.5, abs(h) * 0.5, float(ang))


def _conic_collapsed(conic: Conic) -> bool:
    return conic[2] < _EPS or conic[3] < _EPS


def _to_local(conic: Conic, x: float, y: float) -> Point2:
    """World → ellipse frame (rotation undone, axes not yet scaled)."""
    cx, cy, _a, _b, ang = conic
    dx, dy = x - cx, y - cy
    rad = math.radians(float(-ang))
    c, s = math.cos(rad), math.sin(rad)
    return (dx * c - dy * s, dx * s + dy * c)


def _from_local(conic: Conic, lx: float, ly: float) -> Point2:
    cx, cy, _a, _b, ang = conic
    rad = math.radians(float(ang))
    c, s = math.cos(rad), math.sin(rad)
    return (cx + lx * c - ly * s, cy + lx * s + ly * c)


def _to_unit(conic: Conic, x: float, y: float) -> Point2:
    """World → unit circle. Affine, so a segment's ``t`` is unchanged."""
    _cx, _cy, a, b, _ang = conic
    lx, ly = _to_local(conic, x, y)
    return (lx / a, ly / b)


def _from_unit(conic: Conic, u: float, v: float) -> Point2:
    _cx, _cy, a, b, _ang = conic
    return _from_local(conic, u * a, v * b)


def _conic_point(conic: Conic, theta: float) -> Point2:
    a, b = conic[2], conic[3]
    return _from_local(conic, a * math.cos(theta), b * math.sin(theta))


def _collapsed_axis_segment(conic: Conic) -> Segment:
    """Major-axis segment. Both axes ~0 → a point segment at the centre."""
    cx, cy, a, b, ang = conic
    rad = math.radians(float(ang))
    c, s = math.cos(rad), math.sin(rad)
    if a >= b:
        dx, dy = a * c, a * s
    else:
        # Local +y. ``_from_local(0, b) - centre``.
        dx, dy = -b * s, b * c
    return (cx - dx, cy - dy, cx + dx, cy + dy)


def _segment_degenerate(seg: Segment) -> bool:
    return math.hypot(seg[2] - seg[0], seg[3] - seg[1]) < _EPS


def _conic_aabb(conic: Conic) -> Tuple[float, float, float, float]:
    cx, cy, a, b, ang = conic
    rad = math.radians(float(ang))
    c, s = math.cos(rad), math.sin(rad)
    hw = math.hypot(a * c, b * s)
    hh = math.hypot(a * s, b * c)
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def _aabb_separated(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    pad: float,
) -> bool:
    return a[2] < b[0] - pad or b[2] < a[0] - pad or a[3] < b[1] - pad or b[3] < a[1] - pad


def _seg_conic(seg: Segment, conic: Conic) -> List[Point2]:
    """Segment × ellipse, exact: the segment is a segment in the unit frame."""
    ax, ay, bx, by = seg
    u1, v1 = _to_unit(conic, ax, ay)
    u2, v2 = _to_unit(conic, bx, by)
    return [_from_unit(conic, u, v) for u, v in _seg_circle(u1, v1, u2, v2, 0.0, 0.0, 1.0)]


def _point_hits_segments(px: float, py: float, segs: Sequence[Segment]) -> List[Point2]:
    for x1, y1, x2, y2 in segs:
        qx, qy = _closest_on_segment(px, py, x1, y1, x2, y2)
        if _sq(qx - px) + _sq(qy - py) <= _DEDUP_EPS ** 2:
            return [(px, py)]
    return []


def _intersect_conic_segments(conic: Conic, segs: Sequence[Segment]) -> List[Point2]:
    if _conic_collapsed(conic):
        seg = _collapsed_axis_segment(conic)
        if _segment_degenerate(seg):
            return _point_hits_segments(seg[0], seg[1], segs)
        hits: List[Point2] = []
        for other in segs:
            p = _seg_seg(seg[0], seg[1], seg[2], seg[3], other[0], other[1], other[2], other[3])
            if p is not None:
                hits.append(p)
        return _dedupe(hits)
    hits = []
    for other in segs:
        hits.extend(_seg_conic(other, conic))
    return _dedupe(hits)


def _unit_tol(dst: Conic) -> float:
    """``|q|² − 1`` tolerance matching about ``_DEDUP_EPS`` in world units."""
    scale = min(dst[2], dst[3])
    if scale < _EPS:
        return 1.0
    return max(2.0 * _DEDUP_EPS / scale, 1e-12)


def _f_theta(src: Conic, dst: Conic, theta: float) -> float:
    x, y = _conic_point(src, theta)
    u, v = _to_unit(dst, x, y)
    return u * u + v * v - 1.0


def _bisect_root(
    src: Conic, dst: Conic, t0: float, t1: float, f0: float, f1: float,
) -> float:
    for _ in range(50):
        tm = 0.5 * (t0 + t1)
        fm = _f_theta(src, dst, tm)
        if f0 * fm <= 0.0:
            t1, f1 = tm, fm
        else:
            t0, f0 = tm, fm
    return 0.5 * (t0 + t1)


def _refine_extremum(
    src: Conic, dst: Conic, t0: float, t1: float, *, want_min: bool,
) -> float:
    """Golden-section min (or max) of ``f`` on ``[t0, t1]``. ``f`` is 2π-periodic."""
    invphi = (math.sqrt(5.0) - 1.0) / 2.0

    def g(th: float) -> float:
        v = _f_theta(src, dst, th)
        return v if want_min else -v

    a, b = t0, t1
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    fc, fd = g(c), g(d)
    for _ in range(40):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = g(c)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = g(d)
    return 0.5 * (a + b)


def _sample_conic_against(src: Conic, dst: Conic) -> List[Point2]:
    """Crossings of ``src``'s outline with ``dst``. At most four; coincident → ``[]``."""
    n = _CONIC_SAMPLES
    dth = 2.0 * math.pi / n
    thetas = [dth * i for i in range(n)]
    fs = [_f_theta(src, dst, th) for th in thetas]
    tol = _unit_tol(dst)
    # Identical (or overlapping) outlines: a continuum, same policy as concentric circles.
    if sum(abs(f) <= tol for f in fs) > 4:
        return []

    hits: List[Point2] = []
    for i in range(n):
        j = (i + 1) % n
        f0, f1 = fs[i], fs[j]
        t0 = thetas[i]
        t1 = thetas[j] if j > i else thetas[j] + 2.0 * math.pi
        if abs(f0) <= tol:
            hits.append(_conic_point(src, t0))
        if f0 * f1 < 0.0:
            hits.append(_conic_point(src, _bisect_root(src, dst, t0, t1, f0, f1)))
        elif abs(f0) > tol and min(abs(f0), abs(f1)) < 0.5:
            tm = 0.5 * (t0 + t1)
            fm = _f_theta(src, dst, tm)
            if f0 * fm < 0.0:
                hits.append(_conic_point(src, _bisect_root(src, dst, t0, tm, f0, fm)))
                hits.append(_conic_point(src, _bisect_root(src, dst, tm, t1, fm, f1)))

    # Tangency has no sign change: a local min of f (external) or max (internal) at 0.
    gate = 0.5
    for i in range(n):
        f_prev = fs[(i - 1) % n]
        f_here = fs[i]
        f_next = fs[(i + 1) % n]
        if abs(f_here) > gate:
            continue
        center = thetas[i]
        if f_here <= f_prev and f_here <= f_next:
            th = _refine_extremum(src, dst, center - dth, center + dth, want_min=True)
            if abs(_f_theta(src, dst, th)) <= tol:
                hits.append(_conic_point(src, th))
        if f_here >= f_prev and f_here >= f_next:
            th = _refine_extremum(src, dst, center - dth, center + dth, want_min=False)
            if abs(_f_theta(src, dst, th)) <= tol:
                hits.append(_conic_point(src, th))

    hits = _dedupe(hits)
    # More than four distinct points means the outlines overlap (a continuum).
    if len(hits) > 4:
        return []
    return hits


def _conic_conic(a: Conic, b: Conic) -> List[Point2]:
    """Circle × ellipse and ellipse × ellipse. Circle × circle stays closed-form."""
    if _conic_collapsed(a) or _conic_collapsed(b):
        return _collapsed_conic_intersect(a, b)
    if _aabb_separated(_conic_aabb(a), _conic_aabb(b), _DEDUP_EPS):
        return []
    # Sample the smaller outline so a short partner is not stepped over.
    if (a[2] + a[3]) <= (b[2] + b[3]):
        return _sample_conic_against(a, b)
    return _sample_conic_against(b, a)


def _collapsed_conic_intersect(a: Conic, b: Conic) -> List[Point2]:
    if _conic_collapsed(a) and _conic_collapsed(b):
        sa, sb = _collapsed_axis_segment(a), _collapsed_axis_segment(b)
        if _segment_degenerate(sa):
            return _point_hits_segments(sa[0], sa[1], [sb])
        if _segment_degenerate(sb):
            return _point_hits_segments(sb[0], sb[1], [sa])
        p = _seg_seg(sa[0], sa[1], sa[2], sa[3], sb[0], sb[1], sb[2], sb[3])
        return [p] if p is not None else []
    if _conic_collapsed(a):
        return _intersect_conic_segments(b, [_collapsed_axis_segment(a)])
    return _intersect_conic_segments(a, [_collapsed_axis_segment(b)])


def _closest_on_ellipse_local(a: float, b: float, px: float, py: float) -> Point2:
    """Closest point on ``x²/a² + y²/b² = 1`` to a local-frame query.

    Eberly's formulation: bisect the unique root ``t > 0`` of
    ``F(t) = (a U / (t + a²))² + (b V / (t + b²))² − 1`` for an exterior
    point in the first quadrant, then reflect. Inside points are the
    caller's job (filled body).
    """
    U, V = abs(px), abs(py)

    def F(t: float) -> float:
        return _sq(a * U / (t + a * a)) + _sq(b * V / (t + b * b)) - 1.0

    if U <= _EPS and V <= _EPS:
        return (a if px >= 0.0 else -a, 0.0)
    if F(0.0) <= 0.0:
        return (px, py)
    lo = 0.0
    hi = max(a * U, b * V, 1.0)
    for _ in range(60):
        if F(hi) <= 0.0:
            break
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if F(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    t = 0.5 * (lo + hi)
    x = a * a * U / (t + a * a)
    y = b * b * V / (t + b * b)
    if px < 0.0:
        x = -x
    if py < 0.0:
        y = -y
    return (x, y)


def _closest_on_conic(conic: Conic, px: float, py: float) -> Point2:
    if conic[2] < _EPS and conic[3] < _EPS:
        return (conic[0], conic[1])
    if _conic_collapsed(conic):
        seg = _collapsed_axis_segment(conic)
        return _closest_on_segment(px, py, seg[0], seg[1], seg[2], seg[3])
    u, v = _to_unit(conic, px, py)
    if u * u + v * v <= 1.0 + _EPS:
        # Filled body, centre included (unlike Circle's centre → rim convention).
        return (px, py)
    qx, qy = _closest_on_ellipse_local(conic[2], conic[3], u * conic[2], v * conic[3])
    return _from_local(conic, qx, qy)


def _sort_along_conic(pts: List[Point2], conic: Conic) -> List[Point2]:
    """From local +x toward local +y (same sense as ``angle``)."""

    def key(p: Point2) -> float:
        u, v = _to_unit(conic, p[0], p[1])
        th = math.atan2(v, u)
        if th < 0.0:
            th += 2.0 * math.pi
        return th

    return sorted(pts, key=key)


# ---------------------------------------------------------------------------
# Shape → outline / circle params
# ---------------------------------------------------------------------------

def _is_circle(shape) -> bool:
    from .shapes import Circle
    return isinstance(shape, Circle)


def _is_line(shape) -> bool:
    from .shapes import Line
    return isinstance(shape, Line)


def _circle_params(shape) -> Tuple[float, float, float]:
    cx, cy = _bare_xy(shape.center)
    r = abs(_bare_num(shape.radius))
    return cx, cy, r


def _line_segment(shape) -> Segment:
    x1, y1 = _bare_xy(shape.p1)
    x2, y2 = _bare_xy(shape.p2)
    return (x1, y1, x2, y2)


def _oriented_box_verts(shape) -> List[Point2]:
    """World corners of Rect/Square from ``_oriented_frame`` (CCW from local BL)."""
    cx, cy, w, h, ang = shape._oriented_frame()
    hw, hh = abs(w) * 0.5, abs(h) * 0.5
    local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    rad = math.radians(float(ang))
    c, s = math.cos(rad), math.sin(rad)
    return [
        (cx + lx * c - ly * s, cy + lx * s + ly * c)
        for lx, ly in local
    ]


def _regular_poly_verts(shape) -> List[Point2]:
    """RegularPolygon / Triangle: closed-form vertices (the shape owns the formula)."""
    return shape._closed_form_verts()


def _polygon_verts(shape) -> List[Point2]:
    from .shapes import _RadialPolygon
    if isinstance(shape, _RadialPolygon):
        return _regular_poly_verts(shape)
    return [_bare_xy(v) for v in shape._vertices]


def _outline_verts(shape) -> Optional[List[Point2]]:
    """Closed outline vertices, or None for Line / Circle / Ellipse."""
    from .box import Box
    from .shapes import Line, Circle, Concave, Ellipse, Rect, Square, Polygon
    if isinstance(shape, (Line, Circle, Ellipse)):
        return None
    if isinstance(shape, Concave):
        return shape._world_ring()     # the curve as chords within 0.01 DU
    if isinstance(shape, (Rect, Square, Box)):
        return _oriented_box_verts(shape)
    if isinstance(shape, Polygon):
        return _polygon_verts(shape)
    raise TypeError(f"unsupported outline shape: {type(shape).__name__}")


def _outline_segments(shape) -> List[Segment]:
    """Open or closed edge list. Circle and Ellipse are not segments."""
    from .shapes import Line
    if isinstance(shape, Line):
        return [_line_segment(shape)]
    verts = _outline_verts(shape)
    if verts is None:
        return []
    n = len(verts)
    if n < 2:
        return []
    segs: List[Segment] = []
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        segs.append((x1, y1, x2, y2))
    return segs


def _shape_center(shape) -> Point2:
    from .box import Box
    from .shapes import Circle, Concave, Ellipse, Line, Polygon, Rect, Square
    if isinstance(shape, (Line, Circle, Ellipse, Rect, Square, Concave, Box, Polygon)):
        # RegularPolygon shadows center; free Polygon aliases centroid.
        return _bare_xy(shape.center)
    raise TypeError(
        f"no center to project from on {type(shape).__name__}; "
        f"supported: Line, Circle, Ellipse, Rect, Square, Concave, Box, Polygon"
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def _sort_along_segment(pts: List[Point2], seg: Segment) -> List[Point2]:
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1

    def key(p: Point2) -> float:
        return (p[0] - x1) * dx + (p[1] - y1) * dy

    return sorted(pts, key=key)


def _sort_along_closed(pts: List[Point2], verts: List[Point2]) -> List[Point2]:
    """Order hits by arc length along the closed outline starting at verts[0]."""
    if not pts or len(verts) < 2:
        return pts
    n = len(verts)
    edge_lens = []
    total = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        L = math.hypot(x2 - x1, y2 - y1)
        edge_lens.append(L)
        total += L

    def param(p: Point2) -> float:
        best_s = 0.0
        best_d = float("inf")
        acc = 0.0
        for i in range(n):
            x1, y1 = verts[i]
            x2, y2 = verts[(i + 1) % n]
            qx, qy = _closest_on_segment(p[0], p[1], x1, y1, x2, y2)
            d = _sq(qx - p[0]) + _sq(qy - p[1])
            L = edge_lens[i]
            if L < 1e-18:
                t = 0.0
            else:
                t = ((qx - x1) * (x2 - x1) + (qy - y1) * (y2 - y1)) / (L * L)
                t = max(0.0, min(1.0, t))
            s = acc + t * L
            if d < best_d:
                best_d = d
                best_s = s
            acc += L
        return best_s

    return sorted(pts, key=param)


def _order_hits(a, b, hits: List[Point2]) -> List[Point2]:
    if len(hits) <= 1:
        return hits
    # Line involved → along that line p1→p2 (prefer first arg if both lines).
    if _is_line(a):
        return _sort_along_segment(hits, _line_segment(a))
    if _is_line(b):
        return _sort_along_segment(hits, _line_segment(b))
    # Two circles: left then right already applied in _circle_circle using a→b.
    if _is_circle(a) and _is_circle(b):
        return hits
    # First shape is a conic → along it from local +x toward local +y.
    # (A circle has no vertex list; this is what makes circle-first ordered.)
    if _is_conic(a):
        conic = _conic_params(a)
        if _conic_collapsed(conic):
            return _sort_along_segment(hits, _collapsed_axis_segment(conic))
        return _sort_along_conic(hits, conic)
    # Else along the first shape's outline.
    verts = _outline_verts(a)
    if verts is not None:
        return _sort_along_closed(hits, verts)
    return hits


# ---------------------------------------------------------------------------
# Pair dispatch
# ---------------------------------------------------------------------------

def _intersect_segment_lists(
    segs_a: Sequence[Segment], segs_b: Sequence[Segment],
) -> List[Point2]:
    hits: List[Point2] = []
    for ax, ay, bx, by in segs_a:
        for cx, cy, dx, dy in segs_b:
            p = _seg_seg(ax, ay, bx, by, cx, cy, dx, dy)
            if p is not None:
                hits.append(p)
    return _dedupe(hits)


def _raw_intersections(a, b) -> List[Point2]:
    # Circle × circle keeps the closed form (and its left/right order).
    if _is_circle(a) and _is_circle(b):
        ax, ay, ar = _circle_params(a)
        bx, by, br = _circle_params(b)
        return _circle_circle(ax, ay, ar, bx, by, br)

    a_conic = _is_conic(a)
    b_conic = _is_conic(b)
    if a_conic and b_conic:
        return _conic_conic(_conic_params(a), _conic_params(b))
    if a_conic:
        return _intersect_conic_segments(_conic_params(a), _outline_segments(b))
    if b_conic:
        return _intersect_conic_segments(_conic_params(b), _outline_segments(a))

    return _intersect_segment_lists(_outline_segments(a), _outline_segments(b))


# ---------------------------------------------------------------------------
# Stand-in for intersection(a, b, i) when there are no crossings
# ---------------------------------------------------------------------------

def _stand_in_two_circles(a, b) -> Point2:
    ax, ay, ar = _circle_params(a)
    bx, by, _br = _circle_params(b)
    dx, dy = bx - ax, by - ay
    d = math.hypot(dx, dy)
    if d < _EPS:
        return (ax + ar, ay)
    ux, uy = dx / d, dy / d
    return (ax + ar * ux, ay + ar * uy)


def _stand_in_line_circle(line, circle) -> Point2:
    cx, cy, r = _circle_params(circle)
    x1, y1, x2, y2 = _line_segment(line)
    qx, qy = _closest_on_segment(cx, cy, x1, y1, x2, y2)
    dx, dy = qx - cx, qy - cy
    d = math.hypot(dx, dy)
    if d < _EPS:
        return (cx + r, cy)
    return (cx + r * dx / d, cy + r * dy / d)


def _stand_in(a, b) -> Point2:
    if _is_circle(a) and _is_circle(b):
        return _stand_in_two_circles(a, b)
    if _is_line(a) and _is_circle(b):
        return _stand_in_line_circle(a, b)
    if _is_line(b) and _is_circle(a):
        return _stand_in_line_circle(b, a)
    # Generic: project a.center onto b, then onto a.
    return closest_point(a, closest_point(b, _shape_center(a)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def intersections(a, b) -> List[Point2]:
    """Return outline crossing points of two shapes as ``(x, y)`` tuples.

    Empty list when the contours do not meet (including one shape inside
    another without touching, coincident circles, or collinear overlapping
    segments). Not a filled-body overlap test — use ``@collide`` for that.

    Raises:
        TypeError: if either argument is outside the allowlist.

    Args:
        a: A Line, Circle, Ellipse, Rect, Square, Concave, Polygon or Box.
        b: Another one.
    """
    _require_allowed(a, fn="intersections")
    _require_allowed(b, fn="intersections")
    hits = _raw_intersections(a, b)
    return _order_hits(a, b, hits)


def intersection(a, b, i: int = 0) -> Point2:
    """Return one outline-crossing slot as ``(x, y)`` — always defined.

    Intended for constructors / ``@=`` (e.g. a chord between two circles):

        Line(p1=lambda: intersection(c1, c2, 0),
             p2=lambda: intersection(c1, c2, 1))

    Indexing: ``hits[i]`` if present; else the last hit (so a tangent fills
    slots 0 and 1 with the same point); else a stand-in near the pair so the
    lambda never throws. ``i < 0`` raises ``ValueError``.

    Raises:
        TypeError: if either shape is outside the allowlist.
        ValueError: if ``i < 0``.

    Args:
        a: A Line, Circle, Ellipse, Rect, Square, Concave, Polygon or Box.
        b: Another one.
        i: Which crossing (default 0, the first).
    """
    if int(i) < 0:
        raise ValueError(f"intersection() index must be >= 0, got {i}")
    i = int(i)
    hits = intersections(a, b)
    if i < len(hits):
        return hits[i]
    if hits:
        return hits[-1]
    return _stand_in(a, b)


def closest_point(shape, p) -> Point2:
    """Nearest point on the filled shape to ``p`` as ``(x, y)``.

    If ``p`` is inside a filled shape (not a Line), returns ``p`` itself.
    Circle centre → rightmost rim ``(cx + r, cy)``. ``p`` is a point-like
    (Point, Vec2, ``(x, y)``, Graphic, mouse).

    Raises:
        TypeError: if ``shape`` is outside the allowlist.
    """
    _require_allowed(shape, fn="closest_point")
    # Author argument: point-like, including mouse. Shape parts stay on _bare_xy.
    from .shapes import _xy_of
    px, py = _xy_of(p, required=True)

    if _is_line(shape):
        x1, y1, x2, y2 = _line_segment(shape)
        return _closest_on_segment(px, py, x1, y1, x2, y2)

    if _is_circle(shape):
        cx, cy, r = _circle_params(shape)
        if r < _EPS:
            return (cx, cy)
        dx, dy = px - cx, py - cy
        d = math.hypot(dx, dy)
        if d <= _EPS:
            # At centre — convention: rightmost rim point.
            return (cx + r, cy)
        if d <= r + _EPS:
            # Inside (or on) the filled disk.
            return (px, py)
        return (cx + r * dx / d, cy + r * dy / d)

    from .shapes import Ellipse
    if isinstance(shape, Ellipse):
        return _closest_on_conic(_conic_params(shape), px, py)

    from .box import Box
    from .shapes import Rect, Square
    if isinstance(shape, (Rect, Square, Box)):
        cx, cy, w, h, ang = shape._oriented_frame()
        hw, hh = abs(w) * 0.5, abs(h) * 0.5
        dx, dy = px - cx, py - cy
        rad = math.radians(float(-ang))
        c, s = math.cos(rad), math.sin(rad)
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        if abs(lx) <= hw + _EPS and abs(ly) <= hh + _EPS:
            return (px, py)
        clx = max(-hw, min(hw, lx))
        cly = max(-hh, min(hh, ly))
        rad2 = math.radians(float(ang))
        c2, s2 = math.cos(rad2), math.sin(rad2)
        return (cx + clx * c2 - cly * s2, cy + clx * s2 + cly * c2)

    # Polygon / RegularPolygon / Triangle; a Concave's outline (its curve as chords)
    from .shapes import Concave
    verts = shape._world_ring() if isinstance(shape, Concave) else _polygon_verts(shape)
    if len(verts) < 3:
        if verts:
            return verts[0]
        return (px, py)
    if _point_in_polygon_xy(px, py, verts):
        return (px, py)
    best = verts[0]
    best_d = float("inf")
    n = len(verts)
    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]
        qx, qy = _closest_on_segment(px, py, ax, ay, bx, by)
        d = _sq(qx - px) + _sq(qy - py)
        if d < best_d:
            best_d = d
            best = (qx, qy)
    return best
