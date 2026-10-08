"""
Compiled-once SkSL for ambient background stack fields (internal).

Alpha-from-feature washes for composition via ``canvas.background``.
Tunnel / immersive fields stay in ``_sksl_backdrop.py``.
"""
from __future__ import annotations

from ._sksl_backdrop import _compile_runtime, draw_shader_rect  # noqa: F401

# ---------------------------------------------------------------------------
# Clouds
# ---------------------------------------------------------------------------
_CLOUDS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_band;
uniform float u_spread;
uniform float u_detail;
uniform float u_speed;
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
// Each octave turns its domain by ~37° (rotation (0.8, 0.6)): value noise
// has ridges along its lattice axes, and four octaves on the same axes add
// them up; smoothstep() then cut a straight cloud edge and a square hole.
// floor() of a rotated point is still an integer cell: the hash stays exact.
float fbm(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.02 + float2(17.0, 9.0);
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
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float v = clamp(uv.y, 0.0, 1.0);
    float center_v = 1.0 - clamp(u_band, 0.0, 1.0);
    float half_w = mix(0.12, 0.55, clamp(u_spread, 0.0, 1.0));
    float band = 1.0 - smoothstep(half_w * 0.45, half_w, abs(v - center_v));
    float det = max(u_detail, 0.15);
    float t = time * u_speed;
    float2 cuv = uv * float2(3.5, 2.2) * det + float2(t * 0.02, 0.0);
    float n = fbm(cuv * 2.5 + float2(t * 0.015, 0.1));
    float cloud = smoothstep(0.42, 0.72, n) * band * max(u_amount, 0.0);
    half3 cloud_c = mix(u_color * half3(0.92, 0.94, 0.98),
                        mix(u_color, half3(1.0, 1.0, 1.0), half(0.55)), half(n));
    float af = clamp(cloud * clamp(u_alpha, 0.0, 1.0), 0.0, 0.85);
    return half4(cloud_c * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# Stars
# ---------------------------------------------------------------------------
_STARS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_density;
uniform float u_twinkle;
uniform float u_alpha;

// Per-cell hash: n = dot(cell, (127, 311) / 1024) is exact and small (Intel GPU
// sin() collapses at |x| >= 2^17); salts are whole numbers so n + k stays exact
// under any reassociation. See Effect System Design §9, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);

    float dens = clamp(u_density, 0.05, 2.0);
    float cell = mix(28.0, 70.0, dens * 0.5);
    float2 g = p / max(min(resolution.x, resolution.y), 1.0) * cell;
    float2 id = floor(g);
    float2 f = fract(g) - 0.5;
    float cn = dot(id, float2(0.1240234375, 0.3037109375));
    float h = hash1(cn);
    float h2 = hash1(cn + 3.0);
    float thresh = 1.0 - 0.12 * dens;
    float star = 0.0;
    half3 sc = half3(u_color);
    if (h > thresh) {
        float2 offs = float2(h2, hash1(cn + 6.0)) - 0.5;
        float2 d = f - offs * 0.55;
        float br = (h - thresh) / max(1.0 - thresh, 1e-4);
        float soft = exp(-dot(d, d) * mix(180.0, 420.0, br));
        float hard = smoothstep(0.06, 0.01, length(d));
        float tw = 1.0;
        if (u_twinkle > 0.001) {
            tw = 0.55 + 0.45 * sin(time * (2.0 + h2 * 4.0) + h * 12.0);
            tw = mix(1.0, tw, clamp(u_twinkle, 0.0, 1.0));
        }
        star = (soft * 0.85 + hard * 0.55) * br * tw * u_amount;
        sc = mix(half3(u_color), half3(1.0, 0.98, 1.0), half(0.55 + 0.45 * br));
    }
    float af = clamp(star * clamp(u_alpha, 0.0, 1.0), 0.0, 1.0);
    return half4(sc * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# Stardust
# ---------------------------------------------------------------------------
_STARDUST_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_amount;
uniform float u_speed;
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
float fbm(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
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
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n1 = fbm(q * 2.2 + wobble);
    float n2 = fbm(q * 3.5 + n1 * float2(0.45, 0.35) + wobble * 1.2);
    float dust = smoothstep(0.35, 0.78, n1 * 0.55 + n2 * 0.55) * u_amount;
    half3 col = mix(half3(u_color), half3(u_color2), half(n2));
    col = mix(col * half3(0.25, 0.2, 0.35), col, half(dust));
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Stardust survival — single 4-octave FBM on a low-res plate (FxQuality.LOW)
# ---------------------------------------------------------------------------
_STARDUST_SURVIVAL_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_amount;
uniform float u_speed;
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
float fbm4(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
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
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n = fbm4(q * 2.2 + wobble);
    float dust = smoothstep(0.35, 0.78, n) * u_amount;
    half3 col = mix(half3(u_color), half3(u_color2), half(n));
    col = mix(col * half3(0.25, 0.2, 0.35), col, half(dust));
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Shared HSV→RGB (Chromadust rainbow path)
# ---------------------------------------------------------------------------
_HSV2RGB_SKSL = """
half3 hsv2rgb(float h, float s, float v) {
    float3 k = float3(1.0, 2.0 / 3.0, 1.0 / 3.0);
    float3 p = abs(fract(float3(h, h, h) + k) * 6.0 - 3.0);
    return half3(v * mix(float3(1.0), clamp(p - 1.0, 0.0, 1.0), s));
}
float pal_coord(float x, float ping) {
    float u = fract(x);
    if (ping > 0.5) {
        return 1.0 - abs(u * 2.0 - 1.0);
    }
    return u;
}
half3 palette5(float u, half3 c0, half3 c1, half3 c2, half3 c3, half3 c4) {
    float x = clamp(u, 0.0, 0.9999) * 4.0;
    float i = floor(x);
    float f = fract(x);
    half3 a = c0;
    half3 b = c1;
    if (i < 0.5) { a = c0; b = c1; }
    else if (i < 1.5) { a = c1; b = c2; }
    else if (i < 2.5) { a = c2; b = c3; }
    else { a = c3; b = c4; }
    return mix(a, b, half(f));
}
"""

# ---------------------------------------------------------------------------
# Chromadust — Stardust FBM, hue rotates through rainbow or a 5-stop palette
# ---------------------------------------------------------------------------
_CHROMADUST_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform float u_amount;
uniform float u_speed;
uniform float u_alpha;
uniform float u_hue_speed;
uniform float u_saturation;
uniform float u_mode;
uniform float u_reflect;
uniform half3 u_c0;
uniform half3 u_c1;
uniform half3 u_c2;
uniform half3 u_c3;
uniform half3 u_c4;

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
float fbm(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
        a *= 0.5;
    }
    return v;
}
""" + _HSV2RGB_SKSL + """
half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n1 = fbm(q * 2.2 + wobble);
    float n2 = fbm(q * 3.5 + n1 * float2(0.45, 0.35) + wobble * 1.2);
    float dust = smoothstep(0.35, 0.78, n1 * 0.55 + n2 * 0.55) * u_amount;
    float u = pal_coord(n1 * 7.0 + n2 * 13.0 + time * u_hue_speed, u_reflect);
    half3 col;
    if (u_mode < 0.5) {
        col = hsv2rgb(u, clamp(u_saturation, 0.0, 1.0), 1.0);
    } else {
        col = palette5(u, u_c0, u_c1, u_c2, u_c3, u_c4);
        float sat = clamp(u_saturation, 0.0, 1.0);
        half lum = half(dot(float3(col), float3(0.299, 0.587, 0.114)));
        col = mix(half3(lum, lum, lum), col, half(sat));
    }
    col = mix(col * half3(0.25, 0.2, 0.35), col, half(dust));
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Chromadust survival — 4-octave FBM
# ---------------------------------------------------------------------------
_CHROMADUST_SURVIVAL_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform float u_amount;
uniform float u_speed;
uniform float u_alpha;
uniform float u_hue_speed;
uniform float u_saturation;
uniform float u_mode;
uniform float u_reflect;
uniform half3 u_c0;
uniform half3 u_c1;
uniform half3 u_c2;
uniform half3 u_c3;
uniform half3 u_c4;

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
float fbm4(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
        a *= 0.5;
    }
    return v;
}
""" + _HSV2RGB_SKSL + """
half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n = fbm4(q * 2.2 + wobble);
    float n2 = fbm4(q * 3.1 + n * float2(0.4, 0.3));
    float dust = smoothstep(0.35, 0.78, n) * u_amount;
    float u = pal_coord(n * 7.0 + n2 * 13.0 + time * u_hue_speed, u_reflect);
    half3 col;
    if (u_mode < 0.5) {
        col = hsv2rgb(u, clamp(u_saturation, 0.0, 1.0), 1.0);
    } else {
        col = palette5(u, u_c0, u_c1, u_c2, u_c3, u_c4);
        float sat = clamp(u_saturation, 0.0, 1.0);
        half lum = half(dot(float3(col), float3(0.299, 0.587, 0.114)));
        col = mix(half3(lum, lum, lum), col, half(sat));
    }
    col = mix(col * half3(0.25, 0.2, 0.35), col, half(dust));
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Nebuladust — Stardust density + 3 medium-scale colour fields (cheap)
# Dust matches Stardust (2× 5-octave FBM). Colour is 3× 2-octave; warp is
# 2× value-noise. Same softmax mix as the full-FBM look, ~half the noise taps.
# ---------------------------------------------------------------------------
_NEBULADUST_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform half3 u_color3;
uniform float u_amount;
uniform float u_speed;
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
float fbm(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
        a *= 0.5;
    }
    return v;
}
float fbm2(float2 p) {
    float2 q = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
    return 0.65 * noise(p) + 0.35 * noise(q * 2.05 + float2(11.0, 19.0));
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n1 = fbm(q * 2.2 + wobble);
    float n2 = fbm(q * 3.5 + n1 * float2(0.45, 0.35) + wobble * 1.2);
    float dust = smoothstep(0.35, 0.78, n1 * 0.55 + n2 * 0.55) * u_amount;
    float2 wq = q + 0.32 * float2(
        noise(q * 1.45 + wobble * 0.3) - 0.5,
        noise(q * 1.45 + float2(4.2, 1.8) - wobble * 0.22) - 0.5
    );
    float ba = fbm2(wq * 3.15 + wobble * 0.2);
    float bb = fbm2(wq * 2.95 + float2(7.9, 3.4) - wobble * 0.16);
    float bc = fbm2(wq * 3.35 + float2(2.6, 9.1) + float2(wobble.y, -wobble.x) * 0.14);
    float mx = max(ba, max(bb, bc));
    float k = 6.4;
    float e0 = exp((ba - mx) * k);
    float e1 = exp((bb - mx) * k);
    float e2 = exp((bc - mx) * k);
    float es = e0 + e1 + e2 + 0.0001;
    half3 col = (half3(u_color) * half(e0)
               + half3(u_color2) * half(e1)
               + half3(u_color3) * half(e2)) / half(es);
    col *= half(0.38 + 0.62 * dust);
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Nebuladust survival — Stardust 4-octave dust + 1-octave colour fields
# ---------------------------------------------------------------------------
_NEBULADUST_SURVIVAL_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform half3 u_color3;
uniform float u_amount;
uniform float u_speed;
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
float fbm4(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.05 + float2(11.0, 19.0);
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
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float2 q = (uv - 0.5) * float2(1.6, 1.0);
    float2 wobble = 0.06 * float2(sin(t * 0.35), cos(t * 0.28));
    float n = fbm4(q * 2.2 + wobble);
    float dust = smoothstep(0.35, 0.78, n) * u_amount;
    float2 wq = q + 0.32 * float2(
        noise(q * 1.45 + wobble * 0.3) - 0.5,
        noise(q * 1.45 + float2(4.2, 1.8) - wobble * 0.22) - 0.5
    );
    float ba = noise(wq * 3.15 + wobble * 0.2);
    float bb = noise(wq * 2.95 + float2(7.9, 3.4) - wobble * 0.16);
    float bc = noise(wq * 3.35 + float2(2.6, 9.1) + float2(wobble.y, -wobble.x) * 0.14);
    float mx = max(ba, max(bb, bc));
    float k = 6.4;
    float e0 = exp((ba - mx) * k);
    float e1 = exp((bb - mx) * k);
    float e2 = exp((bc - mx) * k);
    float es = e0 + e1 + e2 + 0.0001;
    half3 col = (half3(u_color) * half(e0)
               + half3(u_color2) * half(e1)
               + half3(u_color3) * half(e2)) / half(es);
    col *= half(0.38 + 0.62 * dust);
    float a = clamp(dust * u_alpha * 0.95, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Borealis — u_height controls vertical reach from top
# ---------------------------------------------------------------------------
_BOREALIS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_speed;
uniform float u_height;
uniform float u_alpha;

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed * 0.85;
    float x = uv.x + 0.08 * sin(uv.y * 6.0 + t * 1.4);
    float ribbon = 0.0;
    ribbon += 0.55 * pow(max(sin(x * 9.0 + t * 1.6), 0.0), 3.0);
    ribbon += 0.40 * pow(max(sin(x * 15.0 - t * 2.1 + 1.2), 0.0), 4.0);
    ribbon += 0.30 * pow(max(sin((x + uv.y * 0.3) * 18.0 + t * 2.8), 0.0), 5.0);
    float reach = mix(0.25, 1.15, clamp(u_height, 0.0, 1.0));
    float top_weight = 1.0 - smoothstep(0.0, reach, uv.y);
    float baseV = 0.18 + 0.30 * (0.5 + 0.5 * sin(uv.y * 4.0 - t));
    float heat = clamp((ribbon * 0.9 + baseV * 0.5) * u_amount * top_weight, 0.0, 1.0);
    half3 base = u_color;
    half3 deep = base * half3(0.15, 0.28, 0.22);
    half3 bright = mix(base, half3(0.9, 1.0, 0.95), half(0.45));
    half3 col = mix(deep, base, half(smoothstep(0.08, 0.5, heat)));
    col = mix(col, bright, half(smoothstep(0.4, 0.95, heat)));
    float a = clamp((0.15 + heat * 0.85) * u_alpha, 0.0, 0.95);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Plasma
# ---------------------------------------------------------------------------
_PLASMA_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_speed;
uniform float u_alpha;

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float x = uv.x * 6.2831853;
    float y = uv.y * 6.2831853;
    float v = 0.0;
    v += sin(x + t);
    v += sin(y * 1.3 - t * 0.9);
    v += sin((x + y) * 0.7 + t * 1.3);
    v += sin(sqrt(x * x + y * y) * 1.8 - t * 0.7);
    v = v * 0.25 + 0.5;
    float heat = clamp(v * u_amount, 0.0, 1.0);
    half3 base = u_color;
    half3 deep = base * half3(0.12, 0.08, 0.22);
    half3 mid = base * half3(0.55, 0.45, 0.85);
    half3 hot = mix(base, half3(1.0, 0.95, 1.0), half(0.55));
    half3 col = mix(deep, mid, half(smoothstep(0.15, 0.55, heat)));
    col = mix(col, hot, half(smoothstep(0.5, 0.95, heat)));
    float a = clamp(u_alpha * (0.35 + 0.65 * heat), 0.0, 1.0);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Mist
# ---------------------------------------------------------------------------
_MIST_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_band;
uniform float u_spread;
uniform float u_amount;
uniform float u_speed;
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

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float center_v = 1.0 - clamp(u_band, 0.0, 1.0);
    float half_w = mix(0.08, 0.5, clamp(u_spread, 0.0, 1.0));
    float band = 1.0 - smoothstep(half_w * 0.35, half_w, abs(uv.y - center_v));
    float n = noise(uv * float2(3.0, 1.2) + float2(time * u_speed * 0.03, 0.0));
    float dens = band * (0.55 + 0.45 * n) * max(u_amount, 0.0);
    float af = clamp(dens * clamp(u_alpha, 0.0, 1.0), 0.0, 0.85);
    return half4(u_color * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# Debris — scrap flecks (shards)
# ---------------------------------------------------------------------------
_DEBRIS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_density;
uniform float u_scale_pat;
uniform float u_drift;
uniform float u_alpha;

// Per-cell hash: n = dot(cell, (127, 311) / 1024) is exact and small (Intel GPU
// sin() collapses at |x| >= 2^17); salts are whole numbers so n + k stays exact
// under any reassociation. See Effect System Design §9, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float dens = clamp(u_density, 0.05, 2.5);
    float cell = mix(12.0, 36.0, clamp(u_scale_pat, 0.2, 2.0) * 0.5);
    float2 drift = float2(u_drift, u_drift * 0.35) * time * 0.15;
    float2 g = p / min_res * cell + drift * cell;
    float2 id = floor(g);
    float2 f = fract(g) - 0.5;
    float cn = dot(id, float2(0.1240234375, 0.3037109375));
    float h = hash1(cn);
    float scrap = 0.0;
    half3 sc = half3(u_color);
    if (h > 1.0 - 0.14 * dens) {
        float2 offs = float2(hash1(cn + 3.0), hash1(cn + 6.0)) - 0.5;
        float2 d = f - offs * 0.45;
        float ang = hash1(cn + 9.0) * 6.2831853;
        float ca = cos(ang);
        float sa = sin(ang);
        float2 q = float2(ca * d.x - sa * d.y, sa * d.x + ca * d.y);
        float shard = max(abs(q.x) * 2.2 + abs(q.y) * 0.9, abs(q.y) * 1.8);
        scrap = (1.0 - smoothstep(0.08, 0.22, shard)) * (0.4 + 0.6 * h);
        sc = mix(u_color * half3(0.55, 0.55, 0.6), u_color, half(h));
    }
    float af = clamp(scrap * clamp(u_alpha, 0.0, 1.0), 0.0, 0.95);
    return half4(sc * half(af), half(af));
}
"""


# ---------------------------------------------------------------------------
# Embers — rising ash (irregular placement; UV scroll so motion wraps)
# ---------------------------------------------------------------------------
_EMBERS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_density;
uniform float u_rise;
uniform float u_alpha;

// Per-cell hash: n = dot(cell, (127, 311) / 1024) is exact and small (Intel GPU
// sin() collapses at |x| >= 2^17); salts are whole numbers so n + k stays exact
// under any reassociation. See Effect System Design §9, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float dens = clamp(u_density, 0.05, 2.5);
    float cell = mix(14.0, 38.0, dens * 0.5);
    float rise = max(u_rise, 0.05);
    // Scroll sample space so ash rises (+scroll.y → content moves up on screen).
    float2 base = p / min_res * cell + float2(0.0, rise) * time * 0.35 * cell;
    float ember = 0.0;
    half3 sc = half3(u_color);
    float thresh = 1.0 - 0.14 * dens;

    for (int j = -1; j <= 1; ++j) {
        for (int i = -1; i <= 1; ++i) {
            float2 gid = floor(base) + float2(float(i), float(j));
            float cn = dot(gid, float2(0.1240234375, 0.3037109375));
            float h = hash1(cn);
            if (h <= thresh) { continue; }
            float spd = 0.5 + 1.0 * hash1(cn + 3.0);
            float wob = (hash1(cn + 6.0) - 0.5) * 0.7;
            float2 offs = float2(hash1(cn + 9.0), hash1(cn + 12.0)) - 0.5;
            offs = offs * 0.95 + (float2(hash1(cn + 15.0), hash1(cn + 18.0)) - 0.5) * 0.4;
            // Stable lattice centre; light sway only (no time term on both sides).
            float2 center_pt = gid + 0.5 + offs + float2(wob * 0.25 * sin(time * spd + h * 9.0), 0.0);
            float2 d = base - center_pt;
            float br = (h - thresh) / max(1.0 - thresh, 1e-3);
            float sz = mix(45.0, 170.0, br * (0.4 + 0.6 * hash1(cn + 21.0)));
            float dd = dot(d, d);
            // Hot core + soft halo: a 1–2 px core alone vanished on a dark sky.
            float e = exp(-dd * sz) + 0.35 * exp(-dd * sz * 0.12);
            float pulse = 0.7 + 0.3 * sin(time * (2.2 + h * 6.5) + h * 14.0);
            e *= pulse * (0.6 + 0.4 * br);
            if (e > ember) {
                ember = e;
                // Dim embers glow the ember color (once a near-black red).
                sc = mix(u_color * half3(0.85, 0.6, 0.45),
                         mix(u_color, half3(1.0, 0.85, 0.4), half(0.6)), half(br));
            }
        }
    }
    float af = clamp(ember * clamp(u_alpha, 0.0, 1.0), 0.0, 0.95);
    return half4(sc * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# WindStreaks — head-bright motion trails; irregular placement; u_angle radians
# ---------------------------------------------------------------------------
_WINDSTREAKS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_density;
uniform float u_length;
uniform float u_angle;
uniform float u_speed;
uniform float u_glow;
uniform float u_alpha;

// Per-cell hash: n = dot(cell, (127, 311) / 1024) is exact and small (Intel GPU
// sin() collapses at |x| >= 2^17); salts are whole numbers so n + k stays exact
// under any reassociation. See Effect System Design §9, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float dens = clamp(u_density, 0.05, 2.5);
    float cell = mix(5.5, 16.0, dens * 0.5);
    float streak = 0.0;
    half3 sc = half3(u_color);
    float thresh = 1.0 - 0.11 * dens;
    float ca0 = cos(u_angle);
    float sa0 = sin(u_angle);
    // Rotate into streak frame, then scroll along +X so trails wrap.
    float2 q = float2(ca0 * p.x - sa0 * p.y, sa0 * p.x + ca0 * p.y);
    float2 base = q / min_res * cell + float2(max(u_speed, 0.05), 0.0) * time * 0.6 * cell;

    for (int j = -1; j <= 1; ++j) {
        for (int i = -1; i <= 1; ++i) {
            float2 gid = floor(base) + float2(float(i), float(j));
            float cn = dot(gid, float2(0.1240234375, 0.3037109375));
            float h = hash1(cn);
            if (h <= thresh) { continue; }

            float2 offs = float2(hash1(cn + 3.0), hash1(cn + 6.0)) - 0.5;
            offs = float2(offs.x * 0.9, offs.y * 0.95);
            offs += (float2(hash1(cn + 9.0), hash1(cn + 12.0)) - 0.5) * 0.45;
            float2 center_pt = gid + 0.5 + offs;
            float2 d = base - center_pt;

            float len = mix(2.0, 9.0, clamp(u_length, 0.2, 2.0) * 0.5);
            len *= 0.5 + 1.0 * hash1(cn + 15.0);
            float head = clamp(d.x / max(len * 0.1, 0.01) + 0.5, 0.0, 1.0);
            float trail = pow(1.0 - smoothstep(-len * 0.1, len * 0.08, d.x), 1.6);
            float core = (1.0 - smoothstep(0.0, 0.014, abs(d.y))) * trail;
            float bloom = exp(-abs(d.y) * 18.0) * trail * 0.4 * clamp(u_glow, 0.0, 2.0);
            float sval = (core * (0.45 + 0.55 * head) + bloom) * (0.45 + 0.55 * h);
            if (sval > streak) {
                streak = sval;
                sc = mix(u_color * half3(0.6, 0.7, 0.9), half3(1.0, 0.98, 1.0), half(head * core));
            }
        }
    }
    float af = clamp(streak * clamp(u_alpha, 0.0, 1.0), 0.0, 0.95);
    return half4(sc * half(af), half(af));
}
"""


# ---------------------------------------------------------------------------
# Ground — orthographic strip (scene base for author art)
# ---------------------------------------------------------------------------
_GROUND_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_edge;
uniform float u_horizon;
uniform float u_fade;
uniform float u_detail;
uniform float u_line;
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

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float top_v = 1.0 - clamp(u_horizon, 0.02, 0.98);
    // Blend band just below the horizon (matches SkyGradient fade). floor at 1 px.
    float px = 1.0 / max(resolution.y, 1.0);
    float fade = max(clamp(u_fade, 0.0, 0.5), px);
    float body = smoothstep(top_v, top_v + fade, uv.y);
    if (body < 0.001) {
        return half4(0.0);
    }
    float depth = clamp((uv.y - top_v) / max(1.0 - top_v, 1e-3), 0.0, 1.0);
    float det = clamp(u_detail, 0.0, 2.0);
    // Top = horizon tint (u_edge), bottom = darker take on u_color — same hue family
    half3 top = u_edge;
    half3 bot = u_color * half3(0.68, 0.68, 0.68);
    half3 base = mix(top, bot, half(depth));
    if (det > 0.001) {
        // Isotropic grit — avoid low Y frequency that reads as horizontal bands
        float2 gp = float2(uv.x, uv.y) * (18.0 * max(det, 0.15));
        float n = noise(gp + float2(u_offset.x, u_offset.y) * 0.0008);
        float n2 = noise(gp * 2.3 + float2(5.1, 9.7));
        float grit = (n - 0.5) * 0.10 + (n2 - 0.5) * 0.05;
        grit *= det * (0.35 + 0.65 * clamp(u_line, 0.0, 2.0));
        base = base + half3(grit, grit * 1.05, grit * 0.85);
    }
    float af = clamp(body * clamp(u_alpha, 0.0, 1.0), 0.0, 1.0);
    return half4(base * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# Nebula — broad ribbon bands
# ---------------------------------------------------------------------------
_NEBULA_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_scale_pat;
uniform float u_contrast;
uniform float u_speed;
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
float fbm3(float2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 3; ++i) {
        p = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
        v += a * noise(p);
        p = p * 2.1 + float2(9.0, 13.0);
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
    float2 uv = (p + center) / max(resolution, float2(1.0));
    float t = time * u_speed;
    float sc = mix(0.6, 2.2, clamp(u_scale_pat, 0.2, 2.0) * 0.5);
    float2 q = (uv - 0.5) * float2(1.4, 1.0) * sc;
    float n = fbm3(q + float2(t * 0.04, sin(t * 0.12) * 0.05));
    float ribbon = sin((uv.x + n * 0.35) * 5.0 + t * 0.3) * 0.5 + 0.5;
    float band = smoothstep(0.25, 0.75, n * 0.55 + ribbon * 0.45);
    float ctr = mix(0.35, 1.2, clamp(u_contrast, 0.0, 2.0) * 0.5);
    band = pow(band, ctr);
    half3 col = mix(half3(u_color), half3(u_color2), half(n));
    float a = clamp(band * u_alpha * 0.85, 0.0, 0.88);
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Lattice — soft geometric wash (fold × edge × layers)
# u_fold: 0 square, 1 hex, 2 tri
# u_layers: square/tri = ×2 UV octaves; hex = children on parent vertices
# u_size: shape extent (1.0 = reference; clamped to 1.7)
# u_layer_scale: child size mul 1..2 (1 = natural)
# u_color + alpha (transparent; stackable — no bg)
# ---------------------------------------------------------------------------
_LATTICE_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_fold;
uniform float u_edge;
uniform float u_spacing;
uniform float u_line;
uniform float u_layers;
uniform float u_size;
uniform float u_layer_scale;
uniform float u_angle;
uniform float u_alpha;

float hex_dist(float2 p) {
    p = abs(p);
    return max(p.x * 0.8660254 + p.y * 0.5, p.y);
}

float2 hex_gv(float2 uv) {
    float2 r = float2(1.0, 1.7320508);
    float2 h = r * 0.5;
    float2 a = mod(uv, r) - h;
    float2 b = mod(uv - h, r) - h;
    return dot(a, a) < dot(b, b) ? a : b;
}

float extent_from_size(float size) {
    return 0.252 * clamp(size, 0.05, 1.7);
}

float motif_from_sd(float sd, float edge_mode, float lw) {
    float outline = 1.0 - smoothstep(0.0, lw, abs(sd));
    float fill = 1.0 - smoothstep(-lw, lw, sd);
    return (edge_mode < 0.5) ? outline : fill;
}

float tri_sd(float2 uv, float extent) {
    float2 n2 = float2(0.5, 0.8660254);
    float2 n3 = float2(-0.5, 0.8660254);
    float d1 = abs(fract(uv.x) - 0.5);
    float d2 = abs(fract(dot(uv, n2)) - 0.5);
    float d3 = abs(fract(dot(uv, n3)) - 0.5);
    float edge_d = min(d1, min(d2, d3));
    float d_center = 0.25 - edge_d;
    return d_center - extent * 0.5;
}

// Local UV scale about square cell center (larger scale → larger shapes → smaller k)
float2 octave_scaled_uv(float2 uv, float k) {
    float2 cell = floor(uv);
    float2 f = fract(uv) - 0.5;
    return cell + 0.5 + f * k;
}

// Square / tri: classic ×2 UV octaves (the look that worked well for square)
float densify_layers(float2 uv, float fold, float extent, float edge_mode, float lw,
                     float nlay, float scale) {
    float ink = 0.0;
    float gain = 1.0;
    float mul = clamp(scale, 1.0, 2.0);
    float k = 1.0 / mul;
    for (int i = 0; i < 3; ++i) {
        if (float(i) >= nlay) { break; }
        float2 u = uv * exp2(float(i));
        if (i > 0) {
            u = octave_scaled_uv(u, k);
        }
        float sd;
        if (fold < 0.5) {
            float2 f = abs(fract(u) - 0.5);
            sd = max(f.x, f.y) - extent;
        } else {
            sd = tri_sd(u, extent);
        }
        ink = max(ink, motif_from_sd(sd, edge_mode, lw) * gain);
        gain *= 0.78;
    }
    return ink;
}

float hex_layers(float2 uv, float extent, float edge_mode, float lw,
                 float nlay, float scale) {
    float2 gv = hex_gv(uv);
    float ink = motif_from_sd(hex_dist(gv) - extent, edge_mode, lw);
    if (nlay < 1.5) { return ink; }

    float mul = clamp(scale, 1.0, 2.0);
    float e1 = extent * 0.5 * mul;
    // Flat-top hex: vertices at 0°, 60°, ... with R = apothem / cos(30°)
    float R0 = extent * 1.154700538;
    float gain = 0.78;
    for (int v = 0; v < 6; ++v) {
        float ang = float(v) * 1.0471975512;
        float2 vtx = float2(cos(ang), sin(ang)) * R0;
        ink = max(ink, motif_from_sd(hex_dist(gv - vtx) - e1, edge_mode, lw) * gain);

        if (nlay >= 2.5) {
            float e2 = e1 * 0.5 * mul;
            float R1 = e1 * 1.154700538;
            float gain2 = gain * 0.78;
            for (int w = 0; w < 6; ++w) {
                float ang2 = float(w) * 1.0471975512;
                float2 vtx2 = vtx + float2(cos(ang2), sin(ang2)) * R1;
                ink = max(ink, motif_from_sd(hex_dist(gv - vtx2) - e2, edge_mode, lw) * gain2);
            }
        }
    }
    return ink;
}

half4 main(float2 coord) {
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float sp = mix(0.045, 0.2, clamp(u_spacing, 0.1, 2.0) * 0.5);
    float2 uv = p / min_res / sp;
    float ca = cos(u_angle);
    float sa = sin(u_angle);
    uv = float2(ca * uv.x - sa * uv.y, sa * uv.x + ca * uv.y);

    float lw = mix(0.006, 0.028, clamp(u_line, 0.1, 2.0) * 0.5);
    float fold = clamp(u_fold, 0.0, 2.0);
    float edge_mode = clamp(u_edge, 0.0, 1.0);
    float nlay = clamp(u_layers, 1.0, 3.0);
    float extent = extent_from_size(u_size);
    float scale = u_layer_scale;

    float ink = 0.0;
    if (fold < 0.5) {
        ink = densify_layers(uv, 0.0, extent, edge_mode, lw, nlay, scale);
    } else if (fold < 1.5) {
        ink = hex_layers(uv, extent, edge_mode, lw, nlay, scale);
    } else {
        ink = densify_layers(uv, 2.0, extent, edge_mode, lw, nlay, scale);
    }

    ink = clamp(ink, 0.0, 1.0);
    float af = clamp(ink * 0.62 * clamp(u_alpha, 0.0, 1.0), 0.0, 0.85);
    return half4(u_color * half(af), half(af));
}
"""

clouds_builder = _compile_runtime(_CLOUDS_SKSL, "ambient.Clouds")
stars_builder = _compile_runtime(_STARS_SKSL, "ambient.Stars")
stardust_builder = _compile_runtime(_STARDUST_SKSL, "ambient.Stardust")
stardust_survival_builder = _compile_runtime(
    _STARDUST_SURVIVAL_SKSL, "ambient.StardustSurvival",
)
chromadust_builder = _compile_runtime(_CHROMADUST_SKSL, "ambient.Chromadust")
chromadust_survival_builder = _compile_runtime(
    _CHROMADUST_SURVIVAL_SKSL, "ambient.ChromadustSurvival",
)
nebuladust_builder = _compile_runtime(_NEBULADUST_SKSL, "ambient.Nebuladust")
nebuladust_survival_builder = _compile_runtime(
    _NEBULADUST_SURVIVAL_SKSL, "ambient.NebuladustSurvival",
)
borealis_builder = _compile_runtime(_BOREALIS_SKSL, "ambient.Borealis")
plasma_builder = _compile_runtime(_PLASMA_SKSL, "ambient.Plasma")
mist_builder = _compile_runtime(_MIST_SKSL, "ambient.Mist")
debris_builder = _compile_runtime(_DEBRIS_SKSL, "ambient.Debris")
embers_builder = _compile_runtime(_EMBERS_SKSL, "ambient.Embers")
windstreaks_builder = _compile_runtime(_WINDSTREAKS_SKSL, "ambient.WindStreaks")
ground_builder = _compile_runtime(_GROUND_SKSL, "ambient.Ground")
nebula_builder = _compile_runtime(_NEBULA_SKSL, "ambient.Nebula")
lattice_builder = _compile_runtime(_LATTICE_SKSL, "ambient.Lattice")

__all__ = [
    "draw_shader_rect",
    "clouds_builder",
    "stars_builder",
    "stardust_builder",
    "stardust_survival_builder",
    "chromadust_builder",
    "chromadust_survival_builder",
    "nebuladust_builder",
    "nebuladust_survival_builder",
    "borealis_builder",
    "plasma_builder",
    "mist_builder",
    "debris_builder",
    "embers_builder",
    "windstreaks_builder",
    "ground_builder",
    "nebula_builder",
    "lattice_builder",
]
