"""
Tiered runner (tests/run_tiers.py): planning, sharding, parsing, and the
guards that keep a tier from silently dropping tests.
"""

import importlib.util
import io
import ast
import os
import re
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location("run_tiers", os.path.join(HERE, "run_tiers.py"))
rt = importlib.util.module_from_spec(_spec)
sys.modules["run_tiers"] = rt  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(rt)


def _fake_ids(module):
    """Three classes: one tiny, one exactly CHUNK, one over CHUNK."""
    ids = [f"tests.{module}.TestA.test_{i}" for i in range(2)]
    ids += [f"tests.{module}.TestB.test_{i}" for i in range(rt.CHUNK)]
    ids += [f"tests.{module}.TestC.test_{i}" for i in range(rt.CHUNK * 2 + 1)]
    return ids


def _module_of(test_name):
    """``tests.test_x[.Cls.meth]`` / ``scena_editor.tests.test_x`` → ``test_x``."""
    for package, _folder in rt.TEST_ROOTS:
        if test_name.startswith(package + "."):
            return test_name[len(package) + 1:].split(".")[0]
    raise AssertionError(test_name)


class TestTierCoverage(unittest.TestCase):
    """No module falls out of the gate; config names real modules."""

    def test_gate_and_deep_plan_every_module(self):
        mods = rt.discover_modules()
        for name in ("gate", "deep"):
            tier = rt.TIERS[name]
            jobs = rt.plan(tier, rt.tier_modules(tier, mods), list_ids=_fake_ids)
            planned = {_module_of(j.names[0]) for j in jobs}
            self.assertEqual(planned, set(mods), name)

    def test_serial_pass_covers_every_root_in_one_process(self):
        names = rt.serial_names()
        mods = rt.discover_modules()
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in names), sorted(mods))
        self.assertIn("tests.test_keyp", names)
        self.assertIn("scena_editor.tests.test_editor_tools", names)
        # framework modules first, then the editor's; each root sorted
        packages = [n.rsplit(".", 1)[0] for n in names]
        self.assertEqual(packages, sorted(packages, key=["tests", "scena_editor.tests"].index))
        for package in ("tests", "scena_editor.tests"):
            part = [n for n in names if n.rsplit(".", 1)[0] == package]
            self.assertEqual(part, sorted(part))

    def test_editor_tests_are_a_second_root(self):
        mods = rt.discover_modules()
        self.assertIn("test_editor_tools", mods)
        self.assertEqual(rt.package_of("test_editor_tools"), "scena_editor.tests")
        self.assertEqual(rt.package_of("test_keyp"), "tests")
        self.assertEqual(rt.normalize("scena_editor/tests/test_editor_tools.py"),
                         "test_editor_tools")
        jobs = rt.plan(rt.TIERS["focused"], ["test_editor_tools"], list_ids=_fake_ids)
        self.assertEqual(jobs[0].names, ["scena_editor.tests.test_editor_tools"])

    def test_quick_skips_only_slow(self):
        mods = rt.discover_modules()
        quick = rt.tier_modules(rt.TIERS["quick"], mods)
        self.assertEqual(set(mods) - set(quick), set(rt.SLOW))

    def test_slow_and_split_name_existing_modules(self):
        mods = set(rt.discover_modules())
        self.assertLessEqual(set(rt.SLOW), mods, "stale SLOW entry")
        self.assertLessEqual(set(rt.SPLIT), mods, "stale SPLIT entry")

    def test_this_module_is_discovered(self):
        self.assertIn("test_run_tiers", rt.discover_modules())


class TestTierSettings(unittest.TestCase):
    def test_envs(self):
        env = rt.tier_env(rt.TIERS["quick"])
        self.assertEqual(env, {"SCENA_HYPOTHESIS_PROFILE": "dev", "SCENA_CANARIES": "0"})
        env = rt.tier_env(rt.TIERS["gate"])
        self.assertEqual(env, {"SCENA_HYPOTHESIS_PROFILE": "ci", "SCENA_CANARIES": "1"})
        env = rt.tier_env(rt.TIERS["deep"])
        self.assertEqual(env["SCENA_HYPOTHESIS_PROFILE"], "deep")
        self.assertEqual(env["SCENA_SOAK"], "1")
        self.assertTrue(rt.TIERS["deep"].serial_pass)
        self.assertEqual(rt.tier_env(rt.TIERS["gate"], "replay")["SCENA_HYPOTHESIS_PROFILE"],
                         "replay")

    def test_children_cache_bytecode_when_the_host_turns_writes_off(self):
        # Claude Code sets PYTHONDONTWRITEBYTECODE=1: every job compiled scena
        # from source (~0.7 s CPU per process, measured 2026-10-10).
        env = rt.child_env({"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/bin"},
                           {"SCENA_CANARIES": "0"})
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", env)
        self.assertEqual(env["PYTHONPYCACHEPREFIX"], rt.PYCACHE)
        self.assertTrue(rt.PYCACHE.startswith(rt.OUT + os.sep), "inside the git-ignored runs folder")
        self.assertEqual((env["PATH"], env["SCENA_CANARIES"], env["PYTHONIOENCODING"]),
                         ("/bin", "0", "utf-8"))
        # A host's own prefix is kept; a host that writes bytecode keeps __pycache__.
        kept = rt.child_env({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": "/x"})
        self.assertEqual(kept["PYTHONPYCACHEPREFIX"], "/x")
        self.assertNotIn("PYTHONPYCACHEPREFIX", rt.child_env({}))

    def test_every_child_process_gets_the_child_env(self):
        seen = []

        class Done(Exception):
            pass

        def popen(*_a, env=None, **_k):
            seen.append(env)
            raise Done
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}), \
                mock.patch.object(rt.subprocess, "Popen", popen), \
                mock.patch.object(rt.subprocess, "run", lambda *a, env=None, **k: popen(env=env)):
            runner = rt.Runner(tmp, timeout=1, workers=1, stream=io.StringIO())
            with self.assertRaises(Done):
                runner._run(rt.Job("x", ["tests.test_lerp"]))
            with self.assertRaises(Done):
                rt.list_ids_subprocess("test_lerp")
        self.assertEqual(len(seen), 2)
        for env in seen:
            self.assertNotIn("PYTHONDONTWRITEBYTECODE", env)
            self.assertEqual(env["PYTHONPYCACHEPREFIX"], rt.PYCACHE)

    def test_gate_is_at_least_the_old_bug_loop_gate(self):
        # The old gate: full suite (dev) + hyp / sys_hyp at ci, canaries on.
        gate = rt.TIERS["gate"]
        self.assertEqual(gate.profile, "ci")
        self.assertTrue(gate.canaries)
        self.assertEqual(gate.exclude, frozenset())


class TestShard(unittest.TestCase):
    def test_every_id_once_in_order_and_class_pure(self):
        ids = _fake_ids("test_x")
        shards = rt.shard(ids)
        self.assertEqual([t for s in shards for t in s], ids)
        for s in shards:
            self.assertLessEqual(len(s), rt.CHUNK)
            self.assertEqual(len({t.rsplit(".", 1)[0] for t in s}), 1)
        self.assertEqual([len(s) for s in shards], [2, rt.CHUNK, rt.CHUNK, rt.CHUNK, 1])

    def test_a_heavy_class_gets_its_own_chunk(self):
        # WP34: TestMethodJunk's tests are 40 examples each at ci; 40 of them
        # in one job ran 1 130 s in a loaded gate.
        heavy, size = next(iter(rt.CHUNKS.items()))
        ids = ([f"tests.{heavy}.test_{i:02}" for i in range(size * 2 + 3)]
               + [f"tests.{heavy}Other.test_{i:02}" for i in range(rt.CHUNK)])
        self.assertEqual([len(s) for s in rt.shard(ids)], [size, size, 3, rt.CHUNK])
        for cls in rt.CHUNKS:
            self.assertIn(cls.split(".", 1)[0], rt.SPLIT, f"{cls}: its module is not SPLIT")

    def test_plan_splits_only_split_modules_in_split_tiers(self):
        mod = next(iter(rt.SPLIT))
        gate = rt.plan(rt.TIERS["gate"], [mod, "test_lerp"], list_ids=_fake_ids)
        labels = {j.label for j in gate}
        self.assertIn(f"{mod}.TestA", labels)
        self.assertIn(f"{mod}.TestC[3/3]", labels)
        self.assertIn("test_lerp", labels)
        focused = rt.plan(rt.TIERS["focused"], [mod], list_ids=_fake_ids)
        self.assertEqual([j.names for j in focused], [[f"tests.{mod}"]])

    def test_tutorial_steps_run_one_job_per_page_in_gate_and_none_in_quick(self):
        # 2026-10-10: tutorials 17-26 doubled the steps; one test ran them all
        # (~440 s CPU) and timed out the quick tier's 300 s job. The module is
        # SLOW, and the gate runs each page's steps as their own job.
        from tests import test_tutorial_steps as ts
        mod = "test_tutorial_steps"
        loaded = unittest.defaultTestLoader.loadTestsFromName(f"tests.{mod}")
        ids = [t.id() for t in rt._flat(loaded)]
        self.assertNotIn(mod, rt.tier_modules(rt.TIERS["quick"], rt.discover_modules()))
        for tier in ("gate", "deep"):
            jobs = rt.plan(rt.TIERS[tier], [mod], list_ids=lambda _m: ids)
            self.assertEqual(sorted(t for j in jobs for t in j.names), sorted(ids), tier)
            for case in ts.PAGE_CASES:
                self.assertIn([f"tests.{mod}.{case.__name__}.test_every_step_and_try_runs"],
                              [j.names for j in jobs], f"{tier}: {case.PAGE}")
        self.assertGreaterEqual(len(ts.PAGE_CASES), 20)

    def test_every_split_module_really_shards(self):
        # The real ids, at the gate's profile (a module's tests may depend on
        # it): every generated class (one per program, per page) is found by
        # the loader and lands in exactly one gate job. SPLIT shards by
        # TestCase class, so a module of one or two big classes stays one or
        # two jobs whatever SPLIT says: no job may hold half the module.
        from concurrent.futures import ThreadPoolExecutor
        mods = sorted(rt.SPLIT)
        lister = rt.ids_lister(rt.tier_env(rt.TIERS["gate"]))
        with ThreadPoolExecutor(len(mods)) as ex:
            listed = dict(zip(mods, ex.map(lister, mods)))
        for mod, ids in listed.items():
            with self.subTest(module=mod):
                jobs = rt.plan(rt.TIERS["gate"], [mod], list_ids=lambda _m, ids=ids: ids)
                planned = [t for j in jobs for t in j.names]
                self.assertEqual(sorted(planned), sorted(ids), "every test in one job")
                self.assertGreater(len(jobs), 2, f"{mod} plans {len(jobs)} gate jobs")
                biggest = max(len(j.names) for j in jobs)
                self.assertLessEqual(biggest, len(ids) // 2,
                                     f"one job of {mod} holds {biggest} of {len(ids)} tests")

    def test_split_ids_are_listed_with_the_tiers_env(self):
        # The parent has no tier env: listed there, test_prog_isolation gave
        # its dev ids (a chain of pairs) to a ci gate, whose shards then ran
        # ~50 of its ~190 cells and passed (2026-10-10).
        seen = []

        def record(module, env=None):
            seen.append((module, dict(env or {})))
            return _fake_ids(module)
        mod = sorted(rt.SPLIT)[0]
        for argv, profile in ((["gate"], "ci"), (["deep"], "deep"),
                              (["gate", "--profile", "replay"], "replay")):
            seen.clear()
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(rt, "list_ids_subprocess", record), \
                    mock.patch.dict(os.environ, {"SCENA_HYPOTHESIS_PROFILE": "dev"}):
                rc = rt.main([*argv, mod, "--plan"], out_root=tmp, stream=io.StringIO())
                self.assertEqual(rc, 0)
                self.assertEqual([m for m, _e in seen], [mod])
                self.assertEqual(seen[0][1].get("SCENA_HYPOTHESIS_PROFILE"), profile)

    def test_slowest_first_from_timings(self):
        jobs = rt.plan(rt.TIERS["quick"], ["test_a", "test_b", "test_c"],
                       list_ids=_fake_ids,
                       timings={"dev:test_b": 9.0, "dev:test_c": 3.0})
        self.assertEqual([j.label for j in jobs], ["test_b", "test_c", "test_a"])


class TestNormalize(unittest.TestCase):
    def test_spellings(self):
        for arg in ("test_shapes", "tests.test_shapes", "tests/test_shapes.py", "test_shapes.py"):
            self.assertEqual(rt.normalize(arg), "test_shapes")
        self.assertEqual(rt.normalize("tests.test_shapes.TestX.test_y"), "test_shapes.TestX.test_y")

    def test_rejects_non_test_names(self):
        with self.assertRaises(ValueError):
            rt.normalize("shapes")

    def test_rejects_several_names_in_one(self):
        # They became one job: an unimportable module and a log name too long
        # for the filesystem (OSError: File name too long).
        for arg in ("test_a test_b", "test_a\ntest_b", "   "):
            with self.assertRaises(ValueError):
                rt.normalize(arg)

    def test_main_splits_an_argument_holding_several_names(self):
        # zsh does not word-split an unquoted $mods: ``focused $mods`` passes
        # every name in one argv string.
        mods = " ".join(f"test_mod_{i:02d}" for i in range(30))
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            rc = rt.main(["focused", mods, "test_lerp", "--plan"], out_root=tmp, stream=out)
        self.assertEqual(rc, 0)
        self.assertIn("tier focused: 31 jobs", out.getvalue())


class TestLogName(unittest.TestCase):
    """A job label longer than the filesystem's NAME_MAX (255 bytes on macOS,
    Linux, and Windows) crashed the runner with OSError before any job ran."""

    def test_short_labels_keep_their_name(self):
        self.assertEqual(rt.log_name("test_lerp"), "test_lerp.log")
        self.assertEqual(rt.log_name("test_hyp_surface.TestC[3/3]"),
                         "test_hyp_surface.TestC[3_3].log")
        self.assertEqual(rt.log_name("serial:all"), "serial_all.log")

    def test_long_labels_are_capped(self):
        labels = [" ".join(f"test_module_number_{i:02d}" for i in range(28)),
                  "test_" + "x" * 1000,
                  "test_x.Test" + "Y" * 300 + ".test_z"]
        for label in labels:
            name = rt.log_name(label)
            self.assertLessEqual(len(name.encode("utf-8")), rt.LOG_NAME_MAX)
            self.assertTrue(name.endswith(".log"))
            self.assertEqual(name, rt._safe(name), name)  # still filesystem-safe

    def test_cap_keeps_first_module_count_and_hash(self):
        mods = [f"test_module_number_{i:02d}" for i in range(28)]
        name = rt.log_name(" ".join(mods))
        self.assertTrue(name.startswith("test_module_number_00-plus27-"), name)
        # The hash covers the whole label: another list, another log.
        other = rt.log_name(" ".join(mods[:-1] + ["test_other_module_xx"]))
        self.assertNotEqual(name, other)
        self.assertEqual(name, rt.log_name(" ".join(mods)))  # stable across runs

    def test_boundary(self):
        fits = "t" * (rt.LOG_NAME_MAX - len(".log"))
        self.assertEqual(rt.log_name(fits), fits + ".log")
        self.assertRegex(rt.log_name(fits + "t"), r"-[0-9a-f]{10}\.log$")

    def test_runner_writes_a_capped_log(self):
        label = "test_" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            runner = rt.Runner(tmp, timeout=120, workers=1, stream=io.StringIO())
            (res,) = runner.run([rt.Job(label, ["tests.test_lerp"])])
            self.assertTrue(res.ok)
            self.assertEqual(os.path.basename(res.log), rt.log_name(label))
            self.assertTrue(os.path.exists(res.log))


class TestParseOutput(unittest.TestCase):
    def test_ok_skipped_failed(self):
        self.assertEqual(rt.parse_output("...\n---\nRan 3 tests in 0.1s\n\nOK\n"), (3, "OK"))
        self.assertEqual(rt.parse_output("Ran 1 test in 0.1s\n\nOK (skipped=1)\n"),
                         (1, "OK (skipped=1)"))
        text = "FAIL: x\nOK not a status\n---\nRan 11 tests in 0.1s\n\nFAILED (failures=1)\n"
        self.assertEqual(rt.parse_output(text), (11, "FAILED (failures=1)"))

    def test_no_run_line(self):
        self.assertEqual(rt.parse_output("Traceback ...\nImportError: nope\n"), (0, ""))


class TestRunner(unittest.TestCase):
    """Real child processes on a tiny module (a few seconds)."""

    def test_focused_run_passes_and_writes_logs_and_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            rc = rt.main(["focused", "test_lerp", "-j", "1"], out_root=tmp, stream=out)
            self.assertEqual(rc, 0, out.getvalue())
            self.assertIn("RESULT: OK", out.getvalue())
            self.assertTrue(os.path.exists(os.path.join(tmp, "focused", "test_lerp.log")))
            self.assertIn("dev:test_lerp", rt.load_timings(os.path.join(tmp, "timings.json")))

    def test_failing_job_fails_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            runner = rt.Runner(tmp, timeout=120, workers=1, stream=out)
            results = runner.run([rt.Job("missing", ["tests.test_no_such_module_xyz"])])
            self.assertFalse(results[0].ok)
            self.assertFalse(rt.summarize(results, 0.0, out))
            self.assertIn("FAILED missing", out.getvalue())

    def test_timeout_is_a_failure(self):
        # On Windows the killed child's log can stay locked for a moment: a
        # venv's python.exe is a launcher, and the interpreter it started
        # (holding the log) ends just after it. Cleanup may not wait (WP26).
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            runner = rt.Runner(tmp, timeout=0.05, workers=1, stream=io.StringIO())
            (res,) = runner.run([rt.Job("slow", ["tests.test_lerp"])])
            self.assertFalse(res.ok)
            self.assertIn("TIMEOUT", res.status)


class TestLogEncoding(unittest.TestCase):
    """WP8: the child writes its log in its stdio encoding; the parent reads it
    back. On Windows they disagreed (cp1252 vs UTF-8) and the runner crashed
    with every job's result lost."""

    TEXT = "— ” → ×"

    def _failing_job(self, tmp, **env):
        with open(os.path.join(tmp, "nonascii_fail_mod.py"), "w", encoding="utf-8") as fh:
            fh.write("import unittest\n\n"
                     "class T(unittest.TestCase):\n"
                     "    def test_fails(self):\n"
                     f"        self.fail({self.TEXT!r})\n")
        return rt.Job("nonascii", ["nonascii_fail_mod"], {"PYTHONPATH": tmp, **env})

    def test_non_ascii_failure_message_round_trips(self):
        # A parent whose own stdio encoding cannot hold the text: the child must
        # still write UTF-8, because the runner pins it.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PYTHONIOENCODING": "ascii"}):
            out = io.StringIO()
            runner = rt.Runner(os.path.join(tmp, "logs"), timeout=120, workers=1, stream=out)
            (res,) = runner.run([self._failing_job(tmp)])
            self.assertFalse(res.ok)
            self.assertFalse(rt.summarize([res], 0.0, out))
            self.assertIn(self.TEXT, out.getvalue())

    def test_undecodable_log_does_not_crash_the_runner(self):
        # A child that writes another encoding anyway (a native library, a job
        # that overrides it): the runner reports the failure, never raises.
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            runner = rt.Runner(os.path.join(tmp, "logs"), timeout=120, workers=1, stream=out)
            (res,) = runner.run([self._failing_job(tmp, PYTHONIOENCODING="cp1252")])
            self.assertFalse(res.ok)
            self.assertEqual(res.ran, 1)
            self.assertFalse(rt.summarize([res], 0.0, out))
            self.assertIn("FAILED nonascii", out.getvalue())


class TestAppleDoublePreflight(unittest.TestCase):
    def test_counts_dot_underscore_files_in_source_dirs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("scena/._a.py", "scena/a.py", "design/sub/._D.md",
                        "media/._m.png", "scena/.DS_Store"):
                path = os.path.normpath(os.path.join(tmp, rel))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "wb").close()
            self.assertEqual(rt.count_appledouble(tmp), 2)

    def test_warning_is_printed_and_nothing_is_deleted(self):
        out = io.StringIO()
        with mock.patch.object(rt, "count_appledouble", return_value=3):
            rc = rt.main(["focused", "test_lerp", "--plan"], stream=out)
        self.assertEqual(rc, 0)
        self.assertIn("warning: 3 AppleDouble '._*' files", out.getvalue())


class TestOpenFresh(unittest.TestCase):
    """WP10: a tree copied from macOS left the old logs Hidden; Windows refuses
    ``open(path, "w")`` on an existing Hidden file, and every OS on a read-only
    one. The runner deletes the old copy first (``open_fresh``)."""

    def _write_old(self, tmp):
        path = os.path.join(tmp, "test_x.TestA[1_2].log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("old run")
        return path

    def _assert_replaced(self, path):
        with rt.open_fresh(path) as fh:
            fh.write("new run")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "new run")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._assert_replaced(os.path.join(tmp, "test_x.TestA[1_2].log"))

    def test_read_only_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_old(tmp)
            os.chmod(path, stat.S_IREAD)
            self._assert_replaced(path)

    @unittest.skipUnless(os.name == "nt", "the Hidden attribute exists only on Windows")
    def test_hidden_file(self):
        import ctypes
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_old(tmp)
            self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(path, 0x2))  # HIDDEN
            with self.assertRaises(PermissionError):   # the bug
                open(path, "w", encoding="utf-8").close()
            self._assert_replaced(path)


class TestHypothesisProfileGuard(unittest.TestCase):
    """WP13: a module that uses Hypothesis without importing
    ``hypothesis_support`` runs under Hypothesis defaults: a 200 ms deadline
    (``DeadlineExceeded`` under a loaded tier), no example database, and
    ``SCENA_HYPOTHESIS_PROFILE`` ignored (``ci`` / ``deep`` do nothing)."""

    USES = re.compile(r"@given\(|RuleBasedStateMachine")
    LOADS = re.compile(
        r"^\s*(?:import (?:tests\.)?hypothesis_support\b"
        r"|from (?:tests\.)?(?:hypothesis|system)_support import)",
        re.MULTILINE)

    def test_every_hypothesis_module_loads_the_profile(self):
        from source_support import iter_files
        missing = []
        for _package, folder in rt.TEST_ROOTS:
            for path in iter_files(folder, ".py"):
                name = os.path.basename(path)
                if not name.startswith("test_"):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if self.USES.search(text) and not self.LOADS.search(text):
                    missing.append(os.path.relpath(path, rt.ROOT))
        self.assertEqual(missing, [], "add `import hypothesis_support` (loads the profile)")

    def test_guard_sees_both_spellings(self):
        self.assertTrue(self.LOADS.search("x = 1\nimport hypothesis_support  # noqa\n"))
        self.assertTrue(self.LOADS.search("from system_support import system_world\n"))
        self.assertFalse(self.LOADS.search("from hypothesis import given\n"))
        self.assertTrue(self.USES.search("    @given(hst.integers())\n"))



class TestSetUpAgainTearsDownFirst(unittest.TestCase):
    """O7: a test that calls ``self.setUp()`` again mid-test (to run a second
    case from a fresh fixture) must tear down first. ``setUp`` resets the
    tracking list, so the first case's actors were never destroyed:
    ``test_driver_composition`` left two Rects in group "heroi", and every
    galaga program run later in the same process counted three heroes."""

    TEARDOWNS = ("tearDown", "teardown")

    @staticmethod
    def _is_self_call(node, name):
        call = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(call, ast.Call):
            return False
        f = call.func
        while isinstance(f, ast.Attribute):
            if f.attr == name:
                inner = f.value
                while isinstance(inner, ast.Attribute):
                    inner = inner.value
                return isinstance(inner, ast.Name) and inner.id == "self"
            return False
        return False

    def offenders(self, text, label="<src>"):
        out = []
        for node in ast.walk(ast.parse(text)):
            for field in ("body", "orelse", "finalbody"):
                stmts = getattr(node, field, None)
                if not isinstance(stmts, list):
                    continue
                for i, st in enumerate(stmts):
                    if not self._is_self_call(st, "setUp"):
                        continue
                    prev = stmts[i - 1] if i else None
                    if prev is None or not any(self._is_self_call(prev, t)
                                               for t in self.TEARDOWNS):
                        out.append(f"{label}:{st.lineno}")
        return out

    def test_every_repeated_setup_follows_a_teardown(self):
        from source_support import iter_files
        found = []
        for _package, folder in rt.TEST_ROOTS:
            for path in iter_files(folder, ".py"):
                if not os.path.basename(path).startswith("test_"):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if "self.setUp()" not in text:
                    continue
                found += self.offenders(text, os.path.relpath(path, rt.ROOT).replace(os.sep, "/"))
        self.assertEqual(found, [], "write self.tearDown() just before self.setUp() "
                         "(setUp drops the tracking list: the first case's actors leak)")

    def test_guard_sees_the_pattern(self):
        bad = "def t(self):\n    run()\n    self.setUp()\n"
        good = "def t(self):\n    self.tearDown()\n    self.setUp()\n"
        world = "def t(self):\n    self.w.teardown()\n    self.setUp()\n"
        self.assertEqual(len(self.offenders(bad)), 1)
        self.assertEqual(self.offenders(good), [])
        self.assertEqual(self.offenders(world), [])

class TestCanarySwitch(unittest.TestCase):
    def test_require_canaries_skips_when_off(self):
        import hypothesis_support as hs
        with mock.patch.object(hs, "CANARIES", False):
            with self.assertRaises(unittest.SkipTest):
                hs.require_canaries(self)
        with mock.patch.object(hs, "CANARIES", True):
            hs.require_canaries(self)  # no skip


if __name__ == "__main__":
    unittest.main()
