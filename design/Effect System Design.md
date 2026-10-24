# Effect System Design

Looks (filters / visuals / recipes), shape transients, SpatialFx, background
kinds, canvas post, quality ladder, and cost model. **Happy path for this
subsystem** — pick one row; do not read the rest. Placement / camera / layers:
[Canvas Design.md](Canvas%20Design.md). Post/background mutate-hide-remove:
[Effect Handles.md](Effect%20Handles.md). Hub: [Scena Design.md](Scena%20Design.md).
Author calls: [Guia da API](../docs/pt/guide/index.html#aparencia).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| One-page takeaways | [§13](#13-one-page-summary) |
| `.visual` / recipes / stamps | [§3.1b](#31b-shape-visuals-shapevisual) |
| Filters / batching / AABB | [§5](#5-shape-filter-batching--cost-model); **[§5.5](#55-changing-the-effect-system-without-regressing-hot-paths) before edits** (incl. Sprite-only helpers on shared paint paths); [§5.6](#56-recipe-draw-hot-path--lessons) for Recipe CPU/GPU draw wins |
| Transients | [§3.1c](#31c-shape-transients-scenatransientspy) |
| SpatialFx | [§3.1d](#31d-spatialfx-ambient-emitters-scenaspatial_fxpy) |
| Background kinds / cost | [§3.1e](#31e-backgroundfields-scenabackgroundpy-scenabackground_kindspy) |
| Parallax (architecture) | [Canvas Design.md](Canvas%20Design.md#parallax-layers-decoration-only) |
| Canvas post / cover / quality | [§3.2](#32-canvas-post-effects--categories), [§4](#4-quality-system-fxquality), [§6](#6-canvas-post-cost-model) |
| Locating code | [§12](#12-file-map) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** in [§12](#12-file-map) only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/`, `_sksl_*`, or the private archive / proposals unless the shader or a named campaign is the task.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `.visual = Glow()` | compiled look in `visuals.py` | `recipes.py` (`Neon`) or `stamps.py` (`.glow =`) |
| `Rain` / `Fire` | SpatialFx (`spatial_fx_effects.py`) | post (`effects.py`) or a background field |
| `Stars` / `Tunnel` | background **kind** (`background_kinds.py`) | SpatialFx or a giant Shape |
| `Portal` (ring of light) | SpatialFx point kind | `Warp` (filled vortex disc) or `ElectricField` (outline look on a host shape) |
| `canvas.fade_out` | cover (`cover.py`) | post stack |
| `explosion_at(None)` / missing `info.point` | hit no-op | `move_to(None)` (pose still errors) |
| Filter batch AABB | dest + `_batch_outset` (gate extras) | `Sprite._domain_aabb` |

## Not in this doc

- Camera / layers / cull / HUD → [Canvas Design.md](Canvas%20Design.md)
- Post / background hide-remove → [Effect Handles.md](Effect%20Handles.md)
- Sprite FrameFx / Shield envelope → [Sprite Design.md](Sprite%20Design.md)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#aparencia)
- Bench method → [§8](#8-benchmarks); time-series pulse → [`scripts/bench/fx.md`](../scripts/bench/fx.md)
- Visual / bench proof → `scripts/smoke/shape_fx.py`, `transients.py`, `spatial.py`, `background.py`, `world_view.py`; `scripts/bench/perf_effects.py`, `perf_fx_matrix.py` (only if the task is proof)


# Effect system

===============

**Status:** framework-integrated (v1), published in 0.5.0. Breaking changes
to the author surface follow [Compatibility and versions](Scena%20Design.md#compatibility-and-versions).

**Last updated:** 2026-09-18 (`shape_pivot` / transient saveLayer extent for Polygon · Text · rotated Square)

## 1. Goals

1. Keep Scena viable for **realtime** creative graphics on modest CPU/GPU (including Retina / HiDPI).
2. Effect layers:
  - **PaintState paints / blend** — base material on the shape. Sprite image blit honors `.blend` at set-time (`_blit_paint`); default `NORMAL` keeps the shared singleton and `_plain_blit`. `Sprite.alpha` is Sprite-only (not a PaintState field) and does not change `Shape.set_alpha`.
  - **Shape ImageFilters** — per-shape `fill_filter` / `line_filter` (blur, glow, shadow, …).
  - **Shape visuals** — one exclusive costume (`shape.visual = Paint(...)` / `Neon()` / …); compiled style packages or multipass Recipes.
  - **Appearance stamps** — sticky pigment / motion around the costume (`shape.glow` / `.shadow` / `.tail`; Sprite also `.hue` / `.gray`). Orthogonal to `.visual`.
  - **Shape transients** — multi-channel one-shots (`life` / `flash` / `pulse` / `pop` / `knock` / `spark`); orthogonal to `.visual`, stamps, and sticky filters.
  - **SpatialFx** — sticky ambient emitters with soft placement domains (campfire, rain, jet, sparks); registered like shapes, not visuals/post. Tick and shader phases run on world time: pause and slow motion reach them ([Scena Design — Clocks](Scena%20Design.md#clocks)).
  - **BackgroundFields** — pre-scene full-screen procedural fields (parallax skies / tunnels); `canvas.background`, not layers/post.
  - **Parallax Layers** — shape/SpatialFx layers with partial camera response (`canvas.layers.create(..., pan_response=…)`); decoration-only (no hit/collision).
  - **Canvas-wide post effects** — grade, vignette, bloom, grain, curated SkSL, hit feedback, …
  - **Canvas cover** — `fade_in` / `fade_out` (fade / wipe / iris); holds until uncover; after widgets, not post. Runs on presentation time: a fade finishes while `clock.paused` ([Scena Design — Clocks](Scena%20Design.md#clocks))
3. One author-facing **quality** knob (`FxQuality`) that trades pixels for FPS.
4. Beginner API: zero-arg constructors look good; no author-written SkSL.
5. Performance first: measure in-app FPS; use matrix/microbench to explain *why*.

---



## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frame (ScenaFramework)                                     │
│                                                             │
│  update() → flush links →                                   │
│  tick_all_transients() → tick_all_spatial_fx() →            │
│                                                             │
│  canvas.background (base wallpaper + fields) →   │
│  view transform + camera → scene (shapes + SpatialFx)       │
│      per layer: neutral → full camera; non-neutral →        │
│        delta = inv(full) · partial_camera(+scroll)          │
│        (fast path: skip when stack has no parallax layers)  │
│                                                             │
│  [if canvas.effects active OR custom post_draw]             │
│     Scene (optional: exclude top) → GPU offscreen RT        │
│     snapshot → scene_image                                  │
│     PostFxStack._render(...) OR  post_draw(...)             │
│     [if top exempt] draw top layer                          │
│  [else]                                                     │
│     Scene → window FB directly (or scene-blit path)         │
│                                                             │
│  widgets (HUD stays sharp)                                  │
│  canvas cover (fade/wipe/iris; after HUD; no scene RT)      │
│                                                             │
│  Scene draw path (per layer, list order = within-layer z):  │
│     Shape | SpatialFx duck-typed: visible + draw()          │
│     Shape: compose transients → visual/filters/geometry    │
│     SpatialFx: soft domain particles / procedural blobs     │
│     optional batching / shape_fx_scale (shapes only)        │
└─────────────────────────────────────────────────────────────┘
```


| Layer                 | Mechanism                                                                                                                     | Where                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Wallpaper             | solid clear / gradient / image via `Wallpaper`                                                                                | `scena/background_kinds.py` (`Wallpaper`)                                      |
| **Background fields** | ordered full-screen fields (parallax / tunnel)                                                                                | `scena/background.py`, `scena/background_kinds.py`, `_sksl_backdrop.py`        |
| **Parallax Layers**   | per-layer partial camera CTM for shapes/SpatialFx                                                                             | `scena/camera_response.py`, `registry.py`, `canvas.py`                            |
| PaintState paints     | Color / Gradient / Texture / ProceduralFill. Shape default `line_width` is **1.5** (`DEFAULT_LINE_WIDTH`). Primary package: solid → fill + contrast stroke; **Gradient** → fill + `mean_color().darker(0.2)` outline (`line_width` kept); Texture / ProceduralFill → fill only. Material shaders enter via `skia.Paint(Shader=…)`, never `setShader` (§5.5 image-shader lesson). Material shaders are origin-centered in the host's local frame (auto-size Gradients are unit-size); code that paints a Gradient / Texture outside a Shape (widget panels) goes through `style._material_paint_for_rect(material, cx, cy, hw, hh)`, never `material._skia_shader` — raw, the panel shows one end stop (A29; guarded by `test_api_docs.TestMaterialShadersStayInTheirFrame`). Sprite body blit honors `.blend` (set-time into `_blit_paint`; do not clear `_plain_blit` for blend alone). `Sprite.alpha` is **not** a PaintState field — Sprite-only sticky blit opacity; `Shape.set_alpha` still means “push alpha into fill/line”. | `scena/style.py`, `scena/sprite.py` |
| Color samplers        | `Colormap` (continuous `get_color(t)`) and `Palette` (N evenly spaced swatches; `palette[i]` wraps, `get_next()`). Same preset table as `Gradient`. Default interpolation is OKLAB. Not paints — assign the returned `Color`. `Gradient.mean_color` / `.darker` / `.lighter` are paint helpers (stop mean / stop-wise tone), not samplers. | `scena/color.py`, `scena/gradient_presets.py`, `scena/style.py` |
| Shape ImageFilters    | `fill_filter` / `line_filter`                                                                                                 | `scena/filters.py`, `style.py`, `canvas.py`                                    |
| Shape visuals         | `Visual._apply` style package, `Recipe.render`, or Sprite `_render_sprite_body` (Halo/Laser)          | `scena/visuals.py`, `scena/recipes.py`, `shapes.py`, `sprite.py`               |
| Appearance stamps     | Sticky `.glow` / `.shadow` / `.hue` / `.gray` / `.tail` around costume                                   | `scena/stamps.py`, `style.py`                                                  |
| Shape transients      | 6-channel timed slots → DrawMods envelope + overlays                                                                          | `scena/transients.py`                                                          |
| **SpatialFx**         | registered soft domains (pad / beam / point)                                                                            | `scena/spatial_fx.py`                                                          |
| Filter batching       | One saveLayer / low-res RT per `_batch_key`, then optional `_overlay_after_filters`; Electric* high PE-glow shares one Plus `Blur(σ=2.2)` plate | `ScenaCanvas`                                                                  |
| Shape FX resolution   | `shape_fx_scale` + `_filter_at_scale`                                                                                          | `canvas.py`, `fx_quality.py`                                                   |
| Canvas post engine    | `PostFxStack` / `PostEffect`                                                                                                  | `scena/postfx.py`                                                              |
| Built-in post effects | Vignette, Bloom, Grade, SkSL, …                                                                                               | `scena/effects.py`, `_sksl_effects.py`                                         |
| Quality presets       | `FxQuality` → scales (+ `particle_scale` for SpatialFx density)                                                               | `scena/fx_quality.py`                                                          |
| Top-layer exemption   | `canvas.layers["top"].post_fx = False`                                                                                     | `registry.py`, `orchestration.py`                                                 |




### Author API (draft)

```python
Vignette()
Bloom(intensity=0.8)
Grade("cool")
Crt()
ColorSweep()                    # spatial grade; axis=radial|horizontal|vertical (anything else raises)
ColorSweep(axis="horizontal", colors=("tomato", "gold", "navy"))
ColorWash()                    # dancing plasma colorize
CosmicBloom()                   # churning wash + glare
canvas.fade_out(0.5)                 # to black, then hold
canvas.fade_out(0.5, color="navy", style="wipe", angle=90)
canvas.fade_out(0.5, style="iris", on_done=load_next)
canvas.fade_in(0.5)                  # uncover; opening fade snaps to cover first
canvas.flash(0.6)
canvas.shake(10)
canvas.glitch()
canvas.ripple_at(x, y)
canvas.ripple_at(x, y, radius=120)     # design-unit radius; omit = full-frame
canvas.wave_at(x, y, angle=0)
canvas.explosion_at(x, y)
canvas.explosion_at(info.point)         # or info, Graphic, Point, Vec2, (x, y)
canvas.burst_at(x, y, radius=42)      # local multi-instance
canvas.burst_at(ship)                  # Graphic.center
canvas.fireworks_at(x, y)             # celebration burst (not a fireball)
canvas.zap_at(x, y)                   # electric spark (styles: spark|fork|corona)
canvas.hit_at(info, angle=90)         # impact mark: struck, still alive (sparks aimed up)
canvas.hit_at(wall, style="disc")      # light version: a round pop of light, no sparks
canvas.debris_at(x, y, color="peru")  # matte shards + dust (no fire); fall=1 arcs down
canvas.explosion_at(x, y, rings=False) # skip expanding rings
# None / missing info.point is a no-op (exit). *info.point still needs a tuple.
canvas.fx_quality = "high"            # default: post ½, shape 1.0, batch True
# Ctrl+Shift+3 → cycle render profiles (low → medium → high; max is API-only)
canvas.layers["top"].post_fx = False    # HUD layer stays sharp

# BackgroundFields — pre-scene full-screen fields (ambient + tunnels)
SkyGradient("night")
Stars(pan_response=0.02)
Stardust(pan_response=0.08, alpha=0.55)
Chromadust()
Chromadust("plasma")
Nebuladust()
Borealis(pan_response=0.12, height=0.55)
Plasma(pan_response=0.35, alpha=0.55)
Debris(pan_response=0.4)
canvas.set_fly(Tunnel())                  # sugar: single immersive field

# Parallax Layers — author shapes/SpatialFx with partial camera response
canvas.layers.create("far", below="default", pan_response=0.2, zoom_response=0.1)
canvas.layers.create("mid", below="default", pan_response=0.5)
Circle(center=(0, 0), radius=40, layer="far")   # decoration only
canvas.set_fly(Floor())
canvas.set_fly(Tunnel())
canvas.set_fly(StarFly())
canvas.set_fly(PlanetFly())                   # into-screen (default)
canvas.set_fly(PlanetFly(roll="side"))        # side-scroll limb
canvas.set_fly(None)
# soft grid wash / side-scroll ground tunnel companion
Lattice(fold="square", scroll=(40, 0))
Road(scroll=(80, 0))       # Mode7 horizontal only

ship.visual = Neon()                         # multipass Recipe; follows host fill/line live
ship.visual = Neon("cyan", flicker=0.6)      # pass-level ADD-halo hum (0 = static)
ship.visual = None                           # restore author package (stamps stay)
ship.glow = True                             # stamp: default Glow halo
ship.glow = "cyan"                           # stamp sugar → Glow("cyan")
sting.glow = CheapGlow("tomato", radius=8)   # fleet ADD halo on .glow (no .cheapglow)
ship.shadow = True                           # stamp: default Shadow
sprite.hue = True                            # Sprite stamp: HueShift(1/3 turn)
sprite.hue = 0.33                            # turns; Shape: Texture(..., shift=HueShift(...))
sprite.gray = True                           # Sprite stamp: Grayscale(1); 0.5 = half way
bolt.tail = True                             # stamp: follow velocity (trail behind + length)
bolt.tail = Tail(angle=180, size=1.4)        # locked trail direction (180 = left); callables ok
ship.visual = Halo()                         # Shape: med ADD / high Blur+rim; Sprite: SDF + blit + rim
ship.visual = Halo("cyan", amount=1.2)    # seed tint + amount
ship.visual = Halo(style="fill")                     # opaque host fill (Sprite blits the bitmap)
ship.visual = Halo(style="soft")                      # fill look; batched HostGlow at medium and high
ship.visual = Halo(style="pulse", rings=3)            # hollow + concentric rings inside the outline
Circle(center=(100,100), radius=30, color="coral")  # sugar for Paint
ship.fill = Color("gold")            # recolors neon costume (primary tint)
NEON = Neon("cyan")                        # seeds cyan onto shape at assignment
fleet_ship.visual = NEON                     # share / auto-intern
ship.visual = Neon("red")
ship.color = "green"                 # de-seeds; Neon tracks host live from here
# ship.visual = Glow(...)                  # TypeError — stamps: .glow / .shadow / .hue / .tail
gem.visual = Beat(amount=0.1, speed=1.2)   # scales over existing shape.scale
token.visual = InsetRim()                    # fill_scale 0.8, amount 0.3, width 6
ship.dissolve_out(0.5, style="vortex")     # life (death; hide on done)
ship.flash(); ship.pulse_outline()         # stack hit channels with life
ship.pop(scale=1.25)                       # temporary draw scale (pop channel)
ship.knock(distance=12, angle=30)          # stacks with pop; draw offset only
ship.spark_burst(0.35)                     # crackles (spark channel)
ship.blink(0.8)                            # replaces flash (i-frame strobe)
ghost.fade_in(0.4)                         # life (spawn; replaces any death)
ghost.implode(0.3)                         # life (death): scale-collapse then hide
c.fill = WaterFill()                 # procedural fill
c.fill = WaveFill("magenta")         # recolorable liquid field
fx.visual = Laser()                          # Shape: stroke ladder; Sprite: blit + SDF beam

# SpatialFx — sticky soft-domain ambience (world layer + z list order)
Fire(center=(200, 150), radius=40)          # camp / soft: disc
Fire(center=(200, 150), width=40, style="plume")  # directed: width + length
Fire(center=lambda: ship.center)            # follows the ship
Rain(p1=(0, 0), p2=(400, 300), amount=0.6)  # pad corners
Rain(center=(500, 400), width=400, height=300)
Rain.from_rect(platform)
Jet(p1=nozzle, p2=exhaust, width=14)
Jet(origin=nozzle, angle=180, length=50)
Jet.from_line(guide, width=12)
Sparks(center=anvil.center, rate=40)
GlowSpot(center=(200, 150), radius=48, color="cyan", amount=1.0)   # additive radial fade
Orb()                                                    # sun-like disc + corona
Orb(color="silver", glow=1.15, phase=0.15, soft_edge=0.1)  # moon-like
Warp()                                                   # placed hyperspace disc
Warp(center=(400, 220), radius=90, color="cyan")
# brief bangs stay on canvas one-shots: canvas.burst_at / explosion_at / fireworks_at / bubbles_at / zap_at / hit_at / debris_at
```

Effect `color=` accepts the same inputs as PaintState (`str` names, `Color`, RGB tuples). Alpha on `Color` is ignored; 4-tuples may set opacity only where the effect stores alpha (glow/shadow/pulse/spark).

Custom `post_draw(skia_canvas, scene_image)` still works and **replaces** the built-in stack when defined.

### Pipeline stages (fixed order)

`FILTER → ADDITIVE → COLOR → OVERLAY → WARP → SHADER`

Authors add in any order; the engine buckets by stage.

### Soft mode

No `post_fx_mode` / soft-mode preset. Composition is hybrid (sharp base when possible; spatial/fill-rate ops at `post_fx_scale`).

---



## 3. Effect inventory



### 3.1 Shape filters (`fill_filter` / `line_filter`)

All live in `scena/filters.py`. Zero-arg constructors use sensible defaults. All implement `_batch_key`, `_batch_outset`, and `_filter_at_scale` for quality/batching. Matching constructor params are **interned** (same key → same instance) so beginner loops do not rebuild Skia DAGs. `_batch_key` **is** that intern key, including the `input` chain and `Blur.tile_mode`, so two filters that differ only there do not share a plate. When a key rounds a field, store the rounded value on the instance: otherwise the first caller decides what every later same-key call reads (bug K6, `Grayscale(0)` after `Grayscale(0.00001)`).


| Effect         | Mechanism                                      | Main params                             | Notes                                                                      |
| -------------- | ---------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------- |
| **Blur**       | `ImageFilters.Blur`                            | `sigma`                                 | Batched; halo inherits source colour                                       |
| **HostGlow**   | Dilate (optional) → Blur → Merge(halo, source) | `sigma`, `spread`                       | Batched across mixed tints (colour not in DAG)                             |
| **GlowFilter** | `DropShadowOnly(0,0)` + Merge                  | `radius`, `sigma`, `color`, `intensity` | Tint **is** in the DAG → per-hue `_batch_key`; ImageFilter at all qualities |
| **DropShadow** | `ImageFilters.DropShadow`                      | `offset`/`dx`/`dy`, `sigma`, `color`    | y-up: default bottom-right `(+d,-d)`; batched                              |
| **Dilate**     | morphology expand                              | `radius`                                | Batched                                                                    |
| **Erode**      | morphology contract                            | `radius`                                | Batched                                                                    |
| **ComposeFx**  | `ImageFilters.Compose`                         | outer, inner                            | No batch_key of its own                                                    |


Legacy shape toys (PointLitSpecular, Wave, …) were **removed**; use canvas **Lamp** / **DistantLight** / **Spotlight** for lighting.

### 3.1b Shape visuals (`shape.visual`)

Fill and line paints are cached in two slots: one built with the current filter object, one filter-free. A batch or fade that clears `_fill_filter` / `_line_filter` for a single pass does **not** mark the paint dirty and does not drop the other slot. Setters that change color, blend, or the filter still invalidate both slots. Procedural fills keep the paint shell and only replace the image-free shader each frame.

Author surface: `shape.visual = …` (or `Circle(..., color="coral")` → `Paint`).  
Type-hint literals exported from `stage`: `HaloStyle`, `ShieldStyle`, `BoltStyle`, `FireStyle`. Looks with `style=` list allowed values in `repr()`.
Implementation: `[scena/visuals.py](../scena/visuals.py)` (compiled packages) + `[scena/recipes.py](../scena/recipes.py)` (`Recipe` multipass).


| Path         | When                                              | Draw                                                    | Solo / batch                                                                                                                                                                               |
| ------------ | ------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Compiled** | `Paint`, `Flame`, `Swell`, `Halo` high, … | Single `_geometry_draw` after `apply` writes PaintState | **Not** forced solo on Shape; GlowRim (Shape Halo high, ElectricField med/high, Bolt high, ElectricBolt high, Shield(style="plasma"), **Rim all qualities**) = batched Blur + deferred rim. **Sprite Halo/fill / Rim:** `_render_sprite_body` (SDF; no ImageFilter). Stamps `Glow` / `CheapGlow` / `Shadow` compose via `.glow` / `.shadow`, not `.visual` |
| **Recipe**   | `Neon`, `Extrude`, `Water`, `Laser`, shells, …    | `Recipe.render` multipass each frame                    | **Solo** (`_is_multipass`) unless consecutive interned Laser / Neon / Ink (`_look_pass_group`) with `batch_shared_filters`; ElectricField **med/high**, Bolt **high**, and **Rim** (all qualities) are GlowRim (batch). ElectricField / ElectricBolt **high** PE-glow shares one overlay Plus plate. **Sprite Laser / Rim:** blit + SDF                                                                                                |


Animation without multipass: curated `ProceduralFill` ticks time in `to_skia_fill_paint`.  
Animation with multipass: `Recipe.render` reads clock each frame.

**Primary tint policy:** `color=` is the hero tint per look. Roles A–E (body / outline / pigment / fixed art / motion) are documented in [Guia da API](../docs/pt/guide/index.html#aparencia-cor); authors need not memorize the matrix. Live sample = field reads only; never rebuild ImageFilter DAGs from tint each frame.

Five rules:

1. `shape.color = X` / `set_color(X)` flows into a `.visual` that binds to host color, unless that look has a fixed tint (`_tint_channel is None`, e.g. Water).
2. A visual that *sets* a color writes that color into the **identity** snapshot, so `visual = None` or a swap leaves it behind: a body look (Role A: `Neon("green")`) as the shape color (fill + derived outline, what `color=` writes), an outline look (Role B: `Rim("green")`, `Halo("green")`) on the outline only, exact (`PaintState._identity_patch_seed`, channel resolved from the look's role; 2026-10-13 — before, an outline seed dyed the body too). `Rim("red")` is `line = "red"` then `Rim()`, on screen and once removed: an outline look that draws its seed must draw what it draws following that line (HaloSoft no longer paints the body with its seed, ElectricBolt's mid stroke reads the seed, not the stashed host line).
3. `set_color(X)` / `.color = X` writes what `color=X` writes (fill X + `contrast_tone(0.2)` outline; a ring keeps its ring), under any look; an outline look then follows that derived outline, so `Circle(color="red")` + `Rim()` and `Rim()` + `set_color("red")` draw the same pinkish rim (decided 2026-10-13; before, Role B wrote the exact line, which no `color=` gives, and it stayed after `visual = None`). For an exact outline: `Rim("red")` or `.line = "red"`.
4. `.fill` / `.line` written under a look re-apply it (`PaintState._look_channel_written`): writing before or after `visual =` draws the same, and a seed on the written channel gives way (de-seed, as in `set_color`). Installers (Paint / Fill / Stroke) are left alone: a later write stands. `line_width` / `blend` / `dash` / `line_cap` / `line_join` go the same way (KN8, decided 2026-10-13): the look wins where its package sets the knob (Rim's width, Halo / Bolt / Shield's blend, Shield's dash; `Rim(width=)` is the spelling to change it), the author's value shows where the look reads it (Neon, Laser, Ink…) and after `visual = None`. The constructor writes `line_width=` before `visual=`. `.line_filter` / `.fill_filter` are not routed yet (stamps own their bases).
5. An explicit later recolor on any *seeded* look that takes `color=` updates the look live — `Neon("red"); shape.color = "green"` is a green Neon from then on, and `Laser("red")` a green Laser (every look since 2026-10-13; Neon / Halo since 2026-09-10).

**Which visuals take `color=` (2026-10-05, 0.6.0).** A visual takes `color` (first positional on Recipes / compiled looks) when it paints a color of its own — body, rim, glow, trail — **or redraws the host body** (`Beat`, `Liquify`: seeded → Role A like `Neon`, unseeded → Role E, motion over the host). It takes none when the color is not the author's to pick: procedural materials (`Flame`, `Swell`, `Water` — Role D, the material is the color) and pixel operators (`Grayscale`, `HueShift(to=)`, `Recolor(key=, to=)`, `EmissiveBloom` — the colors they take are named for what they do). Contract test: `tests/test_visual_color_param.py` (`TestWhoTakesColor`) — a new visual either takes `color` or joins its `_NO_COLOR` list with a reason. `Beat(0.1)` / `Liquify(5)` (old positional `amount`) raise `TypeError` naming `amount=` (`_refuse_number_as_color`). A seeded `Beat` on `Sprite.visual` raises (`Visual._sprite_takes_color = False`): `color=` paints a Shape body and a Sprite keeps its pixels — tint with `.hue = HueShift(to=…)`.

**Omitted color, and `set_color` (2026-10-13).** One rule for every look: **a look that takes `color=` shows `set_color`; a look that takes none paints its own colors and warns.** Leaving the color out means the look's default:

| Kind | No `color` | `color=X` | `set_color(Y)` while on |
|---|---|---|---|
| **Tint look** (Neon, Halo, Bolt, Laser, Gel, Sphere, Shield bands / vortex / plasma, …) | the shape's color (body looks) or outline (outline looks) | X, written into the shape (rule 2: body looks as its color, outline looks as its outline) | Y, live (outline looks: Y's derived outline, rule 3) |
| **Palette look** (`Metal`, `Shield(style="bubble")`) | its own palette (chrome, lime film); the shape's color is left alone | the palette tinted by X, written into the shape | Y, live: the look swaps to its shape-following sibling |
| **Material** (Flame, Swell, Water, the other Shield styles) | its own palette | refused | hidden, warns once (below) |

A palette look's default never overwrites the shape: a power-up `Shield()` that comes and goes must leave the ship its own color (`visual = None` restores it). Only an author-given color is written in, as for every look. The recolor sibling is one interned instance per look and knobs (`Metal(_FOLLOW_SHAPE, amount, speed)`, private sentinel; the de-seed paragraph below), never the palette instance: de-seeding a palette look to its no-color twin would drop the colour `set_color` just wrote. Colouring the palette: `Metal` mixes its chrome stops toward the tint in SkSL (`u_tint`) and the rim follows (`recipes._metal_edge`: 60 % from the tinted base toward the tinted highlight, where `_METAL_EDGE` sits on chrome); the bubble rotates its palette (`Shield._BUBBLE_PALETTE`, uniforms `u_lime` / `u_yell` / `u_film`, plus the rim and glow) onto the tint with `recipes._shift_palette` (hue offset added, saturation and value scaled from the base slot). No color passes the palette as is, so default pixels never go through the shift. Before 2026-10-13: `Metal()` and `Metal("gold")` ignored `set_color` without a warning though labelled Role A, a gold Metal kept the chrome rim, and the bubble refused `color=` (KN4). Guards: `test_visual_color_param` (`TestSetColorShowsWhereColorIsTaken`: every wearable look × style, unseeded and seeded; `TestPaletteLooks`), `test_visuals` (`test_metal_color_tints_the_rim`, `test_bubble_shield_color_rotates_its_palette`).

**Role D hides `set_color` (warn once).** Role D = the look paints its own colors and takes no `color=` (Flame, Swell, Water, the Shield styles other than bubble / bands / vortex / plasma). `set_color` under it still writes the live channel and the identity snapshot, so the color shows after `visual = None`, but no pixel changes while the look is on. `PaintState.set_color` emits one `RuntimeWarning` per look class (`style._warn_recolor_hidden`; recoloring a group with a few flames must not flood). `.color` reads the **current** colour, the live paint (a Halo wash reads as the wash, alpha included; decided 2026-10-08, PM5 in Testing Design); under such a look it reads the **identity** color when the live paint is not a solid `Color` (Flame / Swell install a `ProceduralFill`; the getter once returned the navy fallback `(0, 0, 0.5)`). The role label is load-bearing: a look that draws the host body is Role E, not D (`Liquify` was mislabelled D) — `TestRecolorUnderOwnColors.test_role_matches_whether_set_color_shows` renders every zero-arg D/E look before and after `set_color` and checks the label against the pixels.

**Same-value paint writes (2026-10-20).** An author repaints by state every frame (`self.color = "red" if hit else "white"`): the full write re-parsed the colour, derived the outline and dropped the cached Skia paints, so the draw rebuilt them (~14–19 µs a shape; 120 boids ~2 ms on this machine, ~8 ms on the target). `set_color` / `.color =` keeps `(value, fill, line)` in the `_color_memo` slot after a write with no look on; the next write of the same plain value returns at once when the fill and line are still those objects and no look (`_visual`) or identity snapshot is on. "Same" (`style._same_plain_paint`) is the same object, an equal str, or a Color with exactly the same channels: `Color ==` rounds to 3 decimals and would stall a slow fade. `.fill =` / `.line =` keep `(value, paint)` in `_fill_memo` / `_line_memo` and take only the same object or an equal str, so `set_color`'s own fresh Colors pass unchecked. Tuples, Gradients, Textures, Attributes and linked channels always take the full write. Any write that changes a channel (`set_alpha`, `look_like`, a look, a ring) leaves the memo's objects behind, so the check fails and the next write is full. The memo slots are written with `object.__setattr__` (an Entity's `__setattr__` only forwards a private name, after ~0.3 µs). Measured (two trees, eight alternating processes): `color = RED` 13.9 → 1.0 µs, `color = "red"` 18.8 → 1.0, `fill =` the same 4.5 → 1.0; a colour that changes on every write pays the bookkeeping, `color` alternating 13.9 → 14.7 µs (+5 %), `fill` alternating 4.2 → 4.4, a Gradient `fill` 2.44 → 2.48. Guard: `tests/test_per_object_costs.py` (`TestSamePaintWrites`: the cached paints survive, a new colour still repaints, a slow fade stays exact, and a metamorphic run of random writes with the check off agrees after every step).

**A colour that changes every frame (showcase D4, 2026-10-23).** A plain colour replacing a plain colour on `.fill` / `.line` sets the colour on the paints already built (`PaintState._recolor_cached_paints`: both slots, bare and filtered; a paint built from a Color carries no shader) instead of dropping them for two Paint builds at draw. The cache fields are written with `object.__setattr__`, and `set_color` keeps the last derived outline tone (`_tone_memo`). 126 triangles under a live colour formula: 3.97 → 3.23 ms CPU a frame (raster, in-process A/B). A Gradient fill whose shape changes size swaps the re-fitted shader on its kept paint (`_to_skia_fill_paint`; D5: +0.7 ms for 200 animated gradients, not the 10 ms reported). Guard: `tests/test_color_link_paint.py` (pixels: a linked colour, `=` each frame, a fill filter, a line shape, colour → Gradient → colour, a growing gradient against a fresh one).

**Engine-made colours skip the parser (2026-10-21).** A colour that *changes* every frame (`fio.color = CORES.get_color(x).with_alpha(near)`, a fade, a ramp by position) misses the memo above and pays the full write; part of that was rebuilding Colors through the author-input parser (`as_payload_all` three times, `_parse_color_args`, `_validate_color_components`) from channels the engine already held in [0, 1]. Three paths now build through `Color._unit` (no parse, clamps, seals — the derived-outline constructor since 2026-10-13): `Color.with_alpha` (its own channels, alpha clamped by `alpha01`), `Color.interpolate` in RGB and OKLAB (both clamp; so `Colormap.get_color`), and `style._coerce_channel_paint`'s copy of a `Color` (the copy a `fill` / `line` write keeps; a none-Color copies as the parser copies it, `_is_none` False). A subclass of Color still goes through its own constructor. Values are exactly the parser's (gamma of 1.0 is 0.9999999999999999, so the clamp never changes a value the parser accepts); author input (`Color(…)`, a name, a tuple) is parsed as before. Measured (HEAD vs HEAD + this, eight alternating processes each): `with_alpha` 3.40 → 0.80 µs, `get_color` 6.17 → 3.37, `line.color =` a changing Color 13.84 → 8.69, `fill =` a changing Color 7.94 → 3.09, `color = "red"/"blue"` alternating 18.3 → 14.2; the same-value write (0.94) and author `Color(…)` (2.6 / 3.7 µs) unchanged; `examples/constelacao.py` (55 threads recoloured per frame) 7.73 → 7.06 ms of logic a frame. Guard: `tests/test_color_fast_paths.py` (channels equal the parser's over random colours, ramps and overshooting `t`; results sealed; a spy that the parser is not reached on a per-frame repaint; canary: the slow paths restored fail the spy).

**De-seed on explicit recolor (Phase 1, 2026-09-10):** `set_color` writes the live channel, then `PaintState._deseed_active_visual()` swaps `_visual` to that look’s interned unseeded sibling (`Visual._unseed()` — `Neon(None, amount, width)` / `Halo(None, amount)`), then `_reapply_visual()`. Assign the private slot, **not** the `.visual` setter (that would `_restore_look_identity()` and clobber the new color). The shared interned `Neon("red")` singleton is not mutated. After the first recolor the shape sits on the unseeded singleton: later `set_color` is the already-correct live-tracking path (`_unseed()` returns `None` after a `_seed` / `_seed_color is None` check — do not intern on that path). Identity is already patched by the fill/line writes, so `visual = None` after a live recolor restores the **new** color.

**Phase 2 (2026-10-13): every look that takes `color=` de-seeds.** Each role-A/B look has its own `_unseed()` returning `type(self)(None, <every non-colour knob as stored>)`: the Recipes that seed through `_init_tint` (`_seed_color`: Aurora, Bolt, DashRing, ElectricField, Extrude, GearShell, Gel, Ink, InkBleed, InsetRim, Laser, MultiBorder, OrganicOutline, Rim, Sphere, Tracer, Wave), `HaloLine` (subclasses `Halo` but stores `_seed_color`, not `_seed`: it overrides `Halo._unseed`), the GlowRim looks (`_seed`: `ElectricBolt`, `_OrbHalo` = `Shield(style="plasma")`), and `Shield` bands / vortex (`_TINTED` branch of `Shield._unseed`). A new look that takes `color=` needs one: without it the seed wins and `test_seeded_every_look_and_style` fails. Pass every knob: a sibling that drops one (`Rim(None, amount)` for `Rim("red", width=8)`) draws the default knob after a recolor (`test_deseed_keeps_every_knob`). A knob the constructor clamps (`Extrude.layers` 3–7, `MultiBorder.layers` 1–4) is passed clamped, so `Extrude("red", layers=10)` de-seeds to the `Extrude(layers=7)` intern, a twin of `Extrude(layers=10)` that draws the same; clamping the intern key would merge them but costs ~0.3 µs on every construction (A/B 2026-10-13), so the twins stay. Paint / Fill / Stroke are installers, not seeded looks: `set_color` rebuilds them (`PaintState.set_color`). An outline look (Role B) recolored this way gets the package `color=` gives (rule 3), so the seeded sweep compares with the shape-following look worn on a shape made with `color=` the new colour. Perf (in-process interleaved A/B, 12 rounds, 60 recolored shapes): draw ±2 % (noise) across Laser / Rim / Ink / Aurora / ElectricBolt / Extrude / HaloLine / Shield bands / plasma; `set_color` itself 0–18 % faster (no seed restamp).

Family A filter batching (`Blur` / `HostGlow` `_batch_key`) is colorblind; a de-seed does not change sigma/spread. Family B look-pass grouping keys `.visual is`; shapes recolored to the same new color share one unseeded interned instance.

Palette looks (`Metal`, bubble Shield) use the same hook the other way round: their `_unseed()` returns the shape-following sibling (from the palette instance as well as from a seeded one), and that sibling's own `_unseed()` returns `None`.

Tests: `tests/test_visuals.py` (`TestSeededVisualRecolorBaseline`), `tests/test_visual_color_param.py` (`TestSetColorShowsWhereColorIsTaken`: the seeded sweep, with `SEED_WINS` empty and shrink-only — outline looks such as Rim / Ink repaint the body and keep a seeded outline, which only a "draws like" comparison catches, never a changed-pixel count; `test_deseed_keeps_every_knob`; canaries). Contract `set_color(X)` ≡ `color=X` (rules 2–4): `TestSetColorIsColorParam` (every look × style, seeded and not: pixels and the shape after `visual = None`; write order of `.fill` / `.line`; a write on a seed's channel; outline seeds; no draw re-applies; three canaries). Perf (A/B 2026-10-13, 12 rounds): `.fill` / `.line` with no look and every draw flat; `set_color` under an outline look +6 % (~4 µs: the derived outline, compensated: `Color._unit` in `from_hsl` makes `contrast_tone` 5 → 2 µs, plain `set_color` −19 %, under a body look −8 %); `.fill` / `.line` under a look ~4 → 30–55 µs (the re-apply, as `set_color`). Remaining: optional intern-cache LRU — [§9](#9-known-rules--gaps) rules 18–19, 25, [§11](#11-development-directions-open).


Extrude / Gel / Sphere / Wave / Aurora / Neon / Metal / Bolt are **Role A** (fill-bound on area). They do **not** steal the outline.

**Look identity (**`visual = None`**):**

First `.visual = …` (when `.visual` was `None`) snapshots the author package (`fill` / `line` / width / dash / cap / join / blend / filters) on the look-identity buffer. `visual = None` restores that snapshot and clears `.visual` — **not** canvas module defaults. **Stamps stay** (`.glow` / `.shadow` / `.hue` / `.tail` are orthogonal). Replacing a look (Halo → Flame) does **not** re-snapshot (live fill is already look memory). `look_like(other)` copies the buffer **and** stamps. Clear with no look is a no-op.

Assigning a stamp look to `.visual` (`Glow` / `CheapGlow` / `Shadow` / `HueShift` / `Tail`) raises `TypeError` with a stamp-property hint. The guard only fires when the line runs, so stale scripts (benches, flag-gated branches) can hide it: `tests/test_stamps.py` (`TestScriptsUseStampProperties`) AST-scans `scripts/` and `examples/` (`try` bodies exempt for smoke demos of the error). When a costume that used to replace a stamp becomes a stamp, clear it explicitly (`glow = None` before `visual = Shield(...)`) if the old exclusive look matters — stamps are sticky.

Stroke types (`Line` today; Bézier later) use `PaintState._primary_is_stroke()` → `is_stroke_type()` so `set_color`, identity seed, and sampling stay consistent.

`_identity_patch` runs **only** from the `.visual` setter after `apply` (not from quality re-`apply` or per-frame `ElectricField.render` `_apply()`). Patch the snapshot from the **seed**, never from live fill (Halo wash / FlameFill / Shield plasma must not become identity). Author `.fill =` / `.line =` / `set_color` during an active visual **do** patch identity (`_patch_look_identity`) — that is why `visual = None` after a live Neon/Halo recolor restores the new color.


| After `visual = None`                             |                                             |
| ------------------------------------------------- | ------------------------------------------- |
| `Paint("coral")` / `Circle(color="coral")`        | coral package                               |
| `Neon()` / `Fire()`                               | prior author fill/line                      |
| `Neon("cyan")` / `Halo("cyan")` / `Laser("lime")` | the seed color (not wash / not prior coral) |
| `Neon("red")` then `color="green"` then `None`    | green (identity patched at recolor; Neon/Halo Phase 1) |
| stamps (`.glow` / …)                              | unchanged (not part of identity)            |


Implementation: `PaintState` snapshot + `Visual._identity_patch` (`Paint` family captures live package; `Recipe` / Halo / Shield(style="plasma") / tinted Shield seed the bound channel). Tests: `tests/test_visuals.py` (`TestLookIdentity`, `TestSeededVisualRecolorBaseline`).

**Saved appearance (**`save_visual()` / `restore_visual()`**):**

One slot per Shape / Sprite. First `save_visual()` captures the full on-screen appearance (same payload as `look_like`: channels, interned `.visual`, look identity, **stamps**). Further saves are silent no-ops until `restore_visual()` clears the slot. Empty restore is a no-op. Restore uses `look_like`, not `visual = None` — so `Neon()` home and stamps come back, not the pre-costume identity package. Refresh overlay duration with `after(..., name=)` (two bonuses in a row); do not call `save_visual()` again while the slot is full. Orthogonal to transients. Demo: `scripts/smoke/mix.py` (click overlay). Tests: `tests/test_visuals.py` (`TestSaveVisual`), `tests/test_sprite.py` (`TestSaveVisualSprite`).

**Appearance stamps:** sticky pigment / motion on top of one exclusive `.visual`. Sprite: `.glow` / `.shadow` / `.hue` / `.gray` / `.tail`. `.gray` (`Grayscale(amount=0–1)`, luma) is a second blit ColorFilter composed **over** hue (`ColorFilters.Compose(gray, hue)` in `Sprite._apply_blit_paint_extras`, so the static, live-hue and Recolor routes all get it); a gray sprite stays `_plain_blit`. Out-of-range amounts raise. Shape: `.glow` / `.shadow` / `.tail` (no `.hue`; bitmaps use `Texture(..., shift=HueShift(...))`). Text: `.glow` only (`glow=` ctor); no costume `.visual`. Sugar: `True` / color / number (Tail angle or hue turns) / full object; read back the look or `None`. No `.cheapglow` property — `CheapGlow(...)` goes on `.glow`. `Tail(True)` / `tail = True` follows last center motion; `Tail(angle=…)` locks; callables link live fields on Tail `angle` / `size` / `amount`.

**Perf target:** shared Recipe on ~30 shapes should stay realtime. Prefer **compiled** / shared filters for fleets; use **`CheapGlow` on `.glow`** (filterless ADD halo) on projectiles. Keep sparse same-filter fleets **spatially clustered** when possible (union AABB cost). **Never** attach heavy ImageFilters inside multipass Recipes (use `.glow` / `GlowFilter` / `HostGlow` for mass halo). GPU `Blur` on a compiled `line_filter` is the GlowRim package (**Shape** Halo high, ElectricField med/high, Bolt high, ElectricBolt high, **Rim at every quality**). Halo **medium** on Shape is filterless ADD strokes. Halo(style="soft") is the cheap batched `HostGlow` hollow look. **Sprite** `Halo()` / `Halo(style="fill")` / `Laser()` / `Rim()` use FrameFx SDF instead of that Blur package.

**Recipe paint (Cluster A, 2026-09-09):** `_stroke_paint` / `_fill_paint_from` set Skia `Color4f` from RGBA tuples — no `Color()` / `as_payload_all` / validate on the tuple path. The 4-slot `Paint` pool is unchanged. Interned seed tints (`Laser("tomato")`) bake one RGB `Color4f`; pulse and layer alpha use `setAlphaf` only. White cores share a module `Color4f`. Other RGBs intern in a small map. Pixel-identical; no author API or z change.

**Recipe look-pass grouping (2026-09-09; kind-pure buckets 2026-09-10; host stroke caps 2026-09-22):** consecutive shapes sharing one interned stroke Recipe (`Laser` / `Neon` / `Ink`, `_look_pass_group`) on one layer emit pass-major (halos, then mids/bodies, then cores) with a shared paint per pass. Line/Circle use world `drawPoints` / `drawCircle` (skip Line midpoint CTM). Emit buckets key tint/width, `_world_stroke_kind` (`line` / `circle` / `path`), **and** host `line_cap` (plus `line_join` when the kind is a stroke type) — see [§5.6 look-pass bucket keys](#look-pass-bucket-keys--world-stroke-kind). Z relaxes **only** among that interned look on that layer — same family as filter `_batch_key` grouping. Since 2026-10-12 a run is no longer only consecutive peers (**overlap-aware batching**, below). Escape: `fx_quality="max"` / `canvas.batch_shared_filters=False`. Sprites, stamps, CheapGlow, transients, and hero Recipes (Water, Metal, …) stay per-shape `render`. Bench: `scripts/bench/perf_shape_draw.py --suite --no-sweep-quality`. Tests: `tests/test_visuals.py` (`TestLookPassGrouping`, `TestHostStrokeCaps`).

**Host stroke caps (2026-09-22):** Host-following outline recipes (`Neon`, `Laser`, `Ink`, `Rim`, `Bolt`, `Halo`, …) pass `shape.line_cap` into `_stroke_paint` / rim paints (and `line_join` only on stroke types — `Line` / `Track` / Contrail `_Stroke`). Area shapes keep recipe join `"round"` so neon/rim corners stay soft. Costumes that own their stroke mark (`ElectricField`, `ElectricBolt`, `Shield`, `GearShell`) leave the paint default `"round"`. `Contrail(fade=True)` butts interior samples and applies `line_cap` only at the two tips. Framework default stays `"round"` — untouched scenes change only for faded Contrails (no bead per stamp).

**Graphic.draw ceremony (2026-09-09):** stamp import is hoisted; transient / stamp probes run only when `_tx_state` / `_glow` / `_shadow` / `_hue` / `_tail` is set.

**Plain Shape/Sprite blit (2026-09-10):** sticky `_plain_blit` Graphics skip the envelope via `_blit_plain` — Shape: `_pull_property_anchors` + `_geometry_draw`; Sprite: pull + `_blit_image`. Linked `angle` / `scale` must pull on this path (PropertyAnchors are not pull-on-read). Isolation plain `draw_ms` ~20% down; Recipe cells flat. Cull-off draw walk skips `_passes_cull` when `cull_offscreen` is False. [Sprite Design.md](Sprite%20Design.md#plain-blit--draw-list-compact) · [Shapes Design.md](Shapes%20Design.md#plain-draw-_blit_plain) · [Canvas Design.md](Canvas%20Design.md#offscreen-culling).

**Overlap-aware batching (2026-10-12, B5; `canvas._BATCH_REACH`).** A look run (one interned stroke Recipe) or a one-key filter segment (every member has the same `(fill _batch_key, line _batch_key)`) takes later runs of the same look or key past the runs between them, when none of its boxes meets a box it passes.

- **The box** is the cull box (`_cull_box`: draw box, filter and costume outsets, transient, tail and multipass pads). It must hold every pixel the draw can paint, as culling already requires; unknown geometry is the whole plane and stops the reach. A look whose paint has no bound sets `_cull_outset = inf` (Extrude: its slabs reach toward the vanishing point; the review of 2026-10-12 found reach drawing a Neon peer under them). A look that paints past a constant pad says how far (`_cull_grow`, `Sprite._draw_aabb`'s SDF quad pad: [Canvas Design, "Offscreen culling"](Canvas%20Design.md#offscreen-culling)).
- **Peers that overlap** relax across the runs they pass, as they would side by side: Neon A, a far Blur, Neon B over A draw pass-major (A's and B's halos, then their cores), as `[A, B]` adjacent would. That is the rule, not a leak (review 2026-10-12, item 8).
- **Why the picture is the same:** draws with disjoint boxes touch disjoint pixels, so they commute. Z between different looks is unchanged. Only peers of one look or key relax, as they already did inside a consecutive run, so the rule "z relaxes only among that interned look / key" now covers every peer the reach can bring together, not only neighbours.
- **What does not merge:** a mixed segment (two keys) or a solo draw.
- **Plan:** `_iter_units` yields the runs (plain blits as one range). Runs are drawn as they come until the first look or filter run; from there they are buffered, and `_merge_reach` runs only when a look or a segment repeats. It follows each signature's chain of next indices, at most `_BATCH_REACH_WINDOW` (64) runs ahead.
- **Culled objects stay in the plan** (`_CULL_IN_PLAN`): planned, not drawn, so the cull never changes the units, their signatures or the reach. Without that the cull's backoff made a still scene flicker ([Canvas Design, "Offscreen culling"](Canvas%20Design.md#offscreen-culling)).
- **Escape:** `batch_shared_filters=False` / `fx_quality="max"`.

Festa (300 Neon / glow shots): work 38.9 → 35.6 ms, submit 23.9 → 19.8 ms. Ninja, corrida and mundo: unchanged, measured old vs new code in separate processes.

The cull pads bound the gain. A multipass look's box carries `_MULTIPASS_CULL_PAD` (80 DU), sized to prevent popping at the screen edge, not to bound paint tightly. Neighbouring shots' boxes meet, and those shots stay in place. Tighter per-look paint bounds would merge more, and each would need its own proof.

Tests: `tests/test_batch_reach.py`:
- **planner property:** over random unit sequences, any pair whose order changes is peers or box-disjoint;
- **pixels:** reach on equals reach off over interleaved scenes (Neon in two colors on rects and polygons, glow in two colors, plain, shadow and ADD shapes) where peers stay apart and other looks overlap them;
- **canary:** a reach that ignores overlaps is caught.

**Electric* overlay-glow batch (2026-09-09):** ElectricField / ElectricBolt **high** PE bloom (`_gpu_blur_stroke`, interned `Blur(σ=2.2)`, Plus) is one shared plate among consecutive interned peers on the filter segment, then unfiltered mid/core. Same escape as filter batching. Isolation `circle_ef_static` submit_ms ~13 ms → ~0.4 ms. Do not “fix” by running medium at high.

**Neon HSV + center hoist (2026-09-10):** `_neon_tint` / `_energy_rgb` / `_energy_spark_rgb` use `colorsys` float helpers (`_vivid_rgb`, …) with a small intern — same math as `Color.vibrant_version` / HSV lifts, no per-call `Color()`. Look-pass emit reuses the bucket tint and hoists circle `_center_radius` once across halo/body/core (`centers=` on `_stroke_group_world` / `_fill_group_world`). Isolation `circle_neon_static` draw_ms ~1.42 → ~0.64. Pixel-identical; no z change.

**A gray host gives a gray look (2026-10-08):** a saturation *lift* (`_vivid_rgb`, `_energy_rgb`, `Color.vibrant_version`) is scaled by `color._chroma_weight(s)`, which ramps from 0 at s = 0 to 1 at `_ACHROMATIC_S` (0.1). `colorsys` reports hue 0 (red) for every gray, so the unscaled lift drew `Neon()` on a white, gray or black shape as a red tube (tutorial 01: `triangulo.color = "white"`), and pinked DashRing, GearShell, ElectricBolt and `Halo(style="fill"/"soft")`. The ramp keeps grays neutral (value is still lifted: a black Neon is a light-gray tube), gives near-whites (snow, ivory) a light tint instead of a jump to full color, and leaves s ≥ 0.1 bit-identical. The same ramp guards the `Color` methods that add saturation — `saturate`, `jitter` (scales the ± saturation nudge), `accent_color`, `monochromatic` — and `Color.interpolate` in HSL / HSV (so `Colormap` too): a gray end's hue is pulled to the other end's, `h1 += (1 - w1)·w2·Δh` (and symmetrically), so white → blue stays blue instead of sweeping through magenta, as CSS Color 4 treats a powerless hue. `Recolor(key=…)` keys by hue and its shaders skip pixels under saturation 0.12 (`smoothstep(0.12, 0.28, hsv.y)`), so a gray key could never select its own color and an exact gray keyed hue 0, recoloring red pixels: `Recolor.__new__` raises `ValueError` for a key under `recipes._RECOLOR_MIN_KEY_S` (= the shader floor, guarded by a test), before interning; a gray `to` is fine (it sets saturation 0). A new helper that *adds* saturation or *reads* a hue goes through `_chroma_weight`; one that scales saturation (`s * k`) or rotates hue is already safe. Tests: `tests/test_achromatic_tint.py` (every public look, Halo style, stamp, and gray-seeded look on Shape and Sprite: no red cast; every zero-arg `Color` method on every gray stays gray; HSL / HSV interpolation keeps the colored end's hue; a gray `Recolor` key raises).

Transferable rules and the mechanisms that were rejected: [§5.6](#56-recipe-draw-hot-path--lessons).


| Visual                                   | Tier | Mechanism (sketch)                                                           | Path                              | Notes                                                                                                                                                                                                                           |
| ---------------------------------------- | ---- | ---------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Paint / Fill / Stroke**                | 0    | style package (= `set_color` family; internal installer)                     | compiled                          | `color=` ctor sugar → Paint                                                                                                                                                                                                     |
| **Glow**                                 | 0    | host + interned GlowFilter                                                   | **stamp** `.glow`                 | batchable at all qualities; `color=` tints halo only. Sugar `True` / color / `Glow(...)`. **Text** only stamp (`glow=`; CheapGlow ok). Not assignable to `.visual` |
| **CheapGlow**                            | 0    | filterless ADD strokes (same knobs as Glow)                                  | **stamp** `.glow`                 | prefer on bolts/stings; no `.cheapglow` property — assign on `.glow`                                                                                                                                                            |
| **Halo**                                 | 0    | Shape: wash + tinted stroke; med filterless ADD; high Blur + rim/spine. Sprite hollow/fill: SDF + blit + `path_v2` rim | compiled · Shape med solo / high batches; Sprite `_render_sprite_body` | Same constructor; no public v2 class; Gradient outlines kept on Shape; ctor `color=` seeds; later `set_color` de-seeds (`HaloFill` / `HaloSoft` share `_unseed`; `HaloLine` does not) |
| **Halo(style="fill")**                   | 0    | Shape: Halo shell + opaque host fill. Sprite: same SDF path, NORMAL blit (not ADD wash)                       | same as Halo                      | Non-solid fills left as-is on Shape; NORMAL blend                                                                                                                                                                                        |
| **Halo(style="soft")**                   | 0    | Halo(style="fill") with batched HostGlow at medium **and** high              | compiled (batches at high)        | No blur+rim solo pass; **same on Sprite** (no SDF); low = survival                                                                                                                                                                                           |
| **Shadow**                               | 0    | host + interned DropShadow                                                   | **stamp** `.shadow`               | batchable at med/high; off at low; sugar `True` / color / `Shadow(...)`. Shape + Sprite; not Text                                                                                                                                |
| **Shield(style="plasma") / Shield**        | 0–1  | SkSL body + GlowFilter (+ rim)                                               | compiled                          | flat styles: bubble, nebula, ember, void, molten, bands, vortex, cracks, frost, plasma. Styles that share a shader (`shield_cracks`: cracks / frost; `shield_nebula_mist`: nebula / ember / void) take *every* body color from their palette as uniforms — frost once kept magma's constants (`test_visuals.test_every_shield_style_has_its_own_body`). `color=` follows the shape on bands / vortex / plasma (tint looks) and tints the palette on bubble (palette look, like Metal: lime film without it; `set_color` retints, 2026-10-13); on the other fixed-hue styles it raises naming them (before 2026-10-12 it was taken and ignored, KN4) |
| **Halo(style="line")**                   | 0    | hollow host-tinted outline + HostGlow (no fill)                              | compiled                          | former Shield cloud rim; med/low stroke only; mixed tints share `_batch_key`; `rings=` / `speed=` other than the defaults raise naming `style="pulse"`, as on every non-pulse style (before 2026-10-12 Python's own `HaloLine.__init__()` error leaked here: KN3)                                                                                                                                                     |
| **Halo(style="pulse")**                  | 0    | hollow Halo + animated concentric rings via `_stroke_at_scale`               | compiled + overlay rings          | `rings` / `speed` on the pulse intern; survival 1 ring, lite ≤2, high = `rings`; off unless `style="pulse"` (on any other style, non-default values raise naming `style="pulse"`: KN3, KN4, 2026-10-12; `tests/test_knobs_take_effect.py` sweeps every look × style × knob for pixels) |
| **Neon**                                 | 1    | soft mask stroke + body + thin core                                          | Recipe                            | heroes; mass halo → `.glow`; ctor `color=` seeds; later `set_color` de-seeds to the unseeded intern; optional pass-level `flicker=` (0 = static, same as Laser's pulse) |
| **MultiBorder**                          | 1    | widening outline strokes                                                     | Recipe                            | not scale-expand; `color=None` keeps host                                                                                                                                                                                       |
| **Extrude** (`Extrude`)                  | 1    | depth ∝ distance to vanishing point                                          | Recipe                            | mouse VP in lab                                                                                                                                                                                                                 |
| **DashRing / GearShell / ElectricField** | 1    | shell family                                                                 | Recipe · ElectricField GlowRim    | host-tinted; GearShell closed dashes at med/high, **high** continuum sweep; ElectricField **med/high** = same GlowRim (batched Blur + Discrete-PE overlay, `speed` ≈ old 14 Hz at `1.0`, not capped by medium `pe_hz`); **low** = Recipe survival |
| **OrganicOutline**                       | 1    | host stroke + Discrete fringe                                                | Recipe                            | line tint                                                                                                                                                                                                                       |
| **Tracer**                               | 1    | dash trail                                                                   | Recipe                            |                                                                                                                                                                                                                                 |
| **Tail**                                 | 1    | ghost copies along `angle`; keeps host fill/line/width                       | **stamp** `.tail`                 | `angle` = where the trail extends (90 = up); `True` follows velocity (trail behind + length; collapses when stopped); callables on `angle`/`size`/`amount`; `size` = trail span multiplier; `amount` = ghost fade                                                                                                    |
| **Beat**                                 | 1    | looping CTM scale about pivot                                                | Recipe                            | multiplies over host scale; keeps fill/line/width. `Beat("red")` seeds the body (Role A, Shape only); unseeded = Role E                                                                                                                                                                               |
| **InsetRim**                             | 1    | inset fill (default 80%) + outline                                           | Recipe                            | `width` (default 6), `amount`; cheap; no ImageFilter                                                                                                                                                                            |
| **ElectricBolt**                         | 1    | glow + yellow mid + white core                                               | Recipe · high GlowRim             | **high** = batched Blur + Discrete-PE overlay; **medium Line** = Recipe lite at **70%** stroke width; **low** = survival ladder (`pe_hz` still caps flicker)                                                                    |
| **Laser**                                | 1    | Shape: soft ADD halo + mid + core stroke ladder. Sprite: blit + SDF bands (`sprite_sil_v2`) | Recipe                            | line-first; Shape high = same ladder as medium; Sprite slightly thicker than Shape                                                                                                                                                                                        |
| **Ink / InkBleed**                       | 1    | host + pen/wet stack                                                         | Recipe                            | path effects                                                                                                                                                                                                                    |
| **Rim**                                  | 1    | Shape: batched Blur + ADD core (all qualities). Sprite: SDF + blit | Recipe · GlowRim always       | no MaskFilter; no quality ladder (high path is cheap enough); Sprite skips ImageFilter (`_render_sprite_body`)                                                                                                                          |
| **Gel**                                  | 1    | Multiply + SoftLight + rim                                                   | Recipe                            | fill tint                                                                                                                                                                                                                       |
| **Swell / Flame**                        | 2    | procedural materials                                                         | **compiled**                      | Flame default `border=False` → black rim @ 0.5 α (closed); Line stays yellow                                                                                                                                                    |
| **Metal / Sphere / Wave / Aurora**       | 2    | procedural materials + rim (wave/aurora)                                     | **Recipe multipass**              | Metal: grain on the body (`speed`; `0` freezes); specular world-locked; chrome rim; `Metal(color)` mixes the chrome palette toward the tint (`u_tint`, carried in the fill's `_extra_rgb["tint"]`) and tints the rim (`_metal_edge`; before 2026-10-13 it stayed chrome), `Metal()` stays chrome on any shape color (palette look: `set_color` retints through the shape-following sibling; before 2026-10-09 the tint never reached the shader; guards `test_visuals.test_metal_color_tints_the_metal`, `test_metal_color_tints_the_rim`)                                                                                                                                              |
| **Water**                                | 2    | free-surface multipass + clip                                                | Recipe                            | not host fill                                                                                                                                                                                                                   |
| **Liquify**                              | 2    | hue-shifted ghosts + host                                                    | Recipe                            | `color=` seeds the body (Role A); ghosts hue-shift from it. Unseeded = Role E |
| **Bolt**                                 | 2    | `core                                                                        | filaments                         | tesla`                                                                                                                                                                                                                          |

**A knob one style reads raises on the others (KN4, 2026-10-12).** `Shield(color=)` off bubble / bands / vortex / plasma (bubble joined 2026-10-13), `Halo(rings=, speed=)` off pulse, `Bolt(amount=)` on core: each was taken and drew nothing different; each now raises naming the style that reads it. A new knob or style joins the sweep in `tests/test_knobs_take_effect.py` (every exported look × style × knob must change the pixels, or be refused, or be listed with a reason).




#### Reusable pattern: GPU blur halo + unfiltered rim (Halo)

Hollow neon (Halo, and any new outline-energy look) is **two jobs**, not one filter:

1. **Soft coloured bloom** — the halo. Must stay host-tinted.
2. **Sharp inner line** — the core. Must **not** be the same pixels as (1).

Halo **high** keeps a soft-band structure at about half the old MaskFilter cost: GPU `ImageFilter` Blur of a tinted stroke, wash folded into the first draw, then an unfiltered ADD rim/spine via `_overlay_after_filters` after the filter segment (the interned Blur **batches** like Halo(style="soft")’s halo). `Halo(style="pulse")` reuses that rim hook plus `_stroke_at_scale` for concentric rings that stay inside the host outline. Neon `flicker>0` is a pass-level sine on the ADD halo (same shape as Laser's existing pulse); `flicker=0` skips the trig call. Halo **medium** skips the ImageFilter: two cheap ADD glow strokes plus a sharp ADD outline (solo, no FX RT). The same GlowRim package ships on **ElectricField medium and high** (Discrete-PE rim/spine; PE seed uses `speed` at both qualities — `1.0` ≈ old 14 Hz; medium `pe_hz` does not slow the arcs), **ElectricBolt high**, **Shield(style="plasma")**, **Bolt high**, and **Rim at every quality** (interned `Blur` on `line_filter`, host fill kept NORMAL, unfiltered ADD core via `_overlay_after_filters`; no lite/survival substitute — the GlowRim path is cheap enough). Bolt **medium/low** stay Recipe solo (ADD lip). **Halo(style="soft")** is the fleet HostGlow path (one batched draw at medium *and* high).

**Sprite exception.** Interned Halo/Laser/Rim instances are shared across Shape and Sprite, so `_is_multipass` cannot be per-host. On Sprite, `Halo._apply` / `HaloFill._apply` / `Rim._apply` install **no** ImageFilter; `Graphic.draw` (and the transient envelope) call `_render_sprite_body` — SDF glow (`sprite_sil_v2`) + blit + one smoothed-path rim. Sprite `Laser.render` blits then SDF bands (stroke-ladder fallback). **Do not** route Shape Halo/Laser/Rim through that path: GPU `drawCircle` / cached polygons are faster and look better. `HaloSoft._render_sprite_body = None` so Sprite soft Halo keeps HostGlow.


|                                           | Glow (halo)                                                              | Inner line                                               | Draw                                                        |
| ----------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------- | ----------------------------------------------------------- |
| **Don't**                                 | `GlowFilter` with tint in the DAG (N `_batch_key`s ≈ N solitaires)        | Mix white / “hot” into the stroke that gets blurred      | MaskFilter per shape                                        |
| **Don't**                                 | `HostGlow` Merge if you need a *soft* band (Merge puts a hard core back) | Brighten by bleaching the halo source                    | Special-case Line to a thinner stroke                       |
| **Do (Halo / Halo(style="fill") medium)** | Unfiltered fat ADD strokes (no ImageFilter)                              | Later sharp ADD outline                                  | Solo geometry; cheaper than HostGlow+rim                    |
| **Do (Halo(style="soft") / fleet)**       | Interned `HostGlow` (`Dilate` + `Blur` + `Merge`) on `line_filter`       | Merge *is* the sharp core; keep the stroke thin          | One `_geometry_draw`; mixed tints **share one** `_batch_key` |
| **Do (Halo high / GlowRim)**              | Interned `Blur` only (no Merge) on a **wide** tinted stroke              | Second draw: filters stripped, ADD stroke + hotter spine | 2 draws; Blur **batches**, rim via `_overlay_after_filters`  |
| **Do (Sprite Halo / Laser / Rim)**        | One ADD SDF quad (`sprite_sil_v2`)                                       | Blit + optional `path_v2` rim                            | No ImageFilter RT; Shape stays on the rows above            |


**Why the split matters.** A MaskFilter / blur-only stroke has no hard edge — that *is* the atmospheric glow. `HostGlow` Merge is Halo(style="soft")’s fleet trick (sharp core for free, one batched draw). Halo medium gets the sharp edge from an unfiltered ADD outline on top of cheap glow strokes (no blur kernel). Halo high wants a *soft* bloom band, so drop Merge and put brightness on a **later unfiltered pass**. Mixing the core toward white *in the glow source* tints the bloom pale; lifting RGB / double-ADD / a second spine on the rim pass does not.

**Same package on Line and closed outlines.** High halo width is the stroke that gets blurred (`line_width` 3.2). Medium Halo/Halo(style="fill") do not blur — glow is fat ADD strokes, then a ~1.45 ADD core. Lines skip the interior wash fill.

**Quality re-apply.** Compiled Halo rewrites `fill` / `line` to the wash + mixed core. On the next `_fidelity_sensitive` `_apply()`, sampling those channels poisons tint (wash α≈0.12; Line core already mixed toward white). Stash the author tint on the **shape** before the first rewrite (`_aura_host_tint`); high reads the stash, not the leftover package.

**Filter choice cheat-sheet**


| Need                                              | Use                                                                           |
| ------------------------------------------------- | ----------------------------------------------------------------------------- |
| Mass filled-body halo, author-chosen glow colour  | `GlowFilter` (tint in DAG — share **one** instance, or pay per hue)           |
| Halo that follows each shape’s stroke/fill colour | `HostGlow` or `Blur` on `line_filter` (colour not in DAG)                     |
| Soft neon band like MaskFilter, no hard core      | `Blur` only, then extra unfiltered rim                                        |
| Sharp core + bloom, one draw, fleet-batchable     | `HostGlow` (`spread` dilates the halo only) — **Halo(style="soft")**          |
| Sharp outline without an FX RT                    | Unfiltered ADD glow strokes + ADD core — **Halo / Halo(style="fill") medium** |
| Sprite silhouette glow / beam                     | FrameFx SDF (`sprite_sil_v2`) + blit — **Sprite Halo / Laser**                |


**Legacy:** Foam plumes use `canvas.bubbles_at` (not a shape visual). Orphan EnergyFill SkSL removed.

**Procedural fills:** `WaterFill`, `FlameFill`, `SwellFill`, `WaveFill` / `AuroraFill` (also usable as `fill` without a named visual).

**Transients** (see §3.1c): multi-channel; never assign `.visual`. Demo: `scripts/smoke/transients.py`.

### 3.1c Shape Transients (`scena/transients.py`)

**Orthogonal to visuals and sticky style.** Timed one-shots never assign `.visual` / paints / filters. Progress is **draw-composed** into a pure `DrawMods` envelope; completion side effects run only in `tick_all_transients()` (after link `flush`, **before** `draw`).

#### Channels

Each shape has six independent slots. A method **replaces only its channel** (previous occupant cancelled — its `on_done` fires once with `.cancelled` True), except a second **`blink`** on an in-flight blink (see **Blink refresh** below). Other channels keep running. A transient on a destroyed shape — including one whose replaced occupant's `on_done` just destroyed it — is dropped silently and never re-enters the tick registry (system-test finding S8).


| Channel   | Methods that install here                                      | Role                                         | Finish side effect                                 |
| --------- | -------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------- |
| **life**  | `dissolve_out`, `burn_out`, `fade_out`, `implode`, `dissolve_in`, `fade_in` | Spawn or death (one mutex)                   | death: `visible=False`; spawn: forces `visible=True` on start; optional `on_done` |
| **flash** | `flash`, `blink`                                               | Hit wash / i-frame strobe                    | clear only                                         |
| **pulse** | `pulse_outline`                                                | Expanding outline (does not touch `.visual`) | clear only                                         |
| **pop**   | `pop`                                                          | Scale punch (CTM only)                       | clear only                                         |
| **knock** | `knock`                                                        | Draw-offset punch (CTM only)                 | clear only                                         |
| **spark** | `spark_burst`                                                  | Outward crackle flecks                       | clear only; **never** hides                        |


Same-channel exclusivity (by design): any two life verbs (including spawn vs death); flash↔blink. A second `blink` **refreshes** the live blink (does not cancel). **Not** pop↔knock — they stack.

#### Method inventory


| Method                                  | Channel | Class                | Default dur | Notes                                           |
| --------------------------------------- | ------- | -------------------- | ----------- | ----------------------------------------------- |
| `dissolve_out(style=, angle=)`          | life    | `Dissolve`           | 0.5 s       | Dig mask then hide; see styles; `on_done`       |
| `dissolve_in(style=, angle=)`           | life    | `DissolveIn`         | 0.5 s       | Inverse dig; stays visible; `on_done`           |
| `fade_out` / `fade_in`                  | life    | `FadeOut` / `FadeIn` | 0.35 s      | Alpha only; `on_done`                           |
| `implode(scale_end=)`                   | life    | `Implode`            | 0.28 s      | Scale-collapse + fade then hide; `on_done`      |
| `burn_out`                              | life    | `Burn`               | 0.55 s      | Hot multipass body + dig; `on_done`             |
| `flash(intensity=)`                     | flash   | `Flash`              | 0.12 s      | White ADD peak→decay; `on_done`                 |
| `blink(rate=, intensity=)`              | flash   | `Blink`              | 0.8 s       | Alpha strobe; mild flash while on; second blink refreshes; `on_done` |
| `pulse_outline(color=)`                 | pulse   | `PulseOutline`       | 0.25 s      | Expanding stroke overlay; `on_done`             |
| `pop(scale=)`                           | pop     | `Pop`                | 0.18 s      | Scale envelope about pivot; `on_done`           |
| `knock(distance=, angle=)` or `dx`/`dy` | knock   | `Knock`              | 0.14 s      | Offset punch; `angle` in **degrees**; stacks with pop; `on_done` |
| `spark_burst(amount=, color=)`          | spark   | `SparkBurst`         | 0.35 s      | ADD flecks; does not hide; `on_done`            |
| `clear_transients()`                    | *all*   | —                    | —           | Cancel; **no** callbacks                        |


**Signature grammar** (same as `canvas.fade_out`): `verb(duration=DEFAULT, *, look…, on_done=None)`. A bare number is always seconds. Look knobs (`style=`, `scale=`, `color=`, `intensity=`, `amount=`, `distance=`, `rate=`, …) are keyword-only. `on_done` is keyword-only. Empty call stays valid (gradual defaults). Module-level `scena.transients.*` twins match. Payload is `(shape,)`, arity-truncated like `@collide` / `after` (`on_done=e.destroy` is legal). Durations clamped ≥ ~0.05 s. Exceptions in `on_done` warn and disable that callback.

**Replace:** a second method on the same channel cancels the first (its `on_done` fires once as cancelled) with no framework warning (re-trigger is the common hit case).

**Blink refresh:** a second `blink` while one is in flight keeps `t0` (strobe phase) and `rate`, sets remaining time to at least the new duration (`duration = max(old, elapsed + new)` — never shrinks the window), takes `max` intensity, and replaces `on_done` only if the new call passed one. Returns the live handle; the first callback is not fired. `flash`↔`blink` is still a hard replace.

**Hard** `destroy()`**:** `Registry.destroy` runs `clear_transients` (no pending `on_done`), sets `shape.is_alive` False, then undraws and `clean_up()`. Hide-only life finish does **not** cancel other channels. Soft `undraw` does not flip `is_alive`.

**Park (`active = False`):** does **not** freeze or cancel shape transients — they are presentation (presentation time, like the cover: they run while the world is paused or slowed), not owned process time. Prefer `dissolve_out(..., on_done=self.park)` so the FX finishes while still visible (park forces `visible=False`). Stop early with `clear_transients()`; freeze the world with `clock.paused`, not fleet-wide park. See [Actors Design.md — `active` (park)](Actors%20Design.md#active-park).

#### Dissolve styles (`style=` on dissolve_out / dissolve_in)


| PaintState          | Visual                                                                     | Params                       |
| ------------------- | -------------------------------------------------------------------------- | ---------------------------- |
| `"noise"` (default) | Fractal noise threshold dig                                                | —                            |
| `"vortex"`          | Spinning multi-arm shrink to pivot (continuous multipoles; no `atan` seam) | optional `angle` spins bias  |
| `"wipe"`            | Directional band dig along axis                                            | `angle` **degrees** (0 = +x) |
| `"fade"`            | Alpha only (no dig mask)                                                   | —                            |


Mask shader: SkSL `dissolve` in `scena/_sksl_shape.py`, applied as `DstIn` over a layer. Local matrix places UV center on the shape pivot.

#### Draw envelope (paint never finishes channels)

Per-frame order for an active transient shape:

1. **CTM:** knock `offset` · pop/implode `scale` about pivot (geometry Attributes unchanged).
2. **saveLayer** when alpha ≠ 1 or dig active (`Alphaf` = composed `alpha_mul`). Layer rect from `_transient_layer_bounds`: prefer padded `_approx_draw_aabb` (scale about pivot, knock offset, pulse/spark/burn pad); else a square from `shape_pivot` half.
3. **Body:** burn full hot multipass, else Sprite `_render_sprite_body` if present, else `visual.render` / geometry.
4. **ImageFilters:** during dig **or** non-identity alpha, `fill_filter` / `line_filter` are **omitted for that pass only** (GlowFilter’s light plate would otherwise fade as a backdrop wash). Sticky assignment unchanged.
5. **Overlays:** flash wash · pulse stroke · channel `overlay_after_body` (sparks).
6. **Dig mask** if `dissolve_progress` > 0.

Solo draw: active transients force full `obj.draw` (same as multipass visuals; not filter-batched).

**Pivot / layer extent (`shape_pivot`, 2026-09-18):** `shape_pivot` returns `(cx, cy, approx_radius)` for CTM, dissolve UV, and the square fallback. Order: stroke midpoint → true `radius` hosts (Circle / RegularPolygon — do **not** inflate via AABB √2) → circumradius of `_approx_draw_aabb` about the pivot (free Polygon verts, Text `_domain_aabb`, rotated Rect/Square) → oriented `width`/`height`/`length` half-diagonal → last-resort 24 DU. `recipes._center_radius` delegates here so Recipe UV matches the envelope. **Bug fixed:** free Polygon / large Text / rotated Square used `r=24` or `length/2`, so `fade_in` / `dissolve_in` `saveLayer` clipped to a center patch only. Tests: `tests/test_transients.py` (`TestShapePivotExtent`).

#### Author patterns

```python
# Death stack (hits compose with life)
ship.dissolve_out(0.5, style="vortex")
ship.flash(0.12)
ship.pulse_outline()
ship.pop(scale=1.2)
ship.knock(distance=12, angle=180)
ship.spark_burst(0.3)
# on_done after hide
ship.burn_out(0.5, on_done=ship.destroy)

# Spawn (replaces any in-flight death on the life slot)
ship.visible = False
ship.dissolve_in(0.55, style="noise")

# I-frames (replaces flash)
ship.blink(duration=0.8, rate=9.0)

# Status until outline ends
ship.stunned = True
ship.pulse_outline(duration=0.8, on_done=lambda s: setattr(s, "stunned", False))
```

**Canvas mark vs body reaction:** the canvas verb paints *at the place*; the shape transient is *the body's* reaction. Chain them, never fold one into the other (a canvas verb does not touch actors). A hit that does not kill: `canvas.hit_at(info, angle=…)` + `hero.flash()` / `hero.knock(…)`. A death: `canvas.burst_at` / `explosion_at` (fire), `canvas.debris_at` (it broke, no fire), or `canvas.fireworks_at` (celebration) + a life transient for the silhouette (`dissolve_out`, `implode`, …).

Tests: `tests/test_transients.py`. Visual: `python scripts/smoke/transients.py`.

### 3.1d SpatialFx ambient emitters (`scena/spatial_fx.py`)

**Sticky scene décor** with soft placement domains. Sibling of Shape for **layer / groups / list-order z / destroy**, but **not** PaintState, visuals, filters, or post-FX. Boundaries are soft falloffs of the domain — never hard path silhouettes.


| Author rule                             | Prefer                 |
| --------------------------------------- | ---------------------- |
| Costume of this shape’s geometry        | visual / filter / fill |
| This shape was hit / is dying           | shape transient        |
| Something **lives here** (sticky, soft) | **SpatialFx**          |
| Brief bang **at** a point               | `canvas.*_at`          |
| Whole-picture grade                     | `canvas.effects`       |
| Scenery / chunks that never end         | `Endless` (pieces per slot; `Wallpaper(tile)` for repeated pixels) |

**Author subclasses take class keywords**, like Shape and Sprite (AC2, 2026-10-10): `class Energia(Orb, radius=16, color="gold", group="energia")`. `SpatialFx.__init_subclass__` moves the keywords into `cls._class_defaults` (merged over an author base's) and records the framework kind (`_class_kind`); each framework kind's `__init__` is wrapped (`_wrap_fx_class_defaults`) to fill the keywords a call left out, only when the instance's `_class_kind` is that kind (a framework `super().__init__` chain never receives another kind's knobs; an author `__init__` that calls `super().__init__(**kw)` still gets them). Allowed: the kind's keyword knobs, `group`, `soft_edge` (`_fx_class_keys`). Refused as author errors on the class line: placement (`center`, `p1`, `p2`, `origin`, `layer`), unknown names (did-you-mean), bad numbers (`check_numeric_params`), and `style` (it picks the class `Fire(...)` builds in `Fire.__new__`). An instance `style=` other than the default on an author Fire subclass raises too: it was silently ignored. Before, the class line raised Python's own "takes no keyword arguments". Guard: `test_spatial_fx.TestClassKeywords` (every exported kind).




#### Domains


| Domain           | Models                                        | Defining parts                               |
| ---------------- | --------------------------------------------- | -------------------------------------------- |
| Point blob       | single                                        | `center`, `radius`                           |
| Pad (rect-like)  | `CORNER_CORNER` (p1–p2) · `CENTER_WH`         | opposite corners **or** center/width/height; axis-aligned |
| Beam (line-like) | `POINT_POINT` · `ORIGIN_ANGLE_LENGTH`         | p1–p2+width **or** origin+angle+length+width |


No arbitrary shape masks. Soft edge via `soft_edge` (fraction of half-extent, default ~0.15).
No placement given (`Fire()`, `Rain()`, `Jet()`) → the **design center**, read from
`canvas.width / height` at construction (`SpatialFx._design_center`). It once read a
`design_width` the canvas does not have, and a bare `except` made it a fixed (200, 150)
at every design size; `test_spatial_fx.TestDefaultPlacementFollowsDesign` builds every
kind at two sizes other than the tests' 400×300 (whose center *is* (200, 150)).
Each domain's Derivate parts read live (`Rain(p1=, p2=).width`, `Jet(origin=…).p2`) via
`_materialize_derivate_part`, the same hook as Rect / Line.

#### Placement is points, keyword-only

SpatialFx kinds are Shape siblings and place the same way: point kinds
(Fire, Sparks, GlowSpot, Orb, Sunburst, Starburst, Warp, Portal) are Circle's siblings —
`center=` (a value snapshots, a lambda follows) plus `radius=` (directed Fire:
`width=` + `length=`). `Rain` is Rect's — `p1=` + `p2=`, or
`center=` + `width=` + `height=`. `Jet` is Line's — `p1=` + `p2=`, or
`origin=` + `angle=` + `length=`. A lone `p1=` or `p2=` raises (it used to
become Jet `origin=` silently). Positional numbers raise with a worked example
(`Fire(center=(200, 150), radius=40)`); `at=` / `x=` / `y=` / `x1=` / `pos=`
raise with the point spelling (`fx_placement_hints`, `spatial_fx.py`). `*args`
exists only to reject and is hidden from `help()`.
`TestKeywordOnlyPlacement` walks every exported kind.

**Fence — Rain has no angle.** Drops always fall straight down; the old
`angle=` only turned the pad's clip and collision hull (the Guia called it
"wind"). `Rain(angle=)` raises. Revisit: a taught scene needs slanted rain —
then it is a streak-direction knob, not a turned pad.

#### v1 effects


| Type         | Domain      | Mechanism                                                   |
| ------------ | ----------- | ----------------------------------------------------------- |
| **Fire**     | Point (`camp`/`soft`: `radius`) · directed (`plume`/`tongues`/`embers`: `width`+`length` along `angle`) | Procedural `FlameFill` core + glow discs / emission bed |
| **Rain**     | Pad (dual)  | Streak particles; `amount` = density; soft edge falloff     |
| **Jet**      | Beam (dual) | Soft core stroke + directed embers                          |
| **Sparks**   | Point       | Radius-sized spark field (not shape `spark_burst`)          |
| **GlowSpot** | Point       | Additive radial color fade (`radius`, `color`, `amount`) |
| **Orb**      | Point       | Bright disc + corona; `radius` = felt body; `glow` / `phase` / `color` |
| **Warp**     | Point       | Radial hyperspace disc (`radius`, `color`/`color2`, `spokes`, `core`, `into`, `spin`, `glow`). Not a fly field — use `Tunnel` / `StarFly` for full-screen jump |
| **Portal**   | Point       | Hollow ring of turbulent light (`radius` = the ring; `thickness` fraction, `chaos`, `tilt` + `angle` for a 3D hoop, `color`/`color2`, `glow`). **The clean sample places the light; the turbulent copy only draws strands and drifts the hue** — displacing the geometry itself turned the ring into a lumpy blob (guarded by `test_turbulence_never_moves_the_ring`). 1/d core + 1/d halo. `color2=None`: violet with the default color, a lighter tint of an author's color (never a new hue). March skipped outside a band around the ring and faded to zero at its edge (no visible cut). Steps × octaves: high/max 6×5, medium 4×4, low 3×3. Collision: circle of 1.035 × `radius` (just past the ring, so the outer strands count), or that circle foreshortened to an ellipse when tilted |


**Fire `style="blaze"`** — volumetric column (directed: `width` + `length` + `angle`, default length 2.4 × width). High: SkSL march (32 steps) on a ½-res per-instance plate sized from the device CTM (follows zoom), blitted along `angle` with `kPlus`. Max: full-res, 50 steps (reference). **Medium / low draw the `plume` look** (`_LookPlume` tick + draw); high runs no particles. Collision: plume's emission ellipse, 1.25× longer (base fixed at the hearth) and 0.7× as wide — the column is taller and slimmer than a plume. Plate RT: `_plate_surface` / `_plate_size` (`spatial_fx.py`; ceil to 32 px, cap 1024, per instance — a shared pool would copy-on-write when two blazes draw in one frame).

**Cost (×4 target proxy, 2026-10-01).** The target machine is ~4× slower than the dev M4 and the whole game has a 16 ms budget. Measured on the M4 through the real classes, then ×4: Portal ≈ 0.018 ms → **~0.07 ms** per 256² at high (measured over 1024² and divided — a small area is all fixed overhead); blaze high ≈ 0.23 ms → **~0.9 ms** per 256² footprint (max ≈ 0.4 → ~1.6 ms). **Blaze is a showpiece effect: 1–2 per scene on a weak GPU.** 20 march steps break the blaze look (rays never reach the hearth) — do not add a cheaper "lite" march; medium / low already fall back to `plume`. A cave fly-through background was evaluated and rejected (≥ 2 ms target even at reduced res).

Sugar: `Rain.from_rect(rect)`, `Jet.from_line(line)`. Linking uses normal Point/Attribute `@=` / ctor Attribute capture.

#### Lifecycle

- Construct → `Registry.register` + tick registry.
- `tick_all_spatial_fx()` after `tick_all_transients()`, **before** draw.
- Particles are instance-local lists (not DependencyGraph nodes).
- `undraw` soft; `destroy` hard (also drops tick registration).
- **Process host:** SpatialFx is an `Entity`, so `fx.after` / `fx.every` / `fx.destroy` / groups / tags work the same as on Shape / Sprite. Continuous emitters (`Sparks`) need an explicit timed teardown — prefer `fx.after(0.55, fx.destroy)` (or bare `after(0.55, fx.destroy)`, which binds to `fx` via bound-method ownership). Scheduling teardown on a dying wasp (`self.after(..., fx.destroy)`) cancels with the wasp and leaves the emitter alive.
- **A part does not die with its maker.** A `Jet` made in `Heroi.setup` (the tutorial 06 thruster, `origin=lambda: …` reading the hero) is its own Entity: destroying the hero leaves it burning where the hero died. The owner destroys it in `on_destroy` (`self.propulsor.destroy()`).
- **Every look parameter is writable after birth**, with the constructor's resolution: `color` is a property that runs `resolve_rgb` (a name, hex, `Color`, a tuple). `Jet` / `Sparks` / `Starburst` / `Rain` once kept `color` as a raw field, so `jet.color = "cyan"` stored the string and the next draw raised (2026-10-09). A new kind with `color=` gets the property; `TestColorWriteAfterBirth` walks every kind whose constructor takes `color=`.
- Quality: `particle_scale(FxQuality)` steps density (reuses quality ladder; no new public scale).

Tests: `tests/test_spatial_fx.py`, ownership edge cases in `tests/test_process.py`. Visual: `python scripts/smoke/spatial.py`, `python scripts/smoke/spatial.py`.

### 3.1e BackgroundFields (`scena/background.py`, `scena/background_kinds.py`)

**Pre-scene full-screen procedural fields** with explicit pan / zoom response.
Sibling of `canvas.effects` for stack ergonomics, but drawn **after** wallpaper
and **before** the camera + scene. Not shape layers, not post FX, not SpatialFx.

#### Why not a giant Shape for infinite fields?

BackgroundFields answer a *different* problem than Parallax Layers (§3.1f). Infinite
procedural fields still do not belong as shapes:


| Blocker            | Why a huge low-z Shape fails for infinite fields                   |
| ------------------ | ------------------------------------------------------------------ |
| Infinite coverage  | Shapes are finite; infinite scroll needs author tiling boilerplate |
| Cost               | Screen-covering shape is the anti-pattern for filter-batch RTs     |
| No identity needed | A procedural sky has no hit-test / formulas / groups               |


Partial camera response for **finite author content** is solved by Parallax
Layers (shared knobs vocabulary; real affine matrix, not SkSL UVs).

#### Camera response / scroll

Stack attachment and camera rest-look: [Canvas Design.md — Background engine](Canvas%20Design.md#background-engine).
Field UV uses `parallax_transform` / `BackgroundField._parallax_uv` (device-pixel
offsets from look delta vs rest). **Author `scroll`** (`scroll=(x, y)`, one
spelling — no per-axis `scroll_x` / `scroll_y`) lives on every field: design
units/sec (y-up), independent of camera. The per-frame integrator
(`_advance_scroll`) and constructor helper (`_apply_scroll_arg`) are engine hooks.
Plasma defaults to `speed=0`. Tunnels: prefer `speed`; `scroll` still shifts if set.

#### Inventory (high quality only)


| Class              | Role                                                                         | Default `pan_response` notes |
| ------------------ | ---------------------------------------------------------------------------- | ---------------------- |
| **SkyGradient**    | Full-frame vertical gradient base (`horizon=` atmosphere line, y-up 0–1 from bottom; pair with `Ground`). Scenic presets = `SCENIC_PRESET_NAMES` (day, dawn, sunset, dusk, night, space, overcast, desert, forest, toxic, ember, ice, underwater), each a ramp in `GRADIENT_PRESETS` (tested); `_SKY_ALIASES` map onto them; any other preset or a color also works | 0                      |
| **Clouds**         | Fbm cloud deck                                                               | ~0.08                  |
| **Stars**          | Transparent starfield (≠ SpatialFx `Star`)                                   | ~0.02                  |
| **Stardust**       | Soft two-colour space dust wash                                              | ~0.08                  |
| **Chromadust**     | Stardust density with rotating rainbow / gradient palette; `reflect` yoyos the ramp | ~0.08                  |
| **Nebuladust**     | Stardust density with a few large colour lobes (≠ `Nebula` ribbons)          | ~0.08                  |
| **Borealis**       | Ribbon curtains; `height` vertical reach (≠ Recipe `Aurora`)                 | ~0.1                   |
| **Plasma**         | Colour wash (≠ shape `GearShell`)                                            | ~0.3                   |
| **Mist**           | Soft fog band (≠ post `Haze`)                                                | ~0.2                   |
| **Debris**         | Scrap flecks                                                                 | mid                    |
| **Embers**         | Rising ash (irregular placement). Defaults density 1.1 / alpha 0.95; each ember a hot core + soft halo, dim ones glow the ember color (they were near-black red 1–2 px dots: `test_background.TestEmbersDefaultIsVisible`) | mid                    |
| **WindStreaks**    | Head-bright motion trails + glow; `angle` degrees                            | high                   |
| **Ground**         | Orthographic strip (scene base; `fade=` horizon blend)                       | ~0.9                   |
| **Lattice**        | Soft geometric DSL (`fold` × `edge` × `layers`)                              | ~0.25                  |
| **Nebula**         | Broad ribbon bands                                                           | ~0.06                  |
| **ChurningClouds** | Warp-phase space clouds; 2-octave FBM on `res_scale` plate (default 0.4)     | ~0.06                  |
| **FilamentField**  | Ridged filaments + hotspot; 2-octave on `res_scale` plate (default 0.5)      | ~0.18                  |
| **Road**           | Mode7 floor, **horizontal-only** scroll                                      | ~0.85                  |
| **Floor**          | Mode7 drive ground / horizon (AA grid)                                       | 0                      |
| **Tunnel**         | Radial star streak fly-through. `center=` vanishing point (design space; `None` = screen center). `pan_response` opt-in banks that point | 0                      |
| **StarFly**        | Point-star fly-through (5 planes, cheap ALU). Same `center=` / pan-as-bank as Tunnel | 0                      |
| **PlanetFly**      | Curved limb; `roll="into"` (default) or `"side"`                             | 0                      |
| **PlanetFly**      | Alias → `PlanetFly(roll="into")`                                             | 0                      |


Do not resurrect all-in-one `Sky` or celestial discs as wallpaper (`Sun` / `Moon`
→ SpatialFx `Orb` on a parallax layer): composition stays author-owned — a scene
is a sky, a ground and orbs the author places, not one preset that decides all three
([Scena Design — Product principles](Scena%20Design.md#product-principles)).

**Road:** force UV offset Y = 0 (vertical pan and vertical `scroll` ignored).

**Tunnel / StarFly:** `center=` is the authored vanishing point in design space (`None` = screen center at the camera rest look). Mapped to the framebuffer as a framing offset — not camera-projected. `pan_response` (default 0) is an opt-in **bank** of that point (Star Fox / hyperspace steer), not wallpaper parallax. Prefer `speed` for into-screen motion. World-space vortex: `Warp`; energy ring: `Portal`.

#### Deferred

Backgrounds: medium/low algorithmic LOD.

#### Lifecycle / cost

- Empty stack: free (bool check only); never forces scene RT alone.
- N stacked background fields ≈ N full-screen SkSL passes (~same class as canvas SkSL post).
- Image `Wallpaper`: decode once per file (at construct, or at window open when built before `run()`); swaps / resizes reuse the GPU texture. Mechanism + fences: [Canvas Design.md — Background engine](Canvas%20Design.md#background-engine).
- Compile-once builders in `scena/_sksl_backdrop.py` (tunnels + placed Warp disc) and `scena/_sksl_ambient.py` / `scena/_sksl_ambient_kit.py` (ambient washes).
- Stack API: `add` / `remove` / `clear` / `set_fly` (`canvas.set_fly` sugar).
- All look knobs are ordinary public attributes (constructor **and** live mutation).

Tests: `tests/test_background.py`. Visual proof only: `scripts/smoke/background.py`.

### 3.1f Parallax Layers

Architecture (invariant, knobs, draw path): [Canvas Design.md — Parallax layers](Canvas%20Design.md#parallax-layers-decoration-only).

**Cost only:** zero non-neutral layers → one flag (`_layer_ctm_swaps == 0`).
Non-neutral layers skip `cull_offscreen` (global `visible_bounds` is wrong under
a partial CTM). Do not put interactive / collidable bodies on them.

### 3.2 Canvas post effects — categories

Author split (Guia): **Post** (`#mundo-post`) is what lives in `canvas.effects`
— a look you add, tweak, hide, remove (fixed / animated / light below).
**Impactos** (`#mundo-impactos`) are the one-shot `canvas` verbs that fire and
decay on their own: whole screen (`flash`, `shake`, `glitch`), at a place
(`*_at`), cover (`fade_out` / `fade_in`). The question an author starts from is
"a look that lasts" vs "an event", not "whole screen" vs "a point". Sibling
catalogs: Transientes (one-shot *on an actor*), SpatialFx (*lasts* at a place).
Guard: `test_api_robustness.TestGuiaMatchesCode.test_post_is_the_stack_and_impactos_the_one_shot_verbs`.
The impacts draw through an internal `HitFeedback` post kept in the same
list (`PostFxStack._hit`); the author views (`list(canvas.effects)`, `len`,
iteration) skip it, so an impact never shows in the stack and an act restore
does not hand it back (AC3; `test_postfx.TestPostFxStack.test_impacts_never_join_the_authors_stack`).



#### Fixed look (params steady; re-composited every frame while on stack)


| Effect           | Scena    | Mechanism                                                    | Quality-sensitive |
| ---------------- | -------- | ------------------------------------------------------------ | ----------------- |
| **Vignette**     | OVERLAY  | Corner darkening × Multiply (sharp center)                   | no                |
| **Grain**        | OVERLAY  | Tiled noise × Plus                                           | no                |
| **Fog**          | OVERLAY  | Bottom-weighted atmospheric wash                             | yes               |
| **Bloom**        | ADDITIVE | Bright-extract + Blur + Plus                                 | yes               |
| **Grade**        | COLOR    | ColorFilter matrix (presets + b/c/s)                         | no                |
| **Chroma**       | SHADER   | Horizontal RGB split (SkSL)                                  | no                |
| **Pixelate**     | FILTER   | Nearest down/up scale                                        | yes               |
| **Scanlines**    | OVERLAY  | Nearest-tiled Multiply bands; low-res when quality-sensitive | yes               |
| **ScreenBlur**   | FILTER   | Whole-scene Gaussian                                         | yes               |
| **DistantLight** | SHADER   | Parallel sun + luma normals                                  | no                |
| **Wash**         | COLOR    | ColorFilter lerp toward `color` (default white)              | no                |


`Grade` presets: `filmic`, `cool`, `warm`, `sepia`, `bw`, `duo`, `night` (defaults are intentionally visible).

#### Continuous animation (per-frame time / mouse / feedback)


| Effect           | Scena  | Mechanism                                             | Notes                                                          |
| ---------------- | ------ | ----------------------------------------------------- | -------------------------------------------------------------- |
| **Haze**         | SHADER | Mean-zero UV shimmer                                  | `kind="haze"                                                   |
| **Crt**          | SHADER | Scanlines (quality plate) then barrel→chroma→vignette | `amount`, `chroma`, `scan`                                     |
| **Vortex**       | SHADER | Swirl into a point                                    | `target=None` → mouse                                          |
| **ZoomBlur**     | SHADER | Radial streak toward point                            | `center=None` → mouse                                          |
| **Kaleidoscope** | SHADER | Radial mirror wedges                                  | `segments`, `zoom`, `spin`                                     |
| **Prism**        | SHADER | Rotating RGB split                                    | default `amount=0.004`                                         |
| **Perspective**  | SHADER | Fake tilt UV                                          | `target=None` → mouse                                          |
| **Lamp**         | SHADER | Omni point + specular                                 | range + radius; mouse by default                               |
| **Spotlight**    | SHADER | Cone light + **range** cut-off                        | origin + aim (mouse)                                           |
| **GodRays**      | SHADER | 8-tap brightness shafts, Plus                         | Defaults 0.08 / 0.9 / 0.8 (2026-10-23; 0.35 / 0.86 / 1.8 washed the picture out). The 8 taps span the whole way to the light, so a strong ray repeats bright objects as copies ("ghosting"); more taps or a shorter march is a look change, not done |
| **MotionTrail**  | SHADER | Past-frame afterimage; `fade` @ 60 Hz                 | residual-free (static → identity); crisp movers; mute / survival drops both ping-pong RTs |
| **ColorSweep**   | SHADER | Spatial color-grade + sat/hue; 2–4 colors             | `axis="radial"                                                 |
| **ColorWash**    | SHADER | Dancing plasma colorize of the scene                  | 2–3 colors; ≠ background `Plasma`                              |
| **CosmicBloom**  | SHADER | Churning nebula grade + 4-tap glare                   | `color` / `color2`, `bloom`; default `speed=1.2`, `amount=1.0` |




#### Transient (triggered, then decays)


| Effect          | Scena  | Mechanism                                                                               | API                                                                 |
| --------------- | ------ | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **HitFeedback** | SHADER | SkSL radial/linear warp + flash; FB shake; SkSL glitch; explosion / burst / bubbles / fireworks / zap / hit / debris overlay | `canvas.flash/shake/glitch/ripple_at/wave_at/explosion_at/burst_at/bubbles_at/fireworks_at/zap_at/hit_at/debris_at` |


#### Cover (hold until uncover; not post, not a hit)

Drawn **after widgets** on the window FB — covers HUD. Does **not** pay the scene RT. One overlay; `style=` picks the look. `on_done` is the call channel (arity-truncated, payload `(canvas,)`). No `then=` (canvas is not an Entity).


| Method | Default | Notes |
| ------ | ------- | ----- |
| `canvas.fade_out(duration=0.5, color="black", style="fade", angle=0, center=, on_done=)` | black, `style="fade"` | Tween cover 0→1 and **hold**. `style`: `fade` · `wipe` · `iris`. `angle` wipe axis (degrees, 0 = +x). `center` iris only: any point-like, snapshotted (omit = frame center). Duration `0` is instant. |
| `canvas.fade_in(...)` | keep current look | Tween 1→0. If already uncovered, snap to full cover first (opening fade). Omit `color`/`style` to keep the hold's look. |
| `canvas.covered` | `0…1` | Read-only amount. `1` after `fade_out` until `fade_in`. |


Replace-in-channel: a second `fade_out` / `fade_in` drops the in-flight tween and fires its `on_done` (same as shape transients). Sticky bleach is still `Wash()`; hits are still `canvas.flash`.

- `canvas.flash(intensity=0.6)` — whiteout peak (0–1). Sticky bleach is `Wash()`, not a pulse.
- `canvas.shake(amount=10)` — camera jitter (design pixels).
- `canvas.glitch(amount=1.0)` — slice offsets + RGB split spike (0–1).
- `ripple_at` — radial screen-warp + ring + shake; `amount` = warp/shake magnitude; `radius` = peak design-unit size (`None` = full-frame); `shock=True` (accent ring; warp still runs when off); `shake=True`; `flash=False` by default. Locus: `(x, y)` or one point-like (`info.point`, Graphic, …); `None` is a no-op.
- `wave_at(x, y, angle=0)` — linear shockwave; same locus grammar; `shock=True` (accent band; warp still runs when off); `shake=True`; `flash=False` by default.
- `explosion_at(..., shock=True, flash=False, rings=True)` — cinematic fireball + smoke; mild warp when `shock` (radius ~2/5 of `ripple_at`); camera shake; `flash` toggles whiteout; `rings` draws expanding stroke circles. (one big event + share the burst pool). Same locus grammar.
- `burst_at(x, y, radius=42, amount=1.2, rings=False)` — local multi-instance pyro only (design-unit radius); no shake/flash/shock. Prefer for ship deaths etc. Same locus grammar (`burst_at(ship)`). Neither `burst_at` nor `explosion_at` has a `recipe=` any more: its `"flash"` disc-only pop was retired when `hit_at` landed; the disc now lives on as `hit_at(style="disc")` ([Fences](Fences.md)).
- `fireworks_at(x, y, color=, color2=, radius=64, amount=1, count=28, fall=0, trail=0.35)` — celebration burst of stars at a point (no mortar, no shake/flash/shock). Distinct from `burst_at` (fireball) and SpatialFx `Sparks` (sticky). `fall=0` (default) peony; `~1.2` willow. `color2=None` derives near-white glitter from `color`. Pool ~24, auto-decays. Same locus grammar.
- `zap_at(x, y, color=, radius=24, amount=1, count=, style="spark", flash=False)` — electric spark / lightning flash at a point (bright core + jagged rays). Between Bolt(tesla) and ElectricBolt. Styles: `spark` (impact bloom + short rays), `fork` (branched tesla bolts), `corona` (expanding jagged ring). Soft bloom uses GlowSpot soft-disc stamps at medium/high (concentric ADD discs at low); bolt strokes follow CheapGlow dual-ADD at medium and MaskFilter soft-band + sharp core at high. No shake/shock; optional `flash` whiteout. Distinct from SpatialFx `Sparks`. Pool ~24, auto-decays. Same locus grammar.
- `hit_at(x, y, color=, angle=None, radius=16, amount=1, count=None, style="star")` — impact mark: something was struck **and lives on** (hero / boss taking a shot). White-hot four-point star (holds full size ~2 frames, then shrinks) over a soft tinted glow, a thin crisp ring, and short spark streaks cooling from white to `color` (default warm white); ~0.2 s. `angle` (world degrees, y-up: 90 = up) aims the sparks in a ~100° cone and stretches the star arm along it; `None` sprays all around. Plus blend (emissive). No shake / flash / warp. Pool 64 (a boss under a stream of shots). Not `zap_at` (electric, jagged, bloom-heavy) and not `burst_at` (fire). Same locus grammar. `count` omitted = 8 sparks (3–24, scaled by quality); `count=0` keeps the star and ring with **no** sparks, and quality never adds them back. **`style="disc"`** is the light version: a round pop of light — a tinted radial disc opening to ~1.6 × `radius` (the star's sparks reach ~2 ×) over a soft white-hot core, same lifetime and pool as the star. It has no sparks and no direction, so `angle=` / `count=` with it raise `ValueError` instead of being ignored (`_hit_spec`, shared by the canvas verb and the engine, checked before the `None`-locus return). It draws at every quality: survival swaps the gradients for two concentric ADD discs (`zap_at`'s LOW recipe) faded faster so no flat plate lingers. `style` is a strict choice (`"star"` / `"disc"`, any case, no aliases). Guards: `test_hit_at_disc_is_a_round_pop_at_every_quality`, `test_hit_at_count_zero_keeps_star_without_sparks`, `test_hit_at_rejects_bad_knobs`. **The angle is never read from `info`:** `CollisionInfo.normal` points from `a` toward `b`, so `@collide("shot", "hero")` and `@collide("hero", "shot")` would spray opposite ways ([Fences](Fences.md)). World angle → FB goes through the camera turn and the y flip in `_remap_overlays` (guard: `test_hit_at_angle_points_up_on_screen`).
- `debris_at(x, y, color=, radius=40, amount=1, count=14, fall=0, dust=True)` — matte debris: it broke into pieces, **no fire**. Irregular 3–5-gon shards (sizes skewed small, a few big; big ones slower) fly out with drag, tumble (fake light: brightness follows the turn), then shrink and fade over the last 40 % of their life; optional soft dust puffs (skipped at survival / low). **SrcOver, not Plus** — readable on bright backgrounds, the visual difference from pyro (guard: `test_debris_is_matte_not_emissive`). `amount` is force (reach); `fall` is the same knob as `fireworks_at` (`0` drifts, `~1` arcs down). Pieces are paint only: no collision. The color is never read from a Graphic locus (its fill may be a Gradient / Texture, and `debris_at(ship)` would differ from `debris_at(ship.center)`). Pool 16, 0.7–1.4 s. Chain with `burst_at` (ship blows apart) or `hit_at` (rock cracks). Same locus grammar.
- `bubbles_at(x, y, color=, count=, height=)` / `bubbles(color=…)` — rising foam bubbles that fade/pop (canvas-wide transient). `bubbles_at` uses the same locus grammar.

**`*_at` locus (author surface on `canvas`, not HitFeedback internals):** two numbers, or one of `(x, y)` / Point / Vec2 / Graphic (`.center`) / `CollisionInfo` / `TouchingContact` (`.point`). `None` and exit `info.point` skip (return `canvas`). After a point-like, remaining knobs are keywords (`amount=`, `radius=`). `move_to(None)` still errors — only this hit family no-ops.

**Out of scope (for now):** Multi-Lamp, canvas Magnet/Bleed, CPU DisplacementMap warps.

### 3.3 Lighting roles (canvas)


| Class            | Geometry                                                         |
| ---------------- | ---------------------------------------------------------------- |
| **Lamp**         | Omnidirectional bubble + Lambert/specular (luma normals)         |
| **Spotlight**    | Cone from origin → aim; soft-hard stop at `range` (design units) |
| **DistantLight** | Parallel “sun” rays; no distance falloff                         |


Authors never write SkSL. Sources live in `scena/_sksl_effects.py` (compile-once at import).

---



## 4. Quality system (`FxQuality`)

Fidelity and presentation rate are **orthogonal**. Shipping ladder:


| Level              | Recipe tier | `post_fx_scale` | `shape_fx_scale` | batch   | Particles | Intent                                                                                                   |
| ------------------ | ----------- | --------------- | ---------------- | ------- | --------- | -------------------------------------------------------------------------------------------------------- |
| **high**           | HIGH        | 0.5             | 1.0              | on      | 1.0       | **Product default** — full multipass                                                                     |
| **medium** (`med`) | MED         | 0.5             | 1.0              | on      | 0.75      | Same costume family; **lite** multipass / SpatialFx                                                      |
| **low**            | LOW         | 0.25            | 1.0              | on      | 0.5       | **Survival** — distinct cheaper algorithms (shape filters full res; half-res multi-batch was a net loss) |
| **max**            | HIGH        | 1.0             | 1.0              | **off** | 1.0       | Diagnostic / strict z-order                                                                              |


`canvas.fx_quality = …` calls `activate_quality` once: updates draw-path module slots (`fidelity_tier()`, `hero_fx_lod()`, `particle_scale()`) plus canvas scales/batch. Hot path is O(1) loads — no framework/`_from_value` per stroke.

**Tiers (algorithmic):**

- **HIGH** — full multipass (masks, hot rims, full shells).
- **MED** — promoted former low LODs (fewer passes, no MaskFilter, drop hot cores, SpatialFx soft beds). **Exception:** ElectricField uses the high GlowRim package (same `speed` as high; not the old Discrete-PE + MaskFilter lite). **Rim** uses GlowRim at every quality (no lite substitute).
- **LOW** — survival substitutes where needed (Laser body+core; InkBleed hard stroke; GearShell Line-style dashes (no sweep); ElectricField Recipe ladder; Shield solid+rim). **Glow** keeps batched GlowFilter; **CheapGlow** stays filterless ADD. **Shadow** is omitted. **Rim** keeps GlowRim. Cheap quality-flat effects stay untouched.

No public `*Low` classes. Prefer compiled `Glow` **/** `Halo(style="soft")` **/** `Shield` for fleets; **Shape** `Halo` **/** `Halo(style="fill")` **/** `ElectricField` **(med/high) / Bolt high / ElectricBolt high / Rim** batch interned Blur then deferred rims. Shape Halo/Halo(style="fill") **medium** is a cheap solo ADD outline (no FX RT). **Sprite** Halo/Laser/Rim use FrameFx SDF at all qualities.

`hero_fx_lod`**:** shared multipass budget (`passes`, `mask`, `pe_hz`) for Neon / Laser / ElectricBolt lite / peers that still call `_pe_seed()` with the quality cap. Cached `HeroLod` NamedTuple on the slot. **ElectricField** GlowRim overlay does **not** cap on `pe_hz` — medium and high flicker at `speed` (`1.0` ≈ old 14 Hz).

### Render profiles (Ctrl+Shift+3)


| Profile | Quality | batch |
| ------- | ------- | ----- |
| low     | low     | True  |
| medium  | medium  | True  |
| high    | high    | True  |


`max` remains an API quality (`canvas.fx_quality = "max"`) but is not on the product cycle.

### Auto policy (`set_fx_auto`)

Third policy over the same two axes. **Default on** — starts at high@60. When disabled, the frame path pays only one bool check (no EMA, no controller).


| Concern          | Behavior                                                                                                                                                                                                                                        |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Metric           | CPU **work_ms** (frame start → after `flushAndSubmit`, *before* present wait) and its **draw share** (`_draw_frame` + `flushAndSubmit`; the rest is **simulation**: clock, input, update, processes, collision, flush), fed after the present together with the pacer's **slip** flag and **present overhead**. Period median + EMA for both (`ema_ms`, `sim_ema_ms`; HUD `work:…/…ms sim:…ms`) |
| Net budget       | `interval × period − present overhead` (`net_budget_ms`, floor ½ frame). Overhead = median swap cost after the pacer's wait (`FramePacer.present_overhead`: ~2–3 ms on macOS GL, where the next frame starts only when the flush returns); 0 under native VSync, where the swap time is mostly the vblank block and its after-vblank return cannot be seen. Down / up lines are fractions of the net budget |
| Slips            | A present later than its slot by > ½ vblank (`FramePacer.last_slipped`); an **overrun** (`last_overran`, what FX Auto counts) when the frame itself did not fit — the pacer waking late (App Nap, a busy scheduler) is excused. Catches GPU-bound frames and native-VSync lag. Overload = rate > 10 % over the last 5 evals **and** in the latest one; a climb needs ≤ 1.5 %. A slip-driven step that cut the rate by < 20 % marks the slips external for 30 s (`AutoParams.slip_*`, `external_slip_hold_s`) |
| Ladder           | high@60 → **medium**@60 → **low**@60 → low@30 — hold 60 as long as possible; 30 is last-resort survival. Rate rungs that keep fidelity for a sim-bound frame: **high@30**, **medium@30** (`build_rungs`: indices 4, 5 after the ladder's 0–3). Every rung **display-locked**: the three 60 rungs apply `canvas.framerate = "vsync60"` (vblank divisor nearest 60 Hz; 144 Hz → 72), the survival rung `"vsync30"` (twice that interval). `Rung.framerate` / `Rung.interval`; `present_hz` / budget = the real locked rate |
| Why locked       | A free fixed-60 timer beats against the display (judder bursts; see Scena Design, Frame pacing and GC). The pacer implements the interval on every OS (native swap interval, macOS display link), so the old reason for a fixed timer (macOS ignores `swap_interval > 1`) is gone               |
| Sim-bound        | A down step goes by **rate at the same fidelity** (high@60 → high@30, medium@60 → medium@30) when (a) simulation is ≥ `sim_share_min` (½) of the work — measured, so a draw-heavy scene keeps the fidelity-first ladder whatever the prediction says — and (b) even the cheapest fidelity at this rate is predicted over the down line: `sim + draw / Π draw ratios` of the steps left to low (`lowest_fidelity_ms`). It needs sustained **overruns** too: a frame over the line that still fits keeps 60 (holds). At 30 a sim-bound frame holds (nothing below helps). Draw ratio per step: learned from fidelity steps (`draw before / draw after`, keyed by the fidelity landed on); an unlearned step borrows the mean of this scene's learned ones; prior `draw_cost_ratio` 1.35 (optimistic: costs at most one rung). The 30 row steps fidelity within the row when the frame is draw-bound there (high@30 → medium@30 → low@30) and climbs by **rate only** (F@30 → F@60); a work cost ratio is learned only from the step its climb reverses. No draw share (`note_work_ms(work, slipped)`) = all draw: the old ladder exactly |
| Never            | `max` / batch-off / uncapped                                                                                                                                                                                                                    |
| Hysteresis       | Down on a sustained problem: period **median** work (not mean — spikes / stalls ignored) > `k_down` × net budget, or overruns, for **2 s** (two evals). **Up on a prediction:** next rung's work = current × a **cost ratio learned from past steps** (prior 1.35 fidelity, 1.0 rate); climb when it fits in 0.70 (→ high) / 0.75 (→ medium) / 0.80 (30 → 60) of that rung's net budget, few overruns, for 18 / 15 / 12 s. Cooldowns 1.2 s down / 6 s up, EMA reset + 2 settle evals after a step; failed climb (down within 30 s of an up) locks climbs 15 s, doubling to 120 s, reset by a climb that holds; ~2 s startup warmup. Old rule (climb only if *current* work < ~⅓ budget) was unreachable for a scene that fits, so Auto never recovered |
| Manual           | `canvas.fx_quality` / Ctrl+Shift+3 / `canvas.framerate` / Ctrl+Shift+4 **disable** Auto                                                                                                                                                         |
| Toggle           | `set_fx_auto(True                                                                                                                                                                                                                               |
| HUD              | When Auto on: `FPS: measured/target` plus `auto:medium@60`                                                                                                                                                                                      |
| Stress lab       | `scripts/bench/fx_auto.py` (heavy looks, plain Python motion — no reactive-graph load)                                                                                                                                                     |
| Stress scenarios | `--scenario ramp_up                                                                                                                                                                                                                             |
| Auto eval        | `scripts/tools/eval_fx_auto.py` (CSV → oscillation / FPS-vs-target) · `scripts/tools/run_fx_auto_eval.py` (battery)                                                                                                                                         |


Benches / visual matrix **must** turn Auto off (`set_fx_auto(False)`) and usually uncap with `canvas.framerate = "max"` so the ladder cannot move quality/rate mid-measure.

**Rationale (hold 60):** interactive motion and input feel degrade more from 60→30 than from medium→low look. Auto spends fidelity first (`high` → `medium` → `low` at 60 Hz) and only then drops present to 30 as survival. Product targets stay **60 fps** on balanced hardware, **30 fps** minimum.

**Rationale (sim-bound keeps its look):** fidelity only buys back draw time. When game logic is most of the frame, `high` → `medium` → `low` at 60 cannot make the frame fit; it costs the look and still ends at 30. Measured 2026-10-21: `examples/constelacao.py` at 818072e in a real window on a 60 Hz display ran simulate 11.0 + draw 4.4 + submit 0.5 ms; on the total alone FX Auto walked high@60 → medium@60 → low@60 → low@30 within 15 s (48 fps average, p95 frame 34 ms). Draw + submit per quality on the same scene (machine at load ~70, `game_bench`): high 6.47, medium 6.09, low 5.43 ms (1.06 / 1.12 per step); festa (GPU-heavy bench game): 38.2 / 34.8 / 34.2 ms. With the split the same stream takes one step, high@60 → high@30 (`tests/test_fx_auto.py` `TestSimBound`, which also checks that draw-bound streams take the same steps with and without the split). Live check (2026-10-21, 28bef8c, real 60 Hz window, Constelação + 5 ms of busy work in `_simulate_frame`, 30 s): with the split, high@60 → high@30 at 4.2 s and held (sim 15.4 of 21.9 ms; 30.0 fps, p95 frame 33.5 ms); without it (total only), high → medium → low@60 → low@30 by 12.7 s (29.9 fps, p95 36.6, max 76 ms) while work stayed 21–23 ms on every rung. The share gate (½) keeps the prediction away from scenes where quality is the lever and the draw ratio is least known; requiring overruns keeps 60 for a frame that is over the margin but still fits — the margin was made for cheap fidelity steps, not for halving the rate.

Policy module: `[scena/fx_auto.py](../scena/fx_auto.py)`. Unit tests: `tests/test_fx_auto.py`.

---



## 5. Shape filter batching & cost model



### 5.1 When batching runs

Batching is controlled solely by `canvas.batch_shared_filters` (set by quality presets, overridable):

```text
if batch_shared_filters:
    group filtered shapes by batch_key
    one RT / saveLayer per key
else:
    per-shape paint ImageFilter (strict painter's order)
```


| Quality             | Batch default                          |
| ------------------- | -------------------------------------- |
| low / medium / high | **True**                               |
| max                 | **False** (reference / strict z-order) |


`shape_fx_scale` only changes filter RT resolution. It does **not** force batching.

`fx_quality="max"` (`batch_shared_filters=False`) is unchanged.

Single filtered shapes still use the low-res RT path when `shape_fx_scale < 1` and batch is off (via `_draw_fill_only` / `_draw_stroke_only`).

### 5.2 What one batch costs

Shapes with the same `_batch_key` (prefer **one shared filter instance**) become **one** filtered pass:

1. Union AABB of all shapes in the batch + `_batch_outset` (+ stroke pad).
2. Full-res `saveLayer` **or** low-res GPU RT sized to that AABB × `shape_fx_scale`, then upscale blit.
3. Re-draw each shape into the layer with filters stripped, then apply the ImageFilter DAG.


| Driver                                  | Dominates when…                       |
| --------------------------------------- | ------------------------------------- |
| **Union AABB area** (× scale)           | Filter fill-rate / blur intermediates |
| **Shape count N**                       | Geometry re-raster into the layer     |
| **Outset / σ**                          | Halo pad grows AABB + heavier blur    |
| **Number of distinct** `_batch_key`**s** | Separate passes (cost ≈ sum of each)  |


**Critical:** cost tracks the **union rectangle**, including empty space.  
Same glow, sprites **clustered** → small RT, cheap.  
Same glow, sprites **screen-wide** → near full-frame filter plate — expensive.

**Evidence** (`scripts/bench/perf_glow_fleet.py`, n=48 shared Glow, `fx_quality=high`, Retina FB ~2662×1864):

| layout | visual | fps | work_ms | present_ms | union_frac |
|--------|--------|----:|--------:|-----------:|-----------:|
| clustered | glow | ~1000 | ~1.0 | ~0.4 | ≈0.09 |
| sparse | glow | ~500 | ~2.0 | ~1.3 | ≈0.96 |

Sparse vs clustered (same Glow): **fps× ≈ 2**, almost all Δwork in **`present_ms`** (large saveLayer finishes on `swap_buffers`, not `flushAndSubmit`). Galaga fire-storm shows the same cliff in product form (~33 shared-Glow projectiles ≈127 FPS vs ~380 without Glow).

**`CheapGlow` on `.glow`** = filterless ADD strokes (same knobs as `Glow`, no
ImageFilter RT). Do not restore soft-plate CheapGlow or smart batch tiling. The
soft plate (a radial underlay) was faster on sparse fleets but read as a muddy disc.
Tiling a large empty union (2×2 / 4×4 plates) bought ~4% sparse FPS: the tiles still
covered about the union, and 4×4 hit a submit cliff. Draw-walk nos (image cache,
static decal): [§5.6 — Rejected](#56-recipe-draw-hot-path--lessons).

**CheapGlow draw cost (2026-10-20).** Each fill band (4) scaled the host about
its anchor and called `_geometry_draw`, and each band read the host's pose
twice (`_aura_anchor`, then the draw's own `_placement_params` /
`_oriented_frame`): 9 pose reads a shape per frame. The overlay now reads the
anchor once, draws the first band through `visuals._CanvasTape` (a canvas
stand-in that forwards and records each call) and replays the recorded calls
for the other bands; the bands differ only in the one Paint object, recoloured
between them, and the scale. Only kinds whose `_geometry_draw` comes from
`scena.shapes` (canvas calls only) use the tape (`_geometry_tape_ok`, cached
per class); Sprite / Svg / Track / Text, and an author override, draw each
band as before. A call the tape cannot replay (a keyword argument, a name
outside `_TAPE_VERBS`) turns it off for that overlay. Same pixels:
`tests/test_per_object_costs.py` (`TestCheapGlowBands`: every shape kind and a
stroke host, raster bytes with and without the tape; one `_geometry_draw` per
overlay). Overlay alone (recorded canvas, two trees): Triangle 18.8 → 12.6 µs,
Circle 16.4 → 11.1. In the frame, 120 rotating Triangles over a sky + Bloom,
draw phase: CheapGlow +2.8 → +2.0 ms, Glow +0.8 ms, `blend="add"` +0.0 ms. So on
this machine a sparse CheapGlow fleet still costs ~2.5× a Glow fleet on the
CPU (Glow's batch keeps one plate; its GPU union cost, §5.2, did not show
here); the "prefer CheapGlow on fleets" rule above rests on the GPU side.
Glow cost the same on static and rotating shapes (a cache lost on rotation
was suspected and not found).

**Half A / half B:** two shared keys → **two** passes over `union(A)` and `union(B)`, not one free multi-effect.  
Fill and line filters batch **separately**.

### 5.3 Author rules (shape)

```python
# GOOD — one look, one batch
GLOW = GlowFilter()
for s in ships:
    s.fill_filter = GLOW

# GOOD — fleet stamp on .glow (CheapGlow = filterless ADD; prefer on bolts / stings)
sting.glow = CheapGlow(color="tomato", radius=8)
ship.glow = Glow(color="skyblue", radius=14, sigma=7)  # heroes / few props
ship.glow = True  # sugar → Glow()

# BAD — unique instances / unique params → N batches (or N solitaires)
for s in ships:
    s.fill_filter = GlowFilter(radius=...)  # new object, may break sharing

# BAD — rebuild filter graph every frame
ship.fill_filter = GlowFilter(radius=10 + math.sin(t))
```

| | `Glow` | `CheapGlow` |
|--|--------|-------------|
| Assign | `.glow = Glow(...)` / sugar | `.glow = CheapGlow(...)` (no `.cheapglow`) |
| Pipeline | ImageFilter at all qualities | Filterless ADD strokes |
| `_fidelity_sensitive` | True | False |
| Typical use | Heroes, few props | Bolts, stings, coins, fleets |

Keep same-key fleets **spatially clustered** when possible. Use canvas Bloom / grade for whole-picture atmosphere — not screen-wide shape Glow on every projectile. Filters bake Skia `ImageFilter` graphs at **construct** time; there is no “mutate σ in place.” Prefer discrete presets, or throttle rebuilds.

### 5.4 Shape vs canvas — why shape can cost ~2× a “full-screen” post FX

A near-window AABB shape filter is **not** the same as canvas ScreenBlur/SkSL of the full frame:


|                | Shape ImageFilter                                                  | Canvas post                          |
| -------------- | ------------------------------------------------------------------ | ------------------------------------ |
| Input          | Re-rasterized shape geometry into transparent layer                | Ready `scene_image`                  |
| Geometry       | Paid **again** for filtered shapes                                 | Already in snapshot                  |
| Typical kernel | Multi-node DAG (esp. GlowFilter: colourise + scale + blur + Merge) | Single Blur / matrix / one SkSL pass |
| RT size        | Union AABB (can thrash when bounds animate)                        | Stable `fb × post_fx_scale`          |
| Product role   | Local look, z-ordered with shapes                                  | Whole-frame look                     |


**Conclusions for development:**

- The gap is mostly **pipeline**, not “GPU blur is slower for shapes.”
- Window-wide shared shape glow is often a **bad** author pattern; use canvas Bloom / grade for whole-picture looks. Prefer **`CheapGlow`** on projectiles; keep same-key fleets **clustered** when possible (§5.2–5.3).
- Suspected avoidable costs to investigate: **RT recreate on every AABB size change**, paint dirty thrash when strip-filters in batch, GlowFilter DAG vs simpler DropShadowOnly if visuals allow. Large-batch tiling and soft-plate CheapGlow were **tried and rejected** (§5.2).

### 5.5 Changing the effect system without regressing hot paths

Looks share filters (`HostGlow` / `GlowFilter` intern), one `saveLayer` / RT per `_batch_key`, and dest AABBs that were sized for Shape geometry. A Sprite-only visual bug (costume larger than the bitmap) is easy to “fix” by growing every Sprite box or by putting `_domain_aabb` on `Sprite`. That tax hits Glow fleets, HaloLine batches that share interned HostGlow with `Shield(style="bands")`, and `_plain_blit` cull. Do the due diligence below **before** editing shared paint / filter / AABB code.

**What must not move** (measure before changing the function, not after):


| Path | Why it is hot | Safe if… |
| --- | --- | --- |
| `_plain_blit` | Mass shots skip the effect envelope | `_approx_draw_aabb` stays dest/geometry; no `Sprite._domain_aabb()` (cull still runs for plain blits). Do **not** clear `_plain_blit` for `.blend` ≠ NORMAL or `Sprite.alpha` ≠ 1.0 — those bake into `_blit_paint` at set-time (same family as static HueShift) |
| Filter batch union AABB | GPU cost **is** the union rectangle × blur (§5.2) | Other looks keep today’s dest + `_batch_outset`. Expand a box only when dest+outset **clips source geometry** |
| Interned `HostGlow` / `GlowFilter` | Same `_batch_key` → one plate | Do not grow AABBs for looks that already fit; check intern keys for accidental sharing (`Shield(style="bands")` == `Halo(style="line")` HostGlow) |
| `_ensure_shield_envelope` / FrameFx bake | Walks sheet frames | Per-frame work is a cache hit after `.visual =`. Do not rebake in `_layer_bounds_for` |
| `_uses_shield_envelope` / `to_skia_fill_paint` ProceduralFill | Shared paint path for Shape **and** Sprite | Predicate must require the **host capability** (`_shield_envelope_half`), not only `.visual is Shield` — see lesson below |
| Shape `_geometry_draw` / `Shield._apply` / SkSL / `filters.py` | Shared by Shape and Sprite | Sprite-only clip → canvas AABB gate, not a shader or filter change |
| Host geometry reads in looks / bounds / paint (`_aura_anchor`, `shape_pivot`, `_host_radius`, `_local_half_extents`, `_approx_draw_aabb`) | Run per host per frame; a cold Derivate wake makes that host's **motion** pay `mark_dirty` forever | Read Defining geometry (`_segment_xy` / `_center_xy` / `_oriented_frame`), never `shape.center` / `.width` / `.length` first — see lesson below |

**AABB rule (Shield on Sprite, 2026-09):** `_approx_draw_aabb` is dest-only. `_layer_bounds_for` and cull call `_expand_aabb_for_shield_oval`: union dest with the costume oval **only when** dest padded by this layer’s `outset` does not already contain the oval. Vortex HostGlow (~5 DU pad) must grow; GlowFilter bubble/nebula/molten (~50) and bands HostGlow (~15) stay identical. Shape Shield has no envelope method — no-op. Tests: `tests/test_sprite.py` (`TestShieldFilterBounds`).

**Lesson — Sprite-only helpers on a shared paint path (Shape Shield empty interiors, 2026-09):**

`PaintState.to_skia_fill_paint` maps ProceduralFill UV via `_procedural_shader(half)`. Sprite Shield needs the costume envelope half; Shape Shield needs `_center_radius`. A helper keyed **only** on `type(visual).__name__ == "Shield"` returned True for Circles, then `self._shield_envelope_half()` raised `AttributeError`, and a bare `except Exception` silently fell back to `ProceduralFill.tick()` (fixed `_PROC_FILL_RES=96`, and historically no `_extra_rgb` uniforms). Symptom: bubble/nebula “mostly empty interiors” on Shape fleets — **not** a Recipe draw / filter-batch regression. Do not revert §5.6 Cluster A/B wins to chase this.

Rules that prevent a repeat:

1. **Host capability before visual type.** `_uses_shield_envelope` requires `callable(getattr(shape, "_shield_envelope_half", None))` *and* a Shield/plasma visual. Visual-only predicates are wrong for anything Shape and Sprite share.
2. **Do not swallow `AttributeError` on the paint path.** Capability mismatches must fail loud; last-resort `_tick()` is for RuntimeEffect/uniform failures, not missing Sprite methods.
3. **Last-resort `_tick()` must still write multi-stop palettes** (`_extra_rgb` → `u_deep` / `u_mid` / `u_star` / `u_shell`) so a degraded path is mis-scaled, not black.
4. **Regression tests at small Shape radii** (`r≈12–18`, not only lab `r≈36`). Sample disc brightness, not one center pixel — hollow rims can pass a center check by luck.
5. When a look “broke after a Recipe hot-path campaign,” **check shared paint / envelope helpers first** before touching `_stroke_paint`, look-pass grouping, or overlay-glow batch.

Tests: `tests/test_visuals.py` (`test_shield_shape_not_sprite_envelope`), `tests/test_sprite.py` (`test_plasma_uses_envelope` Shape false branch).

**Lesson — look helpers waking cold Derivates (shape_fx FPS drop after cycling visuals, 2026-09):**

After every shape visual had been shown once and the smoke was back at none/none, idle frame time stayed ~+0.25 ms (~715 → ~610 fps) with **no** leftover visuals, filters, stamps, transients or post stack, and flat memory. Canvas post FX were clean. Cause: `_aura_anchor`, `shape_pivot`, `_approx_draw_aabb` (filter-batch bounds), `CheapGlow._host_radius` and `_local_half_extents` read `shape.center` / `.width` / `.length`. On Line and Square those are cold Derivates; the first read materialized them and permanently flagged the host pull-live, so the smoke's per-frame `move_to` / `rotate_by` left the A1 fast path. It is not an FX leak: the cost lands in **motion**, after the look is gone.

Rules that prevent a repeat:

1. **Geometry for drawing comes from Defining parts.** Use `_segment_xy()` (Line), `_center_xy()` (Shape), `_oriented_frame()` (Rect / Square / Ellipse; gate on `_defining_part_names` so Sprite's scaled frame is not used). `getattr(shape, "center")` is the fallback for other hosts only. Rule and helper list: [Reactive Design.md — Engine readers stay cold](Reactive%20Design.md).
2. **A leak check must measure idle cost, not only inventory.** Return to none/none, compare idle frame time / `cpu_ms_per_frame` against a pre-cycle baseline, and profile call counts (`mark_dirty`, `_move_by_batched`). Graph node count is a quick tell: +1 set of nodes per woken host.
3. **Test in the fleet the smoke uses.** Lines and Squares in motion expose wakes that Circles (Defining `center`) hide.

Test: `tests/test_pose_fast_path.py` (`TestDrawHelpersKeepDerivatesCold`).

**Lesson — `Paint.setShader` copies image shaders (wallpaper swap re-decode, 2026-09):**

A second `Wallpaper("bg3.png")` cost ≈ cold (36 ms) although `_IMAGE_CACHE` held the image. skia-python's `Paint.setShader(sh)` stores a **deep copy** (serialize → deserialize), and `paint.getShader()` is not `sh`. For an image shader the copy wraps a **new `skia.Image`** (new `uniqueID`); Ganesh keys textures by that ID, so the draw misses the GPU cache. A lazy image re-decodes on the next draw (~7 ns/px). A raster / GPU-backed image is **PNG-encoded inside `setShader`** (~120 ns/px, ~0.8 s for 2669×1782). Gradients and SkSL uniforms serialize cheaply; only image content is the trap. Only `setShader` copies (measured, skia-python 144): the `skia.Paint(Shader=sh, …)` kwarg, `skia.Paint(other)` (copy constructor), `RuntimeShaderBuilder.setChild` / `makeShader`, and `setImageFilter` all share the object.

Rules that prevent a repeat:

1. **Never `setShader` an image-bearing shader** (image shader, or SkSL with an image child). Build the paint with `skia.Paint(Shader=sh, …)`, or copy a template Paint (`skia.Paint(template)`). Local matrices are then free: `makeShader(localMatrix=)` / `makeWithLocalMatrix` wrap the same image, so every size and host still hits one GPU texture. Pooled paints that swap shaders with `setShader` (spatial FX `_PAINT_*`, recipe stroke slots) must only receive image-free shaders.
2. **Prefer `drawImage` / `drawImageRect`** when no tiling is needed — they draw the image object itself.
3. **Keep shared-cache images lazy.** Never store `makeRasterImage()` / `makeTextureImage()` results in `_IMAGE_CACHE`; any later `setShader` of them pays the PNG encode. To pay a decode early, *draw* the image (or the template) into a small GPU target.
4. **Measure with a new Paint per draw.** Reusing one Paint hides the cost (its copy is decoded once); per-construct / per-resize rebuilds expose it.

Wallpaper fix (template Paint, identity shader, canvas-matrix placement; predates the kwarg finding and still correct): [Canvas Design.md — Background engine](Canvas%20Design.md#background-engine). Test: `tests/test_background_image.py` (`TestWallpaperImageIdentity`).

Texture on Shapes (2026-09-24): `PaintState._material_paint` builds fill / line paints with `skia.Paint(Shader=…)`. Every shape paint of one Texture file, at any quantized extent and across `Texture(...)` instances, samples the one `_IMAGE_CACHE` image. Before, 50 Rects on a 2670×1780 Texture held 50 copies of ~19 MB, overran the GPU budget and re-decoded every frame (~1.1 s/frame); after, 0.83 ms/frame and one 19 MB texture. Test: `tests/test_texture_image_identity.py` (a raster image over a mutable numpy buffer; a copy keeps stale pixels).

Sprite needs no change: the body blit is `drawImageRect` on the shared decoded image, and hue / recolor / SDF looks pass the image as a runtime child (`setChild` + `Paint(Shader=b.makeShader())`).

**Due diligence (copy this when touching looks / filters / draw bounds):**

1. **Name the host.** Shape vs Sprite vs Text vs SpatialFx. Interned visuals cannot grow `_is_multipass` per host; Sprite exceptions live in `_render_sprite_body` / canvas AABB, not in `_apply()` branching that Shapes also run. Shared helpers (`_uses_shield_envelope`, paint UV sizing) must gate on **host capability**, not visual class alone.
2. **List the batch_key / intern key.** Who else constructs the same `HostGlow(σ, spread)` or `GlowFilter(...)`? A mixed segment shares **one** RT; growing one member’s AABB grows everyone’s plate.
3. **Compare dest AABB vs what is actually drawn.** If the look paints outside `_oriented_frame` (Shield oval × `shield_scale`, SDF pad, Tail ghosts), the filter layer clips to dest+`_batch_outset`. A visible rect / chopped halo is usually this, not SkSL.
4. **Gate expansion on “dest+outset already covers source?”** Naive `dest ∪ extra` then + outset grows GlowFilter layers that were accidentally large enough. The contains-gate keeps those RTs unchanged.
5. **Do not add `_domain_aabb` on Sprite.** `_approx_draw_aabb` prefers it first — every Sprite, including `_plain_blit` cull, would pay. Text/SpatialFx already use `_domain_aabb` for their own domains; Sprite dest stays `_oriented_frame`.
6. **Do not “fix” a Sprite clip by bumping that style’s glow σ.** It changes the look, misses cull, and still fails at large `shield_scale` / other styles with small pad.
7. **Keep Shape paths byte-stable** when the bug is Sprite-only: no `filters.py` / SkSL / `Shield._apply` / Shape `_geometry_draw` edits unless Shape is wrong too. Conversely, when Shape looks empty but Sprite is fine, suspect a Sprite-only helper leaking into the shared paint path — not the Recipe hot path.
8. **Tests that protect the fleet:** dest AABB unchanged; bubble/bands layer size **equals** dest+outset; vortex (or the clipping style) layer **contains** the extra geometry; a Shape with the same look is unchanged; a Glow-stamp Sprite is unchanged. For ProceduralFill looks: assert non-empty interiors on **small** Shape Circles (`r≈16`).
9. **Cost you are allowed to pay:** the object that was clipped gets a larger plate (the pixels it asked to draw). Clustered vortex fleets grow like one envelope; screen-wide same-key batches are already near full-frame (§5.2).

Sprite costume envelope: [Sprite Design.md](Sprite%20Design.md#costume-envelope-shield-on-sprite). Cull pads: [Canvas Design.md](Canvas%20Design.md).

### 5.6 Recipe draw hot path — lessons

Campaign that made Laser / Neon / Ink / Electric* fleets realtime on the isolation grid (2026-09-09…10; `perf_shape_draw.py`, n=80, `fx_quality="high"`, M4). Keep this section when inventing the next draw win — do not re-learn the wrong bottleneck.

**Two clusters — do not mix the fixes**

| Cluster | Symptom | Dominated by | Fix family |
| --- | --- | --- | --- |
| **A. Solo Recipe CPU** | `draw_ms` scales with N; `submit_ms` ≈ 0; quality-flat | Python per stroke: `Color()` / validate / HSV object churn; N× `obj.draw` ceremony | Tuple→`Color4f`; float HSV helpers; look-pass grouping; hoist geometry |
| **B. Overlay GPU submit** | `submit_ms` cliffs (Electric* high); medium collapses it only by dropping bloom | N× `_gpu_blur_stroke` `saveLayer` after an already-batched GlowRim halo | One shared Plus plate among interned peers (same escape as filter batching) |

Filter `_batch_key` grouping already amortized silhouette Blur. Cluster A opts out via `_must_solo_draw` (`_is_multipass`) unless `_look_pass_group`. Cluster B was **not** “all GlowRim” — Rim @ n=80 was cheap; only the high PE overlay was the cliff.

**Safety labels (reuse these words)**

- **Safe** — pixel-identical; no z change; no author API change. Prefer this first.
- **Safe within declared scope** — may relax z among peers that already share a batch/look key; pixels stay equivalent under commutative blends (ADD/Plus); `fx_quality="max"` / `batch_shared_filters=False` restores strict order. Not a fidelity downgrade.
- Lowering `fx_quality` is **never** an approved “fix” for a high-path cliff — medium/low numbers are diagnostic only.

**What worked (keep doing)**

1. **Profile one isolation cell** (`perf_shape_draw.py --cell … --profile`) before inventing a mechanism. cProfile names the Python tax; phase timers separate `draw_ms` vs `submit_ms`.
2. **Kill `Color()` on the paint path.** `_rgba_for_paint` + interned `Color4f` + `setAlphaf` for pulse. ~18× cheaper than `_color_obj` on tuples.
3. **Finish the same cut for HSV helpers.** Leaving `_neon_tint` / `_energy_rgb` on `Color.vibrant_version` / `from_hsv` reintroduced the tax after paint was fixed. `_vivid_rgb` / `_energy_*` = same math via `colorsys` + a tiny intern; pin with a bit-stability test.
4. **Pass-major emit for interned stroke ladders** (`_look_pass_group`). One shared paint per pass; world `drawPoints` / `drawCircle`. Overlapping ADD stays N primitives (one Path would union coverage).
5. **Hoist per-shape reads across passes.** `_center_radius` once for halo/body/core, not once per pass. Reuse bucket tint keys — do not recompute `_neon_tint` for `group[0]`.
6. **Keep look-pass buckets kind-pure** (`_world_stroke_kind`). See [look-pass bucket keys](#look-pass-bucket-keys--world-stroke-kind) below — mixing Circle+Rect in one tint bucket silently kills the world fast path.
7. **Batch Plus/ADD overlays that sit outside filter batching.** Electric* high PE-glow → one plate; mid/core stay unfiltered. Same escape hatch as filters.
8. **Skip unset ceremony** in `Graphic.draw` (transient / stamp slots). Cheap, Safe, compounds with everything else.
9. **Plain `_blit_plain` for Shape and Sprite.** When `_plain_blit` is True, canvas skips the envelope: Shape → pull PropertyAnchors + `_geometry_draw`; Sprite → pull + `_blit_image`. Do not leave linked `angle` / `scale` stale on this path. Not a Recipe win — orthogonal to Cluster A/B; gate that plain `draw_ms` drops and Laser/Neon/Ink/EF stay flat.
10. **When `cull_offscreen` is off, do not call `_passes_cull`.** Visible-only list; counters still count kept. Cull-on path unchanged.
11. **Gate with `--micro` + `--suite --no-sweep-quality`.** Plain and ElectricField must stay flat when touching Cluster A; Neon/Laser/Ink must stay flat when touching Cluster B.

**Rejected (reopen only with a profile that names the cost)**

The isolation grid showed `tick_ms` / `flush_ms` ≈ 0 and the same `draw_ms` for static and moving fleets: the walk redraws everyone, and the tax is per stroke, not per changed shape.

| Idea | Why not |
| --- | --- |
| Scene / layer **image cache** of unchanged shapes | Static ≈ moving `draw_ms`; Laser pulses and ElectricField path effects animate with no geometry change; ADD into movers is not a SrcOver blit; `destroy()` leaves a hole in the plate |
| Per-shape bake to a sprite | Leaves N blits and breaks pulse / ADD; look-pass grouping already is the display list |
| Author-facing "static decal" / "cache this shape" | A hidden caste of objects; wins stay inside the draw walk |
| World primitives for axis-aligned Rect / Ellipse as the Neon lead | Rotated fleets skip the win; more per-kind draw cases. Kind-pure buckets are the cheap related fix |
| Laser rewritten as a GlowRim package | High-quality Halo costs about what Laser does; the RT cliff was ElectricField's overlay |
| "Always prefer CheapGlow over Glow" | A clustered fleet (n=80) drew batched `Glow` in 0.79 ms vs CheapGlow 1.34. CheapGlow is the **sparse** fleet tool (§5.2) |
| Lower `fx_quality` to fix a high-path cliff | A perceptible fidelity cut (medium drops the bloom); medium/low numbers are diagnostic only |
| Graph epoch / `mark_dirty` gating | `flush_ms` ≈ 0: not a graph problem |

### Look-pass bucket keys / `_world_stroke_kind`

`_stroke_group_world` / `_fill_group_world` only take the world fast path when **every** shape in the group shares one kind:

| Kind | Who | Fast path |
| --- | --- | --- |
| `line` | `Line` (stroke types) | `drawPoints(kLines)` / `drawLine` |
| `circle` | full-disk `Circle` (360° sweep) | world `drawCircle` (optional hoisted `centers=`) |
| `path` (or `None`) | Rect, Ellipse, Polygon, arc Circle, Sprite, … | per-shape `_geometry_draw` (CTM) |

If a bucket mixes `circle` and `path`, the helper demotes the **whole** group to `_geometry_draw` — including Circles that could have stayed on `drawCircle`. That happened in mixed fleets (`scripts/smoke/shape_fx.py`: shared `Neon()`, many host tints, Circle+Rect+Polygon on one layer) when buckets keyed only tint/width/`is_line_shape`.

**Rule for any new `_emit_look_passes`:** include `_world_stroke_kind(shp) or "path"` in the bucket key alongside tint/width (and quality/LOD bits as needed). Host-following stroke ladders also key `line_cap` and, for stroke types, `line_join` — two lines with different caps must not share a paint. Splitting buckets this way stays inside the existing look-pass z contract (z already relaxed among one interned Recipe on one layer). Do **not** rely on “check `group[0]` then assume the rest match.”

**Safety:** **Safe** — pixel-identical for kind-pure groups; no new z relaxation beyond §3.2; no author API change. Test: `TestLookPassGrouping.test_world_stroke_kind_keeps_circle_fast_path`.

**What failed / reject**

| Idea | Why |
| --- | --- |
| Scene / layer **image cache** of “unchanged” shapes | `draw_ms` static ≈ move; looks pulse / PE-animate; ADD-into-movers ≠ SrcOver blit; `destroy()` holes the plate |
| Per-shape bake-to-sprite | N blits left; look-pass grouping is the display-list |
| Make Laser a GlowRim package | Halo high ≈ Laser CPU; EF high cliff is RT, not “needs Blur” |
| “Always prefer CheapGlow over Glow” | Clustered grids: batched `Glow` can beat CheapGlow; CheapGlow stays the **sparse** fleet tool (§5.2) |
| Lower `fx_quality` to fix Electric* submit | Drops bloom — perceptible; medium collapse is diagnostic for overlay batching |
| Coalesce Laser strokes to “fix” EF submit (or reverse) | Different bottlenecks; mixed fix regresses the wrong cell |
| Widen world primitives (axis-aligned Rect/Ellipse) as the Neon fleet fix | Rotated smoke fleets skip the win; more per-shape special cases = high break risk for modest gain |
| Shared GPU blur plate for Neon MaskFilter halo as the lead | Medium (no mask) only ~10% on the smoke mix; new `saveLayer` path outside GlowRim — keep for a later scoped item if amount/width cliffs show up |

**Author / API invariants that the wins depend on**

- Interned looks stay interned (`Laser("red")` is one instance) — look-pass and overlay batch group by instance identity.
- No author-facing “mark static” / “cache this shape.”
- Strict z remains available via `batch_shared_filters=False` / `fx_quality="max"`.
- Look-pass emit buckets stay **kind-pure** (`_world_stroke_kind`) whenever they call `_stroke_group_world` / `_fill_group_world`.
- Host-following look-pass paints also stay **cap-pure** (and join-pure on stroke types): bucket keys include `line_cap` / `line_join` so `"butt"` or `"square"` tips do not inherit a peer's round paint.
- Product scope stays tens–hundreds of screen objects; n=80–200 stresses the walk, not a new 500+ promise.

**Benches:** `scripts/bench/perf_shape_draw.py` (`--suite`, `--micro`, `--profile`); product-shaped `scripts/bench/gpu_mix.py --bench --mode fleet|heroes|heroes_mass`. Mixed-geometry smoke: `scripts/smoke/shape_fx.py` (not an isolation cell — also pays `move_to` / wallpaper / HiDPI). Compare **phase ratios** across harnesses (isolation is 1000×700 design==window; `gpu_mix` is HiDPI).

---



## 6. Canvas post cost model



### 6.1 Fixed tax when stack is active

Any active effect forces **scene → offscreen RT → compose**. Empty inactive stack → identity (no soft upscale). That fixed tax is why even “free” Grade is slightly above true baseline (window-only draw).

### 6.2 Cost tiers (author mental model)


| Tier      | Rule of thumb                       | Examples                     |
| --------- | ----------------------------------- | ---------------------------- |
| Free-ish  | Color matrix / Plus grain           | Grade, Grain, Flash          |
| Cheap FB  | One fullscreen pass                 | Single SkSL, Vignette@½      |
| Med FB    | Blur / fill-rate at high res        | Bloom, Chroma, Vignette@full |
| Expensive | Shape ImageFilters × area × batches | GlowFilter / Blur / Shadow   |
| Brutal    | Unique unbatched filters × N        | Per-sprite GlowFilter()      |




### 6.3 Mutating post effects

- **OK:** mutate sticky knobs each frame (`bloom.intensity`, `lamp.target`, uniforms). SkSL = compile-once; per-frame = set uniforms + drawRect.
- **OK:** `canvas.flash` / `shake` / `glitch` / `ripple_at` when sparse.
- **Cost grows** with **how many simultaneous stages** run, not with param thrash.
- Prefer a small stack (e.g. Vignette+Grain+Bloom) over many concurrent SkSL passes.



### 6.4 Quality sensitivity summary

- Shrinks with `post_fx_scale`: vignette, bloom, chroma, pixelate, screenblur, scanlines when quality-sensitive.
- Mostly flat vs quality: SkSL (Lamp, Spotlight, Haze, …), Grade, Grain, Flash — marked `_quality_sensitive=False`.

---



## 7. Performance conclusions


| Finding              | Detail                                                                             |
| -------------------- | ---------------------------------------------------------------------------------- |
| GPU context required | `GrDirectContext.MakeGL()` + `MakeRenderTarget` for speed. With **no** GL context (headless tests, `make_guia_thumbs.py`) `fw._offscreen_surface` hands the scene / post-FX RTs out as raster surfaces: the same `_draw_frame` path, on the CPU (`test_postfx.TestPostFxHeadless` draws every exported post effect) |
| Shared `_batch_key`   | Huge win vs unique-per-shape filters                                               |
| Low-res shape FX     | Helps; batch path sizes RT from union AABB × scale                                 |
| Hybrid post          | Sharp geo + low-res bloom / Multiply overlays                                      |
| Plus grain           | SoftLight was ~1.5 ms; Plus ≈ free                                                 |
| Larger bloom σ       | Often faster and better (Skia downsamples)                                         |
| SkSL GPU             | Compile once at import; ~1–2 ms fullscreen Retina typical                          |
| SkSL raster          | ~30–60 ms — do not use                                                             |
| HitFeedback          | Must stay SkSL (CPU 384² disp maps were a perf regression)                         |
| MotionTrail          | EMA feedback; compose residual (not Plus of full-scene plate) so static → identity. Mute (`enabled` / stack) and survival drop **both** ping-pong RTs — flags-only reset lets the sibling plate return on the second re-enable frame. |
| Dev vs target        | Dev M4 roughly 3× CPU / 5–8× GPU faster than low-spec target                       |


Product targets: **60 fps** on balanced (target hardware), **30 fps** minimum (Auto last rung only).

---



## 8. Benchmarks

Compare runs on one machine and one harness setting; absolute FPS is not the arbiter.

| Metric | Role |
| --- | --- |
| **ms/frame** (`1000 / fps`) | Primary: the frame budget (16.7 ms at 60 fps); `effect_cost_ms ≈ ms − ms_baseline` |
| **cost×** (`T_effect / T_baseline` at the same quality) | Machine-relative ranking |
| FPS | Product language only |

Protocol: `scripts/bench/perf_fx_matrix.py` — one subprocess per cell, design = window 1000×700, n=48 movers, uncapped frame rate, ~0.3 s warmup + ~0.85 s measure. Shape transients re-arm every frame (worst case, sustained); SpatialFx rows keep the movers and add emitters. Rank at `high` (the framework default), never at `max` (batch off multiplies shape-filter cost ~5–8×). Glow union cliff: `scripts/bench/perf_glow_fleet.py` (§5.2). Time-series pulse and the current top of the ranking: [scripts/bench/fx.md](../scripts/bench/fx.md).


## 9. Known rules / gaps

1. Empty `canvas.effects` → identity passthrough (no soft upscale).
2. Custom `post_draw` replaces the built-in stack (escape hatch).
3. Only `top` may opt out of post (`set_post_fx`); interior layers cannot.
4. HiDPI: design size ≠ FB pixels; post/SkSL math uses FB size.
5. Z-order under filter batching: known tradeoff (groups by first-seen `_batch_key`).
6. Shape `ImageFilter` graphs are immutable after construct; param animation requires rebuild.
7. `batch_shared_filters` is part of `FxQuality` (True except full); can override after `canvas.fx_quality`.
8. Shape filter cost still dominated by re-draw + union AABB; GlowFilter is now DropShadowOnly+Merge (was multi-node MatrixTransform DAG).
9. Shape multipass Recipe is not mixed into filter saveLayer batching (correctness of pass order). Interned stroke Recipes (Laser / Neon / Ink) may group **look-passes** among consecutive peers when `batch_shared_filters` is on; that is not a filter RT. Emit buckets must stay **kind-pure** (`_world_stroke_kind`) or `_stroke_group_world` demotes Circles/Lines to `_geometry_draw` (§5.6). ElectricField / ElectricBolt **high** PE-glow may share one overlay Plus plate among consecutive interned peers. `fx_quality="max"` restores per-shape Recipe order and per-shape overlay `saveLayer`. HSV tint helpers on the draw path must stay float/`colorsys` (no per-call `Color()`); see §5.6.
10. API remains draft; more effects/presets welcome.
11. Recolorable procedural fills (`WaveFill`, `AuroraFill`) take optional `color=`; other fills unchanged.
12. Shape transients use six independent channels (`life`/`flash`/`pulse`/`pop`/`knock`/`spark`); orthogonal to sticky visuals/filters; tick completes pre-draw. Transient `saveLayer` / dig extent comes from `shape_pivot` + `_transient_layer_bounds` (AABB-aware) — never a bare `r=24` for free Polygon / Text (§3.1c).
13. Alpha or dig envelopes strip `fill_filter`/`line_filter` for that paint pass only (avoids GlowFilter backdrop wash).
14. Hard `destroy()` cancels pending transients with no late `on_done`; `is_alive` is False. Hide ≠ destroy.
15. `visual = None` restores look identity (author package from before the first look), not module defaults. Host-tint `color=` dyes that snapshot; Glow/Shadow `color=` does not. Author `.fill=` / `.line=` / `set_color` during a visual **do** sync into identity. After a live recolor of seeded Neon / Halo, `visual = None` restores the **new** color. Quality / per-frame `_apply()` must not rewrite identity.
16. Filter `saveLayer` bounds are dest AABB + `_batch_outset`. Looks that paint outside the dest (Sprite Shield oval) must **gate** expansion on “dest+outset already covers source” — do not put `_domain_aabb` on Sprite and do not bump glow σ as a clip workaround (§5.5).
17. Shared paint helpers that branch for Sprite costumes (`_uses_shield_envelope`, ProceduralFill UV half) must require **host capability** (`_shield_envelope_half`), not only `.visual is Shield`. Shape Shield uses `_center_radius` (delegates to `shape_pivot`). Do not swallow `AttributeError` into fixed-res `tick()` (§5.5 lesson 2026-09).
18. Every seeded look that takes `color=` (Neon / Halo since 2026-09-10, the other role-A/B looks since 2026-10-13, [§3.1b](#31b-shape-visuals-shapevisual) "Phase 2"): `set_color` / `.color=` de-seeds to the interned unseeded sibling (`Visual._unseed`, built from every non-colour knob as stored), assigning the private `_visual` slot then `_reapply_visual` — never the `.visual` setter. Already-unseeded `_unseed()` returns `None` without intern. A look that takes `color=` and has no `_unseed` keeps drawing its seed: the seeded sweep (`test_visual_color_param`, `SEED_WINS` empty, shrink-only) fails on it. Palette looks (`Metal`, bubble Shield, 2026-10-13) swap the other way: palette or seed → the shape-following sibling (above). Why: a seed (`Neon("red")`) is written into the shape's color, so removing or swapping the look keeps red; a later `.color = "green"` must then win live, but re-applying the seeded look stamped the old seed back in the same call. The swap does not change batching: filter `batch_key`s exclude color, and every shape recolored to one color resolves to the same interned unseeded instance — what reassigning `Neon(new_color)` by hand would give.
19. Interned looks and filters are **immutable after construction**: `_intern` / `_intern_filter` mark the instance `_interned`, and `_interned_setattr` (`Visual` / `FilterEffect.__setattr__`) refuses public writes once `_ready` (`AttributeError` naming `Look(field=…)`). The suggestion is author code that builds (`_read_only_message`): a styled look keeps its style (`Bolt(style="filaments", amount=6)`), a style's own class is named by the exported look and style (`HaloPulse` → `Halo(style="pulse", …)`, `_OrbHalo` → `Shield(style="plasma", …)`), and a knob that style does not read gets the constructor's refusal instead (error path only: it builds the suggestion once to check; guard `TestInternedLooksFrozen.test_the_suggested_call_builds_on_every_style`). A write on a shared `Neon("red")` would repaint every user, poison the cache for the next same-argument constructor, and skip fields derived in `__init__` (`Recolor._key_hsv`). Change a look by building a new one or through the host (`set_color` de-seed swaps instances). Private caches stay writable; per-draw cursors (`_rp_stroke_i` / `_rp_fill_i`) write `__dict__` directly to skip the guard (~0.1 µs each). Non-interned looks and filters (`Tail`, `Recipe`, `ComposeFx`, an author subclass) are not frozen but **closed**: a write to a name they do not have raises with a did-you-mean (`_interned_setattr` calls `scena.closed.check_closed_write` once the instance is sealed; `Visual.__init_subclass__` / `FilterEffect.__init_subclass__` seal every subclass, author ones included — [Scena Design](Scena%20Design.md#entity-ink-vs-st)). The same holds for post effects, backgrounds, audio effects and their stacks (`ClosedSurface`; construct-to-place and the numbers guard are installed before the seal). Tests: `test_registry_key_fields.TestInternedLooksFrozen` (every exported interned look / filter), `test_closed_surfaces.TestEveryAuthorObjectIsClosed`. Intern caches (`_RECIPE_CACHE` / `_VISUAL_CACHE` / `_FILTER_CACHE`) are unbounded dicts. De-seed keeps Recipe/Halo recolor O(1) after the first swap. Driving `.color=` on a `Paint` / `Fill` / `Stroke` visual still intern-per-material (pre-existing). An LRU cap is deferred.
20. `MotionTrail.enabled = False`, `canvas.effects.enabled = False`, `remove` / `clear`, and `FxQuality.LOW` (survival) drop both ping-pong RTs plus `_prev`. The next active frame seeds from the live plate. A flags-only reset (`_primed` / `_prev`) is not enough: `_ensure` keeps the sibling RT and the old EMA plate returns on the second frame.
21. Every public PostEffect / BackgroundField / SpatialFx / AudioEffect constructor follows [Scena Design — Numbers and signs](Scena%20Design.md#numbers-and-signs) before placing: `guard_init_numbers` runs **outside** the construct-to-place wrapper, so a bad knob never attaches a half-built effect. A string where a number goes raises `TypeError`, `nan`/`inf` `ValueError`, a negative size-like knob (`validate._NONNEG_PARAMS`) `ValueError`; an unknown keyword raises `TypeError` listing valid keywords (engine-only `attr_name` / `owner` / `register` hidden) plus did-you-mean. SpatialFx style owners (`Fire(style="plume")`) report the public class name and include `__new__` params. A new effect gets this for free if its numeric knobs have numeric defaults; `tests/test_api_robustness.py` walks every exported subclass.
22. `shape.visual = "<string>"` is a colour (`Paint`). A string that names an exported `Visual` class and is **not** a colour (`"neon"`, `"electric_field"`) raises `TypeError` pointing to `Neon()` / `ElectricField()` (`style._look_class_named`) — it used to paint magenta with an "Unknown color" warning. Look names that are also colour names (`"ink"`, `"aura"`, `"tail"`) stay colours.
23. **Noise hash (SkSL).** Interpolated lattice noise must hash *exact* inputs: `n = dot(floor(p), (127, 311)/1024)`, corners `hash1(n + c)` with `c ∈ {0, 127, 311, 438}/1024`. Never `hash(i + float2(1,0))` with non-integer weights. The driver may round shared corners differently per cell (FMA/reassociation), and `*43758` turns 1 ulp into a seam (Windows/Intel: blocky Clouds/Stardust). Keep `sin` arguments ≪ 2^17: Intel GPU `sin` collapses at |x| ≥ 131072. Seeds become an exact `k/1024` index shift set once in `main()` (`g_seed_n`), never a float added to the hash input. Exact while |127·ix + 311·iy| < 2^24. Per-cell hashes (Stars, Debris, StarFly, PlanetFly, shield nebula) use the same `/1024` weights (the old `(127.1, 311.7)` hit Intel's `sin` cliff once |cell id| ≳ 300). Shaders that loop over neighbour cells (Embers, WindStreaks) hash the same `gid` from different unrolled iterations, so they compute `cn = dot(gid, W)` once and salt with whole numbers, `hash1(cn + 3.0)`, never `hash(gid + float2(2.3, 0.7))` (an inexact salt can round differently per iteration and cut an ember at the cell edge). Salts are multiples of 3.0: each maps to a cell ≥ 9 away, so attributes stay uncorrelated. Old and new hashes have the same statistics (threshold rates, flat histogram); only layouts moved. Guarded by `tests/test_sksl_noise_hash.py`. **Rotate fbm octaves.** Value noise has ridges along its lattice axes; octaves that only scale + shift keep the same axes and add those ridges up, and a contrast curve (`smoothstep`) turns them into straight edges and square holes (Clouds, 2026-10). Turn each octave's domain (`(0.8, 0.6)` rotation) — `floor()` of the rotated point is still an integer cell, so the exact hash holds (`test_background.TestCloudsHaveNoGridEdges`). Every multi-octave fbm does it (Clouds, Stardust, Chromadust, Nebuladust and their survival variants, Nebula, ChurningClouds, FilamentField, PlanetFly, CosmicBloom's nebula); two-term `fbm2` turns its second octave. Guard over every SkSL module: `test_sksl_noise_hash.TestFbmOctavesRotate`. Stardust / Nebuladust also lose a faint square grid they showed before.
24. **Time as wrapped phases (SkSL).** `_shader_time()` grows without bound. Any time term multiplied by a frequency > 1 (turbulence octaves, rise scrolls) passes Intel's 2^17 `sin` cliff within minutes of uptime, and float32 loses the fraction long before. New shaders take **no raw clock**: the CPU computes each periodic term as `_wrapped_phase(rate)` (`spatial_fx.py`, float64 `fmod` to [0, 2π)) and binds the phases (one per octave, packed in `float4`s). Each octave wraps on its own, so the wrap is seamless. Portal and Fire blaze follow this; older shaders (Warp, backgrounds) still bind `time` and are only safe while their multipliers stay small. Guarded by `TestShaderTimeIsWrapped` (`tests/test_spatial_fx.py`: every uniform stays finite and < 1e4 at t = 1e7 s).
25. **Author channel writes under a look go through the look** (2026-10-13): `.fill` / `.line` setters patch identity and, when they patched (the snapshot exists only while a look is on — a shape without one pays nothing more), call `_look_channel_written`, which de-seeds on the look's own channel and runs `_reapply_visual`. Hence every write a look makes to its shape must run under `_in_visual_apply`: `visual =` and `_reapply_visual` set it, and a `_render` that rewrites the package at draw time (ElectricField / Bolt / Rim quality switch) goes through `recipes._apply_at_draw` — otherwise each draw would re-apply and patch identity with the look's own paint (`test_drawing_never_reapplies`). `set_color` writes under `_in_recolor` (it re-applies once itself). Why: an author write after `visual =` skipped the look (Rim lost its line alpha, Halo kept the old wash, a seed won), so the shape depended on write order. The stroke knobs (`line_width`, `blend`, `dash`, `line_cap`, `line_join`) take the same route (KN8, 2026-10-13; before, 23 / 18 / 11 of 42 unseeded cells drew differently by write order and `visual = None` dropped every write made under a look). The `.blend` setter rebuilds a Sprite's body blit *before* the re-apply, so the blit takes the author's blend as when written before the look. Cost: a no-look setter pays the identity lookup only (A/B flat); a write under a look costs a re-apply (~30–60 µs), so a per-frame tween of a knob under a look pays that per write.

---
26. A linked `color` (`shape["color"] @= …`) is `set_color` re-run under the look on: the identity follows it, `visual = None` shows the formula's value. A look that brings its own color (`Paint` / `Fill` / `Stroke`, a seeded `Neon("red")`) refuses on a linked color, fill or line; an unseeded look tints from it. A look going on pulls the links first, and nothing pulls inside an apply ([Reactive Design — Appearance links](Reactive%20Design.md#appearance-paintstate-internal)).


## 10. Recommended defaults

```python
# fx_quality defaults to "high" → post ½, shape 1.0, batch True
canvas.fx_quality = "high"
Vignette()
Grain()
Bloom()
# Optional: force unbatched paint order without leaving balanced scales
# canvas.batch_shared_filters = False
```

- Prefer **shared** shape filter / visual instances; keep filtered sprites **spatially clustered** when possible.
- Sparse projectiles / fleets: prefer **`CheapGlow` on `.glow`**. Keep fleets clustered or use canvas Bloom for atmosphere.
- Prefer ImageFilters + overlays for stock local FX; Recipes for hero multipass costumes; shape **transients** for spawn/hit/death one-shots; curated SkSL for tilt / lamp / rays / cone.
- Prefer **SpatialFx** (Fire / Rain / Jet / Sparks) for sticky soft place décor; keep `canvas.*_at` for brief bangs.
- Prefer **BackgroundFields** (`SkyGradient` / `Stars` / `Stardust` / `Chromadust` /
`Nebuladust` / `Plasma` / `Borealis` / `Mist` / ambient arcade washes / soft
`Lattice` / `Road` / tunnels: `Floor` / `Tunnel` / `StarFly` / `PlanetFly`) for
infinite-scroll
procedural fields / tunnels — not giant shapes, not post FX. Author scenery on
parallax layers.
- Prefer **Parallax Layers** (`canvas.layers.create(..., pan_response=…)`) for
finite author shapes / SpatialFx that should lag or lead the camera — never
for gameplay bodies (hit / collision forbidden).
- Prefer canvas Bloom/grade for whole-frame glows; shape GlowFilter for **batched** local filled-body halos; `Halo(style="soft")` for batched hollow neon (`HostGlow`); **Shape** `Halo` **/** `Halo(style="fill")` **/** `ElectricField` **(med/high) / Bolt high / Rim** for batched Blur + deferred rim (§3.1b); Shape Halo medium for a sharp ADD outline without an FX RT; **Sprite** `Halo()` / `Laser()` / `Rim()` for SDF silhouette glow/beam; Neon for few highlighted sprites.
- Measure in-app **ms/frame @ high** for ranking; use `perf_fx_matrix` relative cost× + quality ladder to explain regressions.

---



## 11. Development directions (open)

Priority ideas from status-quo analysis + 2026-08-07 matrix (not committed work):

1. **Fidelity ladder shipped:** low / medium / high + max; former scale-only “medium” notes superseded — medium is **algorithmic lite**.
2. Optimize **top cost×@high** hero multipass + SpatialFx / transients (side tracks). Dense-halo filter variants (capped DropShadow / dilate rim) tried and **dropped** — no meaningful win vs batched GlowFilter.
3. ~~Stable pooled shape FX surfaces~~ — **done** (64px buckets, pool of 8; content sub-rect blit; `canvas.shape_fx_surface_stats()`).
4. ~~Tighter bounds / tiling~~ for large multi-shape batches — **rejected** (~+4% sparse FPS; stretch unmet; see §5.2).
5. Optional **mutable filter params** without full graph rebuild (if Skia allows cheap update).
6. Low-spec hardware benches; keep relative tables in this doc.
7. Expand canvas/visual catalog carefully; register stage + zero-arg visual + matrix row.
8. Optional extra transient styles if gameplay demos demand them (keep channel model stable).
9. Recipe multipass: paint slot pool + Discrete PE cache — **done** (interned PE by seed; rotating stroke/fill paints). Stroke/fill `Color4f` from tuples (no per-stroke `Color()`); interned-seed bake + `setAlphaf` for pulse — **done** (2026-09-09). Look-pass grouping of interned Laser / Neon / Ink — **done** (2026-09-09; `batch_shared_filters` escape). Look-pass buckets kind-pure by `_world_stroke_kind` — **done** (2026-09-10). Electric* overlay-glow batch — **done** (2026-09-09; shared Plus `Blur(σ=2.2)` plate). `Graphic.draw` stamp/transient probes — **done** (2026-09-09). Neon `_vivid_rgb` / energy HSV helpers + look-pass center hoist — **done** (2026-09-10). Plain Shape/Sprite `_blit_plain` + PropertyAnchor pull; cull-off draw-walk hoist — **done** (2026-09-10). Live recolor of seeded Neon / Halo / HaloFill / HaloSoft (`_unseed` + `_deseed_active_visual`) — **done** (2026-09-10); `_unseed()` on every other role-A/B look (Phase 2) — **done** (2026-10-13). Lessons: [§5.6](#56-recipe-draw-hot-path--lessons). Remaining: optional LRU on intern caches — [§9](#9-known-rules--gaps) rules 18–19.
10. ~~Large-world~~ `canvas.cull_offscreen` — **shipped** (default on since
  2026-10-12 with a per-layer backoff, opt-in before; draw-only AABB + pads;
  parallax layers never culled; when off, draw walk skips `_passes_cull`;
  [Canvas Design.md — Offscreen culling](Canvas%20Design.md#offscreen-culling)). Demo: `scripts/smoke/world_view.py` (also `app_scene_realistic --cull`).
11. Vignette edge shaders cached (no new half-res variant; rim strips already cheap).
12. Product regression scene: `scripts/bench/gpu_mix.py` (`--suite` / `--profile` / shape_fx_RT counters).
13. :class:`~scena.visuals.Shield(style="plasma")` / :class:`~scena.recipes.Shield` —
  SkSL body + GlowFilter (filter-batchable). On **Sprite**, the shell is a frozen
  silhouette-union ellipse × ``shield_scale`` (not the playhead rect; not the hitbox) —
  see [Sprite Design.md — Costume envelope](Sprite%20Design.md#costume-envelope-shield-on-sprite).
  **Shape** Halo high = GPU `Blur` of a tinted
    stroke + unfiltered ADD rim/spine via `_overlay_after_filters` after the
    filter segment (§3.1b). Halo(style="fill") = opaque fill + that shell. Shape Halo/Halo(style="fill")
    **medium** = filterless ADD glow + sharp outline (solo). Halo(style="soft") = batched
    HostGlow at medium and high. **Sprite** `Halo()` / `Halo(style="fill")` / `Laser()` / `Rim()` =
    FrameFx SDF + blit (no ImageFilter; same constructors, no public v2 classes). Overlay-after-filter **shipped** for the
    GlowRim family (Shape Halo, Halo(style="fill"), ElectricField med/high, ElectricBolt high,
    Shield(style="plasma"), Bolt high, **Rim** (all qualities)). ElectricField medium/high share `speed`
    (not capped by lite `pe_hz`; `1.0` ≈ old 14 Hz).
14. **Parallax Layers shipped** (§3.1f): frozen create-only camera response;
  permanent no-hit / no-collision invariant. Deferred: live mutable response,
    per-shape override, tiling sugar.

---



## 12. File map

Router for this subsystem. Match one row; open **Start**. Search; do not slurp.
Do not read this table as a license to open the whole cluster. Hub map:
[Scena Design.md — Appendix](Scena%20Design.md#appendix-module-map).


| Need | Start | Also |
| --- | --- | --- |
| `Palette` / `Colormap` / color names | `color.py` | `gradient_presets.py` |
| ImageFilters (`Blur`, …) | `filters.py` | `style.py` |
| `.visual` compiled looks | `visuals.py` | — |
| `Neon` / multipass costumes | `recipes.py` | `visuals.py` |
| `set_color` vs seeded look | `style.py` | `visuals.py` (`_unseed`), `recipes.py` (`Neon._unseed`) |
| `.glow` / `.shadow` / `.hue` / `.tail` | `stamps.py` | `style.py` |
| Transients | `transients.py` | — |
| `SpatialFx` host | `spatial_fx.py` | `spatial_fx_effects.py` (kinds) |
| Warp / Portal / Fire blaze shaders | `_sksl_backdrop.py` | `spatial_fx.py` (`_wrapped_phase`, `_plate_surface`) |
| Background **kind** | `background_kinds.py` | `background.py` (stack) |
| Canvas post stack | `postfx.py` | `effects.py` (built-ins) |
| Cover fade/wipe | `cover.py` | `orchestration.py` (draw slot) |
| Quality / Auto | `fx_quality.py` | `fx_auto.py` |
| Look/FX type errors | `validate.py` | — |
| Filter batch / shape FX RT / AABB gate | `canvas.py` | [§5.5](#55-changing-the-effect-system-without-regressing-hot-paths) |
| Parallax layer CTM | `camera_response.py` | `registry.py`, `canvas.py` — [Canvas Design.md](Canvas%20Design.md) |

**Do not slurp:** `recipes.py`, `visuals.py`, `style.py`, `canvas.py`.

**Shader only** (do not open otherwise): `_sksl_shape.py`, `_sksl_effects.py`,
`_sksl_ambient.py`, `_sksl_ambient_kit.py`, `_sksl_backdrop.py`.

**Proof only:** `tests/test_<area>.py`; smokes/benches listed under [Not in this doc](#not-in-this-doc).




---



## 13. One-page summary


| Topic                      | Takeaway                                                                                                                                                                               |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shape FX                   | ImageFilter layers; cost ≈ **union area + N draw + #keys**; share instances; Sprite extras (Shield oval) expand the plate only when dest+outset clips them (§5.5)                                            |
| Shape visuals              | One `.visual`; stamps compose around it; `visual = None` restores author package (**stamps stay**); `save_visual` / `restore_visual` restores on-screen appearance including stamps (one slot); host `color=` dyes identity, Glow/Shadow stamp `color=` does not; seeded Neon / Halo de-seed on later `set_color` |
| Shape transients           | Six channels (`life`/`flash`/`pulse`/`pop`/`knock`/`spark`); tick pre-draw; dig styles noise/vortex/wipe; alpha/dig strip ImageFilters                                                                                                |
| SpatialFx                  | Sticky soft domains on world layers; tick after transients; not visuals/post                                                                                                           |
| BackgroundFields           | Pre-scene full-screen SkSL; pan/zoom response knobs; empty stack free; not layers/post                                                                                                     |
| Parallax Layers            | Create-only camera knobs on shape layers; decoration-only (no hit/collision); zero cost when unused; never `cull_offscreen`                                                            |
| Offscreen cull             | `canvas.cull_offscreen`; draw-only AABB + pads; default on (backoff when a layer is all in view); fail-open; when off, draw walk skips `_passes_cull`                                                                                                          |
| Post FX                    | `canvas.effects` hybrid; empty stack free; active stack pays scene RT                                                                                                                  |
| Canvas cover               | `fade_in` / `fade_out`; after widgets; hold until uncover; not post; no scene RT                                                                                                       |
| Quality                    | 4-step algorithmic ladder **low / medium / high** + **max** escape; **Auto** policy over fidelity×rate (work_ms, on by default at high@60, ~2 s startup warmup) — see §4                |
| SkSL                       | Curated, compile-once; param updates cheap; GPU only                                                                                                                                   |
| Shape vs canvas full plate | Shape = re-draw + DAG + RT; canvas = filter ready image — **not comparable 1:1**                                                                                                       |
| Perf wins                  | Shared batch, hybrid ½ post, Plus grain, large bloom σ, SkSL hit feedback; Recipe tuple→`Color4f` (no per-stroke `Color()`); Electric* high overlay PE-glow one Plus plate                                                                                                              |
| Author DO                  | Create once / share; mutate post fields; channel-stack transients for hits; SpatialFx for sticky place; BackgroundFields for skies / tunnels; Parallax Layers for finite depth sprites |
| Author DON’T               | Unique filter per frame/shape; screen-wide shape glow for global looks; rain as a fill/visual; interactive bodies on parallax layers; infinite scroll as a giant Shape                 |
| Next                       | Stable shape RTs, low-spec benches, more SpatialFx kinds, more BackgroundField kinds + LOD                                                                                             |



