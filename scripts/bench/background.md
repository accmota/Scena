# Background / camera / parallax isolate

Phase-timed probe for **what sits behind the scene**: procedural background fields, image wallpaper, and parallax shape layers — all under a camera that pans, zooms and rotates every frame. Closes the "Camera / parallax / background fields" blind spot (proposal 4.3); before this, `bg_ms` was only ever seen inside `live_mix`.

Script: [`perf_background.py`](perf_background.py). Harness: [`harness.py`](harness.py).

## Why

Every field re-samples its parallax UV and every depth layer rebuilds its partial camera matrix whenever the camera moves. Background kinds are full-screen SkSL; a regression there costs every frame of every game that has a sky. `live_mix` buries it under sprites, collision and SpatialFx.

## What each mode scores

| Mode | Scene | Phase that should move |
|------|-------|------------------------|
| `sky` | `SkyGradient` + `Stars` + `Stardust` + `Clouds` | `bg_ms` |
| `wallpaper` | `Wallpaper("backgrounds/bg1.jpeg", fit="cover")` with pan/zoom response | `bg_ms` |
| `parallax` | 3 parallax layers (far/mid/near, ~60 shapes) + 24 world shapes | `draw_ms` |
| `mix` | sky + parallax (typical side-scroller / shooter). **Primary.** | `bg_ms` + `draw_ms` |

`tick_ms` / `coll_ms` should stay near zero. The camera path is deterministic (`clock.time` sines).

## How to run

From the **repo root**.

```bash
python scripts/bench/perf_background.py --pulse
python scripts/bench/perf_background.py --bench --mode sky
python scripts/bench/perf_background.py --bench --mode parallax --repeats 3
python scripts/bench/perf_background.py            # interactive (mix)
```

## Protocol `bg-1`

Bump this id (and mark the next snapshot **pro-forma**) if you change [`perf_background.py`](perf_background.py), [`harness.py`](harness.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| each mode | `--bench --mode <m> --duration 2 --warmup 0.5 --quality high` | Median `work_ms` of 3 processes; `bg_ms`, `draw_ms`. |

Design 1000×700, design==window via the phase harness (1× points).

**Noise rule.** Median of 3 independent processes per mode. Treat **≲5%** median `work_ms` as noise, **≳15%** as a noteworthy row.

## Summary

Newest first. Primary: **mix work_ms** (bg / draw split in parentheses).

| Date | Protocol | Host | mix work_ms (bg · d) | sky | wallpaper | parallax | Notes |
|------|----------|------|--------------------:|----:|----------:|---------:|-------|
| 2026-09-29 | `bg-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 3.660 (bg 0.08 · d 2.94) | 1.062 | 0.395 | 1.634 | |
| 2026-09-28 | `bg-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.177 (bg 0.10 · d 3.57) | 1.036 | 0.380 | 1.481 | |
| 2026-09-24 | `bg-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 3.971 (bg 0.09 · d 3.41) | 1.036 | 0.381 | 1.482 | |
| 2026-09-24 | `bg-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 3.577 (bg 0.08 · d 2.86) | 1.073 | 0.399 | 1.608 | first row · mix draw 2.87 ms vs parallax alone 1.13 (fields make layer draw ~2.5× dearer) |

---

## Runs

Newest first.

### 2026-09-29 — bg-1

| | |
|---|---|
| When | 2026-09-29 11:36 -0300 (14:36 UTC) |
| Protocol | `bg-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | 3 per mode (median) |
| Scripts | `perf_background.py` `f3212d44af83` · `harness.py` `80407cd97e92` |

| Mode | work_ms | spread | bg_ms | draw_ms | submit_ms | FPS |
|------|-------:|-------:|------:|--------:|----------:|----:|
| sky | **1.062** | ±1% | 0.057 | 0.002 | 0.037 | 942 |
| wallpaper | **0.395** | ±1% | 0.019 | 0.002 | 0.013 | 2530 |
| parallax | **1.634** | ±0% | 0.013 | 1.168 | 0.087 | 612 |
| mix | **3.660** | ±0% | 0.084 | 2.942 | 0.136 | 273 |

### 2026-09-28 — bg-1

| | |
|---|---|
| When | 2026-09-28 21:22 -0300 (00:22 UTC) |
| Protocol | `bg-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | 3 per mode (median) |
| Scripts | `perf_background.py` `f3212d44af83` · `harness.py` `80407cd97e92` |

| Mode | work_ms | spread | bg_ms | draw_ms | submit_ms | FPS |
|------|-------:|-------:|------:|--------:|----------:|----:|
| sky | **1.036** | ±1% | 0.087 | 0.003 | 0.054 | 965 |
| wallpaper | **0.380** | ±0% | 0.014 | 0.002 | 0.013 | 2629 |
| parallax | **1.481** | ±0% | 0.013 | 1.158 | 0.087 | 675 |
| mix | **4.177** | ±3% | 0.101 | 3.572 | 0.166 | 239 |

### 2026-09-24 — bg-1

| | |
|---|---|
| When | 2026-09-24 20:28 -0300 (23:28 UTC) |
| Protocol | `bg-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | 3 per mode (median) |
| Scripts | `perf_background.py` `73ff4a2a39f4` · `harness.py` `80407cd97e92` |

| Mode | work_ms | spread | bg_ms | draw_ms | submit_ms | FPS |
|------|-------:|-------:|------:|--------:|----------:|----:|
| sky | **1.036** | ±1% | 0.080 | 0.003 | 0.054 | 965 |
| wallpaper | **0.381** | ±1% | 0.015 | 0.002 | 0.013 | 2627 |
| parallax | **1.482** | ±0% | 0.013 | 1.163 | 0.088 | 675 |
| mix | **3.971** | ±4% | 0.095 | 3.410 | 0.165 | 252 |

### 2026-09-24 — bg-1

| | |
|---|---|
| When | 2026-09-24 11:41 -0300 (14:41 UTC) |
| Protocol | `bg-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `4000c948cf65` |
| Repeats | 3 per mode (median) |
| Scripts | `perf_background.py` `73ff4a2a39f4` · `harness.py` `80407cd97e92` |

| Mode | work_ms | spread | bg_ms | draw_ms | submit_ms | FPS |
|------|-------:|-------:|------:|--------:|----------:|----:|
| sky | **1.073** | ±1% | 0.055 | 0.001 | 0.037 | 932 |
| wallpaper | **0.399** | ±1% | 0.017 | 0.002 | 0.015 | 2508 |
| parallax | **1.608** | ±1% | 0.012 | 1.128 | 0.085 | 622 |
| mix | **3.577** | ±1% | 0.077 | 2.865 | 0.132 | 280 |

