"""Tool-Erkennung, -Validierung und Versions-Abfrage."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

REQUIRED = ("mkvmerge", "ffmpeg")   # ffmpeg nur für Stereo-Aktionen nötig
_VERSION_RE = {
    "mkvmerge": re.compile(r"mkvmerge v([\d.]+)"),
    "ffmpeg": re.compile(r"ffmpeg version (\S+)"),
}


@dataclass
class ToolStatus:
    name: str
    path: str
    version: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.version)


def detect_tools(base_path: Path, configured: dict[str, str]) -> dict[str, str]:
    """Konfigurierte Pfade haben Vorrang, sonst tools/-Ordner."""
    result: dict[str, str] = {}
    for name in REQUIRED:
        configured_path = configured.get(name, "")
        if configured_path and Path(configured_path).exists():
            result[name] = configured_path
            continue
        candidate = base_path / "tools" / f"{name}.exe"
        result[name] = str(candidate) if candidate.exists() else ""
    return result


def probe(name: str, path: str) -> ToolStatus:
    """Startet das Tool mit --version und parst die Versionsnummer."""
    status = ToolStatus(name=name, path=path)
    if not path or not Path(path).exists():
        return status
    flag = "--version" if name == "mkvmerge" else "-version"
    try:
        result = subprocess.run(
            [path, flag], capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=15, creationflags=_CREATE_NO_WINDOW)
        match = _VERSION_RE[name].search(result.stdout or "")
        if match:
            # ffmpeg-Git-Builds: "2025-09-04-git-…" auf Datum kürzen
            status.version = match.group(1).split("-git")[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return status


def probe_all(paths: dict[str, str]) -> dict[str, ToolStatus]:
    return {name: probe(name, paths.get(name, "")) for name in REQUIRED}
