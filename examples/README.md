# Examples

Beginner-style Scena games. Prefer these over smoke/bench when learning the API.
They read like a beginner's code: flat classes, Portuguese names, game data in
`st`, no advanced Python. A tutorial already translated also ends in an English
twin of its file (English names, the same program), next to the Portuguese one.

## Tutorial endpoints

Each tutorial in [`docs/pt/tutorial/`](../docs/pt/tutorial/index.html) ends in one of these
files: the file is the last step's code plus a docstring, nothing else
(`tests/test_tutorials.py` compares them). Change the tutorial first; then copy
its last step here. The English file is the English page's last step
(`docs/en/tutorial/`); `tools/tutorial/tutorial_parity.py` holds it to the
Portuguese one, name for name.

| Tutorial | File | English |
| --- | --- | --- |
| 01 Primeiro script | `primeiro_script.py` | `first_script.py` |
| 02 Pegar estrelas | `pegar_estrelas.py` | `catch_stars.py` |
| 03 Geometria | `ponto_medio.py` | `midpoint.py` |
| 04 UI Widgets | `cadeia_de_bolas.py`, `desenho.py`, `letreiro.py` | `ball_chain.py`, `drawing.py`, `banner.py` |
| 05 Naves | `naves_1.py` | `ships_1.py` |
| 06 Naves II · Classes | `bolhas.py`, `naves_2_classes.py` | `bubbles.py`, `ships_2_classes.py` |
| 07 Naves III · Atlas, explosão, vidas | `naves_3_vidas.py` | `ships_3_lives.py` |
| 08 Naves IV · Escudo | `naves_4_escudo.py` | `ships_4_shield.py` |
| 09 Fórmulas | `formulas.py` | `formula_machine.py` |
| 10 Bolas | `bolas.py` | `balls.py` |
| 11 Interação | `interacao.py`, `ceu_estrelado.py` | `interaction.py`, `starry_sky.py` |
| 12 Movimento | `movimento.py` | `movement.py` |
| 13 Trilhas | `trilhas.py` | `tracks.py` |
| 14 Órbitas | `orbitas.py` | `orbits.py` |
| 15 Avião | `aviao.py` | `plane.py` |
| 16 Avião II · Profundidade | `aviao_profundidade.py` | `plane_depth.py` |
| 17 Avião III · Paisagem sem fim | `aviao_paisagem.py` | `plane_landscape.py` |
| 18 Ninja | `ninja_1.py` | `ninja_1_run.py` |
| 19 Ninja II · O mundo | `ninja_2_mundo.py` | `ninja_2_world.py` |
| 20 Colisão | `colisao.py` | `collision.py` |
| 21 Ligue 4 | `ligue4.py` | `connect_four.py` |
| 22 Estúdio · Piano | `piano.py` | `studio_piano.py` |
| 23 Estúdio II · Voz | `estudio_voz.py` | `studio_voice.py` |
| 24 Naves V · Capítulos e sequências | `naves_5_modos.py` | `ships_5_modes.py` |
| 25 Naves VI · Atos | `naves_6_atos.py` | `ships_6_acts.py` |
| 26 Ninja III · O nível | `ninja_3_nivel.py` | `ninja_3_level.py` |
| 27 Ninja IV · Perigos | `ninja_4_perigos.py` | `ninja_4_hazards.py` |
| 28 Ninja V · Espada | `ninja_5_espada.py` | `ninja_5_sword.py` |
| 29 Corredor infinito | `corredor.py` | `runner.py` |
| 30 Giros | `barras_girando.py`, `osciloscopio.py` | `spinning_bars.py`, `oscilloscope.py` |
| 31 Duelo | `duelo.py` | `duel.py` |
| 32 Corrida | `corrida.py` | `race.py` |

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
| `guardiao.py` | An arcade defence game: a ship flies around a glowing ring and shoots outward; two pools of life (ship and ring). Three geometric enemies (`Triangle`, `RegularPolygon`, `Gel`), each with its own shot and explosion (`burst_at`, `fireworks_at`, `debris_at`), and a mine whose blast (`query_circle`) takes the enemies around it, other mines in a chain. The waves are a table read by one task (`run_task`): the camera zooms toward the attack side and turns twice in the game (clock marks show the turn), enemies come out of a `Portal`, `WindStreaks` warn and `Embers` celebrate, and `Bloom` follows the wave. Pills give double, fast and strong shots and a `Portal` shield; a narrow radar (`query_sector`) pulls each shot onto an enemy almost in front. ← / → fly, SPACE shoots. |
| `app_rgb_arena.py` | Particles of light (`GlowSpot`) whose colour is a three-pole charge: red pulls green, green pulls blue, blue pulls red, each pushes the one before. A panel creates, deletes and recolours particles and tunes the forces; drag to move one, the wheel zooms. |

## Showcases

Visual pieces that show what Scena can draw: art pieces and demoscene-style
shows, most of them looping forever. Unlike the rest of this folder, their
names and comments are in English. Each docstring says what to try.

| File | What it shows |
| --- | --- |
| `genesis.py` | The life of a star in six chapters (`Act`s): nebula, accretion disc (light windows streaming down spiral arms), ignition, supernova (`explosion_at`, `ZoomBlur`, `Chroma`), pulsar (camera rotation locked to the beams), remnant. SPACE next chapter; click drops matter. |
| `tesla.py` | An electric garden at night in the rain: Tesla coils, cables where power runs as `begin`/`end` windows, lightning that strikes the tallest thing, a dawn. Drag the lightning rods to steer the strikes; click for a discharge; C for the control-room view (`Crt`). |
| `rose_window.py` | An endless dive into a stained-glass rose window: rings grown by φ in a `History`, counter-rotating glass, two lights walking a {7/3} star. Four movements (Glass, Mirror with `Kaleidoscope`, Dawn, Eclipse with a `difference` moon); 1–4, SPACE holds the dive, click strikes a pane. |
| `loom.py` | A Jacquard loom weaving a tapestry of light from punch cards written as strings at the top of the file. Click the card to punch or fill a hole; UP / DOWN speed; N next card. |
| `old_school.py` | A tribute megademo in eight parts, each classic effect rebuilt from Scena parts (starfield, sine scroller, copper bars, twister, rotozoomer, plasma and tunnel, vector balls, CRT power-off), run by one async storyboard, with music. |
| `pulse.py` | Music-driven visuals: shapes linked to `audio.spectrum()` bands, a beat detector on `@when`, three scenes. M switches to the microphone (VJ mode); 1–3 scenes. |
| `one_line.py` | One line of light that draws itself and turns into a star, a spiral, an eight and a wave; everything else on screen is read from it (`at(u)`, riders, a turning echo, rings). |
| `credits_roll.py` | End credits in which the engine thanks its parts: each feature performs under its own name (History, Concave, `@=`, the impacts, the camera, the looks…). |
| `hundred_lines.py` | An intro in exactly 100 lines: nested hexagons, a spiral vortex, a tunnel; the music drives the strokes under the title. |
| `demo100.py` | Rings of dancing triangles around a `Bolt` heart, in three parts (Open, Dance, Storm), written to be built up step by step. |
| `polygon_ballet.py` | A floor of regular polygons in three movements: domino waves that change their sides and looks, rosettes, and their edges as string art. |
| `string_theory.py` | Lines from simple rules: a times-table cardioid, moiré fans, Lissajous strings, harmonograph curves. Starts with a photosensitivity note (SPACE skips). |

```bash
python examples/naves_1.py
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
