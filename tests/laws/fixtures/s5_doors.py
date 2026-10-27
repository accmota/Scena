"""Laws fixture S5: every author door, at least twice, for the chaos doors (S7).

The chaos runtime (``tests/laws/chaos.py``) fires one command at the return of
an author function the engine called. This program opens every door that the
other fixtures leave closed, rarest first, all as ``def`` (the rewrite skips
generators): ``@hover`` / ``@hover_exit``, ``@leave_playfield``, two ``@when``
true in one flush and an ``@on_change``, a tween's and a Track's ``on_done``,
a sound's ``on_done``, an actor ``setup`` inside an act build, act ``setup``
and ``on_destroy``, a Button, a TextInput submit, a Menu choice, script key
and mouse hooks, ``after`` / ``every``, ``on_update``, ``update``, and a
collision step with two contacts at once (a ball into the seam of two bricks)
plus a zone it stays in and leaves. Driven at OS level by ``chaos.S5_STEPS``.

Program for the laws harness (tests/laws/); not an example.
"""
# harness: cwd=examples/media
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=600, height=400, title="laws s5")

st.points = 0
st.ticks = 0
st.fired = 0
st.lit = 0
st.unlit = 0
st.left = 0
st.picks = 0
st.typed = ""
st.sent = 0
st.clicks = 0
st.key_downs = 0
st.mice = 0
st.acts = 0
st.ends = 0
st.sounds = 0
st.stays = 0
st.exits = 0
st.glow = 0.0
st.chips = 0
st.bright = 0

BOOM = Sound("audio/laser7.ogg")


# -- the game: widgets, watches, script hooks ---------------------------------

def press_button():
    st.clicks += 1


def send(value):
    st.sent += 1


Button(top_left=(10, 390), width=80, height=30, label="B", on_click=press_button)
box = TextInput(st["typed"], top_left=(100, 390), width=120, height=30, on_submit=send)


@when(lambda: st.points >= 2)
def two_points():
    st.fired += 1


@when(lambda: st.points >= 2)            # a second watch true in the same flush
def two_points_too():
    st.fired += 1


@on_change(st["points"])
def points_changed(value):
    st.fired += 1


def picked(option):
    st.picks += 1


def on_key_down(key):
    st.key_downs += 1
    if key == "M":
        Menu(options=["ok"], on_choose=picked, modal=False, center=(300, 200))
    elif key == "N":
        change_act(Outra if st.acts == 1 else Mesa)


def on_mouse_down(x, y, button):
    st.mice += 1


def update(dt):
    st.ticks += 1


def sound_over():
    st.sounds += 1


@leave_playfield("tiro")
def gone(shot):
    st.left += 1
    shot.destroy()


# -- the act: a ball, two bricks, a zone, a hover target, a shuttle -----------

def speed():
    """A helper author code calls (not a door): its value must survive the rewrite."""
    return 300


class Bola(Circle):
    def setup(self):
        self.mass = 1.0
        self.vel = Vec2(speed(), 0)
        self.every(0.25, self.shoot)

    def shoot(self):
        Tiro(center=(self.center.x, 230), radius=3, group="tiro")

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)


class Tiro(Circle):
    def on_update(self, dt):
        self.move_by(0, 600 * dt)


@collide("bola", "tijolo")
def hit(ball, brick):
    st.points += 1


@collide("bola", "tijolo")                # a second handler of the same contact (C3)
def chip(ball, brick):
    st.chips += 1


@collide_stay("bola", "zona")
def inside(ball, zone):
    st.stays += 1


@collide_exit("bola", "zona")
def outside(ball, zone):
    st.exits += 1
    if st.exits == 1:
        play_sound(BOOM, volume=0.05, on_done=sound_over)


class Alvo(Rect):
    """A hover target (the hooks as methods: ``@hover(group[...])`` wires
    only the members present when it runs)."""

    def on_hover(self):
        st.lit += 1

    @when(lambda self: st.points >= 2)    # an owned watch per target (L3 in flush)
    def bright(self):
        st.bright += 1

    def on_hover_exit(self):
        st.unlit += 1


def glowed():
    st.ends += 1
    if st.ends < 2:
        tween(st["glow"], 0.0, time=0.2, on_done=glowed)


def lapped():
    st.ends += 1


class Mesa(Act):
    def setup(self):
        st.acts += 1
        Bola(center=(60, 200), radius=8, group="bola")
        Rect(center=(310, 192), width=16, height=16, group="tijolo")
        Rect(center=(310, 208), width=16, height=16, group="tijolo")
        Rect(center=(160, 200), width=80, height=60, group="zona")
        Alvo(center=(520, 320), width=40, height=40, group="alvo")
        Alvo(center=(520, 240), width=40, height=40, group="alvo")
        resolve("bola", "tijolo", bounce=1.0)
        tween(st["glow"], 1.0, time=0.3, on_done=glowed)
        shuttle = Circle(center=(400, 100), radius=6)
        shuttle.move_along(Track.eight(width=40, height=12), time=0.5, on_done=lapped)
        self.after(0.1, self.tick)

    def tick(self):
        st.ticks += 1

    def on_destroy(self):
        st.ends += 1


class Outra(Act):
    def setup(self):
        st.acts += 1
        Bola(center=(60, 200), radius=8, group="bola")
        Rect(center=(310, 200), width=16, height=40, group="tijolo")
        Rect(center=(160, 200), width=80, height=60, group="zona")
        Alvo(center=(520, 320), width=40, height=40, group="alvo")


run(Mesa)
