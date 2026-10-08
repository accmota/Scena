Design docs are in [design]; the author site (Guia, tutorials; `pt` and `en`) is in [docs]; the Guia's tools are in [tools/guide]. Folder map: [design/README.md], "Repository layout".
Read first [design/Scena Design.md] to understand the system.

Agent reading protocol (full version: [design/README.md], "Use (agents)"):
1. Open Scena Design. Pick one router row.
2. Open **Start** only (search; do not slurp fat files).
3. Open the matching companion **only if** invariants are unclear — then pick one jump-box row in that companion; do not read the rest.
4. Treat fences in that section as current constraints (same weight as invariants).
5. Stop. Do not ingest other companions, `scripts/`, or `_sksl_*` unless that is the task. `workbench/` (`archive/`, `proposals/`, `guides/`) is private (not published, may be absent): open its files only when the task names one — except that writing a tutorial or an example starts with the guides in `workbench/guides/`; game examples are developed in the private `drafts/` and move to `examples/` when ready — and never link to them from a published file: a living doc carries the conclusion and its reason ([design/README.md], "Private folders").
6. [design/Fences.md] is not a reading list — open it only when proposing API sugar, a second spelling, or a silent rewrite. However, fences are not set in stone. If a redesign is worth it, we may evaluate the pros and cons.
7. After implementing or changing code, always update the relevant design docs. Always create unit tests for new features.
8. After correcting a bug, update relevant design docs if the change was a design change or if the bug revealed the need for some warning in some document (so this type of error does not happen again). Create unit tests that catches that bug and, if possible, the whole bug class.
9. The API is published (since 0.6.0). Before changing or removing anything in the author surface (`scena.__all__`, the Guia, level files), weigh its author cost and follow [design/Scena Design.md] "Compatibility and versions": old spelling raises with the fix, Guia/tutorial/examples updated, `CHANGELOG.md` entry.
10. Run tests through `python tests/run_tiers.py <tier>` (see [tests/README.txt]): `focused <modules>` after each edit, `quick` (~25 s) before calling a change done, `gate` only as the bug-loop verification gate or before a milestone. Do not run `python -m unittest discover -s tests` as a routine check (~24 min in one process).
