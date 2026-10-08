"""Known violations found by the geometry campaign's harnesses. SHRINK-ONLY.

One dict per harness: ``{pattern: reason}``. A pattern is an ``fnmatch``
pattern over the harness's parameter-free keys (``"kind | step | check"``).
Every key a harness finds must match a pattern; in the full run (gate, the
deterministic arrays) every pattern must match a key it found, so a fixed
entry cannot stay listed. A reason names the finding (Testing Design,
catalogue series GX) and the campaign phase that removes it.

Never add an entry to make a new failure pass: triage it first (engine bug /
design gap / oracle stricter than the contract), and only list an engine bug
or a design gap whose fix is scheduled.
"""

# H1 — affine shadow oracle (test_geom_sequences).
SHADOW = {
    "* | rotate_to timed | heading":
        "Q2: a finished timed rotate_to keeps the shortest-arc end (390 for 30 from 400); phase 7",
    "Rect spine * | flip_? | heading":
        "Q1: the spine unwraps a flip toward the previous heading (500 for -220); phase 7",
    "Ellipse * | flip_? | part fp?":
        "GX1: a tall Ellipse (height > width) swaps its foci names on a flip; phase 7",
    "Line * | flip_? | heading":
        "GX2 / GX3: a zero-length Line keeps its heading on a flip; a zero-length tangent "
        "line accepts the flip it refuses at any other length; phase 7",
    "S* | scale_by about | *":
        "GX5: below MIN_SCALE a pose-zoom kind (Sprite, Svg) moves its center by the clamped "
        "factor and its size by the exact one; phase 7",
    "* | * timed | refusal changed *":
        "GX4: a timed verb skips the up-front write gate; the refusal comes from a later "
        "tick, after part of the motion ran; phase 7",
}
