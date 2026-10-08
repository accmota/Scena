"""
Curated shape-local RuntimeEffect shaders (compile once).

Used by ProceduralFill and shape visuals. Authors never write SkSL.
"""
from __future__ import annotations

from typing import Dict
import math

import skia

_SRCS: Dict[str, str] = {}

# Original cool animated "water" field — kept as Swell (not platform water).
_SRCS["swell"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    // Origin-centered paint coords → 0..1 UV (center = 0.5)
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time + u_seed;
    float w1 = sin(uv.x * 9.0 + t * 2.1);
    float w2 = sin(uv.x * 15.0 - t * 1.4 + uv.y * 3.0);
    float crest = 0.5 + 0.5 * sin(uv.y * 6.0 + w1 * 0.8 + w2 * 0.4);
    float foam = smoothstep(0.72, 0.95, crest) * u_amount;
    half3 deep = half3(0.05, 0.18, 0.42);
    half3 shallow = half3(0.15, 0.55, 0.75);
    half3 col = mix(deep, shallow, half(crest));
    col = mix(col, half3(0.85, 0.95, 1.0), half(foam * 0.65));
    return half4(col, 1.0);
}
"""

# Side-view water volume only (masking to below the surface is done in Water recipe).
_SRCS["water_side"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    // Origin-centered paint coords → 0..1 UV (center = 0.5)
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 1.1 + u_seed;

    float n = sin(uv.x * 14.0 + t * 1.4) * cos(uv.y * 9.0 - t * 0.9);
    n += 0.45 * sin((uv.x * 1.7 + uv.y) * 18.0 - t);
    n = 0.5 + 0.5 * n;

    // Depth from free surface: more opaque deeper (lower y in local UV when mask is water body)
    float depth = clamp(1.0 - uv.y, 0.0, 1.0);
    half3 deep = half3(0.02, 0.18, 0.42);
    half3 midc = half3(0.08, 0.45, 0.68);
    half3 near = half3(0.25, 0.72, 0.88);
    half3 col = mix(near, midc, half(depth));
    col = mix(col, deep, half(depth * depth * 0.7));

    float shafts = pow(max(n, 0.0), 3.0) * u_amount * 0.3;
    col += half3(0.12, 0.32, 0.38) * half(shafts);

    // Thin bright band near surface (high uv.y when water path is filled bottom-up)
    float surf = smoothstep(0.72, 1.0, uv.y);
    col = mix(col, half3(0.55, 0.92, 1.0), half(surf * 0.5 * u_amount));

    float a = (0.38 + 0.4 * depth) * (0.75 + 0.25 * u_amount);
    a = clamp(a, 0.22, 0.9);
    return half4(col * half(a), half(a));
}
"""

_SRCS["water_top"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    // Origin-centered paint coords → 0..1 UV (center = 0.5)
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 0.85 + u_seed;
    float n = sin((uv.x + t * 0.12) * 12.0) * cos((uv.y - t * 0.1) * 11.0);
    n += 0.45 * sin((uv.x - uv.y) * 16.0 + t * 1.2);
    n = 0.5 + 0.5 * n;
    half3 a = half3(0.05, 0.24, 0.42);
    half3 b = half3(0.18, 0.55, 0.72);
    half3 col = mix(a, b, half(n));
    float highlight = smoothstep(0.62, 0.95, n) * u_amount * 0.4;
    col += half3(highlight * 0.9, highlight, highlight * 0.85);
    return half4(col, half(0.7));
}
"""

# Animated fire fill for shapes — turbulent heat field, no hard sparks plateaus.
# Stays in red→orange; yellow only in sparse hot cores (not full-body solid).
_SRCS["fire"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    // Origin-centered paint coords → 0..1 UV (center = 0.5)
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 1.25 + u_seed;

    // Domain-warped rising advection (fills whole body)
    float2 q = uv;
    q.y -= t * 0.35;
    q.x += 0.08 * sin(q.y * 7.0 + t * 1.6);

    float n = 0.0;
    n += 0.50 * sin(q.x * 7.0 + q.y * 9.0 + t * 1.7);
    n += 0.30 * sin(q.x * 14.0 - q.y * 11.0 - t * 2.4);
    n += 0.20 * sin((q.x + q.y) * 22.0 + t * 3.1);
    n = 0.5 + 0.5 * n;

    // Soft vertical structure within the *shape* (0 bottom → 1 top of UV cell)
    // Cooler dark base, hotter mid tongue — keep heat mid-range so we don't wash yellow
    float vertical = mix(0.35, 1.0, smoothstep(0.0, 0.85, uv.y));
    float heat = n * vertical * u_amount;
    // Compress into a fire-friendly range. amount=1 keeps the old 0.82 ceiling;
    // amount>1 opens a little more amber without full-white plateaus.
    float heat_max = 0.82 + 0.13 * clamp(u_amount - 1.0, 0.0, 1.0);
    heat = clamp(heat * 0.85, 0.05, heat_max);
    heat = pow(heat, 1.05);

    // Color ramp: dark red → red → orange → amber (not full white plateaus)
    half3 c0 = half3(0.08, 0.01, 0.0);
    half3 c1 = half3(0.75, 0.08, 0.0);
    half3 c2 = half3(1.0, 0.35, 0.02);
    half3 c3 = half3(1.0, 0.7, 0.12);
    half3 col = mix(c0, c1, half(smoothstep(0.05, 0.28, heat)));
    col = mix(col, c2, half(smoothstep(0.25, 0.55, heat)));
    col = mix(col, c3, half(smoothstep(0.5, 0.82, heat)));

    // Slight flicker, not spark particles
    float flick = 0.88 + 0.12 * sin(t * 9.0 + n * 6.0);
    col *= half(flick);

    float a = clamp(0.55 + heat * 0.55, 0.45, 1.0);
    return half4(col * half(a), half(a));
}
"""

# Organic fluid membrane: energy concentrated on the rim, translucent center.
_SRCS["fluid"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    // Origin-centered paint coords → 0..1 UV (center = 0.5)
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.9 + u_seed;

    float ang = atan(p.y, p.x);
    float rr = length(p) * 2.0;  // 0 = center, ~1 = rim

    // Organic rim deformation
    float blob = sin(ang * 3.0 + t * 1.7) * 0.07
               + sin(ang * 5.0 - t * 2.3) * 0.04
               + sin(rr * 10.0 - t * 3.0) * 0.05;

    // Soft ring weight: near-zero at center → peak near rim
    float ring = smoothstep(0.12, 0.78, rr + blob)
               * (1.0 - smoothstep(0.88 + blob * 0.5, 1.12, rr));

    float n = sin(uv.x * 16.0 + t * 2.1) * cos(uv.y * 14.0 - t * 1.6);
    n = 0.5 + 0.5 * n;
    float fil = pow(max(n * 0.65 + ring * 0.85, 0.0), 1.8) * u_amount;

    half3 deep = half3(0.04, 0.12, 0.4);
    half3 midc = half3(0.2, 0.75, 0.95);
    half3 hot = half3(0.8, 0.98, 1.0);
    half3 col = mix(deep, midc, half(fil));
    col = mix(col, hot, half(pow(fil, 2.2) * 0.7));

    // Center nearly clear; rim readable
    float centerFade = mix(0.08, 1.0, smoothstep(0.15, 0.82, rr));
    float alpha = clamp(ring * (0.4 + fil * 0.55) * centerFade, 0.02, 0.9);
    return half4(col * half(alpha), half(alpha));
}
"""

# Animated plasma disk interior (_OrbHalo / related recipes).
# Paint coords are shape-local (origin = shape center).
_SRCS["plasma_disk"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 1.8 + u_seed;
    float r = length(p) * 2.0;

    float n = sin(p.x * 12.0 + t * 2.4) * cos(p.y * 11.0 - t * 1.9);
    n += 0.5 * sin((p.x + p.y) * 18.0 - t * 3.2);
    n = 0.5 + 0.5 * n;
    float ang = atan(p.y, p.x);
    if (r < 1e-4) { ang = 0.0; }
    float swirl = sin(ang * 4.0 + t * 2.5 + r * 6.0);
    float heat = pow(max((1.0 - r * 0.85) * (0.45 + 0.55 * n) * (0.7 + 0.3 * swirl), 0.0), 1.15);
    heat *= u_amount;

    half3 cold = half3(0.15, 0.02, 0.35);
    half3 midc = half3(0.7, 0.25, 1.0);
    half3 core = half3(1.0, 0.85, 1.0);
    half3 col = mix(cold, midc, half(smoothstep(0.0, 0.5, heat)));
    col = mix(col, core, half(smoothstep(0.45, 1.0, heat)));
    float a = clamp(0.25 + heat * 0.85, 0.12, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Classic projectile plasma (Bolt style=core) — centered swirl ball, older recipe.
_SRCS["plasma_core"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 1.8 + u_seed;
    float r = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (r < 1e-4) { ang = 0.0; }

    float n = sin(p.x * 12.0 + t * 2.4) * cos(p.y * 11.0 - t * 1.9);
    n += 0.5 * sin((p.x + p.y) * 18.0 - t * 3.2);
    n = 0.5 + 0.5 * n;
    float swirl = sin(ang * 4.0 + t * 2.5 + r * 6.0);
    float heat = pow(max((1.0 - r * 0.85) * (0.45 + 0.55 * n) * (0.7 + 0.3 * swirl), 0.0), 1.15);
    heat *= u_amount;

    half3 cold = half3(0.08, 0.0, 0.28);
    half3 midc = half3(0.45, 0.55, 1.0);
    half3 core = half3(0.9, 0.95, 1.0);
    half3 col = mix(cold, midc, half(smoothstep(0.0, 0.5, heat)));
    col = mix(col, core, half(smoothstep(0.45, 1.0, heat)));
    float a = clamp(0.2 + heat * 0.9 * (1.05 - r * 0.4), 0.1, 0.98);
    return half4(col * half(a), half(a));
}
"""

# Filamentary plasma core — rotating spokes around center (Bolt style=filaments).
_SRCS["plasma_filaments"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 2.4 + u_seed;
    float r = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (r < 1e-4) { ang = 0.0; }

    float spokes = clamp(3.0 + u_amount * 0.667, 3.0, 11.0);
    float fil = sin(ang * spokes + t * 3.5 - r * 8.0)
              + 0.5 * sin(ang * (spokes * 1.8) - t * 5.0 + r * 14.0);
    fil = 0.5 + 0.5 * fil;
    float core = exp(-r * r * 2.8);
    float shell = exp(-pow(max(r - 0.55, 0.0) * 3.5, 2.0));
    float heat = (core * 1.1 + shell * 0.65 * fil + fil * 0.25 * (1.0 - r)) * 0.65;
    heat = pow(max(heat, 0.0), 0.9);

    half3 cold = half3(0.05, 0.0, 0.25);
    half3 midc = half3(0.35, 0.55, 1.0);
    half3 hot = half3(0.85, 0.95, 1.0);
    half3 white = half3(1.0, 1.0, 1.0);
    half3 col = mix(cold, midc, half(smoothstep(0.0, 0.35, heat)));
    col = mix(col, hot, half(smoothstep(0.3, 0.7, heat)));
    col = mix(col, white, half(smoothstep(0.65, 1.1, heat)));

    float a = clamp(heat * 1.35 * (1.05 - r * 0.55), 0.0, 1.0);
    return half4(col * half(a), half(a));
}
"""

# Tesla-ball radial arcs (bolts from center).
_SRCS["plasma_tesla"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 2.0 + u_seed;
    float r = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (r < 1e-4) { ang = 0.0; }

    // Several rotating sectors become bright bolts
    float bolt = 0.0;
    for (int k = 0; k < 5; ++k) {
        float phase = float(k) * 1.2566 + t * (1.1 + 0.17 * float(k));
        float a = ang - phase;
        // wrap-ish via sin
        float gap = abs(sin(a * 0.5));
        float wiggle = sin(r * 18.0 - t * 8.0 + float(k) * 3.0) * 0.04;
        float line = 1.0 - smoothstep(0.0, 0.06 + wiggle, gap);
        // fade near core slightly, brightest mid-ray
        float along = smoothstep(0.08, 0.25, r) * (1.0 - smoothstep(0.75, 1.05, r));
        bolt = max(bolt, line * along);
    }
    float glow = exp(-r * r * 1.6) * 0.45;
    float heat = (bolt * 1.4 + glow) * u_amount;

    half3 col = mix(half3(0.1, 0.2, 0.6), half3(0.5, 0.85, 1.0), half(heat));
    col = mix(col, half3(1.0, 1.0, 1.0), half(pow(max(bolt, 0.0), 2.0)));
    float a = clamp(heat * 1.2, 0.0, 1.0);
    a = max(a, glow * 0.5);
    return half4(col * half(a), half(a));
}
"""


# Noise / vortex / wipe silhouette mask for shape dissolve.
# u_progress 0 = fully visible, 1 = fully erased. Used as DstIn (white × alpha).
# u_style: 0 = noise, 1 = vortex, 2 = wipe. u_angle (rad) = wipe dir / vortex spin bias.
# Vortex must not use atan for the dig field — branch cut creates a hard radial seam.
_SRCS["dissolve"] = """
uniform float2 u_resolution;
uniform float u_progress;
uniform float u_seed;
uniform float u_style;
uniform float u_angle;

// Lattice hash: weights (127, 311) / 1024 are exact in float32, so n and the
// corner sums are exact and every pixel gets bit-identical corner hashes (no
// cell seams under FMA / reassociation), and |sin arg| stays < 2^14 (Intel
// GPU sin() collapses at |x| >= 2^17). See Effect System Design, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

float value_noise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float n = dot(i, float2(0.1240234375, 0.3037109375));
    return mix(mix(hash1(n), hash1(n + 0.1240234375), u.x),
               mix(hash1(n + 0.3037109375), hash1(n + 0.427734375), u.x), u.y);
}

// Continuous multipole cos(n*theta) via complex powers (no atan / no branch cut).
float cos2_theta(float2 p) {
    float r2 = max(dot(p, p), 1e-8);
    return (p.x * p.x - p.y * p.y) / r2;
}

float cos3_theta(float2 p) {
    float r2 = max(dot(p, p), 1e-8);
    float r3 = r2 * sqrt(r2);
    return (p.x * p.x * p.x - 3.0 * p.x * p.y * p.y) / r3;
}

half4 main(float2 coord) {
    float2 uv = coord / max(u_resolution, float2(1.0));
    float thr = clamp(u_progress, 0.0, 1.0);
    float keep = 1.0;
    float edge = 0.07;
    // Keep seed moderate so value-noise floors stay stable
    float seed = fract(u_seed * 0.017 + u_seed * 0.0013) * 10.0;

    if (u_style < 0.5) {
        // Noise dig
        float2 p = uv * 6.5 + float2(seed * 1.7, seed * 0.9);
        float n = 0.0;
        n += 0.50 * value_noise(p);
        n += 0.30 * value_noise(p * 2.1 + 3.1);
        n += 0.20 * value_noise(p * 4.3 - 1.7);
        n = clamp(n, 0.0, 1.0);
        keep = smoothstep(thr - edge, thr + edge, n);
        keep *= 1.0 - smoothstep(0.90, 1.0, thr);
    } else if (u_style < 1.5) {
        // Vortex: spinning multi-arm disk that shrinks to the pivot.
        // Uses only continuous multipoles (no atan) so there is no radial seam.
        float2 q = uv - float2(0.5);
        float rr = length(q) * 2.15;  // ~0 center, ~1 at typical shape rim
        // Primary spin (arms + disc)
        float spin = thr * 12.5 + u_angle + seed * 0.7;
        float cs = cos(spin);
        float sn = sin(spin);
        float2 p = float2(cs * q.x - sn * q.y, sn * q.x + cs * q.y);
        float a3 = cos3_theta(p);
        // Counter-spin 2-arm field for a deeper swirl
        float spin2 = -thr * 18.0 + seed * 1.1 + 0.9;
        float cs2 = cos(spin2);
        float sn2 = sin(spin2);
        float2 p2 = float2(cs2 * q.x - sn2 * q.y, sn2 * q.x + cs2 * q.y);
        float a2 = cos2_theta(p2);
        // Spiralization of multipoles with radius → clear arm trails
        float swirl = 0.5 + 0.5 * sin(a3 * 2.2 + rr * (5.5 + thr * 6.0) - thr * 8.0);
        float lobe = clamp(0.55 * a3 + 0.30 * a2 + 0.35 * (swirl * 2.0 - 1.0), -1.0, 1.0);
        lobe = 0.5 + 0.5 * lobe;
        // Outer remaining radius shrinks; deep scallops read as spinning arms
        float outer = (1.0 - thr) * 1.25;
        float wave = 0.38 * (lobe - 0.5) * (0.55 + 0.45 * (1.0 - thr));
        float rim = outer + wave;
        keep = 1.0 - smoothstep(rim - 0.07, rim + 0.07, rr);
        // Arms open holes that spin in as progress rises
        float arm_cut = smoothstep(0.05, 0.85, thr) * pow(1.0 - lobe, 1.35) * 0.92;
        keep *= 1.0 - arm_cut * smoothstep(0.02, max(outer, 0.12) + 0.15, rr);
        // Soft core punch late in the dissolve
        keep *= 1.0 - smoothstep(0.62, 1.0, thr) * (1.0 - smoothstep(0.0, 0.28, rr));
        // Fine grit
        float n2 = value_noise(p * 9.0 + float2(seed, -seed));
        keep *= mix(1.0, smoothstep(0.12, 0.88, n2), 0.18 * thr);
        keep *= 1.0 - smoothstep(0.90, 1.0, thr);
    } else {
        // Directional wipe along u_angle (0 = +x): low-along side digs first
        float ca = cos(u_angle);
        float sa = sin(u_angle);
        float2 d = uv - float2(0.5);
        float along = d.x * ca + d.y * sa + 0.5;  // 0..1 across band
        keep = smoothstep(thr - 0.06, thr + 0.06, along);
        keep *= 1.0 - smoothstep(0.94, 1.0, thr);
    }
    return half4(1.0, 1.0, 1.0, half(clamp(keep, 0.0, 1.0)));
}
"""


# Brushed metal — grain in local paint coords (rotates with the shape).
# Specular crawl stays world-locked via u_rot + u_origin + shared u_light.
_SRCS["metal"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform float u_rot;       // shape CTM rotation (degrees)
uniform float2 u_origin;   // shape center in world/design space
uniform float u_light;     // shared specular direction (degrees)

half4 main(float2 coord) {
    float rad = radians(u_rot);
    float c = cos(rad);
    float s = sin(rad);
    float2 world = float2(c * coord.x - s * coord.y, s * coord.x + c * coord.y) + u_origin;

    float2 uv = coord * 0.007;
    float t = u_time * 0.55 + u_seed;
    float la = radians(u_light);
    float lx = cos(la);
    float ly = sin(la);
    float along = world.x * lx + world.y * ly;

    float brush = sin((uv.x * 1.4 + uv.y * 0.6) * 220.0 + t * 1.1) * 0.42
                + sin((uv.x - uv.y) * 380.0 - t * 0.55) * 0.28
                + sin((uv.x * 2.2 - uv.y * 0.85) * 640.0 + t * 0.9) * 0.18;
    brush = clamp(0.5 + 0.62 * brush, 0.0, 1.0);
    float band = pow(max(sin(along * 0.031 - t * 1.6), 0.0), 14.0);
    float band2 = pow(max(sin(along * 0.052 + t * 2.1), 0.0), 20.0);

    half3 base = half3(0.50, 0.52, 0.56);
    half3 dark = half3(0.16, 0.18, 0.22);
    half3 light = half3(0.92, 0.93, 0.96);
    half3 col = mix(dark, base, half(brush));
    col = mix(col, light, half(band * 0.85 * u_amount));
    col = mix(col, half3(1.0, 1.0, 1.0), half(band2 * 0.55 * u_amount));
    return half4(col, 1.0);
}
"""

# Recolorable liquid field (WaveFill) — any tint via u_color.
# Paint coords are shape-local (origin = shape center). u_resolution = design diameter.
_SRCS["wave"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 1.1 + u_seed;
    float n = sin(uv.x * 14.0 + t * 1.4) * cos(uv.y * 9.0 - t * 0.9);
    n += 0.45 * sin((uv.x * 1.7 + uv.y) * 18.0 - t);
    n = 0.5 + 0.5 * n;
    float depth = clamp(1.0 - uv.y, 0.0, 1.0);
    half3 base = u_color;
    half3 deep = base * half3(0.25, 0.35, 0.55);
    half3 midc = base * half3(0.55, 0.75, 0.95);
    half3 near = mix(base, half3(1.0, 1.0, 1.0), half(0.35));
    half3 col = mix(near, midc, half(depth));
    col = mix(col, deep, half(depth * depth * 0.7));
    float shafts = pow(max(n, 0.0), 3.0) * u_amount * 0.35;
    col += base * half(shafts * 0.55);
    float surf = smoothstep(0.72, 1.0, uv.y);
    col = mix(col, near * half3(1.15, 1.1, 1.05), half(surf * 0.45 * u_amount));
    float a = (0.38 + 0.4 * depth) * (0.75 + 0.25 * u_amount);
    a = clamp(a, 0.22, 0.92);
    return half4(col * half(a), half(a));
}
"""

# Vertical aurora ribbons (AuroraFill) — recolorable, readable coverage.
_SRCS["aurora"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 0.85 + u_seed;
    float x = uv.x + 0.08 * sin(uv.y * 6.0 + t * 1.4);
    float ribbon = 0.0;
    ribbon += 0.55 * pow(max(sin(x * 9.0 + t * 1.6), 0.0), 3.0);
    ribbon += 0.40 * pow(max(sin(x * 15.0 - t * 2.1 + 1.2), 0.0), 4.0);
    ribbon += 0.30 * pow(max(sin((x + uv.y * 0.3) * 18.0 + t * 2.8), 0.0), 5.0);
    // Soft full-body veil so the field is never empty
    float baseV = 0.28 + 0.35 * (0.5 + 0.5 * sin(uv.y * 4.0 - t));
    float heat = clamp((ribbon * 0.85 + baseV) * u_amount, 0.0, 1.0);
    half3 base = u_color;
    half3 deep = base * half3(0.25, 0.35, 0.45);
    half3 bright = mix(base, half3(0.9, 1.0, 0.95), half(0.45));
    half3 col = mix(deep, base, half(smoothstep(0.1, 0.55, heat)));
    col = mix(col, bright, half(smoothstep(0.45, 0.95, heat)));
    float a = clamp(0.35 + heat * 0.65, 0.3, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Fake sphere lighting (Sphere look) — analytic normal + soft specular.
# Paint coords are shape-local (origin = shape center). u_resolution ≈ diameter.
_SRCS["sphere"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = (uv - float2(0.5)) * 2.0;
    float r2 = dot(p, p);
    // Soft edge instead of hard discard so non-circle silhouettes still get coverage
    float edge = 1.0 - smoothstep(0.92, 1.15, r2);
    float z = sqrt(max(1.0 - min(r2, 1.0), 0.0));
    float3 n = float3(p.x, p.y, z);
    float t = u_time * 0.4 + u_seed;
    float3 L = normalize(float3(0.45 + 0.15 * sin(t), 0.35 + 0.1 * cos(t * 0.7), 0.85));
    float ndl = max(dot(n, L), 0.0);
    float3 H = normalize(L + float3(0.0, 0.0, 1.0));
    float spec = pow(max(dot(n, H), 0.0), 28.0) * 0.55 * u_amount;
    float rim = pow(1.0 - z, 2.0) * 0.4;
    half3 base = u_color;
    half3 ambient = base * half3(0.22, 0.24, 0.28);
    half3 diffuse = base * half(0.4 + 0.6 * ndl);
    half3 col = ambient + diffuse;
    col += half3(1.0, 1.0, 1.0) * half(spec);
    col += base * half(rim);
    float a = edge * 0.98;
    return half4(col * half(a), half(a));
}
"""

# ---------------------------------------------------------------------------
# Shield orb interiors (Circle/Ellipse Looks). Fixed art palettes.
# UV: uv = 0.5 + coord / u_resolution; p centered; r ≈ 0 center … ~1 rim.
# ---------------------------------------------------------------------------

# Iridescent bubble: hollow center, lime/yellow blotches, green membrane rim.
_SRCS["shield_bubble"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.95 + u_seed;
    float rr = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (rr < 1e-4) { ang = 0.0; }

    float blob = sin(ang * 3.0 + t * 1.4) * 0.06
               + sin(ang * 5.0 - t * 1.9) * 0.04
               + sin(rr * 8.0 - t * 2.2) * 0.05;
    float rim = smoothstep(0.45, 0.82, rr + blob)
              * (1.0 - smoothstep(0.92 + blob * 0.4, 1.08, rr));

    float n = sin(p.x * 9.0 + t * 1.5) * cos(p.y * 8.0 - t * 1.2);
    n += 0.55 * sin((p.x * 0.7 + p.y) * 14.0 + t * 0.9);
    n = 0.5 + 0.5 * n;
    float blotch = pow(max(n, 0.0), 2.4) * rim * u_amount;

    // lime → yellow film; slightly below max green (toxic, not fluorescent)
    half3 lime = half3(0.26, 0.84, 0.07);
    half3 yell = half3(0.78, 0.92, 0.10);
    half3 film = half3(0.38, 0.82, 0.18);
    half3 col = mix(lime, yell, half(smoothstep(0.2, 0.75, blotch)));
    col = mix(col, film, half(pow(rim, 2.5) * 0.22 * (1.0 - blotch * 0.5)));

    float centerClear = mix(0.04, 1.0, smoothstep(0.25, 0.78, rr));
    float a = clamp(rim * (0.22 + blotch * 1.2) * centerClear, 0.0, 0.92);
    return half4(col * half(a), half(a));
}
"""

# Starry nebula: multi-stop palette via u_deep / u_mid / u_star / u_shell.
_SRCS["shield_stars"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_deep;
uniform half3 u_mid;
uniform half3 u_star;
uniform half3 u_shell;

// Per-cell hash: weights (127, 311) / 1024 keep |sin arg| small (Intel GPU sin()
// collapses at |x| >= 2^17). See Effect System Design §9, "Noise hash".
float hash21(float2 p) {
    return fract(sin(dot(p, float2(0.1240234375, 0.3037109375))) * 43758.5453);
}

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.55 + u_seed;
    float rr = length(p) * 2.0;
    float edge = 1.0 - smoothstep(0.88, 1.08, rr);

    float n = sin(p.x * 6.0 + t) * cos(p.y * 5.5 - t * 0.8);
    n += 0.45 * sin((p.x + p.y) * 11.0 - t * 1.3);
    n = 0.5 + 0.5 * n;
    half3 col = mix(u_deep, u_mid, half(n * 0.75 + 0.15));

    float2 grid = floor(uv * 48.0 + float2(t * 0.4, -t * 0.25));
    float2 f = fract(uv * 48.0 + float2(t * 0.4, -t * 0.25)) - 0.5;
    float h = hash21(grid + u_seed * 13.0);
    float star = (h > 0.92) ? exp(-dot(f, f) * (90.0 + 180.0 * fract(h * 17.0))) : 0.0;
    float2 g2 = floor(uv * 80.0 - float2(t * 0.2, t * 0.15));
    float2 f2 = fract(uv * 80.0 - float2(t * 0.2, t * 0.15)) - 0.5;
    float h2 = hash21(g2 + 41.0);
    float star2 = (h2 > 0.94) ? exp(-dot(f2, f2) * 140.0) : 0.0;
    float stars = (star + star2 * 0.7) * u_amount * edge;
    col = mix(col, u_star, half(clamp(stars * 2.2, 0.0, 1.0)));
    col = mix(col, half3(1.0, 0.95, 1.0), half(clamp(stars * 3.5 - 1.0, 0.0, 1.0)));

    float atmos = pow(max(smoothstep(0.55, 0.95, rr), 0.0), 1.4) * edge;
    col = mix(col, u_shell, half(atmos * 0.55));

    float a = clamp((0.55 + n * 0.25 + stars * 0.5 + atmos * 0.35) * edge * u_amount, 0.0, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Nebula mist — same palette, no flashing white star dots.
_SRCS["shield_nebula_mist"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_deep;
uniform half3 u_mid;
uniform half3 u_star;
uniform half3 u_shell;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.45 + u_seed;
    float rr = length(p) * 2.0;
    float edge = 1.0 - smoothstep(0.88, 1.08, rr);

    float n = sin(p.x * 5.5 + t) * cos(p.y * 5.0 - t * 0.7);
    n += 0.4 * sin((p.x + p.y) * 9.5 - t * 1.1);
    n += 0.25 * sin(p.x * 14.0 - p.y * 11.0 + t * 0.8);
    n = 0.5 + 0.5 * n;
    half3 col = mix(u_deep, u_mid, half(n * 0.8 + 0.1));
    // soft brighter blooms (no hard stars)
    float bloom = pow(max(n, 0.0), 2.4);
    col = mix(col, u_star, half(bloom * 0.45 * u_amount));

    float atmos = pow(max(smoothstep(0.5, 0.95, rr), 0.0), 1.3) * edge;
    col = mix(col, u_shell, half(atmos * 0.6));

    float a = clamp((0.58 + n * 0.28 + atmos * 0.3) * edge * u_amount, 0.0, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Nebula veil — slow rotational curtains / ribbons (still classic palette).
_SRCS["shield_nebula_veil"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_deep;
uniform half3 u_mid;
uniform half3 u_star;
uniform half3 u_shell;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.5 + u_seed;
    float rr = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (rr < 1e-4) { ang = 0.0; }
    float edge = 1.0 - smoothstep(0.88, 1.08, rr);

    // slow spinning veils / curtains
    float v1 = 0.5 + 0.5 * sin(ang * 3.0 + t * 0.9 + rr * 2.5);
    float v2 = 0.5 + 0.5 * sin(ang * 5.0 - t * 1.3 + rr * 4.0);
    float veils = pow(max(v1 * 0.65 + v2 * 0.35, 0.0), 1.6);
    float n = 0.45 * sin(p.x * 7.0 + t) * cos(p.y * 6.0 - t * 0.6);
    n = 0.5 + 0.5 * n;
    half3 col = mix(u_deep, u_mid, half(n * 0.55 + veils * 0.45));
    col = mix(col, u_star, half(veils * 0.55 * u_amount));

    float atmos = pow(max(smoothstep(0.5, 0.96, rr), 0.0), 1.35) * edge;
    col = mix(col, u_shell, half(atmos * 0.55));

    float a = clamp((0.52 + veils * 0.35 + atmos * 0.28) * edge * u_amount, 0.0, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Molten core / gas giant sun: swirling red-orange with yellow limb.
_SRCS["shield_molten"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 1.15 + u_seed;
    float rr = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (rr < 1e-4) { ang = 0.0; }
    float edge = 1.0 - smoothstep(0.9, 1.1, rr);

    float2 q = p;
    q.x += 0.08 * sin(q.y * 10.0 + t * 2.0);
    q.y += 0.07 * cos(q.x * 9.0 - t * 1.6);
    float n = 0.0;
    n += 0.50 * sin(q.x * 8.0 + q.y * 7.0 + t * 1.8);
    n += 0.30 * sin(q.x * 15.0 - q.y * 12.0 - t * 2.5);
    n += 0.20 * sin(ang * 5.0 + t * 1.4 + rr * 6.0);
    n = 0.5 + 0.5 * n;
    float limb = 1.0 - smoothstep(0.2, 1.05, rr);
    float heat = pow(max(n * limb * u_amount, 0.0), 1.05);
    heat = clamp(heat, 0.0, 1.0);

    half3 ash = half3(0.12, 0.02, 0.0);
    half3 red = half3(0.85, 0.12, 0.02);
    half3 ora = half3(1.0, 0.45, 0.05);
    half3 amb = half3(1.0, 0.85, 0.2);
    half3 col = mix(ash, red, half(smoothstep(0.05, 0.35, heat)));
    col = mix(col, ora, half(smoothstep(0.3, 0.65, heat)));
    col = mix(col, amb, half(smoothstep(0.55, 0.95, heat)));

    float rimHot = pow(max(smoothstep(0.55, 0.98, rr), 0.0), 1.6) * edge;
    col = mix(col, half3(1.0, 0.95, 0.35), half(rimHot * 0.55));

    float a = clamp((0.55 + heat * 0.5) * edge, 0.35, 1.0);
    return half4(col * half(a), half(a));
}
"""

# Banded gas planet — recolorable mid tint (u_color).
_SRCS["shield_bands"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.35 + u_seed;
    float rr = length(p) * 2.0;
    float edge = 1.0 - smoothstep(0.9, 1.08, rr);
    float lat = p.y * 2.15 + 0.12 * sin(p.x * 6.0 + t);
    float bands = 0.5 + 0.5 * sin(lat * 11.0 + t * 0.4);
    bands += 0.2 * sin(lat * 23.0 - t * 0.7);
    bands = clamp(bands * 0.55 + 0.35, 0.0, 1.0);
    float grain = fract(sin(dot(uv * 55.0 + t * 0.1, float2(12.9898, 78.233))) * 43758.5453);

    half3 base = u_color;
    half3 deep = base * half3(0.22, 0.35, 0.4);
    half3 midc = base * half3(0.7, 0.85, 0.9);
    half3 lite = mix(base, half3(0.9, 1.0, 0.95), half(0.35));
    half3 col = mix(deep, midc, half(bands));
    col = mix(col, lite, half(pow(bands, 1.6) * 0.45 * u_amount));
    col = mix(col, col * half3(0.9, 0.95, 0.92), half(grain * 0.22));

    float rim = pow(max(smoothstep(0.72, 0.98, rr), 0.0), 1.8) * edge;
    col = mix(col, mix(base, half3(0.85, 1.0, 0.9), half(0.35)), half(rim * 0.5));

    float a = clamp((0.7 + bands * 0.2) * edge, 0.4, 0.98);
    return half4(col * half(a), half(a));
}
"""

# Plasma cloud — recolorable base (u_color).
_SRCS["shield_cloud"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 1.1 + u_seed;
    float rr = length(p) * 2.0;
    float edge = 1.0 - smoothstep(0.88, 1.1, rr);

    float2 q = p + float2(0.12 * sin(t * 0.9), 0.1 * cos(t * 0.7));
    float n = sin(q.x * 5.0 + t * 1.3) * cos(q.y * 4.5 - t * 1.1);
    n += 0.5 * sin((q.x + q.y) * 9.0 - t * 1.6);
    n += 0.35 * sin(q.x * 14.0 - q.y * 11.0 + t * 2.0);
    n = 0.5 + 0.5 * n;
    float bias = 0.55 + 0.45 * (p.x * 0.9 + p.y * 0.35);
    float cloud = smoothstep(0.35, 0.72, n * bias) * u_amount;

    half3 base = u_color;
    half3 glass = base * 0.48;
    half3 midc = base * 0.82;
    half3 hot = mix(base, half3(1.0, 1.0, 0.7), half(0.28));
    half3 core = mix(base, half3(1.0, 1.0, 0.95), half(0.40));
    half3 col = mix(glass, midc, half(0.35 + edge * 0.45));
    col = mix(col, hot, half(cloud));
    col = mix(col, core, half(pow(cloud, 2.2) * 0.55));

    float rim = pow(max(smoothstep(0.7, 0.98, rr), 0.0), 1.5) * edge;
    col = mix(col, mix(base, half3(1.0, 1.0, 0.85), half(0.3)), half(rim * 0.45));

    float a = clamp((0.35 + cloud * 0.7 + rim * 0.25) * edge, 0.22, 0.95);
    return half4(col * half(a), half(a));
}
"""

# Energy vortex — recolorable filament color (u_color).
_SRCS["shield_vortex"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 1.6 + u_seed;
    float rr = length(p) * 2.0;
    float ang = atan(p.y, p.x);
    if (rr < 1e-4) { ang = 0.0; }
    float edge = 1.0 - smoothstep(0.9, 1.08, rr);

    float spin = ang + t * 2.2 - rr * 3.5;
    float fil = sin(spin * 4.0) * 0.5 + 0.5 * sin(spin * 9.0 + rr * 6.0 - t * 3.0);
    fil = 0.5 + 0.5 * fil;
    float trails = pow(max(fil, 0.0), 2.8) * (1.0 - smoothstep(0.15, 0.95, rr));
    trails *= u_amount;

    float rings = pow(max(sin(rr * 14.0 - t * 4.0), 0.0), 8.0) * edge;
    rings += 0.55 * pow(max(sin(rr * 22.0 + t * 2.5), 0.0), 12.0) * edge;

    half3 base = u_color;
    half3 voidc = base * half3(0.12, 0.05, 0.18);
    half3 mag = base;
    half3 gold = mix(base, half3(1.0, 0.92, 0.4), half(0.55));
    half3 white = half3(1.0, 0.98, 0.92);
    half3 col = mix(voidc, mag, half(smoothstep(0.1, 0.55, trails + rings * 0.4)));
    col = mix(col, gold, half(smoothstep(0.4, 0.85, trails)));
    col = mix(col, white, half(pow(max(trails, 0.0), 3.0) * 0.65));
    col = mix(col, mag, half(rings * 0.75));

    float a = clamp((trails * 1.1 + rings * 0.55 + 0.08) * edge, 0.05, 0.95);
    return half4(col * half(a), half(a));
}
"""


# Cracked magma — fixed rock/lava; limb shell via u_shell (palette-driven).
_SRCS["shield_cracks"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_shell;
// Body palette (Shield._CRACKS_PALETTES): magma for "cracks", ice for "frost".
uniform half3 u_rock;
uniform half3 u_dark;
uniform half3 u_lava;
uniform half3 u_spar;

// Lattice hash: weights (127, 311) / 1024 are exact in float32, so n and the
// corner sums are exact and every pixel gets bit-identical corner hashes (no
// cell seams under FMA / reassociation), and |sin arg| stays < 2^14 (Intel
// GPU sin() collapses at |x| >= 2^17). See Effect System Design, "Noise hash".
float hash1(float n) {
    return fract(sin(n) * 43758.5453);
}

float vnoise(float2 p) {
    float2 i = floor(p);
    float2 f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float n = dot(i, float2(0.1240234375, 0.3037109375));
    return mix(mix(hash1(n), hash1(n + 0.1240234375), u.x),
               mix(hash1(n + 0.3037109375), hash1(n + 0.427734375), u.x), u.y);
}

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.7 + u_seed;
    float rr = length(p) * 2.0;
    float edge = 1.0 - smoothstep(0.9, 1.08, rr);

    float2 q = p * 4.5 + float2(t * 0.15, -t * 0.1);
    float n = abs(vnoise(q) * 2.0 - 1.0);
    n = min(n, abs(vnoise(q * 2.1 + 3.1) * 2.0 - 1.0));
    n = min(n, abs(vnoise(q * 4.3 - 1.7) * 2.0 - 1.0) * 0.85);
    float ridges = 1.0 - n;
    float cracks = pow(max(ridges, 0.0), 7.0) * u_amount;
    float glow = pow(max(ridges, 0.0), 3.5) * 0.45 * u_amount;

    half3 col = mix(u_rock, u_dark, half(0.4 + 0.3 * vnoise(q * 0.7)));
    col = mix(col, u_lava, half(clamp(glow + cracks * 0.5, 0.0, 1.0)));
    col = mix(col, u_spar, half(clamp(cracks * 1.8, 0.0, 1.0)));

    float shell = pow(max(smoothstep(0.72, 0.98, rr), 0.0), 1.6) * edge;
    col = mix(col, u_shell, half(shell * 0.5));

    float a = clamp((0.75 + cracks * 0.35 + shell * 0.15) * edge, 0.45, 1.0);
    return half4(col * half(a), half(a));
}
"""

# Ink wash: tonal bands of u_color with structured sin noise (Ink / InkWash).
_SRCS["ink_wash"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float t = u_time * 0.25 + u_seed;
    float bands = 0.55 + 0.45 * sin((uv.x * 1.3 + uv.y * 0.7) * 9.0 + t)
                + 0.25 * sin((uv.x - uv.y) * 17.0 - t * 1.3);
    bands = clamp(bands * 0.55 + 0.35, 0.0, 1.0);
    float blot = 0.5 + 0.5 * sin(uv.x * 6.0 + t) * cos(uv.y * 7.0 - t * 0.7);
    float mixv = mix(bands, blot, 0.35) * u_amount;
    mixv = clamp(mixv, 0.05, 1.0);
    half3 base = u_color;
    half3 light = mix(base, half3(1.0, 1.0, 1.0), half(0.35));
    half3 dark = base * half3(0.35, 0.38, 0.45);
    half3 col = mix(dark, base, half(mixv));
    col = mix(col, light, half(pow(mixv, 2.2) * 0.4));
    // paper grain
    float g = fract(sin(dot(uv * 40.0, float2(12.9898, 78.233))) * 43758.5453);
    col = mix(col, col * half3(0.9, 0.9, 0.92), half(g * 0.12));
    return half4(col, 1.0);
}
"""

# Ink bleed: soft blotches + edge-weighted absorb of tint.
_SRCS["ink_bleed"] = """
uniform float2 u_resolution;
uniform float u_time;
uniform float u_amount;
uniform float u_seed;
uniform half3 u_color;

half4 main(float2 coord) {
    float2 uv = 0.5 + coord / max(u_resolution, float2(1.0));
    float2 p = uv - float2(0.5);
    float t = u_time * 0.35 + u_seed;
    float r = length(p) * 2.0;
    float n = 0.0;
    n += 0.5 * sin(p.x * 11.0 + t * 1.2) * cos(p.y * 9.0 - t);
    n += 0.35 * sin((p.x + p.y) * 18.0 - t * 1.7);
    n += 0.25 * sin(r * 14.0 + t * 2.0);
    n = 0.5 + 0.5 * n;
    float edge = smoothstep(0.15, 0.95, r);
    float pool = pow(max(n * (0.55 + 0.45 * edge), 0.0), 1.4) * u_amount;
    half3 base = u_color;
    half3 paper = mix(half3(0.92, 0.9, 0.86), base, half(0.15));
    half3 wet = base * half3(0.75, 0.8, 0.95);
    half3 dense = base * half3(0.35, 0.32, 0.4);
    half3 col = mix(paper, wet, half(smoothstep(0.1, 0.55, pool)));
    col = mix(col, dense, half(smoothstep(0.45, 0.95, pool)));
    float a = clamp(0.55 + pool * 0.5, 0.5, 1.0);
    return half4(col * half(a), half(a));
}
"""

# Sprite pixel FX — hue-band recolor of an image shader.
# Map local draw coords → image texels via u_src / u_dst (py-skia drops
# makeWithLocalMatrix on RuntimeEffect child shaders).
_SRCS["sprite_recolor"] = """
uniform shader u_image;
uniform float4 u_src;       // image LTRB
uniform float4 u_dst;       // local draw LTRB
uniform float3 u_key_hsv;   // key hue (0-1), sat, val unused for match
uniform float3 u_to_hsv;    // replacement hue/sat/val (sat/val <0 keep source)
uniform float u_range;      // hue half-width (0-1)
uniform float u_soft;       // soft edge (0-1)

half3 rgb_to_hsv(half3 c) {
    half4 K = half4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    half4 p = mix(half4(c.bg, K.wz), half4(c.gb, K.xy), step(c.b, c.g));
    half4 q = mix(half4(p.xyw, c.r), half4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return half3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

half3 hsv_to_rgb(half3 c) {
    half4 K = half4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    half3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

half4 main(float2 coord) {
    float2 uv = (coord - u_dst.xy) / max(u_dst.zw - u_dst.xy, float2(1e-3));
    float2 tc = mix(u_src.xy, u_src.zw, uv);
    half4 src = u_image.eval(tc);
    if (src.a < 0.004) return src;
    half3 hsv = rgb_to_hsv(max(src.rgb / max(src.a, half(0.001)), half3(0.0)));
    float dh = abs(hsv.x - u_key_hsv.x);
    dh = min(dh, 1.0 - dh);
    float m = 1.0 - smoothstep(u_range, u_range + max(u_soft, 0.001), dh);
    // Low-sat pixels are not keyed
    m *= smoothstep(0.12, 0.28, float(hsv.y));
    half3 out_hsv = hsv;
    out_hsv.x = half(u_to_hsv.x);
    if (u_to_hsv.y >= 0.0) out_hsv.y = half(u_to_hsv.y);
    if (u_to_hsv.z >= 0.0) out_hsv.z = half(u_to_hsv.z);
    half3 rgb = mix(src.rgb / max(src.a, half(0.001)), hsv_to_rgb(out_hsv), half(m));
    return half4(rgb * src.a, src.a);
}
"""

# Sprite pixel FX — SDF fringe (inner+outer band, not a fill).
# u_dst / u_sdf_wh map local coords → SDF texels (no child localMatrix).
_SRCS["sprite_aura"] = """
uniform shader u_sdf;
uniform float4 u_color;
uniform float u_amount;
uniform float u_width;
uniform float4 u_dst;    // outer quad LTRB in local blit space
uniform float2 u_sdf_wh; // SDF pixel size

half4 main(float2 coord) {
    float2 uv = (coord - u_dst.xy) / max(u_dst.zw - u_dst.xy, float2(1e-3));
    // Kill hard crop at the padded SDF border
    float edge = min(min(uv.x, uv.y), min(1.0 - uv.x, 1.0 - uv.y));
    float border = smoothstep(0.0, 0.08, edge);
    float2 tc = uv * u_sdf_wh;
    half4 s = u_sdf.eval(tc);
    float d = (float(s.r) - 0.5) * 2.0;  // ≈ -1 inside … +1 far outside
    float w = max(u_width, 0.02);
    float a = exp(-(d * d) / (w * w * 0.42)) * u_amount;
    a = clamp(a * border, 0.0, 1.0) * u_color.a;
    return half4(u_color.rgb * half(a), half(a));
}
"""

# Sprite silhouette bands (Laser / Halo on Sprite): glow + rim + white core.
_SRCS["sprite_sil_v2"] = """
uniform shader u_sdf;
uniform float4 u_color;
uniform float u_glow_w;
uniform float u_glow_a;
uniform float u_rim_w;
uniform float u_rim_a;
uniform float u_core_w;
uniform float u_core_a;
uniform float4 u_dst;
uniform float2 u_sdf_wh;

half4 main(float2 coord) {
    float2 uv = (coord - u_dst.xy) / max(u_dst.zw - u_dst.xy, float2(1e-3));
    float edge = min(min(uv.x, uv.y), min(1.0 - uv.x, 1.0 - uv.y));
    float border = smoothstep(0.0, 0.08, edge);
    float2 tc = uv * u_sdf_wh;
    half4 s = u_sdf.eval(tc);
    float d = (float(s.r) - 0.5) * 2.0;
    float od = max(d, 0.0);
    float gw = max(u_glow_w, 0.001);
    float rw = max(u_rim_w, 0.001);
    float cw = max(u_core_w, 0.001);
    float glow = exp(-od * od / (gw * gw)) * smoothstep(-0.06, 0.04, d) * u_glow_a;
    float rim = exp(-(d * d) / (rw * rw * 0.20)) * u_rim_a;
    float core = exp(-(d * d) / (cw * cw * 0.16)) * u_core_a;
    glow = max(glow, 0.0);
    rim = max(rim, 0.0);
    core = max(core, 0.0);
    float cov = clamp((glow + rim + core) * border, 0.0, 1.0);
    half3 rgb = u_color.rgb * half(glow + rim) + half3(1.0, 1.0, 1.0) * half(core);
    rgb = clamp(rgb, 0.0, 1.0) * half(border);
    return half4(rgb, half(cov));
}
"""

# Full-sprite live hue rotate (amount in turns).
_SRCS["sprite_hue"] = """
uniform shader u_image;
uniform float4 u_src;
uniform float4 u_dst;
uniform float u_amount;

half3 hue_rot(half3 rgb, float ang) {
    float c = cos(ang);
    float s = sin(ang);
    half3x3 m = half3x3(
        half3(0.213 + 0.787*c - 0.213*s, 0.715 - 0.715*c - 0.715*s, 0.072 - 0.072*c + 0.928*s),
        half3(0.213 - 0.213*c + 0.143*s, 0.715 + 0.285*c + 0.140*s, 0.072 - 0.072*c - 0.283*s),
        half3(0.213 - 0.213*c - 0.787*s, 0.715 - 0.715*c + 0.715*s, 0.072 + 0.928*c + 0.072*s)
    );
    return clamp(m * rgb, 0.0, 1.0);
}

half4 main(float2 coord) {
    float2 uv = (coord - u_dst.xy) / max(u_dst.zw - u_dst.xy, float2(1e-3));
    float2 tc = mix(u_src.xy, u_src.zw, uv);
    half4 src = u_image.eval(tc);
    if (src.a < 0.004) return src;
    half3 rgb = hue_rot(src.rgb / max(src.a, half(0.001)), u_amount * 6.2831853);
    return half4(rgb * src.a, src.a);
}
"""

# Texture fill Recolor — ColorFilter on paint output (no UV / atlas).
# Same HSV band logic as sprite_recolor; runs after the image shader.
_COLOR_FILTER_SRCS: Dict[str, str] = {}
_COLOR_FILTER_SRCS["texture_recolor"] = """
uniform float3 u_key_hsv;
uniform float3 u_to_hsv;
uniform float u_range;
uniform float u_soft;

half3 rgb_to_hsv(half3 c) {
    half4 K = half4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    half4 p = mix(half4(c.bg, K.wz), half4(c.gb, K.xy), step(c.b, c.g));
    half4 q = mix(half4(p.xyw, c.r), half4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return half3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

half3 hsv_to_rgb(half3 c) {
    half4 K = half4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    half3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

half4 main(half4 inColor) {
    if (inColor.a < 0.004) return inColor;
    half3 hsv = rgb_to_hsv(max(inColor.rgb / max(inColor.a, half(0.001)), half3(0.0)));
    float dh = abs(hsv.x - u_key_hsv.x);
    dh = min(dh, 1.0 - dh);
    float m = 1.0 - smoothstep(u_range, u_range + max(u_soft, 0.001), dh);
    m *= smoothstep(0.12, 0.28, float(hsv.y));
    half3 out_hsv = hsv;
    out_hsv.x = half(u_to_hsv.x);
    if (u_to_hsv.y >= 0.0) out_hsv.y = half(u_to_hsv.y);
    if (u_to_hsv.z >= 0.0) out_hsv.z = half(u_to_hsv.z);
    half3 rgb = mix(inColor.rgb / max(inColor.a, half(0.001)), hsv_to_rgb(out_hsv), half(m));
    return half4(rgb * inColor.a, inColor.a);
}
"""

_EFFECTS: Dict[str, skia.RuntimeEffect] = {}
_COLOR_FILTER_EFFECTS: Dict[str, skia.RuntimeEffect] = {}

# Fill shaders only — dissolve / sprite_* are not ProceduralFill kinds.
_NON_FILL_SKSL = frozenset({
    "dissolve", "sprite_recolor", "sprite_aura", "sprite_sil_v2", "sprite_hue",
})
PROCEDURAL_FILL_KINDS = tuple(k for k in _SRCS if k not in _NON_FILL_SKSL)


def _effect(kind: str) -> skia.RuntimeEffect:
    key = str(kind).strip().lower()
    if key not in _SRCS:
        listed = ", ".join(repr(k) for k in _SRCS)
        raise ValueError(f"kind={kind!r}; expected one of {listed}")
    if key not in _EFFECTS:
        src = _SRCS[key]
        eff = skia.RuntimeEffect.MakeForShader(src)
        err = None
        if isinstance(eff, tuple):
            eff, err = eff
        if eff is None:
            raise RuntimeError(f"{key} SkSL failed to compile: {err}")
        _EFFECTS[key] = eff
    return _EFFECTS[key]


def _color_filter_effect(kind: str) -> skia.RuntimeEffect:
    key = str(kind).strip().lower()
    if key not in _COLOR_FILTER_SRCS:
        listed = ", ".join(repr(k) for k in _COLOR_FILTER_SRCS)
        raise ValueError(f"kind={kind!r}; expected one of {listed}")
    if key not in _COLOR_FILTER_EFFECTS:
        src = _COLOR_FILTER_SRCS[key]
        eff = skia.RuntimeEffect.MakeForColorFilter(src)
        err = None
        if isinstance(eff, tuple):
            eff, err = eff
        if eff is None:
            raise RuntimeError(f"{key} ColorFilter SkSL failed to compile: {err}")
        _COLOR_FILTER_EFFECTS[key] = eff
    return _COLOR_FILTER_EFFECTS[key]


def procedural_builder(kind: str) -> skia.RuntimeShaderBuilder:
    return skia.RuntimeShaderBuilder(_effect(kind))


def color_filter_builder(kind: str):
    """RuntimeEffectBuilder for MakeForColorFilter kinds (e.g. texture_recolor)."""
    return skia.RuntimeColorFilterBuilder(_color_filter_effect(kind))



def dissolve_mask_shader(
    progress: float,
    seed: float,
    cx: float,
    cy: float,
    half: float,
    *,
    style: str = "noise",
    angle: float = 0.0,
) -> skia.Shader:
    """World-mapped dissolve alpha mask (use with DstIn over a shape layer).

    ``style``: ``"noise"`` | ``"vortex"`` | ``"wipe"``.
    ``angle``: wipe axis / vortex bias in **degrees** (0 = +x). Converted
    to radians at this SkSL boundary.
    """
    b = skia.RuntimeShaderBuilder(_effect("dissolve"))
    res = max(64.0, float(half) * 2.4)
    st = (style or "noise").lower()
    if st in ("vortex", "swirl", "spin"):
        style_id = 1.0
    elif st in ("wipe", "slide", "band"):
        style_id = 2.0
    else:
        style_id = 0.0
    b.setUniform("u_resolution", [res, res])
    b.setUniform("u_progress", float(max(0.0, min(1.0, progress))))
    b.setUniform("u_seed", float(seed))
    b.setUniform("u_style", style_id)
    b.setUniform("u_angle", math.radians(float(angle)))
    sh = b.makeShader()
    # Local matrix places the shader so device (cx, cy) → shader (res/2, res/2)
    # (UV center = shape pivot). Skia: device = LocalMatrix × local_coord.
    # Inverse of the old Translate(res/2−cx) put the pivot off the dig field,
    # so radial styles (vortex) erased the whole silhouette at t=0.
    m = skia.Matrix.Translate(float(cx) - res * 0.5, float(cy) - res * 0.5)
    if hasattr(sh, "makeWithLocalMatrix"):
        return sh.makeWithLocalMatrix(m)
    return sh
