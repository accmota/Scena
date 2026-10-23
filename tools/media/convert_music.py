#!/usr/bin/env python3
"""Music for examples/media: OGG Vorbis at about 96 kbps, with plain names.

Downloaded music comes as WAV, FLAC or 320 kbps MP3 (up to 22 MB a track) and
with names like ``Juhani Junkala - Epic Boss Battle [Seamlessly Looping].wav``.
This re-encodes each track of a folder to OGG Vorbis (quality 2, about 96 kbps
for stereo: background music under sound effects, a few MB a track) and gives
it a plain name: no bracketed or parenthesised parts, camelCase split, lower
case, underscores (``juhani_junkala_epic_boss_battle.ogg``). Plain names are
also what ``tests/test_media_licenses`` can read in a license notice.

Why Vorbis: Scena decodes with miniaudio, which reads Vorbis but not Opus, and
Vorbis at 96 kbps sounds better than MP3 at 96 kbps. The encoder is
libsndfile's (``pip install soundfile``), so no command-line tool is needed.
Each output is decoded back and must hold the same sample count as its source,
so a track made to loop still loops without a gap.

A track that is already OGG Vorbis at or below ``--max-kbps`` is only renamed
(a second lossy pass would cost quality for nothing). File names in the
folder's license file are rewritten to the new names. Originals are moved to
``--originals`` (default ``workbench/media_originals/<folder>/``, git-ignored),
never deleted.

  python tools/media/convert_music.py                      # plan for examples/media/music
  python tools/media/convert_music.py --apply              # convert, rename, move originals
  python tools/media/convert_music.py some/folder --quality 3 --apply
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_FOLDER = os.path.join(REPO, "examples", "media", "music")
AUDIO_EXT = (".wav", ".flac", ".mp3", ".ogg")
LICENSE_NAMES = {"license.txt", "licence.txt"}
BLOCK = 1 << 16                         # frames per write


def plain_name(filename: str) -> str:
    """``"ArcLight (192 Kbps).mp3"`` -> ``"arc_light.ogg"``."""
    stem = os.path.splitext(filename)[0]
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", stem)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", stem)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    if not stem:
        raise ValueError(f"{filename!r} leaves no name once cleaned")
    return stem + ".ogg"


def kbps(path: str, frames: int, rate: int) -> float:
    return os.path.getsize(path) * 8 / (frames / rate) / 1000


def _decode(path: str):
    import miniaudio
    import numpy as np
    d = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.FLOAT32)
    return np.frombuffer(d.samples, dtype=np.float32).reshape(-1, d.nchannels), d.sample_rate


def plan(folder: str, max_kbps: float) -> list[tuple[str, str, bool]]:
    """(old name, new name, encode?) for each audio file in ``folder``."""
    import soundfile as sf
    rows, taken = [], {}
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(AUDIO_EXT) or name.startswith("."):
            continue
        new = plain_name(name)
        if new in taken:
            raise SystemExit(f"{name!r} and {taken[new]!r} would both be {new!r}")
        taken[new] = name
        info = sf.info(os.path.join(folder, name))
        small_vorbis = (info.format == "OGG" and info.subtype == "VORBIS"
                        and kbps(os.path.join(folder, name), info.frames,
                                 info.samplerate) <= max_kbps)
        rows.append((name, new, not small_vorbis))
    return rows


def convert(src: str, dst: str, quality: float) -> None:
    """Encode ``src`` to OGG Vorbis at ``dst``; the decoded copy must hold the
    same number of frames."""
    import soundfile as sf
    samples, rate = _decode(src)
    # libsndfile's compression level is 1 - (Vorbis quality / 10). Written in
    # blocks: libsndfile 1.2 crashes (segfault) on one write of a long track.
    with sf.SoundFile(dst, "w", rate, samples.shape[1], format="OGG", subtype="VORBIS",
                      compression_level=1 - quality / 10) as out:
        for i in range(0, len(samples), BLOCK):
            out.write(samples[i:i + BLOCK])
    back, back_rate = _decode(dst)
    if back.shape != samples.shape or back_rate != rate:
        os.remove(dst)
        raise SystemExit(f"{os.path.basename(src)}: {samples.shape}@{rate} came back "
                         f"as {back.shape}@{back_rate}")


def rewrite_license(folder: str, renames: dict[str, str]) -> list[str]:
    """Replace old file names by new ones in the folder's license file(s);
    longest names first, so one name inside another is not cut."""
    changed = []
    for f in os.listdir(folder):
        if f.lower() not in LICENSE_NAMES:
            continue
        path = os.path.join(folder, f)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = text
        for old in sorted(renames, key=len, reverse=True):
            new = new.replace(old, renames[old])
        if new != text:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
            changed.append(f)
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", nargs="?", default=DEFAULT_FOLDER)
    ap.add_argument("--quality", type=float, default=2.0,
                    help="Vorbis quality, -1..10 (2 is about 96 kbps stereo, 3 about 112)")
    ap.add_argument("--max-kbps", type=float, default=128.0,
                    help="an OGG Vorbis file at or below this is only renamed")
    ap.add_argument("--originals", help="where originals go (default "
                    "workbench/media_originals/<folder name>)")
    ap.add_argument("--apply", action="store_true", help="do it (default: print the plan)")
    args = ap.parse_args(argv)
    try:
        import miniaudio  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"{e.name} is missing: pip install soundfile miniaudio")

    folder = os.path.abspath(args.folder)
    originals = args.originals or os.path.join(
        REPO, "workbench", "media_originals", os.path.basename(folder))
    rows = plan(folder, args.max_kbps)
    for old, new, encode in rows:
        print(f"{'encode' if encode else 'rename' if old != new else 'keep  '}  {old}  ->  {new}")
    if not args.apply:
        print(f"\n{len(rows)} files. Nothing changed: add --apply.")
        return 0

    os.makedirs(originals, exist_ok=True)
    before = after = 0
    for old, new, encode in rows:
        if not encode and old == new:
            continue
        src = os.path.join(folder, old)
        kept = os.path.join(originals, old)
        if os.path.exists(kept):
            raise SystemExit(f"{kept} exists: move it away first")
        dst = os.path.join(folder, new)
        # Written under a name the plan skips, then renamed: a crash leaves
        # the original in place and no half track.
        part = dst + ".part"
        if encode:
            convert(src, part, args.quality)
        else:
            shutil.copy2(src, part)
        shutil.move(src, kept)
        os.replace(part, dst)
        before += os.path.getsize(kept)
        after += os.path.getsize(dst)
        print(f"{new}: {os.path.getsize(kept) / 1e6:.1f} MB -> {os.path.getsize(dst) / 1e6:.1f} MB")
    changed = rewrite_license(folder, {o: n for o, n, _ in rows if o != n})
    print(f"\n{before / 1e6:.1f} MB -> {after / 1e6:.1f} MB. Originals in {originals}.")
    if changed:
        print("Renamed in " + ", ".join(changed) + ": check the names, then CREDITS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
