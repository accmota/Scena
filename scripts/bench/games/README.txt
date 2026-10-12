Benchmark games
===============

Four games written to be timed, not played: real mechanics, written the way
an author writes Scena, each loading one part of the engine hard. They are
not examples or tutorials; nothing in the author docs links here. Their
sibling for correctness is tests/games/ (the game system tests).

  horda.py     top-down arena survival: a crowd of animated enemies steering
               at the hero, resolve("inimigo", "inimigo") crowd separation,
               STATIC pillars, bullets with @collide, gems, a spawner
               (collision, resolve, process tick, spawn churn)
  mundo.py     a long generated tile platformer: STATIC tile Sprites, one-way
               platforms (only=), robots patrolling with floor_below, lifts on
               move_along, raycast turrets, query_circle bombs, parallax
               (big static world, queries, draw walk with most off screen, cull)
  corrida.py   an Endless runner: the track is built slot by slot ahead of the
               camera and released behind, three parallax Endless bands, coins,
               robots, turrets (spawn / destroy churn, refill, large coordinates,
               drift over a long run)
  festa.py     a bullet-hell boss: hundreds of glowing shots (Neon / .glow) that
               tween in, spinning asteroids, ~40 @= HUD labels on State cells,
               @when, Bloom + Vignette, Stars, Fire, Orb, shake
               (draw per look, reactive graph, scheduler, post)

Each game:

* starts with "# harness: cwd=examples/media" (its art resolves from there;
  game_bench.py, tests/script_harness.py and the media guard read the header);
* reads PARAMS (a size knob, seed, auto) and seeds random: the same run every
  time;
* drives itself (auto=True): no input needed; the arrow keys take over;
* must not raise (tests/test_smoke_scripts.py runs each headless) and
  should not warn (check: python tests/script_harness.py <game> 300 --strict).

Sizes: a reference size that must fit the frame budget (<= 4 ms of work on
the M4 the logs come from, about 16 ms on a machine four times slower), and
a ladder that only shows how the cost grows (linear or not, where a cliff
starts). Optimizations are justified at the reference size.

  game      reference                         ladder
  horda     n=150 enemies                     n=50,150,400,1000
  mundo     tiles=1500, robots=20             tiles=500,1500,4000,8000
  corrida   speed=600                         speed=300,600,1500,3000
  festa     n=300 shots                       n=100,300,1000

Run:

  python scripts/bench/game_bench.py scripts/bench/games/horda.py
  python scripts/bench/game_bench.py scripts/bench/games/horda.py --ladder n=50,150,400,1000
  python scripts/bench/game_bench.py scripts/bench/games/mundo.py --cull ab
  python scripts/bench/game_bench.py scripts/bench/games/festa.py --profile 40

Results and the diagnosis: scripts/bench/games.md.
