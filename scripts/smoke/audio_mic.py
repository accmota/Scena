"""
audio_mic.py — smoke: Microphone capture, monitor, analysis, effects.

Separate on purpose: needs a real mic / OS permission prompt.
"""
from scena import *

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — microphone")

hud = SmokeHud(
    title="Microphone",
    expect="Open mic, speak / clap → bars move. Monitor hears yourself. Close → quiet.",
    keys="Open / Close  ·  monitor checkbox  ·  effects",
    status="mic closed",
    show_aux=True,
)

st.monitor = False
st.vol = 0.8
st.pan = 0.0
st.fx_lp = False
st.fx_hp = False
st.fx_echo = False
st.fx_rev = False
st.fx_dist = False
st.fx_fold = False

mic = None
monitor_h = None


def _apply_fx():
    if mic is None:
        return
    mic.effects.clear()
    if st.fx_lp:
        mic.effects.add(LowPass())
    if st.fx_hp:
        mic.effects.add(HighPass())
    if st.fx_echo:
        mic.effects.add(Echo())
    if st.fx_rev:
        mic.effects.add(Reverb())
    if st.fx_dist:
        mic.effects.add(Distortion())
    if st.fx_fold:
        mic.effects.add(Wavefold())


def open_mic():
    global mic
    if mic is not None:
        return
    mic = Microphone()
    _apply_fx()
    hud.status = "mic open"


def close_mic():
    global mic, monitor_h
    if monitor_h is not None and not monitor_h.done:
        monitor_h.cancel()
    monitor_h = None
    if mic is not None:
        mic.close()
        mic.close()
        mic = None
    hud.status = "mic closed"


def toggle_monitor():
    global monitor_h
    if not st.monitor:
        if monitor_h is not None and not monitor_h.done:
            monitor_h.cancel()
        monitor_h = None
        return
    if mic is None:
        hud.status = "open the mic first"
        st.monitor = False
        return
    monitor_h = play_sound(mic, volume=float(st.vol), pan=float(st.pan))
    hud.status = "monitor on"


ui.gap()
Button(label="Open mic", on_click=open_mic)
Button(label="Close mic", on_click=close_mic)
CheckBox(st.monitor, label="Monitor (hear yourself)")
Slider(st.vol, label="Monitor volume", show_value=True, min_value=0.0, max_value=1.5)
Slider(st.pan, label="Pan", show_value=True, min_value=-1.0, max_value=1.0)
CheckBox(st.fx_lp, label="LowPass")
CheckBox(st.fx_hp, label="HighPass")
CheckBox(st.fx_echo, label="Echo")
CheckBox(st.fx_rev, label="Reverb")
CheckBox(st.fx_dist, label="Distortion")
CheckBox(st.fx_fold, label="Wavefold")

bars = [Rect(width=18, height=4, color="lime") for _ in range(8)]
level_meter = Rect(width=24, height=4, color="gold")

_last_mon = False
_last_fx = None


def update(dt):
    global _last_mon, _last_fx, monitor_h
    fx_now = (st.fx_lp, st.fx_hp, st.fx_echo, st.fx_rev, st.fx_dist, st.fx_fold)
    if fx_now != _last_fx:
        _apply_fx()
        _last_fx = fx_now
    if bool(st.monitor) != _last_mon:
        _last_mon = bool(st.monitor)
        toggle_monitor()
    if monitor_h is not None and not monitor_h.done:
        monitor_h.volume = float(st.vol)
        monitor_h.pan = float(st.pan)

    src = mic
    n = 8
    spec = src.spectrum(bins=n) if src is not None else [0.0] * n
    lvl = src.level if src is not None else 0.0
    for i, bar in enumerate(bars):
        bar.height = 8 + 160 * spec[i]
        bar.center = (80 + i * 28, 140 + bar.height / 2)
    level_meter.height = 8 + 160 * lvl
    level_meter.center = (40, 140 + level_meter.height / 2)
    hud.aux = f"level={lvl:.2f}  open={mic is not None}"


canvas.background = (0.07, 0.08, 0.10)
run()
