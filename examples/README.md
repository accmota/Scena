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
| 11 Interação | `interacao.py` |
| 12 Órbitas | `trilhas.py`, `orbitas.py` |
| 13 Giros | `barras_girando.py`, `osciloscopio.py` |
| 14 Avião | `aviao.py` |
| 15 Avião II · Profundidade | `aviao_profundidade.py` |
| 16 Avião III · Paisagem sem fim | `aviao_paisagem.py` |
| 17 Ninja | `ninja.py` |
| 18 Ninja II · O mundo | `ninja_mundo.py` |
| 19 Ligue 4 | `ligue4.py` |
| 20 Estúdio · Piano | `piano.py` |
| 21 Estúdio II · Voz | `estudio_voz.py` |
| 22 Naves V · Capítulos e sequências | `naves_modos.py` |
| 23 Naves VI · Atos | `naves_atos.py` |
| 24 Ninja III · O nível | `ninja_nivel.py` |
| 25 Ninja IV · Perigos | `ninja_perigos.py` |
| 26 Corredor infinito | `corredor.py` |

The appendices (`A-…` to `F-…` in the same folder) are reference pages made of
short programs; they end in no file here.

## Other examples

No tutorial ends in these; each docstring says what to try.

| File | What it shows |
| --- | --- |
| `entropia.py` | Two colours of balls mix once the middle wall goes; the panel counts each side every 5 s (mix, pressure, temperature, energy). Gravity, loose walls that the pressure blows off, a piston. |
| `app_pitagoras.py` | The Pythagorean theorem by rearranging triangles (drag, wheel to turn). |

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
