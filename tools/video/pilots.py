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


# ── Naves VI · Atos ─────────────────────────────────────────────────────────

def act_name() -> str:
    """The class name of the act on stage (``""`` before the first)."""
    import sys
    act = sys.modules["scena.act"]._manager.current
    return type(act).__name__ if act is not None else ""


def velocity(m: dict, obj, t: float) -> float:
    """``obj``'s horizontal speed (px/s), from where the pilot saw it last."""
    seen = m.setdefault("_seen", {})
    x = obj.center.x
    last = seen.get(id(obj))
    seen[id(obj)] = (x, t)
    if last is None or t <= last[1]:
        return 0.0
    return (x - last[0]) / (t - last[1])


def menu_click(game, m: dict, t: float, button, *, key: str, wait: float = 1.2,
               rest=(780, 180)):
    """Show the pointer, glide it to ``button`` after ``wait`` s on the screen
    and click; ``key`` names this screen in the pilot's memory."""
    k = t - m.setdefault(key, t)
    game.cursor = True
    game.mouse(*path_point([(0, rest), (wait, rest), (wait + 0.7, button)], k))
    if at(k, wait + 0.9):
        game.press()
    if at(k, wait + 1.0):
        game.release()


def bursts(m: dict, t: float, share: float, *, burst: float = 0.8) -> bool:
    """Fire in bursts of about ``burst`` s, firing ``share`` of the time."""
    if share >= 1.0:
        return True
    if t >= m.setdefault("_burst_until", 0.0):
        on = not m.get("_burst_on", False)
        span = burst if on else burst * (1 - share) / max(share, 0.05)
        m["_burst_on"] = on
        m["_burst_until"] = t + span * (0.7 + 0.6 * m["rng"].random())
    return m["_burst_on"]


def play_naves(game, t, *, dodge=True, shields=True, aim=1.0, fire=1.0, pause_at=None,
               reaction=0.15, seed=0, end_hold=4.0, title_hold=2.5):
    """A whole game of Naves VI: JOGAR on the title, the fleet, the boss, the
    end screen, SPACE back to the title (the run is over there).

    ``dodge``: step aside from enemy shots about to hit; ``shields``: go for a
    falling shield when it can be reached; ``aim``: 1 leads the target by
    its speed, 0 shoots where it is (misses a moving boss); ``fire``: the
    share of the time it holds SPACE, in bursts; ``pause_at``: seconds into
    the game when P pauses it for a moment. Firing all the time clears the
    fleet before it shoots much: a careless pilot (no dodging, no shields,
    short bursts, slow eyes) loses its three lives: the game-over take.
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), next=0.0, target=None, dodge=None)
    name = act_name()
    if name == "Titulo":
        if m.get("over"):                      # back on the title: the run is over
            game.cursor = False
            game.hold()
            if t - m.setdefault("back", t) >= title_hold:
                game.done = True
            return
        menu_click(game, m, t, (500, 330), key="title")
        game.hold()
        return
    game.cursor = False
    if name == "FimDeJogo":
        m["over"] = True
        game.hold("SPACE" if at(t - m.setdefault("end", t), end_hold, 3) else None)
        return
    if name != "Fase":
        game.hold()
        return
    ns = game.ns
    keys = []
    k = t - m.setdefault("fase", t)
    if pause_at is not None and (at(k, pause_at, 3) or at(k, pause_at + 2.0, 3)):
        keys.append("P")
    heroes = list(ns["group"]["heroi"])
    if not heroes:                             # shot down: the end screen comes
        game.hold(*keys)
        return
    h = heroes[0]
    hx, hy = h.center.x, h.center.y
    rng = m["rng"]

    # 1. a shot about to hit: step aside (and keep going until clear); each
    # shot is noticed with the chance ``dodge`` (True = always)
    if dodge:
        seen = m.setdefault("noticed", {})
        live = {id(s): s for s in ns["group"]["tiros_inimigos"]}
        for k in [k for k in seen if k not in live]:
            del seen[k]
        for k in live:
            if k not in seen:
                seen[k] = rng.random() < float(dodge)
        danger = [s for k, s in live.items()
                  if seen[k] and 0 < s.center.y - hy < 300 and abs(s.center.x - hx) < 50]
        if danger:
            s = min(danger, key=lambda s: s.center.y)
            if m["dodge"] is None:
                away = hx - s.center.x or rng.choice((-1, 1))
                if hx < 120:
                    away = 1
                elif hx > 880:
                    away = -1
                m["dodge"] = "RIGHT" if away > 0 else "LEFT"
            game.hold(m["dodge"], "SPACE" if bursts(m, t, fire) else None, *keys)
            return
        m["dodge"] = None

    # 2. look again every ``reaction`` s: a shield in reach, or what to shoot
    if t >= m["next"]:
        m["next"] = t + reaction * (0.7 + 0.6 * rng.random())
        target = None
        if shields and ns["st"].energia == 0:
            for p in ns["group"]["poderes"]:
                dy = p.center.y - hy
                if 0 < dy < 400 and abs(p.center.x - hx) < 340 * dy / 150 + 30:
                    target = p.center.x
                    break
        if target is None:
            foes = list(ns["group"]["chefe"]) + list(ns["group"]["inimigos"])
            if foes:
                f = min(foes, key=lambda f: abs(f.center.x - hx))
                lead = velocity(m, f, t) * (f.center.y - hy) / 640 * aim
                target = min(940, max(60, f.center.x + lead))
        m["target"] = target
    for f in list(ns["group"]["chefe"]) + list(ns["group"]["inimigos"]):
        velocity(m, f, t)                       # keep every speed fresh
    target = m["target"]
    move = steer(m, target - hx, start=10, stop=3) if target is not None else None
    game.hold(move, "SPACE" if bursts(m, t, fire) else None, *keys)


# ── Avião III · Paisagem ────────────────────────────────────────────────────

def fly_plane(game, t, *, flights=(60.0,), crashes=("pillar",), wait=3.5, seed=0):
    """Flights through the gaps, each ``flights[i]`` seconds long and ended on
    purpose by ``crashes[i]``: "pillar" (flies into the next pillar) or
    "ground" (dives). After a crash the plane burns for ``wait`` s, then
    SPACE starts the next flight; after the last one the run is over.
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), flight=0, start=t, down=None, aim=None)
    ns = game.ns
    st, plane = ns["st"], ns["aviao"]
    i = m["flight"]
    if not st.voando:                           # crashed: burn, then SPACE
        down = m["down"] = m["down"] if m["down"] is not None else t
        if t - down >= wait:
            if i + 1 >= len(flights):
                game.done = True
                game.hold()
                return
            # The next flight starts now: SPACE restarts the game this frame,
            # and from the next frame on only the flying branch runs.
            m.update(flight=i + 1, start=t, down=None, aim=None, next=0.0, diving=False)
            game.hold("SPACE")
            return
        game.hold()
        return
    crash = (t - m["start"]) >= flights[i]
    kind = crashes[i % len(crashes)]
    x, y = plane.center.x, plane.center.y
    doors = [d for d in ns["group"]["porta"] if d.center.x > x - 10]
    if crash and kind == "ground":
        # Dive just after a gap, with open air below: under a pillar the dive
        # would end on the pillar, not on the ground.
        ahead = min((d.center.x for d in doors), default=x + 999) - x
        if m.get("diving") or ahead > 180:
            m["diving"] = True
            game.hold("DOWN")
            return
        crash = False                           # fly on to the next gap first
    if t >= m.get("next", 0.0):
        m["next"] = t + 0.12 * (0.7 + 0.6 * m["rng"].random())
        if doors:
            gap = min(doors, key=lambda d: d.center.x).center.y
            # into the pillar: aim above the gap, where the top pillar is
            m["aim"] = gap + 110 if crash else gap
        else:
            m["aim"] = 200 if not crash else m["aim"]
    aim = m["aim"] if m["aim"] is not None else 200
    game.hold(steer(m, aim - y, start=12, stop=5, keys=("DOWN", "UP")))


PILOTS = {f.__name__: f for f in (catch_falling, tour_first_script, play_naves, fly_plane)}
