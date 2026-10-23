"""Ships VI · Acts — tutorial 25.

The ships game from tutorial 24 split into acts: a title with a PLAY
button, the level and the game over. Restarting is changing acts, with no
cleanup code; the score, the lives and the high score stay in st, which
lasts across acts. The level has two chapters (async modes): the fleet,
until the group is empty, and the boss battle, which ends in victory.

Controls
--------
  click PLAY           start
  LEFT / RIGHT         move
  SPACE                shoot; on the game over, back to the title
  P                    pause and resume
  R                    restart

Usage
-----
    python examples/ships_6_acts.py
"""

from random import uniform
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



def new_game():
    st.score = 0
    st.lives = 3
    st.energy = 0
    st.pace = 80
    st.won = False


st.high_score = 0
new_game()

class Explosion(Sprite, source=explosion, height=90):
    def setup(self):
        self.play("explode", loops=1)
        play_sound("audio/explosion01.wav")
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
        self.jet = Jet(origin=lambda: (self.center.x, self.center.y + 20),
                        angle=90, length=30, width=12, amount=2)
        self.jet.active = False

    @on_mode
    async def arriving(self):
        await wait(self.wait_time)
        await self.move_by(0, -500, time=1.2, ease="ease_out")
        await wait(0.3)
        self.pop(scale=1.3)
        play_sound("audio/impactGeneric_light_003.ogg")
        self.mode = self.formation

    @on_mode
    def formation(self):
        every(uniform(5, 12), self.shoot)
        after(uniform(3, 12), then=self.dive)

    @on_mode
    def dive(self):
        goal = self.center.x
        hero = group["hero"].nearest(self)
        if hero:
            goal = hero.center.x
        self.jet.active = True
        self.move_to(goal, 220, time=0.9, ease="ease_in_out",
                     loops=2, yoyo=True, then=self.formation)
        after(0.9, self.shoot)

    @exit_mode(dive)
    def end_of_dive(self):
        self.jet.active = False

    def shoot(self):
        EnemyShot(center=(self.center.x, self.center.y - 20))

    @collide_with("shots")
    def was_hit(self, shot):
        Explosion(center=self.center)
        if chance(0.2):
            PowerUp(center=self.center)
        shot.destroy()
        self.destroy()
        st.score += 1

    def on_destroy(self):
        self.jet.destroy()


class Boss(Sprite, source=sheet, frame="ufoRed.png", height=110, group="boss"):
    def setup(self):
        self.health = 0
        self.bar = Rect(top_left=(300, 775), width=0, height=10, color="tomato")
        self.bar["width"] @= lambda: self.health * 20
        self.mode = self.arriving

    @on_mode
    async def arriving(self):
        notice = Text(text="WATCH OUT: THE BOSS", center=(500, 400), font_size=40, color="tomato")
        notice.blink(2)
        play_sound("audio/laser-big.wav", pitch=0.5)
        await wait(2)
        notice.destroy()
        await self.move_to(750, 600, time=2, ease="ease_out")
        for turn in range(20):
            self.health += 1
            play_sound("audio/impactGeneric_light_003.ogg")
            await wait(0.05)
        self.mode = self.fighting

    @on_mode
    def fighting(self):
        self.move_by(-500, 0, time=3, ease="ease_in_out", loops="forever", yoyo=True)
        every(1.0, self.volley)

    def volley(self):
        for dx in [-40, 0, 40]:
            EnemyShot(center=(self.center.x + dx, self.center.y - 50))
        play_sound("audio/laser7.wav")

    @collide_with("shots")
    def was_hit(self, shot, info):
        shot.destroy()
        if self.mode != self.fighting:
            return
        canvas.hit_at(info)
        self.flash(0.08)
        self.health -= 1
        if self.health == 0:
            self.mode = self.dying

    @on_mode
    async def dying(self):
        for turn in range(5):
            canvas.explosion_at(self.center + (uniform(-50, 50), uniform(-30, 30)), amount=0.6)
            play_sound("audio/explosion02.wav")
            await wait(0.3)
        canvas.shake(14)
        Explosion(center=self.center)
        st.score += 20
        Starburst(center=self.center, radius=110)
        self.destroy()

    def on_destroy(self):
        self.bar.destroy()


class PowerUp(Sprite, source=sheet, frame="powerupBlue_shield.png", height=30, group="powers"):
    def on_update(self, dt):
        self.move_by(0, -150 * dt)


class ShieldBubble(Circle, radius=38, visual=Shield(style="plasma")):
    @collide_with("enemy_shots")
    def blocked(self, shot, info):
        canvas.zap_at(info, color="sky blue")
        play_sound("audio/sfx-hit-2.wav", pitch=1.6)
        shot.destroy()
        st.energy -= 20


class Hero(Sprite, source=sheet, frame="playerShip1_red.png", height=45, group="hero"):
    def setup(self):
        self.glow = True
        self.thruster = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)
        self.shield = ShieldBubble(center=lambda: self.center)
        self.shield.active = False

    def on_update(self, dt):
        if clock.paused:
            return
        if keyp("LEFT"):
            self.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            self.move_by(340 * dt, 0)
        self.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("shot", 0.2):
            Shot(center=(self.center.x, self.center.y + 28))
            play_sound("audio/laser4.wav")

    @collide_with("enemy_shots")
    def was_hit(self, shot):
        shot.destroy()
        if not ready("damage", 1.5):
            return
        st.lives -= 1
        canvas.shake(8)
        if st.lives > 0:
            self.blink(1.5)
            play_sound("audio/sfx-hit-2.wav")
        else:
            canvas.flash(0.4)
            canvas.explosion_at(self, amount=1.2)
            Fire(center=self.center, radius=30)
            play_sound("audio/gameover.wav")
            self.destroy()

    @collide_with("powers")
    def caught(self, power):
        power.destroy()
        self.pop()
        play_sound("audio/fx1.wav")
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


FLEET = ["enemyBlack1.png", "enemyBlue3.png", "enemyGreen4.png"]


def start_round():
    new_game()
    change_act(Play)


class TitleScreen(Act):
    def setup(self):
        Text(text="SHIPS", center=(500, 520), font_size=80)
        Text(text=f"High score {st.high_score}", center=(500, 430), font_size=24)
        SpriteButton("k-rolling-ball/button_blue.png", center=(500, 330), width=180,
                     label="PLAY", label_inset=(0, 0, 0, 8), on_click=start_round)


class Play(Act):
    def setup(self):
        scoreboard = Text(text="", top_left=(20, 780), font_size=20)
        scoreboard["text"] @= lambda: f"Score {st.score}"

        Sprite(sheet, frame="playerLife1_red.png", height=24, center=(900, 768))
        lives = Text(text="", top_left=(920, 780), font_size=20)
        lives["text"] @= lambda: f"x {st.lives}"

        bar = Rect(top_left=(20, 745), width=200, height=8, color="sky blue")
        bar["width"] @= lambda: st.energy * 2

        self.pause_sign = Text(text="PAUSED", center=(500, 420), font_size=56)
        self.pause_sign.visible = False

        Hero(center=(500, 70))
        self.mode = self.battle

    @on_mode
    async def battle(self):
        for row in range(3):
            for column in range(8):
                enemy = Enemy(frame=FLEET[row], center=(185 + column * 90, 1220 - row * 70))
                enemy.hue = column / 8
                enemy.wait_time = (2 - row) * 0.6 + column * 0.08
                enemy.mode = enemy.arriving
        await until_empty("enemies")
        await wait(1)
        Boss(center=(750, 1000))
        await until_empty("boss")
        await wait(2)
        st.won = True
        change_act(GameOver)

    def on_update(self, dt):
        group["enemies"].move_by(st.pace * dt, 0)

        for enemy in group["enemies"]:
            if enemy.center.x > 960:
                st.pace = -80
            if enemy.center.x < 40:
                st.pace = 80

        if keyp.once("P"):
            clock.paused = not clock.paused
            self.pause_sign.visible = clock.paused
        if keyp.once("R"):
            start_round()

    @when(lambda self: st.lives == 0)
    def lost(self):
        self.after(2, lambda: change_act(GameOver))


class GameOver(Act):
    def setup(self):
        st.high_score = max(st.high_score, st.score)
        if st.won:
            Text(text="YOU WIN", center=(500, 480), font_size=56, color="gold")
        else:
            Text(text="GAME OVER", center=(500, 480), font_size=56, color="tomato")
        Text(text=f"Score {st.score}   High score {st.high_score}", center=(500, 400), font_size=24)
        Text(text="press SPACE", center=(500, 330), font_size=18)
        self.after(10, lambda: change_act(TitleScreen))

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(TitleScreen)


@leave_playfield("shots", "enemy_shots", "powers")
def gone(shot):
    shot.destroy()


run(TitleScreen)
