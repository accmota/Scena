"""One-shot FX cost matrix: per-effect frame time across FxQuality levels.

Reports average ms/frame (primary), FPS, and cost factor vs same-quality
baseline. Primary ranking uses quality=high (not full).

    python scripts/perf_fx_matrix.py
    python scripts/perf_fx_matrix.py --duration 0.9 --n 48
    python scripts/perf_fx_matrix.py --quality high --effect shape_glow
    python scripts/perf_fx_matrix.py --json /tmp/fx_matrix.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--duration", type=float, default=1.0)
parser.add_argument("--warmup", type=float, default=0.35)
parser.add_argument("--n", type=int, default=48)
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--height", type=int, default=700)
parser.add_argument("--quality", default=None, help="single quality; omit for all")
parser.add_argument("--effect", default=None, help="single effect key; omit for all")
parser.add_argument(
    "--category", default=None,
    help="run only this category: none|shape|visual|canvas|transient|spatial",
)
parser.add_argument(
    "--json", dest="json_path", default=None,
    help="write full results as JSON to this path",
)
parser.add_argument(
    "--log", dest="log_path", default=None,
    help="also tee console output to this path (written by process, no shell pipe)",
)
parser.add_argument("--rank-quality", default="high",
                    help="quality used for primary ranking (default high)")
parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--effect-key", default="baseline", help=argparse.SUPPRESS)
parser.add_argument("--q", default="high", help=argparse.SUPPRESS)
args = parser.parse_args()

# (key, category)
EFFECTS = [
    ("baseline", "none"),
    # --- shape filters (shared batchable instance) ---
    ("shape_blur", "shape"),
    ("shape_glow", "shape"),
    ("shape_shadow", "shape"),
    ("shape_dilate", "shape"),
    ("shape_erode", "shape"),
    # --- shape visuals (shared instance unless noted) ---
    ("visual_paint", "visual"),
    ("visual_fill", "visual"),
    ("visual_stroke", "visual"),
    ("visual_glow", "visual"),
    ("visual_neon", "visual"),
    ("visual_neon_unique", "visual"),
    ("visual_multiborder", "visual"),
    ("visual_extrude", "visual"),
    ("visual_shieldring", "visual"),
    ("visual_aura", "visual"),
    ("visual_aurafill", "visual"),
    ("visual_phantom", "visual"),
    ("visual_shieldgear", "visual"),
    ("visual_electricfield", "visual"),
    ("visual_organicoutline", "visual"),
    ("visual_tracer", "visual"),
    ("visual_electricbolt", "visual"),
    ("visual_laser", "visual"),
    ("visual_ink", "visual"),
    ("visual_ink_bleed", "visual"),
    ("visual_edgeglow", "visual"),
    ("visual_gel", "visual"),
    ("visual_water", "visual"),
    ("visual_swell", "visual"),
    ("visual_flame", "visual"),
    ("visual_metal", "visual"),
    ("visual_sphere", "visual"),
    ("visual_wave", "visual"),
    ("visual_aurora", "visual"),
    ("visual_liquify", "visual"),
    ("visual_bolt", "visual"),
    ("visual_tail", "visual"),
    ("visual_beat", "visual"),
    ("visual_insetrim", "visual"),
    ("visual_shield", "visual"),
    ("visual_shield_halo", "visual"),
    ("visual_shield_nebula", "visual"),
    ("visual_shield_molten", "visual"),
    ("visual_shield_vortex", "visual"),
    # --- canvas fixed / continuous / forced-transient ---
    ("vignette", "canvas"),
    ("grain", "canvas"),
    ("bloom", "canvas"),
    ("grade", "canvas"),
    ("chroma", "canvas"),
    ("pixelate", "canvas"),
    ("scanlines", "canvas"),
    ("screenblur", "canvas"),
    ("distant", "canvas"),
    ("fog", "canvas"),
    ("haze", "canvas"),
    ("crt", "canvas"),
    ("vortex", "canvas"),
    ("zoomblur", "canvas"),
    ("prism", "canvas"),
    ("perspective", "canvas"),
    ("kaleido", "canvas"),
    ("lamp", "canvas"),
    ("spotlight", "canvas"),
    ("rays", "canvas"),
    ("trails", "canvas"),
    ("flash_static", "canvas"),
    ("hit_ripple", "canvas"),
    ("hit_wave", "canvas"),
    ("hit_explosion", "canvas"),
    ("hit_burst", "canvas"),
    ("hit_bubbles", "canvas"),
    ("hit_glitch", "canvas"),
    ("flash_pulse", "canvas"),
    ("shake_pulse", "canvas"),
    ("colorsweep", "canvas"),
    ("plasmawash", "canvas"),
    ("nebulabloom", "canvas"),
    # --- shape transients (sustained re-arm every frame) ---
    ("xf_dissolve_noise", "transient"),
    ("xf_dissolve_vortex", "transient"),
    ("xf_dissolve_wipe", "transient"),
    ("xf_burn", "transient"),
    ("xf_implode", "transient"),
    ("xf_fade_out", "transient"),
    ("xf_fade_in", "transient"),
    ("xf_dissolve_in", "transient"),
    ("xf_flash", "transient"),
    ("xf_blink", "transient"),
    ("xf_pulse", "transient"),
    ("xf_pop", "transient"),
    ("xf_knock", "transient"),
    ("xf_spark", "transient"),
    # --- SpatialFx (same movers + emitters) ---
    ("spatial_campfire", "spatial"),
    ("spatial_fire_plume", "spatial"),
    ("spatial_fire_tongues", "spatial"),
    ("spatial_fire_embers", "spatial"),
    ("spatial_rain", "spatial"),
    ("spatial_jet", "spatial"),
    ("spatial_sparks", "spatial"),
    ("spatial_glowspot", "spatial"),
]

QUALITIES = ("low", "medium", "high", "max")
# Adjacent pairs for ladder analysis (higher_fidelity, lower_fidelity)
QUALITY_ADJACENT = (
    ("max", "high"),   # batch off → batch on + post ½
    ("high", "low"),   # full multipass → survival lite + scales
)
NOISE_PCT = 10.0  # < this Δms% between adjacent → quality-flat for that pair


def _fps_to_ms(fps):
    if fps is None or fps <= 0:
        return None
    return 1000.0 / fps


def _cost_factor(base_fps, fps):
    """Frame-time ratio vs baseline (1.0 = same as baseline; higher = slower)."""
    if base_fps is None or fps is None or fps <= 0 or base_fps <= 0:
        return None
    return base_fps / fps


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
if not args.worker:
    # Tee stdout into --log without forcing the shell to pipe (sandbox-friendly).
    _log_fp = None
    if args.log_path:
        _log_fp = open(args.log_path, "w", buffering=1, encoding="utf-8")
        _real_stdout = sys.stdout

        class _Tee:
            def write(self, s):
                _real_stdout.write(s)
                _log_fp.write(s)

            def flush(self):
                _real_stdout.flush()
                _log_fp.flush()

            def fileno(self):
                return _real_stdout.fileno()

            def isatty(self):
                return _real_stdout.isatty()

        sys.stdout = _Tee()  # type: ignore

    script = os.path.abspath(__file__)
    qualities = [args.quality] if args.quality else list(QUALITIES)
    effects = list(EFFECTS)
    if args.effect:
        effects = [e for e in EFFECTS if e[0] == args.effect]
    if args.category:
        cat = args.category.strip().lower()
        effects = [e for e in effects if e[1] == cat]
    # Always measure baseline alongside so cost factors / rank work
    if not any(e[0] == "baseline" for e in effects):
        effects = [("baseline", "none")] + effects

    print(
        f"=== FX cost matrix  n={args.n}  {args.width}x{args.height}  "
        f"dur={args.duration}s  rank_q={args.rank_quality} ===",
        flush=True,
    )
    results = {}  # (effect, q) -> fps
    for key, _kind in effects:
        for q in qualities:
            cmd = [
                sys.executable, script, "--worker",
                "--effect-key", key, "--q", q,
                "--n", str(args.n),
                "--duration", str(args.duration),
                "--warmup", str(args.warmup),
                "--width", str(args.width),
                "--height", str(args.height),
            ]
            # Hard cap so a stuck GLFW worker cannot freeze the full matrix
            timeout_s = max(45.0, args.warmup + args.duration + 25.0)
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                rc = proc.returncode
            except subprocess.TimeoutExpired as exc:
                # Best-effort kill if still around
                try:
                    if exc.stdout:
                        pass
                except Exception:
                    pass
                results[(key, q)] = None
                print(f"{key:<22} {q:<10} TIMEOUT({timeout_s:.0f}s)", flush=True)
                time.sleep(0.3)
                continue
            except Exception as exc:
                results[(key, q)] = None
                print(f"{key:<22} {q:<10} FAIL({exc})", flush=True)
                continue
            fps = None
            for line in out.splitlines():
                if line.startswith("FPS:"):
                    try:
                        fps = float(line.split(":")[1].strip())
                    except ValueError:
                        pass
            results[(key, q)] = fps
            ms = _fps_to_ms(fps)
            if fps is None:
                cell = "FAIL"
            else:
                cell = f"{ms:.2f}ms ({fps:.0f}fps)"
            print(f"{key:<22} {q:<10} {cell}", flush=True)
            if fps is None:
                err_tail = out.strip()[-800:] if out.strip() else "(no output)"
                print(f"  !! worker failed rc={rc}: {err_tail}", flush=True)
            time.sleep(0.05)

    # ---- Summary tables ----
    print("\n" + "=" * 72)
    print("BASELINE-NORMALIZED COST  (cost × / ms @ quality)")
    print("cost = T_effect / T_baseline  (higher = more expensive)")
    print("=" * 72)
    for q in qualities:
        base = results.get(("baseline", q))
        base_ms = _fps_to_ms(base)
        if not base:
            continue
        print(
            f"\n### quality={q}  baseline={base_ms:.3f} ms  ({base:.0f} fps)",
        )
        print(f"{'effect':<22} {'ms':>8} {'fps':>7} {'cost×':>8}")
        for key, _k in effects:
            fps = results.get((key, q))
            ms = _fps_to_ms(fps)
            cf = _cost_factor(base, fps)
            if ms is None:
                print(f"{key:<22} {'?':>8}")
                continue
            print(f"{key:<22} {ms:8.3f} {fps:7.0f} {cf:8.2f}")

    # ---- Primary ranking @ rank-quality ----
    rq = args.rank_quality
    if rq in qualities or (args.quality is None and rq in QUALITIES):
        base_rq = results.get(("baseline", rq))
        rows = []
        for key, kind in effects:
            if key == "baseline":
                continue
            fps = results.get((key, rq))
            ms = _fps_to_ms(fps)
            if ms is None:
                continue
            cf = _cost_factor(base_rq, fps)
            base_ms = _fps_to_ms(base_rq) or 0.0
            extra_ms = ms - base_ms if base_rq else None
            rows.append((key, kind, ms, fps, cf, extra_ms))
        rows.sort(key=lambda r: r[2], reverse=True)  # slowest first
        print("\n" + "=" * 72)
        print(f"RANK @ quality={rq}  (slowest first by ms/frame)")
        print("=" * 72)
        print(
            f"{'#':>3} {'effect':<22} {'cat':<10} {'ms':>8} {'fps':>7} "
            f"{'cost×':>7} {'+ms':>8}"
        )
        for i, (key, kind, ms, fps, cf, extra) in enumerate(rows, 1):
            extra_s = f"{extra:+.3f}" if extra is not None else "?"
            cf_s = f"{cf:7.2f}" if cf is not None else f"{'?':>7}"
            print(
                f"{i:3d} {key:<22} {kind:<10} {ms:8.3f} {fps:7.0f} "
                f"{cf_s} {extra_s:>8}"
            )

        # Also low column if available and different from rank
        bq = "low"
        if bq != rq and (bq in qualities or args.quality is None):
            base_b = results.get(("baseline", bq))
            print(f"\n--- secondary @ quality={bq} (top 15 by ms) ---")
            brows = []
            for key, kind in effects:
                if key == "baseline":
                    continue
                fps = results.get((key, bq))
                ms = _fps_to_ms(fps)
                if ms is None:
                    continue
                cf = _cost_factor(base_b, fps)
                brows.append((key, kind, ms, fps, cf))
            brows.sort(key=lambda r: r[2], reverse=True)
            for i, (key, kind, ms, fps, cf) in enumerate(brows[:15], 1):
                cf_s = f"{cf:7.2f}" if cf is not None else f"{'?':>7}"
                print(f"{i:3d} {key:<22} {kind:<10} {ms:8.3f} {fps:7.0f} {cf_s}")

    # ---- Quality ladder ----
    if len(qualities) >= 2 or (args.quality is None and len(QUALITIES) >= 2):
        qset = set(qualities) if args.quality else set(QUALITIES)
        print("\n" + "=" * 72)
        print(
            f"QUALITY LADDER  (|Δms| ≥ {NOISE_PCT:.0f}% of slower = sensitive; "
            "else flat for that pair)"
        )
        print("=" * 72)
        # per-pair: collect % savings when dropping quality (ms_hi - ms_lo) / ms_hi
        pair_stats = {pair: [] for pair in QUALITY_ADJACENT if pair[0] in qset and pair[1] in qset}

        for key, kind in effects:
            line_bits = [f"{key:<22}"]
            for hi, lo in QUALITY_ADJACENT:
                if hi not in qset or lo not in qset:
                    continue
                ms_hi = _fps_to_ms(results.get((key, hi)))
                ms_lo = _fps_to_ms(results.get((key, lo)))
                if ms_hi is None or ms_lo is None or ms_hi <= 0:
                    line_bits.append(f"{hi[0]}→{lo[0]}:?")
                    continue
                # positive pct = lo is faster (good for lower quality)
                pct = 100.0 * (ms_hi - ms_lo) / ms_hi
                flag = "S" if abs(pct) >= NOISE_PCT else "F"
                pair_stats[(hi, lo)].append((key, kind, pct, flag))
                line_bits.append(f"{hi[0]}→{lo[0]}:{pct:+5.1f}%{flag}")
            print("  ".join(line_bits))

        print("\n### Ladder summary (median Δms% — all vs scale-sensitive subsets)")
        print(f"{'pair':<20} {'all_med%':>9} {'shape%':>8} {'post-ish%':>9} {'spatial%':>9}  note")
        for pair, samples in pair_stats.items():
            if not samples:
                continue
            pcts_all = sorted(s[2] for s in samples if s[0] != "baseline")
            shape_p = sorted(s[2] for s in samples if s[1] == "shape")
            # canvas quality-sensitive ops: bloom/vignette/screenblur etc still listed canvas
            canvas_p = sorted(s[2] for s in samples if s[1] == "canvas")
            spat_p = sorted(s[2] for s in samples if s[1] == "spatial")

            def _med(xs):
                return xs[len(xs) // 2] if xs else float("nan")

            med_all = _med(pcts_all)
            med_shape = _med(shape_p)
            med_canvas = _med(canvas_p)
            med_spat = _med(spat_p)
            # Decision weights shape + spatial more than all-inventory multipass noise
            decision = abs(med_shape) if shape_p else abs(med_all)
            if pair == ("max", "high") and shape_p and med_shape >= NOISE_PCT:
                note = "KEEP max as batch-off escape"
            elif decision < NOISE_PCT and (not spat_p or abs(med_spat) < NOISE_PCT):
                note = "COLLAPSE candidate"
            else:
                note = "KEEP step"
            print(
                f"{pair[0]}→{pair[1]:<10} {med_all:9.1f} {med_shape:8.1f} "
                f"{med_canvas:9.1f} {med_spat:9.1f}  {note}"
            )

        print(
            "\nRecommendation heuristic: drop steps that are flat on both shape "
            f"filters and SpatialFx (median |Δ| < {NOISE_PCT:.0f}%); always keep "
            "max as batch-off reference if max→high is shape-sensitive."
        )

    # JSON dump
    if args.json_path:
        payload = {
            "meta": {
                "n": args.n,
                "width": args.width,
                "height": args.height,
                "duration": args.duration,
                "warmup": args.warmup,
                "rank_quality": args.rank_quality,
                "qualities": list(qualities),
            },
            "results": {
                f"{k}|{q}": {
                    "fps": fps,
                    "ms": _fps_to_ms(fps),
                }
                for (k, q), fps in results.items()
            },
            "effects": [{"key": k, "category": c} for k, c in effects],
        }
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\nWrote JSON → {args.json_path}", flush=True)

    if _log_fp is not None:
        sys.stdout = _real_stdout
        _log_fp.close()
        print(f"Wrote log → {args.log_path}", flush=True)

    sys.exit(0)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

W, H = args.width, args.height
key = args.effect_key
q = args.q

init(width=W, height=H, title=f"bench {key}/{q}")
fw = ScenaFramework.get_instance()
fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))

canvas.background = (0.06, 0.07, 0.10, 1)
set_fx_auto(False)
canvas.fx_quality = q
# Honor quality preset for batch (full → False); do not force True.

cols = max(1, int(math.sqrt(args.n * W / H)))
rows = max(1, math.ceil(args.n / cols))
movers = []
_spatial = []


def _mk_shape(i, x, y):
    kind = i % 4
    if kind == 0:
        return Circle(center=(x, y), radius=12 + (i % 4))
    if kind == 1:
        return Square(center=(x, y), length=18 + (i % 3), angle=i * 7)
    if kind == 2:
        return EquilateralTriangle(center=(x, y), radius=12, angle=i * 5)
    return RegularPolygon(n=5, center=(x, y), radius=11, angle=i * 9)


for i in range(args.n):
    c = i % cols
    r = i // cols
    x = 50 + c * ((W - 100) / max(cols - 1, 1))
    y = 50 + r * ((H - 100) / max(rows - 1, 1))
    shp = _mk_shape(i, x, y)
    shp.set_color(("cyan", "magenta", "gold", "lime", "orange", "white")[i % 6])
    if i % 2:
        shp.set_alpha(0.55)
    movers.append({"shape": shp, "hx": x, "hy": y, "a": i * 0.2})


def _shared_visual(visual):
    for m in movers:
        m["shape"].visual = visual


def _shared_stamp(attr: str, look):
    for m in movers:
        setattr(m["shape"], attr, look)


def _shared_filter(fx):
    for m in movers:
        m["shape"].fill_filter = fx


def _add_spatial(emitters):
    global _spatial
    _spatial = list(emitters)


# Apply effect
ok = True
if key == "baseline":
    pass
elif key == "shape_blur":
    _shared_filter(Blur())
elif key == "shape_glow":
    _shared_filter(GlowFilter())
elif key == "shape_shadow":
    _shared_filter(DropShadow())
elif key == "shape_dilate":
    _shared_filter(Dilate())
elif key == "shape_erode":
    _shared_filter(Erode())
elif key == "visual_paint":
    _shared_visual(Paint("steel blue"))
elif key == "visual_fill":
    _shared_visual(Fill("steel blue"))
elif key == "visual_stroke":
    _shared_visual(Stroke("cyan"))
elif key == "visual_glow":
    _shared_stamp("glow", Glow("cyan"))
elif key == "visual_neon":
    _shared_visual(Neon())
elif key == "visual_neon_unique":
    for m in movers:
        m["shape"].visual = Neon(amount=1.0 + (id(m) % 7) * 0.01)
elif key == "visual_multiborder":
    _shared_visual(MultiBorder())
elif key in ("visual_longshadow", "visual_extrude"):
    _shared_visual(Extrude())
elif key == "visual_shieldring":
    _shared_visual(DashRing())
elif key == "visual_aura":
    _shared_visual(Halo())
elif key == "visual_aurafill":
    _shared_visual(Halo(style="fill"))
elif key == "visual_phantom":
    _shared_visual(Halo(style="soft"))
elif key == "visual_shieldgear":
    _shared_visual(GearShell())
elif key == "visual_electricfield":
    _shared_visual(ElectricField())
elif key == "visual_organicoutline":
    _shared_visual(OrganicOutline())
elif key == "visual_tracer":
    _shared_visual(Tracer())
elif key == "visual_electricbolt":
    _shared_visual(ElectricBolt())
elif key == "visual_laser":
    _shared_visual(Laser())
elif key == "visual_ink":
    _shared_visual(Ink())
elif key == "visual_ink_bleed":
    _shared_visual(InkBleed())
elif key == "visual_edgeglow":
    _shared_visual(Rim())
elif key == "visual_gel":
    _shared_visual(Gel())
elif key == "visual_water":
    _shared_visual(Water())
elif key == "visual_swell":
    _shared_visual(Swell())
elif key == "visual_flame":
    _shared_visual(Flame())
elif key == "visual_metal":
    _shared_visual(Metal())
elif key == "visual_sphere":
    _shared_visual(Sphere())
elif key == "visual_wave":
    _shared_visual(Wave())
elif key == "visual_aurora":
    _shared_visual(Aurora())
elif key == "visual_liquify":
    _shared_visual(Liquify())
elif key == "visual_bolt":
    _shared_visual(Bolt())
elif key == "visual_tail":
    _shared_stamp("tail", Tail())
elif key == "visual_beat":
    _shared_visual(Beat())
elif key == "visual_insetrim":
    _shared_visual(InsetRim())
elif key == "visual_shield":
    _shared_visual(Shield())
elif key == "visual_shield_halo":
    _shared_visual(Shield(style="plasma"))
elif key == "visual_shield_nebula":
    _shared_visual(Shield(style="nebula"))
elif key == "visual_shield_molten":
    _shared_visual(Shield(style="molten"))
elif key == "visual_shield_vortex":
    _shared_visual(Shield(style="vortex"))
elif key == "vignette":
    canvas.effects.add(Vignette())
elif key == "grain":
    canvas.effects.add(Grain())
elif key == "bloom":
    canvas.effects.add(Bloom())
elif key == "grade":
    canvas.effects.add(Grade())
elif key == "chroma":
    canvas.effects.add(Chroma())
elif key == "pixelate":
    canvas.effects.add(Pixelate())
elif key == "scanlines":
    canvas.effects.add(Scanlines())
elif key == "screenblur":
    canvas.effects.add(ScreenBlur())
elif key == "distant":
    canvas.effects.add(DistantLight())
elif key == "fog":
    canvas.effects.add(Fog())
elif key == "haze":
    canvas.effects.add(Haze())
elif key == "crt":
    canvas.effects.add(Crt())
elif key == "vortex":
    canvas.effects.add(Vortex())
elif key == "zoomblur":
    canvas.effects.add(ZoomBlur())
elif key == "prism":
    canvas.effects.add(Prism())
elif key == "perspective":
    canvas.effects.add(Perspective())
elif key == "kaleido":
    canvas.effects.add(Kaleidoscope())
elif key == "lamp":
    canvas.effects.add(Lamp())
elif key == "spotlight":
    canvas.effects.add(Spotlight())
elif key == "rays":
    canvas.effects.add(GodRays())
elif key == "trails":
    canvas.effects.add(MotionTrail())
elif key == "flash_static":
    canvas.effects.add(Wash(intensity=0.25))
elif key in (
    "hit_ripple", "hit_wave", "hit_explosion", "hit_burst", "hit_bubbles",
    "hit_glitch", "shake_pulse", "flash_pulse",
):
    pass  # re-triggered each frame
elif key.startswith("xf_"):
    pass  # re-armed each frame in update
elif key == "spatial_campfire":
    n_emit = 6
    for i in range(n_emit):
        x = 100 + (i % 3) * 300
        y = 150 + (i // 3) * 280
        _spatial.append(Fire(center=(x, y), radius=36))
elif key == "spatial_fire_plume":
    for i in range(6):
        x = 100 + (i % 3) * 300
        y = 150 + (i // 3) * 280
        _spatial.append(Fire(style="plume", center=(x, y), width=34))
elif key == "spatial_fire_tongues":
    for i in range(6):
        x = 100 + (i % 3) * 300
        y = 150 + (i // 3) * 280
        _spatial.append(Fire(style="tongues", center=(x, y), width=34))
elif key == "spatial_fire_embers":
    for i in range(6):
        x = 100 + (i % 3) * 300
        y = 150 + (i // 3) * 280
        _spatial.append(Fire(style="embers", center=(x, y), width=32))
elif key == "spatial_rain":
    _spatial.append(Rain(center=(W * 0.5, H * 0.5), width=W * 0.9, height=H * 0.9, amount=0.9))
elif key == "spatial_jet":
    for i in range(4):
        x = 150 + i * 200
        y = 200 + (i % 2) * 220
        _spatial.append(Jet(origin=(x, y), angle=180 + i * 20, length=120, width=14))
elif key == "spatial_sparks":
    for i in range(6):
        x = 100 + (i % 3) * 300
        y = 150 + (i // 3) * 280
        _spatial.append(Sparks(center=(x, y), rate=40))
elif key == "spatial_glowspot":
    for i in range(8):
        x = 80 + (i % 4) * 240
        y = 140 + (i // 4) * 280
        col = ("cyan", "magenta", "gold", "lime", "orange", "orchid", "tomato", "white")[i]
        _spatial.append(GlowSpot(center=(x, y), radius=48, color=col))
elif key == "colorsweep":
    canvas.effects.add(ColorSweep())
elif key == "plasmawash":
    canvas.effects.add(ColorWash())
elif key == "nebulabloom":
    canvas.effects.add(CosmicBloom())
else:
    ok = False

if not ok:
    print("FPS: 0", flush=True)
    sys.exit(1)


def _rearm_shape_transients():
    """Keep channels active: re-install every frame so they never finish."""
    long = 2.0  # well above frame duration
    for m in movers:
        s = m["shape"]
        s.visible = True
        if key == "xf_dissolve_noise":
            s.dissolve_out(long, style="noise")
        elif key == "xf_dissolve_vortex":
            s.dissolve_out(long, style="vortex")
        elif key == "xf_dissolve_wipe":
            s.dissolve_out(long, style="wipe")
        elif key == "xf_burn":
            s.burn_out(long)
        elif key == "xf_implode":
            s.implode(long)
        elif key == "xf_fade_out":
            s.fade_out(long)
        elif key == "xf_fade_in":
            s.fade_in(long)
        elif key == "xf_dissolve_in":
            s.dissolve_in(long, style="noise")
        elif key == "xf_flash":
            s.flash(long)
        elif key == "xf_blink":
            s.blink(duration=long, rate=9.0)
        elif key == "xf_pulse":
            s.pulse_outline(duration=long)
        elif key == "xf_pop":
            s.pop(long, scale=1.25)
        elif key == "xf_knock":
            s.knock(distance=12, angle=30, duration=long)
        elif key == "xf_spark":
            s.spark_burst(duration=long)


_start = None
_warm = False
_frames = []


def update(dt):
    global _start, _warm
    t = clock.time
    for m in movers:
        m["shape"].move_to(
            m["hx"] + math.sin(t * 1.7 + m["a"]) * 14,
            m["hy"] + math.cos(t * 1.3 + m["a"]) * 10,
        )
        m["shape"].rotate_by(40 * dt)

    # Canvas hit / pulse: worst-case always-on
    if key == "hit_ripple":
        canvas.ripple_at(W * 0.5, H * 0.5, amount=1.0)
    elif key == "hit_wave":
        canvas.wave_at(W * 0.5, H * 0.5, angle=0.0, amount=1.0)
    elif key == "hit_explosion":
        canvas.explosion_at(W * 0.5, H * 0.5, amount=1.0)
    elif key == "hit_burst":
        canvas.burst_at(W * 0.40, H * 0.45, radius=36.0)
        canvas.burst_at(W * 0.55, H * 0.52, radius=28.0)
        canvas.burst_at(W * 0.48, H * 0.60, radius=48.0)
        canvas.burst_at(W * 0.62, H * 0.40, radius=32.0)
    elif key == "hit_bubbles":
        canvas.bubbles_at(W * 0.45, H * 0.35, count=24, height=180)
        canvas.bubbles_at(W * 0.60, H * 0.40, count=18, height=140)
    elif key == "flash_pulse":
        canvas.flash(0.9)
    elif key == "shake_pulse":
        canvas.shake(14.0)
    elif key == "hit_glitch":
        canvas.glitch(1.0)
    elif key.startswith("xf_"):
        _rearm_shape_transients()

    now = time.perf_counter()
    if _start is None:
        _start = now
        return
    elapsed = now - _start
    if not _warm:
        if elapsed >= args.warmup:
            _warm = True
            _start = now
            _frames.clear()
        return
    _frames.append(dt if dt > 0 else 1e-3)
    if elapsed >= args.duration:
        if _frames:
            avg = sum(_frames) / len(_frames)
            fps = 1.0 / avg if avg > 0 else 0.0
        else:
            fps = 0.0
        ms = 1000.0 / fps if fps > 0 else 0.0
        print(f"FPS: {fps:.2f}", flush=True)
        print(f"MS: {ms:.4f}", flush=True)
        try:
            import glfw
            glfw.set_window_should_close(fw._window, True)
        except Exception:
            os._exit(0)


canvas.framerate = "max"
run()
