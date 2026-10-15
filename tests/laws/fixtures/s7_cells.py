"""Laws fixture S7 cells: the chaos doors' directed cells (F3, the snapshot rule).

One small scene per ``PARAMS["cell"]``, each the shrunk repro of a suspect
the chaos runs examined (Testing Design, "Laws and equations", S7; catalogue
CD). ``st.log`` records what the author saw.

* ``park_resume``: a body parked and resumed in a stay handler while in two
  contacts: both exit, both enter again next step (holds).
* ``hover_park`` (CD1, fixed): the old hover target's ``hover_exit`` parks
  the new target; the parked target's ``on_hover`` does not run (L4).
* ``act_callable`` (CD2, fixed): two game bodies whose ``on_collide`` the act
  set as a closure over the act (the act's own hook); the first changes the
  act; the second's hook does not run after its act is gone (F3). A hook
  that does not close over the act is the game's and runs on (``closure``).
* ``ghost_act`` (CD4): a game ball breaks an act brick in a handler that also
  changes the act: the act's ghost goes with it (no bounce).
* ``join_rule`` (CD3, fixed by per-rule contacts): a body gains a tag while
  touching; ``other_rule`` adds an unrelated stay rule on the same pair;
  ``untag`` drops the tag again while the pair keeps touching (CD3-x).
* ``churn``: untag, then tag again a frame later, then both in one frame.
* ``act_in_setup`` (CD5): ``change_act`` from an act's own ``setup``; ``ink``
  then writes the ended act.

Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
CELL = PARAMS.get("cell", "park_resume")

init(width=400, height=300, title="laws s7")

st.log = []
st.changed = False


def log(*item):
    st.log = st.log + [item]


if CELL == "park_resume":
    ball = Circle(center=(200, 150), radius=10, group="ball")
    Rect(center=(200, 150), width=100, height=100, group="zone")
    Rect(center=(200, 150), width=60, height=60, group="core")

    @collide("ball", "zone")
    def zone_in(b, z):
        log("enter", "zone", clock.frame)

    @collide("ball", "core")
    def core_in(b, z):
        log("enter", "core", clock.frame)

    @collide_stay("ball", "zone")
    def zone_stay(b, z):
        log("stay", "zone", clock.frame)
        if clock.frame == 5:
            b.active = False
            b.active = True

    @collide_stay("ball", "core")
    def core_stay(b, z):
        log("stay", "core", clock.frame)

    @collide_exit("ball", "zone")
    def zone_out(b, z):
        log("exit", "zone", clock.frame)

    @collide_exit("ball", "core")
    def core_out(b, z):
        log("exit", "core", clock.frame)

    run()

elif CELL == "hover_park":
    class Card(Rect):
        def on_hover(self):
            log("hover", self.tag_name, clock.frame, self.active)

        def on_hover_exit(self):
            log("hover_exit", self.tag_name, clock.frame)
            if self.tag_name == "a":
                b.active = False            # leaving A locks B

    a = Card(center=(100, 150), width=60, height=60)
    a.tag_name = "a"
    b = Card(center=(160, 150), width=60, height=60)
    b.tag_name = "b"
    run()

elif CELL == "act_callable":
    p = Circle(center=(200, 150), radius=10)
    q = Circle(center=(205, 150), radius=10)

    class Um(Act):
        def setup(self):
            act = self

            def act_hit(me, other):           # closes over the act: the act's hook
                log("hit", "p" if me is p else "q", clock.frame, st.changed, act.is_alive)
                if not st.changed:
                    st.changed = True
                    change_act(Dois)

            def game_hit(me, other):          # no act in its closure: the game's hook
                log("hit", "p" if me is p else "q", clock.frame, st.changed, None)
                if not st.changed:
                    st.changed = True
                    change_act(Dois)
            hit = act_hit if PARAMS.get("closure", True) else game_hit
            p.on_collide = hit
            q.on_collide = hit

    class Dois(Act):
        def setup(self):
            log("Dois", clock.frame)

    run(Um)

elif CELL == "ghost_act":
    ball = Circle(center=(100, 150), radius=8, group="ball")
    ball.mass = 1.0
    ball.vel = Vec2(300, 0)

    def update(dt):
        ball.move_by(ball.vel.x * dt, ball.vel.y * dt)

    class Um(Act):
        def setup(self):
            Rect(center=(200, 150), width=16, height=40, group="brick")
            resolve("ball", "brick", bounce=1.0)

            @collide("ball", "brick")
            def hit(b, k):
                log("hit", clock.frame)
                k.destroy()
                if PARAMS.get("change"):
                    change_act(Dois)

    class Dois(Act):
        def setup(self):
            log("Dois", clock.frame)

    run(Um)

elif CELL == "join_rule":
    hero = Circle(center=(200, 150), radius=10, group="hero")
    Rect(center=(200, 150), width=80, height=80, group="lava")
    if PARAMS.get("other_rule"):
        @collide_stay("hero", "lava")
        def burning(h, l):
            pass

    @collide("shield", "lava")
    def shield_in(h, l):
        log("enter", clock.frame)

    @collide_stay("shield", "lava")
    def shield_stay(h, l):
        log("stay", clock.frame)

    @collide_exit("shield", "lava")
    def shield_out(h, l):
        log("exit", clock.frame)

    def update(dt):
        if clock.frame == 5:
            hero.tag("shield")
            log("tagged", clock.frame)
        if clock.frame == 8 and PARAMS.get("untag"):
            hero.untag("shield")                  # CD3-x: the pair stays touching
            log("untagged", clock.frame)

    run()

elif CELL == "churn":
    hero = Circle(center=(200, 150), radius=10, group="hero")
    Rect(center=(200, 150), width=80, height=80, group="zone")

    @collide("hero", "zone")
    def zone_in(h, z):
        log("enter", clock.frame)

    @collide_exit("hero", "zone")
    def zone_out(h, z):
        log("exit", clock.frame)

    def update(dt):
        if clock.frame == 5:
            hero.untag("hero")
            log("untag", clock.frame)
        if clock.frame == 6:
            hero.tag("hero")
            log("tag", clock.frame)
        if clock.frame == 9:
            hero.untag("hero")
            hero.tag("hero")
            log("untag+tag", clock.frame)

    run()

elif CELL == "act_in_setup":
    st.lives = 0

    class Fase(Act):
        def setup(self):
            log("Fase.setup")
            if st.lives == 0:
                change_act(Fim)
            Circle(center=(100, 100), radius=5, group="after")
            log("made after the change")
            if PARAMS.get("ink"):
                self.score = 0

        def on_destroy(self):
            log("Fase.on_destroy")

    class Fim(Act):
        def setup(self):
            log("Fim.setup")

    def update(dt):
        if clock.frame == 2:
            log("after", group["after"].count)

    run(Fase)
