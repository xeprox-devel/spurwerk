"""Tool-Erkennung, -Validierung und Versions-Abfrage."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.update import parse_version

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

REQUIRED = ("mkvmerge", "ffmpeg")   # ffmpeg nur für Konvertier-Aktionen nötig
# optional: ffprobe (DV-Analyse), dovi_tool („DV/HDR → HDR10“)
OPTIONAL = ("ffprobe", "dovi_tool")
ALL_TOOLS = REQUIRED + OPTIONAL

_VERSION_RE = {
    "mkvmerge": re.compile(r"mkvmerge v([\d.]+)"),
    "ffmpeg": re.compile(r"ffmpeg version (\S+)"),
    "ffprobe": re.compile(r"ffprobe version (\S+)"),
    "dovi_tool": re.compile(r"dovi_tool ([\d.]+)"),
}
_VERSION_FLAG = {
    "mkvmerge": "--version", "ffmpeg": "-version", "ffprobe": "-version",
    "dovi_tool": "--version",
}
# gyan-Release-Builds melden „8.1.2-essentials_build-www.gyan.dev“
_RELEASE_SUFFIX_RE = re.compile(r"^\d+(\.\d+)+-")
# Entwicklungs-Builds: gyan-Git („2025-09-04“ nach dem Kürzen), BtbN („N-…“)
_DEV_BUILD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|N-)")

# Download-Paket → Leit-EXE, an deren Version das Paket erkannt wird
# (mkvextract kommt mit MKVToolNix, ffprobe mit FFmpeg)
KIND_EXE = {"mkvtoolnix": "mkvmerge", "ffmpeg": "ffmpeg",
            "dovi_tool": "dovi_tool"}
KIND_TITLE = {"mkvtoolnix": "MKVToolNix", "ffmpeg": "FFmpeg",
              "dovi_tool": "dovi_tool"}
# alle erkannten EXEs eines Pakets — ein Update ersetzt sie gemeinsam
KIND_EXES = {"mkvtoolnix": ("mkvmerge",), "ffmpeg": ("ffmpeg", "ffprobe"),
             "dovi_tool": ("dovi_tool",)}

# Update-Zustand eines installierten Werkzeugs
CURRENT, OUTDATED, UNKNOWN = "current", "outdated", "unknown"


@dataclass
class ToolStatus:
    name: str
    path: str
    version: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.version)


def detect_tools(base_path: Path, configured: dict[str, str]) -> dict[str, str]:
    """Konfigurierte Pfade haben Vorrang, sonst tools/-Ordner (flach)."""
    result: dict[str, str] = {}
    for name in ALL_TOOLS:
        configured_path = configured.get(name, "")
        if configured_path and Path(configured_path).exists():
            result[name] = configured_path
            continue
        # ffprobe gehört zu ffmpeg: neben einer selbst gewählten ffmpeg.exe
        # gilt es mit (wie mkvextract neben mkvmerge im Runner)
        if name == "ffprobe" and result.get("ffmpeg"):
            sibling = Path(result["ffmpeg"]).with_name("ffprobe.exe")
            if sibling.exists():
                result[name] = str(sibling)
                continue
        candidate = base_path / "tools" / f"{name}.exe"
        result[name] = str(candidate) if candidate.exists() else ""
    return result


def probe(name: str, path: str) -> ToolStatus:
    """Startet das Tool mit --version und parst die Versionsnummer."""
    status = ToolStatus(name=name, path=path)
    if not path or not Path(path).exists():
        return status
    flag = _VERSION_FLAG.get(name, "--version")
    try:
        result = subprocess.run(
            [path, flag], capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=15, creationflags=_CREATE_NO_WINDOW)
        # stdout UND stderr durchsuchen — manche Tools melden dorthin
        match = _VERSION_RE[name].search(
            (result.stdout or "") + (result.stderr or ""))
        if match:
            # ffmpeg-Git-Builds: "2025-09-04-git-…" auf Datum kürzen
            version = match.group(1).split("-git")[0]
            # Release-Builds: Build-Anhängsel weg, die Nummer bleibt
            if _RELEASE_SUFFIX_RE.match(version):
                version = version.split("-", 1)[0]
            status.version = version
    except (OSError, subprocess.SubprocessError):
        pass
    return status


def probe_all(paths: dict[str, str]) -> dict[str, ToolStatus]:
    return {name: probe(name, paths.get(name, "")) for name in ALL_TOOLS}


# ── Update-Vergleich (rein, ohne Netz) ────────────────────────────────────


@dataclass(frozen=True)
class ToolUpdate:
    kind: str        # Download-Paket: mkvtoolnix / ffmpeg / dovi_tool
    installed: str
    latest: str


def comparable_version(version: str) -> tuple[int, ...]:
    """Versionsnummer als Zahlentupel. Entwicklungs-Builds (Datum, Git,
    „N-…“) ergeben () — sie lassen sich mit keinem Release vergleichen."""
    version = version.strip()
    if not version or _DEV_BUILD_RE.match(version):
        return ()
    return parse_version(version)


def update_state(installed: str, latest: str | None) -> str:
    """CURRENT, OUTDATED oder UNKNOWN (kein Netz, Entwicklungs-Build,
    Quelle ohne Versionsangabe). Eine NEUERE installierte Version als die
    veröffentlichte gilt als aktuell — nie zu einem Downgrade raten."""
    have = comparable_version(installed)
    new = comparable_version(latest or "")
    if not have or not new:
        return UNKNOWN
    return OUTDATED if new > have else CURRENT


def pending_updates(status: dict[str, ToolStatus],
                    latest: dict[str, str | None]) -> list[ToolUpdate]:
    """Installierte Werkzeuge, für die sicher eine neuere Version existiert.
    Fehlende Werkzeuge zählen nicht — die bietet das Onboarding an."""
    updates: list[ToolUpdate] = []
    for kind, exe in KIND_EXE.items():
        info = status.get(exe)
        newest = latest.get(kind)
        if (info and info.ok and newest
                and update_state(info.version, newest) == OUTDATED):
            updates.append(ToolUpdate(kind, info.version, newest))
    return updates
