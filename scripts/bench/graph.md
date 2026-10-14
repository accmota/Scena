# Reactive-graph isolate

Pulse for **deep** and **shallow** reactive links. Scripts already existed; this file is the protocol + history table so they show up on the [dashboard](dashboard.md).

- Deep: [`sierpinsky.py`](sierpinsky.py) — recursive midpoint `@=` (depth 5).
- Shallow: [`reactive_graph.py`](reactive_graph.py) — ~200 shapes, driver → dependent only.

Collision / FX stay out. Compare **median `work_ms` and phases**, not raw FPS.

## How to run

From the **repo root**.

```bash
python scripts/bench/run_graph.py
python scripts/bench/sierpinsky.py --bench --depth 5 --duration 2 --warmup 0.4
python scripts/bench/reactive_graph.py --bench --duration 2 --warmup 0.5 --seed 7
```

`--bench` uses the phase harness (design==window, 1× points). Interactive sierpinski / link-stress omit `--bench`.

## Protocol `graph-1`

Bump this id (and mark the next snapshot **pro-forma**) if you change [`sierpinsky.py`](sierpinsky.py), [`reactive_graph.py`](reactive_graph.py), [`run_graph.py`](run_graph.py), [`harness.py`](harness.py), or any **frozen flag**.

| Probe | Frozen argv | What it scores |
|-------|-------------|----------------|
| sierpinski | `--bench --depth 5 --duration 2 --warmup 0.4` | Deep midpoint graph. `work_ms` / `draw_ms` / `flush_ms`. |
| shallow | `--bench --duration 2 --warmup 0.5 --seed 7` | ~200-shape shallow links. `work_ms` / `flush_ms`. |

**Noise rule.** Single-shot. Treat **≲5%** median `work_ms` as noise, **≳15%** as a noteworthy row. Auto-diff uses the scena fingerprint (same hash + >15% → noise).

Sierpinski is draw-bound (many `Line`s). If `flush_ms` moves, the graph itself moved; if only `draw_ms` moves, it is paint.

## If a cell moved

| Cell | Next isolate |
|------|----------------|
| sierpinski `flush_ms` | `--depth 4` vs `5`; [`isolat.py`](isolat.py) `--bench --tier reactive` |
| sierpinski `draw_ms` | paint, not graph — `--depth` ladder |
| shallow `flush_ms` | `reactive_graph.py --profile` |
| both `tick_ms` | unexpected here; check [`sched.md`](sched.md) |

Do **not** fold this into [`sched.md`](sched.md). Scheduler pulse has no deep `@=` chains.

## Summary

Newest first. Primary: sierpinski **work_ms**.

| Date | Protocol | Host | sierpinski work_ms (FPS) | shallow work_ms (FPS) | Notes |
|------|----------|------|-------------------------:|----------------------:|-------|
| 2026-10-14 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 11.546 (86.6) | 6.110 (163.7) |  |
| 2026-09-29 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 7.610 (131.4) | 4.263 (234.6) |  |
| 2026-09-28 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 6.938 (144.1) | 4.283 (233.5) |  |
| 2026-09-28 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 14.637 (68.3) | 4.953 (201.9) |  |
| 2026-09-24 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 7.074 (141.4) | 4.493 (222.6) |  |
| 2026-09-24 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 7.284 (137.3) | 4.576 (218.5) |  |
| 2026-09-23 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 7.205 (138.8) | 4.629 (216.0) |  |
| 2026-09-22 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 6.811 (146.8) | 4.185 (238.9) |  |
| 2026-09-15 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 6.731 (148.6) | 4.161 (240.3) |  |
| 2026-09-12 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 7.169 (139.5) | 4.242 (235.7) |  |
| 2026-09-12 | `tier1-micro` | Apple M4 · Darwin · Py 3.12.13 | deep L=5 **0.95**; L=7 **4.21** | shallow **0.70** | Post-Tier-1 (T1.1–T1.6). vs pre: L=7 6.08→4.21 (~1.45×), shallow 1.31→0.70 (~1.87×). |
| 2026-09-12 | `tier1-micro` | Apple M4 · Darwin · Py 3.12.13 | deep L=5 **1.363** ms; L=7 **6.084** ms | shallow **1.313** ms | Pre-Tier-1 headless pull baseline (`tier1_reactive_micro.py`). Full `graph-1` window pulse deferred (no display in agent env). |
| 2026-09-11 | `graph-1` | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | 11.214 (89.2) | 5.107 (195.8) |  |

---

## Runs

Newest first.

### 2026-10-14 — graph-1

| | |
|---|---|
| When | 2026-10-14 11:44 -0300 (14:44 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | e6cd88ec85a3 |
| Scena | `15bc8e1ffdca` |
| Repeats | single-shot |
| Scripts | fingerprint `32030257fad1` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `43d169448391` |
| `reactive_graph.py` | `ecbe69aa31bf` |
| `run_graph.py` | `1afaa3b51833` |
| `harness.py` | `38953009d9e9` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### sierpinski depth=5

- work_ms **11.546**  FPS 86.6  draw 6.722  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **6.110**  FPS 163.7  draw 2.993  flush 0.002

### 2026-09-29 — graph-1

| | |
|---|---|
| When | 2026-09-29 11:36 -0300 (14:36 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `0275df8b0f3c` |
| Repeats | single-shot |
| Scripts | fingerprint `fe9b66674ca8` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `bf80ec7f5d1c` |
| `run_graph.py` | `f4eea3f5b319` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.

#### sierpinski depth=5

- work_ms **7.610**  FPS 131.4  draw 4.849  flush 0.002

#### reactive_graph (shallow ~200)

- work_ms **4.263**  FPS 234.6  draw 2.371  flush 0.001

### 2026-09-28 — graph-1

| | |
|---|---|
| When | 2026-09-28 21:42 -0300 (00:42 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `7eea1715c753` |
| Repeats | single-shot |
| Scripts | fingerprint `bb95df650d84` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `bf80ec7f5d1c` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **6.938**  FPS 144.1  draw 4.873  flush 0.002

#### reactive_graph (shallow ~200)

- work_ms **4.283**  FPS 233.5  draw 2.372  flush 0.001

### 2026-09-28 — graph-1

| | |
|---|---|
| When | 2026-09-28 21:22 -0300 (00:22 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `256325cf1c62` |
| Repeats | single-shot |
| Scripts | fingerprint `bb95df650d84` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `bf80ec7f5d1c` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **14.637**  FPS 68.3  draw 12.643  flush 0.002

#### reactive_graph (shallow ~200)

- work_ms **4.953**  FPS 201.9  draw 2.897  flush 0.001

### 2026-09-24 — graph-1

| | |
|---|---|
| When | 2026-09-24 20:28 -0300 (23:28 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `b603b2ea41a9` |
| Repeats | single-shot |
| Scripts | fingerprint `23ec3263d576` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `39a69fb7dc2f` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **7.074**  FPS 141.4  draw 5.035  flush 0.004

#### reactive_graph (shallow ~200)

- work_ms **4.493**  FPS 222.6  draw 2.614  flush 0.001

### 2026-09-24 — graph-1

| | |
|---|---|
| When | 2026-09-24 10:39 -0300 (13:39 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `e99ac6a66ad9` |
| Repeats | single-shot |
| Scripts | fingerprint `23ec3263d576` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `39a69fb7dc2f` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **7.284**  FPS 137.3  draw 4.700  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **4.576**  FPS 218.5  draw 2.469  flush 0.001

### 2026-09-23 — graph-1

| | |
|---|---|
| When | 2026-09-23 20:22 -0300 (23:22 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `88e64c88ecb1` |
| Repeats | single-shot |
| Scripts | fingerprint `23ec3263d576` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `39a69fb7dc2f` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **7.205**  FPS 138.8  draw 4.746  flush 0.002

#### reactive_graph (shallow ~200)

- work_ms **4.629**  FPS 216.0  draw 2.496  flush 0.001

### 2026-09-22 — graph-1

| | |
|---|---|
| When | 2026-09-22 20:30 -0300 (23:30 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c91c4e4c91e7` |
| Repeats | single-shot |
| Scripts | fingerprint `23ec3263d576` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `39a69fb7dc2f` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **6.811**  FPS 146.8  draw 4.840  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **4.185**  FPS 238.9  draw 2.337  flush 0.001

### 2026-09-15 — graph-1

| | |
|---|---|
| When | 2026-09-15 13:25 -0300 (16:25 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `8303d83b3439` |
| Repeats | single-shot |
| Scripts | fingerprint `383f93cf9457` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `9efd1e771756` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **6.731**  FPS 148.6  draw 4.713  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **4.161**  FPS 240.3  draw 2.327  flush 0.001

### 2026-09-12 — graph-1

| | |
|---|---|
| When | 2026-09-12 11:54 -0300 (14:54 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `00c71e0ec4d9` |
| Repeats | single-shot |
| Scripts | fingerprint `383f93cf9457` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `9efd1e771756` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **7.169**  FPS 139.5  draw 5.124  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **4.242**  FPS 235.7  draw 2.405  flush 0.002

### 2026-09-12 — tier1-micro (post-Tier-1 T1.1–T1.6)

| | |
|---|---|
| When | 2026-09-12 (agent session) |
| Protocol | tier1-micro |
| Host | Apple M4 · Darwin · Py 3.12.13 |
| Script | `tier1_reactive_micro.py` |
| Notes | After mark_dirty micro-opt, change-gated pose notify, subtree cache, leaf resolve/takein, clean ScalarSlot read. |

| Probe | ms/frame | vs pre |
|-------|----------:|-------:|
| deep L=5 (63 rects) | 0.95 | ~1.44× |
| deep L=7 (255 rects) | 4.21 | ~1.45× |
| shallow n=200 | 0.70 | ~1.87× |

### 2026-09-12 — tier1-micro (pre-Tier-1 baseline)

| | |
|---|---|
| When | 2026-09-12 (agent session) |
| Protocol | tier1-micro (headless pull; complements graph-1) |
| Host | Apple M4 · Darwin · Py 3.12.13 |
| Script | `tier1_reactive_micro.py` |
| Notes | No GLFW. Deep = spinning-rects binary tree; shallow = 200 center+rotation dependents of one hub. |

| Probe | ms/frame |
|-------|----------:|
| deep L=5 (63 rects) | 1.363 |
| deep L=7 (255 rects) | 6.084 |
| shallow n=200 | 1.313 |

### 2026-09-11 — graph-1

| | |
|---|---|
| When | 2026-09-11 21:30 -0300 (00:30 UTC) |
| Protocol | `graph-1` (pro-forma) |
| Host | Apple M4 · Darwin 26.6.2 · Py 3.12.13 |
| Git | none |
| Stage | `c2f322da89d6` |
| Repeats | single-shot |
| Scripts | fingerprint `383f93cf9457` |

| File | sha256[:12] |
|------|-------------|
| `sierpinsky.py` | `fd578285b860` |
| `reactive_graph.py` | `9efd1e771756` |
| `run_graph.py` | `a562aa95b3bb` |
| `harness.py` | `80407cd97e92` |

Frozen argv as in the protocol table. FB 1× via the phase harness.

#### sierpinski depth=5

- work_ms **11.214**  FPS 89.2  draw 8.917  flush 0.003

#### reactive_graph (shallow ~200)

- work_ms **5.107**  FPS 195.8  draw 3.043  flush 0.001

### Run template

```markdown
### YYYY-MM-DD — graph-1

| | |
|---|---|
| When | |
| Protocol | graph-1 (pro-forma: yes/no — why) |
| Host | |
| Git | |
| Stage | |
| Repeats | single-shot |
| Scripts | fingerprint … |
```
