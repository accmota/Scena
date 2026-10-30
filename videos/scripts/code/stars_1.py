from scena import *

init(width=800, height=600)
Wallpaper("dark navy")

paddle = Sprite("k-rolling-ball/button_blue.png",
                width=90, center=(400, 50),
                group="paddle")

run()
