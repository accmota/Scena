#!/usr/bin/env python3
"""scena-examples.zip: the examples and only the media they use.

The README links ``releases/latest/download/scena-examples.zip``: a learner
downloads the examples of the latest release without git and without the 49 MB
of ``examples/media`` (the zip holds about 18 MB). The release workflow
(``.github/workflows/release.yml``) builds it on a version tag and attaches it
to that tag's GitHub Release.

Two steps, so the release machine needs nothing but Python:

* ``--update`` (here, with Scena installed) reads every ``examples/*.py`` and
  every tutorial step with the media-path scanner of ``tests/test_media_refs``,
  follows level files to their images, adds each used folder's license file and
  ``CREDITS.md``, and writes the file list ``tools/release/examples_zip.txt``.
  ``tests/test_examples_zip.py`` fails while the list is stale.
* The default (on the release machine) zips the listed files, standard library
  only: ``scena-examples/<example>.py``, ``scena-examples/media/…`` and a short
  ``README.txt``. Entries carry a fixed date, so the same list makes the same zip.

  python tools/release/make_examples_zip.py --update   # after changing examples / tutorial media
  python tools/release/make_examples_zip.py --check    # exit 1 if the list is stale
  python tools/release/make_examples_zip.py            # dist/scena-examples.zip
  python tools/release/make_examples_zip.py --out x.zip
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES = os.path.join(REPO, "examples")
MEDIA = os.path.join(EXAMPLES, "media")
LIST = os.path.join(REPO, "tools", "release", "examples_zip.txt")
TOP = "scena-examples"
DATE = (2026, 1, 1, 0, 0, 0)            # every entry: the same zip from the same list
LICENSE_NAMES = {"license.txt", "licence.txt"}

README = """\
Scena examples
==============

Each tutorial ends in one of these files, in English and in Portuguese
(ships_4_shield.py is naves_4_escudo.py); the rest are games, creative coding
and showcases. The images and sounds they use are in media/. To run one
(Python 3.12 or newer):

    pip install scena
    python ships_4_shield.py

Tutorial and API Guide: https://accmota.github.io/Scena/
The tutorial copies media/ next to your own scripts: copy this media/ folder.

The images and sounds come from other artists under their own licenses (each
folder has its license file). A few ask for credit: see media/CREDITS.md.
"""

HEADER = """\
# Files in scena-examples.zip (repo-relative), one per line.
# Made by: python tools/release/make_examples_zip.py --update
# Guard: tests/test_examples_zip.py (a stale list fails).
"""


# ── The list (here, with Scena and the tests importable) ───────────────────

def _scanners():
    sys.path.insert(0, REPO)
    import warnings
    warnings.simplefilter("ignore")
    from tests import test_media_refs as refs
    return refs


def example_scripts() -> list[str]:
    return sorted(os.path.join(EXAMPLES, f) for f in os.listdir(EXAMPLES)
                  if f.endswith(".py") and not f.startswith((".", "_")))


def _media_files(path: str) -> list[str]:
    """The files an ``examples/media``-relative path or pattern names."""
    rel = path.split("media/", 1)[1] if path.startswith(("media/", "./media/")) else path
    full = os.path.join(MEDIA, *rel.split("/"))
    if any(c in rel for c in "*?["):
        return sorted(p for p in glob.glob(full) if os.path.isfile(p))
    return [full] if os.path.isfile(full) else []


def _level_images(level: str) -> list[str]:
    """Images a level file places (``"file"`` of an image item, relative to it)."""
    with open(level, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for item in data.get("items", []):
        f = item.get("file")
        if f:
            p = os.path.normpath(os.path.join(os.path.dirname(level), f))
            if os.path.isfile(p):
                out.append(p)
    return out


def _licenses(files) -> list[str]:
    """Each used folder's license file, its parents' up to ``media/``, and a
    ``Licenses/`` folder beside one (fonts)."""
    out = set()
    dirs = {os.path.dirname(f) for f in files}
    for d in dirs:
        while d.startswith(MEDIA) and d != MEDIA:
            for name in os.listdir(d):
                full = os.path.join(d, name)
                if os.path.isfile(full) and name.lower() in LICENSE_NAMES:
                    out.add(full)
                elif os.path.isdir(full) and name.lower() == "licenses":
                    out.update(os.path.join(full, n) for n in os.listdir(full)
                               if not n.startswith("."))
            d = os.path.dirname(d)
    return sorted(out)


def collect() -> tuple[list[str], list[str]]:
    """``(files, unresolved)``: every file the zip needs (repo-relative,
    sorted), and the media paths that name no file."""
    refs = _scanners()
    scripts = example_scripts()
    media, missing = set(), []
    paths = [(os.path.relpath(s, REPO), p) for s in scripts
             for _line, _kind, p in refs.literal_paths(open(s, encoding="utf-8").read())]
    paths += list(refs.tutorial_paths())
    for where, p in paths:
        if refs.DELIBERATE.search(p):
            continue
        found = _media_files(p)
        if not found:
            missing.append(f"{where}: {p}")
        media.update(found)
    for f in list(media):
        if f.endswith(".json") and os.sep + "levels" + os.sep in f:
            media.update(_level_images(f))
    media.update(_licenses(media))
    media.add(os.path.join(MEDIA, "CREDITS.md"))
    files = sorted(os.path.relpath(f, REPO).replace(os.sep, "/") for f in set(scripts) | media)
    return files, missing


def read_list(path: str = LIST) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]


def write_list(files: list[str], path: str = LIST) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HEADER + "".join(f + "\n" for f in files))


# ── The zip (standard library only) ────────────────────────────────────────

def arcname(rel: str) -> str:
    """``examples/x.py`` → ``scena-examples/x.py``; media keeps its path."""
    assert rel.startswith("examples/"), rel
    return f"{TOP}/{rel[len('examples/'):]}"


def build(out: str, files: list[str]) -> int:
    """Write the zip; return its size in bytes."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def put(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)

        put(f"{TOP}/README.txt", README.encode("utf-8"))
        for rel in files:
            with open(os.path.join(REPO, *rel.split("/")), "rb") as fh:
                put(arcname(rel), fh.read())
    return os.path.getsize(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true", help="rewrite the file list (needs Scena)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file list is stale")
    ap.add_argument("--out", default=os.path.join(REPO, "dist", "scena-examples.zip"))
    args = ap.parse_args(argv)

    if args.update or args.check:
        files, missing = collect()
        for m in missing:
            print(f"no file for {m}", file=sys.stderr)
        if args.check:
            stale = files != read_list()
            print("stale: run --update" if stale else f"up to date ({len(files)} files)")
            return 1 if stale or missing else 0
        write_list(files)
        print(f"{len(files)} files -> {os.path.relpath(LIST, REPO)}")
        return 1 if missing else 0

    files = read_list()
    absent = [f for f in files if not os.path.isfile(os.path.join(REPO, *f.split("/")))]
    if absent:
        print("listed but missing (run --update):\n  " + "\n  ".join(absent), file=sys.stderr)
        return 1
    size = build(args.out, files)
    print(f"{args.out}: {len(files) + 1} files, {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
