# Text / HUD isolate

Phase-timed probe for **caption draw**: HUD `Text`, live FPS string, and `Glow()` on captions. Catches the `drawString` fast path (and regressions back to glyph tessellation) without the rest of `cpu_mix`.

Script: [`perf_text.py`](perf_text.py). Harness: [`harness.py`](harness.py).

## Why

A `drawString` fast path already moved a `balanced.md` cell (2026-08-28) without a dedicated isolate. This file is that isolate.

## What each mode scores

| Mode | Scene | Phase that should move |
|------|-------|------------------------|
| `hud` | 6 stacked HUD captions + live FPS string; ink rewritten every frame | `draw_ms` |
| `glow` | 8 `Text` + `Glow()` | `draw_ms` |
| `mix` | both. **Regular pulse.** | `draw_ms` |

`tick_ms` / `coll_ms` should stay near zero.

## How to run

From the **repo root**.

```bash
python scripts/bench/perf_text.py --pulse
python scripts/bench/perf_text.py --bench --mode mix
python scripts/bench/perf_text.py --bench --mode hud --repeats 3
```

## Protocol `text-1`

Bump this id (and mark the next snapshot **pro-forma**) if you change [`perf_text.py`](perf_text.py), [`harness.py`](harness.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| mix pulse | `--bench --mode mix --duration 2 --warmup 0.5 --seed 42` | HUD + Glow. Median `work_ms`; `draw_ms`. |

Quality is hardcoded **medium**. Design==window via the phase harness (1× points).

**Noise rule.** Median of 3 independent processes. Treat **≲5%** median `work_ms` as noise, **≳15%** as a noteworthy row.

## Summary

Newest first. Primary: median **work_ms** (then `draw_ms`).

| Date | Protocol | Host | mix work_ms (FPS) | Notes |
|------|----------|------|------------------:|-------|
| 2026-10-14 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.420 (2381.2) `t0.00 d0.01` | mix HUD+Glow |
| 2026-09-29 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.375 (2667.1) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-28 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.394 (2539.8) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-24 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.383 (2612.9) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-24 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.382 (2614.5) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-23 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.401 (2493.6) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-22 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.380 (2629.3) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-15 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.381 (2627.1) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-12 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.393 (2542.3) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-11 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.382 (2620.5) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-10 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.374 (2675.2) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-09 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.373 (2677.7) `t0.00 d0.00` | mix HUD+Glow |
| 2026-09-05 | `text-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.390 (2566.1) `t0.00 d0.00` | mix HUD+Glow |

---

## Runs

Newest first.

### 2026-10-14 — text-1

| | |
|---|---|
| When | 2026-10-14 11:43 -0300 (14:43 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | e6cd88ec85a3 |
| Scena | `15bc8e1ffdca` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `4f6d1f656712` · `harness.py` `38953009d9e9` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.420** | 0.418–0.456 | ±9% |
| FPS | 2381.2 | | |
| draw_ms | 0.006 | | |
| tick_ms | 0.001 | | |

### 2026-09-29 — text-1

| | |
|---|---|
| When | 2026-09-29 11:36 -0300 (14:36 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `8dda8a9db7be` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.375** | 0.375–0.384 | ±2% |
| FPS | 2667.1 | | |
| draw_ms | 0.002 | | |
| tick_ms | 0.001 | | |

### 2026-09-28 — text-1

| | |
|---|---|
| When | 2026-09-28 21:22 -0300 (00:22 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `f4cde1606f7e` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.394** | 0.378–0.394 | ±4% |
| FPS | 2539.8 | | |
| draw_ms | 0.002 | | |
| tick_ms | 0.001 | | |

### 2026-09-24 — text-1

| | |
|---|---|
| When | 2026-09-24 20:27 -0300 (23:27 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.383** | 0.370–0.383 | ±3% |
| FPS | 2612.9 | | |
| draw_ms | 0.002 | | |
| tick_ms | 0.000 | | |

### 2026-09-24 — text-1

| | |
|---|---|
| When | 2026-09-24 10:39 -0300 (13:39 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.382** | 0.376–0.392 | ±4% |
| FPS | 2614.5 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.001 | | |

### 2026-09-23 — text-1

| | |
|---|---|
| When | 2026-09-23 20:22 -0300 (23:22 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `88e64c88ecb1` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.401** | 0.371–0.424 | ±13% |
| FPS | 2493.6 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.000 | | |

### 2026-09-22 — text-1

| | |
|---|---|
| When | 2026-09-22 20:30 -0300 (23:30 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c91c4e4c91e7` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.380** | 0.376–0.404 | ±8% |
| FPS | 2629.3 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.000 | | |

### 2026-09-15 — text-1

| | |
|---|---|
| When | 2026-09-15 13:24 -0300 (16:24 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `8303d83b3439` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.381** | 0.367–0.396 | ±8% |
| FPS | 2627.1 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.000 | | |

### 2026-09-12 — text-1

| | |
|---|---|
| When | 2026-09-12 11:54 -0300 (14:54 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `00c71e0ec4d9` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.393** | 0.376–0.402 | ±7% |
| FPS | 2542.3 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.000 | | |

### 2026-09-11 — text-1

| | |
|---|---|
| When | 2026-09-11 21:29 -0300 (00:29 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c2f322da89d6` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `679ac4366ecf` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.382** | 0.366–0.384 | ±5% |
| FPS | 2620.5 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.000 | | |

### 2026-09-10 — text-1

| | |
|---|---|
| When | 2026-09-10 14:18 -0300 (17:18 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `1aa4c20cdbb9` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `204507b67bfd` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.374** | 0.370–0.448 | ±21% |
| FPS | 2675.2 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.001 | | |

### 2026-09-09 — text-1

| | |
|---|---|
| When | 2026-09-09 16:23 -0300 (19:23 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `09bca538ac9f` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `204507b67bfd` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.373** | 0.370–0.377 | ±2% |
| FPS | 2677.7 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.001 | | |

### 2026-09-05 — text-1

| | |
|---|---|
| When | 2026-09-05 19:27 -0300 (22:27 UTC) |
| Protocol | `text-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `3a4d14543b38` |
| Repeats | 3 (median) |
| Scripts | `perf_text.py` `204507b67bfd` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **0.390** | 0.376–0.391 | ±4% |
| FPS | 2566.1 | | |
| draw_ms | 0.001 | | |
| tick_ms | 0.001 | | |

### Run template

```markdown
### YYYY-MM-DD — text-1

| | |
|---|---|
| When | |
| Protocol | text-1 (pro-forma: yes/no — why) |
| Host | |
| Git | |
| Stage | |
| Repeats | 3 (median) |
| Scripts | perf_text.py …  harness.py … |
```
