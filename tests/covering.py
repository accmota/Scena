"""t-wise covering arrays (IPOG, greedy, constraint-aware) for the geometry campaign.

Not a test module. ``covering_array(axes, t)`` returns rows (dicts axis -> value)
such that every combination of ``t`` axis values that ``valid`` accepts appears
in at least one row. The full product of the campaign's axes is far too large
to run; a 2-wise array runs in ``quick``, a 3-wise one in ``gate``
(Testing Design — Geometry campaign).

The construction is IPOG (Lei et al., 2007): start with every combination of
the first ``t`` axes, then add one axis at a time — first extend each row with
the value that covers the most new ``t``-tuples (horizontal growth), then add
rows for the tuples still uncovered (vertical growth), leaving the other axes
as wildcards that later axes or the final fill set. Deterministic: the same
axes give the same rows.

``valid(partial)`` sees a dict of the axes assigned so far and returns False
for a combination that cannot be built (Text cannot flip; a Box has no
``move_by``). An invalid tuple is not required; a row is never completed into
an invalid one when a valid value exists.
"""
from __future__ import annotations

import itertools
from typing import Callable, Dict, List, Optional, Sequence, Tuple

Axes = Sequence[Tuple[str, Sequence]]


def covering_array(axes: Axes, t: int = 2,
                   valid: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
    names = [n for n, _ in axes]
    values = [list(v) for _, v in axes]
    if any(not v for v in values):
        raise ValueError("every axis needs at least one value")
    k = len(axes)
    t = max(1, min(t, k))

    def ok(row) -> bool:
        if valid is None:
            return True
        return valid({names[i]: values[i][x] for i, x in enumerate(row) if x is not None})

    rows: List[List[Optional[int]]] = [
        list(c) for c in itertools.product(*(range(len(values[i])) for i in range(t)))
        if ok(list(c))
    ]
    for i in range(t, k):
        col_sets = list(itertools.combinations(range(i), t - 1))
        uncovered = set()
        for cols in col_sets:
            for vals in itertools.product(*(range(len(values[c])) for c in cols)):
                for v in range(len(values[i])):
                    partial: List[Optional[int]] = [None] * (i + 1)
                    for c, x in zip(cols, vals):
                        partial[c] = x
                    partial[i] = v
                    if ok(partial):
                        uncovered.add((cols, vals, v))

        def gains(row, v):
            out = []
            for cols in col_sets:
                vals = tuple(row[c] for c in cols)
                if None in vals:
                    continue
                key = (cols, vals, v)
                if key in uncovered:
                    out.append(key)
            return out

        # Horizontal growth.
        for n, row in enumerate(rows):
            best, best_cov = None, None
            # Rotate the start so ties spread values instead of always the first.
            order = [(n + j) % len(values[i]) for j in range(len(values[i]))]
            for v in order:
                if not ok(row + [v]):
                    continue
                cov = gains(row, v)
                if best_cov is None or len(cov) > len(best_cov):
                    best, best_cov = v, cov
            row.append(best)
            if best_cov:
                uncovered.difference_update(best_cov)

        # Vertical growth.
        for cols, vals, v in sorted(uncovered):
            placed = False
            for row in rows:
                if row[i] not in (None, v):
                    continue
                if any(row[c] not in (None, x) for c, x in zip(cols, vals)):
                    continue
                trial = list(row)
                trial[i] = v
                for c, x in zip(cols, vals):
                    trial[c] = x
                if ok(trial):
                    row[:] = trial
                    placed = True
                    break
            if not placed:
                row = [None] * (i + 1)
                row[i] = v
                for c, x in zip(cols, vals):
                    row[c] = x
                rows.append(row)

    # Fill wildcards with a valid value (rotating, so fillers spread too).
    out = []
    for n, row in enumerate(rows):
        for idx in range(k):
            if row[idx] is not None:
                continue
            for j in range(len(values[idx])):
                v = (n + j) % len(values[idx])
                row[idx] = v
                if ok(row):
                    break
            else:
                row[idx] = None
        if None in row or not ok(row):
            continue
        out.append({names[c]: values[c][x] for c, x in enumerate(row)})
    return out


def uncovered_tuples(rows: List[Dict], axes: Axes, t: int,
                     valid: Optional[Callable[[Dict], bool]] = None) -> List[Tuple]:
    """Every valid ``t``-tuple no row covers (empty for a correct array)."""
    names = [n for n, _ in axes]
    values = {n: list(v) for n, v in axes}
    seen = set()
    for row in rows:
        for cols in itertools.combinations(names, t):
            seen.add(tuple((c, _key(row[c])) for c in cols))
    missing = []
    for cols in itertools.combinations(names, t):
        for vals in itertools.product(*(values[c] for c in cols)):
            partial = dict(zip(cols, vals))
            if valid is not None and not valid(partial):
                continue
            if tuple((c, _key(v)) for c, v in zip(cols, vals)) not in seen:
                missing.append(tuple(zip(cols, vals)))
    return missing


def _key(v):
    try:
        hash(v)
        return v
    except TypeError:
        return repr(v)
