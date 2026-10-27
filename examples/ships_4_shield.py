"""Ships IV — tutorial 08.

The ship game from tutorial 07 with a shield: sometimes a destroyed
enemy drops a gift; catching it fills the energy and turns the shield
on. Every laser the shield stops bursts where it hit and uses up
energy; with no energy, the shield breaks and the ship loses lives again.

Controls
--------
  LEFT / RIGHT   move
  SPACE          shoot

Usage
-----
    python examples/ships_4_shield.py
"""

from random import choice
from scena import *

init(width=1000, height=800, title="Ships")
Wallpaper(Gradient("dark dark blue", "black", angle=90))
Stars(pan_response=0.0, scroll=(0.0, -38.0))
Grain()
Bloom()
Scanlines()

sheet = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
explosion = Sheet("explosions/exp4.png", cols=12)
explosion.clip("explode", range(12), fps=24)

st.score = 0
st.lives = 3
st.energy = 0
st.pace = 80

scoreboard = Text(text="", top_left=(20, 780), font_size=20)
scoreboard["text"] @= lambda: f"Score {st.score}"

Sprite(sheet, frame="playerLife1_red.png", height=24, center=(900, 768))
lives = Text(text="", top_left=(920, 780), font_size=20)
lives["text"] @= lambda: f"x {st.lives}"

bar = Rect(top_left=(20, 745), width=200, height=8, color="sky blue")
bar["width"] @= lambda: st.energy * 2


class Explosion(Sprite, source=explosion, height=90):
    def setup(self):
        self.play("explode", loops=1)
        play_sound("audio/explosion01.ogg")
        self.after(0.5, self.destroy)


class Shot(Sprite, source=sheet, frame="laserBlue03.png", height=28, group="shots"):
    def on_update(self, dt):
        self.move_by(0, 640 * dt)


class EnemyShot(Sprite, source=sheet, frame="laserRed01.png", height=28, group="enemy_shots"):
    def setup(self):
        self.rotate_to(180)

    def on_update(self, dt):
        self.move_by(0, -400 * dt)


class Enemy(Sprite, source=sheet, height=40, group="enemies"):
    def setup(self):
        self.scale_to(1.08, time=0.45, loops="forever", yoyo=True)

    @collide_with("shots")
    def was_hit(self, shot):
        Explosion(center=self.center)
        if chance(0.2):
            PowerUp(center=self.center)
        shot.destroy()
        self.destroy()
        st.score += 1


class PowerUp(Sprite, source=sheet, frame="powerupBlue_shield.png", height=30, group="powers"):
    def on_update(self, dt):
        self.move_by(0, -150 * dt)


class ShieldBubble(Circle, radius=38, visual=Shield(style="plasma")):
    @collide_with("enemy_shots")
    def blocked(self, shot, info):
        canvas.zap_at(info, color="sky blue")
        play_sound("audio/sfx-hit-2.ogg", pitch=1.6)
        shot.destroy()
        st.energy -= 20


class Hero(Sprite, source=sheet, frame="playerShip1_red.png", height=45):
    def setup(self):
        self.glow = True
        self.thruster = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)
        self.shield = ShieldBubble(center=lambda: self.center)
        self.shield.active = False

    def on_update(self, dt):
        if keyp("LEFT"):
            self.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            self.move_by(340 * dt, 0)
        self.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("shot", 0.2):
            Shot(center=(self.center.x, self.center.y + 28))
            play_sound("audio/laser4.ogg")

    @collide_with("enemy_shots")
    def was_hit(self, shot):
        shot.destroy()
        if not ready("damage", 1.5):
            return
        st.lives -= 1
        canvas.shake(8)
        if st.lives > 0:
            self.blink(1.5)
            play_sound("audio/sfx-hit-2.ogg")
        else:
            canvas.flash(0.4)
            canvas.explosion_at(self, amount=1.2)
            Fire(center=self.center, radius=30)
            Text(text="GAME OVER", center=(500, 400), font_size=48)
            play_sound("audio/gameover.ogg")
            self.destroy()

    @collide_with("powers")
    def caught(self, power):
        power.destroy()
        self.pop()
        play_sound("audio/fx1.ogg")
        st.energy = 100

    @on_change(lambda self: st.energy)
    def energy_changed(self):
        self.shield.active = st.energy > 0
        if st.energy == 0:
            canvas.burst_at(self, radius=70, rings=True)
            play_sound("audio/impactBell_heavy_000.ogg")

    def on_destroy(self):
        self.thruster.destroy()
        self.shield.destroy()


ship = Hero(center=(500, 70))

FLEET = ["enemyBlack1.png", "enemyBlue3.png", "enemyGreen4.png"]
for row in range(3):
    for column in range(8):
        enemy = Enemy(frame=FLEET[row], center=(185 + column * 90, 720 - row * 70))
        enemy.hue = column / 8


@every(0.4)
def fleet_fires():
    if group["enemies"].count == 0:
        return
    enemy = choice(group["enemies"])
    EnemyShot(center=(enemy.center.x, enemy.center.y - 20))


def update(dt):
    group["enemies"].move_by(st.pace * dt, 0)

    for enemy in group["enemies"]:
        if enemy.center.x > 960:
            st.pace = -80
        if enemy.center.x < 40:
            st.pace = 80


@leave_playfield("shots", "enemy_shots", "powers")
def gone(shot):
    shot.destroy()


run()
