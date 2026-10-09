"""Sentinel hook (tests/geom_sentinel.py): install it in every process.

Python imports ``sitecustomize`` at startup when this folder is on PYTHONPATH
(``python tests/run_tiers.py <tier> --sentinel`` puts it there). With
``SCENA_SENTINEL`` set (``log`` or ``1``) the engine's entry points are
wrapped right after ``scena`` is first imported; without it this file does
nothing.

It must not import ``scena`` here: site runs before ``__main__`` exists, and
an import of the engine at that point hangs. A one-shot import finder waits
for the test's own ``import scena`` instead.
"""
import os

if os.environ.get("SCENA_SENTINEL"):
    import importlib.abc
    import importlib.util
    import sys

    _here = os.path.dirname(os.path.abspath(__file__))
    _tests = os.path.dirname(_here)

    class _AfterScena(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != "scena":
                return None
            sys.meta_path.remove(self)
            spec = importlib.util.find_spec(name)
            if spec is None or spec.loader is None:
                return spec
            run = spec.loader.exec_module

            def exec_module(module):
                run(module)
                if _tests not in sys.path:
                    sys.path.insert(0, _tests)
                import geom_sentinel
                geom_sentinel.install()
            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _AfterScena())
