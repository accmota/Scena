"""Games pulse: ninja (tutorial 22) and the four benchmark games at reference size.

Each game runs unmodified in the real loop (``game_bench.py``, one fresh
process each), 10 s recorded after 3 s of warm-up, uncapped. The summary row
holds work ms per game; the run section adds p95 / max, x4 and the top phases.

    python scripts/bench/run_games.py
    python scripts/bench/run_games.py --no-append
"""
from __future__ import annotations

import argparse
import json
import os
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

PROTOCOL = "games-1"
LOG_PATH = BENCH_DIR / "games.md"
SCRIPT_FILES = (
    "game_bench.py",
    "run_games.py",
    "games/horda.py",
    "games/mundo.py",
    "games/corrida.py",
    "games/festa.py",
)
# id, script (repo-relative), PARAMS: the reference size of each game.
GAMES: Tuple[Tuple[str, str, str], ...] = (
    ("ninja", "examples/ninja_perigos.py", ""),
    ("horda", "scripts/bench/games/horda.py", "n=150"),
    ("mundo", "scripts/bench/games/mundo.py", "tiles=1500,robots=20"),
    ("corrida", "scripts/bench/games/corrida.py", "speed=600"),
    ("festa", "scripts/bench/games/festa.py", "n=300"),
)
SECONDS, WARMUP = "10", "3"


def _run(script: str, params: str) -> Dict[str, Any]:
    cmd = [sys.executable, str(BENCH_DIR / "game_bench.py"), script,
           "--seconds", SECONDS, "--warmup", WARMUP]
    if params:
        cmd += ["--params", params]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT_JSON: "):
            return json.loads(line[len("RESULT_JSON: "):])
    raise SystemExit(f"{script}: no RESULT_JSON\n{proc.stderr[-2000:]}")


def _side(rep: Dict[str, Any]) -> Dict[str, Any]:
    return rep["sides"]["all"]


def render_markdown(results, meta, hashes, fingerprint, notes, pro_forma) -> Tuple[str, str]:
    host_s = host_oneline(meta["host"])
    date = meta["date"]
    load = os.getloadavg()[0]
    cells = " | ".join(f"{_side(results[g])['work_ms']:.2f}" for g, _s, _p in GAMES)
    row = f"| {date} | `{PROTOCOL}` | {host_s} | {load:.1f} | {cells} | {notes} |"
    hash_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in hashes.items())
    lines = [
        f"### {date} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` ({pro_forma}) |",
        f"| Host | {host_s} |",
        f"| Load | {load:.2f} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Scripts | fingerprint `{fingerprint}` |",
        "",
        "| File | sha256[:12] |",
        "|------|-------------|",
        hash_rows,
        "",
        "| Game | work | p95 | max | x4 | fps | top phases |",
        "|------|-----:|----:|----:|---:|----:|------------|",
    ]
    for g, _script, params in GAMES:
        s = _side(results[g])
        top = ", ".join(f"{k} {v:.2f}" for k, v in list(s["phases"].items())[:4])
        lines.append(
            f"| {g} {params} | {s['work_ms']:.2f} | {s['work_p95']:.2f} | {s['work_max']:.1f} | "
            f"{s['x4_ms']:.1f} | {s['fps']:.0f} | {top} |"
        )
    lines.append("")
    return row, "\n".join(lines)


def _prev_metrics(md_text: str) -> Optional[Dict[str, float]]:
    for cells in parse_summary_table(md_text):
        if len(cells) < 9 or cells[1].strip().strip("`") != PROTOCOL:
            continue
        out = {}
        for i, (g, _s, _p) in enumerate(GAMES):
            v = parse_leading_float(cells[4 + i])
            if v is not None:
                out[f"{g}_work_ms"] = v
        return out or None
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
    for g, script, params in GAMES:
        results[g] = _run(script, params)
        print(f"{g}: work {_side(results[g])['work_ms']:.2f} ms", flush=True)
        time.sleep(0.4)
    row, section = render_markdown(
        results, meta, hashes, scripts_fingerprint(hashes, SCRIPT_FILES), args.notes,
        "comparable" if args.comparable else "pro-forma",
    )
    prev_text = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.is_file() else ""
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same = (prev_fp == meta["scena_fingerprint"]) if prev_fp and meta["scena_fingerprint"] else None
    warnings = autodiff(
        {f"{g}_work_ms": float(_side(results[g])["work_ms"]) for g, _s, _p in GAMES},
        _prev_metrics(prev_text), same_scena=same, prev_label=f"last {PROTOCOL} row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print(section)
    print(f"elapsed={time.perf_counter() - t0:.1f}s")
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
