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
"""
from __future__ import annotations

DEFAULTS = dict(args={}, lead=0.0, tail=2.0, seed=0, size=(2560, 1440), fps=60, crf=14,
                end="cap", seconds=60.0)

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
    # README: no input, the look plays by itself.
    "electric-hosts/watch": dict(program="README.md#electric-hosts", pilot="watch",
                                 seconds=30, lead=0.5),
}


def take(tid: str) -> dict:
    """The take ``tid`` with every field filled in."""
    spec = {**DEFAULTS, **TAKES[tid]}
    spec["args"] = dict(spec["args"])
    return spec
