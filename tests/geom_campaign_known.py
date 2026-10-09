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
}

# Phase-1 probes (test_geom_probes): probe id -> finding. A listed probe must
# still fail; one that passes must be removed.
PROBES = {
    "Q3b-unlink_all": "unlink_all keeps the relational model; phase 7",
    "Q3b-destroy": "a destroyed reference keeps the relational model; phase 7",
    "Q3b-force": "force=True leaves a hybrid (CENTER_WH with a linked center); phase 7",
}

# Timed / instant gate parity (test_geom_structure.TestTimedVerbsGateLikeInstant):
# "kind | link | verb(time=) | accepted / raised from a tick".
GATE_PARITY = {
}

# Structural guards (test_geom_structure): site -> finding.
BARE_EXCEPT = {}

# Sentinel (geom_sentinel; ``run_tiers.py <tier> --sentinel``): fnmatch patterns
# over "invariant | Kind MODEL | Class.call".
SENTINEL = {
    "I-graph | * | *": "harness: program_oracles.reactive_config swaps the scena system mid-process, "
                       "so a module singleton (clock) keeps its node id from the old graph; not an "
                       "author path (one system per process)",
}

# Laws (test_geom_laws): fnmatch patterns over "law | kind | detail".
LAWS = {
}

# Copy commutes with verbs (test_geom_laws.TestCopyCommutes): "door [after verb] | kind | detail".
COPY_LAWS = {
}

# Influence matrix (test_geom_influence): "kind | input | detail".
INFLUENCE = {}

# Value edges through every path (test_geom_values): "kind | field | path [vs =] | detail".
VALUES = {
}

# A linked field whose source turns bad (test_geom_values.TestLinkSourceTurnsBad).
BAD_SOURCE = {
}

# Fuzzer (tests/fuzz/geom_fuzz.py): fnmatch patterns over its signatures
# ("oracle | kind | observable | rewrites | tags: …").
FUZZ = {
    "* | tags: *relational unlinked*":
        "Q3b: unlink_all() keeps the relational model, so later verbs still follow the old "
        "relation (or caches); phase 7",
}
