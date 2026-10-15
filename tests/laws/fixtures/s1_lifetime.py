"""Laws fixture S1: lifetime — destroy, park, act change.

Witnesses for every L law in a few seconds of play:

* top-level objects (a score Text, a Sun) that every act change must keep;
* act Fase: Drones with an ``every`` method, an ``on_update`` and an
  ``on_destroy`` that reads a sibling; one drone is destroyed mid-act (twice:
  the second destroy is a no-op), one is parked and resumed;
* the act ends with ``change_act`` from a timer and is built again, then
  ends in act Fim.

Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=400, height=300, title="laws s1")

st.pings = 0
st.updates = 0
st.hooks = 0
st.rounds = 0
score = Text("0", center=(30, 280))
sun = Circle(center=(370, 270), radius=10)


class Drone(Circle):
    def setup(self):
        self.every(0.1, self.ping)

    def ping(self):
        st.pings += 1

    def on_update(self, dt):
        st.updates += 1
        self.move_by(10 * dt, 0)

    def on_destroy(self):
        st.hooks += 1
        # A sibling is still whole while the act's batch is torn down (L5).
        others = [d for d in group["drone"] if d is not self]
        for d in others:
            d.center.x


class Fase(Act):
    def setup(self):
        st.rounds += 1
        self.drones = [Drone(center=(60 + 60 * i, 150), radius=8, group="drone")
                       for i in range(4)]
        self.after(0.3, self.kill_one)
        self.after(0.4, self.nap)
        self.after(1.0, self.next)

    def kill_one(self):
        d = self.drones[0]
        d.destroy()
        d.destroy()            # a second destroy is a no-op (L2: one hook)

    def nap(self):
        d = self.drones[1]
        d.active = False       # parked: no ping, no on_update (L4)
        self.after(0.3, lambda: setattr(d, "active", True))

    def next(self):
        change_act(Fase if st.rounds < 2 else Fim)


class Fim(Act):
    def setup(self):
        Text("fim", center=(200, 150))


run(Fase)
