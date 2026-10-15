"""Equation twin for E6 (bound method vs closure over ``self``, PA4).

An Enemy schedules its shot with a module ``after`` on its own bound method,
then dies before the shot is due: the shot never comes. E6 rewrites the
callback to ``lambda: self.fire()``; owned the same way, it never comes
either. Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

init(width=300, height=300, title="laws twin: closure owner")

st.shots = 0


class Enemy(Circle):
    def setup(self):
        after(0.3, self.fire)

    def fire(self):
        st.shots += 1


a = Enemy(center=(100, 150), radius=8)
b = Enemy(center=(200, 150), radius=8)
after(0.1, a.destroy)          # dies before its shot; b fires


run()
