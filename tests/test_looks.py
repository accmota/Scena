"""Redirect to tests.test_visuals (look API renamed to visual)."""
from tests.test_visuals import *  # noqa: F401,F403
from tests.test_visuals import TestVisuals as TestLooks  # noqa: F401

if __name__ == "__main__":
    import unittest
    unittest.main()
