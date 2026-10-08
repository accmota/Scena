"""
Compiled-once SkSL RuntimeEffects for tunnel / immersive backdrops and the
placed SpatialFx shaders: Warp disc, Portal ring, Fire(style="blaze") (internal).

Ambient stack fields live in ``_sksl_ambient.py``.
Per frame only uniforms are updated. GPU destination required
(window canvas or MakeRenderTarget) — same rule as ``_sksl_effects``.
"""
from __future__ import annotations

import skia


def _compile_runtime(sksl: str, name: str) -> skia.RuntimeShaderBuilder:
    eff = skia.RuntimeEffect.MakeForShader(sksl)
    err = None
    if isinstance(eff, tuple):
        eff, err = eff
    if eff is None:
        raise RuntimeError(f"{name} SkSL failed to compile: {err}")
    return skia.RuntimeShaderBuilder(eff)


_WARP_SKSL = """
uniform float2 u_center;
uniform float u_radius;
uniform float time;
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_has_color2;
uniform float u_amount;
uniform float u_speed;
uniform float u_twist;
uniform float u_spokes;
uniform float u_core;
uniform float u_into;
uniform float u_spin;
uniform float u_soft;

half4 main(float2 coord) {
    float2 p = coord - u_center;
    float rad = max(u_radius, 1.0);
    float r = length(p) / rad;
    float se = max(u_soft, 0.02);
    if (r > 1.0 + se * 0.25) {
        return half4(0.0);
    }
    float ang = atan(p.y, p.x) + time * u_spin;
    float t = time * max(u_speed, 0.0) * u_into;
    // Radial streaks: spokes MUST be integer or color jumps across the atan cut.
    float spokes_n = u_spokes;
    float phase = spokes_n * ang - t * 3.5
                - log(max(r, 0.01)) * (6.0 + u_twist * 4.0);
    float rings = sin(1.0 / max(r + 0.08, 0.02) * 2.5 + t * 4.0);
    float spokes = pow(max(cos(phase) * 0.5 + 0.5, 0.0), 2.5);
    float flare = pow(max(1.0 - r * 0.85, 0.0), 1.8);
    float core = exp(-r * r * 8.0) * 0.9 * clamp(u_core, 0.0, 1.5);
    float amt = clamp(u_amount, 0.0, 2.0);
    float heat = clamp((spokes * 0.75 + rings * 0.2 + core) * flare * amt, 0.0, 1.0);
    half3 base = u_color;
    half3 derived = base * half3(0.05, 0.04, 0.12);
    half3 deep = mix(derived, u_color2, half(u_has_color2));
    half3 mid = base * half3(0.55, 0.5, 0.95);
    half3 hot = mix(base, half3(1.0, 0.98, 1.0), half(0.7));
    half3 col = mix(deep, mid, half(smoothstep(0.05, 0.45, heat)));
    col = mix(col, hot, half(smoothstep(0.4, 0.95, heat)));
    float wall = smoothstep(0.55, 1.15, r);
    col = mix(col, deep * half3(0.4, 0.4, 0.5), half(wall * 0.85));
    float rim = 1.0 - smoothstep(1.0 - se, 1.0, r);
    float a = clamp(rim * min(amt, 1.0), 0.0, 1.0);
    return half4(col * half(a), half(a));
}
"""

_FLOOR_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_sky;
uniform float u_amount;
uniform float u_speed;
uniform float u_grid;
uniform float u_fog;
uniform float u_alpha;

// Soft AA line along one cell axis; ``aw`` is half-width in cell space.
float grid_axis(float x, float aw) {
    float d = abs(fract(x) - 0.5);
    float half_w = max(aw, 0.015);
    return 1.0 - smoothstep(0.0, half_w, d);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    // Aspect-correct; FB y-down: negative y = top of screen = sky half
    float2 uv = p / max(resolution.y, 1.0);
    half3 sky_c = half3(u_sky);
    float a = clamp(u_alpha, 0.0, 1.0);
    // Soft sky / ground join (hard if() caused a 1px flicker band)
    float ground_w = smoothstep(-0.02, 0.03, uv.y);
    float grad = clamp(-uv.y * 0.85, 0.0, 1.0);
    half3 sky_col = mix(sky_c, sky_c * half3(0.4, 0.45, 0.7), half(grad));

    float y = max(uv.y, 1e-3);
    float t = time * u_speed;
    // Mode7 project; clamp far density so sampling never explodes at horizon
    float z = min(1.0 / y, 40.0);
    float2 ground = float2(uv.x * z, z + t * 2.0);
    float gden = mix(1.5, 5.5, clamp(u_grid, 0.0, 1.0));
    float2 gw = ground * gden;
    // Analytical AA: |d(gw)/d(pixel)| without fwidth (not in Scena SkSL)
    float pix = 1.0 / max(resolution.y, 1.0);
    float aw_x = (abs(z) + abs(uv.x) * z * z) * gden * pix * 1.15 + 0.012;
    float aw_y = (z * z) * gden * pix * 1.15 + 0.012;
    float fw_mag = aw_x + aw_y;
    // Soft checker (cosine — continuous under perspective, no step noise)
    float check = 0.5 + 0.5 * cos(gw.x * 3.14159265) * cos(gw.y * 3.14159265);
    float check_aa = mix(check, 0.5, smoothstep(0.08, 0.55, fw_mag));
    float lx = grid_axis(gw.x, aw_x);
    float ly = grid_axis(gw.y, aw_y);
    // Horizon fade on grid so lines dissolve before aliasing
    float horizon = smoothstep(0.0, 0.12, y);
    float grid = max(lx, ly) * horizon * (1.0 - smoothstep(0.25, 0.85, fw_mag));
    float fogA = clamp(u_fog, 0.0, 1.0);
    float fog = smoothstep(0.0, mix(0.12, 0.5, fogA), y);
    half3 base = half3(u_color);
    half3 deep = mix(sky_c * half3(0.5), base * half3(0.12, 0.1, 0.18), half(0.7));
    half3 pad = mix(base * half3(0.22, 0.2, 0.28), base * half3(0.55, 0.72, 0.52), half(check_aa));
    half3 lit = mix(pad, mix(base, half3(0.95, 1.0, 0.9), half(0.55)), half(grid * 0.85));
    half3 ground_col = mix(deep, lit, half(fog * u_amount));
    half3 col = mix(sky_col * half(u_amount), ground_col, half(ground_w));
    return half4(col * half(a), half(a));
}
"""

_STARTUNNEL_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_speed;
uniform float u_density;
uniform float u_streak;
uniform float u_alpha;

// Per-cell hash: weights (127, 311) / 1024 keep |sin arg| small (Intel GPU sin()
// collapses at |x| >= 2^17). See Effect System Design §9, "Noise hash".
float hash(float2 p) {
    return fract(sin(dot(p, float2(0.1240234375, 0.3037109375))) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = p / max(resolution.y, 1.0);
    float r = length(uv);
    float ang = atan(uv.y, uv.x);
    float t = time * u_speed;
    half3 col = half3(0.01, 0.015, 0.04);
    // Depth coordinate scrolls with time → fly into tunnel (expand outward)
    float z = fract(1.0 / max(r + 0.05, 0.02) * 0.35 + t * 0.55);
    float dens = clamp(u_density, 0.2, 2.5);
    // Integer ray bins so no atan branch-cut seam
    float rays = floor(12.0 + dens * 10.0);
    float ai = floor((ang / 6.2831853 + 0.5) * rays);
    float h = hash(float2(ai, floor(z * 20.0)));
    float streak = clamp(u_streak, 0.0, 2.0);
    if (h > 1.0 - 0.22 * dens) {
        float br = (h - (1.0 - 0.22 * dens)) / max(0.22 * dens, 1e-3);
        float core = exp(-pow((fract(z) - 0.5) * 6.0, 2.0));
        float radial = pow(max(1.0 - r * 0.55, 0.0), 1.2);
        float star = core * br * radial * (0.55 + streak * 0.7) * u_amount;
        // Streak along radial direction
        float along = exp(-abs(fract(z * 3.0 + t) - 0.5) * mix(8.0, 3.0, streak));
        star *= along;
        half3 sc = mix(half3(u_color), half3(1.0), half(0.45 * br));
        col = col + sc * half(star);
    }
    float wall = smoothstep(0.9, 1.6, r);
    col = mix(col, half3(0.0), half(wall * 0.7));
    float a = clamp(u_alpha, 0.0, 1.0);
    return half4(clamp(col, half3(0.0), half3(1.0)) * half(a), half(a));
}
"""

_ROAD_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_sky;
uniform float u_amount;
uniform float u_speed;
uniform float u_grid;
uniform float u_fog;
uniform float u_alpha;

float grid_axis(float x, float aw) {
    float d = abs(fract(x) - 0.5);
    float half_w = max(aw, 0.015);
    return 1.0 - smoothstep(0.0, half_w, d);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    // Horizontal-only: drop Y from camera/scroll offsets (pan_response set in Python).
    float2 p = coord - center - float2(u_offset.x, 0.0);
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = p / max(resolution.y, 1.0);
    half3 sky_c = half3(u_sky);
    float a = clamp(u_alpha, 0.0, 1.0);
    float ground_w = smoothstep(-0.02, 0.04, uv.y);
    float grad = clamp(-uv.y * 0.9, 0.0, 1.0);
    half3 sky_col = mix(sky_c, sky_c * half3(0.35, 0.4, 0.65), half(grad));

    float y = max(uv.y, 1e-3);
    float t = time * u_speed;
    // Mode7: world Z advances with time (drive forward), world X from UV (offset already in p)
    float z = min(1.0 / y, 40.0);
    float gden = mix(1.2, 5.0, clamp(u_grid, 0.0, 1.0));
    float2 gw = float2(uv.x * z, z + t * 1.8) * gden;
    float pix = 1.0 / max(resolution.y, 1.0);
    float aw_x = (abs(z) + abs(uv.x) * z * z) * gden * pix * 1.15 + 0.012;
    float aw_y = (z * z) * gden * pix * 1.15 + 0.012;
    float fw_mag = aw_x + aw_y;
    float check = 0.5 + 0.5 * cos(gw.x * 3.14159265) * cos(gw.y * 3.14159265);
    float check_aa = mix(check, 0.5, smoothstep(0.08, 0.5, fw_mag));
    float grid = max(grid_axis(gw.x, aw_x), grid_axis(gw.y, aw_y));
    float horizon = smoothstep(0.0, 0.1, y);
    grid *= horizon * (1.0 - smoothstep(0.22, 0.8, fw_mag));
    // Soft center road stripe
    float stripe = exp(-pow(uv.x * z * 0.55, 2.0) * 3.5) * horizon;
    float fogA = clamp(u_fog, 0.0, 1.0);
    float fog = smoothstep(0.0, mix(0.1, 0.48, fogA), y);
    half3 base = half3(u_color);
    half3 deep = mix(sky_c * half3(0.55), base * half3(0.15, 0.12, 0.18), half(0.7));
    half3 pad = mix(base * half3(0.18, 0.16, 0.22), base * half3(0.5, 0.55, 0.4), half(check_aa));
    half3 lit = mix(pad, mix(base, half3(1.0, 0.95, 0.7), half(0.5)), half(grid * 0.8));
    lit = mix(lit, half3(0.95, 0.9, 0.55), half(stripe * 0.35));
    half3 ground_col = mix(deep, lit, half(fog * u_amount));
    half3 col = mix(sky_col * half(u_amount), ground_col, half(ground_w));
    return half4(col * half(a), half(a));
}
"""

_STARFIELD_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_speed;
uniform float u_density;
uniform float u_alpha;

// Per-cell hash: weights (127, 311) / 1024 keep |sin arg| small (Intel GPU sin()
// collapses at |x| >= 2^17). See Effect System Design §9, "Noise hash".
float hash(float2 p) {
    return fract(sin(dot(p, float2(0.1240234375, 0.3037109375))) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = p / max(resolution.y, 1.0);
    float t = time * max(u_speed, 0.0);
    half3 col = half3(0.003, 0.005, 0.016);
    float dens = clamp(u_density, 0.15, 3.0);
    float thr = 1.0 - clamp(0.11 + 0.24 * dens, 0.09, 0.75);
    float cell = 9.0 + dens * 11.0;
    half3 u_col = half3(u_color);
    float amount = u_amount;

    for (int layer = 0; layer < 5; ++layer) {
        float li = float(layer);
        float zf = fract(t * 0.20 + li * 0.2);
        float life = min(zf * 14.3, (1.0 - zf) * 8.33);
        life = min(life, 1.0);
        float z = mix(1.7, 0.14, zf);
        float2 world = uv * z * cell;
        float2 id = floor(world) + float2(li * 31.0, li * 17.0);
        float2 f = fract(world) - 0.5;
        float h = hash(id);
        if (h > thr && life > 0.001) {
            float br = (h - thr) / max(1.0 - thr, 1e-3);
            float2 jp = float2(fract(h * 17.31), fract(h * 43.77)) - 0.5;
            jp *= 0.88;
            float2 d = f - jp;
            float d2 = d.x * d.x + d.y * d.y;
            float radius = mix(0.028, 0.055, zf * zf);
            float r2 = radius * radius;
            float pt = max(1.0 - d2 / max(r2, 1e-8), 0.0);
            pt = pt * pt;
            float near = 0.35 + 0.65 * zf;
            half brh = half(0.15 + 0.45 * br);
            half3 sc = mix(u_col, half3(1.0), brh);
            col = col + sc * half(pt * mix(0.45, 1.0, br) * near * life * amount);
        }
    }

    float a = clamp(u_alpha, 0.0, 1.0);
    return half4(clamp(col, half3(0.0), half3(1.0)) * half(a), half(a));
}
"""

# Portal: a torus of light, seen through a short volumetric march. Each sample
# is pushed around by sine octaves (domain turbulence) and glows by its inverse
# squared distance to the torus core. Time enters only as CPU-wrapped phases
# (u_ph0 / u_ph1, Effect System Design §9) — never a raw clock.
_PORTAL_SKSL = """
// Technique: sine-octave turbulence in a short raymarch
// (XorDev, mini.gmshaders.com/p/turbulence).
// The ring's place comes from the clean sample (a crisp circle); the
// turbulent copy only draws filaments and shifts the hue inside the glow.
uniform float2 u_center;
uniform float u_radius;
uniform float u_width;      // band thickness, ring units
uniform float u_chaos;
uniform float2 u_tilt;      // (cos, sin) of tilt
uniform float2 u_heading;   // (cos, sin) of the tilt-axis heading
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_amount;
uniform float u_glow;
uniform float u_reach;      // fade-out radius, ring units
uniform float u_soft;
uniform float4 u_ph0;       // octave phases 0..3
uniform float4 u_ph1;       // octave phase 4, spin phase, steps, octaves

half4 main(float2 coord) {
    float2 q = (coord - u_center) / max(u_radius, 1.0);
    float rq = length(q);
    if (rq > u_reach) {
        return half4(0.0);
    }
    q = float2(u_heading.x * q.x + u_heading.y * q.y,
               -u_heading.y * q.x + u_heading.x * q.y);
    float ct = max(u_tilt.x, 0.15);
    float st = u_tilt.y;
    float w = max(u_width, 0.02);
    float tube = w * 0.2;               // crisp core radius
    float fil = w * 0.06;               // filament line width
    float slab = (w * 0.6 + 0.08 * u_chaos) / ct;
    // Center the march on the tilted ring plane (ring-space z = 0).
    float z0 = -q.y * st / ct;
    float steps = u_ph1.z;
    float octs = u_ph1.w;
    float sp = u_ph1.y;
    float3 acc = float3(0.0);
    float hot = 0.0;
    // In-plane distance to the ring (clean geometry): the halo and the skip test.
    float rp = length(float2(q.x, q.y / ct));
    float dr = abs(rp - 1.0) * mix(ct, 1.0, 0.5);
    // Far from the band the filaments are invisible under the halo: skip the march.
    // Body light is exp(-9 d)-gone past ~0.3; strands wander <= ~0.1 * chaos.
    // The march fades to zero at the skip edge, so the cut never shows.
    float band = (w * 0.6 + 0.12 * u_chaos + 0.06) / ct;
    float edge = 1.0 - smoothstep(band * 0.55, band, abs(rp - 1.0));
    if (abs(rp - 1.0) > band) {
        steps = 0.0;
    }
    for (int i = 0; i < 6; ++i) {
        if (float(i) >= steps) {
            break;
        }
        float z = z0 + mix(-slab, slab, (float(i) + 0.5) / steps);
        // View sample -> ring space (tilt about the heading axis), then spin.
        float3 s = float3(q.x, q.y * ct - z * st, q.y * st + z * ct);
        s.xy = float2(cos(sp) * s.x - sin(sp) * s.y, sin(sp) * s.x + cos(sp) * s.y);
        float3 t = s;
        float f = 7.0;
        for (int k = 0; k < 5; ++k) {
            if (float(k) >= octs) {
                break;
            }
            float ph = k == 0 ? u_ph0.x : k == 1 ? u_ph0.y : k == 2 ? u_ph0.z
                     : k == 3 ? u_ph0.w : u_ph1.x;
            t += sin(t.zxy * f + ph) * (u_chaos * 0.36 / f);
            f *= 2.0;
        }
        // Clean distance places the light; turbulent distance draws strands.
        float d0 = length(float2(length(s.xy) - 1.0, s.z));
        float dt = length(float2(length(t.xy) - 1.0, t.z));
        // 1/d core, cut off well inside the skip radius (no step at the cutoff).
        float body = tube / (d0 + tube) * exp(-d0 * 9.0);
        float strand = fil * fil / (dt * dt + fil * fil);
        // Hue drifts along the strands between color2 and color.
        float hue = 0.5 + 0.5 * sin(t.x * 2.3 + t.y * 1.7 + t.z * 6.0 + s.x * 1.3 + s.y * 0.9);
        float3 tint = mix(float3(u_color), float3(u_color2), hue);
        acc += tint * body * (0.25 + 5.0 * strand);
        hot += body * strand;
    }
    acc *= edge / max(u_ph1.z, 1.0);
    hot *= edge;
    // Halo: 1/d falloff around the ring (long and soft), scaled by glow.
    float halo = u_glow * 0.04 / (dr + 0.04) * exp(-dr * 6.0);
    acc = acc * 6.0 + float3(u_color) * halo * 0.4;
    float fade = 1.0 - smoothstep(u_reach * (1.0 - u_soft), u_reach, rq);
    // Tone-map the peak channel and keep the hue (per-channel 1-exp washes
    // bright colors out to pastel).
    acc *= u_amount;
    float pk = max(acc.r, max(acc.g, acc.b));
    float3 col = acc * ((1.0 - exp(-pk * 1.6)) / max(pk, 1e-4));
    // White-hot strand cores ride on top.
    col = (col + float3(1.0 - exp(-hot * 3.2 / max(u_ph1.z, 1.0) * u_amount)) * 0.85) * fade;
    float a = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
    return half4(half3(col), half(a));
}
"""

# Fire(style="blaze"): a twisting, tapering hollow column of flame, marched in
# fire-local units (1 = half the fire's width; y = height above the hearth).
# Rendered into a reduced plate, then blitted along the fire's angle. Plate
# row 0 is the hearth. Time enters only as CPU-wrapped phases (§9).
_BLAZE_SKSL = """
// Technique: sine-octave turbulence in a short raymarch
// (XorDev, mini.gmshaders.com/p/turbulence).
uniform float2 u_plate;     // plate size in px actually used
uniform float4 u_box;       // fire units: xmin, xmax, ymin, ymax
uniform float u_height;     // flame height, fire units
uniform float4 u_rise;      // per-octave rise phases
uniform float4 u_swirl;     // per-octave swirl phases
uniform float4 u_misc;      // twist phase, steps, chaos, amount

half3 heat(float h) {
    half3 core = half3(1.0, 0.78, 0.38);
    half3 mid = half3(1.0, 0.42, 0.06);
    half3 top = half3(0.55, 0.07, 0.02);
    return h < 0.45 ? mix(core, mid, half(h / 0.45))
                    : mix(mid, top, half(clamp((h - 0.45) / 0.55, 0.0, 1.0)));
}

half4 main(float2 coord) {
    float2 uv = coord / u_plate;
    float2 p = float2(mix(u_box.x, u_box.y, uv.x), mix(u_box.z, u_box.w, uv.y));
    float H = max(u_height, 0.5);
    float steps = u_misc.y;
    float chaos = u_misc.z;
    float3 o = float3(p.x, p.y, 2.6);
    float3 dir = normalize(float3(p.x * 0.10, (p.y - H * 0.3) * 0.05, -1.0));
    float t = 0.0;
    float3 acc = float3(0.0);
    for (int i = 0; i < 50; ++i) {
        if (float(i) >= steps) {
            break;
        }
        float3 s = o + dir * t;
        float h = s.y / H;
        float a = s.y * 0.8 / H * 3.0 + u_misc.x;
        s.xz = float2(cos(a) * s.x - sin(a) * s.z, sin(a) * s.x + cos(a) * s.z);
        float3 q = s;
        float f = 1.6;
        for (int k = 0; k < 4; ++k) {
            float rise = k == 0 ? u_rise.x : k == 1 ? u_rise.y : k == 2 ? u_rise.z : u_rise.w;
            float sw = k == 0 ? u_swirl.x : k == 1 ? u_swirl.y : k == 2 ? u_swirl.z : u_swirl.w;
            q += cos(q.yzx * f - float3(rise, sw, 1.7 * float(k))) * (chaos * 0.6 / f);
            f *= 1.8;
        }
        float hq = clamp(q.y / H, 0.0, 1.0);
        float R = mix(0.9, 0.18, hq * hq) ;
        float d = abs(length(q.xz) - R);
        float step = 0.015 + d * 0.3;
        // Envelope: nothing below the hearth, fades toward the tip.
        float env = smoothstep(-0.5, 0.25, s.y) * (1.0 - smoothstep(0.7, 1.15, h));
        // Light hugs the shell: far samples add almost nothing (no plate haze).
        acc += float3(heat(clamp(h, 0.0, 1.0))) * env / (step * (1.0 + d * d * 110.0));
        t += step;
        if (t > 5.2) {
            break;
        }
    }
    acc *= u_misc.w * 0.9 / steps;
    // Peak-channel tone map keeps the flame's hue (per-channel 1-exp turns
    // the hot base pastel).
    float pk = max(acc.r, max(acc.g, acc.b));
    float3 col = acc * ((1.0 - exp(-pk * 0.13)) / max(pk, 1e-4));
    col += float3(1.0, 0.9, 0.7) * (1.0 - exp(-pk * 0.012)) * 0.35;
    float2 e = min(uv, 1.0 - uv);
    float fade = smoothstep(0.0, 0.08, e.x) * smoothstep(0.0, 0.06, 1.0 - uv.y);
    col *= fade;
    float al = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
    return half4(half3(col), half(al));
}
"""

_PLANETFLY_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_space;
uniform float u_amount;
uniform float u_speed;
uniform float u_relief;
uniform float u_fog;
uniform float u_size;
uniform float u_bright;
uniform float u_roll;   // 0 side, 1 into
uniform float u_alpha;

// Lattice hash: weights (127, 311) / 1024 are exact in float32, so n and the
// corner sums are exact and every pixel gets bit-identical corner hashes (no
// cell seams under FMA / reassociation), and |sin arg| stays < 2^14 (Intel
// GPU sin() collapses at |x| >= 2^17). See Effect System Design, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

float noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float n = dot(i, float2(0.1240234375, 0.3037109375));
    return mix(mix(hash1(n), hash1(n + 0.1240234375), u.x),
               mix(hash1(n + 0.3037109375), hash1(n + 0.427734375), u.x), u.y);
}

// 3 octaves (was 5) — planet ground
float fbm(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 3; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.07 + float2(13.0, 7.0);
        a *= 0.5;
    }
    return v;
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = p / max(resolution.y, 1.0);
    float t = time * u_speed;
    float a = clamp(u_alpha, 0.0, 1.0);
    float bright = max(u_bright, 0.05);

    float size = clamp(u_size, 0.15, 1.0);
    float R = mix(3.4, 2.0, size);
    float alt = mix(0.55, 0.12, size);
    float2 pc = float2(0.0, R + alt);
    float xx = clamp(uv.x, -R + 1e-3, R - 1e-3);
    float limb = pc.y - sqrt(max(R * R - xx * xx, 0.0));

    half3 space = half3(u_space);
    float2 sg = uv * 22.0;
    float2 sid = floor(sg);
    float sh = hash1(dot(sid, float2(0.1240234375, 0.3037109375)));
    float star = 0.0;
    if (sh > 0.97) {
        float2 f = fract(sg) - 0.5;
        star = (1.0 - smoothstep(0.0, 0.045, length(f))) * 0.7;
    }
    half3 col = space + half3(0.8, 0.88, 1.0) * half(star);

    float2 q = uv - pc;
    float dist = length(q);
    float on_body = step(dist, R) * step(limb, uv.y);
    if (on_body > 0.5) {
        float depth = max(uv.y - limb, 1e-3);
        float z = min(1.0 / depth, 30.0);
        float travel = t;
        float sx;
        float sy;
        // roll: 0 side-scroll along X; 1 Mode7 advance Z (into screen)
        if (u_roll > 0.5) {
            sx = uv.x * z * 0.55;
            sy = z + travel * 1.35;
        } else {
            sx = uv.x * z * 0.55 + travel * 0.85;
            sy = z * 0.35;
        }
        float rel = mix(0.35, 2.2, clamp(u_relief, 0.0, 1.5) / 1.5);
        float n1 = fbm(float2(sx, sy) * 0.55);
        // one FBM only (was 2–3); derivative shade dropped
        float terrain = 0.5 + (n1 - 0.5) * rel;
        float ridge = smoothstep(0.45, 0.78, terrain);
        float low = smoothstep(0.55, 0.25, terrain);
        half3 base = half3(u_color);
        half3 deep = base * half3(0.22, 0.20, 0.18);
        half3 mid = base * half3(0.65, 0.68, 0.52);
        half3 high = base * half3(0.88, 0.84, 0.68);
        half3 surf = mix(deep, mid, half(smoothstep(0.2, 0.55, terrain)));
        surf = mix(surf, high, half(ridge * 0.55));
        surf = mix(surf, deep * half3(0.7, 0.75, 0.85), half(low * 0.35));
        float shade = 0.58 + 0.48 * smoothstep(0.0, 0.6, depth);
        if (u_roll > 0.5) {
            float lane = 0.5 + 0.5 * cos(sx * 3.14159);
            float lane_aa = mix(lane, 0.5, smoothstep(8.0, 28.0, z));
            surf = mix(surf, surf * half3(1.08, 1.05, 0.95), half(lane_aa * 0.12));
        }
        surf = surf * half(shade * u_amount * bright);

        float fogA = clamp(u_fog, 0.0, 1.0);
        float near_h = exp(-depth * mix(1.2, 5.0, fogA));
        half3 haze = mix(space, base * half3(0.5, 0.6, 0.75) * half(bright), half(0.4));
        surf = mix(surf, haze, half(near_h * fogA));

        float edge = smoothstep(0.0, 0.02, depth);
        float rim = smoothstep(R, R - 0.04, dist);
        col = mix(col, surf, half(edge * rim));
    }

    float d_limb = abs(uv.y - limb);
    float band = exp(-d_limb * 45.0) * smoothstep(R + 0.05, R - 0.15, dist);
    half3 atmo = mix(half3(u_color) * half(bright), half3(0.55, 0.75, 1.0), half(0.5));
    col = col + atmo * half(band * 0.22 * u_amount * clamp(u_fog * 0.5 + 0.35, 0.0, 1.0));

    return half4(clamp(col, half3(0.0), half3(1.0)) * half(a), half(a));
}
"""


warp_builder = _compile_runtime(_WARP_SKSL, "spatial.Warp")
portal_builder = _compile_runtime(_PORTAL_SKSL, "spatial.Portal")
blaze_builder = _compile_runtime(_BLAZE_SKSL, "spatial.Fire(blaze)")
floor_builder = _compile_runtime(_FLOOR_SKSL, "backdrop.Floor")
startunnel_builder = _compile_runtime(_STARTUNNEL_SKSL, "backdrop.Tunnel")
road_builder = _compile_runtime(_ROAD_SKSL, "backdrop.Road")
starfield_builder = _compile_runtime(_STARFIELD_SKSL, "backdrop.StarFly")
planetfly_builder = _compile_runtime(_PLANETFLY_SKSL, "backdrop.PlanetFly")


def draw_shader_rect(canvas, w: float, h: float, builder: skia.RuntimeShaderBuilder) -> None:
    paint = skia.Paint(Shader=builder.makeShader(), AntiAlias=False)
    paint.setBlendMode(skia.BlendMode.kSrcOver)
    canvas.drawRect(skia.Rect.MakeWH(float(w), float(h)), paint)


__all__ = [
    "_compile_runtime",
    "draw_shader_rect",
    "warp_builder",
    "portal_builder",
    "blaze_builder",
    "floor_builder",
    "startunnel_builder",
    "road_builder",
    "starfield_builder",
    "planetfly_builder",
]
