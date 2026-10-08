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
        'Line parallel_dist | move_by timed | center',
        'Line parallel_dist | move_by timed | p1',
        'Line parallel_dist | move_by timed | p2',
        'Line parallel_dist | move_by | center',
        'Line parallel_dist | move_by | p1',
        'Line parallel_dist | move_by | p2',
        'Line parallel_dist | move_to | center',
        'Line parallel_dist | move_to | p1',
        'Line parallel_dist | move_to | p2',
        # SB4 (batch 8): TANGENT_ANGLE two angle readers, about= ignored
        'Line tangent_angle | angle = | center',
        'Line tangent_angle | angle = | p1',
        'Line tangent_angle | angle = | p2',
        'Line tangent_angle | rotate_by about | center',
        'Line tangent_angle | rotate_by about | p1',
        'Line tangent_angle | rotate_by about | p2',
        'Line tangent_angle | rotate_by timed | center',
        'Line tangent_angle | rotate_by timed | p1',
        'Line tangent_angle | rotate_by timed | p2',
        'Line tangent_angle | rotate_by | center',
        'Line tangent_angle | rotate_by | p1',
        'Line tangent_angle | rotate_by | p2',
        'Line tangent_angle | rotate_to | center',
        'Line tangent_angle | rotate_to | p1',
        'Line tangent_angle | rotate_to | p2',
        'Line tangent_angle | scale_by about | center',
        'Line tangent_angle | scale_by about | p1',
        'Line tangent_angle | scale_by about | p2',
        'Line tangent_angle | scale_by timed | center',
        'Line tangent_angle | scale_by timed | p1',
        'Line tangent_angle | scale_by timed | p2',
        'Line tangent_angle | scale_by | center',
        'Line tangent_angle | scale_by | p1',
        'Line tangent_angle | scale_by | p2',
        'Line tangent_angle | scale_to | center',
        'Line tangent_angle | scale_to | p1',
        'Line tangent_angle | scale_to | p2',
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
        'Line tangent_point | angle = | center',
        'Line tangent_point | angle = | p2',
        'Line tangent_point | move_by timed | center',
        'Line tangent_point | move_by timed | p2',
        'Line tangent_point | move_by | center',
        'Line tangent_point | move_by | p2',
        'Line tangent_point | move_to | center',
        'Line tangent_point | move_to | p2',
        'Line tangent_point | rotate_by about | center',
        'Line tangent_point | rotate_by about | p2',
        'Line tangent_point | rotate_by timed | center',
        'Line tangent_point | rotate_by timed | p1',
        'Line tangent_point | rotate_by timed | p2',
        'Line tangent_point | rotate_by | center',
        'Line tangent_point | rotate_by | p2',
        'Line tangent_point | rotate_to | center',
        'Line tangent_point | rotate_to | p2',
        'Line tangent_point | scale_by about | center',
        'Line tangent_point | scale_by about | p2',
        'Line tangent_point | scale_by timed | center',
        'Line tangent_point | scale_by timed | p1',
        'Line tangent_point | scale_by timed | p2',
        'Line tangent_point | scale_by | center',
        'Line tangent_point | scale_by | p2',
        'Line tangent_point | scale_to | center',
        'Line tangent_point | scale_to | p2',
    }),
    "C2": frozenset({
        # GR1 (batch 8): PARALLEL_DIST move projects onto the normal (changes dist)
        'Line parallel_dist | drawn follows | move_by',
        'Line parallel_dist | drawn follows | move_by timed',
        'Line parallel_dist | drawn follows | move_to',
        # SB4 (batch 8): TANGENT_ANGLE two angle readers, about= ignored
        'Line tangent_angle | drawn follows | angle =',
        'Line tangent_angle | drawn follows | rotate_by',
        'Line tangent_angle | drawn follows | rotate_by about',
        'Line tangent_angle | drawn follows | rotate_by timed',
        'Line tangent_angle | drawn follows | rotate_to',
        'Line tangent_angle | drawn follows | scale_by',
        'Line tangent_angle | drawn follows | scale_by about',
        'Line tangent_angle | drawn follows | scale_by timed',
        'Line tangent_angle | drawn follows | scale_to',
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
        'Line tangent_point | compose | rotate a then b == a+b',
        'Line tangent_point | compose | scale k1 then k2 == k1k2',
        'Line tangent_point | drawn follows | angle =',
        'Line tangent_point | drawn follows | move_by',
        'Line tangent_point | drawn follows | move_by timed',
        'Line tangent_point | drawn follows | move_to',
        'Line tangent_point | drawn follows | rotate_by',
        'Line tangent_point | drawn follows | rotate_by about',
        'Line tangent_point | drawn follows | rotate_by timed',
        'Line tangent_point | drawn follows | rotate_to',
        'Line tangent_point | drawn follows | scale_by',
        'Line tangent_point | drawn follows | scale_by about',
        'Line tangent_point | drawn follows | scale_by timed',
        'Line tangent_point | drawn follows | scale_to',
        'Line tangent_point | inverse | rotate a, -a',
        'Line tangent_point | inverse | scale k, 1/k',
        'Line tangent_point | pose | rotation after rotate_by',
    }),
    "C3": frozenset({
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
        'Line tangent_point | move_by | length',
        'Line tangent_point | rotate_by about | length',
        'Line tangent_point | rotate_by | length',
        'Line tangent_point | scale_by | length',
    }),
    "C4": frozenset({
    }),
    "C5": frozenset({
    }),
    "C6": frozenset({
    }),
    "C7": frozenset({
        # GR1 (batch 8): the PARALLEL_DIST source moves wrong; its free copy is right
        'Line parallel_dist | << then move_by | drawn',
        'Line parallel_dist | absorb then move_by | drawn',
        'Line parallel_dist | clone then move_by | drawn',
        # SB1 (batch 8): the TANGENT_POINT source moves wrong; its free copy is right
        'Line tangent_point | << then move_by | drawn',
        'Line tangent_point | absorb then move_by | drawn',
        'Line tangent_point | clone then move_by | drawn',
    }),
    "C8": frozenset({
        # SB1 (batch 8): TANGENT_POINT pivots on p1, scale shrinks
        'Line tangent_point | scale 0 then 1 | drawn',
        'Line tangent_point | tiny and back | drawn',
    }),
}
