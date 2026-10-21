# Examples

Beginner-style Scena games. Prefer these over smoke/bench when learning the API.
They read like a beginner's code: flat classes, Portuguese names, game data in
`st`, no advanced Python.

## Tutorial endpoints

Each tutorial in [`docs/pt/tutorial/`](../docs/pt/tutorial/index.html) ends in one of these
files: the file is the last step's code plus a docstring, nothing else
(`tests/test_tutorials.py` compares them). Change the tutorial first; then copy
its last step here.

| Tutorial | File |
| --- | --- |
| 01 Primeiro script | `primeiro_script.py` |
| 02 Pegar estrelas | `pegar_estrelas.py` |
| 03 Geometria | `ponto_medio.py` |
| 04 UI Widgets | `cadeia_de_bolas.py`, `desenho.py`, `letreiro.py` |
| 05 Naves | `naves.py` |
| 06 Naves II · Classes | `bolhas.py`, `naves_classes.py` |
| 07 Naves III · Atlas, explosão, vidas | `naves_vidas.py` |
| 08 Naves IV · Escudo | `naves_escudo.py` |
| 09 Fórmulas | `formulas.py` |
| 10 Bolas | `bolas.py` |
| 11 Interação | `interacao.py`, `ceu_estrelado.py` |
| 12 Movimento | `movimento.py` |
| 13 Trilhas | `trilhas.py` |
| 14 Órbitas | `orbitas.py` |
| 15 Avião | `aviao.py` |
| 16 Avião II · Profundidade | `aviao_profundidade.py` |
| 17 Avião III · Paisagem sem fim | `aviao_paisagem.py` |
| 18 Ninja | `ninja.py` |
| 19 Ninja II · O mundo | `ninja_mundo.py` |
| 20 Colisão | `colisao.py` |
| 21 Ligue 4 | `ligue4.py` |
| 22 Estúdio · Piano | `piano.py` |
| 23 Estúdio II · Voz | `estudio_voz.py` |
| 24 Naves V · Capítulos e sequências | `naves_modos.py` |
| 25 Naves VI · Atos | `naves_atos.py` |
| 26 Ninja III · O nível | `ninja_nivel.py` |
| 27 Ninja IV · Perigos | `ninja_perigos.py` |
| 28 Corredor infinito | `corredor.py` |
| 29 Giros | `barras_girando.py`, `osciloscopio.py` |
| 30 Duelo | `duelo.py` |

The appendices (`A-…` to `G-…` in the same folder) are reference pages made of
short programs; they end in no file here.

## Other examples

No tutorial ends in these; each docstring says what to try.

| File | What it shows |
| --- | --- |
| `entropia.py` | Two colours of balls mix once the middle wall goes; the panel counts each side every 5 s (mix, pressure, temperature, energy). Gravity, loose walls that the pressure blows off, a piston. |
| `app_pitagoras.py` | The Pythagorean theorem by rearranging triangles (drag, wheel to turn). |
| `constelacao.py` | Creative coding: drifting points thread to their nearest neighbour (`nearest`) into constellations that keep re-forming; Neon comets hunt the nearest free point and take its colour. Hold the mouse to pull the points, let go for a wave; SPACE adds a comet, T the screen trail. |
| `affinity.py` | Creative coding: invented atoms in a dish with two bonds. Strong bonds (valence, a fast enough collision) make molecules; weak bonds are strings between + and - ends of two molecules that snap and re-form with the heat. Charge comes from the bonds, so white on red bonds and white on amber does not, and the two separate. A soft shell and a steep core keep atoms from piling up; an ion lends charge to the atoms near it, so it holds neutral atoms too. Recipes Nascente / Coroas / Ilhas (1 2 3) and Acaso (R: random rules, ions included, side table); sliders for the atom count and each element's weight, and Rodar to build that mix; UP / DOWN heat, drag to stir, SPACE a spark. The atoms' numbers live on plain objects; the `Circle` only draws. |
| `revoada.py` | Flocking: 120 `Triangle` birds follow three rules (separate, align, gather) and flocks form with no leader. The heading is the colour, so a flock is one colour; the mouse is a falcon whose fright passes from bird to bird (white, thin); the sky lights up (`Bloom`) when the flock is in order. Click for a burst; S / A / J switch the rules. |

```bash
python examples/naves.py
```

More games join this folder when they are ready (each one runs headless in
`tests/test_scripts_run.py`, like these).

## Media and licenses

The images and sounds in `media/` are not under Scena's MIT license. Each
folder has its own `license.txt`, and [`media/CREDITS.md`](media/CREDITS.md)
lists every file's author and license. Most of it is CC0 (no conditions). A few
sounds are CC-BY / CC-BY-SA: a game that ships them must credit their authors
(credits screen or README). The credit lines, ready to copy, are in
[`media/CREDITS.md`](media/CREDITS.md#attribution-required).
