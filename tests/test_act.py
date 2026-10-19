"""Acts: ``class Fase(Act)``, ``change_act(Fase)``, ``run(Titulo)``.

Design: design/Act Design.md. Headless: ``SystemWorld.begin_game``
ends the top level through the same ``ScenaFramework._begin_game`` that
``run()`` uses.

    python tests/run_tiers.py focused test_act
"""
from __future__ import annotations

import builtins
import os
import gc
import warnings
import weakref
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402

import inspect  # noqa: E402

import scena  # noqa: E402
from scena import (  # noqa: E402
    ANYTHING, STATIC, Bloom, Circle, Entity, Line, Point, Rect, Stars, Text, Vignette, after, audio, canvas, clock,
    collide, collide_exit, collision, group, leave_playfield, on_change, on_mode, play_sound,
    resolve, set_defaults, unresolve, wait, when, st, ui,
)
from scena.collision import get_collision_system  # noqa: E402
from scena.process import (  # noqa: E402
    get_scheduler, last_author_error, report_author_warning,
)
from system_support import census, diff_census, format_diff, kitchen_sink, tone  # noqa: E402
from scena.style import PaintState  # noqa: E402
import scena.orchestration as orch  # noqa: E402
from scena.bounds import get_bounds_system  # noqa: E402
from scena.act import (  # noqa: E402
    KEPT_SETTINGS, WORLD_SETTINGS, Act, ActUsageError, change_act,
    get_act_manager,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def current():
    return get_act_manager().current


class Log(list):
    """Shared per-test event log (class bodies below append to ``LOG``)."""


LOG = Log()


# ---------------------------------------------------------------------------
# Acts used across tests
# ---------------------------------------------------------------------------

class Vazia(Act):
    def setup(self):
        LOG.append(("setup", "Vazia"))


class Fase(Act):
    def setup(self):
        LOG.append(("setup", "Fase", current() is self))
        self.heroi = Circle(center=(10, 10), radius=5, group="heroi")
        # Undrawn: the registry holds it weakly, so the act keeps it (an
        # unreferenced Entity that does nothing is collected, act or not).
        self.diretor = Entity(group="diretor")
        Point(3, 4)

    def on_destroy(self):
        # Runs first, while the act's objects are still alive.
        LOG.append(("fase_on_destroy", bool(self.heroi), len(group["heroi"])))


class FimDeJogo(Act):
    def setup(self):
        LOG.append(("setup", "FimDeJogo"))
        Rect(center=(0, 0), width=4, height=4, group="placa")


class Recomeca(Act):
    def setup(self):
        Circle(group="heroi_unico")


class MudaNoSetup(Act):
    def setup(self):
        LOG.append(("setup", "MudaNoSetup"))
        Circle(group="perdido")
        change_act(FimDeJogo)


class Heroi(Circle):
    def on_destroy(self):
        change_act(FimDeJogo)  # act flow in the wrong place


class ComHeroiRedirecionador(Act):
    def setup(self):
        Heroi(center=(0, 0), radius=3)


class ActTestCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        LOG.clear()

    def begin(self, first=None, setup=None):
        self.w.begin_game(first, setup=setup)


# ---------------------------------------------------------------------------
# Starting and switching
# ---------------------------------------------------------------------------

class TestStartAndChange(ActTestCase):

    def test_run_first_act_builds_after_the_seal_and_is_current_in_setup(self):
        game = Circle(group="jogo")
        self.begin(Fase)
        self.assertIsInstance(current(), Fase)
        self.assertIn(("setup", "Fase", True), LOG)
        self.assertTrue(get_act_manager().sealed)
        change_act(FimDeJogo)
        self.assertTrue(game.is_alive, "top-level objects are the game")

    def test_change_removes_everything_the_act_created(self):
        self.begin(Fase)
        fase = current()
        heroi = fase.heroi
        diretor = list(group["diretor"])[0]
        change_act(FimDeJogo)
        self.assertFalse(fase.is_alive)
        self.assertFalse(heroi.is_alive)
        self.assertFalse(diretor.is_alive, "undrawn act entities leave too")
        self.assertEqual(len(group["heroi"]), 0)
        self.assertIsInstance(current(), FimDeJogo)

    def test_undrawn_entity_held_only_by_act_ink_still_gets_on_destroy(self):
        import gc
        gone = []

        class Diretor(Entity):
            def on_destroy(self):
                gone.append("diretor")

        class ComDiretor(Act):
            def setup(self):
                self.diretor = Diretor()

        self.begin(ComDiretor)
        # Collect at the worst moment: after the act's teardown cleared its
        # ink, before the batch drain (the change must hold the batch).
        from scena.act import ActManager
        drain = ActManager._teardown

        def collect_then_drain(manager, first_error, *rest):
            gc.collect()
            return drain(manager, first_error, *rest)

        with mock.patch.object(ActManager, "_teardown", collect_then_drain):
            change_act(Vazia)
        self.assertEqual(gone, ["diretor"])

    def test_act_on_destroy_runs_first_with_objects_alive(self):
        self.begin(Fase)
        change_act(Vazia)
        self.assertIn(("fase_on_destroy", True, 1), LOG)

    def test_restart_builds_a_fresh_instance(self):
        self.begin(Recomeca)
        first = current()
        change_act(Recomeca)
        self.assertIsNot(current(), first)
        self.assertIsInstance(current(), Recomeca)
        change_act(Recomeca)
        self.assertEqual(len(group["heroi_unico"]), 1)  # the old one left

    def test_game_objects_survive_many_changes(self):
        game = Circle(group="jogo")
        leader = Entity()
        leader.x = 1
        self.begin(Fase)
        for cls in (FimDeJogo, Fase, Vazia, Fase) * 3:
            change_act(cls)
        self.assertTrue(game.is_alive)
        self.assertTrue(leader.is_alive)
        self.assertEqual(leader.x, 1)

    def test_parts_of_game_objects_created_after_the_seal_stay(self):
        # A game object's registered part (a Point) made after the top level
        # ended is not an act object: parts leave with their owner.
        game = Rect(center=(0, 0), width=10, height=10)
        self.begin(Vazia)
        game.show_points()
        parts = [p for p in game.parts if isinstance(p, Point)]
        change_act(Vazia)
        self.assertTrue(game.is_alive)
        self.assertTrue(all(p.is_alive for p in parts))

    def test_script_setup_hook_objects_and_system_labels_survive(self):
        made = []
        self.begin(Fase, setup=lambda c: made.append(Circle(group="do_setup")))
        change_act(Vazia)
        self.assertTrue(made[0].is_alive, "script setup(canvas) belongs to the game")
        fw = self.w.fw
        self.assertTrue(fw._system_label.is_alive)
        self.assertTrue(fw._error_label.is_alive)

    def test_objects_created_after_the_change_line_belong_to_the_new_act(self):
        self.begin(Vazia)
        change_act(Fase)
        late = Circle(group="tardio")
        change_act(Vazia)
        self.assertFalse(late.is_alive)

    def test_change_act_inside_setup_builds_the_target(self):
        self.begin(Vazia)
        change_act(MudaNoSetup)
        self.assertIsInstance(current(), FimDeJogo)
        self.assertEqual(len(group["perdido"]), 0)

    def test_change_act_from_timer_and_update(self):
        self.begin(Vazia)
        after(0.05, lambda: change_act(FimDeJogo))
        self.w.seconds(0.1)
        self.assertIsInstance(current(), FimDeJogo)
        self.w.on_update(lambda dt: change_act(Vazia) if isinstance(current(), FimDeJogo) else None)
        self.w.step(1)
        self.assertIsInstance(current(), Vazia)

    def test_act_on_update_runs_each_frame(self):
        ticks = []

        class Conta(Act):
            def on_update(self, dt):
                ticks.append(dt)

        self.begin(Conta)
        self.w.step(3)
        self.assertEqual(len(ticks), 3)

    def test_act_timers_stop_on_leave(self):
        fired = []

        class ComTimer(Act):
            def setup(self):
                self.after(0.05, lambda: fired.append("act"))

        self.begin(ComTimer)
        change_act(Vazia)
        self.w.seconds(0.2)
        self.assertEqual(fired, [])


# ---------------------------------------------------------------------------
# change_act during an act change
# ---------------------------------------------------------------------------

class TestChangeDuringChange(ActTestCase):

    def test_entity_on_destroy_change_raises_and_target_is_built(self):
        self.begin(ComHeroiRedirecionador)
        with self.assertRaises(RuntimeError) as cm:
            change_act(Vazia)
        msg = str(cm.exception)
        self.assertIn("change_act(FimDeJogo) was called from Heroi.on_destroy", msg)
        self.assertIn("leaving ComHeroiRedirecionador", msg)
        self.assertIsInstance(current(), Vazia)
        self.assertFalse(get_act_manager().changing)

    def test_act_on_destroy_change_raises_and_target_is_built(self):
        class Teimosa(Act):
            def on_destroy(self):
                change_act(FimDeJogo)

        self.begin(Teimosa)
        with self.assertRaises(RuntimeError) as cm:
            change_act(Vazia)
        self.assertIn("Teimosa.on_destroy", str(cm.exception))
        self.assertIsInstance(current(), Vazia)


# ---------------------------------------------------------------------------
# Script-level work made after the seal
# ---------------------------------------------------------------------------

class TestScriptLevelWork(ActTestCase):

    def test_post_effects_and_background_fields_from_an_act_leave(self):
        game_bloom = Bloom()
        game_stars = Stars()
        made = {}

        class ComFx(Act):
            def setup(self):
                made["bloom"] = Bloom()
                made["stars"] = Stars()

        self.begin(ComFx)
        effects = list(canvas.effects)
        self.assertIn(made["bloom"], effects)
        change_act(Vazia)
        effects = list(canvas.effects)
        self.assertIn(game_bloom, effects)
        self.assertNotIn(made["bloom"], effects)
        items = self.w.fw.background_stack._items
        self.assertIn(game_stars, items)
        self.assertNotIn(made["stars"], items)

    def test_hit_feedback_singleton_is_never_removed(self):
        class Treme(Act):
            def setup(self):
                canvas.shake(0.5)

        self.begin(Treme)
        hit = canvas.effects._hit
        self.assertIsNotNone(hit)
        change_act(Vazia)
        self.assertIs(canvas.effects._hit, hit)
        self.assertTrue(any(e is hit for e in canvas.effects._effects))
        # ... and it is never one of the author's posts (AC3).
        self.assertNotIn(hit, list(canvas.effects))

    def test_ready_and_recently_slots_made_after_the_seal_are_forgotten(self):
        builtins.ready("jogo", 1.0)
        self.begin(Vazia)
        builtins.ready("tiro", 1.0)
        builtins.recently("no_chao", True, hold=0.1)
        change_act(Vazia)
        self.assertIn("jogo", builtins.ready._timers)
        self.assertNotIn("tiro", builtins.ready._timers)
        self.assertNotIn("no_chao", builtins.recently._slots)

    def test_leave_playfield_handler_added_in_an_act_leaves_with_it(self):
        # Top-level handlers accumulate (like @collide): the act's runs next
        # to the game's, and the act change drops only the act's
        # (review 2026-10-09 S4-10).
        @leave_playfield("tiro")
        def jogo(t):
            pass

        class Outra(Act):
            def setup(self):
                @leave_playfield("tiro", "extra")
                def ato(t):
                    pass

        self.begin(Outra)
        handlers = get_bounds_system()._group_handlers
        self.assertEqual(len(handlers["tiro"]), 2)
        self.assertIs(handlers["tiro"][0], jogo)
        change_act(Vazia)
        handlers = get_bounds_system()._group_handlers
        self.assertEqual(handlers["tiro"], (jogo,))
        self.assertNotIn("extra", handlers)


# ---------------------------------------------------------------------------
# Ownerless work, classless rules, the collision step, pulses
# ---------------------------------------------------------------------------

def _overlap(a, b, center=(100, 100)):
    return (Circle(center=center, radius=10, group=a),
            Circle(center=center, radius=10, group=b))


class TestScopesAndScriptRules(ActTestCase):

    def test_ownerless_scope_is_game_before_the_seal_and_act_after(self):
        before = after(10, lambda: None)
        self.assertEqual(before.scope, "game")
        with quiet():
            report_author_warning("teste", "antes")
        self.assertEqual(last_author_error()["owner"], "<game>")
        self.begin(Vazia)
        later = after(10, lambda: None)
        self.assertEqual(later.scope, "act")
        with quiet():
            report_author_warning("teste", "depois")
        self.assertEqual(last_author_error()["owner"], "<act>")
        self.assertEqual(before.scope, "game", "scope is fixed at creation")

    def test_ownerless_work_from_an_act_is_cancelled_game_work_is_not(self):
        fired = []
        after(0.2, lambda: fired.append("game"))
        made = {}

        class ComTrabalho(Act):
            def setup(self):
                made["timer"] = after(0.2, lambda: fired.append("act"))
                # Forever: a finite act sound rings out (TestActSoundsRingOut).
                made["sound"] = play_sound(tone(2.0), loops="forever")
                made["camera"] = canvas.zoom_to(3.0, time=1.0)

        self.begin(ComTrabalho)
        change_act(Vazia)
        for name, h in made.items():
            with self.subTest(handle=name):
                self.assertTrue(h.cancelled)
        self.w.seconds(1.2)
        self.assertEqual(fired, ["game"])
        self.assertEqual(canvas._engine._zoom, 1.0, "camera tween stopped and pose restored")

    def test_work_started_by_an_on_destroy_during_teardown_is_cancelled(self):
        fired = []

        class Deixa(Circle):
            def on_destroy(self):
                after(0.05, lambda: fired.append("orphan"))

        class ComDeixa(Act):
            def setup(self):
                Deixa()

        self.begin(ComDeixa)
        change_act(Vazia)
        self.w.seconds(0.2)
        self.assertEqual(fired, [])

    def test_classless_when_and_on_change_from_an_act_are_dropped(self):
        st.n = 0
        seen = []

        @when(lambda: st.n == 1)
        def game_rule():
            seen.append("game")

        class ComRegras(Act):
            def setup(self):
                @when(lambda: st.n == 1)
                def act_rule():
                    seen.append("act")

                @on_change(lambda: st.n)
                def act_change(v):
                    seen.append(("change", v))

        self.begin(ComRegras)
        change_act(Vazia)
        st.n = 1
        self.w.step(1)
        self.assertEqual(seen, ["game"])

    def test_act_method_when_dies_with_the_act(self):
        st.m = 0
        seen = []

        class ComMetodo(Act):
            @when(lambda self: st.m == 1)
            def pronto(self):
                seen.append("method")

        self.begin(ComMetodo)
        change_act(Vazia)
        st.m = 1
        self.w.step(1)
        self.assertEqual(seen, [])

    def test_collide_inside_setup_is_gone_top_level_collide_stays(self):
        hits = []

        @collide("g1", "g2")
        def game_pair(a, b):
            hits.append("game")

        class ComColisao(Act):
            def setup(self):
                @collide("s1", "s2")
                def act_pair(a, b):
                    hits.append("act")

        self.begin(ComColisao)
        change_act(Vazia)
        _overlap("g1", "g2", center=(50, 50))
        _overlap("s1", "s2", center=(200, 200))
        self.w.step(1)
        self.assertEqual(hits, ["game"])
        self.assertEqual(get_collision_system()._act_pair_handlers, [])

    def test_resolve_pairs_go_back_to_the_top_level_set(self):
        resolve("bola", "parede")

        class MexeResolve(Act):
            def setup(self):
                resolve("caixa", "chao")
                resolve("bola", "parede", bounce=0.9)
                unresolve("bola", "parede")

        self.begin(MexeResolve)
        change_act(Vazia)
        pairs = [(a, b, t) for a, b, t, _only in get_collision_system()._resolve_pairs]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][:2], ("bola", "parede"))

    def test_act_change_restores_resolve_only(self):
        resolve("heroi", "fina", only="bottom")

        class Retune(Act):
            def setup(self):
                resolve("heroi", "fina")  # the act drops the filter

        self.begin(Retune)
        self.assertFalse(get_collision_system()._has_only)
        change_act(Vazia)
        (pair,) = get_collision_system()._resolve_pairs
        self.assertEqual(pair[:2], ("heroi", "fina"))
        self.assertEqual(pair[3], frozenset({"bottom"}))
        self.assertTrue(get_collision_system()._has_only)

    def test_change_act_in_a_collide_handler_drops_the_old_acts_pairs(self):
        hits = []
        # Game bodies, tagged from the act so their colliders come after the
        # act's: their pair is dispatched *after* the change in the same step.
        g1 = Circle(center=(300, 50), radius=10)
        g2 = Circle(center=(300, 50), radius=10)

        @collide("atacante", "alvo")
        def bateu(a, b):
            if a is g1:
                hits.append("game")
                return
            hits.append("act")
            change_act(Vazia)

        class Arena(Act):
            def setup(self):
                _overlap("atacante", "alvo", center=(50, 50))
                _overlap("atacante", "alvo", center=(150, 50))
                g1.tag("atacante")
                g2.tag("alvo")

        self.begin(Arena)
        self.w.step(1)
        self.assertEqual(hits, ["act", "game"],
                         "no old-act pair after the change; the game pair keeps its enter")
        self.assertIsInstance(current(), Vazia)
        self.assertEqual(len(group["alvo"]), 1)
        self.w.step(2)
        self.assertEqual(hits, ["act", "game"])

    def test_no_exit_for_old_act_pairs_after_a_change_in_a_handler(self):
        exits = []
        st.virar = False

        @collide("x", "y")
        def entrou(a, b):
            if st.virar:
                st.virar = False
                change_act(Vazia)

        @collide_exit("x", "y")
        def saiu(a, b):
            exits.append((a.is_alive, b.is_alive))

        self.begin(Vazia)
        bx, by = _overlap("x", "y", center=(300, 50))   # pair B: touching
        self.w.step(1)
        bx.move_by(100, 0)                               # B separates this step
        _overlap("x", "y", center=(50, 50))              # pair A: enters, changes
        st.virar = True
        self.w.step(1)
        self.assertEqual(exits, [], "no exit to bodies the change removed")
        self.assertFalse(bx.is_alive)

    def test_no_collide_exit_between_two_bodies_leaving_together(self):
        exits = []

        @collide_exit("p", "q")
        def separou(a, b):
            exits.append("exit")

        class Juntos(Act):
            def setup(self):
                _overlap("p", "q")

        self.begin(Juntos)
        self.w.step(1)
        change_act(Vazia)
        self.w.step(1)
        self.assertEqual(exits, [])

    def test_pending_pulses_are_cleared_and_shake_still_works(self):
        class Treme(Act):
            def setup(self):
                canvas.shake(8)
                canvas.flash(0.8)
                canvas.explosion_at((100, 100))

        self.begin(Treme)
        hit = canvas.effects._hit
        self.assertGreater(hit._shake, 0)
        change_act(Vazia)
        self.assertEqual(hit._shake, 0.0)
        self.assertEqual(hit._flash, 0.0)
        self.assertEqual(hit._bursts, [])
        canvas.shake(5)
        self.assertIs(canvas.effects._hit, hit)
        self.assertGreater(hit._shake, 0)

    def test_change_act_from_a_when_handler_during_flush(self):
        st.pronto = 0

        class Espera(Act):
            @when(lambda self: st.pronto == 1)
            def vai(self):
                change_act(FimDeJogo)

        self.begin(Espera)
        st.pronto = 1
        self.w.step(1)
        self.assertIsInstance(current(), FimDeJogo)
        self.w.step(2)

    def test_change_act_from_the_acts_own_async_mode(self):
        log = []

        class Roteiro(Act):
            def setup(self):
                self.mode = self.corre

            @on_mode
            async def corre(self):
                await wait(0.05)
                change_act(Vazia)
                log.append("depois da troca")
                await wait(0.05)
                log.append("nunca")

        self.begin(Roteiro)
        self.w.seconds(0.3)
        self.assertIsInstance(current(), Vazia)
        self.assertEqual(log, ["depois da troca"])

    def test_a_key_press_does_not_carry_into_the_next_act(self):
        from scena import keyp
        seen = []

        class Pergunta(Act):
            def on_update(self, dt):
                if keyp.once("SPACE"):
                    seen.append("space")

        self.begin(Vazia)
        # Pressed and released in the old act, never read with once.
        keyp._press("SPACE")
        self.w.step(1)
        keyp._release("SPACE")
        self.w.step(1)
        change_act(Pergunta)
        self.w.step(3)
        self.assertEqual(seen, [], "an unread edge from the old act fired")
        # Held across the change: must be released and pressed again.
        change_act(Vazia)
        keyp._press("SPACE")
        self.w.step(1)
        change_act(Pergunta)
        self.w.step(2)
        self.assertEqual(seen, [])
        keyp._release("SPACE")
        self.w.step(1)
        keyp._press("SPACE")
        self.w.step(1)
        keyp._release("SPACE")
        self.assertEqual(seen, ["space"])

    def test_fade_cover_survives_and_its_on_done_changes_act(self):
        class Escura(Act):
            def setup(self):
                canvas.fade_out(0.1, on_done=lambda: change_act(Clara))

        class Clara(Act):
            def setup(self):
                LOG.append(("covered", canvas.covered))
                canvas.fade_in(0.1)

        self.begin(Escura)
        self.w.seconds(0.2)
        self.assertIsInstance(current(), Clara)
        self.assertIn(("covered", True), LOG)
        self.w.seconds(0.2)
        self.assertFalse(canvas.covered)

    def test_class_body_collide_message_names_the_act_forms(self):
        with self.assertRaises(TypeError) as cm:
            class ComColide(Act):
                @collide("a", "b")
                def bateu(self, a, b):
                    pass
        msg = str(cm.exception)
        self.assertIn("top of the file for the whole game", msg)
        self.assertIn("inside setup() for this act only", msg)


# ---------------------------------------------------------------------------
# Batch teardown: formula links between leaving objects
# ---------------------------------------------------------------------------

def _unlink_warnings(caught):
    return [str(w.message) for w in caught if "unlinked" in str(w.message)
            or "SCENA WARNING" in str(w.message)]


class TestActSoundsRingOut(ActTestCase):
    """An act change lets the leaving act's sounds that end by themselves
    finish; loops, named slots and paused sounds are cut. Decision 12;
    Sound Design — When the owner ends. Cell-by-cell fates are in
    tests/test_audio.py TestSoundRingsOut."""

    def test_finite_sounds_from_every_act_owner_ring_out(self):
        from scena.audio_mixer import get_mixer
        made = {}

        class Barulhenta(Act):
            def setup(self):
                made["bare"] = play_sound(tone(0.5))
                made["act"] = self.play_sound(tone(0.5))
                made["entity"] = Circle().play_sound(tone(0.5))
                made["loop"] = play_sound(tone(0.2), loops="forever")
                made["named"] = play_sound(tone(0.5), name="musica")
                made["paused"] = play_sound(tone(0.5)).pause()

        self.begin(Barulhenta)
        self.w.seconds(0.05)
        change_act(Vazia)
        for name in ("bare", "act", "entity"):
            with self.subTest(owner=name):
                h = made[name]
                self.assertFalse(h.cancelled)
                self.assertIsNone(h.owner)
                self.assertEqual(h.scope, "game")
        for name in ("loop", "named", "paused"):
            with self.subTest(cut=name):
                self.assertTrue(made[name].cancelled)
        self.w.seconds(0.1)
        live = get_mixer().live_voice_ids()
        for name in ("bare", "act", "entity"):
            self.assertIn(made[name]._voice_id, live, f"{name} still playing")
        self.w.seconds(0.6)
        for name in ("bare", "act", "entity"):
            with self.subTest(done=name):
                self.assertTrue(made[name].done)
                self.assertFalse(made[name].cancelled)

    def test_a_part_loop_of_an_act_object_stops_on_the_change(self):
        # Parts are not in the doomed batch (they leave with their owner);
        # their work must end with it too.
        made = {}

        class ComLinha(Act):
            def setup(self):
                linha = Line()
                made["loop"] = linha.p1.play_sound(tone(0.2), loops="forever")
                made["boom"] = linha.p1.play_sound(tone(0.3))

        self.begin(ComLinha)
        change_act(Vazia)
        self.assertTrue(made["loop"].cancelled)
        self.assertFalse(made["boom"].cancelled)
        self.assertEqual(made["boom"].scope, "game")

    def test_a_released_sound_survives_the_next_change_too(self):
        made = {}

        class Boom(Act):
            def setup(self):
                made["boom"] = play_sound(tone(0.5))

        self.begin(Boom)
        change_act(Vazia)
        change_act(Fase)
        self.assertFalse(made["boom"].cancelled)
        self.w.seconds(0.7)
        self.assertTrue(made["boom"].done)
        self.assertFalse(made["boom"].cancelled)

    def test_on_done_from_the_leaving_act_never_fires(self):
        fired = []

        class Fanfarra(Act):
            def setup(self):
                play_sound(tone(0.3), on_done=lambda: fired.append("done"))

        self.begin(Fanfarra)
        change_act(Vazia)
        self.w.seconds(0.6)
        self.assertEqual(fired, [])

    def test_act_music_can_fade_out_across_the_change(self):
        made = {}

        class ComMusica(Act):
            def setup(self):
                self.musica = self.play_sound(tone(0.2), loops="forever")
                made["musica"] = self.musica

            def on_destroy(self):
                self.musica.fade_out(0.4)

        self.begin(ComMusica)
        self.w.seconds(0.05)
        change_act(Vazia)
        h = made["musica"]
        self.assertFalse(h.cancelled, "a loop fading out ends by itself")
        self.w.seconds(0.2)
        self.assertFalse(h.done)
        self.w.seconds(0.4)
        self.assertTrue(h.done)


class TestNameSlotsAreByPlace(ActTestCase):
    """AC5 (game system tests; decided 2026-10-10: documented, not changed).
    A ``name=`` slot belongs to a place: the object a call is made on, or,
    for a loose call, the actor whose mode body is running — else the game /
    the current act. A loose ``play_sound(name="musica")`` in an act's
    ``setup`` and another loose one inside the act's mode are two slots, so
    both tracks play. ``self.play_sound`` in the act is the act's slot, the
    same one a loose call in the act's mode uses. Guia: vocabulário, slot."""

    def _run(self, in_setup, in_mode):
        made = {}

        class Trilha(Act):
            def setup(self):
                made["a"] = in_setup(self)
                self.mode = self.jogando

            def jogando(self):
                made["b"] = in_mode(self)

        self.begin(Trilha)
        self.w.seconds(0.05)
        return made

    def _end(self):
        change_act(Vazia)       # the module sweep cannot end an act
        self.w.seconds(0.01)

    def test_loose_in_setup_and_loose_in_the_mode_are_two_slots(self):
        m = self._run(lambda a: play_sound(tone(2.0), name="musica", loops="forever"),
                      lambda a: play_sound(tone(2.0), name="musica", loops="forever"))
        self.assertFalse(m["a"].cancelled, "a different place: not replaced")
        self.assertFalse(m["b"].cancelled)
        self._end()

    def test_the_acts_own_slot_is_one(self):
        m = self._run(lambda a: a.play_sound(tone(2.0), name="musica", loops="forever"),
                      lambda a: play_sound(tone(2.0), name="musica", loops="forever", crossfade=0.1))
        self.w.seconds(0.3)
        self.assertTrue(m["a"].cancelled or m["a"].done, "the act's slot replaces")
        self.assertFalse(m["b"].cancelled)
        self._end()

    def test_timers_follow_the_same_rule(self):
        m = self._run(lambda a: after(5.0, lambda: None, name="dica"),
                      lambda a: after(5.0, lambda: None, name="dica"))
        self.assertFalse(m["a"].cancelled)
        self._end()
        m2 = self._run(lambda a: a.after(5.0, lambda: None, name="dica"),
                       lambda a: after(5.0, lambda: None, name="dica"))
        self.assertTrue(m2["a"].cancelled)
        self._end()


class TestBatchTeardown(ActTestCase):

    def change_recording(self, cls):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            change_act(cls)
        return _unlink_warnings(caught)

    def test_hud_and_the_object_it_reads_leave_together_silently(self):
        class ComPlacar(Act):
            def setup(self):
                heroi = Circle(center=(50, 50))
                heroi.hp = 3
                placar = Text("", top_left=(10, 290))
                placar["text"] @= lambda: f"HP {heroi.hp}"
                # Made before the source too: order in the batch must not matter.
                outro = Text("", top_left=(10, 270))
                chefe = Circle(center=(80, 80))
                chefe.vida = 9
                outro["text"] @= lambda: f"Chefe {chefe.vida}"

        self.begin(ComPlacar)
        self.assertEqual(self.change_recording(Vazia), [])

    def test_hud_reading_the_acts_own_ink_leaves_silently(self):
        class ComInk(Act):
            def setup(self):
                self.pontos = 0
                placar = Text("", top_left=(10, 290))
                placar["text"] @= lambda: f"Pontos {self.pontos}"

        self.begin(ComInk)
        self.assertEqual(self.change_recording(Vazia), [])

    def test_an_acts_link_on_a_game_object_leaves_with_the_act(self):
        """Before 2026-10-14 (PA1) this was the warning case below: the link
        was dropped and its last value ("HP 7") stayed."""
        placar = Text("", top_left=(10, 290))

        class Fase2(Act):
            def setup(self):
                heroi = Circle(center=(50, 50))
                heroi.hp = 7
                placar["text"] @= lambda: f"HP {heroi.hp}"

        self.begin(Fase2)
        self.w.step(1)
        self.assertEqual(self.change_recording(Vazia), [])
        self.assertEqual(placar.text, "", "back to how the top of the file left it")
        placar.destroy()

    def test_game_object_linked_to_an_act_object_gets_a_scena_warning(self):
        """A link the act did not make (here: one the game's own code made
        while the act ran, outside ``@=``) still reads an act object."""
        placar = Text("", top_left=(10, 290))
        made = {}

        class Fase2(Act):
            def setup(self):
                heroi = Circle(center=(50, 50))
                heroi.hp = 7
                made["heroi"] = heroi
                placar._link_field("text", lambda: f"HP {heroi.hp}")

        self.begin(Fase2)
        self.w.step(1)
        with quiet():
            msgs = self.change_recording(Vazia)
        self.assertTrue(placar.is_alive)
        self.assertEqual(placar.text, "HP 7", "the last value stays")
        err = last_author_error()
        self.assertIsNotNone(err)
        msg = err["message"]
        self.assertIn("belonged to act Fase2", msg)
        self.assertIn("changed to Vazia", msg)
        self.assertIn("Create it in Fase2.setup()", msg)
        self.assertIn("text of the Text made at test_act.py", msg)
        self.assertFalse(any("was unlinked because a formula source" in m for m in msgs),
                         "the act message replaces the generic one")

    def test_outside_a_change_the_generic_unlink_warning_stands(self):
        class Meio(Act):
            def setup(self):
                heroi = Circle(center=(50, 50))
                heroi.hp = 1
                placar = Text("", top_left=(10, 290))
                placar["text"] @= lambda: f"HP {heroi.hp}"
                self.after(0.05, heroi.destroy)

        self.begin(Meio)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.w.seconds(0.1)
        self.assertTrue(any("was unlinked because a formula source was removed"
                            in m for m in _unlink_warnings(caught)))


# ---------------------------------------------------------------------------
# No leaks across changes
# ---------------------------------------------------------------------------

SOAK = os.environ.get("SCENA_SOAK") == "1"


class TestNoLeaks(ActTestCase):

    def busy_act(self):
        w = self.w
        test = self

        class Movimentada(Act):
            def setup(self):
                # One actor wired into every subsystem, plus act-level work.
                kitchen_sink(w, center=(100, 100))
                after(5, lambda: None)
                Bloom()
                Stars()
                builtins.ready("tiro", 0.1)

                @when(lambda: st.contador > 999)
                def nunca():
                    pass

                @collide("sink", "rock")
                def bateu(a, b):
                    pass

                # Registries an act can write beyond the hand-picked ones
                # (review 2026-10-09 R3): a formula group, an act-only pair
                # tag, ANYTHING interest, a leave rule, a layer, the HUD.
                group["mov_alvos"] @= lambda: group["sink"]

                @collide("mov_moeda", "mov_heroi")
                def pega(a, b):
                    pass
                Circle(center=(300, 300), radius=3, group="mov_moeda")
                resolve("mov_heroi", ANYTHING)

                @leave_playfield("mov_tiro")
                def sumiu(obj):
                    pass
                canvas.layers.create("mov_camada")
                Text("hud", layer="ui")

            def on_update(self, dt):
                st.contador += 1

        return Movimentada

    # Registries with no lazy warm-up: one act must give them back exactly.
    ACT_REGISTRIES = (
        "collision.pair_tags", "collision.anything_targets",
        "collision.pair_handlers", "collision.resolve_pairs", "collision.colliders",
        "registry.group_formulas", "registry.layers", "bounds.group_handlers",
        "widgets", "ready.timers", "recently.slots",
    )

    def test_one_act_gives_back_every_registry(self):
        st.contador = 0
        busy = self.busy_act()
        self.begin(Vazia)
        with quiet():
            before = census()
            hud = orch.ScenaFramework.get_instance().widget_manager.peek_hud_slot()
            self.cycle(busy, 1)
        after_ = census()
        d = {k: (before.get(k), after_.get(k)) for k in self.ACT_REGISTRIES
             if before.get(k) != after_.get(k)}
        self.assertEqual(d, {}, "an act left these registries changed: " + format_diff(d))
        self.assertEqual(orch.ScenaFramework.get_instance().widget_manager.peek_hud_slot(), hud)

    def cycle(self, busy, n):
        for _ in range(n):
            change_act(busy)
            self.w.step(3)
            change_act(Vazia)
            self.w.step(1)

    def test_changes_leave_no_zombies_and_a_stable_census(self):
        st.contador = 0
        busy = self.busy_act()
        self.begin(Vazia)
        # The every() flood detector ages its keys by wall time; drive that
        # clock so the bound below does not depend on machine speed (same as
        # test_process's S3 guard).
        import scena.process as proc
        now = [1000.0]

        def tick():
            now[0] += 0.3
            return now[0]

        with quiet(), mock.patch.object(proc.time, "monotonic", side_effect=tick):
            self.cycle(busy, 2)          # warm lazy singletons (hit feedback, tags)
            before = census()
            self.cycle(busy, 200 if SOAK else 6)
        after_ = census()
        # Same ignore as the other system suites: the every() flood detector is
        # keyed by owner id and swept past a bound, not a leak (bound checked).
        d = diff_census(before, after_, ("sched.every_sites",))
        self.assertEqual(d, {}, "registry sizes changed across act changes: "
                         + format_diff(d))
        self.assertLessEqual(after_["sched.every_sites"], proc._EVERY_SITES_SWEEP_AT + 25)
        self.assertNoZombies()


# ---------------------------------------------------------------------------
# World settings: restored or kept
# ---------------------------------------------------------------------------

def _world_state():
    """Every restored setting, as the author reads it."""
    e = canvas._engine
    pf = canvas.playfield
    return {
        "camera": (e._zoom, e._look_x, e._look_y, e._look_rest_x, e._look_rest_y,
                   e._rotation),
        "background": canvas.background.base,
        "background.fields": list(canvas.background.items()),
        "background.enabled": canvas.background.enabled,
        "effects": list(canvas.effects),
        "effects.enabled": canvas.effects.enabled,
        "playfield": (pf.left, pf.bottom, pf.right, pf.top, pf.pad),
        "clock": (clock.scale, clock.paused),
        "collision.resolve_enabled": collision.resolve_enabled,
        "layers.default": canvas.layers.default,
        "set_defaults": PaintState.get_defaults(),
        # Where the next omitted-y HUD item goes.
        "hud_stack": orch.ScenaFramework.get_instance().widget_manager.peek_hud_slot(),
    }


def _mess_up_the_world():
    """Change every restored setting from inside an act."""
    canvas.zoom_to(2.5)
    canvas.pan_to(123, 45)
    canvas.rotate_to(30)
    canvas.set_origin("center")
    canvas.background = "navy"
    canvas.set_fly(Stars())
    canvas.background.enabled = False
    Vignette()
    canvas.effects.enabled = False
    canvas.playfield.set(left=-5, bottom=-6, right=700, top=800)
    clock.scale = 0.25
    clock.paused = True
    collision.resolve_enabled = not collision.resolve_enabled
    canvas.layers.create("ato_extra", z=40)
    canvas.layers.default = "ato_extra"
    set_defaults("coral", line_width=4.0)
    ui.stack_origin(300, 222)


class Bagunca(Act):
    def setup(self):
        _mess_up_the_world()


class TestWorldSettings(ActTestCase):

    def test_every_restored_setting_goes_back_to_framework_defaults(self):
        # The top never set them: they go back to the framework default.
        self.begin(Bagunca)
        before = self._state_at_seal
        change_act(Vazia)
        after = _world_state()
        for name in before:
            with self.subTest(setting=name):
                self.assertEqual(after[name], before[name])

    def test_every_restored_setting_goes_back_to_top_level_values(self):
        canvas.zoom_to(1.5)
        canvas.background = "maroon"
        Bloom()
        canvas.playfield.pad = 0.3
        clock.scale = 0.5
        self.begin(Bagunca)
        before = self._state_at_seal
        self.assertEqual(before["clock"], (0.5, False))
        change_act(Vazia)
        after = _world_state()
        for name in before:
            with self.subTest(setting=name):
                self.assertEqual(after[name], before[name])

    def test_the_test_changes_every_restored_setting(self):
        # Guard the guard: each WORLD_SETTINGS entry is really moved above.
        self.begin(Vazia)
        before = _world_state()
        _mess_up_the_world()
        after = _world_state()
        self.assertEqual(set(before), {w.name for w in WORLD_SETTINGS})
        for name in before:
            with self.subTest(setting=name):
                self.assertNotEqual(after[name], before[name])

    def test_an_act_cannot_remove_a_game_effect_for_good(self):
        glow = Bloom()
        self.begin(Vazia)
        glow.remove()
        canvas.effects.clear()
        change_act(Vazia)
        self.assertIn(glow, list(canvas.effects))

    def test_kept_settings_stay_as_the_act_left_them(self):
        self.begin(Vazia)
        old_volume = audio.volume
        old_scale = canvas.post_fx_scale
        try:
            audio.volume = 0.3
            canvas.post_fx_scale = 0.5
            change_act(Vazia)
            self.assertAlmostEqual(audio.volume, 0.3)
            self.assertEqual(canvas.post_fx_scale, 0.5)
        finally:
            audio.volume = old_volume
            canvas.post_fx_scale = old_scale

    def setUp(self):
        super().setUp()
        self._orig_defaults = PaintState.get_defaults()
        self._orig_resolve = collision.resolve_enabled
        self._state_at_seal = None
        begin = self.w.begin_game

        def begin_and_record(first=None, setup=None):
            self._state_at_seal = _world_state()
            begin(first, setup=setup)
        self.w.begin_game = begin_and_record

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            PaintState._default_instance = self._orig_defaults
            collision.resolve_enabled = self._orig_resolve
            canvas.background.reset_base()
            canvas.background.clear()
            canvas.background.enabled = True
            canvas.effects.enabled = True
            canvas.playfield.pad = _DEFAULT_PAD
            if "ato_extra" in canvas.layers.list():
                canvas.layers.default = "default"


_DEFAULT_PAD = canvas.playfield.pad


# Not settings: one-shots, queries, factories and engine hooks. A new public
# name on these objects must be classified here, in WORLD_SETTINGS or in
# KEPT_SETTINGS (``test_every_settable_name_is_classified``).
NOT_SETTINGS = {
    # one-shot effects (pending pulses are cleared on a change)
    "canvas.bubbles", "canvas.bubbles_at", "canvas.burst_at", "canvas.debris_at",
    "canvas.explosion_at", "canvas.hit_at",
    "canvas.fireworks_at", "canvas.flash", "canvas.glitch", "canvas.ripple_at",
    "canvas.shake", "canvas.wave_at", "canvas.zap_at",
    # the fade cover is a framework singleton that survives a change
    "canvas.fade_in", "canvas.fade_out",
    # bench / stats
    "canvas.shape_fx_surface_stats", "canvas.reset_shape_fx_surface_stats",
    # engine drivers and Container plumbing
    "clock.advance", "clock.update", "clock.unlink", "clock.unlink_all",
    "clock.owner", "clock.parts", "clock.field_type",
    # canvas is a formula source (a Container like clock): the same plumbing
    "canvas.update", "canvas.unlink", "canvas.unlink_all",
    "canvas.owner", "canvas.parts", "canvas.field_type",
    # queries (read-only) and Box factories (return new boxes)
    "collision.query_circle", "collision.query_point", "collision.query_sector",
    "collision.query_shape", "collision.raycast", "audio.spectrum",
    "background.items", "layers.list",
    "playfield.beside", "playfield.grid", "playfield.inset", "playfield.outset",
    "playfield.strip",
    # layers: a layer an act creates leaves with it (``_drop_act_layers``); a
    # game layer's own state is its own, like a game object's
    "layers.create", "layers.clear", "layers.using",
}

# Exported instances the walk does not enter, each with its reason. Every
# other instance in ``scena.__all__`` is walked: the guard must not depend on
# a hand list of objects (review 2026-10-09 S4-6: ``ui`` was never walked).
NOT_WALKED = {
    "st": "game data: kept across acts by design",
    "group": "group lookup; formulas are recorded at the seal (S4-3)",
    "mouse": "input reader (frame state, not a setting)",
    "keyp": "input reader (frame state, not a setting)",
    "ready": "keys made after the seal are dropped by the change",
    "recently": "keys made after the seal are dropped by the change",
    "ANYTHING": "collision sentinel",
}

# Sub-objects reached through an exported instance.
_SUB_OBJECTS = {
    "playfield": lambda: canvas.playfield, "layers": lambda: canvas.layers,
    "effects": lambda: canvas.effects, "background": lambda: canvas.background,
}


def _exported_instances():
    out = {}
    for name in scena.__all__:
        v = getattr(scena, name)
        if (inspect.isclass(v) or inspect.isroutine(v) or inspect.ismodule(v)
                or isinstance(v, (str, int, float, tuple, frozenset, type(None)))):
            continue
        out[name] = v
    return out


def _settable_surface():
    objs = {k: v for k, v in _exported_instances().items() if k not in NOT_WALKED}
    objs.update({k: fn() for k, fn in _SUB_OBJECTS.items()})
    names = set()
    for label, o in objs.items():
        for c in type(o).__mro__:
            for k, v in vars(c).items():
                if k.startswith("_"):
                    continue
                if isinstance(v, property) and v.fset is not None:
                    names.add(f"{label}.{k}")
                elif inspect.isfunction(v):
                    names.add(f"{label}.{k}")
            if c.__module__.startswith("scena.state"):
                break  # Container plumbing below Clock is not the clock's surface
        for k in getattr(o, "__dict__", {}):
            if not k.startswith("_") and k not in ("parts", "field_type"):
                names.add(f"{label}.{k}")
    for name in scena.__all__:
        if name.startswith(("set_", "show_")) and callable(getattr(scena, name)):
            names.add(name)
    return names


class TestSettingsClassification(unittest.TestCase):
    """Bug class: a new setter leaks across acts because nobody classified it."""

    def test_every_settable_name_is_classified(self):
        restored = {c for w in WORLD_SETTINGS for c in w.covers}
        known = restored | set(KEPT_SETTINGS) | NOT_SETTINGS
        missing = sorted(_settable_surface() - known)
        self.assertEqual(
            missing, [],
            "Classify each new setting in scena/act.py: WORLD_SETTINGS (an act "
            "change restores it) or KEPT_SETTINGS (a preference); or add it to "
            "NOT_SETTINGS here if it is not a setting.")

    def test_no_name_is_classified_twice(self):
        restored = [c for w in WORLD_SETTINGS for c in w.covers]
        self.assertEqual(len(restored), len(set(restored)))
        self.assertEqual(set(restored) & set(KEPT_SETTINGS), set())
        self.assertEqual(set(restored) & NOT_SETTINGS, set())
        self.assertEqual(set(KEPT_SETTINGS) & NOT_SETTINGS, set())

    def test_every_exported_instance_is_walked_or_excused(self):
        exported = set(_exported_instances())
        walked = exported - set(NOT_WALKED)
        self.assertIn("ui", walked)
        self.assertEqual(sorted(set(NOT_WALKED) - exported), [],
                         "NOT_WALKED names that are no longer exported")

    def test_classified_names_exist(self):
        surface = _settable_surface()
        restored = {c for w in WORLD_SETTINGS for c in w.covers}
        stale = sorted((restored | set(KEPT_SETTINGS) | NOT_SETTINGS) - surface)
        self.assertEqual(stale, [], "classified names that no longer exist")


# ---------------------------------------------------------------------------
# Restrictions and messages
# ---------------------------------------------------------------------------

class TestRestrictions(ActTestCase):

    def test_building_an_act_by_hand(self):
        with self.assertRaises(TypeError) as cm:
            Fase()
        self.assertIn("Write change_act(Fase) — or run(Fase)", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            Act()
        self.assertIn("Act is the base class", str(cm.exception))

    def test_change_act_argument_checks(self):
        self.begin(Vazia)
        cases = [
            (lambda: change_act(current()), "Write change_act(Vazia), without ()."),
            (lambda: change_act("Fase"), "not a string. Write change_act(Fase)."),
            (lambda: change_act(Circle), "Circle is not an Act."),
            (lambda: change_act(Act), "Act is the base class."),
            (lambda: change_act(Fase, vidas=2), "Put game data in st"),
            (lambda: change_act(None), "change_act takes an Act class"),
        ]
        for call, text in cases:
            with self.subTest(text=text):
                before = current()
                with self.assertRaises(TypeError) as cm:
                    call()
                self.assertIn(text, str(cm.exception))
                self.assertIs(current(), before, "a bad call changes nothing")

    def test_change_act_before_the_game_starts(self):
        with self.assertRaises(RuntimeError) as cm:
            change_act(Fase)
        self.assertIn("The game has not started", str(cm.exception))

    def test_change_act_after_plain_run(self):
        self.begin(None)
        with self.assertRaises(RuntimeError) as cm:
            change_act(Fase)
        self.assertIn("This game started with run(). To use acts, start with run(Fase).",
                      str(cm.exception))

    def test_run_validates_the_first_act_before_opening_the_window(self):
        fw = self.w.fw
        with mock.patch.object(fw, "open_window") as opened, \
                mock.patch.object(fw, "run") as ran:
            for bad, text in ((Circle, "Circle is not an Act"),
                              ("Fase", "run takes an Act class, not a string"),
                              (Act, "Act is the base class")):
                with self.subTest(bad=bad):
                    with self.assertRaises(TypeError) as cm:
                        orch.run(bad)
                    self.assertIn(text, str(cm.exception))
            opened.assert_not_called()
            ran.assert_not_called()

    def test_setup_with_parameters_raises_at_class_definition(self):
        with self.assertRaises(TypeError) as cm:
            class ComVidas(Act):
                def setup(self, vidas=3):
                    pass
        self.assertIn("Act setup() takes no parameters", str(cm.exception))

    def test_init_is_rejected(self):
        with self.assertRaises(TypeError) as cm:
            class ComInit(Act):
                def __init__(self):
                    pass
        self.assertIn("setup(self), not __init__", str(cm.exception))

    def test_body_only_hooks_raise_at_class_definition(self):
        from scena import collide_with

        def hook_class(name):
            return type(f"S_{name}", (Act,), {name: lambda self, *a: None})

        for name in ("on_click", "on_collide", "on_collide_stay", "on_collide_exit"):
            with self.subTest(hook=name):
                with self.assertRaises(TypeError) as cm:
                    hook_class(name)
                self.assertIn("An act has no body", str(cm.exception))

        with self.assertRaises(TypeError) as cm:
            class ComColisao(Act):
                @collide_with("inimigo")
                def bateu(self, other):
                    pass
        self.assertIn("An act has no body", str(cm.exception))

        with self.assertRaises(TypeError) as cm:
            class ComSaida(Act):
                @leave_playfield
                def saiu(self):
                    pass
        self.assertIn("An act has no body", str(cm.exception))

    def test_class_keywords_raise(self):
        for kw in ("group", "layer"):
            with self.subTest(kw=kw):
                with self.assertRaises(TypeError) as cm:
                    type("S", (Act,), {}, **{kw: "x"})
                self.assertIn("Acts do not draw", str(cm.exception))

    def test_storing_a_group_on_any_entity_names_the_lookup(self):
        from scena.state import CallableAssignError
        for holder in (Entity(), Circle()):
            with self.subTest(holder=type(holder).__name__):
                with self.assertRaises(CallableAssignError) as cm:
                    holder.inimigos = group["inimigo"]
                self.assertIn("A group is looked up, not stored. Write "
                              "group['inimigo'] where you need it", str(cm.exception))
        self.begin(Vazia)
        with self.assertRaises(CallableAssignError) as cm:
            current().naves = group["nave"]
        self.assertIn("group['nave']", str(cm.exception))
        with self.assertRaises(CallableAssignError) as cm:
            Entity().f = lambda: 1
        self.assertIn("cannot be linked by assigning a callable", str(cm.exception))

    def test_public_surface(self):
        self.assertIs(scena.Act, Act)
        self.assertIs(scena.change_act, change_act)
        self.assertIn("Act", scena.__all__)
        self.assertIn("change_act", scena.__all__)
        self.assertIn("first_act", inspect.signature(scena.run).parameters)

    def test_entity_verbs_raise_on_an_act(self):
        self.begin(Vazia)
        s = current()
        cases = [
            (lambda: s.destroy(), "Write change_act(Titulo)"),
            (lambda: setattr(s, "active", False), "clock.paused = True"),
            (lambda: s.cancel_process(), "write change_act(Vazia)"),
            (lambda: s.tag("x"), "Acts do not draw"),
            (lambda: s.untag("x"), "Acts do not draw"),
            (lambda: setattr(s, "visible", False), "Acts do not draw"),
            (lambda: s.visible, "Acts do not draw"),
            (lambda: setattr(s, "layer", "default"), "Acts do not draw"),
            (lambda: setattr(s, "group", "x"), "Acts do not draw"),
        ]
        for call, text in cases:
            with self.subTest(text=text):
                with self.assertRaises(TypeError) as cm:
                    call()
                self.assertIsInstance(cm.exception, ActUsageError)
                self.assertIn(text, str(cm.exception))
        self.assertTrue(s.is_alive)
        self.assertTrue(s.active)
        self.assertIsNone(getattr(s, "visible", None), "engine probes keep their default")


# ---------------------------------------------------------------------------
# Retired names (0.6.0): Scene → Act, change_scene → change_act
# ---------------------------------------------------------------------------

class TestRetiredSceneNames(unittest.TestCase):
    """``scena.Scene`` / ``from scena import Scene`` (and ``change_scene``)
    raise with the new spelling. A star import does not bring the old names
    (not in ``__all__``, not in builtins: nothing is shadowed), so there they
    are Python's own ``NameError``."""

    def _star_namespace(self):
        ns = {}
        exec("from scena import *", ns)
        return ns

    def test_subclassing_the_imported_scene_raises_with_the_fix(self):
        ns = {}
        exec("from scena import Scene", ns)
        with self.assertRaises(TypeError) as ctx:
            exec("class Titulo(Scene):\n    pass", ns)
        msg = str(ctx.exception)
        self.assertIn("Scene was renamed to Act in 0.6.0", msg)
        self.assertIn("class Titulo(Act)", msg)
        self.assertIn("change_act(Titulo)", msg)

    def test_imported_change_scene_raises_with_the_fix(self):
        ns = {"Fase": Fase}
        exec("from scena import change_scene", ns)
        with self.assertRaises(TypeError) as ctx:
            exec("change_scene(Fase)", ns)
        msg = str(ctx.exception)
        self.assertIn("change_scene was renamed to change_act in 0.6.0", msg)
        self.assertIn("change_act(Fase)", msg)

    def test_a_star_import_does_not_bring_the_old_names(self):
        ns = self._star_namespace()
        for old in ("Scene", "change_scene"):
            self.assertNotIn(old, ns)
            self.assertFalse(hasattr(builtins, old), f"{old} must not be installed in builtins")
            with self.assertRaises(NameError):
                exec(old, ns)

    def test_scene_call_and_attribute_spellings_raise(self):
        from scena import Scene as OldScene
        self.assertIs(scena.Scene, OldScene)
        with self.assertRaises(TypeError) as ctx:
            OldScene()
        self.assertIn("Act", str(ctx.exception))
        with self.assertRaises(TypeError):
            scena.change_scene()

    def test_retired_names_are_not_api(self):
        self.assertNotIn("Scene", scena.__all__)
        self.assertNotIn("change_scene", scena.__all__)
        self.assertIn("Act", scena.__all__)
        self.assertIn("change_act", scena.__all__)
        with self.assertRaises(AttributeError):
            scena.NoSuchName  # noqa: B018 — module __getattr__ keeps the default

    def test_an_author_class_named_scene_is_untouched(self):
        ns = self._star_namespace()
        exec("class Scene:\n    pass\nclass Minha(Scene):\n    pass", ns)
        self.assertIn("Minha", ns)



class TestDestroyedSidesLeaveTheActPairLists(ActTestCase):
    """HD2 / HD3 / HD5 (Testing Design, HD): pair lists an act change reads back
    and the widget manager's menu fields must not keep a destroyed object."""

    def test_sealed_resolve_pair_forgets_a_destroyed_game_side(self):
        player = Circle(center=(10, 10), radius=5, group="hd_player")
        wall = Circle(center=(300, 10), radius=5, group="hd_wall")
        wall.mass = STATIC
        resolve(player, wall)
        self.begin(Vazia)
        col = get_collision_system()
        self.assertTrue(any(a is player or b is player
                            for a, b, _t, _o in col._sealed_resolve_pairs))
        player.destroy()
        self.assertFalse(any(a is player or b is player
                             for a, b, _t, _o in col._sealed_resolve_pairs),
                         "the seal kept a destroyed resolve side")
        change_act(Vazia)      # restores the game's pairs: nothing to revive
        self.assertFalse(any(a is player or b is player for a, b, _t, _o in col._resolve_pairs))
        wall.destroy()

    def test_act_pair_handler_forgets_a_destroyed_side_before_the_change(self):
        box = {}

        class ComPar(Act):
            def setup(self):
                box["a"] = a = Circle(center=(10, 10), radius=5)
                box["rock"] = rock = Circle(center=(300, 10), radius=5)

                @collide(a, rock)
                def _hit(x, y, info=None):
                    pass

        self.begin(ComPar)
        col = get_collision_system()
        a = box["a"]
        self.assertTrue(any(x is a or y is a for x, y, _cb, _ph in col._act_pair_handlers))
        a.destroy()
        self.assertFalse(any(x is a or y is a for x, y, _cb, _ph in col._act_pair_handlers),
                         "the act-level pair list kept a destroyed side")
        self.assertFalse(any(x is a or y is a for x, y, _cb, _ph in col._pair_handlers))

    def test_a_modal_menu_open_at_the_change_closes_with_its_act(self):
        from scena import Menu, TextInput
        box = {}

        class ComMenu(Act):
            def setup(self):
                box["menu"] = Menu(options=["um", "dois"], on_choose=lambda v: None, pause=True)

        class Depois(Act):
            def setup(self):
                st.hd_nome = ""
                box["ti"] = TextInput(st["hd_nome"], top_left=(10, 290), width=100)

        self.begin(ComMenu)
        wm = self.w.fw.widget_manager
        self.assertIs(wm._open_modal_menu, box["menu"])
        self.assertTrue(clock.paused)
        change_act(Depois)
        self.assertIsNone(wm._open_modal_menu, "a destroyed menu stayed open")
        self.assertIsNone(wm.modal_widget)
        self.assertFalse(clock.paused, "the menu's pause outlived the menu")
        handle = box["menu"]._choice_handle
        self.assertTrue(handle._done or handle._cancelled, "await menu would hang")
        box["ti"].focus()      # used to raise: "A modal Menu is open"
        self.assertIs(wm.focused_widget, box["ti"])


class TestTeardownPhases(ActTestCase):
    """Act teardown in two phases (review 2026-10-09 X-life-6 / X-life-9):
    every on_destroy of the batch runs while the whole batch is alive, then
    teardown; objects born during the teardown leave without their hook."""

    def test_on_destroy_sees_every_sibling_alive_in_any_creation_order(self):
        seen = []

        class Chefe(Circle):
            def on_destroy(self):
                seen.append(self.escolta.hp)      # ink: raises if the escort died

        class EscoltaPrimeiro(Act):
            def setup(self):
                escolta = Circle(center=(50, 0), radius=5)
                escolta.hp = 3
                self.chefe = Chefe(center=(0, 0), radius=20)
                self.chefe.escolta = escolta

        class ChefePrimeiro(Act):
            def setup(self):
                self.chefe = Chefe(center=(0, 0), radius=20)
                escolta = Circle(center=(50, 0), radius=5)
                escolta.hp = 4
                self.chefe.escolta = escolta

        self.begin(EscoltaPrimeiro)
        change_act(ChefePrimeiro)
        change_act(Vazia)
        self.assertEqual(seen, [3, 4])

    def test_a_self_replacing_on_destroy_settles(self):
        made = []

        class Asteroide(Circle):
            def on_destroy(self):
                made.append(Asteroide(center=(self.center.x + 50, 0), radius=10))

        class Campo(Act):
            def setup(self):
                for i in range(3):
                    Asteroide(center=(i * 60, 0), radius=10)

        self.begin(Campo)
        rock = Asteroide(center=(500, 0), radius=10)
        rock.destroy()                       # in play: replaced, as wanted
        self.assertTrue(made[-1].is_alive)
        n_before = len(made)
        change_act(Vazia)                    # settles: spawns made by the
        self.assertIsInstance(current(), Vazia)  # teardown run no hook
        self.assertEqual(len(made) - n_before, 4)   # one per batch member
        self.assertFalse(any(m.is_alive for m in made))
        from scena.act import _MAX_TEARDOWN_PASSES
        self.assertLessEqual(_MAX_TEARDOWN_PASSES, 100)  # a runaway fails fast

    def test_a_runaway_teardown_still_restores_and_drops_the_act(self):
        # Review 2026-10-09 S4-9: the cap raised before the world settings
        # were restored and before the act's rules and timers were dropped.
        import scena.act as act_mod
        ticks = []

        class Corrida(Act):
            def setup(self):
                Circle(center=(0, 0), radius=5)
                clock.scale = 0.25
                after(0.05, lambda: ticks.append(1))

                @leave_playfield("corrida_bala")
                def sumiu(obj):
                    pass

        self.begin(Corrida)
        with mock.patch.object(act_mod, "_MAX_TEARDOWN_PASSES", 0):
            with self.assertRaises(RuntimeError) as cm:
                change_act(Vazia)
        self.assertIn("did not settle", str(cm.exception))
        self.assertEqual(clock.scale, 1.0, "world settings restored")
        self.assertNotIn("corrida_bala", get_bounds_system()._group_handlers)
        self.w.seconds(0.2)
        self.assertEqual(ticks, [], "the act's timer was dropped")


class TestActOwnsItsRegistries(ActTestCase):
    """Review 2026-10-09 R3: an act change gives back every registry an act
    can write, not only the hand-picked ones (formula groups, pair tags,
    ``ANYTHING`` interest, the HUD cursor, a camera tween)."""

    def _registry(self):
        from scena.canvas import ScenaCanvas
        return ScenaCanvas.get_current().registry

    def test_an_act_formula_group_leaves_and_a_game_formula_comes_back(self):
        Circle(center=(0, 0), radius=4, group="rg_vespa")
        group["rg_alvos"] @= lambda: group["rg_vespa"]
        game_fn = self._registry()._group_formulas["rg_alvos"]
        refs = []

        class Fase2(Act):
            def setup(self):
                refs.append(weakref.ref(self))
                self.chefe = Circle(center=(9, 0), radius=4, group="rg_chefe")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    group["rg_alvos"] @= lambda: (
                        group["rg_vespa"] | group["rg_chefe"]) if self.chefe else group["rg_vespa"]
                group["rg_so_do_ato"] @= lambda: group["rg_chefe"]

        self.begin(Fase2)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            change_act(Fase2)                       # restart
        self.assertFalse([c for c in caught if "overrides its previous link" in str(c.message)
                          and "rg_so_do_ato" in str(c.message)],
                         "a restart starts from the game's formulas")
        change_act(Vazia)
        formulas = self._registry()._group_formulas
        self.assertNotIn("rg_so_do_ato", formulas)
        self.assertIs(formulas["rg_alvos"], game_fn, "the game's formula is back")
        Circle(center=(0, 0), radius=4, group="rg_so_do_ato")   # the name is free
        self.w.step(1)
        gc.collect()
        self.assertEqual([r for r in refs if r() is not None], [],
                         "a formula reading self pinned the old act")

    def test_an_act_only_collide_tag_retires_with_the_act(self):
        class Loja(Act):
            def setup(self):
                @collide("rg_moeda", "rg_heroi")
                def pega(c, h, info):
                    pass

        class Menu(Act):
            def setup(self):
                self.moedas = [Circle(center=(i * 30, 0), radius=10, group="rg_moeda")
                               for i in range(3)]

        cs = get_collision_system()
        enfeite = Circle(center=(400, 0), radius=10)     # a game member, tagged in the act
        manual = Circle(center=(450, 0), radius=10)
        manual.collidable = True                          # the author's own switch
        self.begin(Loja)
        enfeite.tag("rg_moeda")
        manual.tag("rg_moeda")
        self.w.step(1)
        self.assertIsNotNone(enfeite._collider, "enrolled by the act's tag")
        change_act(Menu)
        self.w.step(1)
        self.assertNotIn("rg_moeda", cs._pair_tags)
        self.assertEqual([m for m in current().moedas if m._collider is not None], [],
                         "a later member is not enrolled by a dead act's rule")
        self.assertIsNone(enfeite._collider, "enrolled only by the act's tag: leaves")
        self.assertFalse(enfeite.collidable)
        self.assertIsNotNone(manual._collider, "collidable = True stays")
        self.assertEqual(collision.query_point(0, 0), [])

    def _anything_rule_goes(self, kind):
        from scena import ANYTHING
        heroi = Circle(center=(0, 0), radius=10)          # the game's
        pedra = Circle(center=(300, 0), radius=10)
        pedra.collidable = True

        class Nivel(Act):
            def setup(self):
                if kind == "collide":
                    @collide(heroi, ANYTHING)
                    def bate(me, other, info):
                        pass
                else:
                    resolve(heroi, ANYTHING)

        self.begin(Nivel)
        self.w.step(1)
        self.assertTrue(any(t is ANYTHING for t in heroi._collider._pair_targets))
        change_act(Vazia)
        self.w.step(1)
        col = heroi._collider
        self.assertFalse(col is not None and any(t is ANYTHING for t in col._pair_targets),
                         "the dead act's ANYTHING kept pairing the hero with every body")

    def test_an_act_collide_anything_on_a_game_body_goes(self):
        self._anything_rule_goes("collide")

    def test_an_act_resolve_anything_on_a_game_body_goes(self):
        self._anything_rule_goes("resolve")

    def test_a_game_camera_tween_stops_at_the_change(self):
        def segue(me):
            canvas.pan_to(1000, 0, time=2)

        diretor = Entity()
        self.begin(Vazia)
        diretor.mode = segue
        self.w.seconds(0.5)
        change_act(Vazia)
        x = canvas.pan_x
        self.w.seconds(0.5)
        self.assertAlmostEqual(canvas.pan_x, x, msg="the restored camera pose holds")
        diretor.destroy()

    def test_the_act_hud_starts_at_the_same_slot_on_every_entry(self):
        Text("RECORDE", layer="ui")                     # a game HUD item
        seen = []

        class Fase3(Act):
            def setup(self):
                t = Text("pontos", layer="ui")
                seen.append(round(t.center.y, 3))

        self.begin(Fase3)
        for _ in range(3):
            change_act(Fase3)
        self.assertEqual(len(set(seen)), 1, f"the HUD moved down per restart: {seen}")


class TestActLayers(ActTestCase):
    """A layer created in an act leaves with it (review 2026-10-09 S4-4):
    a restart is a fresh act, and the Endless recipe (create the layer in
    the act) can restart."""

    def test_restart_recreates_the_layer(self):
        class Pista(Act):
            def setup(self):
                canvas.layers.create("act_pista", scroll=(0.0, -40.0))
                Circle(layer="act_pista")

        self.begin(Pista)
        change_act(Pista)                     # raised "already exists" before
        self.assertIsInstance(current(), Pista)
        self.assertIn("act_pista", list(canvas.layers))
        change_act(Vazia)
        self.assertNotIn("act_pista", list(canvas.layers))

    def test_game_layers_stay(self):
        canvas.layers.create("act_jogo")
        try:
            self.begin(Vazia)
            change_act(Vazia)
            self.assertIn("act_jogo", list(canvas.layers))
        finally:
            canvas.layers["act_jogo"].delete()

    def test_a_game_object_on_an_act_layer_raises_with_the_fix(self):
        game = Circle()

        class Movedor(Act):
            def setup(self):
                canvas.layers.create("act_meio")
                game.layer = "act_meio"

        self.begin(Movedor)
        with self.assertRaisesRegex(ActUsageError, "act_meio.*game layer"):
            change_act(Vazia)
        self.assertIsInstance(current(), Vazia)   # the change finished
        game.layer = "default"
        game.destroy()
        canvas.layers["act_meio"].delete()


class TestActCallablesOnGameObjects(ActTestCase):
    """An act's method (or a function closing over the act) handed to a game
    object leaves with the act (review 2026-10-09 X-life-7)."""

    def test_act_method_scheduled_on_a_game_object_does_not_stack(self):
        import gc
        import weakref
        heroi = Circle(group="heroi_jogo")
        pulses = []
        acts = []

        class Fase3(Act):
            def setup(self):
                acts.append(weakref.ref(self))
                self.alvo = 1
                heroi.every(0.25, self.pulsar)
                heroi.on_update = lambda e, dt: self.alvo
                heroi.mode = self.caca

            def pulsar(self):
                pulses.append(self.alvo)

            def caca(self):
                pass

        self.begin(Fase3)
        self.w.step(20, dt=1 / 60)
        change_act(Fase3)                     # restart
        sched = get_scheduler()
        mine = [h for h in sched._handles if not h._cancelled and h.owner is heroi]
        self.assertEqual(len(mine), 1, "the act's every() stacked on restart")
        del mine                              # a test-owned handle keeps its act
        change_act(Vazia)
        self.assertIsNone(heroi.on_update)
        self.assertIsNone(heroi.mode)
        self.w.step(30, dt=1 / 60)            # nothing reaches the dead acts
        gc.collect()
        self.assertTrue(all(r() is None for r in acts), "a dead act stayed alive")
        self.assertTrue(heroi.is_alive)
        heroi.destroy()

    def test_game_callables_stay(self):
        heroi = Circle(group="heroi_jogo")
        ticks = []
        heroi.every(0.25, lambda: ticks.append(1))   # no act in the closure
        self.begin(Vazia)
        change_act(Vazia)
        self.w.step(20, dt=1 / 60)
        self.assertTrue(ticks)
        heroi.destroy()


class TestActLinksOnGameObjects(ActTestCase):
    """An act's ``obj["field"] @= …`` on a game object leaves with the act:
    the field gets back the game's link or value (review 2026-10-14 PA1).
    Before, a restart warned "overrides its previous link" every time, and
    the next act's ``hud.text = …`` raised LinkedAttributeError."""

    def _caught(self, fn):
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            fn()
        return [str(w.message) for w in ws]

    def test_restart_links_again_silently(self):
        st.pontos = 7
        hud = Text("", top_left=(10, 290))

        class FaseHud(Act):
            def setup(self):
                hud["text"] @= lambda: f"Pontos {st.pontos}"

        self.begin(FaseHud)
        self.assertEqual(hud.text, "Pontos 7")
        msgs = self._caught(lambda: [change_act(FaseHud) for _ in range(3)])
        self.assertEqual(msgs, [])
        st.pontos = 8
        self.assertEqual(hud.text, "Pontos 8")
        change_act(Vazia)
        self.assertEqual(hud.text, "", "the top of the file left it empty")
        self.assertFalse(hud["text"].is_linked)
        hud.text = "NAVES"                    # used to raise LinkedAttributeError
        hud.destroy()

    def test_a_link_reading_act_objects_leaves_without_a_warning(self):
        barra = Rect(top_left=(10, 270), width=1, height=5)
        hud = Text("", top_left=(10, 290))

        class FaseVida(Act):
            def setup(self):
                self.pontos = 3
                h = Circle(center=(100, 100), radius=5)
                h.vida = 10
                barra["width"] @= lambda: h.vida * 2
                hud["text"] @= lambda: f"Pontos {self.pontos}"

        self.begin(FaseVida)
        self.assertEqual(barra.width, 20)
        msgs = self._caught(lambda: change_act(Vazia))
        self.assertEqual(msgs, [])
        self.assertEqual(barra.width, 1)
        self.assertEqual(hud.text, "")
        barra.width = 50
        hud.text = "NAVES"
        barra.destroy()
        hud.destroy()

    def test_a_game_link_the_act_replaced_comes_back(self):
        st.titulo = "jogo"
        hud = Text("", top_left=(10, 290))
        hud["text"] @= lambda: st.titulo

        class FaseOutra(Act):
            def setup(self):
                hud["text"] @= lambda: f"ato {st.titulo}"

        msgs = self._caught(lambda: self.begin(FaseOutra))
        self.assertEqual(hud.text, "ato jogo")
        # The replace inside the act still says so, as a SCENA WARNING.
        self.assertTrue(any(m.startswith("SCENA WARNING: @=:") and
                            "overrides its previous link" in m for m in msgs), msgs)
        msgs = self._caught(lambda: change_act(Vazia))
        self.assertEqual(msgs, [])
        self.assertTrue(hud["text"].is_linked)
        st.titulo = "de novo"
        self.assertEqual(hud.text, "de novo")
        hud.destroy()

    def test_a_point_field_gets_its_place_back(self):
        alvo = Circle(center=(50, 60), radius=5)

        class FaseSegue(Act):
            def setup(self):
                guia = Circle(center=(200, 100), radius=3)
                alvo["center"] @= guia["center"]

        self.begin(FaseSegue)
        self.assertEqual((alvo.center.x, alvo.center.y), (200, 100))
        msgs = self._caught(lambda: change_act(Vazia))
        self.assertEqual(msgs, [])
        self.assertEqual((alvo.center.x, alvo.center.y), (50, 60))
        alvo.move_to(1, 2)
        alvo.destroy()

    def test_the_object_spelling_of_a_part_link_leaves_too(self):
        alvo = Circle(center=(50, 60), radius=5)

        class FaseSegue2(Act):
            def setup(self):
                guia = Circle(center=(200, 100), radius=3)
                alvo.center @= guia.center

        self.begin(FaseSegue2)
        self.assertEqual((alvo.center.x, alvo.center.y), (200, 100))
        self.assertEqual(self._caught(lambda: change_act(Vazia)), [])
        self.assertEqual((alvo.center.x, alvo.center.y), (50, 60))
        alvo.destroy()

    def test_links_on_act_objects_and_top_level_links_are_untouched(self):
        st.n = 1
        hud = Text("", top_left=(10, 290))
        hud["text"] @= lambda: f"n={st.n}"
        self.begin(Vazia)
        change_act(Vazia)
        st.n = 2
        self.assertEqual(hud.text, "n=2")
        self.assertEqual(get_act_manager()._act_links, {})
        hud.destroy()


class TestMessagesNameTheAct(ActTestCase):
    """An act is built by the framework: messages say "act Fase", never the
    raw ``<__main__.Fase object at 0x…>`` or "the Fase made at
    system_support.py:364" (review 2026-10-14 PA5)."""

    def test_label_and_repr(self):
        from scena.entity import entity_label
        self.begin(Vazia)
        self.assertEqual(entity_label(current()), "act Vazia")
        self.assertEqual(repr(current()), "act Vazia")
        self.assertEqual(str(current()), "act Vazia")

    def test_a_write_to_an_act_after_its_change_act_names_the_change(self):
        """CD5 (chaos doors): ``change_act`` inside an act's own ``setup``
        ends that act at once; a write to ``self`` after it is refused with a
        fix about the act change, not "Guard the call: if actor:"."""
        from scena.state import DestroyedError

        class Fim5(Act):
            pass

        class Fase5(Act):
            def setup(self):
                change_act(Fim5)
                self.pontos = 0

        with self.assertRaises(DestroyedError) as cm:
            self.begin(Fase5)
        msg = str(cm.exception)
        self.assertIn("act Fase5 ended", msg)
        self.assertIn("Fase5.pontos cannot change", msg)    # the field (VB15)
        self.assertIn("change_act", msg)
        self.assertIn("return right after", msg)
        self.assertNotIn("if actor:", msg)

    def test_the_watchdog_names_the_act(self):
        import scena.process as proc

        class Presa(Act):
            def setup(self):
                self.mode = self.gira

            @on_mode
            async def gira(self):
                while True:
                    pass

        old = proc.WATCHDOG_RESUME_S
        proc.WATCHDOG_RESUME_S = 0.05
        try:
            with warnings.catch_warnings(record=True) as ws:
                warnings.simplefilter("always")
                self.begin(Presa)
                self.w.step(1)
        finally:
            proc.WATCHDOG_RESUME_S = old
        msgs = [str(w.message) for w in ws if "without awaiting" in str(w.message)]
        self.assertTrue(msgs)
        self.assertIn("async mode 'gira' on act Presa ran", msgs[0])
        self.assertNotIn("object at 0x", msgs[0])

    def test_a_dropped_link_that_read_the_act_names_it(self):
        placar = Text("", top_left=(10, 290))

        class ComPontos(Act):
            def setup(self):
                self.pontos = 2
                # Not an act's @= (that one is undone silently, PA1).
                placar._link_field("text", lambda: f"P {self.pontos}")

        self.begin(ComPontos)
        with quiet():
            change_act(Vazia)
        msg = last_author_error()["message"]
        self.assertIn("read act ComPontos, which ended when the game changed to Vazia", msg)
        self.assertNotIn("made at", msg.split(" read ")[1])
        placar.destroy()


class TestNamedSlotsAcrossTheSeal(ActTestCase):
    """An act's ownerless timer with a game timer's name replaces it for the
    act only; the act change gives the game's back (review 2026-10-09 S2-6)."""

    def test_game_timer_pauses_during_the_act_and_comes_back(self):
        from scena import every
        game_beats, act_beats = [], []
        every(0.25, lambda: game_beats.append(1), name="beat")

        class Musica(Act):
            def setup(self):
                every(0.5, lambda: act_beats.append(1), name="beat")

        self.begin(Musica)
        n0 = len(game_beats)
        self.w.step(60, dt=1 / 60)
        self.assertEqual(len(game_beats), n0, "the game's beat ran during the act")
        self.assertEqual(len(act_beats), 2)
        change_act(Vazia)
        self.w.step(60, dt=1 / 60)
        self.assertEqual(len(game_beats) - n0, 4, "the game's beat did not come back")
        self.assertEqual(len(act_beats), 2)
        get_scheduler()._named[(None, "beat")].cancel()

    def test_an_author_pause_is_kept(self):
        from scena import every
        beats = []
        h = every(0.25, lambda: beats.append(1), name="beat2")
        h.pause()

        class Outra2(Act):
            def setup(self):
                every(0.5, lambda: None, name="beat2")

        self.begin(Outra2)
        change_act(Vazia)
        self.w.step(60, dt=1 / 60)
        self.assertEqual(beats, [])
        self.assertTrue(h.paused)
        h.cancel()

    # A task cannot pause, so it cannot step aside for the act: before
    # 2026-10-19 the act's same-name work cancelled the game's task for good
    # (its timers came back at the act change, its task did not), silently.

    def _game_task(self, name, beats):
        from scena import run_task, wait

        async def clima():
            while True:
                await wait(0.25)
                beats.append(1)

        return run_task(clima, name=name)

    def test_an_act_task_taking_a_game_task_name_raises_with_the_fix(self):
        from scena import run_task, wait
        beats = []
        h = self._game_task("clima", beats)
        started = []

        async def chuva():
            started.append(1)
            await wait(1)

        class Tempestade(Act):
            def setup(self):
                run_task(chuva, name="clima")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(ValueError) as cm:
                self.begin(Tempestade)
            gc.collect()
        self.assertEqual([str(w.message) for w in caught
                          if "never awaited" in str(w.message)], [])
        msg = str(cm.exception)
        for part in ("'clima'", "game task", "clima()", "another name", "cancel()"):
            self.assertIn(part, msg)
        self.assertEqual(started, [], "the refused task's body ran")
        self.assertFalse(h.cancelled, "the game's task was cancelled anyway")
        self.assertIs(get_scheduler()._named[(None, "clima")], h)
        self.w.step(30, dt=1 / 60)
        self.assertGreater(len(beats), 0, "the game's task stopped")
        h.cancel()

    def test_an_act_timer_taking_a_game_task_name_raises(self):
        from scena import after
        beats = []
        h = self._game_task("clima2", beats)

        class Garoa(Act):
            def setup(self):
                after(1, lambda: None, name="clima2")

        with self.assertRaises(ValueError) as cm:
            self.begin(Garoa)
        self.assertIn("after(", str(cm.exception))
        self.assertFalse(h.cancelled)
        h.cancel()

    def test_a_refused_sound_or_tween_leaves_nothing_behind(self):
        """The check runs before the voice starts and before the tween
        claims its target, not only at registration."""
        from scena import play_sound, tween
        from scena.audio_mixer import get_mixer
        h = self._game_task("clima5", [])
        alvo = Circle()
        mover = tween(alvo["radius"], 50, time=2)   # game work on alvo
        test = self

        class Trovao(Act):
            def setup(self):
                mixer = get_mixer()
                with mock.patch.object(mixer, "start_voice",
                                       wraps=mixer.start_voice) as start:
                    with test.assertRaises(ValueError) as cm:
                        play_sound(tone(), name="clima5")
                test.assertIn("play_sound(", str(cm.exception))
                test.assertEqual(start.call_count, 0, "a refused play_sound started a voice")
                with test.assertRaises(ValueError) as cm:
                    tween(alvo["radius"], 80, time=1, name="clima5")
                test.assertIn("tween(", str(cm.exception))

        self.begin(Trovao)
        self.assertFalse(mover.cancelled, "a refused tween took the target")
        self.assertFalse(h.cancelled)
        h.cancel()

    def test_a_finished_or_cancelled_game_task_leaves_the_name_free(self):
        from scena import run_task, wait
        h = self._game_task("clima3", [])
        h.cancel()
        ran = []

        async def sol():
            ran.append(1)
            await wait(1)

        class Verao(Act):
            def setup(self):
                run_task(sol, name="clima3")

        self.begin(Verao)
        self.assertEqual(ran, [1])

    def test_a_game_task_restarts_itself_by_name_during_an_act(self):
        """The task's own step is game scope: restart is not a clash."""
        from scena import run_task, wait
        runs = []

        async def onda():
            runs.append(1)
            await wait(0.25)
            if len(runs) < 3:
                run_task(onda, name="onda")

        run_task(onda, name="onda")
        self.begin(Vazia)
        self.w.step(60, dt=1 / 60)
        self.assertEqual(len(runs), 3)

    def test_an_actor_owned_task_with_the_name_is_not_a_clash(self):
        """Owned slots are per owner: only ownerless act work shadows game work."""
        beats = []
        h = self._game_task("clima4", beats)
        from scena import wait

        class Ilha(Act):
            def setup(self):
                async def nuvem(c):
                    await wait(1)
                self.c = Circle()
                self.c.run_task(nuvem, name="clima4")

        self.begin(Ilha)
        self.assertFalse(h.cancelled)
        h.cancel()


class TestCoverOnDoneLeavesWithTheAct(ActTestCase):
    """An act's in-flight fade keeps animating across the change, but its
    on_done leaves with the act (review 2026-10-09 S4-2)."""

    def test_old_on_done_does_not_redirect_the_next_act(self):
        entered = []

        class Fim(Act):
            def setup(self):
                entered.append("Fim")

        class Titulo2(Act):
            def setup(self):
                entered.append("Titulo")
                canvas.fade_in(0.5)          # replaces the old fade

        class Fase4(Act):
            def setup(self):
                entered.append("Fase")
                canvas.fade_out(0.5, on_done=lambda: change_act(Fim))

        self.begin(Fase4)
        self.w.step(6, dt=1 / 60)
        change_act(Titulo2)
        self.w.step(60, dt=1 / 60)
        self.assertEqual(entered, ["Fase", "Titulo"])
        self.assertIsInstance(current(), Titulo2)

    def test_on_done_of_a_fade_that_ends_in_the_act_still_runs(self):
        done = []

        class Fase5(Act):
            def setup(self):
                canvas.fade_out(0.25, on_done=lambda: done.append(1))

        self.begin(Fase5)
        self.w.step(30, dt=1 / 60)
        self.assertEqual(done, [1])
        canvas.fade_in(0)


class TestChangeInsideADispatch(ActTestCase):
    """A change_act made by the first handler of a dispatch stops the dead
    act's handlers that follow in the same dispatch (review 2026-10-09
    S4-1): @collide pair handlers and @leave_playfield handlers."""

    def test_collide_handlers_of_the_leaving_act_stop(self):
        log = []

        class Placar(Act):
            pass

        class Fase6(Act):
            def setup(self):
                @collide("ci_bola", "ci_gol")
                def torcida(b, g):
                    log.append(type(current()).__name__)

        @collide("ci_bola", "ci_gol")
        def gol(b, g):
            change_act(Placar)

        bola = Circle(center=(0, 0), radius=10, group="ci_bola")
        trave = Circle(center=(200, 0), radius=10, group="ci_gol")
        self.begin(Fase6)
        self.w.step(1, dt=1 / 60)
        bola.center = (195, 0)
        self.w.step(1, dt=1 / 60)
        self.assertNotIn("Placar", log)
        bola.destroy()
        trave.destroy()

    def _act_hook_on_game_bodies(self, phase):
        """CD2 (chaos doors): the act set ``phase`` (``on_collide``, the stay
        or the exit hook) on two game bodies, as a closure over the act (the act's own
        hook); the hook that runs first changes the act; the other body's
        hook, already chosen for the same contact, must not run after the
        act is gone (``_drop_act_callables`` cleared it)."""
        log = []

        class Placar2(Act):
            pass

        p = Circle(center=(0, 0), radius=10)
        q = Circle(center=(300, 0), radius=10)

        class Fase8(Act):
            def setup(self):
                act = self

                def hit(me, other):
                    log.append(("p" if me is p else "q", type(current()).__name__, act.is_alive))
                    if len(log) == 1:
                        change_act(Placar2)
                setattr(p, phase, hit)
                setattr(q, phase, hit)

        self.begin(Fase8)
        self.w.step(1, dt=1 / 60)
        q.center = (5, 0)
        self.w.step(3, dt=1 / 60)
        if phase == "on_collide_exit":
            q.center = (300, 0)             # the contact ends: its exit
            self.w.step(3, dt=1 / 60)
        self.assertEqual(len(log), 1, log)
        self.assertEqual(log[0][1:], ("Fase8", True))
        p.destroy()
        q.destroy()

    def test_an_act_hook_on_a_game_body_stops_on_enter(self):
        self._act_hook_on_game_bodies("on_collide")

    def test_an_act_hook_on_a_game_body_stops_on_stay(self):
        self._act_hook_on_game_bodies("on_collide_stay")

    def test_an_act_hook_on_a_game_body_stops_on_exit(self):
        self._act_hook_on_game_bodies("on_collide_exit")

    def test_leave_handlers_of_the_leaving_act_stop(self):
        import itertools
        log = []

        class Fim(Act):
            pass

        class Fase7(Act):
            def setup(self):
                @leave_playfield("ci_tiro")
                def ato(t):
                    log.append(type(current()).__name__)

        @leave_playfield("ci_tiro")
        def jogo(t):
            change_act(Fim)

        tiro = Circle(center=(0, 0), radius=3, group="ci_tiro")
        self.begin(Fase7)
        self.w.step(1, dt=1 / 60)
        tiro.center = (0, -5000)
        self.w.step(1, dt=1 / 60)
        self.assertNotIn("Fim", log)
        tiro.destroy()


if __name__ == "__main__":
    unittest.main()
