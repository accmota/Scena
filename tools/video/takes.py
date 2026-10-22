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
    # README: no input, the look plays by itself.
    "electric-hosts/watch": dict(program="README.md#electric-hosts", pilot="watch",
                                 seconds=30, lead=0.5),
}


def take(tid: str) -> dict:
    """The take ``tid`` with every field filled in."""
    spec = {**DEFAULTS, **TAKES[tid]}
    spec["args"] = dict(spec["args"])
    return spec
