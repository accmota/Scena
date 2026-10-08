"""
Smoke test for Shape click / drag / drop / Anchor interaction.

Controls
--------
- Click cyan / magenta / gold (or the group-registered pair below) → color change.
- Drag the orange token onto the gray zone (droppable); watch drag_over highlight
  and drop_by / drag_to status updates.
- Drag gallery (line / ellipse / polygon / rect / square / regular polygon);
  wheel rotates while mouse is held (`wheel_rotate`).
- Hover Anchors — they enlarge + ring when they would receive a drag; lines follow.
- Click green-over-red stack to check z-order; SPACE clears status.
"""
from scena import *
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _hud import SmokeHud

init(width=1200, height=900, window_scale=0.7)
hud = SmokeHud(
    title="Pointer interaction",
    expect="Click / drag / drop / anchors / z-order; invisible never receives clicks",
    keys="click gallery  ·  drag token→zone  ·  wheel on drag gallery  ·  SPACE clear",
    status="Click or drag shapes…",
)
canvas.background = (0.08, 0.09, 0.12, 1)

# --- clickable gallery -------------------------------------------------------
c1 = Circle(center=(120, 140), radius=40).set_color("cyano")
c2 = Circle(center=(240, 140), radius=40).set_color("zxiojas")
box = Rect(center=(380, 140), width=90, height=70).set_color("gold")

@click(c1, c2, box)
def on_shape_click(shape):
    shape.set_color("blue")
    hud.status = f"clicked: {shape}"


# --- group registration ------------------------------------------------------
g_a = Circle(center=(520, 140), radius=35, group='click_group').set_color("super red")
g_b = Circle(center=(620, 140), radius=35, group='click_group').set_color("dark orange")

g_bb = Circle(center=(620, 140), radius=15).set_color("red")

@click(g_bb)
def on_g_bb_click(shape):
    shape.set_color("blue")
    hud.status = f"g_bb clicked: {shape}"

@click(group['click_group'])
def on_group_click(shape):
    shape.set_color("white")
    hud.status = f"group click: {shape}"


# --- z-order: top layer over default ----------------------------------------
under = Circle(center=(900, 150), radius=55).set_color("red")
over = Rect(center=(930, 170), width=85, height=65, layer='top').set_color("green")

@click(under, over)
def on_stack_click(shape):
    hud.status = f"z-order hit: {shape} (layer={shape.layer})"


# --- token + droppable zone (drag_to / drag_over / drop_by) -------------------
zone = Rect(center=(200, 340), width=160, height=100).set_color("gray")
token = Circle(center=(80, 340), radius=28).set_color("orange")

z1 = g_a.clone(scale=0.8)
z2 = z1.clone(scale=0.8)
z3 = z2.clone(scale=0.8)

@drag_to(z3)
def on_z3_drag_to(from_shape, to_shape, pos):
    target = str(to_shape) if to_shape else "none"
    hud.status = f"drag_to: {from_shape} → {target} @ ({pos[0]:.0f},{pos[1]:.0f})"
    if to_shape is None:
        from_shape.set_color("orange")

@drag_to(token)
def on_token_drag_to(from_shape, to_shape, pos):
    target = str(to_shape) if to_shape else "none"
    hud.status = f"drag_to: {from_shape} → {target} @ ({pos[0]:.0f},{pos[1]:.0f})"
    if to_shape is None:
        from_shape.set_color("orange")

@drag_over(token)
def on_token_drag_over(from_shape, to_shape, pos):
    if to_shape is zone:
        zone.set_color("yellow")
        hud.status = f"drag_over: {from_shape} over {to_shape}"
    else:
        zone.set_color("gray")

@drop_by(zone)
def on_zone_drop(from_shape, to_shape, pos):
    from_shape.set_color("lime")
    to_shape.set_color("sea green")
    hud.status = f"drop_by: {from_shape} dropped on {to_shape}"


# --- drag gallery: one of each major shape type ------------------------------
drag_line = Line(p1=(380, 300), p2=(520, 360)).set_color("white")

drag_line.line_width = 4
drag_ellipse = Ellipse(center=(640, 330), width=110, height=55, angle=17).set_color("turquoise")
drag_poly = Polygon(
    points=[(780, 290), (860, 300), (850, 370), (760, 360)],
).set_color("violet")
drag_rect = Rect(p1=(420, 450), p2=(520, 510), angle=0).set_color("salmon")
drag_square = Square(center=(580, 450), length=70).set_color("khaki")
drag_reg = RegularPolygon(n=5, center=(740, 450), radius=45).set_color("sky blue")

drag_gallery = [drag_line, drag_ellipse, drag_poly, drag_rect, drag_square, drag_reg]
for _s in drag_gallery:
    _s.wheel_rotate = True  # wheel rotates while mouse held on shape
    _s.show_handles()
    _s.show_points()

@drag_to(*drag_gallery)
def on_gallery_drag_to(from_shape, to_shape, pos):
    target = str(to_shape) if to_shape else "none"
    hud.status = f"drag_to: {from_shape} → {target}"


# --- Anchors + connecting lines (hover affordance) ---------------------------
a1 = Anchor(120, 620)
a2 = Anchor(280, 660, color="dark red")
a3 = Anchor(200, 760, color="lime")
(_t := (Line(p1=lambda: a1.center, p2=lambda: a2.center).set_color("white"))).line_width = 1
(_t := (Line(p1=lambda: a2.center, p2=lambda: a3.center).set_color("white"))).line_width = 1
(_t := (Line(p1=lambda: a3.center, p2=lambda: a1.center).set_color("white"))).line_width = 1


# --- move_to_front / move_to_back smoke --------------------------------------
back_r = Rect(center=(520, 680), width=100, height=80).set_color("navy")
front_r = Rect(center=(550, 710), width=100, height=80).set_color("coral")
front_r.move_to_front()

@click(back_r, front_r)
def on_z_methods(shape):
    hud.status = f"z-method hit: {shape}"


# --- invisible should not receive clicks ------------------------------------
ghost = Circle(center=(900, 700), radius=35).set_color("white")
ghost.on_click = lambda s: setattr(hud, 'status', "BUG: invisible shape clicked")
ghost.visible = False


def update(dt, canvas):
    if keyp.once("SPACE"):
        hud.status = "…"
        zone.set_color("gray")


run()
