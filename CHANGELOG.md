# Changelog

What changed for authors, one section per release. Versions follow
`MAJOR.MINOR.PATCH`. While Scena is 0.x, a **minor** release (0.6.0) may break
author code and a **patch** release (0.5.1) never does. The policy for breaking
changes: [Scena Design.md — Compatibility and versions](design/Scena%20Design.md#compatibility-and-versions).

Each release lists **Breaking** (before → after, and the error the old
spelling now raises), **Added**, **Fixed**, and **Documentation** (changes to
the docs and the repository a reader notices). A section with nothing in it is
left out.

## Unreleased

### Breaking

- `EquilateralTriangle` is now `Triangle`, equilateral by default and
  isosceles with `base_ratio=` (one class: the old name would have been a
  second spelling of `Triangle()`). Before:
  `EquilateralTriangle(center=(440, 480), radius=48, angle=90)`. After:
  `Triangle(center=(440, 480), radius=48, angle=90)` — the same keywords,
  models, `angle` (the apex heading) and vertex order. With
  `from scena import *` the old name is gone (`NameError: name
  'EquilateralTriangle' is not defined`); `scena.EquilateralTriangle` /
  `from scena import EquilateralTriangle` raise with the fix: `TypeError:
  EquilateralTriangle was renamed to Triangle in 0.9.0 (equilateral by
  default; base_ratio= makes it isosceles). Write Triangle(center=…,
  radius=…).` (a subclass: `Write class Nave(Triangle).`).
- `Triangle(n=…)` raises `TypeError` with the fix (`RegularPolygon(n=…)`);
  `EquilateralTriangle(n=3)` was accepted. `Triangle` is no longer an
  `isinstance` of `RegularPolygon` (an isosceles triangle is not regular);
  `RegularPolygon(n=3)` is still the regular triangle.
- `Triangle(box=…)` fills the box: the apex at the middle of the far side,
  the base along the near side, `base_ratio` set by the box.
  `EquilateralTriangle(box=…)` put its center (the centroid) on the box's
  center, inside the box's inscribed circle, so the apex touched one side
  and a gap opened on the other. To keep an equilateral triangle, write
  `Triangle(box=…, base_ratio=1)`: the largest one that fits, centered
  (in an 80 × 40 box: radius 23.1, not 20). With `radius=` or `side=`
  nothing changes (the box only centers it).
- `base_ratio` is now a Triangle field: on any other kind,
  `x.base_ratio = …` raises with a hint (it was a plain attribute nothing
  read), like `circle.width = …`.
- On a Graphic (Rect, Circle, Text, Sprite, … and their subclasses),
  writing a built-in name the kind does not have raises `AttributeError`:
  `rect.text = "hi"` → `Rect has no field 'text' (a Text field). A field of
  your own needs another name.` The names: `text`, `background`, `align` (Text
  fields), `frame`, `hitboxes`, `offset`, `tilt`, `art_angle` (Sprite fields),
  `soft_edge` (a SpatialFx field), `model` on a Text, and `collider` (no kind
  has it: the collider is `.hitbox`). Before, the write stored a value nothing
  in Scena read, so `rect.text = "hi"` showed nothing, while `rect["text"] @=
  …` already refused. A program that kept its own data under one of these
  names on a shape or sprite (`self.frame = 0` in a `Rect` subclass) now
  raises at that line: rename the field (`self.quadro = 0`). A bare `Entity`
  keeps them as plain fields. `=` and `@=` give the same words for every
  missing built-in name, sizes and looks included (`circle.width = 20`:
  `Circle has no field 'width'. Size it with radius.`).
- The same on the UI widgets (Button, TextInput, DropDown, Slider,
  CheckBox, Menu) and the spatial effects (Fire, Sunburst, Starburst, Rain,
  Jet, Sparks, GlowSpot, Orb, Warp, Portal): writing a built-in name the kind
  does not have raises `AttributeError` with the fix. `button.text = "Play"`
  → ``Button has no field 'text' (a Text field). Its caption is `.label`. A
  field of your own needs another name.``; `slider.center = (100, 50)` →
  placed by `top_left=(x, y)`; `fire.width = 60` → `Size it with radius.`;
  `jet.center = …` → placed by `p1=` / `p2=`; `fire.color = …`,
  `button.color = …` and `checkbox.frame = 3` say the kind has no such field.
  Before, the write stored a value nothing drew. The fields these kinds have
  keep working (`button.width`, `checkbox.size`, `fire.soft_edge`,
  `orb.glow`, `portal.angle`, …). A program that kept its own data under one
  of these names on a widget or an effect (`self.color = "orange"` in a
  `Fire` subclass) now raises at that line: rename the field. A bare
  `Entity` and an `Act` keep them as plain fields.

- `v *= k` and `v /= k` change the vector itself, as `v += w` always did.
  Before, they made a new vector and rebound the name: after `a = v; v *= 2`,
  `a` kept the old value; now `a` is `v` and reads the new one. Through a
  holder nothing changes (`ship.vel *= 0.9`, `st.pos *= 2` still give the new
  value to `ship.vel` / `st.pos` and to what reads them). A vector that is
  linked or computed now refuses `*=` like `+=` (`LinkedAttributeError` /
  `DerivedAttributeError`) instead of being replaced. To keep the old vector,
  copy first: `a = Vec2(v.x, v.y)`.
- A `Point` is a place, not a displacement: `v += p`, `v -= p` and `v - p` raise
  `TypeError: Cannot add Vec2 and Point: a Point is a place, a Vec2 a
  displacement. The vector between two points is p - q; to move a point by a
  vector, write p + v (v + p is that place moved too).` (`p - v` for subtract).
  Before, `v += p` added the point's coordinates to the vector and `v - p` gave
  a Point at `v - p`. `v + p` and `p + v` (the place moved) are unchanged.

### Added

- `run_task(fn)` runs an `async def` from anywhere: a sequence of waits
  without a mode. Before, `await` worked only in an async mode, so a script
  with no classes needed a host actor (`label.goto_mode(show)`), and a job
  beside an actor's modes (a power-up that counts down while the ship flies
  and gets hit) needed a chain of `after` calls sharing one `name=` slot.
  Now:

  ```python
  async def show():
      await box.move_to(600, 300, time=0.5)
      await wait(0.2)
      await box.rotate_by(90, time=0.3)

  button.on_click = lambda: run_task(show, name="show")   # a new click restarts it
  ```

  The first step runs at the call, the rest in later frames. The owner is
  the one `after` picks (an actor's method or a lambda over its `self`: that
  actor; inside a mode body: that mode; otherwise the act); `ship.run_task(fn)`
  makes `ship` the owner (`fn` gets the ship if it takes a parameter). Work
  the task starts ends when the task is cancelled (`h.cancel()`, `name=`,
  its owner destroyed); a task that finishes leaves it running. `await h`
  returns the task's value; tasks work in `parallel` / `race`. Refused with
  the fix: `run_task(show())`, a plain `def`, a mode (`@on_mode`). Event
  handlers still take a plain `def`: start the task from it. A game task
  (started at the top of the file) cannot pause, so an act's ownerless
  `run_task`, `after`, `every`, `tween` or `play_sound` with its `name=`
  raises with the fix (another name, or cancel the game's task first)
  instead of ending it for good; a game *timer* with that name still pauses
  for the act and comes back at the change.
- An async function called without `await` says so where it happens. Before,
  `self.flash()` written for `async def flash(self)` ran nothing and Python
  printed `coroutine 'Ship.flash' was never awaited`, often at a later line.
  Now it is a SCENA WARNING on the banner and the console, at the line that
  made the call: `flash() was called at game.py, line 12 but never awaited,
  so nothing in flash() ran. Inside async code write await flash(); …`.
  Coroutines of other libraries keep Python's own message.
- Colors, opacity, visibility and flips link with `@=`: a HUD bar can follow
  the game in its length *and* its color, with formulas only.
  `bar["width"] @= lambda: 200 * st.hp / 100` and `bar["fill"] @= lambda:
  ramp.get_color(st.hp / 100)` (`ramp = Colormap.from_colors("red",
  "lime")`); `warning["visible"] @= lambda: st.hp < 20`; `hero["flip_x"] @=
  lambda: st.facing < 0`. The fields: `color`, `fill`, `line`, `line_width`
  on shapes and Text, Text `background`, Sprite `alpha`, and `visible`,
  `flip_x`, `flip_y` (Text cannot flip; a Point takes none of them, a Track
  no `visible`). A link means `=` re-run whenever the formula's sources
  change: a linked color under a look is what `.color =` gives under that
  look. The constructors take a function there too: `Rect(color=lambda: …,
  line_width=lambda: …)`, `Text(…, color=lambda: …, background=lambda: …)`,
  `Sprite(…, flip_x=lambda: …)`. While linked, a plain write raises
  (`rect.color = "red"`, `set_color`, `set_alpha`, `visual = Paint(…)`, a
  seeded look such as `Neon("red")`, `fade_out()` on a linked `visible`),
  like any linked field; `unlink()` frees it. A formula may read these fields,
  but they are not link sources: `b["color"] @= a["color"]` raises (link
  both to the same formula). `tween()` still refuses a color, `visible` or a
  flip with the recipe (tween a color cell, `tween(st["c"], Color("blue"),
  time=1)`, and link to it: `rect["color"] @= lambda: st.c`); `line_width`
  and `alpha` tween.

- A Box copied into an Ellipse fills it, as `Ellipse(box=)` does:
  `ellipse << hero.box` takes the box's center, width, height and angle, and
  `ellipse @= (lambda: hero.box)` follows it.

- `box=` takes a formula: a shape placed in a region that moves follows it.
  `Rect(box=lambda: hero.box.beside("right", gap=8))` stays beside the hero
  as it moves, turns and grows; `Circle(box=lambda: board.cell(st.i))`
  jumps to the cell `st.i` names; `Rect(box=lambda:
  canvas.game_view.strip("top", 40))` follows the camera. It is the same
  fit as `box=region` (fill, inscribe, the Triangle's apex), done again
  whenever something the formula reads changes. A plain region still fits
  once, as before: a value copies, a formula links. For `Rect`, `Square`,
  `Concave`, `Ellipse`, `Circle`, `RegularPolygon`, `Triangle`, `Sprite`,
  `Svg` and `SpriteButton`; a sprite grows by its `scale`, so its frames keep
  one size between them. The moves refuse like on any linked shape ("its
  center follows its box= formula"); `force=True` or `unlink_all()` lets go
  of the region, and the object stays where it is. A `Text(box=)` formula
  raises with the fix (link `center=`): its width sets where lines wrap.

- `Triangle(…, base_ratio=)`: an isosceles triangle. `side` is the length
  of the two equal sides and the base is `base_ratio * side`, with
  `0 < base_ratio < 2` (1, the default, is equilateral; below 1 is sharper,
  like a ship; above 1 wider). `Triangle(center=(0, 0), side=40,
  base_ratio=0.6)` has legs of 40 and a base of 24. It is reactive (`=`,
  `@=`, `tween`), and changing it keeps what placed the triangle: with
  `radius`, the center and the apex; with `side`, the equal sides; with
  `vertex`, the apex and the sides. `radius` is the distance from the center
  (the centroid) to the apex. `box=` fills the box, with the apex at the
  middle of its far side and the base along the near side (the box sets
  `base_ratio`); with `base_ratio=` too, it is the largest triangle of that
  ratio that fits, centered. A class default works like `n`:
  `class Nave(Triangle, base_ratio=0.6)`.

- `Concave`: a box with a concave scoop — a quarter-pipe, a pinball corner
  fill, the inside corner of a race track, a half-pipe. It is placed like a
  `Rect` (every Rect model, the named points, `angle`, `box=`, `.box`).
  `scoop=` is the named point the curve is centered on: a corner
  (`"top_left"`, the default) takes a quarter out, an edge middle
  (`"top_center"` …) a half. The curve reaches the box's far sides, so a
  square box gives a quarter circle and any other box an ellipse.
  `rim=` (a number or a pair, default 0) is the solid left at the curve's
  ends: `Concave(top_left=(0, 200), width=200, height=200, rim=(20, 0))` is
  a quarter-pipe with a 20-wide deck and no step at the floor. `rim` is
  linkable (`c.rim @= …`) and scales with `scale_by`; `scoop` is fixed at
  construction (`flip_x` / `flip_y` mirror it). The curve draws as a true
  arc, `contains_point` follows it exactly, and collision uses chords within
  0.25 design units of it, so a ball rides up the ramp and comes back.
  A `Concave` is not a `Rect` (`isinstance` is false: it does not collide as
  a box). `intersections`, `closest_point`, `Track(concave)` and
  `move_along` accept it.
- Level files: the `"concave"` kind (`center`, `width`, `height`, optional
  `angle`, `scoop`, `rim`); `LevelItem.scoop` / `.rim`; `make()` builds a
  `Concave`. **Level editor:** the Concave tool (key U), drawn like a rect,
  with **Scoop** and **Rim** in the panel; Copy as code prints
  `Concave(…, scoop='top_right', rim=(20, 0))`.

- Level files: the `"triangle"` kind (`center`, `radius`, optional `angle`,
  `base_ratio`); `LevelItem.base_ratio`; `make()` builds a `Triangle`.
  **Level editor:** the Triangle tool (key D), drawn from the center to the
  apex like a regular polygon, with **Base ratio** in the panel; Copy as code
  prints `Triangle(center=(800, 300), radius=20, angle=90, base_ratio=0.6)`.
  The left toolbar now reads Polygon, Triangle, Regular polygon, Track,
  Concave, and the Polygon icon is an irregular outline (it looked like the
  Regular polygon tool's).
- A level item in another model: `LevelItem.length` and `.angle` on a line
  (the direction `p1 → p2`, as `item.make()` reads them), so a line drawn in
  the editor becomes a pendulum fixed at `p1` in one line:
  `Line(p1=item.p1, angle=item.angle, length=item.length)`. A rect already
  had every named point on `item.box`
  (`Rect(top_left=b.top_left, width=b.width, height=b.height, angle=b.angle)`).
  The Guia's Level section shows the recipes. A shape in a constructor is
  still its center as a point: `Rect(p1=bloco, …)` does not copy `bloco`.
- A refusal on a computed field shows the constructor call that rebuilds the
  shape with that field as an input, read from the shape. Before:
  `… or build the rect with top_left=: Rect(..., top_left=...)`. Now:
  `… or build the rect with top_left=: Rect(top_left=rect.top_left,
  width=rect.width, height=rect.height, angle=rect.angle)`. It keeps the
  shape's other inputs where it can, its heading, and what the copy needs
  besides (`n`, `scoop` and `rim`, `base_ratio`, an arc's `spread`).
- **Level editor:** Smooth (tracks) and Base ratio (triangles) are a slider
  with a number box beside it. Dragging redraws the shape as you go and is
  one undo step; typing a number works as before.

- **Level editor, several items selected:**
  - A frame with **corner handles and a rotate knob**. The corners scale
    the items evenly (a circle stays a circle, an image keeps its shape;
    the dragged corner snaps to the grid). The knob turns them about the
    frame's center in 15° steps (Shift: free). Locked items stay where they
    are.
  - **Row** and **Column** put the items edge to edge with no gaps, from
    the leftmost (Row) or lowest (Column) one. This helps with image tiles
    whose size is off the grid.
  - **X / Y** fields move the selection, and the **Groups** field edits the
    groups they all share (below).
- **Level editor:** Alt+drag (Option+drag on macOS) moves copies and leaves
  the originals in place. Holding Cmd (macOS) or Ctrl while moving keeps the
  move straight, horizontal or vertical, so a copy lines up with its original.
- **Level editor:** **Select group [▾]** in the top bar selects every item
  in a group, and None selects nothing. It shows the group's name while the
  selection is exactly that group's items, and None otherwise.
- A `DropDown` list too long for the window now stops at the window edge
  and scrolls with the mouse wheel or trackpad, with a scroll bar on the
  right; opening it shows the current option. Before, the rows past the edge
  could not be reached. A list that fits looks the same. This also fixes the
  editor's **Select group** with many groups.
- **Level editor:** the Groups field takes ";" between names as well as
  "," (a group name can no longer hold ";" by accident).
- **Level editor:** after a groups edit, the status bar says what changed. A
  name with a space shows as «moving enemies» (one group). A new name close
  to an existing group gets a hint: `"plataform" is a new group. Did you
  mean 'plataforma'?`.

### Changed

- When something an async mode or a task awaits is cancelled from outside
  (the actor it moves destroyed, another move on the same property), the
  warning now says what it was awaiting, at which line, and why it ended:
  `task show() was silently cancelled: the tween it was awaiting at
  game.py, line 14 was cancelled (the actor it moves was destroyed)`. The
  task's own cancel stays quiet.
- The errors for an `async def` where Scena calls a plain function, and for
  `wait()` outside async code, now name `run_task(...)` next to the async
  mode.
- Async modes cost less per frame. The freeze watchdog used to switch its
  instrumentation on and off around every resumed mode, which re-instruments
  every function on the stack; it now does it once per frame for all of them.
  300 actors in async modes that wait and resume: about 3.7× less scheduler
  time per frame. Behaviour is unchanged.
- **Level editor:** with several items selected, the "Add group" and
  "Remove group" inputs are gone. The **Groups** field shows the groups every
  selected item has: type a name to add it to all of them, delete one to
  remove it from all of them. Groups only some items have are listed below
  the field (`Some: …`) and are left alone.
- A write to an act after its own `change_act` (more lines of `setup` after
  `change_act(Fim)`) still raises `DestroyedError`, now with the right fix:
  `Fase.set cannot change act Fase …: act Fase ended when the game changed
  act, and code after change_act() runs on the act that is gone. Write
  change_act(...) last, or return right after it.` It said "Guard the call:
  if actor:".
- Shape transients (`dissolve_out`, `fade_out`, `flash`, `pop`, `blink`, …,
  their `on_done`) and SpriteButton eases now run on the same clock as
  `canvas.fade_out` and the screen shake: they still play while the game is
  paused or in slow motion, but a stall (dragging the window, loading a big
  file) no longer jumps them to their end, and a shape's `fade_out` and
  `canvas.fade_out` started together end together. A game run headless now
  plays its transients the same way on every machine.
- Vector math is about 4× faster: `v + w`, `v * 2`, `vec_from_angle(...)`,
  `normalize()` and the first `.length` / `.angle` of a result build no more
  than they need (`v + w` 4.3 → 1.0 µs, `(b - a).normalize() * 3` 19 → 5 µs).
  A crowd that steers with vectors every frame (the `horda` benchmark) runs
  about 15 % faster per frame. Nothing changes in what a vector does.
- `ship.vel += w` and `ship.vel -= w` are about 27 % faster (each axis is
  written once, not twice); a gravity-well pull such as
  `ship.vel += vec_from_angle(heading(ship, hole), pull * dt)` is about 17 %
  faster. Nothing else changes: the same errors, the same values.
- `st.pos.x = 5` (a cell holding a `Vec2`) now changes the vector and tells
  what is linked to `st.pos`, as `nave.desvio.x = 5` does on a field of your
  own. It raised `AttributeError` (assign a whole value:
  `st.pos = Vec2(5, st.pos.y)`), because the write would have reached no
  link; every in-place change of a cell's vector now does. The old spelling
  still works. A vector that is another name for the cell's
  (`v = Vec2(1, 2); st.v = v`) changes `st.v` with `v.x = 3` too.

### Fixed

- Work an async mode started after switching its own actor to another mode,
  later in the same step (`self.mode = self.calm` then `after(1, …)` before
  the next `await`), no longer leaks into the new mode: it is cancelled with
  the old one.
- A destroyed actor says so first, whatever the arguments. `dead.move_to((nan,
  0))`, `dead.move_by()`, `dead.rotate_to("a")`, `dead.scale_by(2, force="no")`,
  `dead.add_to_group(5)` and `dead.radius = lambda: 3` raised the bad
  argument's error ("a point takes two finite numbers", "use @=") before
  `DestroyedError`, so you chased the number when the actor was gone. Every
  verb and setter that refuses a destroyed actor now refuses it before it
  checks a value; guard the call with `if nave:`.
- A state cell keeps its own copy of a `Vec2` it takes from another holder.
  `st.start = st.pos` shared the vector, so `st.pos += v` moved the saved
  start too, and a later `st.start = …` let `st.pos.x = 5` through silently.
  `st.v0 = ship.aim` (a field of your own) made `ship.aim.x = 9` raise naming
  `st.v0`, and `ship.aim += d` moved the snapshot. A vector that is linked
  (`v @= …`, `v["y"] @= …`) is copied too: the cell holds its value of now.
- A formula that reads a field of your own holding a linked `Vec2` follows the
  link. After `ship.aim @= lambda: …` (or `ship.aim["y"] @= …`),
  `Circle(center=lambda: ship.aim)` kept the value of the moment the link was
  made. `st.pos["x"] @= …` now raises with the fix, as `st.pos @= …` does:
  the link stayed on the old vector after the next `st.pos = …`, and nothing
  that read `st.pos` heard it. Link the cell: `st["pos"] @= lambda: Vec2(x, y)`.
- `w += (10**400, 0)` on a vector holding an int (`w.x = 4`) stored a number no
  float holds before raising, and every later `w.length` raised; it now raises
  and leaves `w` as it was.
- `v * 10**400`, `v + (10**400, 0)` and `v + ("a", 1)` (and `+=`, `-=`) raise
  Scena's `ValueError` / `TypeError` instead of Python's. So do `v.lerp(w, "a")`,
  `v.clamp_length(None, 5)`; `vec_from_angle(a, n, reference_vec=)` takes a
  pair as well as a `Vec2` (a pair raised `AttributeError`).
- `v * True`, `v * False` and `v / True` raise `TypeError` ("a Vec2 scales by a
  number"): a flag passed by mistake scaled by 1 or 0 silently. Every other
  place a Vec2 takes a number already refused a bool.
- `angle` and `angle_to` read from just above −180 to 180: a vector pointing
  left reads 180 however it was made. `(-Vec2(1, 0)).angle` read −180 while
  `Vec2(-1, 0).angle` read 180, and `Vec2(1, -0.0).angle` read −0.0.
- A `Vec2` refuses NaN and infinity on every door. `v << (math.nan, 0)` and a
  link that pulled NaN stored it in a vector no shape owns, and the error came
  later from whatever read it ("a point takes two finite numbers" in a formula
  reading `st.pos`). Now `<<` raises `ValueError: a vector takes two finite
  numbers`, and a linked vector raises when read while its source is bad,
  then reads normally again once the source is a number.
- Inside an `@on_change` or `@when` callback, `v += w`, `v -= w` and `v.do_rotation(a)` left
  `v.length` and `v.angle` at their old values if they had been read before.
- `v.abs_angle_to(w)` reads exactly `abs(v.angle_to(w))`: between a vector and
  itself it read about 0.000001° instead of 0.
- `ship.vel << (math.nan, 0)` (and any vector of an actor) says "a vector takes
  two finite numbers"; it said "a point takes…".
- A write to a destroyed actor names the field: `dead.vel = (5, 5)` raises
  `Circle.vel cannot change a destroyed actor … Guard the call: if dead:`; every
  field said `Circle.set` and `if actor:`.
- On the `vel` of a destroyed actor, `held += (math.inf, 0)`, `held += ("a", 1)`
  and `held.do_rotation(math.nan)` raise `DestroyedError`, as `held += (1, 0)`
  does; they raised the bad value's `ValueError` / `TypeError` first.
- `v == [3, 4]` is True when `v == (3, 4)` is: a vector compares with a list
  as with a tuple (`v + [3, 4]` already took both).
- `Vec2(x=1)` says `Vec2 takes x and y together … Write Vec2(1, 0) or
  Vec2(x=1, y=0).`; the type hints and the docstring no longer advertise an
  x-only form, which always raised.

- A cell with a formula (`st["pos"] @= lambda: …`) refuses every change of
  its vector in place, as `st.pos = …` does: `st.pos << (3, 4)`,
  `st.pos += …`, `st.pos *= 2` and `st.pos.do_rotation(90)` changed the
  formula's output without telling anything, and the next run of the
  formula put it back. They now raise `LinkedAttributeError: st.pos is
  linked — call st['pos'].unlink() first`.
- A formula that reads a field of your own holding a `Vec2` now follows the
  field. With `nave.desvio = Vec2(50, 0)` and
  `mira = Circle(center=lambda: nave.center + nave.desvio)`, a new value
  (`nave.desvio = vec_from_angle(0, 20)`, `nave.desvio *= 2`) left `mira`
  where it was, and a vector made by arithmetic (`a + b`, `vec_from_angle`)
  was never followed at all: `nave.desvio << (80, 0)`, `nave.desvio += (10, 0)`
  and `nave.desvio.x = 70` changed it and `mira` did not move, until something
  else in the formula changed. Every spelling now reaches the formula, the
  in-place ones (`<<`, `+=`, `-=`, `.x =`, `do_rotation`) included. A field
  holding a list or a dict now takes `nave.itens += [x]` and `nave.d |= {…}`
  as `st.itens += [x]` does (`nave.itens.append(x)` still changes the list
  without telling the formulas, as in `st`). A field holding an object
  (`nave.alvo = inimigo`) re-runs the formula when it gets a new object.
- `st.pos << (3, 4)` and `st.pos.do_rotation(90)` changed the vector a cell
  holds without telling what is linked to the cell; they now do, as
  `st.pos += …` did. `st.pos += v` is also about 40 % faster.
- A formula that reads through an object kept in a field or a cell now
  follows the object kept there now. With `nave.alvo = a` and
  `r = Circle(radius=lambda: nave.alvo.radius * 2)`, after `nave.alvo = b`
  the formula went on hearing `a.radius` and missed every change of
  `b.radius`; with `st.alvo` it never heard the radius at all
  (`st.alvo.radius = 7` left `r` as it was). It now follows `b`, and stops
  hearing `a`. The same holds for a microphone swapped in a field
  (`g.mic = other_mic`): the formula moves to the new mic's level. A formula
  linked while `st.alvo` is `None` (`lambda: st.alvo.radius if st.alvo else 0`)
  follows the object the cell gets later.

- `v += …`, `v -= …` and `v.do_rotation(…)` check the result before they change
  the vector. `w += (math.inf, 0)` stored `inf` without a word, while
  `w.x = math.inf` raised; `ship.vel += (math.inf, 0)` raised with `vel.x`
  already `inf`. Both now raise `ValueError: x must be a finite number, got inf`
  (`Circle.vel x …` for a velocity) and leave the vector as it was. A vector
  computed from its shape refuses the same way: on a `Line(p1=…, p2=…)`,
  `line.vec += (1, 0)` changed `vec` and not the line; it raises
  `DerivedAttributeError`, as `line.vec.x = 5` does.

- The velocity of a destroyed actor refuses writes, as its center does.
  `bala.vel.x = 3`, `bala.vel += (1, 0)` and `bala.vel << (1, 0)` on a
  destroyed `bala` (or on a `v = bala.vel` you kept) were accepted, so a loop
  over a list that still held destroyed bullets ran on without an error.
  They raise `DestroyedError` now, naming where the actor was destroyed.
  Reads stay: `bala.vel.x`, `bala.vel.length`. Copying from it
  (`v << bala.vel`) raises, as `v << bala.center` does.

- A misspelled short property no longer becomes a silent field of your own.
  `bola.colr = "red"`, `bola.angl = 45`, `bola.scal = 2` and `bola.fil = "blue"`
  used to store a new field that nothing reads, so nothing changed on screen.
  They now raise `AttributeError: Circle has no 'colr'. Did you mean 'color'?`.
  The rule: a new name one letter away from `color`, `fill` or `line` holding a
  colour, or from `alpha`, `angle`, `scale` or `width` holding a number. Real
  fields with nearby names are not affected, because their values are another
  kind: `self.laser = Rect(…)`, `self.owned = True`, `self.lime = 3`. A field
  you meant to keep under such a name with such a value (`item.sale = 10`, one
  letter from `scale`) now raises too; rename it.

- A collision rule now acts the same whatever other rules pair the same
  bodies. When a body gained a tag while already touching (`hero.tag("shield")`
  inside the lava), `@collide("shield", "lava")` ran only if no other rule
  joined hero and lava; with `@collide_stay("hero", "lava")` in the game it got
  stays and never its enter. It now enters at that frame and stays from the
  next. The same for a rule declared, or an `on_collide` set, while the two
  touch. The other way round, `untag` while another rule kept the bodies
  touching never ran the rule's `@collide_exit` (not even when they separated):
  it runs at that frame now. A tag added and removed in the same frame no
  longer runs an exit when the bodies separate. One timing moves: a
  `@collide_stay` declared while two bodies touch runs from the frame after its
  first frame, like a rule whose bodies just met; give it an `@collide` too to
  act on that first frame.

- A shape's `on_hover_exit` that parks or hides the shape the pointer moved
  onto (leaving a card locks the next one) no longer lets that shape light
  up: its `on_hover` ran while it was parked or hidden. It gets its enter
  when it is back in play under the pointer.

- An `on_collide` (or stay / exit hook) an act gave a game body as a closure
  over the act ran once more after another hook of the same contact changed
  the act, on an act that was gone (a write to it raised). The act's hooks
  stop with the act; a hook that is the game's runs on, as before.

- A `SpriteButton` whose `enabled` was linked (`button["enabled"] @=
  lambda: …`) took a plain `button.enabled = False` without a word, and the
  link overwrote it at the next read. It raises `LinkedAttributeError` now,
  like every linked field.

- A flipped Sprite or Svg placed with `box=` in a turned region drew upside
  down (and a sprite with `art_angle=` drew turned the wrong way), unless the
  region's angle was exactly 0. It now turns with the region, flips kept.

- `Svg(box=…)` rasterized at the default size whatever the region, so a big
  box drew it blurred. It rasterizes at the region's size, like
  `Svg(height=…)`.

- A whole copy between kinds (`<<`, `absorb`, a whole `@=`) raised Python's
  own error and left the target half-changed: `Circle(...) << box`
  (`AttributeError: 'Circle' object has no attribute 'width'`),
  `Ellipse(...) << rect` (`ValueError: Unknown ellipse model`),
  `Triangle(...) << box`, `line << rect`, `polygon << rect`. A copy now takes
  only what the target can be (a Rect any Rect, Square, Concave or Box; a
  Triangle a regular triangle; a Polygon any polygon with as many points) and
  refuses everything else before changing anything, with a `TypeError` that
  names the fix: `Circle(box=box)`, `rect << ellipse.box`.

- `box=` on an author subclass of `RegularPolygon` (`class Hex(RegularPolygon)`)
  now takes the box's angle, as `RegularPolygon(box=…)` does; it compared
  class names and missed subclasses.
- The drag gestures as class methods work like `on_click`: `def
  on_drag_to(self, alvo, pos)` and `def on_drag_over(self, alvo, pos)` make
  the object draggable, and `def on_drop_by(self, peca, pos)` makes it
  droppable. Before, the methods turned nothing on, and with `draggable =
  True` set by hand `on_drag_to` received `(self, alvo)` instead of
  `(alvo, pos)`. A method that also asks for the dragged piece
  (`on_drag_to(self, peca, alvo, pos)`) now raises `TypeError` when the
  object is made.
- A body moving into a concave shape that collides as several pieces (a
  concave `Polygon`, a `Concave`) is no longer stopped on the shape's
  outer hull. A ball rolling into a U-shaped `Polygon` dropped onto the
  hull's top instead of into the notch, and a ball rolling into a curve was
  thrown off along the straight line from its foot to its top. `resolve()`
  now sweeps such a shape piece by piece.
- The key that opens a text box no longer types itself into it: with
  `on_key_down` focusing a `TextInput` when T is pressed ("press T to chat"),
  the box started with a "t" in it. A game key held while a box takes focus
  no longer auto-repeats its character into the box either. A typed
  character now follows its key: when the box did not get the key, the
  character goes to `on_char`. Typing in a focused box, Shift and composed
  text (an input method's) type as before.
- A body that touches two partners at once with `resolve(..., bounce=)` (a
  ball on the seam between two bricks, a corner) is answered by both
  together. Before, the partner made first answered alone: a ball sent
  straight up into a seam left 7° to 60° off to one side, the side set by
  creation order, and a symmetric hit did not leave symmetric.
- A bounce keeps the rest of its frame's travel. The part of the frame left
  after the hit was dropped at every bounce, more or less by frame rate: a
  ball in a box ran 3–6 % slow at low frame rates, and a `bounce=1` ball
  dropped from 200 came back to 190 at 30 fps (198 at 144). Bouncing balls
  now take the same time and height at every frame rate. With `bounce=0`
  nothing changes.
- A brick broken in `@collide` bounces the ball where the ball touched it,
  as a whole brick does. Before, the ball went on into the brick's space for
  the rest of that frame, a frame of travel off its path, and a ball near
  the seam of two broken bricks could be sent off at a wrong angle. A brick
  broken the frame after its `@collide` (a mark in the handler, the
  `destroy()` in `update`) also bounces the ball: if the ball ended the
  frame a hair short of the brick, it flew through it (2–5 % of hits).
- `@=` on a built-in name says what the name is on that kind, the same on
  every kind: `rect["text"] @= …` raises `Rect has no field 'text' (a Text
  field)`, `circle["width"] @= …` says `Size it with radius`,
  `rect["color"] @= …` says it is a property set with `=`, `rect["name"] @= …`
  says it is read-only. Before, Rect, Circle, Sprite, Text and the other
  kinds said "appearance and built-in properties stay outside the reactive
  graph" even for a field they do not have; only Line and Point named it.
  What links and what refuses did not change.

### Documentation

- A new interlude after tutorial 25, Eventos e processos: one page that ties
  together what the series taught in pieces about time. A crossing with a
  traffic light, cars and pedestrians shows the frame and its phases, a
  question read every frame (`keyp`) against a notice (`on_key_down`), the
  Handle that `every` returns (`pause` / `resume`), the light's cycle first
  as three chained `after` calls and then as one `async def` run with
  `run_task`, `name=` as a slot (a night-time blinking cycle replaces the day
  cycle), each pedestrian in an async mode that waits with `until` and gives
  up with `race`, and a click that changes the mode and so cancels what the
  old one started. Closing boxes: mode or task, who owns each process, which
  tool for which job, and the common mistakes with time. The cars and
  pedestrians come from the new CC0 `racing/` folder (Kenney's Racing Pack),
  listed in `examples/media/CREDITS.md`.
- A new tutorial after Giros, 30 Duelo: a game for two players on one
  keyboard. Each ship rides a curved rail from the level file
  (`trilho.at(u)`, `angle_at`) and steers like a wheel, both with `chase` as
  weight; the keys of each player live in a dictionary; lasers bounce three
  times (`resolve(…, bounce=1.0)` with a counter in `@collide_with`) and
  bend near a `Warp` whose pull falls with the cube of the distance; a
  barrier of crates, asteroids that split in two, electric rays between two
  balls on an upright eight (`Track.eight(angle=90)`, `phase=`), a star
  whose power-up flies on a `Track` built on the spot (`zigzag`,
  `speed=`), a shield, and a ship-choice act. `examples/duelo.py` is the
  last step; the arena is the new CC0 `levels/duelo.json`.
- Tutorial 10 (Bolas) ends in a new step, "O velocímetro": a bar in the
  window (`layer="ui"`) shows the golden ball's speed. Its width and color
  are `@=` formulas on `escolhida.vel.length`, the color sampled from a
  `Colormap.from_colors("lime", "gold", "red")`, so the bar changes at
  every ball-ball hit with no line that copies the speed.
  `examples/bolas.py` is that step.
- A new interlude after tutorial 14, Girar e crescer: `rotate_to` against
  `rotate_by` (and why `rotate_to(360, time=1)` does not move), the `angle`
  field against the verbs (the field keeps the point the shape was placed by,
  the verbs turn about the center or `about=`), a box held by two anchors that
  leans and changes size beside a free one that turns whole, and the same
  to / by pair for size (`scale_to`, `scale_by`, `scale =`). Appendix F no
  longer says a `Rect`'s `angle` always turns it about its center.
- The README (GitHub and PyPI) is rewritten: 2D games first, what an author
  writes and what Scena takes care of, new sections (geometry, rules and time,
  collision, mouse and widgets, the level editor), one look on a circle, a
  pentagon and a sprite, and Ninja IV and Connect Four in the gallery. Every
  clip is recorded from the code beside it, the editor's included.
- Each release now has a GitHub Release with `scena-examples.zip`: the
  examples and only the images and sounds they use (about 17 MB instead of the
  whole repository). The README links the latest one.
- Tutorials, restructured (the page addresses change):
  - **New chapters:** 12 Movimento (a ship that flies where you click:
    placing or travelling with `time=` / `speed=`, `ease=`, `face=`,
    `on_done=`, the trip's control with `cancel`, and following the mouse
    with `approach`) and 20 Colisão (a lab: the three phases of a touch,
    `query_point`, `query_circle`, `raycast`).
  - **Interludes**, short concept pages between two tutorials: Grupos after
    05 (`count`, `empty`, `nearest`, `filter`, `count_where`, `any`) and
    Ganchos na classe after 11 (every hook in a class, and an `Entity` with
    no drawing that owns its timers).
  - **Appendix G** Imagens e hitboxes: the common ways to load images (one
    file, a file per frame, a strip, several animations, an atlas, SVG) and
    the hitbox shapes, with figures. Appendix C points there.
  - The old 12 Órbitas is split into 13 Trilhas and 14 Órbitas, where the
    moon leaves a trail kept by a `History`. Giros moves to the end (29), and
    the oscilloscope says the trigonometry can be skipped. Every other
    tutorial from 14 on moves up one or two numbers.
  - Interação (11) has a third script, the mouse on the canvas
    (`on_mouse_click`, `on_mouse_double_click`, `on_mouse_drag`,
    `on_mouse_scroll`). The Piano (22) plays a click through the key's own
    `on_click` and ends with an equalizer (`audio.spectrum`). Fórmulas (09)
    builds the trap of a `lambda` inside a `for` (fixed with `lambda i=i:`)
    and ends with its ideas in light boxes instead of a dense list of rules.
  - New boxes: the `Text` options and a `TextInput` bound to a cell (04),
    a cap on the fleet's shots with `count` and `.empty` (05), a named
    `tween` (14). Lists of parallel items are tables (Appendix A's debug
    keys, Appendix F's shape models), and lists in the prose are spaced.
  - A pass over every page trims what a beginner does not need there
    (rare error names, special cases, asset sizes, re-explanations of an
    earlier tutorial) and keeps the explanations in full prose. `@on_change`
    is now taught in 08, where the shield needs it; Appendix F lists the
    line models in a table.

- Guia, "Quebrou no contato": where the ball bounces off a brick it breaks
  (where it touched, also when the brick breaks a frame later), and that two
  bricks at a seam answer together.

## 0.8.1 — 2026-10-14

### Added

- `Shield(color)` on the bubble style (the default): the same lime film,
  turned to that color (`Shield("cyan")` is a cyan bubble). Without a color
  the bubble is unchanged. In 0.8.0 a color on the bubble was taken and
  ignored; code that passed one now draws in it.
- `move_by(distance=d)` without `angle=` moves forward, along the object's
  `angle` (read at the call); a negative distance backs up without turning.
  Before, it raised and you wrote `move_by(angle=x.angle, distance=d)`.
  `face=True` in this form raises with the fix (the direction already is the
  heading; on a back-up it would flip the object every call).
- `approach(current, target, speed)`: the sibling of `chase` that moves at a
  constant speed (units per second) and lands exactly on the target, never
  past it. Called in `update`, it pursues a moving target at a fixed speed:
  `inimigo.move_to(approach(inimigo.center, jogador.center, 120))` replaces the
  hand-written distance / normalize / clamp. Points step in a straight line
  (pass the whole point, not x and y apart); numbers work too
  (`bar.width = approach(bar.width, hp * 2, 80)`).
- `speed=` on the timed verbs that cover a distance: `move_to`, `move_by`,
  `move_along`, `rotate_to`, `rotate_by`, `reset_rotation`, and the camera's
  `pan_to` / `pan_by`. Give the speed instead of the duration (units per
  second, or degrees per second on a turn) and the trip lasts distance ÷
  speed: `hero.move_to(mouse, speed=200)` takes longer the farther it goes,
  and enemies returning to their slots with the same `speed=` all fly at the
  same pace. The distance is read once, at the call; after that it is the
  same trip as `time=` (`ease=`, `loops=`, `yoyo=`, `on_done=` all work; with
  an `ease`, `speed` is the average). `time=` and `speed=` together raise.
  `move_along` now takes either one (before, `time=` was required).
  `scale_*`, `zoom_*` and `tween` have no `speed=`. Like `time=`, it does
  not follow a target that moves: for that, `approach` in `update`.
- A point unpacks: `x, y = ship.center`, `tuple(p)`, `print(*p)`, and the
  same for a `Vec2` (`x, y = v`) and the `mouse` (`x, y = mouse`). The names
  get a copy of the two numbers (like `track.at()`): they do not follow the
  point. Before, it raised "field name must be a str, got int". Passing the
  point itself is unchanged: `center=p` copies, `center @= p` and
  `lambda: p` follow. `p[0]` raises `TypeError` naming `p.x` (a point has no
  index), and `x, y = ship` points to the object's position (`ship.center`).

### Changed

- `Text(st["score"])` shows the cell in one direction, like
  `placar["text"] @= st["score"]`. Before, the text *was* the cell, so
  `placar.text = "oi"` silently wrote `st.score` (a display that changed the
  game state, and a later `st.score + 1` failed far away). Now that write
  raises `LinkedAttributeError`, naming the cell: to change what the text
  shows, change the cell (`st.score = 7`). `SpriteButton(label=st["vidas"])`
  follows the same rule. If you wrote to such a text on purpose, write the
  cell instead, or call `placar["text"].unlink()` first. Widgets (`Slider`,
  `CheckBox`, `TextInput`, …) still write to their cell: editing it is their job.
- `canvas.cull_offscreen` is now `True` by default: Scena skips drawing what
  is outside the view. A level bigger than the window draws much faster (1500
  tiles: 3 ms instead of 8; tutorial 25 about 9 % faster per frame). A game
  on one screen stays the same: a layer where nothing is off screen tests
  again only every few frames. Objects off screen still run `update` and
  collide, as before. `canvas.cull_offscreen = False` draws everything.
- One rule for color: a visual that takes `color=` shows `set_color`; a
  visual that takes none (`Flame`, `Water`, `Swell`, `Shield(style="nebula")`
  and the other fixed-palette shield styles) keeps the color, warns, and
  shows it once the visual is removed. New under the rule: `set_color` on a
  shape wearing a bubble `Shield` (with or without a color) turns the bubble
  to the new color; before, it warned and stayed lime. `Metal()` and
  `Shield()` without a color keep their own palette and leave the shape's
  color as it was.
- `set_color` (and `.color =`) on a shape wearing a visual made with a
  color (`Laser("red")`, `Rim("gold")`, `Ink`, `Gel`, `Sphere`, `Bolt`,
  `Extrude`, `Halo("blue", style="line")`, `Shield("cyan", style="bands")`
  and every other visual that takes `color=`) turns the visual to the new
  color, and from then on it follows the shape, as `Neon("red")` and
  `Halo("blue")` already did. Before, the visual kept drawing its first
  color, and the new one showed only once the visual was removed. To go back
  to the first color, set the visual again: `shape.visual = Laser("red")`.
- `set_color(X)` gives the shape what `color=X` gives, whatever visual it
  wears: the interior X and the outline derived from it (darker on a light
  color, lighter on a dark one). An outline visual (`Rim`, `Laser`, `Ink`,
  `Halo`, `ElectricBolt`, `Tracer`, …) follows that outline, so after
  `set_color("red")` a `Rim()` draws the pinkish rim of
  `Circle(color="red")` with `Rim()`. Before, `set_color` under an outline
  visual put X itself on the outline, and the shape kept that outline after
  `visual = None`. For an outline in X itself: `Rim("red")` or
  `.line = "red"`.
- The color of an outline visual is the shape's outline only: `Rim("red")`
  draws and leaves what `.line = "red"` and then `Rim()` do. Once the
  visual is removed, the shape keeps its own interior and a red outline;
  before, the interior turned red too. `Halo("red", style="soft")` keeps
  the shape's interior (before, it painted it red), and
  `ElectricBolt("red")` no longer mixes the shape's old outline into the
  bolt. Body visuals (`Neon("red")`, `Gel`, `Metal("gold")`, …) are
  unchanged: their color becomes the shape's color.
- Comparing a Point with a position now warns. `==` on a Point compares the
  object, not its position, so `elevador.center == (400, 120)` was always
  False (and `!=` always True), even with the elevator there, and nothing
  said so. It still is: Points stay objects, which sets, dicts and the engine
  rely on. What is new is a warning in the console (a Python `RuntimeWarning`
  pointing at your line), once per line, when your code
  compares a Point with a tuple, a list or a `Vec2` (either side), or with
  another Point at the same position. To test the position:
  `distance(elevador.center, (400, 120)) == 0`, or `< 1` when the motion
  does not land exactly. For the same object: `a is b`. The undocumented
  `Point.eq()` and `Point.get_hash()` are gone (`get_hash` hashed the
  position, which changes when the point moves): use `distance`.
- Every `@collide` / `@collide_stay` handler of a contact runs, also after an
  earlier one destroys (or parks) one of the two: the later ones get the dead
  object, which can still be read (`destroy()` on it again does nothing).
  Before, the rest of that contact's handlers were skipped, so with a `Tiro`
  whose `@collide_with("inimigos")` does `self.destroy()` and an `Inimigo`
  whose `@collide_with("tiros")` destroys itself and scores, a hit scored or
  not depending on which of the two was made first (the same with a module
  `@collide` next to a class method). A body destroyed in a contact still
  starts no other contact that frame (one shot hits one enemy), and a
  `change_act` in a handler still stops the leaving act's handlers. The
  contact's `@collide_exit` now runs after its remaining handlers, so an
  enter `+= 1` / exit `-= 1` counter reads enter, then exit (before, the exit
  ran inside the `destroy()`, ahead of them). Still inside its `destroy()`,
  while it exists: the destroyed object's own exit hooks (`on_collide_exit`,
  `@collide_with_exit`) and the exits of its other contacts.
- Shift held no longer hides a bare key: `keyp("RIGHT")`, `keyp.once("SPACE")`,
  `"SPACE" in keyp` and `on_key_down("SPACE")` / `on_key` read True / arrive
  while Shift is held, so "hold Shift to run" keeps walking and jumping.
  Before, any modifier hid the key (the Guia said "sem Shift / Ctrl / Alt /
  Cmd"). Ctrl, Alt and Cmd still hide it (they make shortcuts). What else
  differs: with Shift and R held, `keyp("R")` and `keyp("SHIFT+R")` are now
  both True (a game that reads both should test the chord first, or use
  `keyp.only("R")`, which stays exclusive: no other key, Shift included); a
  chord stays exact (`keyp("CMD+Z")` is not Cmd+Shift+Z); pressing Shift
  under a held key is not a new press of that key (`once` does not fire
  again).
- `mouse.press(button)` reads False while a HUD widget owns that press
  (dragging a `Slider`, holding a `Button` or a `SpriteButton`, enabled or
  not, on any layer), until the button goes up, as a
  focused `TextInput` hides its keys from `keyp`; `mouse.click_pos` does not
  record such a press. A paint app that paints while
  `mouse.press(Mouse.BTN_LEFT)` no longer paints under the slider or a tool icon. A press on
  any other shape or sprite (your own drag or click target) still reads True.
- A drag drops across the HUD and the world: the drop target is the topmost
  `droppable` under the pointer, `layer="ui"` first, then the world, whichever
  space the drag started in. A HUD inventory seed dropped on a world plot
  gets `@drop_by`, and a world piece dropped on a HUD bin too. Before, a drag
  saw only targets in its own space (`to` was `None`, no `@drop_by`). `pos`
  is in the space of the shape whose handler runs: the dragged shape's for
  `@drag_to` / `@drag_over`, the target's for `@drop_by` (the same point when
  both share a space, or with no camera).
- A lambda (or a nested `def`, or a `functools.partial` of `self`'s method) that uses `self`
  inside an actor's method is owned by that actor, like the method itself:
  `after(0.1, lambda: self.set_color("red"))` in `on_update` now ends when the
  actor is destroyed, as `after(0.1, self.piscar)` already did. Before, it
  belonged to the act: it ran after the death and raised `DestroyedError`, or
  made a destroyed enemy fire one last shot. Applies to `after`, `every`,
  `on_done=` and `play_sound(on_done=)`. Inside the actor's own `on_destroy`
  such a lambda keeps running after the death ("after I am gone" work). A
  lambda that uses another actor (`lambda: alvo.destroy()`) is unchanged.
- An act's `@=` on an object made at the top of the file leaves with the act:
  `hud["text"] @= lambda: f"Pontos {st.pontos}"` in `Fase.setup` is undone at
  `change_act`, and the field gets back what it had (the game's own link, or
  its value: `hud.text` is `""` again). A restart links again without the
  "overrides its previous link" warning, and the next act can write
  `hud.text = "NAVES"` (it raised `LinkedAttributeError`). A formula that
  reads an act object or the act itself leaves the same way, now without a
  SCENA WARNING.
- The "received a formula that overrides its previous link" warning is a
  SCENA WARNING (the amber banner) and names the unlink spelling
  (`Text['text'].unlink()`).
- A class-body method the engine would never call raises `TypeError` at the
  class line, naming the right hook: a method named `update` (any signature,
  even a helper `def update(self)`) in any actor or act class (`update` is
  Scena's own recalculation of linked fields; the per-frame hook is
  `on_update`; on a Shape or Sprite, `update` replaced
  Scena's own recalculation and the object crashed when made, with "missing 1
  required positional argument: 'dt'"); a top-of-file input function
  (`on_key_down`, `on_mouse_click`, …) in a class (in an act: `keyp.once` /
  `mouse.press()` in `on_update`; on an actor: `on_click`); a name one letter
  from a hook (`on_colide`, `on_updat`, `on_destory`) or another engine's
  name (`on_collision`); a plain method named `collide_with`. Before, the
  method was never called and nothing said so. Your own helpers (`on_hit`,
  `on_frame`) are fine.
- `obj["name"] @= …` on a name the object already has as a method, a
  read-only or settable property, or a size / point word its kind lacks
  (`circle["move_to"]`, `tri["points"]`, `poly["pointer_hover"]`,
  `rect["box"]`, `circle["top_left"]`) raises the same error as
  `obj.name = …`. Before, it made a new field of your own that nothing read,
  so the link did nothing. `poly["v1"] @= …` and `poly.v1 = …` raise too,
  naming the vertex spelling `poly.points[1] @= …`. If you used such a name
  as a field of your own, rename it.
- `clone(frame=)` on a kind without frames (shapes, `Svg`, `Text`) raises
  `TypeError`; it was ignored.
- A body standing on a moving platform now moves with it, sideways too, at
  any frame rate: `resolve(heroi, "elevador")` and an elevator moved by
  `move_by`, `move_by(..., time=)` (eased, yoyo) or `move_along` carries the
  hero the whole way, and the hero's own walk adds to it. Before, the carry
  depended on the frame rate: 97 % of a sideways lift at 30 fps, 87 % at 60,
  about 1 % at 240 (the lift slid out from under the hero). A wall in the
  lift's way still stops the hero, and a jump ends the ride. Tutorial 25's
  sideways elevator ("O ninja em cima vai junto para os lados também") now
  does what it says. If your code carried a rider itself (copying the lift's
  speed into `heroi.vel`, or `heroi.move_by(...)` with the lift's step), the
  hero now moves twice: delete that line. Only a platform carries: a `STATIC`
  body, or a movable one without `.vel`; a crate pushed along the floor does
  not drag the crate on top of it. A floor moved with `move_by` under a
  standing player carries the player too, so a "move the world" runner that
  scrolls its platforms with `move_by` while the player stays put should move
  the camera instead, or place the platforms with `center =` (a placement is
  not motion: it carries nothing).

### Fixed

- `ready` held after a short release: letting the button go and pressing it again one frame after the cooldown made the next held shot come one frame early (the late frame was carried over). Now any gap in polling restarts the cadence at the `True` that ends it.
- A bracket field used as a value now raises, with the dot spelling, instead
  of misbehaving in silence. `st.score` is the value; `st["score"]` is the
  field itself, for what follows or writes it (`Slider`, `Text`,
  `@on_change`, `tween`, `@=`). Inside a lambda the dot is the only spelling:
  the lambda already keeps it live. Before, `Text(lambda: f"Pontos:
  {st['score']}")` showed `<field State(...)['score']>`, `if st["vivo"]:` was
  always true, and `@when(lambda: st["score"] == 5)` never fired. Now a
  formula with a bracket inside (`@=`, `Text(lambda)`, a constructor lambda)
  raises at the line that links it; a `@when` / `@on_change` lambda that
  returns `st["x"]` raises when it is registered; and any other use of a
  bracket field as a number or text (`+`, `==`, `bool`, an f-string, `print`)
  raises `TypeError` naming `st.score`. Relied on it: `lambda: st["score"]`
  (a bare bracket, no arithmetic) used to link, and `@on_change(lambda:
  st["x"])` used to fire; write `lambda: st.score`, or pass the field with no
  lambda: `x["r"] @= st["score"]`, `@on_change(st["x"])`.
- A `Gradient` on a `Wallpaper` (and `canvas.background = Gradient(...)`)
  now runs the way it does on a shape: `angle=90` goes from the bottom up,
  as the Guia says. Before, a Wallpaper drew it upside down:
  `Wallpaper(Gradient("red", "blue", angle=90))` was red at the **top**, while
  `rect.fill = Gradient("red", "blue", angle=90)` was red at the bottom. Your
  wallpaper flips, with no error. If you wrote your wallpaper against the old
  direction (the tutorials did), swap the colors to keep the old picture
  (`Gradient("blue", "red", angle=90)`) or write `angle=-90`. A preset sky
  reads top first: `canvas.background = Gradient("sunset", angle=-90)`.
  Only the up/down part flips: `angle=0` (left to right) and radial gradients
  look the same as before, `angle=45` now heads to the upper right, and a
  `type="sweep"` wallpaper turns counter-clockwise, as on a shape.
  `SkyGradient` is unchanged.
- A `Texture` on a `Wallpaper` keeps its `angle`, `shift=` and `set_alpha`,
  as on a shape. Before, `Wallpaper(Texture("x.png", fit="tile", angle=30))`
  drew the image unturned, and a `HueShift` / `Recolor` or a faded Texture
  drew the plain image. The angle turns counter-clockwise, about the middle of
  the screen (a tile turns about the point `(0, 0)` of the world). A turned
  `fit="cover"` image leaves its corners to the underlay, as a shape leaves
  them empty; `tile_mode="mirror"` fills them.
- The key `on_key_down(key)` receives can be written into a field.
  `st.nome = key` over `st.nome = "x"`, or `t.text = key` on a
  `Text("Aperte")`, raised `ValueError` ("on_key receives 'X', not 'x'",
  "unknown key"): the field compared its old value with the key, and the key
  compares loudly to catch `key == "ESCAPE"`. A field now stores the key as a
  plain `str` (`st` cells, `Text.text`, your own fields, `Button.label`,
  `TextInput.text`), so `st.nome != "nenhuma"` later is an ordinary compare.
  `key == "ESCAPE"` inside the handler still raises with the fix.
- `.line = X` or `.fill = X` on a shape already wearing a visual draws what
  writing it before `shape.visual = …` draws. Before, the write skipped the
  visual: under a `Rim` the rim lost its softness (`.line = "blue"` after
  `Rim()` or `Rim("red")` drew a blue rim harder and brighter than the same
  write before the look: the look's alpha was lost), and under a `Halo` the inner
  glow kept the old color. A color given to the look and a write on that
  look's channel: the later one wins. `.line = "blue"` then
  `visual = Rim("red")` draws red; `Rim("red")` then `.line = "blue"` draws
  blue.
- `.line_width`, `.blend`, `.dash`, `.line_cap` and `.line_join` written on a
  shape or sprite already wearing a visual draw what writing them before
  `shape.visual = …` draws, and stay on the shape after `visual = None`.
  Before, the value was lost when the visual was removed, and a write after
  the visual overrode the visual's own setting: `visual = Rim()` then
  `line_width = 3` drew a thinner rim than `line_width = 3` then
  `visual = Rim()`. Now a visual that sets the knob itself keeps its own while
  it is on (Rim's width, Halo's and Shield's blend, Shield's dash; change
  the rim with `Rim(width=…)`); a visual that uses the knob (`Neon`,
  `Laser`, …) follows the new value, as before. Code that set one of these
  knobs after a visual to change that visual draws the visual's own setting
  now. `Circle(visual=…, line_width=…)` sets the width before the visual.
- `set_color` on a shape wearing `Metal()` or `Metal("gold")` turns the
  metal to the new color. Before, the metal did not change and nothing said
  why.
- `Metal("gold")` has a gold rim. Before, every tinted metal kept the chrome
  outline.
- Maximized and fullscreen (`canvas.display`) keep the bands around the game
  black. Before, a body half outside the screen showed its outer half in the
  bands, and `Grain`, `Scanlines` and `Fog` drew over them.
- An `async def` handed to a function Scena asks a question raises
  `TypeError` with the fix, like the hooks in 0.8.0: a filter
  (`group["x"].filter` / `any` / `all` / `count_where`, `nearest(where=)`),
  the condition of `until` / `@when`, the target of `@on_change`,
  `resolve(only=)` and an `@=` formula. Before, its answer (a coroutine)
  counted as True: a filter kept every member, `until` ended at once,
  `@on_change` fired every frame, and Python only printed "coroutine … was
  never awaited".
- `flip_x` / `flip_y` turn `angle` by the usual rule (`180 − angle` /
  `−angle`) on a Circle placed by `p1=, p2=` or `perimeter_point=`, an
  Ellipse placed by its foci, or a Line placed by its ends, when those
  points lie on the mirror line (a vertical diameter under `flip_x`). Before,
  if `angle` had been read, it kept its old value after such a flip (450
  where a copy of the same circle read −270).
- A knob that only one style or fit reads raises `TypeError` with the fix on
  the others. Before, it was taken and drew nothing different, so code that
  passed it never did what it said. Old → new: `Shield("cyan",
  style="nebula")` (any color on the nebula, ember, void, molten, cracks or
  frost styles) → `Shield("cyan")` (the bubble, see Added) or
  `Shield("cyan", style="bands")` (also `"vortex"`, `"plasma"`), or
  `Shield(style="nebula")`; `Halo(rings=5)` / `speed=` on hollow, fill, soft or line →
  `Halo(style="pulse", rings=5)`; `Bolt(amount=6)` (style core) →
  `Bolt(style="filaments", amount=6)` (or `"tesla"`);
  `Wallpaper("bg.png", tile_size=64)` / `Texture(…, tile_size=64)` without
  `fit="tile"` → `fit="tile", tile_size=64`. The error names the style or fit
  that reads the knob. On `Halo(style="line")` the message replaces Python's
  own `HaloLine.__init__() got an unexpected keyword argument`. A write on a
  built look (`Bolt(style="filaments").amount = 6`) still raises, and its
  message now suggests the same style (`Bolt(style="filaments", amount=6)`),
  or says the style takes no such knob (`Shield(style="nebula").color = …`);
  before, it suggested `Bolt(amount=6)` and `Shield(color=…)`, and named a
  Halo or Shield style by an inner class (`HaloPulse(rings=5)`).
- Faster platformers. A Sprite tile (an opaque image, unrotated) now collides
  as an exact box, like an unrotated `Rect`: walkers and `floor_below` sweep
  against it with the closed-form test instead of the general one. A sweep
  against such a tile can stop up to ~0.04 units later than before; the new
  stop is the exact one. `floor_below` also stops re-checking every tile on
  each step of its march, and checks whether a Sprite moved about twice as
  fast. With the other `floor_below` and walker speed-ups of this release
  (below), tutorial 25's level runs about 40 % faster per frame and a level
  of 1500 tiles about 35 %.
- A body under `resolve(…, ANYTHING)` no longer falls through a body spawned
  in the same frame as an earlier one when a query (`floor_below`, a
  `query_*`) ran between the two spawns; it ignored the second one until
  something else enrolled.
- Bodies that did not move cost almost nothing to collide with: Scena now
  knows which Sprites, rectangles, circles and ellipses moved since it last
  looked, and skips the rest. A level of 1500 tiles runs about 40 % faster
  per frame; tutorial 25's level and the endless runner about 15 %.
- A game with `Neon` on moving shapes no longer grows to over 1 GB of memory:
  Scena frees GPU memory nothing has drawn for a second. A bullet hell with
  300 glowing shots now stays near 250 MB. Pictures loaded from files and
  drawn as a Sprite, a fitted wallpaper or a menu icon stay on the GPU, so a
  background shown again after a pause is not uploaded again; a tiled
  wallpaper (`fit="tile"`) and a `Texture` fill can still be freed and
  uploaded again.
- Shots and pickups that are only in `@collide` pairs no longer make every
  body of a mutual `resolve()` crowd rebuild its partner list: a crowd of 150
  that is being shot at resolves about 12 % faster.
- `canvas.cull_offscreen = True` now pays off in a world with still scenery.
  Scena keeps the off-screen test's box of a body that did not move or change
  its look, so a still tile, platform or circle costs almost nothing to test.
  A level of 1500 tiles draws in 3 ms instead of 8. 130 still circles in a
  world 4× the window draw ~2.5× faster. A body that only moved reuses its
  box too, shifted by the move: with culling on, 25 bouncing balls draw
  about 20 % faster and a bullet hell of 300 glowing shots about 8 % faster
  per frame. A body that turns or changes size every frame still costs about
  what drawing it costs.
- Sprites on screen draw faster when they did not change since the last
  frame, or only moved: Scena keeps where and how big each one is drawn
  instead of working it out again. 2000 still sprites draw in 4 ms instead of
  10; the endless runner draws about 35 % faster, a tile platformer level
  about 25 %, and a crowd of walking enemies about 7 %. A sprite that turns
  or changes size every frame costs the same as before. Nothing looks
  different: the picture is the same to the pixel.
- Building a Sprite or a shape is faster: about 15 % for a Sprite and 11 %
  for a `Rect`. Scena no longer asks the operating system for the working
  folder each time it looks up an image, and no longer rebuilds each shape's
  center-marker color. The endless runner builds a stretch of track about
  10 % faster.
- An animated Sprite whose frames have different sizes (a strip made of
  separate images, a trimmed atlas) is no longer hidden by
  `cull_offscreen` while part of it is still in view: the off-screen test
  used the size of the frame shown at `play()`, and ignored `tilt`.
- Faster `floor_below` and walkers on tiles whose image is not a full
  square (rounded platform ends, slopes cut in the art). A box meeting such a
  tile, a turned box or a `Polygon` is now swept in closed form. Tutorial 25
  runs about 25 % faster per frame. A sweep can stop up to 0.001 units later
  than before (the new stop is the exact one), and a body that slides past a
  corner without touching it no longer snags on it.
- Faster `resolve()` with many partners: a body pushed out of a large level
  or a big crowd now looks only at the partners near it. A level of 1500
  tiles with 20 walkers resolves about 3× faster, and a crowd of 150 that
  pushes itself apart about 30 % faster. Every answer is the same as before.
- A big crowd under `resolve("enemy", "enemy")` is much cheaper, above all
  while enemies keep spawning and dying: 150 enemies about 30 % faster per
  frame, 400 enemies about 3× faster. Every answer is the same as before.
- `Collider.on_collide =` (and `on_collide_stay`, `on_collide_exit`) refuses
  an `async def` with the fix, as `Entity.on_collide =` already did. Before,
  the assignment took it and the first contact raised `TypeError`.
- Faster `floor_below(group=)` in a world where many other things move: it
  now updates only the bodies of the group it asks about (a level with 500
  moving coins: `floor_below` about a third faster).
- Each frame's collision step now skips bodies that did not move: it no
  longer re-checks every still tile's box, contact bounds and `touching_*`.
  A level of 1500 tiles runs about 18 % faster per frame, the endless
  runner about 12 %, and tutorial 25 about 7 %.
- Shapes with the same `Neon` (or another stroke look) or the same glow now
  share their glow work even when other shapes are drawn between them in
  z order, as long as they do not overlap those shapes. A bullet hell with
  300 glowing shots in alternating looks runs about 8 % faster. Nothing
  changes on screen, except where two shapes with the same look overlap
  each other (they already relaxed z among themselves when they were
  neighbours), and anti-aliased edges can differ on a few pixels, most on a
  small `Laser` circle (a known difference between a shape drawn in a run
  and drawn alone).
- `canvas.cull_offscreen` no longer hides a body that is still partly in
  view: an `Extrude` look (its depth reaches toward the vanishing point, so it
  is never culled now), `Rim` / `Halo` on a Sprite, and `CheapGlow` on an
  animated Sprite drew past the box the off-screen test used. Nothing that
  is drawn changes either: with the cull on, every shape batches with its
  neighbours as with it off.
- `untag()` no longer raises `KeyError` when it removes the last member of a
  group that a formula group (`group["x"] @= …`) reads.
- A `Collider` subclass that defines `on_collide` (or `on_collide_stay`,
  `on_collide_exit`) as a method now gets those calls, as if it had assigned
  them; an `async def` method raises `TypeError` with the fix at the class
  line, as the assignment does. Before, the method was ignored.
- A class of your own whose `__init__` never calls Scena's
  (`class Bolha(Circle)` with `def __init__(self): self.velocidade = 100`)
  now raises `TypeError` when you make one, with the fix: put that code in
  `def setup(self):`, or give your `__init__` `**kwargs` and call
  `super().__init__(**kwargs)`. Before, `Bolha()` made an empty object that
  was never in the game (nothing drew, `on_update` never ran) and said
  nothing, or raised an internal `AttributeError` (`'_clickable'`) when the
  class had `on_click`; `Bolha(center=…)` said "Write Bolha()", which led to
  the empty object. Using `self` in `__init__` before Scena's `__init__` ran
  (`self.radius`) still raises `AttributeError`, now with the same fix
  ("Bolha has no radius yet: …"); before, `AttributeError: 'Bolha' object
  has no attribute 'radius'`. A program with such a class ran without those objects;
  it now stops at the first one. An `__init__` that calls
  `super().__init__(**kwargs)` works as before.
- A value in a class body under a name Scena owns
  (`class Bolha(Circle): radius = 30`, `class Tiro(Sprite, …): height = 28`,
  `visible = False`, `group = "tiro"`) now raises `TypeError` on the class
  line, with the fix: the class keyword when the kind takes it
  (`class Bolha(Circle, radius=30)`), else `setup(self)`
  (`self.visible = False`). Before, the value was never applied: the object
  kept the default, and a few reads returned the class value while the
  object drew otherwise (`visible`). A program with such a line ran without
  it; it now stops at the class. Fields of your own (`velocidade = 100`),
  methods and properties in the class body are unchanged.
- A track made without a place (`Track.circle(radius=120)`, `Track.eight()`,
  any preset with sizes only) is anchored when you give it one later: a link
  (`orbit["center"] @= lambda: earth.center`), `orbit.center = …`,
  `move_to` or `move_by`. Its riders follow it, also those already riding.
  Before, the place was taken and ignored: the moon circled its own start
  and `is_floating` stayed `True`. To draw a track somewhere while each
  rider still starts from where it is, say so: `floating=True`.
- `resolve()` between two bodies that both move (neither is `STATIC`) now
  splits the push by mass, in any enrollment order, as the Guia says
  ("duas massas iguais se empurram meio a meio"). Before, the body checked
  first was carried by the other's whole step, whatever the masses, and the
  order was the bodies' enrollment order (with `resolve()` called after both
  exist, the order of its arguments): a crate enrolled before the player was
  pushed at full speed even at mass 50, and one enrolled after it was never
  pushed; a wall of mass 50 held by a spring was
  shoved by every ball and the box gained energy (+45 % in 10 s). `.vel`
  already split by mass; now the position agrees. If a floor, wall or
  moving platform must not give, make it `STATIC`: left at the default
  mass `1`, it now yields under an equal mass in every order (before, only
  when it was enrolled first).
- `@collide_exit` (and `@collide_with_exit`) runs when a side leaves, while
  touching, the tag its contact entered under: `heroi.untag("heroi")` (or a
  group change) on a spike fires the spike–hero exit. Before, the contact
  ended with no exit, so an "on the spike" flag or an enter / exit counter
  stayed on. Untag and tag again in the same frame is no change, and the left
  tag matches only that contact's exit, never a contact begun after. An exit
  handler that destroys or untags a side no longer hides the other exit
  handlers of that contact: they all run.
- A `resolve(..., bounce=)` body bounces off a partner that an `@collide`
  handler destroys (or parks) in the same frame. The Breakout pattern
  `resolve(bola, "tijolo", bounce=1)` + `@collide(bola, "tijolo")` with
  `tijolo.destroy()` let the ball plough through every brick it broke,
  because handlers run before resolve. The contact still gives this frame's
  `.vel` response; the dead brick pushes nothing. A body moving away from or
  along the removed partner keeps its speed, and a one-way (`only=`) platform
  answers only on the side it blocks.
- A rider on a `STATIC` lift going down (`lift.move_by(0, -v * dt)`) keeps its
  `@collide` contact: `@collide_stay` fires every frame while `touching_sides`
  says `"bottom"`. Before, the lift's drop each frame opened the gap past the
  resting-contact skin (e.g. from about 45 units/s at 60 Hz with strong
  gravity; lower at higher frame rates), so
  the contact exited while the rider stood on it, and a lift going up and
  down at a constant speed exited at the top and never entered again on the
  way down.
- An idle body on a slope stays put. With `vel.x = 0` when no key is down
  (the ninja idiom) and gravity, a hero on a `STATIC` ramp slid slowly
  downhill: 24 units in 10 s on a 30° ramp at 60 fps, 58 at 144. Walking up
  and down the ramp is unchanged.
- A `STATIC` floor or wall no longer gives way under a stack. A light crate
  under a heavy one sank into the floor (mass 5 on top: 8 units in; mass 20:
  almost all the way), balls at the bottom of a pile fell through a thin
  floor, and a light ball hit by a heavy falling one went through a 10-unit
  floor (or past a thin wall, when hit fast from the side). Crates in a stack
  can still sink a little into each other and jitter (Scena is not a physics
  engine); none ends inside or below a `STATIC` body.
- Two bodies that start overlapping separate by the side they overlap on,
  whatever their `.vel`. Before, a pair moving apart was pushed through each
  other (two balls spawned overlapping swapped sides), a ball spawned inside
  a thin wall and moving into the room came out on the far side, and a
  `STATIC` paddle placed onto a ball (`paddle.center = ...`) could lose it
  below. A body spawned more than halfway into a floor now leaves by the
  nearer face (below a floor's middle: out the bottom), even if it is falling.
- A hold-to-fire `Button(st["firing"])` destroyed while held, or ended by
  `change_act` while held, writes `value_off` (no click). Before, `st.firing`
  stayed `True` into the next act.
- Holding Enter on a `TextInput` whose `on_submit` focuses another box (or
  changes to an act that focuses one) no longer submits that box empty on
  the keyboard's auto-repeat: a key's repeats go only to the box that got its
  press.
- A widget under the cursor (a `Button`, …) loses its hover, and gets
  `on_hover_exit`, when the cursor leaves the window without a last motion
  event. Shapes already did.
- A key held across `change_act` gets its `on_key_up` (and a mouse button its
  `on_mouse_up`), as the Guia says: walking right into the door that loads
  the next level, `on_key_up("RIGHT")` still stops the walk. Nothing else of
  the old press reaches the new act: no `on_key` repeat, no `on_mouse_drag`,
  no click.
- The freeze watchdog stops a busy loop written on one line
  (`while not st.pronto: pass`, `while n < 10**9: n += 1`) in an async mode,
  as it already did for a loop on several lines. Before, the loop ran until
  it ended on its own and froze the game.
- Messages name an act "act Fase": the watchdog said
  `<__main__.Fase object at 0x…>`, and the act-change warning named the line
  inside Scena that made the act ("the Fase made at …").
- `shape.clone(center=(x, y))` puts the copy there for every shape (`Circle`,
  `Rect`, `Square`, `Ellipse`, `Polygon`, `RegularPolygon`, `Line`, `Point`,
  `Track`). Before, `center=` was ignored and the copy sat on the original
  (Sprite, Svg and Text already honoured it). A function there raises: link
  the copy after (`copia.center @= …`).
- `tri.points[1] @= lambda: …` links that vertex cleanly. Before, it linked
  the vertex and then raised "'tuple' object does not support item
  assignment". `tri.points[1] = (x, y)` raises with the spellings that work
  (`tri.points[1].move_to(x, y)`, `@=`).

### Documentation

- New example `examples/entropia.py`: blue balls on one side, red on the
  other, a middle wall to take away and put back. Every 5 seconds two
  invisible rectangles count the colours on each side (`collides_with`), and
  the panel shows the mix (entropy), pressure, temperature and energy.
  Checkboxes turn on gravity, loose outer walls (nothing holds them: the
  pressure pushes them off and the box bursts) and a free middle wall that
  moves like a piston.
- Guia, "Tornar sólido": a floor, wall or platform that must not give is
  `STATIC`. Between two bodies that move, the push splits by mass, so one
  left at the default mass `1` sinks under an equal-mass hero. A `STATIC`
  body holds under a stack. Riders ("Quem está em cima vai junto"), with a
  gotcha against copying a lift's speed into the rider; the Handle examples
  that copied a platform's `h.velocity` into a `rider` now copy it into a
  crate let go of the platform.
- Guia, "Tornar sólido": `resolve(hero, ANYTHING)` makes every enrolled body
  solid, coins, shots and sensors included (the hero shoves the coin instead
  of passing through it; its `@collide` still fires). Name the solid groups
  instead: `resolve(hero, ["walls", "crates"])`.
- Guia, "Clips": the same clip again does nothing only while it plays; a
  `loops=1` clip that has finished starts over. To play it once from
  `update`, ask `showing` first.
- Tutorial 19 (Ligue 4): four in a diagonal wins too (`quatro(x, y, 1, 1)`
  and `(1, -1)`, with `l < 0` for the one going down). Before, only rows and
  columns counted.
- Tutorials 18, 24 and 25 (Ninja): a kunai that hits a robot already
  breaking passes through it (before, it broke the robot again and restarted
  the clip); with no lives left the ninja falls to the ground before the
  `"morto"` clip, and plays it once (before, it died in mid air, and in 25 a
  fall into the water on the last life sent it back to the start first).
- Tutorial 25 has a new step, "O elevador": a gold `Metal` plank from the
  level (`fase["elevador"]`) that rides up and down forever
  (`move_by(..., loops="forever", yoyo=True)`) and carries the ninja to a new
  star. `examples/media/levels/ninja_perigos.json` has the elevator and the star.
- The tutorials are reorganized (Portuguese). New: **09 Fórmulas** (the
  reactive system in depth: cells and formulas as in a spreadsheet,
  `st["x"]` × `st.x`, `=` × `@=`, `@on_change`, `@when`, `unlink`, the
  rules), **11 Interação** (click, hover, the right button, drag, drop, a
  grid that lights the cell under the mouse), **12 Órbitas** (tracks in
  depth, `rotate_by` forever, `tween`, `nearest`, `heading`,
  `ElectricBolt`) and **13 Giros** (the rotating bars, recursion built step
  by step, and the oscilloscope with `cos` / `sin`). 04 drops the bars and
  the oscilloscope (now built step by step in 13) for two new scripts,
  **Desenho** (`Contrail`, `every` + `cancel`) and **Letreiro**
  (`TextInput`, `Text` with gradient and glow, `move_along` on a `Track`).
  06 opens with a script on classes and objects (`bolhas.py`: the mold, the
  copies, fields, `setup` / `on_update`, why not `__init__`). The old 09–23
  are now 10 and 14–26: the page addresses changed (`09-bolas.html` →
  `10-bolas.html`, `11-aviao.html` → `14-aviao.html`, …). Six appendices
  are new: **A** debug keys, **B** useful commands (window, full screen,
  colors, random, clock, key names, volume), **C** where to find art and
  sound (sites, licenses), **D** points and vectors, **E** helpers
  (`remap`, `lerp`, `chase`…), **F** shape constructors in detail.
  `examples/app_draw.py` is now `examples/desenho.py`; new examples
  `letreiro.py`, `bolhas.py`, `formulas.py`, `interacao.py`, `trilhas.py`,
  `orbitas.py`.
- Tutorials: Python words a beginner meets are explained where they first
  appear (`nome=valor`, the decimal point, `+=`, f-strings, comments,
  `range`, indexes, `not`, `in`, `!=`, `elif`, unpacking a pair, a `lambda`
  that delays a call, `int`, `**`, `sin` in radians).
- Guia: `on_mouse_*` callbacks get `button` as a number
  (`Mouse.BTN_LEFT`, `Mouse.BTN_RIGHT`…), not a string; `@drag_over` runs
  on each mouse move during a drag (not each frame), with `to=None` off
  every target; `@click` answers the left button only; the key-name table
  lists `"ENTER"`, `"TAB"`, `"BACKSPACE"` and the other special keys.
- Guia: the `DestroyedError` row says `play_sound` on a destroyed actor is a
  quiet no-op (an already cancelled Handle), like `after`. Under a turned
  camera `canvas.game_view` is the upright box around the view (bigger than
  the screen), and the Guia shows how to confine to the screen. On a `ui`
  shape under a moved camera, `contains_point(mouse)` tests the world: use
  `pointer_hover`. `mouse.x` read right after `pan_by` in the same update is
  still the frame's sample. Surfaces have no friction: damp `vel.x` yourself
  (`self.vel.x *= 0.5 ** dt`).

## 0.8.0 — 2026-10-11

### Breaking

- `st.key` reads the **value**, like an Entity field (`ship.hp`). The cell is
  `st["key"]`. Before, `st.key` returned the cell itself (an `Attribute`), so
  `if st.mic is None:` was always False, `match st.mic: case None` never
  matched, `type(st.n)` and `isinstance(st.n, int)` named the cell, and
  `recorde = st.score` (or `lista.append(st.score)`) kept following the score
  instead of copying it. All of these now do what they say. Same for any
  `State` bag (`hud = State(name="hud")`).
- What binds or watches a cell takes the brackets. Old → new:
  `Slider(st.volume)` → `Slider(st["volume"])` (also `CheckBox`, `DropDown`,
  `TextInput`, `Button`, `Menu`); `Text(st.score)` → `Text(st["score"])`;
  `@on_change(st.wave)` → `@on_change(st["wave"])`; `@when(st.alive)` →
  `@when(st["alive"])`; `until(st.done)` → `until(st["done"])`;
  `tween(st.t, …)` → `tween(st["t"], …)`; `c["radius"] @= st.r` →
  `c["radius"] @= st["r"]`; `st.x @= …` → `st["x"] @= …`. The old spelling
  raises `TypeError` naming the bracket form (`Slider(cell) binds a data
  cell: got float 0.5. Pass the cell with brackets: Slider(st["volume"])`),
  also when the cell holds a `Vec2` (`st.pos @= …`, `c["center"] @= st.pos`,
  `tween(st.pos, …)`, `until(st.pos)`). Two exceptions: `st.x @= …` on a
  number raises Python's own `TypeError` (`unsupported operand type(s) for
  @=`), which Scena cannot word; and `Text(st.nome)` on a text cell shows
  the name of now and no longer follows it (`Text(st["nome"])` follows).
  `SpriteButton(label=st["vidas"])` now shows the cell live. `Text(True)`
  and `Text(c["radius"])` raise too: only a State cell binds a Text.
- A cell holds a `Vec2` by value: `st.v0 = ball.vel` stores a copy of the
  ball's velocity. Before, the cell kept the ball's own `Vec2`, which went
  on changing with the ball without telling anything linked to `st.v0`.
- `st.key.value` raises `AttributeError` (`'int' object has no attribute
  'value'`): write `st.key`, which is already the value.
- `Text(<number>)` raises: write a string (`Text(str(n))`), a cell
  (`Text(st["score"])`) or a function. Before, `Text(5)` showed "5"; after
  the change above, `Text(st.score)` would have been a frozen snapshot.
- A widget's `cell` given as `None` raises; leave the argument out for a
  widget with no cell. `Menu(st.nave)` while `st.nave` is still `None` would
  otherwise have built a menu that writes nowhere.
- `@on_change(v)` / `@when(v)` with a free `Vec2` raises: watch the cell
  (`@on_change(st["pos"])`) or a function (`@on_change(lambda: line.vec)`).
- `st.pos.x = 5` still raises (assign a whole value:
  `st.pos = Vec2(5, st.pos.y)`), and `st.pos += Vec2(1, 0)` /
  `st.itens += [x]` still update what is linked to the cell.
  `st.itens.append(x)` changes the list without telling links, as before.
- `anchor.draggable = False` and `anchor.handle = False` raise `TypeError`
  (an Anchor is always a draggable handle; use `Point(x, y, visible=True)`
  for a point the pointer cannot move). Before, they were accepted and
  ignored. A link on an Anchor (`a["campo"] @= ...`) now says that an Anchor
  takes no links, instead of telling you to set `draggable = False`.
- An `async def` where Scena calls a function raises `TypeError` with the
  fix: `async def setup`, `async def on_update`, an async `@every` / `@when`
  / `@collide` / `on_click` / `on_done=`, or a lambda that calls an async
  method (`after(1, lambda: self.anda())`). Before, the body never ran and
  Python only printed "coroutine ... was never awaited". Only a mode is run
  as a script: write the waits in `async def intro(self)` and start it with
  `self.mode = self.intro`.

### Added

- `until` takes a cell or a field and waits until it is true:
  `await until(st["acabou"])`, `await until(chefe["vivo"])` (the field is read
  each frame, like `until(lambda: chefe.vivo)`).
- Class keywords on spatial effects, like shapes and sprites:
  `class Energia(Orb, radius=16, color="gold", group="energia")` sets the
  defaults of every `Energia`. Placement (`center=`, `p1=`, `origin=`,
  `layer=`) stays on the instance. Before, the class line raised Python's
  "takes no keyword arguments".
- Class keywords on texts: `class Placar(Text, font_size=32, color="gold",
  group="hud")`. The look goes on the class line (`font_size`, `font`,
  `color`, `background`, `glow`, `align`, `width`, `group`); the text and its
  position stay on the instance.
- A formula can read an audio level: `barra["width"] @= lambda: 300 *
  amp_db(mic.level)` follows the voice, like a formula on `clock` or `mouse`.
  The same works for `audio.level`, the `h.level` of a `play_sound`, and
  their `.spectrum()`, in `@=`, `@when` and `@on_change`. The level updates
  once per frame. The microphone must exist when the formula is linked.
  Before, `@=` on `mic.level` raised "formula has no reactive sources", and
  the meter needed an `on_update` that copied the level into `st`; that copy
  still works.

### Fixed

- A walker on a row of tiles no longer snags on, or falls into, a seam where
  the next tile sits a hair higher (a row rotated by hand, a rounded
  coordinate). A body standing on the ground that walks into the side of a
  still piece rising at most 2 above its feet steps onto it, with `resolve()`
  and with `only=` one-way platforms. Before, a 0.1 rise stopped it dead,
  and on a one-way row it rode past the seam and dropped into the tile
  (sooner at a higher frame rate). Taller steps are walls, as before, and
  an airborne body gets no step.
- A `Fire` subclass given `style=` other than `"camp"` raises, naming
  `Fire(style=...)`. Before, the style was silently ignored.
- A shape that is a piece of a `Collider` and also a body of its own (a
  weak point) no longer collides with the Collider it belongs to, nor with
  another weak point of the same Collider, and `raycast`, `query_point`,
  `query_circle`, `query_sector` and `query_shape` name the
  Collider first whatever order the lines ran in; `query_shape(piece)` no
  longer finds the Collider the piece belongs to. Before, the boss touched
  its own torso and the queries depended on statement order.
- `class Rota(Track, color="gold", group="rotas")` applies its class
  keywords. Before, `Track` accepted them and dropped them.
- A class keyword on a family that takes none (the widgets, `Entity`,
  `Endless`: `class Painel(Entity, group="hud")`) raises an error that says to
  pass it when you make one. Before, Python's "takes no keyword arguments".
- A formula that reads a microphone held by an object
  (`lambda: self.mic.level` inside an Entity, `lambda: gravador.mic.level`)
  follows the level. Before, it was accepted and never changed.
- `confine` on a `Sprite` whose sheet has an anchor (`Sheet(anchor="bottom")`,
  an atlas pivot) keeps `center` (the feet) on the edge. Before, each clamp
  lifted the sprite by half its height: a platformer hero walking into the
  screen edge climbed to the top. `by="box"` / `"overlap"` measure the drawn
  box, as documented.
- `Metal("gold")` draws gold metal. Before, the color was ignored and every
  `Metal` was chrome. `Metal()` without a color stays chrome, whatever the
  shape's own color.
- `on_collide`, `on_collide_stay` and `on_collide_exit` written as methods of
  a class (`class Nave(Sprite): def on_collide(self, other, info)`) get the
  other body and the collision info. Before, `other` was the object itself and
  `info` the other body.
- A formula whose lambda takes a default (`for g in gens: g["saida"] @=
  (lambda g=g: g.ganho * 2)`, the loop-variable idiom) links. Before, it could
  raise `CircularReferenceError`: the default was read as a source.
- Declaring a formula group (`group["coluna0"] @= lambda: ...`) no longer warns
  "No group 'coluna0'. Did you mean …?" when a group with a near name exists.
- Destroying an object whose own field reads the object
  (`hero["grounded"] @= lambda: "bottom" in hero.touching_sides`) no longer
  warns that the attribute was unlinked.
- The frozen-mode warning counts the time a mode has had nothing pending, not
  its age: a mode that waited a long `until_empty` and then ends the act no
  longer warns.
- `list(canvas.effects)` and `len(canvas.effects)` show only the effects you
  added. Before, they also showed an internal entry after any `shake`, `flash`
  or `*_at` impact.
- A `tween(..., name="x")` that replaces the running tween in the same `name=`
  slot no longer warns "replaces a previous in-flight tween": the slot asks for
  the replacement. Two tweens on one property in different slots still warn.
- `obj["field"].unlink()` on a field another formula reads keeps that formula
  linked: it reads the frozen value and follows later writes. Before, the
  reader was unlinked with a "formula source was removed" warning.
- A formula that reads a microphone kept in a State cell (`st.mic.level`,
  `hud.mic.level`) follows the level. Before, it depended on the cell only and
  stayed at 0.
- A formula that reads `g.mic.level` while `g.mic` is still `None` raises an
  error that names the read and says to link after the mic exists (sources are
  learned at link time, also behind `if g.mic else 0`). Before, Python's bare
  "'NoneType' object has no attribute 'level'".
- `if canvas.effects:` is False during a `shake` / `flash` / `*_at` impact
  when you added no effect, like `len(canvas.effects)`.
- Classes you define (`class Tiro(Sprite)`) and the script that defined them
  are freed when the program ends. Before, they stayed in memory.
- `Wallpaper("bg.png", tile_mode="mirror", pan_response=0.1)` keeps covering
  the screen when the camera pans or zooms out past the image. Before,
  `fit="cover"` / `"contain"` / `"stretch"` ignored `tile_mode` and showed
  black past the image edge; only `fit="tile"` worked. `"clamp"`, `"repeat"`
  and `"mirror"` now apply to every image fit. With an explicit `tile_mode=`,
  `fit="contain"` also fills its side bands with the image (instead of the
  `underlay`) even while the camera stands still, and the image is sampled
  smoothly.
- An image Wallpaper without `tile_mode=` reads `.source.tile_mode` as `"decal"`
  (`"repeat"` with `fit="tile"`), which is what it draws: nothing past the
  image edge, so the `underlay` shows. The Guia listed `"clamp"`, which was
  never applied. The look is unchanged.

### Documentation

- Guia, reactive sources: a known limit, now named by its error. A custom
  field cannot read its own object's size or computed points
  (`r["dano"] @= lambda: r.width * 2`); use a class `@property` or
  `update(dt)`. Before, the error spoke of a circular link the author never
  wrote.
- Guia, `ready`: the rhythm is exact on average (what a frame overshoots counts
  toward the next), so two `True` can come a little closer than the interval.
- Tutorials 14–23 (Portuguese): Ninja (gravity by hand, `resolve`,
  `touching_sides`, clips of different sizes), Ninja II (a world: `recently`,
  stars, robots, kunai, lives), Ligue 4 (a board game: `Box` / `grid`, drag and
  drop with `@drag_to`, `move_to(time=)`), Estúdio · Piano (`pitch=`),
  Estúdio II · Voz (the microphone, `@=` in depth, `Track` and `move_along`),
  Naves V (modes, `async` / `wait`, a boss), Naves VI (acts: title, restart,
  game over, record, `until_empty`), Ninja III (a level made in the level
  editor, `Level`, a camera that follows, `pan_response`), Ninja IV (one-way
  planks, a sloped plank with `tilt = "ground"` and
  `hitbox_anchor="bottom"`, `floor_below`, a hurtbox, electric rays, restart
  with an act) and
  Corredor infinito (`Endless` building a collidable world under a moving
  camera). Each ends in a new file in `examples/`.
- New media, all CC0 and made for Scena: `synth/` (jump, coin and throw
  sounds), `audio/nota.wav` (a piano note) and `levels/` (the Ninja III and IV
  level files, made with the level editor's own format).
- Guia, Wallpaper: with a camera that moves, pass `tile_mode="mirror"`; the
  examples do.

## 0.7.1 — 2026-10-09

### Fixed

- A formula that reads `canvas` (`canvas.zoom`, `canvas.game_view`, a
  layer's `view`) keeps following the camera after Scena's reactive graph is
  rebuilt. Before, it froze at its last value. A game does not rebuild the
  graph, so this showed only in test suites that do.

### Documentation

- New example `examples/app_draw.py` ("Trilha"): drawing a trail with the
  mouse.
- The release workflow runs its actions on Node 24.

## 0.7.0 — 2026-10-09

### Breaking

- `every(interval, fn)` counts world seconds at any frame rate: a frame
  longer than the interval fires as many times as it owes (at most
  `0.25 / interval` per frame), and a hitch loses no fires. Before, it fired
  at most once per frame, so `every(0.02)` gave 50 fires a second at 60 FPS
  and 30 at 30 FPS. A spawner tuned at 30 FPS spawns more now.
- SpatialFx (`Rain`, `Sparks`, `Fire`, …) run on world time: `clock.paused`
  freezes them and `clock.scale` slows them, like their own `after` / `every`.
  Before, they ran on the wall clock.
- Every top-level `@leave_playfield("tag")` on a tag runs, in order, like
  `@collide`; one made in an act leaves at the act change. Before, a second
  top-level handler silently replaced the first.
- A layer created inside an act (`canvas.layers.create` in `setup`) leaves
  with the act, so restarting the act works. A game object still on such a
  layer makes `change_act` raise (after the new act is built), naming the
  layer: move it to a game layer first, or create the layer at the top.
- An act's method, or a function that reads the act's `self`, handed to a
  game object (`heroi.every(0.5, self.pulsar)`, `heroi.on_update = lambda e,
  dt: self.x`, `heroi.mode = self.caca`) leaves with the act. Before, it
  stacked on every restart and kept the old act alive.
- In an act change, an object created by a teardown hook (a self-replacing
  `on_destroy`) leaves without running its own `on_destroy`; a teardown that
  does not settle stops after 100 passes (was 10,000, about 8 s) and names
  the class it keeps creating.
- `contains_point` on a destroyed actor is `False`, like
  `collision.query_point`. A parked actor still answers from its geometry.
- A hover handler on a shape in a parallax layer raises `ParallaxLayerError`
  (`@hover(deco)`, `deco.on_hover = …`), like `clickable`; a shape with a
  hover handler cannot move into a parallax layer. Before, the handler was
  accepted and never fired (a parallax layer is decoration; hit tests run in
  world space). A parallax item never fires `@leave_playfield`, as before;
  now the design doc says so.
- `Recolor(key=…)` with a white, gray or black key raises `ValueError:
  Recolor(key='white'): Recolor matches pixels by hue and skips pixels under
  HSV saturation 0.12; … Pick a key with a hue, e.g. key="red".` Before, it
  was accepted and recolored the **red** pixels (a gray reads as hue 0), never
  the gray ones. Recolor cannot select gray areas; a gray `to=` still works.
- Writing a name that is not a field raises with the fix, instead of quietly
  storing a value nothing reads: a method (`c.tag = "boss"`, `ship.destroy =
  True` replaced the method), a read-only property (`ship.is_alive = False`
  raised Python's own "property has no setter"), a size the shape does
  not have (`circle.width = 20`, `text.size = 40` changed nothing), and a
  point or relation it does not have (`circle.top_left = (0, 0)`,
  `rect.fp1 = …`, `circle.dist = 3`; the error says to use `move_to`). Pick
  another name for a field of your own (`ship.boss_tag = …`).
- Every setter on a destroyed actor raises DestroyedError, as `move_by` and
  `visible` already did; `time_scale`, `mass`, `clickable`, `corner_radius`
  and others were stored. `active = True`, `mode = None` and `on_update = …`
  stay quiet no-ops.
- `Circle.from_points(center, perimeter)` copies plain points, like every
  constructor; a function links. Before, it linked a plain point (the
  opposite rule), so `Circle.from_points(ship.center, tip)` followed the
  ship. To follow, write `Circle.from_points(lambda: ship.center, lambda: tip)`.
- A `Color` is immutable: `color.alpha = 0.5` raises AttributeError
  `Color is immutable: … Write color.with_alpha(0.5) for a new Color, or
  shape.set_alpha(0.5) to fade one shape.` Before, it changed the colour in
  place, and colours are shared: every shape with the default colour uses the
  same one, so `Circle().set_alpha(0.3)` faded every later default Circle and
  Rect, in every act, and leaked through `clone()`, `look_like` and
  `save_visual`. `shape.set_alpha(a)` now gives the shape new materials; a
  `Gradient` or `Texture` shared with other shapes is left alone
  (`gradient.set_alpha(a)` on the Gradient itself still changes it in place,
  for every shape that uses it).
- A point given as a sequence must be exactly two numbers everywhere. Before,
  tween destinations, `Track(points=…)` / `start=`, group and collision queries
  read the first two items of a longer sequence, and `(True, 0)` counted as a
  point. Now `(1, 2, 3)` or `(True, 0)` raises TypeError
  `expected (x, y) — exactly two numbers — got tuple (1, 2, 3)`; write the two
  coordinates you mean.
- A point is two finite numbers, and a number is finite, at every door:
  `center = (nan, 0)`, `move_to((inf, 0))`, `rotate_by(10, about=(nan, 0))`
  and `contains_point(nan, 0)` raise ValueError (they stored a NaN centre, or
  answered True); `angle = 10**400` raises ValueError (it was stored, or
  leaked Python's `OverflowError`). `scale =` and `mass =` follow the Numbers
  rule: `scale = True`, `mass = True` and `mass = nan` raise (they were
  accepted), `scale = "x"` raises Scena's TypeError.
- A flag takes a real bool (or 0 / 1) everywhere: `rotate_by(…, force="no")`
  (every pose verb), `Point(visible="no")`, `Sprite(flip_x="no")`,
  `play(resume="no")`, `clip(yoyo="no")` and `Track(closed="no")` raise
  TypeError. `"no"` is truthy in Python: `force="no"` unlinked the parts the
  verb wrote.
- `sprite.remove_hitbox(part)` leaves the sprite in the groups it was in on
  its own; only a group the part's claim added goes with it. Before, removing
  a weak spot (`add_hitbox(group=["enemy", "weak"])`) took the boss out of
  `"enemy"`. `part.remove_from_group(name)` follows the same rule.
- A Sheet frame name that two files share (`idle/1.png` and `run/1.png`, both
  `"1"`) raises ValueError naming both files; the last one used to win, even
  for the exact path that loaded the other. The path that loaded a frame
  (or a tail of it, `"idle/1.png"`) still names it. `Sheet()` with no cells
  refuses a frame index (`clip("a", [3])` was accepted and wrapped later), and
  `cell=(16.9, 16)` raises (it truncated to 16; `16.0` is fine).
- `group=""` (and `""` inside a list) raises TypeError, like `tag("")`; it
  made a group no name could reach.
- Reading a field on an empty group raises AttributeError naming the group:
  `group["boss"].center` with no boss left says `group['boss'] is empty: there
  is no member to read .center from …`. It answered an invented `(0, 0)` (and
  `angle` 0.0), built a hidden actor on every read, and `.hp` raised naming
  `Blank`. Methods on an empty group still do nothing (`group["shots"].move_by
  (…)` with no shot alive). For a position that may be gone, read
  `group["boss"].centroid` or `.box` (None when empty), or check `.empty`.
- `ease=` without `time=` raises TypeError on every timed verb (`move_to`,
  `rotate_by`, `scale_to`, …, and the camera's `pan_*` / `zoom_*` /
  `rotate_*` / `frame_to`): an instant call has no curve, and the value was
  ignored. `yoyo="no"` raises like any flag.
- `st.x = some_function` raises CallableAssignError, for any plain function or
  method (a `def`, a bound method, a builtin, a `functools.partial`), as it
  already did for a `lambda` and as a shape field does: `=` copies a value,
  `st["x"] @= fn` links. Before, a named `def` was stored as the cell's value.
  A class and a callable object stay values. `st.create("x", fn)` refuses the
  same.

### Added

- `Text(fn)` links the text to a function, the same link as
  `t["text"] @= fn`: `Text(lambda: f"Pontos {st.pontos}", top_left=(20, 580))`.
  The docstring promised it; the constructor raised `CallableAssignError`.
- `canvas` is a formula source, like `mouse` and `clock`: `ship["center"] @=
  lambda: canvas.game_view.center`, `lambda: canvas.zoom`, or `lambda:
  canvas.layers["bg"].view.left` follow every camera move and every scroll.
  Before, a formula that read only the camera or a view kept the value it
  was linked with.
- `Endless(layer, pieces, step=...)` fills the part of a layer the camera sees,
  slot by slot, forever: an endless runner floor, flappy pipes, a cave, clouds
  that never run out. `pieces` is an image path, a list of image paths, or a
  function `fn(slot)` that builds what goes in one slot at its absolute
  coordinates (`slot.left`, `slot.right`, …) and returns it (`[]` for an empty
  slot). Each slot has its own random stream, `slot.rng` (and
  `slot.chance(p)`), so walking back rebuilds the same piece; `seed=` replays
  the same world. `axis="y"` scrolls vertically, `axis="xy"` fills a grid
  (`step=(w, h)`). `height=` / `width=` / `size=` size each image piece as
  in `Sprite(path, height=...)`: `Endless("montes", "montes.png",
  height=360)` is a band the height of the screen (without them, an image
  piece is a bare `Sprite(path)`, 48 units on its longer side).
  `.index_at(x)` tells which slot holds a point (score by
  chunk), `.pieces` lists what it built. It needs a layer of its own
  (`canvas.layers.create("pista", below="default")`); `default`, `top` and
  `ui` raise with that line. Guia: Mundo sem fim.
- `canvas.layers["nuvens"].view` is the window that layer shows, in its own
  coordinates, as a `Box`. On a parallax layer it moves less than the camera,
  so scenery spawned at `layer.view.right + 200` enters from the right; on a
  gameplay layer it is `canvas.game_view`.
- `layer.scroll` can be changed during play on a layer created with a camera
  response (`pan_response=`, `scroll=`, …): `nuvens.scroll = (0, 0)` stops the
  clouds, `nuvens.scroll = chase(nuvens.scroll, (0, 0), 3)` slows them down.
  The change has no jump. On a gameplay layer it raises with the `create` line
  that makes a scrolling decoration layer.
- `canvas.playfield.set(box)` takes a `Box`:
  `canvas.playfield.set(canvas.game_view.outset(300))` is the per-frame line
  that keeps `@leave_playfield` working while the camera travels. The four
  keywords still work; a Box and keywords together raise.

### Fixed

- `@leave_playfield` checks its arguments at the decorator. `ANYTHING`,
  `group["tiro"]` and a class each raise a `TypeError` that names the right
  spelling (`@leave_playfield("tiro")`, or a bare `@leave_playfield` method on
  the class). Before, `group["tiro"]` and a class were taken for the handler
  ("requires at least one group name", or an `AttributeError` in a class
  body). A handler that needs more arguments than Scena passes (`item` at
  script level, `self, item` on a method) raises at the decorator like
  `@collide`, not at the first leave frames later.
- Decided behaviour (review 2026-10-09):
  - A shape on the `ui` layer or a parallax layer in a group named by
    `@collide` or `resolve` is skipped (it has no body), whether the rule or
    the tag came first. Before, one order raised and the other was silent.
    Naming the shape itself (`@collide(icone, …)`) still raises.
  - While you drag a shape, it stays under the cursor even if `on_update`
    moves it (a per-frame `move_by` for gravity). It used to drift off the
    still cursor and snap back on the next mouse motion.
  - `ready("tiro", 0.07)` polled every frame fires at the same rate at 30 and
    60 FPS (it dropped the overshoot of each period). After a pause in polling,
    it is ready once, with no burst.
  - A fast orbit (`rotate_by(…, about=)`) hits targets on its arc even when a
    slow frame turns it far in one step.
  - A background field's `scroll` keeps moving while the field is disabled,
    like a layer's scroll, so it does not jump or lag when shown again.
  - SpatialFx effects keep world time through a slow frame (they advanced at
    most 0.1 s per frame).
  - `canvas.shake`, `flash` and `glitch` end while the game is paused.
- An act change gives back more of what the act changed:
  - A `group["alvos"] @= …` made in an act leaves with it. A restart no
    longer warns "overrides its previous link". The name can be tagged in the
    next act, and a game formula the act re-bound comes back.
  - A collision tag that no remaining `@collide` or `resolve` names stops
    enrolling members. An act's `@collide("moeda", "heroi")` made every later
    coin in every act a collision body that answered `collision.query_point`.
    A body that only that rule enrolled leaves collision. A body you set
    `collidable = True` stays. The same now happens after `unresolve` and
    when an object named in a rule (`@collide(chefe, "tiro")`) is destroyed.
  - `unresolve(heroi, ANYTHING)` and an act's `ANYTHING` rule on a game body
    stop that body from pairing with every other body.
  - A camera move with `time=` started by a game actor no longer undoes the
    restored camera after the change.
  - The act's HUD starts at the same place on every entry. With one HUD item
    at the top of the file, it used to move one row lower on every restart.
  - An act change from inside a collision handler no longer keeps the old
    act's objects in memory until the next change.
  - An act change whose teardown never settles still restores the world
    settings and drops the act's rules and timers before it raises.
- `ui.min_label_space` refuses `True`, NaN and infinity, like `ui.scale`.
- A rejected call changes nothing:
  - A timed verb that refuses its arguments (`move_to(0, 300, time=-1)`,
    `rotate_by(10, time=1, on_done=5)`, `tween(…, time=-1)`) keeps the move
    already in flight. With `face=True` it no longer turns the shape.
  - `@collide([heroi, icone_hud], parede)` and `resolve([...], ...)` with a
    `ui` or parallax member register no pair at all. Before, the first pairs
    stayed live.
  - `sprite.size = n` with a linked `height` (or `width`) leaves both sides
    as they were. `sprite.frame = i` with a linked size keeps the clip
    playing.
- A sprite clip with `loops=` and `next=` switches in the frame's
  simulation, not first in the draw. With a linked `width` or `height`, the
  switch keeps the link instead of raising from inside the draw.
- A raising `on_done` of one sound no longer loses the other sounds that
  ended in the same frame. Their `on_done` runs on the next frame.
- `contains_point` (and so `@click` and hover) sees a linked `angle` or
  `scale` as it is now, also on a shape that is not drawn.
- `scale_to(…, force=True)` and `rotate_to(…, force=True)` on a linked pose
  start from the value the link holds now.
- `move_along(track.reversed())` follows the host track's turn, scale and
  closure.
- A pivot a rounding off a linked center is the center for every verb, and a
  `Box` turns about a linked corner like a `Rect`.
- `confine` no longer fires a `@collide` with something behind the wall it
  clamped the body to.
- `unresolve(heroi, group["paredes"])` undoes `resolve(heroi, "paredes")` and
  `resolve(heroi, group["paredes"])`.
- `layer.visible = "no"` and `layer.z = 5.5` raise instead of being taken as
  `True` and `5`.
- `ready.disable("tiro")` before the first `ready("tiro", …)` keeps it
  disabled. `ready` and `recently` methods give Scena's message for a name
  that is not a string.
- `play(…, min_hold=0.25)` holds exactly 0.25 s.
- A second timed move replaces the first even when something read `.center`
  in between, and `tween(shape.center, …)` replaces a timed move.
- `on_update` runs in the order the actors were created, the same on every
  run. An `on_update` cleared by an earlier one in the same frame does not run
  later in that frame.
- `@on_change` fires when a value turns from `1` to `True` or from `0` to
  `False`.
- `canvas.cull_offscreen = True` no longer makes drawing slower than drawing
  everything. It costs about the same for trivial shapes and pays off for
  real ones: 1000 text labels draw 2.5× faster.
- Writing a field or calling a timed verb on an empty group
  (`group["tiros"].hp = 3`, `group["tiros"].move_by(…, time=0.5)`) no longer
  builds a hidden actor per call. The timed verb still waits its time and
  runs `on_done`.
- Collision handlers dispatch faster when many `@collide` rules exist.
- The mouse position in the world stays exact at large world coordinates
  with the camera on (it was off by 0.05 units at x = 1 000 000).
- When a key or mouse callback raises and you catch the error, keys and
  buttons the system reports released no longer stay held in `keyp` and
  `mouse`.
- Destroying an actor whose body `@collide_exit` raises still ends the
  contacts of its hitbox parts.
- A second `run()` in the same Python session opens a new window.
- With the camera moving in `update()` or by `canvas.pan_by(…, time=)`, a
  dragged shape, hover and anything linked to `mouse` stay under a still
  cursor (they were one frame of camera travel behind).
- A respawn in a `@collide` handler (`move_to` or `center =`) lands on the
  spawn point under `resolve()`, and `center =`, `center.x =` or `center << p`
  after a `move_by` no longer sweeps through walls the body never crossed.
- A query in `update()` sees a hitbox whose `hb["active"] @= …` formula just
  turned it off, on every kind of query and for the main hitbox too.
- `cull_offscreen` draws a shape whose linked `scale` or `angle` just brought it
  into view, and `.box` / `group[...].box` measure that pose.
- `portal.tilt =` and `portal.angle =` reshape a Portal's collision.
- `canvas.zoom_to(…, time=)` and `zoom_by(…, time=)` zoom geometrically, as the
  docs say: half time is the middle of the zoom, and an elastic zoom-out no
  longer shrinks the world to a dot.
- A `loops=` move or tween keeps world time under a slow frame: it ends at
  `loops × time` and a yoyo stays in phase. `h.elapsed` and `h.remaining` on a
  finite `loops=` count the whole run.
- `every` never fires more than its per-frame bound after a long frame.
- An `Endless` fill keeps up with a camera moved later in the frame, and a
  scrolling layer counts its first frame.
- A key pressed while a modal menu is open no longer sends `on_key` repeats
  once the menu closes.
- `mouse.dx` / `mouse.dy` are this frame's motion: 0 when the mouse is
  still (they kept the last step, so `ship.move_by(mouse.dx, 0)` drifted
  forever), and the sum when several moves arrive in one frame.
- A parked or `collidable = False` body forgets `touching_sides` (it read
  `"bottom"` in mid-air and snapped down when it came back).
- A hidden or parked modal Menu no longer leaves `keyp` and `mouse` dead.
- Every `on_key_down` / `on_mouse_down` the script gets has its up, even with
  a modal opened in between; a consumed Ctrl+Shift shortcut sends no up.
- A dragged shape stays under a still cursor while the camera pans.
- A Button's hover highlight no longer sticks after press, drag off and
  release; a Button shown under a still cursor is hovered.
- A mouse press from the previous act no longer clicks in the new one;
  `mouse.click_pos` ignores clicks made on a modal menu.
- `keyp.once("A")` is not lost when Shift is tapped in the same frame.
- A compound `Collider` whose pieces are destroyed fires `@collide_exit`.
- `collision.query_point(…, group=hero)` in `update()` no longer finds a
  hero parked in the same `update()`.
- A link that reads a field of another object (`q["x"] @= p["x"]`)
  follows every change of that field: `p << …`, `absorb`, `shape.center = …`,
  `move_*` / `rotate_*` / `scale_*` (instant and timed), flips, tweens, drag,
  `resolve`, `confine`, and Text moves. Before, only `p.x = …` updated it.
- A link that reads a computed field (`line["length"]`, `vec["length"]`,
  `rect["width"]` of a corner-to-corner Rect) keeps that field current; it
  froze for every reader.
- `obj["angle"] @= lambda: …` / `["scale"]` refuse `True` and a huge int like
  `=` does.
- Outside the frame loop, `@on_change` / `@when` no longer see a half-moved
  shape in the middle of `move_by`.
- `unlink()` and `destroy()` no longer fail when the linked formula raises;
  the field keeps its last value.
- `clone(scale=…)` refuses a bad scale before making the copy (a negative or
  huge scale left a live copy behind); `clone(scale=True)` raises.
- Destroying a hovered or touching object runs its own `on_hover_exit` /
  `on_collide_exit` while it still exists: the usual un-highlight
  (`shape.color = "white"`) no longer raises `DestroyedError` out of
  `destroy()` or `change_act` (a title-menu option whose click changes act
  crashed). A `destroy()` inside those hooks does nothing.
- A survivor's `@collide_exit` sees the destroyed partner gone from its
  groups (`group["enemy"].empty` is True after the last kill).
- Within one collision dispatch, a handler that destroys a side or changes
  act stops the handlers after it; an exit is delivered only for a pair whose
  enter ran.
- `change_act` from a `@collide` or `@leave_playfield` handler stops the
  leaving act's handlers in the same dispatch.
- An act's `canvas.fade_out(on_done=…)` still animating at an act change no
  longer fires its `on_done` in the next act.
- `tween(x["field"], …)` and `tween(x.center, …)` cancel quietly when `x` is
  destroyed (it kept writing, or crashed the frame).
- Timed `rotate_*` / `scale_*` on a `track.reversed()` view turn the track
  itself, and end with it.
- `setup()`, `on_destroy` and `@exit_mode` of an actor made inside another
  actor's mode own their work themselves (a shot's own timers no longer died
  with the wasp's mode).
- `self.mode = …` inside its own `@exit_mode` raises a `TypeError` with the
  fix (it recursed until `RecursionError`); an exit hook that destroys the
  actor runs no next mode body.
- A top-level `@when` / `@on_change` reading a destroyed actor retires (it
  kept the actor alive when the field stayed readable).
- A group broadcast skips members an earlier member's call destroyed.
- `on_drop_by` does not run on a target `on_drag_to` destroyed.
- A hover target never gets `on_hover_exit` without its `on_hover`.
- Parking an actor runs its collision exits with `active` already False.
- The script gets no `on_mouse_up` for a press a widget or shape took.
- A Button that destroys itself in its `on_click` is no longer kept alive.
- A caption placed by `top_left=` (or `top_center=` / `top_right=`) whose
  `center` is linked keeps the centre where its formula puts it when the
  string changes; it used to keep the corner and drift the centre by half the
  width change. While `center` links, the box grows both ways around it and
  the corner follows: writing the corner raises `DerivedAttributeError`
  (before, the write was accepted and the two disagreed). The same holds the
  other way: after `t["top_left"] @= …`, `t.center = …` raises, as it does for
  `Text(top_left=lambda: …)`. `t.center @= …` is refused when the corner
  already links, as `t["center"] @= …` was. Unlink to write either again.
- The fade cover runs while the world is paused or slowed (presentation
  time): `clock.paused = True; canvas.fade_out(0.5, on_done=…)` finishes.
  Before, the screen stayed black and `on_done` never ran.
- A hidden scroll layer keeps scrolling. Before, it froze while hidden and
  jumped when shown again (or lagged for good after 1.5 s hidden).
- An `@on_change` relay chain longer than 8 links settles in one flush; only a
  real cycle warns. Before, it warned "a cycle?" and the tail lagged a frame.
- An act's ownerless timer with a game timer's `name=` replaces it for the act
  only: the game timer pauses and comes back at the act change. Before, the
  act's cancelled it for good.
- In an act change, every object's `on_destroy` runs while the whole act is
  still alive: a boss's hook can read its escort whatever their creation
  order. Before, reading a sibling's field could raise `DestroyedError`.
- An owned sound's `on_done` waits while its owner is parked (`active =
  False`) and runs on resume; the sound keeps playing and its Handle keeps
  counting. Before, `on_done` ran on the parked actor.
- `sprite.clone()` copies `hitbox.active = False`, like `collidable = False`.
- An atlas file rewritten while the program runs is read again (the cache
  follows the file's time and size); the shared atlas frames refuse writes.
- An act change (or a hard layer clear / a group destroy) that destroyed an
  open modal `Menu` left it open: the dimming mask and the menu's `pause`
  stayed, `await menu` hung, and the next act's `TextInput.focus()` raised
  "A modal Menu is open". Every destroy path now closes the menu.
- A destroyed widget stayed in the double-click memory: a widget made at the
  same spot could take a first click as a double click.
- Pair lists kept destroyed bodies: a group-operator side
  (`@collide(group["a"] | group["b"], …)`, `resolve(group["a"] | …)`) kept a
  destroyed member, the `resolve` pairs remembered when the game started kept
  a destroyed side forever, and an act's `@collide(ship, …)` kept a destroyed
  `ship` until the act changed (a leak and dead-target warnings).
- `target << source` refuses a destroyed source with DestroyedError, as
  `source.clone()` and `absorb(source)` do; it copied the destroyed shape.
- `sprite << other`, `svg << other` and `text << other` raise Scena's
  TypeError with the fix (`other.clone()`, or place it with `center =`);
  they leaked Python's `NotImplementedError("Subclasses must implement
  takein")`. `<<` is a Shape copy.
- An anchored caption (`Text(top_left=…)` / `top_right=`) takes one
  placement link: linking `center` while the anchor is linked (or the anchor
  while `center` is) raises LinkedAttributeError at the second `@=`. Both were
  accepted and disagreed: the center followed its source while the anchor
  stayed.
- A link refused because `wheel_rotate` is on (`polygon["angle"] @= …`,
  `sprite["angle"] @= …`) leaves nothing behind; it kept the link's anchor.
- A flip turns the heading to `180 − θ` (`flip_x`) or `−θ` (`flip_y`) on a
  Rect placed by its spine (`p1=`, `p2=`), as on every other
  shape: after `rotate_by(400)`, `flip_x` reads −220 (it read 500), and a
  fresh `flip_x` reads 180 (it read −180).
- A tall Ellipse (height greater than width) mirrors each focus on a flip;
  `fp1` and `fp2` swapped places.
- A finished `rotate_to(θ, time=…)` reads exactly `θ`, like the instant
  form: from 400, `rotate_to(30, time=1)` ends at 30 (it ended at 390). The
  motion still takes the short way. Same for the camera's `rotate_to`.
- A timed `move_to`, `scale_by` or `scale_to` refuses at the call where the
  instant form refuses (a linked part, a relational shape); `force=True`
  unlinks at the call. Before, the refusal came from the frame loop after
  part of the motion had run. A timed turn of a shape whose linked center is
  its pivot (`circle.rotate_by(90, time=1)` with `circle["center"] @= …`)
  now runs, as the instant turn does; it was refused.
- Linking a part that a running motion moves, or the whole shape (`shape @=
  …`), is refused at the `@=` ("… pushes it"), as linking the heading
  already was; the motion's next frame raised instead.
- A sheet-anchored Sprite's `move_to(…, time=)` starts where the sprite is;
  it jumped first.
- An anchored Text (`top_left=` / `top_right=`) whose anchor is linked
  refuses `rotate_by` / `scale_by` with `time=` at the call, as it does
  without `time=`; it accepted and raised from the next frame.
- A Line placed by `center=` with a linked center keeps taking `scale_by` /
  `rotate_by` about it; after one scale every later one was refused.
- A tangent Line from a point refuses `move_by(0, 0)` like any other move.
- A link refuses what `=` refuses, by the field's name: `shape["width"] @=
  lambda: st.w` with `st.w = True` raises TypeError (it read 1), and a huge
  int raises ValueError (it leaked Python's OverflowError; also for a point
  linked to `(st.x, st.y)`). When the source is good again the link follows;
  `unlink()` and `destroy()` keep the last good value instead of raising.
- `st.v = 1.0` on a cell holding `True` stores `1.0`; it kept `True`.
- `rect.vec` (and a Line's or Box's vector) refuses `(0, inf)` on every
  path, like a point; it stored it, and every later read failed.
- Sprite, Svg and Text scaled about another point stay similar below the
  smallest scale: the center moved by a different factor than the size.
- A Line whose heading is linked turns a point written before any read.
- `track << flipped_track` draws the flipped path; it drew the unflipped one.
- A Line made with `parallel_to=`, `perpendicular_to=` or `circle=`, or an
  Ellipse made with `from_rect=`, becomes a plain shape where it is when its
  relation goes: `unlink_all()`, unlinking one of its linked parts, or
  destroying the line, circle or rect it follows. Before, it kept following
  the relation in part (a parallel line's `move_by` did nothing, a tangent
  line still orbited), and `force=True` left an ellipse whose center still
  followed the rect.
- A Line with both ends on one point turns its heading on a flip; it kept
  the old one. A tangent Line of length 0 refuses a flip, as it does at any
  other length; it accepted the flip and kept drawing the tangent heading.

- A look on a white, gray or black shape stays neutral. `Neon()` drew a red
  tube when the shape was white (tutorial 01, `triangulo.color = "white"`),
  gray or black; `DashRing`, `GearShell`, `ElectricBolt` and
  `Halo(style="fill")` / `Halo(style="soft")` turned pink. Same for
  `Neon("white")` and the other looks seeded with a gray, and for
  `Color.vibrant_version()` on a gray. Near-whites (snow, ivory) get a light
  tint instead of a full color. Colors with any real saturation look as before.
- `Color` methods no longer invent a red hue for a gray: `saturate`,
  `jitter(saturation=)`, `accent_color` and `monochromatic` on white, gray or
  black give grays (before, reddish tints), and `Color.interpolate` /
  `Colormap` in `ColorSpace.HSL` or `HSV` from a gray take the other end's
  hue (white → blue passed through magenta). `Color("gray").jitter()` with a
  fixed seed now gives different (gray) colors.
- Collision callbacks survive park and `collidable`. `on_collide`,
  `on_collide_stay` and `on_collide_exit` (a function or a method in the class
  body) stopped firing after `active = False` then `True`, or `collidable =
  False` then `True`: a pool or respawn game silently stopped reporting hits.
  `on_collide = f` while parked now waits for `active = True` (before, it
  joined collision at once and the actor then never collided with its groups
  again), and the actor rejoins every `@collide` group declared meanwhile.
- `collidable = False` written before any `@collide` is honoured: the actor
  stays out of collision whatever order the lines run in.
- A parked actor with `collidable = True` stashed refuses `layer = "ui"` (and
  a parallax layer) when written, not later on `active = True`, which left
  the actor half resumed. `resolve_now` on a parked actor returns `[]`.
- `on_collide = 5` raises TypeError at once (it crashed in the next frame).
- `remove_hitbox` on a destroyed sprite raises DestroyedError (it returned
  silently). `repr(sprite.hitbox["active"])` works (it raised
  AttributeError), and a hitbox repr no longer runs an `active` link.
  `hb.tagged(["a"])` raises Scena's TypeError instead of "unhashable type".
- `svg.svg = None` clears an Svg to the checker, as `Svg(None)` builds it; it
  was ignored while a good picture was showing.
- Sheet: re-registering a clip replaces its `offset=` (it clashed with its own
  old offset, or kept it when `offset=` was dropped); `showing(True)` raises
  after `showing(1)` (they shared a cache entry); a binary file given as
  `atlas=` raises "not UTF-8 text" instead of Python's codec error; a missing
  file loaded with `cell=` alone keeps every clip (each index shows the
  checker); an image path that matches only because the disk ignores letter
  case warns once (it fails on Linux) and shares one cache entry with the
  right spelling.
- Messages instead of Python's own errors: `middle_point(…, weight="x")`,
  `Circle.from_corners(radius=lambda: 5)` (a one-shot copy: it takes a
  number) and `pos="top_left"` (strings are accepted), `rp.points["a"]`,
  `Polygon(points="abc")`, `Warp.spokes`, Lattice `layers` / `size` /
  `layer_scale`, `DropDown.selected_index = True`, Portal knobs and Sprite
  `tilt` / `offset` / `art_angle` with a huge int. `Polygon(points=<a
  generator>)` works (it is read once). `help(EquilateralTriangle)` no longer
  lists `n=` (still accepted as 3).
- The error for writing a computed point names a move that works: on a line
  or ellipse that follows a link (a tangent line, an ellipse built from a
  rect) it adds `force=True`, which frees it first; on a parallel line it
  says to change `dist`. Before, it suggested a `move_to` the link refused.
- A destroyed focal-points Ellipse's `box` reads the same every time (it
  raised twice, then returned a 0 × 0 box); `box` no longer warms the
  ellipse's computed fields.
- `track.rotate_by(…, about=(x, y))` checks the pivot like every other kind
  (a tuple went past the point reader).
- Faster, with the same results: an instant `move_to` (about a third less:
  it no longer computes an unused pivot), a free Polygon's `move_by` (about
  7×), a Line turned about its center (about 2.5×), `destroy()` (about half),
  a second Sheet over the same image files (it reuses the first one's
  hitbox fits: about 10 ms → 0.4 ms), and every moving actor in a frame (no
  attribute lookup falls through to the slow path).
- Sheet and Sprite warnings (missing file, replaced clip, letter case) name
  the line in your program; they named a file inside Scena.
- A SPINE Rect (`Rect(p1=, p2=, height=)`) with a linked `angle` reads again:
  once the link turned it, every read raised LinkedAttributeError.
- A SPINE Rect's `angle` after its ends move no longer depends on what your
  program read in between. It counts full turns like a `Line(p1=, p2=)`:
  only `rotate_by` / `rotate_to` add turns, and an end write reads the new
  direction nearest to them. Before, a rect whose `angle` had been read could
  read a full turn away (204.78 instead of -155.22) after the same writes.
- `Texture(filename=[])`, `mouse.click_pos([])` and `State().create([])` /
  `exists([])` raise Scena's TypeError instead of Python's "unhashable type".
- An author class named `Point` or `Line` behaves like any other class with
  bracket fields (`obj["hp"]`); the strict rule for the real Point / Line
  went by class name.
- A linked heading or zoom (`sprite["angle"] @= …`, `poly["scale"] @= …`) on a
  Sprite, Point, Polygon, Text or Track refuses `rotate_by`, `scale_by` and
  `angle =` with LinkedAttributeError (`force=True` unlinks); the write was
  silently dropped. A shape linked as a whole (`shape @= other`) refuses a
  verb that would move it; the verb ran and the link snapped the shape back.
- A part that a verb does not move may stay linked:
  `Circle(center=lambda: ship.center, radius=5).rotate_by(5)` turns the
  circle (it raised), and so do scale and flip about the center on Circle,
  Line, Rect, Square and Text, `text.angle =` with a linked pin, and a Point
  with a linked heading that moves.
- Hovering or clicking a shape no longer slows its later moves: one pointer
  test woke computed parts for good (a hexagon's `move_by` + `rotate_by` went
  from 2.8 to 58 µs).
- Big sprite sheets bake each frame's hitbox and silhouette once. A sheet of
  about 200 cells with `hitbox="each"` re-fitted on every frame advance.
- Atlas frames that share pixels but differ in trim or rotation get their own
  hitbox and silhouette; they shared one, shifted by the trim.
- A sprite stretched after construction (`width *= 2` on a `height=` sprite)
  updates its Shield; a later `sheet.clip(..., offset=)` moves the drawn
  frame, not only its hit test.
- Writing a new list, `Vec2` or numpy array to a field that held an equal one
  stores the new object; a numpy array used to raise.
- Animation frames land on time: each frame of a clip showed one game frame
  late. A one-shot clip can be played again on a hidden or off-screen sprite,
  and `play(..., next="idle")` starts `idle` when the first clip ends, not when
  the sprite is next drawn. A clip started while `time_scale = 0` shows its
  first frame. `time_scale = -1`, `nan`, `inf` or `True` raise; they froze the
  clip or crashed every draw.
- `sprite.color = "blue"` with no look draws nothing extra on any path; it
  stroked a blue outline once a shadow or trail was on. A `Recolor` look
  follows the sprite's `alpha` and `blend`.
- `svg.svg = ...` with art of another shape keeps the side you sized and the
  new art's proportions; it stretched the art into the old box. `sprite.size`
  after `size = 0` keeps the proportions.
- `wheel_rotate = True` on its own makes a shape turn with the mouse wheel; it
  needed another pointer flag. A Point built on a layer comes back on it after
  `visible = False` / `True`; it came back on `top`.
- A tangent line from a point (`Line(circle=, from_point=)`) turns about its
  circle's center, staying tangent; `rotate_by(30)` turned it 14.6° and
  `scale_by(2)` shrank it. Scaling or moving such a line, or turning any
  tangent line about another pivot, raises LinkedAttributeError (it was
  ignored); `force=True` frees the line first.
- A tangent line at an angle (`Line(circle=, at_angle=)`) reads one heading:
  `line.angle` and `rotate_to(line.angle)` agree (it added a full turn).
- `point.rotate_to(90, about=p)` turns the point by `90 - point.angle` about
  `p`, like every other shape; it placed the point at polar angle 90.
- `move_to(point, 50)` and `move_by(vec, 5)` raise TypeError; the second
  argument was ignored.
- A copy acts like its source. `copy << shape` and `absorb` now carry the
  flips, the heading with its full turns and the scale, so the next
  `rotate_to` or flip agrees; `clone()` keeps the model (a cloned
  `Line(center=, length=, angle=)` can take `length = 20`; it raised). A copy
  of a line made with `parallel_to=`, `perpendicular_to=` or `circle=` (or an
  ellipse made with `from_rect=`) is a free line or ellipse: it moved and
  scaled wrong before. `force=True` on such a shape frees it the same way.
- `polygon << regular_polygon` takes the polygon's corners; they all read
  (0, 0). A clone of a parked actor is visible.
- A refused call changes nothing. Before, these raised but left a change behind:
  `flip_x = True` on a linked or destroyed shape kept the flag; a Polygon
  with one linked vertex moved the others; `tag("a", 5)` claimed `"a"`;
  `point.handle = True` / `draggable = True` showed the point;
  `sprite.play("big")` with a linked `width` half switched the clip, and
  `play(..., next="big")` raised later from the frame loop (it now raises at
  the `play` call); `reset_rotation()` cleared the tilt; `sheet.strip(...,
  offset="bad")` added the frames; `clone(scale="x")` left a live clone; and
  `show_handles()` on a shape linked as a whole (`shape @= other`) showed
  handles before raising (it now skips them, like any linked point).
- `rect << box` copies the Box's region; it switched the Rect's model and
  then raised AttributeError, leaving a 0 × 0 rect.
- `clone()` of a destroyed actor raises DestroyedError; it returned a live copy.
- `c.center = (5, 5)` and `c.center << p` on a destroyed shape raise
  DestroyedError; they moved it.
- `line_width = 0` draws no outline. It drew a one-pixel hairline, so a
  tween or formula that ended at 0 left a thin line behind.
- Paint writes on a destroyed actor (`line_width`, `fill`, `visual`,
  `set_alpha`, `look_like`, …, and a Sprite's `alpha`) raise DestroyedError,
  as `set_color` already did; they were stored silently.
- A look a Shape refuses (`shape.visual = Recolor(…)`, a Sprite-only look)
  keeps the current look; it stripped it first.
- `sprite.restore_visual()` restores the body `alpha` too; it reset it to 1.
- A ghosting look (`Liquify`) on a Gradient or Texture fill no longer leaves
  the body drawn at the ghost's alpha.
- A class whose `setup()` raises leaves nothing behind. Before, the actor
  stayed alive, drawn and in its groups, and its `@every` kept ticking; an
  `__init__` that set `on_collide` and then raised left its collision body
  behind for good.
- `class Enemy(Damageable, Circle)`, with a mixin that defines `__init__`,
  runs `setup()`, `on_update`, `@every`, `@when` and `@collide_with` like any
  other actor class, and a constructor that raises rolls back. Before, none of
  them ran.
- A hitbox part with a linked `active` (`hb["active"] @= fn`) runs `fn` once
  per frame; it ran once per contact, and a collision handler that changed
  what `fn` reads fired `@collide_exit` for contacts that never entered.

- `canvas.background = canvas.background` keeps the background; it raised
  TypeError (a read gives the whole live background, a write expected a
  colour). To save the background and restore it later, keep
  `canvas.background.base`.

- A method called on an empty group does nothing for every kind of object, as
  the Guia says. `group["inimigos"].play("andar")` (and `showing`,
  `add_hitbox`, `flash_text`, … — methods a Shape does not have) raised
  AttributeError once the group had no member left. A misspelt method still
  raises.

- `amp_db(st.nivel)` takes a cell, like every other number argument.

- A formula built after you edit and save the script while it runs links what
  the running code reads. Before, Scena read the edited file at the old
  positions: it said "formula has no reactive sources", or linked another
  lambda's names. A named function whose source changed now says the file
  changed on disk and asks for a restart.

- `test_collision(a, b)` returns what a `@collide` handler sees: `info.a` is
  `a`, `info.b` is `b`, and the normal points from `a` to `b` (`info.side` is
  `a`'s side). It returned internal objects in `info.a` / `info.b` and, for
  about half of the pairs, the normal and side of the other body.

- `deadzone(..., size=st.folga)` takes a cell, like every other number
  argument; it raised TypeError.

- A timer whose time is a whole number of frames fires on that frame. At a
  steady 60 FPS, `after(0.5)` fired on frame 31 and `every(0.25)` first on
  frame 16 (the frame times summed a hair short of the deadline), while
  `every(0.9)` was on time. The same for a timed move's end, `ready()`,
  `recently()` and effects like `flash` / `pop`.

- A verb on an empty group (`group["tiros"].move_by(0, 600 * dt)` while no
  shot is alive) built a hidden shape on every call, about 0.3 ms each, every
  frame. It now does nothing, as the Guia says, and returns `None` (it returned
  that hidden shape); with `time=` it still returns a Handle.

- `keyp.once("SPACE")` is True only in the frame of the press, as the Guia
  says. Before, a press nobody read in its frame waited for the first reader,
  however late: in `if pronto and keyp.once("SPACE")`, a SPACE pressed while
  `pronto` was False fired seconds later, when `pronto` turned True, and a
  key held since before was reported on its first read. A script that relied
  on that (pressing jump in the air to jump on landing) should keep the press
  itself: `if keyp.once("UP"): st.quer_pular = True`.

- A point linked to a caption's centre (`marker @= text.center`) now follows
  `text.move_by` / `text.move_to` and, for a caption placed by a corner
  (`top_left=` …), a new string too; it stayed where the caption was.

- A list is a point wherever a tuple is: `p << [1, 2]`, `p + [1, 2]`,
  `v + [1, 2]` worked in some places only. A state cell holding a pair works
  wherever a point does (`p + st.offset`, `v + st.offset`). `v << point`
  and `v + "a"` now say why a Point is refused (a Point is a place, a Vec2
  a displacement: the vector between two points is `p - q`).

- A Box placed by `top_left` whose corner names were mirrored (copied from a
  flipped shape) now places and turns like a Rect with the same names; before,
  its points came out where an unmirrored box would be.

- A constructor now refuses NaN or infinity in any number, as `=` does:
  `Rect(…, angle=float('nan'))`, `Line(…, dx=…)`, `Point(nan, 0)` raise
  ValueError (before, the value was stored and the shape vanished).
  `track.begin = fn` and `line.angle = fn` on a line placed by two points raise
  the usual "`=` copies a value, link with `@=`" error.

- A shape linked whole to another (`copy @= rect`, `copy @= lambda: rect`)
  now keeps every point you already read in step: before, `copy.top_right`
  stayed where it was after the source changed, while `copy.width` followed.

- `a << b` between two shapes of one kind built differently (a Rect from
  corners copied into a Rect made from a center) now reads like `b` and takes
  writes to `b`'s inputs; before, sizes and points read stale and
  `a.p2 = …` raised. A Track copy draws the source's path and pose, Box can
  copy a Box (`box << other_box` raised), and `track.reversed() << other`
  raises with the fix instead of doing nothing. `square << rect` raises a
  TypeError that shows how to build the Square from one side (it raised
  AttributeError).

- A shape turned by a link on its `angle` (a Line from two points, a Circle
  placed by its rim, an Ellipse by its foci, a spine Rect) showed its old
  points when you read them (`line.p2`, `line.vec`, `ellipse.fp1`) before
  reading `angle`, after the source had moved. Any order of reads now sees the
  turned shape.

- A Line whose heading comes from its points (`p1`/`p2`, `p1`/`vec`,
  `p1`/`dx`/`dy`) accepted `line["angle"] @= …` together with a link on `p1` or
  `p2`, then raised `LinkedAttributeError` on every read of `angle`. The second
  link now raises at the `@=` and installs nothing: turning the line rewrites
  the point, and a point with its own formula cannot be rewritten.

- A link onto a number field (`p["x"] @= lambda: …`, a shape's `angle`, a
  Track's `begin` / `end`) whose function returns NaN or infinity now raises
  `ValueError` on the read that pulls it, as writing the same value with `=`
  does. Before, the link stored the NaN and every read after it was NaN. A vector or
  point linked whole (`v @= lambda: (x, y)`) is not checked, like `v << (x, y)`.

- A parallax layer's `scroll` moved only when the frame was drawn: `update`
  saw last frame's offset, and a run that did not draw never scrolled. It now
  advances with the clock, before `update`.
- `canvas.playfield.set(left=..., ...)` accepted NaN and infinite edges and
  stored them; it now raises `ValueError`, like the single-edge setters.
- `canvas.layers.create(..., scroll="ab")` (or a 3-item tuple) failed with an
  unrelated error; it now raises `TypeError` naming the pair form, like
  `background.scroll`.
- A write to a name a layer does not have now raises instead of being stored
  and ignored. `layer.visable = False` raises `AttributeError: layer 'far' has
  no 'visable'. Did you mean 'visible'? Writable on a layer: visible, z,
  post_fx, scroll.` The camera-response knobs (`pan_response`,
  `zoom_response`, `rotation_response`) are still set only in
  `canvas.layers.create(...)`; writing one on the layer afterwards raises with
  that call (`scroll` became live, see Added). Code that wrote such a name did nothing before, so a script that
  ran keeps the same picture once the line is fixed or removed.
- The same holds for every other author object except actors and `st`:
  effects (`Bloom`, backgrounds, audio effects, looks and filters you build),
  `canvas`, `canvas.effects`, `canvas.background`, `canvas.playfield`, `ui`,
  `audio`, `clock`, `mouse`, `keyp`, `collision`, `ready`, `recently`, and
  values such as `Box`, `Grid`, `Color`, `Palette`, `Gradient`, `Texture`,
  `Sheet`, `History`, `Sound` and `Level`. `bloom.itnensity = 2` raises
  `AttributeError: Bloom has no 'itnensity'. Did you mean 'intensity'?
  Writable on Bloom: enabled, intensity, sigma.` Each such write did nothing
  before. Your own data still goes on an actor (`ship.hp = 3`) or in `st`.
  A subclass you write (of `History`, say) keeps its own
  fields when it creates them in its `__init__`; a new name created later in a
  method now raises and says to create it in `__init__`.
- `Vec2` is closed too: `v.lenght = 5` raises `AttributeError: Vec2 has no
  'lenght'. Did you mean 'length'? Writable on Vec2: x, y.` It used to store
  a `lenght` that nothing read. Vector arithmetic is as fast as before (a
  little faster).
- Writing a computed field of a shape now says what it is computed from and
  how to get what you wanted. `rect.top_right = (1, 2)` on a rect placed by
  its center: `Rect.top_right is computed from the rect's center, width,
  height and angle, so it cannot be set. To move the rect so its top_right
  lands at (1, 2), write rect.move_to(1, 2, about=rect.top_right).` A size
  (`line.length = 5` on a line between two points) names the inputs to change
  and, when there is one, the constructor that takes it
  (`Line(..., length=...)`). The old message told you to "construct the
  shape with a different model", which made no sense for `Text` or `Track`.
- `rect.top_right << (1, 2)` on a computed point now raises the same error.
  It used to move the point by itself, leaving the rect where it was, so
  the point no longer matched the rect.
- `v.length = 5` and `v.angle = 30` on a `Vec2` now say how to do it:
  `v << vec_from_angle(v.angle, 5)` keeps the direction and sets the length,
  `v << vec_from_angle(30, v.length)` turns it and keeps the length. The old
  message talked about a shape's model.
- A `Vec2` linked whole (`v @= lambda: vec_from_angle(st.heading, 10)`) read
  `length` and `angle` as 0, or as their values from before the link; a
  formula reading them saw the same. They now follow `x` and `y`.
- A field you linked could keep its old value after its source changed:
  with `ship["hp"] @= lambda: st.hp`, reading a size or a corner of the ship
  first (`ship.width`, `ship.top_left`) made `ship.hp` return the previous
  value until the source changed again. Same for a linked `spread` on a
  `Circle`. Fixed for every actor kind.
- A linked `vec` part (`rect.vec["x"] @= …`) and the `vec` of a Rect or Box
  built from two corners could report an old `vec.length` / `vec.angle`.
- `track["begin"] @= …` / `track["end"] @= …` now keep the value between 0
  and 1, as `track.begin = …` does.
- `v @= lambda: st.pos` and `v << st.pos` work when `st.pos` holds a tuple or
  a `Vec2` (on a `Vec2`, a `Point`, or a shape's point such as
  `circle.center`). They raised `TypeError`.
- `st.pos.x = 5`, where `st.pos` holds a `Vec2`, now raises. It used to store
  `x` on the cell: `st.pos.x` read 5 while the `Vec2` and everything linked to
  `st.pos` kept the old value. The error names the write that works:
  `st.pos = Vec2(..., st.pos.y)`.
- `ship.vel @= lambda: …` raised a confusing `LinkedAttributeError`
  (`Circle.Circle_vel is linked — call Circle['Circle_vel'].unlink() first`),
  and `ship.vel["x"] @= …` linked without complaint until the next
  `resolve(..., bounce=)`, `confine(action="bounce")` or `vel.y -= …` raised.
  `.vel` is not linkable — the engine writes it — and every spelling now
  raises the message `ship["vel"] @= …` already gave: set it where it changes,
  `ship.vel = vec_from_angle(st.a * 30, 10)` in `on_update`.
- `field_type` and `parts` are read-only on every object (`ship.field_type = 3`
  broke the actor's links; `v.parts = ...` lost its parts).
- A new actor field one swap of two adjacent letters away from a 5+ letter
  property now raises instead of becoming a field: `ship.anlge = 30` →
  `Did you mean 'angle'?` (also `widht`, `aplha`, `lyaer`, `gruop`, `nagle`).
  A field you meant to call `nagle` needs another name.
- `"lightcyan"`, `"darkblue"`, `"lightgray"`: a `dark` / `light` / `faded`
  prefix written without a space is the same name as with one, like
  `"deepskyblue"` already was. Before, they painted magenta with a warning
  (`"lightpink"` became hot pink). A typo keeps its prefix in the
  suggestion: `"lightcyna"` → `light cyan`.
- `jet.color = "cyan"` after the constructor works on `Jet`, `Sparks`,
  `Starburst` and `Rain`, as it already did on `Orb`, `GlowSpot`, `Warp`,
  `Portal` and `Sunburst`. Before, the name was stored as text and the next
  frame raised `ValueError: too many values to unpack`.

### Documentation

- Act Design lists the UI theme (`ui.scale`, `ui.font`,
  `ui.min_label_space`) as preferences an act may change for good, and the
  HUD column cursor as a setting the change restores.
- Scena Design has a "Clocks" table: which clock (world, presentation,
  wall) each consumer reads. Actors Design no longer says an `on_destroy`
  error is swallowed (it raises after the teardown, as the code does).
- Testing Design gains an "Interaction campaign" section: how the seams
  between subsystems are tested (a matrix with a guard, a model-free
  oracle, a canary per class), the ten classes, their findings, and one
  open design question (RX1: a formula that reads only `canvas.game_view`
  never re-evaluates).
- A new landing page, `README.md` (it replaces `README.txt`, and PyPI shows it
  too): what Scena is for, a whole game in one screen of code, the features
  with short examples, clips of the example games, install, the tutorial and
  the Guia. Its clips are recorded from the real programs
  (`tools/readme/make_readme_media.py`), and its code is tested.
- The Guia now says what several features did without saying it:
  `Button.on_click` fires on release (releasing elsewhere cancels); `zoom_by`
  without `about=` keeps the pan; the widget under the pointer keeps the mouse
  wheel; `.angle` accumulates past 360; a `Slider` never rewrites its cell;
  a destroyed object leaves its groups at once; `st.x` reads the cell
  (`st.x.value` for the plain value); `.scale` leaves `.width` / `.height` as
  given (`.box` is the drawn size); `every` first fires one interval in;
  `e.after(d, fn)` passes the object to a one-parameter `fn`; another key held
  does not change `keyp("A")`; `canvas.game_view` at the start; `confine`
  stops exactly at the edge; `Color.darker` / `lighter` move HSL lightness;
  two layers made `below=` the same one share a z (the newer draws on top).
- `.color` reads the colour the shape paints now: under a look such as `Halo`,
  that is the look's tint (alpha included), not the colour you gave; under
  `Flame` / `Swell` / `Water`, which have no single colour, it is the colour
  you gave.
- Four new tutorials (Portuguese): 09 Bolas (`resolve`, `vel`, `mass`,
  `Tail`, the camera zoom), 11 Avião (a sheet of files with two clips,
  inertia with `chase`, an invisible score gate, restart by hand), 12 Avião II
  · Profundidade (parallax layers with `scroll=`, `Endless` with one image,
  one speed that brakes everything, music) and 13 Avião III · Paisagem sem
  fim (`Endless` with a list, a builder with `slot.rng` / `slot.chance`, a
  layer in front of the game). 10 (Ateliê) has a card and no page yet. Their
  endpoints are `examples/bolas.py`, `aviao.py`, `aviao_profundidade.py` and
  `aviao_paisagem.py`.
- The coyote-time example in the Guia re-applied the jump for several frames
  (a 30 % higher jump); it now calls `recently.reset` after jumping, and the
  note that repeating `vel.y = PULO` "dá no mesmo" is corrected.

## 0.6.0 — 2026-10-06

### Breaking

- The framework is now **Scena**, and the package is `scena` (the name
  `stage` is taken on PyPI by an unrelated package). Before: `from stage
  import *`. After: `from scena import *`. Nothing else in the API changes
  name. The old import fails with `ModuleNotFoundError: No module named
  'stage'`; there is no `stage` package to keep it working, because it would
  hide the unrelated one. To update an install made from this repository:
  `pip uninstall stage`, then `pip install -e .` (or `pip install scena`).
  - **Level files** are written with `"format": "scena-level"`. Files saved
    with `"stage-level"` still load (same version, same data); the editor
    saves them with the new tag.
  - **The editor** is `scena-editor` / `python -m scena_editor`. Run
    `scena-editor --shortcut` again: it makes the "Scena Editor" launcher and
    removes the old "Stage Editor" one. The error log moved to the "Scena
    Editor" folder (`scena-editor` on Linux); the old log stays where it was.
  - Messages say **SCENA WARNING** / **SCENA ERROR**, and a window with no
    `title=` is titled "Scena".
- `Scene` is now `Act`, and `change_scene` is now `change_act` (the framework
  is moving to the name Scena, and `Scene` inside Scena says the same word
  twice). Before: `class Fase(Scene): …` and `change_scene(Fase)`. After:
  `class Fase(Act): …` and `change_act(Fase)`. `run(Titulo)` is unchanged.
  With `from scena import *` the old names are gone (`NameError: name
  'Scene' is not defined`); `scena.Scene` / `from scena import Scene` raise
  with the fix: `TypeError: Scene was renamed to Act in 0.6.0. Write class
  Fase(Act), and change_act(Fase) to enter it.` (and `change_scene` the same
  way, `Write change_act(Fase).`). Also renamed: `SceneUsageError` →
  `ActUsageError`, and the scope of ownerless work started after the top
  level ends, `handle.scope == "scene"` → `"act"` (a string compare cannot
  raise: a test for `"scene"` is now always False). The Guia chapter is
  "Atos".
- `Beat` and `Liquify` take `color` as their first argument, like the other
  visuals that paint a body. Before: `Beat(0.1)` meant `amount=0.1`. After:
  write `Beat(amount=0.1)`. The old spelling raises `TypeError: Beat's first
  argument is color (since 0.6.0). For the old Beat(0.1) write
  Beat(amount=0.1).` (same for `Liquify`).
- `burn_out(fidelity=)` is removed: every value (`"full"`, `"lite"`, `"auto"`)
  drew the same burn. Before: `ship.burn_out(0.5, fidelity="lite")`. After:
  `ship.burn_out(0.5)`. The old spelling raises `TypeError: burn_out(fidelity=)
  was removed in 0.6.0: it never changed the drawing … Delete it`.

### Added

- File patterns for frames: a file name with `*` loads every matching file,
  one frame each, in natural order (`Run (2)` before `Run (10)`). A pack of
  loose PNGs loads one animation per line:
  `ninja = Sheet(anchor="bottom")` then
  `ninja.strip("correndo", "ninja/Run__*.png", fps=12)`; one loop is
  `Sheet("robot/Run (*).png", fps=12)`. A pattern works wherever a list of
  files does (`Sheet` source and extra files, `strip`), searches the usual
  image folders and uses the first one with a match. Only `*` is special, in
  the file name only; matching is case-sensitive. No match is a placeholder
  frame and one warning naming the pattern and the folders searched.
  `cols=` / `rows=` / `cell=` / `atlas=` with a pattern raise `TypeError`.
  `strip` also takes a list of files (`strip("voo", ["a.png", "b.png"])`).
  A `*` in these file names used to be read literally (a missing file);
  `Sprite("…*.png")` used to show a placeholder and now raises `TypeError`
  pointing at `Sprite(Sheet("…*.png", fps=8))` (likewise `SpriteButton` art).
- `Collider` comes with `from stage import *` (it was documented with
  `from stage.collision import Collider`). Its author surface is
  `Collider(shapes)`, `.shapes` and `on_collide` / `on_collide_stay` /
  `on_collide_exit`; the engine members it used to show (`pair_targets`,
  `add_pair_target`, `unregister`, …) are now private.
- `Beat(color=)` and `Liquify(color=)`: paint the shape's body, like
  `Neon("red")`. `visual = None` keeps the color and a later `set_color` wins.
  Without `color` they keep the shape's own color, as before. A `Beat` with a
  color on a `Sprite` raises (a Sprite keeps its pixels; tint it with
  `sprite.hue = HueShift(to=…)`).
- `set_color` under a look that paints its own colors (`Flame`, `Swell`,
  `Water`, `Shield`) now warns once per look: the color is kept and shows
  after `visual = None`.
- A `st` cell (and a widget's `.data`) does math like its number with every
  operator: `**`, `//`, `%`, `divmod`, three-argument `pow`, `round(st.x)`
  (with `ndigits`), `math.trunc` / `floor` / `ceil`, and `complex()`, from
  either side (`2 ** st.f`). Before, these raised `TypeError: unsupported
  operand type(s) for ** or pow(): 'Attribute' and 'int'`, so `st.f ** 3` had
  to be written `float(st.f) ** 3`; that still works. Like `+` and `*`, the
  result is a plain number, and `st.f **= 2` writes into the same cell.

### Fixed

- `Collider(...)` with something that is not a shape or sprite (a function,
  a number, a string, a point tuple) now raises `TypeError: Collider pieces
  must be shapes or sprites; got function. Write Collider([torso, head]).`
  Before, it was accepted and left an empty body in the collision system that
  nothing could remove.
- `shape.color` under `Flame` or `Swell` read navy `(0, 0, 0.5)` instead of
  the shape's color.
- A fast shot no longer passes through what it should hit. A body that moves
  (`move_by`, `move_to(..., time=)`, `move_along`) more than half its own
  thickness in one frame is now checked along its whole path, so `@collide`
  fires the same way at any frame rate. When the path crosses several targets,
  the nearest one's handler runs first. The hit's `info.point` is where they
  met and `info.depth` is `0`. Also fixed: a fast body pushed into a thin
  `resolve()` wall now fires `@collide`. Nothing to change in your code; a
  game that relied on fast shots passing through will now see the hits.
  Placement (`center =`, `@=`, `tween`) is still not checked along the way.
- An object turning around another point (`rotate_by(..., about=pivot)`,
  with or without `time=`) now travels: a fast orbit is checked along its
  path like a `move_by`, and a `resolve()` wall stops it instead of letting
  it jump through. Before, the orbit placed the object, so a fast orbiting
  shield or satellite could pass through what it should hit. Instant
  `rotate_to(..., about=)` still places, and spinning in place
  (`rotate_by(30)`) is still not checked along the way.
- The `Anchor` docstring said `Line(p1=a.center, p2=b.center)` follows the
  Anchors. It does not: a bare `a.center` (or `a`) is copied once when the
  Line is built. The docstring, the Guia and the design docs now show the
  live spelling, `Line(p1=lambda: a.center, p2=lambda: b.center)`. Behavior
  is unchanged.

### Documentation

- The design docs (`design/*.md`) are self-contained: each decision
  carries its reason in the doc that states it. A fence or rejection says why
  the alternative lost; a performance rule gives the number it rests on
  (scene, machine, before → after). New "Not taken" tables in Tracks, Box and
  Canvas Design; reasons added across Collision, Effect System, Sprite,
  Shapes, Reactive, Actors and Act Design. The docs no longer link to plans,
  deliberation or lab notes.
- Those plans, deliberations, dated bench notes and retired lab scripts, and
  the guides for writing tutorials and examples, are private
  (`workbench/`) and not part of the repository. `scripts/bench/results/` (bench output) is no longer
  tracked; the bench runners create it.
- `tests/test_doc_links.py`: a published file (doc, code comment, test,
  script) that cites one of those private files, or a relative link whose
  file does not exist, fails the tests.
- New layout. `design/` holds the design docs (was `documentation/`).
  `docs/` is the author site, published with GitHub Pages: the Guia is
  `docs/pt/guide/index.html` (was `documentation/API Guide/Guia da API.html`),
  the tutorials are `docs/pt/tutorial/` (was `tutorial/`), and `docs/en/`
  will hold the English versions. The Guia's tools moved to `tools/guide/`.
- `examples/` now holds the tutorials' finished scripts, with names that match
  the tutorials: `primeiro_script.py`, `pegar_estrelas.py`, `ponto_medio.py`,
  `cadeia_de_bolas.py`, `barras_girando.py`, `osciloscopio.py`, `naves.py`
  (were `app_primeiro_script.py`, `app_star_catch.py`, `app_geometria.py`,
  `app_mouse_v2.py`, `app_spinning_rects.py`, `app_osc_v2.py`, `app_naves.py`).
  The other sample games are being reworked and come back when ready.

## 0.5.0 — 2026-10-05

The first numbered release: the API is published, and authors outside the
project now write code against it. Everything before was the design phase,
with no compatibility promise and no changelog. The author surface at this
release is `stage.__all__`, described in the
[Guia da API](docs/pt/guide/index.html), and level
files are `"format": "stage-level", "version": 1`.

### Added

- `stage.__version__`.
