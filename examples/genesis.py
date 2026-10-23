"""Genesis.

The life of a star, told in six chapters that loop forever:

  I    Nebula      a cold cloud of gas slowly falls in on itself
  II   Accretion   the gas turns into a disc and streams down its arms
  III  Ignition    the core gets hot enough and the star lights up
  IV   Supernova   the old star swells, collapses and blows apart
  V    Pulsar      what is left spins: two beams of light sweep the sky
  VI   Remnant     the blown-out shell spreads, and becomes a nebula again

The dust of one star is the cloud of the next one.

Things to try
-------------
  Click anywhere     a clump of matter falls into the centre and flares
  Watch chapter V    for a moment the camera turns with the beams: the
                     pulsar stands still and the whole sky spins around it
  Count the orbits   in chapters III and IV the inner planets go round
                     faster, as real ones do (time ~ distance ** 1.5)

Controls
--------
  SPACE        next chapter
  CLICK        drop matter into the centre

Use
---
    python examples/genesis.py
"""

from random import uniform, choice, random
from scena import *

init(width=1280, height=800, title="Genesis")

C = Vec2(640, 400)      # the centre of everything: where the star is born

st.title = ""
st.subtitle = ""
st.next = None          # the chapter that comes after this one
st.leaving = False      # True while the screen fades to the next chapter
st.exit_style = "fade"  # how the screen closes at the end of a chapter


# ---- the stage: the HUD lasts for the whole story ----

Text(lambda: st.title, top_left=(32, 772), font_size=22, color=Color("white").with_alpha(0.85))
Text(lambda: st.subtitle, top_left=(32, 742), font_size=14, color=Color("white").with_alpha(0.5))
Text("SPACE  next chapter      CLICK  drop matter", top_left=(32, 34), font_size=12,
     color=Color("white").with_alpha(0.35))


def around(radius, angle):
    """The point at this distance and angle from the centre."""
    return C + vec_from_angle(angle, radius)


def open_chapter(chapter, title, subtitle, after, length):
    """What every chapter does first: name itself, fade in, plan its end."""
    st.title = title
    st.subtitle = subtitle
    st.next = after
    st.leaving = False
    st.exit_style = "fade"
    canvas.fade_in(1.2)
    chapter.after(length, next_chapter)


def next_chapter():
    """Fade out, then open the next chapter."""
    if st.leaving:
        return      # already on the way out
    st.leaving = True
    canvas.fade_out(1.0, style=st.exit_style, on_done=lambda: change_act(st.next))


def drop_matter(x, y):
    """A clump of five specks that spirals into the centre and flares there."""
    start = Vec2(x, y)
    # a curve that bends around the centre on the way in; orbit() curls it
    path = Track(points=[start, around(distance(start, C) * 0.55, heading(C, start) - 80), C])
    path.orbit(radius=14, laps=5)
    for k in range(5):
        speck = Circle(center=start, radius=2.5, color="light yellow")
        speck.glow = CheapGlow("orange", radius=7)
        speck.tail = Tail(color="orange")
        speck.move_along(path, time=2.2 + 0.18 * k, ease="ease_in",
                         on_done=lambda s=speck: arrive(s))


def arrive(speck):
    """The speck hits the centre: a small flare of light."""
    canvas.zap_at(C, style="corona", color="gold", radius=36)
    speck.implode(0.25, on_done=speck.destroy)


def update(dt):
    if keyp.once("SPACE"):
        next_chapter()


def on_mouse_click(x, y, button):
    drop_matter(x, y)


# ---- I. Nebula ----

class Cloud(Act):
    def setup(self):
        open_chapter(self, "I   Nebula", "a cold cloud of gas and dust", Disc, 16)
        canvas.background = Color(0.02, 0.01, 0.05)
        Nebula(color="purple", color2="midnight blue", alpha=0.75)
        Nebuladust(color="dark magenta", color2="teal", color3="indigo", alpha=0.35)
        Stars(density=0.5)
        Bloom(intensity=0.6)
        Vignette(amount=0.8)
        Grain(amount=0.05)

        # dust lanes: dark bands that dim the glowing gas behind them. Each
        # is a stack of ellipses that multiply: the middle, where they all
        # overlap, is the darkest, and the edges fade out softly
        for angle, y in ((-12, 470), (8, 290)):
            for k in range(6):
                lane = Ellipse(center=(640, y), width=1800 - 160 * k, height=170 - 24 * k, angle=angle,
                               color=Color(0.8, 0.74, 0.8))
                lane.line = None
                lane.blend = "multiply"

        # gas knots: soft glows that gravity pulls slowly to the middle
        for k in range(8):
            far = uniform(180, 520)
            angle = k * 45 + uniform(-15, 15)
            knot = GlowSpot(center=around(far, angle), radius=uniform(90, 200),
                            color=choice(["orchid", "medium purple", "medium slate blue", "plum", "light sea green"]),
                            amount=uniform(0.25, 0.45))
            tween(knot.center, around(far * 0.3, angle + 50), time=17, ease="ease_in")

        # specks of dust already orbiting the centre: the near ones faster
        for k in range(60):
            far = uniform(60, 460)
            orbit = Track.circle(center=C, radius=far)
            speck = Circle(radius=uniform(1, 2.2), color=Color("white").with_alpha(uniform(0.3, 0.8)))
            speck.line = None
            speck.move_along(orbit, time=(far / 60) ** 1.5 * 3, loops="forever", phase=random())

        # the core starts to pull: a warp that opens when the cloud is dense enough
        st.pull = 0
        core = Warp(center=C, radius=1, color="orange", into=True)
        core["amount"] @= lambda: st.pull
        tween(core["radius"], 80, time=8, start=1, ease="ease_in")
        self.after(8, lambda: tween(st["pull"], 1, time=6))

        # the camera drifts in from the side of the cloud
        canvas.pan_to(470, 330)
        canvas.pan_to(640, 400, time=15, ease="ease_in_out")
        canvas.zoom_to(1.3, time=16, ease="ease_in")


# ---- II. Accretion ----

ARMS = 4


def disc_turn(arm):
    """The angle of one spiral arm: the whole disc turns with the clock."""
    return lambda: arm * 360 / ARMS - clock.time * 24


def arm_light(arm, offset):
    """Where the light on an arm is now (0 at the centre, 1 at the rim)."""
    return 1 - (clock.time * 0.22 + arm / ARMS + offset) % 1


class Disc(Act):
    def setup(self):
        open_chapter(self, "II   Accretion", "gravity gathers the gas into a turning disc", Ignition, 20)
        canvas.background = Color(0.01, 0.01, 0.03)
        Nebuladust(color="indigo", color2="dark orange", color3="purple", alpha=0.3)
        Stars(density=0.6)
        Bloom(intensity=0.7)
        Vignette(amount=0.8)

        GlowSpot(center=C, radius=360, color="dark orange", amount=0.35)
        Warp(center=C, radius=80, color="orange", into=True)

        for arm in range(ARMS):
            # the arm itself, dim
            dim = Track.spiral(turns=1.3, radius=420, center=C,
                               color=Color("dark orange").with_alpha(0.3), line_width=2)
            dim["angle"] @= disc_turn(arm)
            # twins of it: only a short window of each shows, and the window
            # slides inward, so light seems to stream down the arm
            for offset in (0, 0.5):
                flow = Track.spiral(turns=1.3, radius=420, center=C,
                                    color=Color(1, 0.7, 0.3), line_width=2.5)
                flow.blend = "add"
                flow["angle"] @= disc_turn(arm)
                flow["end"] @= lambda arm=arm, offset=offset: arm_light(arm, offset)
                flow["begin"] @= lambda arm=arm, offset=offset: max(0, arm_light(arm, offset) - 0.14)

        # grains ride the arms inward: some wander, some tumble in little loops
        for arm in range(ARMS):
            wobbly = Track.spiral(turns=1.3, radius=420, center=C).wander(amount=16, seed=arm)
            loopy = Track.spiral(turns=1.3, radius=420, center=C).orbit(radius=9, laps=16)
            for path in (wobbly, loopy):
                path["angle"] @= disc_turn(arm)
                for k in range(3):
                    # a thin sliver that points where it goes reads as a streak
                    grain = Triangle(radius=uniform(4, 7), base_ratio=0.3,
                                     color=choice(["light yellow", "orange", "gold", "white"]))
                    grain.line = None
                    grain.move_along(path, time=uniform(8, 12), span=(1, 0), loops="forever",
                                     phase=random(), face=True)
            # one big clump per arm, with a tail
            clump = Circle(radius=4, color="light yellow")
            clump.line = None
            clump.glow = CheapGlow("orange", radius=8)
            clump.tail = Tail(color="dark orange")
            clump.move_along(wobbly, time=10, span=(1, 0), loops="forever", phase=random())

        canvas.zoom_to(0.9)
        canvas.zoom_to(1.15, time=20, ease="ease_in_out")


# ---- III. Ignition and IV. Supernova share the same star and planets ----

PLANETS = [(150, "indian red"), (230, "light sea green"), (330, "light steel blue")]


def build_star(radius):
    """The star, its planets and their orbits. Returns the star and the planets."""
    star = Circle(center=C, radius=radius, color=st.tint)
    star.line = None
    star["fill"] @= lambda: st.tint
    star.visual = Sphere()
    star.glow = Glow("orange", radius=18, amount=0.7)
    planets = []
    for far, color in PLANETS:
        period = (far / 60) ** 1.5 * 2.5
        orbit = Track.circle(center=C, radius=far, color=Color("white").with_alpha(0.07), line_width=1)
        planet = Circle(radius=7, color=color)
        planet.visual = Rim()
        # the phase comes from the clock, so the planets keep their places
        # from one chapter to the next
        planet.move_along(orbit, time=period, loops="forever", phase=clock.time / period % 1)
        # a bright stretch of the orbit trails behind the planet (u counts
        # the turn from angle 0, the same way heading does)
        wake = Track.circle(center=C, radius=far, color=Color(color).with_alpha(0.5), line_width=2)
        wake["end"] @= lambda planet=planet: heading(C, planet) / 360 % 1
        wake["begin"] @= lambda planet=planet: (heading(C, planet) / 360 - 0.15) % 1
        planet.orbit = orbit
        planet.wake = wake
        planets.append(planet)
    return star, planets


def crown(star):
    """The corona: three star outlines that turn at their own pace, sized by
    the star. Returns them, so the star can take them along when it dies."""
    pieces = []
    for points, reach, turn in ((12, 1.9, 9), (9, 1.6, -14), (7, 2.3, 5)):
        outline = Track.star(points=points, radius=100, inner=70, center=C,
                             color=Color(1, 0.8, 0.5).with_alpha(0.28), line_width=0.8)
        outline.blend = "add"
        # a track's size comes from its path: scale it (the stroke scales too)
        outline["scale"] @= lambda reach=reach: star.radius * reach / 100
        outline["angle"] @= lambda turn=turn: clock.time * turn
        pieces.append(outline)
    return pieces


class Ignition(Act):
    def setup(self):
        open_chapter(self, "III   Ignition", "the core gets hot enough: hydrogen starts to burn", Supernova, 15)
        canvas.background = Color(0.01, 0.005, 0.01)
        Nebuladust(color="dark red", color2="dark orange", color3="indigo", alpha=0.18)
        Stars(density=0.6)
        self.bloom = Bloom(intensity=0.45)
        self.rays = None
        Vignette(amount=0.8)
        st.tint = Color("dark red")

        # what is left of the disc, still turning, before the star clears it
        self.disc = []
        for arm in range(ARMS):
            arm_track = Track.spiral(turns=1.3, radius=420, center=C,
                                     color=Color("dark orange").with_alpha(0.3), line_width=2)
            arm_track["angle"] @= disc_turn(arm)
            self.disc.append(arm_track)

        self.star, self.planets = build_star(10)
        self.after(2.5, self.ignite)

    def ignite(self):
        canvas.flash(0.8)
        canvas.ripple_at(C)
        self.star.pop(0.3, scale=1.6)
        tween(self.star["radius"], 60, time=3, ease="ease_out")
        tween(st["tint"], Color(1, 0.55, 0.15), time=3)
        sun = Sunburst(center=C, radius=10, color="orange")
        tween(sun["radius"], 190, time=4, ease="ease_out")
        # the first light floods out in rays, then settles
        st.burst = 1
        tween(st["burst"], 0, time=3.5, ease="ease_in")
        self.rays = GodRays(target=C, weight=0, exposure=0.7, decay=0.95)
        crown(self.star)
        # the young star's wind blows the rest of the disc away
        for arm_track in self.disc:
            arm_track.dissolve_out(2.5, style="vortex", on_done=arm_track.destroy)

    def on_update(self, dt):
        # posts take no links: follow the burst by hand
        if self.rays:
            self.rays.weight = 0.18 * st.burst
            self.bloom.intensity = 0.45 + 0.6 * st.burst
            if st.burst == 0:
                self.rays.remove()
                self.rays = None


# ---- IV. Supernova ----

class Supernova(Act):
    def setup(self):
        open_chapter(self, "IV   Supernova", "the fuel runs out: the core collapses and the star blows apart", Pulsar, 16)
        canvas.background = Color(0.01, 0.005, 0.01)
        Nebuladust(color="dark red", color2="dark orange", color3="indigo", alpha=0.18)
        Stars(density=0.6)
        self.bloom = Bloom(intensity=0.45)
        Vignette(amount=0.8)
        st.tint = Color(1, 0.55, 0.15)
        st.shock = 0        # 1 right after the blast, then it calms down
        st.blast = 0        # the radius of the blast front
        self.blur = None
        self.star, self.planets = build_star(60)
        self.corona = crown(self.star)

        # a red giant: it swells and reddens, and swallows the nearest planet
        tween(st["tint"], Color(0.85, 0.15, 0.08), time=5)
        tween(self.star["radius"], 140, time=5.5, ease="ease_in_out")
        self.after(4.2, lambda: self.vanish(self.planets.pop(0), "burn"))
        self.after(6.5, self.collapse)

    def vanish(self, planet, how):
        """A planet goes away, with its orbit and its wake."""
        planet.wake.destroy()
        planet.orbit.fade_out(0.5, on_done=planet.orbit.destroy)
        if how == "burn":
            planet.burn_out(1.0, on_done=planet.destroy)
        else:
            canvas.debris_at(planet, color=planet.color, radius=60)
            planet.implode(0.5, on_done=planet.destroy)

    def collapse(self):
        tween(self.star["radius"], 4, time=0.4, ease="ease_in", on_done=self.explode)

    def explode(self):
        canvas.explosion_at(C, amount=2.5)
        canvas.shake(24)
        canvas.flash(1)
        canvas.glitch(1)
        for piece in self.corona:
            piece.destroy()
        self.star.destroy()
        for planet in self.planets:
            self.vanish(planet, "blast")

        st.shock = 1
        tween(st["shock"], 0, time=4, ease="ease_out")
        tween(st["blast"], 1500, time=6, ease="ease_out")
        # posts take no links: on_update calms them down with st.shock
        self.blur = ZoomBlur(center=C, amount=0.8)
        self.chroma = Chroma(amount=10)

        flare = Starburst(center=C, radius=220, points=12, color="white")
        flare["amount"] @= lambda: st.shock
        # the glowing gas thrown out, hot inside and cooler at the edge
        for size, color in ((0.3, "orange red"), (0.45, "dark cyan")):
            gas = GlowSpot(center=C, radius=10, color=color)
            gas["radius"] @= lambda size=size: 10 + st.blast * size
            gas["amount"] @= lambda: 0.3 + 0.6 * st.shock

        # the blast front: two rings of light racing out
        for size, color in ((1, "light cyan"), (0.8, "orange")):
            ring = Track.circle(center=C, radius=10, color=color, line_width=4)
            ring.blend = "add"
            ring["radius"] @= lambda size=size: 10 + st.blast * size

        # ejecta: shards thrown out in every direction, the fast ones with tails
        for k in range(50):
            angle = uniform(0, 360)
            shard = Triangle(center=C, radius=uniform(4, 9), base_ratio=uniform(0.2, 0.5), angle=angle,
                             color=choice(["light yellow", "orange", "tomato", "light cyan"]))
            shard.line = None
            shard.blend = "add"
            shard.move_to(around(uniform(500, 1200), angle), time=uniform(3, 7), ease="ease_out")
            if k % 5 == 0:
                shard.tail = Tail(color="orange")

        # the camera backs away to see the whole blast
        canvas.zoom_to(0.5, time=5, ease="ease_out")

    def on_update(self, dt):
        if self.blur:
            self.blur.amount = 0.8 * st.shock
            self.chroma.amount = 10 * st.shock
            self.bloom.intensity = 0.45 + st.shock


# ---- V. Pulsar ----

def spin():
    """The pulsar's angle: it turns fast and never stops."""
    return clock.time * 140


class Pulsar(Act):
    def setup(self):
        open_chapter(self, "V   Pulsar", "a city-sized ball of neutrons spins, beaming light from its poles", Remnant, 18)
        canvas.background = Color(0.005, 0.01, 0.03)
        # rotation_response: when the camera turns, the sky turns with it
        FilamentField(color="steel blue", alpha=0.3, rotation_response=1)
        Stars(density=0.7, rotation_response=1)
        Bloom(intensity=0.7)
        Vignette(amount=0.8)
        self.locked = False

        star = Circle(center=C, radius=9, color="white")
        star.visual = Halo("light cyan", style="pulse")
        star.glow = Glow("cyan", radius=24)

        # the magnetosphere: field loops that turn with the star; the outer
        # one burns bright, the inner one is a quiet line
        outer = Track.eight(width=520, height=100, center=C, visual=Laser("deep sky blue"))
        inner = Track.eight(width=290, height=55, center=C,
                            color=Color("deep sky blue").with_alpha(0.6), line_width=1.5)
        inner.blend = "add"
        self.loops = [outer, inner]
        for loop in self.loops:
            loop["angle"] @= lambda: spin() + 90

        # the two beams, out of the magnetic poles: a plume and a hard core
        for side in (0, 180):
            plume = Jet(origin=C, angle=0, length=480, width=34, color="light cyan")
            plume["angle"] @= lambda side=side: spin() + side
            core = Line(p1=C, p2=C, visual=Laser("cyan"))
            core["p2"] @= lambda side=side: around(520, spin() + side)

        # the beams' sweep leaves a fan behind that fades out
        self.sweep = History(duration=0.4)
        self.last = spin()
        self.every(0.07, self.mark_sweep)
        self.every(0.35, self.zap)

        canvas.zoom_to(0.6)
        canvas.zoom_to(1.0, time=4, ease="ease_out")
        self.after(6, self.lock)
        self.after(12, self.unlock)

    def mark_sweep(self):
        # a thin wedge between where each beam was and where it is now; each
        # one starts fading at once, so side by side they make a fan of light
        # that dims toward its old edge
        now = spin()
        for side in (0, 180):
            wedge = self.sweep.add(Polygon(points=[C, around(600, self.last + side), around(600, now + side)],
                                           color=Color("cyan").with_alpha(0.14)))
            wedge.line = None
            wedge.blend = "add"
            wedge.fade_out(0.4)
        self.last = now

    def zap(self):
        canvas.zap_at(choice(self.loops).at(random()), color="light cyan", radius=16)

    def lock(self):
        self.locked = True

    def unlock(self):
        self.locked = False
        canvas.rotate_to(0, time=2, ease="ease_in_out")

    def on_update(self, dt):
        if self.locked:
            # the camera turns with the beams: they stand still, the sky spins
            canvas.rotate_to(90 - spin())


# ---- VI. Remnant ----

# hydrogen glows red, oxygen glows teal: the two colours of a real remnant
HOT = ["tomato", "coral", "orange red", "gold"]
COOL = ["turquoise", "light sea green", "aquamarine"]


class Remnant(Act):
    def setup(self):
        open_chapter(self, "VI   Remnant", "the shell spreads and cools: the dust of the next stars", Cloud, 18)
        st.exit_style = "iris"     # the story closes on the centre, and opens again
        canvas.background = Color(0.01, 0.005, 0.02)
        FilamentField(color="tomato", alpha=0.3)
        Nebuladust(color="dark red", color2="teal", color3="purple", alpha=0.2)
        Stars(density=0.5)
        Bloom(intensity=0.6)
        Vignette(amount=0.8)

        st.shell = 40
        tween(st["shell"], 520, time=17, ease="ease_out")

        # what is left of the star: a faint pulsar
        core = Circle(center=C, radius=4, color="light cyan")
        core.visual = Halo(style="pulse")

        # the gas of the shell: soft glows that ride it outward
        for k in range(8):
            angle = k * 45
            gas = GlowSpot(center=C, radius=60, color=HOT[k % 2] if k % 3 else COOL[0], amount=0.35)
            gas["center"] @= lambda angle=angle: around(st.shell * 0.95, angle + clock.time * 2)
            gas["radius"] @= lambda: 30 + st.shell * 0.3

        # filaments: thin rays across the shell, teal ones inside, red ones outside
        for k in range(24):
            angle = k * 360 / 24 + uniform(-4, 4)
            if k % 2:
                start, end, color = uniform(0.45, 0.6), uniform(0.8, 0.9), choice(COOL)
            else:
                start, end, color = uniform(0.75, 0.85), uniform(1.05, 1.25), choice(HOT)
            strand = Line(p1=C, p2=C, color=Color(color).with_alpha(0.3), line_width=1.5)
            strand.blend = "add"
            strand["p1"] @= lambda angle=angle, start=start: around(st.shell * start, angle + clock.time * 2)
            strand["p2"] @= lambda angle=angle, end=end: around(st.shell * end, angle + clock.time * 2)

        # rings of the shell, each with a light that runs around it
        for k, size in enumerate((0.6, 0.85, 1.05)):
            ring = Track.circle(center=C, radius=10, color=Color("tomato").with_alpha(0.12), line_width=1.5)
            ring["radius"] @= lambda size=size: st.shell * size
            run_light = Track.circle(center=C, radius=10, color=Color("gold").with_alpha(0.5), line_width=2)
            run_light.blend = "add"
            run_light["radius"] @= lambda size=size: st.shell * size
            run_light["begin"] @= lambda k=k: (clock.time * 0.08 * (k + 1) + k / 3) % 1
            run_light["end"] @= lambda k=k: (clock.time * 0.08 * (k + 1) + k / 3 + 0.2) % 1

        # the shards: three kinds of pieces, out on the shell, each spinning
        for k in range(21):
            angle = k * 360 / 21 + uniform(-5, 5)
            reach = uniform(0.9, 1.15)
            turn = uniform(-60, 60)
            color = Color(choice(HOT + COOL)).with_alpha(0.85)
            if k % 3 == 0:
                shard = Concave(width=20, height=20, scoop=choice(["top_left", "bottom_right", "top_center"]), color=color)
                shard["width"] @= lambda: 8 + st.shell * 0.035
                shard["height"] @= lambda: 8 + st.shell * 0.035
            elif k % 3 == 1:
                shard = Triangle(radius=10, base_ratio=uniform(0.3, 0.9), color=color)
                shard["radius"] @= lambda: 4 + st.shell * 0.026
            else:
                shard = RegularPolygon(n=choice([5, 6]), radius=8, color=color)
                shard["radius"] @= lambda: 3 + st.shell * 0.018
            shard.line = None
            shard.blend = "add"
            shard["center"] @= lambda angle=angle, reach=reach: around(st.shell * reach, angle + clock.time * 2)
            shard["angle"] @= lambda turn=turn: clock.time * turn
            shard.fade_in(1.5)
            self.after(14 + random() * 2, lambda shard=shard: shard.dissolve_out(1.2))

        canvas.zoom_to(1.4)
        canvas.zoom_to(0.85, time=17, ease="ease_out")


run(Cloud)
