"""Known violations of the Vec2 door matrix (``test_vec2_doors``), with reasons.

Not a test module. Shrink-only: each entry names a catalogue row (Testing
Design, "VB — Vec2 battery") and why it is not fixed yet. An entry that
matches no violation fails the full run (``test_vec2_doors``, stale check):
remove it when its row is fixed or decided.

A key is a glob over ``kind|door|operand|context/read|invariant``.
"""

DOORS = {
    # VB4 (DECISION): GX15 lets a free Vec2 hold NaN / inf through ``<<`` and a
    # pull; every other door refuses. A held vector then breaks the formulas
    # that read its holder, far from the write.
    "*|<<|(inf, 0)|*|bad": "VB4",
    "*|<<|(inf, 0)|*|finite": "VB4",
    "*|<<|(inf, 0)|*|follow": "VB4",
    "*|<<|(0, nan)|*|bad": "VB4",
    "*|<<|(0, nan)|*|finite": "VB4",
    "*|<<|(0, nan)|*|follow": "VB4",
    "*|<<|Vec2 holding nan|*|bad": "VB4",
    "*|<<|Vec2 holding nan|*|finite": "VB4",
    "*|<<|Vec2 holding nan|*|follow": "VB4",
    "*|@= whole|(inf, 0)|*|*": "VB4",
    "*|@= whole|(0, nan)|*|*": "VB4",
    "*|@= whole|Vec2 holding nan|*|*": "VB4",
    "*|= whole|Vec2 holding nan|*|*": "VB4 (the operand exists only through VB4's door)",
    # VB10 (DECISION): ``v += point`` / ``v -= point`` take a Point as a
    # displacement; ``v + point`` is a Point (moves the place) by design.
    "*|+=|Point(3, 4)|*|bad": "VB10",
    "*|-=|Point(3, 4)|*|bad": "VB10",
    "*|alias +=|Point(3, 4)|*|bad": "VB10",
}
