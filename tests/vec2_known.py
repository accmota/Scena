"""Known violations of the Vec2 door matrix (``test_vec2_doors``), with reasons.

Not a test module. Shrink-only: each entry names a catalogue row (Testing
Design, "VB — Vec2 battery") and why it is not fixed yet. An entry that
matches no violation fails the full run (``test_vec2_doors``, stale check):
remove it when its row is fixed or decided.

A key is a glob over ``kind|door|operand|context/read|invariant``.
"""

DOORS = {
    # VB11 (LATENT): ``v / 0`` is Python's ZeroDivisionError; ``/=`` shares it.
    "*|/=|(-0.0, 0.0)|*|leak": "VB11",
    "*|/=|(-0.0, 0.0)|*|refused": "VB11",
    "*|/=|(0, nan)|*|leak": "VB11",
}
