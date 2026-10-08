"""``scena-editor --shortcut``: a launcher icon for this system, made once.

pip cannot create icons (a package runs no code when it is installed), so the
author runs this once after ``pip install scena``. The launcher starts the
editor with the Python that ran this command (absolute path), without a
terminal window; run the command again after reinstalling Python.

- Windows: ``Scena Editor`` in the Start menu and on the desktop (``.lnk``,
  made through PowerShell, which every Windows has).
- macOS: ``~/Applications/Scena Editor.app`` (Launchpad, Spotlight, the Dock), an
  AppleScript applet: a native universal executable (no Rosetta prompt).
- Linux: a ``scena-editor.desktop`` launcher in the applications menu, and a
  copy on the desktop when there is one.

The icon is drawn with Skia when the command runs (no image files shipped).
Builders take ``home`` / ``env`` / ``run`` so tests can check what they write.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Callable, Dict, List, Optional

APP_NAME = "Scena Editor"
BUNDLE_ID = "org.scena.editor"
# Before 0.6.0 the framework was Stage: launchers made then carry the old
# names. ``remove_legacy`` deletes them so a menu never shows both.
LEGACY_APP_NAME = "Stage Editor"
LEGACY_SLUG = "stage-editor"


# -- the icon ---------------------------------------------------------------------------

def icon_png(size: int) -> bytes:
    """The editor icon as PNG bytes: a dark tile with a turned rectangle, a
    circle and a point — geometry placed on a level."""
    import skia
    s = float(size)
    surface = skia.Surface(size, size)
    c = surface.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    tile = skia.Paint(AntiAlias=True, Color=skia.Color(38, 44, 58))
    c.drawRoundRect(skia.Rect.MakeXYWH(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.2, s * 0.2, tile)
    grid = skia.Paint(AntiAlias=True, Color=skia.Color(255, 255, 255, 28),
                      Style=skia.Paint.kStroke_Style, StrokeWidth=max(1.0, s / 128))
    for i in range(1, 6):
        v = s * (0.04 + 0.92 * i / 6)
        c.drawLine(s * 0.1, v, s * 0.9, v, grid)
        c.drawLine(v, s * 0.1, v, s * 0.9, grid)
    stroke = max(1.5, s / 28)
    gold = skia.Paint(AntiAlias=True, Color=skia.Color(255, 205, 64),
                      Style=skia.Paint.kStroke_Style, StrokeWidth=stroke)
    fill = skia.Paint(AntiAlias=True, Color=skia.Color(255, 205, 64, 70))
    c.save()
    c.translate(s * 0.42, s * 0.6)
    c.rotate(-18)
    rect = skia.Rect.MakeXYWH(-s * 0.22, -s * 0.09, s * 0.44, s * 0.18)
    c.drawRect(rect, fill)
    c.drawRect(rect, gold)
    c.restore()
    blue = skia.Paint(AntiAlias=True, Color=skia.Color(120, 200, 255),
                      Style=skia.Paint.kStroke_Style, StrokeWidth=stroke)
    c.drawCircle(s * 0.68, s * 0.32, s * 0.13, blue)
    dot = skia.Paint(AntiAlias=True, Color=skia.Color(255, 255, 255))
    c.drawCircle(s * 0.27, s * 0.3, s * 0.045, dot)
    data = surface.makeImageSnapshot().encodeToData()
    return bytes(data)


def icon_ico(png256: bytes) -> bytes:
    """A Windows ``.ico`` holding one 256×256 PNG (supported since Vista)."""
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png256), 6 + 16)
    return header + entry + png256


# -- per system --------------------------------------------------------------------------

def _gui_python(python: str, platform: str) -> str:
    """``pythonw.exe`` next to ``python.exe`` on Windows (no console window)."""
    if platform == "win32":
        candidate = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return python


def windows(python: str, home: str, env: Dict[str, str],
            run: Callable[[List[str], Dict[str, str]], None]) -> List[str]:
    """Start-menu and desktop shortcuts through PowerShell's WScript.Shell."""
    appdata = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    folder = os.path.join(local, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    ico = os.path.join(folder, "scena_editor.ico")
    with open(ico, "wb") as f:
        f.write(icon_ico(icon_png(256)))
    menu = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                        APP_NAME + ".lnk")
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        "foreach ($path in @($env:SCENA_LNK_MENU, (Join-Path $desktop 'Scena Editor.lnk'))) { "
        "$s = $shell.CreateShortcut($path); "
        "$s.TargetPath = $env:SCENA_LNK_TARGET; $s.Arguments = '-m scena_editor'; "
        "$s.WorkingDirectory = $env:SCENA_LNK_HOME; $s.IconLocation = $env:SCENA_LNK_ICON; "
        "$s.Description = 'Scena level editor'; $s.Save(); Write-Output $path }"
    )
    values = {"SCENA_LNK_MENU": menu, "SCENA_LNK_TARGET": _gui_python(python, "win32"),
              "SCENA_LNK_HOME": home, "SCENA_LNK_ICON": ico}
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], values)
    return [menu, os.path.join(home, "Desktop", APP_NAME + ".lnk")]


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos(python: str, home: str, env: Dict[str, str],
          run: Callable[[List[str], Dict[str, str]], None]) -> List[str]:
    """``~/Applications/Scena Editor.app`` as an AppleScript applet.

    The applet's executable is Apple's universal (arm64 + x86_64) binary, so
    it opens natively everywhere. An app whose executable is a shell script
    has no architecture LaunchServices can read: on Apple Silicon it asks for
    Rosetta. The applet starts ``python -m scena_editor`` in the background
    and quits. Built with ``osacompile``; our icon and name go in; then it is
    signed again ad hoc (``codesign -s -``) — editing a signed bundle breaks
    its seal, and arm64 code must be signed to run. All three tools ship
    with macOS.
    """
    app = os.path.join(home, "Applications", APP_NAME + ".app")
    if os.path.isdir(app):
        shutil.rmtree(app)
    os.makedirs(os.path.dirname(app), exist_ok=True)
    script = ("set py to " + _applescript_string(python) + "\n"
              'do shell script "cd ~ && " & quoted form of py & '
              '" -m scena_editor > /dev/null 2>&1 &"')
    run(["osacompile", "-o", app, "-e", script], {})
    contents = os.path.join(app, "Contents")
    resources = os.path.join(contents, "Resources")
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "scena_editor.iconset")
        os.makedirs(iconset)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                with open(os.path.join(iconset, name), "wb") as f:
                    f.write(icon_png(size * scale))
        icns = os.path.join(tmp, "scena_editor.icns")
        try:
            run(["iconutil", "-c", "icns", iconset, "-o", icns], {})
        except (OSError, subprocess.SubprocessError):
            pass
        if os.path.exists(icns):
            shutil.copyfile(icns, os.path.join(resources, "applet.icns"))
            # The asset catalog would win over applet.icns.
            catalog = os.path.join(resources, "Assets.car")
            if os.path.exists(catalog):
                os.remove(catalog)
    import plistlib
    info_path = os.path.join(contents, "Info.plist")
    with open(info_path, "rb") as f:
        info = plistlib.load(f)
    info.pop("CFBundleIconName", None)
    info.update({
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleIconFile": "applet",
    })
    with open(info_path, "wb") as f:
        plistlib.dump(info, f)
    run(["codesign", "--force", "--deep", "--sign", "-", app], {})
    return [app]


def linux(python: str, home: str, env: Dict[str, str],
          run: Callable[[List[str], Dict[str, str]], None]) -> List[str]:
    """A ``.desktop`` launcher in the applications menu (and on the desktop)."""
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    icon = os.path.join(data, "icons", "scena-editor.png")
    os.makedirs(os.path.dirname(icon), exist_ok=True)
    with open(icon, "wb") as f:
        f.write(icon_png(256))
    entry = ("[Desktop Entry]\nType=Application\n"
             f"Name={APP_NAME}\nComment=Level editor for Scena games\n"
             f'Exec="{python}" -m scena_editor %f\n'
             f"Icon={icon}\nPath={home}\nTerminal=false\n"
             "Categories=Development;Graphics;\nMimeType=application/json;\n")
    made = []
    menu = os.path.join(data, "applications", "scena-editor.desktop")
    targets = [menu]
    desktop = os.path.join(home, "Desktop")
    if os.path.isdir(desktop):
        targets.append(os.path.join(desktop, "scena-editor.desktop"))
    for path in targets:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(entry)
        os.chmod(path, 0o755)
        made.append(path)
    return made


def _run(cmd: List[str], extra_env: Dict[str, str]) -> None:
    env = dict(os.environ)
    env.update(extra_env)
    # External tools write in the locale; errors="replace" keeps a stray byte
    # from turning a failed command into a UnicodeDecodeError.
    subprocess.run(cmd, env=env, check=True, capture_output=True, text=True,
                   errors="replace", timeout=120)


def legacy_paths(platform: str, home: str, env: Dict[str, str]) -> List[str]:
    """Where the pre-0.6.0 command (``stage-editor --shortcut``) put launchers.

    Only launchers and their icon: the old log folder keeps the old logs.
    """
    if platform == "win32":
        appdata = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return [
            os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                         LEGACY_APP_NAME + ".lnk"),
            os.path.join(home, "Desktop", LEGACY_APP_NAME + ".lnk"),
            os.path.join(local, LEGACY_APP_NAME, "stage_editor.ico"),
        ]
    if platform == "darwin":
        return [os.path.join(home, "Applications", LEGACY_APP_NAME + ".app")]
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return [
        os.path.join(data, "applications", LEGACY_SLUG + ".desktop"),
        os.path.join(home, "Desktop", LEGACY_SLUG + ".desktop"),
        os.path.join(data, "icons", LEGACY_SLUG + ".png"),
    ]


def remove_legacy(platform: Optional[str] = None, *, home: Optional[str] = None,
                  env: Optional[Dict[str, str]] = None) -> List[str]:
    """Delete the pre-0.6.0 launchers that exist. Returns the paths removed;
    a path that cannot be removed is skipped (the new launcher still works)."""
    platform = platform or sys.platform
    home = home or os.path.expanduser("~")
    env = dict(os.environ) if env is None else env
    removed = []
    for path in legacy_paths(platform, home, env):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.remove(path)
            else:
                continue
        except OSError:
            continue
        removed.append(path)
    return removed


def create(platform: Optional[str] = None, *, python: Optional[str] = None,
           home: Optional[str] = None, env: Optional[Dict[str, str]] = None,
           run: Optional[Callable[[List[str], Dict[str, str]], None]] = None) -> List[str]:
    """Make the launcher for ``platform`` (default: this system). Returns the
    paths made."""
    platform = platform or sys.platform
    python = os.path.abspath(python or sys.executable)
    home = home or os.path.expanduser("~")
    env = dict(os.environ) if env is None else env
    run = run or _run
    if platform == "win32":
        return windows(python, home, env, run)
    if platform == "darwin":
        return macos(python, home, env, run)
    return linux(python, home, env, run)
