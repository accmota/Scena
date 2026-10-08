# Benchmarks

Parametrized performance probes. Shared harness: [`harness.py`](harness.py).

**Start here:** [dashboard.md](dashboard.md) — one-glance status of every tracked pulse (last run, headline, trend, freshness). Refresh with `python scripts/bench/dashboard.py`. Run the full battery with `python scripts/bench/run_all.py`.

| Pulse | Log | Runner |
|------|-----|--------|
| Overall mix (cpu/gpu/live/soak) | [balanced.md](balanced.md) | `python scripts/bench/run_balanced.py` |
| Scheduler (process / events / rides) | [sched.md](sched.md) | `python scripts/bench/sched.py --pulse` |
| FX cost matrix | [fx.md](fx.md) | `python scripts/bench/run_fx.py` |
| Text / HUD | [text.md](text.md) | `python scripts/bench/perf_text.py --pulse` |
| Reactive graph | [graph.md](graph.md) | `python scripts/bench/run_graph.py` |
| Resolve (balls + platformer) | [resolve.md](resolve.md) | `python scripts/bench/run_resolve.py` |
| Background / camera / parallax | [background.md](background.md) | `python scripts/bench/perf_background.py --pulse` |
| Startup + warm-up | [startup.md](startup.md) | `python scripts/bench/perf_startup.py --pulse` |
| Asset first-use | [assets.md](assets.md) | `python scripts/bench/perf_assets.py --pulse` |
| Long run (jitter / GC / drift, 5 min) | [longrun.md](longrun.md) | `python scripts/bench/longrun.py --pulse` (or `run_all.py --long`) |
| Guard cost (ScalarSlot write, `keyp()`) | — | `python scripts/bench/perf_guards.py` |
| Swept detection for fast bodies (slow scene must stay free; bullet-hell and fast-laser cost; `--sweep-off` in-process A/B) | 2026-10-05: slow 0.69 ms with `fast 0`, interleaved A/B vs the previous tree within noise; hell (300 r=3 bullets at 400 DU/s, all fast) 4.17 vs 3.79 ms off; laser (10 at 5000 DU/s) 0.98 vs 0.83 ms off, 12.0 hits/frame vs 10.3 (this machine) | `python scripts/bench/perf_collision_fast.py [--mode slow\|hell\|laser] [--bullets 300] [--radius 3] [--speed 400] [--shots 10] [--ladder] [--sweep-off]` |
| Hitbox parts (body vs `add_hitbox` silhouette vs `px_rect` part with a linked `active`, N animated sprites) | 2026-09-28, n=100: body 0.75 ms, silhouette parts +1.09 ms, linked px parts +0.48 ms per step (this machine; ×4 target) | `python scripts/bench/perf_hitbox_parts.py [--mode body\|parts\|linked\|both\|all] [--n 100] [--rotation 1.5] [--tilt 12]` |

**Jitter in an app?** `python scripts/bench/jitter_probe.py examples/naves.py --seconds 120` runs any script unmodified in the product loop and reports held/dropped frames against the real vsync timeline (macOS), the latch-free vblank grid check (vblanks per present), the pacer strategy and CPU %, hitches with their cause (GC / phase / pacing / present), and memory drift. A/B flags: `--present auto|vsync60|vsync30|vsync|fixed60|fixed30|none` (sets `canvas.framerate`; `none` = `"max"`), `--gc-freeze`. See [longrun.md](longrun.md) for how to read it.

Every snapshot records a **scena fingerprint** (content hash of `scena/`) so two rows can be compared for "did the code change" without git. Shared helper: [`fingerprint.py`](fingerprint.py).

## Rules

- Isolate one axis per script; then mix (`cpu_mix`, `gpu_mix`, `live_mix`).
- Ladders: `--ladder 50,200,800` and `--quality`.
- Uncapped FPS; report `work_ms` + phases.
- Fixed design==window pixels when comparing FPS.
- Framebuffer scale is part of a GPU workload. The window follows the display it opens on (Retina 2× vs an external 1×), so a GPU cell is only compared with a row at the same FB: `balanced-2` stamps it (`§` = 1×) and its auto-diff skips other scales (`pulse.fb_scale_tag` / `cell_fb_tag`). Runners that do not record FB (sched / graph / text / fx / background) cannot tell — if a GPU-heavy cell jumps, check which display the window used.
- JSON dumps → `results/` (gitignored) or `/tmp`.
- Runners **append** their pulse log (summary row + run subsection). `--no-append` prints only.

## Suite

| Kind | Scripts |
|------|---------|
| Harness | `harness.py` (replica loop, cost isolates), `frame_probe.py` (wraps the **real** loop: pacing, present, GC, vsync), `perf_profile.py` (shim), `fingerprint.py`, `pulse.py`, `dashboard.py` |
| Isolate | moved `perf_*` (draw, reactive, collision, resolve balls + platformer, FX matrix, text, background, startup, assets, …); [`sched.py`](sched.py) (move_along / tween / after·every / @when / process) |
| Mix | `cpu_mix.py`, `gpu_mix.py`, `live_mix.py`, `isolat.py` |
| Soak | [`soak_leak.py`](soak_leak.py) — create/destroy + FX churn; RSS / idle work_ms / live counts. [`longrun.py`](longrun.py) — minutes in the product loop: jitter, GC, drift |
| Diagnose | [`jitter_probe.py`](jitter_probe.py) — any script under `frame_probe` · [`load_burst.py`](load_burst.py) — background CPU load for a set window (FX Auto stability checks) |
| Windows | [`win/`](win/) — `win_jitter_probe.py` (jitter_probe with a DWM / D3DKMT vsync clock + Windows RSS; patches only its own process), `win_vsync.py` (vsync source check), `win_env.py` (host timing facts), `win_summary.py` (runs table). Procedure: [longrun.md — Still to run on Windows](longrun.md) |
| Churn | [`fx_churn.py`](fx_churn.py) — cycle canvas posts / shape looks then none; leftover inventory + GPU-path A/B |
| Historical | [`historical/`](historical/) — frozen fx_lab2 / scene_demo `--bench` |

```bash
python scripts/bench/run_all.py
python scripts/bench/run_balanced.py
python scripts/bench/sched.py --pulse
python scripts/bench/run_fx.py
python scripts/bench/perf_text.py --pulse
python scripts/bench/run_graph.py
python scripts/bench/run_resolve.py
python scripts/bench/perf_background.py --pulse
python scripts/bench/perf_startup.py --pulse
python scripts/bench/perf_assets.py --pulse
python scripts/bench/longrun.py --pulse
python scripts/bench/jitter_probe.py examples/naves.py --seconds 120
python scripts/bench/perf_resolve_platformer.py --bench --balls 50 --duration 3
python scripts/bench/live_mix.py --bench --duration 3
python scripts/bench/soak_leak.py --cycles 30 --json /tmp/soak.json
python scripts/bench/fx_churn.py --quick
python scripts/bench/historical/fx_lab2.py --bench --canvas none --visual none --duration 2
```
