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
  nothing registers on a dead actor);
* a tween and an ``after`` of the same length, made together: the timer
  sees the tween finished (tweens tick before timers, T1);
* tasks: a top-level task with an ``every`` of its own, cancelled at
  0.45 s (its ``every`` ends with it, T5); a Sleeper's task that parks with
  it (no step while parked, T3); a task started on the destroyed actor
  (its body never runs, T6).

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
st.task_steps = 0
st.task_kid = 0
st.sleeper = 0
st.tw = 0.0
st.tw_seen = -1.0


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


async def pulse():
    every(0.05, pulse_kid)         # the task's work: ends with the task (T5)
    while True:
        st.task_steps += 1
        await wait(0.1)


def pulse_kid():
    st.task_kid += 1


pulse_task = run_task(pulse)       # top level: game work
after(0.45, pulse_task.cancel)


class Sleeper(Circle):
    def setup(self):
        self.run_task(self.count)

    async def count(self):
        while True:
            await wait(0.05)
            st.sleeper += 1


async def never(e):
    st.late += 1


sleeper = Sleeper(center=(150, 250), radius=6)
after(0.3, lambda: setattr(sleeper, "active", False))   # no step while parked (T3)
after(0.6, lambda: setattr(sleeper, "active", True))
after(0.4, lambda: doomed.run_task(never))              # dead owner: never runs (T6)


def tw_start():
    tween(st["tw"], 1.0, time=0.25)
    after(0.25, tw_seen)            # the same length: sees 1.0 (T1)


def tw_seen():
    st.tw_seen = st.tw


after(0.8, tw_start)


def update(dt):
    if 0.7 < clock.time <= 0.7 + dt:
        after(0.1, made_late)       # made in update: counts this frame


def made_late():
    st.made_in_update += 1


run()
