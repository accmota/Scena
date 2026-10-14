# Resolve isolate

Pulse for standing **`resolve()`**, which [`cpu_mix.py`](cpu_mix.py) never enrolls. `@collide` detection stays on the balanced mix (`coll_ms` there is handlers, not settle/sweep).

- [`perf_resolve_balls.py`](perf_resolve_balls.py) — 40 mutual circles, four walls, one spinning bar.
- [`perf_resolve_platformer.py`](perf_resolve_platformer.py) — sprite hero, three walkers, elevator, ramp, spinning slab, 50 sprite shots.

Compare **`coll_ms`**, then **`ms_resolve`**, per scene. Balls moving alone is the mutual pool. Platformer moving alone is sprite hitboxes, resting contacts, the elevator, or the ramp.

## How to run

From the **repo root**.

```bash
python scripts/bench/run_resolve.py
python scripts/bench/perf_resolve_balls.py --bench --n 40 --duration 3 --warmup 0.5 --seed 42
python scripts/bench/perf_resolve_balls.py --bench --ladder 10,20,40,80 --duration 3
python scripts/bench/perf_resolve_platformer.py --bench --balls 50 --duration 3
```

`--resolve-off` is the detection floor. `--no-ball-ball` drops the mutual pool. `--no-spin` (balls only) leaves the bar still.

## Protocol `resolve-2`

`resolve-1` was balls only (one row below; its `work_ms` column is not a platformer number). Bump this id (and mark the next snapshot **pro-forma**) if you change either probe script, [`run_resolve.py`](run_resolve.py), [`harness.py`](harness.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| balls n=40 | `--bench --n 40 --duration 3 --warmup 0.5 --seed 42` | Mutual `resolve("ball","ball")` plus walls and a spinning bar. `coll_ms` / `ms_resolve`. |
| platformer | `--bench --balls 50 --duration 3 --warmup 0.5 --seed 42` | Sprite hero, walkers, elevator, ramp, spinning slab, 50 mutual shots. `coll_ms` / `ms_resolve`. |

Quality is hardcoded **medium**. FX Auto is off. Design==window via the phase harness (1× points).

**Noise rule.** Single-shot. Treat **≲5%** `coll_ms` as noise, **≳15%** as a noteworthy row. Auto-diff uses the scena fingerprint (same hash + >15% → noise).

## If a cell moved

| Cell | Next isolate |
|------|----------------|
| `coll_ms` up, `ms_resolve` flat | snapshot / broad — `--resolve-off`, then [`perf_collision_shooter.py`](perf_collision_shooter.py) |
| `ms_resolve` up | `--no-ball-ball` vs full; `--ladder 10,20,40,80`; `--profile` (balls only — platformer: `python -m cProfile -o out.prof scripts/bench/perf_resolve_platformer.py --bench …`) |
| platformer `coll_ms` up, balls flat | `--resolve-off` / `--no-ball-ball` on `perf_resolve_platformer.py` |

Do **not** fold this into [`balanced.md`](balanced.md). `cpu_mix` `coll_ms` is `@collide` only.

## Summary

Newest first. Primary: balls **coll_ms**, then platformer **coll_ms**.

| Date | Protocol | Host | balls coll_ms (FPS) | balls ms_resolve | platformer coll_ms (FPS) | platformer ms_resolve | Notes |
|------|----------|------|--------------------:|-----------------:|-------------------------:|----------------------:|-------|
| 2026-10-14 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.221 (393.2) | 0.766 | 2.839 (211.3) | 1.641 |  |
| 2026-09-29 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.114 (478.1) | 0.656 | 2.815 (261.0) | 1.564 |  |
| 2026-09-28 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.139 (516.4) | 0.670 | 2.580 (291.0) | 1.532 |  |
| 2026-09-24 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.068 (562.3) | 0.635 | 2.393 (318.7) | 1.374 |  |
| 2026-09-24 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.048 (520.2) | 0.631 | 2.421 (289.9) | 1.391 |  |
| 2026-09-24 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 0.977 (542.0) | 0.587 | 2.253 (320.1) | 1.304 | unswept recovery culls by proxy + stored boxes before prim bounds; inline TOI partner cull; bounds store in trust window |
| 2026-09-24 | `resolve-2` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.789 (173.6) | 4.256 | 8.740 (103.1) | 7.497 | resolve-2 adds platformer balls=50 |
| 2026-09-24 | `resolve-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.688 (178.5) | 4.182 | — | — | balls only; work_ms was 5.604 |

---

## Runs

Newest first.

### 2026-10-14 — resolve-2

| | |
|---|---|
| When | 2026-10-14 11:44 -0300 (14:44 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | e6cd88ec85a3 |
| Scena | `15bc8e1ffdca` |
| Repeats | single-shot |
| Scripts | fingerprint `cbb76047f99a` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `8d73628037f9` |
| `perf_resolve_platformer.py` | `175944e6508a` |
| `run_resolve.py` | `35cbe0dd534c` |
| `harness.py` | `38953009d9e9` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **1.221**  ms_resolve **0.766**  work_ms 2.543  FPS 393.2  broad 0.141  narrow 0.039  proxy_pairs 1.7
- platformer balls=50: coll_ms **2.839**  ms_resolve **1.641**  work_ms 4.732  FPS 211.3  broad 0.278  narrow 0.285  proxy_pairs 15.9

### 2026-09-29 — resolve-2

| | |
|---|---|
| When | 2026-09-29 11:36 -0300 (14:36 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | single-shot |
| Scripts | fingerprint `99f1002270de` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `75c57b9fcd04` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **1.114**  ms_resolve **0.656**  work_ms 2.091  FPS 478.1  broad 0.133  narrow 0.020  proxy_pairs 1.5
- platformer balls=50: coll_ms **2.815**  ms_resolve **1.564**  work_ms 3.831  FPS 261.0  broad 0.240  narrow 0.308  proxy_pairs 16.1

### 2026-09-28 — resolve-2

| | |
|---|---|
| When | 2026-09-28 21:22 -0300 (00:22 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | single-shot |
| Scripts | fingerprint `99f1002270de` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `75c57b9fcd04` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **1.139**  ms_resolve **0.670**  work_ms 1.936  FPS 516.4  broad 0.139  narrow 0.017  proxy_pairs 1.3
- platformer balls=50: coll_ms **2.580**  ms_resolve **1.532**  work_ms 3.436  FPS 291.0  broad 0.253  narrow 0.105  proxy_pairs 15.0

### 2026-09-24 — resolve-2

| | |
|---|---|
| When | 2026-09-24 20:28 -0300 (23:28 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | single-shot |
| Scripts | fingerprint `0f2f2868ac38` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `3c2fd00bfddb` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **1.068**  ms_resolve **0.635**  work_ms 1.778  FPS 562.3  broad 0.138  narrow 0.017  proxy_pairs 1.6
- platformer balls=50: coll_ms **2.393**  ms_resolve **1.374**  work_ms 3.138  FPS 318.7  broad 0.250  narrow 0.099  proxy_pairs 14.2

### 2026-09-24 — resolve-2

| | |
|---|---|
| When | 2026-09-24 10:40 -0300 (13:40 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | single-shot |
| Scripts | fingerprint `0f2f2868ac38` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `3c2fd00bfddb` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **1.048**  ms_resolve **0.631**  work_ms 1.923  FPS 520.2  broad 0.133  narrow 0.014  proxy_pairs 1.3
- platformer balls=50: coll_ms **2.421**  ms_resolve **1.391**  work_ms 3.449  FPS 289.9  broad 0.244  narrow 0.111  proxy_pairs 15.9

### 2026-09-24 — resolve-2

| | |
|---|---|
| When | 2026-09-24 10:29 -0300 (13:29 UTC) |
| Protocol | `resolve-2` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | single-shot |
| Scripts | fingerprint `0f2f2868ac38` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `3c2fd00bfddb` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **0.977**  ms_resolve **0.587**  work_ms 1.845  FPS 542.0  broad 0.126  narrow 0.016  proxy_pairs 1.7
- platformer balls=50: coll_ms **2.253**  ms_resolve **1.304**  work_ms 3.124  FPS 320.1  broad 0.221  narrow 0.109  proxy_pairs 17.0

### 2026-09-24 — resolve-2

| | |
|---|---|
| When | 2026-09-24 10:16 -0300 (13:16 UTC) |
| Protocol | `resolve-2` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0049bbc1b222` |
| Repeats | single-shot |
| Scripts | fingerprint `0f2f2868ac38` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `3c2fd00bfddb` |
| `perf_resolve_platformer.py` | `0818caed6480` |
| `run_resolve.py` | `e3907891b42c` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table.

- balls n=40: coll_ms **4.789**  ms_resolve **4.256**  work_ms 5.759  FPS 173.6  broad 0.142  narrow 0.023  proxy_pairs 1.9
- platformer balls=50: coll_ms **8.740**  ms_resolve **7.497**  work_ms 9.702  FPS 103.1  broad 0.224  narrow 0.144  proxy_pairs 18.5

### 2026-09-24 — resolve-1

| | |
|---|---|
| When | 2026-09-24 10:07 -0300 (13:07 UTC) |
| Protocol | `resolve-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0eb53cf158fa` |
| Repeats | single-shot |
| Scripts | fingerprint `8d732a285c6f` |

| File | sha256[:12] |
|------|-------------|
| `perf_resolve_balls.py` | `bb2380d9881f` |
| `run_resolve.py` | `4bf4a33c22e2` |
| `harness.py` | `80407cd97e92` |

Frozen argv: `--bench --n 40 --duration 3 --warmup 0.5 --seed 42`.

- coll_ms **4.688**  ms_resolve **4.182**  work_ms 5.604  FPS 178.5
- broad 0.131  narrow 0.023  snapshot 0.152  proxy_pairs 2.2

