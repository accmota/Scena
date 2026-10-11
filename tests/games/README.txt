Game system tests
=================

Three games written to be tested, not played: whole-system tests under a real
load. They are not examples or tutorials; nothing here is linked from the
author docs. Strategy, rules and the findings they made: design/Testing
Design.md, "Game system tests".

  armada.py     a shooter with acts (title, hangar, sector, arena, end), modes,
                timers, collision families, hitbox parts, SpatialFx, posts,
                widgets, a pause Menu, music and sound effects
  caverna.py    a platformer on caverna.json (a Level file): resolve, slopes,
                coyote time, a lift, camera deadzone + chase, parallax, Endless,
                clips, History, death and respawn
  oficina.py    a reactive workshop: a Grid board, drag and drop, State cells
                and @= chains, every widget kind, materials, a laser against
                shapes, raycast, Collider, audio effects, the Microphone

Each game:

* starts with "# harness: cwd=examples/media" (art resolves from there; the
  media and colour guards scan this folder);
* imports its instrumentation from tests/game_support.py: G = Ledger(...),
  G.frame() as the first line of update, checks that record and never raise,
  side models whose truth is a Guia sentence, closed-form math or the game's
  own bookkeeping (never the engine function they check);
* reads PARAMS for sizes and switches, and seeds random only.

They run through tests/game_harness.py (scenarios, pilots, reach minimums,
claims) from tests/test_game_<name>.py (quick) and
tests/test_game_<name>_deep.py (SLOW: long runs, L3 oracles, random pilots,
canaries). Run one game alone:

  python tests/run_tiers.py focused test_game_caverna
  SCENA_GAME_CHECKS=raise python -m unittest tests.test_game_caverna
