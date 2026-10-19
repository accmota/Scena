"""perf_watchdog.py -- what the freeze watchdog costs a frame.

In-process interleaved A/B, headless (no window): each round builds the scene
with the watchdog on and with ``set_watchdog(False)`` (the floor), in
alternating order, and times ``tick_processes`` (plus the scene's driver) per
frame. Median of the rounds, in µs per frame; the difference is the guard.

Scenes:
  switch  -- ``--n`` actors each switch between two async modes every frame
             (every first step runs outside the task walk, alone)
  waiting -- 300 async modes, each ready every frame (``await wait(0)``)
  busy    -- 300 async modes that call an author helper and an engine
             method every step
  timers  -- 300 ``every`` timers, no async body (sanity: no guard runs)
  sync    -- 300 ``on_update`` hooks; on / off is ``set_sync_watchdog``

``--deep`` runs each frame under a 400-line function, the size of a real run
loop's frame (a global ``set_events`` re-instruments it). ``--root`` imports
``scena`` from another checkout, so two versions compare by their overhead
over their own floor (one process each).

    python scripts/bench/perf_watchdog.py [--frames 200] [--rounds 9] [--scene all] [--deep] [--root DIR]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--root", default=str(ROOT))
sys.path.insert(0, _pre.parse_known_args()[0].root)

from scena import Circle, wait, every, clock  # noqa: E402
import scena.process as proc  # noqa: E402
from scena.process import reset_process_scheduler, tick_processes  # noqa: E402

DT = 1 / 60


def _set_variant(name, scene):
    if scene == "sync":     # the sync guard: on_update / update(dt)
        proc.set_watchdog(True)
        proc.set_sync_watchdog(name == "on")
    else:
        proc.set_sync_watchdog(False)
        proc.set_watchdog(name == "on")


# --- author code (this file is author code for the watchdog) ---------------

def helper(e, k):
    s = 0
    for i in range(k):
        s += i
    return s


async def mode_a(e):
    helper(e, 3)
    await wait(1.0)


async def mode_b(e):
    helper(e, 3)
    await wait(1.0)


async def waiting(e):
    while True:
        await wait(0)


async def busy(e):
    while True:
        e.n += helper(e, 4)
        e.move_by(0.1, 0)
        await wait(0)


# --- scenes -----------------------------------------------------------------

def scene_switch(n):
    actors = [Circle(radius=2) for _ in range(n)]
    flip = [False]
    for a in actors:
        a.mode = mode_a

    def drive():
        flip[0] = not flip[0]
        m = mode_b if flip[0] else mode_a
        for a in actors:
            a.mode = m
    return actors, drive


def scene_waiting(n):
    actors = [Circle(radius=2) for _ in range(n)]
    for a in actors:
        a.mode = waiting
    return actors, None


def scene_busy(n):
    actors = [Circle(radius=2) for _ in range(n)]
    for a in actors:
        a.n = 0
        a.mode = busy
    return actors, None


def scene_timers(n):
    actors = [Circle(radius=2) for _ in range(n)]
    hits = [0]

    def tick():
        hits[0] += 1
    for a in actors:
        every(0.01, tick)
    return actors, None


def scene_sync(n):
    actors = [Circle(radius=2) for _ in range(n)]

    def step(e, dt):
        e.n += helper(e, 4)
    for a in actors:
        a.n = 0
        a.on_update = step
    return actors, None


SCENES = {
    "switch": (scene_switch, 50),
    "waiting": (scene_waiting, 300),
    "busy": (scene_busy, 300),
    "timers": (scene_timers, 300),
    "sync": (scene_sync, 300),
}

_DEEP_SRC = (
    "def deep(f):\n"
    + "".join(f"    v{i} = {i}\n" for i in range(400))
    + "    return f()\n"
)
_ns: dict = {}
exec(compile(_DEEP_SRC, "<deep-frame>", "exec"), _ns)
_deep = _ns["deep"]


def measure(scene, n, variant, frames, deep):
    reset_process_scheduler()
    _set_variant(variant, scene)
    build, _ = SCENES[scene]
    actors, drive = build(n)

    def one():
        if drive is not None:
            drive()
        clock.advance(DT)
        tick_processes()

    def run(k):
        t0 = time.perf_counter()
        for _ in range(k):
            one()
        return time.perf_counter() - t0

    for _ in range(10):
        one()
    dt = _deep(lambda: run(frames)) if deep else run(frames)
    for a in actors:
        a.destroy()
    reset_process_scheduler()
    return dt / frames * 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--rounds", type=int, default=9)
    ap.add_argument("--scene", default="all")
    ap.add_argument("--variants", default="on,off")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--n", type=int, default=0, help="override the scene's actor count")
    ap.add_argument("--deep", action="store_true")
    args = ap.parse_args()
    variants = args.variants.split(",")
    scenes = list(SCENES) if args.scene == "all" else args.scene.split(",")
    warnings.simplefilter("ignore")
    for scene in scenes:
        n = args.n or SCENES[scene][1]
        res = {v: [] for v in variants}
        for r in range(args.rounds):
            order = variants if r % 2 == 0 else variants[::-1]
            for v in order:
                res[v].append(measure(scene, n, v, args.frames, args.deep))
        med = {v: statistics.median(res[v]) for v in variants}
        base = med[variants[0]]
        cells = "  ".join(
            f"{v} {med[v]:8.1f} µs ({(med[v] / base - 1) * 100:+5.1f} %)" for v in variants
        )
        print(f"{scene:8} n={n:<4} {'deep' if args.deep else 'flat'}  {cells}  "
              f"guard {med[variants[0]] - med[variants[-1]]:+.1f} µs", flush=True)
    proc.set_watchdog(True)
    proc.set_sync_watchdog(False)


if __name__ == "__main__":
    main()
