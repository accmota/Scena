from scena import *

init(width=800, height=600)
Wallpaper("dark navy")
st.life = 100

ufo = Sprite("space/ufoYellow.png", height=90)
path = Track.eight(center=(400, 280),
                   width=520, height=240)
ufo.move_along(path, time=6, loops="forever")

bar = Rect(width=60, height=8, color="lime green")
bar["center"] @= lambda: ufo.center + (0, 70)
bar["width"] @= lambda: 60 * st.life / 100


@every(0.5)
def hit():
    st.life = max(0, st.life - 5)
    ufo.flash()


run()
