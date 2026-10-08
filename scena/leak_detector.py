"""Periodic Container / registry-object leak detector (pure heuristic + sampler).

Samples are ``(entities, graph_nodes)`` pairs, oldest → newest.

A leak is **unbounded growth that keeps stepping up**. Burst-then-plateau
(spawners, first-touch ContainerSlot warmup, clicking Criar a few times)
must not fire. After lazy registration + the GC graph backstop, adding a
handful of registry objects often moves the graph by only ~1 node each, so
"objects up / graph flat" is normal spawn — not a missing ``destroy()``.
Growth that one ``gc.collect()`` gives back (Container trees are reference
cycles) is churn, not a leak: ``LeakSampler.sample(recount=)``.

Hot-path cost is zero except one integer/time comparison on non-sample
frames; full work runs only every ``SAMPLE_EVERY_SECONDS`` (frame-count
fallback when no clock is passed).
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Deque, Optional, Sequence, Tuple

# Wall-clock cadence (~15s of history at 1.5s). Frame fallback is for tests
# and for callers that do not pass ``now`` — do not use it as the real
# interval when FPS is uncapped (``canvas.framerate = "max"``).
SAMPLE_EVERY_SECONDS = 1.5
SAMPLE_EVERY_FRAMES = 90
HISTORY_LEN = 10

# Of HISTORY_LEN-1 intervals, this many must be strict increases.
MIN_CLIMB_STEPS = 7
# Last N intervals must still contain a strict increase (not leveled off).
CLIMB_TAIL = 3

# Absolute net deltas over the full window.
MIN_OBJECT_DELTA = 24
MIN_GRAPH_DELTA = 40
# Registry-object leak: most samples must each add this many objects. Casual
# spawn / button clicks are +1..+4; a per-frame construct is tens–hundreds.
MIN_OBJECT_STEP = 8
# Graph climb with near-flat objects: allow ± this many entities.
OBJECT_FLAT_SLACK = 3
# Orphan-node pile-on: many graph nodes per new (or zero) objects.
MAX_NORMAL_NODES_PER_OBJECT = 40


def _strict_increases(values: Sequence[int]) -> int:
    return sum(1 for i in range(1, len(values)) if values[i] > values[i - 1])


def _still_climbing(values: Sequence[int], tail_steps: int = CLIMB_TAIL) -> bool:
    """True when the tail of the series is still making new highs."""
    if len(values) < 2:
        return False
    start = max(1, len(values) - tail_steps)
    return any(values[i] > values[i - 1] for i in range(start, len(values)))


def _sustained_climb(values: Sequence[int], min_delta: int) -> bool:
    """Net growth plus ongoing step-ups — not a burst that then plateaus."""
    if len(values) < 2:
        return False
    if values[-1] - values[0] < min_delta:
        return False
    if _strict_increases(values) < MIN_CLIMB_STEPS:
        return False
    return _still_climbing(values)


def _large_object_steps(values: Sequence[int]) -> int:
    return sum(
        1
        for i in range(1, len(values))
        if values[i] - values[i - 1] >= MIN_OBJECT_STEP
    )


def leak_signal(history: Sequence[Tuple[int, int]]) -> Optional[str]:
    """Classify a rolling sample window.

    Returns ``"objects"``, ``"graph"``, or ``None``. Pure — unit-testable with
    synthetic histories and soak-churn / arena-spawn replays.
    """
    if len(history) < HISTORY_LEN:
        return None
    ents = [e for e, _ in history]
    graphs = [g for _, g in history]
    d_obj = ents[-1] - ents[0]
    d_graph = graphs[-1] - graphs[0]

    # Orphaned Containers: graph keeps climbing while the registry does not.
    if _sustained_climb(graphs, MIN_GRAPH_DELTA) and abs(d_obj) <= OBJECT_FLAT_SLACK:
        return "graph"

    # Missing destroy() in a loop: objects keep jumping by a leak-sized
    # step, not a spawn-sized step. Proportional graph growth is expected
    # (each Entity registers) and must not suppress this.
    if (
        _sustained_climb(ents, MIN_OBJECT_DELTA)
        and _large_object_steps(ents) >= MIN_CLIMB_STEPS
    ):
        return "objects"

    # Disproportionate graph growth vs objects (many orphan nodes per entity).
    if (
        _sustained_climb(graphs, MIN_GRAPH_DELTA)
        and d_obj >= 0
        and d_graph / max(d_obj, 1) > MAX_NORMAL_NODES_PER_OBJECT
    ):
        return "graph"

    return None


def format_leak_message(kind: str, entities: int, graph_nodes: int,
                        entities0: int, graph0: int) -> str:
    if kind == "objects":
        return (
            f"objects rising ({entities0}→{entities}); "
            f"possible missing destroy()"
        )
    return (
        f"reactive graph rising ({graph0}→{graph_nodes}) while objects "
        f"stay ~{entities}; possible orphaned Container (e.g. Vec2 reassignment)"
    )


class LeakSampler:
    """Rolling sample buffer + enable flag for ScenaFramework."""

    def __init__(self) -> None:
        self.enabled = True
        self._history: Deque[Tuple[int, int]] = deque(maxlen=HISTORY_LEN)
        self._frame = 0
        self._sample_at: Optional[float] = None
        self._active_kind: Optional[str] = None

    def reset(self) -> None:
        self._history.clear()
        self._frame = 0
        self._sample_at = None
        self._active_kind = None

    def advance(self, now: Optional[float] = None) -> bool:
        """Return True iff this frame should sample.

        When ``now`` is wall-clock seconds, sample on ``SAMPLE_EVERY_SECONDS``.
        Otherwise fall back to every ``SAMPLE_EVERY_FRAMES`` frames.
        """
        if not self.enabled:
            return False
        self._frame += 1
        if now is None:
            return self._frame % SAMPLE_EVERY_FRAMES == 0
        t = float(now)
        if self._sample_at is None:
            self._sample_at = t
            return False
        if t - self._sample_at < SAMPLE_EVERY_SECONDS:
            return False
        self._sample_at = t
        return True

    def sample(
        self,
        entities: int,
        graph_nodes: int,
        recount: Optional[Callable[[], Tuple[int, int]]] = None,
    ) -> Optional[Tuple[str, str]]:
        """Record one sample. Returns ``(kind, message)`` only on a new hit.

        Repeats of the same kind while the trend continues are suppressed so a
        sliding window does not spam a new SCENA WARNING every sample.

        ``recount`` runs only when a new hit is about to fire: it collects
        cyclic garbage and returns fresh ``(entities, graph_nodes)``, which
        replace this sample before the window is judged again. Graph nodes
        are weak (GC backstop), but a Container tree is a reference cycle
        (owner ↔ parts), so a discarded one leaves the graph only at a full
        collection. Per-frame temporaries (a ``Point(...)`` built in
        ``update``) pile up there between collections and read as a climb;
        what one ``gc.collect()`` gives back is churn, not a leak.
        """
        self._history.append((int(entities), int(graph_nodes)))
        kind = leak_signal(list(self._history))
        if kind is not None and kind != self._active_kind and recount is not None:
            e, g = recount()
            self._history[-1] = (int(e), int(g))
            kind = leak_signal(list(self._history))
        if kind is None:
            self._active_kind = None
            return None
        if kind == self._active_kind:
            return None
        self._active_kind = kind
        e0, g0 = self._history[0]
        e1, g1 = self._history[-1]
        return kind, format_leak_message(kind, e1, g1, e0, g0)
