"""Known violations of the graphics-review class guards. SHRINK-ONLY.

Seeded 2026-10-08 when the guards were written, before any fix (Testing
Design — What the graphics review taught). Each entry names the finding and
the fix batch that removes it. A listed entry that now passes fails its
guard, so this file cannot go stale. Never add an entry to make a new failure
pass: triage it first (engine bug, design gap, or an oracle stricter than the
contract).
"""


def shrink_only(tc, found: dict, name: str) -> None:
    """``found`` must equal the known set ``name``: no new violation, and no
    fixed one still listed (so this file cannot go stale)."""
    known = globals()[name]
    new = sorted(set(found) - known)
    stale = sorted(known - set(found))
    msg = []
    if new:
        msg.append("NEW:\n  " + "\n  ".join(f"{k}  {found[k]}" for k in new))
    if stale:
        msg.append(f"FIXED but still in graphics_known.{name} (remove):\n  " + "\n  ".join(stale))
    tc.assertFalse(msg, "\n".join(msg))

GATE = frozenset({
})

ATOMIC = frozenset({
})

UNSTABLE_READS = frozenset({
})

CONSTRUCT = frozenset({
})

MATERIAL = frozenset({
})

COLD_READS = frozenset({
})

ROUTE = frozenset({
})

CLIP_DUE = frozenset({
})

TRUNCATED_TIME = frozenset({
})

DRAW_DOORS = frozenset({
})

CACHE_KEYS = frozenset({
})

LIFECYCLE = frozenset({
})

VALUES = frozenset({
})

FLAGS = frozenset({
})
