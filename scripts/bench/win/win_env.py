"""Windows host facts that decide how frame pacing can work (~40 s, one small window).

    python scripts/bench/win/win_env.py --json <out>/env.json

OS / CPU / GPU / driver, power, HAGS, Python + clocks, sleep granularity and
the PRECISION pacing emulation (sleep(1 ms) + busy-wait), timer resolution,
GLFW monitors and modes, GL vendor / renderer, swap-control extensions,
DWM refresh ratio, scena fingerprint.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_BENCH))
for _p in (_HERE, _BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # report, never abort the whole capture
        return {"error": f"{type(exc).__name__}: {exc}"}


def _ps(cmd: str) -> Any:
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", cmd + " | ConvertTo-Json -Depth 3"],
        text=True, stderr=subprocess.STDOUT, timeout=60)
    return json.loads(out) if out.strip() else None


def _stats_ms(xs: List[float]) -> Dict[str, float]:
    s = sorted(xs)
    k = lambda q: s[min(len(s) - 1, int(round(q * (len(s) - 1))))]  # noqa: E731
    return {"p50": k(0.5), "p90": k(0.9), "p99": k(0.99), "max": s[-1], "n": len(s)}


def sleep_granularity(n: int = 200) -> Dict[str, Any]:
    out = {}
    for req in (0.0, 0.0005, 0.001, 0.002, 0.005):
        xs = []
        for _ in range(n):
            a = time.perf_counter()
            time.sleep(req)
            xs.append((time.perf_counter() - a) * 1000.0)
        out[f"sleep_{req * 1000:g}ms"] = _stats_ms(xs)
    return out


def precision_emulation(n: int = 240, work_ms: float = 8.0, frame_ms: float = 1000.0 / 60) -> Dict[str, Any]:
    """Copy of the PRECISION branch in ScenaFramework.run (orchestration.py):
    remaining > 2 ms -> sleep(0.001) once, then busy-wait to target.
    Reports lateness past the target and the one sleep's real length."""
    late, slept = [], []
    for _ in range(n):
        start = time.perf_counter()
        target = start + frame_ms / 1000.0
        end_work = start + work_ms / 1000.0
        while time.perf_counter() < end_work:
            pass
        remaining = target - time.perf_counter()
        if remaining > 0.002:
            a = time.perf_counter()
            time.sleep(0.001)
            slept.append((time.perf_counter() - a) * 1000.0)
        while time.perf_counter() < target:
            pass
        late.append((time.perf_counter() - target) * 1000.0)
    return {"lateness_ms": _stats_ms(late), "sleep_1ms_real_ms": _stats_ms(slept),
            "work_ms": work_ms, "frame_ms": frame_ms}


def timer_resolution() -> Dict[str, Any]:
    nt = ctypes.WinDLL("ntdll")
    mn, mx, cur = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    nt.NtQueryTimerResolution(ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(cur))
    # 100 ns units; "min" is the coarsest (e.g. 15.6 ms), "max" the finest
    return {"coarsest_ms": mn.value / 1e4, "finest_ms": mx.value / 1e4, "current_ms": cur.value / 1e4}


def timing_block() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "perf_counter": str(time.get_clock_info("perf_counter")),
        "monotonic": str(time.get_clock_info("monotonic")),
        "switch_interval_s": sys.getswitchinterval(),
        "timer_resolution": _safe(timer_resolution),
        "default": {"sleep": sleep_granularity(), "precision": precision_emulation()},
    }
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    try:
        out["timeBeginPeriod1"] = {
            "timer_resolution": _safe(timer_resolution),
            "sleep": sleep_granularity(),
            "precision": precision_emulation(),
        }
    finally:
        winmm.timeEndPeriod(1)
    return out


def power_block() -> Dict[str, Any]:
    from ctypes import wintypes

    class SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]
    s = SPS()
    ctypes.WinDLL("kernel32").GetSystemPowerStatus(ctypes.byref(s))
    scheme = subprocess.check_output(["powercfg", "/getactivescheme"], text=True, timeout=30).strip()
    return {"ac_line": {0: "battery", 1: "AC"}.get(s.ACLineStatus, "unknown"),
            "battery_pct": s.BatteryLifePercent, "saver_on": bool(s.SystemStatusFlag),
            "power_scheme": scheme}


def registry_block() -> Dict[str, Any]:
    import winreg

    def get(root, path, name):
        try:
            with winreg.OpenKey(root, path) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return {
        "HAGS_HwSchMode(2=on,1=off)": get(winreg.HKEY_LOCAL_MACHINE,
                                          r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode"),
        "GameMode_AutoGameModeEnabled": get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar",
                                            "AutoGameModeEnabled"),
        "DirectXUserGlobalSettings": get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences",
                                         "DirectXUserGlobalSettings"),
    }


def hardware_block() -> Dict[str, Any]:
    return {
        "cpu": _safe(lambda: _ps("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,"
                                 "NumberOfLogicalProcessors,MaxClockSpeed")),
        "gpu": _safe(lambda: _ps("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,"
                                 "DriverDate,CurrentRefreshRate,CurrentHorizontalResolution,"
                                 "CurrentVerticalResolution")),
        "os": _safe(lambda: _ps("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber")),
        "ram_gb": _safe(lambda: _ps("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB")),
    }


def glfw_block() -> Dict[str, Any]:
    import glfw
    if not glfw.init():
        return {"error": "glfw.init failed"}
    try:
        out: Dict[str, Any] = {"pyglfw": getattr(glfw, "__version__", None),
                               "glfw": glfw.get_version_string().decode() if isinstance(
                                   glfw.get_version_string(), bytes) else glfw.get_version_string()}
        prim = glfw.get_primary_monitor()
        mons = []
        for m in glfw.get_monitors() or []:
            vm = glfw.get_video_mode(m)
            modes = sorted({(v.size.width, v.size.height, v.refresh_rate) for v in glfw.get_video_modes(m)})
            cur = (vm.size.width, vm.size.height)
            mons.append({
                "name": glfw.get_monitor_name(m).decode(errors="replace") if isinstance(
                    glfw.get_monitor_name(m), bytes) else glfw.get_monitor_name(m),
                "primary": bool(ctypes.cast(m, ctypes.c_void_p).value == ctypes.cast(prim, ctypes.c_void_p).value),
                "pos": glfw.get_monitor_pos(m),
                "content_scale": glfw.get_monitor_content_scale(m),
                "mode": {"w": vm.size.width, "h": vm.size.height, "refresh_hz": vm.refresh_rate},
                "refresh_rates_at_current_size": sorted({r for (w_, h_, r) in modes if (w_, h_) == cur}),
            })
        out["monitors"] = mons
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        win = glfw.create_window(64, 64, "env", None, None)
        if win:
            glfw.make_context_current(win)
            gl = ctypes.WinDLL("opengl32")
            gl.glGetString.restype = ctypes.c_char_p
            gl.glGetString.argtypes = [ctypes.c_uint]
            s = lambda e: (gl.glGetString(e) or b"").decode(errors="replace")  # noqa: E731
            out["gl"] = {"vendor": s(0x1F00), "renderer": s(0x1F01), "version": s(0x1F02)}
            out["ext"] = {e: bool(glfw.extension_supported(e)) for e in (
                "WGL_EXT_swap_control", "WGL_EXT_swap_control_tear", "WGL_NV_delay_before_swap")}
            glfw.destroy_window(win)
        return out
    finally:
        glfw.terminate()


def dwm_block() -> Dict[str, Any]:
    import win_vsync
    en = ctypes.c_int()
    ctypes.WinDLL("dwmapi").DwmIsCompositionEnabled(ctypes.byref(en))
    hr, info = win_vsync.dwm_timing()
    freq = win_vsync.qpc_freq()
    return {"composition_enabled": bool(en.value), "hresult": f"0x{hr:08X}",
            "rate_refresh": (info.rateRefresh.num, info.rateRefresh.den) if hr == 0 else None,
            "refresh_hz_exact": (info.rateRefresh.num / info.rateRefresh.den) if hr == 0 and info.rateRefresh.den else None,
            "period_ms": info.qpcRefreshPeriod * 1000.0 / freq if hr == 0 else None,
            "qpc_freq": freq}


def repo_block() -> Dict[str, Any]:
    import fingerprint
    out = {"scena_fingerprint": fingerprint.scena_fingerprint(), "git_head": fingerprint.git_head()}
    for key, cmd in (("autocrlf", ["git", "config", "core.autocrlf"]),
                     ("status_short", ["git", "status", "--short"])):
        try:
            out[key] = subprocess.check_output(cmd, cwd=_REPO, text=True, timeout=30).strip()
        except Exception as exc:
            out[key] = f"n/a ({type(exc).__name__})"
    return out


def packages_block() -> Dict[str, Any]:
    from importlib import metadata
    out = {}
    for name in ("skia-python", "glfw", "numpy", "psutil"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def main(argv=None) -> int:
    if sys.platform != "win32":
        raise SystemExit("win_env.py needs Windows")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", dest="json_path", default=None)
    a = p.parse_args(argv)
    rep = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "python": sys.version, "executable": sys.executable,
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "platform": platform.platform(),
        "hardware": _safe(hardware_block),
        "power": _safe(power_block),
        "registry": _safe(registry_block),
        "packages": _safe(packages_block),
        "repo": _safe(repo_block),
        "dwm": _safe(dwm_block),
        "glfw": _safe(glfw_block),
        "timing": _safe(timing_block),
    }
    print(json.dumps(rep, indent=1, default=str))
    if a.json_path:
        with open(a.json_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
