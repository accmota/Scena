"""Text / HUD draw isolate — captions, live FPS string, Glow stamp.

Catches drawString vs glyph-path regressions that used to hide inside cpu_mix.
Collision, sprites, SpatialFx stay out.

Usage
-----
    python scripts/bench/perf_text.py
    python scripts/bench/perf_text.py --bench --mode mix
    python scripts/bench/perf_text.py --pulse
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODES = ("hud", "glow", "mix")

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--mode", choices=_MODES, default="mix")
_parser.add_argument("--bench", action="store_true")
_parser.add_argument("--duration", type=float, default=2.0)
_parser.add_argument("--warmup", type=float, default=0.5)
_parser.add_argument("--repeats", type=int, default=1)
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument("--json", dest="json_path", default=None)
_parser.add_argument(
    "--pulse", action="store_true",
    help="protocol snapshot: mix median of 3; append text.md",
)
_parser.add_argument("--no-append", action="store_true")
args, _ = _parser.parse_known_args()
args.repeats = max(1, int(args.repeats))

_BENCH = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.environ.get("TEXT_WORKER")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from harness import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)
from fingerprint import script_hashes  # noqa: E402
from pulse import (  # noqa: E402
    append_pulse,
    autodiff,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)


def _worker_cmd() -> List[str]:
    return [
        sys.executable, os.path.abspath(__file__),
        "--bench", "--mode", args.mode,
        "--duration", str(args.duration),
        "--warmup", str(args.warmup),
        "--seed", str(args.seed),
        "--repeats", "1",
    ]


def _parse_result_line(text: str) -> Optional[Dict[str, Any]]:
    for line in (text or "").splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line.split(":", 1)[1].strip())
    return None


def _run_worker() -> Dict[str, Any]:
    env = dict(os.environ)
    env["TEXT_WORKER"] = "1"
    proc = subprocess.run(_worker_cmd(), env=env, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out, end="" if out.endswith("\n") else "\n")
    row = _parse_result_line(out)
    if row is None:
        return {"ok": False, "returncode": proc.returncode, "mode": args.mode}
    row["ok"] = proc.returncode == 0
    return row


def _median_bundle(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r.get("ok") and "work_ms" in r]
    if not ok:
        return {"ok": False, "repeats": len(rows)}
    keys = ("fps", "work_ms", "tick_ms", "flush_ms", "draw_ms", "coll_ms")
    out = dict(ok[0])
    out["repeats"] = len(ok)
    for k in keys:
        vals = [float(r[k]) for r in ok if k in r and r[k] is not None]
        if not vals:
            continue
        out[k] = statistics.median(vals)
        out[f"{k}_min"] = min(vals)
        out[f"{k}_max"] = max(vals)
        med = out[k]
        out[f"{k}_spread_pct"] = (
            0.0 if med == 0 else 100.0 * (max(vals) - min(vals)) / abs(med)
        )
    return out


def _fmt_phase(bundle: Dict[str, Any]) -> str:
    parts = []
    for key, short in (("tick_ms", "t"), ("draw_ms", "d")):
        v = bundle.get(key)
        if v is None:
            continue
        parts.append(f"{short}{v:.2f}")
    return " ".join(parts)


def _render_pulse(mix: Dict[str, Any], meta: Dict[str, Any], hashes: Dict[str, str]) -> Tuple[str, str]:
    host_s = meta["host_s"]
    date = meta["date"]
    work = mix.get("work_ms", float("nan"))
    fps = mix.get("fps", float("nan"))
    row = (
        f"| {date} | `text-1` | {host_s} | "
        f"{work:.3f} ({fps:.1f}) `{_fmt_phase(mix)}` | mix HUD+Glow |"
    )
    hash_s = " · ".join(f"`{k}` `{v}`" for k, v in hashes.items())
    wmin = mix.get("work_ms_min", work)
    wmax = mix.get("work_ms_max", work)
    spread = mix.get("work_ms_spread_pct", 0.0)
    spread_s = f"±{spread:.0f}%" if spread >= 1.0 else "—"
    section = "\n".join([
        f"### {date} — text-1",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `text-1` |",
        f"| Host | {host_s} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Repeats | {mix.get('repeats', 3)} (median) |",
        f"| Scripts | {hash_s} |",
        "",
        "Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.",
        "",
        "#### mix (median)",
        "",
        "| Metric | Median | min–max | spread |",
        "|--------|------:|--------:|-------:|",
        f"| work_ms | **{work:.3f}** | {wmin:.3f}–{wmax:.3f} | {spread_s} |",
        f"| FPS | {fps:.1f} | | |",
        f"| draw_ms | {mix.get('draw_ms', float('nan')):.3f} | | |",
        f"| tick_ms | {mix.get('tick_ms', float('nan')):.3f} | | |",
        "",
    ])
    return row, section


def _run_pulse() -> None:
    log_path = Path(_BENCH) / "text.md"
    meta = now_meta()
    hashes = script_hashes(("perf_text.py", "harness.py"), Path(_BENCH))
    args.mode = "mix"
    print(f"=== text pulse  mix repeats=3  stage={meta['scena_fingerprint']} ===", flush=True)
    shots = [_run_worker() for _ in range(3)]
    mix = _median_bundle(shots)
    mix["mode"] = "mix"
    row, section = _render_pulse(mix, meta, hashes)
    prev_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    prev_metrics = None
    for cells in parse_summary_table(prev_text):
        if len(cells) >= 4 and cells[1].strip().strip("`") == "text-1":
            work = parse_leading_float(cells[3])
            if work is not None:
                prev_metrics = {"mix_work_ms": work}
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same: Optional[bool]
    if prev_fp and meta["scena_fingerprint"]:
        same = prev_fp == meta["scena_fingerprint"]
    else:
        same = None
    new_work = mix.get("work_ms")
    warnings = autodiff(
        {"mix_work_ms": float(new_work)} if new_work is not None else {},
        prev_metrics,
        same_scena=same,
        prev_label="last text-1 row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print("\n" + "=" * 60)
    print("text pulse")
    print("=" * 60)
    print(section)
    if not args.no_append:
        append_pulse(log_path, row, section)
        print(f"appended {log_path}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


if not _WORKER and (args.pulse or args.repeats > 1):
    args.bench = True
    if args.pulse:
        _run_pulse()
        sys.exit(0)
    print(f"=== text repeats={args.repeats} mode={args.mode} ===", flush=True)
    shots = [_run_worker() for _ in range(args.repeats)]
    bundle = _median_bundle(shots)
    work = bundle.get("work_ms", float("nan"))
    spread = bundle.get("work_ms_spread_pct", 0.0)
    print("=" * 60)
    print(f"text {args.mode}  repeats={bundle.get('repeats', 0)}")
    print(f"work_ms:  {work:.3f}  ±{spread:.0f}%")
    print(f"draw_ms:  {bundle.get('draw_ms', 0):.3f}")
    print(f"FPS:      {bundle.get('fps', 0):.1f}")
    print("=" * 60)
    print("RESULT_JSON: " + json.dumps({
        k: bundle.get(k) for k in ("ok", "mode", "fps", "work_ms", "tick_ms", "draw_ms")
    }))
    sys.exit(0)


from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

W, H = 1000, 700
init(width=W, height=H, title=f"Bench — text {args.mode}")
canvas.background = (0.06, 0.07, 0.10)
set_fx_auto(False)
canvas.fx_quality = "medium"
set_watchdog(False)
canvas.framerate = "max"

st.frames = 0
st.score = 0
st.combo = 0

HUD_LINES = (
    "Score {score:06d}",
    "Wave 1  Combo {combo}",
    "Kills {frames}  HP 3",
    "P1 READY",
    "paused=no  seed={seed}",
    "caption stack",
)


def _build_hud() -> List[Any]:
    labels = []
    for i, tmpl in enumerate(HUD_LINES):
        t = Text(
            text=tmpl.format(score=0, combo=0, frames=0, seed=args.seed),
            top_left=(16, H - 28 - i * 22 + 19),
            font_size=16,
            color=Color(0.86, 0.90, 0.95, 1),
            stack=False,
        )
        labels.append((t, tmpl))
    fps = Text(
        text="FPS —",
        top_left=(16, H - 28 - len(HUD_LINES) * 22 + 19),
        font_size=16,
        color=Color(0.95, 0.85, 0.40, 1),
        stack=False,
    )
    labels.append((fps, "FPS {fps:.1f}"))
    return labels


def _build_glow() -> List[Any]:
    out = []
    for i in range(8):
        col = i % 4
        row = i // 4
        t = Text(
            text=f"GLOW {i} ch",
            top_left=(280 + col * 170, 220 + row * 90 + 33),
            font_size=28,
            color=Color(0.95, 0.92, 0.85, 1),
            stack=False,
        )
        t.glow = Glow()
        out.append(t)
    return out


hud_labels: List[Any] = []
if args.mode in ("hud", "mix"):
    hud_labels = _build_hud()
if args.mode in ("glow", "mix"):
    _build_glow()

_t0 = None
_n = 0


def update(dt):
    global _t0, _n
    st.frames = int(st.frames) + 1
    st.score = int(st.frames) * 17
    st.combo = int(st.frames) % 40
    now = clock.time
    if _t0 is None:
        _t0 = now
    _n += 1
    elapsed = max(1e-6, now - _t0)
    fps = _n / elapsed
    for t, tmpl in hud_labels:
        t.text = tmpl.format(
            score=int(st.score),
            combo=int(st.combo),
            frames=int(st.frames),
            seed=args.seed,
            fps=fps,
        )


if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
    )
    run()
    print_phase_report(f"text {args.mode} — phase timing", stats)
    avg = average_phase_stats(stats)
    payload = {
        "ok": True,
        "mode": args.mode,
        "fps": avg["fps"],
        "work_ms": avg["work_ms"],
        "tick_ms": avg["tick_ms"],
        "flush_ms": avg["flush_ms"],
        "draw_ms": avg["draw_ms"],
        "coll_ms": avg["coll_ms"],
        "frames": avg["frames"],
    }
    print("RESULT_JSON: " + json.dumps(payload))
    if args.json_path:
        payload["phases"] = avg
        write_json(args.json_path, payload)
else:
    run()
