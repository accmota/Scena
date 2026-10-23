"""Studio II · Voice — tutorial 23.

The piano from tutorial 22 with your voice: R opens the microphone (the
first time, the system asks permission) and records two seconds; then the
keys play the recording at eight pitches. A meter shows how loud you speak
(st.voice, linked to the microphone with @=), a star travels a figure eight
(Track + move_along) with a light that grows with your voice, and a clap
sets off a sun.

Controls
--------
  A S D F G H J K   play the eight notes (so does a click on a key)
  R                 records two seconds of voice
  clap              a sun where the star is

Usage
-----
    python examples/studio_voice.py
"""

from scena import *

init(width=1000, height=600, title="Studio")
Wallpaper("dark navy")

LETTERS = ["A", "S", "D", "F", "G", "H", "J", "K"]
NOTES = [1, 1.12, 1.26, 1.33, 1.5, 1.68, 1.89, 2]

st.voice = 0


class Key(Rect, width=110, height=300, color="#F2EFE6", group="keys"):
    def on_update(self, dt):
        if keyp.once(self.letter):
            self.play_note()

    def on_click(self):
        self.play_note()

    def play_note(self):
        play_sound(recorder.sound, pitch=self.note, on_done=self.dim)
        self.color = "gold"

    def dim(self):
        self.color = "#F2EFE6"


for i in range(8):
    key = Key(center=(94 + i * 116, 190))
    key.letter = LETTERS[i]
    key.note = NOTES[i]
    Text(text=LETTERS[i], center=(94 + i * 116, 70), font_size=28, color="dim gray")


notice = Text(text="R records your voice", top_left=(20, 585), font_size=20, color="silver")


class Recorder(Circle, radius=10, color="dim gray"):
    def setup(self):
        self.mic = None
        self.sound = "audio/nota.wav"

    def on_update(self, dt):
        if keyp.once("R"):
            self.record_voice()

    def record_voice(self):
        if not self.mic:
            self.mic = Microphone()
            st["voice"] @= lambda: amp_db(self.mic.level)
        if self.mic.recording:
            return
        self.take = self.mic.record(seconds=2, on_done=self.recorded)
        self.color = "red"
        notice.text = "Speak!"

    def recorded(self):
        self.sound = self.take
        self.color = "dim gray"
        notice.text = "The keys play your voice. R records again"


recorder = Recorder(center=(975, 575))


Rect(top_left=(20, 550), width=300, height=10, color="#262B55")
bar = Rect(top_left=(20, 550), width=0, height=10, color="lime")
bar["width"] @= lambda: 300 * st.voice


track = Track.eight(width=760, height=140, center=(500, 470))
star = Sprite("space/star_gold.png", size=32)
star.move_along(track, time=8, loops="forever")
light = GlowSpot(center=lambda: star.center, color="gold")
light["radius"] @= lambda: 30 + 120 * st.voice
light["amount"] @= lambda: 0.3 + st.voice


@when(lambda: st.voice > 0.75)
def clap():
    sun = Sunburst(center=star.center, radius=100)
    sun.after(0.8, sun.destroy)


run()
