# harness: cwd=examples/media
"""Plataforma — exemplo iniciante de Scena.

O herói anda, pula, coleta estrelas e atira bolas que quicam.
Três robôs andam pelas plataformas (e podem cair). Sem classes.
Há um elevador que sobe e desce; na rampa o herói se inclina.

Controles
---------
  ESQUERDA / DIREITA (A / D)   andar
  CIMA (W)                     pular (quando está no chão)
  ESPAÇO / Z                   atirar
  R                            recomeçar

Uso
---
    python examples/app_platformer.py
"""
from scena import *

LARGURA, ALTURA = 1100, 720
GRAVIDADE = 900.0
VELOCIDADE_HEROI = 250.0
PULO = 460.0
VELOCIDADE_ROBO = 55.0
VELOCIDADE_TIRO = 420.0
VELOCIDADE_ELEVADOR = 80.0
QUICADA_BOLA = 0.7
TEMPO_BOLA = 4.0
INTERVALO_TIRO = 0.25
OFFSET_TIRO = 28
NASCER = (120, 120)
ELEVADOR_X = 230
ELEVADOR_CHAO = 90
ELEVADOR_TETO = 700

def criar_plataforma(centro, largura, altura, angulo=0):
    bloco = Rect(
        center=centro,
        width=largura,
        height=altura,
        angle=angulo,
        group="plataforma",
    )
    #bloco.set_color("sienna")
    bloco.visual = Gradient("terracota")
    bloco.mass = STATIC
    return bloco


def criar_estrela(centro):
    return Sprite("space/star_gold.png", size=28, center=centro, group="estrela")


def criar_robo(centro, velocidade=VELOCIDADE_ROBO):
    bicho = Sprite(
        Sheet("robot/Run (*).png", fps=12, pixel_size=0.1),   # 556 px → ~56
        center=centro,
        group="inimigo",
        hitbox_shape="rect",
    )
    bicho.mass = 1.0
    bicho.vel = Vec2(velocidade, 0)
    # O robô olha para a direita; vira ao andar para a esquerda.
    bicho.flip_x = velocidade < 0
    return bicho


# --- cenário -------------------------------------------------------------------
init(width=LARGURA, height=ALTURA, title="Plataforma")
collision.floor = True   # gravidade: quem encosta no que está embaixo fica em pé nele
SkyGradient("light blue", horizon=1.0, rotation_response=0.5)
#Ground(rotation_response=1)
#Wallpaper(Gradient("navy", angle=60), rotation_response=1)

criar_plataforma(centro=(550, 40), largura=LARGURA, altura=40)
criar_plataforma(centro=(420, 200), largura=220, altura=24)
criar_plataforma(centro=(780, 280), largura=180, altura=24)
criar_plataforma(centro=(880, 160), largura=200, altura=24, angulo=22)

elevador = criar_plataforma(centro=(ELEVADOR_X, ELEVADOR_CHAO), largura=120, altura=20)
elevador.set_color("goldenrod")
elevador.vel = Vec2(0, VELOCIDADE_ELEVADOR)

roda = criar_plataforma(centro=(600, 400), largura=120, altura=20)
roda.visual = Metal()


parede_esq = Rect(center=(30, ALTURA * 0.5), width=24, height=ALTURA, group="parede")
parede_esq.set_color("dim gray")
parede_esq.mass = STATIC

parede_dir = Rect(center=(1070, ALTURA * 0.5), width=24, height=ALTURA, group="parede")
parede_dir.set_color("dim gray")
parede_dir.mass = STATIC

parado = [
    "ninja/Idle__000.png", "ninja/Idle__001.png",
    "ninja/Idle__002.png", "ninja/Idle__003.png",
    "ninja/Idle__004.png", "ninja/Idle__005.png",
    "ninja/Idle__006.png", "ninja/Idle__007.png",
    "ninja/Idle__008.png", "ninja/Idle__009.png",
]
correndo = [
    "ninja/Slide__000.png", "ninja/Slide__001.png",
    "ninja/Slide__002.png", "ninja/Slide__003.png",
    "ninja/Slide__004.png", "ninja/Slide__005.png",
    "ninja/Slide__006.png", "ninja/Slide__007.png",
    "ninja/Slide__008.png", "ninja/Slide__009.png",
]
pulando = [
    "ninja/Jump__000.png", "ninja/Jump__001.png",
    "ninja/Jump__002.png", "ninja/Jump__003.png",
    "ninja/Jump__004.png", "ninja/Jump__005.png",
    "ninja/Jump__006.png", "ninja/Jump__007.png",
    "ninja/Jump__008.png", "ninja/Jump__009.png",
]
# pixel_size: cada pixel do PNG vale 0.16 na tela (o ninja parado fica com ~70).
ninja = Sheet(parado + correndo + pulando, pixel_size=0.16)
ninja.clip("parado", parado, fps=8)
ninja.clip("correndo", correndo, fps=12)
ninja.clip("pulando", pulando, fps=10)

heroi = Sprite(
    ninja,
    center=NASCER,
    group="heroi",
    hitbox_shape="rect",
    hitbox_source="all",
    hitbox_anchor="bottom",
    hitbox_scale=(0.55, 1),
)
heroi.mass = 1.0
heroi.vel = Vec2(0, 0)


#rastro = Contrail(
#    duration=2,
#    fade=True,
#    ease="ease_out",
#    visual=Halo("light blue", style="soft"),
#    line_width=2.5,
#    smooth=True,
#)
#roda.every(0.01, lambda: rastro.snapshot(roda.left_square_center))

st.estrelas = 0
st.vidas = 3
placar = Text(text="", top_left=(16, ALTURA - 19), font_size=18)
placar["text"] @= lambda: f"Estrelas {st.estrelas}   Vidas {st.vidas}"


# --- partida -------------------------------------------------------------------
@when(lambda: keyp("R"))
def iniciar_posicoes():
    st.estrelas = 0
    st.vidas = 3
    heroi.active = True
    heroi.visible = True
    heroi.untag("ferido")
    heroi.center = NASCER
    #rastro.clear()
    heroi.vel = Vec2(0, 0)
    heroi.flip_x = False
    heroi.reset_rotation()
    heroi.tilt = 0
    heroi.play("parado")
    heroi.tail = False
    elevador.center = (ELEVADOR_X, ELEVADOR_CHAO+200)
    elevador.vel = Vec2(0, -VELOCIDADE_ELEVADOR)
    placar["text"] @= lambda: f"Estrelas {st.estrelas}   Vidas {st.vidas}"
    group["bola"].destroy()
    group["estrela"].destroy()
    group["inimigo"].destroy()
    group["tchau"].destroy()
    criar_estrela((300, 250))
    criar_estrela((520, 250))
    criar_estrela((780, 370))
    criar_estrela((920, 240))
    criar_robo(centro=(520, 90))
    criar_robo(centro=(420, 230), velocidade=-VELOCIDADE_ROBO)
    criar_robo(centro=(780, 350))


iniciar_posicoes()

resolve(["heroi", "tchau"], ["plataforma", "parede"], bounce=0.0)
resolve("inimigo", "plataforma", bounce=0.2)
resolve("inimigo", "parede", bounce=0.0)
resolve("bola", ["plataforma", "parede"], bounce=QUICADA_BOLA)

resolve("bola", "bola", bounce=1)

# --- jogo ----------------------------------------------------------------------
def atirar():
    lado = -1 if heroi.flip_x else 1
    bola = Sprite(
        "k-rolling-ball/ball_red_large.png",
        center=heroi.center + (OFFSET_TIRO * lado, 10),
        size=16,
        group="bola",
        #hitbox_shape="circle",
    )
    bola.mass = 0.1
    angulo = 150 if heroi.flip_x else 30
    bola.vel = vec_from_angle(angulo, length=VELOCIDADE_TIRO)
    bola.after(TEMPO_BOLA, sumir)


def sumir(bola):
    bola.dissolve_out(0.4, style="vortex", on_done=bola.destroy)


def perder_vida():
    st.vidas -= 1
    if st.vidas <= 0:
        heroi.active = False
        placar["text"] @= (
            lambda: f"Fim de jogo — estrelas {st.estrelas}  (R para recomeçar)"
        )

@collide("heroi", "plataforma")
def hit_plat(heroi, plataforma, info):
    if abs(heroi.vel.y) > 700:
        canvas.fireworks_at(heroi, color="gold", radius=64)
        

@collide("heroi", "estrela")
def coletou(heroi, estrela, info):
    estrela.destroy()
    st.estrelas += 1
    heroi.flash(0.08)
    heroi.tail = True
    heroi.after(2.0, lambda: setattr(heroi, "tail", False), name="tail")


@collide("bola", "inimigo")
def acertou(bola, inimigo, info):
    inimigo.untag("inimigo")
    inimigo.tag("tchau")
    bola.dissolve_out(0.5, style="vortex", on_done=bola.destroy)
    inimigo.burn_out(0.5, on_done=inimigo.destroy)


@collide("heroi", "inimigo")
def machucou(heroi, inimigo, info):
    if heroi.tagged("ferido") or not heroi.active:
        return
    heroi.tag("ferido")
    heroi.blink(1.0)
    heroi.after(1.0, lambda: heroi.untag("ferido"), name="ferido")
    perder_vida()

@collide("inimigo", "parede")
def inimigo_parede(inimigo, parede, info):
    inimigo.flip_x = not inimigo.flip_x
    inimigo.vel.x = -inimigo.vel.x

def update(dt):
    if not heroi.active:
        return

    no_chao = "bottom" in heroi.touching_sides
    # Coyote time: fica "no chão" por 80ms depois de sair da borda.
    no_chao_visivel = recently("no_chao", no_chao, hold=0.08)

    if keyp("LEFT"):
        heroi.vel.x = -VELOCIDADE_HEROI
    elif keyp("RIGHT"):
        heroi.vel.x = VELOCIDADE_HEROI
    else:
        heroi.vel.x = 0.0

    # Parado, mantém o último lado — o tiro segue o olhar.
    if heroi.vel.x < 0:
        heroi.flip_x = True
    elif heroi.vel.x > 0:
        heroi.flip_x = False

    heroi.vel.y -= GRAVIDADE * dt
    # Buffer de pulo: UP até 120ms antes de aterrissar ainda conta.
    if recently("pulo", keyp.once("UP"), hold=0.12) and no_chao_visivel:
        heroi.vel.y = PULO

    if keyp("SPACE") and ready("tiro", INTERVALO_TIRO):
        atirar()

    if not no_chao_visivel:
        heroi.play("pulando")
    elif heroi.vel.x != 0.0:
        heroi.play("correndo")
    else:
        heroi.play("parado")

    heroi.move_by(heroi.vel.x * dt, heroi.vel.y * dt)

    # Elevador sobe e desce; o herói em cima acompanha.
    elevador.move_by(0, elevador.vel.y * dt)
    if elevador.center.y > ELEVADOR_TETO:
        elevador.vel.y = -VELOCIDADE_ELEVADOR
    elif elevador.center.y < ELEVADOR_CHAO:
        elevador.vel.y = VELOCIDADE_ELEVADOR


    roda.rotate_by(150 * dt)

    # Inclinação visual na rampa (só o desenho; o colisor fica em pé).
    # Forma A — açúcar: re-lê touching_contacts; no ar → tilt 0 sozinho.
    heroi.tilt = "ground"  # ou AUTO_GROUND

    # Forma B — explícita: precisa zerar antes, senão o lean cola no ar.
    # heroi.tilt = 0
    # for c in heroi.touching_contacts:
    #     if c.side == "bottom":
    #         heroi.tilt = c

    for robo in group["inimigo"]:
        robo.flip_x = robo.vel.x < 0
        robo.vel.y -= GRAVIDADE * dt
        robo.move_by(robo.vel.x * dt, robo.vel.y * dt)

    for bola in group["bola"]:
        bola.vel.y -= GRAVIDADE * dt
        bola.move_by(bola.vel.x * dt, bola.vel.y * dt)


run()
