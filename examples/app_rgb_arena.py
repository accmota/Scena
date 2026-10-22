"""Arena RGB — física virtual com um trio de cargas.

Partículas com vetor RGB e intensidade, desenhadas como GlowSpot.
R atrai G, G atrai B, B atrai R; no outro sentido cada um repele o
anterior. A força escala com a intensidade das duas, como um campo
elétrico de três pólos em vez de + e −. A arena é ilimitada; um poço
puxa tudo para o centro.

Controles
---------
  painel    Criar, Deletar, Resetar, Rodar/Pausar
            R / G / B / Intensidade
            Centro, Atração, Repulsão, Potência, Visual
  clique    seleciona a partícula (o anel fica visível)
  arraste   move a partícula
  SPACE     rodar / pausar
  wheel     zoom da câmera

Uso
---
    python examples/app_rgb_arena.py
"""
from math import cos, hypot, sin
from random import uniform

from scena import *

W, H = 1100, 760
init(width=W, height=H, title="Arena RGB", window_scale=1.0)
canvas.background = (0.02, 0.025, 0.04, 1)

ui.scale = 0.7

CENTRO = (W * 0.5, H * 0.5)
K_CAMPO = 28.0
R0 = 120.0
REF_I = 50.0
AMORTECIMENTO = 0.0
V_MAX = 360.0
R_MIN = 12.0
HIT_FRAC = 0.45
HIT_MIN = 16.0
MAX_PARTICULAS = 48

st.r = 1.0
st.g = 0.25
st.b = 0.12
st.intensidade = 52.0
st.rodando = True
st.centro = 0.35
st.atracao = 1.0
st.repulsao = 1.0
st.potencia = 2.0
st.visual = 1.0

_particulas = []
_selecionada = None
_sincronizando = False
_botao_rodar = None


def _rgb_atual():
    return (
        max(0.0, min(1.0, float(st.r))),
        max(0.0, min(1.0, float(st.g))),
        max(0.0, min(1.0, float(st.b))),
    )


def _acoplamento(rgb_i, rgb_j):
    ri, gi, bi = rgb_i
    rj, gj, bj = rgb_j
    return ri * (gj - bj) + gi * (bj - rj) + bi * (rj - gj)


def _pintar_anel(hit, visivel):
    hit.fill = None
    hit.line = Color(1.0, 1.0, 1.0, 0.92 if visivel else 0.0)
    hit.line_width = 2.4 if visivel else 2.0


def _raio_visual(intensidade):
    return float(intensidade) * float(st.visual)


def _aplicar_aparencia(p):
    p.spot.color = p.rgb
    p.spot.radius = _raio_visual(p.intensidade)
    p.hit.radius = max(p.intensidade * HIT_FRAC, HIT_MIN)


def _sliders_para_particula(p):
    p.rgb = _rgb_atual()
    p.intensidade = float(st.intensidade)
    _aplicar_aparencia(p)


def _particula_para_sliders(p):
    global _sincronizando
    _sincronizando = True
    st.r, st.g, st.b = p.rgb
    st.intensidade = p.intensidade
    _sincronizando = False


def _selecionar(p):
    global _selecionada
    if _selecionada is not None and _selecionada is not p:
        _pintar_anel(_selecionada.hit, False)
    _selecionada = p
    if p is not None:
        _pintar_anel(p.hit, True)
        p.hit.move_to_front()
        _particula_para_sliders(p)


def _ao_clicar_hit(hit):
    _selecionar(getattr(hit, "_particula", None))


def _ao_arrastar(hit, *args):
    p = getattr(hit, "_particula", None)
    if p is None:
        return
    p.vel.x = 0.0
    p.vel.y = 0.0
    _selecionar(p)


def _arrastando(p):
    return bool(mouse.press(Mouse.BTN_LEFT) and p.hit.pointer_hover)


class Particula:
    def __init__(self, x, y, rgb, intensidade):
        self.rgb = tuple(rgb)
        self.intensidade = float(intensidade)
        self.vel = Vec2(uniform(-24, 24), uniform(-24, 24))
        self.hit = Circle(
            center=(x, y),
            radius=max(self.intensidade * HIT_FRAC, HIT_MIN),
            color=Color(1.0, 1.0, 1.0, 0.0),
            group="hits",
            layer="top",
        )
        self.hit.fill = None
        self.hit.line_width = 2.0
        self.hit.draggable = True
        self.hit._particula = self
        self.hit.on_click = _ao_clicar_hit
        self.hit.on_drag_over = _ao_arrastar
        self.spot = GlowSpot(
            center=(x, y),
            radius=_raio_visual(self.intensidade),
            color=self.rgb,
            amount=1.05,
        )
        self.spot["center"] @= lambda: self.hit.center
        _pintar_anel(self.hit, False)


def _ponto_inicial():
    ang = uniform(0, 6.283185307179586)
    d = uniform(40, 180)
    return CENTRO[0] + cos(ang) * d, CENTRO[1] + sin(ang) * d


def criar(x=None, y=None, rgb=None, intensidade=None):
    if len(_particulas) >= MAX_PARTICULAS:
        return None
    if x is None or y is None:
        x, y = _ponto_inicial()
    p = Particula(
        x, y,
        rgb if rgb is not None else _rgb_atual(),
        intensidade if intensidade is not None else float(st.intensidade),
    )
    _particulas.append(p)
    return p


def deletar():
    p = _selecionada
    if p is None:
        return
    _selecionar(None)
    _particulas.remove(p)
    p.hit.destroy()
    p.spot.destroy()


def _limpar():
    global _selecionada
    _selecionada = None
    for p in list(_particulas):
        try:
            p.hit.destroy()
        except Exception:
            pass
        try:
            p.spot.destroy()
        except Exception:
            pass
    _particulas.clear()


def resetar():
    _limpar()
    canvas.reset_view()
    cx, cy = CENTRO
    sementes = (
        ((cx - 90, cy + 10), (1.0, 0.10, 0.08), 58),
        ((cx + 90, cy + 16), (0.10, 1.0, 0.14), 58),
        ((cx, cy - 96), (0.12, 0.18, 1.0), 58),
        ((cx + 46, cy + 88), (0.95, 0.82, 0.12), 42),
        ((cx - 52, cy + 78), (0.90, 0.16, 0.88), 42),
    )
    for (x, y), rgb, intensidade in sementes:
        criar(x, y, rgb, intensidade)


def _atualizar_botao_rodar():
    if _botao_rodar is not None:
        _botao_rodar.label = "Pausar" if st.rodando else "Rodar"


def alternar_rodar():
    st.rodando = not bool(st.rodando)
    _atualizar_botao_rodar()


Button(label="Criar", on_click=lambda: criar())
Button(label="Deletar", on_click=deletar)
Button(label="Resetar", on_click=resetar)
ui.gap()
_botao_rodar = Button(label="Pausar", on_click=alternar_rodar)
ui.gap()
Slider(st["r"], label="R", min_value=0.0, max_value=1.0)
Slider(st["g"], label="G", min_value=0.0, max_value=1.0)
Slider(st["b"], label="B", min_value=0.0, max_value=1.0)
Slider(st["intensidade"], label="Intensidade", min_value=16.0, max_value=140.0)
ui.gap()
Slider(st["centro"], label="Centro", min_value=0.0, max_value=2.5)
Slider(st["atracao"], label="Atração", min_value=0.0, max_value=3.0)
Slider(st["repulsao"], label="Repulsão", min_value=0.0, max_value=3.0)
Slider(st["potencia"], label="Potência", min_value=0.0, max_value=2.0)
Slider(st["visual"], label="Visual", min_value=0.1, max_value=10.0)


@on_change(st["r"])
@on_change(st["g"])
@on_change(st["b"])
@on_change(st["intensidade"])
def _sliders_mudaram(_valor=None):
    if _sincronizando or _selecionada is None:
        return
    _sliders_para_particula(_selecionada)


@on_change(st["visual"])
def _visual_mudou(_valor=None):
    for p in _particulas:
        _aplicar_aparencia(p)


def _escala_par(acoplamento):
    if acoplamento >= 0.0:
        return float(st.repulsao) * acoplamento
    return float(st.atracao) * acoplamento


def _passo(dt):
    n = len(_particulas)
    if n == 0:
        return
    k_centro = float(st.centro)
    potencia = max(0.0, min(2.0, float(st.potencia)))
    ax = [0.0] * n
    ay = [0.0] * n
    pos = [(float(p.hit.center.x), float(p.hit.center.y)) for p in _particulas]
    for i in range(n):
        pi = _particulas[i]
        xi, yi = pos[i]
        ax[i] -= k_centro * (xi - CENTRO[0])
        ay[i] -= k_centro * (yi - CENTRO[1])
        for j in range(i + 1, n):
            pj = _particulas[j]
            xj, yj = pos[j]
            dx = xi - xj
            dy = yi - yj
            dist = hypot(dx, dy)
            if dist < 1e-6:
                continue
            r_eff = max(dist, R_MIN)
            queda = (R0 / r_eff) ** potencia
            campo = K_CAMPO * (pi.intensidade * pj.intensidade) / (REF_I * REF_I) * queda
            inv_r = 1.0 / dist
            fx = dx * inv_r * campo
            fy = dy * inv_r * campo
            si = _escala_par(_acoplamento(pi.rgb, pj.rgb))
            sj = _escala_par(_acoplamento(pj.rgb, pi.rgb))
            ax[i] += fx * si
            ay[i] += fy * si
            ax[j] -= fx * sj
            ay[j] -= fy * sj
    damp = max(0.0, 1.0 - AMORTECIMENTO * dt)
    for i, p in enumerate(_particulas):
        if _arrastando(p):
            p.vel.x = 0.0
            p.vel.y = 0.0
            continue
        vx = (p.vel.x + ax[i] * dt) * damp
        vy = (p.vel.y + ay[i] * dt) * damp
        speed = hypot(vx, vy)
        if speed > V_MAX:
            s = V_MAX / speed
            vx *= s
            vy *= s
        p.vel.x = vx
        p.vel.y = vy
        p.hit.center = (pos[i][0] + vx * dt, pos[i][1] + vy * dt)


def on_mouse_down(x, y, button):
    if button == Mouse.BTN_LEFT:
        _selecionar(None)


def on_mouse_scroll(xoffset, yoffset):
    factor = 1.08 if yoffset > 0 else 1 / 1.08
    novo = max(0.05, min(3.0, canvas.zoom * factor))
    canvas.zoom_to(novo, about=canvas.game_view.center)


def update(dt):
    if keyp.once("SPACE"):
        alternar_rodar()
    if not st.rodando:
        return
    _passo(min(dt, 1.0 / 30.0))


resetar()
canvas.framerate = "max"
run()
