"""Cem linhas: uma intro de tamanho limitado, no espírito das intros de 4k da demoscene.

Uma peça inteira em no máximo 100 linhas de código simples. Sem shader, sem laço de pixels:
tudo o que se mexe é uma fórmula do relógio (@=), uma luz numa Track ou um efeito.

  I    Flor      hexágonos encaixados se abrem a partir de um ponto
  II   Vórtice   eles se torcem numa espiral; um anel de pétalas se abre em volta do cometa
  III  Túnel     os centros se arrastam num túnel; um mergulho, uma explosão, e de novo
Experimente: mude o número de hexágonos, a roda de cores ou quanto vai o st.torcao. Sem teclas: ela se repete.
"""
from scena import *

init(width=1280, height=800, title="Cem linhas")
canvas.set_origin("center")         # (0, 0) no meio deixa as fórmulas curtas
Nebula(color="indigo", color2="teal", alpha=0.6)
luz = Bloom(intensity=0.8)
play_sound("music/super_hero_original_no_intro.ogg", loops="forever", volume=0.8)
roda = Colormap.from_colors("deep pink", "orange", "gold", "lime", "deep sky blue", "violet", "deep pink")
st.abertura = 0     # 0: fechado num ponto · 1: todo aberto
st.torcao = 0       # graus que cada hexágono gira a mais que o de dentro
st.curva = 0        # 0: um centro só · 1: cada centro se arrasta atrás do de dentro (um túnel)
st.petalas = 0      # quão longe está o anel de pétalas
st.giro = 1         # quão rápido tudo gira
st.pulso = 0        # 1 numa batida do bumbo, e depois some (ver update)
st.batida = 1       # quanto os traços seguem a música: só embaixo do título

def cor_da_roda(i):
    # int(): as cores andam pela roda em degraus, quatro por segundo
    passo = int(clock.time * 4 + i) % 24
    return roda.get_color(passo / 24)

# ---- o miolo: hexágonos encaixados cujo tamanho, giro, lugar e cor são fórmulas ----
for i in range(19):
    hexagono = RegularPolygon(n=6, angle=lambda i=i: clock.time * 20 * st.giro + i * st.torcao)
    hexagono["radius"] @= lambda i=i: st.abertura * (14 + 17 * i)
    hexagono["center"] @= lambda i=i: vec_from_angle(clock.time * 70 - i * 12, st.curva * (220 - 11 * i))
    hexagono.fill = None
    hexagono["line_width"] @= lambda: 3 + 4 * st.pulso
    hexagono["line"] @= lambda i=i: cor_da_roda(i)

# ---- um anel de pétalas, cada uma andando nele com a ponta na frente ----
def no_anel(k):
    return k * 15 + clock.time * 15 * st.giro       # onde a pétala k está no anel, em graus

for k in range(24):
    petala = Triangle(radius=20, base_ratio=0.5, angle=lambda k=k: no_anel(k) + 90)
    petala["center"] @= lambda k=k: vec_from_angle(no_anel(k), st.petalas * st.abertura * 340)
    petala["color"] @= lambda k=k: cor_da_roda(k)

# ---- luz em trilhas: uma coroa em zigue-zague, acesa só numa janela que corre em volta ----
reflexo = Track.circle(center=(0, 0), radius=390, color="white", line_width=4).zigzag(amount=8, waves=72)
reflexo["begin"] @= lambda: clock.time * 0.25 % 1
reflexo["end"] @= lambda: (clock.time * 0.25 + 0.12) % 1
# um cometa numa volta longa e macia que passeia pela tela
passeio = Track(points=[(-520, 250), (-60, 320), (470, 260), (540, -150), (120, -320),
                        (-330, -250), (-560, -20)], smooth=1, closed=True)
cometa = Circle(radius=9, color="white")
cometa.tail = Tail(color="gold", size=4)
cometa.move_along(passeio, time=18, loops="forever")

async def espetaculo():
    await wait(0.5)
    while True:
        # I  Flor: o título, e os hexágonos se abrem a partir de um ponto
        canvas.fade_in(1.5)
        titulo = Text("100 LINHAS DE SCENA", center=(0, 0), font_size=80, font="fonts/VastShadow-Regular.ttf")
        titulo.dissolve_in(2.5)
        await tween(st["abertura"], 1, time=8, ease="ease_out")
        canvas.ripple_at(0, 0)
        titulo.dissolve_out(1.5, style="vortex", on_done=titulo.destroy)
        tween(st["batida"], 0, time=1.5)       # os traços se acalmam numa largura fixa
        # II  Vórtice: os hexágonos se torcem numa espiral, as pétalas saltam para fora
        canvas.zoom_to(1.2, time=4, ease="ease_in_out")
        tween(st["petalas"], 1, time=3, ease="elastic")
        await tween(st["torcao"], 8, time=5, ease="ease_in_out")
        for estouro in range(16):
            canvas.burst_at(cometa, radius=50)
            await wait(0.75)
        # III  Túnel: os centros se arrastam; tudo acelera, cai num ponto e explode
        prisma = Prism(amount=0.006)
        await tween(st["curva"], 1, time=5, ease="ease_in_out")
        prisma.remove()
        canvas.rotate_by(-360, time=8.5, ease="ease_in")
        canvas.zoom_to(1, time=7, ease="ease_in_out")
        await tween(st["giro"], 8, time=7, ease="ease_in")
        await tween(st["abertura"], 0, time=1.5, ease="ease_in")
        canvas.explosion_at(0, 0)
        canvas.fade_out(1.5)
        await wait(2)
        st.abertura, st.torcao, st.curva, st.petalas, st.giro, st.batida = 0, 0, 0, 0, 1, 1

def update(dt):
    grave = amp_db(audio.spectrum(4)[0])     # uns 0.62 nesta música, 0.1 a mais numa batida do bumbo
    bumbo = 8 * st.batida * (grave - 0.62)
    st.pulso = max(0, st.pulso - 2 * dt, bumbo)      # salta numa batida, depois some
    luz.intensity = 0.9 + 0.8 * st.pulso

run_task(espetaculo)
run()
