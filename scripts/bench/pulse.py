"""Shared pulse-log helpers: parse summary tables, append rows, auto-diff.

Used by ``run_balanced.py``, ``sched.py``, ``run_fx.py``, ``dashboard.py``.
Does not invent numbers — it only copies values the runner already measured.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fingerprint import git_head, host_info, host_oneline, scena_fingerprint

# Existing noise convention (balanced.md / sched.md): ≲5% ignore, ≳15% noteworthy.
NOTEWORTHY_PCT = 15.0
NOISE_PCT = 5.0
FRESH_DAYS = 14

_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
_LEADING_NUM_RE = re.compile(r"^\s*`?([0-9]+(?:\.[0-9]+)?)")
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def now_meta() -> Dict[str, Any]:
    now = datetime.now().astimezone()
    utc = datetime.now(timezone.utc)
    host = host_info()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "when": f"{now.strftime('%Y-%m-%d %H:%M %z')} ({utc.strftime('%H:%M')} UTC)",
        "timestamp": now,
        "host": host,
        "host_s": host_oneline(host),
        "git": git_head(),
        "scena_fingerprint": scena_fingerprint(),
    }


def split_md_row(line: str) -> List[str]:
    s = line.strip()
    if not s.startswith("|"):
        return []
    parts = s.split("|")
    # leading/trailing empties from split around pipes
    return [p.strip() for p in parts[1:-1]] if parts[-1].strip() == "" else [p.strip() for p in parts[1:]]


def parse_leading_float(cell: str) -> Optional[float]:
    if not cell or cell in ("—", "-", "?", "n/a"):
        return None
    m = _LEADING_NUM_RE.match(cell.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_summary_table(md_text: str, heading: str = "## Summary") -> List[List[str]]:
    """Return data rows (list of cells) of the first markdown table under ``heading``.

    Newest-first logs: index 0 is the latest snapshot.
    """
    lines = md_text.splitlines()
    start = None
    heading_l = heading.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower() == heading_l:
            start = i
            break
    if start is None:
        return []
    header_i = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            header_i = i
            break
        if lines[i].startswith("## ") and i > start:
            return []
    if header_i is None:
        return []
    rows: List[List[str]] = []
    for i in range(header_i + 2, len(lines)):
        line = lines[i]
        if not line.strip().startswith("|"):
            break
        if _TABLE_SEP_RE.match(line):
            continue
        cells = split_md_row(line)
        if cells:
            rows.append(cells)
    return rows


def parse_kv_table_after(md_text: str, heading_prefix: str) -> Dict[str, str]:
    """Parse the ``| key | value |`` table in the first matching run subsection."""
    lines = md_text.splitlines()
    start = None
    prefix = heading_prefix.strip()
    for i, line in enumerate(lines):
        if line.startswith("### ") and prefix in line:
            start = i
            break
    if start is None:
        return {}
    out: Dict[str, str] = {}
    in_table = False
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("### ") or line.startswith("## "):
            break
        if not in_table:
            if line.strip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
                in_table = True
            continue
        if not line.strip().startswith("|"):
            break
        cells = split_md_row(line)
        if len(cells) >= 2 and cells[0]:
            out[cells[0]] = cells[1]
    return out


def latest_scena_fingerprint(md_text: str) -> Optional[str]:
    """Best-effort: ``| Scena | `hash` |`` (``| Stage |`` before 0.6.0) in the newest ``### `` run subsection."""
    lines = md_text.splitlines()
    runs_i = None
    for i, line in enumerate(lines):
        if line.strip() == "## Runs":
            runs_i = i
            break
    if runs_i is None:
        return None
    first_section = None
    for i in range(runs_i + 1, len(lines)):
        if lines[i].startswith("### "):
            first_section = i
            break
        if lines[i].startswith("## "):
            return None
    if first_section is None:
        return None
    kv = parse_kv_table_after("\n".join(lines[first_section:]), lines[first_section][4:].strip())
    # "Scena" since 0.6.0; older logs say "Stage" (the framework's old name, 0.6.0).
    cell = kv.get("Scena") or kv.get("Stage") or kv.get("scena") or kv.get("stage")  # pre-0.6.0
    if not cell:
        scripts = kv.get("Scripts") or ""
        m = re.search(r"(?:scena|stage)\s+`([0-9a-f]{8,})`", scripts, re.I)
        if m:
            return m.group(1)
        return None
    m = re.search(r"`([0-9a-f]{8,})`", cell)
    if m:
        return m.group(1)
    raw = cell.strip().strip("`")
    if re.fullmatch(r"[0-9a-f]{8,}", raw):
        return raw
    return None


def insert_summary_row(md_text: str, row_line: str, heading: str = "## Summary") -> str:
    """Insert ``row_line`` as the newest summary row (after the header separator)."""
    lines = md_text.splitlines(keepends=True)
    heading_l = heading.strip().lower()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == heading_l:
            start = i
            break
    if start is None:
        raise ValueError(f"no {heading!r} section")
    sep_i = None
    for i in range(start + 1, len(lines)):
        if _TABLE_SEP_RE.match(lines[i]):
            sep_i = i
            break
        if lines[i].startswith("## ") and i > start:
            break
    if sep_i is None:
        raise ValueError(f"no table separator under {heading!r}")
    row = row_line if row_line.endswith("\n") else row_line + "\n"
    if not row.startswith("|"):
        row = "| " + row.lstrip()
    lines.insert(sep_i + 1, row)
    return "".join(lines)


def insert_run_section(md_text: str, section: str, heading: str = "## Runs") -> str:
    """Insert a ``###`` run subsection at the top of ``## Runs`` (newest first)."""
    lines = md_text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        raise ValueError(f"no {heading!r} section")
    insert_at = start + 1
    # Skip a blank line and a "Newest first." blurb if present.
    while insert_at < len(lines) and lines[insert_at].strip() in ("", "Newest first.", "Newest first"):
        insert_at += 1
    body = section.strip("\n") + "\n\n"
    if insert_at < len(lines) and lines[insert_at].startswith("### "):
        lines.insert(insert_at, body)
    else:
        lines.insert(insert_at, body)
    return "".join(lines)


def append_pulse(md_path: Path, summary_row: str, run_section: str) -> None:
    text = md_path.read_text(encoding="utf-8")
    text = insert_summary_row(text, summary_row)
    text = insert_run_section(text, run_section)
    md_path.write_text(text, encoding="utf-8")


# Framebuffer tags. A GPU-bound cell measured at another framebuffer scale (the
# window opened on a different display: Retina 2× vs 1×) is a different
# workload, not a move. Summary cells carry the scale: unmarked = 2× (the
# Retina default), trailing ``§`` = 1× (the older hand convention, now
# written by the runner), ``[FB 1.5×]`` / ``[FB mixed]`` = anything else.
FB_DEFAULT_TAG = "2×"
FB_1X_MARK = "§"
_FB_CELL_RE = re.compile(r"\[FB ([^\]]+)\]")


def fb_scale_tag(fb_width: Any, design_width: Any) -> Optional[str]:
    """``"2×"`` / ``"1×"`` / ``"1.5×"`` from framebuffer vs design width; None if unknown."""
    try:
        fb, design = float(fb_width), float(design_width)
    except (TypeError, ValueError):
        return None
    if not (fb > 0 and design > 0):
        return None
    scale = fb / design
    return f"{int(round(scale))}×" if abs(scale - round(scale)) < 1e-6 else f"{scale:g}×"


def fb_cell_suffix(tag: Optional[str]) -> str:
    """Suffix for a summary cell measured at ``tag`` (empty for the 2× default / unknown)."""
    if tag is None or tag == FB_DEFAULT_TAG:
        return ""
    if tag == "1×":
        return f" {FB_1X_MARK}"
    return f" [FB {tag}]"


def cell_fb_tag(cell: str) -> str:
    """Framebuffer tag of a summary cell (inverse of :func:`fb_cell_suffix`)."""
    m = _FB_CELL_RE.search(cell)
    if m:
        return m.group(1)
    return "1×" if FB_1X_MARK in cell else FB_DEFAULT_TAG


def pct_move(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return 100.0 * (new - old) / abs(old)


def autodiff(
    new_metrics: Mapping[str, float],
    prev_metrics: Optional[Mapping[str, float]],
    *,
    same_scena: Optional[bool],
    prev_label: str = "previous row",
    prev_labels: Optional[Mapping[str, str]] = None,
    same_scena_by_key: Optional[Mapping[str, Optional[bool]]] = None,
    threshold_pct: float = NOTEWORTHY_PCT,
) -> List[str]:
    """Return warning lines for metrics that moved more than ``threshold_pct``.

    ``same_scena`` True → code unchanged, so a big move is environment noise.
    False → candidate regression/improvement. None → unknown (no fingerprint).
    ``prev_labels`` names the row a key was compared against when it is not
    the newest one (e.g. the last row at the same framebuffer scale);
    ``same_scena_by_key`` overrides ``same_scena`` for those keys.
    """
    if not prev_metrics:
        return []
    lines: List[str] = []
    for key, new_v in new_metrics.items():
        if new_v is None or (isinstance(new_v, float) and new_v != new_v):
            continue
        old_v = prev_metrics.get(key)
        if old_v is None or (isinstance(old_v, float) and old_v != old_v):
            continue
        move = pct_move(float(new_v), float(old_v))
        if move is None or abs(move) < threshold_pct:
            continue
        direction = "up" if move > 0 else "down"
        same_k = (same_scena_by_key or {}).get(key, same_scena)
        if same_k is True:
            why = "same scena_fingerprint → treat as environment noise (thermal / compositor / load)"
        elif same_k is False:
            why = "scena_fingerprint changed → candidate real move; inspect the diff"
        else:
            why = "scena_fingerprint of that row unknown → unknown cause"
        lines.append(
            f"  {key}: {old_v:.3f} → {new_v:.3f} ({move:+.0f}% {direction}) "
            f"vs {(prev_labels or {}).get(key, prev_label)}  [{why}]"
        )
    return lines


def print_autodiff_banner(
    warnings: Sequence[str],
    *,
    same_scena: Optional[bool],
    notes: Sequence[str] = (),
) -> None:
    """Print moves (``warnings``) and comparability notes (``notes``)."""
    for line in notes:
        print(f"auto-diff: note — {line}")
    if not warnings:
        print("auto-diff: no >{:.0f}% moves vs last comparable row".format(NOTEWORTHY_PCT))
        return
    print()
    print("!" * 60)
    if same_scena is True:
        print("AUTO-DIFF  >15% move, SAME scena fingerprint — likely noise")
    elif same_scena is False:
        print("AUTO-DIFF  >15% move AND scena fingerprint changed")
    else:
        print("AUTO-DIFF  >15% move (previous row has no scena fingerprint)")
    print("!" * 60)
    for line in warnings:
        print(line)
    print("!" * 60)


def fmt_ms_list(values: Sequence[Optional[float]], digits: int = 2) -> str:
    parts = []
    for v in values:
        if v is None or (isinstance(v, float) and v != v):
            parts.append("—")
        else:
            parts.append(f"{v:.{digits}f}")
    return ", ".join(parts) if parts else "—"


def trend_label(oldest: Optional[float], newest: Optional[float]) -> str:
    """Lower ms is better. ``oldest`` → ``newest`` across last-N."""
    if oldest is None or newest is None:
        return "—"
    if oldest == 0:
        return "—"
    move = (newest - oldest) / abs(oldest)
    if abs(move) < 0.05:
        return "flat"
    if move < 0:
        return "↓ improving"
    return "↑ regressing"


def age_days(date_s: str, today: Optional[datetime] = None) -> Optional[int]:
    m = _DATE_RE.match(date_s.strip().strip("`"))
    if not m:
        return None
    try:
        then = datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None
    now = (today or datetime.now()).date()
    return (now - then).days


def freshness_cell(
    *,
    age: Optional[int],
    scena_unchanged: bool,
    fresh_days: int = FRESH_DAYS,
) -> str:
    if age is None:
        return "—"
    if age <= fresh_days or scena_unchanged:
        return f"✅ {age}d"
    return f"⚠️ {age}d stale"


def replace_section(md_text: str, start_marker: str, end_marker: str, body: str) -> str:
    """Replace the region between HTML comment markers (exclusive of markers)."""
    start = md_text.find(start_marker)
    end = md_text.find(end_marker)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"missing markers {start_marker!r} / {end_marker!r}")
    inner_start = start + len(start_marker)
    body_nl = body if body.startswith("\n") else "\n" + body
    if not body_nl.endswith("\n"):
        body_nl += "\n"
    return md_text[:inner_start] + body_nl + md_text[end:]
