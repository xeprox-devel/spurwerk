"""Datei-Analyse über `mkvmerge -J`."""

from __future__ import annotations

import json
import os
import subprocess

from .langs import normalize
from .model import MediaInfo, Track

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class ScanError(Exception):
    pass


def scan_file(mkvmerge: str, path: str, timeout: float = 60.0) -> MediaInfo:
    """Analysiert eine Datei; wirft ScanError mit verständlicher Meldung."""
    try:
        result = subprocess.run(
            [mkvmerge, "-J", path],
            capture_output=True, text=True, encoding="utf-8",
            creationflags=_CREATE_NO_WINDOW, timeout=timeout)
    except FileNotFoundError as exc:
        raise ScanError(f"mkvmerge nicht gefunden: {mkvmerge}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScanError("Analyse-Timeout — Datei nicht lesbar?") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ScanError("mkvmerge lieferte kein gültiges JSON.") from exc

    if result.returncode >= 2 or not data.get("container", {}).get("recognized"):
        errors = "; ".join(data.get("errors", [])) or "Container nicht erkannt"
        raise ScanError(errors)

    return parse_mkvmerge_json(data, path)


def parse_mkvmerge_json(data: dict, path: str) -> MediaInfo:
    """Reiner Parser (testbar ohne Prozessstart)."""
    tracks = []
    for t in data.get("tracks", []):
        props = t.get("properties", {})
        tracks.append(Track(
            id=t["id"],
            type=t["type"],
            codec_id=props.get("codec_id", "?"),
            codec_name=t.get("codec", props.get("codec_id", "?")),
            lang=normalize(props.get("language"), props.get("language_ietf")),
            name=props.get("track_name", ""),
            channels=props.get("audio_channels"),
            default=bool(props.get("default_track")),
            forced=bool(props.get("forced_track")),
            minimum_timestamp_ns=props.get("minimum_timestamp"),
        ))

    container_props = data.get("container", {}).get("properties", {})
    duration_ns = container_props.get("duration") or 0

    return MediaInfo(
        path=path,
        tracks=tuple(tracks),
        has_chapters=bool(data.get("chapters")),
        attachment_count=len(data.get("attachments", [])),
        duration_s=duration_ns / 1_000_000_000,
        title=container_props.get("title", ""),
    )
