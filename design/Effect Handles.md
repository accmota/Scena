# Effect handles (post + background)

Constructors for canvas-wide post effects and background fields **return the live instance**. There is no separate handle type. Construction both creates the object and attaches it. Keep the return value if you want to tweak, hide, or **`remove()`** it later.

**Happy path for this note** — pick one row; do not read the rest. Looks / cost:
[Effect System Design.md](Effect%20System%20Design.md). Hub:
[Scena Design.md](Scena%20Design.md). Author catalogs:
[API Guide](../docs/en/guide/index.html#mundo-post) (one-shot `canvas.flash` / `*_at` / capa: [Impacts](../docs/en/guide/index.html#mundo-impactos)).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Post mutate / hide / remove | [Canvas-wide post](#canvas-wide-post-vignette-bloom-grade-) |
| Background same | [Background fields](#background-fields-skygradient-stars-clouds-) |
| Delayed / `temp` | [Delayed placement](#delayed-placement) |
| SpatialFx is not this | [Related: SpatialFx](#related-spatialfx-fire-rain-glowspot-orb-) |

## Use

1. Pick one jump-box row.
2. Read that section only.
3. Stop. Do not open Effect System Design unless cost/inventory is the task.

Hits (`canvas.flash`, …) and cover (`fade_out` / `fade_in`) are **not** handles.

Hide is **`enabled`**, not `visible`. There is no name lookup for post or background fields (Scena has no ids at all: keep the handle in a variable).

---

```python
sky   = SkyGradient("night")     # wallpaper base
stars = Stars(density=0.9, twinkle=0.3)
clouds = Clouds(amount=0.45)

vignette = Vignette()
bloom    = Bloom()
grade    = Grade("cool")
wash     = Wash()                 # sticky bleach; not a hit flash
```

Fire-and-forget (`Stars()` with no assignment) still places the effect; you just lose an easy reference.

Do not construct `Wash` to flash a hit — that is `canvas.flash()`. Cover is also not a handle (`on_done` only — no `then=`).

---

## Canvas-wide post (`Vignette`, `Bloom`, `Grade`, …)

Construction appends to `canvas.effects`. `.add` is idempotent (constructing already placed it). Engine compose order is fixed by stage, not add order:

`FILTER → ADDITIVE → COLOR → OVERLAY → WARP → SHADER`

### Change a parameter

Assign on the instance; knobs are read each frame:

```python
bloom.intensity = 1.0
bloom.sigma = 14.0
vignette.amount = 0.4
wash.intensity = 0.4
wash.color = "gold"
grade.preset = "warm"
grade.contrast = 1.2
grade.saturation = 0.8
```

`Bloom` / `Vignette` / `Wash` also mute by driving the knob to `0` (`intensity` / `amount`).

### Visibility (stay on the stack)

```python
bloom.enabled = False              # skip this effect
bloom.enabled = True
canvas.effects.enabled = False     # bypass the whole post stack
```

`MotionTrail` is stateful (ping-pong afterimage). **`enabled = False`**, stack mute (`canvas.effects.enabled = False`), `remove()` / `clear()`, and survival-tier quality all drop that history so the next active frame seeds from the live plate — no ghost of the previous trail.

### Remove

The handle detaches itself. Stack `remove` is the same action:

```python
bloom.remove()                     # drop this one (releases GPU bits)
canvas.effects.remove(bloom)       # same
canvas.effects.clear()             # drop every post effect
```

Idempotent if it is already off the stack. After `remove`, the Python object still exists. You can put it back:

```python
canvas.effects.add(bloom)
```

### Delayed placement

```python
bloom = Bloom.temp(intensity=0.8)   # constructed, not on the stack
canvas.effects.add(bloom)          # place later
```

Do not invent `canvas.add_effect`.

### Find it later without a stored name

```python
list(canvas.effects)               # construction order
```

---

## Background fields (`SkyGradient`, `Stars`, `Clouds`, …)

Two slots:

| Family | What construction does |
|--------|------------------------|
| Wallpaper (`SkyGradient`, `Wallpaper`) | Becomes **`canvas.background.base`**. Last wallpaper wins. |
| Ambient extras (`Stars`, `Clouds`, `Mist`, …) | Append to the extra stack, construction order (bottom → top). |

```python
sky   = SkyGradient("night")   # canvas.background.base is sky
stars = Stars(...)             # in canvas.background extras
clouds = Clouds(...)
```

`list(canvas.background)` is **extras only**. Base is `canvas.background.base`.

A second wallpaper (`SkyGradient("sunset")`) replaces base. The previous wallpaper is orphaned unless you kept the reference.

### Change a parameter

Ambient fields read knobs every draw:

```python
stars.density = 0.5
stars.twinkle = 0.8
stars.alpha = 0.4
clouds.amount = 0.6
```

Shared camera / mute knobs on every field:

| Knob | Role |
|------|------|
| `enabled` | Skip draw, stay on the stack |
| `alpha` / `amount` | Fade without removing |
| `pan_response`, `scroll`, `zoom_response`, `rotation_response` | Camera / author scroll |
| `center` (Tunnel / StarFly) | Vanishing point in design space (`None` = screen center). Live-mutable. |

`SkyGradient` is a bit different. `horizon` is the viewport fraction (0–1, y-up from the bottom) where **`middle`** (atmosphere) sits — `top` at the zenith, `bottom` ramping in across **`fade`** just below the line (default 0.006; `fade=0` is a hard cut). `horizon=0` (default) is a full-height sky (`middle` at the bottom, no ground tint). Same `horizon` / `fade` as `Ground(horizon=…, fade=…)`. `horizon`, `fade`, `pan_response`, `enabled`, and `scroll` update live. **`palette` / `top` / `middle` / `bottom` are baked into an internal stop list at construct.** Changing `sky.palette = "sunset"` later does not rebuild the ramp. To change the sky look, replace the base:

```python
sky = SkyGradient("sunset")                    # last wallpaper wins
# or
canvas.background.base = SkyGradient("sunset")
```

### Visibility

```python
stars.enabled = False              # hide this extra
sky.enabled = False                # hide the wallpaper (base still “exists”)
canvas.background.enabled = False  # hide extras only — base still draws
```

### Remove / replace

**Extras** (`Stars`, `Clouds`, `Tunnel`, …) — the handle detaches itself. Stack `remove` is the same action:

```python
stars.remove()
canvas.background.remove(stars)    # same
canvas.background.clear()          # extras only; base untouched
canvas.set_fly(None)               # same: clear extras
```

Idempotent if it is already off the stack. Does not restore anything else; other extras stay. After `remove`, the Python object still exists (`canvas.background.add(stars)` puts it back).

**Base** (`SkyGradient`) cannot be `remove`d or `clear`ed. `sky.remove()` raises `TypeError`. Replace it:

```python
canvas.background.base = Color("navy")
canvas.background = "navy"         # same: assignment replaces base
Wallpaper("bg1.jpg", fit="cover")  # image base (construct-to-place)
canvas.background.reset_base()     # default black wallpaper
SkyGradient("day")                 # constructing another wallpaper replaces base
```

A displaced wallpaper is orphaned unless you kept the reference. You can put an extra onto base (it leaves the extra list):

```python
canvas.background.base = stars
```

`.add` on an already-placed instance is idempotent. `canvas.set_fly(Tunnel())` clears extras and keeps that one field (does not touch base). `add` returns the instance.

### Delayed placement / extra wallpaper wash

```python
wash = SkyGradient.temp("sunset")
canvas.background.add(wash)        # extra on top of current base (author-set alpha)
wash.remove()                      # drop that extra wash; base untouched
```

---

## Practical pattern

```python
sky   = SkyGradient("night")
stars = Stars(density=0.9, twinkle=0.3)
clouds = Clouds(amount=0.45)

vignette = Vignette()
bloom    = Bloom()
grade    = Grade("cool")
wash     = Wash()

def update(dt):
    clouds.amount = 0.4 + 0.1 * math.sin(clock.time * 0.2)
    bloom.intensity = 0.4 + 0.4 * abs(math.sin(clock.time))
    if keyp.once("SPACE"):
        canvas.flash(0.45)         # hit; not wash.pulse()

    if keyp.once("H"):
        stars.enabled = not stars.enabled
        bloom.enabled = not bloom.enabled

    if keyp.once("X"):
        grade.remove()
        clouds.remove()
```

---

## Related: SpatialFx (`Fire`, `Rain`, `GlowSpot`, `Orb`, …)

Same construct-to-place idea, different stack. Those are registered objects (like shapes): hide with **`fx.visible = False`**, soft-remove with `undraw()`, hard-remove with `destroy()`. They are not on `canvas.effects` or `canvas.background`.
