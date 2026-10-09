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

# Phase-1 probes (test_geom_probes): probe id -> finding. A listed probe must
# still fail; one that passes must be removed.
PROBES = {
    "Q1": "spine flip unwraps toward the previous heading; phase 7",
    "Q2": "a finished timed rotate_to keeps the shortest-arc end; phase 7",
    "Q2-camera": "the camera's timed rotate_to keeps the shortest-arc end; phase 7",
    "Q3b-unlink_all": "unlink_all keeps the relational model; phase 7",
    "Q3b-destroy": "a destroyed reference keeps the relational model; phase 7",
    "Q3b-force": "force=True leaves a hybrid (CENTER_WH with a linked center); phase 7",
    "Q5": "State stores a named function; phase 7",
    "GR17-link": "a link on a Defining angle leaves _rotation behind; phase 7",
    "GX1": "a tall Ellipse swaps its foci on a flip; phase 7",
    "GX2": "a zero-length Line keeps its heading on a flip; phase 7",
    "GX3": "a zero-length tangent Line accepts a flip; phase 7",
    "GX4": "timed verbs skip the up-front write gate; phase 7",
    "GX5": "pose-zoom kinds below MIN_SCALE move by the clamped factor; phase 7",
    "GX6": "a whole link during a running motion raises from a later tick; phase 7",
    "GX7": "a write before any read skips the pull of a pull-owned point; phase 7",
}

# Timed / instant gate parity (test_geom_structure.TestTimedVerbsGateLikeInstant):
# "kind | link | verb(time=) | accepted / raised from a tick".
GATE_PARITY = {
    "* | move_to(time=) | *": "GX4: timed move_to skips the gate (linked part, chain, whole, relational); phase 7",
    "* | scale_by(time=) | *": "GX4: timed scale_by skips the gate; phase 7",
    "* | scale_to(time=) | *": "GX4: timed scale_to skips the gate; phase 7",
    "Line tangent_point | none | move_by(time=) | *": "GX4: timed move_by skips the tangent gate; phase 7",
    "Line center_length | * | rotate_??(time=) | raised from a tick":
        "GX4: a timed turn of a Line whose center is linked writes the center in its tick; phase 7",
}

# Structural guards (test_geom_structure): site -> finding.
BARE_EXCEPT = {
    "track._move_by": "GX8: the fast path swallows every exception and falls back; phase 7",
}

# Sentinel (geom_sentinel; ``run_tiers.py <tier> --sentinel``): fnmatch patterns
# over "invariant | Kind MODEL | Class.call".
SENTINEL = {
    "I-heading | *": "GR17-link: a link on a Defining angle leaves the pose store behind; phase 7",
    "I-bare | Line *": "GX7: a write before any read seeds the bare flag on a pull-owned point; phase 7",
    "I-atomic | Polygon | FieldRef.__imatmul__": "GX11: a link refused for wheel_rotate leaves its anchor; phase 7",
    "I-atomic | Sprite | FieldRef.__imatmul__": "GX11; phase 7",
    "I-graph | * | *": "harness: program_oracles.reactive_config swaps the scena system mid-process, "
                       "so a module singleton (clock) keeps its node id from the old graph; not an "
                       "author path (one system per process)",
}

# Laws (test_geom_laws): fnmatch patterns over "law | kind | detail".
LAWS = {
    "rotate_to timed = instant (Q2) | * | angle (turns)":
        "Q2: a finished timed rotate_to keeps the shortest-arc end; phase 7",
    "flip_x then flip_y = rotate_by 180 (geometry) | Line tangent_angle | *":
        "GX3: a zero-length tangent line accepts the flips it refuses at any other length; phase 7",
}

# Copy commutes with verbs (test_geom_laws.TestCopyCommutes): "door [after verb] | kind | detail".
COPY_LAWS = {
    "<< | Sprite | copy raises NotImplementedError":
        "GX9: << on a Sprite / Svg / Text raises Python's NotImplementedError; phase 7",
    "<< | Svg | copy raises NotImplementedError": "GX9; phase 7",
    "<< | Text * | copy raises NotImplementedError": "GX9; phase 7",
    "<< after flip_? | Track * | *":
        "GX10: a Track copy of a flipped source draws the unflipped points; phase 7",
}

# Influence matrix (test_geom_influence): "kind | input | detail".
INFLUENCE = {}
