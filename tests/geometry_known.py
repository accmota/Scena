"""Known geometry-contract violations (``test_geometry_contract``). SHRINK-ONLY.

Seeded 2026-09-30 by the first full sweep (Testing Design — Geometry contract).
A fix removes its entries; a listed entry that now passes fails the suite,
so this file cannot go stale. Never add an entry to make a new failure pass:
triage it (engine bug / design gap / oracle stricter than the contract) first.
"""

KNOWN = {
    "C1": frozenset({
    }),
    "C2": frozenset({
    }),
    "C3": frozenset({
    }),
    "C4": frozenset({
    }),
    "C5": frozenset({
    }),
    "C6": frozenset({
    }),
    "C7": frozenset({
    }),
    "C8": frozenset({
    }),
}
