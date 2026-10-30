# YouTube texts: the build-ups and demos

Ready to paste. Titles and descriptions in English (the videos are in
English), each with a Portuguese version for YouTube Studio's
"Languages" tab (Studio, the video, "Languages", "Add language",
Portuguese (Brazil): title + description).

Each video's file, subtitles and thumbnail are in `videos/finals/buildups/`
(`buildup_<id>.mp4`, `.srt`, `.jpg`).

---

## Tutorial build-ups

Every build-up has its captions as subtitles: upload
`videos/finals/buildups/buildup_<id>.srt` as English subtitles (Studio, the video,
"Subtitles", "Add language", English, "Upload file", "With timing").
YouTube's auto-translate then offers them in other languages.

The build-ups without music are silent on purpose (the step's code and the
game speak). Category: Education.

Description template (fill `{…}`):

```
{one-line summary}

The "{tutorial}" tutorial, step by step: each step's code on the left, the program running on the right, the lines that changed marked.

Read the chapter: {en page}
Em português: {pt page}

[shared footer: footer.md]
```

Descrição (modelo):

```
{resumo}

O tutorial "{tutorial pt}", passo a passo: o código de cada passo à esquerda, o programa rodando à direita, as linhas que mudaram marcadas.

Leia o capítulo: {página pt}
In English: {página en}

[rodapé: footer.md]
```

| id | Title (en) | Título (pt) | Summary | pt summary | Pages |
|---|---|---|---|---|---|
| first_script | Your first Scena script, step by step (34 lines of Python) | Seu primeiro script Scena, passo a passo (34 linhas de Python) | A window, shapes, looks, a sprite, the keyboard and the mouse, and a rule that waits: 34 lines. | Uma janela, formas, visuais, um sprite, teclado e mouse, e uma regra que espera: 34 linhas. | en/tutorial/01-first-script.html · pt/tutorial/01-primeiro-script.html |
| catch_stars | Catch the stars: a whole game in 33 lines of Python | Pegar estrelas: um jogo inteiro em 33 linhas de Python | A bar, falling stars, a group, a collision rule and a scoreboard: a whole game in 33 lines. | Uma barra, estrelas caindo, um grupo, uma regra de colisão e um placar: um jogo inteiro em 33 linhas. | en/tutorial/02-catch-stars.html · pt/tutorial/02-pegar-estrelas.html |
| ships_1 | Ships: a space shooter in 66 lines of Python | Naves: um jogo de tiro espacial em 66 linhas de Python | A ship, shots, a breathing fleet that fires back, hits, bursts and a score: a shooter in 66 lines. | Uma nave, tiros, uma frota que respira e atira de volta, acertos, explosões e placar: um jogo de tiro em 66 linhas. | en/tutorial/05-ships.html · pt/tutorial/05-naves.html |
| balls | Bouncing balls in 39 lines of Python | Bolas quicando em 39 linhas de Python | Walls, twenty balls that bounce off them and off each other, sparks and sounds, a trail and a zoom: 39 lines. | Paredes, vinte bolas que quicam nelas e umas nas outras, faíscas e sons, um rastro e um zoom: 39 linhas. | en/tutorial/10-balls.html · pt/tutorial/10-bolas.html |
| movement | Movement in Scena: click and the ship flies there (30 lines) | Movimento no Scena: clique e a nave voa até lá (30 linhas) | Trips with an easing, a constant speed, facing where it goes, a target ring, a handle to stop it, and following the mouse: 30 lines. | Viagens com suavização, velocidade constante, virando para onde vai, um anel no alvo, um controle para parar e seguir o mouse: 30 linhas. | en/tutorial/12-movement.html · pt/tutorial/12-movimento.html |
| ninja_1_run | A platformer in 46 lines of Python: the ninja runs and jumps | Um jogo de plataforma em 46 linhas de Python: o ninja corre e pula | Platforms, gravity, walking, jumping only from the ground, and an animation for each move: 46 lines. | Plataformas, gravidade, andar, pular só do chão, e uma animação para cada movimento: 46 linhas. | en/tutorial/18-ninja.html · pt/tutorial/18-ninja.html |
| spinning_bars | Spinning bars: a fractal of formulas in 34 lines of Python | Barras girando: um fractal de fórmulas em 34 linhas de Python | A bar spun by a formula of the clock, a function that calls itself, five levels, a glow, a trail and sliders: 34 lines. | Uma barra girada por uma fórmula do relógio, uma função que chama a si mesma, cinco níveis, brilho, rastro e sliders: 34 linhas. | en/tutorial/30-spins.html · pt/tutorial/30-giros.html |
| oscilloscope | An oscilloscope in 39 lines of Python | Um osciloscópio em 39 linhas de Python | A point on a circle, a tip with its own time, a trail, two spins added into a figure, and sliders: 39 lines. | Um ponto num círculo, uma ponta com seu próprio tempo, um rastro, dois giros somados numa figura, e sliders: 39 linhas. | en/tutorial/30-spins.html · pt/tutorial/30-giros.html |

Page URLs are `https://accmota.github.io/Scena/` + the path in the table.

---

## Demos

Music for both: "Adventure Theme" by Cleyton Kauffman (CC0),
https://opengameart.org/content/adventure-theme. Music by Cleyton Kauffman,
https://soundcloud.com/cleytonkauffman

| id | Title (en) | Título (pt) | Summary (en) | Resumo (pt) | Source |
|---|---|---|---|---|---|
| demo100 | Dancing triangles: a Python demo in about 120 lines | Triângulos dançantes: uma demo em Python em cerca de 120 linhas | Rings of triangles open, sway and burst; every triangle is placed by a formula of the clock, and a three-part storyboard runs it all. | Anéis de triângulos se abrem, balançam e explodem; cada triângulo é posto por uma fórmula do relógio, e um roteiro em três partes conduz tudo. | examples/demo100.py |
| old_school | An old-school megademo in Python: eight classic effects | Uma megademo old-school em Python: oito efeitos clássicos | A starfield, a sine scroller, copper bars, a twister, a rotozoomer, plasma and a tunnel, vector balls and a CRT power-off, each rebuilt from Scena parts and run by one storyboard. | Campo de estrelas, letreiro em senoide, barras de cobre, twister, rotozoomer, plasma e túnel, vector balls e o desligar de um CRT, cada um refeito com peças do Scena e conduzido por um roteiro. | examples/old_school.py |

Source URL: `https://github.com/accmota/Scena/blob/main/` + the path.
