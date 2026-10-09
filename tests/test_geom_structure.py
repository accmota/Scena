"""Structural guards of the geometry campaign (H7): drift candidates become rules.

Each guard turns a place where two copies of one rule could disagree into a
check, so a new kind, model or verb that breaks it fails here instead of in
an author's scene:

* ``TestPoseVerbsNotifyOnce`` — a pose verb that writes several parts
  notifies the shape once (``update()`` at most once on a slow-path subject
  with every Derivate live). Measured, not parsed: the verbs batch through a
  decorator, ``_*_batched`` helpers or gated fast paths.
* ``TestModelAdoptedBeforeWrites`` — every multi-model ``_takein_impl`` adopts
  the source's model (``_adopt_model_of``) before it writes a Defining part.
* ``TestDefiningTablesAgree`` — ``_LINE_MODEL_DEFINING`` / ``_RECT_MODEL_DEFINING``
  / ``_SQUARE_MODEL_DEFINING``, ``_defining_names_for`` and the parts each
  constructor and each cross-model copy marks Defining are one set.
* ``TestTimedVerbsGateLikeInstant`` — a timed verb refuses, at the call, every
  write its instant form refuses (GX4: the timed doors skipped the gate and the
  refusal came from a later tick). Known cells: ``geom_campaign_known.GATE_PARITY``.
* ``TestNoBareExceptInPoseVerbs`` — no bare ``except:`` / ``except Exception: pass``
  in a pose verb (the old ``Track._move_to``).
* ``TestRelationalVerbTable`` — Shapes Design's table "Pose verbs on a relational
  shape", ``geometry_support.CONTRACT_EXEMPT``, ``geom_shadow.CONSTRAINT_MAPS``
  and what the verbs do (``Line._gate_tangent`` included) agree, both ways.
* ``TestAllowlistsCarryReasons`` — every allowlist of the campaign has a reason.

No refactor without a bug: the six ways ``rotate_to`` reads the heading, the
fifteen "about the center?" tests and the copied ``_move_to`` blocks are not
merged for their own sake. The checks that stand in for a merge are the
sentinel's I-heading invariant, ``test_geom_probes.test_about_the_center_is_the_default_pivot``
and the influence matrix (H4).

    python tests/run_tiers.py focused test_geom_structure
"""
from __future__ import annotations

import ast
import fnmatch
import os
import re
import sys
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world  # noqa: E402

import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402
from scena.state import Container, LinkedAttributeError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _tree(mod):
    with open(os.path.join(ROOT, "scena", mod + ".py"), encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _calls(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.append(f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None))
    return out


class TestPoseVerbsNotifyOnce(unittest.TestCase):
    """At most one ``update()`` of the subject per verb (one consistent state)."""

    STEPS = ("move_by", "move_to", "rotate_by", "rotate_by about", "rotate_to", "scale_by",
             "scale_by about", "scale_to", "flip_x", "flip_y", "angle =")
    # (kind pattern, step) -> why two updates are acceptable. Under pull
    # reactivity no read happens between them, so only the cost is extra.
    ALLOWED = {
        ("Text top_*", "rotate_by"): "an anchored caption turns, then re-pins its anchor",
        ("Text top_*", "rotate_by about"): "same",
        ("Text top_*", "rotate_to"): "same",
        ("Text top_*", "scale_by"): "an anchored caption scales, then re-pins its anchor",
        ("Text top_*", "scale_by about"): "same",
        ("Text top_*", "scale_to"): "same",
        ("Track line point_point", "rotate_by about"): "the orbit moves the points, then turns the pose",
        ("Track line point_point", "scale_by about"): "the orbit moves the points, then scales the pose",
    }

    def _counts(self):
        out = {}
        with fresh_world() as w:
            for kind in sorted(A.K):
                for step in self.STEPS:
                    obj = w.track(A.build(kind))
                    if not S.STEP_BY_NAME[step][1](obj):
                        continue
                    obj._flag_pull_consumers()
                    A.W["all"](obj)
                    shadow = S.Shadow(obj, kind)
                    n = [0]
                    real = Container.update

                    def spy(self_, *a, o=obj, **kw):
                        if self_ is o:
                            n[0] += 1
                        return real(self_, *a, **kw)
                    with mock.patch.object(Container, "update", spy):
                        try:
                            S.STEP_BY_NAME[step][2](obj, shadow)
                        except LinkedAttributeError:
                            continue
                    out[(kind, step)] = n[0]
        return out

    def _allowed(self, kind, step):
        return any(fnmatch.fnmatch(kind, k) and s == step for k, s in self.ALLOWED)

    def test_one_update_per_verb(self):
        counts = self._counts()
        self.assertGreater(sum(1 for v in counts.values() if v == 1), 300, "vacuous: no verb notified")
        many = sorted(k for k, v in counts.items() if v > 1 and not self._allowed(*k))
        self.assertEqual(many, [], "a verb published an intermediate state (batch it)")
        stale = sorted(k for k in self.ALLOWED
                       if not any(fnmatch.fnmatch(kind, k[0]) and s == k[1] and v > 1
                                  for (kind, s), v in counts.items()))
        self.assertEqual(stale, [], "ALLOWED entries that now notify once (remove them)")


class TestModelAdoptedBeforeWrites(unittest.TestCase):
    """A copy adopts the source's model, then writes the inputs of that model (C7)."""

    WRITES = {"_takein", "_init_scalar", "_takein_xy_float", "_set_defining_parts"}
    # One-model classes, refusing copies, and the empty-group stand-in.
    NOT_MULTI_MODEL = {
        "Point": "one model",
        "Polygon": "one model (its vertices)",
        "Blank": "empty-group stand-in: takes nothing",
        "Track": "a copy is a free points track (Tracks Design)",
        "_ReversedTrack": "refuses every copy",
    }

    def test_adopt_comes_first(self):
        found, wrong = set(), []
        for mod in ("shapes", "box", "track"):
            for cls in [n for n in ast.walk(_tree(mod)) if isinstance(n, ast.ClassDef)]:
                for f in cls.body:
                    if not (isinstance(f, ast.FunctionDef) and f.name == "_takein_impl"):
                        continue
                    found.add(cls.name)
                    if cls.name in self.NOT_MULTI_MODEL:
                        continue
                    seen_adopt = False
                    for stmt in f.body:
                        names = _calls(stmt)
                        if "_adopt_model_of" in names:
                            seen_adopt = True
                        if not seen_adopt and self.WRITES & set(names):
                            wrong.append(f"{mod}.{cls.name}: writes before _adopt_model_of")
                            break
                    if not seen_adopt:
                        wrong.append(f"{mod}.{cls.name}: never adopts the source's model")
        self.assertEqual(wrong, [])
        self.assertEqual(sorted(set(self.NOT_MULTI_MODEL) - found), [], "stale NOT_MULTI_MODEL")


class TestDefiningTablesAgree(unittest.TestCase):
    """One Defining set per model: table, ``_defining_names_for``, constructor, copy."""

    @staticmethod
    def _table(obj):
        import scena.shapes as SH
        fam = type(obj).__name__
        if fam == "Line":
            return SH._LINE_MODEL_DEFINING.get(obj.model)
        if fam in ("Rect", "Box"):
            return SH._RECT_MODEL_DEFINING.get(obj.model.value)
        if fam == "Square":
            return SH._SQUARE_MODEL_DEFINING.get(obj.model.value)
        return None

    def test_constructors(self):
        checked, wrong = 0, []
        with fresh_world() as w:
            for kind in sorted(A.K):
                obj = w.track(A.build(kind)) if not kind.startswith("Box") else A.build(kind)
                table = self._table(obj)
                if table is None:
                    continue
                checked += 1
                got = A._defining(obj)
                if got != set(table):
                    wrong.append((kind, sorted(got), sorted(table)))
                dn = getattr(obj, "_defining_names_for", None)
                if callable(dn) and set(dn(obj.model)) != set(table):
                    wrong.append((kind, "_defining_names_for", sorted(dn(obj.model))))
        self.assertGreater(checked, 20)
        self.assertEqual(wrong, [])

    def test_cross_model_copies(self):
        """``d << s`` for every ordered pair of models of one class: d's Defining
        set is the table's row for s's model (D21)."""
        checked, wrong = 0, []
        with fresh_world() as w:
            fams = {}
            for kind in sorted(A.K):
                if kind.startswith(("Line", "Rect", "Square")) and not G.is_relational(A.build(kind)):
                    fams.setdefault(A.family(kind), []).append(kind)
            for fam, kinds in fams.items():
                for a in kinds:
                    for b in kinds:
                        src = w.track(A.build(a))
                        dst = w.track(A.build(b, dict(G.P0, x=40.0)))
                        dst << src
                        checked += 1
                        table = self._table(src)
                        if A._defining(dst) != set(table):
                            wrong.append((b, "<<", a, sorted(A._defining(dst))))
        self.assertGreater(checked, 50)
        self.assertEqual(wrong, [])


class TestTimedVerbsGateLikeInstant(unittest.TestCase):
    """GX4 / GX17 class: the instant form refuses ⇔ the timed form refuses at
    the call, and a timed verb that was accepted never raises from a tick."""

    VERBS = {
        "move_by": (lambda o: o.move_by(7, -3), lambda o: o.move_by(7, -3, time=0.2)),
        "move_to": (lambda o: o.move_to(5, 5), lambda o: o.move_to(5, 5, time=0.2)),
        "rotate_by": (lambda o: o.rotate_by(33), lambda o: o.rotate_by(33, time=0.2)),
        "rotate_to": (lambda o: o.rotate_to(80), lambda o: o.rotate_to(80, time=0.2)),
        "scale_by": (lambda o: o.scale_by(1.5), lambda o: o.scale_by(1.5, time=0.2)),
        "scale_to": (lambda o: o.scale_to(2), lambda o: o.scale_to(2, time=0.2)),
    }

    @staticmethod
    def _links(kind):
        """``none``, every Defining part linked alone (a scalar or a point:
        the gate holds per part; one picked field missed RegularPolygon's
        ``radius``), a chain and a whole link."""
        obj = A.build(kind)
        parts = A.linkable_parts(obj)
        A._destroy(obj)
        return (["none"] + [f"{'part' if pt else 'field'} {n}" for n, pt in parts]
                + ["chain", "whole"])

    @staticmethod
    def _apply(link, obj, w):
        if " " in link:
            kind_of, name = link.split(" ", 1)
            return A.link_part(obj, name, kind_of == "part")
        return A.apply_link(link, obj, w)

    def _cells(self):
        found = {}
        with fresh_world() as w:
            for kind in sorted(A.K):
                if kind.startswith("Box"):
                    continue
                for link in self._links(kind):
                    for verb, (instant, timed) in self.VERBS.items():
                        G.reset_clock()
                        twin = A.build(kind)
                        w.track(twin)
                        if self._apply(link, twin, w) is None:
                            continue
                        try:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore")
                                instant(twin)
                            refuses = False
                        except LinkedAttributeError:
                            refuses = True
                        except Exception:  # noqa: BLE001  (not this guard's business)
                            continue
                        obj = w.track(A.build(kind))
                        self._apply(link, obj, w)
                        try:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore")
                                timed(obj)
                            accepted = True
                        except LinkedAttributeError:
                            accepted = False
                        if refuses and accepted:
                            found[f"{kind} | {link} | {verb}(time=) | accepted"] = ""
                        if not refuses and not accepted:
                            found[f"{kind} | {link} | {verb}(time=) | refused (instant runs)"] = ""
                        try:
                            G.settle(0.5)
                        except LinkedAttributeError:
                            found[f"{kind} | {link} | {verb}(time=) | raised from a tick"] = ""
        G.reset_clock()
        return found

    def test_parity(self):
        found = self._cells()
        new = sorted(k for k in found if not any(fnmatch.fnmatch(k, p) for p in KNOWN.GATE_PARITY))
        stale = sorted(p for p in KNOWN.GATE_PARITY if not any(fnmatch.fnmatch(k, p) for k in found))
        self.assertEqual(new, [], "a timed verb skips the gate its instant form runs")
        self.assertEqual(stale, [], "GATE_PARITY patterns nothing matches (fixed: remove)")


class TestNoBareExceptInPoseVerbs(unittest.TestCase):
    VERBS = {"move_by", "move_to", "rotate_by", "rotate_to", "scale_by", "scale_to",
             "_move_by", "_move_to", "_apply_flip", "_mirror_geometry"}

    def test_no_swallowed_errors(self):
        bad = []
        for mod in ("shapes", "box", "entity", "sprite", "text", "track"):
            for f in ast.walk(_tree(mod)):
                if not (isinstance(f, ast.FunctionDef) and f.name in self.VERBS):
                    continue
                for h in ast.walk(f):
                    if not isinstance(h, ast.ExceptHandler):
                        continue
                    broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
                    silent = all(isinstance(s, (ast.Pass, ast.Continue)) for s in h.body)
                    if broad and silent:
                        bad.append(f"{mod}.{f.name}")
        self.assertEqual(sorted(set(bad) - set(KNOWN.BARE_EXCEPT)), [])
        self.assertEqual(sorted(set(KNOWN.BARE_EXCEPT) - set(bad)), [], "stale BARE_EXCEPT")


class TestRelationalVerbTable(unittest.TestCase):
    """The doc table, the exemption table, the shadow's constraint maps and the verbs agree."""

    MODELS = {"PARALLEL_POINT": ["Line parallel_point"], "PERPENDICULAR_POINT": ["Line perpendicular_point"],
              "PARALLEL_DIST": ["Line parallel_dist"], "TANGENT_ANGLE": ["Line tangent_angle"],
              "TANGENT_POINT": ["Line tangent_point"], "FROM_RECT": ["Ellipse from_rect"]}
    COLUMNS = {
        "move": (("move_by", "move_by timed", "move_to"),
                 {"move_by": lambda o: o.move_by(7, -3), "move_to": lambda o: o.move_to(60, 40)}),
        "rotate": (("rotate_by", "rotate_by timed", "rotate_to", "angle ="),
                   {"rotate_by": lambda o: o.rotate_by(33), "rotate_to": lambda o: o.rotate_to(float(o.angle) + 50),
                    "angle =": lambda o: setattr(o, "angle", float(o.angle) + 50)}),
        "scale": (("scale_by", "scale_by timed", "scale_to"),
                  {"scale_by": lambda o: o.scale_by(1.5), "scale_to": lambda o: o.scale_to(1.5)}),
        "flip": ((), {"flip_x": lambda o: setattr(o, "flip_x", True),
                      "flip_y": lambda o: setattr(o, "flip_y", True)}),
    }

    @staticmethod
    def _doc_rows():
        path = os.path.join(ROOT, "design", "Shapes Design.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        sec = text[text.index("## Pose verbs on a relational shape"):]
        sec = sec[:sec.index("\n\n", sec.index("| Model"))]
        rows = {}
        for line in sec.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 5 or cells[0] in ("Model", "---"):
                continue
            for model in re.findall(r"`([A-Z_]+)`", cells[0]):
                rows[model] = dict(zip(("move", "rotate", "scale", "flip"), cells[1:]))
        return rows

    @staticmethod
    def _kind_of(cell):
        c = cell.lower()
        if c.startswith("refuses"):
            return "refuses"
        if "orbits" in c:
            return G._ORBIT
        if "across the reference" in c:
            return G._ALONG
        if "the length" in c:
            return G._LENGTH
        return "rigid"

    def test_doc_rows_cover_every_relational_model(self):
        self.assertEqual(sorted(self._doc_rows()), sorted(G.RELATIONAL_MODELS))

    def test_doc_and_exemptions_agree(self):
        rows = self._doc_rows()
        want = {}
        for model, cols in rows.items():
            for col, cell in cols.items():
                kind = self._kind_of(cell)
                if kind not in (G._ORBIT, G._ALONG, G._LENGTH):
                    continue
                for k in self.MODELS[model]:
                    for verb in self.COLUMNS[col][0]:
                        want[(k, verb)] = kind
        self.assertEqual(want, dict(G.CONTRACT_EXEMPT))

    def test_constraint_maps_cover_the_exemptions(self):
        steps = set(S.STEP_NAMES)
        self.assertEqual(sorted(S.CONSTRAINT_MAPS),
                         sorted(k for k in G.CONTRACT_EXEMPT if k[1] in steps))

    def test_verbs_do_what_the_doc_says(self):
        rows, wrong = self._doc_rows(), []
        with fresh_world() as w:
            for model, cols in rows.items():
                for k in self.MODELS[model]:
                    for col, cell in cols.items():
                        refuses = self._kind_of(cell) == "refuses"
                        for verb, call in self.COLUMNS[col][1].items():
                            obj = w.track(A.build(k))
                            w.track(obj._ref)
                            try:
                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore")
                                    call(obj)
                                raised = False
                            except LinkedAttributeError:
                                raised = True
                            if raised != refuses:
                                wrong.append(f"{k} {verb}: doc says {'refuses' if refuses else 'runs'}")
        self.assertEqual(wrong, [])


class TestAllowlistsCarryReasons(unittest.TestCase):
    def test_reasons(self):
        tables = {
            "geom_axes.ROWS_NOT_BUILT": A.ROWS_NOT_BUILT,
            "geom_axes.VERBS_NOT_STEPS": A.VERBS_NOT_STEPS,
            "geom_campaign_known.SHADOW": KNOWN.SHADOW,
            "geom_campaign_known.PROBES": KNOWN.PROBES,
            "geom_campaign_known.GATE_PARITY": KNOWN.GATE_PARITY,
            "geom_campaign_known.BARE_EXCEPT": KNOWN.BARE_EXCEPT,
            "geom_campaign_known.SENTINEL": KNOWN.SENTINEL,
            "geom_campaign_known.LAWS": KNOWN.LAWS,
            "geom_campaign_known.COPY_LAWS": KNOWN.COPY_LAWS,
            "geom_campaign_known.INFLUENCE": KNOWN.INFLUENCE,
            "geom_campaign_known.VALUES": KNOWN.VALUES,
            "geom_campaign_known.BAD_SOURCE": KNOWN.BAD_SOURCE,
            "TestPoseVerbsNotifyOnce.ALLOWED": TestPoseVerbsNotifyOnce.ALLOWED,
            "TestModelAdoptedBeforeWrites.NOT_MULTI_MODEL": TestModelAdoptedBeforeWrites.NOT_MULTI_MODEL,
        }
        empty = [f"{t}[{k!r}]" for t, d in tables.items() for k, v in d.items()
                 if not isinstance(v, str) or not v.strip()]
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
