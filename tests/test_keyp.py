"""keyp bare / held / chord / once semantics."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.input import KeyPressed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given, strategies as hst  # noqa: E402


class TestKeypBareHeldChord(unittest.TestCase):
    def setUp(self):
        self.k = KeyPressed()

    def test_bare_play_key(self):
        k = self.k
        k._press("R")
        self.assertTrue(k("R"))
        self.assertTrue(k.held("R"))
        self.assertTrue("R" in k)
        k._release("R")
        self.assertFalse(k("R"))
        self.assertFalse(k.held("R"))

    def test_another_play_key_held_does_not_matter(self):
        # Guia keyp("A") (PM10): only modifiers filter; keyp.only is exclusive.
        k = self.k
        k._press("LEFT")
        k._press("RIGHT")
        self.assertTrue(k("LEFT"))
        self.assertTrue(k("RIGHT"))
        self.assertFalse(k.only("LEFT"))

    def test_shift_does_not_hide_a_bare_play_key(self):
        # PD6 (0.8.1): "hold Shift to run" keeps keyp("LEFT"); the chord
        # still reads, keyp.only stays exclusive.
        k = self.k
        k._press("SHIFT")
        k._press("LEFT")
        self.assertTrue(k("LEFT"))
        self.assertTrue("LEFT" in k)
        self.assertTrue(k.held("LEFT"))
        self.assertTrue(k("SHIFT"))
        self.assertTrue(k("SHIFT+LEFT"))
        self.assertFalse(k("CTRL+LEFT"))
        self.assertFalse(k.only("LEFT"))
        self.assertTrue(k.only("SHIFT+LEFT"))

    def test_shift_keeps_a_chord_exact(self):
        # PD6: only a bare key ignores Shift. Cmd+Shift+Z is not CMD+Z.
        k = self.k
        k._press("CMD")
        k._press("SHIFT")
        k._press("Z")
        self.assertFalse(k("CMD+Z"))
        self.assertTrue(k("CMD+SHIFT+Z"))
        self.assertFalse(k("Z"))                 # Cmd still hides the bare key

    def test_ctrl_hides_a_bare_play_key(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        self.assertFalse(k("R"))
        self.assertTrue(k.held("R"))
        self.assertTrue(k("CTRL+R"))
        self.assertFalse(k("SHIFT+R"))

    def test_alt_and_cmd_hide_a_bare_play_key(self):
        for mod in ("ALT", "CMD"):
            with self.subTest(mod):
                k = KeyPressed()
                k._press(mod)
                k._press("SPACE")
                self.assertFalse(k("SPACE"))
                self.assertFalse(k.once("SPACE"))
                self.assertTrue(k(f"{mod}+SPACE"))

    def test_shift_family_either_side(self):
        k = self.k
        k._press("LEFT_SHIFT")
        self.assertTrue(k("SHIFT"))
        self.assertTrue(k("LEFT_SHIFT"))
        self.assertFalse(k("RIGHT_SHIFT"))
        k._release("LEFT_SHIFT")
        k._press("RIGHT_SHIFT")
        self.assertTrue(k("SHIFT"))
        self.assertTrue(k("RIGHT_SHIFT"))
        self.assertFalse(k("LEFT_SHIFT"))

    def test_press_shift_stores_left(self):
        k = self.k
        k._press("SHIFT")
        self.assertTrue(k("LEFT_SHIFT"))
        self.assertTrue(k("SHIFT"))

    def test_ctrl_has_one_spelling(self):
        k = self.k
        k._press("LEFT_CTRL")
        self.assertTrue(k("CTRL"))
        self.assertFalse(k("CTRL+A"))
        k._press("A")
        self.assertTrue(k("CTRL+A"))
        for other in ("CONTROL", "control+a", "LEFT_CONTROL"):
            with self.subTest(other=other):
                with self.assertRaises(ValueError) as ctx:
                    k(other)
                self.assertIn("Scena calls it", str(ctx.exception))

    def test_cmd_family(self):
        k = self.k
        k._press("LEFT_CMD")
        self.assertTrue(k("CMD"))
        for other in ("SUPER", "COMMAND", "WIN", "META"):
            with self.subTest(other=other):
                with self.assertRaises(ValueError) as ctx:
                    k(other)
                self.assertIn("'CMD'", str(ctx.exception))
        k._press("R")
        self.assertFalse(k("R"))
        self.assertTrue(k("CMD+R"))

    def test_chord_extra_play_keys_ok(self):
        k = self.k
        k._press("CTRL")
        k._press("A")
        k._press("LEFT")
        self.assertTrue(k("CTRL+A"))
        self.assertTrue(k("CTRL+LEFT"))
        self.assertFalse(k("A"))
        self.assertFalse(k("LEFT"))

    def test_exact_modifier_set(self):
        k = self.k
        k._press("CTRL")
        k._press("SHIFT")
        k._press("A")
        self.assertFalse(k("CTRL+A"))
        self.assertFalse(k("SHIFT+A"))
        self.assertTrue(k("CTRL+SHIFT+A"))
        self.assertTrue(k("SHIFT+CTRL+A"))
        self.assertTrue(k("A+CTRL+SHIFT"))

    def test_spaces_and_case(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        self.assertTrue(k("ctrl + r"))

    def test_modifier_presence_ignores_play_keys(self):
        k = self.k
        k._press("SHIFT")
        k._press("A")
        k._press("B")
        self.assertTrue(k("SHIFT"))
        self.assertTrue(k("A"))                  # Shift does not hide it (PD6)
        self.assertFalse(k.only("A"))

    def test_bool_any_physical(self):
        k = self.k
        self.assertFalse(k)
        k._press("SHIFT")
        self.assertTrue(bool(k))

    def test_only(self):
        k = self.k
        k._press("A")
        self.assertTrue(k.only("A"))
        k._press("B")
        self.assertFalse(k.only("A"))
        k._release("B")
        k._press("SHIFT")
        self.assertFalse(k.only("A"))
        self.assertFalse(k.only("SHIFT"))
        k._release("A")
        self.assertTrue(k.only("SHIFT"))


class TestKeypOnce(unittest.TestCase):
    def setUp(self):
        self.k = KeyPressed()

    def test_once_is_edge_not_level(self):
        k = self.k
        k._press("R")
        self.assertTrue(k.once("R"))
        self.assertFalse(k.once("R"))
        self.assertTrue(k("R"))
        k._release("R")
        k._press("R")
        self.assertTrue(k.once("R"))

    def test_once_bare_ignores_modified_press(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        self.assertFalse(k.once("R"))
        k._release("CTRL")
        # R still down — must not fire as a new bare press
        self.assertFalse(k.once("R"))
        self.assertTrue(k("R"))

    def test_once_not_polled_during_chord_still_consumed(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        k._release("CTRL")
        self.assertFalse(k.once("R"))

    def test_once_chord_either_order(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        self.assertTrue(k.once("CTRL+R"))
        self.assertFalse(k.once("CTRL+R"))
        k._release("R")
        k._release("CTRL")

        k._press("R")
        k._press("CTRL")
        self.assertTrue(k.once("CTRL+R"))

    def test_held_once(self):
        k = self.k
        k._press("CTRL")
        k._press("LEFT")
        self.assertFalse(k.once("LEFT"))
        self.assertTrue(k.held.once("LEFT"))
        self.assertFalse(k.held.once("LEFT"))
        self.assertTrue(k.held("LEFT"))

    def test_once_with_shift_held(self):
        # PD6: Shift held, then SPACE: the jump fires once; pressing Shift
        # under a held key is not a new press either.
        k = self.k
        k._press("SHIFT")
        k._press("SPACE")
        self.assertTrue(k.once("SPACE"))
        self.assertFalse(k.once("SPACE"))
        k._release("SPACE")
        k._release("SHIFT")
        k._press("RIGHT")
        self.assertTrue(k.once("RIGHT"))
        k._press("SHIFT")
        self.assertFalse(k.once("RIGHT"))
        k._release("SHIFT")
        self.assertFalse(k.once("RIGHT"))

    def test_held_contains(self):
        k = self.k
        k._press("CTRL")
        k._press("LEFT")
        self.assertFalse("LEFT" in k)
        self.assertTrue("LEFT" in k.held)

    def test_once_same_poll_press_release(self):
        k = self.k
        k._press("R")
        k._release("R")
        self.assertFalse(k("R"))
        self.assertTrue(k.once("R"))
        self.assertFalse(k.once("R"))

    def test_once_same_poll_chord(self):
        k = self.k
        k._press("CTRL")
        k._press("R")
        k._release("R")
        k._release("CTRL")
        self.assertFalse(k("CTRL+R"))
        self.assertTrue(k.once("CTRL+R"))
        self.assertFalse(k.once("CTRL+R"))
        self.assertFalse(k.once("R"))

    def test_held_once_same_poll_play_key_released(self):
        k = self.k
        k._press("SHIFT")
        k._press("LEFT")
        k._release("LEFT")
        self.assertFalse(k.held("LEFT"))
        self.assertTrue(k.held.once("LEFT"))
        self.assertFalse(k.held.once("LEFT"))
        self.assertFalse(k.once("LEFT"))

    def test_seed_held_does_not_fire_once(self):
        k = self.k
        k._seed_held(["LEFT"])
        self.assertTrue(k("LEFT"))
        self.assertFalse(k.once("LEFT"))
        self.assertFalse(k.held.once("LEFT"))

    def test_once_same_poll_press_release_press_collapses(self):
        k = self.k
        k._press("R")
        k._release("R")
        k._press("R")
        self.assertTrue(k.once("R"))
        self.assertFalse(k.once("R"))

    def test_once_same_poll_then_next_press_fires_again(self):
        k = self.k
        k._press("R")
        k._release("R")
        self.assertTrue(k.once("R"))
        k._press("R")
        self.assertTrue(k.once("R"))
        self.assertFalse(k.once("R"))


class TestOnceIsFrameScoped(unittest.TestCase):
    """Bug PM3: ``once`` is True only in the frame of the press (Guia #entrada-teclado).

    An unread rising edge waited for its first ``once`` reader, however late:
    ``if pronto and keyp.once("SPACE")`` fired for a SPACE pressed seconds
    before ``pronto`` turned True. SC1 dropped edges at an act change only.
    The end of each frame body (``_expire_edges``, after every reader) now
    drops every unread edge, and ``once`` needs a pending edge even while the keys
    are held, so a late first read of a held key or chord is False too.
    """

    def setUp(self):
        self.k = KeyPressed()

    def test_tap_read_in_a_later_frame_is_false(self):
        k = self.k
        k._press("SPACE")
        k._release("SPACE")
        k._expire_edges()
        self.assertFalse(k.once("SPACE"))

    def test_held_key_first_read_in_a_later_frame_is_false(self):
        k = self.k
        k._press("SPACE")
        k._expire_edges()
        self.assertTrue(k("SPACE"))
        self.assertFalse(k.once("SPACE"))
        self.assertFalse(k.held.once("SPACE"))
        k._release("SPACE")
        k._press("SPACE")
        self.assertTrue(k.once("SPACE"))

    def test_held_chord_first_read_in_a_later_frame_is_false(self):
        k = self.k
        k._press("CTRL")
        k._press("S")
        k._expire_edges()
        self.assertFalse(k.once("CTRL+S"))
        self.assertFalse(k.once("CTRL"))

    def test_same_frame_reads_still_work(self):
        k = self.k
        k._expire_edges()
        k._press("CTRL")
        k._press("S")
        k._release("S")
        k._release("CTRL")
        self.assertTrue(k.once("CTRL+S"))
        k._expire_edges()
        k._press("R")
        self.assertTrue(k.once("R"))
        k._expire_edges()
        self.assertFalse(k.once("R"))      # still held: no new press


class TestOnceIsFrameScopedInFrames(unittest.TestCase):
    """PM3 end to end: real frames, input through the window handler."""

    SRC = (
        "from scena import *\n"
        "init(width=400, height=300)\n"
        "reads = []\n"
        "st.ask = False\n"
        "def update(dt):\n"
        "    if st.ask:\n"
        "        reads.append(keyp.once('SPACE'))\n"
        "run()\n"
    )

    def _run(self, steps):
        import tempfile
        from program_support import ProgramRun
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "once_prog.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.SRC)
            with ProgramRun(path) as run:
                run.play(steps)
                return list(run.ns["reads"])

    def test_a_press_nobody_read_does_not_fire_later(self):
        reads = self._run([("wait", 2), ("key", "SPACE", 2), ("wait", 30),
                           ("set_cell", "st.ask", True), ("wait", 3)])
        self.assertEqual(reads, [False, False, False, False])

    def test_a_press_read_in_its_frame_fires_once(self):
        reads = self._run([("set_cell", "st.ask", True), ("key", "SPACE", 3), ("wait", 1)])
        self.assertEqual(reads.count(True), 1)
        self.assertTrue(reads[1])           # the frame the press arrived in


class TestScriptKeyFilter(unittest.TestCase):
    def test_play_key_suppressed_with_ctrl(self):
        k = KeyPressed()
        k._press("CTRL")
        k._press("R")
        self.assertFalse(k._delivers_script_key("R"))
        self.assertEqual(k._script_key_name("R"), "R")

    def test_play_key_delivered_bare(self):
        k = KeyPressed()
        k._press("R")
        self.assertTrue(k._delivers_script_key("R"))

    def test_modifier_uses_family_name(self):
        k = KeyPressed()
        self.assertEqual(k._script_key_name("LEFT_SHIFT"), "SHIFT")
        self.assertEqual(k._script_key_name("RIGHT_CTRL"), "CTRL")
        self.assertEqual(k._script_key_name("LEFT_CMD"), "CMD")
        k._press("LEFT_SHIFT")
        self.assertTrue(k._delivers_script_key("LEFT_SHIFT"))



class TestKeySpecTypes(unittest.TestCase):
    """A1 (Testing Design): ``keyp(["A"])`` leaked Python's ``unhashable type``.

    The spec cache lookup ran before the type check. Every query path must
    answer any non-string with Scena's ``TypeError`` naming the fix.
    """

    BAD = (["A"], {"A": 1}, {"A"}, bytearray(b"A"), 5, None, ("A",), 1.5, b"A")

    def test_non_string_spec_is_scena_type_error_on_every_path(self):
        from scena import keyp
        for fn in (keyp, keyp.once, keyp.only, keyp.held, keyp.held.once):
            for bad in self.BAD:
                with self.subTest(fn=fn, bad=bad):
                    with self.assertRaises(TypeError) as ctx:
                        fn(bad)
                    msg = str(ctx.exception)
                    self.assertIn("key name string", msg)
                    self.assertNotIn("unhashable", msg)

    def test_membership_form_checks_type_too(self):
        from scena import keyp
        for bad in (["A"], {"A": 1}, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError) as ctx:
                    bad in keyp  # noqa: B015
                self.assertNotIn("unhashable", str(ctx.exception))


class TestOnceChordNeedsKeysDownTogether(unittest.TestCase):
    """Bug IN1: ``once("CMD+O")`` fired from a CMD tap and a later O tap.

    Unread press edges are remembered until a ``once`` reads them. The chord
    fallback used to combine edges from different moments, so keys that were
    never down together made a chord (an editor's Cmd+O opened its dialog
    when the author pressed Cmd alone, because O had been typed earlier).
    """

    def setUp(self):
        self.k = KeyPressed()

    def tap(self, *names):
        for name in names:
            self.k._press(name)
        for name in reversed(names):
            self.k._release(name)

    def test_modifier_tap_then_play_tap_is_not_a_chord(self):
        self.tap("CMD")
        self.tap("O")
        self.assertFalse(self.k.once("CMD+O"))

    def test_play_tap_then_modifier_tap_is_not_a_chord(self):
        self.tap("O")
        self.tap("CMD")
        self.assertFalse(self.k.once("CMD+O"))

    def test_play_tap_then_modifier_held_is_not_a_chord(self):
        self.tap("O")
        self.k._press("CMD")
        self.assertFalse(self.k.once("CMD+O"))

    def test_other_families_too(self):
        self.tap("SHIFT")
        self.tap("S")
        self.assertFalse(self.k.once("SHIFT+S"))
        self.tap("CTRL")
        self.tap("R")
        self.assertFalse(self.k.once("CTRL+R"))

    def test_quick_tap_under_a_held_modifier_still_fires(self):
        k = self.k
        k._press("CMD")
        self.assertTrue(k.once("CMD"))   # the modifier's own edge is read
        k._press("S")
        k._release("S")                  # S up again before the next read
        self.assertTrue(k.once("CMD+S"))
        self.assertFalse(k.once("CMD+S"))

    def test_chord_tapped_together_still_fires_later(self):
        self.tap("CMD", "S")
        self.assertTrue(self.k.once("CMD+S"))
        self.assertFalse(self.k.once("S"))

    def test_left_and_right_modifier_taps_under_a_held_key_are_one_read(self):
        # Deep-tier Hypothesis find: O held, Cmd-L tapped, Cmd-R tapped, all
        # in one poll. Two pending presses completed CMD+O; one read must
        # consume both, as two taps of the same Cmd key collapse into one.
        k = self.k
        k._press("O")
        self.tap("LEFT_CMD")
        self.tap("RIGHT_CMD")
        self.assertTrue(k.once("CMD+O"))
        self.assertFalse(k.once("CMD+O"))

    def test_unread_tap_does_not_fire_after_the_wrong_modifier(self):
        k = self.k
        self.tap("CMD", "S")
        self.assertFalse(k.once("SHIFT+S"))
        self.assertTrue(k.once("CMD+S"))


_KEYS = ("LEFT_CMD", "RIGHT_CMD", "LEFT_SHIFT", "LEFT_CTRL", "S", "O")
_SPECS = ("CMD+S", "CMD+O", "SHIFT+S", "CTRL+O", "CMD+SHIFT+S", "S", "O")
_ORACLE_FAMILIES = {
    "CMD": {"LEFT_CMD", "RIGHT_CMD"},
    "SHIFT": {"LEFT_SHIFT"},
    "CTRL": {"LEFT_CTRL"},
}


def _down_together(spec, down) -> bool:
    """Independent model: the spec's keys are down and no other modifier is
    (a bare key, no modifier listed, ignores Shift: PD6)."""
    parts = spec.split("+")
    families = {p for p in parts if p in _ORACLE_FAMILIES}
    for part in parts:
        if part in _ORACLE_FAMILIES:
            if not (_ORACLE_FAMILIES[part] & down):
                return False
        elif part not in down:
            return False
    extra = {f for f, names in _ORACLE_FAMILIES.items() if names & down} - families
    if not families:
        extra.discard("SHIFT")
    return not extra


_STEP = hst.one_of(
    # A tap: press the keys in order, release in reverse (one poll apart or not).
    hst.tuples(hst.just("tap"), hst.lists(hst.sampled_from(_KEYS), min_size=1,
                                          max_size=2, unique=True)),
    hst.tuples(hst.just("toggle"), hst.sampled_from(_KEYS)),
    hst.tuples(hst.just("read"), hst.sampled_from(_SPECS)),
    hst.tuples(hst.just("frame"), hst.none()),
)


class TestOnceChordProperty(unittest.TestCase):
    """Whole class of IN1 and PM3: ``once(spec)`` never fires unless the spec's
    keys were down together (with no extra modifier) at some moment since that
    spec last fired **and in the current frame**. Random press / release /
    read / frame-boundary sequences."""

    @given(steps=hst.lists(_STEP, max_size=60))
    def test_once_never_fires_for_keys_not_down_together(self, steps):
        k = KeyPressed()
        down = set()
        seen = {spec: False for spec in _SPECS}   # satisfied since last fire
        def toggle(name):
            if name in down:
                down.discard(name)
                k._release(name)
            else:
                down.add(name)
                k._press(name)
            for spec in _SPECS:
                if _down_together(spec, down):
                    seen[spec] = True

        for kind, arg in steps:
            if kind == "tap":
                fresh = [name for name in arg if name not in down]
                for name in fresh:
                    toggle(name)
                for name in reversed(fresh):
                    toggle(name)
            elif kind == "toggle":
                toggle(arg)
            elif kind == "frame":
                # PM3: a frame boundary forgets what was not read in it.
                k._expire_edges()
                seen = {spec: False for spec in _SPECS}
            elif k.once(arg):
                self.assertTrue(
                    seen[arg],
                    f"once({arg!r}) fired but its keys were never down "
                    f"together; steps={steps}",
                )
                seen[arg] = _down_together(arg, down)


class TestOnceChordCanaries(unittest.TestCase):
    """The property catches a chord pieced from separate taps (SCENA_CANARIES)."""

    def test_chord_from_separate_taps_is_caught(self):
        from diff_support import assert_catches

        def pieced(self, spec, *, held):
            # The IN1 bug: merge every unread edge, whenever it was pressed.
            merged = dict(self._pressed_keys)
            merged.update(dict.fromkeys(self._pending_edges, True))
            if self._spec_names_in(spec, self._pending_edges) and self._matches(
                spec, held=held, keys=merged
            ):
                return [frozenset(merged)]
            return []

        assert_catches(
            self,
            "test_keyp.TestOnceChordProperty.test_once_never_fires_for_keys_not_down_together",
            [(KeyPressed, "_pending_rises", pieced)],
            "once() chord pieced from separate taps",
        )


if __name__ == "__main__":
    unittest.main()
