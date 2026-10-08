"""Mutation hook (tests/mutation_run.py): mutate one engine module at import.

Python imports ``sitecustomize`` at startup when this folder is on PYTHONPATH.
With ``SCENA_MUTANT=<module>:<site index>`` set, the named module is compiled
from a mutated AST (no bytecode cache); every child process inherits it.
Without the variable this file does nothing.
"""
import os

_spec = os.environ.get("SCENA_MUTANT")
if _spec:
    import sys
    sys.dont_write_bytecode = True
    _here = os.path.dirname(os.path.abspath(__file__))
    _tests = os.path.dirname(_here)
    if _tests not in sys.path:
        sys.path.insert(0, _tests)
    import mutation_ops
    mutation_ops.install(_spec)
