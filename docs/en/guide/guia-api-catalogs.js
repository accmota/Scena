/* Catalog data for the API Guide — author knobs only. */
(function (w) {
  function P(name, def, meaning, pos, typ) {
    return { name, def, meaning, pos: pos || 0, typ: typ || "" };
  }

  const STAMPS = [
    { id: "stamp-glow", kind: "glow", family: "stamp", name: "Glow",
      idea: "A soft halo in the <code>.glow</code> add-on. Keeps the object's color. <code>color=</code> tints only the glow.",
      code: "ship.glow = True\nship.glow = \"cyan\"\nship.glow = Glow(\"cyan\", radius=14)\nText(\"GO\", glow=True)",
      search: "glow halo add-on stamp sprite shape text",
      hosts: ["Sprite", "Shape", "Text"],
      params: [P("color", "follows the object", "Only the halo's pigment", 1), P("radius", "12", "Reach"), P("sigma", "6", "Blur"), P("amount", "1", "Intensity"), P("alpha", "None", "Opacity of the glow, 0–1; None = the color's")] },
    { id: "stamp-cheapglow", kind: "glow", family: "stamp", name: "CheapGlow",
      idea: "A halo cheaper than Glow: a few light copies added up around the object, with no blur. Prefer it for fleets and projectiles. There is no <code>.cheapglow</code> property — it goes in <code>.glow</code>.",
      code: "shot.glow = CheapGlow(\"tomato\", radius=8)",
      search: "cheapglow fleet projectile add-on sprite shape text",
      hosts: ["Sprite", "Shape", "Text"],
      params: [P("color", "follows the object", "Pigment only", 1), P("radius", "8", "Reach of the halo, in design units"), P("amount", "1", "Intensity"), P("alpha", "None", "Opacity of the halo, 0–1; None = the color's"), P("sigma", "0", "Extra blur of the copies; 0 = no filter (the cheap one)")] },
    { id: "stamp-shadow", kind: "shadow", family: "stamp", name: "Shadow",
      idea: "A shadow in the <code>.shadow</code> add-on. <code>color=</code> tints only the shadow.",
      code: "c.shadow = True\nc.shadow = Shadow(\"navy\")",
      search: "shadow add-on stamp sprite shape",
      hosts: ["Sprite", "Shape"],
      params: [P("color", "soft black", "Pigment of the shadow", 1), P("offset", "8", "A number or (dx, dy)"), P("sigma", "5", "Blur"), P("alpha", "None", "Opacity of the shadow, 0–1; None = shadow_color's"), P("dx", "None", "X offset; None = uses offset"), P("dy", "None", "Y offset (y up); None = uses offset"), P("shadow_color", "(0, 0, 0, 0.55)", "RGBA paint used when color is not given", 0, "color")] },
    { id: "stamp-hueshift", kind: "hue", family: "stamp", name: "HueShift",
      idea: "Turns the hue, in the <code>.hue</code> add-on. On a Shape painted with an image, use <code>Texture(shift=HueShift(...))</code>.",
      code: "sprite.hue = True\nsprite.hue = 0.33\nsprite.hue = HueShift(to=\"cyan\")\ntex = Texture(\"tex2.png\", shift=HueShift(to=\"cyan\"))",
      search: "hueshift hue sprite texture add-on",
      hosts: ["Sprite"],
      params: [P("amount", "—", "Turns (1 = full circle)", 1), P("to", "—", "A color: turns the hue until it reaches it (computes amount by itself; do not use it together with amount=)"), P("live", "False", "True lets the turn change during the game (Sprite only; on a Texture it raises an error)")] },
    { id: "stamp-grayscale", kind: "hue", family: "stamp", name: "Grayscale",
      idea: "Takes the color out, in the <code>.gray</code> add-on (gray by luminance). Combines with <code>.hue</code>: the hue turns first, the gray goes on top. It costs no performance: the Sprite is still drawn the fast way.",
      code: "sprite.gray = True\nsprite.gray = 0.5\nsprite.gray = Grayscale(0.8)\nsprite.gray = None",
      search: "grayscale gray desaturate disabled off sprite add-on",
      hosts: ["Sprite"],
      params: [P("amount", "1", "How gray, 0–1 (1 = all gray)", 1)] },
    { id: "stamp-tail", kind: "motion", family: "stamp", name: "Tail",
      idea: "A ghost trail in the <code>.tail</code> add-on. Without <code>angle=</code> (or with <code>True</code>) it follows the motion; <code>angle=</code> locks it. <code>angle</code> / <code>size</code> / <code>amount</code> take <code>lambda:</code>.",
      code: "c.tail = True\n# no angle=: follows the motion\nc.tail = Tail(color=\"gold\", size=1.4, amount=1.15)\nc.tail = Tail(angle=180)\nc.tail = Tail(angle=lambda: c.angle + 180, size=lambda: 1.4, amount=lambda: 1.15)",
      search: "tail trail ghost add-on stamp sprite shape lambda",
      hosts: ["Sprite", "Shape"],
      params: [P("color", "—", "Tints only the ghosts", 1), P("angle", "follows the motion", "Left out = follows; degrees / lambda = locks", 2), P("size", "1.2", "Length (number or lambda)", 3), P("amount", "1", "Opacity of the copies (number or lambda)", 4)] },
  ];

  const LOOKS = [
    { id: "visual-neon", kind: "glow", family: "visual", name: "Neon",
      idea: "Glow + body + core. Shape only. Use it on a few standout objects; for many (a fleet, shots), the <code>.glow</code> add-on is cheaper. <code>flicker</code> is the tube's hum.",
      code: "c.visual = Neon(\"magenta\")\nc.visual = Neon(\"cyan\", flicker=0.6)",
      search: "neon hero glow core flicker shape",
      hosts: ["Shape"],
      params: [P("color", "follows the fill", "Tints the body", 1), P("amount", "1", "Strength of the glow", 2), P("width", "3", "Thickness of the core", 3), P("flicker", "0", "Hum of the halo. 0 = static.", 0, "number")] },
    { id: "visual-halo", kind: "glow", family: "visual", name: "Halo",
      idea: "A glowing shell. Hollow by default. <code>style=\"pulse\"</code> animates concentric rings inside.",
      code: "c.visual = Halo()\nc.visual = Halo(\"cyan\", amount=1.2)\nc.visual = Halo(style=\"fill\")\nc.visual = Halo(style=\"pulse\", rings=3)",
      search: "halo shell ring hollow pulse",
      hosts: ["Shape", "Sprite"],
      variants: "style",
      params: [P("color", "follows the object", "Tints the shell", 1), P("amount", "1", "Strength", 2), P("style", "\"hollow\"", "hollow · fill · soft · line · pulse"), P("rings", "3", "Rings (pulse only; in another style it is a TypeError)"), P("speed", "1", "Pace of the rings (pulse only; in another style it is a TypeError)")] },
    { id: "visual-laser", kind: "glow", family: "visual", name: "Laser",
      idea: "A beam: halo + color + white core. Best on <code>Line</code>.",
      code: "beam.visual = Laser()\nbeam.visual = Laser(\"lime\")",
      search: "laser ray beam line",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the outline", "Tints the beam", 1), P("amount", "1", "Thickness of the beam, in multiples of line_width (2 = double)", 2)] },
    { id: "visual-rim", kind: "glow", family: "visual", name: "Rim",
      idea: "A lit outline: a border of light around the object, with the inside slightly darkened. Makes the silhouette of a hero or an item stand out.",
      code: "c.visual = Rim()\nc.visual = Rim(\"cyan\", amount=1.2)",
      search: "rim outline highlight",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the outline", 1), P("amount", "1", "Intensity of the light (1 = normal, 0 = off)", 2), P("width", "4", "Thickness of the outline, in units", 3, "number"), P("darken", "0.35", "How much the inside darkens: 0 = none, 1 = black", 4, "number")] },
    { id: "visual-bolt", kind: "glow", family: "visual", name: "Bolt",
      idea: "Electric energy inside the body — a plasma shot, an energy orb. <code>style</code> picks the drawing: <code>core</code> (a swirl at the center), <code>filaments</code> (spinning filaments), <code>tesla</code> (bolts from the center to the edge, like a plasma ball).",
      code: "shot.visual = Bolt(style=\"core\")\nshot.visual = Bolt(style=\"filaments\")",
      search: "bolt lightning tesla filaments plasma energy",
      hosts: ["Shape"],
      variants: "style",
      params: [P("color", "follows the object", "Color of the energy", 1), P("amount", "3", "How many filaments (filaments / tesla; in core it is a TypeError)", 2), P("speed", "1.2", "Pace of the animation; 0 freezes it", 3), P("intensity", "0.6 in filaments", "Brightness of the outline", 4), P("style", "\"core\"", "core · filaments · tesla", 5)] },
    { id: "visual-multiborder", kind: "shell", family: "visual", name: "MultiBorder",
      idea: "Several outline lines around the object, each a little farther out and wider — like the rings of a target.",
      code: "c.visual = MultiBorder()\nc.visual = MultiBorder(layers=3, spread=4)",
      search: "multiborder border layers outline rings",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the lines", 1), P("layers", "3", "How many lines", 2, "int"), P("spread", "0.3", "Distance between the lines (larger = farther apart)", 3, "number")] },
    { id: "visual-organicoutline", kind: "shell", family: "visual", name: "OrganicOutline",
      idea: "A shaky, irregular outline, as if drawn by hand, that moves slowly.",
      code: "c.visual = OrganicOutline()",
      search: "organic outline fringe hand-drawn",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the outline", "Color of the stroke", 1), P("amount", "2.5", "How much the stroke trembles (0 = smooth)", 2), P("speed", "1", "Pace of the trembling; 0 freezes it", 3)] },
    { id: "visual-tracer", kind: "shell", family: "visual", name: "Tracer",
      idea: "A dashed line of light running around the outline — selection, target locked, active object.",
      code: "c.visual = Tracer()",
      search: "tracer dash trail selection",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the dashes", 1), P("speed", "1", "Speed at which the dashes run; 0 stops them", 2), P("gap", "12", "Space between the dashes, in units", 3, "number"), P("width", "2.4", "Thickness, in units", 4, "number")] },
    { id: "visual-dashring", kind: "shell", family: "visual", name: "DashRing",
      idea: "Two dashed rings spinning around the object, like a crosshair or a radar. Looks best on Circle, Ellipse and Line.",
      code: "c.visual = DashRing()",
      search: "dashring ring dashed crosshair radar",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the rings", 1), P("speed", "1", "Spin speed; 0 stops it", 2), P("width", "2", "Thickness, in units", 3, "number")] },
    { id: "visual-gearshell", kind: "shell", family: "visual", name: "GearShell",
      idea: "A shell of strokes spinning around the object, like a gear, over the softened body.",
      code: "c.visual = GearShell()\nc.visual = GearShell(color=\"cyan\")",
      search: "gearshell gear shell",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the strokes", 1), P("speed", "1.2", "Spin speed; 0 stops it", 2), P("amount", "1", "Intensity (1 = normal, 0 = off)", 3)] },
    { id: "visual-electricfield", kind: "shell", family: "visual", name: "ElectricField",
      idea: "Small electric arcs flickering around the silhouette — electrified, overloaded.",
      code: "c.visual = ElectricField()",
      search: "electric field arc",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the arcs", 1), P("amount", "5", "How many arcs", 2), P("speed", "1", "How often they change", 3)] },
    { id: "visual-electricbolt", kind: "shell", family: "visual", name: "ElectricBolt",
      idea: "Electric discharges running along the outline — stronger and longer than ElectricField.",
      code: "c.visual = ElectricBolt(\"gold\")",
      search: "electricbolt discharge electric",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the discharges", 1), P("amount", "5", "Intensity of the discharges", 2), P("speed", "1", "How often they change", 3)] },
    { id: "visual-ink", kind: "shell", family: "visual", name: "Ink",
      idea: "Ink-drawing style: the object keeps its fill and gets a pen outline that trembles slightly.",
      code: "c.visual = Ink()",
      search: "ink pen drawing",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the ink", 1), P("amount", "1.8", "How much the stroke trembles", 2), P("speed", "0.6", "Pace of the trembling; 0 freezes it", 3)] },
    { id: "visual-inkbleed", kind: "shell", family: "visual", name: "InkBleed",
      idea: "Wet ink spreading at the edges, still (it does not animate).",
      code: "c.visual = InkBleed()",
      search: "inkbleed bleed ink",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Color of the ink", 1), P("amount", "1", "How far the ink spreads outward", 2)] },
    { id: "visual-insertrim", kind: "shell", family: "visual", name: "InsetRim",
      idea: "The fill shrinks inward and an outline stays around it, with a gap between the two.",
      code: "c.visual = InsetRim()",
      search: "insertrim inset rim gap",
      hosts: ["Shape"],
      params: [P("color", "follows the object", "Color of the outline", 1), P("fill_scale", "0.8", "Size of the shrunken fill (0.8 = 80%)", 2, "number"), P("width", "6", "Thickness of the outline, in units", 3, "number"), P("amount", "0.3", "Intensity of the outline", 4)] },
    { id: "visual-shield", kind: "orb", family: "visual", name: "Shield",
      idea: "An energy shield. Best on Circle / Ellipse.",
      code: "orb.visual = Shield()\norb.visual = Shield(\"cyan\")\norb.visual = Shield(style=\"nebula\")",
      search: "shield bubble nebula plasma energy",
      hosts: ["Shape", "Sprite"],
      variants: "style",
      params: [P("color", "—", "Color of the shield. bubble: without it, the usual lime-green film; with it, the same film in that color. bands, vortex and plasma: without it, they follow the object's color. The other styles have their own colors, and a color on them is a TypeError", 1), P("style", "\"bubble\"", "bubble · nebula · ember · void · molten · bands · vortex · cracks · frost · plasma"), P("amount", "1", "Intensity (1 = normal, 0 = off)"), P("speed", "1", "Pace of the animation; 0 freezes it")] },
    { id: "visual-sphere", kind: "orb", family: "visual", name: "Sphere",
      idea: "Makes a disk look like a sphere: light and shadow give it volume, and the shine turns slowly. Best on Circle.",
      code: "orb.visual = Sphere(\"steel blue\")",
      search: "sphere ball volume",
      hosts: ["Shape"],
      params: [P("color", "follows the fill", "Color of the sphere", 1), P("amount", "1", "How much volume (0 = flat)"), P("speed", "0.5", "Speed at which the light turns; 0 stops it")] },
    { id: "visual-gel", kind: "orb", family: "visual", name: "Gel",
      idea: "Gummy-candy look: translucent, with a shine and a darker edge.",
      code: "candy.visual = Gel(\"pink\")",
      search: "gel candy translucent gummy",
      hosts: ["Shape"],
      params: [P("color", "follows the fill", "Color of the candy", 1), P("amount", "1", "Intensity of the effect (1 = normal)", 2)] },
    { id: "visual-extrude", kind: "element", family: "visual", name: "Extrude",
      idea: "Gives 3D depth: the object gets side faces that fade toward a vanishing point, like a block seen in perspective. The default vanishing point applies to every <code>Extrude</code>: change it with <code>set_extrude_focus(x, y)</code> (default: center of the screen). For a single object, pass <code>focus=(x, y)</code> or fix the direction with <code>angle=</code>.",
      code: "set_extrude_focus(600, 40)\nship.visual = Extrude(depth=40, layers=5)",
      search: "extrude depth 3d perspective",
      thumb: "set_extrude_focus(W * 0.95, H * 0.95)\nship.visual = Extrude(depth=40, layers=5)",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the fill", "Color", 1), P("depth", "36", "Length of the faces, in % of the distance to the vanishing point", 2, "number"), P("focus", "set_extrude_focus", "Vanishing point. Or set_extrude_focus", 3, "point"), P("layers", "5", "How many slices make up the side (more = smoother, more expensive)", 4, "int"), P("edges", "False", "Outlines the solid's side edges"), P("darken", "0.42", "How much the side faces darken, 0–1"), P("angle", "None", "Fixed extrusion direction in degrees; None = follows the global focus (set_extrude_focus)")] },
    { id: "visual-metal", kind: "element", family: "visual", name: "Metal",
      idea: "Brushed metal with a chrome rim — plates, coins, metal buttons. With a color, body and rim take the color (Metal(\"gold\") is gold with a golden rim).",
      code: "c.visual = Metal()\nc.visual = Metal(\"gold\")\nc.visual = Metal(speed=0)",
      search: "metal chrome brushed",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "chrome", "Color of the metal, on the body and the rim (without it, chrome, whatever the shape's color; set_color later recolors the metal)", 1), P("amount", "1", "How much the brushed grain shows", 2), P("speed", "1", "Pace of the shine; 0 freezes it", 3)] },
    { id: "visual-water", kind: "element", family: "visual", name: "Water",
      idea: "Water seen from the side, with the surface rippling on top. The colors are fixed (it does not take color=).",
      code: "pool.visual = Water()",
      search: "water ripple",
      hosts: ["Shape"],
      params: [P("amount", "1", "Ripple", 1), P("speed", "1", "Pace", 2)] },
    { id: "visual-swell", kind: "element", family: "visual", name: "Swell",
      idea: "A slow, abstract flow running inside the object, like smoke or ink in water.",
      code: "fx.visual = Swell()",
      search: "swell flow smoke",
      hosts: ["Shape", "Sprite"],
      params: [P("amount", "1", "Intensity (1 = normal, 0 = off)", 1), P("speed", "1", "Pace; 0 freezes it", 2)] },
    { id: "visual-flame", kind: "element", family: "visual", name: "Flame",
      idea: "Fire rising inside the object. The colors are fixed (it does not take color=).",
      code: "ember.visual = Flame()\nember.visual = Flame(border=True)",
      search: "flame fire",
      hosts: ["Shape", "Sprite"],
      params: [P("amount", "1", "Turbulence", 1), P("speed", "1.2", "Pace", 2), P("border", "False", "Yellow rim", 3)] },
    { id: "visual-wave", kind: "element", family: "visual", name: "Wave",
      idea: "Liquid rippling inside the object, with a soft edge.",
      code: "c.visual = Wave()",
      search: "wave liquid ripple",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the fill", "Color", 1), P("amount", "1", "Strength", 2), P("speed", "1", "Pace", 3)] },
    { id: "visual-aurora", kind: "element", family: "visual", name: "Aurora",
      idea: "Northern-lights bands rising inside the object.",
      code: "c.visual = Aurora()",
      search: "aurora borealis northern lights",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the fill", "Color", 1), P("amount", "1", "Strength", 2), P("speed", "0.9", "Pace", 3)] },
    { id: "visual-liquify", kind: "element", family: "visual", name: "Liquify",
      idea: "Soft copies of the object wobble around it, like jelly. The copies follow the body's color.",
      code: "blob.visual = Liquify()\nblob.visual = Liquify(\"orchid\", amount=5)",
      search: "liquify wobble jelly",
      hosts: ["Shape"],
      params: [P("color", "follows the object", "Tints the body (and the ghosts)", 1), P("amount", "3.5", "How far the copies move apart as they wobble", 2), P("speed", "1", "Pace of the wobble; 0 freezes it", 3)] },
    { id: "visual-beat", kind: "motion", family: "visual", name: "Beat",
      idea: "The object grows and shrinks in a rhythm, as if breathing. Without a color, it keeps the object's color. <code>color</code> tints the body (Shape only; a Sprite keeps its pixels).",
      code: "c.visual = Beat()\nc.visual = Beat(\"tomato\", amount=0.12)",
      search: "beat pulse scale breathe",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "follows the object", "Tints the body (Shape only)", 1), P("amount", "0.08", "How much it grows, as a fraction of the size (0.08 = 8%)", 2), P("speed", "1", "Pace of the breathing", 3)] },
    { id: "visual-recolor", kind: "sprite", family: "visual", name: "Recolor",
      idea: "Swaps one color of the image for another — the same enemy PNG in blue and in red. Pixels near the <code>key</code> hue turn to the <code>to</code> hue; the rest stays. On a Sprite (in <code>.visual</code>) or on a <code>Texture(shift=)</code>. <code>key</code> needs a hue: white, gray or black raise an error (Recolor does not select gray areas); <code>to</code> may be gray.",
      code: "sprite.visual = Recolor(\"blue\", \"tomato\")\nTexture(\"tex2.png\", shift=Recolor(\"blue\", \"gold\"))",
      search: "recolor palette sprite texture swap hue",
      hosts: ["Sprite"],
      params: [P("key", "\"blue\"", "The color to be swapped", 1, "color"), P("to", "\"tomato\"", "The new color", 2), P("range", "0.08", "How close to key a color must be to be swapped (larger = catches more shades)", 0, "number"), P("soft", "0.04", "Softens the transition between swapped and not swapped", 0, "number")] },
    { id: "visual-aura", kind: "sprite", family: "visual", name: "Aura",
      idea: "A band of light that follows the Sprite's silhouette exactly, inside and outside the edge, with no hard stroke. Sprite only.",
      code: "sprite.visual = Aura()\nsprite.visual = Aura(\"cyan\", amount=1.2)",
      search: "aura fringe sdf sprite silhouette light",
      hosts: ["Sprite"],
      params: [P("color", "follows the object", "Color of the light", 1), P("amount", "1", "Intensity (1 = normal, 0 = off)", 2), P("width", "0.35", "Width of the band, as a fraction of the size")] },
    { id: "visual-emissivebloom", kind: "sprite", family: "visual", name: "EmissiveBloom",
      idea: "The Sprite's bright parts glow and leak light around them (bloom), like lamps or glowing eyes. Sprite only; it is expensive — use it on a few (heroes, bosses).",
      code: "sprite.visual = EmissiveBloom()\nsprite.visual = EmissiveBloom(intensity=1.6, sigma=12)",
      search: "emissivebloom bloom sprite glow",
      hosts: ["Sprite"],
      params: [P("intensity", "1.35", "Strength of the glow", 1), P("sigma", "10", "How far the light spreads", 2)] },
  ];

  const TRANSIENTS = [
    { id: "fx-dissolve-out", kind: "life", family: "life", name: "dissolve_out",
      idea: "Carves the silhouette away and hides it. Death / exit. <code>style</code>: noise · vortex · wipe · fade. Replaces any other life verb.",
      code: "ship.dissolve_out(0.5, style=\"vortex\", on_done=ship.destroy)\nship.dissolve_out(0.45, style=\"wipe\", angle=0)\nship.dissolve_out(0.4, style=\"fade\")",
      search: "dissolve_out death exit life style noise vortex wipe fade on_done",
      params: [P("duration", "0.5", "Seconds", 1), P("style", "\"noise\"", "noise · vortex · wipe · fade"), P("angle", "0", "Direction in degrees (0 = right): where the wipe sweeps from; in vortex, where the swirl pulls"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-burn-out", kind: "life", family: "life", name: "burn_out",
      idea: "Burns the body away and disappears. Replaces any other life verb.",
      code: "ship.burn_out(0.55, on_done=ship.destroy)\nship.burn_out(duration=0.55, intensity=1.2)",
      search: "burn_out burn life on_done intensity",
      params: [P("duration", "0.55", "Seconds", 1), P("intensity", "1", "Strength of the fire"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-fade-out", kind: "life", family: "life", name: "fade_out",
      idea: "Alpha only, then gone. Cheap. Replaces any other life verb.",
      code: "ship.fade_out(0.35, on_done=ship.destroy)\nship.fade_out(duration=0.35)",
      search: "fade_out alpha life on_done",
      params: [P("duration", "0.35", "Seconds", 1), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-implode", kind: "life", family: "life", name: "implode",
      idea: "Collapses the scale and disappears. Replaces any other life verb.",
      code: "ship.implode(0.28, scale_end=0.05, on_done=ship.destroy)",
      search: "implode collapse life on_done",
      params: [P("duration", "0.28", "Seconds", 1), P("scale_end", "0.05", "Final scale", 0, "number"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-dissolve-in", kind: "life", family: "life", name: "dissolve_in",
      idea: "Materializes (spawn). Turns <code>visible</code> on at the start. <code>style</code>: noise · vortex · wipe · fade. If the object is in the middle of an exit effect (dissolve_out, fade_out…), this one replaces it.",
      code: "ship.dissolve_in(0.5, style=\"noise\", on_done=lambda: None)\nship.dissolve_in(0.45, style=\"vortex\")",
      search: "dissolve_in spawn appear life style noise vortex wipe fade on_done",
      params: [P("duration", "0.5", "Seconds", 1), P("style", "\"noise\"", "noise · vortex · wipe · fade"), P("angle", "0", "Direction in degrees (0 = right): where the wipe sweeps from; in vortex, where the swirl pulls"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-fade-in", kind: "life", family: "life", name: "fade_in",
      idea: "Appears through alpha (spawn). Replaces any other life verb.",
      code: "ship.fade_in(0.35, on_done=lambda: None)\nship.fade_in(duration=0.35)",
      search: "fade_in spawn appear life on_done",
      params: [P("duration", "0.35", "Seconds", 1), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-flash", kind: "hit", family: "hit", name: "flash",
      idea: "The object turns white for an instant — the classic feedback for taking a hit. Same channel as blink: one replaces the other.",
      code: "ship.flash(0.12)\nship.flash(0.2, intensity=0.6, on_done=mark_hit)",
      search: "flash hit on_done",
      params: [P("duration", "0.12", "Seconds", 1), P("intensity", "1", "Strength"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-blink", kind: "hit", family: "hit", name: "blink",
      idea: "Blinks the object (it vanishes and comes back) — the classic sign of invincibility after taking damage. A second blink extends it; it replaces flash.",
      code: "ship.blink(duration=0.8, rate=8)\nship.blink(1.0, rate=6, intensity=1, on_done=clear_iframe)",
      search: "blink iframe on_done invincible damage",
      params: [P("duration", "0.8", "Seconds", 1), P("rate", "8", "Blinks per second"), P("intensity", "1", "Strength"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-pulse", kind: "pulse", family: "pulse", name: "pulse_outline",
      idea: "An outline that expands.",
      code: "ship.pulse_outline(0.25, color=(1, 1, 1, 1))\nship.pulse_outline(0.4, color=\"cyan\", on_done=clear_stun)",
      search: "pulse_outline outline on_done",
      params: [P("duration", "0.25", "Seconds", 1), P("color", "white", "Stroke color"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-pop", kind: "pop", family: "pop", name: "pop",
      idea: "The object suddenly grows and goes back to its normal size. Runs together with knock.",
      code: "ship.pop()\nship.pop(scale=1.4)\nship.pop(0.3, scale=1.4, on_done=None)",
      search: "pop scale grow on_done",
      params: [P("duration", "0.18", "Seconds", 1), P("scale", "1.2", "Peak"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-knock", kind: "knock", family: "knock", name: "knock",
      idea: "Pushes the drawing. Does not move the geometry. Stacks with <code>pop</code>. Polar (<code>distance=</code> + <code>angle=</code>) or Cartesian (<code>dx=</code> / <code>dy=</code>).",
      code: "ship.knock(distance=16, angle=30)\nship.knock(dx=12, dy=-4, on_done=None)",
      search: "knock recoil on_done",
      params: [P("duration", "0.14", "Seconds", 1), P("distance", "—", "Polar, with angle=", 0, "number"), P("angle", "—", "Degrees (y-up)"), P("dx", "0", "Or x offset", 0, "number"), P("dy", "0", "y offset", 0, "number"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-spark", kind: "spark", family: "spark", name: "spark_burst",
      idea: "Sparks fly outward. Never hides. Not SpatialFx <code>Sparks</code> nor <code>canvas.zap_at</code>.",
      code: "ship.spark_burst(0.35)\nship.spark_burst(amount=1.2, color=(1, 0.92, 0.75, 1), on_done=None)",
      search: "spark_burst spark sparks on_done",
      params: [P("duration", "0.35", "Seconds", 1), P("amount", "1", "How many"), P("color", "(1, 0.92, 0.75, 1)", "Color of the sparks"), P("on_done", "None", "Callback when it ends or is cancelled")] },
    { id: "fx-clear", kind: "life", family: "life", name: "clear_transients",
      idea: "Cancels every channel and calls each one's <code>on_done</code> (the same <code>on_done</code> as a normal end; it is not told that it was cancelled). <code>destroy()</code> cancels the same way, but without calling the on_done callbacks.",
      code: "ship.clear_transients()",
      search: "clear_transients cancel clear stop on_done",
      thumb: false,
      params: [] },
  ];

const SPATIAL = [
    { id: "spatial-fire", kind: "point", family: "spatial", name: "Fire",
      idea: "Fire that stays at one place in the world: a campfire, a torch, an exhaust. Two kinds: <code>camp</code> / <code>soft</code> are a disc of fire of radius <code>radius</code>; <code>plume</code> / <code>tongues</code> / <code>embers</code> / <code>blaze</code> are a jet of width <code>width</code> that rises in the direction <code>angle</code>. <code>blaze</code> is a costly volumetric column (1–2 on screen on a weak GPU; at medium / low quality it draws the <code>plume</code>).",
      code: "Fire()\nFire(center=(200, 150), radius=40)\nFire(center=(200, 150), width=40, style=\"plume\")\nFire(center=(400, 60), width=80, style=\"blaze\")",
      search: "fire camp plume blaze campfire column",
      variants: "style",
      params: [P("center", "design center", "Where the fire is (the base of the jet). A lambda follows: center=lambda: ship.center"), P("radius", "45", "Radius of the disc, in design units (camp / soft)"), P("style", "\"camp\"", "camp · soft · plume · tongues · embers · blaze"), P("width", "—", "Width of the jet, in design units (plume, tongues, embers, blaze)"), P("length", "—", "Height of the jet. Left out: in proportion to the width, depending on the style"), P("angle", "90", "Where the jet points, in degrees (90 = up, 0 = right)"), P("amount", "1", "Intensity: 1 = normal, 0 = off, 2 = strong"), P("speed", "1.2", "Pace of the animation; 0 freezes it"), P("rate", "None", "Particles per second (plume / embers). None = the style's default"), P("tongues", "5", "How many tongues of fire (style=\"tongues\"), from 3 to 9", 0, "integer")] },
    { id: "spatial-rain", kind: "pad", family: "spatial", name: "Rain",
      idea: "Rain falling in a rectangle of the world. It is an object of its own, not a visual of another object.",
      code: "Rain(p1=(300, 250), p2=(700, 550))\nRain(center=(500, 400), width=400, height=300)\nplatform = Rect(center=(500, 200), width=400, height=40)\nRain.from_rect(platform)",
      search: "rain",
      params: [P("p1", "—", "Corner. With p2=: opposite corners"), P("p2", "—", "Corner opposite p1"), P("center", "—", "Or a rectangle: center=, width=, height="), P("width", "200", "Width of the rectangle"), P("height", "160", "Height of the rectangle"), P("amount", "0.55", "Density"), P("color", "None", "Color of the drops; None = the default light blue")] },
    { id: "spatial-jet", kind: "beam", family: "spatial", name: "Jet",
      idea: "A directed jet. Axis + embers.",
      code: "Jet(p1=(200, 100), p2=(200, 40), width=14)\nguide = Line(p1=(400, 80), p2=(520, 200))\nJet.from_line(guide, width=12)",
      search: "jet",
      params: [P("p1", "—", "With p2=: a segment"), P("p2", "—", "End of the segment"), P("origin", "—", "Or polar, with angle= and length="), P("angle", "0", "Degrees"), P("length", "50", "Reach"), P("width", "14", "Thickness"), P("amount", "1", "Intensity of the jet"), P("color", "None", "Color of the jet; None = the effect's default")] },
    { id: "spatial-sparks", kind: "point", family: "spatial", name: "Sparks",
      idea: "A continuous patch of sparks. Not <code>spark_burst</code> nor <code>canvas.zap_at</code> (an electric flash at a point).",
      code: "fx = Sparks(center=(200, 150), radius=32, rate=40)\nfx.after(0.55, fx.destroy)",
      search: "sparks",
      params: [P("center", "design center", "Point of the patch"), P("radius", "28", "Size of the patch"), P("rate", "40", "Particles / s"), P("amount", "1", "Amount / brightness of the sparks"), P("color", "None", "Color of the sparks; None = the effect's default")] },
    { id: "spatial-glowspot", kind: "point", family: "spatial", name: "GlowSpot",
      idea: "A spot of light. Collides as a circle of 0.9 × radius.",
      code: "GlowSpot(center=(200, 150), radius=48, color=\"cyan\")",
      search: "glowspot light spot",
      params: [P("center", "design center", "Point of the glow. A lambda follows"), P("radius", "56", "Reach"), P("color", "—", "Color"), P("amount", "1", "Brightness")] },
    { id: "spatial-orb", kind: "point", family: "spatial", name: "Orb",
      idea: "Disc + corona. A sun by default. Collides by the disc's radius.",
      code: "Orb()\nOrb(color=\"silver\", glow=1.15, phase=0.15, soft_edge=0.1)",
      search: "orb sun moon",
      params: [P("center", "design center", "Point of the orb. A lambda follows"), P("radius", "48", "Body, collision"), P("color", "warm", "Pigment"), P("glow", "1", "Corona outside the body"), P("phase", "0", "Phase, like the moon's: 0 = full, 1 = new; values in between give a crescent"), P("amount", "1", "Intensity of the orb")] },
    { id: "spatial-sunburst", kind: "point", family: "spatial", name: "Sunburst",
      idea: "A burst of sun in the world. Not the <code>Stars</code> background.",
      code: "Sunburst()\nSunburst(color=\"cyan\")",
      search: "sunburst starburst",
      params: [P("center", "design center", "Point of the burst. A lambda follows"), P("radius", "48", "Reach"), P("color", "white→amber", "Optional; left out = the canonical ramp"), P("amount", "1", "Intensity"), P("speed", "1", "Speed of the animation")] },
    { id: "spatial-starburst", kind: "point", family: "spatial", name: "Starburst",
      idea: "A star of rays in the world. Not the <code>Stars</code> background nor Sunburst.",
      code: "Starburst()\nStarburst(center=(200, 150), radius=40, points=5)",
      search: "starburst star rays",
      params: [P("center", "design center", "Point of the star. A lambda follows"), P("radius", "40", "Reach"), P("points", "5", "Rays (≥ 4)"), P("amount", "1", "Strength"), P("speed", "1", "Pulse"), P("color", "cream", "Pigment")] },
    { id: "spatial-warp", kind: "point", family: "spatial", name: "Warp",
      idea: "A hyperspace vortex in the world. A disc with a radius, at one place in the world. Full-screen flight: <code>Tunnel</code> / <code>StarFly</code>. Energy ring: <code>Portal</code>.",
      code: "Warp()\nWarp(center=(400, 220), radius=90, color=\"cyan\")\nWarp(color=\"navy\", color2=\"black\", core=0, into=False)",
      search: "warp hyperspace vortex tunnel",
      params: [
        P("center", "design center", "Point of the vortex. A lambda follows"),
        P("radius", "72", "Body, collision"),
        P("color", "cool blue", "Pigment of the rays"),
        P("color2", "derived", "Background / wall. None = derived from color"),
        P("amount", "1", "Energy"),
        P("speed", "1", "Flight through the tunnel. 0 = still"),
        P("twist", "0.35", "Spiral", 0, "number"),
        P("spokes", "6", "Rays (integer 3…24)", 0, "int"),
        P("core", "1", "Core. 0 = hollow", 0, "number"),
        P("into", "True", "True = the flight goes into the tunnel; False = the flight comes out of the tunnel", 0, "bool"),
        P("spin", "0", "Spin (independent of speed)"),
        P("glow", "0.8", "Corona outside the radius")
      ] },
    { id: "spatial-portal", kind: "point", family: "spatial", name: "Portal",
      idea: "A ring of turbulent light in the world. Hollow: the radius is the ring. <code>tilt</code> tilts the ring (it turns into a 3D ellipse). Not <code>Warp</code> (a vortex disc) nor the <code>ElectricField</code> visual (the outline of a shape).",
      code: "Portal()\nPortal(center=(400, 220), radius=80, color=\"magenta\")\nPortal(radius=70, tilt=60, angle=20, chaos=1.6)",
      search: "portal ring hoop rift energy",
      params: [
        P("center", "design center", "Point of the ring. A lambda follows"),
        P("radius", "60", "Radius of the ring, collision"),
        P("color", "electric blue", "Color of the ring"),
        P("color2", "derived", "Second color of the filaments. None = violet with the default color; otherwise a lighter shade of color"),
        P("amount", "1", "Brightness"),
        P("speed", "1", "Speed. 0 = frozen"),
        P("thickness", "0.25", "Thickness, as a fraction of the radius (0.05…1)", 0, "number"),
        P("chaos", "1", "Turbulence: 0 = clean hoop … 2 = wild", 0, "number"),
        P("tilt", "0", "Degrees of tilt: 0 = facing you, 80 ≈ edge-on", 0, "number"),
        P("angle", "0", "Direction of the tilt axis (degrees)", 0, "number"),
        P("glow", "0.8", "Corona around the ring")
      ] },
  ];

  const POST = [
    { id: "post-vignette", kind: "fixed", family: "post", name: "Vignette",
      idea: "Darkens the corners.", code: "Vignette()\nVignette(amount=0.8, thickness=0.22)", search: "vignette corners",
      params: [P("amount", "1", "Strength", 1, "number"), P("thickness", "0.22", "Fraction of the edge", 0, "number")] },
    { id: "post-grain", kind: "fixed", family: "post", name: "Grain",
      idea: "Film grain.", code: "Grain()\nGrain(amount=0.12)", search: "grain film",
      params: [P("amount", "0.07", "Grain opacity", 1, "number")] },
    { id: "post-fog", kind: "fixed", family: "post", name: "Fog",
      idea: "Fog settling heavy at the bottom.", code: "Fog()\nFog(amount=0.6, color=\"dim gray\")", search: "fog mist",
      params: [P("amount", "0.45", "Density", 1, "number"), P("color", "(0.75, 0.82, 0.9)", "Fog color", 0, "color"), P("height", "0.55", "How high it rises on the screen", 0, "number")] },
    { id: "post-bloom", kind: "fixed", family: "post", name: "Bloom",
      idea: "Glow bursting out of the bright parts.",
      code: "bloom = Bloom(intensity=0.8)\nbloom.intensity = 1.0",
      search: "bloom glow",
      params: [P("intensity", "0.6", "Strength", 1, "number"), P("sigma", "10", "Blur", 0, "number")] },
    { id: "post-grade", kind: "fixed", family: "post", name: "Grade",
      idea: "Changes the color of the whole picture, like a photo filter: warmer, cooler, sepia, black and white, night.",
      code: "Grade(\"cool\")",
      search: "grade filmic cool sepia",
      variants: "preset",
      params: [P("preset", "\"filmic\"", "filmic · cool · warm · sepia · bw · duo · night", 1), P("brightness", "0", "Lightens (positive) or darkens (negative) everything; 0 = as the preset", 0, "number"), P("contrast", "1", "Contrast: 1 = normal, higher = stronger", 0, "number"), P("saturation", "1", "Color strength: 1 = normal, 0 = gray", 0, "number"), P("matrix", "None", "Your own 4×5 color matrix (20 floats); None = uses the preset", 0, "sequence")] },
    { id: "post-chroma", kind: "fixed", family: "post", name: "Chroma",
      idea: "Pushes red, green and blue apart, like a cheap lens or a faulty screen.", code: "Chroma()\nChroma(amount=6)", search: "chroma rgb",
      params: [P("amount", "4", "How far the colors split, in screen pixels", 1, "number")] },
    { id: "post-pixelate", kind: "fixed", family: "post", name: "Pixelate",
      idea: "Shows the picture in big blocks, like an old low-resolution game.", code: "Pixelate()\nPixelate(cell=8)", search: "pixelate",
      params: [P("cell", "5", "Size of each block, in screen pixels", 1, "number")] },
    { id: "post-scanlines", kind: "fixed", family: "post", name: "Scanlines",
      idea: "Thin horizontal lines over the picture, like an old TV (CRT).", code: "Scanlines()\nScanlines(amount=0.8)", search: "scanlines crt",
      params: [P("amount", "1", "Strength", 1, "number")] },
    { id: "post-screenblur", kind: "fixed", family: "post", name: "ScreenBlur",
      idea: "Blurs the whole picture.", code: "ScreenBlur()\nScreenBlur(sigma=4)", search: "screenblur",
      params: [P("sigma", "2.5", "Blur", 1, "number")] },
    { id: "post-wash", kind: "fixed", family: "post", name: "Wash",
      idea: "Covers the whole picture with a pale, steady color while it is on — a white veil, damage red, heat gold. For a flash that lasts an instant, use <code>canvas.flash</code>.",
      code: "Wash()\nWash(intensity=0)",
      search: "wash bleach", params: [P("intensity", "0.25", "Veil strength: 0 = nothing, 1 = only the color", 1), P("color", "(1, 1, 1)", "Veil color; white by default")] },
    { id: "post-distantlight", kind: "light", family: "post", name: "DistantLight",
      idea: "Sunlight: it comes from one direction and lights the whole screen evenly, giving the objects relief.",
      code: "DistantLight()\nDistantLight(direction=(-0.55, -0.75), intensity=1.1)",
      search: "distantlight sun",
      params: [
        P("direction", "(-0.55, -0.75)", "Where the light comes from, in design space", 1, "point"),
        P("color", "(1.12, 1.05, 0.92)", "Light color", 0, "color"),
        P("ambient", "0.28", "Ambient light", 0, "number"),
        P("intensity", "0.95", "Strength", 0, "number"),
        P("specular", "0.35", "Specular shine", 0, "number")
      ] },
    { id: "post-haze", kind: "anim", family: "post", name: "Haze",
      idea: "Makes the picture ripple gently, like hot air over asphalt or the view under water. <code>kind</code> picks the starting style (<code>haze</code>, <code>heat</code>, <code>underwater</code>); once created, adjust <code>amount</code> / <code>speed</code>.",
      code: "Haze(kind=\"heat\")",
      search: "haze heat underwater",
      variants: "kind",
      params: [
        P("amount", "from kind", "Strength. Left out = the kind's default", 1, "number"),
        P("speed", "from kind", "Pace. Left out = the kind's default", 2, "number"),
        P("kind", "\"haze\"", "haze · heat · underwater. Only picks defaults at construction."),
        P("bias", "from kind", "Average offset of the ripple. Left out: the kind's default")
      ] },
    { id: "post-crt", kind: "anim", family: "post", name: "Crt",
      idea: "Imitates an old tube TV (CRT): picture curved at the edges, colors split apart, horizontal lines and dark corners.",
      code: "Crt()\nCrt(amount=0.8, chroma=1.2, scan=0.9)",
      search: "crt",
      params: [P("amount", "1", "How much the picture curves at the edges and darkens at the corners", 1, "number"), P("chroma", "1", "How far red, green and blue split apart", 0, "number"), P("scan", "1", "Strength of the horizontal lines", 0, "number")] },
    { id: "post-vortex", kind: "anim", family: "post", name: "Vortex",
      idea: "Twists the picture into a whirlpool around a point. Without <code>target</code>, the center follows the mouse.", code: "Vortex()", search: "vortex", params: [P("target", "mouse", "Center of the whirlpool: a point or an object; left out = the mouse"), P("amount", "1", "How much it twists"), P("spin", "1", "Spin speed; 0 = still")] },
    { id: "post-zoomblur", kind: "anim", family: "post", name: "ZoomBlur",
      idea: "A blur in rays from a point, like a fast camera zoom or a jump to light speed. Without <code>center</code>, it follows the mouse.", code: "ZoomBlur()", search: "zoomblur", params: [P("center", "mouse", "Where the rays come from: a point or an object; left out = the mouse"), P("amount", "0.5", "Blur strength")] },
    { id: "post-kaleidoscope", kind: "anim", family: "post", name: "Kaleidoscope",
      idea: "Kaleidoscope: repeats a slice of the picture in mirrors around the center, spinning.", code: "Kaleidoscope()", search: "kaleidoscope",
      params: [P("segments", "8", "How many mirrored slices", 1), P("zoom", "1", "Zooms in (higher) or out (lower) on the picture", 2), P("spin", "0.15", "Spin speed; 0 = still", 3)] },
    { id: "post-prism", kind: "anim", family: "post", name: "Prism",
      idea: "Splits the picture's colors in rotating directions, like light through a prism.", code: "Prism()\nPrism(amount=0.006)", search: "prism",
      params: [P("amount", "0.004", "How far the colors split (small values: 0.002–0.01)", 1, "number")] },
    { id: "post-perspective", kind: "anim", family: "post", name: "Perspective",
      idea: "Tilts the picture as if the screen were seen from the side, pulling toward a point. Without <code>target</code>, it follows the mouse.",
      code: "Perspective()\nPerspective(amount=0.7, target=(400, 300))",
      search: "perspective",
      params: [P("amount", "0.55", "How much it tilts", 1, "number"), P("target", "mouse", "Where the picture tilts toward: a point or an object; None = the mouse")] },
    { id: "post-lamp", kind: "light", family: "post", name: "Lamp",
      idea: "A lamp over the game: it lights up around a point and leaves the rest in shadow, with shine on the objects' edges. Without <code>target</code>, it follows the mouse.",
      code: "Lamp()\nLamp(range=400, radius=180)",
      search: "lamp light",
      params: [
        P("color", "(1.15, 1.05, 0.85)", "Light color", 1, "color"),
        P("radius", "38% of the short side", "Size of the well-lit area, in design units (follows the zoom)", 0, "number"),
        P("range", "55% of the short side", "Distance, in design units, beyond which no light reaches", 0, "number"),
        P("ambient", "0.16", "Ambient light", 0, "number"),
        P("specular", "0.6", "Specular shine", 0, "number"),
        P("intensity", "1.15", "Strength", 0, "number"),
        P("target", "mouse", "Point. None = follows the mouse")
      ] },
    { id: "post-spotlight", kind: "light", family: "post", name: "Spotlight",
      idea: "A spotlight: a cone of light that comes from <code>origin</code> and points at <code>target</code>; outside the cone it is dark.", code: "Spotlight(range=400)", search: "spotlight",
      params: [P("range", "55% of the short side", "Cutoff, in design units", 0, "number"), P("origin", "None", "Where the light comes from; None = top center", 0, "point"), P("target", "None", "Where it points; None = mouse", 0, "point"), P("color", "(1.15, 1.05, 0.85)", "Light color (can go above 1 = stronger)"), P("cone_angle", "34", "Cone opening, in degrees"), P("softness", "14", "Soft edge of the cone, in degrees"), P("ambient", "0.1", "Light outside the cone, 0–1"), P("intensity", "1.45", "Light strength in the cone")] },
    { id: "post-godrays", kind: "anim", family: "post", name: "GodRays",
      idea: "Rays of light from the bright parts of the picture toward a point, like sun through clouds.",
      code: "GodRays()\nGodRays(weight=0.4, target=(400, 300))",
      search: "godrays",
      thumb: "GodRays(target=(W * 0.62, H * 0.5))",
      params: [
        P("weight", "0.35", "Ray strength (higher = brighter rays)", 1, "number"),
        P("decay", "0.86", "Falloff along the ray", 0, "number"),
        P("exposure", "1.8", "Exposure", 0, "number"),
        P("target", "mouse", "Where the rays come from. None = mouse")
      ] },
    { id: "post-motiontrail", kind: "anim", family: "post", name: "MotionTrail",
      idea: "A ghost trail of everything that moves on the screen: the objects stay sharp and leave a fading image behind. <code>enabled = False</code> clears the trail.",
      code: "MotionTrail()", search: "motiontrail",
      thumb: "ball = Circle(center=(W * 0.1, H * 0.5), radius=36, color=\"gold\")\nball.move_to(W * 0.9, H * 0.5, time=1.6)\nMotionTrail()",
      params: [P("opacity", "1", "Trail strength (0 = invisible)"), P("fade", "0.9", "How much of the trail is left every 1/60 s: 0.85–0.95 gives long trails")] },
    { id: "post-colorsweep", kind: "anim", family: "post", name: "ColorSweep",
      idea: "Tints the picture with 2–4 colors that change along an axis (center to edge, left to right or top to bottom), pulsing slowly.",
      code: "ColorSweep()", search: "colorsweep",
      params: [P("axis", "radial", "radial · horizontal · vertical"), P("speed", "1", "Pace"), P("colors", "None", "2–4 tints of the sweep; None = default palette"), P("amount", "0.55", "Blend strength"), P("saturation", "0.45", "Saturation of the tints")] },
    { id: "post-colorwash", kind: "anim", family: "post", name: "ColorWash",
      idea: "Plasma coloring the picture. After construction, the palette is <code>.colors</code> (not color / color2 / color3).",
      code: "wash = ColorWash()\nwash.colors = (\"gold\", \"cyan\")\nwash.amount = 0.7\nColorWash(\"orchid\", \"cyan\", \"magenta\", amount=0.7)",
      search: "colorwash",
      params: [
        P("color", "orchid", "First color", 1, "color"),
        P("color2", "cyan", "Second color", 0, "color"),
        P("color3", "magenta", "Third color", 0, "color"),
        P("colors", "—", "After construction: a 2–3 color palette. Replaces color / color2 / color3."),
        P("amount", "0.55", "Strength", 0, "number"),
        P("speed", "0.55", "Pace", 0, "number"),
        P("saturation", "0.4", "Saturation", 0, "number")
      ] },
    { id: "post-cosmicbloom", kind: "anim", family: "post", name: "CosmicBloom",
      idea: "Nebula patches coloring the picture, plus glow bursting out of the bright parts.", code: "CosmicBloom()", search: "cosmicbloom",
      params: [P("speed", "1.2", "Pace"), P("amount", "1", "Strength"), P("color", "None", "First nebula tint; None = default"), P("color2", "None", "Second tint; None = default"), P("bloom", "0.7", "Glow strength on the bright pixels"), P("saturation", "0.35", "Saturation of the color shift")] },
  ];

  // One-shot canvas verbs: fired, decay on their own, never in canvas.effects.
  // kind: screen (whole picture) · point (*_at, at a place) · cover (fade_out / fade_in).
  const IMPACTS = [
    { id: "post-flash", kind: "screen", family: "impact", name: "canvas.flash",
      idea: "A white burst. Not Wash.",
      code: "canvas.flash(0.6)", search: "flash impact", params: [P("intensity", "0.6", "Strength", 1)] },
    { id: "post-shake", kind: "screen", family: "impact", name: "canvas.shake",
      idea: "Shakes the camera for an instant.", code: "canvas.shake(10)", search: "shake", params: [P("amount", "10", "Strength of the shake (10 = default; higher = stronger)", 1)] },
    { id: "post-glitch", kind: "screen", family: "impact", name: "canvas.glitch",
      idea: "A one-instant picture glitch: the screen jumps and the colors split apart.", code: "canvas.glitch()\ncanvas.glitch(0.8)", search: "glitch", params: [P("amount", "1", "Strength", 1)] },
    { id: "post-ripple", kind: "point", family: "impact", name: "canvas.ripple_at",
      idea: "A wave at the point. Also <code>ripple_at(info.point)</code> / Graphic. <code>None</code> does nothing.",
      code: "canvas.ripple_at(x, y, amount=1.0)\ncanvas.ripple_at(info.point)", search: "ripple",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("amount", "1", "How much the picture warps (and the strength of the shake)", 3), P("radius", "screen", "How far the wave reaches, in design units; left out = the whole screen", 4), P("shock", "True", "Draws the shock ring"), P("flash", "False", "Brief flash"), P("shake", "True", "Camera shake")] },
    { id: "post-wave", kind: "point", family: "impact", name: "canvas.wave_at",
      idea: "A straight-line shock wave that leaves the point in the direction of <code>angle</code> and warps the screen. Takes the place the way <code>ripple_at</code> does.",
      code: "canvas.wave_at(x, y, angle=0)\ncanvas.wave_at(info.point, angle=90)", search: "wave_at",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("angle", "0", "Degrees. 0 = +x", 3), P("amount", "1", "Strength of the wave / shake"), P("shock", "True", "Draws the shock ring"), P("flash", "False", "Brief flash"), P("shake", "True", "Camera shake")] },
    { id: "post-explosion", kind: "point", family: "impact", name: "canvas.explosion_at",
      idea: "A big fireball at a point, with a shake and a ripple of the screen. Takes x, y, a point or the collision info: <code>explosion_at(info)</code> / <code>info.point</code>. <code>None</code> does nothing.",
      code: "canvas.explosion_at(x, y)\ncanvas.explosion_at(info.point, amount=0.8, shake=False)\ncanvas.explosion_at(info, amount=0.8, shake=False)",
      search: "explosion_at explosion fireball",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("rings", "True", "Rings"), P("amount", "1.2", "Strength; after a point, pass amount= by name"), P("shock", "True", "Adds a weak ripple of the screen"), P("flash", "False", "Brief flash"), P("shake", "True", "Camera shake")] },
    { id: "post-burst", kind: "point", family: "impact", name: "canvas.burst_at",
      idea: "A small explosion, the size of a ship, with no shake or flash: you can fire many at the same time. <code>burst_at(ship)</code> uses the center.",
      code: "canvas.burst_at(x, y, radius=42)\ncanvas.burst_at(ship, radius=36)", search: "burst_at",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("radius", "42", "Reach. 3rd or radius=", 3), P("amount", "1.2", "Strength", 4), P("rings", "False", "Expanding stroke rings")] },
    { id: "post-fireworks", kind: "point", family: "impact", name: "canvas.fireworks_at",
      idea: "Stars that burst open. A celebration, not a fireball. No mortar. Peony pattern (<code>fall=0</code>); raise <code>fall</code> for a willow. Takes the place the way <code>explosion_at</code> does.",
      code: "canvas.fireworks_at(x, y)\ncanvas.fireworks_at(x, y, color=\"gold\", radius=64)\ncanvas.fireworks_at(x, y, color=\"cyan\", color2=\"white\", fall=1.1)",
      search: "fireworks_at fireworks star celebration peony willow",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("color", "gold", "Color of the stars", 3), P("color2", "derived white", "Glitter / tips. Left out = derived from color"), P("radius", "64", "Reach"), P("amount", "1", "Brightness"), P("count", "28", "Stars (8–48)"), P("fall", "0", "Gravity. 0 = peony; ~1.2 = willow"), P("trail", "0.35", "Trail")] },
    { id: "post-zap", kind: "point", family: "impact", name: "canvas.zap_at",
      idea: "An electric spark at the point: a bright core + jagged rays. Three styles: <code>spark</code> (impact + short rays), <code>fork</code> (long branching rays), <code>corona</code> (an electric ring that opens). Not SpatialFx <code>Sparks</code> (continuous) nor <code>spark_burst</code> (a shape transient). No screen shake / warp. Takes the place the way <code>explosion_at</code> does.",
      code: "canvas.zap_at(x, y)\ncanvas.zap_at(x, y, style=\"fork\", color=\"gold\", radius=40)\ncanvas.zap_at(ship, style=\"corona\", flash=True)\ncanvas.zap_at(info.point, style=\"spark\", amount=1.2)",
      search: "zap_at electric spark fork corona lightning ray tesla bolt",
      variants: "style",
      params: [
        P("x", "—", "Where: x, y as two numbers, or a point as the 1st (tuple, Point, Vec2, Graphic, collision info). None = does nothing", 1),
        P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x). After a point, the other parameters go by name", 2),
        P("color", "cyan", "Color of the glow and the rays", 3),
        P("radius", "24", "Reach in design units (min. 12)"),
        P("amount", "1", "Brightness / strength (about 0.15–2.5)"),
        P("count", "per style", "How many rays. Left out: spark 16 · fork 8 · corona 12 (4–36; scales with quality)"),
        P("style", "\"spark\"", "spark = impact + short rays · fork = branching rays · corona = electric ring"),
        P("flash", "False", "True = a short white flash on the screen (canvas.flash)", 0, "bool")
      ] },
    { id: "post-hit", kind: "point", family: "impact", name: "canvas.hit_at",
      idea: "A hit mark: something took the blow and <strong>is still alive</strong>. A hot white star + a thin ring + short sparks, ~0.2 s. <code>style=\"disc\"</code> is the light version: a disc of light that opens and fades, with no sparks and no direction. <code>count=0</code> keeps the star and the ring, without sparks. <code>angle</code> aims the sparks in a cone (90 = up); without <code>angle</code> they fly every way. The angle never comes from <code>info</code> — the normal flips side with the order of <code>@collide</code>. Pair it with the body's reaction (<code>hero.flash()</code>, <code>hero.knock(...)</code>). No shake / warp; many at the same time (a boss under a barrage). Takes the place the way <code>explosion_at</code> does.",
      code: "canvas.hit_at(info, angle=90)\ncanvas.hit_at(x, y)\ncanvas.hit_at(boss, color=\"cyan\", radius=24)\ncanvas.hit_at(wall, style=\"disc\")\ncanvas.hit_at(shield, count=0)",
      thumb: "canvas.hit_at(x, y, radius=32)",
      search: "hit_at hit blow strike impact shot damage spark bullet boss disc flash light",
      variants: "style",
      params: [
        P("x", "—", "Where: x, y as two numbers, or a point as the 1st (tuple, Point, Vec2, Graphic, collision info). None = does nothing", 1),
        P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x). After a point, the parameters go by name", 2),
        P("color", "warm white", "Tint of the rim and the sparks. The core stays white", 3),
        P("angle", "None", "Direction of the sparks in degrees (0 = right, 90 = up), a cone of ~100°. None = all around"),
        P("radius", "16", "Size in design units"),
        P("amount", "1", "Brightness / strength"),
        P("count", "8", "Sparks (3–24; scales with quality). 0 = star and ring, no sparks"),
        P("style", "\"star\"", "star = star + ring + sparks · disc = disc of light, no sparks (angle / count raise an error)")
      ] },
    { id: "post-debris", kind: "point", family: "impact", name: "canvas.debris_at",
      idea: "Broken into pieces, <strong>no fire</strong>: irregular shards fly, spin, shrink and fade over a dust cloud. Matte (does not add light) — it shows on a light background. <code>fall=0</code> floats (ship, top-down view); <code>fall≈1</code> falls in an arc (platformer). The color never comes from the Graphic; pass <code>color=</code>. The shards are only paint — they do not collide. Chain it with <code>burst_at</code> (a ship exploding) or <code>hit_at</code> (a rock cracking). Takes the place the way <code>explosion_at</code> does.",
      code: "canvas.debris_at(x, y)\ncanvas.debris_at(asteroid, color=\"dim gray\", radius=48)\ncanvas.debris_at(crate, color=\"peru\", fall=1)",
      thumb: "canvas.debris_at(x, y, color=\"peru\", radius=80, count=22)",
      search: "debris_at debris shards pieces break shatter dust rock asteroid crate",
      params: [
        P("x", "—", "Where: x, y as two numbers, or a point as the 1st (tuple, Point, Vec2, Graphic, collision info). None = does nothing", 1),
        P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x). After a point, the parameters go by name", 2),
        P("color", "stone gray", "Color of the shards. The dust is a lighter mix", 3),
        P("radius", "40", "Spread in design units"),
        P("amount", "1", "Strength — how far the shards fly"),
        P("count", "14", "Shards (4–40; scales with quality)"),
        P("fall", "0", "Gravity. 0 = floats; ~1 = arc downward"),
        P("dust", "True", "Dust cloud under the shards (gone at low quality)", 0, "bool")
      ] },
    { id: "post-bubbles", kind: "point", family: "impact", name: "canvas.bubbles_at",
      idea: "Rising foam. Also <code>canvas.bubbles()</code> in columns. Takes the place the way <code>explosion_at</code> does.",
      code: "canvas.bubbles_at(x, y, color=\"cyan\", count=18)\ncanvas.bubbles_at(info.point, color=\"cyan\")", search: "bubbles foam",
      params: [P("x", "—", "Where: x, y as two numbers, or a point as the 1st", 1), P("y", "—", "The y coordinate, with x (leave it out if you passed a point as x)", 2), P("color", "—", "Color", 3), P("count", "18", "How many"), P("height", "140", "How high they rise"), P("amount", "1", "Amount / strength of the bubbles")] },
    { id: "post-fade-out", kind: "cover", family: "cover", name: "canvas.fade_out",
      idea: "Covers the screen and <strong>holds</strong> until <code>fade_in</code>. Drawn after the widgets (it covers the HUD). Not a post or an impact. No <code>then=</code>.",
      code: "canvas.fade_out(0.5)\ncanvas.fade_out(0.5, color=\"navy\", style=\"wipe\", angle=90)\ncanvas.fade_out(0.5, style=\"iris\", on_done=load_next)",
      search: "fade_out cover wipe iris transition black",
      params: [P("duration", "0.5", "Seconds. 0 = at once", 1), P("color", "black", "Cover color"), P("style", "\"fade\"", "fade · wipe · iris"), P("angle", "0", "Wipe only, degrees (0 = +x)"), P("center", "screen center", "Iris only, design point"), P("on_done", "None", "Callback when the tween ends")] },
    { id: "post-fade-in", kind: "cover", family: "cover", name: "canvas.fade_in",
      idea: "Reveals. With no cover before it, it starts covered (an opening). Leave out color / style to use the same ones as <code>fade_out</code>.",
      code: "canvas.fade_in(0.5)\ncanvas.fade_in(0.45, style=\"iris\")",
      search: "fade_in cover uncover reveal opening",
      params: [P("duration", "0.5", "Seconds. 0 = at once", 1), P("color", "fade_out's", "Cover color. Left out: the same as the current cover"), P("style", "fade_out's", "fade · wipe · iris. Left out: the same as fade_out"), P("angle", "fade_out's", "Wipe only, degrees. Left out: the same as fade_out"), P("center", "fade_out's", "Iris only, design point. Left out: the same as fade_out"), P("on_done", "None", "Callback when it ends")] },
  ];

  const FLY_PAN = "Moves the vanishing point with the camera (pan). Off by default.";
  function fieldCam(pan, zoom, rot, panHint) {
    return [
      P("pan_response", String(pan), panHint || "0 = stuck to the screen. 1 = 1:1 with the world"),
      P("zoom_response", String(zoom), "How much the camera zoom affects the pattern"),
      P("rotation_response", String(rot), "Fraction of the camera rotation"),
      P("scroll", "(0, 0)", "Drift in design units / s, independent of the camera"),
      P("enabled", "True", "Hides the drawing without taking it off the stack"),
    ];
  }

  const BACKGROUNDS = [
    { id: "bg-sky", kind: "base", family: "field", name: "SkyGradient",
      idea: "A sky in a vertical gradient. It becomes the base. The last wallpaper wins. <code>horizon</code> is where the atmosphere (<code>middle</code>) sits — 0–1, y-up. <code>palette</code> / <code>top</code> / <code>middle</code> / <code>bottom</code> are fixed at construction — to change the ramp, replace the base. <code>horizon</code> / <code>fade</code> / camera / <code>enabled</code> apply live.",
      code: "SkyGradient(\"night\")\nSkyGradient(\"sunset\")\nSkyGradient(\"day\", horizon=0.42)\nSkyGradient(top=\"navy\", middle=\"sky blue\", bottom=\"navy\")",
      search: "skygradient sky day night sunset dawn dusk space",
      variants: "palette",
      params: [
        P("palette", "\"day\"", "day · dawn · sunset · dusk · night · space · overcast · desert · forest · toxic · ember · ice · underwater. Any top/middle/bottom skips the preset and fills in the rest from day.", 1),
        P("top", "from the preset", "Color of the zenith (top of the screen). With middle/bottom, palette is ignored."),
        P("middle", "from the preset", "Color of the atmosphere, at the horizon."),
        P("bottom", "from the preset", "Color below the horizon (solid). With horizon=0 it does not show."),
        P("horizon", "0", "Horizon line (0–1, y-up from the bottom). 0 = sky all the way down (middle at the bottom). Line it up with Ground."),
        P("fade", "0.003", "Blends middle → bottom below the line. 0 = a sharp cut. The same parameter as in Ground."),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-wallpaper", kind: "base", family: "field", name: "Wallpaper",
      idea: "The base of the background: a color, gradient, image file or texture. Creating it already makes it <code>canvas.background.base</code>. No args: opaque black. A string with <code>.</code> or <code>/</code> is a file; otherwise it is a color. Once created, you can change <code>.source</code>, the camera settings and <code>enabled</code>. <code>fit</code> / <code>tile_mode</code> / <code>scale</code> / <code>tile_size</code> / <code>underlay</code> / <code>filename</code> / <code>image</code> stay fixed — to change them, replace <code>.source</code> or create another Wallpaper. With a camera that moves (<code>pan_response</code> / <code>zoom_response</code>), pass <code>tile_mode=\"mirror\"</code>: without it, the <code>underlay</code> (black) shows beyond the image's border.",
      code: "Wallpaper(\"navy\")\nWallpaper(Gradient(\"black\", \"navy\", angle=90), pan_response=0.05)\nWallpaper(\"space.jpg\", tile_mode=\"mirror\", pan_response=0.15, zoom_response=0.3)\nWallpaper(\"bg2.png\", fit=\"contain\")\nWallpaper(path, fit=\"tile\", tile_size=200, tile_mode=\"mirror\")",
      search: "wallpaper base color image texture fit tile cover contain",
      params: [
        P("source", "black", "A color name, tuple, Color, Gradient, Texture, file (str with . or /) or Image. A Visual / SpatialFx / filter raises TypeError.", 1, "color / Gradient / file / Texture"),
        P("filename", "None", "Instead of source: a path. Searched like Image files."),
        P("image", "None", "Instead of source: a skia.Image already loaded."),
        P("fit", "\"cover\"", "Image only: cover · contain · stretch · tile"),
        P("tile_mode", "\"decal\"", "Image only: what shows beyond the border when the camera moves or zooms out. decal (nothing; the underlay shows) · clamp (stretches the border) · repeat · mirror (mirrored, no seam). Left out: repeat with fit=\"tile\", otherwise decal. In tile, clamp becomes repeat."),
        P("scale", "1", "Image only: extra zoom. Must be > 0."),
        P("tile_size", "¼ of the shorter side", "Image / fit=\"tile\" only: the cell, in design units. With another fit it is a TypeError."),
        P("underlay", "black", "Image only: color of the bands left over in fit=\"contain\" and of everything beyond the border with tile_mode=\"decal\". None = does not paint what is left over."),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-stars", kind: "ambient", family: "field", name: "Stars",
      idea: "A star field. Not SpatialFx Starburst.",
      code: "Stars()\nStars(pan_response=0.0, density=0.9, scroll=(0.0, -45.0))",
      search: "stars starfield twinkle",
      params: [
        P("color", "light blue", "Star pigment", 1),
        P("density", "0.8", "Amount"),
        P("twinkle", "0", "Twinkle. 0 = static."),
        P("amount", "1", "Brightness"),
        P("alpha", "1", "Opacity"),
        ...fieldCam(0.02, 0, 0)
      ] },
    { id: "bg-clouds", kind: "ambient", family: "field", name: "Clouds",
      idea: "A band of clouds. Stack several for depth.",
      code: "Clouds()\nClouds(pan_response=0.1, amount=0.6, speed=0.8)",
      search: "clouds sky",
      thumb: "canvas.background = SkyGradient(\"day\")\nClouds()",
      params: [
        P("color", "white", "Cloud pigment", 1),
        P("amount", "0.45", "Coverage"),
        P("band", "0.45", "Height of the band's middle on the screen: 0 = bottom, 1 = top"),
        P("spread", "0.55", "How wide the band is"),
        P("detail", "1", "How much fine detail the clouds have"),
        P("speed", "1", "Own drift"),
        P("alpha", "1", "Opacity"),
        P("res_scale", "0.5", "Internal resolution. 1 = full."),
        ...fieldCam(0.08, 0.05, 0)
      ] },
    { id: "bg-mist", kind: "ambient", family: "field", name: "Mist",
      idea: "A band of mist. Not the Haze post or a shape filter.",
      code: "Mist()\nMist(pan_response=0.2, amount=0.85)",
      search: "mist fog",
      params: [
        P("color", "gray", "Mist pigment", 1),
        P("amount", "0.7", "Density"),
        P("band", "0.4", "Height of the band's middle on the screen: 0 = bottom, 1 = top"),
        P("spread", "0.35", "How wide the band is"),
        P("speed", "0.15", "Own drift"),
        P("alpha", "0.7", "Opacity"),
        ...fieldCam(0.2, 0, 0)
      ] },
    { id: "bg-stardust", kind: "ambient", family: "field", name: "Stardust",
      idea: "Soft space dust (several octaves), two colors. Not Chromadust or Nebuladust.",
      code: "Stardust()\nStardust(color=\"violet\", color2=\"cyan\", speed=0.3)",
      search: "stardust dust space two colors",
      params: [
        P("color", "violet", "First pigment", 1),
        P("color2", "cyan", "Second pigment"),
        P("amount", "1", "Density"),
        P("speed", "0.2", "Own drift"),
        P("alpha", "0.7", "Opacity"),
        P("res_scale", "0.6", "Internal resolution. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-chromadust", kind: "ambient", family: "field", name: "Chromadust",
      idea: "The same dust as Stardust, but the color cycles: an HSV rainbow with no args, or any preset / Gradient. <code>reflect</code> goes back and forth along the ramp (red→blue→red). Not the Chroma post.",
      code: "Chromadust()\nChromadust(\"plasma\")\nChromadust(Gradient(\"sunset\"))\nChromadust((\"red\", \"blue\"))\nChromadust((\"red\", \"blue\"), reflect=False)",
      search: "chromadust rainbow gradient palette hue reflect yoyo dust chroma",
      params: [
        P("colors", "None", "None = rainbow. A preset name, a Gradient, or a sequence of colors.", 1, "None / preset / Gradient / colors"),
        P("amount", "1", "Density"),
        P("speed", "0.2", "Own drift"),
        P("hue_speed", "0.25", "Speed of the palette cycle", 0, "number"),
        P("saturation", "1", "Chroma (HSV and palette)", 0, "number"),
        P("reflect", "True", "True = back and forth along the ramp. False = wraps around (last → first).", 0, "bool"),
        P("alpha", "0.7", "Opacity"),
        P("res_scale", "0.6", "Internal resolution. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-nebuladust", kind: "ambient", family: "field", name: "Nebuladust",
      idea: "Dust like Stardust, with medium patches of the 3 colors (a nebula). Not Nebula (bands) or Chromadust (rainbow).",
      code: "Nebuladust()\nNebuladust(color=\"violet\", color2=\"teal\", color3=\"rose\")",
      search: "nebuladust nebula space dust patches colors",
      params: [
        P("color", "violet", "First region", 1),
        P("color2", "cyan", "Second region"),
        P("color3", "pink", "Third region", 0, "color"),
        P("amount", "1", "Density"),
        P("speed", "0.2", "Own drift"),
        P("alpha", "0.7", "Opacity"),
        P("res_scale", "0.6", "Internal resolution. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-borealis", kind: "ambient", family: "field", name: "Borealis",
      idea: "An aurora. <code>height</code> comes down from the top of the screen.",
      code: "Borealis()\nBorealis(height=0.55, color=\"cyan\")",
      search: "borealis aurora northern lights",
      params: [
        P("color", "green", "Aurora pigment", 1),
        P("amount", "1", "Intensity"),
        P("speed", "0.9", "Ripple"),
        P("height", "0.65", "Vertical reach from the top (0–1)"),
        P("alpha", "0.85", "Opacity"),
        ...fieldCam(0.1, 0.15, 0)
      ] },
    { id: "bg-plasma", kind: "ambient", family: "field", name: "Plasma",
      idea: "Patches of color that move slowly and cover the whole background.",
      code: "Plasma()\nPlasma(color=\"magenta\", pan_response=0.3)",
      search: "plasma",
      params: [
        P("color", "magenta", "Pigment", 1),
        P("amount", "1", "Energy"),
        P("speed", "0", "Time. 0 = still."),
        P("alpha", "0.55", "Opacity"),
        ...fieldCam(0.3, 0.4, 0)
      ] },
    { id: "bg-debris", kind: "ambient", family: "field", name: "Debris",
      idea: "Shreds / debris. A full-screen field, not SpatialFx particles.",
      code: "Debris()\nDebris(density=0.9, drift=0.6)",
      search: "debris shreds",
      params: [
        P("color", "gray", "Pigment", 1),
        P("density", "0.7", "Amount"),
        P("scale", "1", "Size of the pattern"),
        P("drift", "0.4", "Own drift"),
        P("alpha", "0.75", "Opacity"),
        ...fieldCam(0.35, 0.15, 0)
      ] },
    { id: "bg-embers", kind: "ambient", family: "field", name: "Embers",
      idea: "Rising embers. An ambient field; ≠ SpatialFx Fire.",
      code: "Embers()\nEmbers(color=\"orange\", density=0.9, rise=1.1)",
      search: "embers ash sparks",
      params: [
        P("color", "orange", "Pigment", 1),
        P("density", "1.1", "Amount"),
        P("rise", "0.8", "Rise"),
        P("alpha", "0.95", "Opacity"),
        ...fieldCam(0.4, 0.1, 0)
      ] },
    { id: "bg-wind", kind: "ambient", family: "field", name: "WindStreaks",
      idea: "Wind trails (a bright head + glow). <code>angle</code> in degrees; 0 = horizontal.",
      code: "WindStreaks()\nWindStreaks(angle=15, density=0.8, length=1.8)",
      search: "windstreaks wind streaks",
      params: [
        P("color", "light blue", "Pigment", 1),
        P("density", "0.65", "Amount"),
        P("length", "1.4", "Trail length"),
        P("angle", "0", "Degrees. 0 = horizontal."),
        P("speed", "1.3", "Speed"),
        P("glow", "0.9", "Halo"),
        P("alpha", "0.8", "Opacity"),
        ...fieldCam(0.85, 0.2, 0)
      ] },
    { id: "bg-ground", kind: "ambient", family: "field", name: "Ground",
      idea: "An orthographic strip of ground. Transparent above <code>horizon</code> (the horizon line). Line it up with SkyGradient. <code>horizon</code> / <code>fade</code> apply live.",
      code: "Ground(horizon=0.42)\nGround(color=\"olive\", horizon=0.42, detail=0.4)",
      search: "ground horizon",
      params: [
        P("color", "olive green", "Ground pigment (darkens toward the bottom)", 1),
        P("edge", "derived from color", "Horizon tint. Left out = a lighter version of color.", 0, "color"),
        P("horizon", "0.42", "Horizon line (0–1, y-up from the bottom). The same value as in SkyGradient."),
        P("fade", "0.003", "Blend at the horizon line. 0 = a sharp cut. The same parameter as in SkyGradient."),
        P("detail", "0", "Grain. 0 = flat fill."),
        P("line", "1", "Grain strength"),
        P("alpha", "1", "Opacity"),
        ...fieldCam(0.9, 0, 0)
      ] },
    { id: "bg-lattice", kind: "ambient", family: "field", name: "Lattice",
      idea: "A soft grid of cells. It is transparent between the lines, so you can lay it over other backgrounds.",
      code: "Lattice()\nLattice(fold=\"hex\", layers=3)\nLattice(fold=\"square\", edge=\"fill\", color=\"red\")",
      search: "lattice grid hex",
      variants: "fold, edge",
      params: [
        P("fold", "\"hex\"", "square · hex · tri", 1),
        P("edge", "\"outline\"", "outline · fill", 0, "str"),
        P("color", "aqua", "Pigment"),
        P("spacing", "1", "Step between cell centers"),
        P("size", "1", "Extent of the shape in its cell (max 1.7)"),
        P("line", "1", "Stroke thickness"),
        P("layers", "1", "1–3 overlaid grids; in hex, the extra ones sit on the vertices."),
        P("layer_scale", "1", "Size of the child layers (1–2)"),
        P("angle", "0", "Grid rotation, in degrees"),
        P("alpha", "0.55", "Opacity"),
        ...fieldCam(0.25, 0.35, 0)
      ] },
    { id: "bg-nebula", kind: "ambient", family: "field", name: "Nebula",
      idea: "Wide bands of dust. A cousin of Stardust, cheaper. Not Shield style=\"nebula\".",
      code: "Nebula()\nNebula(color=\"purple\", color2=\"navy\", contrast=1.2)",
      search: "nebula space bands",
      params: [
        P("color", "violet", "First pigment", 1),
        P("color2", "blue", "Second pigment"),
        P("scale", "1", "Size of the pattern"),
        P("contrast", "1", "Contrast of the bands"),
        P("speed", "0.15", "Own drift"),
        P("alpha", "0.55", "Opacity"),
        ...fieldCam(0.06, 0.08, 0)
      ] },
    { id: "bg-churn", kind: "ambient", family: "field", name: "ChurningClouds",
      idea: "Space clouds that churn and breathe in place.",
      code: "ChurningClouds()\nChurningClouds(alpha=0.65, speed=0.5, contrast=1.2)",
      search: "churningclouds clouds space swirl",
      params: [
        P("color", "blue", "First pigment", 1),
        P("color2", "pink", "Second pigment"),
        P("amount", "1", "Density"),
        P("speed", "0.4", "Pace of the swirl; 0 = still"),
        P("scale", "1", "Size of the pattern"),
        P("contrast", "1", "Contrast"),
        P("alpha", "0.6", "Opacity"),
        P("seed", "0", "Noise seed"),
        P("res_scale", "0.4", "Internal resolution. 1 = full."),
        ...fieldCam(0.06, 0.08, 0)
      ] },
    { id: "bg-filament", kind: "ambient", family: "field", name: "FilamentField",
      idea: "Filaments with a slow drift and occasional bursts.",
      code: "FilamentField()\nFilamentField(color=\"cyan\", alpha=0.45, contrast=1.3)",
      search: "filamentfield filaments",
      params: [
        P("color", "cyan", "Pigment", 1),
        P("amount", "1", "Density"),
        P("speed", "0.35", "Own drift"),
        P("contrast", "1", "Contrast of the filaments"),
        P("alpha", "0.55", "Opacity"),
        P("seed", "0", "Noise seed"),
        P("res_scale", "0.5", "Internal resolution. 1 = full."),
        ...fieldCam(0.18, 0.08, 0)
      ] },
    { id: "bg-floor", kind: "fly", family: "field", name: "Floor",
      idea: "An endless floor in perspective, like in old racing games: grid and checkerboard, fog at the horizon.",
      code: "canvas.set_fly(Floor())\ncanvas.set_fly(Floor(speed=1.2, grid=0.9, fog=0.4))",
      search: "floor mode7 perspective racing",
      params: [
        P("color", "green", "Floor pigment", 1),
        P("sky", "near black", "Color above the horizon"),
        P("amount", "1", "Contrast of the pattern"),
        P("speed", "1", "Own flight speed"),
        P("grid", "0.75", "Visibility of the grid"),
        P("fog", "0.55", "Fog at the horizon"),
        P("alpha", "1", "Opacity"),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-road", kind: "fly", family: "field", name: "Road",
      idea: "A road in perspective for a side-scrolling game: horizontal pan / scroll only. The horizon does not rise.",
      code: "canvas.set_fly(Road())\ncanvas.set_fly(Road(speed=1.4, pan_response=0.85))",
      search: "road perspective side-scroller",
      params: [
        P("color", "brown", "Road pigment", 1),
        P("sky", "night blue", "Color above the horizon"),
        P("amount", "1", "Contrast of the pattern"),
        P("speed", "1", "Own flight speed"),
        P("grid", "0.7", "Visibility of the grid"),
        P("fog", "0.5", "Fog at the horizon"),
        P("alpha", "1", "Opacity"),
        ...fieldCam(0.85, 0, 0)
      ] },
    { id: "bg-tunnel", kind: "fly", family: "field", name: "Tunnel",
      idea: "A full-screen tunnel of streaks. A vortex in the world: SpatialFx <code>Warp</code>. Prefer <code>canvas.set_fly(Tunnel())</code>.",
      code: "canvas.set_fly(Tunnel())\ncanvas.set_fly(Tunnel(speed=1.4, density=1.2, center=(200, 0)))",
      search: "tunnel streaks hyperspace",
      params: [
        P("color", "bluish white", "Streak pigment", 1),
        P("amount", "1", "Brightness"),
        P("speed", "1", "Flight. Prefer speed for immersion."),
        P("density", "1", "Number of streaks"),
        P("streak", "1", "Streak length"),
        P("alpha", "1", "Opacity"),
        P("center", "None", "Vanishing point, in design units. None = center of the screen."),
        ...fieldCam(0, 0, 0, FLY_PAN)
      ] },
    { id: "bg-starfly", kind: "fly", family: "field", name: "StarFly",
      idea: "Point stars flying at your face (screensaver). ≠ flat Stars, ≠ the streaks of Tunnel.",
      code: "canvas.set_fly(StarFly())\ncanvas.set_fly(StarFly(speed=1.5, density=1.2, center=(200, 0)))",
      search: "starfly stars screensaver",
      params: [
        P("color", "white", "Pigment", 1),
        P("amount", "1", "Brightness"),
        P("speed", "1", "Flight"),
        P("density", "1", "Amount"),
        P("alpha", "1", "Opacity"),
        P("center", "None", "Vanishing point, in design units. None = center of the screen."),
        ...fieldCam(0, 0, 0, FLY_PAN)
      ] },
    { id: "bg-planetfly", kind: "fly", family: "field", name: "PlanetFly",
      idea: "A flyover with a curved horizon. <code>roll=\"into\"</code> goes into the screen; <code>\"side\"</code> is a side-scroller.",
      code: "canvas.set_fly(PlanetFly())\ncanvas.set_fly(PlanetFly(roll=\"side\", speed=1.2, fog=0.35))",
      search: "planetfly planet flyover",
      params: [
        P("color", "earth green", "Ground pigment", 1),
        P("space", "near black", "Color of space above the horizon"),
        P("amount", "1", "Contrast of the relief"),
        P("bright", "1.15", "Visibility of the ground"),
        P("speed", "1", "Flight"),
        P("relief", "0.9", "Relief"),
        P("fog", "0.45", "Fog at the horizon"),
        P("size", "0.55", "Scale of the planet in the frame"),
        P("roll", "\"into\"", "into / forward = goes in; side / lateral = rolls R→L"),
        P("alpha", "1", "Opacity"),
        ...fieldCam(0, 0, 0)
      ] },
  ];

  const FILTERS = [
    { id: "filter-blur", kind: "filter", family: "filter", name: "Blur",
      idea: "Blurs the inside or the outline of the object (depending on whether it goes in <code>fill_filter</code> or <code>line_filter</code>).",
      code: "c.fill_filter = Blur()\nc.fill_filter = Blur(sigma=4)",
      search: "blur soften",
      params: [P("sigma", "4", "How much it blurs, in units (0 = sharp)", 1), P("sigmaX", "None", "Blur on the X axis only; None = sigma"), P("sigmaY", "None", "Blur on the Y axis only; None = sigma"), P("tile_mode", "\"decal\"", "Edge: decal · clamp · repeat · mirror"), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-glowfilter", kind: "filter", family: "filter", name: "GlowFilter",
      idea: "A halo of light around the inside or the outline. For many objects, create just one and use it on all of them (<code>halo = GlowFilter(); a.fill_filter = halo; b.fill_filter = halo</code>). An object's ordinary glow is the <code>.glow</code> add-on.",
      code: "c.fill_filter = GlowFilter(radius=10, sigma=5)",
      search: "glowfilter filter halo",
      params: [P("radius", "12", "How far the halo reaches, in units"), P("sigma", "10", "How blurred the halo is"), P("intensity", "1", "Strength of the glow"), P("color", "(1, 0.95, 0.65, 1)", "Color of the halo (default: light yellow)"), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-hostglow", kind: "filter", family: "filter", name: "HostGlow",
      idea: "A halo in each object's own color: the same filter on ships of different colors gives each one its own glow.",
      code: "c.fill_filter = HostGlow()\nc.fill_filter = HostGlow(sigma=4, spread=2)",
      search: "hostglow filter halo host",
      params: [P("sigma", "3.5", "How blurred the halo is", 1), P("spread", "0", "Thickens the halo before blurring it (units)", 2), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-emissive", kind: "filter", family: "filter", name: "EmissiveFilter",
      idea: "Makes the bright parts of the object glow and leak light around them (bloom), on the inside (<code>fill_filter</code>) or on the outline (<code>line_filter</code>). For a Sprite, the ready-made visual is <code>EmissiveBloom</code>.",
      code: "sprite.fill_filter = EmissiveFilter(intensity=1.4, sigma=10)",
      search: "emissivefilter bloom filter",
      params: [P("intensity", "1.35", "Strength", 1), P("sigma", "10", "Blur", 2), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-dropshadow", kind: "filter", family: "filter", name: "DropShadow",
      idea: "A shadow. y-up: by default it falls down and to the right. Add-on: <code>.shadow</code>.",
      code: "c.fill_filter = DropShadow(offset=12, sigma=8)",
      search: "dropshadow shadow filter",
      params: [P("offset", "(8, -8)", "A number or (dx, dy)"), P("sigma", "5", "Blur"), P("color", "(0, 0, 0, 0.55)", "Pigment"), P("dx", "None", "X offset; None = uses offset"), P("dy", "None", "Y offset (y up); None = uses offset"), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-dilate", kind: "filter", family: "filter", name: "Dilate",
      idea: "Expands the silhouette.",
      code: "c.fill_filter = Dilate(radius=3)",
      search: "dilate expand",
      params: [P("radius", "4", "Reach", 1), P("radiusX", "None", "Radius on the X axis only; None = radius"), P("radiusY", "None", "Radius on the Y axis only; None = radius"), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-erode", kind: "filter", family: "filter", name: "Erode",
      idea: "Shrinks the silhouette.",
      code: "c.fill_filter = Erode(radius=3)",
      search: "erode shrink",
      params: [P("radius", "2.5", "Reach", 1), P("radiusX", "None", "Radius on the X axis only; None = radius"), P("radiusY", "None", "Radius on the Y axis only; None = radius"), P("input", "None", "input filter (chains filters); None = the shape itself", 0, "filter")] },
    { id: "filter-compose", kind: "filter", family: "filter", name: "ComposeFx",
      idea: "Two filters, one around the other.",
      code: "c.fill_filter = ComposeFx(Blur(2), DropShadow())",
      search: "composefx compose combine",
      params: [P("outer", "—", "Outer filter", 1), P("inner", "—", "Inner filter", 2)] },
  ];

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inside an attribute value: also quotes (a variant's code is Halo(style="pulse")).
  function escAttr(s) {
    return esc(s).replace(/"/g, "&quot;");
  }

  function ordinal(n) {
    const teen = n % 100 >= 11 && n % 100 <= 13;
    return n + (teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
  }

  const FAMILY_LABEL = {
    visual: "look",
    spatial: "spatial",
    post: "post",
    impact: "impact",
    field: "material",
    filter: "filter",
    stamp: "add-on",
    life: "transient",
    knock: "transient",
    exit: "transient",
    enter: "transient",
    hit: "transient",
    pulse: "transient",
    pop: "transient",
    spark: "transient",
    cover: "cover",
  };

  function familyLabel(item) {
    return FAMILY_LABEL[item.family] || item.family || "";
  }

  const HOST_ORDER = ["Sprite", "Shape", "Text"];
  const HOST_ORDER_VISUAL = ["Shape", "Sprite"];

  function hostChips(item) {
    if (!item.hosts) return "";
    const set = new Set(item.hosts);
    const order = (item.family === "stamp" || set.has("Text"))
      ? HOST_ORDER
      : HOST_ORDER_VISUAL;
    const yes = order.filter((h) => set.has(h));
    const chips = order.map((h) => {
      const on = set.has(h);
      return `<span class="host ${on ? "yes" : "no"}">${esc(h)}</span>`;
    }).join("");
    const label = (order === HOST_ORDER_VISUAL && yes.length === 2)
      ? "Shape and Sprite"
      : (yes.join(", ") || "none");
    return `<span class="hosts" aria-label="Works on ${label}">${chips}</span>`;
  }

  function sigHint(params) {
    const hasPos = params.some((p) => p.pos);
    const hasKw = params.some((p) => !p.pos);
    if (hasPos && hasKw) {
      return "Name without <code>=</code>: 1st, 2nd… in order. Name with <code>=</code>: by name.";
    }
    if (hasPos) return "Name without <code>=</code>: 1st, 2nd… in order.";
    return "Name with <code>=</code>: pass it by name.";
  }

  function inferType(p) {
    if (p.typ) return p.typ;
    const n = p.name;
    const byName = {
      color: "color", to: "color", color2: "color", color3: "color", underlay: "color",
      top: "color", middle: "color", bottom: "color", sky: "color", space: "color",
      key: "color",
      live: "bool", only_int: "bool", show_value: "bool", centered: "bool",
      use_center: "bool", enabled: "bool", rings: "bool", border: "bool",
      into: "bool", reflect: "bool", flash: "bool",
      on_done: "() → None",
      at: "point / (() → point)",
      style: "str", preset: "str", kind: "str", fit: "str", tile_mode: "str",
      wrap: "str", family: "str", palette: "str", source: "str", label: "str",
      name: "str", axis: "str", fold: "str", roll: "str", filename: "str",
      colors: "sequence",
      center: "point", p1: "point", p2: "point", origin: "point", focus: "point",
      offset: "number / point", scroll: "point", target: "point",
      n: "int", points: "int", cols: "int", rows: "int", layers: "int",
      count: "int", segments: "int", spokes: "int",
      outer: "filter", inner: "filter", image: "Image",
    };
    if (byName[n]) return byName[n];
    if (/^(radius|sigma|amount|speed|width|height|length|intensity|duration|fps|scale|angle|min_value|max_value|density|rate|spread|glow|phase|soft_edge|x|y|x1|y1|x2|y2|pan_response|zoom_response|rotation_response|alpha|size|tile_size|opacity|fade|zoom|spin|fall|trail|horizon|twinkle|band|detail|drift|rise|spacing|layer_scale|line|contrast|grid|fog|streak|bright|relief|seed|res_scale|flicker|darken|gap|fill_scale|depth|range|soft|scale_end|distance|dx|dy|twist|core|hue_speed|saturation|thickness|cell|weight|decay|exposure|ambient|specular|brightness|bias)$/.test(n)) {
      return "number";
    }
    return "";
  }

  function identOk(name) {
    return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
  }

  function signatureLine(item) {
    item.params.forEach((p) => {
      if (!identOk(p.name)) {
        console.warn("Guide: invalid parameter name in " + item.name + ": " + p.name);
      }
      if (!inferType(p)) {
        console.warn("Guide: parameter without a type in " + item.name + "." + p.name);
      }
    });
    const inner = item.params.map((p) => p.pos ? p.name : p.name + "=").join(", ");
    return item.name + "(" + inner + ")";
  }

  // The Type column shows the type + the constructor's default. When the default
  // is not a plain literal (it depends on context: "follows the object", "the
  // fade_out's", …), the descriptive text stands in that same place.
  function typeCell(p) {
    const typ = inferType(p);
    const def = p.def && p.def !== "—" ? `<span class="ex">${esc(p.def)}</span>` : "";
    return `<td class="type"><span class="t">${esc(typ)}</span>${def}</td>`;
  }

  function paramRows(params) {
    return params.map((p) =>
      `<tr><td><code>${esc(p.name)}</code></td><td>${p.pos ? ordinal(p.pos) : "name="}</td>${typeCell(p)}<td>${p.meaning}</td></tr>`
    ).join("");
  }

  function renderPanel(item, active) {
    let details = "";
    if (item.params && item.params.length) {
      details = `<details class="spec" open><summary>Parameters</summary>
        <p class="sig"><code>${esc(signatureLine(item))}</code></p>
        <p class="sig-hint">${sigHint(item.params)}</p>
        <div class="tbl-wrap"><table>
        <thead><tr><th>Parameter</th><th>Pass</th><th>Type (default)</th><th>Meaning</th></tr></thead>
        <tbody>${paramRows(item.params)}</tbody></table></div></details>`;
    } else if (item.params) {
      details = `<details class="spec" open><summary>Parameters</summary>
        <p class="sig"><code>${esc(item.name)}()</code></p>
        <p class="sig-hint">No parameters.</p></details>`;
    }
    const on = active ? " active" : "";
    const fam = familyLabel(item);
    const hosts = hostChips(item);
    const chip = !hosts && fam ? `<span class="family">${esc(fam)}</span>` : "";
    const hostAttr = item.hosts && item.hosts.length
      ? ` data-hosts="${esc(item.hosts.join(" "))}"`
      : "";
    const text = `<p class="one-liner">${item.idea}</p>
      <div class="code-panel"><button class="copy-btn" type="button">copy</button><pre>${esc(item.code)}</pre></div>`;
    const th = thumbOf(item);
    const body = th
      ? `<div class="catalog-body"><div class="catalog-text">${text}</div>
        <figure class="thumb"><div class="thumb-frame">${thumbImg(item, th, "lazy")}${playButton(th)}</div>
        <figcaption class="thumb-code" hidden><code></code></figcaption></figure></div>${variantStrips(item, th)}`
      : text;
    return `<div class="tab-panel${on}" data-panel="${item.id}" id="${item.id}" data-kind="${item.kind}"${hostAttr}>
      <div class="catalog-meta">${chip}${hosts}</div>
      ${body}
      ${details}
    </div>`;
  }

  // ── Thumbnails (guia-api-thumbs.js, made by make_guia_thumbs.py) ──
  // A card with a picture shows it next to its code; a catalog with pictures
  // also gets a gallery view. No thumbs file → the text-only catalog of old.

  function thumbOf(item) {
    const all = w.ScenaGuideThumbs;
    return all && all[item.id] ? all[item.id] : null;
  }

  // ``small``: the gallery picture (reduced from the full render, so stars and
  // thin lights survive; the browser shrinking the 480 px poster erased them).
  function thumbImg(item, th, loading, small) {
    const anim = th.anim ? ` data-anim="${esc(th.anim)}"` : "";
    const src = small && th.card ? th.card : th.src;
    const tall = th.h > th.w ? " data-tall" : "";
    return `<img src="${esc(src)}" data-static="${esc(src)}"${anim}${tall} width="${th.w}" height="${th.h}" loading="${loading}" alt="Preview of ${esc(item.name)}">`;
  }

  function playButton(th) {
    return `<button class="thumb-play" type="button" aria-pressed="false" aria-label="Play"${th.anim ? "" : " hidden"}>▶</button>`;
  }

  // One strip per varied parameter: every value the code accepts, as pictures.
  function variantStrips(item, th) {
    if (!th.variants || !th.variants.length) return "";
    const byParam = {};
    th.variants.forEach((v) => { (byParam[v.param] = byParam[v.param] || []).push(v); });
    return Object.keys(byParam).map((param) => {
      const cards = byParam[param].map((v) => {
        const anim = v.anim ? ` data-anim="${esc(v.anim)}"` : "";
        return `<button class="v-card" type="button" aria-pressed="false" data-src="${escAttr(v.src)}" data-w="${v.w}" data-h="${v.h}"${anim} data-code="${escAttr(v.code)}" title="${escAttr(v.code)}">
          <img src="${escAttr(v.card || v.src)}" width="${v.w}" height="${v.h}" loading="lazy" alt="${escAttr(v.code)}"><span>${esc(v.value)}</span></button>`;
      }).join("");
      return `<div class="variants" role="group" aria-label="${esc(item.name)} ${esc(param)}=">
        <span class="v-param"><code>${esc(param)}=</code></span><div class="v-row">${cards}</div></div>`;
    }).join("");
  }

  function reducedMotion() {
    return !!(w.matchMedia && w.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // A loop plays when the reader asked for it (▶), or on its own where the
  // eye is, unless the system asks for reduced motion. The reader's ▶ / ❚❚
  // always wins: reduced motion stops autoplay, not a requested animation.
  function setPlaying(img, auto) {
    if (!img) return;
    const btn = img.parentElement && img.parentElement.querySelector(".thumb-play");
    if (!img.dataset.anim) {
      if (img.getAttribute("src") !== img.dataset.static) img.setAttribute("src", img.dataset.static);
      if (btn) btn.hidden = true;
      return;
    }
    const user = img.dataset.user;
    const on = user === "on" || (auto && user !== "off" && !reducedMotion());
    const want = on ? img.dataset.anim : img.dataset.static;
    if (img.getAttribute("src") !== want) img.setAttribute("src", want);
    if (btn) {
      btn.hidden = false;
      btn.setAttribute("aria-pressed", String(on));
      btn.setAttribute("aria-label", on ? "Pause" : "Play");
      btn.textContent = on ? "❚❚" : "▶";
    }
  }

  function panelActive(img) {
    const host = img.closest(".catalog-host");
    return (!host || host.dataset.view !== "gallery") && img.closest(".tab-panel").classList.contains("active");
  }

  function wirePanels(el) {
    el.querySelectorAll(":scope > .tabs > .tab-panel").forEach((panel) => {
      const img = panel.querySelector(".thumb-frame img");
      if (!img) return;
      const btn = panel.querySelector(".thumb-play");
      const cap = panel.querySelector(".thumb-code");
      const base = { src: img.dataset.static, anim: img.dataset.anim || "",
        w: img.getAttribute("width"), h: img.getAttribute("height") };
      btn.addEventListener("click", () => {
        img.dataset.user = img.getAttribute("src") === img.dataset.anim ? "off" : "on";
        setPlaying(img, panelActive(img));
      });
      panel.querySelectorAll(".v-card").forEach((card) => {
        card.addEventListener("click", () => {
          const again = card.getAttribute("aria-pressed") === "true";
          panel.querySelectorAll(".v-card").forEach((c) => c.setAttribute("aria-pressed", "false"));
          const pick = again ? base : { src: card.dataset.src, anim: card.dataset.anim || "",
            w: card.dataset.w, h: card.dataset.h };
          img.dataset.static = pick.src;
          img.setAttribute("width", pick.w);
          img.setAttribute("height", pick.h);
          if (Number(pick.h) > Number(pick.w)) img.dataset.tall = ""; else delete img.dataset.tall;
          if (pick.anim) img.dataset.anim = pick.anim; else delete img.dataset.anim;
          img.setAttribute("src", pick.src);
          if (!again) card.setAttribute("aria-pressed", "true");
          cap.hidden = again;
          cap.querySelector("code").textContent = again ? "" : card.dataset.code;
          setPlaying(img, panelActive(img));
        });
      });
    });
  }

  // Loops play only where the eye is: the visible active panel of each host.
  function playThumbs(scope) {
    const hosts = scope && scope.classList && scope.classList.contains("catalog-host")
      ? [scope]
      : [...(scope || document).querySelectorAll(".catalog-host")];
    hosts.forEach((host) => {
      const tabsView = host.dataset.view !== "gallery";
      host.querySelectorAll(":scope > .tabs > .tab-panel .thumb-frame img").forEach((img) => {
        setPlaying(img, tabsView && img.closest(".tab-panel").classList.contains("active"));
      });
    });
  }

  const VIEW_KEY = "guia.catalog-view.";

  function showView(host, view, remember) {
    if (!host || !host.querySelector(":scope > .gallery")) return;
    host.dataset.view = view;
    host.querySelectorAll(":scope > .view-toggle button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.view === view));
    });
    if (remember) {
      try { w.localStorage.setItem(VIEW_KEY + host.id, view); } catch (e) { /* storage off */ }
    }
    playThumbs(host);
  }

  function savedView(host) {
    try { return w.localStorage.getItem(VIEW_KEY + host.id); } catch (e) { return null; }
  }

  function galleryCard(item) {
    const th = thumbOf(item);
    const hosts = item.hosts && item.hosts.length
      ? ` data-hosts="${esc(item.hosts.join(" "))}"`
      : "";
    const pic = th ? thumbImg(item, th, "lazy", true) : `<span class="g-none">no preview</span>`;
    const moves = th && th.anim ? " data-moves" : "";
    return `<button class="g-card" type="button" data-goto="${item.id}" data-kind="${item.kind}"${hosts}${moves}>
      <span class="g-img">${pic}</span><span class="g-name">${esc(item.name)}</span></button>`;
  }

  function wireGallery(el) {
    el.querySelectorAll(":scope > .view-toggle button").forEach((b) => {
      b.addEventListener("click", () => showView(el, b.dataset.view, true));
    });
    el.querySelectorAll(":scope > .gallery .g-card").forEach((card) => {
      const img = card.querySelector("img");
      card.addEventListener("mouseenter", () => setPlaying(img, true));
      card.addEventListener("mouseleave", () => setPlaying(img, false));
      card.addEventListener("focus", () => setPlaying(img, true));
      card.addEventListener("blur", () => setPlaying(img, false));
      card.addEventListener("click", () => {
        setPlaying(img, false);
        // Reading one card is not choosing Abas: only the toggle is remembered,
        // or the next visit opens this catalog without its gallery.
        showView(el, "tabs", false);
        const tab = el.querySelector(`:scope > .tabs > .tab-bar > .tab[data-tab="${card.dataset.goto}"]`);
        if (tab) tab.click();
        // The gallery just collapsed: bring the toggle + tab bar + panel to the top.
        el.querySelector(":scope > .view-toggle").scrollIntoView({ block: "start" });
      });
    });
    // Runs after the page's own tab handler (bubbling): the new panel is active.
    el.addEventListener("click", (e) => {
      if (e.target.closest(".tab-bar > .tab")) playThumbs(el);
    });
  }

  function fill(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!items.length) {
      el.innerHTML = "";
      return;
    }
    const tabs = items.map((item, i) => {
      const on = i === 0 ? " active" : "";
      const hosts = item.hosts && item.hosts.length
        ? ` data-hosts="${esc(item.hosts.join(" "))}"`
        : "";
      return `<button class="tab${on}" type="button" data-tab="${item.id}" data-kind="${item.kind}"${hosts} data-search="${esc(item.search || "")}">${esc(item.name)}</button>`;
    }).join("");
    const panels = items.map((item, i) => renderPanel(item, i === 0)).join("");
    el.classList.add("catalog-host");
    const gallery = items.some(thumbOf)
      ? `<div class="view-toggle" role="group" aria-label="Show the catalog as">
          <button type="button" data-view="gallery">Gallery</button><button type="button" data-view="tabs">Tabs</button></div>
        <div class="gallery">${items.map(galleryCard).join("")}</div>`
      : "";
    el.innerHTML = `${gallery}<div class="tabs catalog" data-tabs>
      <div class="tab-bar catalog">${tabs}</div>
      ${panels}
    </div>`;
    wirePanels(el);
    if (gallery) {
      wireGallery(el);
      const saved = savedView(el);
      showView(el, saved === "tabs" || saved === "gallery" ? saved : "gallery", false);
    }
  }

  w.ScenaGuideCatalogs = {
    LOOKS, STAMPS, TRANSIENTS, SPATIAL, POST, IMPACTS, BACKGROUNDS, FILTERS, fill,
    playThumbs, showView,
  };
})(window);
