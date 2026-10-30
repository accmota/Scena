ufo = Sprite("space/ufoYellow.png", height=60, center=(940, 800))
lamps = [Circle(center=(700 + 60 * k, 200), radius=12,
                color="dark cyan") for k in range(9)]
st.open = False


async def visit():
    await ufo.move_to(940, 420, time=2.0, ease="ease_out")
    for lamp in lamps:
        lamp.color = "gold"
        await wait(0.6)
    await until(lambda: st.open)
    await ufo.move_to(940, 820, time=1.6, ease="ease_in")


def gate():
    st.open = True


every(1.0, lambda: ufo.pop(scale=1.6))
after(12, gate)
run_task(visit)
