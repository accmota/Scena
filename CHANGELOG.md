# Changelog

What changed for authors, one section per release. Versions follow
`MAJOR.MINOR.PATCH`. While Scena is 0.x, a **minor** release (0.6.0) may break
author code and a **patch** release (0.5.1) never does. The policy for breaking
changes: [Scena Design.md — Compatibility and versions](design/Scena%20Design.md#compatibility-and-versions).

Each release lists **Breaking** (before → after, and the error the old
spelling now raises), **Added**, **Fixed**, and **Documentation** (changes to
the docs and the repository a reader notices). A section with nothing in it is
left out.

## Unreleased (0.7.0)

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
  (`step=(w, h)`). `.index_at(x)` tells which slot holds a point (score by
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

### Documentation

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
