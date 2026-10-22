"""Video pilots: they play a whole run, not a few seconds of a clip.

A pilot is ``(game, t, **args)``, called once per game frame (60 Hz) before the
frame steps; ``game`` is the README tool's ``Pilot`` (``hold(*keys)``,
``mouse(x, y)``, ``press()`` / ``release()``, ``game.ns`` the program's
globals; design units, y up). ``args`` come from the take (``takes.py``), so
one pilot plays several variations of a run. Two flags tell the recorder:

  game.cursor = True    draw the pointer (a window has none to capture)
  game.done = True      the run is over; the take ends after its tail

Play like a player, not like a bot: re-aim a few times a second (a reaction
time), start a key past a threshold and let go inside a smaller one (no
key flutter), and miss now and then when the take asks for it. A pilot keeps
what it remembers between frames in ``memo(game)``.
"""
from __future__ import annotations

import random


def memo(game) -> dict:
    """The pilot's memory for this run."""
    m = getattr(game, "_memo", None)
    if m is None:
        m = game._memo = {}
    return m


def at(t: float, when: float, frames: int = 1) -> bool:
    """``t`` is one of the ``frames`` game frames that start at ``when``."""
    return when <= t < when + frames / 60


def path_point(keys, t: float):
    """The point at ``t`` on a path of ``(time, (x, y))`` keys, eased between keys
    (a key repeated at two times holds still between them)."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            k = k * k * (3 - 2 * k)
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
    return keys[-1][1]


def steer(m: dict, dx: float, *, start: float = 14, stop: float = 4,
          keys=("LEFT", "RIGHT")):
    """The key to hold toward ``dx``: starts past ``start``, lets go inside ``stop``."""
    left, right = keys
    d = m.get("_steer")
    if d is None and abs(dx) > start:
        d = right if dx > 0 else left
    elif d == right and dx < stop:
        d = None
    elif d == left and dx > -stop:
        d = None
    m["_steer"] = d
    return d


# ── 02 Pegar estrelas, README catch-the-stars ──────────────────────────────

def catch_falling(game, t, *, paddle, group, fall, speed, half=40, miss=0.0,
                  reaction=0.2, seed=0):
    """A paddle that catches falling things, as a player would.

    It looks again every ``reaction`` seconds (±30 %) and goes for the item
    that arrives first among those it can still reach (``fall`` and ``speed``:
    px/s; ``half``: half the paddle). ``miss``: the chance it never notices an
    item, so some fall (``Perdidas`` counts them).
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), noticed={}, target=None, next=0.0)
    rng = m["rng"]
    pad = game.ns[paddle]
    items = list(game.ns["group"][group])
    alive = {id(s) for s in items}
    noticed = m["noticed"]
    for k in [k for k in noticed if k not in alive]:
        del noticed[k]
    for s in items:
        if id(s) not in noticed:
            noticed[id(s)] = rng.random() >= miss
    if t >= m["next"]:
        m["next"] = t + reaction * (0.7 + 0.6 * rng.random())
        px, py = pad.center.x, pad.center.y
        best = None
        for s in items:
            dy = s.center.y - py
            if not noticed[id(s)] or dy < 0:
                continue
            arrive = dy / fall
            if abs(s.center.x - px) - half > speed * arrive:
                continue
            if best is None or arrive < best[0]:
                best = (arrive, s.center.x)
        m["target"] = best[1] if best else None
    if m["target"] is None:
        game.hold()
        return
    game.hold(steer(m, m["target"] - pad.center.x))


# ── 01 Primeiro script ──────────────────────────────────────────────────────

# Design 1000 x 700, y up. Shapes: Rect (160, 480), Circle (300, 480),
# Triangle (440, 480); the star starts at (500, 200) and moves 400 px/s.
_REST = (720, 560)
_RECT, _CIRC, _TRI = (160, 480), (300, 480), (440, 480)
_DROPS = ((620, 610), (770, 530), (890, 620), (850, 330), (620, 320), (920, 430))
_FIRST_MOUSE = [
    (0.0, _REST), (3.4, _REST),
    (4.2, _RECT), (4.6, _RECT), (5.1, _CIRC), (5.5, _CIRC), (6.0, _TRI), (6.4, _TRI),
    (6.8, _CIRC), (7.2, _CIRC), (7.7, _RECT), (8.6, _RECT),
    (9.1, _DROPS[0]), (9.4, _DROPS[0]), (9.8, _DROPS[1]), (10.1, _DROPS[1]),
    (10.5, _DROPS[2]), (10.8, _DROPS[2]), (11.2, _DROPS[3]), (11.5, _DROPS[3]),
    (11.9, _DROPS[4]), (12.2, _DROPS[4]), (12.6, _DROPS[5]), (14.2, _DROPS[5]),
    (14.8, (300, 470)), (16.2, (300, 470)), (16.9, (700, 250)), (17.6, (700, 250)),
    (18.2, (560, 600)), (20.0, (560, 600)),
]
_FIRST_CLICKS = (4.4, 5.3, 6.2, 7.0, 7.9, 8.3, 15.1, 15.7)
# D once per drop point, just after the mouse arrives (a point is in the path
# twice: arriving, and holding until it leaves).
_FIRST_D = tuple(min(t for t, p in _FIRST_MOUSE if p == d) + 0.1 for d in _DROPS) + (17.2, 18.6)
_FIRST_KEYS = (                       # (from, to, keys): the star with the arrows
    (1.0, 1.5, ("RIGHT",)), (1.5, 2.1, ("UP",)), (2.1, 2.6, ("LEFT",)), (2.6, 3.2, ("DOWN",)),
    (13.0, 14.0, ("RIGHT",)),         # past x = 800: the @when rule fires
    (16.4, 16.8, ("UP",)), (16.8, 17.1, ("LEFT", "UP")),
)


def tour_first_script(game, t, *, end=20.0):
    """Every thing tutorial 01 makes, in order: the star on the arrows, a
    click on each shape (twice on some), D drops circles where the mouse is,
    then the star crosses x = 800 and the @when rule whitens the triangle and
    grows the circle; a few more clicks and drops on the new picture."""
    game.cursor = True
    game.mouse(*path_point(_FIRST_MOUSE, t))
    keys = [k for a, b, ks in _FIRST_KEYS if a <= t < b for k in ks]
    if any(at(t, w, 4) for w in _FIRST_D):
        keys.append("D")
    game.hold(*keys)
    if any(at(t, w) for w in _FIRST_CLICKS):
        game.press()
    if any(at(t, w + 0.1) for w in _FIRST_CLICKS):
        game.release()
    if t >= end:
        game.done = True


PILOTS = {f.__name__: f for f in (catch_falling, tour_first_script)}
