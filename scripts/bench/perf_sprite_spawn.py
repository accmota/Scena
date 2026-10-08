"""Microbench: Sprite construct vs clone() after path-intern + shared Sheet.

Clone should be no slower than warm reconstruction — clone is ergonomics,
not a fire-rate requirement.

Usage:
    python scripts/bench/perf_sprite_spawn.py
    python scripts/bench/perf_sprite_spawn.py --n 4000
"""
from __future__ import annotations

import argparse
import gc
import os
import statistics
import sys
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--n", type=int, default=2500, help="spawns per trial")
parser.add_argument("--trials", type=int, default=5)
parser.add_argument("--warmup", type=int, default=80)
args = parser.parse_args()

from scena import *  # noqa: E402
import skia  # noqa: E402

init(width=400, height=300, title="sprite spawn bench")
set_watchdog(False)


def _write_png(path, px=16):
    info = skia.ImageInfo.Make(px, px, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
    surf.makeImageSnapshot().save(path, skia.kPNG)


class Bolt(Sprite):
    def setup(self):
        self.visual = Halo("deepskyblue")

    def on_update(self, dt):
        pass


def _median_us(samples):
    return statistics.median(samples) * 1e6


def _trial(n, fn):
    gc.collect()
    t0 = time.perf_counter()
    spawned = []
    for i in range(n):
        spawned.append(fn(i))
    elapsed = time.perf_counter() - t0
    for s in spawned:
        s.destroy()
    return elapsed / n


def _run_case(name, warmup_fn, spawn_fn):
    for i in range(args.warmup):
        s = warmup_fn(i)
        s.destroy()
    samples = [_trial(args.n, spawn_fn) for _ in range(args.trials)]
    return name, _median_us(samples), min(x * 1e6 for x in samples)


def main():
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "shot.png")
    _write_png(path)

    rows = []

    def ctor_path(i):
        return Bolt(path, height=18, center=(10 + i % 50, 20), group="sting")

    stamp_path = Bolt(path, height=18, group="sting", layer=None)
    stamp_path.active = False

    def clone_path(i):
        return stamp_path.clone(center=(10 + i % 50, 20))

    rows.append(_run_case("path ctor (warm intern)", ctor_path, ctor_path))
    rows.append(_run_case("path clone", clone_path, clone_path))

    media = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "examples", "media", "shooter", "sheet.xml",
    ))
    if os.path.isfile(media):
        space = Sheet(media)

        def ctor_sheet(i):
            return Bolt(
                space,
                frame="laserBlue02.png",
                height=28,
                center=(10 + i % 50, 20),
                group="bolt",
            )

        stamp_sheet = Bolt(
            space, frame="laserBlue02.png", height=28, group="bolt", layer=None,
        )
        stamp_sheet.active = False

        def clone_sheet(i):
            return stamp_sheet.clone(center=(10 + i % 50, 20))

        rows.append(_run_case("atlas ctor (shared Sheet)", ctor_sheet, ctor_sheet))
        rows.append(_run_case("atlas clone", clone_sheet, clone_sheet))

    print("=== sprite spawn: construct vs clone ===")
    print(f"n={args.n}  trials={args.trials}  (median µs / spawn, then destroy)")
    print(f"{'case':<28} {'median_us':>10} {'min_us':>10}")
    for name, med, mn in rows:
        print(f"{name:<28} {med:10.1f} {mn:10.1f}")

    by_name = {name: med for name, med, _ in rows}
    if "path ctor (warm intern)" in by_name and "path clone" in by_name:
        ctor, clone = by_name["path ctor (warm intern)"], by_name["path clone"]
        ratio = clone / ctor if ctor else float("inf")
        print()
        print(f"path clone / warm ctor = {ratio:.2f}x")
        if ratio > 1.15:
            print("NOTE: clone is slower than reconstruction — check intern sharing.")
        else:
            print("clone is not meaningfully slower than warm construct.")
            print("clone is for ergonomics, not required for fire-rate performance.")
    tmp.cleanup()


if __name__ == "__main__":
    main()
    sys.exit(0)
