"""Process overlay: a panel that lists what is running (Ctrl+Shift+6).

Tasks (``run_task``, an async mode's body), modes, and in a second step the
loose timers. Read from the scheduler at refresh time (10 Hz, wall clock);
each frame only draws the cached lines. Off: one test of ``_level`` in the
draw (Actors Design — Process overlay).
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple

from .process import _is_entity, _is_ignored_filename, get_scheduler

# 0 off, 1 processes (tasks + modes), 2 processes + loose timers.
_level = 0

# A task that waits this long (its own time) on an await with no clock is slow
# (the epsilon: fifty frames of 0.1 s add up to 4.9999…).
SLOW_S = 5.0
_SLOW_AT = SLOW_S - 1e-9
MAX_ROWS = 16
REFRESH_S = 0.1
FONT_SIZE = 12.0

_CHORD = "Ctrl+Shift+6"
# Awaits that say when they end: never slow, however long.
_TIMED = frozenset(("wait", "after", "every", "tween", "sound"))

_cache_lines: Optional[List[Tuple[str, ...]]] = None
_cache_header = ""
_cache_at = 0.0
_font = None


def show_processes(enabled: bool = True) -> None:
    """Show a panel of what is running: tasks, async and plain modes.

    The same panel as Ctrl+Shift+6: one row per task (``run_task``, an async
    mode's body) with what it awaits, for how long and the line, then one row
    per mode; alike rows fold (``Wasp x12``). A task that waits 5 s or more
    on an ``until`` is marked SLOW. Debug, not game logic.

    Args:
        enabled: Show the panel (``False`` hides it).
    """
    global _level
    from .validate import expect_bool
    _level = 1 if expect_bool(enabled, "show_processes enabled") else 0
    _invalidate()


def processes_overlay_level() -> int:
    return _level


def cycle_processes_overlay() -> int:
    """Ctrl+Shift+6: off -> processes -> processes + timers -> off."""
    global _level
    _level = (_level + 1) % 3
    _invalidate()
    return _level


def _invalidate() -> None:
    global _cache_lines, _cache_at
    _cache_lines = None
    _cache_at = 0.0


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


class Row:
    """One panel row (or a fold of alike ones: ``count`` > 1)."""

    __slots__ = ("owner", "func", "kind", "age", "awaiting", "line", "work",
                 "depth", "slow", "count", "wait_age", "group")

    def __init__(self, *, owner, func, kind, age, awaiting="", line="",
                 work=0, depth=0, slow=False, wait_age=0.0, group="task"):
        self.owner = owner
        self.func = func
        self.kind = kind
        self.age = age
        self.awaiting = awaiting
        self.line = line
        self.work = work
        self.depth = depth
        self.slow = slow
        self.count = 1
        self.wait_age = wait_age
        self.group = group

    def key(self):
        return (self.group, self.depth, self.owner, self.func, self.kind,
                self.awaiting.split(" ", 1)[0], self.line)

    def __repr__(self) -> str:
        return f"<Row {' '.join(self.cells())}>"

    def cells(self) -> Tuple[str, ...]:
        owner = self.owner if self.count == 1 else f"{self.owner} x{self.count}"
        if self.depth:
            owner = "  " * (self.depth - 1) + "|_ " + owner
        work = ""
        if self.work and self.group == "mode":
            work = f"{self.work} timer{'s' if self.work > 1 else ''}"
        elif self.work:
            work = f"+{self.work} work"
        return (owner, self.func, self.kind, f"{self.age:.1f}s", self.awaiting,
                "SLOW" if self.slow else "", self.line, work)


def _owner_label(handle) -> str:
    owner = handle._owner
    if owner is None:
        return "game" if handle.scope == "game" else "act"
    return _actor_label(owner)


def _actor_label(owner) -> str:
    label = type(owner).__name__
    if _is_entity(owner):
        if not getattr(owner, "active", True):
            label += " (parked)"
        elif getattr(owner, "_time_scale", 1.0) == 0.0:
            label += " (time 0)"
    return label


def _await_line(coro) -> str:
    """``file.py:41`` of the deepest author frame the task is suspended in
    (helpers it awaits included); engine frames are skipped."""
    best = ""
    c = coro
    for _ in range(64):
        frame = getattr(c, "cr_frame", None) or getattr(c, "gi_frame", None)
        if frame is None:
            break
        filename = frame.f_code.co_filename
        if not _is_ignored_filename(filename):
            best = f"{os.path.basename(filename)}:{frame.f_lineno}"
        nxt = getattr(c, "cr_await", None)
        if nxt is None:
            nxt = getattr(c, "gi_yieldfrom", None)
        if nxt is None:
            break
        c = nxt
    return best


def _verb(handle) -> str:
    label = handle._claim_label
    if label:
        return label.split("(", 1)[0]
    return handle.kind


def _describe_await(awaited, wait_age: float) -> Tuple[str, bool]:
    """What a task awaits, as a short phrase, and whether it has no clock."""
    if awaited is None:
        return "no Handle (never resumes)", True
    kind = awaited.kind
    if kind in ("wait", "after", "sound"):
        text = f"{kind} {awaited.remaining:.1f}s left"
    elif kind == "every":
        text = f"every {awaited.remaining:.1f}s to next"
    elif kind == "tween":
        text = f"{_verb(awaited)} {awaited.remaining:.1f}s left"
    elif kind == "until":
        hint = awaited._await_hint or ""
        word = "until_empty" if "until_empty" in hint else "until"
        return f"{word} {wait_age:.1f}s", True
    elif kind == "parallel":
        kids = awaited._children or ()
        done = sum(1 for k in kids if k._done or k._cancelled)
        text = f"parallel {done}/{len(kids)} done"
        return text + _held(awaited), not any(k.kind in _TIMED for k in kids)
    elif kind == "race":
        kids = awaited._children or ()
        text = f"race of {len(kids)}"
        return text + _held(awaited), not any(k.kind in _TIMED for k in kids)
    elif kind == "task":
        script = awaited._task
        name = getattr(getattr(script, "coro", None), "__name__", "task")
        text = f"task {name}() {awaited._elapsed:.1f}s"
        return text, False      # its own row says whether it is slow
    else:
        return f"{kind} {wait_age:.1f}s", True
    return text + _held(awaited), False


def _held(handle) -> str:
    if handle._paused:
        return " (paused)"
    if handle._held:
        return " (held)"
    return ""


def _task_row(handle, depth: int) -> Optional[Row]:
    script = handle._task
    if script is None or handle._done or handle._cancelled:
        return None
    coro = script.coro
    func = getattr(coro, "__name__", "task")
    if script.kind == "mode":
        kind = "mode"
    else:
        kind = "task·mode" if handle.scope == "mode" else "task"
    if handle._name:
        kind += f' "{handle._name}"'
    wait_age = max(0.0, handle._elapsed - script.waiting_since)
    awaiting, no_clock = _describe_await(script.waiting_on, wait_age)
    kids = handle._children or ()
    # Its work, not what it is awaiting (the wait, a parallel's members).
    work = sum(1 for k in kids if k.kind != "task" and not (k._awaited or k._must_await))
    return Row(
        owner=_owner_label(handle), func=func, kind=kind, age=handle._elapsed,
        awaiting=awaiting, line=_await_line(coro), work=work, depth=depth,
        slow=no_clock and wait_age >= _SLOW_AT, wait_age=wait_age, group="task",
    )


def _task_rows(sched) -> List[Row]:
    tasks = [h for h in sched._tasks if not (h._done or h._cancelled)]
    live = set(tasks)
    nested: Dict[object, List[object]] = {}
    roots = []
    for h in tasks:
        parent = h._task_parent
        if parent is not None and parent in live:
            nested.setdefault(parent, []).append(h)
        else:
            roots.append(h)
    rows: List[Row] = []

    def walk(handles, depth):
        pairs = []
        for h in handles:
            row = _task_row(h, depth)
            if row is not None:
                pairs.append((row, h))
        for row, members in _fold_pairs(pairs):
            rows.append(row)
            kids = [k for m in members for k in nested.get(m, ())]
            if kids and depth < 8:
                walk(kids, depth + 1)

    walk(roots, 0)
    return rows


def _fold_pairs(pairs) -> List[Tuple[Row, list]]:
    """Alike rows become one (``Wasp x12``), at the first one's place; it
    shows the member that has waited longest. Returns (row, members)."""
    out: List[Tuple[Row, list]] = []
    by_key: Dict[tuple, Tuple[Row, list]] = {}
    for row, payload in pairs:
        key = row.key()
        hit = by_key.get(key)
        if hit is None:
            hit = by_key[key] = (row, [payload])
            out.append(hit)
            continue
        first, members = hit
        members.append(payload)
        first.count += 1
        first.work += row.work
        first.slow = first.slow or row.slow
        first.age = max(first.age, row.age)
        if row.wait_age > first.wait_age:
            first.wait_age = row.wait_age
            first.awaiting = row.awaiting
    return out


def _fold(rows: List[Row]) -> List[Row]:
    return [row for row, _ in _fold_pairs((r, None) for r in rows)]


def _mode_rows(sched) -> List[Row]:
    from .validate import is_async_callable
    rows: List[Row] = []
    by_owner = sched._by_owner
    for owner in sched._mode_owners:
        if _is_entity(owner) and not getattr(owner, "is_alive", True):
            continue
        mode = getattr(owner, "_mode", None)
        if mode is None:
            continue
        task = getattr(owner, "_mode_task", None)
        if task is not None and not (task._done or task._cancelled):
            continue                    # its body is a task row
        is_async = is_async_callable(mode)
        work = 0
        for h in by_owner.get(id(owner), ()):
            if h.scope == "mode" and h.kind != "task" and not (h._done or h._cancelled):
                work += 1
        rows.append(Row(
            owner=_actor_label(owner), func=getattr(mode, "__name__", "mode"),
            kind="mode" if is_async else "sync",
            age=float(getattr(owner, "_mode_time", 0.0)),
            awaiting="body ended" if is_async else "", work=work, group="mode",
        ))
    return _fold(rows)


def _callback_line(fn) -> str:
    fn = getattr(fn, "__func__", fn)
    code = getattr(fn, "__code__", None)
    if code is None or _is_ignored_filename(code.co_filename):
        return ""
    return f"{os.path.basename(code.co_filename)}:{code.co_firstlineno}"


def _timer_rows(sched) -> List[Row]:
    rows: List[Row] = []
    for h in sched._handles:
        if h.kind == "task" or h._done or h._cancelled:
            continue
        if h._task_parent is not None or h.scope == "mode" or h._awaited:
            continue                    # a task's or a mode's: counted on its row
        fn = h._fn
        func = getattr(fn, "__name__", "") if fn is not None else ""
        if h.kind == "tween":
            func = _verb(h)
        kind = h.kind + (f' "{h._name}"' if h._name else "")
        rows.append(Row(
            owner=_owner_label(h), func=func, kind=kind, age=h.elapsed,
            awaiting=f"{h.remaining:.1f}s left" + _held(h),
            line=_callback_line(fn), group="timer",
        ))
    return _fold(rows)


def build_rows(sched=None, *, timers: bool = False) -> List[Row]:
    """Every row of the panel, in order: tasks, modes, then (``timers``)
    the loose timers. Pure read of the scheduler."""
    sched = sched or get_scheduler()
    rows = _task_rows(sched)
    rows.extend(_mode_rows(sched))
    if timers:
        rows.extend(_timer_rows(sched))
    return rows


def task_counts(sched=None) -> Tuple[int, int]:
    """(live tasks, slow ones) — for the system HUD line."""
    sched = sched or get_scheduler()
    n = slow = 0
    for h in sched._tasks:
        if h._done or h._cancelled or h._task is None:
            continue
        n += 1
        script = h._task
        wait_age = h._elapsed - script.waiting_since
        if wait_age >= _SLOW_AT and _describe_await(script.waiting_on, wait_age)[1]:
            slow += 1
    return n, slow


def _header(sched, rows: List[Row]) -> str:
    bits = ["PROCESSES"]
    try:
        from .act import get_act_manager
        m = get_act_manager()
        if m.current is not None:
            act = f"act {type(m.current).__name__}"
            if m.changing:
                act += " (changing)"
            bits.append(act)
    except Exception:
        pass
    tasks = sum(r.count for r in rows if r.group == "task")
    slow = sum(r.count for r in rows if r.group == "task" and r.slow)
    modes = sum(r.count for r in rows if r.group == "mode")
    part = f"{tasks} task{'s' if tasks != 1 else ''}"
    if slow:
        part += f" ({slow} slow)"
    bits.append(part)
    bits.append(f"{modes} mode{'s' if modes != 1 else ''}")
    if sched._update_owners:
        bits.append(f"on_update {len(sched._update_owners)}")
    if _level == 2:
        bits.append("+ timers")
    return "  ·  ".join(bits)


def panel_lines(sched=None) -> Tuple[str, List[Tuple[str, ...]]]:
    """The header and the row cells as drawn (row cap applied)."""
    sched = sched or get_scheduler()
    rows = build_rows(sched, timers=_level == 2)
    header = _header(sched, rows)
    lines = [r.cells() for r in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines.append((f"+{len(rows) - MAX_ROWS} more",) + ("",) * 7)
    if not rows:
        lines.append(("nothing running",) + ("",) * 7)
    return header, lines


# ---------------------------------------------------------------------------
# Draw (view space, after the cover)
# ---------------------------------------------------------------------------


def _get_font():
    global _font
    if _font is None:
        from .uiwidget import _make_ui_font, resolve_ui_typeface
        _font = _make_ui_font(resolve_ui_typeface(), FONT_SIZE)
    return _font


def draw_process_overlay(skia_canvas, design_width: float, design_height: float) -> None:
    """Draw the panel at the top right of the design view (y-up view CTM)."""
    global _cache_lines, _cache_header, _cache_at
    if not _level:
        return
    now = time.perf_counter()
    if _cache_lines is None or now - _cache_at >= REFRESH_S:
        _cache_header, _cache_lines = panel_lines()
        _cache_at = now
    import skia
    from .uiwidget import iter_font_runs, measure_text
    font = _get_font()
    lines = _cache_lines
    pad, gap, lh = 8.0, 12.0, FONT_SIZE * 1.35
    ncol = len(lines[0]) if lines else 0
    widths = [0.0] * ncol
    for cells in lines:
        for i, cell in enumerate(cells):
            if cell:
                widths[i] = max(widths[i], measure_text(font, cell))
    cols_w = sum(w + gap for w in widths if w > 0.0) - gap if any(widths) else 0.0
    header_w = measure_text(font, _cache_header + "    " + _CHORD)
    w = max(cols_w, header_w) + 2 * pad
    h = lh * (len(lines) + 1) + 2 * pad
    x0 = max(4.0, design_width - w - 8.0)

    skia_canvas.save()
    try:
        skia_canvas.translate(0, design_height)
        skia_canvas.scale(1, -1)       # y down from the top of the view
        plate = skia.Paint(AntiAlias=True)
        plate.setColor4f(skia.Color4f(0.06, 0.07, 0.09, 0.82))
        skia_canvas.drawRoundRect(skia.Rect.MakeXYWH(x0, 8.0, w, h), 6, 6, plate)
        ink = skia.Paint(AntiAlias=True)
        ink.setColor4f(skia.Color4f(0.92, 0.94, 0.97, 1.0))
        dim = skia.Paint(AntiAlias=True)
        dim.setColor4f(skia.Color4f(0.62, 0.66, 0.72, 1.0))
        amber = skia.Paint(AntiAlias=True)
        amber.setColor4f(skia.Color4f(1.0, 0.72, 0.25, 1.0))

        def text(s, x, y, paint):
            for run, run_font in iter_font_runs(font, s):
                skia_canvas.drawString(run, x, y, run_font, paint)
                x += run_font.measureText(run)

        y = 8.0 + pad + FONT_SIZE
        text(_cache_header, x0 + pad, y, amber if " slow)" in _cache_header else ink)
        text(_CHORD, x0 + w - pad - measure_text(font, _CHORD), y, dim)
        for cells in lines:
            y += lh
            slow = len(cells) > 5 and cells[5] == "SLOW"
            x = x0 + pad
            for i, cell in enumerate(cells):
                if cell:
                    paint = amber if slow and i in (4, 5) else (dim if i in (2, 6, 7) else ink)
                    text(cell, x, y, paint)
                if widths[i] > 0.0:
                    x += widths[i] + gap
    finally:
        skia_canvas.restore()
