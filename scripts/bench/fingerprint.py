"""Content hashes for bench scripts and the ``scena/`` package.

Pulse logs already hashed their own scripts. This module also hashes the
framework so two rows can be compared for "did the code change" without git.

Once git exists, keep the same ``scena_fingerprint`` slot and optionally
show ``git_head()`` next to it — no format change.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
SCENA_DIR = REPO_ROOT / "scena"


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def script_hashes(
    names: Iterable[str],
    directory: Optional[Path] = None,
) -> Dict[str, str]:
    root = directory if directory is not None else BENCH_DIR
    return {name: sha12(root / name) for name in names}


def scripts_fingerprint(hashes: Mapping[str, str], order: Iterable[str]) -> str:
    parts = " ".join(f"{k}:{hashes[k]}" for k in order)
    return hashlib.sha256(parts.encode()).hexdigest()[:12]


def scena_fingerprint() -> str:
    """sha256 over sorted (path, contents) of every ``scena/**/*.py`` file."""
    h = hashlib.sha256()
    root = SCENA_DIR
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def git_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or "none"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "none"


def host_info() -> Dict[str, str]:
    cpu = platform.processor() or ""
    if sys.platform == "darwin":
        try:
            cpu = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass
    os_ver = platform.mac_ver()[0] if sys.platform == "darwin" else platform.version()
    return {
        "cpu": cpu or platform.machine(),
        "machine": platform.machine(),
        "os": f"{platform.system()} {os_ver}".strip(),
        "python": platform.python_version(),
    }


def host_oneline(host: Optional[Mapping[str, str]] = None) -> str:
    info = dict(host) if host is not None else host_info()
    return f"{info['cpu']} · {info['os']} · Py {info['python']}"
