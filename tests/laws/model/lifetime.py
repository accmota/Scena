"""L laws: lifetime (design/Laws.md, "Lifetime").

L1  destroy() is synchronous: when the outermost destroy of an object
    returns, the object is dead.
L2  on_destroy runs at most once per object, before its teardown starts
    (the object is still whole when its hook reads it).
L3  After an object's destroy returns, none of its own methods runs again
    as a hook (handlers, timers, on_update, formulas) — except the rest of
    the contact it died in: every enter / stay handler of a contact runs,
    chosen before the first (PB5), the dying body's other methods included.
L4  A parked actor (active = False) runs none of its own methods as a
    timer, on_update, contact, hover or leave hook until it resumes.
L5  An act change runs every on_destroy of the ending act's objects before
    it tears down the first of them (a hook can read any sibling).
L6  An act change builds the next act only after the ending act's objects
    are gone, and tears down nothing made at the top of the file.

"Its own methods": an author call whose first parameter is ``self`` and is
the object (the trace's ``method`` flag). A module rule that receives the
object (``@collide_exit`` with a dead ``me``) is not the object's own hook:
the contact laws judge it.
"""
from __future__ import annotations

from typing import Dict, List, Set

from laws.model.base import Report, Trace, kind_of

LAWS = ("L1", "L2", "L3", "L4", "L5", "L6")

# L4: what a parked actor must not run. Exits, @when / @on_change, formula
# pulls and resumes of a mode are not on it: a park ends contacts (their
# exits fire) and a parked actor's conditions keep polling (Actors Design,
# "active (park)").
OWNED_WHILE_PARKED = {"every", "after", "tick", "on_update", "contact", "enter", "stay",
                      "hover", "leave"}

# Doors that run inside the destroy itself (the dying body's own exits).
INSIDE_DESTROY = {"exit-of", "exit-keys", "on_destroy"}


def _x(e):
    """(door, fn, me, method) of an author call."""
    args = e[4]
    return e[1], e[3], (args[0] if args else None), (e[6] if len(e) > 6 else False)


def check(tr: Trace, rep: Report) -> None:
    ev = tr.events
    frames = tr.frames
    open_d: Dict[str, List[int]] = {}       # label -> stack of D indices (nesting)
    dead_at: Dict[str, int] = {}            # label -> index of its outermost d (dead)
    torn: Set[str] = set()                  # labels whose teardown started (T)
    hooked: Dict[str, int] = {}             # label -> on_destroy count
    parked: Dict[str, int] = {}             # root label -> K index
    windows = []                            # (A index, a index)
    a_open = None
    sealed = False
    top_level: Set[str] = set()
    acts: Set[str] = set()                  # act class names (B events)
    in_collision = False
    contact = None                          # pair of the last enter / stay call
    died_in: Dict[str, object] = {}         # label -> the contact it died in (this step)

    for i, e in enumerate(ev):
        k = e[0]
        if k == "N":
            label = e[1]
            dead_at.pop(label, None)        # id reused: a new life
            torn.discard(label)
            hooked.pop(label, None)
            if not sealed:
                top_level.add(label)
        elif k == "B":
            sealed = True
            acts.add(e[1])
        elif k == "A":
            a_open = i
        elif k == "a":
            if a_open is not None:
                windows.append((a_open, i))
            a_open = None
        elif k == "T":
            torn.add(e[1])
            if in_collision:
                died_in.setdefault(e[1], contact)
        elif k == "P" and e[1] == "collision":
            in_collision, contact, died_in = True, None, {}
        elif k == "p" and e[1] == "collision":
            in_collision, contact, died_in = False, None, {}
        elif k == "D":
            open_d.setdefault(e[1], []).append(i)
        elif k == "d":
            label, dead = e[1], e[2]
            stack = open_d.get(label)
            if not stack:
                continue
            start = stack.pop()
            if stack:                      # an inner (re-entrant) destroy returned
                continue
            if not ev[start][2]:           # this call started the destroy
                rep.witness("L1")
                if not dead:
                    rep.find("L1", frames[i], f"{label} not dead when destroy returned",
                             kind_of(label))
            if dead:
                dead_at[label] = i
        elif k == "K":
            if e[2] is None:
                parked[e[1]] = i
                rep.witness("L4")
        elif k == "R":
            parked.pop(e[1], None)
        elif k == "X":
            door, fn, me, method = _x(e)
            pair = None
            if door in ("enter", "stay") and len(e[4]) > 1 and e[4][1] is not None:
                pair = tuple(sorted((e[4][0], e[4][1]))) if me is not None else None
                contact = pair
            if me is None:
                continue
            if door == "on_destroy":
                rep.witness("L2")
                n = hooked.get(me, 0) + 1
                hooked[me] = n
                if n > 1:
                    rep.find("L2", frames[i], f"on_destroy of {me} ran {n} times ({fn})",
                             f"twice|{kind_of(me)}")
                if me in torn:
                    rep.find("L2", frames[i], f"on_destroy of {me} ran after its teardown "
                             f"started ({fn})", f"late|{kind_of(me)}")
            if not method:
                continue
            if me in dead_at and door not in INSIDE_DESTROY:
                if pair is not None and died_in.get(me) == pair:
                    rep.witness("L3")           # the rest of its contact (PB5)
                    continue
                rep.find("L3", frames[i], f"{door} {fn} ran for {me} after its destroy returned",
                         f"{door}|{fn}")
            elif me in dead_at:
                pass
            else:
                rep.witness("L3")
            if door in OWNED_WHILE_PARKED and me in parked:
                rep.find("L4", frames[i], f"{door} {fn} ran for parked {me}", f"{door}|{fn}")

    _act_changes(tr, rep, windows, top_level, acts)


def _act_changes(tr, rep, windows, top_level, acts) -> None:
    ev = tr.events
    for a0, a1 in windows:
        requested = set()
        batch_t = []                       # teardown starts not asked for by a destroy()
        hooks = []                         # (index, label) of on_destroy calls
        builds = []
        for j in range(a0, a1 + 1):
            e = ev[j]
            if e[0] == "Q":
                requested.add(e[1])
            elif e[0] == "T" and e[1] not in requested and e[1].split("@", 1)[0] not in acts:
                batch_t.append(j)
            elif e[0] == "X" and e[1] == "on_destroy" and e[4]:
                hooks.append((j, e[4][0]))
            elif e[0] == "B":
                builds.append(j)
        if not batch_t:
            continue
        batch = {ev[j][1] for j in batch_t}
        first_t, last_t = batch_t[0], batch_t[-1]
        if len(batch) > 1:
            rep.witness("L5")
            for j, label in hooks:
                if label in batch and j > first_t:
                    rep.find("L5", tr.frames[j], f"on_destroy of {label} ran after the "
                             f"teardown began ({ev[first_t][1]} first)", kind_of(label))
        rep.witness("L6")
        for j in builds:
            if j < last_t:
                rep.find("L6", tr.frames[j], f"act {ev[j][1]} built before {ev[last_t][1]} "
                         f"was torn down", "build-early")
                break
        for j in batch_t:
            if ev[j][1] in top_level:
                rep.find("L6", tr.frames[j], f"act change tore down top-level {ev[j][1]}",
                         f"top-level|{kind_of(ev[j][1])}")
