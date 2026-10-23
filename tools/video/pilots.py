"""Video pilots: they play a whole run, not a few seconds of a clip.

A pilot is ``(game, t, **args)``, called once per game frame (60 Hz) before the
frame steps; ``game`` is the README tool's ``Pilot`` (``hold(*keys)``,
``mouse(x, y)``, ``press()`` / ``release()``, ``game.ns`` the program's
globals; design units, y up). ``args`` come from the take (``takes.py``), so
one pilot plays several variations of a run. Two flags tell the recorder:

  game.cursor = True    draw the pointer (a window has none to capture)
  game.done = True      the run is over; the take ends after its tail
  game.still = True     this screen stands still on purpose (a results screen
                        to read): the review does not flag it as a stall

Play like a player, not like a bot: re-aim a few times a second (a reaction
time), start a key past a threshold and let go inside a smaller one (no
key flutter), and miss now and then when the take asks for it. A pilot keeps
what it remembers between frames in ``memo(game)``.
"""
from __future__ import annotations

import math
import random


def memo(game) -> dict:
    """The pilot's memory for this run."""
    m = getattr(game, "_memo", None)
    if m is None:
        m = game._memo = {}
    return m


def at(t: float, when: float, frames: int = 1) -> bool:
    """``t`` is one of the ``frames`` game frames that start at ``when``.

    Counted in whole frames: a time measured from a screen's first frame
    (``t - start``) carries float error, and a test on seconds could fall
    just short on one frame and just past the window on the next (a click
    that never happened)."""
    n, w = round(t * 60), round(when * 60)
    return w <= n < w + frames


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

def current_act():
    """The act on stage (``None`` before the first)."""
    import sys
    return sys.modules["scena.act"]._manager.current


def act_name() -> str:
    """The class name of the act on stage (``""`` before the first)."""
    act = current_act()
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


# ── Corrida ─────────────────────────────────────────────────────────────────

_PLAYERS_BUTTON = {1: (640, 380), 2: (640, 280)}
_TRACK_BUTTON = {"SERPENTINA": (340, 170), "RELÂMPAGO": (940, 170)}


def race(game, t, *, players=1, track="SERPENTINA", seed=0, result_hold=5.0, title_hold=2.0):
    """A whole race of Corrida: the players button, the track button (pointer
    in view), the countdown, three laps, the results, SPACE back to the
    opening (the run is over there).

    Each human car is driven by the game's own CPU brain (``Carro.pensar``)
    turned into its keys: what the brain wants this frame is what the pilot
    holds. The wheel is proportional in the brain and a key is all or
    nothing, so a partial turn is a key held that share of the frames.
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), wheel={})
    name = act_name()
    if name == "Escolha":
        if m.get("over"):
            game.cursor = False
            game.hold()
            if t - m.setdefault("back", t) >= title_hold:
                game.done = True
            return
        menu_click(game, m, t, _PLAYERS_BUTTON[players], key="players", rest=(1000, 110))
        game.hold()
        return
    if name == "EscolhaPista":
        menu_click(game, m, t, _TRACK_BUTTON[track], key="track", wait=0.9,
                   rest=_PLAYERS_BUTTON[players])
        game.hold()
        return
    game.cursor = False
    game.still = name == "Resultado"           # the podium holds still on purpose
    if name == "Resultado":
        m["over"] = True
        game.hold("SPACE" if at(t - m.setdefault("end", t), result_hold, 3) else None)
        return
    if name != "Corrida" or not game.ns["st"].largou:
        game.hold()
        return
    act = current_act()
    keys = []
    for car in [act.azul] + ([act.vermelho] if players == 2 else []):
        if not car.is_alive or car.chegou:
            continue
        k = car.teclas
        car.pensar(1 / 60)
        acc = m["wheel"].get(car.nome, 0.0) + min(1.0, abs(car.vira))
        if acc >= 1.0:
            acc -= 1.0
            keys.append(k["esquerda"] if car.vira > 0 else k["direita"])
        m["wheel"][car.nome] = acc
        keys += [k["acelera"] if car.acelera else None, k["freia"] if car.freia else None,
                 k["tiro"] if car.quer_atirar else None]
    game.hold(*keys)


# ── Corredor ────────────────────────────────────────────────────────────────

_JUMP_VY, _GRAVITY = 900.0, 2200.0      # corredor.py: a jump and its fall (px/s, px/s²)


def _robot_jump_is_safe(ns, robo, v: float) -> bool:
    """A jump taken now lands on ground, clear of crates, and no crate is in
    the way of the arc (the game's own jump speed and gravity, the speed
    ``v`` held for the whole jump)."""
    query, altura = ns["collision"].query_point, ns["altura"]
    body = robo.hitbox.box                      # what collides (42 px), not the picture (90)
    back, front, y0 = body.left, body.right, body.bottom

    def height(t):
        return y0 + _JUMP_VY * t - _GRAVITY / 2 * t * t

    # landing: the first time after the peak the feet reach the ground under them
    t = _JUMP_VY / _GRAVITY
    while t < 2.0:
        t += 1 / 120
        mid = (back + front) / 2 + v * t
        if height(t) <= altura(mid):
            break
    land = t
    lb, lf = back + v * land, front + v * land
    for k in range(9):
        x = lb + (lf - lb) * k / 8
        if not query((x, altura(x) - 8), group="chao"):
            return False
    for b in ns["group"]["caixa"]:
        cl, cr, top = b.box.left, b.box.right, b.box.top
        if cr < back:
            continue
        if cl < lf + 30 and cr > lb - 10:       # lands on it, or right in front of it
            return False
        t0 = max(0.0, (cl - front) / v)        # over the crate between t0 and t1
        t1 = min(land, (cr - back) / v)
        for k in range(7):
            tt = t0 + (t1 - t0) * k / 6
            if t0 <= t1 and height(tt) < top + 4:
                return False
    return True


def run_robot(game, t, *, runs=(45.0,), ends=("crate",), wait=2.5, seed=0, eager=0.0):
    """Runs of the robot, each ``runs[i]`` seconds and then ended on purpose
    by ``ends[i]``: "crate" (runs into the next crate) or "hole" (falls into
    the next hole); it keeps jumping the other kind until its own comes. After
    a fall, ``wait`` s on "Aperte espaço", then SPACE starts the next run (the
    record grows); after the last one the run is over.

    It plays like a good player who reads ahead: with a hole or a crate
    coming, it jumps at the first moment the landing is safe (on ground,
    clear of crates: a crate right after a hole, or a hole right after a
    crate, needs the jump early), and only jumps blind at the last moment.
    ``eager`` (0–1): the chance per frame of jumping at once in the safe
    window instead of a few frames into it (a hurried player).
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), run=0, start=t, down=None, delay=None)
    ns = game.ns
    st = ns["st"]
    act = current_act()
    if act_name() != "Corrida":
        game.hold()
        return
    i = m["run"]
    if not st.correndo:
        down = m["down"] = m["down"] if m["down"] is not None else t
        if t - down >= wait:
            if i + 1 >= len(runs):
                game.done = True
                game.hold()
                return
            # The next run starts this frame (SPACE changes the act at once).
            m.update(run=i + 1, start=t, down=None, delay=None)
            game.hold("SPACE")
            return
        game.hold()
        return
    robo = act.robo
    if "bottom" not in robo.touching_sides:
        game.hold()
        return
    ending = (t - m["start"]) >= runs[i]
    end_kind = ends[i % len(ends)]
    c, v = robo.center.x, st.velocidade
    query, altura = ns["collision"].query_point, ns["altura"]
    hole = None                                 # px from the robot's middle
    for d in range(0, int(v * 0.6) + 60, 4):
        x = c + d
        if not query((x, altura(x) - 8), group="chao"):
            hole = d
            break
    body = robo.hitbox.box
    c = body.center.x
    crates = [b.box.left - body.right for b in ns["group"]["caixa"] if b.box.right > body.left]
    crate = min(crates) if crates else None
    skip = {"hole": ending and end_kind == "hole", "crate": ending and end_kind == "crate"}
    near_hole = hole is not None and hole <= v * 0.5 and not skip["hole"]
    near_crate = crate is not None and crate <= 140 and not skip["crate"]
    last = (hole is not None and hole <= 16 and not skip["hole"]) or \
           (crate is not None and crate <= 14 and not skip["crate"])
    jump = False
    if last:
        jump = True
    elif (near_hole or near_crate) and _robot_jump_is_safe(ns, robo, v):
        if m["delay"] is None:                  # a few frames into the window, like a player
            m["delay"] = 0 if m["rng"].random() < eager else m["rng"].randint(0, 4)
        m["delay"] -= 1
        jump = m["delay"] < 0
    else:
        m["delay"] = None
    if jump:
        m["delay"] = None
    game.hold("UP" if jump else None)


# ── Ligue 4 ─────────────────────────────────────────────────────────────────

# Moves are columns (0-6), red first; each game ends in the named win.
CONNECT4_GAMES = {
    "red_row": (3, 3, 4, 4, 2, 5, 1),                      # red: bottom row 1-4
    "blue_column": (0, 6, 1, 6, 0, 6, 5, 6),               # blue: four up column 6
    "red_diagonal": (0, 1, 1, 2, 3, 2, 2, 3, 4, 3, 3),     # red: (0,0) (1,1) (2,2) (3,3)
}


def play_connect4(game, t, *, games=("red_row", "blue_column", "red_diagonal"), seed=0,
                  think=(0.4, 1.2), hesitate=0.25, misdrop=None, win_hold=3.0, end_hold=3.5):
    """Games of Ligue 4, one after another, each to its win (``CONNECT4_GAMES``):
    grab the waiting ball, carry it over the column, let go; after a win the
    board glows ``win_hold`` s and the pointer clicks "Novo jogo".

    ``think``: seconds before a move (random in the range); ``hesitate``: the
    chance a move first hovers over a neighbour column; ``misdrop``: (game,
    move) where the ball is let go off the board and slides back, once.
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed), g=0, move=0, phase="wait", t0=t, path=None,
                 misdropped=False)
    rng = m["rng"]
    ns = game.ns
    st, ball, start = ns["st"], ns["proxima"], ns["INICIO"]
    game.cursor = True
    game.hold()
    moves = CONNECT4_GAMES[games[m["g"]]]
    k = t - m["t0"]

    def above(col):
        # The top cell of the column: the game reads the column from the cell
        # under the drop, so a point above the board is a drop off it.
        c = ns["grade"].cell(col, 0).center
        return c.x, c.y

    if m["phase"] == "wait":                     # the next ball is up: think, then grab
        if st.fim:
            m.update(phase="won", t0=t)
            return
        if m["move"] >= len(moves) or not ball.visible:
            return
        if "pause" not in m:
            m["pause"] = rng.uniform(*think)
        if k < m["pause"]:
            return
        col = moves[m["move"]]
        keys = [(0.0, start)]
        if rng.random() < hesitate:              # over a neighbour first
            other = col + rng.choice((-1, 1)) if 0 < col < 6 else (1 if col == 0 else 5)
            keys += [(0.45, above(other)), (0.75, above(other))]
        drop = above(col)
        if misdrop == (m["g"], m["move"]) and not m["misdropped"]:
            drop = (drop[0], drop[1] + 260)      # off the board: the ball slides back
            m["misdropped"] = True
            m["redo"] = True
        keys.append((keys[-1][0] + 0.45, drop))
        m.update(phase="drag", t0=t, path=keys)
        m.pop("pause", None)
        game.mouse(*start)
        game.press()
        return
    if m["phase"] == "drag":
        game.mouse(*path_point(m["path"], k))
        if k >= m["path"][-1][0] + 0.1:
            game.release()
            if m.pop("redo", False):
                m.update(phase="wait", t0=t + 0.4)
            else:
                m.update(phase="wait", t0=t, move=m["move"] + 1)
        return
    if m["phase"] == "won":                      # glow, then "Novo jogo" (or the end)
        if m["g"] + 1 >= len(games):
            game.done = k >= end_hold
            return
        if k < win_hold:
            return
        button = game.run.widget_center("Novo jogo")
        game.mouse(*path_point([(0, game._at), (0.6, button)], k - win_hold))
        if at(k, win_hold + 0.8):
            game.press()
        if at(k, win_hold + 0.9):
            game.release()
        if k >= win_hold + 1.2:
            m.update(phase="wait", t0=t, g=m["g"] + 1, move=0)


# ── Duelo ───────────────────────────────────────────────────────────────────

def _duel_side(game, m, t, me, other, side, *, skill, rng):
    """One ship's keys this frame: wander on the rail, step aside from a laser
    coming at it, aim at the other ship (or a star, now and then) with an
    error that sweeps, and fire when the aim is close."""
    ns = game.ns
    s = m.setdefault(side, {"rng": random.Random(rng.random()), "goal": 0.5, "next_goal": 0.0,
                            "phase": rng.uniform(0, 6.28)})
    k = me.teclas
    keys = []
    # 1. a laser coming: slide along the rail to the side farther from its line
    threat = None
    for shot in ns["group"]["tiros"]:
        if getattr(shot, "dono", None) is me or shot.vel.length < 1:
            continue
        v = shot.vel
        rx, ry = me.center.x - shot.center.x, me.center.y - shot.center.y
        along = (rx * v.x + ry * v.y) / v.length
        side_off = abs(rx * v.y - ry * v.x) / v.length
        if 0 < along < 420 and side_off < 48:
            threat = shot
            break
    if threat is not None and s["rng"].random() < 0.6 + 0.4 * skill:
        v = threat.vel

        def miss(u):
            p = me.trilho.at(min(1, max(0, u)))
            rx, ry = p[0] - threat.center.x, p[1] - threat.center.y
            return abs(rx * v.y - ry * v.x) / v.length

        keys.append(k["cima"] if miss(me.u + 0.12) > miss(me.u - 0.12) else k["baixo"])
    else:                                        # 2. wander to a goal on the rail
        if t >= s["next_goal"]:
            s["goal"] = s["rng"].uniform(0.1, 0.9)
            s["next_goal"] = t + s["rng"].uniform(1.5, 3.5)
        keys.append(steer(s, (s["goal"] - me.u) * 400, start=20, stop=6,
                          keys=(k["baixo"], k["cima"])))
    # 3. aim (the other ship, or a star now and then) and fire when close
    stars = list(ns["group"]["alvo"])
    target = other
    if stars and s.get("hunt", False):
        target = stars[0]
    if t >= s.get("next_hunt", 0.0):
        s["hunt"] = s["rng"].random() < 0.4
        s["next_hunt"] = t + 3.0
    sweep = (6 + 30 * (1 - skill)) * math.sin(t * 1.7 + s["phase"])
    want = ns["heading"](me, target) + sweep
    err = (want - me.angle + 180) % 360 - 180
    turn = {"_steer": s.get("_turn")}
    keys.append(steer(turn, err, start=8, stop=3, keys=(k["direita"], k["esquerda"])))
    s["_turn"] = turn["_steer"]
    if abs(err) < 14 and bursts(s, t, 0.45 + 0.5 * skill):
        keys.append(k["tiro"])
    return keys


def duel_match(game, t, *, ships=(1, 2), skill=(0.8, 0.8), seed=0, victory_hold=4.0,
               title_hold=2.0):
    """A whole Duelo match: on the choice screen each player browses the two
    ships and confirms ``ships`` (blue, red); the match to its end; the
    victory screen; SPACE back to the choice (the run is over there).

    ``skill`` (blue, red), 0-1: a steadier aim (smaller sweep), more firing,
    more dodging. The side with more skill usually wins.
    """
    m = memo(game)
    if "rng" not in m:
        m.update(rng=random.Random(seed))
    name = act_name()
    game.cursor = False
    if name == "Escolha":
        if m.get("over"):
            game.hold()
            if t - m.setdefault("back", t) >= title_hold:
                game.done = True
            return
        k = t - m.setdefault("choice", t)
        taps = [(0.8, "D"), (1.0, "RIGHT"), (1.4, "A"), (1.6, "LEFT")]
        if ships[0] == 2:
            taps.append((2.0, "D"))
        if ships[1] == 2:
            taps.append((2.2, "RIGHT"))
        taps += [(2.8, "TAB"), (3.3, "ENTER")]
        game.hold(*[key for when, key in taps if at(k, when, 3)])
        return
    if name == "Vitoria":
        m["over"] = True
        game.hold("SPACE" if at(t - m.setdefault("end", t), victory_hold, 3) else None)
        return
    if name != "Duelo":
        game.hold()
        return
    act = current_act()
    blue, red = act.azul, act.vermelha
    if not (blue.is_alive and red.is_alive):     # the explosion, then the victory screen
        game.hold()
        return
    keys = _duel_side(game, m, t, blue, red, "blue", skill=skill[0], rng=m["rng"])
    keys += _duel_side(game, m, t, red, blue, "red", skill=skill[1], rng=m["rng"])
    game.hold(*keys)


# ── Ninja V · Espada ────────────────────────────────────────────────────────

# A route is a list of steps the ninja does in order; each one ends on its
# own condition (``_ninja_step``). Places are world points of
# ``levels/ninja_perigos.json`` (ground top y = 80; x 0-4000).
#   ("to", x)          run until the middle is at x
#   ("jump", dir[, x]) jump, holding dir ("LEFT" / "RIGHT" / None) until landed
#                      (or until past x, then straight down)
#   ("drop",)          DOWN through the platform underfoot, until landed
#   ("land",)          wait until standing (after running off an edge)
#   ("hit", dir)       face dir, SPACE once: the sword by a crate, else a kunai
#   ("clear", dir)     kunai at every robot ahead (same level, 520 px) until none
#   ("barrier", x[, "on"]) wait until the barrier at x has just switched off
#                      (or on)
#   ("lose", dir)      walk that way until a life is lost (a pit, a robot, a shock)
#   ("wait", s)        stand still s seconds
#   ("lift", top)      wait until the elevator's top is at or below top
#   ("ride", y)        stand still until the feet are above y (the elevator)
NINJA_ROUTE = (
    ("wait", 2.6),                               # the level overview, then the zoom
    ("to", 168), ("hit", "RIGHT"), ("wait", 0.5),  # the sword breaks the crate
    ("to", 240), ("wait", 0.3),                  # the gold light: invincible
    ("to", 300), ("jump", None),                 # onto the low platform (y 220)
    ("to", 360), ("jump", None),                 # star (360, 300)
    ("to", 470), ("jump", "RIGHT"),              # onto the mid platform (y 390)
    ("clear", "RIGHT"),
    ("to", 720), ("jump", None),                 # star (720, 470)
    ("to", 610), ("jump", "LEFT"),               # onto the high platform (y 560)
    ("to", 420), ("jump", None),                 # star (420, 640)
    ("to", 330), ("drop",), ("drop",),           # down to the ground
    ("to", 440), ("jump", "RIGHT"),              # over the first pit; star (560, 220)
    ("clear", "RIGHT"),                          # the ground robots
    ("to", 960),                                 # star (960, 150)
    # The ramp (three pieces tilted 15°) only holds a landing from above: it
    # is reached from the mid platform, so back over the pit and up again.
    ("to", 655), ("jump", "LEFT"),               # back over the first pit
    ("to", 300), ("jump", None),                 # onto the low platform
    ("to", 470), ("jump", "RIGHT"),              # onto the mid platform
    ("to", 832), ("jump", "RIGHT"),              # down onto the ramp
    ("to", 1100),                                # star (1100, 330)
    ("to", 1228), ("jump", "RIGHT"),             # long jump over the barrier, onto the
                                                 # platform above the second pit
    ("to", 1530), ("hit", "RIGHT"), ("wait", 0.4),
    ("to", 1600),                                # the sword, the light: invincible
    # The high platforms (y 420, y 250) only hold a landing from above:
    # from here, before going down.
    ("to", 1660), ("jump", "RIGHT", 1800),       # onto the high platform (y 420)
    ("to", 1900),                                # star (1900, 500)
    ("to", 2010), ("jump", "RIGHT", 2110),       # down onto the robot's platform (y 250)
    ("clear", "RIGHT"),
    ("to", 2200),                                # star (2200, 330)
    ("to", 2240), ("drop",),                     # down to the ground
    ("clear", "RIGHT"), ("clear", "LEFT"),       # the ground robot, either side
    ("to", 1662), ("jump", "LEFT"),              # back over the second pit (coyote
    ("to", 1468), ("jump", "RIGHT"),             # time) and over again: star (1560, 220)
    ("to", 2290), ("barrier", 2350), ("to", 2465),
    ("jump", "RIGHT", 2530),                     # onto the platform over the third pit
    ("to", 2640),                                # star (2640, 300)
    ("to", 2775), ("land",),                     # off its end, to the ground
    ("to", 2895), ("hit", "RIGHT"), ("wait", 0.4),
    ("to", 2960),                                # the third crate, the light
    ("to", 2815), ("jump", "LEFT", 2745),        # back up on the pit's platform
    ("to", 2780), ("jump", "RIGHT"),             # from its very edge to the robot's
                                                 # platform (y 300)
    ("clear", "RIGHT"),
    ("to", 3100),                                # star (3100, 380)
    ("to", 3150), ("barrier", 3200),             # the barrier crosses this platform's end
    ("to", 3205), ("jump", "RIGHT"),             # onto the platform (y 470)
    ("to", 3400),                                # star (3400, 550)
    ("to", 3500), ("jump", "RIGHT", 3600),       # down onto the platform (y 260)
    ("clear", "RIGHT"),
    ("to", 3815), ("drop",),                     # down to the ground
    ("to", 3940), ("jump", None),                # star (3940, 200)
    ("lift", 230), ("jump", None),               # onto the elevator near its bottom
    ("ride", 540), ("wait", 1.0),                # star (3900, 640) at the top
)


# Three lives lost the three ways, then "Fim de jogo" (the pilot presses R).
NINJA_MISHAPS = (
    ("wait", 2.6),
    ("to", 160), ("jump", "RIGHT"),              # over the crate (its light would make
    ("wait", 0.4),                               # the ninja invincible: no losses)
    ("lose", "RIGHT"), ("land",),                # off the low platform into the first
                                                 # pit: back at the start
    ("to", 160), ("jump", "RIGHT"),
    ("to", 440), ("drop",),                      # to the ground (from the platform the
    ("jump", "RIGHT"),                           # jump meets the robot above); over the pit
    ("wait", 0.5), ("lose", "RIGHT"),            # into the ground robot
    ("wait", 1.6), ("clear", "RIGHT"),           # (blinking) then the kunai
    ("to", 1290), ("barrier", 1350, "on"),
    ("lose", "RIGHT"),                           # into the barrier: the shock
)


def _ninja_hero():
    act = current_act()
    return getattr(act, "heroi", None) if act is not None else None


def _ninja_step(game, m, t, hero, step):
    """Keys for one route step this frame and whether the step is done."""
    ns = game.ns
    kind = step[0]
    x = hero.center.x
    feet = hero.hitbox.box.bottom
    on_ground = "bottom" in hero.touching_sides
    k = t - m["step_t"]
    if kind == "wait":
        return [], k >= step[1]
    if kind == "to":
        d = step[1] - x
        if abs(d) <= 6:
            return [], True
        return ["RIGHT" if d > 0 else "LEFT"], False
    if kind == "jump":
        held = [step[1]] if step[1] else []
        if len(step) > 2:                       # let go of the direction past x
            sign = 1 if step[1] == "RIGHT" else -1
            if (x - step[2]) * sign >= 0:
                held = []
        if k < 3 / 60:
            return held + ["UP"], False
        return held, k > 0.2 and on_ground
    if kind == "lift":                           # wait until the elevator is low
        lift = max(ns["group"]["plataforma"], key=lambda p: p.box.width)
        return [], lift.box.top <= step[1]
    if kind == "land":                           # walked off an edge: wait to stand
        return [], k > 0.1 and on_ground
    if kind == "drop":
        if k < 3 / 60:
            return ["DOWN"], False
        return [], k > 0.25 and on_ground
    if kind == "hit":
        if k < 2 / 60:
            return [step[1]], False                 # face that way (a tap)
        if k < 4 / 60:
            return ["SPACE"], False
        return [], k > 0.35
    if kind == "clear":
        sign = 1 if step[1] == "RIGHT" else -1
        ahead = [r for r in ns["group"]["robo"]
                 if 0 < (r.center.x - x) * sign < 520 and abs(r.hitbox.box.bottom - feet) < 40]
        if not ahead:
            return [], k > 0.3
        face = [step[1]] if hero.flip_x == (sign > 0) else []
        # "When due", not "on that frame": the time is left over from the
        # last clear step, long past by the next one.
        fire = ["SPACE"] if not face and t >= m.get("next_throw", 0.0) else []
        if fire:
            m["next_throw"] = t + 0.45
        return face + fire, False
    if kind == "barrier":
        bar = min(ns["group"]["raio"], key=lambda b: abs(b.center.x - step[1]))
        on = len(step) > 2 and step[2] == "on"
        was = m.get("bar_was")
        m["bar_was"] = bar.active
        return [], was is (not on) and bar.active is on
    if kind == "lose":                           # walk on until a life is lost
        lives = m.setdefault("lives0", ns["st"].vidas)
        return [step[1]], ns["st"].vidas < lives
    if kind == "ride":
        return [], on_ground and feet >= step[1]
    raise ValueError(f"unknown ninja step {step!r}")


def ninja_route(game, t, *, route="full", end_hold=4.0, restart=False):
    """Ninja V along a scripted route (``"full"``: ``NINJA_ROUTE``, every
    star, robot and crate; ``"mishaps"``: ``NINJA_MISHAPS``): the steps run in
    order, each to its own end. After the last step the run is over
    (``end_hold`` s later). A route that loses the last life ends on "Fim de
    jogo"; with ``restart`` the pilot presses R there and the run is over
    once the level is back."""
    m = memo(game)
    if "i" not in m:
        m.update(i=0, step_t=t)
    route = {"full": NINJA_ROUTE, "mishaps": NINJA_MISHAPS}.get(route, route)
    hero = _ninja_hero()
    st = game.ns["st"]
    if hero is None:
        game.hold()
        return
    if st.vidas == 0:                            # game over
        k = t - m.setdefault("over", t)
        if restart and at(k, 2.5, 3):
            game.hold("R")
            m["restarted"] = t
            return
        game.hold()
        if (not restart and k >= end_hold) or ("restarted" in m and t - m["restarted"] >= end_hold):
            game.done = True
        return
    if "restarted" in m:                         # the level is back: hold, then end
        game.hold()
        if t - m["restarted"] >= end_hold:
            game.done = True
        return
    if m["i"] >= len(route):
        game.hold()
        if t - m.setdefault("end", t) >= end_hold:
            game.done = True
        return
    keys, done = _ninja_step(game, m, t, hero, route[m["i"]])
    if done:
        m["i"] += 1
        m["step_t"] = t
        m.pop("bar_was", None)
        m.pop("lives0", None)
    game.hold(*keys)


# ── Demos: a tour of the controls ───────────────────────────────────────────

def slider_tour(game, t, *, drags=(), keys=(), end=30.0):
    """The pointer drags sliders and keys are tapped, on a timetable:
    ``drags``: (label, from, to, start, end) each; the pointer glides to the
    handle in the 0.8 s before ``start``, presses, drags, lets go.
    ``keys``: (time, key) taps. The run is over at ``end``."""
    m = memo(game)
    game.cursor = True
    for label, a, b, start, stop in drags:
        if start - 0.9 <= t < start:            # glide to the handle
            frm = m.setdefault(("from", start), game._at)
            to = game.slider_point(label, a)
            game.mouse(*path_point([(start - 0.9, frm), (start - 0.1, to)], t))
        elif start <= t <= stop:                 # drag
            k = (t - start) / (stop - start)
            game.mouse(*game.slider_point(label, a + (b - a) * k))
            if at(t, start):
                game.press()
        if at(t, stop + 1 / 60):
            game.release()
    game.hold(*[key for when, key in keys if at(t, when, 3)])
    if t >= end:
        game.done = True


def _target(game, target):
    """A point (design units) for a tour target: ``(x, y)``; ``("w", x, y)``
    (a world point of the level editor, through its camera); ``"@name"`` (a
    global's centre); ``"middle:group"`` / ``"first:group"`` (a group's mean
    centre / first member); ``"dropdown"`` (the DropDown's box);
    ``"option:text"`` (a row of the open DropDown); else a widget label (or an
    open Menu's option)."""
    if isinstance(target, tuple) and target[0] == "w":   # a world point of the editor
        from scena_editor.view import view_point
        return view_point(target[1], target[2])
    if isinstance(target, tuple):
        return target
    ns = game.ns
    if target.startswith("@"):
        c = ns[target[1:]].center
        return c.x, c.y
    if target.startswith(("middle:", "first:")):
        kind, name = target.split(":", 1)
        items = list(ns["group"][name])
        if kind == "first":
            return items[0].center.x, items[0].center.y
        return (sum(i.center.x for i in items) / len(items),
                sum(i.center.y for i in items) / len(items))
    if target == "dropdown" or target.startswith("option:"):
        from scena.uiwidget import DropDown
        dd = next(w for w in game.run.world.fw.widget_manager.widgets
                  if isinstance(w, DropDown) and getattr(w, "active", True))
        if target == "dropdown":
            return (dd._x1 + dd._x2) / 2, (dd._y1 + dd._y2) / 2
        i = dd.options.index(target.split(":", 1)[1])
        return (dd._x1 + dd._x2) / 2, dd._row_y(i) + dd._option_height / 2
    return game.run.widget_center(target)


def _path(kind, params, t, start):
    """Where a pointer path is at ``t`` (``"orbit"``, ``"eight"``)."""
    cx, cy, rx, ry, rate = params
    a = (t - start) * rate * 2 * math.pi
    if kind == "orbit":
        return cx + rx * math.cos(a), cy + ry * math.sin(a)
    if kind == "eight":
        return cx + rx * math.sin(a), cy + ry * math.sin(2 * a)
    raise ValueError(f"unknown path {kind!r}")


def tour(game, t, *, script=(), end=30.0, glide=0.8):
    """A tour of a program's controls on a timetable (``script``), the
    pointer in view. Events:

      ("drag", label, a, b, start, stop)   a Slider from a to b
      ("click", time, target)              a press and release on a target
      ("path", start, stop, kind, (cx, cy, rx, ry, rate))  the pointer moves
                                           ("orbit" / "eight"; rate: turns/s)
      ("glide", start, stop, target)       the pointer moves there
      ("press", start, stop)               the button held (wherever it is)
      ("rpress", start, stop)              the right button held
      ("carry", start, stop, target, (x, y))  grab a target, carry it there
      ("key", time, key) / ("hold", start, stop, key)
      ("scroll", time, dy)                 the wheel

    Before a click or a drag the pointer glides to it in ``glide`` s. The
    button goes down and up on the frames these say (one press per window).
    """
    m = memo(game)
    game.cursor = True
    point, held_at, down, rdown, keys = None, None, False, False, []
    for ev in script:
        kind = ev[0]
        if kind == "path" and ev[1] <= t <= ev[2]:
            point = _path(ev[3], ev[4], t, ev[1])
        elif kind == "glide" and ev[1] <= t <= ev[2]:
            frm = m.setdefault(("glide", ev[1]), game._at)
            point = path_point([(ev[1], frm), (ev[2], _target(game, ev[3]))], t)
        elif kind == "click":
            when = ev[1]
            if when - glide <= t < when:
                frm = m.setdefault(("click", when), game._at)
                point = path_point([(when - glide, frm), (when - 0.1, _target(game, ev[2]))], t)
            elif when <= t < when + 0.1:
                held_at = m.setdefault(("clicked", when), _target(game, ev[2]))
                down = True
        elif kind == "drag":
            _, label, a, b, start, stop = ev
            if start - glide <= t < start:
                frm = m.setdefault(("drag", start), game._at)
                point = path_point([(start - glide, frm),
                                    (start - 0.1, game.slider_point(label, a))], t)
            elif start <= t <= stop:
                k = (t - start) / (stop - start)
                held_at = game.slider_point(label, a + (b - a) * k)
                down = True
        elif kind == "carry":                    # grab a (moving) target, carry it
            _, start, stop, target, to = ev
            if start - glide <= t < start:
                frm = m.setdefault(("carry", start), game._at)
                point = path_point([(start - glide, frm), (start - 0.05, _target(game, target))], t)
            elif start <= t <= stop:
                grab = m.setdefault(("grabbed", start), _target(game, target))
                held_at = path_point([(start, grab), (stop, _target(game, to))], t)
                down = True
        elif kind == "press" and ev[1] <= t < ev[2]:
            down = True
        elif kind == "rpress" and ev[1] <= t < ev[2]:
            rdown = True
        elif kind == "key" and at(t, ev[1], 3):
            keys.append(ev[2])
        elif kind == "hold" and ev[1] <= t < ev[2]:
            keys.append(ev[3])
        elif kind == "scroll" and at(t, ev[1]):
            game.run.scroll(0, ev[2])
    # A pressed click, drag or carry owns the pointer: the next event's glide
    # (which may start before this press ends) must not pull it off the button.
    point = held_at if held_at is not None else point
    if not down and m.get("down"):
        point = m["held_at"]                     # let go where it was held (a band
    if down:                                     # select ends at the release point)
        m["held_at"] = point if point is not None else game._at
    if point is not None:
        game.mouse(*point)
    if down and not m.get("down"):
        game.press()
    elif not down and m.get("down"):
        game.release()
    m["down"] = down
    if rdown and not m.get("rdown"):
        game.run.press(*game._at, "right")
    elif not rdown and m.get("rdown"):
        game.run.release("right")
    m["rdown"] = rdown
    game.hold(*keys)
    if t >= end:
        game.done = True


# ── Debug keys over a run ───────────────────────────────────────────────────

def with_debug_keys(game, t, *, pilot, args=None, chords=()):
    """Another pilot's run, with Ctrl+Shift chords at set times: ``chords`` is
    ``(time, key)`` each ("7" hitboxes and overlays, "6" processes, "8" debug
    zoom). The modifiers go down a moment before the key and come up after
    it: keys pressed in one frame arrive in name order, and a "7" before its
    Ctrl and Shift is a plain 7."""
    from record_game import load_pilot
    fly = memo(game).setdefault("_base", load_pilot(pilot))
    extra = []
    for when, key in chords:
        if when - 0.1 <= t < when + 0.25:
            extra += ["LEFT_CTRL", "LEFT_SHIFT"]
        if at(t, when, 3):
            extra.append(key)
    hold = game.hold
    called = []

    def hold_too(*keys):
        called.append(True)
        hold(*keys, *extra)

    game.hold = hold_too
    try:
        fly(game, t, **(args or {}))
    finally:
        game.hold = hold
    if not called:                   # a pilot that holds no keys (watch): the chord alone
        hold(*extra)


PILOTS = {f.__name__: f for f in (catch_falling, tour_first_script, play_naves, fly_plane,
                                  race, run_robot, play_connect4, duel_match, ninja_route,
                                  slider_tour, tour, with_debug_keys)}
