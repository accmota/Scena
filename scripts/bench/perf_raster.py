"""Cost of a frame on skia's CPU raster surface (headless tests, offline renders).

A game draws through a GL context, so its SkSL runs on the GPU. With no
window (``SystemWorld``, the Guia's ``--cpu`` thumbnails, an offline render)
skia runs the same work on the CPU, per pixel, and a headless frame is
2000 x 1200 unless the test pins a smaller one (Testing Design, "A headless
frame is 2000 x 1200"). This probe prints what that costs on this machine:
a plain translucent fill, a linear gradient, a trivial SkSL shader and the
real ``Embers`` field (the engine's own ``draw``), in ms a frame and ns a
pixel, with the machine and how its skia was built. Run it on each machine
and compare the rows (WP50).

    python scripts/bench/perf_raster.py
    python scripts/bench/perf_raster.py --size 2000x1200 --repeats 1
"""
from __future__ import annotations

import argparse
import os
import platform
import struct
import sys
import time
from typing import Callable, Dict, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import skia  # noqa: E402

from scena.background import CameraSample  # noqa: E402
from scena.background_kinds import Embers  # noqa: E402

_TRIVIAL_SKSL = """
uniform float2 resolution;
half4 main(float2 c) { return half4(half2(c / resolution), 0.0, 1.0); }
"""


def skia_build() -> str:
    """How this skia binary was built, as far as the file tells: on Windows,
    a Rich header means MSVC's linker (skia's raster pipeline then runs its
    portable, non-SIMD stages; clang-cl builds get the SIMD ones)."""
    if os.name != "nt":
        return f"skia {skia.__version__}"
    with open(skia.__file__, "rb") as f:
        head = f.read(4096)
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    linker = "MSVC link.exe" if head.find(b"Rich", 0x40, pe) >= 0 else "not MSVC (no Rich header)"
    return f"skia {skia.__version__}, {linker}"


def _embers_draw(w: int, h: int) -> Callable[[skia.Canvas], None]:
    field = Embers()
    cam = CameraSample(pan_x=0.0, pan_y=0.0, zoom=1.0, rotation=0.0)

    def draw(canvas: skia.Canvas) -> None:
        field.draw(canvas, w, h, 1.0, cam, design_width=w, design_height=h)
    return draw


def _cases(w: int, h: int) -> Dict[str, Callable[[skia.Canvas], None]]:
    rect = skia.Rect.MakeWH(w, h)
    solid = skia.Paint(Color=0x80FF8040)
    grad = skia.Paint(Shader=skia.GradientShader.MakeLinear(
        [(0, 0), (w, h)], [0xFF102030, 0xFFE0A050]))
    builder = skia.RuntimeShaderBuilder(skia.RuntimeEffect.MakeForShader(_TRIVIAL_SKSL))
    builder.setUniform("resolution", [float(w), float(h)])
    trivial = skia.Paint(Shader=builder.makeShader())
    return {
        "translucent fill": lambda c: c.drawRect(rect, solid),
        "linear gradient": lambda c: c.drawRect(rect, grad),
        "trivial SkSL": lambda c: c.drawRect(rect, trivial),
        "Embers": _embers_draw(w, h),
    }


def measure(size: Tuple[int, int], repeats: int = 3) -> Dict[str, float]:
    """Best ms a frame of each case at ``size`` (one warm-up draw first)."""
    w, h = size
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    out: Dict[str, float] = {}
    for name, draw in _cases(w, h).items():
        draw(canvas)
        surface.makeImageSnapshot()
        best = float("inf")
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            draw(canvas)
            surface.makeImageSnapshot()
            best = min(best, time.perf_counter() - t0)
        out[name] = best * 1000.0
    return out


def _size(text: str) -> Tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=_size, default=(800, 500), help="WxH (default 800x500)")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args(argv)
    w, h = args.size
    print(f"{platform.system()} {platform.release()}, {platform.machine()}, "
          f"{platform.processor() or 'cpu ?'}, {os.cpu_count()} threads")
    print(f"Python {platform.python_version()}, {skia_build()}")
    print(f"{w} x {h} raster, best of {args.repeats}:")
    for name, ms in measure(args.size, args.repeats).items():
        print(f"  {name:<17} {ms:9.1f} ms  {ms * 1e6 / (w * h):8.1f} ns/px")


if __name__ == "__main__":
    main()
