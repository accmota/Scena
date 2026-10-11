"""Warning-site recorder (tests/warning_sites.py): install it in every process.

Python imports ``sitecustomize`` at startup when this folder is on PYTHONPATH.
With ``SCENA_WARNSITE_LOG`` set to a folder, ``warnings.warn`` is wrapped:
each call made from a ``scena`` module is recorded as ``module:qualname``
(through ``report_author_warning`` to its caller), and the set is written to
``<folder>/<pid>.txt`` at exit with the test module that ran. The wrapper
adds a frame, so tests that check a warning's ``stacklevel`` fail under it:
measurement only, never in a tier. It does not import ``scena``.
"""
import os

if os.environ.get("SCENA_WARNSITE_LOG"):
    import atexit
    import sys
    import warnings

    _out = os.environ["SCENA_WARNSITE_LOG"]
    _seen = set()
    _orig = warnings.warn
    _SEP = os.sep + "scena" + os.sep
    _FUNNELS = ("report_author_warning", "_warn_asset")

    def _key(f):
        mod = f.f_code.co_filename.rsplit(_SEP, 1)[1][:-3].replace(os.sep, ".")
        return f"{mod}:{f.f_code.co_qualname}"

    def warn(message, *a, **k):
        try:
            f = sys._getframe(1)
            if _SEP in f.f_code.co_filename and os.sep + "tests" + os.sep not in f.f_code.co_filename:
                if f.f_code.co_name == "report_author_warning":
                    f = f.f_back
                if f is not None:
                    _seen.add(_key(f))
        except Exception:
            pass
        return _orig(message, *a, **k)

    warnings.warn = warn

    def _dump():
        if _seen:
            mod = " ".join(x for x in sys.argv if x.startswith(("tests.", "scena_editor")))
            with open(os.path.join(_out, f"{os.getpid()}.txt"), "w", encoding="utf-8") as fh:
                for s in sorted(_seen):
                    fh.write(f"{s}\t{mod}\n")

    atexit.register(_dump)
