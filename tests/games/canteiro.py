# harness: cwd=examples/media
"""Canteiro — a game system test (tests/games/). Not an example, not a tutorial.

A building site: a physics-style world (a ramp, a lift that slides across a
pit, a lift that climbs a shaft, stacks on thin STATIC shelves, overlapping
bubbles, a brick box with a bouncing ball, a turret and its targets, parcels
falling through a scale) played with held keys, drags and HUD widgets under a
camera that chases the hero, zooms with a Slider and may turn. Checked while
it runs by side models (tests/game_support.py) and by the driver
(tests/game_harness.py, tests/test_game_canteiro*.py). Strategy:
design/Testing Design.md, "Game system tests".

It keeps the game-behaviour campaign's seams covered (Testing Design, "PG"):
riders carried by a sideways and a descending lift (PB2, PB4), an idle body on
a slope (PE2), overlapping bodies moving apart (PE1), STATIC shelves under a
stack and under a heavy ball (PE3, PE4), a ball bouncing off bricks its own
handler destroys (PE5), two enter rules on one contact in both spawn orders
(PB5), an exit after an untag (PB1), two exit rules where the first destroys
(PB3), a closure over ``self`` owned by its actor (PA4), a held Button
destroyed (PD1), presses a widget takes hidden from ``mouse.press`` (PD2), an
Enter repeat after the focus moved (PD3), widget hover when the cursor leaves
the window (PD4), drags across the ui and world spaces (PD5), Shift held while
running and jumping (PD6), a key held across ``change_act`` (PD7), the world
pointer under a moving camera, read once per frame (PC8), ``clone(center=)``
(PC1) and ``x, y = mouse`` (PB6).

The pilot tells the game where it put the cursor and what it pressed
(``CURSOR``): that is the truth the pointer models compare ``mouse`` with.

PARAMS: giro (camera turn amplitude, degrees), lift_speed, rounds, ramp_angle.
Controls (the pilot drives them): LEFT / RIGHT walk, SHIFT runs, SPACE jumps;
the HUD: the Zoom slider, the Jato button (hold), the crate icon (drag onto
the plot), the trash (drop a crate on it), the Nome / Nota boxes.
"""
import math

from scena import *
from game_support import (ChangeModel, Ledger, TimerModel, geom)

PARAMS = globals().get("PARAMS", {})
G = Ledger("canteiro", mark=globals().get("mark"))
TIMERS = G.model(TimerModel())

W, H = 1000, 600
init(width=W, height=H, title="Canteiro")

GRAVIDADE = 2200.0
PULO = 760.0
ANDAR = 140.0
CORRER = 280.0
GIRO = float(PARAMS.get("giro", 0.0))
RAMPA = float(PARAMS.get("ramp_angle", 25.0))
VEL_ELEVADOR = float(PARAMS.get("lift_speed", 110.0))
RODADAS = int(PARAMS.get("rounds", 1))
SKIN_SLACK = 2.5            # a foot may rest up to the contact skin above a top
AFUNDA = 0.5                # how far a body may sit inside a STATIC top (slop)

st.zoom = 1.0
st.segurando = False
st.pontos = 0
ATO = {"nome": None, "n": 0, "t0": 0.0, "patios": 0}
CENA = {}                   # the act's objects, by name (cleared per act)
PILOTO = {}                 # what the pilot may read (plain numbers)
CURSOR = {"view": None, "botao": False, "dono": None}   # written by the pilot


# --- the camera map, closed form (Canvas Design: the pointer map is the
# float64 inverse of the camera; never scena's own function) ------------------

def vista_para_mundo(vx, vy):
    """Design (view) point -> world, under the camera as it is now: the view
    centre shows ``(pan_x, pan_y)``, ``zoom`` scales about it, ``rotation``
    turns the world by minus that many degrees on screen."""
    z = canvas.zoom
    dx, dy = vx - W / 2.0, vy - H / 2.0
    r = math.radians(canvas.rotation)
    c, s = math.cos(r), math.sin(r)
    return (canvas.pan_x + (dx * c + dy * s) / z, canvas.pan_y + (-dx * s + dy * c) / z)


def _ponteiro():
    """Guia, ``mouse.x``: the pointer in design units, in world space (the
    camera taken into account), read once per frame. At ``G.frame()`` the
    camera has not moved since the frame's sample."""
    v = CURSOR["view"]
    if v is None:
        return None
    ex, ey = vista_para_mundo(*v)
    x, y = mouse                      # PB6: a point unpacks as x, y
    G.hit("ponteiro.medido")
    return (abs(x - ex) < 1e-6 and abs(y - ey) < 1e-6
            or f"mouse ({x:.6f}, {y:.6f}) vs camera map of {v}: ({ex:.6f}, {ey:.6f})")


G.invariant("mouse.world_under_camera", _ponteiro)


def _aperto_de_widget():
    """Guia, ``mouse.press``: a press a widget took reads False until it goes up."""
    if CURSOR["botao"] and CURSOR["dono"] == "widget":
        G.hit("widget.aperto_medido")
        return not mouse.press(Mouse.BTN_LEFT) or "mouse.press True under a widget's press"
    return None


G.invariant("mouse.widget_press_hidden", _aperto_de_widget)


# --- keys: the hooks are the twin of keyp ------------------------------------

TECLAS = {"baixo": {}, "agora": set(), "epoca": 0}


def on_key_down(key):
    k = str(key)
    G.check(k not in TECLAS["baixo"], "keys.down_twice", k)
    TECLAS["baixo"][k] = TECLAS["epoca"]
    TECLAS["agora"].add(k)
    G.hit(f"tecla.{k}")
    if k == "SPACE" and "SHIFT" in TECLAS["baixo"]:
        G.hit("tecla.space_com_shift")


def on_key_up(key):
    """Guia, ``on_key_up``: only for a key whose down came; also when the act
    changed with the key held."""
    k = str(key)
    if G.check(k in TECLAS["baixo"], "keys.up_without_down", k):
        if TECLAS["baixo"][k] != TECLAS["epoca"]:
            G.hit("tecla.up_no_ato_novo")
        del TECLAS["baixo"][k]


def conferir_teclas():
    """Guia, ``keyp``: a bare key reads True while held, Shift does not block
    it; ``keyp.once`` is True in the frame of the press. The hooks of this
    act (downs since the last act change) say which keys are held."""
    for k in ("LEFT", "RIGHT"):
        if TECLAS["baixo"].get(k, TECLAS["epoca"]) == TECLAS["epoca"]:
            G.equal(keyp(k), k in TECLAS["baixo"], "keys.keyp_twin", key=k,
                    shift="SHIFT" in TECLAS["baixo"])
    G.equal(keyp.once("SPACE"), "SPACE" in TECLAS["agora"], "keys.once_twin",
            shift="SHIFT" in TECLAS["baixo"])
    if "SHIFT" in TECLAS["baixo"] and "RIGHT" in TECLAS["baixo"]:
        G.hit("tecla.correndo")


# --- lifetimes --------------------------------------------------------------

def marcar(obj, how):
    obj.__dict__["_fim"] = how


def fim(obj):
    return obj.__dict__.get("_fim", "ato")


class Vivo:
    """A mixin for the ledger: born in setup, died from on_destroy."""
    TIPO = "?"

    def setup(self):
        G.born(self, self.TIPO)

    def on_destroy(self):
        G.died(self, fim(self))


# --- the hero ---------------------------------------------------------------

class Heroi(Vivo, Rect, width=28, height=40, color="orange", group="heroi"):
    TIPO = "heroi"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 0)
        self.tag("pisante")
        self.intencao = None

    def on_update(self, dt):
        lados = self.touching_sides
        no_chao = "bottom" in lados
        direita, esquerda = keyp("RIGHT"), keyp("LEFT")
        rapido = CORRER if keyp("SHIFT") else ANDAR
        self.vel.x = rapido * (direita - esquerda)
        pulou = False
        if keyp.once("SPACE") and no_chao:
            self.vel.y = PULO
            pulou = True
            G.hit("pulo")
        if st.segurando:
            self.vel.y = 260.0          # the jet
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        self.intencao = {"dx": self.vel.x * dt, "pulou": pulou or st.segurando}


# --- side models: physics -----------------------------------------------------

def _so_contato(corpo, outro, lado="bottom"):
    cs = list(corpo.touching_contacts)
    return len(cs) == 1 and cs[0].side == lado and cs[0].other is outro


class Fisica:
    """What a frame did to the hero, checked at the next ``G.frame()``.

    * Riders (Guia, "Tornar sólido": "Quem está em cima vai junto ... para os
      lados e para cima e para baixo, com move_by, time= ou move_along, em
      qualquer taxa de quadros"): a hero whose only contact at frame start
      was the bottom one on a lift moved by the lift's displacement plus its
      own step, unless it jumped. On the climbing lift the foot stays on the
      top through the descent.
    * Resting on a lift keeps the contact open (Guia, ``@collide_stay``: runs
      every frame while they touch): bottom on a lift at frame start means
      the enter came and no exit since.
    * An idle hero on the ramp does not creep (Collision Design: "an idle
      body on a slope does not creep"): the slope in the Guia, "Grudar no
      chão", is held still by ``bounce=0`` with ``vel.x = 0``.
    """

    def __init__(self):
        self.antes = None

    def on_frame(self, G):
        h = CENA.get("heroi")
        if h is None or not h.is_alive:
            self.antes = None
            return
        agora = {"x": h.center.x, "y": h.center.y,
                 "lift": {k: (e.center.x, e.center.y) for k, e in CENA["elevadores"].items()}}
        a = self.antes
        it = h.intencao                  # the step of the frame that just ended
        if a is not None and it is not None:
            for k, e in CENA["elevadores"].items():
                if a["sobre"] != k:
                    continue
                lx0, ly0 = a["lift"][k]
                lx1, ly1 = agora["lift"][k]
                if not it["pulou"]:
                    G.equal(agora["x"] - a["x"], (lx1 - lx0) + it["dx"], "rider.carried_x",
                            tol=1e-6, lift=k, lift_dx=round(lx1 - lx0, 6))
                    G.hit(f"carona.{k}")
                    if ly1 < ly0 - 1e-9:
                        G.hit("carona.descendo")
            if a["parado_rampa"] and _so_contato(h, CENA["rampa"]) and not it["pulou"] \
                    and it["dx"] == 0.0:
                G.equal((agora["x"], agora["y"]), (a["x"], a["y"]), "ramp.idle_no_creep", tol=1e-6)
                G.hit("rampa.parado")
        sobre = None
        for k, e in CENA["elevadores"].items():
            if _so_contato(h, e):
                sobre = k
                G.check(ABERTOS.get(("heroi", k), 0) == 1, "lift.contact_open",
                        f"bottom on lift {k} but {ABERTOS.get(('heroi', k), 0)} open contacts")
                topo = e.center.y + e.height / 2.0
                G.within(h.box.bottom - topo, -AFUNDA, SKIN_SLACK, "lift.foot_on_top", lift=k)
        parado = (_so_contato(h, CENA["rampa"]) and not keyp("LEFT") and not keyp("RIGHT")
                  and not st.segurando)
        agora.update(sobre=sobre, parado_rampa=parado)
        h.intencao = None
        self.antes = agora

    def release(self):
        self.antes = None


FISICA = G.model(Fisica())
ABERTOS = {}


def _prateleiras():
    """Collision Design, "Settle direction and STATIC under a stack": nothing a
    movable body does pushes another movable body into or through a STATIC
    one. A body over a shelf never sits deeper than the slop in its top."""
    for nome in ("prateleira_a", "prateleira_b"):
        p = CENA.get(nome)
        if p is None:
            continue
        topo = p.center.y + p.height / 2.0
        for b in group["carga"]:
            bx = b.box
            if bx.right < p.box.left or bx.left > p.box.right:
                continue
            G.hit("carga.medida")
            if bx.bottom < topo - AFUNDA:
                return f"{b.__dict__.get('_nome')} bottom {bx.bottom:.3f} under shelf top {topo:.3f}"
    return None


G.invariant("static.shelf_holds", _prateleiras)


def _bolhas():
    """Collision Design, "Settle direction": an overlap is separated along the
    overlap, never along the velocity. A pair spawned overlapping and moving
    apart keeps its sides; eight frames on it no longer overlaps."""
    for par in BOLHAS["pares"]:
        a, b = par["a"], par["b"]
        if not (a.is_alive and b.is_alive):
            continue
        G.check(a.center.x < b.center.x, "settle.pair_keeps_sides",
                f"left bubble at {a.center.x:.3f}, right at {b.center.x:.3f}")
        par["quadros"] += 1
        if par["quadros"] >= 8:
            gap = (b.center.x - a.center.x) - (a.radius + b.radius)
            G.check(gap > -0.2, "settle.pair_separates", f"gap {gap:.3f} after {par['quadros']} frames")
            G.hit("bolha.separou")


G.invariant("settle.bubbles", _bolhas)


def _pedras():
    """Collision Design, "Settle direction": a ball spawned in a wall, moving
    into the room, leaves into the room (it escaped through the far face when
    settle guessed from its velocity)."""
    for p in group["pedra"]:
        p.quadros += 1
        if p.quadros >= 8:
            G.hit("pedra.medida")
            if p.center.x < MURO_FACE + p.radius - 0.5 or p.vel.x <= 0:
                return f"stone at x {p.center.x:.3f} vel {p.vel.x:.1f} (wall face {MURO_FACE})"
    return None


G.invariant("settle.ball_in_a_wall_leaves_into_the_room", _pedras)


def _bate_estaca():
    """Collision Design, "Mass split", row "Body's walls": a light body swept
    before its fast pusher stops at the STATIC wall behind it; the pusher
    never passes it."""
    leve, ariete = CENA.get("estaca_leve"), CENA.get("ariete")
    if leve is None or not leve.is_alive:
        return None
    G.hit("bate.medido")
    if leve.center.x + leve.radius > BATE_FACE + 1e-6:
        return f"light ball's face at {leve.center.x + leve.radius:.4f} past the wall {BATE_FACE}"
    if ariete.center.x > leve.center.x + 1e-6:
        return f"ram at {ariete.center.x:.3f} past the light ball at {leve.center.x:.3f}"
    return None


G.invariant("static.thin_wall_holds", _bate_estaca)


def _caixa_da_bola():
    """The brick box is closed: the ball stays inside its walls."""
    bola, (l, b, r, t) = CENA.get("bola"), CENA.get("caixa_interior", (0, 0, 0, 0))
    if bola is None or not bola.is_alive:
        return None
    x, y, rr = bola.center.x, bola.center.y, bola.radius
    return (l - 1.0 <= x - rr and x + rr <= r + 1.0 and b - 1.0 <= y - rr and y + rr <= t + 1.0
            or f"ball at ({x:.2f}, {y:.2f}) left the box {(l, b, r, t)}")


G.invariant("breakout.ball_inside", _caixa_da_bola)


class Quique:
    """Guia, "Quebrou no contato": destroying (or parking) the partner in
    ``@collide`` does not take the bounce away. The contact normal is the
    closed form's (``geom.sweep_circle_box``: the ball's circle swept from
    where it started the frame against the brick's rectangle; a face, or a
    corner where two bricks meet or a slot is empty): by the next frame the
    ball moves away along it. (Not ``info.normal``: the detection normal the
    handler gets can be a face's while the bounce uses the swept corner's —
    found at 30 Hz.)"""

    def __init__(self):
        self.pend = []

    def batida(self, bola, tijolo):
        p0 = CENA.get("bola_p")
        if p0 is None:
            return
        hit = geom.sweep_circle_box(p0, (bola.center.x, bola.center.y), bola.radius,
                                    tijolo.center.x, tijolo.center.y, tijolo.width, tijolo.height)
        if hit is None:
            G.hit("tijolo.raspou")      # already touching at frame start: no path to judge
            return
        self.pend.append(((bola.vel.x, bola.vel.y), hit[1]))

    def on_frame(self, G):
        bola = CENA.get("bola")
        if bola is None or not bola.is_alive:
            self.pend = []
            return
        v1 = (bola.vel.x, bola.vel.y)
        for (v0, n) in self.pend:
            G.check(v1[0] * n[0] + v1[1] * n[1] > 0, "breakout.bounce_off_destroyed",
                    f"v {v0} -> {v1}, contact normal ({n[0]:.4f}, {n[1]:.4f})")
            G.hit("tijolo.quique")
        self.pend = []
        CENA["bola_p"] = (bola.center.x, bola.center.y)


QUIQUE = G.model(Quique())


# --- actors of the free-running stations --------------------------------------

class Carga(Vivo, Rect):
    TIPO = "carga"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        self.move_by(0.0, self.vel.y * dt)


class Bola(Vivo, Circle):
    TIPO = "carga"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        self.move_by(0.0, self.vel.y * dt)


class Caixote(Vivo, Rect, width=36, height=36, color="peru", group="caixote"):
    """A crate the player drops on the plot and may drag to the trash."""
    TIPO = "caixote"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 0)
        self.draggable = True

    def on_update(self, dt):
        if self.pointer_pressed or not self.collidable:
            self.vel = Vec2(0, 0)
            return
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        self.move_by(0.0, self.vel.y * dt)


class Quicador(Circle, radius=6, color="white", group="bola"):
    """The brick box's ball."""

    def setup(self):
        self.vel = Vec2(170, 230)

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)


class Bolha(Vivo, Circle, radius=10, color=Color("skyblue").with_alpha(0.7), group="bolha"):
    """PA4: a closure over ``self`` scheduled by the bubble is owned by it."""
    TIPO = "bolha"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 0)
        # PA4's form: the module ``after`` with a closure over ``self`` (not
        # ``self.after``, which is owned by the call itself).
        self.tarde = after(5.0, lambda: self.estourar_tarde())

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    def estourar_tarde(self):
        G.fail("closure.outlived_actor", f"bubble #{G.serial(self)} ran its timer after it died")


class Tijolo(Vivo, Rect, width=44, height=14, color="firebrick", group="tijolo"):
    TIPO = "tijolo"

    def setup(self):
        super().setup()
        self.mass = STATIC


class Tiro(Vivo, Circle, radius=5, color="yellow", group="tiro"):
    """PB5: two independent enter rules on one contact, written as methods."""
    TIPO = "tiro"

    def setup(self):
        super().setup()
        self.vel = Vec2(0, 600)

    def on_update(self, dt):
        self.move_by(0.0, self.vel.y * dt)
        if self.center.y > 900:
            marcar(self, "longe")
            self.destroy()

    @collide_with("alvo")
    def bateu(self, alvo):
        ALVOS["tiros"].add(G.serial(self))
        marcar(self, "bateu")
        self.destroy()


class Alvo(Vivo, Rect, width=40, height=24, color="lime", group="alvo"):
    TIPO = "alvo"

    @collide_with("tiro")
    def atingido(self, tiro):
        ALVOS["alvos"].add(G.serial(self))
        ALVOS["pares"].add((G.serial(tiro), G.serial(self)))
        marcar(self, "atingido")
        self.destroy()
        st.pontos += 1


class Pacote(Vivo, Rect, width=20, height=20, color="tan", group="pacote"):
    TIPO = "pacote"

    def on_update(self, dt):
        self.move_by(0.0, -240.0 * dt)


class Estaca(Vivo, Circle, radius=5, color="white", group="estaca"):
    TIPO = "estaca"


class Pedra(Vivo, Circle, radius=10, color="gray", group="pedra"):
    """Spawned 5 units inside a 4-unit wall, moving into the room (PE1)."""
    TIPO = "pedra"

    def setup(self):
        super().setup()
        self.vel = Vec2(100, 0)
        self.quadros = 0

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)


ALVOS = {"tiros": set(), "alvos": set(), "pares": set(), "feitos": []}
BOLHAS = {"pares": [], "n": 0}
BALANCA = {"primeiro": 0, "segundo": 0}
ESPINHO = {"dentro": 0, "sem_tag_desde": None, "n": 0}
JATO = {"quebrou_em": None, "cliques": 0, "hover": [], "conserto": None}
NOMES = {"nome": [], "nota": []}
PINTOR = {"antes": False}
POP = ("carga", "caixote", "bolha", "tijolo", "tiro", "alvo", "pacote", "estaca", "pedra")
MURO_FACE = 2600.0          # the stones' wall: x 2596 .. 2600
BATE_FACE = 2499.0          # the pile driver's wall: x 2499 .. 2501


def _pop(kind):
    def check():
        n = group[kind].count
        return n == G.alive(kind) or f"group[{kind!r}] has {n}, the game made {G.alive(kind)} alive"
    return check


for _k in POP:
    G.invariant(f"pop.{_k}", _pop(_k))
PONTOS = G.model(ChangeModel("pontos", lambda: st.pontos))


@on_change(st["pontos"])
def mudou_pontos(valor):
    PONTOS.fired(G, valor)


# --- rules ---------------------------------------------------------------------

@collide("heroi", "elevador")
def subiu(heroi, elev):
    k = elev.__dict__["_nome"]
    ABERTOS[("heroi", k)] = ABERTOS.get(("heroi", k), 0) + 1
    G.check(ABERTOS[("heroi", k)] == 1, "lift.enter_once", k)


@collide_exit("heroi", "elevador")
def desceu(heroi, elev):
    k = elev.__dict__["_nome"]
    ABERTOS[("heroi", k)] = ABERTOS.get(("heroi", k), 0) - 1
    G.check(ABERTOS[("heroi", k)] == 0, "lift.exit_once", k)


@collide_stay("heroi", "elevador")
def em_cima(heroi, elev):
    G.hit("elevador.stay")


@collide("pisante", "espinho")
def pisou(heroi, espinho):
    ESPINHO["dentro"] += 1
    G.check(ESPINHO["dentro"] == 1, "spikes.enter_balanced", f"{ESPINHO['dentro']} inside")
    G.hit("espinho.enter")
    ESPINHO["n"] += 1
    label = f"invul{ESPINHO['n']}"
    h = heroi.after(0.1, lambda: invulneravel(heroi, label))
    TIMERS.expect_after(G, label, h, 0.1, early=False)


def invulneravel(heroi, label):
    TIMERS.fired(G, label)
    heroi.untag("pisante")
    ESPINHO["sem_tag_desde"] = G.frame_no
    G.hit("espinho.untag")
    heroi.after(0.5, lambda: vulneravel(heroi))


def vulneravel(heroi):
    heroi.tag("pisante")
    ESPINHO["sem_tag_desde"] = None
    G.hit("espinho.retag")


@collide_exit("pisante", "espinho")
def saiu_espinho(heroi, espinho):
    ESPINHO["dentro"] -= 1
    G.check(ESPINHO["dentro"] == 0, "spikes.exit_balanced", f"{ESPINHO['dentro']} inside")
    G.hit("espinho.exit")


def _espinho():
    """Guia, ``@collide_exit``: a contact ends when the bodies stop touching,
    and also when a side leaves the group (untag): the exit runs."""
    desde = ESPINHO["sem_tag_desde"]
    if desde is not None and G.frame_no > desde + 1:
        G.hit("espinho.medido")
        return ESPINHO["dentro"] == 0 or f"untagged since frame {desde}, {ESPINHO['dentro']} inside"
    return None


G.invariant("spikes.exit_on_untag", _espinho)


@collide("bola", "tijolo")
def quebrou(bola, tijolo, info):
    QUIQUE.batida(bola, tijolo)
    marcar(tijolo, "quebrado")
    tijolo.destroy()
    G.hit("tijolo.quebrado")


def reencher():
    """All bricks gone: a new row once the ball is low in the box (never on it)."""
    bola = CENA["bola"]
    l, b, r, t = CENA["caixa_interior"]
    if G.alive("tijolo") == 0 and bola.vel.y < 0 and bola.center.y < b + 60:
        encher_tijolos()


@collide_exit("pacote", "balanca")
def pesou(pacote, balanca):
    BALANCA["primeiro"] += 1
    marcar(pacote, "pesado")
    pacote.destroy()


@collide_exit("pacote", "balanca")
def contou(pacote, balanca):
    BALANCA["segundo"] += 1
    G.hit("balanca.contou")


def _balanca():
    """Guia, ``@collide_exit``: every exit rule of a contact runs, also when
    an earlier one destroyed a side (PB3)."""
    return BALANCA["primeiro"] == BALANCA["segundo"] or f"{BALANCA}"


G.invariant("exit.every_rule_runs", _balanca)


def _alvos():
    """PB5: each shot that hit a target was counted by both rules, whichever
    of the two was made first; the score is the targets hit."""
    if ALVOS["tiros"] != {t for t, _a in ALVOS["pares"]}:
        return f"shots that hit {sorted(ALVOS['tiros'])} vs pairs {sorted(ALVOS['pares'])}"
    G.hit("alvo.medido")
    return st.pontos == len(ALVOS["alvos"]) or f"st.pontos {st.pontos} vs {len(ALVOS['alvos'])} hit"


G.invariant("collide.every_enter_rule_runs", _alvos)


# --- HUD: drags across spaces, the held button, the boxes ---------------------

def soltou_no_terreno(icone, terreno, pos):
    """Guia, ``@drop_by``: ``pos`` is where the pointer let go, in the space of
    the shape that owns the function (the plot: the world)."""
    x, y = pos
    v = CURSOR["view"]
    if v is not None:
        G.equal((x, y), vista_para_mundo(*v), "drop.world_pos", tol=1e-6)
    G.check(terreno is CENA["terreno"], "drop.target_is_plot")
    c = CENA["caixote_modelo"].clone(center=(x, y))
    G.equal((c.center.x, c.center.y), (x, y), "clone.center_places", tol=1e-9)
    c.visible = True
    c.collidable = True
    c.draggable = True
    resolve(c, "chao", bounce=0.0)
    G.event("drop.caixote")
    caixotes = [o for o in group["caixote"] if o is not c and o is not CENA["caixote_modelo"]]
    if len(caixotes) > 4:
        marcar(caixotes[0], "velho")
        caixotes[0].destroy()


def soltou_na_lixeira(caixote, lixeira, pos):
    v = CURSOR["view"]
    if v is not None:
        x, y = pos
        G.equal((x, y), tuple(v), "drop.ui_pos", tol=1e-6)
    G.check(caixote.tagged("caixote"), "drop.world_piece")
    marcar(caixote, "lixo")
    caixote.destroy()
    G.event("drop.lixeira")


def icone_voltou(icone, alvo, pos):
    icone.move_to(CENA["icone_casa"])


@on_change(st["segurando"])
def jato_mudou(valor):
    if valor:
        h = after(0.4, quebrar_jato)
        CENA["jato_quebra"] = h
        TIMERS.expect_after(G, f"quebra{ATO['n']}.{G.reach.get('jato.apertado', 0)}", h, 0.4,
                            early=False)
        CENA["jato_label"] = f"quebra{ATO['n']}.{G.reach.get('jato.apertado', 0)}"
        G.hit("jato.apertado")
    else:
        h = CENA.pop("jato_quebra", None)
        if h is not None and not h.done:
            h.cancel()
            TIMERS.cancelled(CENA["jato_label"])


def quebrar_jato():
    """The jet overheats while held: the Button is destroyed with the mouse
    button still down (Guia, Button: "Destruído com o botão do mouse
    segurado ... também grava value_off, sem clique")."""
    TIMERS.fired(G, CENA["jato_label"])
    CENA.pop("jato_quebra", None)
    b = CENA.get("jato")
    if b is None:
        return
    segurava = st.segurando
    b.destroy()
    CENA["jato"] = None
    if segurava:
        G.equal(st.segurando, False, "button.destroyed_writes_off")
        G.hit("jato.quebrou_segurado")
    JATO["quebrou_em"] = G.frame_no
    h = after(1.0, consertar_jato)
    JATO["conserto"] = h


def novo_jato():
    b = Button(st["segurando"], label="Jato", top_left=(20, H - 70), width=110,
               on_click=lambda: JATO.__setitem__("cliques", JATO["cliques"] + 1))
    b.on_hover = lambda w: (JATO["hover"].append("in"), G.hit("jato.hover"))
    b.on_hover_exit = lambda w: (JATO["hover"].append("out"), G.hit("jato.hover_exit"))
    JATO["hover"] = []
    CENA["jato"] = b
    return b


def consertar_jato():
    if ATO["nome"] == "Patio":
        novo_jato()
        G.hit("jato.consertado")


def _hover_jato():
    """Guia, ``@hover`` / ``@hover_exit``: enter and exit alternate, starting
    with an enter."""
    seq = JATO["hover"]
    for i, e in enumerate(seq):
        if e != ("in" if i % 2 == 0 else "out"):
            return f"hover events {seq}"
    return None


G.invariant("hover.alternates", _hover_jato)


def _jato_fora():
    """Guia, ``pointer_hover``: "A saída é imediata: ... sair de baixo do
    cursor": with the cursor outside the window (put there with no motion
    event), the Jato is not hovered from the next frame on."""
    v, b = CURSOR["view"], CENA.get("jato")
    if v is None or b is None or CURSOR["botao"]:
        return None
    fora = not (0 <= v[0] <= W and 0 <= v[1] <= H)
    JATO["fora"] = JATO.get("fora", 0) + 1 if fora else 0
    if JATO["fora"] >= 2:
        G.hit("jato.fora_medido")
        return not b.pointer_hover or f"Jato hovered with the cursor at {v}"
    return None


G.invariant("hover.leaves_with_the_cursor", _jato_fora)


def nome_enviado(texto):
    NOMES["nome"].append(texto)
    G.hit("nome.enviado")
    CENA["nota"].focus()


def nota_enviada(texto):
    NOMES["nota"].append(texto)


def _caixas():
    """Guia, TextInput: a key held in one box and the focus moved by its
    ``on_submit``: the OS repeats of that key do not reach the new box."""
    nota = CENA.get("nota")
    if nota is None or not nota.is_alive:
        return None
    if NOMES["nome"]:
        G.hit("nota.medida")
        return (nota.value == "" and not NOMES["nota"]
                or f"Nota got {nota.value!r}, submits {NOMES['nota']}")
    return None


G.invariant("textinput.repeat_stays_with_its_press", _caixas)


def pintar():
    """A paint rule an author writes: a stake where the left button went down
    on the world (a press a widget took reads False; a press on a crate or the
    icon is a drag, not paint)."""
    apertado = mouse.press(Mouse.BTN_LEFT)
    novo = apertado and not PINTOR["antes"]
    PINTOR["antes"] = apertado
    if not novo or ATO["nome"] != "Patio":
        return
    if any(o.pointer_pressed for o in list(group["caixote"]) + [CENA["icone"]]):
        return
    x, y = mouse
    Estaca(center=(x, y))
    v = CURSOR["view"]
    if v is not None:                    # a pilot reports the cursor (a script does not)
        G.check(CURSOR["dono"] == "mundo", "paint.only_on_world", f"press owner {CURSOR['dono']}")
        G.equal((x, y), vista_para_mundo(*v), "paint.at_pointer", tol=1e-6)
    G.event("estaca")
    est = list(group["estaca"])
    if len(est) > 6:
        marcar(est[0], "velha")
        est[0].destroy()


# --- stations -----------------------------------------------------------------

def chao(cx, cy, w, h, nome=None):
    r = Rect(center=(cx, cy), width=w, height=h, color="dimgray", group="chao")
    r.mass = STATIC
    if nome:
        CENA[nome] = r
    return r


def montar_mundo():
    # Ground: start -> pit (sideways lift) -> ledge -> shaft (climbing lift) -> high block.
    chao(325, 50, 1250, 100)                     # x -300 .. 950, top 100
    chao(1150, -40, 400, 40)                     # pit floor, top -20
    chao(1400, 50, 100, 100)                     # ledge 1350 .. 1450
    chao(1520, -175, 140, 50)                    # shaft floor, top -150
    chao(1945, 150, 710, 300, "alto")            # high block 1590 .. 2300, top 300
    # The ramp: its top face starts on the ground at x 600 and climbs RAMPA degrees.
    u = (math.cos(math.radians(RAMPA)), math.sin(math.radians(RAMPA)))
    n = (-u[1], u[0])
    cx, cy = 600 + 150 * u[0] - 10 * n[0], 100 + 150 * u[1] - 10 * n[1]
    rampa = Rect(center=(cx, cy), width=300, height=20, color="silver", group="chao")
    rampa.mass = STATIC
    rampa.rotate_by(RAMPA)
    CENA["rampa"] = rampa
    CENA["rampa_topo"] = (600 + 300 * u[0], 100 + 300 * u[1])
    # Lifts: one slides across the pit, one climbs the shaft (both move_by, STATIC).
    lado = Rect(center=(1020, 90), width=140, height=20, color="peru", group="elevador")
    lado.__dict__["_nome"] = "lado"
    sobe = Rect(center=(1520, 90), width=140, height=20, color="peru", group="elevador")
    sobe.__dict__["_nome"] = "sobe"
    for e in (lado, sobe):
        e.mass = STATIC
        e.tag("chao")
    CENA["elevadores"] = {"lado": lado, "sobe": sobe}
    CENA["lado_dir"] = 1
    CENA["sobe_fase"] = ("baixo", 0.0)
    # Spikes on the ground (a zone, not solid).
    CENA["espinho"] = Rect(center=(460, 108), width=60, height=16, color="crimson", group="espinho")
    # The door at the high block's far end.
    CENA["porta"] = Rect(center=(2260, 360), width=30, height=120,
                         color=Color("white").with_alpha(0.2), group="porta")
    # The plot (a drop target in the world) and the crate template (hidden).
    terreno = Rect(center=(250, 130), width=160, height=60, color=Color("olive").with_alpha(0.4))
    terreno.on_drop_by = soltou_no_terreno
    CENA["terreno"] = terreno
    # The crate template: a hidden Caixote far away; drops clone it (PC1).
    molde = Caixote(center=(-900, -900))
    molde.visible = False
    molde.collidable = False
    molde.draggable = False
    CENA["caixote_modelo"] = molde


def montar_estacoes():
    # Stacks on thin STATIC shelves (PE3, PE4).
    pa = Rect(center=(300, 470), width=200, height=10, color="gray", group="prateleira")
    pb = Rect(center=(700, 520), width=200, height=10, color="gray", group="prateleira")
    for p in (pa, pb):
        p.mass = STATIC
    CENA["prateleira_a"], CENA["prateleira_b"] = pa, pb
    leve = Carga(center=(300, 475 + 20.08), width=40, height=40, color="tan", group="carga")
    leve.__dict__["_nome"] = "leve"
    medio = Carga(center=(300, 475 + 60.2), width=40, height=40, color="sienna", group="carga")
    medio.mass = 5.0
    medio.__dict__["_nome"] = "medio"
    pesado = Carga(center=(300, 680), width=40, height=40, color="brown", group="carga")
    pesado.mass = 20.0
    pesado.__dict__["_nome"] = "pesado"
    bolinha = Bola(center=(700, 525 + 12.08), radius=12, color="khaki", group="carga")
    bolinha.__dict__["_nome"] = "bolinha"
    bolona = Bola(center=(700, 650), radius=18, color="goldenrod", group="carga")
    bolona.mass = 30.0
    bolona.__dict__["_nome"] = "bolona"
    CENA.update(pesado=pesado, bolona=bolona)
    resolve("carga", ["prateleira", "carga"], bounce=0.0)
    h = every(3.0, soltar_pesos)
    TIMERS.expect_every(G, "pesos", h, 3.0, early=False, scope="Patio")
    # Bubbles (PE1, PA4).
    resolve("bolha", "bolha", bounce=1.0)
    h = every(1.2, soprar)
    TIMERS.expect_every(G, "bolhas", h, 1.2, early=False, scope="Patio")
    # The brick box (PE5).
    l, b, r, t = 1740, 420, 1960, 580
    CENA["caixa_interior"] = (l, b, r, t)
    for (cx, cy, w, hh) in ((l - 10, (b + t) / 2, 20, t - b + 40), (r + 10, (b + t) / 2, 20, t - b + 40),
                            ((l + r) / 2, b - 10, r - l, 20), ((l + r) / 2, t + 10, r - l, 20)):
        p = Rect(center=(cx, cy), width=w, height=hh, color="dimgray", group="parede")
        p.mass = STATIC
    encher_tijolos()
    bola = Quicador(center=((l + r) / 2, b + 30))
    CENA["bola"] = bola
    resolve(bola, ["tijolo", "parede"], bounce=1.0)
    # The turret and its targets (PB5).
    h = every(0.6, disparar)
    TIMERS.expect_every(G, "torre", h, 0.6, early=False, scope="Patio")
    # The pile driver (PE4): a light ball against a 2-unit wall, made before
    # the heavy ram that hits it at 6000 units/s (position-only resolve).
    Rect(center=(BATE_FACE + 1, 460), width=2, height=200, color="dimgray", group="fixo").mass = STATIC
    leve = Circle(center=(BATE_FACE - 8 - 0.08, 460), radius=8, color="khaki", group="percussao")
    leve.mass = 0.2
    ariete = Circle(center=(BATE_FACE - 300, 460), radius=8, color="brown", group="percussao")
    CENA.update(estaca_leve=leve, ariete=ariete, ariete_t=0.0)
    resolve("percussao", ["percussao", "fixo"])
    # Stones in a wall (PE1).
    Rect(center=(MURO_FACE - 2, 460), width=4, height=200, color="dimgray", group="muro").mass = STATIC
    resolve("pedra", "muro", bounce=1.0)
    h = every(1.0, atirar_pedra)
    TIMERS.expect_every(G, "pedras", h, 1.0, early=False, scope="Patio")
    # Parcels through the scale (PB3).
    Rect(center=(1150, 420), width=80, height=40, color=Color("cyan").with_alpha(0.25), group="balanca")
    h = every(0.7, lancar_pacote)
    TIMERS.expect_every(G, "pacotes", h, 0.7, early=False, scope="Patio")


def encher_tijolos():
    l, b, r, t = CENA["caixa_interior"]
    for i in range(5):
        Tijolo(center=(l + 22 + 44 * i, t - 7))
    G.hit("tijolos.cheios")


def soltar_pesos():
    """Re-drop the heavy crate on the stack and the heavy ball on the light one
    (placement, then gravity): the shelves must hold every time."""
    TIMERS.fired(G, "pesos")
    for nome, x, alto in (("pesado", 300, 740.0), ("bolona", 700, 680.0)):
        o = CENA[nome]
        o.center = (x, alto)
        o.vel = Vec2(0, 0)
    G.hit("pesos.soltos")


def soprar():
    """A pair of bubbles spawned 5 units into each other, moving apart."""
    TIMERS.fired(G, "bolhas")
    BOLHAS["n"] += 1
    n = BOLHAS["n"]
    x0 = 1100 + 40 * (n % 3)
    a = Bolha(center=(x0, 540))
    b = Bolha(center=(x0 + 15, 540))
    a.vel, b.vel = Vec2(-60, 0), Vec2(60, 0)
    par = {"a": a, "b": b, "quadros": 0}
    BOLHAS["pares"].append(par)
    label = f"estoura{n}"
    h = after(0.8, lambda: estourar(par, label))
    TIMERS.expect_after(G, label, h, 0.8, early=False, scope="Patio")


def estourar(par, label):
    TIMERS.fired(G, label)
    for b in (par["a"], par["b"]):
        h = b.tarde
        marcar(b, "estourou")
        b.destroy()
        G.check(h.cancelled, "closure.owned_by_actor",
                "a lambda over self scheduled by the bubble outlived it")
    BOLHAS["pares"].remove(par)
    G.hit("bolha.estourou")


def disparar():
    """Alternate which of the pair is made first (PB5: the outcome must not
    depend on it)."""
    TIMERS.fired(G, "torre")
    k = len(ALVOS["feitos"])
    torre = (2050.0, 420.0)
    if k % 2 == 0:
        a = Alvo(center=(torre[0], torre[1] + 120))
        t = Tiro(center=torre)
    else:
        t = Tiro(center=torre)
        a = Alvo(center=(torre[0], torre[1] + 120))
    ALVOS["feitos"].append((G.serial(t), G.serial(a)))
    G.hit("torre.disparo")


def atirar_pedra():
    TIMERS.fired(G, "pedras")
    p = Pedra(center=(MURO_FACE + 5, 460))
    p.after(0.4, lambda: sumir_pedra(p))      # owned by the stone: a bound closure
    G.hit("pedra.atirada")


def sumir_pedra(p):
    marcar(p, "sumiu")
    p.destroy()


def bater_estaca(dt):
    """Every second: the ram rushes the light ball for 0.15 s, then both go back."""
    leve, ariete = CENA["estaca_leve"], CENA["ariete"]
    t = CENA["ariete_t"] + dt
    if t >= 1.0:
        t = 0.0
        leve.center = (BATE_FACE - 8 - 0.08, 460)
        ariete.center = (BATE_FACE - 300, 460)
        G.hit("bate.volta")
    elif t <= 0.15:
        ariete.move_by(6000.0 * dt, 0.0)
    CENA["ariete_t"] = t


def lancar_pacote():
    TIMERS.fired(G, "pacotes")
    Pacote(center=(1150, 560))


def mover_elevadores(dt):
    """The pit lift slides between its ends at VEL_ELEVADOR; the shaft lift
    rests at the bottom, climbs, rests at the top, comes down."""
    lado = CENA["elevadores"]["lado"]
    x = lado.center.x
    alvo = x + CENA["lado_dir"] * VEL_ELEVADOR * dt
    if alvo >= 1280.0:
        alvo, CENA["lado_dir"] = 1280.0, -1
    elif alvo <= 1020.0:
        alvo, CENA["lado_dir"] = 1020.0, 1
    lado.move_by(alvo - x, 0.0)
    sobe = CENA["elevadores"]["sobe"]
    fase, t = CENA["sobe_fase"]
    t += dt
    y = sobe.center.y
    if fase in ("baixo", "cima"):
        if t >= 1.5:
            fase, t = ("subindo" if fase == "baixo" else "descendo"), 0.0
        sobe_y = y
    else:
        passo = 160.0 * dt * (1 if fase == "subindo" else -1)
        sobe_y = min(max(y + passo, 90.0), 290.0)
        if fase == "subindo" and sobe_y >= 290.0:
            fase, t = "cima", 0.0
        elif fase == "descendo" and sobe_y <= 90.0:
            fase, t = "baixo", 0.0
    sobe.move_by(0.0, sobe_y - y)
    CENA["sobe_fase"] = (fase, t)


# --- acts ----------------------------------------------------------------------

def entrar_ato(nome):
    anterior = ATO["nome"]
    if anterior is not None:
        G.check(all(G.alive(k) == 0 for k in POP + ("heroi",)), "act.objects_removed")
        G.equal((canvas.zoom, canvas.pan_x, canvas.pan_y, canvas.rotation), (1.0, W / 2, H / 2, 0.0),
                "act.camera_restored", tol=1e-9)
        TIMERS.retire(G, anterior)
    TROCA["pendente"] = False
    ATO.update(nome=nome, n=ATO["n"] + 1, t0=clock.time)
    TECLAS["epoca"] += 1
    CENA.clear()
    ABERTOS.clear()
    BOLHAS["pares"] = []
    ESPINHO.update(dentro=0, sem_tag_desde=None)
    G.scope(nome)
    G.event("act", nome=nome)
    PILOTO.clear()
    PILOTO.update(ato=nome, patios=ATO["patios"])


class Patio(Act):
    def setup(self):
        ATO["patios"] += 1
        entrar_ato("Patio")
        montar_mundo()
        montar_estacoes()
        heroi = Heroi(center=(120, 125))
        CENA["heroi"] = heroi
        resolve(heroi, "chao", bounce=0.0)
        # HUD: zoom slider, jet button, crate icon, trash, two boxes.
        Slider(st["zoom"], label="Zoom", min_value=0.6, max_value=1.6, top_left=(20, H - 20), width=200)
        novo_jato()
        casa = (60.0, 60.0)
        icone = Rect(center=casa, width=40, height=40, color="peru", layer="ui")
        icone.draggable = True
        icone.on_drag_to = icone_voltou
        CENA["icone"], CENA["icone_casa"] = icone, casa
        lixeira = Rect(center=(940, 60), width=60, height=60, color=Color("red").with_alpha(0.4),
                       layer="ui")
        lixeira.on_drop_by = soltou_na_lixeira
        CENA["lixeira"] = lixeira
        TextInput(label="Nome", top_left=(260, H - 20), width=180, on_submit=nome_enviado)
        CENA["nota"] = TextInput(label="Nota", top_left=(460, H - 20), width=180,
                                 on_submit=nota_enviada)
        NOMES.update(nome=[], nota=[])
        placar = Text("", top_right=(W - 16, H - 16), font_size=16, layer="ui")
        placar["text"] @= lambda: f"Pontos {st.pontos}"
        CENA["placar"] = placar
        self.publicar()

    def on_update(self, dt):
        mover_elevadores(dt)
        bater_estaca(dt)
        h = CENA["heroi"]
        # The camera chases the hero, zooms with the slider and may turn.
        x0 = mouse.x
        olhar = (canvas.pan_x, canvas.pan_y)
        nx, ny = chase(olhar, (h.center.x, h.center.y + 120), rate=4.0)
        canvas.pan_to(nx, ny)
        canvas.zoom_to(st.zoom)
        if GIRO:
            canvas.rotate_to(GIRO * math.sin(0.8 * (clock.time - ATO["t0"])))
        # Guia, mouse.x: read once per frame; after a pan in this update it is
        # still the value from before the camera moved (PC8).
        G.equal(mouse.x, x0, "mouse.sampled_once", tol=0.0)
        reencher()
        if h.center.x > 2245 and h.center.y > 290 and not TROCA["pendente"]:
            trocar(Galpao)
            return
        self.publicar()

    def publicar(self):
        h = CENA["heroi"]
        lado, sobe = CENA["elevadores"]["lado"], CENA["elevadores"]["sobe"]
        PILOTO.update(x=h.center.x, y=h.center.y, chao="bottom" in h.touching_sides,
                      t=clock.time - ATO["t0"], lado_x=lado.center.x, lado_dir=CENA["lado_dir"],
                      sobe_y=sobe.center.y, sobe_fase=CENA["sobe_fase"][0],
                      sobe_t=CENA["sobe_fase"][1], jato=CENA.get("jato") is not None,
                      caixotes=len(group["caixote"]), estacas=len(group["estaca"]))


class Galpao(Act):
    """The shed: the hero walked in holding RIGHT; its up arrives here (PD7)."""

    def setup(self):
        entrar_ato("Galpao")
        Text("GALPAO", center=(W / 2, H / 2), font_size=48)
        h = self.after(1.2, self.voltar)
        TIMERS.expect_after(G, f"volta{ATO['n']}", h, 1.2, early=False, scope="Galpao")
        CENA["volta_label"] = f"volta{ATO['n']}"

    def on_update(self, dt):
        PILOTO.update(t=clock.time - ATO["t0"])

    def voltar(self):
        TIMERS.fired(G, CENA["volta_label"])
        G.hit("galpao.voltou")
        if ATO["patios"] < RODADAS:
            trocar(Patio)
        else:
            G.hit("fim")


TROCA = {"pendente": False}


def trocar(ato):
    TROCA["pendente"] = True
    change_act(ato)


def _texto():
    p = CENA.get("placar")
    if p is None or not p.is_alive:
        return None
    return p.text == f"Pontos {st.pontos}" or f"{p.text!r} vs Pontos {st.pontos}"


G.invariant("hud.fresh", _texto)


def update(dt):
    G.frame()
    conferir_teclas()
    pintar()
    TECLAS["agora"].clear()


run(Patio)
