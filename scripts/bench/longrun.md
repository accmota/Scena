# Long-run pulse (jitter · hitches · GC · drift)

Minutes of a busy scene in the **product loop** — real pacing, real present, real GC — measured frame by frame. Catches what every other pulse is blind to by construction: they run 2–3 s, uncapped, in a replica loop (`harness.install_phase_run`), and discard warm-up.

Runner: [`longrun.py`](longrun.py). Probe: [`frame_probe.py`](frame_probe.py) via [`jitter_probe.py`](jitter_probe.py). Workload: [`live_mix.py`](live_mix.py) (sprites + shapes + SpatialFx + camera + background fields + spawn/destroy churn + HUD + vignette).

## Why

"Runs at 400–500 fps but still stutters now and then" is not a cost problem, so cost isolates cannot see it. Candidates this pulse separates:

| Symptom | Likely cause | What shows it |
|---------|--------------|---------------|
| ~1 s of judder every N seconds/minutes, then smooth | frame timer (fixed 60, vsync off) beating against the display refresh | `held` / `dropped` **episodes** with regular spacing ≈ predicted beat |
| single 10–30 ms hitch at random | GC gen2 pass, OS preemption, present blocked | worst-frames table: `gc2`, `pace`, `swap` |
| stutter in the first seconds | first-use work (shaders, glyphs, decode), young-heap GC | startup window; [`startup.md`](startup.md) |
| slower after 20 minutes | leak / growing structure | drift slopes (RSS, Python objects, graph nodes, work) |

## What it scores

| Metric | What |
|--------|------|
| `held /min` | a displayed image stayed on screen longer than pacing intends (vsync model; macOS CoreVideo timeline). **Primary.** |
| episodes /min | held/dropped events clustered (≤ 1 s apart) — what a person perceives as "a moment of jitter" |
| episode spacing vs predicted beat | measured median spacing vs `1 / |frame Hz − refresh Hz|` |
| hitch /min | frame duration (= next `dt`) > 1.5 display periods, steady part |
| dur p99 | steady frame-duration p99 (ms) |
| gc2 max | longest gen-2 GC pass (ms) |
| RSS /10min | resident-memory slope after the startup window |
| work %/10min | slope of per-10 s median CPU work |

**Vsync model.** The probe records real vsync timestamps (CoreVideo `inOutputTime`, the vblank's own time, since `longrun-2`) and assigns each presented frame to the first vsync after `glfwSwapBuffers` returns (+ `latch_ms`, default 0). The compositor latch is not observable; it moves *when* an episode lands, not how many there are or their spacing. No CoreVideo (non-macOS) → only cadence metrics. Windows: [`win/win_jitter_probe.py`](win/win_jitter_probe.py) adds a DWM vsync clock through a wrapper, without touching the fingerprinted scripts.

**Vblank grid check** (`longrun-2`, latch-free): fit a regular grid to the vsync stamps, count how many vblanks each present advances. A steady cadence is one value (`{1: n}` at 60 on 60 Hz); a beat shows 0s and 2s. `off-cadence /min` = frames off the most common step. The report also prints the pacer (`strategy`, `interval`, fallback) and CPU % of one core; `pace` is the pacer's wait before the swap (it is no longer counted as work).

## How to run

From the **repo root**.

```bash
python scripts/bench/longrun.py --pulse                         # protocol longrun-1 (5 min), append
python scripts/bench/longrun.py --minutes 30                    # ad-hoc soak, print only
python scripts/bench/longrun.py --minutes 5 --present vsync     # A/B pacing
python scripts/bench/longrun.py --minutes 5 --gc-freeze         # A/B GC
python scripts/bench/jitter_probe.py examples/naves_1.py --seconds 120   # any app
```

Keep the window **visible and in front** (macOS throttles occluded windows) and leave the machine alone.

## Protocol `longrun-2`

`longrun-2` (2026-09-29): product pacing is display-locked (see Findings 2026-09-29), the GC freeze is on, and `frame_probe.py` changed (CoreVideo output time, grid check, pacer wait = `pace`, `Clock._tick` hook; a missing hook now fails the install instead of hanging the run). Framerate is `canvas.framerate` (`live_mix.py` sets `"max"`; the probe's `--present` replaces it at the first frame). Rows before it (`longrun-1`) measured the old free-running timer; do not compare `held /min` across the two.

Bump this id if you change [`longrun.py`](longrun.py), [`jitter_probe.py`](jitter_probe.py), [`frame_probe.py`](frame_probe.py), [`live_mix.py`](live_mix.py), or a frozen flag.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| pulse | `jitter_probe.py live_mix.py --seconds 300 --present auto --startup 10 --objects-every 30` | One 5-min run. Present `auto` = product default (FX Auto → fixed 60, vsync off). |

**Noise rule.** One run; event rates are counts, so small numbers swing. Rates < 1/min are compared by eye; ≥ 1/min, **≳30%** is noteworthy. Drift slopes from a 5-min run are indicative only — use `--minutes 30` to confirm a leak.

## Findings 2026-09-29 (the fix: display-locked pacing + GC freeze)

Windows data (Dell Latitude 5330, Iris Xe, Win 11, CPython 3.14.7). What it settled:

- **The beat reproduces on Windows** (PRECISION at 59.815 Hz vs a 60.002 Hz panel: 41 held + 30 dropped /min, an episode every 5.8 s). Part of it was a bug: `target = frame start + period` accumulated each frame's lateness. Fixed: absolute schedule.
- **Plain VSync is exact on Windows GL**: `swap_interval(1)` advanced exactly one vblank per frame, windowed (4801/4801) and fullscreen (3001/3001), at 24–36 % of a core (PRECISION: ~100 %). On macOS it is not (61.8 Hz, 13 hitches/min here; GLFW #1990 / #2249).
- **gen-2 GC is 37–54 ms there**, on 3.14.7: CPython 3.14.5 rolled back the incremental GC. `gc.freeze()` after setup removed them (R3). Even the incremental GC (3.14.3 here) made 24 ms increments on a 400k-object heap, 0.29 ms after a freeze.
- The DWM vsync reader must key on `qpcVBlank` (`cRefresh` counts calls on Win 11 26200); its timeline is invalid in fullscreen.

The fix (Scena Design, [Frame pacing and GC](../../design/Scena%20Design.md#frame-pacing-and-gc)): `scena/pacing.py` — Windows/Linux native VSync with a self-check, macOS a CoreVideo display link (present 1 ms after vblank), fixed caps on an absolute schedule; world `dt` snapped to whole vblank periods; FX Auto rungs locked to the vblank divisor nearest 60 / 30; `scena/gc_policy.py` freezes after the build and re-freezes at each scene change.

Mac results after the fix (Apple M4, Dell P2723QE 59.997 Hz, 40–60 s runs, `--present auto` unless noted):

| Run | Python | strategy | vblank steps (steady) | held /min | work spikes /min | gen2 after setup | CPU % 1 core |
|-----|--------|----------|-----------------------|----------:|-----------------:|------------------|-------------:|
| before: `longrun-1` pulse, live_mix 5 min | 3.12 | timer | — | 63.78 | 2.8–3.7 | 19 × ≤ 9.8 ms | ~93 |
| app_first | 3.12 | display_link | {1: 2097, 3: 1} (an OS `poll` stall) | 1.50 | — | none | 16 |
| live_mix | 3.14.3 | display_link | {1: 2998, 2: 1} | 2.00 | 0.00 | none | 52 (work 7.6 ms) |
| app_first `--present fixed60` | 3.12 | timer | {1: 1500} | 0.00 | — | none | 31 |

Fixed 60 now presents at 60.0011 Hz against 59.997 → predicted beat 227 s (was seconds). The present phase under the display link stays at 0.19–0.23 of the period for the whole run (it used to walk through it).

**Still to run on Windows** (3.14.7 and 3.12) — procedure (~15 min): expect `strategy native`, vblank steps `{1: all}` (or `{2: all}` on the 30 rung), ~30 % CPU on `app_first`, no gen-2 after setup. The Windows wrapper feeds the grid check with the DWM timeline (windowed; use `--vsync-source d3dkmt` in fullscreen, where DWM's timeline is invalid). From the repo root, `OUT` = `scripts/bench/results/windows-jitter-fix`:

```
python scripts/bench/win/win_jitter_probe.py --raw OUT/V1_first.raw.json tests/loads/app_first.py --seconds 90 --present auto --startup 10 --json OUT/V1_first.json
python scripts/bench/win/win_jitter_probe.py --display fullscreen --vsync-source d3dkmt --raw OUT/V2_first_fs.raw.json tests/loads/app_first.py --seconds 60 --present auto --startup 10 --json OUT/V2_first_fs.json
python scripts/bench/win/win_jitter_probe.py --raw OUT/V3_galaga.raw.json examples/app_galaga_v3.py --seconds 120 --present auto --startup 10 --json OUT/V3_galaga.json
python scripts/bench/win/win_jitter_probe.py --raw OUT/V4_live_mix.raw.json scripts/bench/live_mix.py --seconds 120 --present auto --startup 10 --objects-every 30 --json OUT/V4_live_mix.json
```

Read the `vblank grid check`, `pacer` and `gc` lines of each report. `live_mix` cannot hold 60 on that laptop: expect FX Auto to settle on the 30 rung (`interval 2`) with overloaded frames slipping (off-cadence > 0) — by design, nothing below 30.

## Findings 2026-09-24 (first diagnosis, stage `4000c948cf65`)

`live_mix` under `jitter_probe.py`, Apple M4, Dell P2723QE at **59.997 Hz** (not 60.000). 3-min A/B runs + one 10-min run. Frame work ≈ 7.5 ms, so every frame has ~9 ms of slack.

| Run | dt p99.9 | hitch /min | held /min | judder episodes | gen2 GC (n / total / max) | work spikes /min |
|-----|---------:|-----------:|----------:|-----------------|---------------------------|-----------------:|
| `auto` (product: fixed 60, vsync off), 10 min | 16.80 | 0.51 | 44 | 59 (3 lasting 9–13 s) | 40 / 308 ms / 8.8 ms | 3.7 |
| `auto`, 3 min | 16.77 | 0.35 | 76 | 17 (3 lasting 6–11 s) | 12 / 91 ms / 8.5 ms | 2.8 |
| `vsync` (swap interval 1), 3 min | 33.55 | **13.4** | 105 | 27 | 12 / 104 ms / 9.8 ms | 5.3 |
| `auto` + `gc.freeze()` after setup, 3 min | 16.79 | 0.00 | 69 | 16 | 22 / **21 ms** / 6.9 ms¹ | **0.0** |

¹ the explicit `gc.collect()` before freezing; later passes ≈ 1 ms.

1. **"~1 s of jitter every so often" = beat between the 60 Hz timer and the display.** Cadence is near-perfect (dt p99.9 16.8 ms), yet the displayed image repeats and skips in clusters. The present phase inside the vsync interval drifts steadily (≈ one lap per 40–70 s here, from 60.00 vs 59.997 Hz plus µs-level pacing bias). Every large episode sits at phase ≈ 0.93–0.03, i.e. where presents straddle the vsync / compositor latch; there, µs of timer noise decides which vsync a frame lands on, so frames alternately double and drop. More CPU headroom cannot fix this; the frame timer has to lock to the display.
   - The vsync model assumes latch 0, so the *length* of an episode is an upper bound (vsync timestamp jitter p99 ≈ 1 ms widens the band). Their existence, spacing and phase alignment do not depend on the latch.
2. **Plain VSync is not the fix on macOS GL.** `swap_interval(1)` ran at 61.8 Hz (swap does not strictly block), with 13 hitches/min and more held frames. A fix would pace from the real vsync timeline (CoreVideo display link on macOS, which `frame_probe.VsyncClock` already reads via ctypes) — e.g. start the frame at a fixed offset after vsync — instead of a free-running `perf_counter` timer. Framework decision, not done here.
3. **Periodic single hitches = gen-2 GC.** Full collections every ~15 s cost 8–9 ms here (≈ 35 ms on the 4× target → a visible hitch every 15 s). Short episodes at 33.6 / 48.8 / 122.0 / 137.5 s coincide with them. `gc.collect(); gc.freeze()` after setup made gen-2 passes ≈ 1 ms and removed all steady work spikes. Candidate framework change: freeze after `setup()` (and after big scene builds).
4. **Startup:** frame 1 ≈ 90 ms (`poll` +45 ms while the window appears, first `update` +20 ms), frame 2 ≈ 37 ms, then steady. See [`startup.md`](startup.md).
5. **Pacing burns a core.** Fixed-60 sleeps 1 ms then busy-waits the rest (~8 of every 16.7 ms here), so the process sits at ~93% of a core with frame work at 7.5 ms. On a laptop-class target that means heat and battery, and thermal throttling can itself cause slowdowns over a long run.
6. **No leak / no drift in 10 min:** RSS 186.8 → 169.0 MiB, Python objects flat, graph nodes and entities flat, work drift +0.4 %/10 min. Rare one-off stalls came from the OS (`swap` +101 ms, `poll` +46 ms), not Stage.

**Uncapped example apps** (`app_galaga_v3.py` sets `FrameRateControl.NONE` — the 400–500 fps case; 5 min, 505 fps):

- No held frames or episodes (the beat needs a ~60 Hz timer). Instead there is a constant mild micro-judder: the frame shown at each vsync was sampled up to one frame earlier, so motion error is p50 0.42 / p99 2.2 ms per displayed step (~13% of a display interval).
- **Early-run spikes:** frames at 5.0–7.4 s cost 21–24 ms, all `draw +21 ms`: first-use draw work as new things appear. On the 4× target that is ~90 ms, which matches "stutters right after start". Frame 1: 51 ms (`poll` +29).
- One gen-2 GC (10.8 ms) and one OS present stall (`swap` +14 ms) in 5 min.
- **To confirm with a 30-min run:** RSS 188.5 → 218.7 MiB, graph nodes +207/10 min and Python objects +9.9k/10 min while entity count stays flat. That could be cache warm-up or an orphan-node leak.

Reproduce: `python scripts/bench/jitter_probe.py scripts/bench/live_mix.py --seconds 180 --present auto` (then `--present vsync`, then `--present auto --gc-freeze`).

## Summary

Newest first. Primary: **held /min** (episodes /min).

| Date | Protocol | Host | held /min (episodes) | hitch /min | dur p99 ms | gc2 max ms | RSS MiB/10min | work %/10min | startup worst ms | Notes |
|------|----------|------|---------------------:|-----------:|-----------:|-----------:|--------------:|-------------:|-----------------:|-------|
| 2026-09-29 | `longrun-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 63.78 (4.20) | 0.41 | 16.67 | 9.8 | -2.80 | -4.9 | 70.9 | |
| 2026-09-28 | `longrun-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | — (—) | 1.45 | 16.68 | 9.7 | 16.83 | -3.2 | 319.5 | |
| 2026-09-24 | `longrun-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | — (—) | 0.00 | 16.68 | 13.2 | 7.79 | -2.9 | 40.0 | |
| 2026-09-24 | `longrun-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 61.58 (6.80) | 0.21 | 16.69 | 10.0 | -33.40 | -0.7 | 83.2 | first row · big episodes at present phase ≈ 0.95 (timer/vsync beat, see Findings) |

---

## Runs

Newest first.

### 2026-09-29 — longrun-1

| | |
|---|---|
| When | 2026-09-29 11:38 -0300 (14:38 UTC) |
| Protocol | `longrun-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Run | 5 min · present `auto` → PRECISION 60 Hz · display 59.997 Hz |
| Scripts | `longrun.py` `2079f0e327da` · `jitter_probe.py` `d26eae8c448a` · `frame_probe.py` `6e76703d984f` · `live_mix.py` `2241f297c2dc` |

| Metric | Value |
|--------|------:|
| frames / fps | 17992 / 60.0 |
| held frames /min (episodes /min) | **63.78** (4.20) |
| dropped /min | 62.98 |
| episode spacing (predicted beat) | 3.6 s (60.8 s) |
| frames Hz vs refresh Hz | 59.9802 vs 59.9967 |
| hitches /min (dur > 25.0 ms) | 0.41 |
| dur p50 / p99 / max (steady) | 16.67 / 16.67 / 40.2 ms |
| work p50 / p99 (steady) | 7.981 / 9.175 ms |
| GC gen2 n / max | 19 / 9.8 ms |
| RSS first→last (slope) | 192.6 → 190.7 MiB (-2.80 MiB/10min) |
| Python objects (slope) | 91524 → 92571 (-1454/10min) |
| work drift | -4.9 %/10min |
| startup worst frame | 70.9 ms |

Episodes (start / length): 18s/0.0s, 34s/0.0s, 42s/1.5s, 46s/0.0s, 48s/28.4s, 77s/0.2s, 78s/0.3s, 159s/0.0s, 172s/0.0s, 175s/0.2s, 177s/0.0s, 179s/0.7s

Worst frames:

| t s | dur ms | work ms | swap ms | pace ms | cause |
|----:|-------:|--------:|--------:|--------:|-------|
| 0.0 | 70.9 | 66.9 | 4.0 | 0.0 | gc1 0.6, poll +37.1, other +13.0 |
| 186.8 | 40.2 | 9.9 | 30.3 | 0.1 | swap +30.0, coll +0.5 |
| 200.8 | 30.0 | 10.5 | 19.6 | 0.0 | swap +19.3, update +0.6 |
| 191.6 | 18.2 | 17.9 | 0.3 | 0.0 | gc2 9.8, coll +9.8 |
| 18.5 | 18.2 | 17.8 | 0.3 | 0.0 | gc2 8.8, coll +9.1 |
| 222.8 | 17.9 | 17.5 | 0.3 | 0.0 | gc2 8.7, coll +9.0 |
| 159.4 | 17.8 | 17.5 | 0.3 | 0.0 | gc2 8.7, coll +9.0 |
| 34.5 | 17.4 | 17.1 | 0.3 | 0.0 | gc2 8.4, coll +8.9 |

### 2026-09-28 — longrun-1

| | |
|---|---|
| When | 2026-09-28 21:23 -0300 (00:23 UTC) |
| Protocol | `longrun-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Run | 5 min · present `auto` → PRECISION 60 Hz · display 60.000 Hz |
| Scripts | `longrun.py` `2079f0e327da` · `jitter_probe.py` `d26eae8c448a` · `frame_probe.py` `6e76703d984f` · `live_mix.py` `2241f297c2dc` |

| Metric | Value |
|--------|------:|
| frames / fps | 17946 / 59.8 |
| held frames /min (episodes /min) | **—** (—) |
| dropped /min | — |
| episode spacing (predicted beat) | — s (— s) |
| frames Hz vs refresh Hz | — vs — |
| hitches /min (dur > 25.0 ms) | 1.45 |
| dur p50 / p99 / max (steady) | 16.67 / 16.68 / 83.1 ms |
| work p50 / p99 (steady) | 8.245 / 9.988 ms |
| GC gen2 n / max | 19 / 9.7 ms |
| RSS first→last (slope) | 172.2 → 179.9 MiB (16.83 MiB/10min) |
| Python objects (slope) | 90796 → 91239 (-3200/10min) |
| work drift | -3.2 %/10min |
| startup worst frame | 319.5 ms |

Episodes (start / length): —

Worst frames:

| t s | dur ms | work ms | swap ms | pace ms | cause |
|----:|-------:|--------:|--------:|--------:|-------|
| 6.4 | 319.5 | 9.8 | 309.6 | 0.0 | swap +309.4, coll +0.6 |
| 4.2 | 132.9 | 128.9 | 3.5 | 0.5 | poll +106.0, coll +4.3 |
| 10.6 | 83.0 | 14.8 | 68.2 | 0.0 | swap +68.0, tick +2.3 |
| 6.7 | 81.6 | 70.5 | 11.1 | 0.0 | poll +45.6, swap +10.9 |
| 4.4 | 47.6 | 38.2 | 9.4 | 0.1 | poll +17.7, swap +9.2 |
| 6.9 | 41.3 | 23.1 | 18.2 | 0.0 | swap +18.0, coll +10.9 |
| 0.0 | 39.3 | 34.9 | 4.4 | 0.0 | gc1 0.5, other +12.9, update +6.8 |
| 59.0 | 37.1 | 36.8 | 0.3 | 0.0 | poll +27.7 |

### 2026-09-24 — longrun-1

| | |
|---|---|
| When | 2026-09-24 20:29 -0300 (23:29 UTC) |
| Protocol | `longrun-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Run | 5 min · present `auto` → PRECISION 60 Hz · display 60.000 Hz |
| Scripts | `longrun.py` `2079f0e327da` · `jitter_probe.py` `d26eae8c448a` · `frame_probe.py` `12f9864ac18b` · `live_mix.py` `a1622e496536` |

| Metric | Value |
|--------|------:|
| frames / fps | 17996 / 60.0 |
| held frames /min (episodes /min) | **—** (—) |
| dropped /min | — |
| episode spacing (predicted beat) | — s (— s) |
| frames Hz vs refresh Hz | — vs — |
| hitches /min (dur > 25.0 ms) | 0.00 |
| dur p50 / p99 / max (steady) | 16.67 / 16.68 / 17.7 ms |
| work p50 / p99 (steady) | 7.797 / 9.293 ms |
| GC gen2 n / max | 20 / 13.2 ms |
| RSS first→last (slope) | 185.6 → 187.4 MiB (7.79 MiB/10min) |
| Python objects (slope) | 86700 → 87092 (-123/10min) |
| work drift | -2.9 %/10min |
| startup worst frame | 40.0 ms |

Episodes (start / length): —

Worst frames:

| t s | dur ms | work ms | swap ms | pace ms | cause |
|----:|-------:|--------:|--------:|--------:|-------|
| 0.0 | 40.0 | 35.4 | 4.5 | 0.0 | other +13.1, update +6.8 |
| 3.4 | 23.6 | 23.2 | 0.4 | 0.0 | gc2 13.2, coll +13.9 |
| 18.1 | 17.7 | 17.4 | 0.3 | 0.0 | gc2 7.7, tick +7.9, coll +0.8 |
| 180.6 | 17.4 | 17.0 | 0.4 | 0.0 | gc2 8.2, coll +8.2 |
| 77.3 | 17.1 | 16.7 | 0.4 | 0.0 | gc2 7.9, coll +8.4 |
| 33.8 | 17.1 | 16.7 | 0.3 | 0.0 | gc2 8.1, coll +8.5 |
| 151.0 | 16.7 | 15.8 | 0.2 | 0.7 | gc2 7.6, coll +7.3 |
| 165.2 | 16.7 | 15.7 | 0.3 | 0.7 | gc2 7.4, coll +7.5 |

### 2026-09-24 — longrun-1

| | |
|---|---|
| When | 2026-09-24 11:43 -0300 (14:43 UTC) |
| Protocol | `longrun-1` |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `4000c948cf65` |
| Run | 5 min · present `auto` → PRECISION 60 Hz · display 59.997 Hz |
| Scripts | `longrun.py` `2079f0e327da` · `jitter_probe.py` `d26eae8c448a` · `frame_probe.py` `12f9864ac18b` · `live_mix.py` `a1622e496536` |

| Metric | Value |
|--------|------:|
| frames / fps | 17986 / 59.9 |
| held frames /min (episodes /min) | **61.58** (6.80) |
| dropped /min | 59.58 |
| episode spacing (predicted beat) | 3.1 s (30.7 s) |
| frames Hz vs refresh Hz | 59.9642 vs 59.9967 |
| hitches /min (dur > 25.0 ms) | 0.21 |
| dur p50 / p99 / max (steady) | 16.67 / 16.69 / 28.3 ms |
| work p50 / p99 (steady) | 7.498 / 9.361 ms |
| GC gen2 n / max | 20 / 10.0 ms |
| RSS first→last (slope) | 185.7 → 169.5 MiB (-33.40 MiB/10min) |
| Python objects (slope) | 86669 → 85910 (-828/10min) |
| work drift | -0.7 %/10min |
| startup worst frame | 83.2 ms |

Episodes (start / length): 0s/0.3s, 1s/0.0s, 3s/0.9s, 5s/0.0s, 15s/0.0s, 16s/6.9s, 45s/0.0s, 48s/0.0s, 60s/0.0s, 62s/0.0s, 66s/0.2s, 68s/6.6s

Worst frames:

| t s | dur ms | work ms | swap ms | pace ms | cause |
|----:|-------:|--------:|--------:|--------:|-------|
| 0.0 | 83.2 | 76.1 | 7.1 | 0.0 | poll +34.4, update +20.0 |
| 0.1 | 38.8 | 35.7 | 3.0 | 0.0 | update +25.1, other +3.4 |
| 232.1 | 28.3 | 9.5 | 18.8 | 0.0 | swap +18.6, tick +0.6 |
| 230.8 | 22.4 | 15.5 | 6.9 | 0.0 | poll +6.9, swap +6.7 |
| 0.2 | 22.4 | 15.0 | 7.3 | 0.0 | update +7.4, swap +7.1 |
| 168.8 | 22.4 | 18.3 | 4.0 | 0.0 | gc2 10.0, coll +10.0, swap +3.8 |
| 33.4 | 18.5 | 18.1 | 0.4 | 0.0 | gc2 9.2, coll +9.6 |
| 183.8 | 17.4 | 17.1 | 0.3 | 0.0 | gc2 8.6, coll +8.8 |

