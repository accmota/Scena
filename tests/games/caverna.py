# harness: cwd=examples/media
"""Caverna — a game system test (tests/games/). Not an example, not a tutorial.

A side-scrolling platformer on a tracked level file (``caverna.json``, next to
this script), checked while it runs by side models (tests/game_support.py) and
by the driver (tests/game_harness.py, tests/test_game_caverna*.py). Strategy:
design/Testing Design.md, "Game system tests".

What it leans on: ``Level`` and ``make()``, ``resolve`` with ``bounce=0`` and
``STATIC``, ``touching_sides`` / ``touching_contacts`` / ``slope_angle``,
``floor_below``, coyote time and a jump buffer through ``recently``,
``keyp.once``, ``ready``, a lift on ``move_along`` whose ``Handle.velocity``
carries the rider, a camera on ``deadzone`` + ``chase``, a parallax layer, an
``Endless`` cloud layer with ``slot.rng``, ninja and robot sheets by file
pattern (``strip``), an attack hitbox switched by ``showing`` through
``part["active"] @=``, a hurtbox part, ``History`` of checkpoints, death by
``@leave_playfield`` and an iris cover, ``Contrail``, ``Fire`` / ``Rain``,
a HUD grid from ``Box.grid``, two acts.

PARAMS: camera ("chase" | "deadzone"), fade, endless_layer_response.
Controls (the pilot drives them): LEFT / RIGHT run, UP jump, X attack.
"""
import json
import math
import os

from scena import *
from game_support import (ChangeModel, CoverModel, Ledger, TimerModel, geom, reached)

PARAMS = globals().get("PARAMS", {})
G = Ledger("caverna", mark=globals().get("mark"))
TIMERS = G.model(TimerModel())
COVER = G.model(CoverModel(lambda: canvas.covered))

W, H = 1000, 600
init(width=W, height=H, title="Caverna")

FADE = float(PARAMS.get("fade", 0.25))
CAMERA = PARAMS.get("camera", "chase")
GRAVIDADE = 1800.0
PULO = 760.0
CORRIDA = 300.0
COYOTE = 0.08
BUFFER = 0.12
ZONA_MORTA = (260.0, 180.0)
RITMO_CAMERA = 6.0
RESPOSTA_MONTANHAS = 0.25
RESPOSTA_NUVENS = float(PARAMS.get("endless_layer_response", 1.0))
PASSO_NUVENS = 420.0

# --- the level, read twice: through Level, and as plain JSON (the oracle) ---

FASE = Level("caverna.json")
_here = os.path.dirname(os.path.abspath(globals().get("__file__", "caverna.py")))
with open(os.path.join(_here, "caverna.json"), encoding="utf-8") as _fh:
    BRUTO = json.load(_fh)
ITENS = {it["name"]: it for it in BRUTO["items"]}
MUNDO_W, MUNDO_H = BRUTO["size"]


def _grupo_bruto(nome):
    return [it for it in BRUTO["items"] if nome in it.get("groups", ())]


def conferir_fase():
    """Level against the file: names, groups, order, every field, boxes."""
    G.equal(tuple(FASE.size), (MUNDO_W, MUNDO_H), "level.size")
    G.equal(list(FASE.names), [it["name"] for it in BRUTO["items"]], "level.names_in_order")
    for nome in ("plataforma", "fruta", "checkpoint", "robo", "decor", "trilho"):
        G.equal([i.name for i in FASE.group(nome)], [it["name"] for it in _grupo_bruto(nome)],
                f"level.group.{nome}")
    for item in FASE:
        bruto = ITENS[item.name]
        G.equal(item.kind, bruto["kind"], "level.kind")
        G.equal(tuple(item.groups), tuple(bruto.get("groups", ())), "level.groups")
        if "center" in bruto:
            G.equal((item.center.x, item.center.y), tuple(bruto["center"]), "level.center", tol=1e-9)
        if bruto["kind"] in ("rect", "image"):
            G.equal((item.width, item.height, item.angle),
                    (bruto["width"], bruto["height"], bruto.get("angle", 0.0)), "level.size_angle")
            b = item.box
            G.equal((b.center.x, b.center.y, b.width, b.height, b.angle),
                    (*bruto["center"], bruto["width"], bruto["height"], bruto.get("angle", 0.0)),
                    "level.box", tol=1e-9)
        if bruto["kind"] in ("polygon", "track"):
            G.equal([(p.x, p.y) for p in item.points], [tuple(p) for p in bruto["points"]],
                    "level.points", tol=1e-9)
        if bruto["kind"] == "image":
            esperado = os.path.normpath(os.path.join(_here, *bruto["file"].split("/")))
            G.equal(item.image, esperado, "level.image_path")
    G.hit("level.checked")


conferir_fase()

# --- art ------------------------------------------------------------------

NINJA = Sheet(anchor="bottom", pixel_size=0.16)
NINJA.strip("parado", "ninja/Idle__*.png", fps=8)
NINJA.strip("correndo", "ninja/Run__*.png", fps=14)
NINJA.strip("pulando", "ninja/Jump__*.png", fps=12)
NINJA.strip("golpe", "ninja/Attack__*.png", fps=18)
NINJA.strip("morto", "ninja/Dead__*.png", fps=14)
EM_PE = ("parado", "correndo", "pulando")
GOLPE = tuple(f"Attack__{i:03d}" for i in range(3, 8))
ROBO = Sheet(anchor="bottom", pixel_size=0.13)
ROBO.strip("andando", "robot/Run (*).png", fps=12)
ROBO.strip("morto", "robot/Dead (*).png", fps=14)
CEREJA = Sheet("pixel_adv/Cherries.png", cols=17, fps=20, pixel_size=1.6)
BANDEIRA = Sheet("pixel_adv/Checkpoint (Flag Idle)(64x64).png", cols=10, fps=12, pixel_size=1.2)
G.equal(NINJA.nframes, 50, "sheet.nframes")
G.equal(CEREJA.nframes, 17, "sheet.grid_nframes")

st.frutas = 0
st.mortes = 0
MODELO = {"frutas": set(), "mortes": 0, "checkpoints": 0, "saidas_hist": 0, "pulos": 0}
ATO = {"nome": None, "n": 0}
HUD = {}
NUVENS = {"sorteios": {}, "vivas": {}, "left0": None, "revisitas": 0}
CAMERA_MODELO = {"esperado": None}
ELEVADOR = {"h": None, "antes": None, "dt": 0.0}
SALTO = {"no_chao_t": None, "pulo_t": None}
PILOTO = {}                         # what the pilot may read (plain numbers)


# --- independent formulas from the Guia ---------------------------------------

def zona_morta(atual, alvo, tamanho):
    """Guia, "deadzone": the target moves freely inside a box of ``tamanho``
    centred on ``atual``; outside it, the result moves just enough to bring
    it back to the edge."""
    out = []
    for c, t, s in zip(atual, alvo, tamanho):
        h = s / 2.0
        out.append(t - h if t > c + h else (t + h if t < c - h else c))
    return tuple(out)


def perseguir(atual, alvo, ritmo, dt):
    """Guia, "chase": ``lerp(current, target, 1 - exp(-rate * dt))``."""
    k = 1.0 - math.exp(-ritmo * dt)
    return tuple(a + (b - a) * k for a, b in zip(atual, alvo))


def camera_alvo(heroi):
    olhar = (canvas.pan_x, canvas.pan_y)
    tx, ty = deadzone(olhar, heroi.center, size=ZONA_MORTA)
    ex, ey = zona_morta(olhar, (heroi.center.x, heroi.center.y), ZONA_MORTA)
    G.equal((tx, ty), (ex, ey), "deadzone.formula", tol=1e-9)
    if CAMERA == "chase":
        nx, ny = chase(olhar, (tx, ty), rate=RITMO_CAMERA)
        G.equal((nx, ny), perseguir(olhar, (ex, ey), RITMO_CAMERA, clock.dt), "chase.formula", tol=1e-9)
    else:
        nx, ny = tx, ty
    # The world's edges: the camera never shows past them.
    nx = min(max(nx, W / 2), MUNDO_W - W / 2)
    ny = min(max(ny, H / 2), MUNDO_H - H / 2)
    return nx, ny


def _camera():
    esp = CAMERA_MODELO["esperado"]
    if esp is None:
        return None
    return (abs(canvas.pan_x - esp[0]) < 1e-9 and abs(canvas.pan_y - esp[1]) < 1e-9
            or f"pan ({canvas.pan_x}, {canvas.pan_y}) vs pan_to's {esp}")


G.invariant("camera.pan_to_holds", _camera)


def _paralaxe():
    """Guia, "Camadas": pan_response 0 = glued to the screen, 1 = with the world;
    in between, the layer's view moves that fraction of the camera's move."""
    if "montanhas" not in canvas.layers:
        return None
    v = canvas.layers["montanhas"].view
    ex = W / 2 + (canvas.pan_x - W / 2) * RESPOSTA_MONTANHAS
    ey = H / 2 + (canvas.pan_y - H / 2) * RESPOSTA_MONTANHAS
    # 1e-3: the layer's view goes through Skia's float32 matrices (~3e-5 at 500).
    return (abs(v.center.x - ex) < 1e-3 and abs(v.center.y - ey) < 1e-3
            or f"layer view centre ({v.center.x:.3f}, {v.center.y:.3f}) vs ({ex:.3f}, {ey:.3f})")


G.invariant("parallax.view", _paralaxe)


# --- stage invariants (lifetimes) ---------------------------------------------

def _pop(kind, grp):
    def check():
        n = group[grp].count
        return n == G.alive(kind) or f"group[{grp!r}] has {n}, the game made {G.alive(kind)} alive"
    return check


for _k in ("fruta", "robo", "nuvem", "bandeira"):
    G.invariant(f"pop.{_k}", _pop(_k, _k))

FRUTAS = G.model(ChangeModel("frutas", lambda: st.frutas))


@on_change(st["frutas"])
def mudou_frutas(valor):
    FRUTAS.fired(G, valor)
    for i, cel in enumerate(HUD.get("celulas", ())):
        cel.color = "gold" if valor >= (i + 1) * 2 else Color("gray").with_alpha(0.3)


# --- actors ---------------------------------------------------------------

def marcar_morte(obj, how):
    obj.__dict__["_morte_jogo"] = how


def morte(obj):
    return obj.__dict__.get("_morte_jogo", "ato")


class Heroi(Sprite, source=NINJA, group="heroi", hitbox_shape="rect", hitbox_source=EM_PE,
            hitbox_anchor="bottom", hitbox_scale=(0.45, 0.92)):
    def setup(self):
        G.born(self, "heroi")
        self.vel = Vec2(0, 0)
        self.dor = self.add_hitbox(group="dor", scale=0.6)
        self.espada = self.add_hitbox(group="ataque", px_rect=(330, 140, 200, 230))
        self.espada["active"] @= lambda: self.showing(GOLPE)
        self.morrendo = False
        self.ferido = False
        self.no_ar = False

    def on_destroy(self):
        G.died(self, morte(self))

    def on_update(self, dt):
        if self.morrendo:
            return
        contatos = self.touching_contacts
        no_chao = "bottom" in self.touching_sides
        apertou = keyp.once("UP")
        coyote = recently("no_chao", no_chao, hold=COYOTE)
        pediu = recently("pulo", apertou, hold=BUFFER)
        self.modelo_salto(no_chao, apertou, coyote, pediu)
        if pediu and coyote:
            self.vel.y = PULO
            recently.reset("pulo")
            recently.reset("no_chao")
            SALTO["pulo_t"] = None
            SALTO["no_chao_t"] = None
            tipo = "coyote" if not no_chao else ("buffer" if not apertou else "normal")
            G.event(f"pulo.{tipo}")
            MODELO["pulos"] += 1
        direita, esquerda = keyp("RIGHT"), keyp("LEFT")
        self.vel.x = CORRIDA * (direita - esquerda)
        if direita and not esquerda:
            self.flip_x = False
        elif esquerda and not direita:
            self.flip_x = True
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        carona = 0.0
        h = ELEVADOR["h"]
        if no_chao and h is not None and any(c.other is HUD.get("elevador") for c in contatos
                                             if c.side == "bottom"):
            carona = h.velocity.x * dt
            G.hit("elevador.carona")
        self.move_by(self.vel.x * dt + carona, self.vel.y * dt)
        if keyp.once("X") and self.ready("golpe", 0.5):
            self.play("golpe", loops=1, next="parado")
            G.hit("golpe")
        if not self.showing("golpe"):
            if not no_chao:
                self.play("pulando", min_hold=0.06)
            elif self.vel.x != 0:
                self.play("correndo", min_hold=0.08, resume=True)
            else:
                self.play("parado", min_hold=0.08, resume=True)
        self.tilt = AUTO_GROUND

    def modelo_salto(self, no_chao, apertou, coyote, pediu):
        """Guia, "recently": True if the value is true now or was in the last
        ``hold`` seconds; ``recently.reset`` forgets. The twin keeps the last
        time each value was true and answers the same question."""
        t = clock.time
        if no_chao:
            SALTO["no_chao_t"] = t
        if apertou:
            SALTO["pulo_t"] = t

        def lembra(t0, hold):
            return t0 is not None and reached(hold, t - t0)

        G.equal(coyote, lembra(SALTO["no_chao_t"], COYOTE), "recently.coyote_twin")
        G.equal(pediu, lembra(SALTO["pulo_t"], BUFFER), "recently.buffer_twin")

    def ferir(self, empurrao):
        if self.ferido or self.morrendo:
            return
        self.ferido = True
        self.blink(0.6)
        self.knock(distance=18, angle=90)
        h = self.after(0.6, self.curar, name="iframes")
        TIMERS.expect_after(G, "iframes", h, 0.6, early=False)
        G.hit("dano")

    def curar(self):
        TIMERS.fired(G, "iframes")
        self.ferido = False


class Robo(Sprite, source=ROBO, group="robo", hitbox_shape="rect", hitbox_source="andando",
           hitbox_anchor="bottom", hitbox_scale=(0.5, 0.9)):
    def setup(self):
        G.born(self, "robo")
        self.vel = Vec2(0, 0)
        self.dir = -1
        self.morto = False
        self.play("andando")

    def on_destroy(self):
        G.died(self, morte(self))

    def patrulha(self, esquerda, direita):
        self.__dict__["_limites"] = (esquerda, direita)

    def on_update(self, dt):
        if self.morto:
            return
        lados = self.touching_sides
        frente = self.hitbox.box.width * self.dir
        if "bottom" in lados and not self.floor_below(dx=frente):
            self.dir = -self.dir
            G.hit("robo.borda")
        elif ("left" in lados and self.dir < 0) or ("right" in lados and self.dir > 0):
            self.dir = -self.dir
            G.hit("robo.parede")
        self.flip_x = self.dir < 0
        self.vel.y = max(self.vel.y - GRAVIDADE * dt, -1400.0)
        self.move_by(60 * self.dir * dt, self.vel.y * dt)

    def abatido(self):
        if self.morto:
            return
        self.morto = True
        self.play("morto", loops=1)
        self.collidable = False
        self.after(0.6, self.destroy)
        G.hit("robo.abatido")


class Fruta(Sprite, source=CEREJA, group="fruta", hitbox_shape="circle"):
    def setup(self):
        G.born(self, "fruta")
        self.__dict__["_nasceu"] = clock.time

    def on_destroy(self):
        G.died(self, morte(self))


class Bandeira(Sprite, source=BANDEIRA, group="bandeira", hitbox_shape="rect"):
    def setup(self):
        G.born(self, "bandeira")
        self.tocada = False

    def on_destroy(self):
        G.died(self, morte(self))


class Nuvem(Sprite):
    def setup(self):
        G.born(self, "nuvem")

    def on_destroy(self):
        i = self.__dict__.get("_vaga")
        vivas = NUVENS["vivas"]
        if i in vivas:
            vivas[i] -= 1
        G.died(self, "endless")


def nuvem(slot):
    """Endless piece: the draws come from ``slot.rng`` (Guia: the same slot
    builds the same piece when it comes back)."""
    x = slot.left + slot.rng.uniform(0, 260)
    y = slot.rng.uniform(400, 540)
    alto = slot.rng.uniform(70, 120)
    sorteio = (round(x, 9), round(y, 9), round(alto, 9))
    antes = NUVENS["sorteios"].get(slot.i)
    if antes is not None:
        G.equal(sorteio, antes, "endless.same_slot_same_piece", slot=slot.i)
        NUVENS["revisitas"] += 1
        G.hit("endless.revisit")
    NUVENS["sorteios"][slot.i] = sorteio
    if NUVENS["left0"] is None and slot.i == 0:
        NUVENS["left0"] = slot.left
    if NUVENS["left0"] is not None:
        G.equal(slot.left, NUVENS["left0"] + slot.i * PASSO_NUVENS, "endless.slot_left", tol=1e-6)
    G.equal(slot.right - slot.left, PASSO_NUVENS, "endless.slot_width", tol=1e-9)
    n = Nuvem("backgrounds/mountains/clouds.png", height=alto, center=(x, y), layer="nuvens",
              group="nuvem")
    n.__dict__["_vaga"] = slot.i
    NUVENS["vivas"][slot.i] = NUVENS["vivas"].get(slot.i, 0) + 1
    G.hit("endless.build")
    return n


def _cobertura():
    """Guia, "Mundo sem fim": every slot of the view is built (it fills a
    little before a slot enters the screen)."""
    e = HUD.get("endless")
    if e is None or NUVENS["left0"] is None:
        return None
    v = canvas.layers["nuvens"].view
    i0 = math.floor((v.left - NUVENS["left0"]) / PASSO_NUVENS)
    i1 = math.floor((v.right - NUVENS["left0"]) / PASSO_NUVENS)
    for i in range(i0, i1 + 1):
        if NUVENS["vivas"].get(i, 0) < 1:
            return f"slot {i} in view [{v.left:.0f}, {v.right:.0f}] has no piece"
        G.equal(e.index_at(NUVENS["left0"] + (i + 0.5) * PASSO_NUVENS), i, "endless.index_at")
    return None


G.invariant("endless.view_covered", _cobertura)


# --- physics models -----------------------------------------------------------

PLATAFORMAS_RETAS = [it for it in _grupo_bruto("plataforma") if it["kind"] == "rect"
                     and not it.get("angle")]


def _chao():
    """``touching_sides`` against the level's own numbers (flat platforms):
    a "bottom" contact means the hitbox's foot line sits on a platform top,
    over it; a hitbox never sinks into one."""
    hs = list(group["heroi"])
    if not hs:
        return None
    h = hs[0]
    if h.morrendo:
        return None
    hb = h.hitbox.box
    for it in PLATAFORMAS_RETAS:
        cx, cy = it["center"]
        topo = cy + it["height"] / 2.0
        esq, dir_ = cx - it["width"] / 2.0, cx + it["width"] / 2.0
        sobre = min(hb.right, dir_) - max(hb.left, esq)
        if sobre > 6 and hb.bottom < topo - 3.0 and hb.top > topo:
            return f"hitbox sinks {topo - hb.bottom:.2f} into {it['name']}"
    for c in h.touching_contacts:
        if c.side != "bottom":
            continue
        G.hit("chao.contato")
        outro = c.other
        nome = PLATAFORMA_DE.get(G.serial(outro))
        it = ITENS.get(nome) if nome else None
        if it is not None and it["kind"] == "rect":
            topo_bruto = (it["center"][1] + it["height"] / 2.0) if not it.get("angle") else None
            if topo_bruto is not None:
                # The contact keeps a skin: a foot up to ~2 units over the top
                # still reads "bottom" (the ground pull reaches 16 units: Guia,
                # "Grudar no chão"); never below it by more than the slop.
                G.within(hb.bottom - topo_bruto, -1.0, 2.5, "ground.foot_on_top", plat=nome)
                so_chao = all(k.side == "bottom" and abs(k.slope_angle) < 1e-6
                              for k in h.touching_contacts)
                if so_chao:
                    # Only flat ground under it: bounce=0 took the vertical part.
                    G.check(abs(h.vel.y) < 1e-9, "ground.vel_y_zero", f"vel.y {h.vel.y} on {nome}")
            else:
                # Inside the ramp's run only: on its end corner the hero's
                # flat foot rests on a vertex (the contact's surface is the foot).
                cx, ang = it["center"][0], math.radians(it["angle"])
                meio = it["width"] / 2.0 * math.cos(ang)
                if cx - meio + 15 < h.center.x < cx + meio - 15:
                    G.equal(abs(c.slope_angle), abs(it["angle"]), "ground.slope_angle", tol=0.5,
                            plat=nome)
                    G.hit("chao.rampa")
    return None


G.invariant("ground.model", _chao)
PLATAFORMA_DE = {}


def _elevador():
    """Handle readout against the pose: what the lift moved last frame is
    ``h.velocity * dt`` (Guia, "Handle": units per second this frame)."""
    h, e = ELEVADOR["h"], HUD.get("elevador")
    if h is None or e is None or not e.is_alive:
        return None
    agora = (e.center.x, e.center.y)
    antes, dt_antes = ELEVADOR["antes"], ELEVADOR["dt"]
    ELEVADOR["antes"], ELEVADOR["dt"] = agora, clock.dt
    if antes is None:
        return None
    dx, dy = agora[0] - antes[0], agora[1] - antes[1]
    vx, vy = h.velocity.x * dt_antes, h.velocity.y * dt_antes
    G.hit("elevador.medido")
    return abs(dx - vx) < 1e-6 and abs(dy - vy) < 1e-6 or f"moved ({dx:.4f}, {dy:.4f}) vs velocity*dt ({vx:.4f}, {vy:.4f})"


G.invariant("handle.velocity_is_motion", _elevador)


def _robos():
    """``floor_below`` turns a walker at the edge (Guia, "Chão à frente"): a
    robot never leaves its stretch of ground and never sinks under it."""
    for r in group["robo"]:
        lim = r.__dict__.get("_limites")
        if lim is None or r.morto:
            continue
        G.hit("robo.medido")
        x, pe = r.center.x, r.hitbox.box.bottom
        if not (lim[0] - 20 <= x <= lim[1] + 20) or pe < 78.0:
            return f"robot at x {x:.1f}, foot {pe:.1f} left its ground {lim}"
    return None


G.invariant("robo.stays_on_ground", _robos)


def _drone():
    """The traveller sits on its track at the handle's ``u`` (two doors)."""
    d, h, trilho = HUD.get("drone"), HUD.get("drone_h"), HUD.get("drone_trilho")
    if d is None or h is None or not d.is_alive:
        return None
    x, y = trilho.at(h.u)
    G.hit("drone.medido")
    return abs(d.center.x - x) < 1e-6 and abs(d.center.y - y) < 1e-6 or f"drone at {d.center} vs track.at(u) {(x, y)}"


G.invariant("move_along.on_track", _drone)


def _cerejas():
    """A one-clip sheet autoplays; the shown frame is the clip's frame at the
    sprite's age, at fps (Guia, "Animar sprites"). The read sees the clock of
    the frame it is made in (``clock.time`` at ``G.frame()``), exactly."""
    for f in list(group["fruta"])[:3]:
        idade = G.t - f.__dict__["_nasceu"]     # the playhead reads the clock now
        if idade < 0:
            continue
        # whole steps of 1/fps in summed time, with the due rule's tolerance
        n = int(math.floor(idade * 20 * (1 + 1e-12) + 1e-9)) % 17
        G.hit("clip.medido")
        if int(f.frame) != n:
            return f"cherry shows frame {f.frame}, age {idade:.6f}s -> {n}"
    return None


G.invariant("clip.frame_at_age", _cerejas)


# --- rules -------------------------------------------------------------------

@collide("heroi", "fruta")
def pegou(heroi, fruta):
    s = G.serial(fruta)
    G.check(s not in MODELO["frutas"], "fruta.once", f"fruit #{s} twice")
    MODELO["frutas"].add(s)
    st.frutas += 1
    marcar_morte(fruta, "pega")
    fruta.destroy()
    G.hit("fruta.pega")


@collide("ataque", "robo")
def golpeou(heroi, robo, info):
    G.check(heroi.showing(GOLPE), "hitbox.active_only_on_strike", f"frame {heroi.frame}")
    G.check(info.a_hitbox is heroi.espada, "hitbox.part_is_sword")
    robo.abatido()


@collide("robo", "dor")
def robo_feriu(robo, heroi, info):
    G.check(info.b_hitbox is heroi.dor, "hitbox.part_is_hurtbox")
    if not robo.morto:
        heroi.ferir(robo)


@collide("heroi", "bandeira")
def checkpoint(heroi, bandeira):
    if bandeira.tocada:
        return
    bandeira.tocada = True
    hist = HUD["historia"]
    antes = len(hist)
    chao = bandeira.__dict__["_chao"]
    p = hist.snapshot(chao)
    G.equal((p.x, p.y), chao, "history.snapshot_copies")
    MODELO["checkpoints"] += 1
    G.equal(len(hist), min(3, antes + 1), "history.max_points")
    bandeira.flash(0.2)
    G.hit("checkpoint")


@collide("heroi", "saida")
def chegou(heroi, saida):
    if ATO["nome"] == "Fase" and not heroi.morrendo:
        st.chegou = True
        G.event("saida")
        trocar(Fim)


def saiu_historia(ponto):
    MODELO["saidas_hist"] += 1
    G.hit("history.leave")


@leave_playfield("heroi")
def caiu(heroi):
    G.check(heroi.center.y < canvas.playfield.bottom, "leave.below", f"y {heroi.center.y}")
    morrer(heroi)


def morrer(heroi):
    if heroi.morrendo:
        return
    heroi.morrendo = True
    st.mortes += 1
    MODELO["mortes"] += 1
    G.event("morte", x=round(heroi.center.x, 1), y=round(heroi.center.y, 1))
    label = f"morte{MODELO['mortes']}"
    COVER.start(G, label, out=True)
    alvo = (canvas.pan_x, canvas.pan_y)

    def renascer():
        COVER.done(G, label, out=True)
        hist = HUD["historia"]
        volta = hist.last if len(hist) else FASE["inicio"].center
        heroi.center = (volta.x, volta.y + 4)
        heroi.vel = Vec2(0, 0)
        G.equal((heroi.center.x, heroi.center.y), (volta.x, volta.y + 4), "respawn.at_checkpoint")
        heroi.morrendo = False
        CAMERA_MODELO["esperado"] = None
        canvas.pan_to(min(max(volta.x, W / 2), MUNDO_W - W / 2), H / 2)
        lab = f"renasce{MODELO['mortes']}"
        COVER.start(G, lab, out=False)
        canvas.fade_in(FADE, style="iris", center=heroi, on_done=lambda: COVER.done(G, lab, out=False))
        G.hit("respawn")

    canvas.fade_out(FADE, style="iris", center=heroi, on_done=renascer)


TROCA = {"pendente": False, "n": 0}


def trocar(ato):
    if TROCA["pendente"]:
        return
    TROCA["pendente"] = True
    TROCA["n"] += 1
    label = f"troca{TROCA['n']}"
    COVER.start(G, label, out=True)

    def feito():
        COVER.done(G, label, out=True)
        TROCA["pendente"] = False
        change_act(ato)

    canvas.fade_out(FADE, on_done=feito)


def entrar_ato(nome):
    anterior = ATO["nome"]
    if anterior is not None:
        G.check(all(G.alive(k) == 0 for k in ("fruta", "robo", "nuvem", "bandeira", "heroi")),
                "act.objects_removed")
        G.equal((canvas.zoom, canvas.pan_x, canvas.pan_y), (1.0, W / 2, H / 2), "act.camera_restored",
                tol=1e-9)
        G.check("nuvens" not in canvas.layers and "montanhas" not in canvas.layers,
                "act.layers_removed")
        G.equal(canvas.playfield.pad, 0.25, "act.playfield_restored", tol=1e-12)
    ATO.update(nome=nome, n=ATO["n"] + 1)
    CAMERA_MODELO["esperado"] = None
    ELEVADOR.update(h=None, antes=None, dt=0.0)
    HUD.clear()
    G.scope(nome)
    G.event("act", nome=nome)
    label = f"in{ATO['n']}"
    COVER.start(G, label, out=False)
    canvas.fade_in(FADE, on_done=lambda: COVER.done(G, label, out=False))


# --- acts --------------------------------------------------------------------

class Fase(Act):
    def setup(self):
        entrar_ato("Fase")
        st.chegou = False
        canvas.layers.create("montanhas", pan_response=RESPOSTA_MONTANHAS, below="default")
        for i, nome in enumerate(("mountains1", "mountains2", "mountains3", "mountains4")):
            Sprite(f"backgrounds/mountains/{nome}.png", height=H * 0.8,
                   center=(W * 0.4 + i * 520, H * 0.42), layer="montanhas")
        canvas.layers.create("nuvens", pan_response=RESPOSTA_NUVENS, below="montanhas")
        HUD["endless"] = Endless("nuvens", nuvem, step=PASSO_NUVENS, seed=7)
        G.equal(HUD["endless"].seed, 7, "endless.seed")
        for item in FASE.group("plataforma"):
            p = item.make(color="sienna")
            p.mass = STATIC
            PLATAFORMA_DE[G.serial(p)] = item.name
            G.check(p.tagged("plataforma"), "level.make_groups")
            if item.kind == "rect":
                G.equal((p.center.x, p.center.y, p.width, p.height, p.angle),
                        (item.center.x, item.center.y, item.width, item.height, item.angle),
                        "level.make_rect", tol=1e-9)
                cantos = sorted((round(c.x, 6), round(c.y, 6)) for c in p.corners)
                indep = sorted((round(x, 6), round(y, 6)) for x, y in
                               geom.rect_corners(item.center.x, item.center.y, item.width,
                                                 item.height, item.angle))
                G.equal(cantos, indep, "level.rect_corners", tol=1e-6)
        for item in FASE.group("decor"):
            s = item.make()
            G.equal((s.center.x, s.center.y), (item.center.x, item.center.y), "level.make_image",
                    tol=1e-9)
        trilho = FASE["elevador"].make()
        elev = Rect(center=trilho.at(0), width=120, height=20, color="peru", group="plataforma")
        elev.mass = STATIC
        PLATAFORMA_DE[G.serial(elev)] = "elevador"
        ELEVADOR.update(h=elev.move_along(trilho, time=2.5, loops="forever", yoyo=True),
                        antes=None, dt=0.0)
        HUD["elevador"] = elev
        drone_trilho = FASE["drone"].make()
        drone = Sprite("space/ufoYellow.png", height=36, center=drone_trilho.at(0))
        HUD["drone"], HUD["drone_trilho"] = drone, drone_trilho
        HUD["drone_h"] = drone.move_along(drone_trilho, time=6.0, loops="forever")
        for item in FASE.group("fruta"):
            Fruta(center=item.center)
        for item in FASE.group("checkpoint"):
            b = Bandeira(center=(item.center.x, item.center.y + 38))
            b.__dict__["_chao"] = (item.center.x, item.center.y)
        # floor_below follows the ramp up to the high platform's far edge.
        for item, (e, d) in zip(FASE.group("robo"), ((1250, 2345), (2460, 3260))):
            Robo(center=item.center).patrulha(e, d)
        for item in FASE.group("tocha"):
            Fire(center=(item.center.x, item.center.y + 18), radius=18)
        chuva = FASE["chuva"]
        Rain(center=chuva.center, width=chuva.width, height=chuva.height)
        Rect(center=(FASE["saida"].center.x, FASE["saida"].center.y + 60), width=40, height=120,
             color=Color("white").with_alpha(0.15), group="saida")
        heroi = Heroi(center=FASE["inicio"].center)
        HUD["heroi"] = heroi
        resolve(heroi, "plataforma", bounce=0.0)
        resolve("robo", "plataforma", bounce=0.0)
        rastro = Contrail(max_points=16, duration=0.4, fade=True, color="white", line_width=2)
        heroi.every(0.03, lambda: rastro.snapshot(heroi))
        HUD["rastro"] = rastro
        HUD["historia"] = History(max_points=3, on_leave=saiu_historia)
        faixa = canvas.ui_view.strip("top", 46).inset(8)
        grade = faixa.grid(5, 1, gap=6)
        HUD["celulas"] = []
        for cel in grade:
            cx, cy, cw, ch = geom.grid_cell(faixa.left, faixa.top, faixa.width, faixa.height,
                                            5, 1, 6, cel.col_index, cel.row_index)
            G.equal((cel.center.x, cel.center.y, cel.width, cel.height), (cx, cy, cw, ch),
                    "grid.cell", tol=1e-9)
            HUD["celulas"].append(Rect(box=cel, layer="ui", color=Color("gray").with_alpha(0.3)))
        placar = Text("", top_right=(W - 16, H - 60), font_size=16)
        placar["text"] @= lambda: f"Frutas {st.frutas}   Quedas {st.mortes}"
        HUD["placar"] = placar
        Vignette(amount=0.4)
        # A quarter-second metronome: 15 frames of 1/60 sum a hair short of
        # 0.25, the due rule's own case (PM8).
        h = every(0.25, self.tic)
        TIMERS.expect_every(G, "tic", h, 0.25, early=False, scope="Fase")
        PILOTO.update(fase=True)

    def tic(self):
        TIMERS.fired(G, "tic")

    def on_update(self, dt):
        h = HUD.get("heroi")
        if h is None:
            return
        if not h.morrendo:
            alvo = camera_alvo(h)
            canvas.pan_to(*alvo)
            CAMERA_MODELO["esperado"] = alvo
        canvas.playfield.set(canvas.game_view.outset(250))
        PILOTO.update(x=h.center.x, y=h.center.y, vy=h.vel.y,
                      chao="bottom" in h.touching_sides, morrendo=h.morrendo,
                      elevador_x=HUD["elevador"].center.x)


class Fim(Act):
    def setup(self):
        entrar_ato("Fim")
        G.check(st.chegou, "fim.chegou")
        Text("SAIDA!", center=(W / 2, H / 2), font_size=48)
        G.equal(st.frutas, len(MODELO["frutas"]), "fruta.count_kept")
        G.equal(st.mortes, MODELO["mortes"], "mortes.count_kept")
        h = self.after(1.0, self.fim)
        TIMERS.expect_after(G, "fim", h, 1.0, early=False, scope="Fim")

    def fim(self):
        TIMERS.fired(G, "fim")
        G.hit("fim")


def _historia():
    hist = HUD.get("historia")
    if hist is None:
        return None
    esperado_saidas = max(0, MODELO["checkpoints"] - 3)
    return (len(hist) <= 3 and MODELO["saidas_hist"] == esperado_saidas
            or f"History len {len(hist)}, left {MODELO['saidas_hist']} (model {esperado_saidas})")


G.invariant("history.model", _historia)


def _hud():
    p = HUD.get("placar")
    if p is None or not p.is_alive:
        return None
    esperado = f"Frutas {st.frutas}   Quedas {st.mortes}"
    return p.text == esperado or f"{p.text!r} vs {esperado!r}"


G.invariant("hud.fresh", _hud)
G.invariant("fruta.model", lambda: st.frutas == len(MODELO["frutas"])
            or f"st.frutas {st.frutas} vs {len(MODELO['frutas'])}")


def update(dt):
    G.frame()
    PILOTO["t"] = G.frame_no


run(Fase)
