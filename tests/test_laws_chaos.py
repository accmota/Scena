"""Laws campaign, stage S7: chaos doors — law F3, the snapshot rule.

At the return of an author function the engine called (a door), the chaos
runtime (``tests/laws/chaos.py``) fires one command an author could write
there; the run is then checked: the law models, no engine-internal
exception, no dead object later, owed work paid (the rest of a contact's
handlers, its ghost, its exit), nothing new in the pass that made it, and
E0-style neutrality for neutral commands (design/Laws.md, F3).

* the machinery: the rewrite keeps every line, the classifier, the owed
  check on synthetic passes (both ways);
* the fixture ``s5_doors``: the idle rewrite is the plain run, every door
  opens, a seeded slice of single-fault runs is clean;
* the directed cells ``s7_cells``: the suspects, today's behaviour pinned
  (CD catalogue in Testing Design);
* canaries (gate): an engine that does not keep its snapshot, caught.

    python tests/run_tiers.py focused test_laws_chaos
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import chaos  # noqa: E402
from laws.known import KNOWN  # noqa: E402
from laws.plants import F3_PLANTS  # noqa: E402

S5, S5_STEPS = chaos.S5, chaos.S5_STEPS
S7 = "tests/laws/fixtures/s7_cells"
SLICE_SEED, SLICE_RUNS = 7, 40

# Doors the fixture must open (pass 1 lists each one at least once).
S5_DOORS = {
    "setup", "update", "on_update", "after", "every", "hover", "hover_exit", "enter", "stay",
    "exit", "leave", "when", "on_destroy", "on_key_down", "on_mouse_down",
    "button>Button._on_mouse_click", "key>TextInput._submit", "button>Menu._choose",
    "tick>Handle._tick_tween",
}


def _base():
    if not hasattr(_base, "run"):
        _base.run = chaos.run(S5, steps=S5_STEPS, listing=True)
    return _base.run


# -- the machinery -------------------------------------------------------------

SOURCE = '''\
def a(x):
    if x:
        return x + 1
    y = x
def b():
    yield 1
f = lambda: 3
class K:
    def m(self):
        pass
'''


class TestRewrite(unittest.TestCase):
    def test_every_node_keeps_its_line(self):
        plain = ast.parse(SOURCE)
        tree = chaos.rewrite(ast.parse(SOURCE))
        code = compile(tree, "<t>", "exec")
        lines = {c.co_name: c.co_firstlineno for c in code.co_consts if hasattr(c, "co_name")}
        ref = compile(plain, "<t>", "exec")
        self.assertEqual(lines, {c.co_name: c.co_firstlineno for c in ref.co_consts
                                 if hasattr(c, "co_name")})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "ret":
                self.assertLessEqual(node.lineno, len(SOURCE.splitlines()))

    def test_returns_go_through_the_runtime_and_keep_their_value(self):
        seen = []

        class Probe:
            def ret(self, v=None):
                seen.append(v)
                return v
        ns = {chaos.NAME: Probe()}
        exec(compile(chaos.rewrite(ast.parse(SOURCE)), "<t>", "exec"), ns)
        self.assertEqual(ns["a"](1), 2)
        self.assertIsNone(ns["a"](0))
        self.assertEqual(list(ns["b"]()), [1])        # a generator: untouched
        self.assertEqual(ns["f"](), 3)                 # a lambda: its body's value
        ns["K"]().m()
        self.assertEqual(seen, [2, None, 3, None])


class TestClassify(unittest.TestCase):
    def test_an_engine_raise_is_a_refusal(self):
        from scena.registry import _OrderedWeakGroup
        try:
            from scena.validate import number
            number("x", "probe")
        except Exception as e:  # noqa: BLE001
            self.assertEqual(chaos.classify(e)[0], "refusal")
        try:
            _OrderedWeakGroup().add(None)              # weakref.ref(None) inside the engine
        except Exception as e:  # noqa: BLE001
            self.assertEqual(chaos.classify(e)[0], "internal")


# -- the owed check on synthetic passes ---------------------------------------

B, R, R2 = "Bola@g.py:1#0", "Rect@g.py:2#0", "Rect@g.py:3#0"


def X(door, fn, *args):
    return ("X", door, "collision", fn, tuple(args), False, False)


def step(*body):
    return [("F", 1, 1 / 60), ("P", "collision", True), ("C", ((B, R),), (), ())] + list(body) \
        + [("S", "resolve"), ("p", "collision"), ("f", 1)]


def fired(command, index, end=None, door="enter"):
    return chaos.Fired(door, 0, command, 1, index, None, end=end if end is not None else index)


class TestOwed(unittest.TestCase):
    def test_a_hidden_handler_of_the_contact_is_named(self):
        base = step(X("enter", "g.py:5:hit", B, R), X("enter", "g.py:9:chip", B, R))
        got = step(X("enter", "g.py:5:hit", B, R), ("d", R, True))
        self.assertTrue(any(m.startswith("C3|") for m in chaos.owed(base, got, fired("destroy.partner", 4))))
        same = step(X("enter", "g.py:5:hit", B, R), ("d", R, True), X("enter", "g.py:9:chip", B, R))
        self.assertEqual(chaos.owed(base, same, fired("destroy.partner", 4, 5)), [])

    def test_a_removed_body_in_another_contact_is_named(self):
        base = step(X("enter", "g.py:5:hit", B, R), X("enter", "g.py:5:hit", B, R2))
        got = step(X("enter", "g.py:5:hit", B, R), ("d", B, True), X("enter", "g.py:5:hit", B, R2))
        self.assertTrue(any(m.startswith("F3|") for m in chaos.owed(base, got, fired("destroy.self", 4, 5))))

    def test_after_an_act_change_the_contact_owes_nothing(self):
        base = step(X("enter", "g.py:5:hit", B, R), X("enter", "g.py:9:chip", B, R))
        got = step(X("enter", "g.py:5:hit", B, R), ("d", B, True), ("d", R, True),
                   X("enter", "g.py:9:chip", B, R))
        self.assertTrue(any("after the act changed" in m
                            for m in chaos.owed(base, got, fired("act", 4, 6))))

    def test_what_a_pass_made_waits_for_its_next_run(self):
        tick = [("F", 1, 1 / 60), ("P", "tick", True),
                ("X", "every", "tick", "g.py:5:spawn", (B,), False, True)]
        made = [("N", "Bola@g.py:7#0", "Bola", "g.py:7", None)]
        late = [("X", "every", "tick", "g.py:8:Bola.ping", ("Bola@g.py:7#0",), False, True)]
        fleet = [("X", "on_update", "tick", "g.py:9:Bola.on_update", ("Bola@g.py:7#0", None), False, True)]
        end = [("p", "tick"), ("f", 1)]
        base = tick + end
        bad = chaos.owed(base, tick + made + late + end, fired("sibling", 3, 4, door="every"))
        self.assertTrue(any(m.startswith("F3|") for m in bad), bad)
        ok = chaos.owed(base, tick + made + fleet + end, fired("sibling", 3, 4, door="every"))
        self.assertEqual(ok, [])        # the fleet's loop starts after the timers'


# -- the fixture ---------------------------------------------------------------

class TestFixture(unittest.TestCase):
    def test_the_idle_rewrite_is_the_plain_run(self):
        plain = chaos.run(S5, steps=S5_STEPS, rewrite_it=False)
        self.assertEqual(chaos.neutral_diff(plain.events, _base().events), [])
        self.assertIsNone(_base().error)

    def test_every_door_opens(self):
        opened = {d for d, *_ in _base().chaos.doors}
        self.assertEqual(S5_DOORS - opened, set())

    def test_no_finding_without_chaos(self):
        self.assertEqual(_base().report.findings, [], _base().report.summary())
        self.assertEqual(_base().zombies, [])

    def test_the_program_did_what_it_does(self):
        s = _base().state
        self.assertEqual((s["points"], s["chips"]), (2, 2))     # two contacts in one step
        self.assertEqual((s["lit"], s["unlit"]), (5, 5))
        self.assertEqual((s["picks"], s["sent"], s["clicks"], s["sounds"]), (2, 1, 2, 1))
        self.assertEqual(s["acts"], 3)
        self.assertGreater(s["stays"], 10)


class TestSlice(unittest.TestCase):
    """A fixed seeded slice of single-fault runs, rare doors weighted up."""

    def test_the_slice_is_clean(self):
        base = _base()
        plans = chaos.draw(base.chaos.doors, SLICE_SEED, SLICE_RUNS)
        bad = []
        ran = 0
        for plan in plans:
            got = chaos.run(S5, steps=S5_STEPS, plan=[plan], seed=SLICE_SEED)
            ran += bool(got.fired and got.fired.outcome == "ran")
            found = [v for v in chaos.verdict(base, got, known=tuple(KNOWN))]
            if found:
                bad.append(f"{chaos.repro(S5, [plan], SLICE_SEED)}: {found[0][:300]}")
        self.assertEqual(bad, [])
        self.assertGreater(ran, SLICE_RUNS // 3)               # not vacuous

    def test_the_commands_reach_and_change_the_run(self):
        base = _base()
        for name in ("destroy.partner", "act", "group.destroy", "park"):
            plan = ("enter", 0, name)
            got = chaos.run(S5, steps=S5_STEPS, plan=[plan])
            self.assertEqual(got.fired.outcome, "ran", name)
            self.assertNotEqual(chaos.neutral_diff(base.events, got.events), [], name)


# -- the directed cells (S7, catalogue CD) ---------------------------------------

def cell(name, frames=12, steps=None, **params):
    return chaos.run(S7, frames=frames, steps=steps, rewrite_it=False,
                     params=dict(cell=name, **params))


class TestCells(unittest.TestCase):
    def test_park_and_resume_in_a_step_exits_then_enters_again(self):
        log = cell("park_resume").state["log"]
        at5 = [e for e in log if e[2] == 5]
        self.assertEqual(sorted(at5), [("exit", "core", 5), ("exit", "zone", 5), ("stay", "zone", 5)])
        self.assertIn(("enter", "zone", 6), log)
        self.assertIn(("enter", "core", 6), log)

    def test_a_tag_dropped_and_taken_back_pairs_its_exit_and_enter(self):
        log = cell("churn").state["log"]
        self.assertEqual(log, [("enter", 1), ("untag", 5), ("exit", 5), ("tag", 6), ("enter", 6),
                               ("untag+tag", 9)])

    def test_cd1_a_hover_target_parked_by_the_old_exit_does_not_light(self):
        """CD1 (fixed): the old target's hover_exit parks the new one; its
        on_hover does not run (L4). Guard: ``test_pointer_hover``."""
        run = cell("hover_park", steps=[("step", 2), ("move", 100, 150), ("step", 2),
                                        ("move", 170, 150), ("step", 3)])
        self.assertEqual(run.state["log"], [("hover", "a", 3, True), ("hover_exit", "a", 5)])
        self.assertEqual([f.sig for f in run.report.findings], [])

    def test_cd2_the_acts_own_hook_stops_with_its_act(self):
        """CD2 (fixed): the act set both bodies' on_collide as a closure over
        the act; the first changes the act; the second does not run after
        the act is gone. A hook that is the game's (no closure over the act)
        runs on. Guard: ``test_act.TestChangeInsideADispatch``."""
        own = cell("act_callable", frames=3).state["log"]
        self.assertEqual([e[0] for e in own], ["hit", "Dois"])
        self.assertTrue(own[0][4])
        game = cell("act_callable", frames=3, closure=False).state["log"]
        # Which side runs first is the colliders' order (by id): either way,
        # the game's hook runs on after the new act was built.
        self.assertEqual([e[0] for e in game], ["hit", "Dois", "hit"])
        self.assertEqual({game[0][1], game[2][1]}, {"p", "q"})

    def test_cd3_a_tag_gained_while_touching_enters_whatever_other_rules(self):
        """CD3 (fixed, per-rule contacts): the shield rule enters when the
        body gains the tag mid-contact, whatever other rule pairs the two;
        dropping the tag while they keep touching runs its exit (CD3-x).
        Guards: ``test_collision`` (CD3 classes), equation E15."""
        want = [("tagged", 5), ("enter", 5), ("stay", 6)]
        for other in (False, True):
            with self.subTest(other_rule=other):
                self.assertEqual(cell("join_rule", other_rule=other).state["log"][:3], want)
                log = cell("join_rule", other_rule=other, untag=True).state["log"]
                self.assertIn(("untagged", 8), log)
                self.assertIn(("exit", 8), log)
                self.assertEqual([e for e in log if e[0] in ("enter", "exit")],
                                 [("enter", 5), ("exit", 8)])

    def test_cd4_an_act_change_drops_the_ending_acts_ghost(self):
        """CD4 (today's rule): the ghost of an act brick goes with its act, so
        a game ball the changing handler broke it under does not bounce."""
        kept = cell("ghost_act", frames=30).state["log"]
        changed = cell("ghost_act", frames=30, change=True).state["log"]
        self.assertEqual(kept[0][0], "hit")
        self.assertEqual(changed[:2], [("hit", 17), ("Dois", 17)])

    def test_cd5_change_act_in_setup_then_a_write_to_the_ended_act(self):
        """CD5 (message): objects made after the change join the new act; a
        write to the ended act is refused (DestroyedError)."""
        ok = cell("act_in_setup", frames=4)
        self.assertIsNone(ok.error)
        self.assertEqual(ok.state["log"][:4], [("Fase.setup",), ("Fase.on_destroy",),
                                               ("Fim.setup",), ("made after the change",)])
        ink = cell("act_in_setup", frames=4, ink=True)
        self.assertEqual(type(ink.error).__name__, "DestroyedError")
        self.assertEqual(ink.error_kind, "refusal")


# -- canaries (gate) ---------------------------------------------------------------

def _first(door, fn):
    return next(n for d, n, _f, _i, name in _base().chaos.doors if d == door and fn in name)


CANARIES = {
    "live_handlers": (lambda: ("enter", _first("enter", "hit"), "destroy.partner"), "C3|"),
    "no_ghost": (lambda: ("enter", _first("enter", "hit"), "destroy.partner"), "C8|"),
    "act_epoch_blind": (lambda: ("enter", _first("enter", "hit"), "act"), "F3|"),
    "live_flush": (lambda: ("when", _first("when", "bright"), "group.destroy"), "L3|"),
    "new_in_pass": (lambda: ("after", 0, "timer"), "X2|"),
    "live_group_walk": (lambda: ("on_update", 0, "group.walk"), "X1|"),
    "tag_changes_forgotten": (lambda: ("stay", 3, "untag"), "C5|"),
}


class TestCanaries(unittest.TestCase):
    def setUp(self):
        require_canaries(self)

    def test_every_f3_plant_bites_through_its_check(self):
        self.assertEqual(set(CANARIES), set(F3_PLANTS))
        missed = []
        for name, (plan_of, prefix) in CANARIES.items():
            plan = plan_of()
            clean = chaos.verdict(_base(), chaos.run(S5, steps=S5_STEPS, plan=[plan]))
            if clean:
                missed.append(f"{name}: not clean without the plant: {clean[:1]}")
                continue
            base = chaos.run(S5, steps=S5_STEPS, listing=True, patches=F3_PLANTS[name]())
            got = chaos.run(S5, steps=S5_STEPS, plan=[plan], patches=F3_PLANTS[name]())
            found = chaos.verdict(base, got)
            if not any(v.startswith(prefix) for v in found):
                missed.append(f"{name}: {prefix} not named; found {[v[:120] for v in found]}")
        self.assertEqual(missed, [])

    def test_a_rewrite_that_loses_a_return_value_is_not_neutral(self):
        class Lose(ast.NodeTransformer):
            def visit_Return(self, node):
                if node.value is not None:
                    node.value = ast.copy_location(ast.Constant(value=None), node.value)
                return node

        def bad(tree):
            return chaos.rewrite(Lose().visit(tree))
        got = chaos.run(S5, steps=S5_STEPS, transform=bad)
        self.assertTrue(chaos.neutral_diff(_base().events, got.events) or got.error is not None)


if __name__ == "__main__":
    unittest.main()
