"""F laws: the frame (design/Laws.md, "Frame").

F1  Every frame runs its phases once each, in one order: update, process
    tick, collision, leave playfield, hover, flush, pre-draw, edge expiry.
    (An explicit ``flush()`` from author code is not a frame phase.)
F2  Each door that belongs to a phase runs in that phase: update in
    update; timers and on_update in the tick; enter and stay handlers in
    collision (an exit runs where its contact ends: the step, a destroy, a
    park); @leave_playfield in leave; @hover in hover; @when /
    @on_change in flush;
    key and mouse callbacks in the poll (before update); pre-draw callbacks
    (transients, covers) in pre-draw. Destroy-time hooks (on_destroy, exits
    of a destroyed body), act builds and formula pulls run where they are
    called.
"""
from __future__ import annotations

from laws.model.base import Report, Trace

LAWS = ("F1", "F2")

ORDER = ("update", "tick", "collision", "leave", "hover", "flush", "predraw", "expire")

# The door an author function came through -> the phase it must run in.
DOOR_PHASE = {
    "update": "update",
    "every": "tick", "after": "tick", "tick": "tick", "on_update": "tick",
    "when": "flush",
    # Exits are not here: a destroy, a park or an untag ends a contact where
    # it happens (the contact laws judge exits).
    "contact": "collision", "enter": "collision", "stay": "collision",
    "leave": "leave",
    "hover": "hover",
    "flush": "flush",
    "key": "poll", "button": "poll",
    "on_key_down": "poll", "on_key_up": "poll", "on_key": "poll",
    "on_mouse_down": "poll", "on_mouse_up": "poll", "on_mouse_click": "poll",
    "on_mouse_move": "poll", "on_mouse_drag": "poll", "on_mouse_scroll": "poll",
    "predraw": "predraw",
}


def check(tr: Trace, rep: Report) -> None:
    top = []
    depth = 0
    for i, e in enumerate(tr.events):
        k = e[0]
        if k == "F":
            top = []
            depth = 0
        elif k == "P":
            # Only the frame body's own calls make the frame's phases: an
            # explicit flush() from a handler is the author's (Guia, flush).
            if depth == 0 and (len(e) < 3 or e[2]):
                top.append(e[1])
            depth += 1
        elif k == "p":
            depth = max(0, depth - 1)
        elif k == "f":
            f = e[1]
            if f in tr.aborted:
                rep.abstain["F1"] += 1
                continue
            rep.witness("F1")
            if tuple(top) != ORDER:
                rep.find("F1", f, f"phases {top}", "order")
        elif k == "X":
            door, phase = e[1], e[2]
            want = DOOR_PHASE.get(door)
            if want is None or phase is None:      # phase None: outside a frame body
                continue
            rep.witness("F2")
            if phase != want:
                rep.find("F2", tr.frames[i], f"{door} door ran in {phase} ({e[3]})",
                         f"{door}|{phase}")
