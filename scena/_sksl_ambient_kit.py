"""
Compiled-once SkSL for ambient kit backgrounds (internal).

Cheap 2-octave shaders intended for half-res / low-res plate draw.
"""
from __future__ import annotations

from ._sksl_backdrop import _compile_runtime, draw_shader_rect  # noqa: F401

# ---------------------------------------------------------------------------
# ChurningClouds — warp-phase churn, 2-octave FBM (low-res plate)
# ---------------------------------------------------------------------------
_CHURNINGCLOUDS_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform half3 u_color2;
uniform float u_amount;
uniform float u_speed;
uniform float u_scale_pat;
uniform float u_contrast;
uniform float u_alpha;
uniform float u_seed;

// Lattice hash: weights (127, 311) / 1024 are exact in float32, so n and the
// corner sums are exact and every pixel gets bit-identical corner hashes (no
// cell seams under FMA / reassociation), and |sin arg| stays < 2^14 (Intel
// GPU sin() collapses at |x| >= 2^17). See Effect System Design, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}
// u_seed -> exact lattice-index shift (k / 1024, k < 4096), set once in main().
float g_seed_n;
float noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float n = dot(i, float2(0.1240234375, 0.3037109375)) + g_seed_n;
    return mix(mix(hash1(n), hash1(n + 0.1240234375), u.x),
               mix(hash1(n + 0.3037109375), hash1(n + 0.427734375), u.x), u.y);
}
float fbm2(float2 p) {
    float2 q = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
    return 0.65 * noise(p) + 0.35 * noise(q * 2.05 + float2(11.0, 7.0));
}

half4 main(float2 coord) {
    g_seed_n = floor(fract(u_seed * 0.7548776662) * 4096.0) * (1.0 / 1024.0);
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float2 uv = p / min_res;
    float t = time * u_speed * 0.12;
    float breathe = 1.0 + 0.08 * sin(t * 0.65);
    float wr = t * 0.25;
    float wc = cos(wr), ws = sin(wr);
    float sc = mix(0.8, 2.5, clamp(u_scale_pat, 0.2, 2.0) * 0.5) * breathe;
    float2 q = float2(wc * uv.x - ws * uv.y, ws * uv.x + wc * uv.y) * sc;
    float phase = t * 0.9;
    float2 w = float2(fbm2(q + float2(phase, 0.2)), fbm2(q.yx + float2(0.3, phase) + 3.0));
    q += (w - 0.5) * 1.2;
    float dens = fbm2(q + phase * 0.05);
    float ridge = 1.0 - abs(noise(q * 1.55 + w) * 2.0 - 1.0);
    ridge = ridge * ridge * ridge;
    float ctr = mix(0.7, 2.0, clamp(u_contrast, 0.0, 2.0) * 0.5);
    float mass = smoothstep(0.3, 0.72, pow(dens, ctr));
    float core = smoothstep(0.48, 0.9, dens + ridge * 0.4);
    float ink = clamp((mass * 0.72 + ridge * 0.4 + core * 0.3) * u_amount, 0.0, 1.0);
    half3 col = mix(half3(u_color) * half3(0.18, 0.12, 0.3), half3(u_color), half(mass));
    col = mix(col, half3(u_color2), half(core * 0.7));
    float af = clamp(ink * clamp(u_alpha, 0.0, 1.0) * 0.9, 0.0, 0.92);
    return half4(col * half(af), half(af));
}
"""

# ---------------------------------------------------------------------------
# FilamentField — ridged filaments, 2-octave + cheap hotspot (low-res plate)
# ---------------------------------------------------------------------------
_FILAMENTFIELD_SKSL = """
uniform float2 resolution;
uniform float time;
uniform float2 u_offset;
uniform float u_scale;
uniform float u_rotation;
uniform half3 u_color;
uniform float u_amount;
uniform float u_speed;
uniform float u_contrast;
uniform float u_alpha;
uniform float u_seed;

// Lattice hash: weights (127, 311) / 1024 are exact in float32, so n and the
// corner sums are exact and every pixel gets bit-identical corner hashes (no
// cell seams under FMA / reassociation), and |sin arg| stays < 2^14 (Intel
// GPU sin() collapses at |x| >= 2^17). See Effect System Design, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}
// u_seed -> exact lattice-index shift (k / 1024, k < 4096), set once in main().
float g_seed_n;
float noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float n = dot(i, float2(0.1240234375, 0.3037109375)) + g_seed_n;
    return mix(mix(hash1(n), hash1(n + 0.1240234375), u.x),
               mix(hash1(n + 0.3037109375), hash1(n + 0.427734375), u.x), u.y);
}
float fbm2(float2 p) {
    float2 q = float2(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y);
    return 0.65 * noise(p) + 0.35 * noise(q * 2.1 + float2(3.0, 8.0));
}

half4 main(float2 coord) {
    g_seed_n = floor(fract(u_seed * 0.7548776662) * 4096.0) * (1.0 / 1024.0);
    float2 center = resolution * 0.5;
    float2 p = coord - center - u_offset;
    float c = cos(u_rotation);
    float s = sin(u_rotation);
    p = float2(c * p.x - s * p.y, s * p.x + c * p.y);
    p /= max(u_scale, 0.0001);
    float min_res = max(min(resolution.x, resolution.y), 1.0);
    float2 uv = p / min_res;
    float t = time * u_speed * 0.15;
    float2 q = uv * 2.2 + float2(t * 0.2, -t * 0.15);
    float ridge = 1.0 - abs(fbm2(q) * 2.0 - 1.0);
    float ctr = mix(2.0, 6.0, clamp(u_contrast, 0.0, 2.0) * 0.5);
    float fil = pow(ridge, ctr);
    float hotspot = pow(max(sin(t * 0.7 + noise(uv * 1.1) * 6.0), 0.0), 8.0);
    float ink = clamp((fil * 0.85 + hotspot * 0.55) * u_amount * 0.55, 0.0, 1.0);
    half3 col = mix(u_color * half3(0.2, 0.3, 0.55), mix(u_color, half3(0.85, 0.95, 1.0), half(0.5)), half(fil));
    col = mix(col, half3(1.0, 0.95, 0.9), half(hotspot));
    float af = clamp(ink * clamp(u_alpha, 0.0, 1.0), 0.0, 0.85);
    return half4(col * half(af), half(af));
}
"""

churningclouds_builder = _compile_runtime(_CHURNINGCLOUDS_SKSL, "ambient.ChurningClouds")
filamentfield_builder = _compile_runtime(_FILAMENTFIELD_SKSL, "ambient.FilamentField")

__all__ = [
    "draw_shader_rect",
    "churningclouds_builder",
    "filamentfield_builder",
]
