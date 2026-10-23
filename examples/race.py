"""Race — a car race seen from above.

One or two players on the same keyboard; the other cars are the CPU's, always
four on the track. There are two tracks, each in a level file
(levels/race.json, the Serpentine, and levels/race_lightning.json, the
Lightning): the floor of tiles, the center line of the track, the obstacles,
the strips of light outside the bends, the starting spots and the camera view.
The opening has two steps: how many play and, then, the track. The steering
wheel turns little by little and, in a fast turn, the rear slides out; let
go, and the car lines up with the track. Off the asphalt the car loses speed.
Tires, trees, tents and stands stop the car, which bounces back; a barrel
makes the car crash, and it stays stopped, blinking, for a moment, while the
others drive through it. The faster car shoves the one ahead, which skids.
The oil slick makes the car spin. The power boxes give a shot: a fireball
that flies straight ahead and makes the car it hits crash. The CPU aims at
the center line, swerves around what is ahead, backs up when it gets stuck
and, now and then, fires at whoever is ahead of it. The race ends when the
players finish.

Controls
--------
  Opening      click ONE PLAYER or TWO PLAYERS (or press 1 / 2) and
               then a track (or 1 / 2)
  Player 1     blue: UP accelerates · DOWN brakes and reverses · LEFT / RIGHT turn · ENTER fires
  Player 2     red: W accelerates · S brakes and reverses · A / D turn · TAB fires
  At the end   SPACE goes back to the opening

Usage
-----
    python examples/race.py
"""

from random import choice, randrange, uniform
from scena import *

# The two tracks. Each file has the same pieces with the same names; the
# code does not know which is which.
TRACKS = {
    "SERPENTINE": Level("levels/race.json"),
    "LIGHTNING": Level("levels/race_lightning.json"),
}
init(width=1280, height=720, title="Race")
Wallpaper("#145a32")
FONT = "fonts/Quantico-Bold.ttf"

vehicles = Sheet("racing/spritesheet_vehicles.png", atlas="racing/spritesheet_vehicles.xml")
powers = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
fire = Sheet("explosions/fireball/Fireball_Effect_*.png", fps=30)
# 25 different smoke clouds, not the frames of an animation: each
# smoke shows just one (see Smoke).
smoke = Sheet("explosions/Black_smoke/blackSmoke*.png")

WIDTH = 154       # the width of the asphalt, curbs included

LAPS = 3
TOP_SPEED = 380        # the top speed on the asphalt
ON_GRASS = 140      # the top speed off the asphalt
REVERSE = -110           # the top speed in reverse
TURN = 170          # how many degrees per second the car turns, wheel all the way
GRIP = 7       # how well the tire grips: below this, the car skids more

# Player 1 (blue) drives with the arrows; player 2 (red), with W A S D.
BLUE_KEYS = {"accelerate": "UP", "brake": "DOWN", "left": "LEFT", "right": "RIGHT", "shot": "ENTER"}
RED_KEYS = {"accelerate": "W", "brake": "S", "left": "A", "right": "D", "shot": "TAB"}

# Everything the car runs into that stops it (and puts out a shot).
SOLIDS = ["wall", "tire", "tree", "barrel"]

st.players = 2
st.track = "SERPENTINE"
st.started = False
st.arrivals = 0
st.podium = []


def turn_needed(car, direction):
    """How many degrees the car must turn to point in that direction (+ is to the left)."""
    return vec_from_angle(car.angle).angle_to(vec_from_angle(direction))


class Car(Sprite, source=vehicles, height=46, art_angle=90, group="cars"):
    def setup(self):
        self.pace = 0     # the engine's push: forward, or negative in reverse
        self.vel = Vec2(0, 0)   # where the car really goes
        self.wheel = 0        # from -1 (full right) to 1 (full left)
        self.top_speed = TOP_SPEED
        self.laps = 0
        self.checkpoint = 0          # the last checkpoint on the track's line that the car passed
        self.shots = 0
        self.arrived = False
        self.finish_place = 0        # the place it finished in: 1, 2…
        # What the driver wants to do now. The keyboard decides or, in a
        # CPU car, think().
        self.cpu = False
        self.accelerate = False
        self.brake = False
        self.steer = 0           # 1 for left, -1 for right, 0 straight
        self.wants_to_shoot = False
        self.lane = 0          # CPU: how far beside the center line it drives
        self.skid = 0        # seconds in which the tire barely grips (it got shoved)
        self.no_checkpoint = 0      # CPU: seconds since it last passed a checkpoint
        self.backing_up = 0       # CPU: seconds of reverse still left

    def on_update(self, dt):
        if self.mode is None and st.started and not self.arrived:
            if self.cpu:
                self.think(dt)
            else:
                self.read_keys()
            self.drive(dt)
        else:
            self.pace = approach(self.pace, 0, 300)

        # Off the asphalt, the speed drops to the grass limit, and the tire
        # grips less. Spinning on oil, hardly at all.
        grip = GRIP
        if not collision.query_point(self, group="asphalt"):
            self.pace = approach(self.pace, min(self.pace, ON_GRASS), 700)
            grip = 3
        if self.skid > 0:
            self.skid -= dt
            grip = 1.5
        if self.mode == self.spinning:
            grip = 1

        # The car wants to go where it points, but its motion gets there
        # little by little: in a fast turn the rear slides out (it skids).
        forward = vec_from_angle(self.angle, self.pace)
        self.vel = chase(self.vel, forward, grip)
        self.move_by(self.vel * dt)
        self.confine(self.view, by="box")
        self.count_checkpoints()

    def read_keys(self):
        self.accelerate = keyp(self.controls["accelerate"])
        self.brake = keyp(self.controls["brake"])
        self.steer = 0
        if keyp(self.controls["left"]):
            self.steer = 1
        if keyp(self.controls["right"]):
            self.steer = -1
        self.wants_to_shoot = keyp.once(self.controls["shot"])

    def think(self, dt):
        # Stuck on an obstacle: back up a little, with the wheel turned, and try again.
        if self.backing_up > 0:
            self.backing_up -= dt
            self.accelerate = False
            self.brake = True
            return

        # Aim at a point on the track a little ahead, in its own lane.
        ahead = self.checkpoint + 3
        aim = Vec2(*self.checkpoints[ahead % len(self.checkpoints)]) + vec_from_angle(self.track_direction(ahead) + 90, self.lane)
        error = turn_needed(self, heading(self, aim))

        # An obstacle just ahead: swerve to the side where it is not.
        near = collision.query_sector(self, radius=140, spread=70, group=SOLIDS + ["oil"])
        if near:
            thing = min(near, key=lambda c: distance(self, c))
            if turn_needed(self, heading(self, thing)) > 0:
                error -= 45
            else:
                error += 45
        self.steer = max(-1, min(1, error / 15))

        # Accelerate when pointing roughly at the aim, and ease off before
        # a sharp bend further ahead.
        bend = abs(turn_needed(self, self.track_direction(self.checkpoint + 6)))
        self.accelerate = (abs(error) < 40 or self.pace < 120) and not (bend > 60 and self.pace > 260)
        self.brake = abs(error) > 70 and self.pace > 200

        # With a shot and a car ahead, sometimes fire: the CPU takes a moment
        # to decide (chance) and aims a little off (in shoot).
        in_sight = collision.query_sector(self, radius=450, spread=24, group="cars")
        self.wants_to_shoot = self.shots > 0 and len(in_sight) > 0 and chance(0.03)

        # A long time without passing a checkpoint: it is stuck.
        self.no_checkpoint += dt
        if self.no_checkpoint > 2.5:
            self.no_checkpoint = 0
            self.backing_up = 0.8
            # In reverse, the wheel turned the other way brings the nose to the aim.
            self.steer = -1 if error > 0 else 1

    def drive(self, dt):
        if self.accelerate:
            self.pace = approach(self.pace, self.top_speed, 260)
        elif self.brake:
            self.pace = approach(self.pace, REVERSE, 500)
        else:
            self.pace = approach(self.pace, 0, 120)

        # The wheel turns little by little and returns to the middle by itself.
        self.wheel = chase(self.wheel, self.steer, 10)

        # Standing still, the car does not turn; in reverse, the wheel flips.
        turn = TURN * self.wheel * min(abs(self.pace) / 120, 1)
        if self.pace < 0:
            turn = -turn
        self.rotate_by(turn * dt)

        # With no one at the wheel, the car slowly lines up with the track. Only
        # when it is almost lined up, so it does not steal a turn from the driver.
        if self.steer == 0 and self.pace > 0:
            error = turn_needed(self, self.track_direction(self.checkpoint))
            if abs(error) < 25:
                self.rotate_by(error * 3 * dt)

        if self.wants_to_shoot and self.shots > 0:
            self.shoot()

    def track_direction(self, i):
        """Where the track goes at checkpoint i, in degrees."""
        return heading(self.checkpoints[i % len(self.checkpoints)], self.checkpoints[(i + 1) % len(self.checkpoints)])

    def count_checkpoints(self):
        # The checkpoints are points in a row down the middle of the track. The
        # car moves on when it gets near one of the next five: it can skip one
        # in a wide turn, but cutting across the grass does not count.
        for step in range(1, 6):
            i = self.checkpoint + step
            if distance(self, self.checkpoints[i % len(self.checkpoints)]) < WIDTH * 0.7:
                self.checkpoint = i % len(self.checkpoints)
                self.no_checkpoint = 0
                if i >= len(self.checkpoints):
                    self.complete_lap()
                return

    def complete_lap(self):
        self.laps += 1
        if self.laps == LAPS:
            # A finished car gets out of the way: it turns see-through and no longer collides.
            self.arrived = True
            self.alpha = 0.5
            self.collidable = False
            st.arrivals += 1
            self.finish_place = st.arrivals
            canvas.fireworks_at(self)
            play_sound("audio/impactBell_heavy_000.ogg")
        elif not self.cpu:
            play_sound("synth/coin.wav")

    def progress(self):
        # How much of the race the car has done: laps, checkpoints and, between two
        # checkpoints, which is closer to the next one. A finished car, by its finish.
        if self.arrived:
            return 1000000 - self.finish_place
        next_point = self.checkpoints[(self.checkpoint + 1) % len(self.checkpoints)]
        return self.laps * len(self.checkpoints) + self.checkpoint - distance(self, next_point) / 1000

    def spot(self):
        return 1 + group["cars"].count_where(lambda other_one: other_one.progress() > self.progress())

    def shoot(self):
        self.shots -= 1
        self.glow = False
        shot = Shot(center=self.center + vec_from_angle(self.angle, 38))
        shot.angle = self.angle
        if self.cpu:
            shot.angle += uniform(-8, 8)    # the CPU aims a little off
        shot.shooter = self
        play_sound("synth/throw.wav")

    def crash(self):
        if self.mode != self.crashed:
            self.mode = self.crashed

    @on_mode
    async def crashed(self):
        # Stopped and blinking while it is out of the race. The others drive
        # through it: a crashed car collides with nothing.
        self.pace = 0
        self.vel = Vec2(0, 0)
        self.collidable = False
        canvas.explosion_at(self, amount=0.5)
        play_sound("audio/explosion02.wav", volume=0.6)
        self.blink(1.5)
        await self.rotate_by(choice([360, -360]), time=0.8, ease="ease_out")
        await wait(0.7)
        self.collidable = True
        self.mode = None

    @on_mode
    async def spinning(self):
        play_sound("audio/footstep_snow_001.ogg")
        await self.rotate_by(choice([300, -300]), time=0.9, ease="ease_out")
        self.mode = None


class Smoke(Sprite, source=smoke, height=40):
    # The black smoke of a car that was hit: a random cloud that grows,
    # turns slowly and fades while the car is out of the race. Changing
    # clouds every frame would make the smoke flicker in shape.
    def setup(self):
        self.frame = randrange(25)
        self.rotate_by(choice([60, -60]), time=1.5)
        self.scale_to(2.5, time=1.5, ease="ease_out")
        self.tween(self["alpha"], 0, time=1.5, on_done=self.destroy)


class Shot(Sprite, source=fire, height=32, group="shots"):
    def on_update(self, dt):
        self.move_by(distance=800 * dt)

    @leave_playfield
    def gone(self):
        self.destroy()


class PowerUp(Sprite, source=powers, frame="powerupRed_bolt.png", height=30, group="powers"):
    def setup(self):
        self.rotate_by(360, time=2, loops="forever")


# bounce= makes the car bounce: it comes back a little from the obstacle
# instead of sticking to it. Between two cars, the faster one pushes the other.
resolve("cars", SOLIDS, bounce=0.6)
resolve("cars", "cars", bounce=0.8)


@collide("cars", ["wall", "tire", "tree"])
def bumped(car, thing, info):
    if abs(car.pace) > 150:
        play_sound("audio/impactPlank_medium_002.ogg", volume=0.5)
        canvas.hit_at(info, style="disc", radius=12)
    # Head-on, the car backs off a little; from the side, it only loses speed
    # and scrapes along. info.normal points from the car to the obstacle.
    if abs(turn_needed(car, info.normal.angle)) < 45:
        car.pace = -car.pace * 0.3
    else:
        car.pace *= 0.8


# Pressed head-on against an obstacle, the engine does not push: the car
# only creeps forward, and reverse stays free. From the side, it scrapes along.
@collide_stay("cars", SOLIDS)
def touching(car, thing, info):
    if abs(turn_needed(car, info.normal.angle)) < 45:
        car.pace = min(car.pace, 40)


@collide("cars", "barrel")
def crashed_hard(car, thing, info):
    if abs(car.pace) > 120:
        car.crash()
    else:
        car.pace = 0
        car.vel = Vec2(0, 0)


@collide("cars", "cars")
def touched(car, other_one, info):
    play_sound("audio/impactGeneric_light_003.ogg", volume=0.6)
    # The faster car shoves the other: resolve gives the jolt, and the tires
    # of the shoved car barely grip for a moment, so it slides to
    # where it was thrown. The pusher loses power.
    if car.vel.length > other_one.vel.length:
        fast, slow = car, other_one
    else:
        fast, slow = other_one, car
    fast.pace *= 0.6
    slow.skid = 0.6


@collide("cars", "cone")
def knocked_over(car, cone):
    play_sound("audio/impactGeneric_light_003.ogg", volume=0.4)
    cone.frame = "cone_down.png"
    cone.untag("cone")
    cone.move_by(angle=car.vel.angle, distance=90, time=0.5, ease="ease_out")
    cone.rotate_by(choice([200, -200]), time=0.5, ease="ease_out")
    car.pace *= 0.8


@collide("cars", "oil")
def slipped(car, oil):
    if car.mode is None and abs(car.pace) > 100:
        car.mode = car.spinning


@collide("cars", "powers")
def caught(car, power):
    if car.shots == 0:
        car.shots = 1
        car.glow = True
        play_sound("audio/fx1.wav")
        spot = tuple(power.center)
        after(5, lambda: PowerUp(center=spot))
        power.destroy()


@collide("shots", "cars")
def struck(shot, car):
    if car != shot.shooter:
        canvas.shake(8)
        car.crash()
        Smoke(center=lambda: car.center)
        shot.destroy()


@collide("shots", SOLIDS)
def faded(shot, thing, info):
    canvas.burst_at(info, radius=30)
    shot.destroy()


def banner(caption, center, size):
    """A big on-screen text: gradient letters with a dark outline."""
    letters = Text(text=caption, center=center, font=FONT, font_size=size, layer="ui")
    letters.fill = Gradient("yellow", "orange red", angle=-90)
    letters.line = "black"
    return letters


class Race(Act):
    def setup(self):
        level = TRACKS[st.track]
        # The camera shows the level's "view": the track and a strip of grass. The
        # cars stay inside it, and a shot that leaves it disappears.
        self.view = level["view"].box
        canvas.frame_to(self.view)
        canvas.playfield.set(self.view)
        st.started = False
        st.arrivals = 0
        st.podium = []
        for item in level.group("floor"):
            item.make()
        # Strips of light on the ground, outside the bends: just decoration, the car
        # drives over them. They are halos; every other strip changes color, the
        # rest intensity. The color links with @= to a field with a tween (from a
        # light red to yellow: pure red glows dark on the grass).
        # The intensity is the Halo's amount, and a visual does not link with @=:
        # on_update swaps those strips' halo every frame (see shine).
        st.light_color = Color("tomato")
        self.tween(st["light_color"], Color("yellow"), time=1, loops="forever", yoyo=True)
        st.light_glow = 0.5
        self.tween(st["light_glow"], 4, time=0.7, loops="forever", yoyo=True)
        self.pulsing = []
        for i, item in enumerate(level.group("light")):
            if i % 2 == 0:
                light = item.make(line_width=8, visual=Halo(amount=3, style="line"))
                light["color"] @= lambda: st.light_color
            else:
                light = item.make(line_width=8, visual=Halo("gold", style="line"))
                self.pulsing.append(light)
        for driver in ["wall", "tire", "tree", "barrel", "cone", "oil", "decor"]:
            for item in level.group(driver):
                item.make()
        for driver in SOLIDS:
            group[driver].mass = STATIC
        # The asphalt: the center line of the track, as wide as the track. No one
        # sees it; it only answers whether a point is on the asphalt.
        asphalt = level["centerline"].make(line_width=WIDTH, group="asphalt")
        asphalt.visible = False
        # The checkpoints: 48 points in a row down the middle of the track, evenly spaced.
        self.checkpoints = asphalt.spaced_points(48)
        for item in level.group("power"):
            PowerUp(center=item.center)

        # Always four cars: blue on the keyboard, red on the keyboard or
        # the CPU, and two CPU cars, each in its own lane and at its own speed.
        self.blue = self.make_car("car_blue_1.png", "BLUE", "deep sky blue", level["start1"].center)
        self.blue.controls = BLUE_KEYS
        self.red = self.make_car("car_red_1.png", "RED", "tomato", level["start2"].center)
        if st.players == 2:
            self.red.controls = RED_KEYS
        else:
            self.red.cpu = True
            self.red.top_speed = TOP_SPEED * 0.96
        green = self.make_car("car_green_1.png", "GREEN", "lime green", level["start3"].center)
        green.cpu = True
        green.lane = 15
        green.top_speed = TOP_SPEED * 0.94
        yellow = self.make_car("car_yellow_1.png", "YELLOW", "gold", level["start4"].center)
        yellow.cpu = True
        yellow.lane = -15
        yellow.top_speed = TOP_SPEED * 0.9
        self.humans = [car for car in group["cars"] if not car.cpu]

        blue_scoreboard = Text(text="", top_left=(24, 704), font=FONT, font_size=26, color=self.blue.paint)
        blue_scoreboard["text"] @= lambda: self.scoreboard(self.blue)
        if st.players == 2:
            red_scoreboard = Text(text="", top_right=(1256, 704), font=FONT, font_size=26,
                                   color=self.red.paint)
            red_scoreboard["text"] @= lambda: self.scoreboard(self.red)

        self.notice = banner("", (640, 400), 150)
        self.mode = self.start_line

    def make_car(self, frame, driver, paint, start_line):
        car = Car(frame=frame, center=start_line)
        # The track belongs to the race; each car keeps its checkpoints and view.
        car.checkpoints = self.checkpoints
        car.view = self.view
        car.angle = car.track_direction(0)
        car.driver = driver
        car.paint = paint
        return car

    def on_update(self, dt):
        self.shine()

    def shine(self):
        # Rounded, the amount repeats: the same intensity is the same Halo.
        halo = Halo("gold", amount=round(st.light_glow, 1), style="line")
        for light in self.pulsing:
            light.visual = halo

    def scoreboard(self, car):
        lap = min(car.laps + 1, LAPS)
        caption = f"lap {lap}/{LAPS}   P{car.spot()}"
        if car.shots > 0:
            caption += "   FIRE!"
        return caption

    @on_mode
    async def start_line(self):
        for number in ["3", "2", "1"]:
            self.notice.text = number
            self.notice.pop()
            play_sound("audio/nota.wav")
            await wait(1)
        self.notice.text = "GO!"
        self.notice.pop()
        play_sound("audio/nota.wav", pitch=2)
        st.started = True
        await wait(1)
        self.notice.text = ""
        self.mode = None

    # The race ends when the players finish; a CPU car that has not finished
    # keeps the place it had.
    @when(lambda self: all(car.arrived for car in self.humans))
    def finish(self):
        for car in sorted(group["cars"], key=lambda c: c.spot()):
            st.podium.append((car.driver, car.paint))
        self.after(2, lambda: change_act(Results))


def choose_players(players):
    st.players = players
    change_act(TrackChoice)


def race_on(track):
    st.track = track
    change_act(Race)


def miniature(level, center, width):
    """The track's layout in miniature: the center line, shrunk to the
    given width, as a gray road with a white stripe down the middle."""
    points = level["centerline"].points
    xs = [x for x, y in points]
    ys = [y for x, y in points]
    scale = width / (max(xs) - min(xs))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    points = [(center[0] + (x - mx) * scale, center[1] + (y - my) * scale) for x, y in points]
    Track(points=points, closed=True, smooth=1, line_width=WIDTH * scale, color="dim gray", layer="ui")
    Track(points=points, closed=True, smooth=1, line_width=2, color="white", layer="ui")


class Choice(Act):
    # First step: how many play. Each button in the color of the car of
    # whoever will play; keys 1 and 2 do the same.
    def setup(self):
        banner("RACE", (640, 520), 130)
        SpriteButton(powers, frame="buttonBlue.png", center=(640, 380), width=440,
                     label="ONE PLAYER", font=FONT, label_color="dodger blue",
                     on_click=lambda: choose_players(1))
        SpriteButton(powers, frame="buttonRed.png", center=(640, 280), width=440,
                     label="TWO PLAYERS", font=FONT, label_color="firebrick",
                     on_click=lambda: choose_players(2))
        Text(text="the other cars are CPU", center=(640, 200), font=FONT, font_size=22, layer="ui")

    def on_update(self, dt):
        if keyp.once("1"):
            choose_players(1)
        if keyp.once("2"):
            choose_players(2)


class TrackChoice(Act):
    # Second step: the track. The two side by side, each with a drawing of
    # its layout above its button; keys 1 and 2 do the same.
    def setup(self):
        banner("TRACK", (640, 630), 90)
        how_many = "one player" if st.players == 1 else "two players"
        Text(text=how_many, center=(640, 550), font=FONT, font_size=24, layer="ui")
        for driver, x, frame, paint in [("SERPENTINE", 340, "buttonGreen.png", "dark green"),
                                     ("LIGHTNING", 940, "buttonYellow.png", "saddle brown")]:
            miniature(TRACKS[driver], (x, 380), 420)
            SpriteButton(powers, frame=frame, center=(x, 170), width=400, label=driver, font=FONT,
                         label_color=paint, breathe=True, on_click=lambda driver=driver: race_on(driver))

    def on_update(self, dt):
        if keyp.once("1"):
            race_on("SERPENTINE")
        if keyp.once("2"):
            race_on("LIGHTNING")


class Results(Act):
    def setup(self):
        driver, paint = st.podium[0]
        banner(f"{driver} WINS", (640, 560), 72)
        y = 440
        for spot, (driver, paint) in enumerate(st.podium, start=1):
            Text(text=f"P{spot}   {driver}", center=(640, y), font=FONT, font_size=32, color=paint, layer="ui")
            y -= 52
        Text(text="press SPACE", center=(640, 160), font=FONT, font_size=24, layer="ui")
        play_sound("audio/Victory.mp3")

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Choice)


run(Choice)
