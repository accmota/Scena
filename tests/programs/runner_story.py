# harness: cwd=examples/media
"""Runner story: an auto-scrolling endless runner with a scripted intro and outro.

Program-model test program (tests/program_support.py).
PARAMS: seed, speed, lives, name_wait.

Controls
--------
  SPACE      skip the intro countdown; jump while running
  P          pause / resume the world clock
  letters    type a name at the end, ENTER saves it
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

W, H = 1000, 600
GROUND = 60                       # top of the ground strip
SPEED = PARAMS.get("speed", 260)
GRAVITY = 1500
JUMP = 620

init(width=W, height=H, title="Runner story")
SkyGradient("dusk")

st.lives = PARAMS.get("lives", 3)
st.coins = 0
st.distance = 0
st.phase = "boot"
st.countdown = 3.0
st.skipped = False
st.player_name = ""
st.runs_ended = 0

# ---- layers ----------------------------------------------------------------
canvas.layers.create("track", below="default")
clouds = canvas.layers.create("clouds", pan_response=0.3, scroll=(-40, 0), below="track")

def cloud(slot):
    y = slot.rng.uniform(380, 540)
    return Ellipse(center=(slot.left + 120, y), width=slot.rng.uniform(90, 160), height=36,
                   color="white", layer="clouds")

sky = Endless("clouds", cloud, step=260, seed=PARAMS.get("seed", 7))

set_defaults("dim gray")        # every track piece below is born dim gray
taken = set()

def stretch(slot):
    pieces = [Rect(top_left=(slot.left, GROUND), width=300, height=GROUND, group="ground")]
    if slot.i >= 2 and slot.chance(0.6):
        pieces.append(Rect(center=(slot.left + 150, GROUND + 25), width=30, height=50,
                           color="crimson", group="spike"))
    if slot.i >= 1 and slot.i not in taken and slot.chance(0.5):
        coin = Circle(center=(slot.left + slot.rng.uniform(40, 260), GROUND + 130),
                      radius=10, color="gold", group="coin")
        coin.stretch = slot.i
        pieces.append(coin)
    return pieces

track = Endless("track", stretch, step=300, seed=PARAMS.get("seed", 7))

set_defaults("orange", line_width=2.0)
hero = Rect(center=(200, GROUND + 20), width=40, height=40, group="hero")
hero.vy = 0.0
dust = Ellipse(center=(200, GROUND + 4), width=50, height=8, color="black",
               layer=above("default"))          # in front of the hero
haze = Rect(center=(W / 2, 30), width=W, height=60, color="steel blue",
            layer=below("clouds"))              # behind everything in the world

# ---- sounds ----------------------------------------------------------------
jump_snd = Sound("audio/laser4.ogg", volume=0.6)
coin_snd = Sound("audio/impact_bell_heavy_000.ogg", volume=0.5)
hit_snd = Sound("audio/sfx-hit-2.ogg")

# ---- HUD -------------------------------------------------------------------
hud = Text(text="", top_left=(20, 580), font_size=20)
hud["text"] @= lambda: f"Lives {st.lives}  Coins {st.coins}  Dist {st.distance}"
meter = Rect(center=(970, 40), width=14, height=4, color="lime", layer="ui")
title = Text(text="RUNNER", center=(W / 2, 700), font_size=48, layer="ui")
hint = Text(text="SPACE to skip", center=(W / 2, -40), font_size=20, layer="ui")
count_text = Text(text="", center=(W / 2, 260), font_size=32, layer="ui")
count_text["text"] @= lambda: f"{st.countdown:.1f}" if st.phase == "intro" else ""
result = Text(text="", center=(W / 2, 300), font_size=28, layer="ui")

def save_name(value):
    result.text = f"{value or 'ANON'}: {st.coins} coins, {st.distance} m"

name_box = TextInput(st["player_name"], placeholder="Name", label="Name", max_length=10,
                     on_submit=save_name, top_left=(350, 240))
name_box.visible = False

# ---- the story: one director, three chapters --------------------------------
director = Entity()

@on_mode
async def intro(e):
    st.phase = "intro"
    await parallel(tween(title.center, (W / 2, 420), time=0.8, ease="ease_out"),
                   tween(hint.center, (W / 2, 360), time=0.8))
    e.countdown = tween(st["countdown"], 0.0, time=3.0)
    try:
        await e.countdown
    except Cancelled:
        st.skipped = True          # SPACE cancelled the countdown
    title.visible = False
    hint.visible = False
    e.mode = running

def measure():
    st.distance = max(0, track.index_at(hero.center.x) - 1)

@on_mode
def running(e):
    st.phase = "run"
    every(0.5, measure)            # belongs to the chapter: stops when it ends

@exit_mode(running)
def running_exit(e):
    st.runs_ended += 1
    clouds.scroll = (0, 0)         # the sky stops with the run

@on_mode
async def outro(e):
    st.phase = "outro"
    play_sound("audio/gameover.ogg")
    await hero.rotate_by(90, time=0.6)
    name_box.visible = True
    name_box.focus()
    i = await race(until(lambda: st.player_name != ""), wait(PARAMS.get("name_wait", 6.0)))
    if i == 1:
        save_name("")
    name_box.visible = False
    st.phase = "done"
    e.mode = None

@after(0.3)
def start_story():
    director.mode = intro

# ---- the run ---------------------------------------------------------------
def back_to_speed():
    clock.scale = 1.0

@collide("hero", "spike")
def hit(h, spike):
    spike.destroy()
    st.lives -= 1
    play_sound(hit_snd)
    clock.scale = 0.5              # a short slow-motion beat
    after(0.25, back_to_speed)
    if st.lives <= 0:
        director.mode = outro

@collide("hero", "coin")
def grab(h, coin):
    taken.add(coin.stretch)
    coin.destroy()
    st.coins += 1
    play_sound(coin_snd, pitch=1.0 + 0.05 * (st.coins % 5))

def update(dt):
    if director.mode == intro and keyp.once("SPACE") and getattr(director, "countdown", None):
        director.countdown.cancel()
    if keyp.once("P") and st.phase != "outro":
        clock.paused = not clock.paused
    if director.mode == running:
        if keyp.once("SPACE") and hero.center.y <= GROUND + 20.5:
            hero.vy = JUMP
            play_sound(jump_snd)
        hero.vy -= GRAVITY * dt
        hero.move_by(SPEED * dt, hero.vy * dt)
        if hero.center.y < GROUND + 20:
            hero.move_by(0, GROUND + 20 - hero.center.y)
            hero.vy = 0.0
        canvas.pan_to(hero.center.x + 300, canvas.pan_y)
        canvas.playfield.set(canvas.game_view.outset(60))
    dust.center = (hero.center.x, GROUND + 4)
    haze.center = (canvas.game_view.center.x, 30)
    meter.height = 4 + 100 * amp_db(audio.level)
    meter.center = (970, 20 + meter.height / 2)

run()
