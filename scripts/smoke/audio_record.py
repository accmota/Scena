"""
audio_record.py — smoke: record a clip, then play it back with effects.

Separate on purpose: needs a real mic / OS permission prompt.
The recording is dry (what the mic heard). Effects apply on playback,
or frozen with bake. Mic effects color the monitor only.
"""
from scena import *

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — record a clip")

hud = SmokeHud(
    title="Record a clip",
    expect="Record → stop → play hears your voice. Effects only on playback. Mic echo is the monitor. Held record stops at 30 s (banner).",
    keys="Record / Stop  ·  Record 2 s  ·  Play / Play baked  ·  effect checkboxes",
    status="mic opening",
    show_aux=True,
)

st.pitch = 1.0
st.semitones = 0.0
st.monitor = False
st.mic_echo = False
st.fx_lp = False
st.fx_hp = False
st.fx_echo = False
st.fx_rev = False
st.fx_dist = False
st.fx_fold = False
st.limit = 30.0

mic = Microphone()
holder = Circle()
holder.visible = False
clip = None
play_h = None
monitor_h = None
baked = False


def _apply_mic_fx():
    mic.effects.clear()
    if st.mic_echo:
        mic.effects.add(Echo())


def _apply_play_fx(handle):
    if handle is None or handle.done or baked:
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
    handle.pitch = float(st.pitch)


def _ready():
    if play_h is not None and not play_h.done:
        return
    if clip is not None and clip.duration >= 29.9:
        hud.status = "stopped at the 30 s limit"
    else:
        hud.status = "clip ready"


def _stop_play():
    global play_h, baked
    if play_h is not None and not play_h.done:
        play_h.cancel()
    play_h = None
    baked = False


def start_record():
    global clip
    if mic.recording:
        hud.status = "already recording — Stop first"
        return
    _stop_play()
    st.limit = 30.0
    clip = mic.record(on_done=_ready)
    hud.status = "REC"


def stop_record():
    if not mic.recording:
        hud.status = "not recording — Record first"
        return
    mic.stop()
    hud.status = "clip ready"


async def take_two(e):
    global clip
    if mic.recording:
        hud.status = "already recording — Stop first"
        return
    _stop_play()
    st.limit = 2.0
    clip = mic.record(seconds=2)
    hud.status = "REC 2 s"
    await clip
    hud.status = "clip ready (2 s)"


def record_two():
    holder.mode = take_two


def _have_clip():
    if mic.recording or clip is None:
        hud.status = "record, then stop (or wait for 2 s)"
        return False
    return True


def play_clip():
    global play_h, baked
    if not _have_clip():
        return
    _stop_play()
    play_h = play_sound(clip, pitch=float(st.pitch))
    baked = False
    _apply_play_fx(play_h)
    hud.status = "playing"


def play_baked():
    global play_h, baked
    if not _have_clip():
        return
    _stop_play()
    material = clip.bake(Echo(), transpose=float(st.semitones))
    play_h = play_sound(material)
    baked = True
    hud.status = f"playing baked echo, transpose={float(st.semitones):.1f}"


def toggle_monitor():
    global monitor_h
    if not st.monitor:
        if monitor_h is not None and not monitor_h.done:
            monitor_h.cancel()
        monitor_h = None
        return
    monitor_h = play_sound(mic, volume=0.8)
    hud.status = "monitor on (wet) — the clip stays dry"


ui.gap()
Button(label="Record", on_click=start_record)
Button(label="Stop", on_click=stop_record)
Button(label="Record 2 s", on_click=record_two)
Button(label="Play", on_click=play_clip)
Button(label="Play baked", on_click=play_baked)
Slider(st["pitch"], label="Playback pitch", show_value=True, min_value=0.5, max_value=2.0)
Slider(st["semitones"], label="Bake transpose", show_value=True, min_value=-12.0, max_value=12.0)
CheckBox(st["monitor"], label="Monitor (hear yourself)")
CheckBox(st["mic_echo"], label="Mic Echo (monitor only)")
CheckBox(st["fx_lp"], label="Play LowPass")
CheckBox(st["fx_hp"], label="Play HighPass")
CheckBox(st["fx_echo"], label="Play Echo")
CheckBox(st["fx_rev"], label="Play Reverb")
CheckBox(st["fx_dist"], label="Play Distortion")
CheckBox(st["fx_fold"], label="Play Wavefold")

progress = Rect(width=4, height=18, color="crimson")
level_meter = Rect(width=18, height=4, color="gold")

_last_mon = False
_last_mic_fx = None
_last_play_fx = None


def update(dt):
    global _last_mon, _last_mic_fx, _last_play_fx
    mic_fx = bool(st.mic_echo)
    if mic_fx != _last_mic_fx:
        _apply_mic_fx()
        _last_mic_fx = mic_fx
    if bool(st.monitor) != _last_mon:
        _last_mon = bool(st.monitor)
        toggle_monitor()
    play_fx = (
        st.fx_lp, st.fx_hp, st.fx_echo, st.fx_rev, st.fx_dist, st.fx_fold, float(st.pitch)
    )
    if play_fx != _last_play_fx:
        _apply_play_fx(play_h)
        _last_play_fx = play_fx

    dur = clip.duration if clip is not None else 0.0
    limit = max(0.001, float(st.limit))
    progress.width = 8 + 420 * min(1.0, dur / limit)
    progress.center = (240 + progress.width / 2, 150)
    lvl = mic.level
    level_meter.height = 8 + 140 * lvl
    level_meter.center = (40, 150 + level_meter.height / 2)
    rec = "REC" if mic.recording else "idle"
    hud.aux = f"{rec}  {dur:.2f}s / {limit:.0f}s  level={lvl:.2f}"


_apply_mic_fx()
hud.status = "ready — Record, speak, Stop, Play"
canvas.background = (0.07, 0.08, 0.10)
run()
