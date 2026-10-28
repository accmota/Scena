#!/usr/bin/env python3
"""Gameplay videos with sound (60 fps, any size), rendered offline.

A video is made the way the README clips are (``tools/readme/make_readme_media.py``):
the real program runs headless (``tests/program_support.ProgramRun``: the frame
body a windowed run uses, input through the same GLFW handlers), every frame is
drawn on the GPU path the author sees on screen, and a *pilot* plays the game.
The run is not real time: each frame steps the game by exactly 1/60 s however
long it takes to draw, so the video never drops or repeats a frame.

Sound: a windowed run opens a sound card that pulls blocks from the mixer
(``Mixer.start_device``: the mixer is then not ``offline`` and the engine stops
pumping it by world time). The recorder is that sound card: it takes the mixer
off ``offline`` and pulls exactly one frame of samples after each step
(44100 / 60 = 735), so picture and sound line up to the sample. Slow motion,
pause and a world-time scale act on sound as on a real card: the card's clock
is wall time, never the world's.

  python tools/video/record_game.py examples/corrida.py --pilot pick_and_race --seconds 30
  python tools/video/record_game.py examples/ninja_4_perigos.py --pilot run_jump_and_throw \\
      --lead 1 --seconds 12 --size 2560x1440 --out recordings/ninja.mp4
  python tools/video/record_game.py README.md#catch-the-stars --pilot follow_stars --seconds 10
  python tools/video/record_game.py examples/bolas.py --frames-dir recordings/bolas  # PNGs + WAV

The shot list (``takes.py``) names every take of the YouTube videos: a
program, a video pilot (``pilots.py``) with its keywords, a seed. A take ends
when its pilot says the run is over (``game.done``, plus a tail) or at its
cap. Each take writes ``recordings/<game>/<take>.mp4`` and a review sheet
``<take>.review.jpg`` (frames every 5 s, still and silent seconds, flags a
stall the pilot did not mean). ``--review`` makes only the sheet, small and
fast, to check a pilot before a full render. Several takes run as child
processes, ``-j`` at once.

  python tools/video/record_game.py --list
  python tools/video/record_game.py --all --review            # check every pilot (seconds)
  python tools/video/record_game.py --take pegar_estrelas     # a game's takes, 1440p60
  python tools/video/record_game.py --all -j 2

The program is an example file or ``README.md#<clip id>`` (a README block, as
the README tool runs it). ``--pilot`` names a video pilot (``pilots.py``), a
pilot of the README tool (``PILOTS`` there) or a function in any file,
``path/to/pilots.py:function``; a pilot is ``(game, t, **args)`` each frame
(see ``pilots.py``). The game is fitted into ``--size`` with its own aspect
and letterboxed.

Output: ``.mp4`` (H.264, BT.709, AAC 48 kHz) or, with ``--prores``, ``.mov``
(ProRes 422 HQ, PCM) for an editor; ``--frames-dir`` writes a PNG sequence and
``audio.wav`` and needs no encoder. Encoding needs ffmpeg: ``ffmpeg`` on the
PATH or the ``imageio-ffmpeg`` package (``pip install imageio-ffmpeg``).
Default output: ``recordings/<program>.mp4`` (git-ignored).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # tools/video (this script)
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools" / "readme"))

import make_readme_media as mm  # noqa: E402  (pilots, surfaces, README programs)

GAME_FPS = 60                  # the game steps at 1/60 s, as a window does
LETTERBOX = mm.LETTERBOX


# ── Sound: the recorder is the sound card ──────────────────────────────────

def frame_samples(frame: int, rate: int, fps: int = GAME_FPS) -> int:
    """Samples that play during game frame ``frame`` (0-based).

    Integer edges (``frame * rate // fps``), so any run of frames sums to its
    exact duration: no drift between picture and sound over a long take.
    """
    return (frame + 1) * rate // fps - frame * rate // fps


class SoundCard:
    """Pull the mixer once per frame, as the device callback of a window does.

    While open the mixer is not ``offline``: the engine's own pump
    (``Mixer.pump_dt``, by world time) is a no-op, as with a real device, and
    only ``pull`` advances the voices.
    """

    def __init__(self, mixer, fps: int = GAME_FPS) -> None:
        self.mixer = mixer
        self.fps = fps
        self.rate = mixer.sample_rate
        self.frame = 0
        self.blocks: list = []
        self._was_offline = None

    def __enter__(self) -> "SoundCard":
        self._was_offline = self.mixer.offline
        self.mixer.offline = False
        return self

    def __exit__(self, *exc) -> None:
        self.mixer.offline = self._was_offline

    def pull(self, keep: bool = True):
        """One frame of sound (``(n, 2)`` float32); kept unless ``keep`` is False."""
        import numpy as np
        n = frame_samples(self.frame, self.rate, self.fps)
        self.frame += 1
        # A copy: a silent block is a buffer the mixer reuses.
        block = np.array(self.mixer.render_block(n).block, dtype=np.float32, copy=True)
        if keep:
            self.blocks.append(block)
        return block

    def samples(self):
        import numpy as np
        if not self.blocks:
            return np.zeros((0, 2), dtype=np.float32)
        return np.concatenate(self.blocks)


def write_wav(path, samples, rate: int) -> None:
    """16-bit stereo WAV (the mixer's limiter keeps samples inside ±1)."""
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# ── Picture ────────────────────────────────────────────────────────────────

def fit_size(design: tuple, box: tuple) -> tuple:
    """The largest even size of the design's aspect inside ``box``.

    Even: 4:2:0 video halves the chroma, so an odd edge is refused by the encoder.
    """
    dw, dh = design
    bw, bh = box
    k = min(bw / dw, bh / dh)
    w = min(bw, round(dw * k)) // 2 * 2
    h = min(bh, round(dh * k)) // 2 * 2
    return max(2, w), max(2, h)


def draw_cursor(frame, at, scale: float):
    """A mouse arrow with its tip at ``at`` (pixels) on an RGBA frame."""
    import numpy as np
    from PIL import Image, ImageDraw
    x, y = at
    arrow = [(0, 0), (0, 17), (4.5, 13), (7.5, 19.5), (10, 18.5), (7, 12), (12.5, 12)]
    img = Image.fromarray(frame, "RGBA")
    ImageDraw.Draw(img).polygon([(x + ax * scale, y + ay * scale) for ax, ay in arrow],
                                fill=(255, 255, 255, 255), outline=(0, 0, 0, 255),
                                width=max(1, round(scale)))
    return np.asarray(img)


# ── The code panel ("this code → this game") ───────────────────────────────

CODE_FONTS = ("/System/Library/Fonts/Menlo.ttc",                       # macOS
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",   # Linux
              "C:/Windows/Fonts/consola.ttf")                          # Windows
CODE_STYLE = "one-dark"
CODE_BG = (24, 26, 33)
CODE_SHARE = 0.4               # the panel's share of the frame's width


def program_code(source: str) -> str:
    """The program as the viewer reads it: no module docstring, no blank
    lines before the first line of code."""
    import ast
    lines = source.splitlines()
    tree = ast.parse(source)
    first = tree.body[0] if tree.body else None
    if (isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)):
        lines = lines[first.end_lineno:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).rstrip() + "\n"


CODE_MARK = (44, 49, 60)          # the band behind a highlighted line
CODE_MARK_EDGE = (229, 192, 123)  # and its mark at the left edge
CODE_MUTED = "#7f848e"            # the title, and the "…" that stands for code left out
CODE_MAX_PT = 1 / 40              # font size, as a share of the panel's height: at most,
CODE_MIN_PT = 1 / 72              # and the least that reads (20 px at 1440): below it, wrap
CODE_WRAP_INDENT = 4              # a wrapped line's rest, this far past the line's indent


def _code_lines(source: str) -> list:
    """``source`` as Pygments tokens, one list of ``(ttype, text)`` per line."""
    from pygments.lexers import PythonLexer
    lines = [[]]
    for ttype, text in PythonLexer().get_tokens(source.rstrip("\n") + "\n"):
        for k, part in enumerate(text.split("\n")):
            if k:
                lines.append([])
            if not part:
                continue
            last = lines[-1][-1] if lines[-1] else None
            if last and last[0] == ttype and not part.isspace():    # a string, whole
                lines[-1][-1] = (ttype, last[1] + part.expandtabs(4))
            else:
                lines[-1].append((ttype, part.expandtabs(4)))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _wrap(lines: list, cols: int) -> list:
    """The panel's rows: ``(line, tokens)`` each. A line longer than ``cols``
    breaks before the token that does not fit (a token longer than a row
    breaks inside, after a space when it has one), its rest
    ``CODE_WRAP_INDENT`` past the line's indent."""
    rows = []
    for n, tokens in enumerate(lines):
        text = "".join(part for _, part in tokens)
        indent = min(len(text) - len(text.lstrip()) + CODE_WRAP_INDENT, cols // 2)
        row, col = [], 0
        for ttype, part in tokens:
            while part:
                room = cols - col
                if len(part) <= room:
                    row.append((ttype, part))
                    col += len(part)
                    break
                if part.isspace():                     # a space at the edge: the row ends
                    if col > indent:
                        rows.append((n, row))
                        row, col = [(None, " " * indent)], indent
                    break
                if col > indent and len(part) <= cols - indent:    # break before it
                    rows.append((n, row))
                    row, col = [(None, " " * indent)], indent
                    continue
                space = part.rfind(" ", 0, room)       # longer than a row: cut it
                room = space + 1 if space > 0 else room
                row.append((ttype, part[:room]))
                rows.append((n, row))
                row, col, part = [(None, " " * indent)], indent, part[room:]
        rows.append((n, row))
    return rows


def code_fit(source: str, size: tuple, title: str = "", font_path: str | None = None):
    """How ``code_panel`` sets ``source`` in ``size``: ``(pt, rows)``, the font
    size and the rows (``_wrap``). The largest font that shows every line
    whole, up to ``CODE_MAX_PT``; when that is below ``CODE_MIN_PT``, the
    largest at which long lines wrap and every row still fits (a tall
    program still gets a small font: ``buildup.fit`` folds code first)."""
    from PIL import ImageFont
    path = font_path or mono_font()
    w, h = size
    pad = round(h * 0.04)
    lines = _code_lines(source)
    extra = 2 if title else 0
    char_w = ImageFont.truetype(path, 100).getlength("M") / 100    # per point of size

    def fits(rows, cols):
        return min((w - 2 * pad) / (max(cols, 1) * char_w),
                   (h - 2 * pad) / ((len(rows) + extra) * 1.35))

    longest = max((sum(len(p) for _, p in tokens) for tokens in lines), default=1)
    whole = _wrap(lines, longest)
    pt = max(4, min(int(fits(whole, longest)), round(h * CODE_MAX_PT)))
    if pt >= round(h * CODE_MIN_PT):
        return pt, whole
    for wrapped in range(round(h * CODE_MAX_PT), pt, -1):
        cols = int((w - 2 * pad) / (wrapped * char_w))
        rows = _wrap(lines, cols)
        if fits(rows, cols) >= wrapped:
            return wrapped, rows
    return pt, whole


def mono_font() -> str:
    """The system's monospace font (the repository ships none)."""
    path = next((p for p in CODE_FONTS if os.path.exists(p)), None)
    if path is None:
        raise SystemExit("no monospace font found: pass a font file (--code-font)")
    return path


def code_panel(source: str, size: tuple, title: str = "", font_path: str | None = None,
               highlight=()):
    """An RGBA picture of ``source``, syntax-coloured (Pygments, ``CODE_STYLE``),
    set by ``code_fit`` in ``size``, ``title`` on top.
    ``highlight``: line numbers (0-based) drawn on a band with a mark at the
    left (a build-up's new lines); a wrapped line's band covers its rows.
    A ``…`` (code left out) is drawn muted."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from pygments.styles import get_style_by_name
    path = font_path or mono_font()
    w, h = size
    pad = round(h * 0.04)
    pt, rows = code_fit(source, size, title, path)
    font = ImageFont.truetype(path, pt)
    step = round(pt * 1.35)
    style = get_style_by_name(CODE_STYLE)
    default = "#abb2bf"

    def color(ttype, part):
        if part.strip() == "…":
            return CODE_MUTED
        while ttype is not None:
            c = style.style_for_token(ttype).get("color")
            if c:
                return "#" + c
            ttype = ttype.parent
        return default

    img = Image.new("RGBA", (w, h), CODE_BG + (255,))
    draw = ImageDraw.Draw(img)
    y = pad
    if title:
        draw.text((pad, y), title, font=font, fill=CODE_MUTED)
        y += 2 * step
    marked = set(highlight)
    for k, (n, _) in enumerate(rows):
        if n in marked:
            top = y + k * step - round(step * 0.12)
            draw.rectangle((0, top, w, top + step - 1), fill=CODE_MARK + (255,))
            draw.rectangle((0, top, max(3, pad // 4), top + step - 1),
                           fill=CODE_MARK_EDGE + (255,))
    for _, tokens in rows:
        x = pad
        for ttype, part in tokens:
            if part.strip():
                draw.text((x, y), part, font=font, fill=color(ttype, part))
            x += font.getlength(part)
        y += step
    return np.asarray(img)


# ── Captions: what is going on, in big letters above the game ──────────────

CAPTION_FONT = REPO / "examples" / "media" / "fonts" / "Quantico-Bold.ttf"
CAPTION_PT = 0.045        # the caption's font, at most, as a share of the frame's height
CAPTION_BAR = 0.05        # a letterbox band lower than this share: the caption goes over the
CAPTION_BAND = 0.08       # top of the game, on a dark band this high
CAPTION_COLOR = (255, 255, 255)


def caption_image(text: str, size: tuple, frame_h: int):
    """An RGBA picture of ``text`` centred in ``size``: one line, as big as
    ``CAPTION_PT`` allows and the box holds (94 % of its width, 60 % of its
    height), with a soft shadow."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    w, h = size
    px = max(8, min(round(frame_h * CAPTION_PT), round(h * 0.6)))
    font = ImageFont.truetype(str(CAPTION_FONT), px)
    wide = font.getlength(text)
    if wide > w * 0.94:
        px = max(8, int(px * w * 0.94 / wide))
        font = ImageFont.truetype(str(CAPTION_FONT), px)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    at = (w / 2, h / 2)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((at[0], at[1] + px * 0.06), text, font=font, anchor="mm",
                                fill=(0, 0, 0, 200))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(px * 0.08)))
    ImageDraw.Draw(img).text(at, text, font=font, anchor="mm", fill=CAPTION_COLOR + (255,))
    return np.asarray(img)


def caption_box(size: tuple, game: tuple) -> tuple:
    """Where captions go: ``(top, bottom, left, right, over_game)``. The
    letterbox band above the game when it is at least ``CAPTION_BAR`` of the
    frame's height, else a band over the top of the game."""
    (x0, y0), (gw, _) = game
    if y0 >= size[1] * CAPTION_BAR:
        return 0, y0, x0, x0 + gw, False
    return y0, y0 + round(size[1] * CAPTION_BAND), x0, x0 + gw, True


def load_pilot(spec: str):
    """A video pilot (``pilots.py``) or README pilot by name, or ``file.py:function``."""
    if ":" in spec and spec.split(":", 1)[0].endswith(".py"):
        path, name = spec.rsplit(":", 1)
        mod_spec = importlib.util.spec_from_file_location(Path(path).stem, path)
        if mod_spec is None or mod_spec.loader is None:
            raise SystemExit(f"cannot load pilot file {path!r}")
        mod = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(mod)
        fn = getattr(mod, name, None)
        if not callable(fn):
            raise SystemExit(f"{path} has no function {name!r}")
        return fn
    import pilots
    if spec in pilots.PILOTS:
        return pilots.PILOTS[spec]
    if spec not in mm.PILOTS:
        raise SystemExit(f"unknown pilot {spec!r}; video pilots: {', '.join(pilots.PILOTS)}; "
                         f"README pilots: {', '.join(mm.PILOTS)} "
                         "(or path/to/pilots.py:function)")
    return mm.PILOTS[spec]


# ── Output ─────────────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class FramesSink:
    """A PNG per frame and ``audio.wav`` in a folder (no encoder needed)."""

    def __init__(self, folder: Path, size: tuple, fps: int) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def frame(self, rgba) -> None:
        from PIL import Image
        Image.fromarray(rgba, "RGBA").convert("RGB").save(
            self.folder / f"frame_{self.n:06d}.png", compress_level=1)
        self.n += 1

    def finish(self, samples, rate: int) -> Path:
        write_wav(self.folder / "audio.wav", samples, rate)
        return self.folder

    def abort(self) -> None:
        pass


class FfmpegSink:
    """Frames stream into ffmpeg; the sound is muxed in at the end."""

    def __init__(self, out: Path, size: tuple, fps: int, *, ffmpeg: str,
                 crf: int = 16, prores: bool = False) -> None:
        self.out = Path(out)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.ffmpeg, self.fps, self.prores = ffmpeg, fps, prores
        self.tmp = tempfile.TemporaryDirectory(prefix="scena_video_")
        self.video = Path(self.tmp.name) / ("video.mov" if prores else "video.mp4")
        w, h = size
        if prores:
            codec = ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
            fmt = "yuv422p10le"
        else:
            codec = ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                     "-pix_fmt", "yuv420p", "-g", str(fps // 2), "-bf", "2"]
            fmt = "yuv420p"
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-framerate", str(fps),
               "-i", "-",
               # Tag and convert as BT.709: an untagged stream plays a little
               # washed out or shifted on some players. ``setparams`` tags the
               # frames: ffmpeg 7 takes the tags from them, not from the flags below.
               "-vf", f"scale=out_color_matrix=bt709:out_range=tv,format={fmt},"
                      "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
               *codec,
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-color_range", "tv", str(self.video)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def frame(self, rgba) -> None:
        self.proc.stdin.write(rgba.tobytes())

    def finish(self, samples, rate: int) -> Path:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding the picture")
        wav = Path(self.tmp.name) / "audio.wav"
        write_wav(wav, samples, rate)
        audio = ["-c:a", "pcm_s16le"] if self.prores else ["-c:a", "aac", "-b:a", "320k"]
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(self.video), "-i", str(wav),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", *audio, "-ar", "48000",
               *([] if self.prores else ["-movflags", "+faststart"]), str(self.out)]
        subprocess.run(cmd, check=True)
        self.tmp.cleanup()
        return self.out

    def abort(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.kill()
        self.tmp.cleanup()


class Review:
    """A take's contact sheet and stall numbers; passes every frame on to ``inner``.

    A second is *still* when the picture a second later differs by less than
    ``STILL`` (mean of |Δ| over the channels, 0–255): a frozen "press SPACE"
    screen, a hero stuck at a wall. It is *silent* when its sound stays under
    ``SILENT`` (RMS). A take that stands still for ``STALL`` seconds in a row is
    flagged: a stall the pilot did not mean is a pilot bug. A pilot that holds
    a still screen on purpose (a results screen to read) sets ``game.still``
    and those seconds are not counted (``mark_meant``).
    """

    STILL = 0.15
    SILENT = 1e-3
    STALL = 3

    def __init__(self, inner, fps: int, *, every: float = 5.0, thumb_width: int = 384) -> None:
        self.inner, self.fps = inner, fps
        self.every = max(1, int(round(every * fps)))
        self.thumb_width = thumb_width
        self.n = 0
        self.thumbs: list = []
        self.motion: list = []          # one value per second
        self.loud: list = []            # one RMS per second
        self.meant: set = set()         # seconds the pilot marked still on purpose
        self._last = None

    def mark_meant(self) -> None:
        """The frame about to come is still on purpose (``game.still``)."""
        self.meant.add(self.n // self.fps)

    def frame(self, rgba) -> None:
        import numpy as np
        if self.n % self.fps == 0:
            small = rgba[::4, ::4, :3].astype(np.int16)
            if self._last is not None:
                self.motion.append(float(np.abs(small - self._last).mean()))
            self._last = small
        if self.n % self.every == 0:
            from PIL import Image
            img = Image.fromarray(rgba, "RGBA").convert("RGB")
            h = round(img.height * self.thumb_width / img.width)
            self.thumbs.append((self.n / self.fps, img.resize((self.thumb_width, h))))
        if self.inner is not None:
            self.inner.frame(rgba)
        self.n += 1

    def finish(self, samples, rate: int):
        import numpy as np
        self.loud = [float(np.sqrt((samples[i:i + rate] ** 2).mean()))
                     for i in range(0, len(samples) - rate // 2, rate)]
        return self.inner.finish(samples, rate) if self.inner is not None else None

    def abort(self) -> None:
        if self.inner is not None:
            self.inner.abort()

    def report(self, *, tail_from: float | None = None) -> dict:
        """``tail_from``: seconds after which stillness is meant (the run is over)."""
        # motion[k] compares second k with second k + 1
        still = [m < self.STILL and k not in self.meant and k + 1 not in self.meant
                 for k, m in enumerate(self.motion)]
        if tail_from is not None:
            still = still[:max(0, int(tail_from))]
        longest, at, run_len = 0, 0, 0
        for k, s in enumerate(still):
            run_len = run_len + 1 if s else 0
            if run_len > longest:
                longest, at = run_len, k - run_len + 1
        return {"seconds": self.n / self.fps, "still": sum(still),
                "longest_still": longest, "still_at": at,
                "silent": sum(x < self.SILENT for x in self.loud), "heard": len(self.loud)}

    def flags(self, report: dict, *, ended: str, expect_end: bool) -> list:
        out = []
        if report["longest_still"] >= self.STALL:
            out.append(f"still {report['longest_still']} s from {report['still_at']} s")
        if expect_end and ended != "done":
            out.append("the run never ended (cap reached)")
        return out

    def save_sheet(self, path, title: str) -> None:
        from PIL import Image, ImageDraw
        if not self.thumbs:
            return
        cols = 4
        tw, th = self.thumbs[0][1].size
        rows = (len(self.thumbs) + cols - 1) // cols
        head = 28
        sheet = Image.new("RGB", (cols * tw, head + rows * th), (24, 24, 28))
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 8), title, fill=(235, 235, 235))
        for k, (t, img) in enumerate(self.thumbs):
            x, y = (k % cols) * tw, head + (k // cols) * th
            sheet.paste(img, (x, y))
            draw.rectangle((x, y, x + 44, y + 16), fill=(0, 0, 0))
            draw.text((x + 4, y + 3), f"{t:5.1f}s", fill=(255, 255, 255))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path, quality=85)


# ── Recording ──────────────────────────────────────────────────────────────

def record(program: str, sink_factory, *, pilot="watch", args: dict | None = None,
           seconds: float = 10.0, lead: float = 0.0, tail: float = 2.0,
           size: tuple = (1920, 1080), fps: int = GAME_FPS, supersample: int = 1,
           gpu: bool = True, seed: int = 0, progress: bool = True,
           source: str | None = None, layout: str | None = None,
           code_font: str | None = None, code_title: str | None = None,
           code_highlight=(), code_at=None, caption_at=None) -> dict:
    """Play ``program`` and hand each video frame and the sound to a sink.

    ``sink_factory(size, fps)`` builds the sink once the frame size is known.
    ``pilot``: a name (``load_pilot``) or a function ``(game, t, **args)``.
    ``seconds``: the take's length, or its cap when the pilot ends the run: a
    pilot sets ``game.done = True`` when the run is over (a results screen),
    and the take stops ``tail`` seconds later (``ended`` is then ``"done"``).
    ``lead``: seconds played (and heard by no one) before the take starts.
    ``fps``: 60, or 30 (every second game frame; the sound keeps every frame).
    ``source``: run this text as if it were the file ``program`` (its media
    resolve from the file's folder).
    ``layout``: ``"code"`` puts the program's code on the left of the frame
    (``code_panel``, ``CODE_SHARE`` of the width) and the game on the right;
    ``code_title`` (default: the file) heads it, ``code_highlight`` marks lines.
    ``code_at(game, t)``: the panel changes during the take: it returns
    ``(code, title, highlight)`` for each video frame (``t`` the pilot's
    clock), the code as shown; it may end the take (``game.done``).
    ``caption_at(game, t)``: ``(text, alpha)`` or ``None`` for each video
    frame, drawn big above the game (``caption_box``); the result's
    ``captions`` lists ``(start, end, text)`` in video seconds, each span a
    caption was seen (a subtitle file's lines).
    """
    import numpy as np
    import skia
    from program_support import ProgramRun  # type: ignore
    from scena.audio_mixer import get_mixer

    if GAME_FPS % fps:
        raise ValueError(f"fps must divide {GAME_FPS} (60 or 30), got {fps}")
    random.seed(seed)
    np.random.seed(seed)
    fly = load_pilot(pilot) if isinstance(pilot, str) else pilot
    args = dict(args or {})
    if source is None:
        path, source = mm.program_of({"program": program})
    else:
        path = program
    if layout not in (None, "code"):
        raise ValueError(f"layout is None or 'code', got {layout!r}")
    if code_at is not None and layout != "code":
        raise ValueError("code_at needs layout='code'")
    text = source if source is not None else (REPO / path).read_text(encoding="utf-8")
    run = ProgramRun(path, source=source, seed=seed, draw=True)
    sink = None
    backend = "cpu"
    try:
        run.start()
        fw = run.world.fw
        dw, dh = fw.design_width, fw.design_height
        panel_w = round(size[0] * CODE_SHARE) // 2 * 2 if layout == "code" else 0
        gw, gh = fit_size((dw, dh), (size[0] - panel_w, size[1]))
        rw, rh = gw * supersample, gh * supersample
        s = rw / dw
        fw.pixel_ratio, fw.view_scale = s, 1.0
        fw._letterbox_pad_x = fw._letterbox_pad_y = 0
        fw.fb_width, fw.fb_height = rw, rh
        surf = mm._gpu_surface(fw, rw, rh) if gpu else None
        if surf is not None:
            backend = "gpu"
        else:
            surf = skia.Surface(rw, rh)
        mm._pin_surface(fw, surf, s)
        run.world.surface = surf

        canvas = np.empty((size[1], size[0], 4), dtype=np.uint8)
        canvas[...] = LETTERBOX + (255,)
        x0, y0 = panel_w + (size[0] - panel_w - gw) // 2, (size[1] - gh) // 2
        if layout == "code" and code_at is None:
            whole = (program_code(text),
                     code_title or (program if program.startswith("README") else path),
                     tuple(code_highlight))
            code_at = lambda game, t: whole  # noqa: E731
        panels, shown = {}, None
        cap_box = caption_box(size, ((x0, y0), (gw, gh)))
        cap_images, said, spans = {}, None, []
        sink = sink_factory(size, fps)
        game = mm.Pilot(run)
        step = GAME_FPS // fps
        lead_frames = int(round(lead * GAME_FPS))
        stop = int(round(seconds * fps))        # video frames; the pilot may end it sooner
        ended = "cap"
        cursor_scale = size[1] / 540
        t0 = time.monotonic()
        frames = 0
        i = 0
        with SoundCard(get_mixer()) as card:
            while frames < stop:
                # The HUD's FPS (Ctrl+Shift+1 / 7) counts frames per wall-clock
                # second: offline that is the render's speed, not the video's.
                # The video plays at GAME_FPS, so that is what the clock reports.
                if getattr(fw, "clock", None) is not None:
                    fw.clock._fps = float(GAME_FPS)
                fly(game, i / GAME_FPS, **args)
                if ended == "cap" and getattr(game, "done", False):
                    ended = "done"
                    stop = frames + int(round(tail * fps))
                    if frames >= stop:
                        break
                run.step(1)
                card.pull(keep=i >= lead_frames)
                i += 1
                if i <= lead_frames or (i - lead_frames) % step:
                    continue
                if backend == "gpu":
                    surf.flushAndSubmit()
                px = np.asarray(surf.makeImageSnapshot().toarray(
                    colorType=skia.kRGBA_8888_ColorType))
                if supersample > 1:
                    px = mm._downscale(px, supersample)
                if getattr(game, "cursor", False):      # set by the pilot, frame by frame
                    mx, my = game._at
                    px = draw_cursor(px, (mx * gw / dw, (dh - my) * gh / dh), cursor_scale)
                canvas[y0:y0 + gh, x0:x0 + gw] = px
                if code_at is not None:
                    code, title, marks = code_at(game, (i - 1) / GAME_FPS)
                    key = (code, title, tuple(marks))
                    if key != shown:
                        if key not in panels:
                            panels[key] = code_panel(code, (panel_w, size[1]), title=title,
                                                     font_path=code_font, highlight=marks)
                        canvas[:, :panel_w] = panels[key]
                        shown = key
                if caption_at is not None:
                    cue = caption_at(game, (i - 1) / GAME_FPS)
                    text, alpha = cue if cue else (None, 0.0)
                    _draw_caption(canvas, cap_box, cap_images, text, alpha, size[1])
                    seen = text if text and alpha > 0 else None
                    if seen != said:
                        if said is not None:
                            spans[-1][1] = frames / fps
                        if seen is not None:
                            spans.append([frames / fps, None, seen])
                        said = seen
                if getattr(game, "still", False) and hasattr(sink, "mark_meant"):
                    sink.mark_meant()
                sink.frame(canvas)
                frames += 1
                if progress and frames % fps == 0:
                    rate = frames / max(1e-6, time.monotonic() - t0)
                    print(f"  {frames / fps:6.1f} s of {seconds:g} s  ({rate:.0f} frames/s)",
                          file=sys.stderr, flush=True)
            samples = card.samples()
            rate = card.rate
        if said is not None:
            spans[-1][1] = frames / fps
        out = sink.finish(samples, rate)
        sink = None
    finally:
        if sink is not None:
            sink.abort()
        try:
            run.close(strict=False)
        except Exception:
            pass
    return {"out": str(out), "frames": frames, "samples": int(len(samples)),
            "rate": rate, "backend": backend, "game_size": (gw, gh), "ended": ended,
            "captions": [tuple(span) for span in spans]}


def _draw_caption(canvas, box, images, text, alpha, frame_h) -> None:
    """Draw ``text`` at ``alpha`` in ``box`` (``caption_box``). Over the
    letterbox the band is cleared every frame (the game never draws there);
    over the game, the game's own pixels are under it, darkened."""
    import numpy as np
    top, bottom, left, right, over_game = box
    if not over_game:
        canvas[top:bottom, left:right] = LETTERBOX + (255,)
    if not text or alpha <= 0:
        return
    if text not in images:
        images[text] = caption_image(text, (right - left, bottom - top), frame_h)
    img = images[text]
    region = canvas[top:bottom, left:right, :3].astype(np.float32)
    if over_game:
        region *= 1.0 - 0.6 * alpha
    a = img[..., 3:4].astype(np.float32) * (alpha / 255.0)
    canvas[top:bottom, left:right, :3] = (region * (1.0 - a) + img[..., :3] * a).astype(np.uint8)


def _size(text: str) -> tuple:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"size is WxH (1920x1080), got {text!r}") from None
    if w < 2 or h < 2 or w % 2 or h % 2:
        raise argparse.ArgumentTypeError(f"size must be even on both edges, got {text!r}")
    return w, h


# ── Takes (the shot list in takes.py) ──────────────────────────────────────

RECORDINGS = REPO / "recordings"
REVIEW_SIZE, REVIEW_FPS = (640, 360), 30


def pick_takes(names: list[str]) -> list[str]:
    """Take ids for ``names``: an id, or a game (every take ``<game>/…``)."""
    from takes import TAKES
    out = []
    for name in names:
        hit = [t for t in TAKES if t == name or t.startswith(name.rstrip("/") + "/")]
        if not hit:
            raise SystemExit(f"no take {name!r}; --list shows them")
        out += [t for t in hit if t not in out]
    return out


def run_take(tid: str, *, review_only: bool = False, gpu: bool = True,
             progress: bool = True) -> dict:
    """Record one take of the shot list (or only its review, fast and small)."""
    from takes import take
    spec = take(tid)
    out = RECORDINGS / f"{tid}.mp4"
    sheet = RECORDINGS / f"{tid}.review.jpg"
    size, fps = (REVIEW_SIZE, REVIEW_FPS) if review_only else (spec["size"], spec["fps"])
    ffmpeg = None if review_only else find_ffmpeg()
    if not review_only and ffmpeg is None:
        raise SystemExit("no ffmpeg: install it (brew install ffmpeg) or pip install imageio-ffmpeg")
    reviews = []

    def factory(size, fps):
        inner = None if review_only else FfmpegSink(out, size, fps, ffmpeg=ffmpeg, crf=spec["crf"])
        reviews.append(Review(inner, fps))
        return reviews[-1]

    r = record(spec["program"], factory, pilot=spec["pilot"], args=spec["args"],
               seconds=spec["seconds"], lead=spec["lead"], tail=spec["tail"], size=size,
               fps=fps, seed=spec["seed"], gpu=gpu, progress=progress,
               layout=spec["layout"])
    review = reviews[0]
    tail_from = r["frames"] / fps - spec["tail"] if r["ended"] == "done" else None
    rep = review.report(tail_from=tail_from)
    flags = review.flags(rep, ended=r["ended"], expect_end=spec["end"] == "done")
    title = (f"{tid}   {rep['seconds']:.1f} s ({r['ended']})   still {rep['still']} s   "
             f"silent {rep['silent']}/{rep['heard']} s" + ("   !! " + "; ".join(flags) if flags else ""))
    review.save_sheet(sheet, title)
    return {"take": tid, "ok": True, "out": None if review_only else str(out),
            "sheet": str(sheet), "ended": r["ended"], "flags": flags, **rep}


def _take_child(tid: str, review_only: bool, gpu: bool) -> dict:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--take", tid, "--child"]
    cmd += ["--review"] if review_only else []
    cmd += [] if gpu else ["--cpu"]
    out = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                         cwd=str(REPO), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in reversed(out.stdout.strip().splitlines()):
        if line.startswith("{"):
            import json
            return json.loads(line)
    tail = "\n".join((out.stderr or "").strip().splitlines()[-6:])
    return {"take": tid, "ok": False, "error": f"exit {out.returncode}: {tail}"}


def _print_take(r: dict) -> None:
    if not r.get("ok"):
        print(f"FAILED  {r['take']}: {r.get('error')}")
        return
    where = r["out"] or r["sheet"]
    print(f"{'ok' if not r['flags'] else 'check':7} {r['take']}  {r['seconds']:.1f} s ({r['ended']})  "
          f"still {r['still']} s  silent {r['silent']}/{r['heard']} s  -> {where}")
    for f in r["flags"]:
        print(f"        !! {f}")


def takes_main(args) -> int:
    import json
    from concurrent.futures import ThreadPoolExecutor
    from takes import TAKES
    if args.list:
        for tid, t in TAKES.items():
            print(f"{tid:32} {t['program']:36} {t['pilot']}")
        return 0
    ids = list(TAKES) if args.all else pick_takes(args.take)
    gpu = not args.cpu
    if args.child or len(ids) == 1:
        try:
            r = run_take(ids[0], review_only=args.review, gpu=gpu, progress=not args.child)
        except Exception as e:  # noqa: BLE001 — reported as data
            r = {"take": ids[0], "ok": False, "error": f"{type(e).__name__}: {e}"}
        if args.child:
            print(json.dumps(r), flush=True)
        else:
            _print_take(r)
        return 0 if r.get("ok") else 1
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = pool.map(lambda tid: _take_child(tid, args.review, gpu), ids)
        failed = 0
        for r in results:
            _print_take(r)
            failed += not r.get("ok")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("program", nargs="?", help="examples/<file>.py or README.md#<clip id>")
    ap.add_argument("--take", action="append", default=[],
                    help="a take of takes.py, or a game (all its takes); repeatable")
    ap.add_argument("--all", action="store_true", help="every take of takes.py")
    ap.add_argument("--list", action="store_true", help="list the takes")
    ap.add_argument("--review", action="store_true",
                    help="takes: only the review sheet, small and fast (no video)")
    ap.add_argument("-j", "--jobs", type=int, default=2, help="takes recorded at once")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--pilot", default="watch",
                    help="a README pilot name or path/to/pilots.py:function (default: watch)")
    ap.add_argument("--seconds", type=float, default=10.0, help="length of the take")
    ap.add_argument("--lead", type=float, default=0.0, help="seconds played before the take")
    ap.add_argument("--size", type=_size, default=(1920, 1080), help="video size (1920x1080)")
    ap.add_argument("--fps", type=int, default=60, choices=(60, 30))
    ap.add_argument("--supersample", type=int, default=1, choices=(1, 2, 3),
                    help="render at N× and average (smoother edges, slower)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cpu", action="store_true", help="raster only (no GPU / display)")
    ap.add_argument("--crf", type=int, default=16, help="H.264 quality (lower = better)")
    ap.add_argument("--prores", action="store_true", help=".mov ProRes 422 HQ + PCM (editing)")
    ap.add_argument("--out", help="output file (default recordings/<program>.mp4)")
    ap.add_argument("--frames-dir", help="write PNG frames + audio.wav here instead")
    args = ap.parse_args(argv)
    if args.take or args.all or args.list:
        return takes_main(args)
    if not args.program:
        ap.error("name a program, or --take / --all / --list")

    stem =args.program.split("#", 1)[1] if "#" in args.program else Path(args.program).stem
    # Resolved now: the run moves into the program's folder, and a relative
    # path read there would land beside the program.
    if args.frames_dir:
        frames_dir = Path(args.frames_dir).resolve()

        def factory(size, fps):
            return FramesSink(frames_dir, size, fps)
    else:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            ap.error("no ffmpeg: install it (brew install ffmpeg) or "
                     "pip install imageio-ffmpeg; or use --frames-dir")
        ext = ".mov" if args.prores else ".mp4"
        out = Path(args.out).resolve() if args.out else REPO / "recordings" / f"{stem}{ext}"

        def factory(size, fps):
            return FfmpegSink(out, size, fps, ffmpeg=ffmpeg, crf=args.crf, prores=args.prores)

    t0 = time.monotonic()
    r = record(args.program, factory, pilot=args.pilot, seconds=args.seconds, lead=args.lead,
               size=args.size, fps=args.fps, supersample=args.supersample, gpu=not args.cpu,
               seed=args.seed)
    print(f"{r['out']}: {r['frames']} frames, {r['samples'] / r['rate']:.2f} s of sound, "
          f"game {r['game_size'][0]}x{r['game_size'][1]} ({r['backend']}), "
          f"{time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
