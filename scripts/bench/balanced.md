# Balanced mix — historical log

Index: [dashboard.md](dashboard.md). Periodic overall pulse: CPU game load, product GPU mix, dense multipass grid, live composite, and leak/churn. Isolates stay out of this file — use them when a mix number moved (see [If a cell moved](#if-a-cell-moved)).

Compare **median `work_ms` and phases**, not raw FPS. Same machine, same protocol. All mix probes use the phase harness with design==window points (VSync off). Retina framebuffer scale is recorded; do not compare across displays.

## How to run

From the **repo root**. Close other GPU-heavy apps. Do not overlap windows.

```bash
python scripts/bench/run_balanced.py                  # 3 repeats, median; appends balanced.md
python scripts/bench/run_balanced.py --repeats 1      # debug
python scripts/bench/run_balanced.py --comparable     # later snapshots on this protocol
python scripts/bench/run_balanced.py --no-append      # print only
python scripts/bench/dashboard.py                     # refresh the index
```

The runner writes `scripts/bench/results/balanced_latest.json` (gitignored) and **appends** a summary row plus a **Runs** subsection (newest first). Use `--no-append` to preview. Every row records a **scena fingerprint** (content hash of `scena/`) next to the script fingerprint.

Frozen argv (also the runner’s probe list):

```bash
python scripts/bench/cpu_mix.py --bench --n 180 --duration 2 --warmup 0.5 --seed 42
python scripts/bench/gpu_mix.py --bench --mode realistic --quality high --duration 3 --warmup 0.5 --seed 42
python scripts/bench/gpu_mix.py --bench --mode heroes_mass --n-heroes 48 --quality high --duration 3 --warmup 0.5 --seed 42
python scripts/bench/live_mix.py --bench --n 80 --quality high --duration 3 --warmup 0.5 --seed 42
python scripts/bench/soak_leak.py --cycles 30 --idle-frames 40 --churn-frames 10 --quality high
```

Script hashes (must match the protocol table, or bump the protocol):

```bash
python -c "
import hashlib, pathlib
for p in ['cpu_mix.py','gpu_mix.py','live_mix.py','soak_leak.py','harness.py','run_balanced.py']:
    h = hashlib.sha256(pathlib.Path('scripts/bench', p).read_bytes()).hexdigest()[:12]
    print(f'{p:16} {h}')
"
```

## Protocol `balanced-2`

Bump this id (and mark the next snapshot **pro-forma**) if you change a mix/soak **script**, [`harness.py`](harness.py), [`run_balanced.py`](run_balanced.py), or any **frozen flag**. Pro-forma rows stay in the log so the break is visible; they are not 1:1 comparable to earlier protocol rows.

`balanced-1` used wall-clock `gpu_mix` frame time at `window_frac` size, no heroes_mass cell, soak Δ vs first-frame baseline, and a single shot. Keep those rows; do not mix them into `balanced-2` trends.

| Probe | Script | Frozen argv | What it scores |
|-------|--------|-------------|----------------|
| CPU mix | [`cpu_mix.py`](cpu_mix.py) | `--bench --n 180 --duration 2 --warmup 0.5 --seed 42` | Mass sprites/shapes, scheduler, collision, spawn/destroy. Quality hardcoded **medium**. Phase `work_ms`. |
| GPU mix | [`gpu_mix.py`](gpu_mix.py) | `--bench --mode realistic --quality high --duration 3 --warmup 0.5 --seed 42` | Product-like ~150-shape composite (cheap fleet + ~20 unique heroes + light post). Phase `work_ms`, 1× window points. |
| GPU heroes | [`gpu_mix.py`](gpu_mix.py) | `--bench --mode heroes_mass --n-heroes 48 --quality high --duration 3 --warmup 0.5 --seed 42` | Dense multipass grid (fx_lab2-style). **No canvas post** unless `--post-only`. |
| Live mix | [`live_mix.py`](live_mix.py) | `--bench --n 80 --quality high --duration 3 --warmup 0.5 --seed 42` | Sprites + shapes + SpatialFx + camera + backgrounds + lifecycle churn. |
| Soak | [`soak_leak.py`](soak_leak.py) | `--cycles 30 --idle-frames 40 --churn-frames 10 --quality high` | Last idle `work_ms`, last RSS, Δ objects/handles. Δ is after_cycle 1→last (baseline excluded). |

**Noise rule.** Median of 3 independent processes. Spread `(max−min)/median` is printed. Treat **≲5%** median `work_ms` movement as noise, **≳15%** as a noteworthy row. `gpu_mix` realistic often has a **cold first shot** (submit); high spread on that cell alone is not a regression if the median holds. Soak: inventory (Δ objects/handles) is the leak signal; RSS without inventory growth is usually allocator settle. The runner auto-diffs against the last `balanced-2` row: same `stage_fingerprint` + >15% → environment noise; different fingerprint + >15% → candidate real move.

**balanced-2 script SHA-256** (first 12 hex). Filled on the first snapshot; a mismatch means bump or pro-forma. **Scena fingerprint** is per-row (see the `Stage` cell in each run) — it is *not* frozen here; it changes whenever `scena/` changes.

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `0b4dab89bf9d` |
| `gpu_mix.py` | `4ad50342acfc` |
| `live_mix.py` | `0c191cafb982` |
| `soak_leak.py` | `c794ee02565c` |
| `harness.py` | `1b961ba409de` |
| `run_balanced.py` | `2f711d25419a` |

Fingerprint: `ad550601488b`.

## If a cell moved

The pulse is a **detector**. After a noteworthy median shift:

| Cell | Next isolate |
|------|----------------|
| cpu `coll_ms` | `cpu_mix.py --bench --n 180 --firestorm --duration 3`; [`perf_collision_shooter.py`](perf_collision_shooter.py). That cell is `@collide` only. Standing `resolve()` is [`resolve.md`](resolve.md). |
| cpu `tick_ms` | `cpu_mix.py --bench --n 180 --profile`; scheduler / `every` density |
| cpu `draw_ms` | [`isolat.py`](isolat.py) `--bench --tier reactive`; [`perf_scena.py`](perf_scena.py) vs [`perf_raw_skia.py`](perf_raw_skia.py) |
| gpu `work_ms` / `post_ms` | `gpu_mix.py --bench --suite`; then [`perf_fx_matrix.py`](perf_fx_matrix.py) `--quality high --category canvas` |
| gpu `draw_ms` | `gpu_mix.py --bench --mode fleet` vs `--mode heroes`; [`perf_glow_fleet.py`](perf_glow_fleet.py) |
| heroes_mass `work_ms` | [`perf_fx_matrix.py`](perf_fx_matrix.py) `--quality high --category visual` (or one `--effect`) |
| live `spatial_ms` | [`perf_spatial_fx.py`](perf_spatial_fx.py) |
| live `coll_ms` / `tick_ms` | same as cpu_mix |
| live `bg_ms` | [`historical/scene_demo.py`](historical/scene_demo.py) `--bench`; smoke `background.py` |
| soak Δ objects / handles | soak JSON `samples`; check destroy / `cancel_owner` |
| soak last RSS only | ignore unless inventory also climbs |

Do **not** add the full FX matrix, `isolat --suite`, or historical labs to this pulse.

## Summary

Newest first. Primary: median **work_ms**. cpu/live phases in backticks (`t` tick, `c` coll, `d` draw). Soak: last RSS / last idle ms / Δ objects.

| Date | Protocol | Host | cpu_mix work_ms (FPS) | gpu_mix work_ms (FPS) | heroes_mass work_ms (FPS) | live_mix work_ms (FPS) | soak last RSS / idle / Δobj | Notes |
|------|----------|------|----------------------:|----------------------:|--------------------------:|-----------------------:|----------------------------:|-------|
| 2026-09-29 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.795 (208.6) `t1.37 c1.68 d0.99` | 8.430 (118.6) | 6.227 (160.6) | 8.390 (119.2) `t2.72 c3.26 d1.03` | 177.7 MiB / 0.811 ms / Δobj 0 |  |
| 2026-09-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.482 (223.1) `t1.31 c1.71 d0.99` | 6.628 (150.9) § | 7.637 (130.9) § | 8.124 (123.1) `t2.71 c3.31 d1.04` | 171.6 MiB / 0.802 ms / Δobj 0 | post B1+B2 fixes (pull stores raw; hot validators). § GPU cells ran at FB 1200×800 (1×, window on another display) — not comparable to the 2× rows; the gpu −25% auto-diff is the FB change. Same code at 2× on 09-29: heroes 6.18 ms, draw 2.35 (flat vs 09-24) |
| 2026-09-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.531 (180.8) `t1.63 c1.74 d1.01` | 8.846 (113.0) | 7.147 (139.9) | 8.681 (115.2) `t2.81 c3.32 d1.02` | 173.5 MiB / 0.872 ms / Δobj 0 |  |
| 2026-09-24 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.137 (241.7) `t1.22 c1.62 d0.90` | 8.092 (123.6) | 5.814 (172.0) | 7.557 (132.3) `t2.47 c3.13 d0.97` | 170.7 MiB / 0.679 ms / Δobj 0 |  |
| 2026-09-24 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.321 (231.4) `t1.19 c1.59 d0.93` | 8.177 (122.3) | 6.059 (165.0) | 8.071 (123.9) `t2.29 c3.08 d0.99` | 174.4 MiB / 0.793 ms / Δobj 0 |  |
| 2026-09-23 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 6.591 (151.7) `t1.29 c3.68 d0.94` | 7.799 (128.2) | 6.051 (165.3) | 8.537 (117.1) `t2.31 c4.13 d0.98` | 174.7 MiB / 0.734 ms / Δobj 0 |  |
| 2026-09-22 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.631 (216.0) `t1.23 c1.77 d0.89` | 8.510 (117.5) | 6.385 (156.6) | 8.331 (120.0) `t2.40 c3.62 d1.05` | 170.7 MiB / 0.647 ms / Δobj 0 |  |
| 2026-09-15 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.242 (235.8) `t1.21 c1.79 d0.89` | 7.556 (132.3) | 5.913 (169.1) | 7.677 (130.3) `t2.25 c3.42 d0.97` | 170.1 MiB / 0.656 ms / Δobj 0 |  |
| 2026-09-12 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.744 (210.8) `t1.25 c1.78 d0.92` | 8.316 (120.3) | 6.573 (152.1) | 7.566 (132.2) `t2.25 c3.42 d0.96` | 169.2 MiB / 0.621 ms / Δobj 0 |  |
| 2026-09-11 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.410 (226.8) `t1.19 c1.69 d0.86` | 8.730 (114.5) | 6.547 (152.7) | 7.567 (132.2) `t2.36 c3.32 d0.95` | 169.1 MiB / 0.619 ms / Δobj 0 |  |
| 2026-09-09 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.279 (189.4) `t1.73 c1.68 d0.94` | 8.149 (122.7) | 7.017 (142.5) | 8.309 (120.4) `t2.62 c3.18 d1.00` | 173.4 MiB / 0.797 ms / Δobj 0 |  |
| 2026-09-05 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.306 (188.5) `t1.50 c1.63 d0.95` | 8.460 (118.2) | 8.325 (120.1) | 8.366 (119.5) `t2.44 c3.22 d1.00` | 161.7 MiB / 0.767 ms / Δobj 0 | mix-collision 1–4; coll recovered vs 09-05 regression; GPU FB 2× |
| 2026-08-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 3.794 (263.6) `t1.49 c1.09 d0.85` | 6.224 (160.7) § | 8.018 (124.7) § | 6.755 (148.0) `t2.55 c2.23 d0.99` | 154.7 MiB / 0.614 ms / Δobj 0 | Text drawString fast path; GPU FB 1× |
| 2026-08-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.081 (245.1) `t1.50 c1.09 d0.86` | 8.125 (123.1) | 7.367 (135.7) | 7.216 (138.6) `t2.46 c2.20 d0.97` | 160.5 MiB / 0.671 ms / Δobj 0 | pose instant path; cpu tick recovered vs noon |
| 2026-08-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.479 (223.3) `t1.77 c1.11 d0.86` | 8.360 (119.6) | 7.089 (141.1) | 7.096 (140.9) `t2.59 c2.11 d0.94` | 160.4 MiB / 0.674 ms / Δobj 0 | cpu/live tick tax (rotation=/move_by import); one cpu shot under-populated |
| 2026-08-26 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.907 (203.8) `t1.63 c1.13 d0.90` | 8.378 (119.4) | 7.298 (137.0) | 6.651 (150.4) `t2.44 c2.16 d0.94` | 157.8 MiB / 0.584 ms / Δobj 0 | cpu +20% present tax (compositor); GPU/live/soak hold |
| 2026-08-26 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.086 (244.7) `t1.52 c1.08 d0.83` | 8.475 (118.0) | 7.376 (135.6) | 6.864 (145.7) `t2.37 c2.11 d0.92` | 161.9 MiB / 0.665 ms / Δobj 0 | framework pulse; cpu present recovered; heroes +13% (submit) |
| 2026-08-25 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.875 (205.1) `t1.58 c1.06 d0.82` | 8.353 (119.7) | 8.214 (121.7) | 8.207 (121.9) `t2.30 c1.99 d0.88` | 160.5 MiB / 0.664 ms / Δobj 0 | coll fix holds (−17% vs morning); work_ms up from present |
| 2026-08-25 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.412 (226.7) `t1.51 c1.44 d0.80` | 6.226 (160.6) § | 7.449 (134.2) § | 6.869 (145.6) `t2.36 c2.34 d0.90` | 160.5 MiB / 0.675 ms / Δobj 0 | idle re-run; FB 1×; cpu coll still +12% vs morning |
| 2026-08-25 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.690 (213.2) `t1.60 c1.44 d0.83` | 8.363 (119.6) | 6.544 (152.8) | 7.309 (136.8) `t2.38 c2.42 d0.91` | 160.6 MiB / 0.646 ms / Δobj 0 | pro-forma (mix hashes); cpu +16% coll noteworthy |
| 2026-08-25 | balanced-2 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.059 (246.4) `t1.54 c1.29 d0.79` | 8.715 (114.7) | 6.518 (153.4) | 6.963 (143.6) `t2.38 c2.25 d0.91` | 160.3 MiB / 0.713 ms / Δobj 0 | pro-forma; gpu cold first shot ±25% |
| 2026-08-25 | balanced-1 | Apple M4 · macOS 26.5.2 · Py 3.12.13 | 4.239 (235.9) | 9.099 mean frame (109.9) † | — | 6.685 (149.6) | +12.45 Δrss / −5.489 Δwork ‡ | first snapshot; soak RSS warn |

† `balanced-1` gpu_mix was wall-clock mean frame ms at Retina `window_frac` (FB 2764×1842), not harness `work_ms`.  
‡ `balanced-1` soak Δ included the first-frame baseline.  
§ GPU cells at FB 1200×800 (1×). Do not compare to Retina 2× rows (FB 2400×1600). Since 2026-09-29 `run_balanced.py` writes the mark itself (unmarked = 2×, `§` = 1×, `[FB n×]` = other) and auto-diff compares each GPU cell only with the newest row at the same FB, printing an `auto-diff: note —` line when it falls back or cannot compare (`tests/test_bench_pulse.py`).

---

## Runs

Newest first.

### 2026-09-29 — balanced-2

| | |
|---|---|
| When | 2026-09-29 11:32 -0300 (14:32 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | 3 (median) |
| Scripts | fingerprint `6167e87114b2` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `cb188e0ad0de` |
| `gpu_mix.py` | `4d026eeb9b6c` |
| `live_mix.py` | `2241f297c2dc` |
| `soak_leak.py` | `4d6cb64483ad` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `a26c0e063528` |

Summary row:

| 2026-09-29 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.795 (208.6) `t1.37 c1.68 d0.99` | 8.430 (118.6) | 6.227 (160.6) | 8.390 (119.2) `t2.72 c3.26 d1.03` | 177.7 MiB / 0.811 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.795 ±2%**  FPS 208.6  tick 1.371  coll 1.684  draw 0.990

#### gpu_mix (realistic)

- work_ms **8.430 ±3%**  FPS 118.6  draw 3.471  post 0.090  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.227 ±1%**  FPS 160.6  draw 2.501  post 0.000  FB 2400×1600

#### live_mix

- work_ms **8.390**  FPS 119.2  tick 2.719  coll 3.264  draw 1.032

#### soak_leak

- last RSS **177.67 MiB**  last idle **0.811 ms**  Δrss 0.80  Δwork -0.127  Δobj 0  Δhandles 0

### 2026-09-28 — balanced-2

| | |
|---|---|
| When | 2026-09-28 21:50 -0300 (00:50 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c80d3268bb2b` |
| Repeats | 3 (median) |
| Scripts | fingerprint `0f1e2890f605` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `cb188e0ad0de` |
| `gpu_mix.py` | `4d026eeb9b6c` |
| `live_mix.py` | `2241f297c2dc` |
| `soak_leak.py` | `4d6cb64483ad` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.482 (223.1) `t1.31 c1.71 d0.99` | 6.628 (150.9) § | 7.637 (130.9) § | 8.124 (123.1) `t2.71 c3.31 d1.04` | 171.6 MiB / 0.802 ms / Δobj 0 | post B1+B2 fixes (pull stores raw; hot validators). § GPU cells ran at FB 1200×800 (1×, window on another display) — not comparable to the 2× rows; the gpu −25% auto-diff is the FB change. Same code at 2× on 09-29: heroes 6.18 ms, draw 2.35 (flat vs 09-24) |

#### cpu_mix

- work_ms **4.482 ±2%**  FPS 223.1  tick 1.314  coll 1.711  draw 0.988

#### gpu_mix (realistic)

- work_ms **6.628 ±7%**  FPS 150.9  draw 2.698  post 0.086  FB 1200×800

#### gpu_mix (heroes_mass n=48)

- work_ms **7.637**  FPS 130.9  draw 5.608  post 0.000

#### live_mix

- work_ms **8.124 ±6%**  FPS 123.1  tick 2.711  coll 3.310  draw 1.038

#### soak_leak

- last RSS **171.59 MiB**  last idle **0.802 ms**  Δrss 1.03  Δwork 0.066  Δobj 0  Δhandles 0

### 2026-09-28 — balanced-2

| | |
|---|---|
| When | 2026-09-28 21:17 -0300 (00:17 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | 3 (median) |
| Scripts | fingerprint `0f1e2890f605` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `cb188e0ad0de` |
| `gpu_mix.py` | `4d026eeb9b6c` |
| `live_mix.py` | `2241f297c2dc` |
| `soak_leak.py` | `4d6cb64483ad` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-28 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.531 (180.8) `t1.63 c1.74 d1.01` | 8.846 (113.0) | 7.147 (139.9) | 8.681 (115.2) `t2.81 c3.32 d1.02` | 173.5 MiB / 0.872 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **5.531 ±14%**  FPS 180.8  tick 1.634  coll 1.741  draw 1.010

#### gpu_mix (realistic)

- work_ms **8.846 ±5%**  FPS 113.0  draw 3.498  post 0.089  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **7.147 ±12%**  FPS 139.9  draw 2.440  post 0.000

#### live_mix

- work_ms **8.681 ±3%**  FPS 115.2  tick 2.814  coll 3.316  draw 1.023

#### soak_leak

- last RSS **173.50 MiB**  last idle **0.872 ms**  Δrss 0.78  Δwork -0.021  Δobj 0  Δhandles 0

### 2026-09-24 — balanced-2

| | |
|---|---|
| When | 2026-09-24 20:23 -0300 (23:23 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | 3 (median) |
| Scripts | fingerprint `e22c41286a7a` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `f0af6a03b8f0` |
| `gpu_mix.py` | `60bb68d74f37` |
| `live_mix.py` | `a1622e496536` |
| `soak_leak.py` | `6b7a6c4ab5e9` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-24 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.137 (241.7) `t1.22 c1.62 d0.90` | 8.092 (123.6) | 5.814 (172.0) | 7.557 (132.3) `t2.47 c3.13 d0.97` | 170.7 MiB / 0.679 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.137 ±2%**  FPS 241.7  tick 1.216  coll 1.618  draw 0.896

#### gpu_mix (realistic)

- work_ms **8.092 ±9%**  FPS 123.6  draw 3.297  post 0.085  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **5.814 ±1%**  FPS 172.0  draw 2.347  post 0.000

#### live_mix

- work_ms **7.557**  FPS 132.3  tick 2.467  coll 3.135  draw 0.975

#### soak_leak

- last RSS **170.69 MiB**  last idle **0.679 ms**  Δrss 0.94  Δwork -0.051  Δobj 0  Δhandles 0

### 2026-09-24 — balanced-2

| | |
|---|---|
| When | 2026-09-24 10:35 -0300 (13:35 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | 3 (median) |
| Scripts | fingerprint `e22c41286a7a` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `f0af6a03b8f0` |
| `gpu_mix.py` | `60bb68d74f37` |
| `live_mix.py` | `a1622e496536` |
| `soak_leak.py` | `6b7a6c4ab5e9` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-24 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.321 (231.4) `t1.19 c1.59 d0.93` | 8.177 (122.3) | 6.059 (165.0) | 8.071 (123.9) `t2.29 c3.08 d0.99` | 174.4 MiB / 0.793 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.321 ±11%**  FPS 231.4  tick 1.190  coll 1.591  draw 0.931

#### gpu_mix (realistic)

- work_ms **8.177 ±5%**  FPS 122.3  draw 3.154  post 0.080  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.059 ±1%**  FPS 165.0  draw 2.269  post 0.000

#### live_mix

- work_ms **8.071 ±2%**  FPS 123.9  tick 2.293  coll 3.085  draw 0.989

#### soak_leak

- last RSS **174.39 MiB**  last idle **0.793 ms**  Δrss 0.84  Δwork -0.094  Δobj 0  Δhandles 0

### 2026-09-23 — balanced-2

| | |
|---|---|
| When | 2026-09-23 20:18 -0300 (23:18 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `88e64c88ecb1` |
| Repeats | 3 (median) |
| Scripts | fingerprint `e22c41286a7a` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `f0af6a03b8f0` |
| `gpu_mix.py` | `60bb68d74f37` |
| `live_mix.py` | `a1622e496536` |
| `soak_leak.py` | `6b7a6c4ab5e9` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-23 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 6.591 (151.7) `t1.29 c3.68 d0.94` | 7.799 (128.2) | 6.051 (165.3) | 8.537 (117.1) `t2.31 c4.13 d0.98` | 174.7 MiB / 0.734 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **6.591 ±10%**  FPS 151.7  tick 1.289  coll 3.685  draw 0.941

#### gpu_mix (realistic)

- work_ms **7.799 ±9%**  FPS 128.2  draw 3.194  post 0.083  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.051**  FPS 165.3  draw 2.282  post 0.000

#### live_mix

- work_ms **8.537 ±1%**  FPS 117.1  tick 2.306  coll 4.129  draw 0.985

#### soak_leak

- last RSS **174.72 MiB**  last idle **0.734 ms**  Δrss 0.62  Δwork -0.101  Δobj 0  Δhandles 0

### 2026-09-22 — balanced-2

| | |
|---|---|
| When | 2026-09-22 20:26 -0300 (23:26 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c91c4e4c91e7` |
| Repeats | 3 (median) |
| Scripts | fingerprint `e22c41286a7a` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `f0af6a03b8f0` |
| `gpu_mix.py` | `60bb68d74f37` |
| `live_mix.py` | `a1622e496536` |
| `soak_leak.py` | `6b7a6c4ab5e9` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-22 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.631 (216.0) `t1.23 c1.77 d0.89` | 8.510 (117.5) | 6.385 (156.6) | 8.331 (120.0) `t2.40 c3.62 d1.05` | 170.7 MiB / 0.647 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.631 ±7%**  FPS 216.0  tick 1.231  coll 1.769  draw 0.887

#### gpu_mix (realistic)

- work_ms **8.510 ±5%**  FPS 117.5  draw 3.334  post 0.085  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.385 ±2%**  FPS 156.6  draw 2.292  post 0.000

#### live_mix

- work_ms **8.331 ±3%**  FPS 120.0  tick 2.404  coll 3.619  draw 1.049

#### soak_leak

- last RSS **170.73 MiB**  last idle **0.647 ms**  Δrss 1.03  Δwork -0.058  Δobj 0  Δhandles 0

### 2026-09-15 — balanced-2

| | |
|---|---|
| When | 2026-09-15 13:20 -0300 (16:20 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `8303d83b3439` |
| Repeats | 3 (median) |
| Scripts | fingerprint `93886264821d` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `9c86a1884a55` |
| `gpu_mix.py` | `76ec19163909` |
| `live_mix.py` | `bdfe227b6947` |
| `soak_leak.py` | `43d96e710d48` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-15 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.242 (235.8) `t1.21 c1.79 d0.89` | 7.556 (132.3) | 5.913 (169.1) | 7.677 (130.3) `t2.25 c3.42 d0.97` | 170.1 MiB / 0.656 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.242 ±11%**  FPS 235.8  tick 1.208  coll 1.790  draw 0.889

#### gpu_mix (realistic)

- work_ms **7.556 ±9%**  FPS 132.3  draw 3.223  post 0.085  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **5.913**  FPS 169.1  draw 2.245  post 0.000

#### live_mix

- work_ms **7.677 ±3%**  FPS 130.3  tick 2.253  coll 3.423  draw 0.971

#### soak_leak

- last RSS **170.11 MiB**  last idle **0.656 ms**  Δrss 0.78  Δwork -0.033  Δobj 0  Δhandles 0

### 2026-09-12 — balanced-2

| | |
|---|---|
| When | 2026-09-12 11:50 -0300 (14:50 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `00c71e0ec4d9` |
| Repeats | 3 (median) |
| Scripts | fingerprint `34050c842615` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `9c86a1884a55` |
| `gpu_mix.py` | `76ec19163909` |
| `live_mix.py` | `bdfe227b6947` |
| `soak_leak.py` | `ae59238ca401` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-12 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.744 (210.8) `t1.25 c1.78 d0.92` | 8.316 (120.3) | 6.573 (152.1) | 7.566 (132.2) `t2.25 c3.42 d0.96` | 169.2 MiB / 0.621 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.744 ±8%**  FPS 210.8  tick 1.249  coll 1.777  draw 0.923

#### gpu_mix (realistic)

- work_ms **8.316 ±3%**  FPS 120.3  draw 3.096  post 0.075  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.573 ±5%**  FPS 152.1  draw 2.256  post 0.000

#### live_mix

- work_ms **7.566 ±2%**  FPS 132.2  tick 2.251  coll 3.420  draw 0.957

#### soak_leak

- last RSS **169.25 MiB**  last idle **0.621 ms**  Δrss 0.84  Δwork -0.041  Δobj 0  Δhandles 0

### 2026-09-11 — balanced-2

| | |
|---|---|
| When | 2026-09-11 21:25 -0300 (00:25 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c2f322da89d6` |
| Repeats | 3 (median) |
| Scripts | fingerprint `b8694817e455` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `9c86a1884a55` |
| `gpu_mix.py` | `f2e35ce250b3` |
| `live_mix.py` | `bdfe227b6947` |
| `soak_leak.py` | `ae59238ca401` |
| `harness.py` | `80407cd97e92` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-11 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.410 (226.8) `t1.19 c1.69 d0.86` | 8.730 (114.5) | 6.547 (152.7) | 7.567 (132.2) `t2.36 c3.32 d0.95` | 169.1 MiB / 0.619 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **4.410 ±17%**  FPS 226.8  tick 1.194  coll 1.690  draw 0.863

#### gpu_mix (realistic)

- work_ms **8.730 ±6%**  FPS 114.5  draw 3.502  post 0.085  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **6.547**  FPS 152.7  draw 2.233  post 0.000

#### live_mix

- work_ms **7.567 ±3%**  FPS 132.2  tick 2.364  coll 3.322  draw 0.946

#### soak_leak

- last RSS **169.14 MiB**  last idle **0.619 ms**  Δrss 1.12  Δwork -0.119  Δobj 0  Δhandles 0

### 2026-09-09 — balanced-2

| | |
|---|---|
| When | 2026-09-09 16:18 -0300 (19:18 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `09bca538ac9f` |
| Repeats | 3 (median) |
| Scripts | fingerprint `4aa860e0967c` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `7e5017384570` |
| `gpu_mix.py` | `5afcd3fbc242` |
| `live_mix.py` | `4a1a71a5de5b` |
| `soak_leak.py` | `9b7f08ac7a0a` |
| `harness.py` | `1b961ba409de` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-09 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.279 (189.4) `t1.73 c1.68 d0.94` | 8.149 (122.7) | 7.017 (142.5) | 8.309 (120.4) `t2.62 c3.18 d1.00` | 173.4 MiB / 0.797 ms / Δobj 0 |  |

#### cpu_mix

- work_ms **5.279 ±4%**  FPS 189.4  tick 1.733  coll 1.682  draw 0.939

#### gpu_mix (realistic)

- work_ms **8.149 ±3%**  FPS 122.7  draw 3.574  post 0.079  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **7.017 ±1%**  FPS 142.5  draw 2.809  post 0.000

#### live_mix

- work_ms **8.309 ±1%**  FPS 120.4  tick 2.621  coll 3.176  draw 0.998

#### soak_leak

- last RSS **173.41 MiB**  last idle **0.797 ms**  Δrss 1.08  Δwork -0.104  Δobj 0  Δhandles 0

### 2026-09-05 — balanced-2

| | |
|---|---|
| When | 2026-09-05 19:23 -0300 (22:23 UTC) |
| Protocol | `balanced-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `3a4d14543b38` |
| Repeats | 3 (median) |
| Scripts | fingerprint `2c5050bc1d94` |

| File | sha256[:12] |
|------|-------------|
| `cpu_mix.py` | `616e94e723d6` |
| `gpu_mix.py` | `5afcd3fbc242` |
| `live_mix.py` | `f5de0aeae4f4` |
| `soak_leak.py` | `08bf2b9b7958` |
| `harness.py` | `1b961ba409de` |
| `run_balanced.py` | `858a0396dd16` |

Summary row:

| 2026-09-05 | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 5.306 (188.5) `t1.50 c1.63 d0.95` | 8.460 (118.2) | 8.325 (120.1) | 8.366 (119.5) `t2.44 c3.22 d1.00` | 161.7 MiB / 0.767 ms / Δobj 0 | mix-collision 1–4; coll recovered vs 09-05 regression; GPU FB 2× |

Frozen argv as in the protocol table. **FB 2400×1600** (design 1200×800 points, Retina 2×). GPU cells are not comparable to the 08-28 15:47 1× row. Compare GPU to 08-28 12:32 2×.

Mix-collision hot path items 1–4 (vectorized A×B broad, cheaper pose extra, RegularPolygon spin, skip unused `touching_*`). Auto-diff vs 15:47 1× is misleading on GPU (`+36%`). cpu/live `tick_ms` hold vs 12:32. Remaining `coll_ms` is the leftover after the fix (cpu 2.83 → **1.63**, live 5.67 → **3.22**), still above 08-28. cpu `work_ms` spread ±9% is present tax (0.60–1.02); median used.

| | 12:32 2× | 09-05 regression | now 19:23 2× | vs 12:32 | vs regression |
|--|----------:|-----------------:|-------------:|---------:|--------------:|
| cpu work_ms | 4.081 | 7.049 | **5.306** | +30% (present+coll) | −25% |
| cpu tick_ms | 1.497 | 2.45 | **1.498** | hold | recovered |
| cpu coll_ms | 1.09 | 2.83 | **1.634** | +50% | −42% |
| live work_ms | 7.216 | 11.156 | **8.366** | +16% (coll) | −25% |
| live tick_ms | 2.460 | 2.90 | **2.437** | hold | recovered |
| live coll_ms | 2.20 | 5.67 | **3.223** | +46% | −43% |
| gpu_mix work_ms | **8.125** | — | **8.460** | +4% hold | — |
| heroes work_ms | 7.367 | — | **8.325** | +13% | — |

#### cpu_mix

Tight repeats on tick/coll/draw. Present 0.60–1.02 inflates headline `work_ms`.

- work_ms **5.306 ±9%**  FPS 188.5  tick 1.498  coll 1.634  draw 0.945

#### gpu_mix (realistic)

- work_ms **8.460 ±2%**  FPS 118.2  draw 3.554  post 0.079  FB 2400×1600

#### gpu_mix (heroes_mass n=48)

- work_ms **8.325**  FPS 120.1  draw 2.906  post 0.000

#### live_mix

- work_ms **8.366**  FPS 119.5  tick 2.437  coll 3.223  draw 1.005

#### soak_leak

- last RSS **161.70 MiB**  last idle **0.767 ms**  Δrss 1.20  Δwork -0.077  Δobj 0  Δhandles 0

### 2026-08-28 — balanced-2 (Text drawString)

| | |
|---|---|
| When | 2026-08-28 15:47 −03 (18:47 UTC) |
| Protocol | `balanced-2` (pro-forma — mix hashes drifted vs protocol table) |
| Host | Apple M4, arm64, Darwin 26.6.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 66.3 s |
| Scripts | fingerprint `16c498363727` — `harness.py` / `run_balanced.py` still match protocol; mix hashes drifted (`cpu_mix` `c4d6ef079dab`, `gpu_mix` `afc9eabc4a39`, `live_mix` `cfb9a0c58c21`, `soak_leak` `0004764ed649`) |

Frozen argv as in the protocol table. **FB 1200×800** (design 1200×800 points, **1×**). GPU cells are not comparable to Retina 2× rows (FB 2400×1600). Compare GPU to the 08-25 idle 1× row.

`Text` captions (HUD / FPS / `visual=Glow`) no longer tessellate glyph paths every frame. Solid fill ± Glow uses GPU `drawString`; path outlines stay for Gradient/Texture. Isolate (µs/call): 6 HUD + live FPS **691 → 164**; Glow 8ch **206 → 34**. cpu/live phases hold vs 12:32 (cpu `work_ms` −7% sits with present 0.16, not a phase jump). GPU 1× holds vs idle 08-25 gpu_mix 6.226; heroes draw 6.06 vs idle 5.47 is the 1× multipass band, not Text.

| | 12:32 2× | idle 08-25 1× | now 15:47 1× | vs 12:32 (cpu/live) |
|--|----------:|--------------:|-------------:|--------------------:|
| cpu work_ms | 4.081 | 4.412 | **3.794** | −7% |
| cpu tick_ms | 1.497 | 1.510 | 1.490 | hold |
| cpu draw_ms | 0.861 | 0.802 | 0.847 | hold |
| live work_ms | 7.216 | 6.869 | **6.755** | −6% |
| live tick_ms | 2.460 | 2.363 | 2.552 | +4% |
| gpu_mix work_ms | 8.125 † | **6.226** | **6.224** | 1× hold |
| heroes work_ms | 7.367 † | 7.449 | **8.018** | 1× band |
| heroes draw_ms | 2.833 † | 5.466 | 6.063 | 1× band |

† Retina 2× — not 1:1 with this shot.

#### cpu_mix

Tight repeats. Present recovered (0.16).

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **3.794** | 3.773–3.917 | ±4% |
| FPS | 263.6 | 255.3–265.0 | |
| tick_ms | 1.490 | | ±3% |
| coll_ms | 1.092 | | ±1% |
| draw_ms | 0.847 | | ±3% |
| present_ms | 0.159 | 0.157–0.222 | ±41% |

#### gpu_mix (realistic)

FB 1× — do not trend vs 2× rows. Holds idle 08-25 6.226.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.224** | 5.985–6.386 | ±6% |
| FPS | 160.7 | 156.6–167.1 | |
| draw_ms | 2.811 | | ±8% |
| post_ms | 0.081 | | ±10% |
| submit_ms | 1.940 | | ±5% |

#### gpu_mix (heroes_mass n=48)

No canvas post. FB 1× — do not trend vs 2× rows. `draw_ms` is the 1× multipass band (~5.5–6.1), not the 2× ~2.8 paint number.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.018** | 7.839–8.094 | ±3% |
| FPS | 124.7 | 123.5–127.6 | |
| draw_ms | 6.063 | | ±6% |
| submit_ms | 1.504 | 1.371–1.514 | ±10% |
| present_ms | 0.256 | 0.232–0.273 | ±16% |

#### live_mix

Tick +4% vs 12:32 is under the 15% bar. Headline `work_ms` improved.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.755** | 6.737–6.936 | ±3% |
| FPS | 148.0 | 144.2–148.4 | |
| tick_ms | 2.552 | | ±2% |
| coll_ms | 2.233 | | ±3% |
| draw_ms | 0.992 | | ±3% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **154.67 MiB** |
| last idle work_ms | **0.614** |
| Δ rss_mb | +0.91 |
| Δ idle_work_ms | −0.073 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-28 — balanced-2 (pose instant path)

| | |
|---|---|
| When | 2026-08-28 12:32 −03 (15:32 UTC) |
| Protocol | `balanced-2` (pro-forma — mix hashes still drifted vs protocol table) |
| Host | Apple M4, arm64, Darwin 26.6.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 67.4 s |
| Scripts | fingerprint `a5f31ee6723e` — same as 12:21 |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×).

Instant `rotation=` / `move_by` / `scale=` no longer import `process` or validate `then=`/`on_done=` on the default path. cpu `tick_ms` **−15%** vs 12:21 and back on the noon band. live `tick_ms` **−5%** vs 12:21 (still +4% vs noon — under the 15% bar). GPU/heroes/soak hold. live `work_ms` spread ±8% is one faster shot (6.670); median used.

| | noon 08-26 | 12:21 pre-fix | now 12:32 | vs 12:21 | vs noon |
|--|-----------:|--------------:|----------:|---------:|--------:|
| cpu tick_ms | 1.524 | **1.767** | **1.497** | **−15%** | noise |
| cpu work_ms | 4.086 | 4.479 | **4.081** | −9% | hold |
| cpu present_ms | 0.446 | 0.437 | 0.393 | recovered | |
| live tick_ms | 2.365 | **2.589** | 2.460 | −5% | +4% |
| live work_ms | 6.864 | 7.096 | 7.216 | +2% (spread) | +5% |
| gpu_mix work_ms | 8.475 | 8.360 | 8.125 | noise | noise |
| heroes work_ms | 7.376 | 7.089 | 7.367 | noise | hold |

#### cpu_mix

Tight repeats. Enemies ~178 on all three shots.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.081** | 4.036–4.241 | ±5% |
| FPS | 245.1 | 235.8–247.8 | |
| tick_ms | 1.497 | | ±4% |
| coll_ms | 1.091 | | ±3% |
| draw_ms | 0.861 | | ±1% |
| present_ms | 0.393 | 0.338–0.436 | ±25% |

#### gpu_mix (realistic)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.125** | 8.078–8.296 | ±3% |
| FPS | 123.1 | 120.5–123.8 | |
| draw_ms | 3.600 | | ±4% |
| post_ms | 0.089 | | ±6% |
| submit_ms | 2.485 | | ±2% |

#### gpu_mix (heroes_mass n=48)

No canvas post. 48 multipass bodies. Tight repeats.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.367** | 7.267–7.367 | ±1% |
| FPS | 135.7 | 135.7–137.6 | |
| draw_ms | 2.833 | | ±1% |
| submit_ms | 3.487 | 3.460–3.490 | ±1% |
| present_ms | 0.638 | 0.571–0.656 | ±13% |

#### live_mix

Repeat 1 was the faster shot (6.670 / tick 2.367); median used. Tick is down vs 12:21; headline `work_ms` sits on the noise line vs noon.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.216** | 6.670–7.238 | ±8% |
| FPS | 138.6 | 138.2–149.9 | |
| tick_ms | 2.460 | | ±7% |
| coll_ms | 2.201 | | ±6% |
| draw_ms | 0.972 | | ±6% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **160.45 MiB** |
| last idle work_ms | **0.671** |
| Δ rss_mb | +1.27 |
| Δ idle_work_ms | −0.211 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-28 — balanced-2 (tick tax / pose import)

| | |
|---|---|
| When | 2026-08-28 12:21 −03 (15:21 UTC) |
| Protocol | `balanced-2` (pro-forma — mix hashes still drifted vs protocol table) |
| Host | Apple M4, arm64, Darwin 26.6.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 68.0 s |
| Scripts | fingerprint `a5f31ee6723e` — `cpu_mix.py` / `harness.py` / `run_balanced.py` still match protocol; `gpu_mix.py` `96c6dbfdca32`, `live_mix.py` `c60e2cf35d18`, `soak_leak.py` `d46e7440794f` |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×). OS 26.6.2 vs prior 26.5.2 rows.

cpu `tick_ms` **+16%** vs noon (1.524 → 1.767) is the cell that moved. live `tick_ms` **+9%** (2.365 → 2.589), tight repeats. GPU/heroes/soak hold. Next isolate was `cpu_mix.py --bench --n 180 --profile`: instant `rotation=` / `move_by` imported `process` and ran `_require_timed_completion` every call (on_done= gate added on the pose hot path).

cpu spread ±80% is one under-populated shot (avg enemies 45.7 / 761 FPS — rocks only); median used the two full-wave shots (4.479 / 4.877). Tick on those two was 1.767 / 1.942.

| | noon 12:47 | evening 20:40 | now 12:21 | vs noon |
|--|-----------:|--------------:|----------:|--------:|
| cpu tick_ms | 1.524 | 1.632 | **1.767** | **+16%** |
| cpu coll_ms | 1.080 | 1.132 | 1.110 | noise |
| cpu draw_ms | 0.826 | 0.897 | 0.864 | noise |
| cpu present_ms | 0.446 | 0.897 | 0.437 | recovered |
| cpu work_ms | 4.086 | 4.907 | **4.479** | +10% (tick) |
| live tick_ms | 2.365 | 2.444 | **2.589** | **+9%** |
| live work_ms | 6.864 | 6.651 | 7.096 | +3% |
| gpu_mix work_ms | 8.475 | 8.378 | 8.360 | noise |
| heroes work_ms | 7.376 | 7.298 | 7.089 | noise |

#### cpu_mix

Repeat 2 was the empty-wave shot (work 1.313 / 45 enemies); median used.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.479** | 1.313–4.877 | ±80% |
| FPS | 223.3 | 205.0–761.3 | |
| tick_ms | 1.767 | | ±84% |
| coll_ms | 1.110 | | ±82% |
| draw_ms | 0.864 | | ±86% |
| present_ms | 0.437 | 0.220–0.456 | ±54% |

#### gpu_mix (realistic)

Tight repeats. No cold first shot.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.360** | 8.326–8.383 | ±1% |
| FPS | 119.6 | 119.3–120.1 | |
| draw_ms | 3.334 | | ±1% |
| post_ms | 0.075 | | ±2% |
| submit_ms | 3.183 | | ±1% |

#### gpu_mix (heroes_mass n=48)

No canvas post. 48 multipass bodies.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.089** | 7.023–7.403 | ±5% |
| FPS | 141.1 | 135.1–142.4 | |
| draw_ms | 2.753 | | ±1% |
| submit_ms | 3.444 | 3.401–3.587 | ±5% |
| present_ms | 0.508 | 0.462–0.717 | ±50% |

#### live_mix

Tick band is tight — not a cold first shot.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.096** | 7.093–7.150 | ±1% |
| FPS | 140.9 | 139.9–141.0 | |
| tick_ms | 2.589 | | ±0% |
| coll_ms | 2.109 | | ±1% |
| draw_ms | 0.942 | | ±1% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **160.42 MiB** |
| last idle work_ms | **0.674** |
| Δ rss_mb | +1.23 |
| Δ idle_work_ms | −0.180 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-26 — balanced-2 (evening present tax)

| | |
|---|---|
| When | 2026-08-26 20:40 −03 (23:40 UTC) |
| Protocol | `balanced-2` (pro-forma — same drifted mix hashes as 08-25 evening) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 67.5 s |
| Scripts | fingerprint `14d5ac7b5661` — same as noon / 08-25 evening / idle / after coll fix |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×) — comparable to noon and the 2× GPU cells, not the idle 1× row.

cpu `work_ms` **+20%** vs noon is compositor again: `present_ms` 0.45 → 0.90 (±60%). tick/coll/draw are modestly up (+7% / +5% / +9%) but under the 15% bar. live/gpu hold. heroes `submit_ms` stays in the elevated noon band (~3.62), not a new jump.

| | evening 19:24 | after fix 20:09 | noon 12:47 | now 20:40 | vs noon |
|--|-------------:|----------------:|-----------:|----------:|--------:|
| cpu coll_ms | 1.439 | 1.065 | 1.080 | **1.132** | noise |
| cpu tick_ms | 1.597 | 1.579 | 1.524 | 1.632 | +7% |
| cpu draw_ms | 0.834 | 0.820 | 0.826 | 0.897 | +9% |
| cpu present_ms | — | **1.172** | **0.446** | **0.897** | compositor |
| cpu work_ms | 4.690 | 4.875 | 4.086 | **4.907** | **+20%** (present) |
| live coll_ms | 2.417 | 1.990 | 2.113 | 2.159 | noise |
| live work_ms | 7.309 | 8.207 | 6.864 | **6.651** | −3% |
| gpu_mix work_ms | 8.363 | 8.353 | 8.475 | 8.378 | noise |
| gpu_mix draw_ms | 3.375 | 3.343 | 3.387 | 3.504 | noise |
| heroes draw_ms | 2.657 | 2.646 | 2.813 | 2.768 | noise |
| heroes submit_ms | 2.653 | 2.842 | **3.559** | **3.620** | holds noon band |
| heroes work_ms | 6.544 | 8.214 | 7.376 | **7.298** | noise |

Soak inventory still Δ 0. RSS −4.1 MiB vs noon is settle, not a leak.

#### cpu_mix

Repeat 2 was the faster present shot (4.432 / present 0.529); median used. Spread ±12% is present, not a phase regression. Even that faster shot sits at noon’s max (4.431).

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.907** | 4.432–5.031 | ±12% |
| FPS | 203.8 | 198.8–225.6 | |
| tick_ms | 1.632 | | ±6% |
| coll_ms | 1.132 | | ±9% |
| draw_ms | 0.897 | | ±6% |
| present_ms | 0.897 | 0.529–1.070 | ±60% |

#### gpu_mix (realistic)

First repeat was the cold shot (work 9.390, present 1.550). Median used.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.378** | 8.262–9.390 | ±13% |
| FPS | 119.4 | 106.5–121.0 | |
| draw_ms | 3.504 | | ±3% |
| post_ms | 0.082 | | ±8% |
| submit_ms | 3.017 | | ±3% |

Holds vs noon 8.475 / evening 8.363.

#### gpu_mix (heroes_mass n=48)

No canvas post. 48 multipass bodies. Tight repeats. `submit_ms` still ~3.62 — same elevated band as noon, not the 2.65–2.84 morning/evening/after-fix band.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.298** | 7.258–7.423 | ±2% |
| FPS | 137.0 | 134.7–137.8 | |
| draw_ms | 2.768 | | ±1% |
| submit_ms | 3.620 | 3.581–3.626 | ±1% |
| present_ms | 0.589 | 0.588–0.669 | ±14% |

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.651** | 6.547–6.853 | ±5% |
| FPS | 150.4 | 145.9–152.7 | |
| tick_ms | 2.444 | | ±1% |
| coll_ms | 2.159 | | ±2% |
| draw_ms | 0.944 | | ±1% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **157.81 MiB** |
| last idle work_ms | **0.584** |
| Δ rss_mb | +1.22 |
| Δ idle_work_ms | −0.021 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-26 — balanced-2 (framework pulse)

| | |
|---|---|
| When | 2026-08-26 12:47 −03 (15:47 UTC) |
| Protocol | `balanced-2` (pro-forma — same drifted mix hashes as 08-25 evening) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 68.0 s |
| Scripts | fingerprint `14d5ac7b5661` — same as 08-25 evening / idle / after coll fix |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×) — comparable to morning/evening/after-fix GPU cells, not the idle 1× row.

`present_ms` recovered (cpu 1.17 → 0.45), so last night’s headline `work_ms` bump was compositor, not framework. cpu/live phases hold the coll fix. **heroes_mass is the cell that moved**: +13% vs evening/morning, driven by `submit_ms` (2.65 → 3.56, +34%), not present. Next isolate: [`perf_fx_matrix.py`](perf_fx_matrix.py) `--quality high --category visual`.

| | morning 17:15 | evening 19:24 | after fix 20:09 | today 12:47 | vs evening |
|--|-------------:|-------------:|----------------:|------------:|-----------:|
| cpu coll_ms | 1.289 | 1.439 | 1.065 | **1.080** | coll fix holds |
| cpu tick_ms | 1.539 | 1.597 | 1.579 | 1.524 | noise |
| cpu draw_ms | 0.792 | 0.834 | 0.820 | 0.826 | noise |
| cpu present_ms | ~0.58 | — | **1.172** | **0.446** | recovered |
| cpu work_ms | 4.059 | 4.690 | 4.875 | **4.086** | −13% (present + coll) |
| live coll_ms | 2.254 | 2.417 | 1.990 | 2.113 | coll fix holds |
| live work_ms | 6.963 | 7.309 | 8.207 | **6.864** | −6% |
| gpu_mix work_ms | 8.715 | 8.363 | 8.353 | 8.475 | noise |
| gpu_mix draw_ms | 3.549 | 3.375 | 3.343 | 3.387 | noise |
| heroes draw_ms | 2.624 | 2.657 | 2.646 | 2.813 | +6% |
| heroes submit_ms | 2.699 | 2.653 | 2.842 | **3.559** | **+34%** |
| heroes work_ms | 6.518 | 6.544 | 8.214 | **7.376** | **+13%** |

Soak inventory still Δ 0. RSS +1.4 MiB vs last night is settle.

#### cpu_mix

Repeat 3 was a slower shot (4.431); median used. Spread ±10% is that tail, not a phase regression.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.086** | 4.033–4.431 | ±10% |
| FPS | 244.7 | 225.7–248.0 | |
| tick_ms | 1.524 | | ±7% |
| coll_ms | 1.080 | | ±9% |
| draw_ms | 0.826 | | ±7% |
| present_ms | 0.446 | 0.412–0.515 | ±23% |

#### gpu_mix (realistic)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.475** | 8.103–8.664 | ±7% |
| FPS | 118.0 | 115.4–123.4 | |
| draw_ms | 3.387 | | ±6% |
| post_ms | 0.079 | | ±12% |
| submit_ms | 3.229 | | ±16% |

Holds vs evening 8.363 / after-fix 8.353. Submit spread is one faster shot; median used.

#### gpu_mix (heroes_mass n=48)

No canvas post. 48 multipass bodies. `draw_ms` +6% vs the 2.62–2.66 band; `submit_ms` is the jump. Present recovered vs last night, so this is not the compositor tax.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.376** | 7.086–7.647 | ±8% |
| FPS | 135.6 | 130.8–141.1 | |
| draw_ms | 2.813 | | ±2% |
| submit_ms | 3.559 | 3.411–3.605 | ±5% |
| present_ms | 0.698 | 0.512–0.850 | ±48% |

Submit band is tight — not a cold first shot.

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.864** | 6.714–6.911 | ±3% |
| FPS | 145.7 | 144.7–148.9 | |
| tick_ms | 2.365 | | ±3% |
| coll_ms | 2.113 | | ±2% |
| draw_ms | 0.921 | | ±3% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **161.94 MiB** |
| last idle work_ms | **0.665** |
| Δ rss_mb | +1.05 |
| Δ idle_work_ms | −0.070 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-25 — balanced-2 (after coll fix)

| | |
|---|---|
| When | 2026-08-25 20:09 −03 (23:09 UTC) |
| Protocol | `balanced-2` (pro-forma — same drifted mix hashes) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 69.1 s |
| Scripts | fingerprint `14d5ac7b5661` — same as evening / idle |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×) — comparable to morning/evening GPU cells, not the idle 1× row.

Landed as the pulse for the collision proxy AABB change of 2026-08-21 ([Collision Design — Runtime cost](../../design/Collision%20Design.md#runtime-cost-mass-sprite-related)).

Collision path is fixed and faster than the morning baseline. Headline `work_ms` is worse because `present_ms` jumped (window server / compositor), not because tick/coll/draw regressed.

| | morning 17:15 | idle 19:36 | after fix 20:09 | vs morning |
|--|-------------:|----------:|----------------:|-----------:|
| cpu coll_ms | 1.289 | 1.442 | **1.065** | **−17%** |
| live coll_ms | 2.254 | 2.342 | **1.990** | **−12%** |
| cpu tick_ms | 1.539 | 1.510 | 1.579 | +3% |
| cpu draw_ms | 0.792 | 0.802 | 0.820 | +4% |
| cpu present_ms | ~0.58 | 0.448 | **1.172** | compositor |
| cpu work_ms | 4.059 | 4.412 | 4.875 | +20% (present) |
| live work_ms | 6.963 | 6.869 | 8.207 | +18% (present) |
| gpu_mix work_ms | 8.715 | — § | 8.353 | noise vs evening 8.363 |
| heroes draw_ms | 2.624 | — § | 2.646 | noise |
| heroes work_ms | 6.518 | — § | 8.214 | present 0.95 → 2.42 |

Soak inventory still Δ 0.

#### cpu_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.875** | 4.664–4.943 | ±6% |
| FPS | 205.1 | 202.3–214.4 | |
| tick_ms | 1.579 | | ±4% |
| coll_ms | 1.065 | | ±4% |
| draw_ms | 0.820 | | ±5% |
| present_ms | 1.172 | 1.050–1.184 | ±11% |

#### gpu_mix (realistic)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.353** | 8.351–8.493 | ±2% |
| FPS | 119.7 | 117.7–119.7 | |
| draw_ms | 3.343 | | ±3% |
| post_ms | 0.079 | | ±7% |
| submit_ms | 2.362 | | ±31% |

Holds vs evening 8.363. Submit spread is one slower shot; median used.

#### gpu_mix (heroes_mass n=48)

No canvas post. 48 multipass bodies. `draw_ms` matches morning/evening; `work_ms` is present tax.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.214** | 8.164–8.329 | ±2% |
| FPS | 121.7 | 120.1–122.5 | |
| draw_ms | 2.646 | | ±2% |
| submit_ms | 2.842 | | ±1% |
| present_ms | 2.424 | 2.272–2.523 | ±10% |

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.207** | 8.144–8.230 | ±1% |
| FPS | 121.9 | 121.5–122.8 | |
| tick_ms | 2.297 | | ±2% |
| coll_ms | 1.990 | | ±1% |
| draw_ms | 0.875 | | ±2% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **160.53 MiB** |
| last idle work_ms | **0.664** |
| Δ rss_mb | +1.42 |
| Δ idle_work_ms | −0.113 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-25 — balanced-2 (idle re-run)

| | |
|---|---|
| When | 2026-08-25 19:36 −03 (22:36 UTC) |
| Protocol | `balanced-2` (pro-forma — same drifted mix hashes as evening) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 68.3 s |
| Scripts | fingerprint `14d5ac7b5661` — same as evening |

Frozen argv as in the protocol table. **FB 1200×800** (design 1200×800 points, **1×**). GPU cells are not comparable to morning/evening Retina 2× rows.

Idle vs evening vs morning (`cpu_mix.py` hash still matches):

| | morning 17:15 | evening 19:24 | idle 19:36 | idle vs morning |
|--|-------------:|-------------:|----------:|----------------:|
| cpu work_ms | 4.059 | 4.690 | **4.412** | +9% |
| cpu tick_ms | 1.539 | 1.597 | 1.510 | noise |
| cpu coll_ms | 1.289 | 1.439 | **1.442** | **+12%** |
| cpu draw_ms | 0.792 | 0.834 | 0.802 | noise |
| live work_ms | 6.963 | 7.309 | 6.869 | noise |

Evening **+16% cpu work_ms was partly load**: tick and draw came back. `coll_ms` did not — same as evening, still +12% vs morning. That is not machine-load noise. Overall cpu `work_ms` +9% sits between the 5% noise line and the 15% noteworthy bar. live_mix evening +5% **was** load.

#### cpu_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.412** | 4.399–4.602 | ±5% |
| FPS | 226.7 | 217.3–227.3 | |
| tick_ms | 1.510 | | ±7% |
| coll_ms | 1.442 | | ±3% |
| draw_ms | 0.802 | | ±0% |

#### gpu_mix (realistic)

FB 1× — do not trend vs 2× rows.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.226** | 6.139–6.274 | ±2% |
| FPS | 160.6 | 159.4–162.9 | |
| draw_ms | 2.689 | | ±1% |
| post_ms | 0.075 | | ±3% |
| submit_ms | 1.877 | | ±2% |

#### gpu_mix (heroes_mass n=48)

No canvas post. FB 1× — do not trend vs 2× rows. `draw_ms` is much higher than the 2× snapshots (5.47 vs ~2.66); treat as a different display, not a paint regression.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.449** | 7.405–7.458 | ±1% |
| FPS | 134.2 | 134.1–135.0 | |
| draw_ms | 5.466 | | ±1% |
| submit_ms | 1.226 | | ±1% |

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.869** | 6.841–6.915 | ±1% |
| FPS | 145.6 | 144.6–146.2 | |
| tick_ms | 2.363 | | ±2% |
| coll_ms | 2.342 | | ±1% |
| draw_ms | 0.899 | | ±1% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable.

| Metric | Median |
|--------|------:|
| last RSS | **160.53 MiB** |
| last idle work_ms | **0.675** |
| Δ rss_mb | +1.59 |
| Δ idle_work_ms | −0.104 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-25 — balanced-2 (evening)

| | |
|---|---|
| When | 2026-08-25 19:24 −03 (22:24 UTC) |
| Protocol | `balanced-2` (pro-forma — gpu_mix / live_mix / soak_leak hashes drifted) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 67.8 s |
| Scripts | fingerprint `14d5ac7b5661` — `cpu_mix.py` / `harness.py` / `run_balanced.py` still match; `gpu_mix.py` `96c6dbfdca32`, `live_mix.py` `931ea2a349ab`, `soak_leak.py` `cdfe6090fafa` |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×) on gpu probes.

`cpu_mix.py` hash still matches the protocol table, so that cell is 1:1 vs the morning snapshot. Median `work_ms` **+16%** (4.059 → 4.690), driven by `coll_ms` (1.289 → 1.439, +12%). New min 4.592 sits above the morning max 4.417. Next isolate: `cpu_mix.py --bench --n 180 --firestorm`.

gpu_mix / heroes_mass / soak hold (noise). live_mix **+5%** (`coll_ms` 2.254 → 2.417) sits on the noise line and is not 1:1 because `live_mix.py` drifted.

#### cpu_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.690** | 4.592–4.725 | ±3% |
| FPS | 213.2 | 211.7–217.8 | |
| tick_ms | 1.597 | | ±3% |
| coll_ms | 1.439 | | ±1% |
| draw_ms | 0.834 | | ±2% |

#### gpu_mix (realistic)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.363** | 8.213–8.371 | ±2% |
| FPS | 119.6 | 119.5–121.8 | |
| draw_ms | 3.375 | | ±2% |
| post_ms | 0.079 | | ±1% |
| submit_ms | 3.119 | | ±12% |

Tight repeats; no cold-first-shot this time. −4% vs morning is noise.

#### gpu_mix (heroes_mass n=48)

No canvas post (mode isolates paint). 48 multipass bodies.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.544** | 6.520–6.599 | ±1% |
| FPS | 152.8 | 151.5–153.4 | |
| draw_ms | 2.657 | | ±2% |
| submit_ms | 2.653 | | ±1% |

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **7.309** | 7.301–7.380 | ±1% |
| FPS | 136.8 | 135.5–137.0 | |
| tick_ms | 2.383 | | ±5% |
| coll_ms | 2.417 | | ±1% |
| draw_ms | 0.908 | | ±2% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable; RSS +~1 MiB is settle, not a warn.

| Metric | Median |
|--------|------:|
| last RSS | **160.58 MiB** |
| last idle work_ms | **0.646** |
| Δ rss_mb | +1.17 |
| Δ idle_work_ms | −0.157 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### 2026-08-25 — balanced-2

| | |
|---|---|
| When | 2026-08-25 17:15 −03 (20:15 UTC) |
| Protocol | `balanced-2` (pro-forma — protocol bump / first snapshot) |
| Host | Apple M4, arm64, macOS 26.5.2, Python 3.12.13 |
| Git | none |
| Repeats | 3 (median); elapsed 67.6 s |
| Scripts | fingerprint `ad550601488b` — hashes match the protocol table |

Frozen argv as in the protocol table. FB 2400×1600 (design 1200×800 points, Retina 2×) on gpu probes.

#### cpu_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **4.059** | 4.041–4.417 | ±9% |
| FPS | 246.4 | 226.4–247.5 | |
| tick_ms | 1.539 | | ±1% |
| coll_ms | 1.289 | | ±3% |
| draw_ms | 0.792 | | ±1% |

#### gpu_mix (realistic)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **8.715** | 7.850–10.011 | ±25% |
| FPS | 114.7 | 99.9–127.4 | |
| draw_ms | 3.549 | | ±16% |
| post_ms | 0.086 | | ±28% |
| submit_ms | 2.951 | | ±29% |

First repeat was the cold shot (submit). Median used. Not a leak/regression by itself.

#### gpu_mix (heroes_mass n=48)

No canvas post (mode isolates paint). 48 multipass bodies.

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.518** | 6.429–6.608 | ±3% |
| FPS | 153.4 | 151.3–155.6 | |
| draw_ms | 2.624 | | ±5% |
| submit_ms | 2.699 | | ±1% |

#### live_mix

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **6.963** | 6.925–6.970 | ±1% |
| FPS | 143.6 | 143.5–144.4 | |
| tick_ms | 2.377 | | ±1% |
| coll_ms | 2.254 | | ±1% |
| draw_ms | 0.907 | | ±1% |

#### soak_leak

Δ is after_cycle 1→last. Inventory stable; RSS +~1 MiB is settle, not a warn.

| Metric | Median |
|--------|------:|
| last RSS | **160.30 MiB** |
| last idle work_ms | **0.713** |
| Δ rss_mb | +1.08 |
| Δ idle_work_ms | −0.098 |
| Δ objects | 0 |
| Δ handles | 0 |

Teardown still prints `Attribute Circle.center.x was unlinked because a formula source was removed`.

---

### Run template

```markdown
### YYYY-MM-DD — balanced-N

| | |
|---|---|
| When | |
| Protocol | balanced-N (pro-forma: yes/no — why) |
| Host | |
| Git | |
| Stage | (sha256[:12] of `scena/**/*.py`) |
| Repeats | 3 (median) |
| Scripts | fingerprint … |

#### cpu_mix
#### gpu_mix (realistic)
#### gpu_mix (heroes_mass n=48)
#### live_mix
#### soak_leak
```

### 2026-08-25 — balanced-1

Single-shot, no heroes_mass, gpu_mix wall-clock / Retina window. Not comparable to `balanced-2`. First overall mix pulse after the CPU hot-path campaign of 2026-08-21 ([Reactive Design](../../design/Reactive%20Design.md)).

| | |
|---|---|
| When | 2026-08-25 ~16:48 −03 (19:48 UTC) |
| Protocol | `balanced-1` (superseded) |
| Host | Apple M4, arm64, macOS 26.5.2 (25F84), Python 3.12.13 |
| Git | none |
| Scripts | fingerprint `76384681b54d` |

cpu_mix work_ms **4.239** (t1.505 c1.277 d0.794) FPS 235.9.  
gpu_mix mean frame **9.099** ms FPS 109.9, FB 2764×1842.  
live_mix work_ms **6.685** (t2.317 c2.176 d0.874) FPS 149.6.  
soak Δrss **+12.45** MiB (vs baseline), Δ idle −5.489 ms, Δobj 0.
