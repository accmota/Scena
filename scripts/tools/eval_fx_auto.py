"""
eval_fx_auto.py — offline analysis of app_fx_auto_stress CSV logs.

Usage
-----
    python scripts/eval_fx_auto.py scripts/_fx_auto_ramp_up.csv
    python scripts/eval_fx_auto.py scripts/_fx_auto_*.csv --json /tmp/report.json
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _f(row: dict, key: str, default: float = float("nan")) -> float:
    v = row.get(key, "")
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(row: dict, key: str, default: int = -1) -> int:
    v = row.get(key, "")
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def load_csv(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def transitions(rows: Sequence[dict]) -> List[dict]:
    out: List[dict] = []
    prev = None
    for r in rows:
        label = (r.get("rung") or "").strip()
        if not label:
            continue
        if prev is None:
            prev = label
            continue
        if label != prev:
            out.append({
                "t": _f(r, "t"),
                "from": prev,
                "to": label,
                "n": _i(r, "n"),
                "ema_ms": _f(r, "ema_ms"),
                "fps": _f(r, "fps"),
                "bad_for_s": _f(r, "bad_for_s"),
                "good_for_s": _f(r, "good_for_s"),
            })
            prev = label
    return out


def oscillation_pairs(trans: Sequence[dict]) -> List[Tuple[dict, dict]]:
    pairs = []
    for i in range(len(trans) - 1):
        a, b = trans[i], trans[i + 1]
        if a["from"] == b["to"] and a["to"] == b["from"]:
            pairs.append((a, b))
    return pairs


def dwell_times(rows: Sequence[dict]) -> Dict[str, float]:
    """Approximate seconds spent on each rung from sample spacing."""
    if not rows:
        return {}
    dwell: Dict[str, float] = defaultdict(float)
    for i in range(len(rows) - 1):
        r0, r1 = rows[i], rows[i + 1]
        label = (r0.get("rung") or r0.get("quality") or "?").strip() or "?"
        dt = _f(r1, "t") - _f(r0, "t")
        if dt > 0 and dt < 5.0:  # ignore gaps
            dwell[label] += dt
    # last sample: no interval
    return dict(dwell)


def fps_alignment(rows: Sequence[dict], tol: float = 0.15) -> Dict[str, Any]:
    """Per-rung measured FPS vs present_hz / label target."""
    by: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for r in rows:
        label = (r.get("rung") or "").strip()
        if not label:
            continue
        fps = _f(r, "fps")
        tgt = _f(r, "present_hz")
        if math.isnan(fps) or fps <= 0:
            continue
        if math.isnan(tgt) or tgt <= 0:
            if "@" in label:
                try:
                    tgt = float(label.split("@", 1)[1])
                except ValueError:
                    continue
            else:
                continue
        by[label].append((fps, tgt))

    report = {}
    for label, pairs in sorted(by.items()):
        fpss = [p[0] for p in pairs]
        tgts = [p[1] for p in pairs]
        mean_fps = sum(fpss) / len(fpss)
        mean_tgt = sum(tgts) / len(tgts)
        # When overloaded, FPS can be *below* target — still report.
        # Instantaneous undershoot fraction (fps < 0.85 * tgt).
        under = sum(1 for f, t in pairs if f < t * (1.0 - tol))
        over = sum(1 for f, t in pairs if f > t * (1.0 + tol))
        report[label] = {
            "samples": len(pairs),
            "mean_fps": round(mean_fps, 2),
            "mean_target_hz": round(mean_tgt, 2),
            "mean_abs_err": round(abs(mean_fps - mean_tgt), 2),
            "mean_rel_err": round(abs(mean_fps - mean_tgt) / mean_tgt, 3) if mean_tgt else None,
            "within_tol_fraction": round(
                sum(1 for f, t in pairs if abs(f - t) / t <= tol) / len(pairs), 3
            ),
            "under_tol_fraction": round(under / len(pairs), 3),
            "over_tol_fraction": round(over / len(pairs), 3),
            "ok_mean_within_tol": abs(mean_fps - mean_tgt) / mean_tgt <= tol if mean_tgt else None,
        }
    return report


def work_vs_budget(rows: Sequence[dict]) -> Dict[str, Any]:
    """How often EMA sits above down-line / below up-line (decision pressure)."""
    stats = {
        "over_down": 0,
        "under_up": 0,
        "sticky": 0,
        "n": 0,
        "ema_samples": [],
    }
    for r in rows:
        ema = _f(r, "ema_ms")
        down = _f(r, "down_line_ms")
        up = _f(r, "up_line_ms")
        if math.isnan(ema) or math.isnan(down) or math.isnan(up):
            continue
        stats["n"] += 1
        stats["ema_samples"].append(ema)
        if ema > down:
            stats["over_down"] += 1
        elif ema < up:
            stats["under_up"] += 1
        else:
            stats["sticky"] += 1
    n = max(1, stats["n"])
    emas = stats.pop("ema_samples")
    return {
        "samples": stats["n"],
        "frac_over_down": round(stats["over_down"] / n, 3),
        "frac_under_up": round(stats["under_up"] / n, 3),
        "frac_sticky": round(stats["sticky"] / n, 3),
        "ema_mean_ms": round(sum(emas) / len(emas), 3) if emas else None,
        "ema_p95_ms": (
            round(sorted(emas)[int(0.95 * (len(emas) - 1))], 3) if emas else None
        ),
    }


def border_n_estimate(rows: Sequence[dict], a: str = "high@60", b: str = "medium@60") -> Optional[dict]:
    """Heuristic: N values seen near a↔b transitions."""
    trans = [t for t in transitions(rows) if {t["from"], t["to"]} == {a, b}]
    if not trans:
        return None
    ns = [t["n"] for t in trans if t["n"] >= 0]
    if not ns:
        return None
    return {
        "pair": f"{a}↔{b}",
        "transitions": len(trans),
        "n_min": min(ns),
        "n_max": max(ns),
        "n_mean": round(sum(ns) / len(ns), 1),
        "samples": ns,
    }


def analyze(path: str, fps_tol: float = 0.15) -> dict:
    rows = load_csv(path)
    trans = transitions(rows)
    osc = oscillation_pairs(trans)
    dwell = dwell_times(rows)
    fidelities = set()
    for r in rows:
        f = (r.get("fidelity") or "").strip()
        if f:
            fidelities.add(f)
        lab = (r.get("rung") or "").strip()
        if lab.startswith("low"):
            fidelities.add("low")

    n_vals = [_i(r, "n") for r in rows if _i(r, "n") >= 0]
    return {
        "path": path,
        "scenario": rows[0].get("scenario") if rows else None,
        "samples": len(rows),
        "duration_s": round(_f(rows[-1], "t") - _f(rows[0], "t"), 2) if len(rows) >= 2 else 0.0,
        "n_range": [min(n_vals), max(n_vals)] if n_vals else None,
        "heavy": bool(_i(rows[0], "heavy", 0)) if rows else False,
        "dwell_s": {k: round(v, 2) for k, v in sorted(dwell.items(), key=lambda kv: -kv[1])},
        "transitions": trans,
        "transition_count": len(trans),
        "oscillation_pairs": len(osc),
        "oscillation_detail": [
            {"t0": a["t"], "t1": b["t"], "pair": f"{a['from']}↔{a['to']}", "n": a["n"]}
            for a, b in osc
        ],
        "fps_alignment": fps_alignment(rows, tol=fps_tol),
        "work_vs_budget": work_vs_budget(rows),
        "border_high_med": border_n_estimate(rows, "high@60", "medium@60"),
        "border_med60_low60": border_n_estimate(rows, "medium@60", "low@60"),
        "border_low60_low30": border_n_estimate(rows, "low@60", "low@30"),
        "reached_fidelities": sorted(fidelities),
        "reached_low": "low" in fidelities,
        "verdict": _verdict(trans, osc, fps_alignment(rows, tol=fps_tol), fidelities),
    }


def _verdict(trans, osc, fps_align, fidelities) -> List[str]:
    notes = []
    if len(osc) >= 2:
        notes.append(
            f"OSCILLATION: {len(osc)} A↔B pairs — consider harder Up "
            f"(↑t_up / ↓k_up) or longer cooldown"
        )
    elif len(osc) == 1:
        notes.append("Mild A↔B flip once (may be load change, not sustained oscillation)")
    else:
        notes.append("No sustained oscillation pairs detected")

    bad_fps = [
        (lab, info) for lab, info in fps_align.items()
        if info.get("ok_mean_within_tol") is False and info.get("under_tol_fraction", 0) > 0.5
    ]
    if bad_fps:
        for lab, info in bad_fps:
            notes.append(
                f"FPS UNDER target on {lab}: mean {info['mean_fps']} vs "
                f"{info['mean_target_hz']} (work likely over budget — Auto should step down)"
            )
    else:
        ok = [lab for lab, info in fps_align.items() if info.get("ok_mean_within_tol")]
        if ok:
            notes.append(f"FPS mean within 15% of target on: {', '.join(ok)}")

    if "low" not in fidelities:
        notes.append("Did not reach low fidelity — raise --n-max and/or use --heavy / low_probe")
    else:
        notes.append("Reached low fidelity")

    if len(trans) == 0:
        notes.append("No rung transitions — load may be too light for Auto to leave high@60")

    return notes


def print_report(rep: dict) -> None:
    print("=" * 72)
    print(f"File: {rep['path']}")
    print(f"Scenario: {rep.get('scenario')}  samples={rep['samples']}  "
          f"dur={rep['duration_s']}s  N={rep.get('n_range')}  heavy={rep.get('heavy')}")
    print("-" * 72)
    print("Dwell (s):", rep.get("dwell_s"))
    print(f"Transitions: {rep['transition_count']}  oscillation_pairs: {rep['oscillation_pairs']}")
    for t in rep.get("transitions") or []:
        print(
            f"  t={t['t']:6.1f}  {t['from']:12s} → {t['to']:12s}  "
            f"N={t['n']}  ema={t['ema_ms']:.1f}ms  fps={t['fps']:.0f}"
        )
    print("FPS alignment:")
    for lab, info in (rep.get("fps_alignment") or {}).items():
        flag = "OK" if info.get("ok_mean_within_tol") else "!!"
        print(
            f"  [{flag}] {lab:12s}  mean_fps={info['mean_fps']:6.1f}  "
            f"tgt={info['mean_target_hz']:5.1f}  "
            f"rel_err={info['mean_rel_err']}  "
            f"within={info['within_tol_fraction']}"
        )
    w = rep.get("work_vs_budget") or {}
    print(
        f"Work vs budget: over_down={w.get('frac_over_down')}  "
        f"under_up={w.get('frac_under_up')}  sticky={w.get('frac_sticky')}  "
        f"ema_mean={w.get('ema_mean_ms')}ms"
    )
    for key in ("border_high_med", "border_med60_med30", "border_med30_low"):
        b = rep.get(key)
        if b:
            print(f"Border {b['pair']}: N∈[{b['n_min']},{b['n_max']}] mean={b['n_mean']}")
    print("Verdict:")
    for note in rep.get("verdict") or []:
        print(f"  • {note}")
    print("=" * 72)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="+", help="CSV log path(s) or globs")
    p.add_argument("--json", default="", help="write combined JSON report")
    p.add_argument("--fps-tol", type=float, default=0.15, help="relative FPS tolerance")
    ns = p.parse_args(argv)

    files: List[str] = []
    for pat in ns.paths:
        matched = sorted(glob.glob(pat))
        if matched:
            files.extend(matched)
        elif os.path.isfile(pat):
            files.append(pat)
        else:
            print(f"warn: no match for {pat}", file=sys.stderr)

    if not files:
        print("No CSV files found.", file=sys.stderr)
        return 2

    reports = [analyze(path, fps_tol=ns.fps_tol) for path in files]
    for rep in reports:
        print_report(rep)

    if ns.json:
        with open(ns.json, "w", encoding="utf-8") as f:
            json.dump(reports if len(reports) > 1 else reports[0], f, indent=2)
        print(f"Wrote {ns.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
