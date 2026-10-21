"""Corrida — uma corrida de carros vista de cima.

Um ou dois jogadores no mesmo teclado; os outros carros são da CPU, sempre
quatro na pista. Há duas pistas, cada uma num arquivo de fase
(levels/corrida.json, a Serpentina, e levels/corrida_relampago.json, a
Relâmpago): o chão de ladrilhos, a linha do meio da pista, os obstáculos, as
faixas de luz por fora das curvas, os lugares de largada e a vista da câmera.
A abertura tem dois passos: quantos jogam e, depois, a pista. O volante
gira aos poucos e, numa curva rápida, a traseira escorrega; solto, o carro
se alinha com a pista. Fora do asfalto o carro perde velocidade. Pneus,
árvores, barracas e arquibancadas seguram o carro, que quica de volta; um
barril faz o carro bater, e ele fica parado, piscando, um instante,
enquanto os outros passam por ele. O carro mais rápido joga o da frente, que
derrapa. A mancha de óleo faz o carro rodar. As caixas de poder dão um tiro:
uma bola de fogo que sai reta para a frente e faz bater o carro que pegar. A
CPU mira na linha do meio, desvia do que está à frente, dá ré quando fica
presa e, às vezes, atira em quem está na frente dela. A corrida acaba quando
os jogadores chegam.

Controles
---------
  Na abertura  clique em UM JOGADOR ou DOIS JOGADORES (ou aperte 1 / 2) e
               depois numa pista (ou 1 / 2)
  Jogador 1    o azul: CIMA acelera · BAIXO freia e dá ré · ESQ / DIR viram · ENTER atira
  Jogador 2    o vermelho: W acelera · S freia e dá ré · A / D viram · TAB atira
  No fim       ESPAÇO volta à abertura

Uso
---
    python examples/corrida.py
"""

from random import choice, randrange, uniform
from scena import *

# As duas pistas. Cada arquivo tem as mesmas peças com os mesmos nomes; o
# código não sabe qual é qual.
PISTAS = {
    "SERPENTINA": Level("levels/corrida.json"),
    "RELÂMPAGO": Level("levels/corrida_relampago.json"),
}
init(width=1280, height=720, title="Corrida")
Wallpaper("#145a32")
FONTE = "fonts/Quantico-Bold.ttf"

veiculos = Sheet("racing/spritesheet_vehicles.png", atlas="racing/spritesheet_vehicles.xml")
poderes = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
fogo = Sheet("explosions/fireball/Fireball_Effect_*.png", fps=30)
# 25 nuvens de fumaça diferentes, não os quadros de uma animação: cada
# fumaça mostra uma só (ver Fumaca).
fumaca = Sheet("explosions/Black_smoke/blackSmoke*.png")

LARGURA = 154       # a largura do asfalto, com as zebras

VOLTAS = 3
MAXIMA = 380        # a velocidade máxima no asfalto
NA_GRAMA = 140      # a máxima fora do asfalto
RE = -110           # a máxima de ré
GIRO = 170          # quantos graus por segundo o carro vira, com o volante todo
ADERENCIA = 7       # quanto o pneu segura: menos que isso, o carro derrapa mais

# O jogador 1 (azul) dirige com as setas; o jogador 2 (vermelho), com W A S D.
TECLAS_AZUL = {"acelera": "UP", "freia": "DOWN", "esquerda": "LEFT", "direita": "RIGHT", "tiro": "ENTER"}
TECLAS_VERMELHO = {"acelera": "W", "freia": "S", "esquerda": "A", "direita": "D", "tiro": "TAB"}

# Tudo em que o carro bate e que segura o carro (e apaga um tiro).
SOLIDOS = ["parede", "pneu", "arvore", "barril"]

st.jogadores = 2
st.pista = "SERPENTINA"
st.largou = False
st.chegaram = 0
st.podio = []


def quanto_virar(carro, rumo):
    """Quantos graus o carro precisa virar para apontar no rumo (+ é para a esquerda)."""
    return vec_from_angle(carro.angle).angle_to(vec_from_angle(rumo))


class Carro(Sprite, source=veiculos, height=46, art_angle=90, group="carros"):
    def setup(self):
        self.velocidade = 0     # a força do motor: para a frente, ou negativa de ré
        self.vel = Vec2(0, 0)   # para onde o carro anda de verdade
        self.volante = 0        # de -1 (todo à direita) a 1 (todo à esquerda)
        self.maxima = MAXIMA
        self.voltas = 0
        self.marco = 0          # o último marco da linha da pista por onde o carro passou
        self.tiros = 0
        self.chegou = False
        self.chegada = 0        # em que lugar chegou: 1, 2…
        # O que o piloto quer fazer agora. Quem decide é o teclado ou, num
        # carro da CPU, o pensar().
        self.cpu = False
        self.acelera = False
        self.freia = False
        self.vira = 0           # 1 para a esquerda, -1 para a direita, 0 reto
        self.quer_atirar = False
        self.faixa = 0          # CPU: quanto anda ao lado da linha do meio
        self.derrapa = 0        # segundos em que o pneu quase não segura (levou um tranco)
        self.sem_marco = 0      # CPU: há quantos segundos não passa por um marco
        self.recuando = 0       # CPU: quantos segundos de ré ainda faltam

    def on_update(self, dt):
        if self.mode is None and st.largou and not self.chegou:
            if self.cpu:
                self.pensar(dt)
            else:
                self.ler_teclado()
            self.dirigir(dt)
        else:
            self.velocidade = approach(self.velocidade, 0, 300)

        # Fora do asfalto a velocidade cai até o limite da grama, e o pneu
        # segura menos. Rodando no óleo, quase nada.
        aderencia = ADERENCIA
        if not collision.query_point(self, group="asfalto"):
            self.velocidade = approach(self.velocidade, min(self.velocidade, NA_GRAMA), 700)
            aderencia = 3
        if self.derrapa > 0:
            self.derrapa -= dt
            aderencia = 1.5
        if self.mode == self.rodando:
            aderencia = 1

        # O carro quer andar para onde aponta, mas o movimento chega lá aos
        # poucos: numa curva rápida a traseira escorrega (derrapa).
        frente = vec_from_angle(self.angle, self.velocidade)
        self.vel = chase(self.vel, frente, aderencia)
        self.move_by(self.vel * dt)
        self.confine(self.vista, by="box")
        self.contar_marcos()

    def ler_teclado(self):
        self.acelera = keyp(self.teclas["acelera"])
        self.freia = keyp(self.teclas["freia"])
        self.vira = 0
        if keyp(self.teclas["esquerda"]):
            self.vira = 1
        if keyp(self.teclas["direita"]):
            self.vira = -1
        self.quer_atirar = keyp.once(self.teclas["tiro"])

    def pensar(self, dt):
        # Preso num obstáculo: dá ré um pouco, com o volante virado, e tenta de novo.
        if self.recuando > 0:
            self.recuando -= dt
            self.acelera = False
            self.freia = True
            return

        # Mira num ponto da pista um pouco à frente, na sua faixa.
        adiante = self.marco + 3
        mira = Vec2(*self.marcos[adiante % len(self.marcos)]) + vec_from_angle(self.rumo_da_pista(adiante) + 90, self.faixa)
        erro = quanto_virar(self, heading(self, mira))

        # Um obstáculo logo à frente: desvia para o lado onde ele não está.
        perto = collision.query_sector(self, radius=140, spread=70, group=SOLIDOS + ["oleo"])
        if perto:
            coisa = min(perto, key=lambda c: distance(self, c))
            if quanto_virar(self, heading(self, coisa)) > 0:
                erro -= 45
            else:
                erro += 45
        self.vira = max(-1, min(1, erro / 15))

        # Acelera quando aponta mais ou menos para a mira, e alivia antes de
        # uma curva forte mais adiante.
        curva = abs(quanto_virar(self, self.rumo_da_pista(self.marco + 6)))
        self.acelera = (abs(erro) < 40 or self.velocidade < 120) and not (curva > 60 and self.velocidade > 260)
        self.freia = abs(erro) > 70 and self.velocidade > 200

        # Com um tiro e um carro na frente, às vezes atira: a CPU demora um
        # pouco a decidir (chance) e erra a mira um pouco (em atirar).
        na_mira = collision.query_sector(self, radius=450, spread=24, group="carros")
        self.quer_atirar = self.tiros > 0 and len(na_mira) > 0 and chance(0.03)

        # Muito tempo sem passar por um marco: está presa.
        self.sem_marco += dt
        if self.sem_marco > 2.5:
            self.sem_marco = 0
            self.recuando = 0.8
            # De ré, o volante ao contrário leva o nariz para a mira.
            self.vira = -1 if erro > 0 else 1

    def dirigir(self, dt):
        if self.acelera:
            self.velocidade = approach(self.velocidade, self.maxima, 260)
        elif self.freia:
            self.velocidade = approach(self.velocidade, RE, 500)
        else:
            self.velocidade = approach(self.velocidade, 0, 120)

        # O volante gira aos poucos e volta sozinho ao meio.
        self.volante = chase(self.volante, self.vira, 10)

        # Parado, o carro não vira; de ré, o volante inverte.
        giro = GIRO * self.volante * min(abs(self.velocidade) / 120, 1)
        if self.velocidade < 0:
            giro = -giro
        self.rotate_by(giro * dt)

        # Sem ninguém no volante, o carro se alinha devagar com a pista. Só
        # quando já está quase alinhado, para não roubar uma curva de quem dirige.
        if self.vira == 0 and self.velocidade > 0:
            erro = quanto_virar(self, self.rumo_da_pista(self.marco))
            if abs(erro) < 25:
                self.rotate_by(erro * 3 * dt)

        if self.quer_atirar and self.tiros > 0:
            self.atirar()

    def rumo_da_pista(self, i):
        """Para onde a pista vai no marco i, em graus."""
        return heading(self.marcos[i % len(self.marcos)], self.marcos[(i + 1) % len(self.marcos)])

    def contar_marcos(self):
        # Os marcos são pontos em fila no meio da pista. O carro avança
        # quando chega perto de um dos próximos cinco: pode pular um marco
        # numa curva aberta, mas cortar caminho pela grama não conta.
        for passo in range(1, 6):
            i = self.marco + passo
            if distance(self, self.marcos[i % len(self.marcos)]) < LARGURA * 0.7:
                self.marco = i % len(self.marcos)
                self.sem_marco = 0
                if i >= len(self.marcos):
                    self.completar_volta()
                return

    def completar_volta(self):
        self.voltas += 1
        if self.voltas == VOLTAS:
            # Quem chegou sai da frente: fica transparente e não bate mais.
            self.chegou = True
            self.alpha = 0.5
            self.collidable = False
            st.chegaram += 1
            self.chegada = st.chegaram
            canvas.fireworks_at(self)
            play_sound("audio/impactBell_heavy_000.ogg")
        elif not self.cpu:
            play_sound("synth/coin.wav")

    def progresso(self):
        # Quanto da corrida o carro já fez: voltas, marcos e, entre dois
        # marcos, quem está mais perto do próximo. Quem chegou, pela chegada.
        if self.chegou:
            return 1000000 - self.chegada
        proximo = self.marcos[(self.marco + 1) % len(self.marcos)]
        return self.voltas * len(self.marcos) + self.marco - distance(self, proximo) / 1000

    def lugar(self):
        return 1 + group["carros"].count_where(lambda outro: outro.progresso() > self.progresso())

    def atirar(self):
        self.tiros -= 1
        self.glow = False
        tiro = Tiro(center=self.center + vec_from_angle(self.angle, 38))
        tiro.angle = self.angle
        if self.cpu:
            tiro.angle += uniform(-8, 8)    # a CPU erra um pouco a mira
        tiro.dono = self
        play_sound("synth/throw.wav")

    def bater(self):
        if self.mode != self.batido:
            self.mode = self.batido

    @on_mode
    async def batido(self):
        # Parado e piscando enquanto está fora da corrida. Os outros passam
        # por ele: um carro batido não colide com nada.
        self.velocidade = 0
        self.vel = Vec2(0, 0)
        self.collidable = False
        canvas.explosion_at(self, amount=0.5)
        play_sound("audio/explosion02.wav", volume=0.6)
        self.blink(1.5)
        await self.rotate_by(choice([360, -360]), time=0.8, ease="ease_out")
        await wait(0.7)
        self.collidable = True
        self.mode = None

    @on_mode
    async def rodando(self):
        play_sound("audio/footstep_snow_001.ogg")
        await self.rotate_by(choice([300, -300]), time=0.9, ease="ease_out")
        self.mode = None


class Fumaca(Sprite, source=fumaca, height=40):
    # A fumaça preta de um carro atingido: uma nuvem sorteada que cresce,
    # gira devagar e some no tempo em que ele fica fora da corrida. Trocar
    # de nuvem a cada quadro faria a fumaça tremer de forma.
    def setup(self):
        self.frame = randrange(25)
        self.rotate_by(choice([60, -60]), time=1.5)
        self.scale_to(2.5, time=1.5, ease="ease_out")
        self.tween(self["alpha"], 0, time=1.5, on_done=self.destroy)


class Tiro(Sprite, source=fogo, height=32, group="tiros"):
    def on_update(self, dt):
        self.move_by(distance=800 * dt)

    @leave_playfield
    def saiu(self):
        self.destroy()


class Poder(Sprite, source=poderes, frame="powerupRed_bolt.png", height=30, group="poderes"):
    def setup(self):
        self.rotate_by(360, time=2, loops="forever")


# bounce= faz o carro quicar: ele volta um pouco do obstáculo em vez de
# ficar grudado nele. Entre dois carros, quem vem mais rápido empurra o outro.
resolve("carros", SOLIDOS, bounce=0.6)
resolve("carros", "carros", bounce=0.8)


@collide("carros", ["parede", "pneu", "arvore"])
def bateu_de_leve(carro, coisa, info):
    if abs(carro.velocidade) > 150:
        play_sound("audio/impactPlank_medium_002.ogg", volume=0.5)
        canvas.hit_at(info, style="disc", radius=12)
    # De frente, o carro volta um pouco de ré; de lado, só perde velocidade
    # e segue raspando. info.normal aponta do carro para o obstáculo.
    if abs(quanto_virar(carro, info.normal.angle)) < 45:
        carro.velocidade = -carro.velocidade * 0.3
    else:
        carro.velocidade *= 0.8


# Empurrando de frente um obstáculo, o motor não empurra: o carro só anda
# devagar para a frente, e a ré fica livre. De lado, ele segue raspando.
@collide_stay("carros", SOLIDOS)
def encostado(carro, coisa, info):
    if abs(quanto_virar(carro, info.normal.angle)) < 45:
        carro.velocidade = min(carro.velocidade, 40)


@collide("carros", "barril")
def bateu_forte(carro, coisa, info):
    if abs(carro.velocidade) > 120:
        carro.bater()
    else:
        carro.velocidade = 0
        carro.vel = Vec2(0, 0)


@collide("carros", "carros")
def encostou(carro, outro, info):
    play_sound("audio/impactGeneric_light_003.ogg", volume=0.6)
    # Quem vinha mais rápido joga o outro: o resolve dá o tranco, e o pneu
    # do empurrado quase não segura por um instante, então ele desliza para
    # onde foi jogado. Quem empurrou perde força.
    if carro.vel.length > outro.vel.length:
        rapido, lento = carro, outro
    else:
        rapido, lento = outro, carro
    rapido.velocidade *= 0.6
    lento.derrapa = 0.6


@collide("carros", "cone")
def derrubou(carro, cone):
    play_sound("audio/impactGeneric_light_003.ogg", volume=0.4)
    cone.frame = "cone_down.png"
    cone.untag("cone")
    cone.move_by(angle=carro.vel.angle, distance=90, time=0.5, ease="ease_out")
    cone.rotate_by(choice([200, -200]), time=0.5, ease="ease_out")
    carro.velocidade *= 0.8


@collide("carros", "oleo")
def escorregou(carro, oleo):
    if carro.mode is None and abs(carro.velocidade) > 100:
        carro.mode = carro.rodando


@collide("carros", "poderes")
def pegou(carro, poder):
    if carro.tiros == 0:
        carro.tiros = 1
        carro.glow = True
        play_sound("audio/fx1.wav")
        lugar = tuple(poder.center)
        after(5, lambda: Poder(center=lugar))
        poder.destroy()


@collide("tiros", "carros")
def acertou(tiro, carro):
    if carro != tiro.dono:
        canvas.shake(8)
        carro.bater()
        Fumaca(center=lambda: carro.center)
        tiro.destroy()


@collide("tiros", SOLIDOS)
def apagou(tiro, coisa, info):
    canvas.burst_at(info, radius=30)
    tiro.destroy()


def letreiro(texto, centro, tamanho):
    """Um texto grande da tela: letras em degradê com contorno escuro."""
    letras = Text(text=texto, center=centro, font=FONTE, font_size=tamanho, layer="ui")
    letras.fill = Gradient("yellow", "orange red", angle=-90)
    letras.line = "black"
    return letras


class Corrida(Act):
    def setup(self):
        fase = PISTAS[st.pista]
        # A câmera mostra a "vista" da fase: a pista e uma faixa de grama. Os
        # carros ficam dentro dela, e um tiro que sai dela some.
        self.vista = fase["vista"].box
        canvas.frame_to(self.vista)
        canvas.playfield.set(self.vista)
        st.largou = False
        st.chegaram = 0
        st.podio = []
        for item in fase.group("chao"):
            item.make()
        # Faixas de luz no chão, por fora das curvas: só enfeite, o carro passa
        # por cima. São halos; uma faixa sim, uma não, muda de cor ou de
        # intensidade. A cor liga com @= numa célula com tween (de um
        # vermelho claro ao amarelo: o vermelho puro brilha escuro na grama).
        # A intensidade é o amount do Halo, e um visual não liga com @=: o
        # on_update troca o halo dessas faixas a cada quadro (ver brilhar).
        st.cor_luz = Color("tomato")
        self.tween(st["cor_luz"], Color("yellow"), time=1, loops="forever", yoyo=True)
        st.brilho_luz = 0.5
        self.tween(st["brilho_luz"], 4, time=0.7, loops="forever", yoyo=True)
        self.pulsando = []
        for i, item in enumerate(fase.group("luz")):
            if i % 2 == 0:
                luz = item.make(line_width=8, visual=Halo(amount=3, style="line"))
                luz["color"] @= lambda: st.cor_luz
            else:
                luz = item.make(line_width=8, visual=Halo("gold", style="line"))
                self.pulsando.append(luz)
        for nome in ["parede", "pneu", "arvore", "barril", "cone", "oleo", "enfeite"]:
            for item in fase.group(nome):
                item.make()
        for nome in SOLIDOS:
            group[nome].mass = STATIC
        # O asfalto: a linha do meio da pista, grossa como a pista. Ninguém
        # a vê; ela só responde se um ponto está no asfalto.
        asfalto = fase["linha"].make(line_width=LARGURA, group="asfalto")
        asfalto.visible = False
        # Os marcos: 48 pontos em fila no meio da pista, à mesma distância um do outro.
        self.marcos = asfalto.spaced_points(48)
        for item in fase.group("poder"):
            Poder(center=item.center)

        # Sempre quatro carros: o azul no teclado, o vermelho no teclado ou
        # na CPU, e dois da CPU, cada um na sua faixa e com a sua velocidade.
        self.azul = self.criar_carro("car_blue_1.png", "AZUL", "deep sky blue", fase["largada1"].center)
        self.azul.teclas = TECLAS_AZUL
        self.vermelho = self.criar_carro("car_red_1.png", "VERMELHO", "tomato", fase["largada2"].center)
        if st.jogadores == 2:
            self.vermelho.teclas = TECLAS_VERMELHO
        else:
            self.vermelho.cpu = True
            self.vermelho.maxima = MAXIMA * 0.96
        verde = self.criar_carro("car_green_1.png", "VERDE", "lime green", fase["largada3"].center)
        verde.cpu = True
        verde.faixa = 15
        verde.maxima = MAXIMA * 0.94
        amarelo = self.criar_carro("car_yellow_1.png", "AMARELO", "gold", fase["largada4"].center)
        amarelo.cpu = True
        amarelo.faixa = -15
        amarelo.maxima = MAXIMA * 0.9
        self.humanos = [carro for carro in group["carros"] if not carro.cpu]

        placar_azul = Text(text="", top_left=(24, 704), font=FONTE, font_size=26, color=self.azul.cor)
        placar_azul["text"] @= lambda: self.placar(self.azul)
        if st.jogadores == 2:
            placar_vermelho = Text(text="", top_right=(1256, 704), font=FONTE, font_size=26,
                                   color=self.vermelho.cor)
            placar_vermelho["text"] @= lambda: self.placar(self.vermelho)

        self.aviso = letreiro("", (640, 400), 150)
        self.mode = self.largada

    def criar_carro(self, quadro, nome, cor, largada):
        carro = Carro(frame=quadro, center=largada)
        # A pista é da corrida; cada carro guarda os marcos e a vista dela.
        carro.marcos = self.marcos
        carro.vista = self.vista
        carro.angle = carro.rumo_da_pista(0)
        carro.nome = nome
        carro.cor = cor
        return carro

    def on_update(self, dt):
        self.brilhar()

    def brilhar(self):
        # Arredondado, o amount repete: a mesma intensidade é o mesmo Halo.
        halo = Halo("gold", amount=round(st.brilho_luz, 1), style="line")
        for luz in self.pulsando:
            luz.visual = halo

    def placar(self, carro):
        volta = min(carro.voltas + 1, VOLTAS)
        texto = f"volta {volta}/{VOLTAS}   {carro.lugar()}º"
        if carro.tiros > 0:
            texto += "   FOGO!"
        return texto

    @on_mode
    async def largada(self):
        for numero in ["3", "2", "1"]:
            self.aviso.text = numero
            self.aviso.pop()
            play_sound("audio/nota.wav")
            await wait(1)
        self.aviso.text = "JÁ!"
        self.aviso.pop()
        play_sound("audio/nota.wav", pitch=2)
        st.largou = True
        await wait(1)
        self.aviso.text = ""
        self.mode = None

    # A corrida acaba quando os jogadores chegam; a CPU que não chegou fica
    # no lugar em que estava.
    @when(lambda self: all(carro.chegou for carro in self.humanos))
    def fim(self):
        for carro in sorted(group["carros"], key=lambda c: c.lugar()):
            st.podio.append((carro.nome, carro.cor))
        self.after(2, lambda: change_act(Resultado))


def escolher_jogadores(jogadores):
    st.jogadores = jogadores
    change_act(EscolhaPista)


def correr_na(pista):
    st.pista = pista
    change_act(Corrida)


def miniatura(fase, centro, largura):
    """O traçado da pista em miniatura: a linha do meio, encolhida até a
    largura dada, como uma estrada cinza com a faixa branca no meio."""
    pontos = fase["linha"].points
    xs = [x for x, y in pontos]
    ys = [y for x, y in pontos]
    escala = largura / (max(xs) - min(xs))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    pontos = [(centro[0] + (x - mx) * escala, centro[1] + (y - my) * escala) for x, y in pontos]
    Track(points=pontos, closed=True, smooth=1, line_width=LARGURA * escala, color="dim gray", layer="ui")
    Track(points=pontos, closed=True, smooth=1, line_width=2, color="white", layer="ui")


class Escolha(Act):
    # Primeiro passo: quantos jogam. Cada botão na cor do carro de quem vai
    # jogar; as teclas 1 e 2 fazem o mesmo.
    def setup(self):
        letreiro("CORRIDA", (640, 520), 130)
        SpriteButton(poderes, frame="buttonBlue.png", center=(640, 380), width=440,
                     label="UM JOGADOR", font=FONTE, label_color="dodger blue",
                     on_click=lambda: escolher_jogadores(1))
        SpriteButton(poderes, frame="buttonRed.png", center=(640, 280), width=440,
                     label="DOIS JOGADORES", font=FONTE, label_color="firebrick",
                     on_click=lambda: escolher_jogadores(2))
        Text(text="os outros carros são da CPU", center=(640, 200), font=FONTE, font_size=22, layer="ui")

    def on_update(self, dt):
        if keyp.once("1"):
            escolher_jogadores(1)
        if keyp.once("2"):
            escolher_jogadores(2)


class EscolhaPista(Act):
    # Segundo passo: a pista. As duas lado a lado, cada uma com o desenho do
    # seu traçado em cima do botão; as teclas 1 e 2 fazem o mesmo.
    def setup(self):
        letreiro("PISTA", (640, 630), 90)
        quantos = "um jogador" if st.jogadores == 1 else "dois jogadores"
        Text(text=quantos, center=(640, 550), font=FONTE, font_size=24, layer="ui")
        for nome, x, quadro, cor in [("SERPENTINA", 340, "buttonGreen.png", "dark green"),
                                     ("RELÂMPAGO", 940, "buttonYellow.png", "saddle brown")]:
            miniatura(PISTAS[nome], (x, 380), 420)
            SpriteButton(poderes, frame=quadro, center=(x, 170), width=400, label=nome, font=FONTE,
                         label_color=cor, breathe=True, on_click=lambda nome=nome: correr_na(nome))

    def on_update(self, dt):
        if keyp.once("1"):
            correr_na("SERPENTINA")
        if keyp.once("2"):
            correr_na("RELÂMPAGO")


class Resultado(Act):
    def setup(self):
        nome, cor = st.podio[0]
        letreiro(f"{nome} VENCEU", (640, 560), 72)
        y = 440
        for lugar, (nome, cor) in enumerate(st.podio, start=1):
            Text(text=f"{lugar}º   {nome}", center=(640, y), font=FONTE, font_size=32, color=cor, layer="ui")
            y -= 52
        Text(text="aperte ESPAÇO", center=(640, 160), font=FONTE, font_size=24, layer="ui")
        play_sound("audio/Victory.mp3")

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Escolha)


run(Escolha)
