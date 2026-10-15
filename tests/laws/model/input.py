"""I laws: input ownership (design/Laws.md, "Input").

Input: one ``I`` event per OS key or button event — its name, action
(0 release, 1 press, 2 repeat) and the doors it reached while it was
handled (``script-down`` / ``script-up`` / ``script-key``, ``widget-down`` /
``widget-up`` / ``widget-key``, ``shape-down``, ``script-forget``) — the act
changes (``A``) and the presses a leaving widget gave up (``O abandon``).
The doors are the engine's delivery points, whether or not the author wrote
the hook behind them.

I1  Every down the script got gets exactly one up, also when the act
    changed, a modal opened or a widget took focus in between (PD7, S3-7).
I2  An up goes where its down went: a key or a button a widget or a shape
    took never ends in the script's up (and never as a script click).
I3  A repeat follows its press: never to the script for a press it did not
    get or one made in an old act (W-P4); never into a box that took focus
    after the script got the press (PD3).
I4  A typed character follows the key event that made it: the character of
    a key the box did not get (the script's press, a game key held into
    focus) is never typed into the box (LW5).
I5  A press a widget gave up when it left (destroyed, act change) ends with
    no release to any widget and no script up (PD1).
"""
from __future__ import annotations

from typing import Dict, Tuple

from laws.model.base import Report, Trace

LAWS = ("I1", "I2", "I3", "I4", "I5")

RELEASE, PRESS, REPEAT = 0, 1, 2


def _owner(doors) -> str:
    if "widget-down" in doors:
        return "widget"
    if "shape-down" in doors:
        return "shape"
    if "script-down" in doors:
        return "script"
    return "none"


def check(tr: Trace, rep: Report) -> None:
    keys: Dict[str, Tuple[str, int]] = {}      # key -> (owner, act epoch at the press)
    buttons: Dict[str, str] = {}
    abandoned: Dict[str, bool] = {}
    last_key = [None]                          # owner of the last press / repeat, until its release
    act = 0
    for i, e in enumerate(tr.events):
        k = e[0]
        if k == "A":
            act += 1
        elif k == "O" and e[1] == "abandon":
            abandoned[e[2]] = True
        elif k == "I":
            _kind, name, action, doors = e[1], e[2], e[3], set(e[4])
            f = tr.frames[i]
            if _kind == "key":
                _key(rep, f, keys, name, action, doors, act)
                if action == RELEASE:
                    last_key[0] = None
                else:
                    last_key[0] = "widget" if doors & {"widget-down", "widget-key"} else "other"
            elif _kind == "char":
                if last_key[0] == "other":
                    rep.witness("I4")
                    if "widget-char" in doors:
                        rep.find("I4", f, f"char {name!r} of a key the box did not get typed "
                                 "into the box", "char-into-box")
            else:
                _button(rep, f, buttons, abandoned, name, action, doors)


def _key(rep, f, keys, name, action, doors, act):
    if action == PRESS:
        owner = _owner(doors)
        prev = keys.get(name)
        if owner == "script" and prev is not None and prev[0] == "script":
            rep.find("I1", f, f"key {name}: a second script down with no up", "key-down-twice")
        keys[name] = (owner, act)
    elif action == REPEAT:
        owner = keys.get(name)
        rep.witness("I3")
        if "script-key" in doors:
            if owner is None or owner[0] != "script":
                rep.find("I3", f, f"key {name}: a repeat reached the script, the press went to "
                         f"{owner[0] if owner else 'nobody'}", "repeat-not-script's")
            elif owner[1] != act:
                rep.find("I3", f, f"key {name}: a repeat of an old act's press reached on_key",
                         "repeat-old-act")
        if "widget-key" in doors and owner is not None and owner[0] == "script":
            rep.find("I3", f, f"key {name}: a repeat of the script's press typed into a box",
                     "repeat-into-box")
    elif action == RELEASE:
        owner = keys.pop(name, None)
        rep.witness("I2")
        if owner is not None and owner[0] == "script":
            rep.witness("I1")
            if "script-up" not in doors:
                rep.find("I1", f, f"key {name}: the script got the down, not the up"
                         + (" (the act changed)" if owner[1] else ""), "key-up-lost")
        elif "script-up" in doors:
            rep.find("I2", f, f"key {name}: a script up for a press that went to "
                     f"{owner[0] if owner else 'nobody'}", "key-up-stray")


def _button(rep, f, buttons, abandoned, name, action, doors):
    if action == PRESS:
        buttons[name] = _owner(doors)
        abandoned.pop(name, None)
    elif action == RELEASE:
        owner = buttons.pop(name, None)
        rep.witness("I2")
        if owner == "script":
            rep.witness("I1")
            if "script-up" not in doors:
                rep.find("I1", f, f"button {name}: the script got the down, not the up",
                         "button-up-lost")
        elif "script-up" in doors:
            rep.find("I2", f, f"button {name}: a script up for a press that went to "
                     f"{owner or 'nobody'}", "button-up-stray")
        if abandoned.pop(name, False):
            rep.witness("I5")
            if "widget-up" in doors or "script-up" in doors:
                rep.find("I5", f, f"button {name}: a press given up still released into "
                         f"{sorted(doors & {'widget-up', 'script-up'})}", "abandoned-released")
