"""Known geometry-contract violations (``test_geometry_contract``). SHRINK-ONLY.

Seeded 2026-09-30 by the first full sweep (Testing Design — Geometry contract).
A fix removes its entries; a listed entry that now passes fails the suite,
so this file cannot go stale. Never add an entry to make a new failure pass:
triage it (engine bug / design gap / oracle stricter than the contract) first.
Relational Line models and Ellipse FROM_RECT joined KINDS on 2026-10-08 (graphics
review); their entries carry the finding ID and the batch that removes them.
"""

KNOWN = {
    "C1": frozenset({
        # GR1 (batch 8): PARALLEL_DIST move projects onto the normal (changes dist)
        # SB4 (batch 8): TANGENT_ANGLE two angle readers, about= ignored
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
    }),
    "C2": frozenset({
        # GR1 (batch 8): PARALLEL_DIST move projects onto the normal (changes dist)
        # SB4 (batch 8): TANGENT_ANGLE two angle readers, about= ignored
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
    }),
    "C3": frozenset({
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
    }),
    "C4": frozenset({
    }),
    "C5": frozenset({
    }),
    "C6": frozenset({
    }),
    "C7": frozenset({
        # GR1 (batch 8): the PARALLEL_DIST source moves wrong; its free copy is right
        # SB1 (batch 8): the TANGENT_POINT source moves wrong; its free copy is right
    }),
    "C8": frozenset({
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
    }),
}
