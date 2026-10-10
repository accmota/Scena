<h1 align="center">Scena</h1>

<p align="center">
  <b>Creative graphics and 2D games in Python, made for learning to program.</b><br>
  Easy to begin. Space to grow.
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

Scena is a Python framework for drawing, animating and making games, written for
people who are learning to program. You write
what is on the screen and what should happen; Scena runs the loop, draws every
frame, moves the animations, checks the collisions and cleans up after you. It
draws with [Skia](https://skia.org) (the engine behind Chrome and Android), so even a
first program looks good.

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

- **Made for learning.** The first program is a few lines; the concepts arrive one
  at a time, in the order a learner needs them. Speed is the framework's job, not
  the beginner's.
- **Simple things are simple.** `Circle()` draws a circle. `Sprite("ship.png")`
  shows a ship. No setup, no boilerplate, no classes to inherit before anything
  appears.
- **Easy to begin, space to grow.** Parameters are gradual: start with
  `Circle()`, then `Circle(center=(200, 150), radius=40)`, then
  `circle.visual = Neon("cyan")`. Add detail only when you want it.
- **Say what should happen.** `@collide`, `@when`, `@every` and `@click` read like
  the rules of the game. A formula (`label["text"] @= lambda: ...`) is written once
  and stays true.
- **No magic.** Code does what it looks like it does. Scena never adds behavior or
  content you did not ask for: it gives you rich vocabulary, and the scene is yours.
- **Mistakes explain themselves.** A misspelled key, color or parameter gets a
  message that says what was wrong and suggests the closest right name.
- **Batteries included.** Collision, animation, effects, camera, layers, UI
  widgets, sound and a level editor are in the box, and they work together.

## What's in the box

**Shapes and sprites.** Circles, rectangles, polygons, lines, text, images and
sprite sheets. Every one draws with nothing but defaults, and takes more when you
want more.

```python
ball = Circle()                          # a circle in the middle of the window
ball.color = "coral"
ball.visual = Neon("cyan")               # one of 30+ looks
ship = Sprite("space/playerShip1_red.png", height=45, center=(400, 60))
ship.glow = True
```

**Events that read like rules.** Collisions, timers, clicks, conditions and
objects leaving the screen, each one a decorator.

```python
@collide("shots", "enemies")
def hit(shot, enemy):
    canvas.burst_at(enemy, radius=40)
    shot.destroy()
    enemy.destroy()


@when(lambda: st.score >= 10)
def level_up():
    st.speed *= 1.5
```

**Formulas.** Link a value to others once; Scena keeps it up to date.

```python
a = Circle(center=(200, 300), radius=8)
b = Circle(center=(600, 300), radius=8)
bridge = Line(p1=lambda: a.center, p2=lambda: b.center)   # follows a and b
```

**Animation in one line.** Move, turn, scale and fade over time, with easing,
loops and yoyo. Effects such as `pop`, `flash`, `dissolve_out` and `explosion_at`
clean up after themselves.

```python
ship.move_to(400, 300, time=1.5, ease="ease_in_out")
enemy.scale_to(1.08, time=0.45, loops="forever", yoyo=True)
```

**Looks, effects and backgrounds.** Visuals for shapes, screen effects, animated
backgrounds and one-shot explosions, all composable.

<table>
  <tr>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/visual-flame.anim.webp" width="240" alt="A circle with the Flame look"><br><code>visual = Flame()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/visual-electricfield.anim.webp" width="240" alt="A circle with the ElectricField look"><br><code>visual = ElectricField()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/spatial-portal.anim.webp" width="240" alt="A swirling portal"><br><code>Portal()</code></td>
  </tr>
  <tr>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/post-fireworks.anim.webp" width="240" alt="Fireworks over a picture"><br><code>canvas.fireworks_at(x, y)</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/bg-borealis.anim.webp" width="240" alt="An aurora background"><br><code>Borealis()</code></td>
    <td align="center"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/thumbs/fx-dissolve-out.anim.webp" width="240" alt="A ship dissolving"><br><code>ship.dissolve_out(0.5)</code></td>
  </tr>
</table>

**And more.** A camera, layers and endless scrolling worlds; boxes, grids and
geometry (intersections, midpoints, tangents); sliders, buttons, menus and
check boxes; sound effects, music and the microphone; acts for menus and levels;
and `scena-editor`, a level editor whose files a game reads with `Level`.

## Gallery

Every clip below is a program from [`examples/`](https://github.com/accmota/Scena/tree/main/examples),
played and recorded by the computer (nothing is edited by hand). Each one is the
last step of a tutorial.

<table>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/naves_escudo.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/naves_escudo.webp" width="380" alt="Naves"></a><br><b>Naves</b>: a space shooter with lives, explosions and a shield</td>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/aviao_paisagem.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/aviao_paisagem.webp" width="380" alt="Plane"></a><br><b>Plane</b>: fly between pillars over an endless, layered landscape</td>
  </tr>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/barras_girando.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/barras_girando.webp" width="380" alt="Spinning bars"></a><br><b>Spinning bars</b>: recursion you can watch</td>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/osciloscopio.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/osciloscopio.webp" width="380" alt="Oscilloscope"></a><br><b>Oscilloscope</b>: two circles make a curve</td>
  </tr>
  <tr>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/ponto_medio.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/ponto_medio.webp" width="380" alt="Midpoint"></a><br><b>Midpoint</b>: a compass-and-ruler construction you can drag</td>
    <td align="center"><a href="https://github.com/accmota/Scena/blob/main/examples/bolas.py"><img src="https://github.com/accmota/Scena/raw/main/docs/assets/readme/bolas.webp" width="380" alt="Balls"></a><br><b>Balls</b>: twenty balls bounce off the walls and each other</td>
  </tr>
</table>

## Install

Scena needs Python 3.12 or newer, on Windows, macOS or Linux.

```bash
pip install scena
```

To try the examples, get a copy of this repository and run one:

```bash
git clone https://github.com/accmota/Scena.git
cd Scena
pip install -e .
python examples/naves_escudo.py
```

Then, in any script: `from scena import *`.

## Learn

- **[Tutorial](https://accmota.github.io/Scena/pt/tutorial/)**: from the first
  shapes to a space shooter, bouncing balls and a side-scrolling plane. Each one ends in a file in
  [`examples/`](https://github.com/accmota/Scena/tree/main/examples).
- **[API Guide](https://accmota.github.io/Scena/pt/guide/)**: every class,
  function and effect, with a live picture of each look.

The tutorial and the Guide are in Portuguese today; the English version is in
progress. The API itself (every name you type) is in English.

## Is Scena for you?

Scena is a good fit for learning to program, small 2D games and creative coding. It is not trying to be a
professional engine: it is 2D only, runs on the desktop (not in the browser or on
phones), and is made for scenes with tens to hundreds of objects. Simple games stay
simple, even if that means less power for very large ones.

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
