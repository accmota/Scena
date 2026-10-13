# Game benchmarks

Whole games timed in the **real** run loop by [`game_bench.py`](game_bench.py): the
four benchmark games in [`games/`](games/README.txt) plus the tutorial-22 ninja
(`examples/ninja_perigos.py`). The other pulses time one subsystem each; these
time what an author's game costs, and where.

**Budget.** The target machine is about 4× slower than the M4 these rows come
from. A frame there has 16.7 ms, so a game must do **≤ 4 ms of work per frame
here** (`x4` ≈ work × 4). Each game has a **reference size** that must fit, and
a ladder that only shows how the cost grows ([games/README.txt](games/README.txt)).

## How to run

From the repo root (opens a window; uncapped pacing, FX Auto off).

```bash
python scripts/bench/game_bench.py examples/ninja_perigos.py
python scripts/bench/game_bench.py scripts/bench/games/horda.py --ladder n=50,150,400,1000
python scripts/bench/game_bench.py scripts/bench/games/mundo.py --cull ab
python scripts/bench/game_bench.py scripts/bench/games/festa.py --profile 40
```

Record `uptime` with a number: peers load this machine.

## Summary

Protocol `games-1`: the five games at reference size (ninja; horda n=150;
mundo tiles=1500, robots=20; corrida speed=600; festa n=300), 10 s recorded
after 3 s of warm-up, one fresh process each, uncapped, fb as opened (1× here).
Cells are work ms. Runner: [`run_games.py`](run_games.py) (in `run_all.py`).
Noise: ≲5 % is noise, ≳15 % noteworthy (auto-diff against the last row).

| Date | Protocol | Host | Load | ninja | horda | mundo | corrida | festa | Notes |
|------|----------|------|-----:|------:|------:|------:|--------:|------:|-------|
| 2026-10-12 | `games-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 4.1 | 2.83 | 15.19 | 23.60 | 1.98 | 36.18 | after group B (B1 B2 B4 B5, swept SAT, step skips) |
| 2026-10-12 | `games-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 2.3 | 5.06 | 16.99 | 96.26 | 3.02 | 37.21 | first runner row (HEAD after group A + B4/DG1) |
| 2026-10-12 | `games-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 3.2 | 5.12 | 18.41 | 98.67 | 3.02 | 37.83 | after group A (A1–A9, PF1); fingerprint `6eae4542094f`; corrida max 25 ms (slot builds) |
| 2026-10-12 | `games-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 2.3 | 8.90 | 20.01 | 156.9 | 5.34 | 38.37 | baseline before group A; fingerprint `9333a78e4e4d` |

## Diagnosis 2026-10-12

### Where the time goes (reference size, ms per frame, M4, load ≈ 2.3)

| Game | fps | work | x4 | processes | collision | scene draw | submit | Top cost |
|------|----:|-----:|---:|----------:|----------:|-----------:|-------:|----------|
| ninja | 109 | 8.90 | 35.6 | 6.91 | 1.13 | 0.64 | 0.06 | `floor_below`: 7 calls, 6.75 ms |
| horda | 49 | 20.0 | 80.0 | 1.43 | **17.1** | 1.01 | 0.18 | `resolve`: 12.7 ms (crowd) |
| mundo | 6 | 156.9 | 627 | **114** | 33.5 | 8.34 | 0.25 | `floor_below`: 21 calls, 112 ms |
| corrida | 179 | 5.34 | 21.4 | 3.09 | 1.22 | 0.71 | 0.07 | `floor_below` 2.8 ms; p99 12.6 / max 27.6 ms (slot builds) |
| festa | 26 | 38.4 | 154 | 4.64 | 2.14 | 7.68 | **22.6** | GPU submit of per-shot glow / Neon |

None of the five fits the budget at reference size. Ninja, the lightest real
game, misses it by 2×; rendering is not why.

### How it scales (ladders)

| Game | Rungs → work ms | Shape |
|------|-----------------|-------|
| horda n | 50 → 3.9 · 150 → 18.1 · 400 → 149 · 1000 → 771 (collision 2.6 → 15 → 138 → 740) | **quadratic** (resolve) |
| mundo tiles | 500 → 51 · 1500 → 163 · 4000 → 428 | linear in world size, **from a high base**: every query walks the whole group |
| corrida speed | 300 → 4.5 · 600 → 5.3 · 1500 → 4.8 · 3000 → 4.8 (p95 5.5 → 10.0) | flat mean; hitches grow with the slot rate |
| festa n | 100 → 13.2 · 300 → 38.8 · 1000 → 135 | linear, ≈ 130 µs per glowing shot (≈ 75 µs of it GPU submit) |

### Bottlenecks

**D1. Queries walk the whole group and rebuild every pose key** (ninja, mundo,
corrida). `floor_below(group=...)` refreshes the proxy of every member
(`_candidates_for_group` → `_update_proxy`, `collision.py` ~7134), and each
refresh rebuilds the full pose key, even for STATIC tiles that never moved
(Sprite `_collision_pose_extra` → `_hitbox_pose_wh` → `_du_per_px` through
`ScalarSlot.__get__`). The march then casts up to 15 times
(5 sub-steps × lift / across / drop), and every cast calls `_world_prims`, which
rebuilds the keys again: `_trust_proxy_world` is off outside `step()`.
- Ninja: about 91 refreshes and about 13 GJK time-of-impact sweeps per call, ≈ 0.95 ms per call.
- Mundo: about 34,000 proxy refreshes per frame.
- The other query APIs (`query_*`, `raycast`) have the same shape. `query_shape` also has no proxy-AABB reject (B3).

**D2. Tile hitboxes take the general sweep** (ninja, mundo, corrida). Level
tiles are image Sprites, so their hitbox is a polygon hull. `_toi_prim_sets`
takes the closed-form `_toi_fast` only when every prim is a circle or an AABB,
so an unrotated square tile goes to GJK (`_toi_advance`, `_gjk_distance`).

**D3. Every frame refreshes every proxy** (all games). `step()` calls
`_update_proxy` on every enrolled collider, static or not. That is
`ms_snapshot`: 0.47 ms for ninja's ~100 tiles, 8.0 ms for mundo's ~2000.
Nothing records "this body did not move". Collision keeps no pose revision,
and `_collision_epoch` misses translations and slot writes on purpose
(Collision Design, "World prims / pose keys").

**D4. Resolve is O(n²) in a crowd** (horda, mundo).
- Every pass (sweep, unswept recovery, up to four settle iterations, floor
  snap) walks the body's whole partner list in Python. In horda that is about
  56,000 `_proxy_aabb_overlap` calls per frame.
- Mundo's hero and robots each walk ~1560 ground tiles per pass.
- On top of that, the partner-identity cache (`_partner_ident_cache`) is
  cleared on **every** enroll / unenroll, any tag (bug H1). Every bullet or
  gem that horda makes or destroys makes every enemy rebuild its O(n) list next
  frame: `_append_side` alone is ~12 ms/frame under the profiler.

**D5. Culling costs as much as drawing** (mundo, ninja_nivel).
- `_cull_keeps` recomputes `_approx_draw_aabb` (pose) and `_filter_outset`
  (style only) for every object, every frame.
- On tutorial 21's level (129 objects), cull on draws 45 instead of 129 yet
  scene draw goes from 0.48 to 0.66 ms.
- Mundo draws all ~1950 objects (8.3 ms) to show ~250.
- Level tiles are one Graphic each; nothing batches them (D10).

**D6. Building a Sprite is slow** (corrida, horda).
- One `Sprite(...)` costs ~180 µs (~240 µs when it joins a resolve group); destroy costs ~35 µs.
- One construction makes ~276 `__setattr__` calls and two Style objects.
- A Corrida slot (~30 pieces) costs 7.6 ms to build, which is the p99 / max spike. On the target machine one slot is ~30 ms: a visible hitch every second.

**D7. Reading author ink goes through the miss path** (all games). An
author field (`self.idade`, `self.rumo`) lives in `_ink`. Every read misses
normal lookup and runs the whole `Entity.__getattr__`: the destroyed check, the
pose-name check, the retired-name lookup (`_retired_attr_message`), then the
ink dict. Festa: ~1200 misses / frame, all from `Disparo.on_update`
(300 shots × 4 field reads), ~1.2 µs each under the profiler.

**D8. Per-shot glow is the most expensive draw** (festa).
- About 115 `saveLayer` per frame for about 150 same-colour `.glow` shots
  (`_save_filter_layer`), plus each Neon shot drawn alone.
- Cause (F1, see "After group A"): batches merge only consecutive objects of
  one look, and festa's rings alternate Neon and Glow shots.
- The effects doc already names per-projectile Glow as the expensive pattern
  (`CheapGlow` for fleets). The engine fix is overlap-aware batching.

**D9. Skia's GPU cache keeps every Neon blur mask** (festa; memory, not
time; M1).
- Neon on shapes that move: RSS climbs from ~270 MiB to ~1.3 GB in about 4 s, then
  plateaus. Neon on still shapes and plain moving shapes stay flat. Python
  objects stay flat, and a forced `gc.collect()` changes nothing.
- With `GrDirectContext.setResourceCacheLimit(32 MiB)` RSS stays at 273 MiB at
  the same frame time, so the memory is one-use blur masks in Skia's GPU cache
  (limit 256 MiB; the driver adds the rest).
- A plain lower limit could make a texture-heavy game re-upload every frame. Measure before choosing.

**D10. Static scenery is drawn object by object.** No tile layer, no
picture, no atlas batch: ~4.3 µs per plain sprite, so the ~250 tiles on screen in
mundo are ~1 ms even with a perfect cull.

**D11. Frame time feeds back into detection.**
- A body that moves more than half its thickness in one frame takes swept detection.
- At 26 fps all ~320 of festa's shots are "fast" (`#fast` 319); at 60 fps none would be.
- A slow frame makes the next one slower. This is only an observation: the rule is correct.

### Measurement notes

- `harness.install_phase_run` (the replica loop behind most pulses) has
  drifted from `ScenaFramework._simulate_frame`. It lacks the clip settle,
  Endless refill, bounds step, hover, pointer resync and the history and cover
  ticks. Its pulses undercount and settle clip `next=` later (B2).
  `game_bench.py` wraps the real methods.
- `startup` import time read 358 ms against 184 on the dashboard. The shell
  that ran it disables bytecode (`PYTHONDONTWRITEBYTECODE=1`). Re-run with
  bytecode before calling it a regression (B4).

### Long run and cull A/B

**Mundo, `--cull ab`** (block 10, 15 s): cull on draws 130 and skips 1820, yet
scene draw is **8.98 ms**. Cull off draws all 1950 in **8.33 ms**. Testing an
object costs more than drawing a plain one (D5).

**Corrida, 5 minutes** (before the turret fix, see DG1):
- RSS flat at 313 → 314 MiB. No engine leak in the build / release churn.
- Work drifts 5.1 → 6.2 ms, colliders 129 → 205 and layer slots 153 → 230 as
  shots born outside the playfield pile up.
- Max frame 15–28 ms in every 30 s window: slot builds (D6).
- Re-run on the fixed game, after group A (2026-10-12):
  - flat: work 2.6–3.2 ms per 30 s window (p99 3.4–4.2), colliders 118–140, RSS 270–294 MiB;
  - no drift over 5 minutes;
  - the max frame is still 12–26 ms in every window: slot builds (D6).

### After group A (2026-10-12, same reference sizes)

| Game | Before | After A | Δ | x4 | What moved |
|------|-------:|--------:|--:|---:|------------|
| ninja | 8.90 | 5.12 | −42 % | 20.5 | `floor_below` 6.75 → 3.18 ms (A1 trust + envelope, A2 tile AABB prims, A4 sprite key) |
| horda | 20.0 | 18.4 | −8 % | 73.6 | resolve 12.7 → 11.4 ms (A3 selective partner cache); the O(n²) passes remain |
| mundo | 156.9 | 98.7 | −37 % | 395 | `floor_below` 112 → 61 ms, snapshot 8.0 → 6.3 ms (A2, A4); still O(world) per query |
| corrida | 5.34 | 3.02 | −43 % | 12.1 | **inside the budget**; max frame still ~25 ms (a slot build: D6, A8 cut 7 %) |
| festa | 38.4 | 37.8 | −1 % | 151 | GPU-bound (D8); RSS 433 → 254 MiB over 10 s (A9) |

Each step's A/B is in its commit and design-doc section. Bugs fixed on the
way: B6 (bench rot), PF1 (Testing Design; `ANYTHING` expansion stale after an
enroll). Not fixed: DG1 (Guia), B2 / B4 (bench), F1 (diagnosed below).

**F1, diagnosed.** `.glow = color` is interned (one `Glow` per colour), so the
sugar is not the cause. Filter batches and Neon's pass-major runs merge only
**consecutive** objects in a layer (`_draw_layer_batched`). Festa fires rings
that alternate Neon and Glow shots, so every run has length 1: a `saveLayer`
per glow shot, and Neon drawn shot by shot. The fix is overlap-aware batching:
a batch may skip intervening objects whose draw bounds do not intersect it.
That is pixel-identical by construction, but it changes §5.5's z rules, so it
is in the group B proposal.

### After group B (2026-10-12, same reference sizes)

| Game | Before A | After A | After B | x4 | What moved in B |
|------|---------:|--------:|--------:|---:|-----------------|
| ninja | 8.90 | 5.12 | **2.83** | 11.3 | in the budget. Swept SAT for the rounded platform-end hulls (GJK → closed form: `floor_below` 2.6 → 1.3 ms), pose revision (B1), step skips |
| horda | 20.0 | 18.4 | 15.2 | 61 | resolve pools on the proxy mirror (10.5 → 7.0 ms); the mutual crowd stays O(n²) (B3, fenced) |
| mundo | 156.9 | 98.7 | 23.6 | 94 | B1 (proxies skip still bodies), B2 (vectorized query candidates and resolve pools, member-scoped refresh), step skips (snapshot, stored bounds, touching), B4 makes `cull_offscreen` pay (draw 8.2 → 3.0 ms if the game turns it on) |
| corrida | 5.34 | 3.02 | **1.98** | 7.9 | in the budget. B1, step skips |
| festa | 38.4 | 37.8 | 36.2 | 145 | B5 overlap-aware batching (submit 23.9 → 19.8 ms); the 80 DU multipass cull pad keeps most shots in place |

Each step's A/B is in its commit and design-doc section:
- Collision Design: "Pose revision", "Polygon sweeps", "Moved set and vectorized candidates" (resolve pools, scoped refresh), "Step cost";
- Canvas Design: "Offscreen culling";
- Effect System Design §5.5: overlap-aware batching.

Found on the way:
- `Collider.on_collide` took an `async def` (now refused; Testing Design, AH lesson 1);
- `_touching_live` held a body after an act change (caught by the holders guard before it shipped);
- LP1 (below).

What remains:
- **horda:** shared partner lists and one prefilter query per turn (5f74e45) took resolve from 6.9 to 3.4 ms at n=150 (work 12.3 → 8.6) and from 66 to 22 ms at n=400. The pool rebuilds were the O(n²) part. What grows now is contact work in a denser crowd, so a grid (B3, fenced) would not remove it.
- **mundo:** a 1500-tile level still pays per-collider Python loops in the broad phase (1.5 ms), 500 moving coins in the snapshot (2 ms) and drawing 1950 objects with the cull off (8 ms).
- **festa:** a tighter paint bound per multipass look would let B5 merge more.

### Recommended optimizations (ranked by gain at reference size × reach ÷ risk)

**A. Local, unfenced, backed by the numbers above.**

| # | Change | Fixes | Expected | Risk / test plan |
|---|--------|-------|----------|------------------|
| A1 | Queries (`floor_below` first, then `query_*`, `raycast`): build each partner's world prims **once per call**; reject partners against the whole march envelope (probe ∪ dx ∪ lift ∪ depth) before any cast | D1 (casts) | ninja `floor_below` 6.75 → ~2 ms | Low: nothing runs between casts inside one call. Differential test: old vs new answer over randomized levels (tiles, slopes, one-way, `only=`), plus `test_floor_below` |
| A2 | An unrotated axis-aligned 4-vertex hull emits an **AABB prim**, so tiles take the closed-form sweep | D2 | ninja / corrida / mundo sweeps ≈ 3× cheaper | Medium: same geometry, different prim type. Differential test of contacts, TOI, normals and points (AABB vs polygon) within tolerance; rotation must turn it back into a polygon |
| A3 | Partner-cache invalidation only when the enrolled / leaving collider sits on a resolve side (or the pair graph changed) | D4 (H1) | horda −5…8 ms | Low: a list is rebuilt exactly as before when it is touched. Guard: partner lists equal a from-scratch build after every enroll / unenroll / tag change (randomized) |
| A4 | A Sprite-specialized pose key that reads `__dict__` directly, with class lookups resolved once | D1, D3 | proxy refresh 2–3× cheaper in every game | Medium: the key must cover every Defining input. Oracle: specialized key == generic key over hypothesis poses (flip, tilt, clip frame, scale, hitbox anchor / source, links); `TestPoseKeyCoversDefiningInputs` |
| A5 | `query_shape` rejects on proxy AABB before building prims (B3) | D1 | query-heavy scenes | Low |
| A6 | Ink read fast path in `Entity.__getattr__` (ink dict first, after the destroyed check; `x` / `y` still refused) | D7 | ~0.4 µs × every author field read | Low–medium: differential test vs the old path over names × states (destroyed, retired, `x` / `y` on Graphics, linked ink) |
| A7 | Process / input micro-optimizations: arity and bound-method checks cached in the dense tuple; parsed `keyp` specs cached per string, active families once per frame | per-actor overhead | small, everywhere | Low: memo of values fixed at registration / per frame |
| A8 | Sprite construction: cut the ~276 `__setattr__` and duplicate Style work per Sprite | D6 | corrida slot 7.6 ms → target < 3 ms; horda spawns | Medium: construct path. Census + snapshot tests of a built Sprite (fields, groups, collider, style) before / after |
| A9 | Skia GPU cache: purge resources unused for a few seconds (and choose a limit by measurement on all games) | D9 (M1) | festa RSS 1.3 GB → ~0.3 GB | Low for time if measured: no texture re-upload on any game |

**B. Structural: they reach the O(N) and O(n²) shapes. They need your decision.**

| # | Change | Fixes | Notes |
|---|--------|-------|-------|
| B1 | **Moved-since tracking** (a pose revision per Graphic, bumped on every pose write; linked anchors always count as moved). `step()` and queries skip unchanged proxies; draw boxes are cached per revision | D3, D5, D1 (refresh part) | Cross-cutting, on the hottest write path (A1–A4 rules, `_pose_fast_ok`). Needs a write-path allowlist guard and a randomized "cached == recomputed after every API call" test. Mundo snapshot 8 → < 1 ms; cull per object ~3.7 → < 0.5 µs |
| B2 | **Vectorized candidate filter**: a numpy array of proxy boxes (kept current through B1's moved set and through solver nudges). Queries, resolve passes and cull test all rows at once in C | D1 (scan), D4 (O(n²)), D5 | Stays inside the fence: "declared-pair AABB … only needed to be vectorized" (Collision Design, "What not to add"). Mundo queries O(N) in C (~10 µs per query); horda settle from ~56,000 Python calls to ~150 numpy calls per pass |
| B3 | Uniform-grid spatial index for queries and partners | same as B2, O(k) instead of O(N) | **Reopens a fence** (`Fences.md`: "Spatial hash / all-collider n×n"). Only if B2 measures short |
| B4 | Static-scenery batching (`drawAtlas` for runs of plain sprites that share an image, or a recorded picture per static layer) | D10 | Only if mundo still draws over budget after B1 + B2 |
| B5 | Per-shot glow (F1): find out whether same-colour `.glow` shots batch; make the taught sugar batch (or teach `CheapGlow` for shots) | D8 | Effects area (§5.5 rules). Festa is GPU-bound: the CPU work above does not fix it |

### Bugs and issues found

| ID | What | Status |
|----|------|--------|
| B6 (Testing Design) | `gpu_mix.py` passed `Shield(style="bubble", color=…)` after the KN refusal; `run_balanced` and `run_all` crashed | fixed 08068a5; pulse scenes now in the headless guard |
| H1 | Every enroll / unenroll clears all resolve partner lists, any tag (D4) | fixed 0ce4670 (A3) |
| B3 | `query_shape` builds world prims for every candidate, with no proxy reject | fixed 45881e7 (A5) |
| M1 | Neon on moving shapes grows RSS by ~1 GB (Skia GPU cache of one-use blur masks) (D9) | mitigated 712d0b4 (A9: 1.3 → 0.77 GB); the mask per position remains |
| PF1 (Testing Design) | `resolve(…, ANYTHING)` missed a body spawned after a query in the same frame, across frames | fixed cddf59d |
| F1 | Interleaved looks (Neon / Glow) defeat batching: one saveLayer per glow shot (D8) | partly fixed (B5, overlap-aware batching): festa work 38.9 → 35.6 ms, submit 23.9 → 19.8. The cull pads bound the gain: a multipass look pads its box by 80 DU, so most shots "overlap" a neighbour's box and stay in place |
| LP1 | A look run's pass-major emit draws a Circle's core with `drawCircle`; its solo `render` uses a path. The AA edges differ, up to 43/255 on a few pixels at radius ≈ 3.8 (identical at 3.5 and 4). Pre-existing in every consecutive Neon run; found by the B5 pixel test | open, low (sub-pixel AA); `tests/test_batch_reach.py` keeps Neon on rects and polygons |
| LB1 | In maximized / fullscreen letterbox mode the world spilled into the black bands: a body half outside the design rect showed its outer half (the cull drops only bodies wholly outside), and full-FB post overlays (Grain, Scanlines) lit the bands too. Confirmed on a real window (1920×940 maximized: 114,740 red pixels in the bands; with Scanlines + Grain 227,808 lit) | fixed: `_mask_letterbox_bands` paints the bands black after the world pass, before the HUD (Canvas Design, "Letterbox bands stay black"); 0 lit pixels after. A `clipRect` on the world pass cost +0.8 to +1.7 % per frame in letterbox (per-frame round-robin A/B, 1500 circles); the band rects −0.0 to +0.4 % (windowed control ±0.1 %). `tests/test_diff_pipeline.py` `TestLetterboxBands` |
| B2 (bench) | `harness.install_phase_run` replica loop drifted from the product frame | open: move pulses to wrapping the real frame, with a protocol bump |
| DG1 | Guia gap: `@leave_playfield` fires only for an object that was inside the playfield first. A shot born outside (a spawner behind a moving camera) never leaves, and accumulates. Corrida did that: 2 → 36 live shots in two minutes. The Guia teaches the camera-following playfield but not this rule | fixed: the Guia's `@leave_playfield` section says so, with both fixes (pt; the en Guia is a stub) |
| B4 (bench) | startup import time doubled in the 2026-10-12 run, likely a no-bytecode shell | confirmed artifact (with bytecode: import 179 ms, ttff 406 ms, both better than the dashboard); `perf_startup` launches now always use bytecode |

## Runs

### 2026-10-12 — games-1

| | |
|---|---|
| When | 2026-10-12 17:31 -0300 (20:31 UTC) |
| Protocol | `games-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Load | 4.09 |
| Git | 3de337321078 |
| Scena | `c41691d4e4ea` |
| Scripts | fingerprint `e6ecf1585b5d` |

| File | sha256[:12] |
|------|-------------|
| `game_bench.py` | `363e0eed2a31` |
| `run_games.py` | `16983bab8a41` |
| `games/horda.py` | `d1861b67aea7` |
| `games/mundo.py` | `1c6ba949a8b6` |
| `games/corrida.py` | `d341e6926ba1` |
| `games/festa.py` | `cba1b8c5597b` |

| Game | work | p95 | max | x4 | fps | top phases |
|------|-----:|----:|----:|---:|----:|------------|
| ninja  | 2.83 | 3.19 | 7.2 | 11.3 | 324 | simulate 2.04, processes 1.45, draw_frame 0.73, scene_draw 0.64 |
| horda n=150 | 15.19 | 21.41 | 24.3 | 60.8 | 65 | simulate 13.86, collision 12.52, processes 1.25, draw_frame 1.15 |
| mundo tiles=1500,robots=20 | 23.60 | 28.93 | 38.4 | 94.4 | 42 | simulate 15.38, collision 10.53, draw_frame 8.06, scene_draw 7.86 |
| corrida speed=600 | 1.98 | 2.26 | 24.3 | 7.9 | 449 | simulate 1.23, draw_frame 0.69, scene_draw 0.62, processes 0.54 |
| festa n=300 | 36.18 | 42.82 | 49.5 | 144.7 | 27 | submit 19.62, draw_frame 9.68, scene_draw 8.68, simulate 6.86 |

### 2026-10-12 — games-1

| | |
|---|---|
| When | 2026-10-12 14:57 -0300 (17:57 UTC) |
| Protocol | `games-1` (comparable) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Load | 2.34 |
| Git | a40489f5088c |
| Scena | `6eae4542094f` |
| Scripts | fingerprint `e6ecf1585b5d` |

| File | sha256[:12] |
|------|-------------|
| `game_bench.py` | `363e0eed2a31` |
| `run_games.py` | `16983bab8a41` |
| `games/horda.py` | `d1861b67aea7` |
| `games/mundo.py` | `1c6ba949a8b6` |
| `games/corrida.py` | `d341e6926ba1` |
| `games/festa.py` | `cba1b8c5597b` |

| Game | work | p95 | max | x4 | fps | top phases |
|------|-----:|----:|----:|---:|----:|------------|
| ninja  | 5.06 | 5.89 | 9.2 | 20.2 | 188 | simulate 4.26, processes 3.30, collision 0.92, draw_frame 0.73 |
| horda n=150 | 16.99 | 22.60 | 27.0 | 68.0 | 58 | simulate 15.70, collision 14.37, processes 1.24, draw_frame 1.12 |
| mundo tiles=1500,robots=20 | 96.26 | 105.61 | 110.6 | 385.1 | 10 | simulate 86.79, processes 60.88, collision 25.74, draw_frame 9.22 |
| corrida speed=600 | 3.02 | 3.43 | 25.0 | 12.1 | 304 | simulate 2.24, processes 1.07, collision 1.01, draw_frame 0.72 |
| festa n=300 | 37.21 | 43.63 | 45.8 | 148.8 | 27 | submit 22.41, draw_frame 8.13, scene_draw 7.16, simulate 6.64 |

Newest first. `run_games.py` adds one section per run.
