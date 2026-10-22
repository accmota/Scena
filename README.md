<h1 align="center">Scena</h1>

<p align="center">
  <b>2D games and creative graphics in Python.</b><br>
  Built for learning. Easy to begin, room to grow.
</p>

<p align="center">
  <a href="https://accmota.github.io/Scena/pt/tutorial/">Tutorial</a> ·
  <a href="https://accmota.github.io/Scena/pt/guide/">API Guide</a> ·
  <a href="https://github.com/accmota/Scena/tree/main/examples">Examples</a> ·
  <a href="https://github.com/accmota/Scena/blob/main/CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/naves_escudo.webp" width="600" alt="Naves: a space shooter from the tutorial. A red ship fires at a breathing fleet, enemies explode, and a plasma shield catches the enemy fire.">
</p>

Scena is a Python framework for 2D games and creative graphics, built for
learning and for making good games without the complications.

You write the game: what is on the screen, how it moves, what happens when two
things touch, what comes next. Scena gives you a vocabulary in which each of
these is a line or two that says what it means, and it takes care of the
machinery underneath: the loop, the drawing, the timers, the cleanup. A first
program is three lines, a whole game fits on one screen, and with over 100
ready-made looks, effects and backgrounds it looks good from the start.

## A whole game, one screen of code

<!-- clip: catch-the-stars -->
```python
from random import uniform
from scena import *

init(width=800, height=600, title="Catch the stars")
Wallpaper("dark navy")

st.score = 0
label = Text(text="", top_left=(20, 580), font_size=22)
label["text"] @= lambda: f"Stars: {st.score}"

paddle = Sprite("k-rolling-ball/button_blue.png", width=90, center=(400, 50), group="paddle")


@every(0.5)
def drop_star():
    star = Sprite("k-rolling-ball/star.png", size=36, center=(uniform(40, 760), 580), group="stars")
    star.glow = True


def update(dt):
    if keyp("LEFT"):
        paddle.move_by(-420 * dt, 0)
    if keyp("RIGHT"):
        paddle.move_by(420 * dt, 0)
    group["stars"].move_by(0, -180 * dt)


@collide("paddle", "stars")
def catch(paddle, star):
    star.destroy()
    st.score += 1
    paddle.pop(scale=1.25)


@leave_playfield("stars")
def missed(star):
    star.destroy()


run()
```

<p align="center">
  <img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/catch-the-stars.webp" width="560" alt="The program above running: stars fall, the paddle catches them, the score counts up.">
</p>

No game loop to write, no event queue to poll, no list of objects to draw or to
clean up. The label is a formula (`@=`): it keeps up with the score by itself.

## Why Scena

- **Built for learning.** The first program is a few lines; the concepts arrive
  one at a time, in the order a learner needs them. Programming is the point, so
  nothing is hidden behind a wizard.
- **Simple things are simple.** `Circle()` draws a circle. `Sprite("ship.png")`
  shows a ship. Parameters are gradual: start with `Circle()`, then
  `Circle(center=(200, 150), radius=40)`, then `circle.visual = Neon("cyan")`.
  Add detail only when you want it. This is the philosophy of the whole
  engine: nearly every feature works in a short, simple form, and has the
  vocabulary for more when you want it. Easy to begin, room to grow.
- **Code that says what it means.** `@collide`, `@when`, `@every` and `@click`
  read like the rules of the game. A formula (`@=`) states a relation once, and
  it stays true. A health bar that rides above the hero and shrinks with each
  hit, with no update code:

  ```python
  bar = Rect(width=60, height=6, color="lime green")
  bar["center"] @= lambda: hero.center + (0, 40)    # rides above the hero
  bar["width"] @= lambda: 60 * st.life / 100        # shrinks with each hit
  ```
- **You write the game.** Scena handles the machinery, never the decisions. It
  does not invent content or behavior you did not ask for: what is on the
  screen is what your code says.
- **Mistakes explain themselves.** A misspelled key, color or parameter gets a
  message that says what was wrong and suggests the closest right name.

## What's in the box

**Shapes and sprites.** Circles, rectangles, polygons, lines, text, images and
sprite sheets. Every one draws with nothing but defaults, and takes more when you
want more. A sprite animates from a strip, a grid, one file per frame or a packed
atlas (TexturePacker JSON, Kenney XML), and its hitbox can come from the art.

```python
ball = Circle()                                     # a circle in the middle of the window
ball.color = "coral"
ball.visual = Neon("cyan")                          # one of 30 looks
hero = Sprite(Sheet("ninja/Run__*.png", fps=12))    # an animation from its frames
hero.glow = True
```

**Geometry.** Build a shape the way you think of it (center and radius, two
points, a point, an angle and a length), lay things out with boxes and grids, and
ask for intersections, closest points, midpoints and tangents. With points you
can drag and a few formulas, a compass-and-ruler construction stays live as you
move it.

```python
a = Anchor(420, 320)                                # points you can drag
b = Anchor(580, 380)
c1 = Circle(center=lambda: a.center, perimeter_point=lambda: b.center)
c2 = Circle(center=lambda: b.center, perimeter_point=lambda: a.center)
bisector = Line(p1=lambda: intersection(c1, c2, 0), p2=lambda: intersection(c1, c2, 1))
```

**Animation in one line.** Move by an offset, to a place, or along a track or a
shape's outline; by time or by speed; with easing, loops and yoyo, facing the way
you go. Turn, scale and fade the same way, or tween any number. Effects such as
`pop`, `flash`, `dissolve_out` and `explosion_at` clean up after themselves.

```python
ship.move_to(400, 300, time=1.5, ease="ease_in_out")             # to a place, in a time
ship.move_by(0, 200, speed=300)                                  # by an offset, at a speed
probe.move_along(orbit, time=4, loops="forever", face=True)      # along a path, facing ahead
enemy.scale_to(1.08, time=0.45, loops="forever", yoyo=True)
```

**Rules and time.** Conditions and timers are decorators, and `after`, `every`,
`wait`, `until`, `race` and `parallel` say how things happen over time. A
sequence reads like a script, top to bottom, with no state machine to build: a
boss arrives, waits, and starts the fight.

```python
@when(lambda: st.score >= 10)
def level_up():
    st.speed *= 1.5


class Boss(Sprite):
    def setup(self):
        self.mode = self.arriving

    @on_mode
    async def arriving(self):
        await self.move_to(750, 600, time=2, ease="ease_out")
        await wait(0.5)
        self.pop(scale=1.3)
        self.mode = self.fighting

    @on_mode
    async def fighting(self):
        ...
```

**Formulas.** Link a value to others once, in the constructor or later with
`@=`; Scena keeps it up to date.

```python
a = Circle(center=(200, 300), radius=8)
b = Circle(center=(600, 300), radius=8)
bridge = Line(p1=lambda: a.center, p2=lambda: b.center)     # follows a and b
size = Text(text="", font_size=18)
size["text"] @= lambda: f"{distance(a, b):.0f} px"          # measures it
size["center"] @= lambda: middle_point(a, b)                # and sits in the middle
```

**Collision.** A collision between objects or groups is one decorator. Ask for
automatic resolution and walls stop the hero; one-way platforms are one rule.
Hitboxes are made from the art, or shaped by hand when you want.

```python
collision.floor = True                                             # a world with gravity
resolve("hero", "walls")
resolve("hero", "platforms", only=lambda c: c.side == "bottom")    # one-way


@collide("shots", "enemies")
def hit(shot, enemy):
    canvas.explosion_at(enemy)
    shot.destroy()
    enemy.destroy()
```

**Looks, effects and backgrounds.** Over 100 ready to use: looks for shapes,
screen effects, animated backgrounds and one-shot explosions, all composable.
Any look works on any shape or sprite.

<!-- clip: electric-hosts -->
```python
from scena import *

init(width=900, height=300, title="One look, any host")
Wallpaper("dark navy")

ball = Circle(center=(150, 150), radius=70, color="royal blue")
star = RegularPolygon(n=5, center=(450, 150), radius=85, color="gold")
plane = Sprite("plane/Fly1.png", height=110, center=(750, 150))

for thing in (ball, star, plane):
    thing.visual = ElectricField()

run()
```

<p align="center">
  <img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/electric-hosts.webp" width="720" alt="The program above running: electric arcs flicker around a blue circle, a gold pentagon and a red plane.">
</p>

<table>
  <tr>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/visual-flame.anim.webp" width="240" alt="A circle with the Flame look"><br><code>visual = Flame()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/spatial-portal.anim.webp" width="240" alt="A swirling portal"><br><code>Portal()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/post-explosion.anim.webp" width="240" alt="An explosion"><br><code>canvas.explosion_at(x, y)</code></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/bg-stardust.webp" width="240" alt="A stardust background"><br><code>Stardust()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/spatial-fire~style-tongues.anim.webp" width="240" alt="Tongues of fire licking upward"><br><code>Fire(style="tongues")</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/fx-dissolve-out.anim.webp" width="240" alt="A ship dissolving"><br><code>ship.dissolve_out(0.5)</code></td>
  </tr>
</table>

**Mouse and widgets.** Everything a good interface, a board game or a strategy
game needs, made simple. Click, hover, drag, drop and wheel-rotate work on any
shape, sprite or group. Buttons, sliders, check boxes, drop-downs, menus and text
inputs bind straight to your game's state.

```python
@drag_to(token)                        # the token can be dragged; this runs when it is let go
def dropped(token, target, pos):
    if target is None:
        token.move_to(home, time=0.3)  # nowhere to go: back home


@hover(group["cards"])
def lift(card):
    card.scale_to(1.1, time=0.1)


Slider(st["radius"], label="Radius", min_value=10, max_value=100)
Button(label="New game", on_click=new_game)
```

Scena's own level editor is built with them.

**And more.** A camera that pans, zooms, shakes and frames; layers and
parallax; `Endless` worlds that build themselves as the camera moves and rebuild
the same piece when you walk back; tracks to follow; platform helpers (the floor
ahead, which sides touch, leaning on slopes); acts for menus and levels; sound
effects, music, filters and the microphone.

## Level editor

`scena-editor` comes with Scena, and is built 100% in Scena *(only Scena and
the system's Open and Save windows)*. Draw platforms, place points and images,
give them names and groups, and save a level file. The editor places geometry;
your code decides what each piece becomes.

<p align="center">
  <img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/scena-editor.webp" width="720" alt="The level editor with the Ninja IV level open: the view zooms in, three platforms are selected with a box and lifted together, then a star point is selected and its group shows in the side panel.">
</p>

```bash
scena-editor levels/ninja_perigos.json
```

```python
level = Level("levels/ninja_perigos.json")
for piece in level.group("chao"):
    piece.make()                                       # the shape as drawn
lift = level["elevador"].make(visual=Metal("gold"))    # or as you choose
```

## Gallery

Every clip below is a program from [`examples/`](https://github.com/accmota/Scena/tree/main/examples),
played and recorded by the computer (nothing is edited by hand). The games are
the last step of a tutorial. Line counts are code only, without blank lines or
comments.

<table>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/naves_4_escudo.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/naves_escudo.webp" width="380" alt="Naves"></a><br><b>Naves</b>: a space shooter with lives, explosions and a shield<br><sub>127 lines of Python</sub></td>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/ninja_4_perigos.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/ninja_perigos.webp" width="380" alt="Ninja IV"></a><br><b>Ninja IV</b>: a platformer built in the level editor, with robots and electric traps<br><sub>192 lines of Python</sub></td>
  </tr>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/aviao_paisagem.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/aviao_paisagem.webp" width="380" alt="Plane"></a><br><b>Plane</b>: fly between pillars over an endless, layered landscape<br><sub>120 lines of Python</sub></td>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/ligue4.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/ligue4.webp" width="380" alt="Connect Four"></a><br><b>Connect Four</b>: a board game for two, played by dragging the balls<br><sub>78 lines of Python</sub></td>
  </tr>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/corrida.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/corrida.webp" width="380" alt="Race"></a><br><b>Race</b>: pick the players and the track, then race the CPU cars<br><sub>425 lines of Python</sub></td>
    <td align="center"><a href="https://github.com/accmota/Scena/tree/main/examples"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/mais_exemplos.webp" width="380" alt="And many more"></a><br><b>And many more</b>: an oscilloscope, constellations, a duel, a runner, charges, a flock, a chain<br><sub>39 to 328 lines of Python each</sub></td>
  </tr>
</table>

## Install

Scena needs Python 3.12 or newer, on Windows, macOS or Linux.

```bash
pip install scena
```

Then, in any script: `from scena import *`.

To try the examples, download
[`scena-examples.zip`](https://github.com/accmota/Scena/releases/latest/download/scena-examples.zip)
(the examples of the latest release and the images and sounds they use), unzip it
and run one:

```bash
python scena-examples/naves_4_escudo.py
```

## Learn

- **[Tutorial](https://accmota.github.io/Scena/pt/tutorial/)**: from the first
  shapes to a space shooter, bouncing balls, a side-scrolling plane, a ninja
  platformer built in the level editor, a board game, a voice-driven music
  studio and an endless runner. Each one ends in a file in
  [`examples/`](https://github.com/accmota/Scena/tree/main/examples).
- **[API Guide](https://accmota.github.io/Scena/pt/guide/)**: every class,
  function and effect, with a live picture of each look.

The tutorial and the Guide are in Portuguese today; the English version is in
progress. The API itself (every name you type) is in English.

## Is Scena for you?

Scena is for learning to program, for small 2D games and for creative coding,
and for having fun doing it.

- **Simple code.** Your code is about the game's logic; Scena takes care of
  the boring details. Every design decision in Scena was made for learning and
  for the joy of making things: simple, yet expressive, with no boilerplate, so
  your focus stays on the thinking and the creativity.
- **Scripts or classes, both simple.** Scena was built for both. A flat script
  with no classes is a complete game (the one above). When an enemy deserves its
  own behavior, `class Enemy(Sprite)` with `setup` and `on_update` is all a class
  needs. Events, modes and acts work the same in either style.
- **It's Python.** If you know Python or are learning it, Scena is for you. No
  new language to learn: what you learn here works anywhere, and the rest of
  Python works here, from NumPy to the AI libraries Python is known for.
- **Smooth games.** Scena has the performance a typical 2D arcade game needs:
  tens to hundreds of objects at 60 fps on an ordinary computer. When a scene
  asks for more than the machine has, Scena lowers the detail of its effects
  before it drops frames.
- **What it is not.** It is not trying to be a professional engine: it is 2D
  only and runs on the desktop. Simple games stay simple, even if that means
  less power for very large ones.

## License

Scena's code and documentation are under the [MIT license](https://github.com/accmota/Scena/blob/main/LICENSE).
The images and sounds in `examples/media/` come from other artists under their own
licenses (mostly CC0). A few sounds ask for credit; the lines to copy are in
[`examples/media/CREDITS.md`](https://github.com/accmota/Scena/blob/main/examples/media/CREDITS.md).

Contributions are welcome under the same license: see
[CONTRIBUTING.md](https://github.com/accmota/Scena/blob/main/CONTRIBUTING.md).

---

<p align="center">
  By André Mota. For my sons, with much love.
</p>
