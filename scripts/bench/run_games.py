"""Games pulse: ninja (tutorial 22) and the four benchmark games, real loop.

Each game runs unmodified in the real loop (``game_bench.py``, one fresh
process per run), 10 s recorded after 3 s of warm-up, uncapped. ``games-2``:

* the reference size of every game, plus one stress size for the two games
  whose cost grows with size (horda n=400: the crowd; mundo tiles=4000: the
  world). A regression of the growth shape shows there long before it moves
  the reference size;
* ``--repeats`` rounds (default 3), interleaved (every game once per round),
  and the median of each metric: one run of horda or mundo moves ±10–15 %
  with the machine load;
* festa's framebuffer (pixels) in its own column. festa is GPU-bound, so its
  cells are compared only with a row at the same framebuffer. The window is
  fitted to the display, so fb / design width is not a stable scale (2.0×,
  2.24×, 2.51× on one 4K display): the tag is the framebuffer size itself;
* besides work ms: corrida's max frame (a track slot build: Sprite
  construction) and festa's RSS at the end of the run (Skia GPU cache, image
  pins).

    python scripts/bench/run_games.py
    python scripts/bench/run_games.py --repeats 1 --no-append   # smoke
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

PROTOCOL = "games-2"
LOG_PATH = BENCH_DIR / "games.md"
SCRIPT_FILES = (
    "game_bench.py",
    "run_games.py",
    "games/horda.py",
    "games/mundo.py",
    "games/corrida.py",
    "games/festa.py",
)
# id, script (repo-relative), PARAMS. Reference sizes, then the stress sizes.
GAMES: Tuple[Tuple[str, str, str], ...] = (
    ("ninja", "examples/ninja_4_perigos.py", ""),
    ("horda", "scripts/bench/games/horda.py", "n=150"),
    ("horda400", "scripts/bench/games/horda.py", "n=400"),
    ("mundo", "scripts/bench/games/mundo.py", "tiles=1500,robots=20"),
    ("mundo4000", "scripts/bench/games/mundo.py", "tiles=4000,robots=20"),
    ("corrida", "scripts/bench/games/corrida.py", "speed=600"),
    ("festa", "scripts/bench/games/festa.py", "n=300"),
)
# Summary cells after Load and FB, in order: metric key, game id, field.
CELLS: Tuple[Tuple[str, str, str], ...] = (
    ("ninja_work_ms", "ninja", "work_ms"),
    ("horda_work_ms", "horda", "work_ms"),
    ("horda400_work_ms", "horda400", "work_ms"),
    ("mundo_work_ms", "mundo", "work_ms"),
    ("mundo4000_work_ms", "mundo4000", "work_ms"),
    ("corrida_work_ms", "corrida", "work_ms"),
    ("corrida_max_ms", "corrida", "work_max"),
    ("festa_work_ms", "festa", "work_ms"),
    ("festa_rss_mb", "festa", "rss_end"),
)
FIRST_CELL = 5          # Date, Protocol, Host, Load, FB, then CELLS
FB_COL = 4
# GPU-bound cells: a run at another framebuffer is another workload. The FB
# column holds FB_GAME's framebuffer.
FB_KEYS = frozenset({"festa_work_ms", "festa_rss_mb"})
FB_GAME = "festa"
SECONDS, WARMUP = "10", "3"
# Per-run fields aggregated by median.
_MEDIAN_FIELDS = ("work_ms", "work_p95", "work_p99", "work_max", "x4_ms", "fps", "rss_end", "load")


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


def run_fb_tag(rep: Dict[str, Any]) -> Optional[str]:
    """Framebuffer of one ``game_bench`` report, ``"2006x1504"`` (None if unknown)."""
    fb = rep.get("fb")
    if not fb or len(fb) < 2:
        return None
    return f"{int(fb[0])}x{int(fb[1])}"


def summarize_game(reports: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Median over the repeats of one game; keeps the median-work run for its phases."""
    flat = []
    for rep in reports:
        s = dict(rep["sides"]["all"])
        rss = rep.get("rss_mb") or [float("nan"), float("nan")]
        s["rss_end"] = float(rss[1])
        s["load"] = float((rep.get("load") or [float("nan")])[0])
        flat.append(s)
    out: Dict[str, Any] = {"repeats": len(flat), "works": [s["work_ms"] for s in flat]}
    for k in _MEDIAN_FIELDS:
        vals = [float(s[k]) for s in flat if s.get(k) is not None and s[k] == s[k]]
        out[k] = statistics.median(vals) if vals else float("nan")
    by_work = sorted(flat, key=lambda s: s["work_ms"])
    out["phases"] = by_work[len(by_work) // 2]["phases"]
    tags = {run_fb_tag(rep) for rep in reports}
    out["fb_tag"] = "mixed" if len(tags) > 1 else next(iter(tags))
    return out


def row_fb_tag(games: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """The FB column: ``FB_GAME``'s framebuffer (``"mixed"`` when its runs disagree)."""
    g = games.get(FB_GAME)
    return g["fb_tag"] if g else None


def metrics(games: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    return {key: float(games[gid][field]) for key, gid, field in CELLS if gid in games}


def _fmt(key: str, v: float) -> str:
    if v != v:
        return "—"
    return f"{v:.0f}" if key.endswith("_mb") else f"{v:.2f}"


def summary_row(games: Dict[str, Dict[str, Any]], meta: Dict[str, Any], notes: str) -> str:
    load = statistics.median([g["load"] for g in games.values()])
    m = metrics(games)
    cells = " | ".join(_fmt(key, m.get(key, float("nan"))) for key, _g, _f in CELLS)
    tag = row_fb_tag(games) or "?"
    return (f"| {meta['date']} | `{PROTOCOL}` | {host_oneline(meta['host'])} | {load:.1f} | "
            f"{tag} | {cells} | {notes} |")


def render_markdown(games, meta, hashes, fingerprint, notes, pro_forma) -> Tuple[str, str]:
    row = summary_row(games, meta, notes)
    repeats = max(g["repeats"] for g in games.values())
    hash_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in hashes.items())
    lines = [
        f"### {meta['date']} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` ({pro_forma}) |",
        f"| Host | {host_oneline(meta['host'])} |",
        f"| Load | {statistics.median([g['load'] for g in games.values()]):.2f} (median of runs) |",
        f"| FB | {FB_GAME} {row_fb_tag(games) or '?'} (the gated cells) |",
        f"| Repeats | {repeats} (interleaved; median) |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Scripts | fingerprint `{fingerprint}` |",
        "",
        "| File | sha256[:12] |",
        "|------|-------------|",
        hash_rows,
        "",
        "| Game | work | runs | p95 | p99 | max | x4 | fps | RSS end | FB | top phases |",
        "|------|-----:|------|----:|----:|----:|---:|----:|--------:|----|------------|",
    ]
    for gid, _script, params in GAMES:
        g = games.get(gid)
        if g is None:
            continue
        top = ", ".join(f"{k} {v:.2f}" for k, v in list(g["phases"].items())[:4])
        runs = " / ".join(f"{w:.2f}" for w in g["works"])
        lines.append(
            f"| {gid} {params} | {g['work_ms']:.2f} | {runs} | {g['work_p95']:.2f} | "
            f"{g['work_p99']:.2f} | {g['work_max']:.1f} | {g['x4_ms']:.1f} | {g['fps']:.0f} | "
            f"{g['rss_end']:.0f} | {g['fb_tag'] or '?'} | {top} |"
        )
    lines.append("")
    return row, "\n".join(lines)


def prev_metrics(
    md_text: str, fb_tag: Optional[str],
) -> Tuple[Optional[Dict[str, float]], Dict[str, str], List[str]]:
    """Previous-row metrics for auto-diff, per-key labels and notes.

    CPU-bound cells come from the newest ``games-2`` row. ``FB_KEYS`` come
    from the newest row at the same framebuffer scale as ``fb_tag`` (unknown
    → newest row); with no such row they are left out and explained.
    """
    rows = [c for c in parse_summary_table(md_text)
            if len(c) > FIRST_CELL + len(CELLS) - 1 and c[1].strip().strip("`") == PROTOCOL]
    if not rows:
        return None, {}, []
    newest = rows[0]
    out: Dict[str, float] = {}
    labels: Dict[str, str] = {}
    notes: List[str] = []
    for i, (key, _g, _f) in enumerate(CELLS):
        col = FIRST_CELL + i
        if key not in FB_KEYS or fb_tag is None:
            v = parse_leading_float(newest[col])
            if v is not None:
                out[key] = v
            continue
        for j, cells in enumerate(rows):
            got = cells[FB_COL].strip()
            if got != fb_tag or fb_tag == "mixed":
                continue
            v = parse_leading_float(cells[col])
            if v is None:
                continue
            out[key] = v
            if j:
                labels[key] = f"{cells[0]} {PROTOCOL} row (last at FB {got})"
                notes.append(f"{key}: FB {fb_tag} differs from the newest row (FB "
                             f"{newest[FB_COL].strip()}) → compared with the {cells[0]} row instead")
            break
        else:
            notes.append(f"{key}: not compared — measured at FB {fb_tag}; no earlier {PROTOCOL} "
                         f"row at FB {fb_tag} (newest is FB {newest[FB_COL].strip()}): "
                         "different workload, re-run on the usual display")
    return out, labels, notes


def report_autodiff(games: Dict[str, Dict[str, Any]], md_text: str, scena_fp: Optional[str]) -> None:
    prev, labels, notes = prev_metrics(md_text, row_fb_tag(games))
    prev_fp = latest_scena_fingerprint(md_text) if md_text else None
    same = (prev_fp == scena_fp) if prev_fp and scena_fp else None
    warnings = autodiff(
        metrics(games), prev, same_scena=same, prev_label=f"last {PROTOCOL} row",
        prev_labels=labels,
        # An older same-FB row: the newest row's fingerprint says nothing about it.
        same_scena_by_key={k: None for k in labels},
    )
    print_autodiff_banner(warnings, same_scena=same, notes=notes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="")
    parser.add_argument("--comparable", action="store_true")
    parser.add_argument("--no-append", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    meta = now_meta()
    hashes = script_hashes(SCRIPT_FILES)
    t0 = time.perf_counter()
    reports: Dict[str, List[Dict[str, Any]]] = {gid: [] for gid, _s, _p in GAMES}
    for r in range(max(1, args.repeats)):
        for gid, script, params in GAMES:
            rep = _run(script, params)
            reports[gid].append(rep)
            print(f"[{r + 1}/{args.repeats}] {gid}: work {rep['sides']['all']['work_ms']:.2f} ms "
                  f"(fb {run_fb_tag(rep)}, load {rep['load'][0]:.1f})", flush=True)
            time.sleep(0.4)
    games = {gid: summarize_game(reps) for gid, reps in reports.items()}
    row, section = render_markdown(
        games, meta, hashes, scripts_fingerprint(hashes, SCRIPT_FILES), args.notes,
        "comparable" if args.comparable else "pro-forma",
    )
    prev_text = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.is_file() else ""
    report_autodiff(games, prev_text, meta["scena_fingerprint"])
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
