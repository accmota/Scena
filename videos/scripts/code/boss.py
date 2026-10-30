from scena import *

init(width=800, height=600)
Wallpaper("midnight blue")


class Boss(Sprite):
    def setup(self):
        self.mode = self.arriving

    @on_mode
    async def arriving(self):
        await self.move_to(400, 430, time=2,
                           ease="ease_out")
        await wait(0.5)
        self.pop(scale=1.3)
        self.mode = self.fighting

    @on_mode
    async def fighting(self):
        while True:
            await self.move_to(200, 430, time=1.2)
            canvas.zap_at(self, color="orange")
            await self.move_to(600, 430, time=1.2)
            canvas.zap_at(self, color="orange")


Boss("space/enemyBlue2.png", height=140,
     center=(400, 760))

run()
