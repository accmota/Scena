"""tools/video pilots that play whole games: the takes end as their names say.

The long runs of ``tests/test_record_game.py`` (gate and deep; quick skips
this module). Each test plays a take of ``tools/video/takes.py`` without
drawing, as the recorder would, and checks the run it was written for.

Bug classes guarded:

* **A take shows another ending than its name.** ``victory`` wins with every
  life, ``close_call`` wins with fewer, ``game_over`` loses, and each one goes
  through the end screen back to the title (where the pilot ends the run). A
  pilot that fires all the time wins even when careless: the losing take
  needs short bursts and slow eyes.
* **A pilot's memory survives a restart.** The plane's flights each last their
  own length; the pilot must move on to the next flight in the frame it
  presses SPACE (a frame later the game is already flying again).
* **A race take skips a screen.** Each race clicks its players and track
  buttons (the take's mode and track are the ones raced), finishes, shows
  the results and goes back to the opening.
* **A duel or a Ligue 4 take ends with another winner.** ``duelo/blue_wins``
  is won by blue with the chosen ships; Ligue 4 plays its three games to
  their named wins, and its off-board drop slides back without a move.
* **A runner take stops after one run.** The corredor takes are several runs
  with SPACE between them; the record never goes down and grows past the
  first run.

    python -m unittest tests.test_record_game_deep -v
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "video"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import pilots  # noqa: E402
import takes as tk  # noqa: E402
from test_record_game import _play  # noqa: E402


def rg_act():
    return pilots.act_name()


class TestWholeGames(unittest.TestCase):
    def test_naves_takes_end_as_named(self):
        """Victory wins with every life, close_call wins with fewer, game_over
        loses; each one sees the end screen and goes back to the title."""
        acts = {}

        def watch(tid):
            def w(ns, t):
                acts.setdefault(tid, []).append(rg_act())
            return w

        ends = {}
        for tid in ("naves_6_atos/victory", "naves_6_atos/close_call", "naves_6_atos/game_over"):
            r = _play(tid, 120, watch(tid))
            self.assertTrue(r["done"], f"{tid}: the run never ended")
            seen = [a for k, a in enumerate(acts[tid]) if k == 0 or a != acts[tid][k - 1]]
            self.assertEqual(seen[-3:], ["Fase", "FimDeJogo", "Titulo"], tid)
            ends[tid] = r["st"]
        self.assertTrue(ends["naves_6_atos/victory"]["venceu"])
        self.assertEqual(ends["naves_6_atos/victory"]["vidas"], 3)
        self.assertTrue(ends["naves_6_atos/close_call"]["venceu"])
        self.assertLess(ends["naves_6_atos/close_call"]["vidas"], 3)
        self.assertFalse(ends["naves_6_atos/game_over"]["venceu"])
        self.assertEqual(ends["naves_6_atos/game_over"]["vidas"], 0)

    def test_plane_flights_last_their_length(self):
        """Each flight lasts its own ``flights[i]`` and ends by its own crash.
        A pilot that moved on to the next flight a frame late (after SPACE had
        already restarted the game) kept the old flight's clock and crashed
        the second flight at once (2026-10-22)."""
        spec = tk.take("aviao_paisagem/flights")
        flights, crashes = spec["args"]["flights"], spec["args"]["crashes"]
        log = []

        def watch(ns, t):
            flying = ns["st"].voando
            if not log or log[-1][1] != flying:
                log.append((t, flying, ns["aviao"].center.y, ns["st"].pontos))

        r = _play("aviao_paisagem/flights", 120, watch)
        self.assertTrue(r["done"])
        downs = [e for e in log if not e[1]]
        ups = [e for e in log if e[1]]
        self.assertEqual(len(downs), len(flights))
        for k, (down, length) in enumerate(zip(downs, flights)):
            took = down[0] - ups[k][0]
            # a dive waits for open air after the next gap (a pillar is 2 s away)
            late = 4.0 if crashes[k] == "ground" else 1.5
            self.assertTrue(length - 0.5 <= took <= length + late,
                            f"flight {k + 1} crashed after {took:.1f} s, not {length}")
            self.assertGreater(down[3], 3, "it flew through gaps")
        ground = [d for d, kind in zip(downs, crashes) if kind == "ground"]
        self.assertTrue(all(d[2] < 35 for d in ground), "a dive ends on the ground")

    def test_races_go_through_every_screen(self):
        for tid in ("corrida/relampago_2p",):        # 2 players, the second track (~50 s CPU a race)
            spec = tk.take(tid)
            screens, picked = [], {}

            def watch(ns, t):
                a = rg_act()
                if not screens or screens[-1] != a:
                    screens.append(a)
                if a == "Corrida":
                    picked.update(players=ns["st"].jogadores, track=ns["st"].pista)

            r = _play(tid, 180, watch)
            self.assertTrue(r["done"], tid)
            self.assertEqual(screens, ["Escolha", "EscolhaPista", "Corrida", "Resultado",
                                       "Escolha"], tid)
            self.assertEqual(picked, {"players": spec["args"]["players"],
                                      "track": spec["args"]["track"]}, tid)

    def test_runner_takes_are_several_runs(self):
        spec = tk.take("corredor/runs_a")
        runs = []

        def watch(ns, t):
            st = ns["st"]
            if not runs or runs[-1][0] != st.correndo:
                runs.append((st.correndo, t, st.recorde))

        r = _play("corredor/runs_a", 300, watch)
        self.assertTrue(r["done"])
        falls = [e for e in runs if not e[0]]
        self.assertEqual(len(falls), len(spec["args"]["runs"]))
        records = [e[2] for e in runs]
        self.assertEqual(records, sorted(records), "the record never goes down")
        self.assertGreater(records[-1], 0)

    def test_duels_end_as_named(self):
        for tid, winner in (("duelo/blue_wins", "AZUL"), ("duelo/red_wins", "VERMELHO")):
            spec = tk.take(tid)
            flown = {}

            def watch(ns, t):
                if rg_act() == "Duelo":
                    flown.update(ships=(ns["st"].tipo_azul, ns["st"].tipo_vermelha))

            r = _play(tid, 180, watch)
            self.assertTrue(r["done"], tid)
            self.assertEqual(flown["ships"], tuple(spec["args"]["ships"]), tid)
            self.assertEqual(r["st"]["vencedor"], winner, tid)

    def test_connect4_games_end_as_named(self):
        import pilots
        spec = tk.take("ligue4/three_games")
        ends, seen = [], {"fim": False}

        def watch(ns, t):
            st = ns["st"]
            if st.fim and not seen["fim"]:
                ends.append((st.vez, len(list(ns["group"]["jogadas"]))))
            seen["fim"] = st.fim

        r = _play("ligue4/three_games", 180, watch)
        self.assertTrue(r["done"])
        names = pilots.play_connect4.__kwdefaults__["games"]
        want = [("vermelho" if n.startswith("red") else "azul", len(pilots.CONNECT4_GAMES[n]))
                for n in names]
        self.assertEqual(ends, want, "each game ends in its win, the misdrop is no move")


if __name__ == "__main__":
    unittest.main()
