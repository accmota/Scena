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
    "Q2": "a finished timed rotate_to keeps the shortest-arc end; phase 7",
    "Q2-camera": "the camera's timed rotate_to keeps the shortest-arc end; phase 7",
    "Q3b-unlink_all": "unlink_all keeps the relational model; phase 7",
    "Q3b-destroy": "a destroyed reference keeps the relational model; phase 7",
    "Q3b-force": "force=True leaves a hybrid (CENTER_WH with a linked center); phase 7",
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
    "Circle * | * | rotate_??(time=) | refused (instant runs)":
        "GX17: a timed turn of a Circle whose center is linked is refused; the instant turn runs; phase 7",
}

# Structural guards (test_geom_structure): site -> finding.
BARE_EXCEPT = {}

# Sentinel (geom_sentinel; ``run_tiers.py <tier> --sentinel``): fnmatch patterns
# over "invariant | Kind MODEL | Class.call".
SENTINEL = {
    "I-bare | Line *": "GX7: a write before any read seeds the bare flag on a pull-owned point; phase 7",
    "I-graph | * | *": "harness: program_oracles.reactive_config swaps the scena system mid-process, "
                       "so a module singleton (clock) keeps its node id from the old graph; not an "
                       "author path (one system per process)",
}

# Laws (test_geom_laws): fnmatch patterns over "law | kind | detail".
LAWS = {
    "rotate_to timed = instant (Q2) | * | angle (turns)":
        "Q2: a finished timed rotate_to keeps the shortest-arc end; phase 7",
}

# Copy commutes with verbs (test_geom_laws.TestCopyCommutes): "door [after verb] | kind | detail".
COPY_LAWS = {
    "<< after flip_? | Track * | *":
        "GX10: a Track copy of a flipped source draws the unflipped points; phase 7",
}

# Influence matrix (test_geom_influence): "kind | input | detail".
INFLUENCE = {}

# Value edges through every path (test_geom_values): "kind | field | path [vs =] | detail".
VALUES = {
    "* | * | link vs = | ok vs refused":
        "GX14: a link pull accepts a bool that = refuses; phase 7",
    "* | * | link | not an author error":
        "GX14: a link pull leaks OverflowError for a huge int; phase 7",
    "* | vec | * | stores a non-finite value":
        "GX15: a shape's vec part stores inf (the Vec2 takein skips the Numbers rule); phase 7",
    "* | vec | * | not an author error": "GX15: a huge int leaks OverflowError; phase 7",
    "* | vec | * vs = | stores another value": "GX15: a stored inf draws NaN geometry; phase 7",
    "Line * | vec | * | refusal changed *": "GX15: a Line refuses vec=(0, inf) after moving its center; phase 7",
}

# A linked field whose source turns bad (test_geom_values.TestLinkSourceTurnsBad).
BAD_SOURCE = {
    "bad source | * <- True: accepted": "GX14; phase 7",
    "bad source | * <- 1000000000000000000000*: accepted": "GX14 (a huge int through a pull); phase 7",
    "bad source | * <- 1000000000000000000000*: OverflowError is not an author error": "GX14; phase 7",
}

# Fuzzer (tests/fuzz/geom_fuzz.py): fnmatch patterns over its signatures
# ("oracle | kind | observable | rewrites | tags: …").
FUZZ = {
    "P vs P' | Circle * | * | *timed_to_instant* | tags: *part link*":
        "GX17: a timed turn of a Circle with a linked center is refused; phase 7",
    "* | tags: *zero scale*":
        "GX5: at or below MIN_SCALE a pose-zoom kind moves its center by the clamped factor "
        "and sizes its box by the exact one; phase 7",
    "P vs P' | Line center_length | * | tags: *part link*":
        "GX16: after one scale about a linked center, the center drifts 1 ulp and the next "
        "scale_by is refused; phase 7",
    "* | tags: *relational unlinked*":
        "Q3b: unlink_all() keeps the relational model, so later verbs still follow the old "
        "relation (or caches); phase 7",
}
