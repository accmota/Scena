"""Refresh ``scripts/bench/dashboard.md`` from the pulse logs.

Reads the latest summary row of each registered log. Does not invent numbers —
a pulse with no fresh run just gets staler in the Fresh? column.

    python scripts/bench/dashboard.py
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from fingerprint import BENCH_DIR, host_oneline, scena_fingerprint
from pulse import (
    FB_DEFAULT_TAG,
    age_days,
    cell_fb_tag,
    fmt_ms_list,
    freshness_cell,
    latest_scena_fingerprint,
    parse_leading_float,
    parse_summary_table,
    replace_section,
    trend_label,
)

DASHBOARD = BENCH_DIR / "dashboard.md"

_SOAK_RSS_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*MiB")
_SOAK_DOBJ_RE = re.compile(r"Δobj\s+(-?[0-9]+(?:\.[0-9]+)?)")


def _rss(cell: str) -> Optional[float]:
    m = _SOAK_RSS_RE.search(cell)
    return float(m.group(1)) if m else None


def _dobj(cell: str) -> Optional[float]:
    m = _SOAK_DOBJ_RE.search(cell)
    return float(m.group(1)) if m else None


def _proto(cell: str) -> str:
    return cell.strip().strip("`")


def _filter_protocol(rows: Sequence[Sequence[str]], protocol: str, col: int = 1) -> List[List[str]]:
    out = []
    for cells in rows:
        if len(cells) <= col:
            continue
        if _proto(cells[col]) == protocol:
            out.append(list(cells))
    return out


def _last5(values: Sequence[Optional[float]], n: int = 5) -> List[Optional[float]]:
    """Newest-first input → oldest→newest last-n (drop missing)."""
    got = [v for v in values if v is not None]
    got = got[:n]
    got.reverse()
    return got


class Pulse:
    id: str
    area: str
    log: str
    protocol: str

    def parse(self, md: str) -> Dict[str, Any]:
        raise NotImplementedError


class BalancedPulse(Pulse):
    id = "balanced"
    area = "Overall mix (cpu/gpu/live/soak)"
    log = "balanced.md"
    protocol = "balanced-2"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        cpu = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        gpu = [parse_leading_float(r[4]) for r in rows if len(r) > 4]
        live = [parse_leading_float(r[6]) for r in rows if len(r) > 6]
        last5 = _last5(cpu)
        headline = "—"
        if cpu and cpu[0] is not None:
            g = f"{gpu[0]:.2f}" if gpu and gpu[0] is not None else "?"
            fb = cell_fb_tag(latest[4]) if len(latest) > 4 else FB_DEFAULT_TAG
            g_note = "" if fb == FB_DEFAULT_TAG else f" (FB {fb}, not comparable to {FB_DEFAULT_TAG} rows)"
            l = f"{live[0]:.2f}" if live and live[0] is not None else "?"
            headline = f"cpu {cpu[0]:.2f} ms · gpu {g} ms{g_note} · live {l} ms"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None),
            "scena_fp": latest_scena_fingerprint(md),
        }


class SoakPulse(Pulse):
    id = "soak"
    area = "Soak (leak/inventory)"
    log = "balanced.md"
    protocol = "balanced-2"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        rss = [_rss(r[7]) for r in rows if len(r) > 7]
        dobj = _dobj(latest[7]) if len(latest) > 7 else None
        last5 = _last5(rss)
        headline = "—"
        if rss and rss[0] is not None:
            d = f"{dobj:.0f}" if dobj is not None else "?"
            headline = f"RSS {rss[0]:.1f} MiB · Δobj {d}"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None),
            "scena_fp": latest_scena_fingerprint(md),
            "digits": 1,
            "log_href": "balanced.md",
            "log_label": "(section inside balanced.md)",
        }


class SchedPulse(Pulse):
    id = "sched"
    area = "Scheduler (process/events)"
    log = "sched.md"
    protocol = "sched-1"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        work = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        last5 = _last5(work)
        headline = "—"
        if work and work[0] is not None:
            headline = f"mix {work[0]:.2f} ms"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "— first row",
            "scena_fp": latest_scena_fingerprint(md),
        }


class FxPulse(Pulse):
    id = "fx"
    area = "FX cost matrix"
    log = "fx.md"
    protocol = "fx-1"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        base = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        last5 = _last5(base)
        headline = "—"
        if base and base[0] is not None:
            headline = f"baseline {base[0]:.2f} ms @ high"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "—",
            "scena_fp": latest_scena_fingerprint(md),
        }


class TextPulse(Pulse):
    id = "text"
    area = "Text / HUD draw"
    log = "text.md"
    protocol = "text-1"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        work = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        last5 = _last5(work)
        headline = "—"
        if work and work[0] is not None:
            headline = f"mix {work[0]:.2f} ms"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "— first row",
            "scena_fp": latest_scena_fingerprint(md),
        }


class ResolvePulse(Pulse):
    id = "resolve"
    area = "Resolve (balls / platformer)"
    log = "resolve.md"
    protocol = "resolve-2"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        coll = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        plat = [parse_leading_float(r[5]) for r in rows if len(r) > 5]
        last5 = _last5(coll)
        headline = "—"
        if coll and coll[0] is not None:
            p = f"{plat[0]:.2f}" if plat and plat[0] is not None else "?"
            headline = f"balls {coll[0]:.2f} ms · platformer {p} ms"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "— first row",
            "scena_fp": latest_scena_fingerprint(md),
        }


class GraphPulse(Pulse):
    id = "graph"
    area = "Reactive-graph scaling"
    log = "graph.md"
    protocol = "graph-1"

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        latest = rows[0]
        work = [parse_leading_float(r[3]) for r in rows if len(r) > 3]
        last5 = _last5(work)
        headline = "—"
        if work and work[0] is not None:
            headline = f"sierpinski {work[0]:.2f} ms"
        return {
            "date": latest[0],
            "protocol": self.protocol,
            "headline": headline,
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "— first row",
            "scena_fp": latest_scena_fingerprint(md),
        }


class ColumnPulse(Pulse):
    """Pulse whose summary table has one primary number in ``col``.

    ``headline(rows)`` formats the latest row (newest-first cells). Lower is better.
    """

    def __init__(self, id: str, area: str, log: str, protocol: str, col: int,
                 headline: Callable[[List[List[str]]], str], digits: int = 2) -> None:
        self.id, self.area, self.log, self.protocol = id, area, log, protocol
        self.col, self.headline, self.digits = col, headline, digits

    def parse(self, md: str) -> Dict[str, Any]:
        rows = _filter_protocol(parse_summary_table(md), self.protocol)
        if not rows:
            return {}
        vals = [parse_leading_float(r[self.col]) for r in rows if len(r) > self.col]
        last5 = _last5(vals)
        return {
            "date": rows[0][0],
            "protocol": self.protocol,
            "headline": self.headline(rows),
            "last5": last5,
            "trend": trend_label(last5[0] if last5 else None, last5[-1] if last5 else None)
            if len(last5) >= 2 else "— first row",
            "scena_fp": latest_scena_fingerprint(md),
            "digits": self.digits,
        }


def _cell(rows: List[List[str]], i: int) -> str:
    r = rows[0]
    return r[i].strip() if len(r) > i else "?"


def _num_cell(rows: List[List[str]], i: int, digits: int = 2) -> str:
    v = parse_leading_float(_cell(rows, i))
    return "?" if v is None else f"{v:.{digits}f}"


# Registered pulses. A log that does not exist yet is skipped (stays in Blind spots).
REGISTRY: List[Pulse] = [
    BalancedPulse(),
    SchedPulse(),
    FxPulse(),
    SoakPulse(),
    TextPulse(),
    GraphPulse(),
    ResolvePulse(),
    ColumnPulse(
        "background", "Background / camera / parallax", "background.md", "bg-1", 3,
        lambda rows: f"mix {_num_cell(rows, 3)} ms · sky {_num_cell(rows, 4)} · parallax {_num_cell(rows, 6)}",
    ),
    ColumnPulse(
        "startup", "Startup + warm-up", "startup.md", "startup-1", 3,
        lambda rows: f"ttff {_num_cell(rows, 3, 0)} ms · import {_num_cell(rows, 4, 0)} · warm-up excess {_num_cell(rows, 8, 0)} ms",
        digits=0,
    ),
    ColumnPulse(
        "assets", "Asset first-use", "assets.md", "assets-1", 3,
        lambda rows: f"cold Σ {_num_cell(rows, 3, 1)} ms · worst {_cell(rows, 4)} · warm Σ {_num_cell(rows, 5, 1)}",
        digits=1,
    ),
    ColumnPulse(
        "longrun", "Long run (jitter / GC / drift)", "longrun.md", "longrun-2", 3,
        lambda rows: f"held {_num_cell(rows, 3)}/min · hitch {_num_cell(rows, 4)}/min · RSS {_cell(rows, 7)} MiB/10min",
    ),
]


def _log_cell(pulse: Pulse, info: Dict[str, Any]) -> str:
    href = info.get("log_href", pulse.log)
    label = info.get("log_label")
    if label:
        return f"[{label}]({href})"
    return f"[{pulse.log}]({href})"


def collect(today: Optional[datetime] = None) -> Dict[str, Any]:
    now_fp = scena_fingerprint()
    today = today or datetime.now()
    rows_out = []
    for pulse in REGISTRY:
        path = BENCH_DIR / pulse.log
        if not path.is_file():
            continue
        md = path.read_text(encoding="utf-8")
        info = pulse.parse(md)
        if not info:
            # Log exists (protocol registered) but no snapshot yet.
            rows_out.append({
                "area": pulse.area,
                "log_cell": f"[{pulse.log}]({pulse.log})",
                "protocol": pulse.protocol,
                "date": "—",
                "headline": "— no row yet",
                "last5": "—",
                "trend": "—",
                "fresh": "🔴 no row",
            })
            continue
        age = age_days(str(info.get("date") or ""), today)
        recorded_fp = info.get("scena_fp")
        unchanged = bool(recorded_fp and recorded_fp == now_fp)
        digits = int(info.get("digits") or 2)
        last5 = info.get("last5") or []
        log_cell = _log_cell(pulse, info)
        rows_out.append({
            "area": pulse.area,
            "log_cell": log_cell,
            "protocol": info.get("protocol") or pulse.protocol,
            "date": info.get("date") or "—",
            "headline": info.get("headline") or "—",
            "last5": fmt_ms_list(last5, digits=digits),
            "trend": info.get("trend") or "—",
            "fresh": freshness_cell(age=age, scena_unchanged=unchanged),
        })
    return {
        "scena_fingerprint": now_fp,
        "host": host_oneline(),
        "when": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "rows": rows_out,
    }


def render_pulses_table(bundle: Dict[str, Any]) -> str:
    lines = [
        "| Area | Log | Protocol | Last run | Headline | Last 5 (oldest→newest) | Trend | Fresh? |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for r in bundle["rows"]:
        lines.append(
            f"| {r['area']} | {r['log_cell']} | {r['protocol']} | {r['date']} | "
            f"{r['headline']} | {r['last5']} | {r['trend']} | {r['fresh']} |"
        )
    return "\n".join(lines) + "\n"


def render_fingerprint_line(bundle: Dict[str, Any]) -> str:
    return (
        f"Scena fingerprint now: `{bundle['scena_fingerprint']}` "
        f"({bundle['when']} · {bundle['host']})\n"
    )


def refresh(path: Optional[Path] = None) -> Path:
    dest = path or DASHBOARD
    if not dest.is_file():
        raise FileNotFoundError(f"dashboard not found: {dest}")
    bundle = collect()
    text = dest.read_text(encoding="utf-8")
    text = replace_section(
        text, "<!-- FINGERPRINT:START -->", "<!-- FINGERPRINT:END -->",
        render_fingerprint_line(bundle),
    )
    text = replace_section(
        text, "<!-- PULSES:START -->", "<!-- PULSES:END -->",
        render_pulses_table(bundle),
    )
    dest.write_text(text, encoding="utf-8")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print", action="store_true",
        help="print the Pulses table to stdout; do not write the file",
    )
    args = parser.parse_args()
    bundle = collect()
    table = render_pulses_table(bundle)
    print(render_fingerprint_line(bundle), end="")
    print()
    print(table)
    if args.print:
        return
    dest = refresh()
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
