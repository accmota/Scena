"""C laws: contacts (design/Laws.md, "Contacts").

Input: each collision step's committed contacts (``C`` events: the pairs the
continuous layer found, as label pairs) and the author calls of the enter,
stay and exit doors. The model does not know which handler matches which
pair (that is the engine's table, not an outcome); it checks what any
handler set must satisfy.

C1  An enter handler runs only for a pair whose contact began this step, or
    a touching pair a rule began matching (``gained``: a tag joined, a rule
    set, CD3); a stay handler only for a pair that was touching in the last
    step too.
C2  A step runs its enters, then its stays, then its exits (a destroy's exit
    and a deferred exit run where the contact ended, inside the loops).
C4  A body destroyed or parked by a handler enters and stays in no other
    pair that step (its current contact's remaining handlers still run).
C5  An exit runs only for a pair in contact, once per contact (a touching
    pair a rule stopped matching, ``lost``, exits that rule once and stays).
C7  A destroyed body is in no contact after its destroy returns: no later
    step commits a pair with it (not even as an exit: its contacts ended at
    the destroy).
C8  Every handler of a step runs before that step's resolve.

C3 (every matching handler of a contact runs, chosen before the first runs)
and C6 (an exit runs the handlers its contact entered under) need the
handler table: the equations E3 / E4 and their unit tests check them.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from laws.model.base import Report, Trace, kind_of

LAWS = ("C1", "C2", "C4", "C5", "C7", "C8")

STAGE = {"enter": 0, "stay": 1, "exit": 2}


def _pair(e) -> Optional[Tuple[str, str]]:
    args = e[4]
    if len(args) < 2 or args[0] is None or args[1] is None:
        return None
    return tuple(sorted((args[0], args[1])))


def check(tr: Trace, rep: Report) -> None:
    ev = tr.events
    frames = tr.frames
    in_step = False
    entered: Set = set()
    stayed: Set = set()
    exited: Set = set()
    gained: Set = set()                  # touching pairs a rule began matching (CD3)
    lost: Set = set()                    # touching pairs a rule stopped matching, not run
    owed: Set = set()                    # pairs in contact that have not exited yet
    stage = 0
    resolved = False
    current: Optional[Tuple] = None      # pair of the last enter / stay call
    died_in: Dict[str, Optional[Tuple]] = {}
    dead: Set[str] = set()
    d_open: Dict[str, int] = {}
    d_depth = 0
    last_exit: Optional[Tuple] = None
    handlers = 0
    # pair -> the exit handlers that ran since its last enter: each runs once
    # per contact. Not "consecutive": a handler that destroys a body in two
    # contacts runs the other contact's exits inside its own (S7 found the
    # first rule naming the resumed handler a second exit).
    exited_once: Dict[Tuple, Set[Tuple]] = {}

    for i, e in enumerate(ev):
        k = e[0]
        if k == "N":
            dead.discard(e[1])
        elif k == "P" and e[1] == "collision":
            in_step = True
            stage, resolved, current = 0, False, None
            died_in = {}
            handlers = 0
        elif k == "p" and e[1] == "collision":
            in_step = False
            owed -= exited
        elif k == "C":
            entered, stayed, exited = set(e[1]), set(e[2]), set(e[3])
            gained = set(e[4]) if len(e) > 4 else set()
            lost = set(e[5]) if len(e) > 5 else set()
            last_exit = None
            rep.witness("C7")
            for p in entered | stayed | exited:
                if p[0] in dead or p[1] in dead:
                    rep.find("C7", frames[i], f"dead body in contact {p}",
                             f"{kind_of(p[0])}|{kind_of(p[1])}")
            for p in entered:
                exited_once.pop(p, None)
            owed |= entered | stayed
        elif k == "S" and e[1] == "resolve":
            resolved = True
            if handlers:
                rep.witness("C8")
        elif k == "D":
            d_open[e[1]] = d_open.get(e[1], 0) + 1
            d_depth += 1
        elif k == "d":
            d_depth = max(0, d_depth - 1)
            n = d_open.get(e[1], 0) - 1
            if n <= 0:
                d_open.pop(e[1], None)
                if e[2]:
                    dead.add(e[1])
            else:
                d_open[e[1]] = n
        elif k == "T" or (k == "K" and e[2] is None):
            if in_step and e[1] not in died_in:
                died_in[e[1]] = current
                rep.witness("C4")
        elif k == "F":
            last_exit = None
        elif k == "X" and e[1] in STAGE:
            door = e[1]
            if in_step:
                handlers += 1
            p = _pair(e)
            if p is None or "?" in p:
                rep.abstain["C"] += 1
                continue
            if door in ("enter", "stay"):
                if in_step and resolved:
                    rep.find("C8", frames[i], f"{door} {e[3]} after resolve began", door)
                rep.witness("C1")
                want = (entered | gained) if door == "enter" else stayed
                if p not in want:
                    rep.find("C1", frames[i], f"{door} {e[3]} for {p}, not {door}ed this step",
                             f"{door}|{e[3]}")
                st = STAGE[door]
                if st < stage:
                    rep.find("C2", frames[i], f"{door} {e[3]} after a later loop began",
                             f"{door}-late")
                stage = max(stage, st)
                rep.witness("C2")
                for side in p:
                    if side in died_in and died_in[side] != p:
                        rep.find("C4", frames[i], f"{side} out of play, {door} {e[3]} for {p}",
                                 f"{door}|{e[3]}")
                current = p
                last_exit = None
            else:
                rep.witness("C5")
                if in_step and resolved and not d_depth:
                    rep.find("C8", frames[i], f"exit {e[3]} after resolve began", "exit")
                if p in lost and p in owed and p not in exited:
                    # A rule the touching pair lost (CD3): its exit; the pair
                    # stays, so it is no exit of the pair's contact.
                    if in_step and not d_depth:
                        if STAGE["exit"] < stage:
                            rep.find("C2", frames[i], "exit before stays", "exit-early")
                        stage = 2
                    last_exit = p
                    continue
                if p not in owed and p not in exited:
                    rep.find("C5", frames[i], f"exit {e[3]} for {p}, not in contact",
                             f"stray|{e[3]}")
                elif (e[3], e[4][0]) in exited_once.get(p, ()):
                    rep.find("C5", frames[i], f"second exit {e[3]} for {p}", f"twice|{e[3]}")
                step_exit = in_step and p in exited and not d_depth
                if step_exit:
                    if STAGE["exit"] < stage:
                        rep.find("C2", frames[i], "exit before stays", "exit-early")
                    stage = 2
                # A handler is its function and the side it runs as: a class
                # rule (``@collide_with_exit``) of both bodies runs one function
                # once from each side (the World machine's M5 found it).
                exited_once.setdefault(p, set()).add((e[3], e[4][0]))
                last_exit = p
