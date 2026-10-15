"""Directory scans for tests that read source, docs, scripts or media files.

Not a test module (no ``test_`` prefix). Every scan in ``tests/`` goes through
``iter_files`` (guard: ``test_platform_portability.TestSourceScansUseTheHelper``).

Why: a tree copied from macOS to a volume without extended attributes holds an
AppleDouble ``._<name>`` file next to every real file. ``._foo.py`` ends in
``.py`` and ``._Foo Design.md`` ends in ``.md``, so a bare ``os.listdir`` +
``endswith`` (or ``Path.glob`` / ``rglob``, which match dot files) hands binary
metadata to ``open(..., encoding="utf-8")``, ``ast.parse`` or an audio decoder.
"""
from __future__ import annotations

import os
from typing import Iterable, List

JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


def is_junk(name: str) -> bool:
    """OS metadata that is not a real file: AppleDouble ``._x``, ``.DS_Store``,
    ``Thumbs.db``, ``desktop.ini``."""
    return name.startswith("._") or name in JUNK_NAMES


def iter_files(root: str, *suffixes: str, recursive: bool = False,
               skip_dirs: Iterable[str] = ()) -> List[str]:
    """Sorted paths of the real files under ``root`` whose lower-case name ends
    in one of ``suffixes`` (all files when none are given).

    ``recursive`` walks sub-directories, pruning ``skip_dirs`` (names), hidden
    directories and ``__pycache__``.
    """
    root = os.fspath(root)
    ends = tuple(s.lower() for s in suffixes)
    skip = set(skip_dirs) | {"__pycache__"}
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if recursive:
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        else:
            dirnames[:] = []
        for name in filenames:
            if is_junk(name) or (ends and not name.lower().endswith(ends)):
                continue
            out.append(os.path.join(dirpath, name))
    return sorted(out, key=path_key)


def iter_entries(root: str) -> List[str]:
    """Sorted names of the real entries directly in ``root``, files and
    folders (OS metadata skipped): a folder mirrored entry by entry (the laws
    equations' script twins run next to the example's art)."""
    with os.scandir(os.fspath(root)) as it:
        return sorted(e.name for e in it if not is_junk(e.name))


def path_key(path: str, sep: str = os.sep) -> str:
    """Sort key for paths: ``path`` in ``/`` form. ``"\\"`` sorts after
    letters and digits, ``"/"`` before them, so a plain sort puts
    ``sub/x.py`` and ``subA.py`` in a different order on Windows."""
    return path.replace(sep, "/")
