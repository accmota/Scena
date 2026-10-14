# Scheduler isolate

Index: [dashboard.md](dashboard.md). Phase-timed probe for the **process + event** cluster: `move_along`, pose **tween**, **after** / **every**, **@when** / **@on_change**, **Handle** lifecycle, and the cooperative **process** tick (modes, `wait` / `until` / `parallel` / `race`).

Not a game. Collision, sprites, SpatialFx, and canvas post stay out — those live in [`cpu_mix.py`](cpu_mix.py) / [`live_mix.py`](live_mix.py). This file peels the scheduler so `tick_ms` and `flush_ms` are readable.

Script: [`sched.py`](sched.py). Harness: [`harness.py`](harness.py).

## Why

Two jobs:

1. **Bottlenecks.** `--mode` isolates one axis; `--profile` and `--hide` say whether the cost is process tick, event flush, or draw.
2. **Regression pulse.** Frozen `--mode mix` (and `--suite`) so a later snapshot is comparable.

Product scope is tens–hundreds of objects ([Scena Design.md](../../design/Scena%20Design.md)). This isolate may go denser than a taught sample — that is the point. This machine is ~4× the target box; compare **median `work_ms` and phases**, not raw FPS.

## What each mode scores

| Mode | Bodies (default) | Hot path | Phase that should move |
|------|-----------------:|----------|------------------------|
| `ride` | 200 | Forever `move_along` on Track presets (circle / eight / star). `--tracks unique` = one path per rider. `--face` = tangent → rotation every tick. | `tick_ms` (RideState + `_move_by`) |
| `tween` | 150 | Ping-pong `move_to` / `rotate_by` / `tween(radius)` via `on_done` (handle complete + re-arm). Mixed eases. | `tick_ms` (easing write) |
| `timers` | 200 | Named `every` + named `after` replace-slot. `--tight` shortens intervals. | `tick_ms` (fire + `_forget` / add) |
| `when` | 200 | `on_update` ramps ink; method `@when` / `@on_change` poll on flush. | `flush_ms` (and some `tick_ms` from `on_update`) |
| `process` | 80 | `@on_mode` patrol ↔ async dash: mode-scoped `every`, `then=`, `await parallel` / `wait` / `until` / `race`, `@exit_mode`. | `tick_ms` (scripts + await family) |
| `mix` | 120 | All of the above at fixed proportions (36 / 28 / 24 / 20 / 12). **Regular pulse.** | `tick_ms` + `flush_ms` |

`coll_ms` should stay near zero (nobody enrolls). If it does not, motion is leaking into collision. `draw_ms` is small circles; `--hide` peels it off.

## How to run

From the **repo root**. Close other GPU-heavy apps.

```bash
python scripts/bench/sched.py --bench --mode mix --repeats 3
python scripts/bench/sched.py --pulse
python scripts/bench/sched.py --bench --suite
python scripts/bench/sched.py --bench --mode ride --n 200 --face
python scripts/bench/sched.py --bench --mode ride --tracks unique --ladder 50,200,400
python scripts/bench/sched.py --bench --mode mix --hide --duration 2
python scripts/bench/sched.py --bench --mode mix --profile --duration 2
python scripts/bench/sched.py --bench --mode mix --json scripts/bench/results/sched_mix.json
```

`--pulse` is the protocol snapshot: mix median of 3 + suite single-shot, then appends this file. Interactive (no `--bench`): colored bands per role; HUD shows live handle / event counts.

| Flag | Effect |
|------|--------|
| `--mode` | Isolate axis; default `mix` |
| `--n` | Body count (per-mode default if omitted) |
| `--ladder` | Comma-separated N; one worker process each |
| `--suite` | Frozen N per mode (table below) |
| `--repeats` | Fresh processes; print median + spread |
| `--face` | All rides use `face=True` (mix default is 1 in 4) |
| `--tracks shared\|unique` | Shared Track + `phase=` vs a circle per rider |
| `--hide` | `visible=False` — scheduler CPU without Skia |
| `--no-readout` | Skip the per-frame `Handle.elapsed` / `.remaining` walk |
| `--tight` | Shorter timer / when periods (ceiling, not the pulse) |
| `--profile` | cProfile cumulative + tottime |
| `--json` | Full payload (worker only) |
| `--pulse` | Protocol snapshot: mix ×3 + suite; append this log |
| `--no-append` | With `--pulse`, print markdown only |

`--suite` / `--ladder` / `--repeats > 1` spawn workers (no window in the parent).

## Protocol `sched-1`

Bump this id (and mark the next snapshot **pro-forma**) if you change [`sched.py`](sched.py), [`harness.py`](harness.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| mix pulse | `--bench --mode mix --n 120 --duration 2 --warmup 0.5 --seed 42` | Combined scheduler. Median `work_ms`; `tick_ms` / `flush_ms`. |
| suite | `--bench --suite --duration 2 --warmup 0.5 --seed 42` | One cell per mode at frozen N. |

Suite N: ride 200, tween 150, timers 200, when 200, process 80, mix 120. `tracks=shared`, readout on, not `--face`, not `--hide`, not `--tight`. Quality is hardcoded **medium**. Design==window via the phase harness (1× points).

**Noise rule.** Median of 3 independent processes for the mix pulse. Spread `(max−min)/median` is printed. Treat **≲5%** median `work_ms` as noise, **≳15%** as a noteworthy row. Suite cells are single-shot unless you pass `--repeats 3`. `--pulse` auto-diffs mix `work_ms` against the last `sched-1` row using the scena fingerprint (same hash + >15% → noise; different hash + >15% → candidate real move).

Script hash (must match, or bump / pro-forma):

```bash
python -c "
import hashlib, pathlib
for p in ['sched.py', 'harness.py']:
    h = hashlib.sha256(pathlib.Path('scripts/bench', p).read_bytes()).hexdigest()[:12]
    print(f'{p:12} {h}')
"
```

| File | sha256[:12] |
|------|-------------|
| `sched.py` | `3d97e030dbf3` |
| `harness.py` | `80407cd97e92` |

## How to read a row

Primary: median **`work_ms`**. Then:

| Phase | Means |
|-------|--------|
| `tick_ms` | `tick_processes()` — tweens, rides, `after`/`every` fires, `on_update`, async resume |
| `flush_ms` | `@when` / `@on_change` poll (+ any other flush work; should be small here except `when`) |
| `draw_ms` | Small circles. Use `--hide` if this masks tick |
| `coll_ms` | Should be ~0 |
| `present_ms` | Compositor; ignore for scheduler conclusions |

Inventory (printed + JSON): live **handles** (split every / tween / rides / once / await), **events**, async **scripts**. Fire rates: `every` / `after` / `when` / tween-complete / mode-exit per second over the measured window.

`RESULT_JSON:` one line on stdout for the parent / suite parser.

## If a cell moved

The pulse is a **detector**. After a noteworthy median shift:

| Cell | Next isolate |
|------|----------------|
| mix `tick_ms` | `--suite` — which mode moved? |
| ride `tick_ms` | `--mode ride --hide --profile`; `--face` vs default; `--tracks unique` vs `shared` |
| tween `tick_ms` | `--mode tween --hide --profile` (on_done re-arm vs write) |
| timers `tick_ms` | `--mode timers --tight --profile`; `--no-readout` A/B |
| when `flush_ms` | `--mode when --hide --profile`; if `tick_ms` moved it is `on_update` ink, not poll |
| process `tick_ms` | `--mode process --profile` (async resume / `parallel` / mode cancel) |
| mix `draw_ms` | `--hide` — if work_ms holds, it was paint, not scheduler |
| mix `coll_ms` | unexpected; nothing here enrolls |
| handles climb over a long run | [`soak_leak.py`](soak_leak.py); cancel / `destroy` / named replace |
| mix `tick_ms` and cpu_mix `tick_ms` | scheduler vs collision/spawn — both moved means process.py / pose write |

Do **not** fold this isolate into [`balanced.md`](balanced.md). `cpu_mix` stays the overall CPU pulse (scheduler **plus** collision and sprites). Use this file when that cell’s `tick_ms` / `flush_ms` moved, or when changing `process.py` / `events.py` / `track.py` rides.

## Mix proportions

At `n=120`: 36 ride, 28 tween, 24 timers, 20 when, 12 process. Other `--n` scales the same weights. Shared tracks; every fourth rider `face=True`.

Timer `after` is re-armed from `on_update`, not from the fire callback — optional
style in this isolate (the hop still wants a live handle to read `.remaining` /
`.elapsed` each frame). Re-arming `after(d, fn)` from inside `fn` is also safe:
`Scheduler.tick()` snapshots each bucket’s length, so a Handle created during that
call waits for the next tick (no same-pass spin on hitch / `delay=0`).

## Summary

Newest first. Primary: median **work_ms**. Phases in backticks (`t` tick, `f` flush, `d` draw).

| Date | Protocol | Host | mix work_ms (FPS) | suite notes | Notes |
|------|----------|------|------------------:|-------------|-------|
| 2026-10-14 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 2.060 (485.5) `t0.86 f0.04 d0.51` | ride tick **1.82** (n=200) is the heavy cell | |
| 2026-09-29 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.563 (639.9) `t0.73 f0.03 d0.43` | ride tick **1.56** (n=200) is the heavy cell | |
| 2026-09-28 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.449 (690.0) `t0.73 f0.03 d0.43` | ride tick **1.61** (n=200) is the heavy cell | |
| 2026-09-28 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.765 (566.4) `t0.78 f0.03 d0.44` | ride tick **1.63** (n=200) is the heavy cell | |
| 2026-09-24 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.284 (778.6) `t0.62 f0.03 d0.38` | ride tick **1.24** (n=200) is the heavy cell | |
| 2026-09-24 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.449 (690.1) `t0.75 f0.03 d0.41` | ride tick **1.69** (n=200) is the heavy cell | |
| 2026-09-24 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.548 (645.8) `t0.71 f0.03 d0.38` | ride tick **1.78** (n=200) is the heavy cell | |
| 2026-09-23 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.554 (643.7) `t0.72 f0.03 d0.38` | ride tick **1.70** (n=200) is the heavy cell | |
| 2026-09-22 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.339 (746.9) `t0.72 f0.03 d0.38` | ride tick **1.71** (n=200) is the heavy cell | |
| 2026-09-15 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.345 (743.5) `t0.70 f0.02 d0.38` | ride tick **1.70** (n=200) is the heavy cell | |
| 2026-09-12 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.363 (733.8) `t0.72 f0.03 d0.39` | ride tick **1.72** (n=200) is the heavy cell | |
| 2026-09-11 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.349 (741.4) `t0.71 f0.02 d0.38` | ride tick **1.69** (n=200) is the heavy cell | |
| 2026-09-10 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.520 (658.1) `t0.70 f0.02 d0.36` | ride tick **1.60** (n=200) is the heavy cell | |
| 2026-09-09 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.897 (527.2) `t0.89 f0.03 d0.57` | ride tick **1.91** (n=200) is the heavy cell | |
| 2026-09-05 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.925 (519.5) `t0.73 f0.03 d0.56` | ride tick **1.77** (n=200) is the heavy cell | mix-collision follow-up; tick hold vs first row |
| 2026-09-05 | `sched-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 1.817 (550.2) `t0.71 f0.03 d0.54` | ride tick **1.68** (n=200) is the heavy cell | first snapshot; coll ~0 |

---

## Runs

Newest first.

### 2026-10-14 — sched-1

| | |
|---|---|
| When | 2026-10-14 11:40 -0300 (14:40 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | e6cd88ec85a3 |
| Scena | `15bc8e1ffdca` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `c3baaa06a869` · `harness.py` `38953009d9e9` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **2.060** | 2.049–2.186 | ±7% |
| FPS | 485.5 | | |
| tick_ms | 0.855 | | |
| flush_ms | 0.038 | | |
| draw_ms | 0.506 | | |
| coll_ms | 0.024 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 3.409 | 1.817 | 0.001 | 0.724 | 293.4 | 200 | 0 |
| tween | 150 | 2.722 | 1.402 | 0.001 | 0.555 | 367.4 | 450 | 0 |
| timers | 200 | 1.514 | 0.316 | 0.001 | 0.740 | 660.4 | 400 | 0 |
| when | 200 | 2.740 | 0.734 | 0.328 | 0.727 | 365.0 | 38 | 400 |
| process | 80 | 0.895 | 0.247 | 0.001 | 0.317 | 1117.8 | 190 | 0 |
| mix | 120 | 1.851 | 0.791 | 0.034 | 0.473 | 540.3 | 202 | 40 |

### 2026-09-29 — sched-1

| | |
|---|---|
| When | 2026-09-29 11:33 -0300 (14:33 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `b6b17e300d76` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.563** | 1.529–1.566 | ±2% |
| FPS | 639.9 | | |
| tick_ms | 0.727 | | |
| flush_ms | 0.031 | | |
| draw_ms | 0.427 | | |
| coll_ms | 0.003 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.746 | 1.558 | 0.001 | 0.650 | 364.1 | 200 | 0 |
| tween | 150 | 2.194 | 1.296 | 0.001 | 0.498 | 455.8 | 450 | 0 |
| timers | 200 | 1.307 | 0.315 | 0.001 | 0.644 | 765.4 | 400 | 0 |
| when | 200 | 2.060 | 0.692 | 0.292 | 0.656 | 485.5 | 33 | 400 |
| process | 80 | 0.805 | 0.252 | 0.001 | 0.278 | 1242.8 | 192 | 0 |
| mix | 120 | 1.567 | 0.738 | 0.031 | 0.428 | 638.2 | 202 | 40 |

### 2026-09-28 — sched-1

| | |
|---|---|
| When | 2026-09-28 21:51 -0300 (00:51 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c80d3268bb2b` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `db212c4e3313` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.449** | 1.449–1.518 | ±5% |
| FPS | 690.0 | | |
| tick_ms | 0.725 | | |
| flush_ms | 0.031 | | |
| draw_ms | 0.429 | | |
| coll_ms | 0.003 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.571 | 1.607 | 0.001 | 0.664 | 389.0 | 200 | 0 |
| tween | 150 | 2.114 | 1.329 | 0.001 | 0.501 | 473.0 | 450 | 0 |
| timers | 200 | 1.230 | 0.315 | 0.001 | 0.651 | 813.0 | 400 | 0 |
| when | 200 | 1.889 | 0.670 | 0.288 | 0.654 | 529.3 | 36 | 400 |
| process | 80 | 0.749 | 0.260 | 0.001 | 0.277 | 1335.4 | 193 | 0 |
| mix | 120 | 1.477 | 0.729 | 0.031 | 0.449 | 677.2 | 202 | 40 |

### 2026-09-28 — sched-1

| | |
|---|---|
| When | 2026-09-28 21:18 -0300 (00:18 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `db212c4e3313` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.765** | 1.727–1.977 | ±14% |
| FPS | 566.4 | | |
| tick_ms | 0.782 | | |
| flush_ms | 0.034 | | |
| draw_ms | 0.443 | | |
| coll_ms | 0.004 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.808 | 1.628 | 0.001 | 0.646 | 356.1 | 200 | 0 |
| tween | 150 | 2.251 | 1.380 | 0.001 | 0.496 | 444.2 | 450 | 0 |
| timers | 200 | 1.177 | 0.300 | 0.001 | 0.647 | 849.9 | 400 | 0 |
| when | 200 | 1.836 | 0.662 | 0.288 | 0.646 | 544.7 | 36 | 400 |
| process | 80 | 0.714 | 0.244 | 0.001 | 0.275 | 1400.2 | 193 | 0 |
| mix | 120 | 1.445 | 0.751 | 0.031 | 0.424 | 692.3 | 202 | 40 |

### 2026-09-24 — sched-1

| | |
|---|---|
| When | 2026-09-24 21:08 -0300 (00:08 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `17d2f4de648a` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.284** | 1.280–1.294 | ±1% |
| FPS | 778.6 | | |
| tick_ms | 0.618 | | |
| flush_ms | 0.028 | | |
| draw_ms | 0.379 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.104 | 1.243 | 0.001 | 0.586 | 475.4 | 200 | 0 |
| tween | 150 | 1.852 | 1.153 | 0.001 | 0.442 | 539.9 | 450 | 0 |
| timers | 200 | 1.122 | 0.285 | 0.001 | 0.582 | 891.2 | 400 | 0 |
| when | 200 | 1.726 | 0.608 | 0.261 | 0.589 | 579.3 | 37 | 400 |
| process | 80 | 0.695 | 0.232 | 0.001 | 0.257 | 1439.3 | 193 | 0 |
| mix | 120 | 1.309 | 0.650 | 0.028 | 0.383 | 763.7 | 202 | 40 |

### 2026-09-24 — sched-1

| | |
|---|---|
| When | 2026-09-24 20:24 -0300 (23:24 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.449** | 1.428–1.452 | ±2% |
| FPS | 690.1 | | |
| tick_ms | 0.752 | | |
| flush_ms | 0.034 | | |
| draw_ms | 0.407 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.556 | 1.690 | 0.001 | 0.612 | 391.3 | 200 | 0 |
| tween | 150 | 1.906 | 1.202 | 0.001 | 0.469 | 524.6 | 450 | 0 |
| timers | 200 | 1.212 | 0.371 | 0.001 | 0.603 | 825.3 | 400 | 0 |
| when | 200 | 1.893 | 0.723 | 0.310 | 0.618 | 528.1 | 36 | 400 |
| process | 80 | 0.722 | 0.269 | 0.001 | 0.259 | 1385.3 | 194 | 0 |
| mix | 120 | 1.405 | 0.735 | 0.033 | 0.397 | 711.5 | 202 | 40 |

### 2026-09-24 — sched-1

| | |
|---|---|
| When | 2026-09-24 10:36 -0300 (13:36 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.548** | 1.489–1.562 | ±5% |
| FPS | 645.8 | | |
| tick_ms | 0.714 | | |
| flush_ms | 0.034 | | |
| draw_ms | 0.384 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.788 | 1.780 | 0.001 | 0.583 | 358.7 | 200 | 0 |
| tween | 150 | 1.879 | 1.040 | 0.001 | 0.445 | 532.2 | 450 | 0 |
| timers | 200 | 1.329 | 0.367 | 0.001 | 0.581 | 752.5 | 400 | 0 |
| when | 200 | 2.049 | 0.727 | 0.315 | 0.586 | 488.0 | 35 | 400 |
| process | 80 | 0.794 | 0.263 | 0.001 | 0.240 | 1260.0 | 193 | 0 |
| mix | 120 | 1.518 | 0.715 | 0.033 | 0.376 | 658.7 | 202 | 40 |

### 2026-09-23 — sched-1

| | |
|---|---|
| When | 2026-09-23 20:19 -0300 (23:19 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `88e64c88ecb1` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.554** | 1.497–1.562 | ±4% |
| FPS | 643.7 | | |
| tick_ms | 0.719 | | |
| flush_ms | 0.034 | | |
| draw_ms | 0.384 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.773 | 1.700 | 0.001 | 0.571 | 360.6 | 200 | 0 |
| tween | 150 | 1.873 | 1.046 | 0.001 | 0.448 | 533.9 | 450 | 0 |
| timers | 200 | 1.331 | 0.375 | 0.001 | 0.584 | 751.2 | 400 | 0 |
| when | 200 | 2.038 | 0.708 | 0.314 | 0.586 | 490.7 | 35 | 400 |
| process | 80 | 0.794 | 0.264 | 0.001 | 0.242 | 1259.9 | 193 | 0 |
| mix | 120 | 1.521 | 0.706 | 0.033 | 0.377 | 657.7 | 202 | 40 |

### 2026-09-22 — sched-1

| | |
|---|---|
| When | 2026-09-22 20:27 -0300 (23:27 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c91c4e4c91e7` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.339** | 1.318–1.359 | ±3% |
| FPS | 746.9 | | |
| tick_ms | 0.721 | | |
| flush_ms | 0.029 | | |
| draw_ms | 0.384 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.499 | 1.711 | 0.001 | 0.581 | 400.2 | 200 | 0 |
| tween | 150 | 1.707 | 1.062 | 0.001 | 0.445 | 585.9 | 450 | 0 |
| timers | 200 | 1.170 | 0.368 | 0.001 | 0.603 | 854.6 | 400 | 0 |
| when | 200 | 1.770 | 0.717 | 0.274 | 0.594 | 564.9 | 36 | 400 |
| process | 80 | 0.684 | 0.264 | 0.001 | 0.242 | 1461.7 | 194 | 0 |
| mix | 120 | 1.366 | 0.716 | 0.029 | 0.377 | 731.9 | 202 | 40 |

### 2026-09-15 — sched-1

| | |
|---|---|
| When | 2026-09-15 13:21 -0300 (16:21 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `8303d83b3439` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.345** | 1.315–1.357 | ±3% |
| FPS | 743.5 | | |
| tick_ms | 0.700 | | |
| flush_ms | 0.024 | | |
| draw_ms | 0.377 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.537 | 1.702 | 0.001 | 0.573 | 394.2 | 200 | 0 |
| tween | 150 | 1.720 | 1.048 | 0.001 | 0.442 | 581.5 | 450 | 0 |
| timers | 200 | 1.176 | 0.365 | 0.001 | 0.579 | 850.7 | 400 | 0 |
| when | 200 | 1.771 | 0.721 | 0.229 | 0.582 | 564.8 | 36 | 400 |
| process | 80 | 0.694 | 0.262 | 0.001 | 0.238 | 1440.6 | 194 | 0 |
| mix | 120 | 1.347 | 0.703 | 0.024 | 0.381 | 742.4 | 202 | 40 |

### 2026-09-12 — sched-1

| | |
|---|---|
| When | 2026-09-12 11:51 -0300 (14:51 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `00c71e0ec4d9` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.363** | 1.346–1.366 | ±2% |
| FPS | 733.8 | | |
| tick_ms | 0.720 | | |
| flush_ms | 0.025 | | |
| draw_ms | 0.388 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.486 | 1.715 | 0.001 | 0.584 | 402.3 | 200 | 0 |
| tween | 150 | 1.669 | 1.048 | 0.001 | 0.446 | 599.1 | 450 | 0 |
| timers | 200 | 1.129 | 0.364 | 0.001 | 0.587 | 886.1 | 400 | 0 |
| when | 200 | 1.716 | 0.720 | 0.228 | 0.588 | 582.8 | 36 | 400 |
| process | 80 | 0.678 | 0.261 | 0.001 | 0.244 | 1476.0 | 194 | 0 |
| mix | 120 | 1.304 | 0.710 | 0.024 | 0.391 | 766.7 | 202 | 40 |

### 2026-09-11 — sched-1

| | |
|---|---|
| When | 2026-09-11 21:26 -0300 (00:26 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c2f322da89d6` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `3d97e030dbf3` · `harness.py` `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.349** | 1.325–1.351 | ±2% |
| FPS | 741.4 | | |
| tick_ms | 0.709 | | |
| flush_ms | 0.025 | | |
| draw_ms | 0.376 | | |
| coll_ms | 0.002 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.513 | 1.691 | 0.001 | 0.558 | 397.9 | 200 | 0 |
| tween | 150 | 1.695 | 1.031 | 0.001 | 0.431 | 590.1 | 450 | 0 |
| timers | 200 | 1.157 | 0.367 | 0.001 | 0.564 | 863.9 | 400 | 0 |
| when | 200 | 1.789 | 0.731 | 0.231 | 0.587 | 558.8 | 35 | 400 |
| process | 80 | 0.691 | 0.265 | 0.001 | 0.236 | 1446.5 | 194 | 0 |
| mix | 120 | 1.334 | 0.713 | 0.024 | 0.365 | 749.7 | 202 | 40 |

### 2026-09-10 — sched-1

| | |
|---|---|
| When | 2026-09-10 14:15 -0300 (17:15 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `1aa4c20cdbb9` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `062b1848c399` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.520** | 1.435–1.539 | ±7% |
| FPS | 658.1 | | |
| tick_ms | 0.696 | | |
| flush_ms | 0.024 | | |
| draw_ms | 0.355 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 2.691 | 1.597 | 0.001 | 0.532 | 371.6 | 200 | 0 |
| tween | 150 | 1.848 | 0.991 | 0.001 | 0.413 | 541.1 | 450 | 0 |
| timers | 200 | 1.262 | 0.354 | 0.001 | 0.543 | 792.6 | 400 | 0 |
| when | 200 | 1.931 | 0.699 | 0.223 | 0.543 | 517.8 | 37 | 400 |
| process | 80 | 0.767 | 0.249 | 0.001 | 0.225 | 1304.4 | 192 | 0 |
| mix | 120 | 1.434 | 0.683 | 0.023 | 0.355 | 697.4 | 202 | 40 |

### 2026-09-09 — sched-1

| | |
|---|---|
| When | 2026-09-09 16:20 -0300 (19:20 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `09bca538ac9f` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `062b1848c399` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.897** | 1.884–1.936 | ±3% |
| FPS | 527.2 | | |
| tick_ms | 0.893 | | |
| flush_ms | 0.032 | | |
| draw_ms | 0.569 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 3.515 | 1.905 | 0.001 | 0.884 | 284.5 | 200 | 0 |
| tween | 150 | 2.623 | 1.408 | 0.001 | 0.674 | 381.3 | 450 | 0 |
| timers | 200 | 1.772 | 0.511 | 0.001 | 0.892 | 564.4 | 400 | 0 |
| when | 200 | 2.582 | 0.907 | 0.334 | 0.909 | 387.2 | 33 | 400 |
| process | 80 | 1.137 | 0.411 | 0.001 | 0.383 | 879.2 | 196 | 0 |
| mix | 120 | 1.889 | 0.909 | 0.032 | 0.575 | 529.5 | 202 | 40 |

### 2026-09-05 — sched-1

| | |
|---|---|
| When | 2026-09-05 19:24 -0300 (22:24 UTC) |
| Protocol | `sched-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `3a4d14543b38` |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `062b1848c399` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.925** | 1.769–2.019 | ±13% |
| FPS | 519.5 | | |
| tick_ms | 0.732 | | |
| flush_ms | 0.032 | | |
| draw_ms | 0.557 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 3.296 | 1.769 | 0.001 | 0.884 | 303.4 | 200 | 0 |
| tween | 150 | 2.257 | 1.123 | 0.001 | 0.662 | 443.1 | 450 | 0 |
| timers | 200 | 1.683 | 0.369 | 0.001 | 0.868 | 594.3 | 400 | 0 |
| when | 200 | 2.466 | 0.755 | 0.329 | 0.881 | 405.6 | 32 | 400 |
| process | 80 | 0.981 | 0.259 | 0.001 | 0.363 | 1019.7 | 193 | 0 |
| mix | 120 | 1.819 | 0.731 | 0.032 | 0.561 | 549.7 | 202 | 40 |

### 2026-09-05 — sched-1

| | |
|---|---|
| When | 2026-09-05 (first snapshot) |
| Protocol | `sched-1` |
| Host | Apple M4, arm64, Darwin 26.6.2, Python 3.12.13 |
| Git | none |
| Repeats | mix 3 (median); suite single-shot |
| Scripts | `sched.py` `68ab95916fb7` · `harness.py` `1b961ba409de` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

**Bottleneck readout.** Among isolates, **`move_along` is the expensive axis** (`ride` `tick_ms` 1.68 at n=200). Pose tween is next (1.09 at 150 bodies / 450 live tweens). `@when` is the only cell that moves `flush_ms` (0.32 at 400 events). Dense `every`/`after` (4000 + 1600 fires/s) is cheaper than rides (`tick_ms` 0.36). `coll_ms` stayed ~0. Mix `draw_ms` ~0.54 is 120 small circles — `--hide` peels it if tick is the question.

#### mix (median of 3)

| Metric | Median | min–max | spread |
|--------|------:|--------:|-------:|
| work_ms | **1.817** | 1.794–1.847 | ±3% |
| FPS | 550.2 | 541.4–557.3 | |
| tick_ms | 0.711 | | |
| flush_ms | 0.030 | | |
| draw_ms | 0.540 | | |
| coll_ms | 0.001 | | |
| handles | 202 | | |
| events | 40 | | |

#### suite (single-shot)

| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |
|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|
| ride | 200 | 3.337 | **1.680** | 0.001 | 0.834 | 299.7 | 200 | 0 |
| tween | 150 | 2.327 | 1.090 | 0.001 | 0.643 | 429.7 | 450 | 0 |
| timers | 200 | 1.708 | 0.355 | 0.001 | 0.840 | 585.4 | 400 | 0 |
| when | 200 | 2.517 | 0.744 | **0.318** | 0.894 | 397.3 | 33 | 400 |
| process | 80 | 1.004 | 0.253 | 0.001 | 0.366 | 996.2 | 193 | 0 |
| mix | 120 | 1.848 | 0.722 | 0.031 | 0.538 | 541.3 | 202 | 40 |

---

### Run template

```markdown
### YYYY-MM-DD — sched-1

| | |
|---|---|
| When | |
| Protocol | sched-1 (pro-forma: yes/no — why) |
| Host | |
| Git | |
| Stage | (sha256[:12] of `scena/**/*.py`) |
| Repeats | 3 (median) mix; suite single-shot or 3 |
| Scripts | sched.py …  harness.py … |

Frozen argv as in the protocol table.

#### mix
#### suite (optional)
```
