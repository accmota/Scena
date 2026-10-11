# harness: cwd=examples/media
"""Armada — a game system test (tests/games/). Not an example, not a tutorial.

A vertical shooter written to be checked while it runs: every rule it uses
reports to a ``Ledger`` (tests/game_support.py), side models predict what the
engine must do, and the driver (tests/game_harness.py, tests/test_game_armada*.py)
fails on any recorded failure. Strategy: design/Testing Design.md, "Game system
tests". The code is written the way an author writes Scena; the extra lines
(``G.…``, ``TIMERS.…``) are the instrumentation.

Acts: Titulo → Hangar → Setor (waves) → Chefe → Fim → Titulo, every change
through ``canvas.fade_out`` / ``fade_in`` (one iris). Stage (whole game): the
sky, Bloom, Vignette, the score rules, ``@when`` lives == 0, ``@on_change``.

PARAMS: waves, cols, rows, boss_hp, lives, god, fade, music.

Controls (the pilot drives them): LEFT / RIGHT move, SPACE fire, P pause.
"""
from random import random, uniform

from scena import *
from game_support import (ChangeModel, CoverModel, EdgeModel, Ledger, SoundModel,
                          TimerModel, TweenModel, geom, reached)

PARAMS = globals().get("PARAMS", {})
G = Ledger("armada", mark=globals().get("mark"))
TIMERS = G.model(TimerModel())
TWEENS = G.model(TweenModel())
SONS = G.model(SoundModel())

W, H = 1000, 750
init(width=W, height=H, title="Armada")

FADE = float(PARAMS.get("fade", 0.25))
WAVES = int(PARAMS.get("waves", 2))
COLS, ROWS = int(PARAMS.get("cols", 5)), int(PARAMS.get("rows", 2))
BOSS_HP = int(PARAMS.get("boss_hp", 14))
LIVES = int(PARAMS.get("lives", 3))
GOD = bool(PARAMS.get("god", False))
MUSIC = bool(PARAMS.get("music", True))

VEL_HEROI = 360
VEL_TIRO = float(PARAMS.get("vel_tiro", 620))
MERGULHO = float(PARAMS.get("mergulho", 0.35))
VEL_TIRO_INIMIGO = 300
CADENCIA = 0.15
PAD_SETOR = 0.1

# --- the stage: lives the whole game --------------------------------------

SkyGradient("night")
Stars(pan_response=0.0, density=0.6, scroll=(0.0, -40.0))
BLOOM = Bloom(intensity=0.4)
VINHETA = Vignette(amount=0.6)
PALCO_FX = [BLOOM, VINHETA]

SPACE = Sheet("shooter/sheet.xml")
BOOM = Sheet("misc/exp4.png", cols=12)
BOOM.clip("explode", list(range(12)), fps=24)
LASER = Sound("audio/laser4.wav").bake(Distortion(), Wavefold(), transpose=3)
EXPLOSAO = Sound("audio/explosion02.wav")
TRILHA_A = "audio/fx1.wav"
TRILHA_B = "audio/fx2.wav"
NAVES = ["playerShip1_red.png", "playerShip2_blue.png", "playerShip3_green.png"]
AREA = canvas.game_view.inset(40)
G.equal((AREA.left, AREA.bottom, AREA.right, AREA.top), (40, 40, W - 40, H - 40), "box.inset")


def curva(u):
    """The game's own ease (smoothstep): the tween model checks it exactly."""
    return u * u * (3.0 - 2.0 * u)


def jogo_novo():
    st.pontos = 0
    st.vidas = LIVES
    st.setor = 1
    st.venceu = False
    st.escudo = 0.0
    MODELO["pontos"] = 0


MODELO = {"pontos": 0}
st.recorde = 0
st.nave = NAVES[0]
st.crt = False
st.volume = 0.8
audio.volume = 0.8
jogo_novo()

# What the pilot and the probes read (plain dicts: the game's own notes).
ATO = {"nome": None, "objs": set(), "n": 0, "fx": [], "sons": []}
BOTOES = {}
WIDGETS = {}
HUD = {}
TROCA = {"pendente": None, "n": 0}
TIRO = {"ultimo": None, "segurando_desde": None, "nova": True, "ancora": None, "k": 0}
MODOS = {}


def nascer(obj, kind):
    """G.born plus the act it belongs to (the act change must remove it)."""
    s = G.born(obj, kind)
    ATO["objs"].add(s)
    return s


def morte(obj):
    return obj.__dict__.get("_morte_jogo", "ato")


def marcar_morte(obj, how):
    obj.__dict__["_morte_jogo"] = how


def pontuar(n, motivo):
    st.pontos += n
    MODELO["pontos"] += n
    G.hit(f"pontos.{motivo}")


# --- stage invariants -----------------------------------------------------

def _pop(kind, grp):
    def check():
        n = group[grp].count
        return n == G.alive(kind) or f"group[{grp!r}] has {n}, the game made {G.alive(kind)} alive"
    return check


for _k, _g in (("tiro", "tiro"), ("tiro_inimigo", "tiro_inimigo"), ("inimigo", "inimigo"),
               ("chefe", "chefe"), ("marca", "marca"), ("energia", "energia")):
    G.invariant(f"pop.{_k}", _pop(_k, _g))

group["alvos"] @= lambda: group["inimigo"] | group["chefe"]
G.invariant("group.formula", lambda: group["alvos"].count
            == group["inimigo"].count + group["chefe"].count or "alvos != inimigo + chefe")
G.invariant("score.model", lambda: st.pontos.value == MODELO["pontos"]
            or f"st.pontos {st.pontos.value} vs model {MODELO['pontos']}")
# A widget writes st.volume in the input poll (frame step 1); @on_change runs
# at flush (step 6): at G.frame() audio.volume is what the last flush set.
VOLUME = {"flushed": 0.8}
G.invariant("audio.volume", lambda: abs(audio.volume - VOLUME["flushed"]) < 1e-9
            or f"audio.volume {audio.volume} vs the last flushed {VOLUME['flushed']}")


def texto_placar():
    return f"Setor {st.setor}   Pontos {st.pontos}   Vidas {st.vidas}"


def _placar():
    p = HUD.get("placar")
    if p is None or not p.is_alive:
        return None
    return p.text == texto_placar() or f"placar {p.text!r} vs {texto_placar()!r}"


G.invariant("hud.fresh", _placar)


def _ccd():
    """A shot that survived the last frame did not travel deep through an
    enemy (Guia, "Objeto rápido": a fast traveller is checked along its whole
    path). Independent geometry: the shot's path last frame against each
    enemy's circle, at half its radius (enemies move too: a margin)."""
    for t in group["tiro"]:
        a0 = t.__dict__.get("_antes_jogo")
        if a0 is None:
            continue
        for e in group["inimigo"]:
            r = e.hitbox.box.width / 2.0
            p = geom.closest_on_seg(e.center, a0, (t.center.x, t.center.y))
            if geom.dist(p, e.center) < 0.5 * r and abs(t.center.y - a0[1]) > 0:
                G.hit("ccd.checked_deep")
                return f"shot path {a0} -> {(round(t.center.x, 1), round(t.center.y, 1))} crossed an enemy"
    G.hit("ccd.checked")
    return None


G.invariant("ccd.no_tunnel", _ccd)


def _rastro():
    r = HUD.get("rastro")
    if r is None:
        return None
    return len(r) <= 24 or f"Contrail holds {len(r)} > 24"


G.invariant("contrail.bound", _rastro)

PERDEU = G.model(EdgeModel("perdeu", lambda: st.vidas.value == 0))
PONTOS = G.model(ChangeModel("pontos", lambda: st.pontos.value))
COVER = G.model(CoverModel(lambda: canvas.covered))


@when(lambda: st.vidas == 0)
def perdeu():
    PERDEU.fired(G)
    st.venceu = False
    if ATO["nome"] in ("Setor", "Chefe"):
        heroi = group["heroi"].first if group["heroi"].count else None
        trocar(Fim, style="iris", center=heroi.center if heroi else None)


@on_change(st.pontos)
def mudou_pontos(valor):
    PONTOS.fired(G, valor)
    st.recorde = max(st.recorde, valor)


@on_change(st.volume)
def mudou_volume(valor):
    G.equal(valor, st.volume.value, "on_change.value_is_current")
    audio.volume = valor
    VOLUME["flushed"] = valor
    G.hit("widget.volume")


@leave_playfield("tiro", "tiro_inimigo")
def saiu(t):
    c = t.center
    pad = PAD_SETOR if ATO["nome"] in ("Setor", "Chefe") else 0.25
    box = (-pad * W, -pad * H, W + pad * W, H + pad * H)
    pf = canvas.playfield
    G.equal((pf.left, pf.bottom, pf.right, pf.top), box, "playfield.edges", tol=1e-9)
    fora = c.x < box[0] or c.y < box[1] or c.x > box[2] or c.y > box[3]
    G.check(fora, "leave.outside", f"{c.x:.1f},{c.y:.1f} inside {box}")
    marcar_morte(t, "saiu")
    t.destroy()


def raio(obj):
    """Bounding radius of what is drawn: half the diagonal of its box."""
    b = obj.box
    return (b.width ** 2 + b.height ** 2) ** 0.5 / 2.0


@collide("tiro", "inimigo")
def acertou(tiro, ini, info):
    G.check(tiro.is_alive and ini.is_alive, "collide.alive_args")
    G.check(info.a is tiro and info.b is ini, "collide.info_sides")
    if info.depth > 1e-6:
        # One payload, two doors (PM11): the query sees what the handler sees.
        q = test_collision(tiro, ini)
        G.check(q is not None and q.a is tiro and q.b is ini, "door.test_collision",
                f"query {q!r:.80}")
        if q is not None:
            G.equal((q.normal.x, q.normal.y), (info.normal.x, info.normal.y), "door.normal", tol=1e-6)
        G.check(geom.dist(tiro, ini) <= raio(tiro) + raio(ini) + 1.0, "collide.geometry",
                f"centers {geom.dist(tiro, ini):.1f} apart")
    else:
        G.hit("collide.swept")
        a0 = tiro.__dict__.get("_antes_jogo")
        if a0 is not None:
            G.check(geom.swept_circle_hits(a0, tiro.center, raio(tiro), ini.center, raio(ini) + 12),
                    "collide.swept_geometry")
    canvas.hit_at(info, angle=90)
    marcar_morte(tiro, "acerto")
    tiro.destroy()
    ini.atingido()


@collide("tiro_inimigo", "dor")
def ferido(tiro, heroi, info):
    G.check(info.b_hitbox is heroi.dor, "hitbox.part_answers", f"b_hitbox {info.b_hitbox!r:.60}")
    G.check(info.a_hitbox is None, "hitbox.body_side")
    marcar_morte(tiro, "acerto")
    tiro.destroy()
    heroi.levar_dano()


# --- actors ---------------------------------------------------------------

class Tiro(Sprite, source=SPACE, frame="laserBlue01.png", height=28, group="tiro"):
    def setup(self):
        nascer(self, "tiro")

    def on_destroy(self):
        G.died(self, morte(self))

    def on_update(self, dt):
        self.__dict__["_antes_jogo"] = (self.center.x, self.center.y)
        self.move_by(0, VEL_TIRO * dt)


class TiroInimigo(Sprite, source=SPACE, frame="laserRed01.png", height=24,
                  group="tiro_inimigo", art_angle=90):
    def setup(self):
        nascer(self, "tiro_inimigo")
        self.rumo = -90

    def mirar(self, angulo, lento=False):
        self.rumo = angulo
        self.angle = angulo
        if lento:
            self.time_scale = 0.6
            G.hit("time_scale.lento")

    def on_destroy(self):
        G.died(self, morte(self))

    def on_update(self, dt):
        G.equal(dt, clock.dt * self.time_scale, "time_scale.on_update_dt", tol=1e-12)
        self.move_by(angle=self.rumo, distance=VEL_TIRO_INIMIGO * dt)


class Heroi(Sprite, source=SPACE, frame="playerShip1_red.png", height=48, group="heroi",
            art_angle=90):
    def setup(self):
        nascer(self, "heroi")
        TIRO.update(ultimo=None, segurando_desde=None, nova=True, ancora=None, k=0)
        self.frame = st.nave.value
        self.dor = self.add_hitbox(group="dor", scale=0.55)
        self.ferido = False

    def on_destroy(self):
        G.died(self, morte(self))

    def on_update(self, dt):
        dx = 0
        if keyp("LEFT"):
            dx -= VEL_HEROI * dt
        if keyp("RIGHT"):
            dx += VEL_HEROI * dt
        self.move_by(dx, 0)
        lados = self.confine(AREA)
        if lados:
            G.hit("confine.edge")
            G.check(AREA.left - 1e-6 <= self.center.x <= AREA.right + 1e-6, "confine.clamped")
        if keyp("SPACE"):
            agora = clock.time
            if TIRO["segurando_desde"] is None:
                TIRO["segurando_desde"] = agora
                TIRO["nova"] = True
                h = after(2.0, self.dica, name="dica")
                TIMERS.expect_after(G, "dica", h, 2.0, early=False)
            pronto = self.ready("tiro", CADENCIA)
            self.modelo_ready(pronto, agora)
            if pronto:
                TIRO["ultimo"] = agora
                Tiro(center=self.center + (0, 30))
                play_sound(LASER, volume=0.2)
                G.hit("tiro.disparado")
        else:
            TIRO["segurando_desde"] = None

    def modelo_ready(self, pronto, agora):
        """``ready`` polled every frame: True on the first call, then a steady
        cadence (the k-th True on the first frame k intervals have passed since
        the hold's first True: "carries its overshoot like every", Scena Design
        "Clocks"); after a gap in polling it reopens one interval after the last
        True, without a burst (Guia, "ready")."""
        ult, a, k = TIRO["ultimo"], TIRO["ancora"], TIRO["k"]
        if TIRO["nova"]:
            esperado = ult is None or reached(agora - ult, CADENCIA)
            G.equal(pronto, esperado, "ready.reopen", agora=round(agora, 6))
            if pronto:
                TIRO.update(nova=False, ancora=agora, k=0)
            return
        due = (k + 1) * CADENCIA
        esperado = reached(agora - a, due)
        G.equal(pronto, esperado, "ready.cadence", elapsed=round(agora - a, 9), due=due)
        if pronto:
            G.check(not reached(agora - a - clock.dt, due), "ready.not_late")
            TIRO["k"] = k + 1

    def dica(self):
        TIMERS.fired(G, "dica")
        G.hit("dica")

    def levar_dano(self):
        if self.ferido or GOD or st.escudo.value > 0:
            G.hit("dano.ignorado")
            return
        st.vidas -= 1
        self.ferido = True
        self.blink(0.8)
        canvas.shake(6)
        cx = ATO.get("chroma")
        if cx is not None:
            cx.amount = 6
        h = self.after(0.8, self.curar, name="iframes")
        TIMERS.expect_after(G, "iframes", h, 0.8, early=False)
        G.hit("dano")

    def curar(self):
        TIMERS.fired(G, "iframes")
        self.ferido = False
        cx = ATO.get("chroma")
        if cx is not None:
            cx.amount = 0


class Explosao(Sprite, source=BOOM, height=90):
    def setup(self):
        self.play("explode", loops=1)
        self.__dict__["_quadro_jogo"] = -1
        self.after(0.7, self.destroy)

    def on_update(self, dt):
        f = int(self.frame)
        G.check(f >= self.__dict__["_quadro_jogo"], "clip.monotone", f"{self.__dict__['_quadro_jogo']} -> {f}")
        G.check(0 <= f <= 11, "clip.range", str(f))
        self.__dict__["_quadro_jogo"] = f
        if f == 11:
            G.hit("clip.last_frame")


class Marca(Circle, radius=5, color="gold", group="marca"):
    def setup(self):
        nascer(self, "marca")

    def on_destroy(self):
        G.died(self, morte(self))


class Energia(Orb, radius=16, color="gold", group="energia"):
    """Class keywords on a SpatialFx subclass (AC2: they used to raise)."""

    def setup(self):
        nascer(self, "energia")

    def on_destroy(self):
        G.died(self, morte(self))

    def on_collide(self, other, info):
        if not other.tagged("heroi") or not self.is_alive:
            return
        G.hit("orb.pego")
        st.escudo = 1.0
        h = tween(st["escudo"], 0.0, time=3.0, ease=curva, name="escudo",
                  on_done=lambda: TWEENS.done(G, "escudo"))
        TWEENS.expect(G, "escudo", lambda: st.escudo.value, 1.0, 0.0, 3.0, ease=curva, early=False)
        ATO["tweens"] = ATO.get("tweens", []) + ["escudo"]
        G.check(not h.done, "tween.handle")
        marcar_morte(self, "pego")
        self.destroy()


def soltar_orbe():
    TIMERS.fired(G, "orbe")
    x = uniform(120, W - 120)
    o = Energia(center=(x, H + 10))
    G.equal(o.radius, 16.0, "fx.class_default", tol=1e-9)
    h = tween(o.center, (x, -60), time=4.0, on_done=lambda o=o: _orbe_fim(o))
    G.check(not h.done, "tween.point")


def _orbe_fim(o):
    if o.is_alive:
        marcar_morte(o, "caiu")
        o.destroy()


class Inimigo(Sprite, source=SPACE, height=40, group="inimigo", art_angle=270,
              hitbox_shape="circle"):
    valor = 100

    def setup(self):
        nascer(self, "inimigo")
        MODOS[G.serial(self)] = [None]

    def on_destroy(self):
        G.died(self, morte(self))

    def _modo(self, nome):
        hist = MODOS[G.serial(self)]
        ok = {None: ("chegando",), "chegando": ("formacao", "morrendo"),
              "formacao": ("mergulho", "morrendo"), "mergulho": ("formacao", "morrendo"),
              "morrendo": ()}
        G.check(nome in ok.get(hist[-1], ()), "mode.transition", f"{hist[-1]} -> {nome}")
        hist.append(nome)
        G.hit(f"mode.{nome}")

    def entrar(self, vaga, fase):
        self.vaga = (vaga[0], vaga[1])
        self.fase = fase
        self.mode = self.chegando

    @on_mode
    def chegando(self):
        self._modo("chegando")
        self.center = (self.vaga[0], H + 60)
        self.fade_in(0.3)
        self.move_to(self.vaga[0], self.vaga[1], time=1.0, ease="ease_out", then=self.formacao)

    @on_mode
    async def formacao(self):
        self._modo("formacao")
        h = every(uniform(1.8, 3.2), self.atirar)
        self.__dict__["_handles_jogo"] = [h]
        self.move_along(Track.eight(width=40, height=12), time=3.0, loops="forever", phase=self.fase)
        while True:
            await wait(uniform(2.0, 4.5))
            if chance(MERGULHO) and group["heroi"].count:
                self.mode = self.mergulho
                return

    @exit_mode(formacao)
    def saiu_da_formacao(self):
        hs = self.__dict__.get("_handles_jogo", [])
        G.hit("exit_mode.formacao")
        LATER.append((G.frame_no + 1, lambda hs=hs: [G.check(h.cancelled, "mode.scope_cancels",
                                                                "every from formacao still running")
                                                        for h in hs]))

    @on_mode
    async def mergulho(self):
        self._modo("mergulho")
        alvo = group["heroi"].nearest(self)
        if alvo is None:
            self.mode = self.formacao
            return
        t_move, t_wait = uniform(0.7, 1.4), uniform(0.5, 1.6)
        if abs(t_move - t_wait) < 0.1:
            t_wait += 0.25
        hm = self.move_to(alvo.center.x, alvo.center.y + 220, time=t_move, ease="ease_in", face=True)
        hw = wait(t_wait)
        i = await race(hm, hw)
        G.equal(i, 0 if t_move < t_wait else 1, "race.winner")
        G.check((hw if i == 0 else hm).cancelled, "race.loser_cancelled")
        G.hit(f"race.{i}")
        G.hit("race")
        self.atirar(lento=True)
        await self.move_to(self.vaga[0], self.vaga[1], time=0.9, face=True)
        self.reset_rotation()
        self.mode = self.formacao

    def atirar(self, lento=False):
        if not group["heroi"].count:
            return
        t = TiroInimigo(center=self.center + (0, -22))
        if lento:
            t.mirar(heading(self, group["heroi"].first), lento=True)

    def atingido(self):
        if self.mode != self.morrendo:
            self.mode = self.morrendo

    @on_mode
    def morrendo(self):
        self._modo("morrendo")
        pontuar(self.valor, "inimigo")
        abate(self)
        self.dissolve_out(0.3, on_done=self.destroy)


def abate(ini):
    Explosao(center=ini.center)
    canvas.burst_at(ini, radius=40)
    m = ATO.get("marcas")
    if m is not None:
        m.add(Marca(center=ini.center))
        G.hit("history.add")
    tocar_explosao(0.4)


def tocar_explosao(volume):
    ATO["nsom"] = ATO.get("nsom", 0) + 1
    label = f"boom{ATO['n']}.{ATO['nsom']}"
    h = play_sound(EXPLOSAO, volume=volume, on_done=lambda: SONS.done(G, label))
    SONS.started(G, label, h, EXPLOSAO.duration)
    ATO["sons"].append(label)
    return h, label


def montar_onda(n):
    caixa = Box(center=(W / 2, 560), width=620, height=150)
    grade = caixa.grid(COLS, ROWS, gap=14)
    frota = ("enemyGreen1.png", "enemyRed1.png", "enemyBlue1.png", "enemyBlack1.png")
    i = 0
    for linha, celulas in enumerate(grade.rows):
        for celula in celulas:
            cx, cy, cw, ch = geom.grid_cell(caixa.left, caixa.top, 620, 150, COLS, ROWS, 14,
                                            celula.col_index, celula.row_index)
            G.equal((celula.center.x, celula.center.y), (cx, cy), "grid.cell_center", tol=1e-9)
            G.equal((celula.width, celula.height), (cw, ch), "grid.cell_size", tol=1e-9)
            G.check(grade.cell_at(cx, cy).col_index == celula.col_index, "grid.cell_at")
            e = Inimigo(frame=frota[linha % len(frota)])
            e.entrar((cx, cy), fase=(i * 0.13) % 1.0)
            i += 1
    G.hit("onda")


# --- the boss -------------------------------------------------------------

class Chefe(Sprite, source=SPACE, frame="ufoRed.png", height=120, group="chefe",
            hitbox_shape="circle", hitbox_scale=0.75):
    def setup(self):
        nascer(self, "chefe")
        self.vida = BOSS_HP
        # The core hangs below the 91 px frame (a part may pass the frame's
        # edge: Guia, "Caixas de ataque"), clear of the body's circle.
        self.fraco = self.add_hitbox(group="ponto_fraco", px_circle=(45.5, 104, 15))
        self.golpes = {"fraco": 0, "casco": 0, "torre": 0}
        self.mode = self.chegando

    def on_destroy(self):
        G.died(self, morte(self))

    @on_mode
    def chegando(self):
        G.event("chefe.chegando")
        self.move_to(W / 2, 560, time=1.5, ease="ease_out", then=self.lutando)

    @on_mode
    def lutando(self):
        G.event("chefe.lutando")
        self.move_along(Track.eight(width=460, height=80, center=(W / 2, 560)), time=6.0,
                        loops="forever")
        h = every(1.4, self.rajada)
        TIMERS.expect_every(G, "rajada", h, 1.4, early=False, scope="Chefe")

    def rajada(self):
        TIMERS.fired(G, "rajada")
        for angulo in (-120, -105, -90, -75, -60):
            TiroInimigo(center=self.center + (0, -50)).mirar(angulo)

    def dano(self, onde, n):
        if self.mode != self.lutando:
            return
        self.golpes[onde] += 1
        self.vida -= n
        G.equal(self.vida, BOSS_HP - 3 * self.golpes["fraco"] - self.golpes["casco"]
                - self.golpes["torre"], "boss.hp_model")
        self.flash(0.08)
        if self.vida <= BOSS_HP // 2 and ATO.get("faiscas") is None:
            ATO["faiscas"] = Sparks(center=lambda: self.center, radius=40, rate=30)
            G.hit("sparks")
        if self.vida <= 0:
            self.mode = self.morrendo

    @on_mode
    async def morrendo(self):
        pontuar(5000, "chefe")
        G.event("chefe.morrendo")
        h, label = tocar_explosao(0.6)
        eco = h.effects.add(Echo(delay=0.15, decay=0.4))
        SONS.fx_add(G, label, eco)
        sala = h.effects.add(Reverb(size=0.8, mix=0.4))
        SONS.fx_add(G, label, sala)
        eco.remove()
        SONS.fx_remove(G, label, eco)
        eco.remove()
        SONS.fx_remove(G, label, eco)      # a second remove does nothing
        SONS._s[label]["len"] = None        # a reverb tail: no length to check
        for _ in range(4):
            canvas.explosion_at(self.center + (uniform(-50, 50), uniform(-40, 40)), amount=0.7)
            await wait(0.2)
        for t in ATO.get("torres_shapes", ()):
            if t.is_alive:
                t.destroy()
        faiscas = ATO.get("faiscas")
        if faiscas is not None and faiscas.is_alive:
            faiscas.destroy()          # it follows the boss: it goes before the boss does
        Fire(center=self.center, radius=40)
        self.dissolve_out(0.5, on_done=self.destroy)


@collide("tiro", "chefe")
def acertou_chefe(tiro, chefe, info):
    if not tiro.is_alive:
        G.fail("collide.dead_shot")
        return
    G.check(info.b_hitbox is None, "hitbox.body_answers_chefe")
    marcar_morte(tiro, "acerto")
    tiro.destroy()
    chefe.dano("casco", 1)


@collide("tiro", "ponto_fraco")
def acertou_fraco(tiro, chefe, info):
    if not tiro.is_alive:
        G.fail("collide.dead_shot")
        return
    G.check(info.b_hitbox is chefe.fraco, "hitbox.weak_point_answers")
    marcar_morte(tiro, "acerto")
    tiro.destroy()
    chefe.dano("fraco", 3)
    G.hit("chefe.fraco")


# --- act bookkeeping -----------------------------------------------------

LATER = []


def _later():
    keep = []
    for due, fn in LATER:
        if due <= G.frame_no:
            fn()
        else:
            keep.append((due, fn))
    LATER[:] = keep


def trocar(ato, style="fade", center=None):
    """Every act change goes through the cover (Guia, "Transições")."""
    if TROCA["pendente"] is not None:
        G.hit("troca.ignorada")
        return
    TROCA["n"] += 1
    label = f"out{TROCA['n']}"
    TROCA["pendente"] = ato.__name__
    COVER.start(G, label, out=True)

    def feito():
        COVER.done(G, label, out=True)
        TROCA["pendente"] = None
        change_act(ato)

    if center is not None:
        canvas.fade_out(FADE, style=style, center=center, on_done=feito)
        G.hit("cover.iris")
    else:
        canvas.fade_out(FADE, style=style, on_done=feito)


def entrar_ato(nome):
    """The Guia's act-change table ("o palco e o ato"), one check per row."""
    anterior = ATO["nome"]
    # Sai: every object the previous act made is gone (on_destroy ran).
    vivos = {s for s in ATO["objs"] if any(s in G.alive_serials(k) for k in
                                          ("tiro", "tiro_inimigo", "inimigo", "chefe", "marca",
                                           "energia", "heroi"))}
    G.check(not vivos, "act.objects_removed", f"{len(vivos)} objects of {anterior} still alive")
    if anterior is not None:
        TIMERS.retire(G, anterior)
        for t in ATO.get("tweens", []):
            TWEENS.cancel(t)
        for label in ATO["sons"]:
            SONS.cancelled(label)       # its owner ended: on_done must not run
        for h in ATO.get("handles_ato", []):
            G.check(h.cancelled or h.done, "act.handles_cancelled")
        # Volta: posts, camera, playfield and clock are what the stage left.
        G.check([id(e) for e in canvas.effects] == [id(e) for e in PALCO_FX], "act.effects_restored",
                f"{[type(e).__name__ for e in canvas.effects]}")
        G.equal((canvas.zoom, canvas.pan_x, canvas.pan_y), (1.0, W / 2, H / 2), "act.camera_restored",
                tol=1e-9)
        G.equal(canvas.playfield.pad, 0.25, "act.playfield_restored", tol=1e-12)
        G.equal(clock.scale, 1.0, "act.clock_restored")
        # Fica: st (the score crosses the change).
        G.equal(st.pontos.value, MODELO["pontos"], "act.st_kept")
    ATO.update(nome=nome, objs=set(), n=ATO["n"] + 1, sons=[], tweens=[], handles_ato=[])
    for k in ("chroma", "marcas", "faiscas", "torres_shapes"):
        ATO.pop(k, None)
    HUD.clear()
    BOTOES.clear()
    WIDGETS.clear()
    G.scope(nome)
    G.event("act", nome=nome)
    label = f"in{ATO['n']}"
    COVER.start(G, label, out=False)
    canvas.fade_in(FADE, on_done=lambda: COVER.done(G, label, out=False))


# --- acts -----------------------------------------------------------------

class Titulo(Act):
    def setup(self):
        entrar_ato("Titulo")
        Text("ARMADA", center=(W / 2, H * 0.68), font_size=72, color="gold")
        BOTOES["jogar"] = SpriteButton("k-rolling-ball/button_yellow.png", center=(W / 2, H * 0.40),
                                       width=150, label="JOGAR", label_inset=(0, 0, 0, 8),
                                       on_click=self.jogar)
        self.cliques = 0

    def jogar(self):
        self.cliques += 1
        G.hit("spritebutton.click")
        jogo_novo()
        trocar(Hangar)


class Hangar(Act):
    def setup(self):
        entrar_ato("Hangar")
        Text("HANGAR", center=(W / 2, H * 0.8), font_size=48)
        WIDGETS["nave"] = DropDown(st.nave, options=NAVES)
        WIDGETS["crt"] = CheckBox(st.crt, label="CRT")
        WIDGETS["volume"] = Slider(st.volume, label="Volume", max_value=1)
        WIDGETS["lancar"] = Button(label="LANCAR", on_click=self.lancar)
        self.trocas_nave = 0

    @on_change(lambda self: st.nave)
    def nave_mudou(self, valor):
        G.check(valor in NAVES, "dropdown.value_is_option", repr(valor))
        G.equal(WIDGETS["nave"].selected_index, NAVES.index(valor), "dropdown.index")
        G.hit("widget.nave")

    @on_change(lambda self: st.crt)
    def crt_mudou(self, valor):
        G.check(isinstance(valor, bool), "checkbox.bool")
        G.hit("widget.crt")

    def lancar(self):
        G.hit("widget.lancar")
        trocar(Setor, style="iris", center=(W / 2, 80))


class Pausador(Entity):
    @on_mode
    async def pausa(self):
        G.hit("pausa")
        musica = ATO.get("musica")
        lp = None
        if musica is not None and not musica.done:
            lp = musica.effects.add(LowPass(cutoff=500))
            SONS.fx_add(G, ATO["musica_label"], lp)
        metro = ATO["metronomo"]
        metro.pause()
        resto = metro.remaining
        px = Pixelate(cell=6)
        escolha = await Menu(options=["Continuar", "Desistir"], title="Pausa", pause=True)
        G.check(not clock.paused, "menu.unpauses")
        G.equal(metro.remaining, resto, "handle.pause_holds", tol=1e-12)
        G.check(metro.paused, "handle.paused_flag")
        metro.resume()
        px.remove()
        if lp is not None and not musica.done:
            lp.remove()
            SONS.fx_remove(G, ATO["musica_label"], lp)
        G.hit(f"menu.{escolha}")
        if escolha == "Desistir":
            st.vidas = 0
        self.mode = None


class Setor(Act):
    def setup(self):
        entrar_ato("Setor")
        canvas.playfield.pad = PAD_SETOR
        placar = Text("", top_left=(16, H - 12), font_size=18)
        placar["text"] @= texto_placar
        HUD["placar"] = placar
        heroi = Heroi(center=(W / 2, 80))
        Jet(p1=lambda: heroi.center - (0, 22), p2=lambda: heroi.center - (0, 64), width=10)
        rastro = Contrail(max_points=24, duration=0.5, fade=True, color="sky blue", line_width=3)
        heroi.every(0.04, lambda: rastro.snapshot(heroi))
        HUD["rastro"] = rastro
        ATO["marcas"] = History(max_points=5, on_leave=lambda m: G.hit("history.leave"))
        ATO["chroma"] = Chroma(amount=0)
        self.wash = Wash(intensity=0, color=(1.0, 0.2, 0.2))
        if st.crt.value:
            Crt(amount=0.6)
            G.hit("post.crt")
        Rect(center=(760, 80), width=160, height=70, color=Color("teal").with_alpha(0.25),
             group="zona")
        Portal(center=(W / 2, H - 60), radius=50)
        self.pausador = Pausador()
        h = every(1.0, self.tic)
        TIMERS.expect_every(G, "metronomo", h, 1.0, early=False, scope="Setor")
        ATO["metronomo"] = h
        ATO["handles_ato"].append(h)
        h = every(3.0, soltar_orbe)
        TIMERS.expect_every(G, "orbe", h, 3.0, early=False, scope="Setor")
        if MUSIC:
            # self.play_sound: the act owns the slot, so the mode's crossfade
            # below replaces it (a loose call here and one in the mode are two
            # owners and two slots: finding AC5, Testing Design).
            ATO["musica"] = self.play_sound(TRILHA_A, name="musica", loops="forever", volume=0.3)
            ATO["musica_label"] = "musica_a"
            SONS.started(G, "musica_a", ATO["musica"], None, slot="musica")
        self.dentro = 0

        @collide("heroi", "zona")
        def entrou(heroi, zona):
            self.dentro += 1
            G.check(self.dentro == 1, "collide.enter_exit_alternate", f"{self.dentro}")
            G.hit("zona.enter")

        @collide_stay("heroi", "zona")
        def ficou(heroi, zona, info):
            G.check(self.dentro == 1, "collide.stay_inside")
            G.hit("zona.stay")

        @collide_exit("heroi", "zona")
        def saiu_zona(heroi, zona, info):
            self.dentro -= 1
            G.check(self.dentro == 0, "collide.enter_exit_alternate", f"{self.dentro}")
            G.check(info.point is None, "collide.exit_no_point")
            G.hit("zona.exit")

        self.mode = self.jogando

    def tic(self):
        TIMERS.fired(G, "metronomo")

    def on_update(self, dt):
        self.wash.intensity = 0.25 if st.vidas.value == 1 else 0.0
        if keyp.once("P") and self.pausador.mode is None:
            self.pausador.mode = self.pausador.pausa

    @on_mode
    async def jogando(self):
        for onda in range(WAVES):
            st.setor = onda + 1
            faixa = Text(f"SETOR {onda + 1}", center=(W / 2, H / 2), font_size=40)
            await wait(0.8)
            faixa.dissolve_out(0.3, on_done=faixa.destroy)
            montar_onda(onda)
            await until_empty("inimigo")
            G.equal(group["inimigo"].count, 0, "until_empty.empty")
            if onda == 0 and MUSIC and ATO.get("musica") is not None:
                velha = ATO["musica"]
                ATO["musica"] = self.play_sound(TRILHA_B, name="musica", loops="forever", volume=0.3,
                                                crossfade=0.5)
                ATO["musica_label"] = "musica_b"
                SONS.started(G, "musica_b", ATO["musica"], None, slot="musica")
                LATER.append((G.frame_no + 60, lambda v=velha: G.check(v.done, "sound.crossfade_ends_old")))
                G.hit("sound.crossfade")
        await wait(0.4)
        trocar(Arena)



class Arena(Act):
    """The boss act (``Chefe`` names the boss's class)."""

    def setup(self):
        entrar_ato("Chefe")
        canvas.playfield.pad = PAD_SETOR
        placar = Text("", top_left=(16, H - 12), font_size=18)
        placar["text"] @= texto_placar
        HUD["placar"] = placar
        Heroi(center=(W / 2, 80))
        chefe = Chefe(center=(W / 2, H + 100))
        torre_a = Rect(center=lambda: (chefe.center.x - 95, chefe.center.y - 10), width=34,
                       height=34, color="dim gray")
        torre_b = Circle(center=lambda: (chefe.center.x + 95, chefe.center.y - 10), radius=18,
                         color="dim gray")
        ATO["torres_shapes"] = (torre_a, torre_b)
        torres = Collider([torre_a, torre_b])

        @collide(torres, "tiro")
        def acertou_torre(me, tiro, info):
            G.check(me is torres, "collider.me_is_body")
            G.check(info.a is torres or info.a in (torre_a, torre_b), "collider.info_a")
            if not tiro.is_alive or not chefe.is_alive:
                return
            marcar_morte(tiro, "acerto")
            tiro.destroy()
            chefe.dano("torre", 1)
            G.hit("collider.hit")

        clock.scale = 0.8
        G.hit("clock.slowmo")
        self.mode = self.batalha

    @on_mode
    async def batalha(self):
        t0 = clock.time
        hs = [canvas.zoom_to(1.12, time=0.6), canvas.pan_to(W / 2, H / 2 + 30, time=0.6)]
        await parallel(*hs)
        G.check(all(h.done for h in hs), "parallel.all_done")
        G.check(reached(clock.time - t0, 0.6), "parallel.waited", f"{clock.time - t0}")
        G.event("parallel")
        clock.scale = 1.0
        await until_empty("chefe")
        G.event("chefe.vazio")
        st.venceu = True
        await wait(0.4)
        G.event("batalha.fim")
        trocar(Fim)



class Fim(Act):
    def setup(self):
        entrar_ato("Fim")
        st.recorde = max(st.recorde, st.pontos)
        G.check(st.recorde.value >= st.pontos.value, "st.recorde")
        msg = "VITORIA" if st.venceu.value else "FIM DE JOGO"
        Text(msg, center=(W / 2, H * 0.6), font_size=60)
        if st.venceu.value:
            canvas.fireworks_at((W / 2, H * 0.6))
        h = self.after(1.2, self.voltar)
        TIMERS.expect_after(G, "fim", h, 1.2, early=False, scope="Fim")

    def voltar(self):
        TIMERS.fired(G, "fim")
        G.hit("fim.voltou")
        trocar(Titulo)



def update(dt):
    G.frame()
    _later()
    G.within(canvas.covered, 0.0, 1.0, "cover.range_update")


run(Titulo)
