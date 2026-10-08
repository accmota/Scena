# Startup + warm-up isolate

Time to first frame, and what the **first seconds** cost compared with steady state. Closes the "Startup / import / GLFW+Skia init" blind spot (proposal 4.4), widened on purpose: the gap that users actually feel is not only launch time but the stutter right after launch, while caches fill.

Script: [`perf_startup.py`](perf_startup.py). Per-frame timing: [`frame_probe.py`](frame_probe.py) (real run loop).

## Why

A beginner's first impression is the launch. Two things matter: how long until something is on screen (`ttff`), and whether the first seconds hitch (Skia shader programs, glyph atlases, lazy image decode, first-touch graph slots, young-heap GC). Warm-up hitches are invisible to every other pulse — they all discard warm-up on purpose.

## What it scores

Each sample is a **fresh process** (warm OS file cache and `.pyc`: a second launch, not a first-ever one). Times are from the parent's spawn; `perf_counter` is system-wide on macOS/Linux.

| Stage | What |
|-------|------|
| `python_ms` | spawn → first line (interpreter + site) |
| `import_ms` | `import scena` (skia, glfw, numpy, SkSL compile at import) |
| `build_ms` | construct the scene: sky + stars + vignette, 12 atlas sprites, 60 shapes, 4 HUD texts (one with Glow) |
| `window_ms` | `open_window` (GLFW window + GL + Skia surface) |
| `first_ms` | first frame through present (includes lazy first-use work) |
| `ttff_ms` | spawn → first frame presented. **Primary.** |
| `warm_excess_ms` | Σ max(0, work − steady p50) over frames in the first 2 s (steady = seconds 3–4, uncapped) |
| `warm_spikes` | frames in the first 2 s with work > 2× steady p50 + 1 ms |
| `warm_worst_ms` | worst single frame in the first 2 s |

## How to run

From the **repo root**.

```bash
python scripts/bench/perf_startup.py --pulse
python scripts/bench/perf_startup.py                 # 5 launches, print only
python scripts/bench/perf_startup.py --headless      # python + import only, no window (CI-safe)
```

## Protocol `startup-1`

Bump this id if you change [`perf_startup.py`](perf_startup.py), [`frame_probe.py`](frame_probe.py), or the scene.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| pulse | `--pulse` (5 fresh launches) | Median per stage. |

**Noise rule.** Median of 5 launches. `ttff` / `import` include OS work (dyld, window server): treat **≲10%** as noise, **≳20%** as noteworthy. `warm_*` are small sums of spikes — compare spike counts, not percentages.

## Summary

Newest first. Primary: median **ttff_ms**.

| Date | Protocol | Host | ttff ms | import | build | window | first frame | warm excess ms (spikes) | Notes |
|------|----------|------|--------:|-------:|------:|-------:|------------:|------------------------:|-------|
| 2026-09-29 | `startup-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 474 | 184 | 25 | 120 | 54.2 | 93.9 (1) | |
| 2026-09-28 | `startup-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 405 | 182 | 26 | 95 | 22.1 | 37.3 (2) | |
| 2026-09-24 | `startup-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 401 | 180 | 25 | 95 | 22.1 | 38.9 (1) | |
| 2026-09-24 | `startup-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 459 | 177 | 20 | 118 | 54.8 | 87.0 (1) | |

---

## Runs

Newest first.

### 2026-09-29 — startup-1

| | |
|---|---|
| When | 2026-09-29 11:37 -0300 (14:37 UTC) |
| Protocol | `startup-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Launches | 5 fresh processes (median) |
| Scripts | `perf_startup.py` `e79887a1dcdc` · `frame_probe.py` `6e76703d984f` |

| Stage | median ms | min–max |
|-------|---------:|--------:|
| python_ms | 27.31 | 24.58–31.42 |
| import_ms | 184.02 | 181.66–186.82 |
| build_ms | 24.61 | 24.17–24.81 |
| window_ms | 120.32 | 113.80–124.61 |
| first_ms | 54.25 | 51.71–55.55 |
| ttff_ms | 474.35 | 461.28–479.06 |
| warm_excess_ms | 93.85 | 83.74–108.40 |
| warm_spikes | 1.00 | 1.00–1.00 |
| warm_worst_ms | 50.40 | 48.03–51.77 |
| steady_work_ms | 0.69 | 0.69–0.70 |

### 2026-09-28 — startup-1

| | |
|---|---|
| When | 2026-09-28 21:23 -0300 (00:23 UTC) |
| Protocol | `startup-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Launches | 5 fresh processes (median) |
| Scripts | `perf_startup.py` `e79887a1dcdc` · `frame_probe.py` `6e76703d984f` |

| Stage | median ms | min–max |
|-------|---------:|--------:|
| python_ms | 24.20 | 22.85–29.60 |
| import_ms | 181.73 | 175.31–195.89 |
| build_ms | 25.67 | 24.58–28.17 |
| window_ms | 94.79 | 93.22–127.50 |
| first_ms | 22.10 | 21.82–24.00 |
| ttff_ms | 404.68 | 399.23–467.57 |
| warm_excess_ms | 37.34 | 32.89–124.22 |
| warm_spikes | 2.00 | 1.00–2.00 |
| warm_worst_ms | 17.56 | 17.42–19.27 |
| steady_work_ms | 0.70 | 0.69–0.72 |

### 2026-09-24 — startup-1

| | |
|---|---|
| When | 2026-09-24 20:29 -0300 (23:29 UTC) |
| Protocol | `startup-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Launches | 5 fresh processes (median) |
| Scripts | `perf_startup.py` `436b7cc4689c` · `frame_probe.py` `12f9864ac18b` |

| Stage | median ms | min–max |
|-------|---------:|--------:|
| python_ms | 24.75 | 23.50–28.21 |
| import_ms | 180.33 | 176.38–200.76 |
| build_ms | 24.62 | 23.81–25.57 |
| window_ms | 94.81 | 91.95–114.93 |
| first_ms | 22.13 | 21.77–22.60 |
| ttff_ms | 400.80 | 395.11–456.09 |
| warm_excess_ms | 38.86 | 30.31–73.62 |
| warm_spikes | 1.00 | 1.00–2.00 |
| warm_worst_ms | 17.90 | 17.37–18.02 |
| steady_work_ms | 0.68 | 0.68–0.69 |

### 2026-09-24 — startup-1

| | |
|---|---|
| When | 2026-09-24 11:42 -0300 (14:42 UTC) |
| Protocol | `startup-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `4000c948cf65` |
| Launches | 5 fresh processes (median) |
| Scripts | `perf_startup.py` `436b7cc4689c` · `frame_probe.py` `12f9864ac18b` |

| Stage | median ms | min–max |
|-------|---------:|--------:|
| python_ms | 28.88 | 21.67–29.41 |
| import_ms | 176.52 | 167.93–178.87 |
| build_ms | 19.80 | 19.21–19.84 |
| window_ms | 118.04 | 99.10–127.63 |
| first_ms | 54.84 | 45.79–57.52 |
| ttff_ms | 459.11 | 422.59–470.30 |
| warm_excess_ms | 86.96 | 81.05–97.76 |
| warm_spikes | 1.00 | 1.00–1.00 |
| warm_worst_ms | 51.15 | 42.23–53.79 |
| steady_work_ms | 0.64 | 0.63–0.65 |

