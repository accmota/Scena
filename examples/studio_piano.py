"""Studio · Piano — tutorial 22.

An eight-key piano: a single note (audio/nota.wav) played at eight
pitches with pitch=; a key lights up while its note sounds (on_done=); an
equalizer shows the game's sound in twelve bands (audio.spectrum).

Controls
--------
  A S D F G H J K   play the eight notes, from C to the next C
  click             on a key also plays it

Usage
-----
    python examples/studio_piano.py
"""

from scena import *

init(width=1000, height=600, title="Piano")
Wallpaper("dark navy")

LETTERS = ["A", "S", "D", "F", "G", "H", "J", "K"]
NOTES = [1, 1.12, 1.26, 1.33, 1.5, 1.68, 1.89, 2]


class Key(Rect, width=110, height=300, color="#F2EFE6", group="keys"):
    def on_update(self, dt):
        if keyp.once(self.letter):
            self.play_note()

    def on_click(self):
        self.play_note()

    def play_note(self):
        play_sound("audio/nota.wav", pitch=self.note, on_done=self.dim)
        self.color = "gold"

    def dim(self):
        self.color = "#F2EFE6"


for i in range(8):
    key = Key(center=(94 + i * 116, 190))
    key.letter = LETTERS[i]
    key.note = NOTES[i]
    Text(text=LETTERS[i], center=(94 + i * 116, 70), font_size=28, color="dim gray")

bars = []
for i in range(12):
    bars.append(Rect(center=(82 + i * 76, 470), width=60, height=4, color="turquoise"))


def update(dt):
    bands = audio.spectrum(bins=12)
    for i in range(12):
        bars[i].height = 4 + 150 * amp_db(bands[i])


run()
