"""Run the balanced mix pulse (median of N fresh processes) and print a snapshot.

Usage
-----
    python scripts/bench/run_balanced.py
    python scripts/bench/run_balanced.py --repeats 3
    python scripts/bench/run_balanced.py --repeats 1   # debug / smoke
    python scripts/bench/run_balanced.py --no-append   # print only; do not write balanced.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fingerprint import (
    BENCH_DIR,
    REPO_ROOT,
    host_oneline,
    script_hashes as _script_hashes,
    scripts_fingerprint,
)
from pulse import (
    append_pulse,
    autodiff,
    cell_fb_tag,
    fb_cell_suffix,
    fb_scale_tag,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)

PROTOCOL = "balanced-2"
RESULTS = BENCH_DIR / "results"
LOG_PATH = BENCH_DIR / "balanced.md"
SCRIPT_FILES = (
    "cpu_mix.py",
    "gpu_mix.py",
    "live_mix.py",
    "soak_leak.py",
    "harness.py",
    "run_balanced.py",
)

PROBES = (
    {
        "id": "cpu_mix",
        "argv": [
            "cpu_mix.py", "--bench",
            "--n", "180", "--duration", "2", "--warmup", "0.5", "--seed", "42",
        ],
    },
    {
        "id": "gpu_mix",
        "argv": [
            "gpu_mix.py", "--bench",
            "--mode", "realistic", "--quality", "high",
            "--duration", "3", "--warmup", "0.5", "--seed", "42",
        ],
    },
    {
        "id": "gpu_heroes",
        "argv": [
            "gpu_mix.py", "--bench",
            "--mode", "heroes_mass", "--n-heroes", "48", "--quality", "high",
            "--duration", "3", "--warmup", "0.5", "--seed", "42",
        ],
    },
    {
        "id": "live_mix",
        "argv": [
            "live_mix.py", "--bench",
            "--n", "80", "--quality", "high",
            "--duration", "3", "--warmup", "0.5", "--seed", "42",
        ],
    },
    {
        "id": "soak",
        "argv": [
            "soak_leak.py",
            "--cycles", "30", "--idle-frames", "40", "--churn-frames", "10",
            "--quality", "high",
        ],
    },
)


def script_hashes() -> Dict[str, str]:
    return _script_hashes(SCRIPT_FILES, BENCH_DIR)


def fingerprint(hashes: Dict[str, str]) -> str:
    return scripts_fingerprint(hashes, SCRIPT_FILES)


def _median(xs: Sequence[float]) -> float:
    vals = [float(x) for x in xs if x == x]
    if not vals:
        return float("nan")
    return float(statistics.median(vals))


def _spread_pct(xs: Sequence[float]) -> float:
    vals = [float(x) for x in xs if x == x]
    if len(vals) < 2:
        return 0.0
    med = statistics.median(vals)
    if med == 0:
        return 0.0
    return 100.0 * (max(vals) - min(vals)) / abs(med)


def _parse_result_json_line(text: str) -> Optional[Dict[str, Any]]:
    for line in text.splitlines():
        if line.startswith("RESULT_JSON:"):
            raw = line.split(":", 1)[1].strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
    return None


def run_probe(probe: Dict[str, str], *, repeat: int, json_path: Path) -> Dict[str, Any]:
    script, *rest = probe["argv"]
    cmd = [sys.executable, str(BENCH_DIR / script), *rest, "--json", str(json_path)]
    print(f"\n>> {probe['id']}  repeat={repeat + 1}  {' '.join(cmd[2:])}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"{probe['id']} repeat {repeat + 1} exited {proc.returncode}")
    if json_path.is_file():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        payload = _parse_result_json_line(proc.stdout or "") or {}
    payload["_probe"] = probe["id"]
    payload["_repeat"] = repeat
    return payload


def _num(rows: List[Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for row in rows:
        if key not in row:
            continue
        try:
            out.append(float(row[key]))
        except (TypeError, ValueError):
            continue
    return out


def summarize_probe(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = (
        "fps", "work_ms", "tick_ms", "coll_ms", "flush_ms", "draw_ms", "post_ms",
        "submit_ms", "present_ms", "frames",
        "last_rss_mb", "last_idle_work_ms", "delta_rss_mb", "delta_work_ms",
        "delta_objects", "delta_handles",
        "fb_width", "fb_height", "design_w", "design_h", "n_shapes", "n_heroes",
    )
    out: Dict[str, Any] = {"repeats": len(rows)}
    for key in keys:
        vals = _num(rows, key)
        if not vals:
            continue
        out[key] = _median(vals)
        out[f"{key}_spread_pct"] = _spread_pct(vals)
        out[f"{key}_min"] = min(vals)
        out[f"{key}_max"] = max(vals)
    return out


def _fmt_ms(summary: Dict[str, Any], key: str = "work_ms") -> str:
    v = summary.get(key)
    if v is None or v != v:
        return "?"
    spread = summary.get(f"{key}_spread_pct", 0.0)
    extra = f" ±{spread:.0f}%" if spread >= 1.0 else ""
    return f"{v:.3f}{extra}"


def _fmt_phase(summary: Dict[str, Any]) -> str:
    parts = []
    for key, short in (("tick_ms", "t"), ("coll_ms", "c"), ("draw_ms", "d")):
        v = summary.get(key)
        if v is None or v != v:
            continue
        parts.append(f"{short}{v:.2f}")
    return " ".join(parts)


def render_markdown(bundle: Dict[str, Any]) -> str:
    host = bundle["host"]
    hashes = bundle["scripts"]
    probes = bundle["probes"]
    date = bundle["date"]
    cpu = probes["cpu_mix"]
    gpu = probes["gpu_mix"]
    heroes = probes["gpu_heroes"]
    live = probes["live_mix"]
    soak = probes["soak"]

    host_s = host_oneline(host)
    row = _summary_row_line(bundle)

    hash_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in hashes.items())
    lines = [
        f"### {date} — {bundle['protocol']}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {bundle['when']} |",
        f"| Protocol | `{bundle['protocol']}` ({bundle['pro_forma']}) |",
        f"| Host | {host_s} |",
        f"| Git | {bundle['git']} |",
        f"| Scena | `{bundle['scena_fingerprint']}` |",
        f"| Repeats | {bundle['repeats']} (median) |",
        f"| Scripts | fingerprint `{bundle['fingerprint']}` |",
        "",
        "| File | sha256[:12] |",
        "|------|-------------|",
        hash_rows,
        "",
        "Summary row:",
        "",
        row,
        "",
        "#### cpu_mix",
        "",
        f"- work_ms **{_fmt_ms(cpu)}**  FPS {cpu.get('fps', float('nan')):.1f}  "
        f"tick {cpu.get('tick_ms', float('nan')):.3f}  "
        f"coll {cpu.get('coll_ms', float('nan')):.3f}  "
        f"draw {cpu.get('draw_ms', float('nan')):.3f}",
        "",
        "#### gpu_mix (realistic)",
        "",
        f"- work_ms **{_fmt_ms(gpu)}**  FPS {gpu.get('fps', float('nan')):.1f}  "
        f"draw {gpu.get('draw_ms', float('nan')):.3f}  "
        f"post {gpu.get('post_ms', float('nan')):.3f}  "
        f"FB {int(gpu.get('fb_width', 0))}×{int(gpu.get('fb_height', 0))}",
        "",
        "#### gpu_mix (heroes_mass n=48)",
        "",
        f"- work_ms **{_fmt_ms(heroes)}**  FPS {heroes.get('fps', float('nan')):.1f}  "
        f"draw {heroes.get('draw_ms', float('nan')):.3f}  "
        f"post {heroes.get('post_ms', float('nan')):.3f}  "
        f"FB {int(heroes.get('fb_width', 0))}×{int(heroes.get('fb_height', 0))}",
        "",
        "#### live_mix",
        "",
        f"- work_ms **{_fmt_ms(live)}**  FPS {live.get('fps', float('nan')):.1f}  "
        f"tick {live.get('tick_ms', float('nan')):.3f}  "
        f"coll {live.get('coll_ms', float('nan')):.3f}  "
        f"draw {live.get('draw_ms', float('nan')):.3f}",
        "",
        "#### soak_leak",
        "",
        f"- last RSS **{soak.get('last_rss_mb', float('nan')):.2f} MiB**  "
        f"last idle **{soak.get('last_idle_work_ms', float('nan')):.3f} ms**  "
        f"Δrss {soak.get('delta_rss_mb', float('nan')):.2f}  "
        f"Δwork {soak.get('delta_work_ms', float('nan')):.3f}  "
        f"Δobj {soak.get('delta_objects', float('nan')):.0f}  "
        f"Δhandles {soak.get('delta_handles', float('nan')):.0f}",
        "",
    ]
    return "\n".join(lines)


def _summary_row_line(bundle: Dict[str, Any]) -> str:
    probes = bundle["probes"]
    cpu = probes["cpu_mix"]
    gpu = probes["gpu_mix"]
    heroes = probes["gpu_heroes"]
    live = probes["live_mix"]
    soak = probes["soak"]
    soak_s = (
        f"{soak.get('last_rss_mb', float('nan')):.1f} MiB / "
        f"{soak.get('last_idle_work_ms', float('nan')):.3f} ms / "
        f"Δobj {soak.get('delta_objects', float('nan')):.0f}"
    )
    return (
        f"| {bundle['date']} | {bundle['protocol']} | {host_oneline(bundle['host'])} | "
        f"{cpu.get('work_ms', float('nan')):.3f} ({cpu.get('fps', float('nan')):.1f}) "
        f"`{_fmt_phase(cpu)}` | "
        f"{gpu.get('work_ms', float('nan')):.3f} ({gpu.get('fps', float('nan')):.1f})"
        f"{fb_cell_suffix(_probe_fb_tag(gpu))} | "
        f"{heroes.get('work_ms', float('nan')):.3f} ({heroes.get('fps', float('nan')):.1f})"
        f"{fb_cell_suffix(_probe_fb_tag(heroes))} | "
        f"{live.get('work_ms', float('nan')):.3f} ({live.get('fps', float('nan')):.1f}) "
        f"`{_fmt_phase(live)}` | "
        f"{soak_s} | {bundle.get('notes', '')} |"
    )


def _parse_soak_rss(cell: str) -> Optional[float]:
    import re
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*MiB", cell)
    return float(m.group(1)) if m else None


def _balanced_metrics(bundle: Dict[str, Any]) -> Dict[str, float]:
    p = bundle["probes"]
    out: Dict[str, float] = {}
    for key, probe in (
        ("cpu_work_ms", "cpu_mix"),
        ("gpu_work_ms", "gpu_mix"),
        ("heroes_work_ms", "gpu_heroes"),
        ("live_work_ms", "live_mix"),
    ):
        v = p.get(probe, {}).get("work_ms")
        if v is not None and v == v:
            out[key] = float(v)
    soak = p.get("soak", {})
    rss = soak.get("last_rss_mb")
    if rss is not None and rss == rss:
        out["soak_rss_mb"] = float(rss)
    return out


# GPU-bound cells (summary column index, bundle probe). Their framebuffer scale
# is part of the workload: compare only against a row at the same scale.
_FB_CELLS = (("gpu_work_ms", 4, "gpu_mix"), ("heroes_work_ms", 5, "gpu_heroes"))


def _probe_fb_tag(probe: Dict[str, Any]) -> Optional[str]:
    """Scale of a summarized probe; ``"mixed"`` when its repeats disagree
    (the window moved to another display mid-run — never median that away)."""
    lo, hi = probe.get("fb_width_min"), probe.get("fb_width_max")
    if lo is not None and hi is not None and lo != hi:
        return "mixed"
    return fb_scale_tag(probe.get("fb_width"), probe.get("design_w"))


def _prev_balanced_metrics(
    md_text: str,
    fb_tags: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[Optional[Dict[str, float]], Dict[str, str], List[str]]:
    """Previous-row metrics for auto-diff, plus per-key labels and notes.

    cpu / live / soak come from the newest ``balanced-2`` row. GPU cells come
    from the newest row whose cell was measured at the same framebuffer scale
    as ``fb_tags[key]`` (unknown tag → newest row, as before). A GPU key with
    no same-scale row is left out and explained in ``notes``.
    """
    fb_tags = fb_tags or {}
    rows = [
        c for c in parse_summary_table(md_text)
        if len(c) >= 8 and c[1].strip().strip("`") == PROTOCOL
        and parse_leading_float(c[3]) is not None
    ]
    if not rows:
        return None, {}, []
    newest = rows[0]
    out: Dict[str, float] = {"cpu_work_ms": parse_leading_float(newest[3])}
    live = parse_leading_float(newest[6])
    if live is not None:
        out["live_work_ms"] = live
    rss = _parse_soak_rss(newest[7])
    if rss is not None:
        out["soak_rss_mb"] = rss
    labels: Dict[str, str] = {}
    notes: List[str] = []
    for key, col, _probe in _FB_CELLS:
        want = fb_tags.get(key)
        for i, cells in enumerate(rows):
            v = parse_leading_float(cells[col])
            if v is None:
                continue
            got = cell_fb_tag(cells[col])
            if want is not None and got != want:
                continue
            out[key] = v
            if i:
                labels[key] = f"{cells[0]} {PROTOCOL} row (last at FB {got})"
                notes.append(
                    f"{key}: FB {want} differs from the newest row (FB {cell_fb_tag(newest[col])}) "
                    f"→ compared with the {cells[0]} row instead"
                )
            break
        else:
            newest_tag = cell_fb_tag(newest[col])
            notes.append(
                f"{key}: not compared — measured at FB {want}; no earlier {PROTOCOL} row at "
                f"FB {want} (newest is FB {newest_tag}): different workload, re-run on the usual display"
            )
    return out, labels, notes


def _autodiff_balanced(bundle: Dict[str, Any]) -> None:
    if not LOG_PATH.is_file():
        return
    text = LOG_PATH.read_text(encoding="utf-8")
    fb_tags = {key: _probe_fb_tag(bundle["probes"].get(probe, {})) for key, _c, probe in _FB_CELLS}
    prev, labels, notes = _prev_balanced_metrics(text, fb_tags)
    prev_fp = latest_scena_fingerprint(text)
    new_fp = bundle.get("scena_fingerprint")
    same: Optional[bool]
    if prev_fp and new_fp:
        same = prev_fp == new_fp
    else:
        same = None
    warnings = autodiff(
        _balanced_metrics(bundle),
        prev,
        same_scena=same,
        prev_label="last balanced-2 row",
        prev_labels=labels,
        # An older same-FB row: the newest row's fingerprint says nothing about it.
        same_scena_by_key={k: None for k in labels},
    )
    print_autodiff_banner(warnings, same_scena=same, notes=notes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3,
                        help="independent process repeats per probe (default 3)")
    parser.add_argument(
        "--notes", default="pro-forma (protocol bump)",
        help="Notes cell for the summary row",
    )
    parser.add_argument(
        "--comparable", action="store_true",
        help="mark this run as comparable (not pro-forma)",
    )
    parser.add_argument(
        "--no-append", action="store_true",
        help="print the snapshot only; do not write balanced.md",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")

    RESULTS.mkdir(parents=True, exist_ok=True)
    hashes = script_hashes()
    meta = now_meta()
    bundle: Dict[str, Any] = {
        "protocol": PROTOCOL,
        "pro_forma": "comparable" if args.comparable else "pro-forma — protocol bump / first snapshot",
        "notes": args.notes if not args.comparable else (args.notes or ""),
        "date": meta["date"],
        "when": meta["when"],
        "git": meta["git"],
        "host": meta["host"],
        "scripts": hashes,
        "fingerprint": fingerprint(hashes),
        "scena_fingerprint": meta["scena_fingerprint"],
        "repeats": args.repeats,
        "probes": {},
        "raw": {},
    }

    t0 = time.perf_counter()
    for probe in PROBES:
        rows: List[Dict[str, Any]] = []
        for i in range(args.repeats):
            json_path = RESULTS / f"balanced_{probe['id']}_{i}.json"
            rows.append(run_probe(probe, repeat=i, json_path=json_path))
            # Let GLFW / the window server settle between processes (macOS).
            time.sleep(0.75)
        bundle["raw"][probe["id"]] = rows
        bundle["probes"][probe["id"]] = summarize_probe(rows)
    bundle["elapsed_s"] = round(time.perf_counter() - t0, 1)

    out_json = RESULTS / "balanced_latest.json"
    slim = {k: v for k, v in bundle.items() if k != "raw"}
    # Drop per-sample lists from soak repeats in the latest file; keep medians.
    out_json.write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md = render_markdown(bundle)
    _autodiff_balanced(bundle)
    print("\n" + "=" * 60)
    print("balanced pulse")
    print("=" * 60)
    print(md)
    print(f"wrote {out_json}  elapsed={bundle['elapsed_s']:.1f}s")
    if not args.no_append:
        row = _summary_row_line(bundle)
        append_pulse(LOG_PATH, row, md)
        print(f"appended {LOG_PATH}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


if __name__ == "__main__":
    main()
