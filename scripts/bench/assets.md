# Asset first-use isolate

What a **never-seen image** costs the frame it first appears in. Closes the "Asset load / atlas decode" blind spot (proposal 4.5), reframed: the useful question is not bulk decode throughput but *first-use hitches* — `skia.Image.open` is lazy, so decode and GPU upload land on the first frame that draws the image, not at construct.

Script: [`perf_assets.py`](perf_assets.py). Per-frame timing: [`frame_probe.py`](frame_probe.py) (real run loop).

## Why

Spawning a new sprite kind, a new sheet, or swapping a wallpaper mid-game is normal author code. If the first draw decodes a 2669×1782 PNG, that frame hitches — on this machine and ~4× worse on the target. Warm (cached) spawns should be ~free; the gap between **cold** and **warm** is what a preload / eager-decode policy would remove.

## What it scores

A steady scene runs uncapped; each asset is spawned **cold** (fresh process, empty caches) at a fixed time, then **warm** (same asset again). Per asset:

| Column | What |
|--------|------|
| construct | the constructor call alone (ms) |
| cold first-use | excess work of the spawn frame (+ the next one if it is > 1 ms over) vs the 0.3 s before |
| warm | same, second spawn of the same asset |
| decode (CPU) | plain Skia raster decode of the file(s) — the rest of *cold* is GPU upload + framework |

| Asset | What |
|-------|------|
| `sprite` | single PNG sprite (`planets/planet08.png`, the former `ball2.png`) |
| `atlas` | Kenney XML atlas (1024² sheet) + one frame |
| `strip` | 10-file frame sequence (ninja run) |
| `hitbox` | new atlas frame with `hitbox="auto"` + collision rule (fit cost) |
| `wall_jpg` | `Wallpaper` 1456×816 JPEG (`images/bg1.jpeg`) |
| `wall_png` | `Wallpaper` 1456×816 PNG (2.7 MB, `images/bg2.png`) |

## How to run

From the **repo root**.

```bash
python scripts/bench/perf_assets.py --pulse
python scripts/bench/perf_assets.py --launches 5
```

## Protocol `assets-1`

Bump this id if you change [`perf_assets.py`](perf_assets.py), [`frame_probe.py`](frame_probe.py), or the asset list.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| pulse | `--pulse` (3 fresh launches) | Median per asset; Σ cold (primary), worst asset, Σ warm. |

**Noise rule.** Median of 3 launches. Single-frame excesses are noisy under ~1 ms; judge the Σ and the big assets. **≳20%** on Σ cold is noteworthy.

## Open questions from the first row (2026-09-24)

- ~~**Wallpaper swap-back re-decodes.**~~ **Resolved.** Not Skia purging: skia-python's `Paint.setShader` deep-copies the shader (serialize → deserialize), so every Wallpaper build drew a *new* `skia.Image` (new uniqueID) and the GPU texture cache — keyed by image ID — missed; `_IMAGE_CACHE` held the right image but it was never the one drawn. Eager `makeRasterImage()` / `makeTextureImage()` would have been far worse: `setShader` then PNG-re-encodes the pixels (~0.8 s for bg3). Fixed in `scena/style.py`: fitted images draw with `drawImageRect` on the shared lazy image; tiles share one template shader per image placed by the canvas matrix (`BackgroundFill`). Construct prewarms the texture on the GPU context (queued until `run()` opens it), so a `Wallpaper.temp` built in setup and swapped in later costs 0.6 ms instead of 35 ms. Warm 36.5 → 0.25 ms. Tests: `TestWallpaperImageIdentity` (test_background_image).
- ~~**`hitbox="auto"` in the running loop.**~~ **Resolved.** Not a live-path / GPU-readback issue: the bench builds a fresh `Sheet(xml)` per spawn, and each `Sheet` got its own cache token, so `_AUTO_CACHE` / `_MASK_CACHE` missed although the decoded image was shared. The headless 0.3 ms reused one `Sheet`. Fixed in `scena/atlas.py`: an image keeps the first live sheet's token (refcounted holders; bakes drop with the last holder). Warm 27.5 → 1.1 ms. Regression: `test_sheets_sharing_one_image_share_bakes` (test_atlas), `test_hitbox_auto_fresh_sheet_per_spawn_reuses_bake` (test_sprite).

## Summary

Newest first. Primary: **Σ cold first-use ms**.

| Date | Protocol | Host | Σ cold ms | worst asset (ms) | Σ warm ms | Notes |
|------|----------|------|----------:|-----------------:|----------:|-------|
| 2026-10-14 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 68.7 | wall_png 15.3 | 7.2 | |
| 2026-09-29 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 83.9 | wall_png 36.8 | 6.5 | |
| 2026-09-28 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 86.8 | wall_png 38.0 | 7.0 | |
| 2026-09-24 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 84.3 | wall_png 37.1 | 6.6 | |
| 2026-09-24 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 94.7 | wall_png 34.2 | 6.4 | wall_png warm 36.5 → 0.25 ms, wall_jpg warm 3.7 → 0.2 ms: wallpaper images no longer `setShader` per build (skia-python clones → new image ID → GPU cache miss); decode moved into the constructor (prewarm) · cold Σ within noise |
| 2026-09-24 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 105.5 | wall_png 39.8 | 46.7 | hitbox warm 27.5 → 1.1 ms: image-token cache shared across `Sheet`s over one decoded image (`atlas.bind_sheet_images` refcount); cold Σ within noise |
| 2026-09-24 | `assets-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 101.1 | wall_png 38.4 | 72.6 | first row · wall_png warm ≈ cold (swap-back re-decodes) · hitbox warm 27 ms in-loop vs 0.3 ms headless |

---

## Runs

Newest first.

### 2026-10-14 — assets-1

| | |
|---|---|
| When | 2026-10-14 11:50 -0300 (14:50 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | e6cd88ec85a3 |
| Scena | `15bc8e1ffdca` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `c31b9c291b26` · `frame_probe.py` `58c8e71cd04f` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 4.12 | **7.07** | 0.69 | 2.92 |
| atlas | 5.58 | **7.43** | 1.10 | 1.56 |
| strip | 13.62 | **15.30** | 0.68 | 9.16 |
| hitbox | 15.00 | **15.22** | 1.23 | — |
| wall_jpg | 5.12 | **8.33** | 1.75 | 3.90 |
| wall_png | 14.43 | **15.32** | 1.75 | 12.57 |

### 2026-09-29 — assets-1

| | |
|---|---|
| When | 2026-09-29 11:38 -0300 (14:38 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `2f9ca22274ca` · `frame_probe.py` `6e76703d984f` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 3.86 | **6.70** | 0.57 | 2.85 |
| atlas | 4.13 | **5.87** | 1.00 | 1.61 |
| strip | 11.69 | **12.98** | 3.31 | 9.07 |
| hitbox | 14.84 | **14.97** | 1.10 | — |
| wall_jpg | 4.19 | **6.52** | 0.25 | 3.11 |
| wall_png | 36.63 | **36.83** | 0.28 | 35.78 |

### 2026-09-28 — assets-1

| | |
|---|---|
| When | 2026-09-28 21:23 -0300 (00:23 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `2f9ca22274ca` · `frame_probe.py` `6e76703d984f` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 4.00 | **6.99** | 0.62 | 2.85 |
| atlas | 4.13 | **5.80** | 1.10 | 1.79 |
| strip | 12.56 | **13.98** | 3.65 | 9.06 |
| hitbox | 15.27 | **15.46** | 1.14 | — |
| wall_jpg | 4.32 | **6.58** | 0.24 | 3.10 |
| wall_png | 37.78 | **37.99** | 0.30 | 35.75 |

### 2026-09-24 — assets-1

| | |
|---|---|
| When | 2026-09-24 20:29 -0300 (23:29 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `dd413251f9fa` · `frame_probe.py` `12f9864ac18b` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 3.80 | **6.56** | 0.55 | 3.01 |
| atlas | 3.99 | **5.60** | 0.99 | 1.81 |
| strip | 11.66 | **12.93** | 3.49 | 9.09 |
| hitbox | 15.53 | **15.66** | 1.14 | — |
| wall_jpg | 4.19 | **6.47** | 0.24 | 3.17 |
| wall_png | 36.87 | **37.08** | 0.24 | 35.79 |

### 2026-09-24 — assets-1

| | |
|---|---|
| When | 2026-09-24 14:43 -0300 (17:43 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `48904ccad936` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `dd413251f9fa` · `frame_probe.py` `12f9864ac18b` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 0.97 | **5.94** | 0.48 | 2.80 |
| atlas | 2.10 | **5.23** | 1.00 | 1.49 |
| strip | 10.61 | **11.93** | 3.35 | 8.40 |
| hitbox | 30.76 | **30.94** | 1.06 | — |
| wall_jpg | 4.13 | **6.42** | 0.21 | 2.91 |
| wall_png | 34.03 | **34.23** | 0.25 | 32.98 |

### 2026-09-24 — assets-1

| | |
|---|---|
| When | 2026-09-24 11:58 -0300 (14:58 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `2d17994451dd` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `dd413251f9fa` · `frame_probe.py` `12f9864ac18b` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 0.82 | **6.68** | 0.48 | 2.97 |
| atlas | 2.12 | **6.33** | 0.98 | 1.74 |
| strip | 11.50 | **12.89** | 3.59 | 9.00 |
| hitbox | 31.78 | **31.98** | 1.09 | — |
| wall_jpg | 0.42 | **7.78** | 3.90 | 3.18 |
| wall_png | 0.40 | **39.84** | 36.61 | 35.71 |

### 2026-09-24 — assets-1

| | |
|---|---|
| When | 2026-09-24 11:42 -0300 (14:42 UTC) |
| Protocol | `assets-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `4000c948cf65` |
| Launches | 3 fresh processes (median per asset) |
| Scripts | `perf_assets.py` `dd413251f9fa` · `frame_probe.py` `12f9864ac18b` |

| Asset | construct | cold first-use | warm | decode (CPU) |
|-------|---------:|---------------:|-----:|-------------:|
| sprite | 0.83 | **5.90** | 0.52 | 2.91 |
| atlas | 2.04 | **5.44** | 0.96 | 1.54 |
| strip | 11.16 | **12.50** | 3.44 | 8.99 |
| hitbox | 31.72 | **31.87** | 27.48 | — |
| wall_jpg | 0.45 | **7.03** | 3.66 | 3.13 |
| wall_png | 0.60 | **38.36** | 36.52 | 35.54 |

