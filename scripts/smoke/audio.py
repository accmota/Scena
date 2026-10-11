"""
audio.py — smoke: play_sound, fades, master bus, analysis, effects.

Widgets auto-stack under the HUD in two columns (split after Spectrum bins).
Level / FFT bars are world-space Rects in a third column.
"""
from scena import *

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

SOUNDS = Path(__file__).resolve().parents[2] / "examples" / "media" / "audio"
FILES = sorted(
    p.name for p in SOUNDS.iterdir()
    if p.suffix.lower() in (".wav", ".ogg", ".flac", ".mp3")
    and not p.name.startswith("._")  # AppleDouble files in a tree copied from macOS
)

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — audio")

hud = SmokeHud(
    title="Audio",
    expect="Play a clip → hear it. Bars follow loudness (no extra smoothing). Missing file → SCENA WARNING, not ERROR.",
    keys="Play/Stop  ·  music slot  ·  sliders  ·  effects checkboxes",
    status="ready",
    show_aux=True,
)

# Short clip / long music piece from examples/media/audio (any file still works).
st.clip = "laser-big.wav" if "laser-big.wav" in FILES else (FILES[0] if FILES else "laser-big.wav")
st.music = ("SuperHero_original_no_Intro.ogg" if "SuperHero_original_no_Intro.ogg" in FILES
            else (FILES[-1] if FILES else "Victory.mp3"))
st.master = 1.0
st.vol = 1.0
st.pan = 0.0
st.pitch = 1.0
st.level_tau = 0.08
st.fade_in = 0.0
st.fade_out = 0.3
st.crossfade = 1.0
st.muted = False
st.loop = False
st.fx_lp = False
st.fx_hp = False
st.fx_echo = False
st.fx_rev = False
st.fx_dist = False
st.fx_fold = False
st.bins = 8.0
st.transpose = 0.0

live = None
music_h = None
fx_handles = {}
live_baked = False


def _path(name):
    return str(SOUNDS / name)


def _stop_live():
    global live, live_baked
    if live is not None and not live.done:
        live.cancel()
    live = None
    live_baked = False


def _apply_fx(handle):
    if handle is None or handle.done:
        return
    handle.effects.clear()
    if st.fx_lp:
        handle.effects.add(LowPass())
    if st.fx_hp:
        handle.effects.add(HighPass())
    if st.fx_echo:
        handle.effects.add(Echo())
    if st.fx_rev:
        handle.effects.add(Reverb())
    if st.fx_dist:
        handle.effects.add(Distortion())
    if st.fx_fold:
        handle.effects.add(Wavefold())


def play_clip():
    global live, live_baked
    _stop_live()
    fade = float(st.fade_in) or None
    live = play_sound(
        _path(st.clip),
        volume=float(st.vol),
        pan=float(st.pan),
        pitch=float(st.pitch),
        loops="forever" if st.loop else 1,
        fade_in=fade,
    )
    live_baked = False
    _apply_fx(live)
    hud.status = f"play {st.clip}"


def play_baked():
    global live, live_baked
    _stop_live()
    chain = []
    if st.fx_dist:
        chain.append(Distortion())
    if st.fx_fold:
        chain.append(Wavefold())
    if st.fx_echo:
        chain.append(Echo())
    if st.fx_rev:
        chain.append(Reverb())
    if st.fx_lp:
        chain.append(LowPass())
    if st.fx_hp:
        chain.append(HighPass())
    material = Sound(_path(st.clip)).bake(
        *chain,
        transpose=float(st.transpose),
        pitch=float(st.pitch),
    )
    live = play_sound(
        material,
        volume=float(st.vol),
        pan=float(st.pan),
        pitch=1.0,
        loops="forever" if st.loop else 1,
    )
    live_baked = True
    hud.status = (
        f"baked {st.clip} transpose={float(st.transpose):.1f} "
        f"pitch={float(st.pitch):.2f}"
    )


def stop_clip():
    _stop_live()
    hud.status = "stopped"


def stop_all():
    global live, music_h
    _stop_live()
    if music_h is not None and not music_h.done:
        music_h.cancel()
    music_h = None
    hud.status = "stop all"


def play_music():
    global music_h
    music_h = play_sound(
        _path(st.music),
        volume=float(st.vol),
        loops="forever",
        name="music",
    )
    hud.status = f"music {st.music} (cut)"


def crossfade_music():
    global music_h
    music_h = play_sound(
        _path(st.music),
        volume=float(st.vol),
        loops="forever",
        name="music",
        crossfade=float(st.crossfade),
    )
    hud.status = f"crossfade {st.music} {st.crossfade:.2f}s"


def fade_out_live():
    if live is not None and not live.done:
        live.fade_out(float(st.fade_out))
        hud.status = f"fade_out {st.fade_out:.2f}s"


def missing():
    play_sound("no_such_file.wav")
    hud.status = "missing file (SCENA WARNING banner)"


ui.gap()
clip_dd = DropDown(st["clip"], options=FILES or ["(no files)"])
DropDown(st["music"], options=FILES or ["(no files)"])
Button(label="Play", on_click=play_clip)
Button(label="Play baked", on_click=play_baked)
Button(label="Stop", on_click=stop_clip)
Button(label="Stop all", on_click=stop_all)
Button(label="Play music", on_click=play_music)
Button(label="Crossfade to music", on_click=crossfade_music)
Button(label="Fade out live", on_click=fade_out_live)
Button(label="Missing file", on_click=missing)
Slider(st["master"], label="Master volume", show_value=True, min_value=0.0, max_value=1.5)
Slider(st["vol"], label="Voice volume", show_value=True, min_value=0.0, max_value=1.5)
Slider(st["pan"], label="Pan", show_value=True, min_value=-1.0, max_value=1.0)
Slider(st["pitch"], label="Pitch", show_value=True, min_value=0.25, max_value=2.0)
Slider(st["transpose"], label="Bake transpose st", show_value=True, min_value=-12.0, max_value=12.0)
Slider(st["level_tau"], label="level_tau", show_value=True, min_value=0.01, max_value=0.4)
Slider(st["fade_in"], label="Fade in s", show_value=True, min_value=0.0, max_value=2.0)
Slider(st["fade_out"], label="Fade out s", show_value=True, min_value=0.05, max_value=2.0)
Slider(st["crossfade"], label="Crossfade s", show_value=True, min_value=0.1, max_value=3.0)
Slider(st["bins"], label="Spectrum bins", show_value=True, min_value=4.0, max_value=16.0)

COL_GAP = 24.0
col2_x = float(clip_dd.box.top_right.x) + COL_GAP
ui.stack_origin(col2_x, clip_dd.box.top_left.y)
CheckBox(st["muted"], label="Master muted")
CheckBox(st["loop"], label="Loop forever")
CheckBox(st["fx_lp"], label="LowPass")
CheckBox(st["fx_hp"], label="HighPass")
CheckBox(st["fx_echo"], label="Echo")
CheckBox(st["fx_rev"], label="Reverb")
CheckBox(st["fx_dist"], label="Distortion")
CheckBox(st["fx_fold"], label="Wavefold")

col3_x = col2_x + clip_dd.width + COL_GAP
_meter_x = col3_x + 12.0
_bar_x0 = _meter_x + 40.0
_bar_base_y = float(clip_dd.box.top_left.y) - (8.0 + 160.0)

N0 = 8
bars = [Rect(width=18, height=4, color="cyan") for _ in range(16)]
level_meter = Rect(width=24, height=4, color="gold")

_last_fx = None


def update(dt):
    global _last_fx
    audio.volume = float(st.master)
    audio.muted = bool(st.muted)
    audio.level_tau = max(0.01, float(st.level_tau))
    if live is not None and not live.done:
        live.volume = float(st.vol)
        live.pan = float(st.pan)
        if not live_baked:
            live.pitch = float(st.pitch)
    fx_now = (st.fx_lp, st.fx_hp, st.fx_echo, st.fx_rev, st.fx_dist, st.fx_fold)
    if fx_now != _last_fx:
        _apply_fx(live)
        _last_fx = fx_now

    n = max(4, min(16, int(round(float(st.bins)))))
    spec = audio.spectrum(bins=n)
    for i, bar in enumerate(bars):
        if i < n:
            bar.visible = True
            bar.height = 8 + 160 * amp_db(spec[i], floor=-48)
            bar.center = (_bar_x0 + i * 28, _bar_base_y + bar.height / 2)
        else:
            bar.visible = False
    level_meter.height = 8 + 160 * amp_db(audio.level, floor=-48)
    level_meter.center = (_meter_x, _bar_base_y + level_meter.height / 2)
    who = "—"
    if live is not None and not live.done:
        who = f"sfx {live.elapsed:.2f}s"
    elif music_h is not None and not music_h.done:
        who = "music"
    hud.aux = f"{who}  level={audio.level:.2f}  tau={audio.level_tau:.2f}"


canvas.background = (0.08, 0.09, 0.12)
run()
