"""Guard: every author export is reached by a program model test or excluded with a reason.

Coverage tool: tests/program_coverage.py (calls from a program's own code into
scena, mapped onto ``scena.__all__``). Protocol: design/Testing Design.md,
"Program model tests". In ``run_tiers.SLOW`` (~55 s at any profile: every
spec scenario under the hook).

A new export fails this guard until a program uses it (write or extend an
API-first program in tests/programs/, with specs) or it gets a reason below.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402

# Families checked at the "draws something / changes over time" level by the
# Guia render probe (tools/guide/make_guia_thumbs.py, tests/test_guia_thumbs_render.py),
# not modeled: their contract is a look.
_LOOK_BASES = ("Visual", "Recipe", "PostEffect", "BackgroundField", "SpatialFx",
               "FilterEffect", "AudioEffect", "ProceduralFill")
_LOOK_REASON = "a look: Guia render probe (make_guia_thumbs) checks it draws / animates"

PROGRAM_EXCLUDED = {
    # Raised, never built by an author program.
    "CallableAssignError": "an error type: raised, not built",
    "Cancelled": "an error type: raised inside a cancelled mode / await",
    "DerivedAttributeError": "an error type: raised, not built",
    "DestroyedError": "an error type: raised, not built",
    "LinkedAttributeError": "an error type: raised, not built",
    "ParallaxLayerError": "an error type: raised, not built",
    "UiLayerError": "an error type: raised, not built",
    # Material helpers for looks (the *Fill functions build a ProceduralFill).
    "AuroraFill": _LOOK_REASON, "FlameFill": _LOOK_REASON, "SwellFill": _LOOK_REASON,
    "WaterFill": _LOOK_REASON, "WaveFill": _LOOK_REASON,
    "Colormap": "look data (gradient presets): test_gradient_presets",
    "Palette": "look data: test_gradient_presets",
    "ColorNames": "the colour table: test_color / test_color_literals",
    "ColorSpace": "an enum of colour spaces: test_color",
    "FxQuality": "an enum for canvas.fx_quality: test_fx_quality",
    # Not author program behaviour.
    "run": "replaced by the harness's startup (every program calls it)",
    "set_fx_auto": "a bench / performance knob: test_fx_auto",
    "set_watchdog": "a debugging knob: test_framework_debug",
    "set_extrude_focus": "a look tuning knob (Extrude): test_visuals",
    "show_tracks": "a debug overlay: test_track",
    "show_processes": "a debug overlay (the process panel): test_process_overlay",
    "Microphone": "an input device (no device headless): test_audio_capture",
    "Level": "loads a level file made by the editor: test_level, scena_editor/tests",
    # Reached through the State bag only. Before 0.8.0 ``st.x`` handed out the
    # cell, so ``st.x + 1`` counted; now ``st.x`` is the value and programs pass
    # ``st["x"]`` to widgets / tween / @on_change, which count as those exports.
    "Attribute": "the cell type: st['x'] in every program; its members: test_state_reads_value",
}


def excluded(name: str):
    if name in PROGRAM_EXCLUDED:
        return PROGRAM_EXCLUDED[name]
    obj = getattr(scena, name, None)
    if inspect.isclass(obj) and any(c.__name__ in _LOOK_BASES for c in obj.__mro__):
        return _LOOK_REASON
    return None


class TestEveryExportIsReachedOrExcused(unittest.TestCase):
    def test_coverage(self):
        from program_coverage import report
        r = report(write_json=True)
        missing = [n for n in r["missing"] if excluded(n) is None]
        self.assertFalse(
            missing,
            f"{len(missing)} exports reached by no program and not excused "
            f"(see .scena_test_runs/program_coverage.json): {', '.join(missing)}")

    def test_no_stale_exclusion(self):
        for name in PROGRAM_EXCLUDED:
            with self.subTest(name=name):
                self.assertIn(name, scena.__all__, "excluded name is not exported")


if __name__ == "__main__":
    unittest.main()
