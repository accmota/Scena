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

| Date | Load | Scena | ninja | horda n=150 | mundo tiles=1500 | corrida speed=600 | festa n=300 | Notes |
|------|------|-------|------:|------:|------:|------:|------:|-------|
| 2026-10-12 | 2.3 | `9333a78e4e4d` | 8.90 | 20.01 | 156.9 | 5.34 | 38.37 | work ms at reference size, 10 s, fb 1×; first row |

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
  (`_save_filter_layer`).
- `.glow = "cyan"` makes a new `Glow` per shape (`stamps.coerce_glow`; `Neon` is interned).
- Whether those shots batch is unconfirmed (F1).
- The effects doc already names per-projectile Glow as the expensive pattern
  (`CheapGlow` for fleets). The question is whether the taught `.glow = color`
  sugar defeats batching.

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
- To re-run on the fixed game in the milestone check.

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
| H1 | Every enroll / unenroll clears all resolve partner lists, any tag (D4) | open (A3) |
| B3 | `query_shape` builds world prims for every candidate, with no proxy reject | open (A5) |
| M1 | Neon on moving shapes grows RSS by ~1 GB (Skia GPU cache of one-use blur masks) (D9) | open (A9) |
| F1 | `.glow = color` makes a new `Glow` per shape; per-shot glow may not batch (D8) | to investigate (B5) |
| B2 (bench) | `harness.install_phase_run` replica loop drifted from the product frame | open: move pulses to wrapping the real frame, with a protocol bump |
| DG1 | Guia gap: `@leave_playfield` fires only for an object that was inside the playfield first. A shot born outside (a spawner behind a moving camera) never leaves, and accumulates. Corrida did that: 2 → 36 live shots in two minutes. The Guia teaches the camera-following playfield but not this rule | open: one sentence in the Guia (`#reagir-bounds`, pt and en) |
| B4 (bench) | startup import time doubled in the 2026-10-12 run, likely a no-bytecode shell | to check: re-run with bytecode; record the flag in the row |
