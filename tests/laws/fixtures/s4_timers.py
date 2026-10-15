"""Laws fixture S4: timers — when ``after`` and ``every`` fire.

* ``after(0.5)`` at the top: fires on frame 30 at 60 Hz (T1, PM8);
* ``every(0.05)``: one fire per three frames, and at most five in one tick
  when the driver steps a long hitch frame (T4);
* a timer made inside a timer's callback waits for the next tick (T2); one
  made in ``update`` counts that frame;
* a Drone parks for a while (its timers freeze, T3) and another is destroyed
  with a timer pending (never fires);
* a Slow actor at ``time_scale = 0.5``: its ``after(0.5)`` takes a second;
* an actor that schedules work on itself in its own ``on_destroy`` (T6:
  nothing registers on a dead actor).

Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=400, height=300, title="laws s4")

st.half = 0
st.ticks = 0
st.chained = 0
st.made_in_update = 0
st.drone_pings = 0
st.ghost = 0
st.slow = 0
st.late = 0


def half_second():
    st.half += 1
    after(0.1, chained)            # made in the tick: counts from the next one


def chained():
    st.chained += 1


after(0.5, half_second)


@every(0.05)
def tick():
    st.ticks += 1


class Drone(Circle):
    def setup(self):
        self.every(0.1, self.ping)

    def ping(self):
        st.drone_pings += 1


class Doomed(Circle):
    def setup(self):
        self.after(0.3, self.boom)

    def boom(self):
        st.ghost += 1              # never: destroyed at 0.2 s

    def on_destroy(self):
        self.after(0.1, self.late)  # on a dying actor: registers nothing (T6)

    def late(self):
        st.late += 1


class Slow(Circle):
    def setup(self):
        self.time_scale = 0.5
        self.after(0.5, self.done)  # one second of world time

    def done(self):
        st.slow += 1


drone = Drone(center=(100, 150), radius=6)
doomed = Doomed(center=(200, 150), radius=6)
slow = Slow(center=(300, 150), radius=6)

after(0.2, doomed.destroy)
# Work on the destroyed actor's bound method: owned by it, so nothing
# registers (T6).
after(0.4, lambda: after(0.1, doomed.boom))
after(0.3, lambda: setattr(drone, "active", False))
after(0.6, lambda: setattr(drone, "active", True))


def update(dt):
    if 0.7 < clock.time <= 0.7 + dt:
        after(0.1, made_late)       # made in update: counts this frame


def made_late():
    st.made_in_update += 1


run()
