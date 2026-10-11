"""
Dependency logic tests for circular reference detection and ownership chains.

Run headless (no window) with either:

    python -m unittest tests.test_dependency_logic -v
    python tests/test_dependency_logic.py
"""

import os
import sys
import unittest

# Ensure the repo root is importable regardless of how the test is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.state import State, CircularReferenceError, DependencyState
from scena.shapes import Point, Circle, Line
from scena.scenamath import Vec2

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def get_diameter(circle: Circle) -> float:
    return circle.radius * 2


# ---------------------------------------------------------------------------
# Circular reference examples
# ---------------------------------------------------------------------------
class TestCircularReferenceExamples(unittest.TestCase):

    def test_example_1_circular_reference(self):
        """
        a1, a2 are parts of A
        b1, b2 are parts of B
        c1, c2 are parts of C

        a2 ← B ← c1    (a2 depends on B, B depends on c1)
        C ← A          (C depends on A) — should detect cycle via ownership
        """
        A = Circle(center=(100, 100), radius=50)
        B = Circle(center=(200, 200), radius=30)
        C = Circle(center=(300, 300), radius=40)

        a2 = A["radius"]
        c1 = C.center

        a2 @= lambda: get_diameter(B)
        B @= lambda: Circle(center=c1, radius=10)

        # Cycle: C → A → a2 → B → c1 → C
        with self.assertRaises(CircularReferenceError):
            C @= lambda: A

    def test_example_2_no_circular_reference(self):
        """
        a1, a2 are parts of A
        b1, b2 are parts of B

        a2 ← B         (a2 depends on B)
        B ← a1         (B depends on a1)  — no cycle (a1 and a2 independent)
        """
        A = Circle(center=(100, 100), radius=50)
        B = Circle(center=(200, 200), radius=30)

        a1 = A.center
        a2 = A["radius"]

        a2 @= lambda: get_diameter(B)
        B @= lambda: Circle(center=a1, radius=10)


# ---------------------------------------------------------------------------
# Owner with / without link
# ---------------------------------------------------------------------------
class TestOwnerWithLinkVsNoLink(unittest.TestCase):

    def test_parts_independent_when_owner_has_no_link(self):
        A = Circle(center=(100, 100), radius=50)
        B = Circle(center=(200, 200), radius=30)

        a1 = A.center
        a2 = A["radius"]
        b1 = B.center

        a2 @= lambda: b1.x
        b1 @= lambda: a1

    def test_parts_dependent_when_owner_linked(self):
        A = Circle(center=(100, 100), radius=50)
        B = Circle(center=(200, 200), radius=30)

        a1 = A.center
        b1 = B.center

        A @= lambda: B

        with self.assertRaises(CircularReferenceError):
            b1 @= lambda: a1

    def test_parts_dependent_when_owner_linked_inverted_order(self):
        A = Circle(center=(100, 100), radius=50)
        B = Circle(center=(200, 200), radius=30)

        a1 = A.center
        b1 = B.center

        b1 @= lambda: a1

        with self.assertRaises(CircularReferenceError):
            A @= lambda: B


# ---------------------------------------------------------------------------
# Mixed object / state circular references
# ---------------------------------------------------------------------------
class TestCircularReferenceDetection(unittest.TestCase):

    def test_valid_links_then_detect_cycles(self):
        st = State()
        c1 = Circle(center=(100, 100), radius=50)
        c2 = Circle(center=(200, 200), radius=30)
        p1 = Point(150, 150)
        v = Vec2(10, 10)
        st.create('varA', initial=0)

        c2.center @= lambda: p1 + v
        p1["x"] @= lambda: st.varA
        c1 @= lambda: c2

        # varA already feeds c1 via p1.x → … → c1; linking varA to c1.center.x cycles.
        # Use assign_formula: `st["varA"] @=` also goes through State.__setattr__.
        with self.assertRaises(CircularReferenceError):
            st._resolve_cell("varA")._assign_formula(lambda: c1.center.x * 2)


# ---------------------------------------------------------------------------
# Complex chains
# ---------------------------------------------------------------------------
class TestComplexCircularReference(unittest.TestCase):

    def test_chain_of_dependencies(self):
        c1 = Circle(center=(100, 100), radius=50)
        c2 = Circle(center=(200, 200), radius=30)
        p1 = Point(150, 150)
        p2 = Point(250, 250)

        c1 @= lambda: c2
        c2.center @= lambda: p1
        p1 @= lambda: p2

        with self.assertRaises(CircularReferenceError):
            p2 @= lambda: c1


# ---------------------------------------------------------------------------
# Ownership chains
# ---------------------------------------------------------------------------
class TestOwnershipChainCircularReference(unittest.TestCase):

    def test_circular_through_ownership(self):
        parent = Point(100, 100)
        child1 = Point(150, 150, owner=parent)
        child2 = Point(200, 200, owner=parent)

        child1 @= lambda: child2

        with self.assertRaises(CircularReferenceError):
            child2 @= lambda: parent


# ---------------------------------------------------------------------------
# Dependency state along ownership chains
# ---------------------------------------------------------------------------
class TestLineOwnershipChainDependencyStates(unittest.TestCase):

    def test_line_link_and_unlink_states(self):
        line = Line(p1=(10, 20), p2=(30, 40))

        self.assertEqual(line._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.p1._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.p2._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.center._dependency_state, DependencyState.DEPENDENT_DOWNWARD)

        src = Line(p1=(100, 200), p2=(300, 400))
        line @= src

        self.assertEqual(line._dependency_state, DependencyState.LINKED_OUTWARD)
        self.assertEqual(line.p1._dependency_state, DependencyState.DEPENDENT_UPWARD)
        self.assertEqual(line.p2._dependency_state, DependencyState.DEPENDENT_UPWARD)
        self.assertEqual(line.center._dependency_state, DependencyState.DEPENDENT_UPWARD)

        line.unlink()

        self.assertEqual(line._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.p1._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.p2._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.center._dependency_state, DependencyState.DEPENDENT_DOWNWARD)


class TestCircleOwnershipChainDependencyStates(unittest.TestCase):

    def test_circle_link_and_unlink_states(self):
        circle = Circle(center=(50, 60), radius=25)

        self.assertEqual(circle._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(circle.center._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertIsInstance(circle.radius, float)

        src = Circle(center=(150, 160), radius=75)
        circle @= src

        self.assertEqual(circle._dependency_state, DependencyState.LINKED_OUTWARD)
        self.assertEqual(circle.center._dependency_state, DependencyState.DEPENDENT_UPWARD)
        self.assertIsInstance(circle.radius, float)

        circle.unlink()

        self.assertEqual(circle._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(circle.center._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertIsInstance(circle.radius, float)


class TestPartialOwnershipChainLink(unittest.TestCase):

    def test_partial_chain_states(self):
        st = State()
        st.create('x1', initial=10)
        p = Point(10, 20)
        line = Line(p1=lambda: p, p2=(lambda: st.x1, 40))

        self.assertEqual(line._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(line.p1._dependency_state, DependencyState.LINKED_OUTWARD)
        self.assertEqual(line.p2._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertTrue(line.p2["x"].is_linked)
        self.assertFalse(line.p2["y"].is_linked)
        self.assertEqual(line.center._dependency_state, DependencyState.DEPENDENT_DOWNWARD)


class TestCircularReferenceComplexChains(unittest.TestCase):

    def test_line_to_line_cycle(self):
        # Use plain tuples so construction does not install descendant formulas
        line1 = Line(p1=(10, 20), p2=(30, 40))
        line2 = Line(p1=(50, 60), p2=(70, 80))

        line1 @= line2
        with self.assertRaises(CircularReferenceError):
            line2 @= line1

    def test_partial_ownership_cycle(self):
        line1 = Line(p1=(10, 20), p2=(30, 40))
        line2 = Line(p1=(50, 60), p2=(70, 80))

        line1.p1 @= line2.p1
        with self.assertRaises(CircularReferenceError):
            line2.p1 @= line1.p1


if __name__ == "__main__":
    unittest.main(verbosity=2)
