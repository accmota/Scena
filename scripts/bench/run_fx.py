"""Run the FX matrix pulse (protocol fx-1) and append ``fx.md``.

    python scripts/bench/run_fx.py
    python scripts/bench/run_fx.py --no-append
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fingerprint import BENCH_DIR, REPO_ROOT, host_oneline, script_hashes, scripts_fingerprint
from pulse import (
    append_pulse,
    autodiff,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)

PROTOCOL = "fx-1"
RESULTS = BENCH_DIR / "results"
LOG_PATH = BENCH_DIR / "fx.md"
SCRIPT_FILES = ("perf_fx_matrix.py", "run_fx.py")
FROZEN_ARGV = [
    "perf_fx_matrix.py",
    "--duration", "0.85",
    "--warmup", "0.3",
    "--n", "48",
    "--quality", "high",
]


def _cell(payload: Dict[str, Any], effect: str, quality: str = "high") -> Optional[Dict[str, Any]]:
    return (payload.get("results") or {}).get(f"{effect}|{quality}")


def _ms(cell: Optional[Dict[str, Any]]) -> Optional[float]:
    if not cell:
        return None
    v = cell.get("ms")
    if v is None:
        fps = cell.get("fps")
        if fps:
            v = 1000.0 / float(fps)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rank(payload: Dict[str, Any], quality: str = "high") -> List[Tuple[str, str, float, float]]:
    """Slowest-first (effect, category, ms, extra_ms vs baseline)."""
    base = _ms(_cell(payload, "baseline", quality)) or 0.0
    cat = {e["key"]: e.get("category", "") for e in payload.get("effects") or []}
    rows: List[Tuple[str, str, float, float]] = []
    for key, cell in (payload.get("results") or {}).items():
        if not key.endswith(f"|{quality}"):
            continue
        effect = key.split("|", 1)[0]
        if effect == "baseline":
            continue
        ms = _ms(cell)
        if ms is None:
            continue
        rows.append((effect, cat.get(effect, ""), ms, ms - base))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows


def render_markdown(bundle: Dict[str, Any]) -> Tuple[str, str]:
    meta = bundle["meta"]
    payload = bundle["payload"]
    base_ms = bundle["baseline_ms"]
    base_fps = bundle["baseline_fps"]
    rank = bundle["rank"]
    host_s = host_oneline(meta["host"])
    top3 = " · ".join(
        f"{name} {extra:+.1f}" for name, _cat, _ms, extra in rank[:3]
    )
    row = (
        f"| {meta['date']} | {PROTOCOL} | {host_s} | "
        f"{base_ms:.3f} ({base_fps:.0f}) | {top3} | {bundle.get('notes', '')} |"
    )
    hashes = bundle["scripts"]
    hash_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in hashes.items())
    rank_lines = [
        "| # | Effect | Cat | ms | +ms vs base |",
        "|--:|--------|-----|---:|------------:|",
    ]
    for i, (name, cat, ms, extra) in enumerate(rank[:10], 1):
        rank_lines.append(f"| {i} | `{name}` | {cat} | {ms:.2f} | {extra:+.2f} |")
    section = "\n".join([
        f"### {meta['date']} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` ({bundle['pro_forma']}) |",
        f"| Host | {host_s} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Repeats | single-shot per cell |",
        f"| Scripts | fingerprint `{bundle['fingerprint']}` |",
        "",
        "| File | sha256[:12] |",
        "|------|-------------|",
        hash_rows,
        "",
        "Frozen argv as in the protocol table.",
        "",
        "#### baseline @ high",
        "",
        f"- **{base_ms:.3f} ms**  ({base_fps:.0f} fps)",
        "",
        "#### top-10 rank",
        "",
        *rank_lines,
        "",
    ])
    return row, section


def _prev_metrics(md_text: str) -> Optional[Dict[str, float]]:
    for cells in parse_summary_table(md_text):
        if len(cells) < 4:
            continue
        if cells[1].strip().strip("`") != PROTOCOL:
            continue
        base = parse_leading_float(cells[3])
        if base is not None:
            return {"baseline_ms": base}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="", help="Notes cell for the summary row")
    parser.add_argument(
        "--comparable", action="store_true",
        help="mark this run as comparable (not pro-forma)",
    )
    parser.add_argument(
        "--no-append", action="store_true",
        help="print the snapshot only; do not write fx.md",
    )
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS / "fx_latest.json"
    cmd = [sys.executable, str(BENCH_DIR / FROZEN_ARGV[0]), *FROZEN_ARGV[1:], "--json", str(json_path)]
    print(f">> fx-1  {' '.join(cmd[2:])}", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"perf_fx_matrix exited {proc.returncode}")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    base = _cell(payload, "baseline", "high") or {}
    base_ms = _ms(base)
    if base_ms is None:
        raise SystemExit("fx pulse: no baseline|high in JSON")
    base_fps = float(base.get("fps") or (1000.0 / base_ms))
    hashes = script_hashes(SCRIPT_FILES)
    meta = now_meta()
    bundle: Dict[str, Any] = {
        "meta": meta,
        "payload": payload,
        "baseline_ms": base_ms,
        "baseline_fps": base_fps,
        "rank": _rank(payload),
        "scripts": hashes,
        "fingerprint": scripts_fingerprint(hashes, SCRIPT_FILES),
        "pro_forma": "comparable" if args.comparable else "pro-forma",
        "notes": args.notes,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "scena_fingerprint": meta["scena_fingerprint"],
    }
    row, section = render_markdown(bundle)
    prev_text = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.is_file() else ""
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same: Optional[bool]
    if prev_fp and meta["scena_fingerprint"]:
        same = prev_fp == meta["scena_fingerprint"]
    else:
        same = None
    warnings = autodiff(
        {"baseline_ms": base_ms},
        _prev_metrics(prev_text),
        same_scena=same,
        prev_label="last fx-1 row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print("\n" + "=" * 60)
    print("fx pulse")
    print("=" * 60)
    print(section)
    print(f"wrote {json_path}  elapsed={bundle['elapsed_s']:.1f}s")
    if not args.no_append:
        append_pulse(LOG_PATH, row, section)
        print(f"appended {LOG_PATH}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


if __name__ == "__main__":
    main()
