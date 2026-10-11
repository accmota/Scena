"""
Test the enum-based dependency tracking system.

Run headless (no window) with either:

    python -m unittest tests.test_simplified_dependency -v
    python tests/test_simplified_dependency.py
"""

import os
import sys
import unittest

# Ensure the repo root is importable regardless of how the test is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.state import State, CircularReferenceError, Attribute, DependencyState


class TestDependencyStateChanges(unittest.TestCase):
    """Dependency state changes correctly when links are assigned/removed."""

    def test_dependency_state_changes(self):
        st = State()
        st.create('varA', initial=0)

        A = st._resolve_cell("varA")  # Container A
        a1 = Attribute(10, owner=A, attr_name="a1")
        a2 = Attribute(20, owner=A, attr_name="a2")

        # Initially, A should depend on parts (not owners)
        self.assertEqual(A._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(a1._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(a2._dependency_state, DependencyState.DEPENDENT_DOWNWARD)

        # Assign a formula to A (must name a Container source)
        src = Attribute(100)
        A @= lambda: src

        # Now A should be LINKED_OUTWARD, and a1, a2 should be DEPENDENT_UPWARD
        self.assertEqual(A._dependency_state, DependencyState.LINKED_OUTWARD)
        self.assertEqual(a1._dependency_state, DependencyState.DEPENDENT_UPWARD)
        self.assertEqual(a2._dependency_state, DependencyState.DEPENDENT_UPWARD)

        # Remove the link
        A.unlink()

        # Now all should be DEPENDENT_DOWNWARD again
        self.assertEqual(A._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(a1._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertEqual(a2._dependency_state, DependencyState.DEPENDENT_DOWNWARD)


class TestCircularReferenceDetection(unittest.TestCase):
    """Circular reference detection works with the enum system."""

    def test_circular_reference_detection(self):
        st = State()
        st.create('varA', initial=0)
        st.create('varB', initial=0)

        A = st._resolve_cell("varA")
        B = st._resolve_cell("varB")
        # Create a circular reference: A @= B and B @= A
        A @= lambda: B

        with self.assertRaises(CircularReferenceError):
            B @= lambda: A


if __name__ == "__main__":
    unittest.main()
