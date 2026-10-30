for k in range(24):
    Sprite("space/meteorBrown_big3.png", height=30, group="rocks",
           center=(uniform(680, 1200), uniform(330, 600)))
gun = Sprite("space/playerShip1_red.png", height=46,
             center=(940, 110))

group["rocks"].move_by(0, -60, time=12, ease="ease_in_out")


def fire():
    target = nearest(gun, group["rocks"])
    if target:
        shot = Sprite("space/laserBlue03.png", height=24,
                      center=gun.center, group="shots")
        shot.move_to(target, speed=700, on_done=shot.destroy)


every(2.0, fire)


@collide("shots", "rocks")
def hit(shot, rock):
    canvas.burst_at(rock, radius=40)
    shot.destroy()
    rock.destroy()
