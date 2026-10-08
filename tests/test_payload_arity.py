"""One rule for what Scena passes an author hook: ``validate.payload_arity``.

Scena passes its payload (the Button, the shape, ``me, other, info``, the
owner, ``dt``, the new value) only to parameters **with no default**.

Bug class guarded here: *a default-valued parameter receives a payload the
author never asked for*. ``lambda tool=tool: choose(tool)`` got the Button as
``tool``; ``app.save(then=None)`` got it as ``then``; ``jump(height=10)`` got
it as ``height``. Three counters (``call_truncated``, ``process._argcount``,
``events._callback_npos``) each counted defaulted parameters; every hook kind
is checked below so a fourth counter cannot drift. See Shapes Design,
Decorators, and Testing Design (PH5).

Run headless:

    python -m unittest tests.test_payload_arity -v
"""

import functools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Button, Circle, Entity
from scena.events import cleanup_global_event_system, on_change
from scena.state import Attribute, get_scena_system
from scena.validate import call_truncated, payload_arity
from tests.test_process import ProcessTestCase, _frame


def _plain(a, b=None):
    return a, b


class _Thing:
    def method(self, a, b=None):
        return a, b

    def no_args(self, then=None):
        return then


class _CallableObj:
    def __call__(self, a, b=1):
        return a


class TestPayloadArity(unittest.TestCase):
    def test_counts_only_parameters_without_default(self):
        cases = [
            (lambda: None, 0),
            (lambda x: None, 1),
            (lambda tool="pen": None, 0),
            (lambda a, b=1: None, 1),
            (lambda a, *, k: None, 1),
            (lambda *a: None, None),
            (lambda a, *rest: None, None),
            (_plain, 1),
            (_Thing().method, 1),
            (_Thing.method, 2),
            (_Thing().no_args, 0),
            (functools.partial(_plain, 1), 0),
            (functools.partial(lambda a, b: None, 1), 1),
            (_CallableObj(), 1),
            ([].clear, 0),
            ([].append, 1),
            (print, None),
        ]
        for fn, want in cases:
            with self.subTest(fn=fn):
                self.assertEqual(payload_arity(fn), want)

    def test_unreadable_signature_takes_everything(self):
        self.assertIsNone(payload_arity(max))

    def test_slow_path_cached_on_the_object_not_on_classes(self):
        obj = _CallableObj()
        self.assertEqual(payload_arity(obj), 1)
        self.assertEqual(obj.__dict__["_scena_payload_arity"], 1)
        p = functools.partial(_plain, 1)
        payload_arity(p)
        self.assertEqual(p.__dict__["_scena_payload_arity"], 0)

        class Spawn:
            def __init__(self, where):
                pass

        class SpawnLater(Spawn):
            def __init__(self):
                pass

        self.assertEqual(payload_arity(Spawn), 1)
        self.assertNotIn("_scena_payload_arity", vars(Spawn))
        self.assertEqual(payload_arity(SpawnLater), 0)

    def test_nothing_cached_on_functions(self):
        def f(a, b=None):
            pass

        bound = f.__get__(object(), object)
        self.assertEqual(payload_arity(bound), 0)
        self.assertEqual(payload_arity(f), 1)
        self.assertNotIn("_scena_payload_arity", f.__dict__)


class TestCallTruncated(unittest.TestCase):
    def test_default_parameters_get_nothing(self):
        got = []
        call_truncated(lambda tool="pen": got.append(tool), "BUTTON")
        call_truncated(lambda a, b="own": got.append((a, b)), 1, 2)
        call_truncated(functools.partial(lambda t, x="own": got.append((t, x)), "brush"), "BUTTON")
        self.assertEqual(got, ["pen", (1, "own"), ("brush", "own")])

    def test_required_and_varargs_get_the_payload(self):
        got = []
        call_truncated(lambda b: got.append(b), "BUTTON", "extra")
        call_truncated(lambda *a: got.append(a), 1, 2)
        self.assertEqual(got, ["BUTTON", (1, 2)])


class TestButtonClick(unittest.TestCase):
    def setUp(self):
        self._owned = []

    def tearDown(self):
        for b in self._owned:
            b.destroy()

    def _click(self, on_click):
        b = Button(label="x", on_click=on_click)
        self._owned.append(b)
        b._on_mouse_click(0, 0, 0)
        return b

    def test_loop_variable_captured_by_default(self):
        got = []
        for tool in ("select", "rect"):
            self._click(lambda tool=tool: got.append(tool))
        self.assertEqual(got, ["select", "rect"])

    def test_method_with_optional_parameter(self):
        got = []

        class App:
            def save(self, then=None):
                got.append(then)

        self._click(App().save)
        self.assertEqual(got, [None])

    def test_partial(self):
        got = []
        self._click(functools.partial(got.append, "tool"))
        self.assertEqual(got, ["tool"])

    def test_required_parameter_receives_the_button(self):
        got = []
        b = self._click(lambda btn: got.append(btn))
        self.assertEqual(got, [b])


class TestShapeClick(unittest.TestCase):
    def test_shape_click_handler_with_default(self):
        from scena.orchestration import ShapeInteractionManager

        got = []
        c = Circle(center=(70_000, 70_000), radius=5)
        try:
            c.on_click = lambda which="mine": got.append(which)
            ShapeInteractionManager._call(c.on_click, c)
            c.on_click = lambda shape: got.append(shape)
            ShapeInteractionManager._call(c.on_click, c)
        finally:
            c.destroy()
        self.assertEqual(got, ["mine", c])


class TestTimersAndUpdate(ProcessTestCase):
    def test_after_with_default_gets_no_owner(self):
        c = self.track(Circle())
        got = []
        c.after(0.1, lambda who="nobody": got.append(who))
        c.after(0.1, lambda who: got.append(who))
        _frame(0.1)
        self.assertEqual(got, ["nobody", c])

    def test_on_update_function_with_default_dt(self):
        e = self.track(Entity())
        got = []
        e.on_update = lambda me, dt=0.5: got.append((me, dt))
        _frame(0.1)
        self.assertEqual(got, [(e, 0.5)])


class TestOnChange(unittest.TestCase):
    def tearDown(self):
        ss = get_scena_system()
        if ss is not None and ss.update_manager.deferring:
            ss.end_frame_batch()
        cleanup_global_event_system()

    def test_default_parameter_gets_no_value(self):
        a = Attribute(1)
        got = []

        @on_change(a)
        def redraw(value="own"):
            got.append(value)

        @on_change(a)
        def show(value):
            got.append(value)

        a.value = 2
        get_scena_system().flush()
        self.assertEqual(sorted(map(str, got)), ["2", "own"])


if __name__ == "__main__":
    unittest.main()
