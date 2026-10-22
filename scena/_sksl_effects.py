"""
Curated SkSL / RuntimeEffect post passes (internal).

Compiled once at import; per frame only uniforms / children are updated.
Must run on a GPU destination (window canvas or MakeRenderTarget) —
raster destinations are ~30–60× slower and are not supported.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple, Union

import skia

from .postfx import PostEffect, PostEffectStage
from .color import resolve_rgb
from .validate import expect_choice


def _compile_runtime(sksl: str, name: str) -> skia.RuntimeShaderBuilder:
    eff = skia.RuntimeEffect.MakeForShader(sksl)
    err = None
    if isinstance(eff, tuple):
        eff, err = eff
    if eff is None:
        raise RuntimeError(f"{name} SkSL failed to compile: {err}")
    return skia.RuntimeShaderBuilder(eff)


_PRISM_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float u_strength;

half4 main(float2 coord) {
    float2 uv = coord / resolution;
    float2 c = uv - float2(0.5);
    float ang = time * 1.7;
    float2 dir = float2(cos(ang), sin(ang));
    float am = u_strength * (0.55 + 0.45 * sin(time * 3.1));
    float2 off = dir * am * resolution.x;
    half r = image.eval(coord + off).r;
    half g = image.eval(coord).g;
    half b = image.eval(coord - off).b;
    half pulse = half(0.04 * (0.5 + 0.5 * sin(time * 5.0)));
    half3 rgb = half3(r, g, b) * half3(0.96, 0.98, 1.06)
              + half3(0.0, pulse, pulse * 1.4);
    return half4(rgb, 1.0);
}
"""

_CHROMA_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float u_amount;

half4 main(float2 coord) {
    float px = u_amount;
    half4 c0 = image.eval(coord);
    half r = image.eval(coord + float2(px, 0.0)).r;
    half g = c0.g;
    half b = image.eval(coord - float2(px, 0.0)).b;
    return half4(r, g, b, c0.a);
}
"""

_TILT_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_tilt;
uniform float u_amount;

half4 main(float2 coord) {
    float2 uv = coord / resolution - float2(0.5);
    float z = 1.0
            + u_tilt.y * uv.y * u_amount
            + u_tilt.x * uv.x * u_amount * 0.55;
    float2 p = uv / max(z, 0.28);
    p *= 1.0 + 0.10 * dot(p, p);
    float2 sample_xy = (p + float2(0.5)) * resolution;
    if (sample_xy.x < 0.0 || sample_xy.y < 0.0
        || sample_xy.x > resolution.x || sample_xy.y > resolution.y) {
        return half4(0.02, 0.02, 0.04, 1.0);
    }
    return image.eval(sample_xy);
}
"""

_LAMP_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_light;
uniform float3 u_light_color;
uniform float u_radius;
uniform float u_range;
uniform float u_ambient;
uniform float u_specular;
uniform float u_intensity;

half luma(half3 c) {
    return dot(c, half3(0.299, 0.587, 0.114));
}

half4 main(float2 coord) {
    half4 col = image.eval(coord);
    half h  = luma(col.rgb);
    half hl = luma(image.eval(coord + float2(-2.0, 0.0)).rgb);
    half hr = luma(image.eval(coord + float2( 2.0, 0.0)).rgb);
    half hd = luma(image.eval(coord + float2(0.0,  2.0)).rgb);
    half hu = luma(image.eval(coord + float2(0.0, -2.0)).rgb);
    float3 n = normalize(float3(float(hl - hr) * 3.0,
                                float(hd - hu) * 3.0,
                                0.55));
    float3 to_l = float3(u_light - coord, 55.0);
    float dist = length(to_l.xy);
    float3 L = normalize(to_l);
    half ndotl = max(half(dot(n, L)), 0.0);
    // Soft range gate: fully off beyond u_range.
    float range_gate = 1.0 - smoothstep(u_range * 0.65, max(u_range, 1.0), dist);
    half atten = half(exp(-dist / max(u_radius, 1.0)) * range_gate);
    half3 light = half3(u_light_color) * (ndotl * atten * half(u_intensity));
    half3 H = half3(normalize(L + float3(0.0, 0.0, 1.0)));
    half spec = pow(max(half(dot(half3(n), H)), 0.0), 24.0)
              * half(u_specular) * atten * h;
    half3 outc = col.rgb * (half(u_ambient) + light) + half3(spec);
    return half4(outc, col.a);
}
"""

_DISTANT_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_dir;
uniform float3 u_light_color;
uniform float u_ambient;
uniform float u_intensity;
uniform float u_specular;

half luma(half3 c) {
    return dot(c, half3(0.299, 0.587, 0.114));
}

half4 main(float2 coord) {
    half4 col = image.eval(coord);
    half h  = luma(col.rgb);
    half hl = luma(image.eval(coord + float2(-2.0, 0.0)).rgb);
    half hr = luma(image.eval(coord + float2( 2.0, 0.0)).rgb);
    half hd = luma(image.eval(coord + float2(0.0,  2.0)).rgb);
    half hu = luma(image.eval(coord + float2(0.0, -2.0)).rgb);
    float3 n = normalize(float3(float(hl - hr) * 3.0,
                                float(hd - hu) * 3.0,
                                0.55));
    // Parallel rays (direction points *toward* the surface from the light).
    float3 L = normalize(float3(u_dir.x, u_dir.y, 0.65));
    half ndotl = max(half(dot(n, L)), 0.0);
    half3 light = half3(u_light_color) * (ndotl * half(u_intensity));
    half3 H = half3(normalize(L + float3(0.0, 0.0, 1.0)));
    half spec = pow(max(half(dot(half3(n), H)), 0.0), 28.0)
              * half(u_specular) * h;
    half3 outc = col.rgb * (half(u_ambient) + light) + half3(spec);
    return half4(outc, col.a);
}
"""

_RAYS_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_light;
uniform float u_weight;
uniform float u_decay;
uniform float u_exposure;

half bright(half3 c) {
    return max(c.r, max(c.g, c.b));
}

half4 main(float2 coord) {
    float2 delta = (u_light - coord) * (1.0 / 8.0);
    float2 pos = coord;
    half illum = 0.0;
    half decay = 1.0;
    for (int i = 0; i < 8; ++i) {
        pos += delta;
        half3 s = image.eval(pos).rgb;
        half b = bright(s);
        illum += b * b * decay * half(u_weight);
        decay *= half(u_decay);
    }
    half3 shaft = half3(1.0, 0.92, 0.70) * illum * half(u_exposure);
    return half4(shaft, 1.0);
}
"""

_HAZE_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float u_amount;
uniform float u_bias;

half4 main(float2 coord) {
    float2 uv = coord / resolution;
    // Multi-scale heat shimmer — mean displacement is ~0 (no global shift).
    float t = time;
    float2 n = float2(
        sin(uv.y * 28.0 + t * 2.4) * 0.55
      + sin(uv.y * 61.0 - t * 3.1 + uv.x * 8.0) * 0.35
      + sin(uv.x * 40.0 + t * 1.7) * 0.15,
        cos(uv.x * 24.0 - t * 1.9) * 0.55
      + cos(uv.x * 53.0 + t * 2.6 + uv.y * 7.0) * 0.35
      + cos(uv.y * 36.0 - t * 2.2) * 0.15
    );
    n.y *= u_bias;
    float2 sample_xy = coord + n * u_amount;
    return image.eval(sample_xy);
}
"""

_SPOTLIGHT_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_origin;
uniform float2 u_dir;
uniform float3 u_color;
uniform float u_range;
uniform float u_cone_inner;
uniform float u_cone_outer;
uniform float u_ambient;
uniform float u_intensity;

half4 main(float2 coord) {
    half4 col = image.eval(coord);
    float2 delta = coord - u_origin;
    float dist = length(delta);
    float2 nd = dist > 1e-3 ? delta / dist : float2(0.0, 1.0);
    float cang = clamp(dot(nd, u_dir), -1.0, 1.0);
    // Cosine falloff through the cone: 1 on-axis → 0 at outer rim.
    float cone = smoothstep(u_cone_outer, u_cone_inner, cang);
    // Hard-ish range: no light beyond u_range (soft shoulder).
    float range_gate = 1.0 - smoothstep(u_range * 0.72, max(u_range, 1.0), dist);
    // Soft inverse-square-ish within the lit volume.
    float atten = range_gate * (1.0 / (1.0 + (dist / max(u_range * 0.35, 1.0))
                                      * (dist / max(u_range * 0.35, 1.0))));
    float lit = cone * atten * u_intensity;
    half3 litc = half3(u_color) * half(lit);
    half3 outc = col.rgb * (half(u_ambient) + litc);
    return half4(outc, col.a);
}
"""

_KALEIDO_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float u_segments;
uniform float u_zoom;
uniform float u_spin;

half4 main(float2 coord) {
    float2 uv = coord / resolution - float2(0.5);
    float aspect = resolution.x / max(resolution.y, 1.0);
    uv.x *= aspect;
    float ang0 = time * u_spin;
    float ca = cos(ang0);
    float sa = sin(ang0);
    uv = float2(ca * uv.x - sa * uv.y, sa * uv.x + ca * uv.y);

    float r = length(uv);
    float a = atan(uv.y, uv.x);
    float seg = 6.28318530718 / max(u_segments, 2.0);
    a = abs(mod(a, seg) - seg * 0.5);
    float2 p = float2(cos(a), sin(a)) * r / max(u_zoom, 0.05);
    p.x /= aspect;
    float2 sample_xy = (p + float2(0.5)) * resolution;
    return image.eval(sample_xy);
}
"""

_RIPPLE_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_center;
uniform float u_progress;
uniform float u_strength;
uniform float u_flash;
uniform float u_mode;
uniform float u_angle;
uniform float u_span;

half4 main(float2 coord) {
    float2 uv = coord / resolution;
    float aspect = resolution.y / max(resolution.x, 1.0);
    float2 d = float2(uv.x - u_center.x, (uv.y - u_center.y) * aspect);
    float span = max(u_span, 0.05);
    float dist;
    float2 n;
    float wave_arg;
    if (u_mode > 0.5) {
        // Linear: displace along a single normal (no sign flip → no seam).
        float2 dir = float2(cos(u_angle), sin(u_angle));
        float sd = dot(d, dir);
        dist = abs(sd);
        n = dir;
        wave_arg = (sd / span) * 48.0 - (1.0 - u_progress) * 18.0;
    } else {
        dist = length(d);
        n = dist > 1e-4 ? d / dist : float2(0.0);
        wave_arg = (dist / span) * 48.0 - (1.0 - u_progress) * 18.0;
    }
    float env = max(0.0, 1.0 - u_progress);
    env = env * env;
    float wave = sin(wave_arg);
    float fall = max(0.0, 1.0 - (dist / span) * 1.35);
    float amp = fall * wave * env * u_strength;
    float2 sample_xy = coord + n * amp * resolution.x * 0.045;
    half4 col = image.eval(sample_xy);
    col.rgb = mix(col.rgb, half3(1.0), half(clamp(u_flash, 0.0, 1.0)));
    return col;
}
"""

_CRT_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float u_amount;
uniform float u_chroma_px;

half4 main(float2 coord) {
    // Final geometric CRT tube: mild barrel, then chroma, then vignette.
    // Input plate already has scanlines from the quality overlay pass.
    float2 uv = coord / resolution - float2(0.5);
    float r2 = dot(uv, uv);
    float barrel = 1.0 + r2 * (0.14 * u_amount);
    float2 bent = uv * barrel;
    float2 base = (bent + float2(0.5)) * resolution;
    if (base.x < 0.0 || base.y < 0.0
        || base.x > resolution.x || base.y > resolution.y) {
        return half4(0.02, 0.02, 0.03, 1.0);
    }
    float px = u_chroma_px;
    half4 c0 = image.eval(base);
    half r = image.eval(base + float2(px, 0.0)).r;
    half g = c0.g;
    half b = image.eval(base - float2(px, 0.0)).b;
    half3 rgb = half3(r, g, b);
    float vig = 1.0 - smoothstep(0.50, 0.98, length(bent) * 1.35) * 0.45 * u_amount;
    rgb *= half(vig);
    return half4(rgb, c0.a);
}
"""

_GLITCH_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float u_amount;

half4 main(float2 coord) {
    float2 uv = coord / resolution;
    float band = floor(uv.y * 28.0);
    float n = fract(sin(band * 12.9898 + time * 7.1) * 43758.5453);
    float slice = (n - 0.5) * u_amount * resolution.x * 0.08;
    float tear = step(0.82, n) * u_amount * resolution.x * 0.04;
    float2 base = coord + float2(slice + tear, 0.0);
    float2 coff = float2(u_amount * 4.0, 0.0);
    half r = image.eval(base + coff).r;
    half g = image.eval(base).g;
    half b = image.eval(base - coff).b;
    half3 rgb = half3(r, g, b);
    float line = step(0.97, fract(uv.y * 90.0 + time * 3.0));
    rgb = mix(rgb, half3(0.2, 1.0, 0.9), half(line * 0.15 * u_amount));
    return half4(rgb, 1.0);
}
"""

_VORTEX_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_center;
uniform float u_strength;
uniform float u_spin;

half4 main(float2 coord) {
    float2 uv = coord / resolution;
    float aspect = resolution.x / max(resolution.y, 1.0);
    float2 c = u_center / resolution;
    float2 d = uv - c;
    d.x *= aspect;
    float dist = length(d);
    float fall = exp(-dist * 3.2);
    float ang = u_spin * fall * u_strength;
    float ca = cos(ang);
    float sa = sin(ang);
    float2 rd = float2(ca * d.x - sa * d.y, sa * d.x + ca * d.y);
    // Mild pull toward center.
    rd *= 1.0 - 0.18 * fall * u_strength;
    rd.x /= aspect;
    float2 sample_xy = (rd + c) * resolution;
    return image.eval(sample_xy);
}
"""

_ZOOMBLUR_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float2 u_center;
uniform float u_amount;

half4 main(float2 coord) {
    float2 dir = u_center - coord;
    half4 acc = half4(0.0);
    acc += image.eval(coord) * 0.28;
    acc += image.eval(coord + dir * 0.04 * u_amount) * 0.18;
    acc += image.eval(coord + dir * 0.08 * u_amount) * 0.16;
    acc += image.eval(coord + dir * 0.12 * u_amount) * 0.14;
    acc += image.eval(coord + dir * 0.16 * u_amount) * 0.12;
    acc += image.eval(coord + dir * 0.22 * u_amount) * 0.12;
    return acc;
}
"""

# ---------------------------------------------------------------------------
# Spatial color-grade / dancing wash family (post, not BackgroundFields)
# ---------------------------------------------------------------------------

_COLORSWEEP_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float3 u_c0;
uniform float3 u_c1;
uniform float3 u_c2;
uniform float3 u_c3;
uniform float u_n;
uniform float u_axis;
uniform float u_amount;
uniform float u_speed;
uniform float u_sat;

half3 pal(float t) {
    t = clamp(t, 0.0, 1.0);
    float segs = max(u_n - 1.0, 1.0);
    float x = t * segs;
    half3 a = half3(u_c0);
    half3 b = half3(u_c1);
    if (x >= 2.0) {
        a = half3(u_c2);
        b = half3(u_c3);
        x -= 2.0;
    } else if (x >= 1.0) {
        a = half3(u_c1);
        b = half3(u_c2);
        x -= 1.0;
    }
    return mix(a, b, half(clamp(x, 0.0, 1.0)));
}

half3 hue_rot(half3 rgb, float ang) {
    float c = cos(ang);
    float s = sin(ang);
    float3 v = float3(rgb);
    float y = dot(v, float3(0.299, 0.587, 0.114));
    float i = dot(v, float3(0.596, -0.274, -0.322));
    float q = dot(v, float3(0.211, -0.523, 0.312));
    float i2 = i * c - q * s;
    float q2 = i * s + q * c;
    return half3(
        y + i2 * 0.956 + q2 * 0.621,
        y + i2 * -0.272 + q2 * -0.647,
        y + i2 * -1.107 + q2 * 1.705
    );
}

half ov1(half b, half tcol) {
    half lo = 2.0 * b * tcol;
    half hi = 1.0 - 2.0 * (1.0 - b) * (1.0 - tcol);
    return mix(lo, hi, step(0.5, b));
}

half4 main(float2 coord) {
    float2 uv = coord / max(resolution, float2(1.0));
    float axis_t;
    if (u_axis < 0.5) {
        float2 d = uv - float2(0.5);
        axis_t = length(d) * 1.41421356;
    } else if (u_axis < 1.5) {
        axis_t = uv.x;
    } else {
        axis_t = uv.y;
    }
    float drift = 0.14 * sin(time * u_speed);
    float t = clamp(axis_t + drift, 0.0, 1.0);
    half4 src4 = image.eval(coord);
    half3 src = src4.rgb;
    half luma = dot(src, half3(0.299, 0.587, 0.114));
    half3 vivid = mix(half3(luma), src, half(1.0 + u_sat));
    half3 tint = pal(t);
    half3 ov = half3(ov1(vivid.r, tint.r), ov1(vivid.g, tint.g), ov1(vivid.b, tint.b));
    float hue = (t - 0.5) * u_amount * 1.65 + 0.22 * sin(time * u_speed * 0.85);
    half3 spun = hue_rot(vivid, hue);
    half3 mixc = mix(spun, ov, half(0.55));
    half3 outc = mix(src, mixc, half(clamp(u_amount, 0.0, 1.25)));
    return half4(outc, src4.a);
}
"""

_PLASMAWASH_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float3 u_c0;
uniform float3 u_c1;
uniform float3 u_c2;
uniform float u_n;
uniform float u_amount;
uniform float u_speed;
uniform float u_sat;

half3 pal(float t) {
    t = clamp(t, 0.0, 1.0);
    if (u_n < 2.5) {
        return mix(half3(u_c0), half3(u_c1), half(t));
    }
    float x = t * 2.0;
    if (x < 1.0) {
        return mix(half3(u_c0), half3(u_c1), half(x));
    }
    return mix(half3(u_c1), half3(u_c2), half(x - 1.0));
}

half3 hue_rot(half3 rgb, float ang) {
    float c = cos(ang);
    float s = sin(ang);
    float3 v = float3(rgb);
    float y = dot(v, float3(0.299, 0.587, 0.114));
    float i = dot(v, float3(0.596, -0.274, -0.322));
    float q = dot(v, float3(0.211, -0.523, 0.312));
    float i2 = i * c - q * s;
    float q2 = i * s + q * c;
    return half3(
        y + i2 * 0.956 + q2 * 0.621,
        y + i2 * -0.272 + q2 * -0.647,
        y + i2 * -1.107 + q2 * 1.705
    );
}

half4 main(float2 coord) {
    float2 uv = coord / max(resolution, float2(1.0));
    float t = time * u_speed;
    float x = uv.x * 6.2831853;
    float y = uv.y * 6.2831853;
    float v = 0.0;
    v += sin(x + t);
    v += sin(y * 1.3 - t * 0.9);
    v += sin((x + y) * 0.7 + t * 1.3);
    v += sin(sqrt(x * x + y * y) * 1.8 - t * 0.7);
    v = v * 0.25 + 0.5;
    half4 src4 = image.eval(coord);
    half3 src = src4.rgb;
    half luma = dot(src, half3(0.299, 0.587, 0.114));
    half3 vivid = mix(half3(luma), src, half(1.0 + u_sat));
    half3 tint = pal(v);
    half3 spun = hue_rot(vivid, (v - 0.5) * u_amount * 2.2);
    half3 wash = mix(spun, spun * tint * 1.35, half(0.55 + 0.45 * v));
    half3 outc = mix(src, wash, half(clamp(u_amount, 0.0, 1.2)));
    return half4(outc, src4.a);
}
"""

_NEBULABLOOM_SKSL = """
uniform shader image;
uniform float2 resolution;
uniform float time;
uniform float3 u_c0;
uniform float3 u_c1;
uniform float u_amount;
uniform float u_speed;
uniform float u_bloom;
uniform float u_sat;

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
float fbm2(float2 p) {
    float2 q = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
    return 0.65 * noise(p) + 0.35 * noise(q * 2.05 + float2(11.0, 7.0));
}

half3 hue_rot(half3 rgb, float ang) {
    float c = cos(ang);
    float s = sin(ang);
    float3 v = float3(rgb);
    float y = dot(v, float3(0.299, 0.587, 0.114));
    float i = dot(v, float3(0.596, -0.274, -0.322));
    float q = dot(v, float3(0.211, -0.523, 0.312));
    float i2 = i * c - q * s;
    float q2 = i * s + q * c;
    return half3(
        y + i2 * 0.956 + q2 * 0.621,
        y + i2 * -0.272 + q2 * -0.647,
        y + i2 * -1.107 + q2 * 1.705
    );
}

half luma(half3 c) {
    return dot(c, half3(0.299, 0.587, 0.114));
}

half4 main(float2 coord) {
    float2 uv = coord / max(resolution, float2(1.0));
    float t = time * u_speed * 0.12;
    float2 q = (uv - 0.5) * float2(1.35, 1.0) * 1.6;
    float wr = t * 0.25;
    float wc = cos(wr), ws = sin(wr);
    q = float2(wc * q.x - ws * q.y, ws * q.x + wc * q.y);
    float2 w = float2(fbm2(q + float2(t * 0.9, 0.2)), fbm2(q.yx + float2(0.3, t * 0.9) + 3.0));
    q += (w - 0.5) * 1.15;
    float dens = fbm2(q + t * 0.05);
    float ridge = 1.0 - abs(noise(q * 1.55 + w) * 2.0 - 1.0);
    float field = clamp(dens * 0.7 + ridge * ridge * 0.45, 0.0, 1.0);
    half4 src4 = image.eval(coord);
    half3 src = src4.rgb;
    half L = luma(src);
    half3 vivid = mix(half3(L), src, half(1.0 + u_sat));
    half3 tint = mix(half3(u_c0), half3(u_c1), half(field));
    half3 spun = hue_rot(vivid, (field - 0.5) * u_amount * 1.8);
    half3 graded = mix(spun, spun * tint * 1.28, half(0.35 + 0.55 * field));
    float2 dir = float2(wc, ws);
    half glare = 0.0;
    glare += pow(luma(image.eval(coord + dir * 7.0).rgb), 2.4);
    glare += pow(luma(image.eval(coord - dir * 7.0).rgb), 2.4);
    glare += pow(luma(image.eval(coord + float2(-dir.y, dir.x) * 6.0).rgb), 2.4);
    glare += pow(L, 2.6);
    glare *= 0.25;
    half3 bloom = tint * half(glare * u_bloom * (0.55 + 0.45 * field));
    half3 outc = mix(src, graded, half(clamp(u_amount, 0.0, 1.2))) + bloom;
    return half4(outc, src4.a);
}
"""

_prism_builder = _compile_runtime(_PRISM_SKSL, "prism")
_chroma_builder = _compile_runtime(_CHROMA_SKSL, "chroma")
_tilt_builder = _compile_runtime(_TILT_SKSL, "tilt")
_lamp_builder = _compile_runtime(_LAMP_SKSL, "lamp")
_distant_builder = _compile_runtime(_DISTANT_SKSL, "distant")
_rays_builder = _compile_runtime(_RAYS_SKSL, "rays")
_haze_builder = _compile_runtime(_HAZE_SKSL, "haze")
_spotlight_builder = _compile_runtime(_SPOTLIGHT_SKSL, "spotlight")
_kaleido_builder = _compile_runtime(_KALEIDO_SKSL, "kaleido")
_ripple_builder = _compile_runtime(_RIPPLE_SKSL, "ripple")
_crt_builder = _compile_runtime(_CRT_SKSL, "crt")
_glitch_builder = _compile_runtime(_GLITCH_SKSL, "glitch")
_vortex_builder = _compile_runtime(_VORTEX_SKSL, "vortex")
_zoomblur_builder = _compile_runtime(_ZOOMBLUR_SKSL, "zoomblur")
_colorsweep_builder = _compile_runtime(_COLORSWEEP_SKSL, "colorsweep")
_plasmawash_builder = _compile_runtime(_PLASMAWASH_SKSL, "plasmawash")
_nebulabloom_builder = _compile_runtime(_NEBULABLOOM_SKSL, "nebulabloom")

_ALL_RUNTIME_BUILDERS = (
    _prism_builder, _chroma_builder, _tilt_builder, _lamp_builder, _distant_builder,
    _rays_builder, _haze_builder, _spotlight_builder, _kaleido_builder,
    _ripple_builder,
    _crt_builder, _glitch_builder,
    _vortex_builder, _zoomblur_builder,
    _colorsweep_builder, _plasmawash_builder,
    _nebulabloom_builder,
)


def release_runtime_children() -> None:
    """Drop retained ``image`` children so scene snapshots can be freed."""
    for b in _ALL_RUNTIME_BUILDERS:
        try:
            b.setChild("image", None)
        except Exception:
            pass


def _design_size():
    from .orchestration import ScenaFramework
    fw = ScenaFramework.get_instance()
    return float(fw.design_width), float(fw.design_height)


_scanline_strip_cache: dict = {}


def draw_scanlines_multiply(canvas, w: float, h: float, amount: float = 1.0) -> None:
    """CRT scanlines — Nearest-tiled Multiply bands.

    Strip images are cached. Band height tracks the destination height vs
    design size so Full/Retina stays visible; Balanced can still draw this
    on the low-res overlay plate (``Scanlines._quality_sensitive``).
    """
    a = max(0.0, min(1.0, float(amount)))
    if a <= 0:
        return
    try:
        _, design_h = _design_size()
    except Exception:
        design_h = float(h) or 1.0
    # ~1 design-pixel bright + 1 design-pixel dark per cycle on this surface.
    dpr = max(1.0, float(h) / max(float(design_h), 1.0))
    pair = max(2, int(round(2.0 * dpr)))
    if pair % 2:
        pair += 1
    key = (round(a, 3), pair)
    img = _scanline_strip_cache.get(key)
    if img is None:
        half = pair // 2
        strip = skia.Surface(1, pair)
        sc = strip.getCanvas()
        sc.clear(skia.ColorWHITE)
        dark = int(255 * (1.0 - 0.18 * a))
        sc.drawRect(
            skia.Rect.MakeXYWH(0, half, 1, half),
            skia.Paint(Color=skia.Color(dark, dark, dark)),
        )
        img = strip.makeImageSnapshot()
        _scanline_strip_cache[key] = img
    nearest = skia.SamplingOptions(skia.FilterMode.kNearest)
    shader = img.makeShader(
        skia.TileMode.kRepeat, skia.TileMode.kRepeat, nearest,
    )
    canvas.drawRect(
        skia.Rect.MakeWH(w, h),
        skia.Paint(Shader=shader, BlendMode=skia.BlendMode.kMultiply),
    )


def _mouse_fb_xy(fb_w: float, fb_h: float) -> Tuple[float, float]:
    import builtins
    mouse = getattr(builtins, "mouse", None)
    W, H = _design_size()
    mx = float(getattr(mouse, "x", W * 0.5) or (W * 0.5))
    my = float(getattr(mouse, "y", H * 0.5) or (H * 0.5))
    return (mx / W * fb_w, (1.0 - my / H) * fb_h)


def _resolve_target_fb(target, fb_w, fb_h) -> Tuple[float, float]:
    """``target=None`` → mouse; else a point or an object (its center, read
    every frame, so the effect follows it) → FB pixels. The Guia promises
    "a point or an object" for every ``target=`` / ``center=`` here; reading
    ``target[0]`` raised on an object at the first drawn frame (2026-10-22)."""
    if target is None:
        return _mouse_fb_xy(fb_w, fb_h)
    from .shapes import _xy_of
    W, H = _design_size()
    x, y = _xy_of(target, required=True)
    return (x / W * fb_w, (1.0 - y / H) * fb_h)


class Prism(PostEffect):
    """Rotating chromatic prism split (SkSL).

    Args:
        amount: RGB split strength (default 0.004).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self, amount: float = 0.004):
        self.amount = float(amount)

    def _fx_cache_key(self) -> tuple:
        return ("prism", round(self.amount, 4))

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _prism_builder.setChild("image", sh)
        _prism_builder.setUniform("resolution", [float(w), float(h)])
        _prism_builder.setUniform("time", float(t))
        _prism_builder.setUniform("u_strength", float(self.amount))
        paint = skia.Paint(Shader=_prism_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Chroma(PostEffect):
    """Chromatic aberration — horizontal RGB channel split (SkSL).

    ``amount`` is offset in framebuffer pixels (default 4).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self, amount: float = 4.0):
        self.amount = float(amount)

    def _fx_cache_key(self) -> tuple:
        return ("chroma", round(self.amount, 2))

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if abs(self.amount) < 0.05:
            canvas.drawImage(image, 0, 0)
            return
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _chroma_builder.setChild("image", sh)
        _chroma_builder.setUniform("resolution", [float(w), float(h)])
        _chroma_builder.setUniform("u_amount", float(self.amount))
        paint = skia.Paint(Shader=_chroma_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Perspective(PostEffect):
    """Fake perspective / tilt UV remap (SkSL). ``target=None`` follows mouse.

    Args:
        amount: Tilt (default 0.55).
        target: Point it leans toward; ``None`` = the mouse.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self, amount: float = 0.55, target=None):
        self.amount = float(amount)
        self.target = target  # None | (x, y) design space

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        if self.target is None:
            import builtins
            mouse = getattr(builtins, "mouse", None)
            W, H = _design_size()
            mx = float(getattr(mouse, "x", W * 0.5) or (W * 0.5))
            my = float(getattr(mouse, "y", H * 0.5) or (H * 0.5))
            pitch = max(-1.0, min(1.0, (mx / W - 0.5) * 2.0))
            yaw = max(-1.0, min(1.0, (my / H - 0.5) * 2.0))
        else:
            from .shapes import _xy_of
            W, H = _design_size()
            tx, ty = _xy_of(self.target, required=True)
            pitch = max(-1.0, min(1.0, (tx / W - 0.5) * 2.0))
            yaw = max(-1.0, min(1.0, (ty / H - 0.5) * 2.0))
        pitch = max(-1.0, min(1.0, pitch + 0.12 * math.sin(t * 0.7)))
        yaw = max(-1.0, min(1.0, yaw + 0.10 * math.cos(t * 0.55)))
        _tilt_builder.setChild("image", sh)
        _tilt_builder.setUniform("resolution", [float(w), float(h)])
        _tilt_builder.setUniform("u_tilt", [float(pitch), float(yaw)])
        _tilt_builder.setUniform("u_amount", float(self.amount))
        paint = skia.Paint(Shader=_tilt_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Lamp(PostEffect):
    """Omnidirectional point light with Lambert + specular (SkSL).

    Estimates normals from scene luminance, then lights from a point. Distinct
    from :class:`Spotlight` (cone) and :class:`DistantLight` (parallel sun).

    ``target=None`` follows the mouse. ``range`` hard-limits illumination
    distance (FB pixels when set; default fraction of the shorter side).

    Args:
        color: Light color (can pass 1 for stronger light).
        radius: Light bubble size; ``None`` = 38 % of the short side.
        range: Where the light stops; ``None`` = 55 % of the short side.
        ambient: Light outside the lamp (default 0.16).
        specular: Shine (default 0.6).
        intensity: Strength (default 1.15).
        target: Where the lamp is; ``None`` = the mouse.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        color=(1.15, 1.05, 0.85),
        radius: Optional[float] = None,
        range: Optional[float] = None,
        ambient: float = 0.16,
        specular: float = 0.6,
        intensity: float = 1.15,
        target=None,
    ):
        self.color = resolve_rgb(color, default=(1.15, 1.05, 0.85))
        self.radius = radius
        self.range = range
        self.ambient = float(ambient)
        self.specular = float(specular)
        self.intensity = float(intensity)
        self.target = target

    def _fx_cache_key(self) -> tuple:
        return (
            "lamp",
            round(self.ambient, 3), round(self.specular, 3),
            round(self.intensity, 3), self.target, self.range,
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        lx, ly = _resolve_target_fb(self.target, w, h)
        short = float(min(w, h))
        rad = float(self.radius) if self.radius is not None else short * 0.38
        rng = float(self.range) if self.range is not None else short * 0.55
        _lamp_builder.setChild("image", sh)
        _lamp_builder.setUniform("resolution", [float(w), float(h)])
        _lamp_builder.setUniform("u_light", [float(lx), float(ly)])
        _lamp_builder.setUniform("u_light_color", list(self.color))
        _lamp_builder.setUniform("u_radius", rad)
        _lamp_builder.setUniform("u_range", rng)
        _lamp_builder.setUniform("u_ambient", self.ambient)
        _lamp_builder.setUniform("u_specular", self.specular)
        _lamp_builder.setUniform("u_intensity", self.intensity)
        paint = skia.Paint(Shader=_lamp_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class DistantLight(PostEffect):
    """Directional / sun-style lighting with parallel rays (SkSL).

    No distance falloff. ``direction`` is a 2D vector in design space (light
    comes from this heading); default is an upper-left key light.

    Args:
        direction: Where the light comes from, in design space (default ``(-0.55,
            -0.75)``).
        color: Light color.
        ambient: Ambient light (default 0.28).
        intensity: Strength (default 0.95).
        specular: Shine (default 0.35).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        direction: Tuple[float, float] = (-0.55, -0.75),
        color=(1.12, 1.05, 0.92),
        ambient: float = 0.28,
        intensity: float = 0.95,
        specular: float = 0.35,
    ):
        from .validate import pair
        dx, dy = pair(direction, "DistantLight direction")
        # Store design-space "light comes from" then flip Y for FB.
        length = math.hypot(dx, dy) or 1.0
        self.direction = (dx / length, dy / length)
        self.color = resolve_rgb(color, default=(1.12, 1.05, 0.92))
        self.ambient = float(ambient)
        self.intensity = float(intensity)
        self.specular = float(specular)

    def _fx_cache_key(self) -> tuple:
        return (
            "distant",
            self.direction, round(self.intensity, 3), round(self.ambient, 3),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        # Design y-up light-from vector → FB y-down L direction (toward surface)
        # If light *comes from* upper-left, L points down-right ≈ (-dir.x?);
        # L should be direction *from surface toward light* = opposite of rays.
        # Convention: ``direction`` = where light comes FROM in design coords.
        # Toward-light in design: +direction; FB y flip: (dx, -dy).
        dx, dy = self.direction
        Lx, Ly = float(dx), float(-dy)
        nlen = math.hypot(Lx, Ly) or 1.0
        Lx, Ly = Lx / nlen, Ly / nlen
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _distant_builder.setChild("image", sh)
        _distant_builder.setUniform("resolution", [float(w), float(h)])
        _distant_builder.setUniform("u_dir", [Lx, Ly])
        _distant_builder.setUniform("u_light_color", list(self.color))
        _distant_builder.setUniform("u_ambient", self.ambient)
        _distant_builder.setUniform("u_intensity", self.intensity)
        _distant_builder.setUniform("u_specular", self.specular)
        paint = skia.Paint(Shader=_distant_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class GodRays(PostEffect):
    """8-tap brightness-gated god rays, Plus-blended (SkSL).

    Args:
        weight: How much each sample adds (default 0.35).
        decay: Fall-off along the ray (default 0.86).
        exposure: Exposure (default 1.8).
        target: Ray source; ``None`` = the mouse.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        weight: float = 0.35,
        decay: float = 0.86,
        exposure: float = 1.8,
        target=None,
    ):
        self.weight = float(weight)
        self.decay = float(decay)
        self.exposure = float(exposure)
        self.target = target

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        lx, ly = _resolve_target_fb(self.target, w, h)
        canvas.drawImageRect(
            image,
            skia.Rect.MakeWH(w, h),
            skia.SamplingOptions(skia.FilterMode.kLinear),
        )
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _rays_builder.setChild("image", sh)
        _rays_builder.setUniform("resolution", [float(w), float(h)])
        _rays_builder.setUniform("u_light", [float(lx), float(ly)])
        _rays_builder.setUniform("u_weight", self.weight)
        _rays_builder.setUniform("u_decay", self.decay)
        _rays_builder.setUniform("u_exposure", self.exposure)
        paint = skia.Paint(
            Shader=_rays_builder.makeShader(),
            AntiAlias=False,
            BlendMode=skia.BlendMode.kPlus,
        )
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


_HAZE_KINDS = {
    "haze": {"amount": 6.0, "speed": 1.0, "bias": 1.0},
    "heat": {"amount": 10.0, "speed": 1.4, "bias": 1.35},
    "underwater": {"amount": 8.0, "speed": 0.55, "bias": 0.45},
}


class Haze(PostEffect):
    """Animated heat-shimmer warp (SkSL — mean-zero displacement, no overall shift).

    ``kind`` presets: ``\"haze\"`` (default), ``\"heat\"``, ``\"underwater\"``.
    Explicit ``amount`` / ``speed`` override the kind defaults when passed.

    Args:
        amount: Strength; ``None`` = the kind's default.
        speed: Animation speed; ``None`` = the kind's default.
        kind: ``"haze"`` (default) · ``"heat"`` · ``"underwater"`` — picks the defaults.
        bias: Warp offset; ``None`` = the kind's default.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        amount: Optional[float] = None,
        speed: Optional[float] = None,
        *,
        kind: str = "haze",
        bias: Optional[float] = None,
    ):
        k = expect_choice(kind, tuple(_HAZE_KINDS.keys()), what="Haze kind")
        preset = _HAZE_KINDS[k]
        self.kind = k
        self.amount = float(preset["amount"] if amount is None else amount)
        self.speed = float(preset["speed"] if speed is None else speed)
        self.bias = float(preset["bias"] if bias is None else bias)

    def _fx_cache_key(self) -> tuple:
        return (
            "haze", self.kind,
            round(self.amount, 2), round(self.speed, 2), round(self.bias, 2),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0:
            canvas.drawImage(image, 0, 0)
            return
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _haze_builder.setChild("image", sh)
        _haze_builder.setUniform("resolution", [float(w), float(h)])
        _haze_builder.setUniform("time", float(t) * self.speed)
        _haze_builder.setUniform("u_amount", float(self.amount))
        _haze_builder.setUniform("u_bias", float(self.bias))
        paint = skia.Paint(Shader=_haze_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Spotlight(PostEffect):
    """Directional cone spotlight (SkSL).

    Distinct from :class:`Lamp` (omni bubble) — light only inside the
    cone, and only up to ``range`` (soft hard-stop). ``origin`` / ``target``
    are design-space points (y-up). Defaults: top-center origin, mouse aim.

    Args:
        origin: Where the light comes from; ``None`` = top center.
        target: Where it points; ``None`` = the mouse.
        color: Light color (can pass 1 for stronger light).
        range: Cut-off distance in design units; ``None`` = 55 % of the short side.
        cone_angle: Cone opening in degrees (default 34).
        softness: Soft cone edge in degrees (default 14).
        ambient: Light outside the cone, 0–1 (default 0.1).
        intensity: Light strength in the cone (default 1.45).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        origin: Optional[Tuple[float, float]] = None,
        target=None,
        color=(1.15, 1.05, 0.85),
        range: Optional[float] = None,
        cone_angle: float = 34.0,
        softness: float = 14.0,
        ambient: float = 0.1,
        intensity: float = 1.45,
    ):
        self.origin = origin  # design (x,y) or None → top-center
        self.target = target  # design (x,y) or None → mouse
        self.color = resolve_rgb(color, default=(1.15, 1.05, 0.85))
        self.range = range  # max reach (design units); None → ~55% short side
        self.cone_angle = float(cone_angle)  # half-angle degrees (inner)
        self.softness = float(softness)      # outer rim softness degrees
        self.ambient = float(ambient)
        self.intensity = float(intensity)

    def _fx_cache_key(self) -> tuple:
        return (
            "spotlight",
            self.origin, self.target,
            round(self.cone_angle, 1), round(self.intensity, 2),
            self.range,
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        W, H = _design_size()
        if self.origin is None:
            ox, oy = W * 0.5, H * 0.95
        else:
            from .shapes import _xy_of
            ox, oy = _xy_of(self.origin, required=True)
        # Design y-up → FB y-down
        origin_fb = (ox / W * w, (1.0 - oy / H) * h)

        if self.target is None:
            aim_fb = _mouse_fb_xy(w, h)
        else:
            aim_fb = _resolve_target_fb(self.target, w, h)

        dx = aim_fb[0] - origin_fb[0]
        dy = aim_fb[1] - origin_fb[1]
        length = math.hypot(dx, dy)
        if length < 1e-3:
            dir_x, dir_y = 0.0, 1.0
        else:
            dir_x, dir_y = dx / length, dy / length

        half = math.radians(max(self.cone_angle, 1.0))
        soft = math.radians(max(self.softness, 0.5))
        cos_inner = math.cos(half)
        cos_outer = math.cos(min(half + soft, math.pi * 0.49))

        # Range: design units → FB scale (average of axes for roughly isotropic)
        if self.range is not None:
            sx = w / max(W, 1e-6)
            sy = h / max(H, 1e-6)
            rng = float(self.range) * 0.5 * (sx + sy)
        else:
            rng = float(min(w, h) * 0.55)

        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _spotlight_builder.setChild("image", sh)
        _spotlight_builder.setUniform("resolution", [float(w), float(h)])
        _spotlight_builder.setUniform("u_origin", [float(origin_fb[0]), float(origin_fb[1])])
        _spotlight_builder.setUniform("u_dir", [float(dir_x), float(dir_y)])
        _spotlight_builder.setUniform("u_color", list(self.color))
        _spotlight_builder.setUniform("u_range", float(rng))
        _spotlight_builder.setUniform("u_cone_inner", float(cos_inner))
        _spotlight_builder.setUniform("u_cone_outer", float(cos_outer))
        _spotlight_builder.setUniform("u_ambient", self.ambient)
        _spotlight_builder.setUniform("u_intensity", self.intensity)
        paint = skia.Paint(Shader=_spotlight_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Kaleidoscope(PostEffect):
    """Radial mirror kaleidoscope (SkSL).

    Args:
        segments: Mirror slices (default 8).
        zoom: Zoom (default 1).
        spin: Spin speed (default 0.15).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        segments: int = 8,
        zoom: float = 1.0,
        spin: float = 0.15,
    ):
        self.segments = max(2, int(segments))
        self.zoom = float(zoom)
        self.spin = float(spin)

    def _fx_cache_key(self) -> tuple:
        return ("kaleido", self.segments, round(self.zoom, 2), round(self.spin, 3))

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _kaleido_builder.setChild("image", sh)
        _kaleido_builder.setUniform("resolution", [float(w), float(h)])
        _kaleido_builder.setUniform("time", float(t))
        _kaleido_builder.setUniform("u_segments", float(self.segments))
        _kaleido_builder.setUniform("u_zoom", float(self.zoom))
        _kaleido_builder.setUniform("u_spin", float(self.spin))
        paint = skia.Paint(Shader=_kaleido_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


def draw_ripple_shader(
    canvas,
    image,
    w: float,
    h: float,
    *,
    center_uv: Tuple[float, float],
    progress: float,
    strength: float = 1.0,
    flash: float = 0.0,
    mode: float = 0.0,
    angle: float = 0.0,
    span: float = 1.0,
) -> None:
    """Fullscreen hit-ripple / linear wave + optional white flash (HitFeedback).

    ``span`` scales the warp radius (1 = ``ripple_at``; explosion shock is smaller).
    """
    sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
    _ripple_builder.setChild("image", sh)
    _ripple_builder.setUniform("resolution", [float(w), float(h)])
    _ripple_builder.setUniform("u_center", [float(center_uv[0]), float(center_uv[1])])
    _ripple_builder.setUniform("u_progress", float(progress))
    _ripple_builder.setUniform("u_strength", float(strength))
    _ripple_builder.setUniform("u_flash", float(flash))
    _ripple_builder.setUniform("u_mode", float(mode))
    _ripple_builder.setUniform("u_angle", float(angle))
    _ripple_builder.setUniform("u_span", float(max(span, 0.05)))
    paint = skia.Paint(Shader=_ripple_builder.makeShader(), AntiAlias=False)
    canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


def draw_glitch_shader(canvas, image, w, h, t, amount: float) -> None:
    """Fullscreen slice offsets + RGB split (HitFeedback)."""
    amp = float(amount)
    if amp < 0.01:
        canvas.drawImage(image, 0, 0)
        return
    sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
    _glitch_builder.setChild("image", sh)
    _glitch_builder.setUniform("resolution", [float(w), float(h)])
    _glitch_builder.setUniform("time", float(t))
    _glitch_builder.setUniform("u_amount", float(amp))
    paint = skia.Paint(Shader=_glitch_builder.makeShader(), AntiAlias=False)
    canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Crt(PostEffect):
    """CRT look: scanlines + chroma + vignette + mild barrel.

    Order: scanlines on the quality overlay plate, then a final SkSL pass
    applies barrel → chroma → corner vignette on that plate.

    Args:
        amount: Barrel distortion + vignette (default 1).
        chroma: RGB separation (default 1).
        scan: Scanlines (default 1).
    """

    _stage = PostEffectStage.SHADER
    # Scanline overlay rides the low-res Multiply path; barrel/chroma full-res.
    _quality_sensitive = True
    _has_quality_overlay = True

    def __init__(
        self,
        amount: float = 1.0,
        chroma: float = 1.0,
        scan: float = 1.0,
    ):
        self.amount = float(amount)
        self.chroma = float(chroma)
        self.scan = float(scan)

    def _fx_cache_key(self) -> tuple:
        return (
            "crt",
            round(self.amount, 2), round(self.chroma, 2), round(self.scan, 2),
        )

    def _is_active(self) -> bool:
        return bool(self.enabled) and (
            self.amount > 0 or self.chroma > 0 or self.scan > 0
        )

    def _draw_overlay(self, canvas, w, h, t) -> None:
        if self.scan > 0:
            draw_scanlines_multiply(canvas, w, h, self.scan)

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0 and self.chroma <= 0:
            canvas.drawImage(image, 0, 0)
            return
        try:
            W, _ = _design_size()
            sx = float(w) / max(W, 1.0)
        except Exception:
            sx = 1.0
        chroma_px = float(self.chroma) * 3.0 * sx
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _crt_builder.setChild("image", sh)
        _crt_builder.setUniform("resolution", [float(w), float(h)])
        _crt_builder.setUniform("u_amount", float(self.amount))
        _crt_builder.setUniform("u_chroma_px", float(chroma_px))
        paint = skia.Paint(Shader=_crt_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Vortex(PostEffect):
    """Swirl warp into a point (SkSL). ``target=None`` follows the mouse.

    Args:
        amount: Twist strength (default 1).
        spin: Automatic spin speed (default 1).
        target: Center: a point or an object (followed); ``None`` = the mouse.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        amount: float = 1.0,
        spin: float = 1.0,
        target=None,
    ):
        self.amount = float(amount)
        self.spin = float(spin)
        self.target = target

    def _fx_cache_key(self) -> tuple:
        return (
            "vortex",
            round(self.amount, 2), round(self.spin, 2), self.target,
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0:
            canvas.drawImage(image, 0, 0)
            return
        cx, cy = _resolve_target_fb(self.target, w, h)
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _vortex_builder.setChild("image", sh)
        _vortex_builder.setUniform("resolution", [float(w), float(h)])
        _vortex_builder.setUniform("u_center", [float(cx), float(cy)])
        _vortex_builder.setUniform("u_strength", float(self.amount))
        # Slow automatic spin so zero-arg still animates when mouse is still.
        spin = self.spin * (1.2 + 0.35 * math.sin(t * 0.7))
        _vortex_builder.setUniform("u_spin", float(spin))
        paint = skia.Paint(Shader=_vortex_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class ZoomBlur(PostEffect):
    """Radial streak / zoom blur toward a point (SkSL).

    ``center=None`` follows the mouse (same convention as Lamp / Vortex).

    Args:
        amount: Radial blur strength (default 0.5).
        center: Center: a point or an object (followed); ``None`` = the mouse.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self, amount: float = 0.5, center=None):
        self.amount = float(amount)
        self.center = center

    def _fx_cache_key(self) -> tuple:
        return ("zoomblur", round(self.amount, 2), self.center)

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0:
            canvas.drawImage(image, 0, 0)
            return
        cx, cy = _resolve_target_fb(self.center, w, h)
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        _zoomblur_builder.setChild("image", sh)
        _zoomblur_builder.setUniform("resolution", [float(w), float(h)])
        _zoomblur_builder.setUniform("u_center", [float(cx), float(cy)])
        _zoomblur_builder.setUniform("u_amount", float(self.amount))
        paint = skia.Paint(Shader=_zoomblur_builder.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


# ---------------------------------------------------------------------------
# Spatial color-grade / dancing wash (author classes)
# ---------------------------------------------------------------------------

_AXIS_NAMES = ("radial", "horizontal", "vertical")
_AXIS_ALIASES = {
    "radial": 0, "r": 0, "center": 0, "out": 0,
    "horizontal": 1, "h": 1, "x": 1, "lr": 1, "left": 1,
    "vertical": 2, "v": 2, "y": 2, "tb": 2, "top": 2,
}


def _parse_axis(value) -> Tuple[float, str]:
    """``"radial"`` / ``"horizontal"`` / ``"vertical"`` (short aliases such as
    ``"h"`` / ``"x"`` too), or the code 0 / 1 / 2.

    Anything else raises (A13): an unknown name used to fall back to radial
    silently, and a number wrapped (``axis=7`` meant horizontal) — a wrong
    axis looks plausible, so unlike an unknown colour (magenta + warning) it
    gives the author no signal.
    """
    from .state import as_payload
    raw = as_payload(value)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        from .validate import number
        n = number(raw, "ColorSweep axis")
        if n not in (0, 1, 2):
            raise ValueError(
                f"ColorSweep axis= code must be 0 (radial), 1 (horizontal) or 2 "
                f"(vertical), got {raw!r}. Prefer the name: axis=\"horizontal\"."
            )
        code = int(n)
        return float(code), _AXIS_NAMES[code]
    if not isinstance(raw, str):
        raise TypeError(
            f"ColorSweep axis= expected \"radial\", \"horizontal\" or \"vertical\", "
            f"got {type(raw).__name__} {raw!r}"
        )
    key = raw.strip().lower()
    if key not in _AXIS_ALIASES:
        from .validate import did_you_mean
        hint = did_you_mean(key, _AXIS_ALIASES)
        raise ValueError(
            f"ColorSweep axis={raw!r} is not an axis. Use \"radial\", "
            f"\"horizontal\" or \"vertical\".{(' ' + hint.strip()) if hint else ''}"
        )
    code = _AXIS_ALIASES[key]
    return float(code), _AXIS_NAMES[code]


def _palette_rgbs(
    colors,
    default: Sequence = ("cyan", "magenta", "gold"),
    *,
    nmax: int = 4,
) -> Tuple[list, int]:
    """Resolve 2–``nmax`` author colors to RGB triples (pad with last)."""
    if colors is None:
        seq = list(default)
    elif isinstance(colors, str):
        seq = [colors]
    else:
        try:
            seq = list(colors)
        except TypeError:
            seq = [colors]
    if not seq:
        seq = list(default)
    rgbs = [resolve_rgb(c, default=(1.0, 1.0, 1.0)) for c in seq[:nmax]]
    if len(rgbs) < 2:
        rgbs.append(rgbs[0])
    n = len(rgbs)
    while len(rgbs) < nmax:
        rgbs.append(rgbs[-1])
    return rgbs, n


def _bind_palette(builder, rgbs: Sequence, prefix: str = "u_c") -> None:
    for i, rgb in enumerate(rgbs):
        builder.setUniform(f"{prefix}{i}", [float(rgb[0]), float(rgb[1]), float(rgb[2])])


class ColorSweep(PostEffect):
    """Spatial color-grade along an axis — photo-filter 'more colorful'.

    ``axis``: ``\"radial\"`` (center→edge), ``\"horizontal\"`` (left→right),
    ``\"vertical\"`` (top→bottom). ``colors`` is 2–4 tints. ``saturation``
    boosts chroma before the wash; ``speed`` breathes the mix.

    Args:
        colors: 2–4 colors; ``None`` = the default palette.
        axis: ``"radial"`` (default) · ``"horizontal"`` · ``"vertical"``.
        amount: Blend strength (default 0.55).
        speed: Animation speed.
        saturation: Color saturation (default 0.45).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        colors=None,
        *,
        axis: Union[str, int, float] = "radial",
        amount: float = 0.55,
        speed: float = 1.0,
        saturation: float = 0.45,
    ):
        self._colors, self._n = _palette_rgbs(
            colors, default=("cyan", "magenta", "gold"), nmax=4,
        )
        self._axis_code, self._axis_name = _parse_axis(axis)
        self.amount = float(amount)
        self.speed = float(speed)
        self.saturation = float(saturation)

    @property
    def colors(self):
        """The 1–4 colors the sweep cycles through (any color forms; a Gradient / preset works). Writable."""
        return tuple(self._colors[: self._n])

    @colors.setter
    def colors(self, value) -> None:
        self._colors, self._n = _palette_rgbs(
            value, default=("cyan", "magenta", "gold"), nmax=4,
        )

    @property
    def axis(self) -> str:
        """Sweep direction: ``"radial"`` · ``"horizontal"`` · ``"vertical"`` (``"h"`` / ``"v"`` or 0 / 1 / 2 too)."""
        return self._axis_name

    @axis.setter
    def axis(self, value) -> None:
        self._axis_code, self._axis_name = _parse_axis(value)

    def _fx_cache_key(self) -> tuple:
        return (
            "colorsweep", self._axis_name, self._n,
            round(self.amount, 3), round(self.speed, 3),
            round(self.saturation, 3),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0:
            canvas.drawImage(image, 0, 0)
            return
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        b = _colorsweep_builder
        b.setChild("image", sh)
        b.setUniform("resolution", [float(w), float(h)])
        b.setUniform("time", float(t))
        _bind_palette(b, self._colors)
        b.setUniform("u_n", float(self._n))
        b.setUniform("u_axis", float(self._axis_code))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_sat", float(self.saturation))
        paint = skia.Paint(Shader=b.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class ColorWash(PostEffect):
    """Dancing plasma field that hue-shifts / colorizes the scene (2–3 colors).

    After-effect cousin of background :class:`~scena.background_kinds.Plasma`.

    Args:
        color: First color (default orchid).
        color2: Second color (default cyan).
        color3: Third color (default magenta).
        colors: 2–3 colors at once; replaces ``color`` / ``color2`` / ``color3``.
        amount: Strength (default 0.55).
        speed: Animation speed (default 0.55).
        saturation: Saturation (default 0.4).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        color=None,
        color2=None,
        color3=None,
        *,
        colors=None,
        amount: float = 0.55,
        speed: float = 0.55,
        saturation: float = 0.4,
    ):
        if colors is not None:
            pal = colors
        elif color is None and color2 is None and color3 is None:
            pal = ("orchid", "cyan", "magenta")
        else:
            pal = [
                color if color is not None else "orchid",
                color2 if color2 is not None else "cyan",
            ]
            if color3 is not None:
                pal.append(color3)
        self._colors, self._n = _palette_rgbs(
            pal, default=("orchid", "cyan", "magenta"), nmax=3,
        )
        self.amount = float(amount)
        self.speed = float(speed)
        self.saturation = float(saturation)

    @property
    def colors(self):
        """The 1–4 colors the wash blends (any color forms). Writable."""
        return tuple(self._colors[: self._n])

    @colors.setter
    def colors(self, value) -> None:
        self._colors, self._n = _palette_rgbs(
            value, default=("orchid", "cyan", "magenta"), nmax=3,
        )

    def _fx_cache_key(self) -> tuple:
        return (
            "plasmawash", self._n,
            round(self.amount, 3), round(self.speed, 3),
            round(self.saturation, 3),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0:
            canvas.drawImage(image, 0, 0)
            return
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        b = _plasmawash_builder
        b.setChild("image", sh)
        b.setUniform("resolution", [float(w), float(h)])
        b.setUniform("time", float(t))
        _bind_palette(b, self._colors)
        b.setUniform("u_n", float(self._n))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_sat", float(self.saturation))
        paint = skia.Paint(Shader=b.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class CosmicBloom(PostEffect):
    """Churning nebula color-shift plus bloom / glare on bright pixels.

    After-effect cousin of background Nebula / ChurningClouds, with a cheap
    4-tap glare extract. Two ``color`` / ``color2`` tints.

    Args:
        color: First nebula tint; ``None`` = default.
        color2: Second tint; ``None`` = default.
        amount: Strength (default 1).
        bloom: Glow on bright pixels (default 0.7).
        speed: Animation speed (default 1.2).
        saturation: Color shift saturation (default 0.35).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(
        self,
        color=None,
        color2=None,
        *,
        amount: float = 1.0,
        bloom: float = 0.7,
        speed: float = 1.2,
        saturation: float = 0.35,
    ):
        self.color = resolve_rgb(color, default=(0.75, 0.35, 0.95))
        self.color2 = resolve_rgb(color2, default=(0.25, 0.75, 1.0))
        self.amount = float(amount)
        self.bloom = float(bloom)
        self.speed = float(speed)
        self.saturation = float(saturation)

    def _fx_cache_key(self) -> tuple:
        return (
            "nebulabloom",
            round(self.amount, 3), round(self.bloom, 3),
            round(self.speed, 3), round(self.saturation, 3),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if self.amount <= 0 and self.bloom <= 0:
            canvas.drawImage(image, 0, 0)
            return
        sh = image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp)
        b = _nebulabloom_builder
        b.setChild("image", sh)
        b.setUniform("resolution", [float(w), float(h)])
        b.setUniform("time", float(t))
        b.setUniform("u_c0", list(self.color))
        b.setUniform("u_c1", list(self.color2))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_bloom", float(self.bloom))
        b.setUniform("u_sat", float(self.saturation))
        paint = skia.Paint(Shader=b.makeShader(), AntiAlias=False)
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)
