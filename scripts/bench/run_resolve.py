"""Resolve pulse: mutual circle pool (n=40) and platformer sprite shots (50).

    python scripts/bench/run_resolve.py
    python scripts/bench/run_resolve.py --no-append
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

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

PROTOCOL = "resolve-2"
LOG_PATH = BENCH_DIR / "resolve.md"
SCRIPT_FILES = (
    "perf_resolve_balls.py",
    "perf_resolve_platformer.py",
    "run_resolve.py",
    "harness.py",
)

PROBES = (
    {
        "id": "balls",
        "argv": [
            "perf_resolve_balls.py", "--bench",
            "--n", "40", "--duration", "3", "--warmup", "0.5", "--seed", "42",
        ],
    },
    {
        "id": "platformer",
        "argv": [
            "perf_resolve_platformer.py", "--bench",
            "--balls", "50", "--duration", "3", "--warmup", "0.5", "--seed", "42",
        ],
    },
)


def _parse_result(text: str) -> Optional[Dict[str, Any]]:
    for line in (text or "").splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line.split(":", 1)[1].strip())
    return None


def _run(probe: Dict[str, Any]) -> Dict[str, Any]:
    script, *rest = probe["argv"]
    cmd = [sys.executable, str(BENCH_DIR / script), *rest]
    print(f">> {probe['id']}  {' '.join(cmd[2:])}", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout or "")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"{probe['id']} exited {proc.returncode}")
    row = _parse_result(proc.stdout or "") or {}
    row["ok"] = True
    return row


def _cell(result: Dict[str, Any]) -> Tuple[float, float, float, float]:
    return (
        float(result.get("coll_ms", float("nan"))),
        float(result.get("ms_resolve", float("nan"))),
        float(result.get("work_ms", float("nan"))),
        float(result.get("fps", 0)),
    )


def _phase_line(label: str, result: Dict[str, Any]) -> str:
    coll, resolve, work, fps = _cell(result)
    return (
        f"- {label}: coll_ms **{coll:.3f}**  ms_resolve **{resolve:.3f}**  "
        f"work_ms {work:.3f}  FPS {fps:.1f}  "
        f"broad {float(result.get('ms_broad', 0)):.3f}  "
        f"narrow {float(result.get('ms_narrow', 0)):.3f}  "
        f"proxy_pairs {float(result.get('proxy_pairs', 0)):.1f}"
    )


def render_markdown(
    *,
    balls: Dict[str, Any],
    platformer: Dict[str, Any],
    meta: Dict[str, Any],
    hashes: Dict[str, str],
    fingerprint: str,
    notes: str,
    pro_forma: str,
) -> Tuple[str, str]:
    host_s = host_oneline(meta["host"])
    date = meta["date"]
    b_coll, b_res, _b_work, b_fps = _cell(balls)
    p_coll, p_res, _p_work, p_fps = _cell(platformer)
    row = (
        f"| {date} | `{PROTOCOL}` | {host_s} | "
        f"{b_coll:.3f} ({b_fps:.1f}) | {b_res:.3f} | "
        f"{p_coll:.3f} ({p_fps:.1f}) | {p_res:.3f} | {notes} |"
    )
    hash_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in hashes.items())
    section = "\n".join([
        f"### {date} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` ({pro_forma}) |",
        f"| Host | {host_s} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Repeats | single-shot |",
        f"| Scripts | fingerprint `{fingerprint}` |",
        "",
        "| File | sha256[:12] |",
        "|------|-------------|",
        hash_rows,
        "",
        "Frozen argv as in the protocol table.",
        "",
        _phase_line("balls n=40", balls),
        _phase_line("platformer balls=50", platformer),
        "",
    ])
    return row, section


def _prev_metrics(md_text: str) -> Optional[Dict[str, float]]:
    for cells in parse_summary_table(md_text):
        if len(cells) < 7:
            continue
        if cells[1].strip().strip("`") != PROTOCOL:
            continue
        balls_coll = parse_leading_float(cells[3])
        balls_res = parse_leading_float(cells[4])
        plat_coll = parse_leading_float(cells[5])
        plat_res = parse_leading_float(cells[6])
        if balls_coll is None:
            continue
        out = {"balls_coll_ms": balls_coll}
        if balls_res is not None:
            out["balls_ms_resolve"] = balls_res
        if plat_coll is not None:
            out["platformer_coll_ms"] = plat_coll
        if plat_res is not None:
            out["platformer_ms_resolve"] = plat_res
        return out
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="")
    parser.add_argument("--comparable", action="store_true")
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()

    meta = now_meta()
    hashes = script_hashes(SCRIPT_FILES)
    t0 = time.perf_counter()
    results: Dict[str, Dict[str, Any]] = {}
    for probe in PROBES:
        results[probe["id"]] = _run(probe)
        time.sleep(0.4)
    elapsed = round(time.perf_counter() - t0, 1)
    balls, platformer = results["balls"], results["platformer"]
    row, section = render_markdown(
        balls=balls,
        platformer=platformer,
        meta=meta,
        hashes=hashes,
        fingerprint=scripts_fingerprint(hashes, SCRIPT_FILES),
        notes=args.notes,
        pro_forma="comparable" if args.comparable else "pro-forma",
    )
    prev_text = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.is_file() else ""
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same: Optional[bool]
    if prev_fp and meta["scena_fingerprint"]:
        same = prev_fp == meta["scena_fingerprint"]
    else:
        same = None
    warnings = autodiff(
        {
            "balls_coll_ms": float(balls.get("coll_ms", float("nan"))),
            "balls_ms_resolve": float(balls.get("ms_resolve", float("nan"))),
            "platformer_coll_ms": float(platformer.get("coll_ms", float("nan"))),
            "platformer_ms_resolve": float(platformer.get("ms_resolve", float("nan"))),
        },
        _prev_metrics(prev_text),
        same_scena=same,
        prev_label="last resolve-2 row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print("\n" + "=" * 60)
    print("resolve pulse")
    print("=" * 60)
    print(section)
    print(f"elapsed={elapsed:.1f}s")
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
