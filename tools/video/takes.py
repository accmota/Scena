"""The shot list: every take ``record_game.py --take`` / ``--all`` records.

A take is one run of one program by one pilot, with its variation in ``args``
and ``seed``. Several takes of a game show the whole game (a win, a loss,
another track); the edit picks the best parts. Ids are ``<game>/<take>``;
``--take <game>`` records all of a game's takes. Output:
``recordings/<game>/<take>.mp4`` and its review sheet ``<take>.review.jpg``.

Programs are the last version of each example (``naves_6_atos``, not
``naves_4_escudo``) and the README's own blocks (``README.md#<clip id>``).

Fields (``DEFAULTS`` fills the rest):
  program   examples/<file>.py or README.md#<clip id>
  pilot     a name in pilots.py (or a README pilot); ``args`` its keywords
  end       "done": the pilot ends the run (``game.done``), ``seconds`` is a cap;
            "cap": the program never ends, the take is ``seconds`` long
  seconds   length (or cap), lead (played before the take), tail (after done)
  layout    None, or "code": the program's code on the left, the game on the right
"""
from __future__ import annotations

DEFAULTS = dict(args={}, lead=0.0, tail=2.0, seed=0, size=(2560, 1440), fps=60, crf=14,
                end="cap", seconds=60.0, layout=None)

# half: the bar's half width plus the star's (they touch inside it). Stars fall
# faster than a bar crosses the screen: even a perfect player misses some.
_PEGAR = dict(paddle="barra", group="estrelas", fall=220, speed=380, half=56)
_CATCH = dict(paddle="paddle", group="stars", fall=180, speed=420, half=63)

TAKES = {
    # Tutorial 01: every feature, scripted in order.
    "primeiro_script/tour": dict(program="examples/primeiro_script.py",
                                 pilot="tour_first_script", end="done", seconds=30),
    # Tutorial 02: a good player and a sloppy one (more "Perdidas").
    "pegar_estrelas/careful": dict(program="examples/pegar_estrelas.py", pilot="catch_falling",
                                   args=dict(_PEGAR, miss=0.08, seed=1), seed=1),
    "pegar_estrelas/sloppy": dict(program="examples/pegar_estrelas.py", pilot="catch_falling",
                                  args=dict(_PEGAR, miss=0.6, reaction=0.5, seed=2), seed=2),
    # README: the whole-game block.
    "catch-the-stars/run": dict(program="README.md#catch-the-stars", pilot="catch_falling",
                                args=dict(_CATCH, miss=0.1, seed=3), seed=3, lead=0.5),
    # Naves VI: a clean win (shields, a pause on the way), a close win (one
    # life left), and a careless game that dies at the boss. Each goes back
    # to the title. Firing in bursts (fire < 1) lets the fleet live long
    # enough to dive; firing all the time clears it in ~12 s.
    "naves_6_atos/victory": dict(program="examples/naves_6_atos.py", pilot="play_naves",
                                 args=dict(fire=0.6, pause_at=14.0, seed=1), seed=1,
                                 end="done", seconds=240),
    "naves_6_atos/close_call": dict(program="examples/naves_6_atos.py", pilot="play_naves",
                                    args=dict(dodge=0.85, shields=False, aim=0.5, fire=0.6,
                                              reaction=0.3, seed=5),
                                    seed=5, end="done", seconds=240),
    "naves_6_atos/game_over": dict(program="examples/naves_6_atos.py", pilot="play_naves",
                                   args=dict(dodge=False, shields=False, aim=0.0, fire=0.5,
                                             reaction=0.4, seed=3),
                                   seed=3, end="done", seconds=240),
    # Avião III: two flights (into a pillar, then a dive), and one long flight.
    "aviao_paisagem/flights": dict(program="examples/aviao_paisagem.py", pilot="fly_plane",
                                   args=dict(flights=(40.0, 25.0), crashes=("pillar", "ground"),
                                             seed=1),
                                   seed=1, end="done", seconds=120),
    "aviao_paisagem/long": dict(program="examples/aviao_paisagem.py", pilot="fly_plane",
                                args=dict(flights=(110.0,), crashes=("pillar",), seed=2),
                                seed=2, end="done", seconds=150),
    # Corrida: both tracks, one and two players (the human cars driven by the
    # game's own CPU brain); menus with the pointer, the results, back to the
    # opening.
    "corrida/serpentina_1p": dict(program="examples/corrida.py", pilot="race",
                                  args=dict(players=1, track="SERPENTINA", seed=1), seed=1,
                                  end="done", seconds=180),
    "corrida/relampago_1p": dict(program="examples/corrida.py", pilot="race",
                                 args=dict(players=1, track="RELÂMPAGO", seed=2), seed=2,
                                 end="done", seconds=180),
    "corrida/serpentina_2p": dict(program="examples/corrida.py", pilot="race",
                                  args=dict(players=2, track="SERPENTINA", seed=3), seed=3,
                                  end="done", seconds=180),
    "corrida/relampago_2p": dict(program="examples/corrida.py", pilot="race",
                                 args=dict(players=2, track="RELÂMPAGO", seed=4), seed=4,
                                 end="done", seconds=180),
    # Corredor: four runs each, every one until the robot falls (the level
    # makes spots no jump clears at the early speeds, so runs are 3-20 s);
    # SPACE in between, the record grows. Seeds with the longest runs.
    "corredor/runs_a": dict(program="examples/corredor.py", pilot="run_robot",
                            args=dict(runs=(60.0,) * 4, ends=("crate", "hole"), seed=10),
                            seed=10, end="done", seconds=300),
    "corredor/runs_b": dict(program="examples/corredor.py", pilot="run_robot",
                            args=dict(runs=(60.0,) * 4, ends=("crate", "hole"), seed=2),
                            seed=2, end="done", seconds=300),
    # Duelo: both players browse the ships and confirm; a match to its end;
    # the victory screen, SPACE back to the choice. The side with more skill
    # (steadier aim, more firing and dodging) usually wins.
    "duelo/blue_wins": dict(program="examples/duelo.py", pilot="duel_match",
                            args=dict(ships=(1, 2), skill=(0.9, 0.5), seed=1), seed=1,
                            end="done", seconds=180),
    "duelo/red_wins": dict(program="examples/duelo.py", pilot="duel_match",
                           args=dict(ships=(2, 1), skill=(0.5, 0.9), seed=2), seed=2,
                           end="done", seconds=180),
    "duelo/even": dict(program="examples/duelo.py", pilot="duel_match",
                       args=dict(ships=(2, 2), skill=(0.8, 0.8), seed=3), seed=3,
                       end="done", seconds=180),
    # Ligue 4: three games in a row (red's row, blue's column, red's
    # diagonal), "Novo jogo" between them; one ball let go off the board.
    "ligue4/three_games": dict(program="examples/ligue4.py", pilot="play_connect4",
                               args=dict(misdrop=(1, 2), seed=1), seed=1, end="done",
                               seconds=180),
    # Ninja V: the whole level by a scripted route (every star, robot and
    # crate; "Todas as estrelas!" on the elevator), and a run that loses its
    # three lives three ways (a pit, a robot, a barrier) and restarts with R.
    "ninja_5_espada/full": dict(program="examples/ninja_5_espada.py", pilot="ninja_route",
                                args=dict(route="full"), end="done", seconds=150),
    "ninja_5_espada/mishaps": dict(program="examples/ninja_5_espada.py", pilot="ninja_route",
                                   args=dict(route="mishaps", restart=True), end="done",
                                   seconds=90),
    # Barras girando (tutorial 30): the bars spin; the pointer drags each
    # slider through its range, M turns the trail on and off.
    "barras_girando/tour": dict(program="examples/barras_girando.py", pilot="slider_tour",
                                args=dict(drags=(("Velocidade", 26, 60, 5.0, 7.5),
                                                 ("Giro", -1.5, 2.0, 12.0, 14.5),
                                                 ("Velocidade", 60, 12, 20.0, 22.5),
                                                 ("Giro", 2.0, -3.0, 26.0, 28.5),
                                                 ("Velocidade", 12, 30, 33.0, 34.5),
                                                 ("Giro", -3.0, -1.5, 36.0, 37.0)),
                                          keys=((10.0, "M"), (17.5, "M"), (30.0, "M"),
                                                (39.0, "M")),   # the trail starts on
                                          end=41.0),
                                end="done", seconds=60),
    # The demos: a tour of each one's controls on a timetable (pilot "tour"),
    # the pointer in view. Times in seconds from the start.
    "osciloscopio/tour": dict(program="examples/osciloscopio.py", pilot="tour", end="done",
                              seconds=70, args=dict(end=46.0, script=(
        ("click", 1.6, "@bola"),                 # the beam and the trail
        ("drag", "tx1", 6, 2, 5.0, 7.0), ("drag", "ty1", 6, -3, 9.0, 11.0),
        ("drag", "x1", 60, 100, 13.0, 15.0), ("drag", "n", 4, 2, 17.0, 19.0),
        ("drag", "y1", 60, -80, 22.0, 24.0), ("drag", "tx1", 2, 9, 27.0, 30.0),
        ("drag", "ty1", -3, 7, 33.0, 36.0), ("drag", "n", 2, 5, 39.0, 41.0),
        ("glide", 41.5, 42.5, (880, 120))))),
    "constelacao/tour": dict(program="examples/constelacao.py", pilot="tour", end="done",
                             seconds=70, lead=1.0, args=dict(end=50.0, script=(
        ("path", 0.0, 30.0, "orbit", (640, 400, 380, 220, 0.06)),
        ("path", 30.0, 50.0, "eight", (640, 400, 420, 230, 0.05)),
        ("key", 2.0, "SPACE"), ("key", 4.5, "SPACE"), ("key", 7.0, "SPACE"),   # comets
        ("key", 9.5, "SPACE"),
        ("press", 12.0, 16.0),                   # held: the points fall to the mouse;
        ("press", 22.0, 25.0),                   # let go: a wave pushes them away
        ("key", 28.0, "T"), ("key", 38.0, "T"),  # the trail of everything
        ("press", 41.0, 44.5)))),
    "app_rgb_arena/tour": dict(program="examples/app_rgb_arena.py", pilot="tour", end="done",
                               seconds=80, args=dict(end=56.0, script=(
        ("click", 1.6, "Criar"), ("click", 2.2, "Criar"), ("click", 2.8, "Criar"),
        ("drag", "R", 1.0, 0.15, 4.5, 6.0), ("drag", "G", 0.25, 0.9, 7.0, 8.5),
        ("drag", "B", 0.12, 0.85, 9.5, 11.0),
        ("click", 12.3, "Criar"), ("click", 12.9, "Criar"),    # new colours
        ("drag", "Atração", 1.0, 2.6, 14.5, 16.5), ("drag", "Repulsão", 1.0, 0.3, 18.0, 20.0),
        ("carry", 23.0, 25.0, "first:hits", (550, 380)),       # grab one, carry it
        ("drag", "Intensidade", 52.0, 120.0, 27.0, 29.0),      # its own sliders now
        ("drag", "R", 1.0, 0.1, 30.0, 31.0), ("drag", "G", 0.1, 0.9, 31.8, 32.8),  # red to cyan
        ("key", 34.0, "SPACE"), ("key", 37.0, "SPACE"),         # pause, run
        ("glide", 38.0, 38.6, (550, 380)),
        ("scroll", 39.0, 1), ("scroll", 39.3, 1), ("scroll", 39.6, 1),  # zoom in
        ("scroll", 42.0, -1), ("scroll", 42.3, -1), ("scroll", 42.6, -1),
        ("drag", "Visual", 1.0, 7.0, 45.0, 47.5),
        ("drag", "Centro", 0.35, 1.8, 49.5, 51.5)))),
    "revoada/tour": dict(program="examples/revoada.py", pilot="tour", end="done", seconds=70,
                         lead=2.0, args=dict(end=50.0, script=(
        ("path", 0.0, 50.0, "eight", (640, 400, 480, 260, 0.06)),   # the falcon
        ("click", 8.0, "middle:passaro"), ("click", 21.0, "middle:passaro"),
        ("key", 14.0, "S"), ("key", 19.0, "S"),  # separation off, on
        ("key", 25.0, "J"), ("key", 30.0, "J"),  # cohesion off, on
        ("click", 34.0, "middle:passaro"),
        ("key", 38.0, "A"), ("key", 43.0, "A")))),   # alignment off, on
    "cadeia_de_bolas/tour": dict(program="examples/cadeia_de_bolas.py", pilot="tour",
                                 end="done", seconds=80, args=dict(end=58.0, script=(
        ("path", 0.0, 10.0, "eight", (500, 350, 330, 190, 0.22)),
        ("drag", "Bolas", 30, 55, 11.0, 13.0), ("click", 14.5, "Rodar"),
        ("path", 15.5, 24.0, "eight", (500, 350, 360, 210, 0.35)),
        ("click", 25.5, "Linhas"), ("click", 27.0, "Rodar"),   # without the lines
        ("path", 28.0, 35.0, "orbit", (500, 350, 300, 200, 0.3)),
        ("click", 36.5, "dropdown"), ("click", 38.0, "option:Flame"),
        ("click", 39.5, "Rodar"),
        ("path", 40.5, 49.0, "eight", (500, 350, 330, 190, 0.28)),
        ("key", 49.5, "ESC"), ("click", 52.0, "Continuar"),     # the pause menu
        ("path", 53.0, 58.0, "orbit", (500, 350, 280, 180, 0.3))))),
    # The level editor (as ``scena-editor`` starts it, with Ninja IV's level):
    # zoom, box-select and lift, then draw, nudge, duplicate, delete, undo,
    # redo, pan and fit. ("w", x, y): world points, through the editor camera.
    "scena-editor/session": dict(program="tools/readme/editor_ninja.py", pilot="tour",
                                 end="done", seconds=60, args=dict(end=31.0, script=(
        ("glide", 0.0, 1.1, ("w", 1250, 260)),
        *[("scroll", 0.1 * k, 1) for k in range(1, 11)],     # zoom about the pointer
        ("carry", 1.6, 2.2, ("w", 1425, 360), ("w", 1695, 250)),   # box select
        ("carry", 2.8, 4.0, ("w", 1560, 300), ("w", 1560, 390)),   # lift the three
        ("click", 5.0, ("w", 1100, 330)),        # one star
        ("key", 6.0, "R"), ("carry", 7.0, 7.8, ("w", 980, 600), ("w", 1180, 680)),
        ("key", 8.4, "C"), ("carry", 9.3, 9.9, ("w", 1290, 640), ("w", 1350, 700)),
        ("key", 10.4, "P"), ("click", 11.2, ("w", 1450, 660)),
        ("key", 11.8, "L"), ("carry", 12.7, 13.4, ("w", 1520, 600), ("w", 1680, 700)),
        ("key", 14.0, "V"), ("click", 15.0, ("w", 1080, 640)),     # select the rect
        ("hold", 15.6, 17.0, "LEFT_SHIFT"),      # Shift+arrows: nudge by the grid
        ("key", 15.8, "RIGHT"), ("key", 16.2, "RIGHT"), ("key", 16.6, "UP"),
        ("hold", 17.6, 18.6, "LEFT_CMD"), ("key", 17.8, "D"), ("key", 18.2, "D"),  # duplicate
        ("key", 19.2, "DEL"),                    # delete the last copy
        ("hold", 20.2, 22.4, "LEFT_CMD"),        # undo three times
        ("key", 20.4, "Z"), ("key", 21.1, "Z"), ("key", 21.8, "Z"),
        ("hold", 23.0, 23.8, "LEFT_CMD"), ("hold", 23.0, 23.8, "LEFT_SHIFT"),
        ("key", 23.3, "Z"),                      # redo
        ("key", 24.5, "H"), ("carry", 25.4, 26.6, (700, 420), (430, 460)),   # pan
        ("key", 27.6, "F"),                      # fit the level in view
        ("key", 29.0, "V"), ("glide", 29.2, 30.4, (1000, 160))))),
    # "This code → this game": the one-screen programs with their code beside
    # the game (the same runs as their plain takes).
    "primeiro_script/code": dict(program="examples/primeiro_script.py",
                                 pilot="tour_first_script", end="done", seconds=30,
                                 layout="code"),
    "pegar_estrelas/code": dict(program="examples/pegar_estrelas.py", pilot="catch_falling",
                                args=dict(_PEGAR, miss=0.08, seed=1), seed=1, layout="code"),
    "catch-the-stars/code": dict(program="README.md#catch-the-stars", pilot="catch_falling",
                                 args=dict(_CATCH, miss=0.1, seed=3), seed=3, lead=0.5,
                                 layout="code"),
    # README: no input, the look plays by itself.
    "electric-hosts/watch": dict(program="README.md#electric-hosts", pilot="watch",
                                 seconds=30, lead=0.5),
}


# Build-up videos (``buildup.py``): a tutorial's steps one after another, each
# step's code beside the step running. ``steps``: per step (from 1) a pilot,
# its args and seconds; a step not listed plays 4 s with no input.
_RIGHT = (("hold", 1.0, 3.0, "RIGHT"),)
BUILDUPS = {
    "primeiro_script": dict(page="docs/pt/tutorial/01-primeiro-script.html",
                            program="examples/primeiro_script.py", steps={
        1: dict(seconds=3.0), 2: dict(seconds=3.0),
        5: dict(seconds=4.5),                    # the looks animate
        7: dict(seconds=4.5),                    # the star moves by itself
        8: dict(pilot="tour", seconds=5.0, args=dict(script=_RIGHT)),
        9: dict(pilot="tour", seconds=5.0, args=dict(script=(
            ("hold", 0.8, 1.4, "RIGHT"), ("hold", 1.4, 2.0, "UP"),
            ("hold", 2.0, 2.6, "LEFT"), ("hold", 2.6, 3.2, "DOWN")))),
        10: dict(pilot="tour", seconds=5.5, args=dict(script=(
            ("click", 1.5, "@triangulo"), ("click", 2.7, "@triangulo"),
            ("click", 3.9, "@triangulo")))),
        11: dict(pilot="tour", seconds=6.0, args=dict(script=(
            ("click", 1.4, "@retangulo"), ("click", 2.4, "@circulo"),
            ("click", 3.4, "@triangulo"), ("click", 4.4, "@circulo")))),
        12: dict(pilot="tour", seconds=6.0, args=dict(script=(
            ("glide", 0.3, 1.0, (620, 610)), ("key", 1.1, "D"),
            ("glide", 1.3, 1.9, (770, 530)), ("key", 2.0, "D"),
            ("glide", 2.2, 2.8, (890, 620)), ("key", 2.9, "D"),
            ("glide", 3.1, 3.7, (850, 330)), ("key", 3.8, "D")))),
        13: dict(pilot="tour", seconds=5.0, args=dict(script=(
            ("hold", 1.0, 2.4, "RIGHT"),))),     # past x = 800: the @when fires
    }),
    "pegar_estrelas": dict(page="docs/pt/tutorial/02-pegar-estrelas.html",
                           program="examples/pegar_estrelas.py", steps={
        1: dict(pilot="tour", seconds=4.5, args=dict(script=(
            ("hold", 0.8, 1.8, "LEFT"), ("hold", 2.2, 3.6, "RIGHT")))),
        2: dict(seconds=4.5),                    # one star falls
        3: dict(seconds=4.5), 4: dict(seconds=5.0), 5: dict(seconds=5.0),
        **{n: dict(pilot="catch_falling", seconds=secs,
                   args=dict(_PEGAR, miss=miss, seed=n))
           for n, secs, miss in ((6, 7.0, 0.1), (7, 5.0, 0.1), (8, 5.0, 0.2),
                                 (9, 7.0, 0.3), (10, 8.0, 0.3))},
    }),
}


def take(tid: str) -> dict:
    """The take ``tid`` with every field filled in."""
    spec = {**DEFAULTS, **TAKES[tid]}
    spec["args"] = dict(spec["args"])
    return spec
