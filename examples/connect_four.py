"""Connect Four — tutorial 21.

A board game for two players, red and blue. On their turn, each player
drags the ball beside the board and drops it on a column; the ball falls
to the lowest free cell. Four balls of the same color in a row, lying
down, standing or on a diagonal, win the game and light up. The rules
keep one list per column.

Controls
--------
  MOUSE (drag)         carry the ball to a column and let go
  New game             clears the board

Usage
-----
    python examples/connect_four.py
"""

from scena import *

init(width=1000, height=760, title="Connect Four")
Wallpaper("#2b3550")

pieces = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

zone = Box(center=(500, 340), width=560, height=480)
Rect(box=zone.outset(14), color="#d8dce4", corner_radius=24)
board = zone.grid(7, 6)
for cell in board:
    Sprite(pieces, frame="hole_large.png", box=cell)

START = (110, 520)
next_ball = Sprite(pieces, frame="ball_red_large.png", height=64, center=START, layer="top")
next_ball.draggable = True

columns = [[], [], [], [], [], [], []]
st.turn = "red"
st.finish = False


def message():
    if st.finish:
        return f"Winner: {st.turn}!"
    return f"Turn: {st.turn}"


notice = Text(text="", center=(500, 712), font_size=36, color="white")
notice["text"] @= message


@drag_to(next_ball)
def dropped(ball, goal, pos):
    cell = board.cell_at(pos)
    if st.finish or cell is None or len(columns[cell.col_index]) == 6:
        ball.move_to(START, time=0.3)
        return
    column = columns[cell.col_index]
    destination = board.cell(cell.col_index, 5 - len(column))
    new_ball = Sprite(pieces, frame=ball.frame, height=64, center=(destination.center.x, 630), group="moves")
    new_ball.player = st.turn
    new_ball.move_to(destination.center, time=0.5, ease="bounce", on_done=landed)
    column.append(new_ball)
    ball.visible = False
    ball.center = START


def landed():
    play_sound("audio/impactPlank_medium_002.ogg")
    check()
    if st.finish:
        play_sound("audio/Victory.mp3")
    else:
        switch_turn()
    next_ball.visible = True


def switch_turn():
    if st.turn == "red":
        st.turn = "blue"
        next_ball.frame = "ball_blue_large.png"
    else:
        st.turn = "red"
        next_ball.frame = "ball_red_large.png"


def four(x, y, dx, dy):
    balls = []
    for step in range(4):
        c = x + step * dx
        r = y + step * dy
        if c > 6 or r < 0 or r >= len(columns[c]) or columns[c][r].player != st.turn:
            return False
        balls.append(columns[c][r])
    for ball in balls:
        ball.glow = "gold"
    return True


def check():
    for x in range(7):
        for y in range(6):
            if four(x, y, 1, 0) or four(x, y, 0, 1):
                st.finish = True
            if four(x, y, 1, 1) or four(x, y, 1, -1):
                st.finish = True


def new_game():
    group["moves"].destroy()
    for column in columns:
        column.clear()
    st.turn = "red"
    st.finish = False
    next_ball.frame = "ball_red_large.png"
    next_ball.visible = True


Button(label="New game", on_click=new_game)

run()
