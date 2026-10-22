"""Midpoint with a compass — tutorial 03.

Two Anchors define a segment. Two circles (center on one end,
radius to the other) cross; the chord between the crossings cuts
the segment in the middle. Drag the ends — everything follows.

Controls
--------
  Drag the Anchors at the ends of the segment.

Usage
-----
    python examples/midpoint.py
"""

from scena import *

init(width=1000, height=700, title="Midpoint")
Wallpaper("dark navy")

end1 = Anchor(420, 320)
end2 = Anchor(580, 380)

segment = Line(p1=lambda: end1.center, p2=lambda: end2.center, color="white")
segment.line_width = 3

# Compass: center on one end, radius to the other
circle1 = Circle(
    center=lambda: end1.center,
    perimeter_point=lambda: end2.center,
    color="deep sky blue",
)
circle1.fill = None
circle1.line_width = 2

circle2 = Circle(
    center=lambda: end2.center,
    perimeter_point=lambda: end1.center,
    color="orchid",
)
circle2.fill = None
circle2.line_width = 2

# The two crossings (shown before the chord)
crossing1 = Point(lambda: intersection(circle1, circle2, 0))
crossing1.visible = True
crossing1.color = "white"

crossing2 = Point(lambda: intersection(circle1, circle2, 1))
crossing2.visible = True
crossing2.color = "white"

# Chord between the crossings (perpendicular bisector)
chord = Line(p1=lambda: crossing1, p2=lambda: crossing2, color="gold")
chord.line_width = 2
chord.dash = "dash"  # or "dot", "dot-dash", "solid"

# Midpoint = where the chord crosses the segment
mid = Circle(
    center=lambda: intersection(chord, segment, 0),
    radius=8,
    color="gold",
)
mid.glow = True

run()
