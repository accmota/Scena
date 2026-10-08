"""Headless Tier-1 reactive pull microbench (no GLFW).

Measures the deep binary tree (spinning-rects shape) and a shallow fan-out
without opening a window — usable in CI / sandboxes where ``run_graph.py``
cannot create a display.

    python scripts/bench/tier1_reactive_micro.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scena import init, Rect, State, Point  # noqa: E402
from scena.state import Attribute  # noqa: E402


def _deep(levels: int = 5):
    st = State(name="drv")
    st.t = 0.0
    t = st.t
    root = Rect(center=(500.0, 350.0), width=200.0, height=200.0 / 15)
    root["angle"] @= (lambda t=t: (t * 26.0) % 360.0)
    bars = [root]

    def recurse(nivel: int, parent: Rect) -> None:
        if nivel > levels:
            return
        for side in ("left_square_center", "right_square_center"):
            child = Rect(
                center=(lambda b=parent, s=side: getattr(b, s)),
                width=200.0 / (2 ** nivel),
                height=(200.0 / (2 ** nivel)) / 15,
            )
            child["angle"] @= (
                lambda t=t, n=nivel: (t * 26.0 * ((-1.5) ** n)) % 360.0
            )
            bars.append(child)
            recurse(nivel + 1, child)

    recurse(1, root)
    return st, bars


def _shallow(n: int = 200):
    hub = Rect(center=(0.0, 0.0), width=10.0, height=10.0)
    sinks = []
    for i in range(n):
        r = Rect(center=(lambda h=hub: h.center), width=20.0, height=8.0)
        r["angle"] @= (lambda h=hub, i=i: (h.center.x + i) % 360.0)
        sinks.append(r)
    return hub, sinks


def _bench(label: str, frame_fn, warmup: int = 30, n: int = 120) -> dict:
    for _ in range(warmup):
        frame_fn()
    t0 = time.perf_counter()
    for _ in range(n):
        frame_fn()
    ms = (time.perf_counter() - t0) / n * 1000.0
    print(f"{label:28s} {ms:7.3f} ms/frame")
    return {"label": label, "ms_per_frame": ms, "frames": n}


def main() -> int:
    init(width=400, height=300, title="tier1-micro")
    rows = []

    st, bars = _deep(5)

    def deep_frame():
        st.t = float(st.t) + 0.1
        for b in bars:
            _ = b.center.x, b.center.y, b.angle

    rows.append(_bench(f"deep L=5 n={len(bars)}", deep_frame))
    for b in bars:
        b.destroy()

    st7, bars7 = _deep(7)

    def deep7_frame():
        st7.t = float(st7.t) + 0.1
        for b in bars7:
            _ = b.center.x, b.center.y, b.angle

    rows.append(_bench(f"deep L=7 n={len(bars7)}", deep7_frame, warmup=20, n=80))
    for b in bars7:
        b.destroy()

    hub, sinks = _shallow(200)

    def shallow_frame():
        hub.center._takein((float(hub.center.x) + 0.1, 0.0))
        for r in sinks:
            _ = r.center.x, r.angle

    rows.append(_bench(f"shallow n={len(sinks)}", shallow_frame))
    hub.destroy()
    for r in sinks:
        r.destroy()

    print("RESULT_JSON:" + json.dumps({"ok": True, "rows": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
