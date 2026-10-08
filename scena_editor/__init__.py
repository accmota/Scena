"""Scena level editor — a companion app, not part of the framework.

Run ``python -m scena_editor [level.json]``. It places geometry (rects,
ellipses, circles, lines, polygons, paths, points, images) with names and
groups and saves a level file that games read with ``scena.Level``.

Boundary: nothing in ``scena/`` imports this package. The editor uses the
public Scena API; every Scena private it needs goes through ``_engine.py``.
Pure modules (``doc``, ``undo``, ``geometry``, ``tools``, ``i18n``) never
create Graphics and are tested headless. See
``design/Editor Design.md``.
"""
