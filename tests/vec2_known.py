"""Known violations of the Vec2 door matrix (``test_vec2_doors``), with reasons.

Not a test module. Shrink-only: each entry names a catalogue row (Testing
Design, "VB — Vec2 battery") and why it is not fixed yet. An entry that
matches no violation fails the full run (``test_vec2_doors``, stale check):
remove it when its row is fixed or decided.

A key is a glob over ``kind|door|operand|context/read|invariant``.
"""

DOORS = {
    # VB10 (DECISION): ``v += point`` / ``v -= point`` take a Point as a
    # displacement; ``v + point`` is a Point (moves the place) by design.
    "*|+=|Point(3, 4)|*|bad": "VB10",
    "*|-=|Point(3, 4)|*|bad": "VB10",
    "*|alias +=|Point(3, 4)|*|bad": "VB10",
}
