"""Trace view and report shared by the model's areas."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Finding:
    law: str
    frame: int
    msg: str
    # Deduplication key: one cause seen in 500 cells is one investigation
    # (law, the author function or label kind, the first diverging event kind).
    sig: str


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    witnesses: Counter = field(default_factory=Counter)
    abstain: Counter = field(default_factory=Counter)

    def find(self, law: str, frame: int, msg: str, sig: str) -> None:
        self.findings.append(Finding(law, frame, msg, f"{law}|{sig}"))

    def witness(self, law: str, n: int = 1) -> None:
        self.witnesses[law] += n

    def signatures(self) -> Dict[str, List[Finding]]:
        out: Dict[str, List[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.sig, []).append(f)
        return out

    def merge(self, other: "Report") -> None:
        self.findings += other.findings
        self.witnesses.update(other.witnesses)
        self.abstain.update(other.abstain)

    def summary(self, limit: int = 12) -> str:
        lines = []
        for sig, fs in sorted(self.signatures().items()):
            lines.append(f"{sig}: {len(fs)}x, first at frame {fs[0].frame}: {fs[0].msg}")
            if len(lines) >= limit:
                lines.append("...")
                break
        return "\n".join(lines)


def kind_of(label: Optional[str]) -> str:
    """``Brick@game.py:25#3`` -> ``Brick@game.py:25`` (a signature part)."""
    if not label:
        return "-"
    return label.rsplit("#", 1)[0]


class Trace:
    """Events with their frame number (0 before the first frame body)."""

    def __init__(self, events: Sequence[Tuple]) -> None:
        self.events = list(events)
        self.frames: List[int] = []
        f = 0
        for e in self.events:
            if e[0] == "F":
                f = e[1]
            self.frames.append(f)
        # Frames an exception unwound through a hooked engine function: the
        # model abstains on them (a frame cut short is not a law's business).
        self.aborted = {self.frames[i] for i, e in enumerate(self.events) if e[0] == "E"}
