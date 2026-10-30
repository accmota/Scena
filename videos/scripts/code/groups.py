from scena import *

init(width=800, height=600)
Wallpaper("midnight blue")

ship = Sprite("space/playerShip1_red.png",
              center=(400, 70))
for x in range(100, 800, 100):
    Sprite("space/enemyGreen1.png",
           center=(x, 520), group="wasps")
group["wasps"].hp = 3


@every(0.5)
def march():
    wasps = group["wasps"]
    wasps.move_by(0, -18)
    target = wasps.nearest(ship.center)
    if target:
        canvas.zap_at(target, color="cyan")
        target.hp -= 1
    wasps.filter(lambda w: w.hp <= 0).destroy()


run()
