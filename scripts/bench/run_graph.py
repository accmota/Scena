"""Reactive-graph pulse: sierpinski (deep links) + shallow link stress.

    python scripts/bench/run_graph.py
    python scripts/bench/run_graph.py --no-append
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

PROTOCOL = "graph-1"
LOG_PATH = BENCH_DIR / "graph.md"
SCRIPT_FILES = ("sierpinsky.py", "reactive_graph.py", "run_graph.py", "harness.py")

PROBES = (
    {
        "id": "sierpinski",
        "argv": [
            "sierpinsky.py", "--bench",
            "--depth", "5", "--duration", "2", "--warmup", "0.4",
        ],
    },
    {
        "id": "shallow",
        "argv": [
            "reactive_graph.py", "--bench",
            "--duration", "2", "--warmup", "0.5", "--seed", "7",
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
    row["_probe"] = probe["id"]
    return row


def render_markdown(
    *,
    deep: Dict[str, Any],
    shallow: Dict[str, Any],
    meta: Dict[str, Any],
    hashes: Dict[str, str],
    fingerprint: str,
    notes: str,
    pro_forma: str,
) -> Tuple[str, str]:
    host_s = host_oneline(meta["host"])
    date = meta["date"]
    d_work = float(deep.get("work_ms", float("nan")))
    s_work = float(shallow.get("work_ms", float("nan")))
    row = (
        f"| {date} | `{PROTOCOL}` | {host_s} | "
        f"{d_work:.3f} ({float(deep.get('fps', 0)):.1f}) | "
        f"{s_work:.3f} ({float(shallow.get('fps', 0)):.1f}) | {notes} |"
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
        "Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.",
        "",
        "#### sierpinski depth=5",
        "",
        f"- work_ms **{d_work:.3f}**  FPS {float(deep.get('fps', 0)):.1f}  "
        f"draw {float(deep.get('draw_ms', 0)):.3f}  "
        f"flush {float(deep.get('flush_ms', 0)):.3f}",
        "",
        "#### reactive_graph (shallow ~200)",
        "",
        f"- work_ms **{s_work:.3f}**  FPS {float(shallow.get('fps', 0)):.1f}  "
        f"draw {float(shallow.get('draw_ms', 0)):.3f}  "
        f"flush {float(shallow.get('flush_ms', 0)):.3f}",
        "",
    ])
    return row, section


def _prev_metrics(md_text: str) -> Optional[Dict[str, float]]:
    for cells in parse_summary_table(md_text):
        if len(cells) < 4:
            continue
        if cells[1].strip().strip("`") != PROTOCOL:
            continue
        deep = parse_leading_float(cells[3])
        shallow = parse_leading_float(cells[4]) if len(cells) > 4 else None
        if deep is None:
            continue
        out = {"sierpinski_work_ms": deep}
        if shallow is not None:
            out["shallow_work_ms"] = shallow
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
    deep, shallow = results["sierpinski"], results["shallow"]
    row, section = render_markdown(
        deep=deep,
        shallow=shallow,
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
            "sierpinski_work_ms": float(deep.get("work_ms", float("nan"))),
            "shallow_work_ms": float(shallow.get("work_ms", float("nan"))),
        },
        _prev_metrics(prev_text),
        same_scena=same,
        prev_label="last graph-1 row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print("\n" + "=" * 60)
    print("graph pulse")
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
