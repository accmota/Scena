from scena import *

VELOCIDADE_MIN = 80
VELOCIDADE_MAX = 380
ACELERACAO = 260
GIRO_MAX = 220
# menor = volante mais pesado (demora a virar e a parar de virar)
RESPOSTA_VOLANTE = 5

init(width=1000, height=700, title="Cadeia no teclado")
Wallpaper(Gradient("navy", "cyan"))
Plasma(speed=0.2)

st.angulo = 90
st.velocidade = VELOCIDADE_MIN
st.giro = 0
st.cor = Color("tomato")

# --- cadeia: a ponta é o veículo; cada bola segue a anterior ----------------
def acrescentar():
    bolas = group["bolas"]
    if bolas.empty:
        centro = canvas.game_view.center
    else:
        centro = bolas.last.center

    bola = Circle(center=centro, radius=16, color=st.cor, group="bolas")
    bola.visual = Sphere()
    st.cor = st.cor.darker(0.02)


for i in range(8):
    acrescentar()


@every(1)
def crescer():
    acrescentar()


# --- farejador: segue a ponta sempre na mesma velocidade -------------------
VELOCIDADE_FAREJADOR = 150
farejador = Circle(center=(80, 80), radius=10, color="gold")


def update(dt):
    bolas = group["bolas"]
    ponta = bolas[0]

    # o volante não vira de uma vez: o giro vai até o alvo aos poucos
    alvo = 0
    if keyp("LEFT"):
        alvo += GIRO_MAX
    if keyp("RIGHT"):
        alvo -= GIRO_MAX
    st.giro = chase(st.giro, alvo, rate=RESPOSTA_VOLANTE)
    st.angulo += st.giro * dt

    if keyp("UP"):
        st.velocidade += ACELERACAO * dt
    if keyp("DOWN"):
        st.velocidade -= ACELERACAO * dt
    st.velocidade = max(VELOCIDADE_MIN, min(VELOCIDADE_MAX, st.velocidade))

    ponta.move_by(angle=st.angulo, distance=st.velocidade * dt)
    ponta.confine(canvas.game_view)
    ponta.angle = st.angulo

    # as outras seguem a da frente
    for i in range(1, bolas.count):
        bola = bolas[i]
        da_frente = bolas[i - 1]
        x = chase(bola.center.x, da_frente.center.x, rate=8)
        y = chase(bola.center.y, da_frente.center.y, rate=8)
        bola.move_to(x, y)

    # o farejador anda até a ponta, nem mais rápido nem mais devagar
    farejador.move_to(approach(farejador.center, ponta.center, VELOCIDADE_FAREJADOR))


run()
