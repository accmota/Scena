# FX cost matrix — historical log

Time-series pulse for [`perf_fx_matrix.py`](perf_fx_matrix.py). Cost model and methodology: [Effect System Design — §5.2 and §8](../../design/Effect%20System%20Design.md#8-benchmarks).

Primary headline: **baseline ms @ quality=`high`** (n=48 movers, design==window 1000×700). Rank the rest as cost× vs that baseline. Do not mix Retina / window-frac rows into this protocol.

## How to run

From the **repo root**. Close other GPU-heavy apps. Do not pipe workers through `head`/`tee` (orphan GLFW).

```bash
python scripts/bench/run_fx.py                  # protocol pulse; appends this file
python scripts/bench/run_fx.py --no-append      # print only
python scripts/bench/perf_fx_matrix.py --quality high --duration 0.85 --warmup 0.3 --n 48
```

Full inventory × all qualities is a deep campaign, not this pulse — dump it next to the notes file when you actually need the ladder.

Frozen argv (also the runner’s probe list):

```bash
python scripts/bench/perf_fx_matrix.py --duration 0.85 --warmup 0.3 --n 48 --quality high
```

Script hashes (must match the protocol table, or bump / pro-forma):

```bash
python -c "
import hashlib, pathlib
for p in ['perf_fx_matrix.py', 'run_fx.py']:
    h = hashlib.sha256(pathlib.Path('scripts/bench', p).read_bytes()).hexdigest()[:12]
    print(f'{p:20} {h}')
"
```

## Protocol `fx-1`

Bump this id (and mark the next snapshot **pro-forma**) if you change [`perf_fx_matrix.py`](perf_fx_matrix.py), [`run_fx.py`](run_fx.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| high matrix | `--duration 0.85 --warmup 0.3 --n 48 --quality high` | All effects @ `high`. Headline = baseline ms. Also record top-3 slowest +ms. |

Design==window **1000×700**, **n=48** movers, uncapped. Shape transients re-armed every frame (worst-case sustained). SpatialFx rows keep the same movers and add emitters.

**Noise rule.** Single-shot per cell (subprocess). Treat **≲5%** baseline ms movement as noise, **≳15%** as a noteworthy row. Individual effects are noisier than the baseline — use cost× rank, not absolute ms, for one-effect conclusions. `run_fx.py` auto-diffs baseline ms against the last `fx-1` row using the scena fingerprint.

**fx-1 script SHA-256** (first 12 hex). Filled on the first runner snapshot; a mismatch means bump or pro-forma.

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `9f04a7f7b9d2` |
| `run_fx.py` | `7c6dd60564b2` |

## If a cell moved

| Cell | Next isolate |
|------|----------------|
| baseline ms | [`isolat.py`](isolat.py) `--bench --tier reactive`; [`perf_raw_skia.py`](perf_raw_skia.py) |
| visual rank / +ms | `perf_fx_matrix.py --quality high --category visual` (or one `--effect`) |
| shape filter +ms | `--category shape`; [`perf_glow_fleet.py`](perf_glow_fleet.py) |
| canvas post +ms | `--category canvas`; `gpu_mix.py --bench --suite` |
| spatial +ms | [`perf_spatial_fx.py`](perf_spatial_fx.py) |
| quality ladder | not kept in this pulse (rerun `perf_fx_matrix.py --json`) |


## Summary

Newest first. Primary: **baseline ms @ high**.

| Date | Protocol | Host | baseline ms (FPS) @ high | top-3 +ms | Notes |
|------|----------|------|-------------------------:|-----------|-------|
| 2026-09-29 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.043 (959) | xf_burn +37.5 · visual_neon_unique +10.2 · visual_neon +9.7 |  |
| 2026-09-28 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.951 (1051) | xf_burn +36.6 · visual_neon_unique +10.1 · visual_neon +9.4 |  |
| 2026-09-24 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.826 (1210) | xf_burn +35.9 · visual_neon +9.6 · visual_neon_unique +9.5 |  |
| 2026-09-24 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.927 (1078) | xf_burn +36.5 · visual_neon_unique +10.4 · visual_neon +9.5 |  |
| 2026-09-23 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.935 (1069) | xf_burn +36.6 · visual_neon_unique +10.2 · visual_neon +9.5 |  |
| 2026-09-22 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.835 (1198) | xf_burn +35.9 · visual_neon +10.5 · visual_neon_unique +10.1 |  |
| 2026-09-15 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.810 (1234) | xf_burn +36.9 · visual_neon_unique +10.2 · visual_neon +9.8 |  |
| 2026-09-12 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.783 (1277) | xf_burn +37.3 · visual_neon +10.8 · visual_neon_unique +10.1 |  |
| 2026-09-11 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.800 (1250) | xf_burn +36.7 · visual_neon_unique +9.8 · visual_neon +9.7 |  |
| 2026-09-10 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.007 (993) | xf_burn +38.2 · visual_neon +10.5 · visual_neon_unique +9.8 |  |
| 2026-09-09 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.001 (999) | xf_burn +37.1 · visual_electricbolt +12.1 · visual_electricfield +11.1 |  |
| 2026-09-05 | fx-1 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.000 (1000) | xf_burn +37.0 · visual_neon +12.5 · visual_neon_unique +12.5 | mix-collision follow-up; auto-diff vs 08-07 under 15% |
| 2026-08-07 | fx-1 | arm64 M-class | 0.874 (~1144) | xf_burn +17.2 · spatial_campfire +14.9 · visual_electricfield +13.8 | first snapshot (full inventory; see notes). No scena fingerprint yet |

---

## Runs

Newest first.

### 2026-09-29 — fx-1

| | |
|---|---|
| When | 2026-09-29 11:36 -0300 (14:36 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `e4b9dbd1e54e` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `fa4965b3d9e0` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **1.043 ms**  (959 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 38.51 | +37.46 |
| 2 | `visual_neon_unique` | visual | 11.27 | +10.23 |
| 3 | `visual_neon` | visual | 10.76 | +9.72 |
| 4 | `xf_spark` | transient | 8.33 | +7.29 |
| 5 | `visual_ink_bleed` | visual | 7.38 | +6.34 |
| 6 | `visual_shieldgear` | visual | 6.46 | +5.41 |
| 7 | `visual_electricbolt` | visual | 5.55 | +4.50 |
| 8 | `visual_electricfield` | visual | 4.81 | +3.77 |
| 9 | `visual_tail` | visual | 3.86 | +2.82 |
| 10 | `visual_water` | visual | 3.80 | +2.75 |

### 2026-09-28 — fx-1

| | |
|---|---|
| When | 2026-09-28 21:22 -0300 (00:22 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.951 ms**  (1051 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 37.54 | +36.59 |
| 2 | `visual_neon_unique` | visual | 11.04 | +10.09 |
| 3 | `visual_neon` | visual | 10.37 | +9.42 |
| 4 | `xf_spark` | transient | 7.64 | +6.68 |
| 5 | `visual_ink_bleed` | visual | 7.59 | +6.64 |
| 6 | `visual_shieldgear` | visual | 6.19 | +5.24 |
| 7 | `visual_electricbolt` | visual | 5.32 | +4.37 |
| 8 | `visual_electricfield` | visual | 4.43 | +3.48 |
| 9 | `visual_water` | visual | 3.56 | +2.61 |
| 10 | `visual_tail` | visual | 3.45 | +2.50 |

### 2026-09-24 — fx-1

| | |
|---|---|
| When | 2026-09-24 20:27 -0300 (23:27 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.826 ms**  (1210 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 36.72 | +35.90 |
| 2 | `visual_neon` | visual | 10.40 | +9.57 |
| 3 | `visual_neon_unique` | visual | 10.34 | +9.52 |
| 4 | `xf_spark` | transient | 7.71 | +6.88 |
| 5 | `visual_ink_bleed` | visual | 7.50 | +6.67 |
| 6 | `visual_shieldgear` | visual | 5.84 | +5.01 |
| 7 | `visual_electricbolt` | visual | 5.11 | +4.28 |
| 8 | `visual_electricfield` | visual | 4.41 | +3.58 |
| 9 | `visual_water` | visual | 3.41 | +2.58 |
| 10 | `visual_tail` | visual | 3.34 | +2.52 |

### 2026-09-24 — fx-1

| | |
|---|---|
| When | 2026-09-24 10:39 -0300 (13:39 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.927 ms**  (1078 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 37.41 | +36.48 |
| 2 | `visual_neon_unique` | visual | 11.34 | +10.41 |
| 3 | `visual_neon` | visual | 10.47 | +9.54 |
| 4 | `xf_spark` | transient | 8.34 | +7.41 |
| 5 | `visual_ink_bleed` | visual | 7.43 | +6.50 |
| 6 | `visual_shieldgear` | visual | 5.57 | +4.64 |
| 7 | `visual_electricbolt` | visual | 5.56 | +4.63 |
| 8 | `visual_electricfield` | visual | 4.43 | +3.50 |
| 9 | `visual_tail` | visual | 3.40 | +2.47 |
| 10 | `visual_water` | visual | 3.37 | +2.45 |

### 2026-09-23 — fx-1

| | |
|---|---|
| When | 2026-09-23 20:22 -0300 (23:22 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `88e64c88ecb1` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.935 ms**  (1069 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 37.55 | +36.62 |
| 2 | `visual_neon_unique` | visual | 11.15 | +10.22 |
| 3 | `visual_neon` | visual | 10.44 | +9.51 |
| 4 | `xf_spark` | transient | 8.35 | +7.41 |
| 5 | `visual_ink_bleed` | visual | 7.46 | +6.53 |
| 6 | `visual_shieldgear` | visual | 5.59 | +4.65 |
| 7 | `visual_electricbolt` | visual | 5.56 | +4.62 |
| 8 | `visual_electricfield` | visual | 4.25 | +3.31 |
| 9 | `xf_dissolve_noise` | transient | 3.36 | +2.43 |
| 10 | `xf_dissolve_wipe` | transient | 3.35 | +2.42 |

### 2026-09-22 — fx-1

| | |
|---|---|
| When | 2026-09-22 20:30 -0300 (23:30 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c91c4e4c91e7` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.835 ms**  (1198 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 36.70 | +35.86 |
| 2 | `visual_neon` | visual | 11.36 | +10.53 |
| 3 | `visual_neon_unique` | visual | 10.94 | +10.11 |
| 4 | `visual_ink_bleed` | visual | 7.58 | +6.74 |
| 5 | `xf_spark` | transient | 7.51 | +6.68 |
| 6 | `visual_shieldgear` | visual | 5.51 | +4.68 |
| 7 | `visual_electricbolt` | visual | 4.99 | +4.15 |
| 8 | `visual_electricfield` | visual | 4.26 | +3.42 |
| 9 | `visual_water` | visual | 3.32 | +2.48 |
| 10 | `visual_tail` | visual | 3.25 | +2.41 |

### 2026-09-15 — fx-1

| | |
|---|---|
| When | 2026-09-15 13:24 -0300 (16:24 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `8303d83b3439` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.810 ms**  (1234 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 37.69 | +36.88 |
| 2 | `visual_neon_unique` | visual | 10.99 | +10.18 |
| 3 | `visual_neon` | visual | 10.57 | +9.76 |
| 4 | `xf_spark` | transient | 7.84 | +7.03 |
| 5 | `visual_ink_bleed` | visual | 7.82 | +7.01 |
| 6 | `visual_shieldgear` | visual | 5.72 | +4.91 |
| 7 | `visual_electricbolt` | visual | 5.04 | +4.23 |
| 8 | `visual_electricfield` | visual | 4.41 | +3.60 |
| 9 | `visual_tail` | visual | 3.58 | +2.77 |
| 10 | `visual_bolt` | visual | 3.37 | +2.56 |

### 2026-09-12 — fx-1

| | |
|---|---|
| When | 2026-09-12 11:54 -0300 (14:54 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `00c71e0ec4d9` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.783 ms**  (1277 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 38.07 | +37.28 |
| 2 | `visual_neon` | visual | 11.54 | +10.76 |
| 3 | `visual_neon_unique` | visual | 10.86 | +10.08 |
| 4 | `xf_spark` | transient | 7.92 | +7.14 |
| 5 | `visual_ink_bleed` | visual | 7.59 | +6.81 |
| 6 | `visual_shieldgear` | visual | 5.68 | +4.89 |
| 7 | `visual_electricbolt` | visual | 4.99 | +4.21 |
| 8 | `visual_electricfield` | visual | 4.31 | +3.53 |
| 9 | `visual_tail` | visual | 3.50 | +2.72 |
| 10 | `visual_shield_halo` | visual | 3.23 | +2.45 |

### 2026-09-11 — fx-1

| | |
|---|---|
| When | 2026-09-11 21:29 -0300 (00:29 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c2f322da89d6` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `26295aa0e7d1` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `6448778c724a` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **0.800 ms**  (1250 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 37.54 | +36.74 |
| 2 | `visual_neon_unique` | visual | 10.56 | +9.76 |
| 3 | `visual_neon` | visual | 10.52 | +9.72 |
| 4 | `visual_ink_bleed` | visual | 8.00 | +7.20 |
| 5 | `xf_spark` | transient | 7.73 | +6.93 |
| 6 | `visual_shieldgear` | visual | 5.60 | +4.80 |
| 7 | `visual_electricbolt` | visual | 5.06 | +4.26 |
| 8 | `visual_electricfield` | visual | 4.33 | +3.53 |
| 9 | `visual_tail` | visual | 3.57 | +2.77 |
| 10 | `visual_shield_halo` | visual | 3.30 | +2.50 |

### 2026-09-10 — fx-1

| | |
|---|---|
| When | 2026-09-10 14:18 -0300 (17:18 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `1aa4c20cdbb9` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `04d70f4da9af` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `9f04a7f7b9d2` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **1.007 ms**  (993 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 39.17 | +38.16 |
| 2 | `visual_neon` | visual | 11.54 | +10.53 |
| 3 | `visual_neon_unique` | visual | 10.82 | +9.81 |
| 4 | `xf_spark` | transient | 8.41 | +7.40 |
| 5 | `visual_ink_bleed` | visual | 7.90 | +6.89 |
| 6 | `visual_shieldgear` | visual | 5.63 | +4.63 |
| 7 | `visual_electricbolt` | visual | 5.59 | +4.59 |
| 8 | `visual_electricfield` | visual | 4.42 | +3.41 |
| 9 | `visual_tail` | visual | 3.79 | +2.79 |
| 10 | `xf_dissolve_wipe` | transient | 3.45 | +2.44 |

### 2026-09-09 — fx-1

| | |
|---|---|
| When | 2026-09-09 16:23 -0300 (19:23 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `09bca538ac9f` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `04d70f4da9af` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `9f04a7f7b9d2` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **1.001 ms**  (999 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 38.08 | +37.08 |
| 2 | `visual_electricbolt` | visual | 13.12 | +12.12 |
| 3 | `visual_electricfield` | visual | 12.11 | +11.11 |
| 4 | `visual_neon_unique` | visual | 11.54 | +10.54 |
| 5 | `visual_neon` | visual | 11.48 | +10.48 |
| 6 | `visual_ink_bleed` | visual | 8.45 | +7.45 |
| 7 | `xf_spark` | transient | 8.43 | +7.43 |
| 8 | `visual_shieldgear` | visual | 6.95 | +5.95 |
| 9 | `visual_shieldring` | visual | 4.18 | +3.18 |
| 10 | `visual_tail` | visual | 3.94 | +2.93 |

### 2026-09-05 — fx-1

| | |
|---|---|
| When | 2026-09-05 19:27 -0300 (22:27 UTC) |
| Protocol | `fx-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `3a4d14543b38` |
| Repeats | single-shot per cell |
| Scripts | fingerprint `04d70f4da9af` |

| File | sha256[:12] |
|------|-------------|
| `perf_fx_matrix.py` | `9f04a7f7b9d2` |
| `run_fx.py` | `7c6dd60564b2` |

Frozen argv as in the protocol table.

#### baseline @ high

- **1.000 ms**  (1000 fps)

#### top-10 rank

| # | Effect | Cat | ms | +ms vs base |
|--:|--------|-----|---:|------------:|
| 1 | `xf_burn` | transient | 38.01 | +37.01 |
| 2 | `visual_neon` | visual | 13.52 | +12.52 |
| 3 | `visual_neon_unique` | visual | 13.51 | +12.51 |
| 4 | `visual_electricbolt` | visual | 13.21 | +12.21 |
| 5 | `visual_electricfield` | visual | 12.67 | +11.67 |
| 6 | `xf_spark` | transient | 8.40 | +7.40 |
| 7 | `visual_ink_bleed` | visual | 8.37 | +7.37 |
| 8 | `visual_shieldgear` | visual | 8.17 | +7.17 |
| 9 | `visual_shieldring` | visual | 4.22 | +3.22 |
| 10 | `visual_tail` | visual | 4.18 | +3.18 |

### 2026-08-07 — fx-1

| | |
|---|---|
| When | 2026-08-07 |
| Protocol | `fx-1` (seeded from the notes-file full inventory) |
| Host | arm64 M-class, design==window 1000×700, n=48 |
| Git | none |
| Stage | *(not recorded)* |
| Repeats | single-shot per cell; all 5 qualities were measured that day |
| Scripts | `perf_fx_matrix.py` (hash not recorded) |

Frozen argv of this pulse is **high only**. The 2026-08-07 campaign also ran `low` / `medium` / `balanced` / `full` — those ladder numbers live in the notes file, not here.

Baseline @ **high**: **0.874 ms** (~1144 fps). Category medians cost× @ high: canvas ~1.09× · shape ~1.84× · spatial ~2.39× · transient ~3.24× · visual ~5.18×.

Top of rank @ high (slowest): `xf_burn` 18.1 ms (20.7×), `spatial_campfire` 15.8 ms (18.0×), `visual_electricfield` 14.7 ms (16.8×). Top 20 (baseline 0.874 ms; the quality ladder of this run used the old five-mode set and is not kept):

| # | Effect | Cat | ms | cost× | +ms vs base |
| --- | --- | --- | --- | --- | --- |
| 1 | xf_burn | transient | 18.1 | 20.7× | +17.2 |
| 2 | spatial_campfire | spatial | 15.8 | 18.0× | +14.9 |
| 3 | visual_electricfield | visual | 14.7 | 16.8× | +13.8 |
| 4 | visual_laser | visual | 13.5 | 15.4× | +12.6 |
| 5 | visual_electricbolt | visual | 13.0 | 14.8× | +12.1 |
| 6 | visual_plasmashot | visual | 12.9 | 14.7× | +12.0 |
| 7 | visual_gel | visual | 11.7 | 13.4× | +10.8 |
| 8 | visual_neon / _unique | visual | 11.1–11.6 | ~13× | +10.3 |
| 9 | visual_shield_vortex | visual | 9.4 | 10.8× | +8.5 |
| 10 | xf_spark | transient | 8.6 | 9.9× | +7.8 |
| 11 | visual_metal / ink_bleed / edgeglow | visual | ~8.1–8.3 | ~9.3–9.5× | +7.2 |
| 12 | visual_plasmafield / shields | visual | ~5.8–6.6 | ~6.7–7.6× | +4.9–5.7 |
| 13 | visual_extrude / water / ringfield | visual | ~4.1–4.5 | ~4.7–5.2× | +3.3–3.7 |
| 14 | dissolve / plume / wave-like transients | mix | ~3.3–3.8 | ~3.8–4.4× | +2.5–3.0 |
| 15 | shape_glow (shared GlowFilter) | shape | 2.19 | 2.51× | +1.3 |
| — | shared shape blur / shadow / dilate / erode | shape | 1.5–1.7 | 1.7–1.9× | +0.6–0.8 |
| — | canvas Grade / Grain / SkSL family | canvas | ~0.87–1.1 | ~1.0–1.3× | ≤ +0.2 |
| — | vignette (outlier post) | canvas | 2.08 | 2.38× | +1.2 |
| — | visual_paint / fill / ghost / stroke | visual | ≤ baseline | ≤ 1× | cheaper package |

Category medians cost× @ high: canvas ~1.09× · shape ~1.84× · spatial ~2.39× · transient ~3.24× · visual ~5.18× (hero multipass). The Recipe draw work of 2026-09-09…10 cut Laser / Neon / Ink and Electric* since ([Effect System Design §5.6](../../design/Effect%20System%20Design.md#56-recipe-draw-hot-path--lessons)).

---

### Run template

```markdown
### YYYY-MM-DD — fx-1

| | |
|---|---|
| When | |
| Protocol | fx-1 (pro-forma: yes/no — why) |
| Host | |
| Git | |
| Stage | |
| Repeats | single-shot per cell |
| Scripts | perf_fx_matrix.py …  run_fx.py … |

Frozen argv as in the protocol table.

#### baseline @ high
#### top-10 rank
```

## Earlier campaigns (pre-protocol)

These rows predate `fx-1`. Kept so the break is visible; do not trend them against the summary table.

| Date | Machine | Script / mode | Quality | Notes / FPS |
| --- | --- | --- | --- | --- |
| 2026-08-02 | M4 (dev) | lab shooter reference | various | Pre-engine: bal/noFX ~855, +glow ~555, +all post ~240, full+all ~130 |
| 2026-08-02 | M4 Retina | `perf_effects` baseline n=80 | balanced | **199** fps (HiDPI FB) |
| 2026-08-02 | M4 Retina | `perf_effects` glow batched | balanced | **160** fps |
| 2026-08-02 | M4 Retina | `perf_effects` glow+post | balanced | **149** fps |
| 2026-08-02 | M4 Retina | `app_shooter_fx --bench` | high | vignette+grain+bloom **1.98 ms** isolated |
| 2026-08-04 | M-class | `perf_fx_matrix` n=48 | all | Shape filters ~2× baseline; post SkSL ~1.1×; see notes |
| 2026-08-04 | M-class | Shape visuals pre-baseline | balanced/high | See notes |
| 2026-08-04 | M-class | Shape visuals post-ship | balanced/high | Regression PASS; visual cost inventory in notes |
| 2026-08-21 | arm64 Retina | `perf_glow_fleet` n=48 sprite | high | Sparse same-Glow ≈**2×** slower than clustered (Δwork +1.0 ms, almost all `present_ms`). Soft-plate CheapGlow + smart tiling tried/rejected; keep CheapGlow = GlowFilter + cluster fleets. |
