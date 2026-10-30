a = Circle(center=(940, 330), radius=9, color="coral")
b = Circle(center=(1060, 420), radius=9, color="coral")
b.draggable = True
ring = Circle(center=lambda: a.center,
              perimeter_point=lambda: b.center)
ring.visual = Stroke("turquoise", width=2)
mid = Circle(center=lambda: middle_point(a, b), radius=6)
size = Text("", center=(940, 610), font_size=22)
size["text"] @= lambda: f"{distance(a, b):.0f} px"
