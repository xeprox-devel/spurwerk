"""Tool-Downloader: holt mkvmerge/mkvextract, ffmpeg/ffprobe und dovi_tool
in den tools/-Ordner.

Komplett Standardbibliothek (urllib, gzip, xml, hashlib, zipfile).
Quellen (verifiziert 2026-07-04, siehe UMSETZUNGSPLAN.md Abschnitt 6):

  MKVToolNix  Version aus latest-release.xml.gz, dann offizielle portable
              ZIP (existiert seit v92, nur STORED/DEFLATE), SHA-256 aus
              sha256sums.txt. Die EXEs sind statisch gelinkt.
  FFmpeg x64  gyan.dev release-essentials.zip (echtes Stable-Release,
              .sha256 daneben); Fallback BtbN GitHub latest.
  FFmpeg x86  Community-Build sudo-nautilus/FFmpeg-Builds-Win32.
  dovi_tool   GitHub-Release von quietvoid (nur 64-bit).

Die Architektur richtet sich nach dem BETRIEBSSYSTEM (nicht nach der
Python-Bitness): ein 32-bit-Prozess auf 64-bit-Windows startet problemlos
64-bit-Tools.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import shutil
import threading
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from version import USER_AGENT as _APP_USER_AGENT

USER_AGENT = f"{_APP_USER_AGENT} (Tool-Downloader; Windows)"
TIMEOUT = 30
CHECK_TIMEOUT = 8    # reine Versionsabfragen: kurz, damit offline nichts hängt
CHUNK = 1024 * 1024

MKVTOOLNIX_XML = "https://mkvtoolnix.download/latest-release.xml.gz"
MKVTOOLNIX_DL = "https://mkvtoolnix.download/windows/releases"
GYAN_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
GYAN_VERSION = "https://www.gyan.dev/ffmpeg/builds/release-version"
BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download"
WIN32_BASE = ("https://github.com/sudo-nautilus/FFmpeg-Builds-Win32"
              "/releases/latest/download")

DOVI_API = "https://api.github.com/repos/quietvoid/dovi_tool/releases/latest"
DOVI_LATEST = "https://github.com/quietvoid/dovi_tool/releases/latest"
DOVI_DOWNLOAD = "https://github.com/quietvoid/dovi_tool/releases/download"

DOWNLOAD_PAGES = {
    "mkvtoolnix": "https://mkvtoolnix.download/downloads.html",
    "ffmpeg": "https://www.gyan.dev/ffmpeg/builds/",
    "dovi_tool": "https://github.com/quietvoid/dovi_tool/releases",
}


class DownloadError(Exception):
    pass


# progress_cb(schritt_text, prozent 0..100 oder None für unbestimmt)
ProgressCb = Callable[[str, int | None], None]


@dataclass
class DownloadResult:
    tool: str
    version: str
    files: list[str] = field(default_factory=list)
    verified: bool = True    # False: Quelle ohne Prüfsumme (wird angesagt)


def os_is_64bit() -> bool:
    if os.environ.get("PROCESSOR_ARCHITEW6432"):
        return True
    return platform.machine().endswith("64")


# ── HTTP-Bausteine ────────────────────────────────────────────────────────


def _open(url: str, timeout: float = TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def _get_bytes(url: str, timeout: float = TIMEOUT) -> bytes:
    with _open(url, timeout) as response:
        return response.read()


def _get_text(url: str, timeout: float = TIMEOUT) -> str:
    return _get_bytes(url, timeout).decode("utf-8", errors="replace").strip()


def _final_url(url: str, timeout: float = TIMEOUT) -> str:
    """Ziel-URL nach allen Weiterleitungen — per HEAD, lädt keinen Inhalt."""
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def _release_number(text: str) -> str:
    """Nur eine saubere Release-Nummer („102.0“, „9.0.2“) durchlassen —
    eine Fehlerseite oder ein Platzhalter darf nie als Version gelten."""
    text = text.strip().lstrip("vV")
    parts = text.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"keine Versionsnummer: {text[:40]!r}")
    return text


def _download(url: str, dest: Path, progress: ProgressCb, label: str,
              cancel: threading.Event) -> str:
    """Streamt eine Datei nach dest, liefert den SHA-256-Hexdigest."""
    sha = hashlib.sha256()
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with _open(url) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel.is_set():
                    raise DownloadError("Abgebrochen.")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                pct = int(done / total * 100) if total else None
                progress(f"{label} — {done // (1024 * 1024)} MB …", pct)
        part.replace(dest)
        return sha.hexdigest()
    except OSError as exc:
        raise DownloadError(f"Download fehlgeschlagen: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def _expect_hash(sums_text: str, filename: str) -> str | None:
    """Parst beide sha256-Formate: 'hash  name' pro Zeile ODER nackter Digest."""
    lines = [ln.strip() for ln in sums_text.splitlines() if ln.strip()]
    for line in lines:
        parts = line.replace("*", " ").split()
        if len(parts) < 2:
            continue
        # exakter Dateinamen-Vergleich (Pfadpräfixe abschneiden) — endswith
        # würde auch "xyz-<name>.zip" matchen
        name = parts[-1].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name == filename.lower():
            return parts[0].lower()
    if len(lines) == 1 and len(lines[0].split()[0]) == 64:
        return lines[0].split()[0].lower()
    return None


def _extract_members(archive: Path, wanted_suffixes: dict[str, str],
                     tools_dir: Path, progress: ProgressCb) -> list[str]:
    """Extrahiert nur die gewünschten EXEs flach nach tools/.

    wanted_suffixes: Member-Endung (lowercase, '/'-normalisiert) → Zieldatei.
    """
    extracted: list[str] = []
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                normalized = member.replace("\\", "/").lower()
                for suffix, target_name in wanted_suffixes.items():
                    if normalized.endswith(suffix):
                        progress(f"Entpacke {target_name} …", None)
                        target = tools_dir / target_name
                        # erst .part schreiben, dann atomar ersetzen — nie
                        # eine halbe EXE hinterlassen
                        part = target.with_suffix(".part")
                        try:
                            with zf.open(member) as src, \
                                    open(part, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            part.replace(target)
                        finally:
                            # EXE in Benutzung, Platte voll, CRC-Fehler:
                            # keine 100-MB-Reste in tools/ liegen lassen
                            part.unlink(missing_ok=True)
                        extracted.append(str(target))
    except PermissionError as exc:
        raise DownloadError(
            "EXE wird gerade verwendet — bitte laufende Jobs beenden und "
            "erneut versuchen.") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise DownloadError(f"Entpacken fehlgeschlagen: {exc}") from exc
    missing = set(wanted_suffixes.values()) - {Path(p).name for p in extracted}
    if missing:
        raise DownloadError(
            f"Archiv unvollständig — nicht gefunden: {', '.join(missing)}")
    return extracted


# ── MKVToolNix ────────────────────────────────────────────────────────────


def mkvtoolnix_latest_version(timeout: float = TIMEOUT) -> str:
    xml_data = gzip.decompress(_get_bytes(MKVTOOLNIX_XML, timeout))
    version = ET.fromstring(xml_data).findtext("latest-source/version")
    if not version:
        raise DownloadError("Konnte MKVToolNix-Version nicht ermitteln.")
    return version.strip()


def download_mkvtoolnix(tools_dir: Path, progress: ProgressCb,
                        cancel: threading.Event) -> DownloadResult:
    progress("Ermittle aktuelle Version …", None)
    try:
        version = mkvtoolnix_latest_version()
    except (OSError, gzip.BadGzipFile, ET.ParseError) as exc:
        raise DownloadError(
            f"mkvtoolnix.download nicht erreichbar: {exc}") from exc
    arch = "64" if os_is_64bit() else "32"
    filename = f"mkvtoolnix-{arch}-bit-{version}.zip"
    url = f"{MKVTOOLNIX_DL}/{version}/{filename}"

    progress("Lade Prüfsummen …", None)
    try:
        expected = _expect_hash(
            _get_text(f"{MKVTOOLNIX_DL}/{version}/sha256sums.txt"), filename)
    except OSError:
        expected = None  # Prüfsumme optional, Download selbst nicht

    tools_dir.mkdir(parents=True, exist_ok=True)
    archive = tools_dir / filename
    try:
        actual = _download(url, archive, progress,
                           f"MKVToolNix {version}", cancel)
        if expected and actual != expected:
            raise DownloadError("SHA-256-Prüfung fehlgeschlagen — "
                                "Download beschädigt?")
        files = _extract_members(
            archive,
            {"mkvtoolnix/mkvmerge.exe": "mkvmerge.exe",
             "mkvtoolnix/mkvextract.exe": "mkvextract.exe"},
            tools_dir, progress)
        return DownloadResult("mkvtoolnix", version, files,
                              verified=bool(expected))
    finally:
        archive.unlink(missing_ok=True)


# ── FFmpeg ────────────────────────────────────────────────────────────────


def download_ffmpeg(tools_dir: Path, progress: ProgressCb,
                    cancel: threading.Event) -> DownloadResult:
    tools_dir.mkdir(parents=True, exist_ok=True)
    if os_is_64bit():
        try:
            return _ffmpeg_from(GYAN_ZIP, f"{GYAN_ZIP}.sha256",
                                _gyan_version(), tools_dir, progress, cancel)
        except DownloadError as exc:
            if cancel.is_set():
                raise
            progress(f"gyan.dev nicht erreichbar ({exc}) — "
                     f"wechsle zu GitHub-Fallback …", None)
            return _ffmpeg_from(
                f"{BTBN_BASE}/ffmpeg-master-latest-win64-gpl.zip",
                f"{BTBN_BASE}/checksums.sha256",
                "master-latest", tools_dir, progress, cancel)
    return _ffmpeg_from(
        f"{WIN32_BASE}/ffmpeg-master-latest-win32-gpl.zip",
        f"{WIN32_BASE}/checksums.sha256",
        "master-latest (win32)", tools_dir, progress, cancel)


def _gyan_version() -> str:
    try:
        return _get_text(GYAN_VERSION)
    except OSError:
        return "release"


def _ffmpeg_from(url: str, sums_url: str, version: str, tools_dir: Path,
                 progress: ProgressCb,
                 cancel: threading.Event) -> DownloadResult:
    filename = url.rsplit("/", 1)[-1]
    expected = None
    try:
        expected = _expect_hash(_get_text(sums_url), filename)
    except OSError:
        pass  # Prüfsumme optional (Community-Quellen), Download selbst nicht

    archive = tools_dir / filename
    try:
        actual = _download(url, archive, progress, f"FFmpeg {version}", cancel)
        if expected and actual != expected:
            raise DownloadError("SHA-256-Prüfung fehlgeschlagen — "
                                "Download beschädigt?")
        files = _extract_members(
            archive,
            {"bin/ffmpeg.exe": "ffmpeg.exe",
             "bin/ffprobe.exe": "ffprobe.exe"},   # ffprobe: DV-/HDR-Analyse
            tools_dir, progress)
        return DownloadResult("ffmpeg", version, files,
                              verified=bool(expected))
    finally:
        archive.unlink(missing_ok=True)


# ── dovi_tool (DV/HDR-Kompatibilitäts-Remux) ─────────────────────────────


def dovi_tool_release(timeout: float = TIMEOUT) -> tuple[str, dict]:
    """(Version, Windows-x64-Asset) des neuesten dovi_tool-Releases."""
    release = json.loads(_get_bytes(DOVI_API, timeout))
    version = str(release.get("tag_name", "?")).strip().lstrip("vV")
    # Achtung: im selben Release liegt auch libdovi-*-windows-msvc.zip —
    # deshalb strikt aufs dovi_tool-Präfix matchen
    asset = next(
        a for a in release.get("assets", [])
        if a["name"].startswith("dovi_tool-")
        and "x86_64-pc-windows" in a["name"]
        and a["name"].endswith(".zip"))
    return version, asset


def _dovi_tool_release_via_web(timeout: float = TIMEOUT) -> tuple[str, dict]:
    """Ersatzweg ohne API (z. B. API-Limit bei geteilter IP): Version aus
    der latest-Weiterleitung, Asset nach dem festen Namensschema — dann
    allerdings ohne Digest."""
    tag = _final_url(DOVI_LATEST, timeout).rstrip("/").rsplit("/", 1)[-1]
    version = _release_number(tag)
    name = f"dovi_tool-{version}-x86_64-pc-windows-msvc.zip"
    return version, {"name": name, "browser_download_url":
                     f"{DOVI_DOWNLOAD}/{tag}/{name}"}


def _asset_sha256(asset: dict) -> str | None:
    """GitHub liefert seit 2025 pro Asset „digest“: „sha256:<hex>“."""
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        value = digest.split(":", 1)[1].strip().lower()
        if len(value) == 64:
            return value
    return None


def download_dovi_tool(tools_dir: Path, progress: ProgressCb,
                       cancel: threading.Event) -> DownloadResult:
    """dovi_tool von GitHub — die Versionsnummer steckt im Asset-Namen,
    darum führt der Weg über die GitHub-API (releases/latest)."""
    if not os_is_64bit():
        raise DownloadError("dovi_tool gibt es nur für 64-bit-Windows.")
    tools_dir.mkdir(parents=True, exist_ok=True)
    progress("Ermittle aktuelle dovi_tool-Version …", None)
    try:
        try:
            version, asset = dovi_tool_release()
        except OSError:
            # API gestört/limitiert → normaler Release-Link, wie bei
            # Quellen ohne Prüfsummen-Datei dann ohne SHA-256
            progress("GitHub-API nicht erreichbar — nehme den Release-Link "
                     "(ohne Prüfsumme) …", None)
            version, asset = _dovi_tool_release_via_web()
    except (OSError, StopIteration, ValueError, KeyError) as exc:
        raise DownloadError(
            f"GitHub-Release nicht auflösbar: {exc}") from exc

    expected = _asset_sha256(asset)   # None: ältere Releases, Ersatzweg
    archive = tools_dir / asset["name"]
    try:
        actual = _download(asset["browser_download_url"], archive, progress,
                           f"dovi_tool {version}", cancel)
        if expected and actual != expected:
            raise DownloadError("SHA-256-Prüfung fehlgeschlagen — "
                                "Download beschädigt?")
        files = _extract_members(
            archive, {"dovi_tool.exe": "dovi_tool.exe"}, tools_dir, progress)
        return DownloadResult("dovi_tool", version, files,
                              verified=bool(expected))
    finally:
        archive.unlink(missing_ok=True)


DOWNLOADERS = {
    "mkvtoolnix": download_mkvtoolnix,
    "ffmpeg": download_ffmpeg,
    "dovi_tool": download_dovi_tool,
}


def can_download(kind: str) -> bool:
    """Gibt es für dieses System eine Quelle? dovi_tool: nur 64-bit."""
    return kind in DOWNLOADERS and (kind != "dovi_tool" or os_is_64bit())


# ── Update-Prüfung ────────────────────────────────────────────────────────


def _latest_mkvtoolnix() -> str:
    return _release_number(mkvtoolnix_latest_version(CHECK_TIMEOUT))


def _latest_ffmpeg() -> str | None:
    # Nur gyan.dev nennt eine Release-Nummer; die 32-bit-Quelle liefert
    # ausschließlich „master-latest“-Snapshots ohne vergleichbare Version
    if not os_is_64bit():
        return None
    return _release_number(_get_text(GYAN_VERSION, CHECK_TIMEOUT))


def _latest_dovi_tool() -> str | None:
    # Die Weiterleitung von releases/latest (…/tag/2.3.4) statt der API:
    # zählt nicht gegen GitHubs API-Limit (60 Anfragen/Stunde je IP), das
    # sich die App-Update-Prüfung und der eigentliche Download teilen
    if not os_is_64bit():
        return None
    tag_url = _final_url(DOVI_LATEST, CHECK_TIMEOUT)
    return _release_number(tag_url.rstrip("/").rsplit("/", 1)[-1])


LATEST_CHECKS = {
    "mkvtoolnix": _latest_mkvtoolnix,
    "ffmpeg": _latest_ffmpeg,
    "dovi_tool": _latest_dovi_tool,
}


def latest_versions() -> dict[str, str | None]:
    """Neueste veröffentlichte Version je Download-Paket — genau das, was
    der Downloader jetzt holen würde. None = nicht ermittelbar (offline,
    Quelle gestört, keine Versionsangabe). Wirft nie: die Prüfung läuft
    still im Hintergrund und darf die App nie stören."""
    result: dict[str, str | None] = {}
    for kind, check in LATEST_CHECKS.items():
        try:
            result[kind] = check()
        except Exception:
            result[kind] = None
    return result
