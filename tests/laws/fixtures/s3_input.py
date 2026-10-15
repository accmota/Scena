"""Laws fixture S3: input ownership — who gets a key or a button, down to up.

Script key hooks count what the script sees; a TextInput takes the keys it
claims while focused; a hold Button writes a cell while pressed; the test
driver (``test_laws_input``) presses, repeats and releases keys and buttons
across a focus change, an act change and a Button destroyed while held.
Key commands for the driver: N changes the act, F focuses the box, D
destroys the Button (a click elsewhere unfocuses the box). Program for the laws harness; not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=400, height=300, title="laws s3")

st.downs = 0
st.ups = 0
st.key_calls = 0
st.mouse_downs = 0
st.mouse_ups = 0
st.clicks = 0
st.firing = False
st.text = ""
st.acts = 0

box = TextInput(st["text"], top_left=(20, 280), width=160, height=30)
fire = Button(st["firing"], top_left=(220, 280), width=120, height=30, label="Fogo",
              value_on=True, value_off=False)


def on_key_down(key):
    st.downs += 1
    if key == "N":
        change_act(Fase if st.acts % 2 == 0 else Outra)
    elif key == "F":
        box.focus()
    elif key == "D" and fire.is_alive:
        fire.destroy()


def on_key_up(key):
    st.ups += 1


def on_key(key):
    st.key_calls += 1


def on_mouse_down(x, y, button):
    st.mouse_downs += 1


def on_mouse_up(x, y, button):
    st.mouse_ups += 1


def on_mouse_click(x, y, button):
    st.clicks += 1


class Inicio(Act):
    def setup(self):
        st.acts += 1


class Fase(Act):
    def setup(self):
        st.acts += 1
        Circle(center=(200, 150), radius=10)


class Outra(Act):
    def setup(self):
        st.acts += 1
        Rect(center=(200, 150), width=20, height=20)


run(Inicio)
