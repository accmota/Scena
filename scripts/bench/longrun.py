"""Long-run pulse: jitter, hitches, GC, and slow drift under the product loop.

Runs ``live_mix.py`` (sprites + shapes + SpatialFx + camera + background +
spawn/destroy churn) in the **real** run loop with product pacing (FX Auto →
fixed 60) for minutes, under ``frame_probe``. Catches what short isolates can't:
beat judder between the frame timer and the display, GC pauses, leaks, and
work that creeps up over time.

    python scripts/bench/longrun.py --pulse                 # protocol longrun-2 (5 min), append longrun.md
    python scripts/bench/longrun.py --minutes 30            # ad-hoc, print only
    python scripts/bench/longrun.py --minutes 10 --present vsync
    python scripts/bench/longrun.py --minutes 5 --gc-freeze # A/B experiment
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fingerprint import BENCH_DIR, REPO_ROOT, script_hashes
from pulse import (
    append_pulse,
    autodiff,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)

PROTOCOL = "longrun-2"
LOG_PATH = BENCH_DIR / "longrun.md"
SCRIPT_FILES = ("longrun.py", "jitter_probe.py", "frame_probe.py", "live_mix.py")
PULSE_MINUTES = 5.0
PULSE_PRESENT = "auto"


def _probe_argv(minutes: float, present: str, json_path: str, extra: List[str]) -> List[str]:
    return [
        sys.executable, str(BENCH_DIR / "jitter_probe.py"),
        str(BENCH_DIR / "live_mix.py"),
        "--seconds", f"{minutes * 60.0:g}",
        "--present", present,
        "--startup", "10",
        "--objects-every", "30",
        "--json", json_path,
        *extra,
    ]


def run_probe(minutes: float, present: str, extra: List[str]) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        jpath = str(Path(td) / "longrun.json")
        cmd = _probe_argv(minutes, present, jpath, extra)
        print(f"=== longrun  {minutes:g} min  present={present}  ({' '.join(cmd[2:4])}) ===", flush=True)
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if proc.returncode != 0 or not Path(jpath).is_file():
            raise SystemExit(f"probe failed (exit {proc.returncode})")
        return json.loads(Path(jpath).read_text(encoding="utf-8"))


def _num(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{float(v):.{digits}f}"


def headline(rep: Dict[str, Any]) -> Dict[str, Optional[float]]:
    pr = rep.get("present") or {}
    dr = rep.get("drift") or {}
    return {
        "held_per_min": pr.get("held_per_min"),
        "episodes_per_min": pr.get("episodes_per_min"),
        "hitch_per_min": (rep.get("hitches") or {}).get("steady_per_min"),
        "dur_p99": (rep.get("dur_steady") or {}).get("p99"),
        "gc2_max": (rep.get("gc") or {}).get("gen2_max_ms"),
        "rss_per_10min": dr.get("rss_mb_per_10min"),
        "objs_per_10min": dr.get("py_objects_per_10min"),
        "work_pct_per_10min": dr.get("work_pct_per_10min"),
    }


def render(rep: Dict[str, Any], meta: Dict[str, Any], hashes: Dict[str, str], minutes: float, present: str):
    h = headline(rep)
    pr = rep.get("present") or {}
    su = rep.get("startup") or {}
    host_s = meta["host_s"]
    date = meta["date"]
    row = (
        f"| {date} | `{PROTOCOL}` | {host_s} | "
        f"{_num(h['held_per_min'])} ({_num(h['episodes_per_min'])}) | "
        f"{_num(h['hitch_per_min'])} | {_num(h['dur_p99'])} | {_num(h['gc2_max'], 1)} | "
        f"{_num(h['rss_per_10min'])} | {_num(h['work_pct_per_10min'], 1)} | "
        f"{_num(su.get('worst_dur_ms'), 1)} | |"
    )
    hash_s = " · ".join(f"`{k}` `{v}`" for k, v in hashes.items())
    ep = pr.get("episode_list") or []
    ep_s = ", ".join(f"{e['t']:.0f}s/{e['len_s']:.1f}s" for e in ep[:12]) or "—"
    worst = rep.get("worst_frames") or []
    worst_lines = [
        f"| {w['t']:.1f} | {w['dur_ms']:.1f} | {w['work_ms']:.1f} | {w['swap_ms']:.1f} | {w['pace_ms']:.1f} | {w['cause']} |"
        for w in worst[:8]
    ]
    gc = rep.get("gc") or {}
    dr = rep.get("drift") or {}
    lines = [
        f"### {date} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` |",
        f"| Host | {host_s} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Run | {minutes:g} min · present `{present}` → {rep['meta'].get('present_mode')} "
        f"{_num(rep.get('target_hz'), 0)} Hz · display {_num(rep.get('display_hz'), 3)} Hz |",
        f"| Scripts | {hash_s} |",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| frames / fps | {rep.get('frames')} / {_num(rep.get('fps'), 1)} |",
        f"| held frames /min (episodes /min) | **{_num(h['held_per_min'])}** ({_num(h['episodes_per_min'])}) |",
        f"| dropped /min | {_num(pr.get('dropped_per_min'))} |",
        f"| episode spacing (predicted beat) | {_num(pr.get('episode_spacing_s'), 1)} s ({_num(pr.get('predicted_beat_s'), 1)} s) |",
        f"| frames Hz vs refresh Hz | {_num(pr.get('frames_hz'), 4)} vs {_num(pr.get('refresh_hz'), 4)} |",
        f"| hitches /min (dur > {_num((rep.get('thresholds') or {}).get('hitch_ms'), 1)} ms) | {_num(h['hitch_per_min'])} |",
        f"| dur p50 / p99 / max (steady) | {_num((rep.get('dur_steady') or {}).get('p50'))} / {_num(h['dur_p99'])} / {_num((rep.get('dur_steady') or {}).get('max'), 1)} ms |",
        f"| work p50 / p99 (steady) | {_num((rep.get('work_steady') or {}).get('p50'), 3)} / {_num((rep.get('work_steady') or {}).get('p99'), 3)} ms |",
        f"| GC gen2 n / max | {(gc.get('gen2') or {}).get('count', '—')} / {_num(h['gc2_max'], 1)} ms |",
        f"| RSS first→last (slope) | {_num(dr.get('rss_mb_first'), 1)} → {_num(dr.get('rss_mb_last'), 1)} MiB ({_num(h['rss_per_10min'])} MiB/10min) |",
        f"| Python objects (slope) | {dr.get('py_objects_first', '—')} → {dr.get('py_objects_last', '—')} ({_num(h['objs_per_10min'], 0)}/10min) |",
        f"| work drift | {_num(h['work_pct_per_10min'], 1)} %/10min |",
        f"| startup worst frame | {_num(su.get('worst_dur_ms'), 1)} ms |",
        "",
        f"Episodes (start / length): {ep_s}",
        "",
        "Worst frames:",
        "",
        "| t s | dur ms | work ms | swap ms | pace ms | cause |",
        "|----:|-------:|--------:|--------:|--------:|-------|",
        *worst_lines,
        "",
    ]
    return row, "\n".join(lines)


def run_pulse(no_append: bool) -> None:
    meta = now_meta()
    hashes = script_hashes(SCRIPT_FILES, BENCH_DIR)
    rep = run_probe(PULSE_MINUTES, PULSE_PRESENT, [])
    row, section = render(rep, meta, hashes, PULSE_MINUTES, PULSE_PRESENT)
    prev_text = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.is_file() else ""
    prev = None
    for cells in parse_summary_table(prev_text):
        if len(cells) >= 5 and cells[1].strip().strip("`") == PROTOCOL:
            prev = {
                "held_per_min": parse_leading_float(cells[3]),
                "hitch_per_min": parse_leading_float(cells[4]),
                "dur_p99": parse_leading_float(cells[5]) if len(cells) > 5 else None,
            }
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same = (prev_fp == meta["scena_fingerprint"]) if prev_fp else None
    h = headline(rep)
    new = {k: float(h[k]) for k in ("held_per_min", "hitch_per_min", "dur_p99") if h.get(k) is not None}
    # Counts near zero swing wildly in %; only diff rates that are meaningfully non-zero.
    new = {k: v for k, v in new.items() if k == "dur_p99" or v >= 1.0}
    print_autodiff_banner(
        autodiff(new, {k: v for k, v in (prev or {}).items() if v is not None}, same_scena=same,
                 prev_label=f"last {PROTOCOL} row"),
        same_scena=same,
    )
    print(section)
    if not no_append:
        append_pulse(LOG_PATH, row, section)
        print(f"appended {LOG_PATH}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pulse", action="store_true", help=f"protocol {PROTOCOL}: {PULSE_MINUTES:g} min, present {PULSE_PRESENT}")
    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--present", default="auto", choices=("keep", "auto", "fixed60", "fixed30", "vsync", "none"))
    p.add_argument("--gc-freeze", action="store_true")
    p.add_argument("--no-append", action="store_true")
    p.add_argument("--json", dest="json_path", default=None)
    args = p.parse_args()
    if args.pulse:
        run_pulse(args.no_append)
        return
    extra = ["--gc-freeze"] if args.gc_freeze else []
    rep = run_probe(args.minutes, args.present, extra)
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    print("RESULT_JSON: " + json.dumps(headline(rep)))


if __name__ == "__main__":
    main()
