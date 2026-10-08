"""Benchmark auto-hitbox fitting quality and collision runtime cost.

Loads the examples/media hitbox atlases, compares auto picks vs forced kinds,
and times CollisionSystem broad/narrow phase (see perf_collision_shooter.py).

Usage:
    python scripts/bench/perf_sprite_hitbox.py
    python scripts/bench/perf_sprite_hitbox.py --frames 300 --copies 40
    python scripts/bench/perf_sprite_hitbox.py --rotation 45

Also reports frozen-vs-``each`` collision-epoch bumps over playhead ticks.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from typing import List, Tuple

parser = argparse.ArgumentParser()
parser.add_argument("--frames", type=int, default=200, help="collision steps to measure")
parser.add_argument("--copies", type=int, default=30, help="sprite copies per kind in stress scene")
parser.add_argument("--rotation", type=float, default=0.0, help="sprite rotation in degrees")
args = parser.parse_args()

from scena import *  # noqa: E402
from scena.atlas import (  # noqa: E402
    _AUTO_QUALITY_BAR,
    auto_collider_for_frame,
    boxes_to_local,
    circle_to_local,
    ellipse_to_local,
    hull_to_local,
    reset_atlas_caches,
)
from scena.collision import (  # noqa: E402
    PrimKind,
    get_collision_system,
    narrow_phase,
    reset_collision_system,
    snapshot_shape,
)
from scena.sprite import reset_sprite_caches  # noqa: E402

_MEDIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "examples", "media")
_ENTRIES: List[Tuple[str, Sheet, str]] = []


def _load_entries() -> List[Tuple[str, Sheet, str]]:
    out: List[Tuple[str, Sheet, str]] = []
    for png, xml in (
        (os.path.join(_MEDIA, "shooter", "sheet.png"), os.path.join(_MEDIA, "shooter", "sheet.xml")),
        (os.path.join(_MEDIA, "k-rolling-ball", "rollingBall_sheet.png"),
         os.path.join(_MEDIA, "k-rolling-ball", "rollingBall_sheet.xml")),
    ):
        try:
            sh = Sheet(png, atlas=xml)
        except Exception:
            continue
        for name in sh.names:
            out.append((name, sh, name))
    try:
        sh = Sheet(os.path.join(_MEDIA, "space", "star_gold.png"))
        out.append(("star_gold.png", sh, sh.names[0]))
    except Exception:
        pass
    return out


def _apply_collider(sprite: Sprite, col, fr) -> None:
    sprite._clear_auto_hitbox()
    sprite._hitbox_kind = "auto"
    src_circles = col.circles or ((col.circle,) if col.circle is not None else ())
    if col.kind in ("circle", "circles") and src_circles:
        locals_c = tuple(circle_to_local(*c, fr) for c in src_circles)
        sprite._hitbox_circles = locals_c
        sprite._hitbox_circle = locals_c[0] if len(locals_c) == 1 else None
    elif col.kind == "ellipse" and col.ellipse is not None:
        sprite._hitbox_ellipse = ellipse_to_local(*col.ellipse, fr)
    elif col.kind == "poly" and col.poly:
        sprite._hitbox_poly = hull_to_local(col.poly, fr)
    elif col.kind == "boxes" and col.boxes:
        sprite._hitbox_boxes = boxes_to_local(col.boxes, fr)
    sprite._commit_hitbox_base()


def _kind_label(col) -> str:
    if col.kind == "boxes":
        return f"rect{len(col.boxes)}"
    if col.kind == "poly":
        return f"hull{len(col.poly)}"
    if col.kind == "circles":
        return f"circ{len(col.circles)}"
    return col.kind or "none"


def _fit_report(entries: List[Tuple[str, Sheet, str]]) -> None:
    reset_atlas_caches()
    t0 = time.perf_counter()
    kinds: Counter = Counter()
    recalls: List[float] = []
    precisions: List[float] = []
    below_rec = 0
    below_prec = 0
    for _name, sheet, frame_name in entries:
        idx = sheet.frame_index(frame_name)
        fr = sheet._frame_at(idx)
        col = auto_collider_for_frame(sheet.image, fr)
        kinds[_kind_label(col)] += 1
        recalls.append(col.recall)
        precisions.append(col.precision)
        if col.recall < _AUTO_QUALITY_BAR:
            below_rec += 1
        if col.precision < _AUTO_QUALITY_BAR:
            below_prec += 1
    elapsed = time.perf_counter() - t0
    n = len(entries) or 1
    print("=" * 64)
    print("FIT — auto_collider_for_frame over examples/media atlases")
    print("=" * 64)
    print(f"Frames:              {len(entries)}")
    print(f"Total fit time:      {elapsed * 1000:.1f} ms  ({elapsed / n * 1000:.3f} ms/frame)")
    print(f"Avg recall:          {sum(recalls) / n:.3f}")
    print(f"Avg precision:       {sum(precisions) / n:.3f}")
    print(f"Below recall bar:    {below_rec}  (bar={_AUTO_QUALITY_BAR})")
    print(f"Below precision bar: {below_prec}  (bar={_AUTO_QUALITY_BAR})")
    print("Distribution:", dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))))
    print()


def _frozen_vs_each(entries: List[Tuple[str, Sheet, str]]) -> None:
    """Count collision-epoch bumps while a clip plays (frozen default vs ``each``)."""
    multi = next((sheet for _n, sheet, _f in entries if len(sheet.names) >= 4), None)
    if multi is None:
        print("FROZEN VS EACH — skipped (no multi-frame sheet in the corpus)")
        print()
        return

    clip_frames = list(multi.names[:8])
    multi.clip("_hitbox_bench", clip_frames, fps=8)

    def _run(hitbox_from):
        reset_sprite_caches()
        reset_atlas_caches()
        reset_collision_system()
        init(width=900, height=700, window_scale=0.01)
        canvas.background = (0.05, 0.06, 0.12, 1)

        @collide("stress", "stress")
        def _touch(me, other, info):
            pass

        sprites = []
        for i in range(args.copies):
            x = 80 + (i % 10) * 85
            y = 80 + (i // 10) * 85
            s = Sprite(
                multi, frame=clip_frames[0], height=48, center=(x, y),
                group="stress", hitbox_shape="auto", hitbox_source=hitbox_from,
            )
            s.play("_hitbox_bench")
            s.collidable = True
            sprites.append(s)
        sys = get_collision_system()
        sys.step()
        base = [int(s._collision_epoch) for s in sprites]
        t0 = time.perf_counter()
        for _ in range(args.frames):
            clock.advance(0.125)
            sys.step()
        elapsed = time.perf_counter() - t0
        bumps = sum(int(s._collision_epoch) - b for s, b in zip(sprites, base))
        return bumps, elapsed

    frozen_bumps, frozen_t = _run(clip_frames[0])
    each_bumps, each_t = _run("each")
    print("=" * 64)
    print(
        f"FROZEN VS EACH — {args.copies} sprites × {args.frames} playhead ticks  "
        f"(sheet={len(multi.names)} frames)"
    )
    print("=" * 64)
    print(
        f"frozen  epoch_bumps={frozen_bumps:5d}  "
        f"{frozen_t / args.frames * 1000:7.3f} ms/step"
    )
    print(
        f"each    epoch_bumps={each_bumps:5d}  "
        f"{each_t / args.frames * 1000:7.3f} ms/step"
    )
    print(f"removed per-tick epoch bumps: {each_bumps - frozen_bumps}")
    print()


def _stress_scene(kind: str, entries: List[Tuple[str, Sheet, str]], copies: int) -> None:
    """Spawn ``copies`` sprites using forced ``kind`` collider."""
    force = None if kind == "auto" else kind
    if kind == "hull":
        force = "poly"
    if kind == "rect1":
        force = "box"
    if kind == "rects":
        force = "boxes"
    pick = entries[: min(len(entries), max(1, copies))]
    rot = float(args.rotation)
    for i in range(copies):
        label, sheet, frame_name = pick[i % len(pick)]
        x = 80 + (i % 10) * 85
        y = 80 + (i // 10) * 85
        s = Sprite(
            sheet, frame=frame_name, height=48, center=(x, y),
            group="stress", hitbox_shape="auto",
        )
        s.angle = rot
        s.collidable = True
        idx = sheet.frame_index(frame_name)
        fr = sheet._frame_at(idx)
        col = auto_collider_for_frame(
            sheet.image, fr, force_kind=force,
        )
        _apply_collider(s, col, fr)


def _timed_collision(frames: int):
    import numpy as np

    sys = get_collision_system()
    sys.step()
    t0 = time.perf_counter()
    last_prims = 0
    last_narrow = 0
    last_kinds: Counter = Counter()
    sat = 0
    for _ in range(frames):
        sys._prune_dead()
        sys._resolve_cache.clear()
        for c in sys._colliders:
            c._tags_cache = None
        sys._refresh_pair_enrollments()
        prim_list = []
        kinds: Counter = Counter()
        for c in sys._colliders:
            for shape in c.shapes:
                for prim in snapshot_shape(shape, cache_owner=c):
                    prim_list.append((c, prim))
                    kinds[prim.kind.name] += 1
        n = len(prim_list)
        last_prims = n
        last_kinds = kinds
        if n == 0:
            continue
        aabb = np.zeros((n, 4), dtype=np.float64)
        for i, (_, prim) in enumerate(prim_list):
            aabb[i] = prim.aabb
        minx, miny, maxx, maxy = aabb[:, 0], aabb[:, 1], aabb[:, 2], aabb[:, 3]
        no_x = (minx[:, None] > maxx[None, :]) | (minx[None, :] > maxx[:, None])
        no_y = (miny[:, None] > maxy[None, :]) | (miny[None, :] > maxy[:, None])
        overlap = ~(no_x | no_y)
        np.fill_diagonal(overlap, False)
        ii, jj = np.nonzero(np.triu(overlap, k=1))
        narrow = 0
        sat = 0
        for i, j in zip(ii.tolist(), jj.tolist()):
            ca, pa = prim_list[i]
            cb, pb = prim_list[j]
            if ca is cb:
                continue
            if not sys._interested(ca, cb):
                continue
            narrow += 1
            fast = (
                (pa.kind == PrimKind.CIRCLE and pb.kind == PrimKind.CIRCLE)
                or (pa.kind == PrimKind.AABB and pb.kind == PrimKind.AABB)
                or (pa.kind == PrimKind.CIRCLE and pb.kind == PrimKind.AABB)
                or (pa.kind == PrimKind.AABB and pb.kind == PrimKind.CIRCLE)
            )
            if not fast:
                sat += 1
            narrow_phase(pa, pb)
        last_narrow = narrow
    elapsed = time.perf_counter() - t0
    return elapsed, last_prims, last_narrow, dict(last_kinds), sat


def _run_kind_benchmark(kind: str, entries: List[Tuple[str, Sheet, str]]) -> None:
    reset_sprite_caches()
    reset_atlas_caches()
    reset_collision_system()
    init(width=900, height=700, window_scale=0.01)
    canvas.background = (0.05, 0.06, 0.12, 1)

    @collide("stress", "stress")
    def _touch(me, other, info):
        pass

    _stress_scene(kind, entries, args.copies)
    elapsed, n_prims, n_narrow, kinds, n_sat = _timed_collision(args.frames)
    ms = elapsed / args.frames * 1000.0
    print(
        f"{kind:8s}  prims={n_prims:4d}  narrow={n_narrow:5d}/frame  "
        f"sat={n_sat:4d}  {ms:7.3f} ms/frame  {kinds}"
    )


def main() -> None:
    entries = _load_entries()
    if not entries:
        print("No hitbox media assets found (examples/media).")
        return
    _fit_report(entries)
    _frozen_vs_each(entries)
    print("=" * 64)
    print(
        f"COLLISION — {args.copies} sprites × {args.frames} steps  "
        f"rotation={args.rotation:g}°"
    )
    print("=" * 64)
    for kind in ("auto", "circle", "circles", "ellipse", "hull", "rect1", "rects"):
        _run_kind_benchmark(kind, entries)
    print("=" * 64)


if __name__ == "__main__":
    main()
