"""Open divergences of the program model tests (shrink-only).

Not a test module. design/Testing Design.md, "Program model tests" has the
protocol; the closed findings live in its catalogue (PM series).

A divergence is a spec expectation the engine does not meet. Each gets one verdict:

  BUG         the engine is wrong: bug loop (regression test in the owning
              test_<area>.py, fix, gate), then generalize to the class.
  SPEC-GAP    the docs are silent or ambiguous (two specs read them two ways):
              fix the Design doc / Guia, then revise the spec.
  SURPRISE    the engine is right but a reasonable author expects otherwise:
              doc line, warning, clearer error, or an API change ("Compatibility
              and versions"); then revise the spec.
  SPEC-ERROR  the spec misread clear docs: revise the spec, record the cause.
  TOLERANCE   an L1/L2 bound was too tight: widen it with a numeric reason.

Only a divergence that stays open (a BUG not fixed yet, a doc change waiting on
a decision) is listed here. ``OPEN[key]`` must still diverge: an entry whose
expectation now passes fails the guard, so the ledger only shrinks.
A revised expectation carries ``revised="<CAUSE>: <why>"`` in its spec file.

Cause codes (why the expectation was wrong, or why the bug hid):
  DOC-SILENT    the docs say nothing about this behaviour
  DOC-AMBIG     the docs allow two readings
  DOC-WRONG     the docs state something the engine does not do (and should not)
  DOC-BURIED    stated, but where an author would not look
  INTUITION     the author's intuition (the spec's GUESS) differs from the design
  MISREAD       the spec author misread a clear statement
  HARNESS       the expectation was right; the harness observed it wrongly
  NUMERIC       float / tolerance artefact
  SPEC-LOGIC    the check did not implement its own stated claim
"""
from __future__ import annotations

from typing import Dict, Tuple

VERDICTS = ("BUG", "SPEC-GAP", "SURPRISE", "SPEC-ERROR", "TOLERANCE")
CAUSES = ("DOC-SILENT", "DOC-AMBIG", "DOC-WRONG", "DOC-BURIED", "INTUITION",
          "MISREAD", "HARNESS", "NUMERIC", "SPEC-LOGIC")

# (program, spec letter, expectation id) -> (verdict, cause, note with PM id)
OPEN: Dict[Tuple[str, str, str], Tuple[str, str, str]] = {
}
