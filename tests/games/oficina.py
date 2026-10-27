# harness: cwd=examples/media
"""Oficina — a game system test (tests/games/). Not an example, not a tutorial.

A workbench of pieces on a grid, wired by live formulas: two generators feed a
power cell (a ``State``), the power sizes a lamp, a laser crosses the pieces.
Checked while it runs by side models (tests/game_support.py) and by the driver
(tests/game_harness.py, tests/test_game_oficina*.py). Strategy:
design/Testing Design.md, "Game system tests".

What it leans on: ``@=`` chains across objects and a second ``State``,
constructor formulas, unlink / relink, ``@when`` / ``@on_change`` cascades, a
group formula, every widget kind (Slider float and int, CheckBox, DropDown,
TextInput, Button, Menu), the HUD column across act instances, drag / drop /
hover / click, ``Grid.cell_at``, the geometry helpers (``intersections``,
``intersection``, ``closest_point``, ``distance``, ``heading``, ``nearest``,
``middle_point``, ``Vec2``), collision queries (``raycast``, ``query_point``,
``test_collision`` on a ``Collider``), ``move_along`` a ``Track``, visuals
(``Fill``, ``Stroke``, ``Paint`` with ``Gradient`` / ``Texture``) checked by
pixels at checkpoints, ``Sound.bake`` through the whole effect catalog, a live
effect stack, ``audio.spectrum`` / ``amp_db`` / ``muted``, and a
``Microphone`` on the null backend.

PARAMS: none needed (the pilot drives it).
"""
import math

import miniaudio

from scena import *
from game_support import (ChangeModel, EdgeModel, Ledger, SoundModel, TimerModel, geom, reached)

PARAMS = globals().get("PARAMS", {})
G = Ledger("oficina", mark=globals().get("mark"))
TIMERS = G.model(TimerModel())
SONS = G.model(SoundModel())

W, H = 1000, 700
init(width=W, height=H, title="Oficina")
FUNDO = (26, 28, 34)
CASA = tuple(round(c + 0.06 * (255 - c)) for c in FUNDO)   # a cell rect over the wallpaper
Wallpaper(Color(FUNDO[0] / 255, FUNDO[1] / 255, FUNDO[2] / 255))

# --- the board ----------------------------------------------------------------

TABULEIRO = Box(center=(470, 330), width=560, height=420)
GRADE = TABULEIRO.grid(4, 3, gap=10)
COL0_DIREITA = TABULEIRO.left + (560 - 30) / 4.0      # generators in column 0 produce


def celula_de(x, y):
    """Grid arithmetic from the Guia ("Grid": row 0 on top, equal cells, gap
    between), independent of ``Grid.cell_at``: (col, row) or None in a gap."""
    cw, ch = (560 - 30) / 4.0, (420 - 20) / 3.0
    dx, dy = x - TABULEIRO.left, TABULEIRO.top - y
    if dx < 0 or dy < 0 or dx > 560 or dy > 420:
        return None
    col, ox = divmod(dx, cw + 10)
    row, oy = divmod(dy, ch + 10)
    if ox > cw or oy > ch:
        return None
    return int(col), int(row)


SINO = Sound("audio/impact_bell_heavy_000.ogg")
SINO_FX = SINO.bake(LowPass(cutoff=800), HighPass(cutoff=200), Echo(delay=0.1, decay=0.4),
                    Reverb(size=0.5, mix=0.3), Distortion(drive=2), Wavefold(drive=1.5))
G.check(SINO_FX.duration >= SINO.duration - 1e-9, "bake.tail_kept",
        f"{SINO_FX.duration} < {SINO.duration}")
G.equal(SINO.bake(transpose=5).duration, SINO.duration, "bake.transpose_keeps_length", tol=1e-3)
G.equal(SINO.bake(pitch=2).duration, SINO.duration / 2, "bake.pitch_rate", tol=2e-3)
ZUMBIDO = Sound("audio/fx2.ogg")

st.tensao = 4.0
st.ganho_a = 2
st.congelar = False
st.mudo = False
st.material = "fill"
st.semente = 7
st.sobrecargas = 0
OFICINA = State(name="oficina")
OFICINA.potencia = 0.0
MODELO = {"raio_congelado": None, "sobrecargas": 0, "soltas": 0, "semente_commits": 0,
          "hover": {}, "mudo_desde": None, "pixels": 0, "ato": 0, "coluna0": None}
ATO = {"nome": None}
PECAS = {}
PILOTO = {}
VISUAIS = {
    "fill": lambda: Fill("tomato"),
    "stroke": lambda: Stroke("navy", width=8),
    "paint": lambda: Paint(Gradient("sunset")),
    "gradiente": lambda: Paint(Gradient("red", "blue", angle=0), line=False),
    "textura": lambda: Paint(Texture("textures/Brick_01.png")),
}
MATERIAIS = list(VISUAIS)


def saida_esperada(g):
    """The generator formula, in plain Python (the twin)."""
    ganho = st.ganho_a if g is PECAS.get("ga") else 2.0
    return st.tensao * ganho if g.center.x < COL0_DIREITA else 0.0


def raio_formula():
    return 18 + OFICINA.potencia * 0.5


# --- reactive twin, read in alternating orders --------------------------------

def _gemeo():
    ga, gb, lamp = PECAS.get("ga"), PECAS.get("gb"), PECAS.get("lampada")
    if ga is None or not lamp.is_alive:
        return None
    ea = saida_esperada(ga) if ga.is_alive else 0.0
    eb = saida_esperada(gb) if gb.is_alive else 0.0
    pot = ea + eb
    # Read order is an axis (Testing Design, lessons): the link first on odd
    # frames, the source first on even ones.
    if G.frame_no % 2:
        r = lamp.radius
        p = OFICINA.potencia
    else:
        p = OFICINA.potencia
        r = lamp.radius
    if ga.is_alive:
        G.equal(float(ga.saida), ea, "link.generator_a", tol=1e-9)
    G.equal(float(p), pot, "link.state_power", tol=1e-9)
    if MODELO["raio_congelado"] is None:
        G.equal(r, 18 + pot * 0.5, "link.constructor_formula", tol=1e-9)
    else:
        G.equal(r, MODELO["raio_congelado"], "link.unlink_freezes", tol=1e-12)
    G.hit("twin.read")
    return None


G.invariant("link.twin", _gemeo)


def _grupo_formula():
    """The formula group follows the tags, which the drops set from the home
    cell (a piece being dragged keeps its tag until it lands)."""
    esperado = sum(1 for k in ("ga", "gb", "prisma", "lampada") if PECAS.get(k) is not None
                   and PECAS[k].is_alive and PECAS[k].__dict__["_casa"][0] < COL0_DIREITA)
    n = group["coluna0"].count
    return n == esperado or f"group['coluna0'] has {n}, column 0 holds {esperado}"


G.invariant("group.formula_live", _grupo_formula)


def _painel():
    t = PECAS.get("painel")
    if t is None or not t.is_alive:
        return None
    esperado = f"Tensao {st.tensao:.2f}  Potencia {OFICINA.potencia:.2f}"
    return t.text == esperado or f"{t.text!r} vs {esperado!r}"


G.invariant("hud.fresh", _painel)
SOBRE = G.model(EdgeModel("sobrecarga", lambda: OFICINA.potencia > 40))
POT = G.model(ChangeModel("potencia", lambda: OFICINA.potencia))
SEMENTE = G.model(ChangeModel("semente", lambda: st.semente))


# --- geometry: the engine against closed forms ---------------------------------

def vertices(peca):
    if isinstance(peca, Circle):
        return None
    if isinstance(peca, RegularPolygon):
        return [geom.rot(peca.center.x + peca.radius, peca.center.y, peca.angle + k * 360.0 / 6,
                         peca.center.x, peca.center.y) for k in range(6)]
    if isinstance(peca, Rect):
        return geom.rect_corners(peca.center.x, peca.center.y, peca.width, peca.height, peca.angle)
    return [(p.x, p.y) for p in peca.points]


def cortes(peca, a, b):
    v = vertices(peca)
    if v is None:
        return geom.seg_circle(a, b, peca.center, peca.radius)
    return geom.seg_poly(a, b, v)


def contem(peca, p):
    v = vertices(peca)
    if v is None:
        return geom.dist(p, peca.center) <= peca.radius + 1e-9
    return geom.point_in_poly(p, v)


def _mesmos(a, b, tol=1e-6):
    a, b = sorted(a), sorted(b)
    return len(a) == len(b) and all(geom.dist(p, q) <= tol for p, q in zip(a, b))


def _laser():
    laser, alvo = PECAS.get("laser"), PECAS.get("alvo")
    if laser is None or not laser.is_alive:
        return None
    a, b = (laser.p1.x, laser.p1.y), (laser.p2.x, laser.p2.y)
    G.equal(b, (alvo.center.x, alvo.center.y), "link.line_endpoint", tol=1e-9)
    vivas = [p for k, p in PECAS.items() if k in ("ga", "gb", "prisma", "lampada") and p.is_alive]
    for peca in vivas:
        eng = [tuple(p) for p in intersections(laser, peca)]
        ind = cortes(peca, a, b)
        G.check(_mesmos(eng, ind), "geom.intersections", f"{type(peca).__name__}: {eng} vs {ind}")
        G.hit(f"laser.hits{min(len(ind), 2)}")
    lamp = PECAS["lampada"]
    if lamp.is_alive:
        hits = geom.seg_circle(a, b, lamp.center, lamp.radius)
        corda = PECAS["corda"]
        if len(hits) == 2:
            G.check(_mesmos([(corda.p1.x, corda.p1.y), (corda.p2.x, corda.p2.y)], hits, tol=1e-6),
                    "geom.intersection_chord")
            G.hit("laser.chord")
        cp = closest_point(lamp, alvo)
        G.equal(tuple(cp), geom.closest_on_circle_disk(alvo, lamp.center, lamp.radius),
                "geom.closest_point_circle", tol=1e-9)
        G.equal(distance(alvo, lamp), geom.dist(alvo, lamp), "geom.distance", tol=1e-9)
        hx, hy = lamp.center.x - alvo.center.x, lamp.center.y - alvo.center.y
        if hx or hy:
            G.equal(heading(alvo, lamp), math.degrees(math.atan2(hy, hx)), "geom.heading", tol=1e-9)
        mx, my = middle_point(alvo, lamp)
        G.equal((mx, my), ((alvo.center.x + lamp.center.x) / 2, (alvo.center.y + lamp.center.y) / 2),
                "geom.middle_point", tol=1e-9)
    if vivas:
        perto = nearest(alvo, vivas)
        ind = min(vivas, key=lambda p: geom.dist(p, alvo))
        G.check(perto is ind or abs(geom.dist(perto, alvo) - geom.dist(ind, alvo)) < 1e-9,
                "geom.nearest")
        # raycast: the first body the segment meets (the pieces are enrolled)
        if not any(contem(p, a) for p in vivas):
            primeiro, t_min = None, None
            for p in vivas:
                for h in cortes(p, a, b):
                    t = geom.dist(a, h) / max(geom.dist(a, b), 1e-12)
                    if t_min is None or t < t_min:
                        primeiro, t_min = p, t
            hit = collision.raycast(a, p2=b)
            if primeiro in (PECAS.get("ga"), PECAS.get("gb")) and PECAS.get("corpo") is not None:
                primeiro = PECAS["corpo"]          # one body for the collision (Guia, "Collider")
            if primeiro is None:
                G.check(hit is None or hit[0] not in vivas, "query.raycast_miss", repr(hit)[:80])
            else:
                G.check(hit is not None and hit[0] is primeiro and abs(hit[1] - t_min) < 1e-4,
                        "query.raycast_first", f"{hit!r:.80} vs {type(primeiro).__name__} t={t_min:.5f}")
                G.hit("raycast.hit")
        corpo = PECAS.get("corpo")
        compostos = (PECAS.get("ga"), PECAS.get("gb"))
        dentro = {id(corpo) if p in compostos else id(p) for p in vivas if contem(p, alvo)}
        achados = {id(p) for p in collision.query_point(alvo) if p in vivas or p is corpo}
        G.check(achados == dentro, "query.point", f"{len(achados)} vs {len(dentro)}")
    return None


G.invariant("geom.laser", _laser)


def _corpo():
    corpo, lamp = PECAS.get("corpo"), PECAS.get("lampada")
    if corpo is None or not lamp.is_alive:
        return None
    partes = [p for p in (PECAS["ga"], PECAS["gb"]) if p.is_alive]

    def circulo_retangulo(centro, raio, r):
        lx, ly = geom.rot(centro.x, centro.y, -r.angle, r.center.x, r.center.y)
        qx = min(max(lx, r.center.x - r.width / 2), r.center.x + r.width / 2)
        qy = min(max(ly, r.center.y - r.height / 2), r.center.y + r.height / 2)
        return math.hypot(lx - qx, ly - qy) <= raio

    esperado = any(circulo_retangulo(lamp.center, lamp.radius - 1e-6, p) for p in partes)
    longe = all(not circulo_retangulo(lamp.center, lamp.radius + 2, p) for p in partes)
    info = test_collision(corpo, lamp)
    if esperado:
        G.check(info is not None, "collider.test_collision_hit")
        G.hit("collider.hit")
    elif longe:
        G.check(info is None, "collider.test_collision_miss")
    return None


G.invariant("collider.compound", _corpo)


def _sonda():
    s, h, trilho = PECAS.get("sonda"), PECAS.get("sonda_h"), PECAS.get("orbita")
    if s is None or not s.is_alive:
        return None
    x, y = trilho.at(h.u)
    return abs(s.center.x - x) < 1e-6 and abs(s.center.y - y) < 1e-6 or f"probe {s.center} vs at(u) {(x, y)}"


G.invariant("move_along.on_track", _sonda)


def _espectro():
    v = audio.level
    G.equal(amp_db(v), geom.amp_db(v), "audio.amp_db_closed_form", tol=1e-9)
    for i, x in enumerate(audio.spectrum(bins=8)):
        G.within(x, 0.0, 1.0, "audio.spectrum_range")
        G.equal(amp_db(x), geom.amp_db(x), "audio.amp_db_closed_form", tol=1e-9)
    if MODELO["mudo_desde"] is not None and G.t - MODELO["mudo_desde"] > 1.0:
        G.check(v < 0.02, "audio.muted_silences", f"level {v:.4f} after a second muted")
        G.hit("audio.mudo_medido")
    mic = PECAS.get("mic")
    if mic is not None:
        G.equal(mic.level, 0.0, "mic.null_level")
        G.check(all(x == 0 for x in mic.spectrum(bins=8)), "mic.null_spectrum")
    return None


G.invariant("audio.meters", _espectro)


# --- the pixels (the driver draws a checkpoint frame and calls this) ----------

def conferir_pixels(px):
    """``px(x, y)`` -> (r, g, b) of the drawn frame at a world point."""
    prisma = PECAS.get("prisma")
    if prisma is None or not prisma.is_alive:
        return
    MODELO["pixels"] += 1
    c = (prisma.center.x, prisma.center.y)
    mat = st.material
    meio = px(*c)
    if not prisma.visible:
        G.equal(meio, CASA, "pixel.hidden_is_background", tol=2)
    elif mat == "fill":
        G.equal(meio, (255, 99, 71), "pixel.fill_colour", tol=3)
    elif mat == "stroke":
        G.equal(meio, CASA, "pixel.stroke_leaves_inside", tol=2)
        # near a vertex, inside: within the 8-wide stroke of both edges
        borda = geom.rot(c[0] + prisma.radius * 0.95, c[1], prisma.angle, c[0], c[1])
        r, g, b = px(*borda)
        G.check(b > 90 and r < 60 and g < 60, "pixel.stroke_on_edge", f"edge {(r, g, b)}")
    elif mat == "gradiente":
        esq = px(c[0] - prisma.radius * 0.5, c[1])
        dir_ = px(c[0] + prisma.radius * 0.5, c[1])
        G.check(esq[0] > dir_[0] and esq[2] < dir_[2], "pixel.gradient_runs",
                f"left {esq} right {dir_}")
    elif mat in ("paint", "textura"):
        amostras = {px(c[0] + dx, c[1] + dy) for dx in (-20, 0, 20) for dy in (-20, 0, 20)}
        G.check(len(amostras) > 2, f"pixel.{mat}_varies", f"{len(amostras)} colours")
        G.check(meio != CASA, f"pixel.{mat}_drawn")
    G.hit(f"pixel.{mat if prisma.visible else 'hidden'}")


# --- rules ----------------------------------------------------------------------

@when(lambda: OFICINA.potencia > 40)
def sobrecarga():
    SOBRE.fired(G)
    st.sobrecargas += 1
    MODELO["sobrecargas"] += 1
    lamp = PECAS.get("lampada")
    if lamp is not None and lamp.is_alive:
        lamp.flash(0.2)


@on_change(lambda: OFICINA.potencia)
def mudou_potencia(valor):
    POT.fired(G, float(valor))
    h = PECAS.get("zumbido")
    if h is not None and not h.done:
        h.pitch = remap(valor, 0, 80, 0.8, 1.6)
        G.equal(h.pitch, 0.8 + valor / 80 * 0.8, "remap.linear", tol=1e-9)


@on_change(st["semente"])
def mudou_semente(valor):
    SEMENTE.fired(G, valor)
    MODELO["semente_commits"] += 1


@on_change(st["mudo"])
def mudou_mudo(valor):
    audio.muted = bool(valor)
    MODELO["mudo_desde"] = G.t if valor else None
    G.hit("widget.mudo")


@on_change(st["material"])
def mudou_material(valor):
    G.check(valor in MATERIAIS, "dropdown.value_is_option", repr(valor))
    w = PECAS.get("dd")
    if w is not None:
        G.equal(w.selected_index, MATERIAIS.index(valor), "dropdown.index")
    prisma = PECAS.get("prisma")
    if prisma is not None and prisma.is_alive:
        prisma.visual = VISUAIS[valor]()
    G.hit(f"material.{valor}")


@on_change(st["congelar"])
def mudou_congelar(valor):
    lamp, h = PECAS.get("lampada"), PECAS.get("zumbido")
    if lamp is None or not lamp.is_alive:
        return
    if valor:
        lamp["radius"].unlink()
        MODELO["raio_congelado"] = lamp.radius
        if h is not None and not h.done:
            lp = h.effects.add(LowPass(cutoff=400))
            SONS.fx_add(G, "zumbido", lp)
            lp.enabled = False
            lp.enabled = True
            PECAS["lp"] = lp
        G.hit("link.unlink")
    else:
        lamp["radius"] @= raio_formula
        MODELO["raio_congelado"] = None
        lp = PECAS.pop("lp", None)
        if lp is not None:
            lp.remove()
            SONS.fx_remove(G, "zumbido", lp)
            lp.remove()
            SONS.fx_remove(G, "zumbido", lp)
        G.hit("link.relink")


def soltar(peca, alvo, pos):
    """drag_to: snap to the cell under the drop (Grid.cell_at), or go home."""
    x, y = (pos.x, pos.y) if hasattr(pos, "x") else (pos[0], pos[1])
    pos = (x, y)
    cel = GRADE.cell_at(x, y)
    ind = celula_de(x, y)
    G.check((cel is None) == (ind is None), "grid.cell_at_matches", f"{pos} -> {cel} vs {ind}")
    if cel is not None and ind is not None:
        G.equal((cel.col_index, cel.row_index), ind, "grid.cell_at_index")
        peca.move_to(cel.center)
        peca.__dict__["_casa"] = (cel.center.x, cel.center.y)
        G.hit("drop.snap")
    else:
        casa = peca.__dict__.get("_casa")
        if casa is not None and peca.is_alive:
            peca.move_to(*casa)
        G.hit("drop.home")
    if peca.is_alive:
        if peca.center.x < COL0_DIREITA:
            peca.tag("col0")
        else:
            peca.untag("col0")
    h = play_sound(SINO_FX, volume=0.3, on_done=lambda n=MODELO["soltas"]: SONS.done(G, f"sino{n}"))
    SONS.started(G, f"sino{MODELO['soltas']}", h, None)
    MODELO["soltas"] += 1


def pairou(peca):
    rec = MODELO["hover"].setdefault(G.serial(peca), [])
    G.check(not rec or rec[-1] == "exit", "hover.alternates", f"{rec[-3:]}")
    rec.append("enter")
    G.check(contem(peca, (mouse.x, mouse.y)), "hover.pointer_inside",
            f"{type(peca).__name__} at {peca.center} pointer {(mouse.x, mouse.y)}")
    G.hit("hover.enter")


def saiu(peca):
    rec = MODELO["hover"].setdefault(G.serial(peca), [])
    G.check(rec and rec[-1] == "enter", "hover.alternates", f"{rec[-3:]}")
    rec.append("exit")
    G.hit("hover.exit")


def nascer(obj, kind):
    G.born(obj, kind)
    obj.on_destroy = lambda o, k=kind: G.died(o, o.__dict__.get("_morte_jogo", "ato"))


# --- acts ----------------------------------------------------------------------

class Bancada(Act):
    def setup(self):
        ATO["nome"] = "Bancada"
        MODELO["ato"] += 1
        MODELO["raio_congelado"] = None
        PECAS.clear()
        G.scope(f"Bancada{MODELO['ato']}")
        G.event("act", n=MODELO["ato"])
        st.congelar = False
        st.mudo = False
        for cel in GRADE:
            Rect(box=cel.inset(2), color=Color("white").with_alpha(0.06), layer=below("default"))
        celula = lambda c, r: GRADE.cell(c, r).center
        ga = Rect(center=celula(0, 0), width=90, height=60, color="dark orange", group=["peca", "gerador"])
        gb = Rect(center=celula(1, 1), width=90, height=60, color="goldenrod", group=["peca", "gerador"])
        ga["ganho"] @= lambda: st.ganho_a
        gb.ganho = 2.0
        for g in (ga, gb):
            g["saida"] @= (lambda g=g: st.tensao * g.ganho if g.center.x < COL0_DIREITA else 0.0)
        OFICINA["potencia"] @= lambda: ga.saida + gb.saida
        lampada = Circle(center=celula(2, 1), radius=lambda: 18 + OFICINA.potencia * 0.5,
                         color="light yellow", group="peca")
        prisma = RegularPolygon(n=6, center=celula(3, 2), radius=48, angle=10, group="peca")
        prisma.visual = VISUAIS[st.material]()
        PECAS.update(ga=ga, gb=gb, lampada=lampada, prisma=prisma)
        for k, p in (("ga", ga), ("gb", gb), ("lampada", lampada), ("prisma", prisma)):
            nascer(p, "peca")
            if k in ("lampada", "prisma"):
                # The generators collide as one body, through the Collider
                # below; a shape both collidable and in a Collider is two
                # bodies (finding AC10, Testing Design).
                p.collidable = True
            p.__dict__["_casa"] = (p.center.x, p.center.y)
            if p.center.x < COL0_DIREITA:
                p.tag("col0")
        group["coluna0"] @= lambda: group["peca"] & group["col0"]
        PECAS["corpo"] = Collider([ga, gb])
        lixeira = Rect(center=(920, 80), width=110, height=70, color="dark red")
        PECAS["lixeira"] = lixeira
        alvo = Anchor(860, 560, color="lime")
        PECAS["alvo"] = alvo
        laser = Line(p1=(40, 40), p2=lambda: alvo.center, color="red", line_width=2)
        PECAS["laser"] = laser
        PECAS["corda"] = Line(p1=lambda: intersection(laser, lampada, 0),
                              p2=lambda: intersection(laser, lampada, 1), color="cyan", line_width=4)
        orbita = Track.circle(center=(900, 360), radius=50)
        sonda = Circle(radius=6, color="white", center=orbita.at(0))
        PECAS["orbita"], PECAS["sonda"] = orbita, sonda
        PECAS["sonda_h"] = sonda.move_along(orbita, time=3.0, loops="forever")

        for p in (ga, gb, lampada, prisma):
            p.on_drag_to = soltar
            p.on_hover = pairou
            p.on_hover_exit = saiu

        @drop_by(lixeira)
        def jogou_fora(peca, onde, pos):
            if peca is PECAS.get("lampada") or not peca.is_alive:
                return
            if peca in (ga, gb):
                # What is left feeds the cell: unlink, then link anew (a second
                # @= on a linked field replaces it with a warning, by design).
                OFICINA["potencia"].unlink()
                if peca is gb:
                    OFICINA["potencia"] @= lambda: ga.saida
                else:
                    OFICINA["potencia"] @= lambda: gb.saida
                G.hit("link.relinked_source")
            peca.__dict__["_morte_jogo"] = "lixeira"
            peca.destroy()
            G.hit("drop.trash")

        @click(lampada)
        def clicou(lamp):
            st.laser = not st.laser
            laser.visible = st.laser
            G.hit("click.lampada")

        st.laser = True
        painel = Text("", top_left=(20, 120), font_size=16, stack=False)
        painel["text"] @= lambda: f"Tensao {st.tensao:.2f}  Potencia {OFICINA.potencia:.2f}"
        PECAS["painel"] = painel
        ui.stack_reset()
        primeiro = Slider(st["tensao"], label="Tensao", max_value=10)
        if MODELO["coluna0"] is None:
            MODELO["coluna0"] = (primeiro.box.left, primeiro.box.top)
        else:
            G.equal((primeiro.box.left, primeiro.box.top), MODELO["coluna0"], "act.column_restored")
        Slider(st["ganho_a"], label="Ganho A", min_value=1, max_value=5, only_int=True)
        ui.gap()
        CheckBox(st["congelar"], label="Congelar")
        CheckBox(st["mudo"], label="Mudo")
        PECAS["dd"] = DropDown(st["material"], options=MATERIAIS)
        ui.stack_column()
        PECAS["ti"] = TextInput(st["semente"], placeholder="semente", label="Semente", max_length=6)
        Button(label="Reset", on_click=self.perguntar)
        barras = []
        for i in range(8):
            barras.append(Rect(center=(640 + i * 22, 640), width=14, height=4, color="cyan",
                               layer="ui"))
        PECAS["barras"] = barras
        PECAS["zumbido"] = lampada.play_sound(ZUMBIDO, name="zumbido", loops="forever", volume=0.2)
        SONS.started(G, "zumbido", PECAS["zumbido"], None)
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        eco = mic.effects.add(Echo())
        G.check([id(e) for e in mic.effects] == [id(eco)], "mic.effects_stack")
        PECAS["mic"] = mic
        PECAS["clip"] = mic.record()
        G.check(mic.recording, "mic.recording")
        h = self.after(0.5, self.parar_gravacao)
        TIMERS.expect_after(G, f"grava{MODELO['ato']}", h, 0.5, early=False, scope="Bancada")
        h = every(0.25, self.tic)
        TIMERS.expect_every(G, f"tic{MODELO['ato']}", h, 0.25, early=False, scope="Bancada")
        PILOTO.update(ato=MODELO["ato"])

    def tic(self):
        TIMERS.fired(G, f"tic{MODELO['ato']}")

    def parar_gravacao(self):
        TIMERS.fired(G, f"grava{MODELO['ato']}")
        mic, clip = PECAS["mic"], PECAS["clip"]
        mic.stop()
        G.check(not mic.recording, "mic.stopped")
        G.check(clip.duration >= 0.0, "mic.clip_duration")
        if clip.duration > 0:
            play_sound(clip, volume=0.1)
        G.hit("mic.clip")

    def perguntar(self):
        G.hit("widget.reset")
        Menu(options=["Sim", "Nao"], title="Recomecar?", on_choose=self.escolheu)

    def escolheu(self, opcao):
        G.hit(f"menu.{opcao}")
        if opcao == "Sim":
            change_act(Bancada)

    def on_update(self, dt):
        for i, (b, v) in enumerate(zip(PECAS["barras"], audio.spectrum(bins=8))):
            b.height = 4 + 80 * amp_db(v)
        ti = PECAS.get("ti")
        if ti is not None and ti.focused:
            # Guia, "TextInput": while focused, text keys are the box's: keyp
            # does not see them.
            G.check(not keyp("R") and not keyp("4"), "textinput.swallows_keys")
        if keyp.once("H"):
            prisma = PECAS.get("prisma")
            if prisma is not None and prisma.is_alive:
                prisma.visible = not prisma.visible
                G.hit("hotkey.H")
        if keyp.once("R"):
            prisma = PECAS.get("prisma")
            if prisma is not None and prisma.is_alive:
                prisma.rotate_by(15)
            G.hit("hotkey.R")
        ti = PECAS.get("ti")
        PILOTO.update(foco=bool(ti and ti.focused))

    def on_destroy(self):
        # The power cell is the stage's; its formula reads this act's pieces:
        # the author unlinks it (else the change drops it with a warning).
        OFICINA["potencia"].unlink()
        mic = PECAS.get("mic")
        if mic is not None:
            mic.close()
            mic.close()          # a second close does nothing (Guia, "Microphone")
            G.hit("mic.closed")


def update(dt):
    G.frame()


run(Bancada)
