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
    # Debug mode over a run: none at first, then each overlay in turn, the
    # earlier ones kept on. Ninja V: Ctrl+Shift+7 (hitboxes, view frame,
    # HUD), then +6 (the process panel: the invincibility task, modes).
    # Naves VI: +7, then +8 (debug zoom: the world past the screen).
    "ninja_5_espada/debug": dict(program="examples/ninja_5_espada.py", pilot="with_debug_keys",
                                 end="done", seconds=150,
                                 args=dict(pilot="ninja_route", args=dict(route="full"),
                                           chords=((9.0, "7"), (21.0, "6")))),
    "naves_6_atos/debug": dict(program="examples/naves_6_atos.py", pilot="with_debug_keys",
                               seed=1, end="done", seconds=240,
                               args=dict(pilot="play_naves", args=dict(fire=0.6, seed=1),
                                         chords=((7.0, "7"),     # the whole fleet boxed
                                                 (19.0, "8")))),  # the boss, from off screen
    # README: no input, the look plays by itself.
    "electric-hosts/watch": dict(program="README.md#electric-hosts", pilot="watch",
                                 seconds=30, lead=0.5),
}


# Build-up videos (``buildup.py``): a tutorial's steps one after another, each
# step's code beside the step running, from the English pages. ``steps``: per
# step (from 1) a pilot, its args and seconds; a step not listed plays 4 s
# with no input. ``example``: on a page that ends in two programs, whose steps.
# ``finale``: after the last step's own seconds the game plays on
# (``buildup.FINALE``) with this pilot and args (none: the step's pilot goes on).
# A chapter build-up (``chapters``) is one run of a demo: ``(title, picks,
# folds)`` each (``buildup.excerpt``), the next one on screen when ``key(game)``
# changes; the last, the storyboard as the demo loops, ends the take.
_EN = "docs/en/tutorial/"
_BAR = dict(paddle="bar", group="stars", fall=220, speed=380, half=56)
_SWEEP = (("hold", 0.5, 1.5, "LEFT"), ("hold", 1.5, 3.3, "RIGHT"), ("hold", 3.3, 4.0, "LEFT"))
_SWEEP_FIRE = _SWEEP + (("hold", 0.6, 4.2, "SPACE"),)
_LONG_SWEEP_FIRE = (("hold", 0.4, 1.6, "LEFT"), ("hold", 1.6, 3.8, "RIGHT"),
                    ("hold", 3.8, 5.4, "LEFT"), ("hold", 5.4, 6.4, "RIGHT"),
                    ("hold", 0.5, 6.6, "SPACE"))
_TRIPS = (("click", 1.0, (750, 220)), ("click", 2.6, (250, 500)), ("click", 4.2, (620, 560)))


def _tour(seconds, *script):
    return dict(pilot="tour", seconds=seconds, args=dict(script=script))


def _finale(*script):
    return dict(pilot="tour", args=dict(script=script))


BUILDUPS = {
    "first_script": dict(page=_EN + "01-first-script.html", program="examples/first_script.py",
                         steps={
        1: dict(seconds=3.0), 2: dict(seconds=3.0),
        5: dict(seconds=4.5),                    # the looks animate
        7: dict(seconds=4.5),                    # the star moves by itself
        8: _tour(5.0, ("hold", 1.0, 3.0, "RIGHT")),
        9: _tour(5.0, ("hold", 0.8, 1.4, "RIGHT"), ("hold", 1.4, 2.0, "UP"),
                 ("hold", 2.0, 2.6, "LEFT"), ("hold", 2.6, 3.2, "DOWN")),
        10: _tour(5.5, ("click", 1.5, "@triangle"), ("click", 2.7, "@triangle"),
                  ("click", 3.9, "@triangle")),
        11: _tour(6.0, ("click", 1.4, "@rectangle"), ("click", 2.4, "@circle"),
                  ("click", 3.4, "@triangle"), ("click", 4.4, "@circle")),
        12: _tour(6.0, ("glide", 0.3, 1.0, (620, 610)), ("key", 1.1, "D"),
                  ("glide", 1.3, 1.9, (770, 530)), ("key", 2.0, "D"),
                  ("glide", 2.2, 2.8, (890, 620)), ("key", 2.9, "D"),
                  ("glide", 3.1, 3.7, (850, 330)), ("key", 3.8, "D")),
        13: _tour(5.0, ("hold", 1.0, 2.4, "RIGHT")),   # past x = 800: the @when fires
    }, finale=_finale(("hold", 0.3, 1.0, "LEFT"), ("click", 2.0, "@circle"),   # the star back
                      ("click", 3.0, "@triangle"), ("glide", 3.4, 4.0, (620, 610)),
                      ("key", 4.2, "D"), ("glide", 4.4, 4.9, (770, 560)), ("key", 5.1, "D"),
                      ("hold", 5.6, 6.4, "UP"), ("click", 7.2, "@rectangle"))),
    "catch_stars": dict(page=_EN + "02-catch-stars.html", program="examples/catch_stars.py",
                        steps={
        1: _tour(4.5, ("hold", 0.8, 1.8, "LEFT"), ("hold", 2.2, 3.6, "RIGHT")),
        2: dict(seconds=4.5),                    # one star falls
        3: dict(seconds=4.5), 4: dict(seconds=5.0), 5: dict(seconds=5.0),
        **{n: dict(pilot="catch_falling", seconds=secs, args=dict(_BAR, miss=miss, seed=n))
           for n, secs, miss in ((6, 7.0, 0.1), (7, 5.0, 0.1), (8, 5.0, 0.2),
                                 (9, 7.0, 0.3), (10, 8.0, 0.3))},
    }),
    "movement": dict(page=_EN + "12-movement.html", program="examples/movement.py", steps={
        1: _tour(4.0, ("click", 1.0, (750, 220)), ("click", 2.5, (250, 500))),   # jumps there
        **{n: _tour(5.5, *_TRIPS) for n in (2, 3, 4, 5, 6)},   # time, speed, ease, face, ring
        7: _tour(6.0, ("click", 1.0, (820, 160)), ("key", 1.7, "SPACE"),         # halted
                 ("click", 2.6, (200, 560)), ("click", 4.3, (850, 500))),
        8: _tour(7.0, ("path", 0.8, 4.4, "orbit", (500, 350, 280, 180, 0.3)),
                 ("rpress", 1.0, 4.2),           # the right button: follow the mouse
                 ("click", 5.2, (300, 220))),
    }, finale=_finale(("click", 1.0, (780, 560)), ("click", 2.8, (220, 200)),
                      ("key", 3.6, "SPACE"),
                      ("path", 4.2, 7.8, "orbit", (500, 350, 260, 170, 0.3)),
                      ("rpress", 4.4, 7.6))),
    "ships_1": dict(page=_EN + "05-ships.html", program="examples/ships_1.py", steps={
        **{n: _tour(4.5, *_SWEEP) for n in (1, 2, 3, 4)},
        **{n: _tour(4.5, *_SWEEP_FIRE) for n in (5, 6)},
        # @leave_playfield: hitboxes and the view frame (7), the debug zoom
        # (8: 50 %, then 25 %, then back to 100 %) show the shots leave the
        # screen and go; then the overlays off again.
        7: dict(pilot="with_debug_keys", seconds=9.0, args=dict(
            pilot="tour", args=dict(script=_LONG_SWEEP_FIRE + (("hold", 7.0, 8.4, "SPACE"),)),
            chords=((1.0, "7"), (1.6, "8"), (4.4, "8"), (7.2, "8"), (7.8, "7")))),
        8: dict(seconds=4.0), 9: dict(seconds=4.0), 10: dict(seconds=4.0),
        11: dict(seconds=5.0), 12: dict(seconds=5.0),          # the fleet moves
        **{n: _tour(7.0, *_LONG_SWEEP_FIRE) for n in (13, 14, 15)},
        # the last: played to the end of the finale, then hit (the new @collide);
        # while the viewer reads, it only dodges (idle, it would be shot down)
        16: dict(pilot="shoot_fleet", seconds=7.0,
                 args=dict(fire=0.5, careless_from=10.5, seed=16),
                 reader="shoot_fleet", reader_args=dict(fire=0.0, seed=160)),
    }),
    "ninja_1_run": dict(page=_EN + "18-ninja.html", program="examples/ninja_1_run.py", steps={
        1: dict(seconds=3.0), 2: dict(seconds=3.0),            # gravity: it falls away
        3: dict(seconds=3.5),                                  # the floor holds
        4: _tour(4.5, ("hold", 0.6, 2.4, "RIGHT"), ("hold", 2.8, 3.8, "LEFT")),
        **{n: _tour(6.0, ("hold", 0.5, 4.0, "RIGHT"), ("key", 1.0, "UP"),
                    ("key", 2.3, "UP"), ("hold", 4.3, 5.4, "LEFT"), ("key", 4.6, "UP"))
           for n in (5, 6)},
    }, finale=_finale(("hold", 0.3, 2.5, "RIGHT"), ("key", 0.8, "UP"), ("key", 2.0, "UP"),
                      ("hold", 3.0, 5.5, "LEFT"), ("key", 3.4, "UP"), ("key", 4.6, "UP"),
                      ("hold", 6.0, 7.5, "RIGHT"), ("key", 6.4, "UP"))),
    "balls": dict(page=_EN + "10-balls.html", program="examples/balls.py", steps={
        1: dict(seconds=3.0),
        **{n: dict(seconds=4.5) for n in (2, 3, 4, 5, 6, 7)},
        8: dict(seconds=6.0),                                  # the stroke grows
        9: _tour(6.0, ("glide", 0.3, 0.9, (500, 360)),
                 *[("scroll", 1.0 + 0.2 * k, 1) for k in range(5)],
                 *[("scroll", 3.2 + 0.2 * k, -1) for k in range(5)]),
        10: dict(seconds=6.0),
    }, finale=_finale(("glide", 0.3, 1.2, "@chosen"),       # zoom in where the gold ball is, out
                      *[("scroll", 1.4 + 0.2 * k, 1) for k in range(4)],
                      *[("scroll", 5.6 + 0.2 * k, -1) for k in range(4)])),
    "spinning_bars": dict(page=_EN + "30-spins.html", example="spinning_bars.py",
                          program="examples/spinning_bars.py", steps={
        8: _tour(6.0, ("drag", "Speed", 26, 60, 1.0, 2.0), ("drag", "Spin", -1.5, 2.0, 2.6, 3.6),
                 ("key", 4.4, "M")),
    }, finale=_finale(("drag", "Speed", 60, 15, 1.0, 2.5), ("drag", "Spin", 2.0, -2.5, 3.4, 5.0),
                      ("key", 5.8, "M"), ("drag", "Speed", 15, 35, 6.4, 7.6))),
    "oscilloscope": dict(page=_EN + "30-spins.html", example="oscilloscope.py",
                         program="examples/oscilloscope.py", steps={
        5: _tour(4.5, ("click", 1.2, "@ball")),               # the click switches it on
        6: _tour(7.0, ("click", 1.0, "@ball"), ("drag", "tx1", 6, 2, 2.0, 3.0),
                 ("drag", "ty1", 6, -3, 3.5, 4.5), ("drag", "n", 4, 2, 5.0, 6.0)),
    }, finale=_finale(("drag", "tx1", 2, 7, 1.0, 2.5), ("drag", "ty1", -3, 5, 3.2, 4.7),
                      ("drag", "n", 2, 5, 5.4, 6.6))),
    # The demos: one run each, the code of the part on screen.
    "old_school": dict(program="examples/old_school.py", seconds=240,
                       key=lambda game: game.ns["st"].t0 or None,   # new_part() sets it
                       chapters=(
        ("I  Starfield", ("starfield",)),
        ("II  Sine scroller", ("MESSAGE", "SPACING", "SCROLL", "scroll_place", "scroller")),
        ("III  Copper bars", ("COPPER", "drop_ghost", "copper_bars")),
        # the shades made once (PAINTS) are a speed-up, not the effect
        ("IV  Twister", ("ROWS", "RADIUS", "STEPS", "LIGHT", "Row", "twister"),
         ("Row.__doc__", "Row.setup")),
        ("V  Rotozoomer", ("rotozoomer",)),
        ("VI  Plasma", ("plasma",)),
        ("VII  Vector balls", ("BALLS", "BALL_COLORS", "cube_point", "sphere_point", "ring_point",
                               "blend3", "Ball", "vector_balls"),
         ("cube_point", "sphere_point", "ring_point", "blend3", "Ball.__doc__")),
        ("VIII  Power off", ("power_off",)),
        ("The storyboard", ("light", "play_sound", "new_part", "cut", "show", "update",
                            "run_task", "run")),
    )),
    "demo100": dict(program="examples/demo100.py", seconds=120,
                    key=lambda game: (game.ns["st"].sway > 0, game.ns["st"].spin > 1),
                    chapters=(
        ("I  Open", ("turn", "reach", "make_rings", ("show", "# I  Open", "# II  Dance"))),
        ("II  Dance", ("st", "reach", ("show", "# II  Dance", "# III  Storm"))),
        ("III  Storm", ("turn", ("show", "# III  Storm", "# back to the start"))),
        ("The storyboard", ("show", "run_task", "run")),
    )),
}


# What each build-up says on screen (``buildup.py``: big, above the game;
# and the ``.srt``). Per step from 1 (a step not listed shows its title);
# ``(offset, text)`` pairs when a step says more than one thing, each from
# that many seconds into the step; "finale" after the last step's own
# seconds ({lines}: the program's lines of code). Chapter build-ups: per
# chapter from 1. Say what to look at, not what the code is called; one line.
_SAY = {
    "first_script": {
        1: "One line opens a window", 2: "A background for the window",
        3: "Three shapes, each placed by its center", 4: "A color for each shape",
        5: "A look for each: halo, glow, neon", 6: "A sprite: a picture from a file",
        7: "update() runs every frame: the star moves", 8: "Hold RIGHT and the star moves",
        9: "The four arrows move it every way", 10: "A click on the triangle: a new color",
        11: "One rule, three shapes to click", 12: "Press D: a circle where the mouse is",
        13: ((0.0, "A rule waits for the star to pass x = 800"),
             (1.9, "There: the triangle whitens, the circle grows")),
    },
    "catch_stars": {
        1: "A bar that the arrows move", 2: "A star falls", 3: "A new star every 0.9 seconds",
        4: "A list moves every star", 5: "A group: the same, with less code",
        6: "Catch a star and it is gone", 7: "Missed stars fall on forever, unseen",
        8: "Missed stars are deleted below the screen", 9: "A scoreboard: caught and missed",
        10: "The bar pops, a lost star flashes", "finale": "The finished game: {lines} lines",
    },
    "movement": {
        1: "Click: the ship jumps there", 2: "Now it travels there, in one second",
        3: "The same speed for every trip", 4: "It speeds up, then slows down",
        5: "It turns to face where it goes", 6: "A ring marks the target until it lands",
        7: ((0.0, "Every trip has a handle to stop it"), (1.7, "SPACE: the trip stops halfway")),
        8: ((0.0, "Hold the right button: it follows"), (4.9, "A click sends it again")),
    },
    "ships_1": {
        1: "A ship the arrows move", 2: "It stays inside the screen",
        3: "A sky: gradient, stars, grain, glow", 4: "The ship glows",
        5: "SPACE fires: a shot every 0.2 s", 6: "The shots fly up",
        7: ((0.0, "Shots that leave the screen are deleted"),
            (1.6, "Debug view: the world beyond the screen"),
            (4.4, "Each shot vanishes as it leaves"), (7.2, "Back to the normal view")),
        8: "A fleet: 3 rows of 8", 9: "Each column its own hue", 10: "The fleet breathes",
        11: "The fleet moves, and keeps going", 12: "Back and forth between the edges",
        13: "A shot hits an enemy: both are gone", 14: "A burst for each hit, and a score",
        15: "The fleet fires back", 16: "Enemy shots can now destroy the ship",
        "finale": ((0.0, "The finished game: {lines} lines"), (4.0, "One shot too many")),
    },
    "ninja_1_run": {
        1: "Floor, platforms and the ninja", 2: "Gravity: the ninja falls through",
        3: "Now the floor holds", 4: "The arrows walk; walls at the sides",
        5: "UP jumps, only from the ground", 6: "Run, jump, stand: an animation for each",
        "finale": "The finished game: {lines} lines",
    },
    "balls": {
        1: "Four walls", 2: "One ball, moving on its own",
        3: "A rule: balls bounce off the walls", 4: "Twenty balls, random directions",
        5: "Balls bounce off each other too", 6: "A spark and a sound at each wall",
        7: "One ball is chosen: gold, with a tail", 8: "A trail draws its path",
        9: "The wheel zooms in and out", 10: "A bar shows its speed",
    },
    "spinning_bars": {
        1: "A bar spins, by a formula of the clock", 2: "A function that makes bars",
        3: "It calls itself: a bar at the tip", 4: "Attached: the child follows its parent",
        5: "Two children for every bar", 6: "Five levels, a color for each",
        7: "A background, a glow and a trail", 8: "Sliders for speed and spin; M for the trail",
    },
    "oscilloscope": {
        1: "A point turning on a circle", 2: "The tip keeps its own time",
        3: "A trail behind the tip", 4: "Two spins added: a figure",
        5: "A click on the ball switches it on", 6: "Sliders change the figure",
    },
    "old_school": {
        1: "Stars fly at you; letters fly into place",
        2: "Letters ride a sine wave, placed by a formula",
        3: "Copper bars: light adds where they cross",
        4: "100 rows, each a slice of a turning column",
        5: "The whole world tiles, turns and zooms",
        6: "A plasma sky, then a dive into a tunnel",
        7: "64 balls: a cube, a sphere, a ring",
        8: "An old TV switching off",
        9: "The storyboard: the demo's running order",
    },
    "demo100": {
        1: "Every triangle is placed by a formula", 2: "Two waves: a sway that never repeats",
        3: "Faster and faster, then a burst", 4: "The storyboard: three parts, on a loop",
    },
}
for _bid, _say in _SAY.items():
    BUILDUPS[_bid]["say"] = _say


def take(tid: str) -> dict:
    """The take ``tid`` with every field filled in."""
    spec = {**DEFAULTS, **TAKES[tid]}
    spec["args"] = dict(spec["args"])
    return spec
