"""Every engine warning has two sides: when it fires, and the pattern next to it that stays silent.

Class of bugs (Testing Design, "What the game system tests taught"): a
warning is a contract with two sides, and the tests only held one. AC7 (the
frozen-mode warning), AC9 (the group near-miss), AC11 (an own field unlinked
on destroy) and AC13 (a named tween refreshed) each had a test that fired
the warning; none ran the documented pattern next to it, which fired it
too. A game run treats every SCENA warning as a failure and met all four in
its first runs.

This guard holds every warning site of the engine (each ``warnings.warn``
and each ``report_author_warning`` call, by module and function, found by
``ast``) to a row of ``CONTRACTS``:

* ``fires`` — the test module that triggers it (measured: ``python
  tests/warning_sites.py`` runs a tier with a recording hook), or
  ``untested=`` with the reason none does;
* ``silent`` — the test that runs the legitimate pattern next to it and
  requires no warning (``module.Class.method``), or ``twin=`` saying why the
  warning has no legitimate twin (a missing file is always a mistake).

A new warning site fails until it has a row; a row whose site is gone fails;
a named test that does not exist fails. The documented patterns themselves
run in ``test_documented_patterns``.

    python tests/run_tiers.py focused test_warning_contracts
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from dataclasses import dataclass
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCENA = os.path.join(ROOT, "scena")
sys.path.insert(0, HERE)

from source_support import iter_files  # noqa: E402

# Funnels: they warn for their callers, whose rows are kept instead.
FUNNELS = {"process:report_author_warning"}


@dataclass(frozen=True)
class W:
    fires: Optional[str] = None          # test module that triggers it
    untested: str = ""                   # why no test triggers it
    silent: Optional[str] = None         # test of the legitimate twin: "module.Class.method"
    twin: str = ""                       # why there is no legitimate twin


MISSING_FILE = "a missing or unreadable file has no legitimate twin: the placeholder is the contract"
MISTAKE = "always an author mistake: no legitimate pattern reaches it"
GUARD = "a runaway guard (time / count limit): nothing legitimate reaches the limit"

CONTRACTS: Dict[str, W] = {
    # --- acts, modes, timers ---------------------------------------------------
    "act:_unlink_notice": W(fires="test_act", silent="test_act.TestBatchTeardown.test_hud_and_the_object_it_reads_leave_together_silently"),
    "process:Scheduler._warn_frozen_modes": W(fires="test_process", silent="test_process.TestFrozenModeWarning.test_idle_time_counts_not_mode_age"),
    "process:_preempt_tween_keys": W(fires="test_driver_composition", silent="test_process.TestNamedTweenSlotReplacesQuietly.test_same_slot_on_a_cell_is_quiet"),
    "process:Scheduler.add": W(fires="test_process", silent="test_process.TestNamedTweenSlotReplacesQuietly.test_same_slot_on_a_field_is_quiet"),
    "process:Script._cancelled_under_it": W(fires="test_process", silent="test_process.TestAsyncAwait.test_destroy_while_waiting_is_silent"),
    "process:Script._tripped_watchdog": W(fires="test_process", twin=GUARD),
    "process:Script.cancel": W(untested="an exception raised inside a cancelled async body while it unwinds: not reached by any test yet",
                               twin="a body that unwinds cleanly on cancel is the normal path (every mode-change test)"),
    "process:exit_mode.<locals>.deco": W(fires="test_process", silent="test_process.TestOnModeAndExitMode.test_async_enter_fn_allows_exit_mode_without_warning"),
    "process:Handle._apply_then": W(fires="test_process", twin="then= into a mode while no async body runs: the normal then= path (test_process)"),
    "process:_warn_unawaited": W(fires="test_async_hooks", silent="test_async_hooks.TestNeverAwaitedHook.test_awaited_or_closed_coroutine_is_silent"),
    "process:_python_unawaited": W(fires="test_async_hooks", silent="test_async_hooks.TestNeverAwaitedHook.test_awaited_or_closed_coroutine_is_silent"),
    "process:Handle.__del__": W(fires="test_process", twin="an awaited handle is the normal path: every async test"),
    "process:Scheduler.note_every_site": W(fires="test_process", twin="every() armed once (setup, a mode body) is the normal path"),
    "process:Scheduler._tick_on_update": W(fires="test_process", twin=GUARD),
    "orchestration:ScenaFramework._simulate_frame": W(untested="the script-update watchdog needs a real time budget overrun; test_process covers the on_update / async twins", twin=GUARD),
    "orchestration:ScenaFramework._cleanup": W(fires="test_run_cleanup", twin="a cleanup step that raises: no legitimate twin"),
    "orchestration:ScenaFramework._tick_leak_detector": W(fires="test_leak_detector", twin="steady memory is the normal path (test_leak_detector)"),
    "pacing:FramePacer.__init__": W(untested="platform pacing fallback (no CoreVideo display link): test_pacing_corevideo runs where it exists", twin="the display link is present: the normal path"),
    # --- reactive core ----------------------------------------------------------
    "state:Container._clean_up": W(fires="test_act", silent="test_graph_lifecycle.TestOwnFieldLinksDieQuietly.test_self_reading_field_is_quiet"),
    "state:FormulaLink._follow_holders": W(fires="test_formula_follows_holder", silent="test_formula_follows_holder.TestHolderMatrix.test_follows_a_new_object"),
    "state:Container._assign_formula": W(fires="test_graph_lifecycle", twin="a first link on a field is silent: every link test"),
    "state:UpdateManager.flush": W(fires="test_reactive_edge_cases", silent="test_reactive_edge_cases.TestEvents.test_destroyed_source_retires_quietly"),
    "shapes:_ensure_writable": W(fires="test_pose_fast_path", twin="only with force=True: the author asked to unlink"),
    "shapes:_warn_point_compare": W(fires="test_point_equality", silent="test_point_equality.TestEngineStaysSilent.test_handles_on_one_spot"),
    "registry:GroupOperator.__getitem__": W(fires="test_group_name_guard", silent="test_group_name_guard.TestDeclaringAFormulaIsNotATypo.test_formula_declaration_does_not_warn"),
    "registry:Registry.set_group_formula": W(fires="test_registry_layers", twin="a first group formula is silent: every formula-group test"),
    # --- collision ----------------------------------------------------------------
    "collision:CollisionSystem.remove_resolve_pair": W(fires="test_collision", twin="unresolve() of a standing pair is silent: every resolve test"),
    "collision:CollisionSystem._warn_dead_object_target": W(fires="test_warning_contracts", twin="@collide on a live object, or on group tags: the normal path"),
    "collision:_warn_missing_vel_once": W(fires="test_sys_holders", twin="bounce= on bodies with .vel: every bounce test"),
    "collision:_mass_or_static": W(fires="test_warning_contracts", twin="a push between bodies with .mass: every push test"),
    "collision:_ear_clip": W(untested="a polygon the ear clipper cannot finish (self-intersecting / degenerate in a way the guards upstream let through)", twin=MISTAKE),
    "collision:note_collider_motion": W(untested="an engine-internal NaN delta: refused upstream by every author door", twin=MISTAKE),
    "entity:_warn_anything_and_on_collide": W(fires="test_collision", twin=MISTAKE),
    # --- art, files, fonts --------------------------------------------------------
    "atlas:_empty_alpha_mask": W(untested="a downsample failure of a decoded image: not reachable with a valid file", twin=MISSING_FILE),
    "audio:_warn_asset": W(fires="test_audio", twin=MISSING_FILE),
    "audio_capture:Microphone._fail_open": W(fires="test_audio_capture", twin="an input device exists: the normal path"),
    "audio_capture:Microphone._warn_cap": W(fires="test_audio_capture", twin=GUARD),
    "sprite:_true_case_path": W(fires="test_sheet_patterns", twin=MISSING_FILE),
    "sprite:_expand_pattern": W(fires="test_sheet_patterns", twin=MISSING_FILE),
    "sprite:_load_sprite_image": W(fires="test_sprite", silent="test_sprite.TestIdentityAndPlaceholder.test_placeholder_is_legal_no_warning"),
    "sprite:Sheet._init_from_atlas": W(fires="test_sprite", twin=MISSING_FILE),
    "sprite:Sheet._register_clip": W(fires="test_sprite", twin="a clip name used once: the normal path"),
    "sprite:_warn_stale_hitbox_from": W(fires="test_sprite", twin=MISTAKE),
    "sprite:_warn_atlas_source_mismatch": W(fires="test_sprite", twin=MISSING_FILE),
    "sprite:_svg_warn_once": W(fires="test_svg", twin=MISSING_FILE),
    "sprite:_warn_unknown_frame": W(fires="test_sprite", twin=MISTAKE),
    "style:_load_image": W(fires="test_background_image", twin=MISSING_FILE),
    "style:_warn_recolor_hidden": W(fires="test_visuals", twin="set_color on a visual that paints the shape's colour: the normal path"),
    "color:ColorNames.get": W(fires="test_color", twin=MISTAKE),
    "color:Color._parse_color_args": W(fires="test_color", twin=MISTAKE),
    "orchestration:ScenaFramework.set_auto_callbacks": W(fires="test_class_hook_names", silent="test_class_hook_names.TestTopLevelNearMisses.test_helpers_hooks_and_decorated_functions_are_left_alone"),
    "entity:_class_hook_refusal": W(fires="test_class_hook_names", silent="test_class_hook_names.TestOtherEnginesHookNames.test_a_method_the_file_calls_itself_is_a_helper"),
    "formula_check:_warn_container_read": W(fires="test_formula_functions", silent="test_formula_functions.TestContainerItemLinks.test_a_list_only_reassigned_says_nothing"),
    "color:_comparable_rgba": W(fires="test_color", silent="test_color.TestColorEquality.test_not_a_color_is_unequal_and_silent"),
    "uiwidget:resolve_typeface": W(fires="test_text", twin=MISSING_FILE),
    "uiwidget:resolve_ui_typeface": W(fires="test_api_robustness", twin=MISSING_FILE),
    "background:wrap_background_source": W(untested="no caller passes camera knobs: every door calls wrap_background_source(value) bare, so the branch is unreachable today",
                                            twin="camera knobs set on the field itself: the normal path"),
    # --- layout -------------------------------------------------------------------
    "endless:Endless._warn_cap": W(fires="test_endless", twin=GUARD),
    "endless:Endless._check_drift": W(fires="test_endless", silent="test_endless.TestCapAndWarnings.test_drift_warning_silent_when_the_camera_moves"),
    "menu:Menu._fit_into": W(fires="test_menu", silent="test_menu.MenuTest.test_box_shrinks_to_fit_title"),
    "sprite_button:SpriteButton._label_fit": W(fires="test_sprite_button", silent="test_sprite_button.TestLabel.test_shrinks_to_fit_font_size_unchanged"),
}


def _key(path: str, stack) -> str:
    mod = os.path.relpath(path, SCENA)[:-3].replace(os.sep, ".")
    parts = []
    for kind, name in stack:
        if parts and parts[-1][0] == "def":
            parts.append(("locals", "<locals>"))
        parts.append((kind, name))
    return f"{mod}:" + ".".join(n for _k, n in parts)


def warning_sites() -> Dict[str, int]:
    """``{module:qualname: count}`` of every warning call in ``scena/``."""
    out: Dict[str, int] = {}

    def visit(node, stack, path):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, stack + [("def", child.name)], path)
            elif isinstance(child, ast.ClassDef):
                visit(child, stack + [("class", child.name)], path)
            else:
                if isinstance(child, ast.Call):
                    f = child.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                    is_warn = name == "warn" and isinstance(f, ast.Attribute) and \
                        getattr(f.value, "id", "") == "warnings"
                    if is_warn or name == "report_author_warning":
                        key = _key(path, stack)
                        out[key] = out.get(key, 0) + 1
                visit(child, stack, path)

    for path in iter_files(SCENA, ".py", recursive=True):
        with open(path, encoding="utf-8") as fh:
            visit(ast.parse(fh.read(), filename=path), [], path)
    for f in FUNNELS:
        out.pop(f, None)
    return out


def _test_exists(test_id: str) -> bool:
    """``module.Class.method`` (or ``module``) names a real test in ``tests/``."""
    parts = test_id.split(".")
    path = os.path.join(HERE, parts[0] + ".py")
    if not os.path.isfile(path):
        return False
    if len(parts) == 1:
        return True
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == parts[1]:
            if len(parts) == 2:
                return True
            return any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == parts[2]
                       for m in node.body)
    return False


class TestEveryWarningHasAContract(unittest.TestCase):
    def test_sites_and_rows_match(self):
        sites = set(warning_sites())
        self.assertGreater(len(sites), 40, "the site scan found almost nothing")
        new = sorted(sites - set(CONTRACTS))
        gone = sorted(set(CONTRACTS) - sites)
        self.assertEqual(new, [], "a warning site with no row: add a test that fires it and "
                                 "one that runs the legitimate pattern next to it, then list it")
        self.assertEqual(gone, [], "a row whose warning site is gone")

    def test_each_row_answers_both_sides(self):
        for key, w in CONTRACTS.items():
            with self.subTest(site=key):
                self.assertTrue(bool(w.fires) != bool(w.untested), "fires= or untested=, one of them")
                self.assertTrue(bool(w.silent) != bool(w.twin), "silent= or twin=, one of them")
                if w.fires:
                    self.assertTrue(_test_exists(w.fires), f"no test module {w.fires}")
                if w.silent:
                    self.assertTrue(_test_exists(w.silent), f"no test {w.silent}")
                for text in (w.untested, w.twin):
                    if text:
                        self.assertGreater(len(text), 15, "a reason, not a word")


class TestWarningsNoTestFired(unittest.TestCase):
    """Rows that pointed at this module: the first test that fires each."""

    def setUp(self):
        sys.path.insert(0, ROOT)
        from system_support import SystemWorld
        self.w = SystemWorld(draw=False)

    def tearDown(self):
        self.w.teardown()

    def _warned(self, fn, words):
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fn()
        msgs = [str(c.message) for c in caught]
        self.assertTrue(any(words in m for m in msgs), f"no warning with {words!r}: {msgs}")

    def test_collide_on_a_destroyed_object(self):
        from scena import Circle, collide
        a = self.w.track(Circle(radius=4))
        a.destroy()

        def register():
            @collide(a, "parede_wc")
            def _hit(x, y):
                pass
        self._warned(register, "is destroyed")

    def test_push_without_mass(self):
        from scena import Orb, Rect, collide
        self.w.track(Rect(center=(100, 100), width=20, height=20, group="wc_a"))
        self.w.track(Orb(center=(110, 100), radius=12, group="wc_b"))   # a SpatialFx has no .mass

        @collide("wc_a", "wc_b")
        def _push(x, y, info):
            info.push_apart()
        self._warned(lambda: self.w.step(1), "has no .mass")


if __name__ == "__main__":
    unittest.main()
