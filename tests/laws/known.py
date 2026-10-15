"""Expected laws findings, each with its triage verdict and reason.

Shrink-only: ``test_laws_families`` fails on a finding not listed here and
on an entry no run produces any more (fixed: remove it). Verdicts
(Testing Design, "Laws and equations"): ACADEMIC (legitimate approximation;
the engine is not touched), LATENT (a wrong calculation no game shows yet;
names the scenario that would), DECISION (the law itself is in question;
asked of the user). A BUG is fixed, never listed.

Keys are finding signatures (``Finding.sig``: ``law|detail``); values are
``(verdict, reason, family)`` with family one of ``programs``, ``games``,
``examples``, ``tutorials`` (the family whose sweep must still produce it).
"""
from __future__ import annotations

from typing import Dict, Tuple

KNOWN: Dict[str, Tuple[str, str, str]] = {
}
