"""Dolby-Vision-/HDR-Analyse und -Pipeline (verlustfrei, kein Re-Encoding).

Fachlicher Kern (siehe Feature-Spec „DV/HDR-Kompatibilitäts-Remux“):
UHD-Blu-ray-Remuxes tragen oft DV **Profil 7** (Dual-Layer BL+EL+RPU), das
aus MKV kaum ein Gerät korrekt abspielt (Grün-/Lilastich). Die Reparatur —
ohne das Videobild anzufassen:

  „hdr10“  Dolby-Vision-Daten (RPU + EL) entfernen → reiner HDR10-Base-
           Layer, MKV bleibt MKV. 100 % verlustfrei, läuft auf jedem Gerät.
           GESPERRT bei Profil 5 (kein HDR10-Fallback — ohne RPU sind die
           Farben kaputt).

Alle Erkennungs-Details (ffprobe side_data „DOVI configuration record“)
wurden am lokalen Build verifiziert; dovi_tool lehnt MKV-Input ab, darum
wird der HEVC-Stream immer zuerst extrahiert.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

VIDEO_MODE_COPY = "copy"
VIDEO_MODE_HDR10 = "hdr10"

# Modi, die die DV-Pipeline (Extraktion + dovi_tool) durchlaufen —
# aktuell genau einer: „DV/HDR → HDR10“
DV_MODES = (VIDEO_MODE_HDR10,)

# Standard-Bildraten (fps). Nur bei diesen setzen wir beim DV-Remux eine
# exakte --default-duration; alles Ungewöhnliche (VFR, exotische Raten)
# überlassen wir mkvmerges eigener Erkennung, um nie etwas zu verschlimmern.
_STANDARD_FPS = (24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0,
                 48.0, 50.0, 60000 / 1001, 60.0)


@dataclass(frozen=True)
class DVInfo:
    """Ergebnis der Video-Analyse (erste Videospur)."""

    codec: str = ""                 # ffprobe codec_name, z. B. "hevc"
    dv_profile: int | None = None   # 5 / 7 / 8 / … oder None (kein DV)
    el_present: bool = False        # Enhancement-Layer vorhanden (Profil 7)
    bl_present: bool = False
    compat_id: int | None = None    # dv_bl_signal_compatibility_id
    hdr10: bool = False             # color_transfer == smpte2084 (PQ)
    frame_rate: str = ""            # ffprobe r_frame_rate, z. B. "24000/1001"

    @property
    def has_dv(self) -> bool:
        return self.dv_profile is not None

    @property
    def is_hevc(self) -> bool:
        return self.codec == "hevc"

    def describe(self) -> str:
        if not self.has_dv:
            return "HDR10 (PQ)" if self.hdr10 else ""
        layers = "BL+EL+RPU" if self.el_present else "BL+RPU"
        text = f"Dolby Vision Profil {self.dv_profile} ({layers})"
        if self.hdr10 or (self.dv_profile in (7, 8) and self.compat_id):
            text += " · HDR10-Fallback"
        return text

    # ── Modus-Verfügbarkeit (Spec Abschnitt 5/6) ─────────────────────────

    def hdr10_blocked_reason(self) -> str | None:
        if not self.is_hevc:
            return "DV-Remux ist nur für HEVC definiert."
        if not self.has_dv:
            return "Kein Dolby Vision vorhanden — nichts zu entfernen."
        if self.dv_profile == 5:
            return ("Profil 5 hat KEINEN HDR10-Fallback (IPTPQc2) — "
                    "ohne RPU wären die Farben kaputt. Entfernen unmöglich.")
        return None


class DVError(Exception):
    pass


def analyze(ffprobe: str, path: str, timeout: float = 60.0) -> DVInfo:
    """Liest DV-/HDR-Infos der ersten Videospur per ffprobe (JSON)."""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", path],
            capture_output=True, text=True, encoding="utf-8",
            errors="ignore", creationflags=_CREATE_NO_WINDOW, timeout=timeout)
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        raise DVError(f"Video-Analyse fehlgeschlagen: {exc}") from exc
    streams = data.get("streams") or []
    if not streams:
        return DVInfo()
    return parse_stream(streams[0])


def parse_stream(stream: dict) -> DVInfo:
    """Reiner Parser (testbar ohne Prozess)."""
    dovi = next((sd for sd in stream.get("side_data_list", [])
                 if "DOVI" in str(sd.get("side_data_type", ""))), None)
    return DVInfo(
        codec=stream.get("codec_name", ""),
        dv_profile=dovi.get("dv_profile") if dovi else None,
        el_present=bool(dovi.get("el_present_flag")) if dovi else False,
        bl_present=bool(dovi.get("bl_present_flag")) if dovi else True,
        compat_id=dovi.get("dv_bl_signal_compatibility_id") if dovi else None,
        hdr10=stream.get("color_transfer") == "smpte2084",
        frame_rate=str(stream.get("r_frame_rate", "") or ""),
    )


def default_duration_arg(frame_rate: str) -> str | None:
    """Wandelt eine ffprobe-Bildrate („24000/1001“) in das mkvmerge-Token für
    `--default-duration TID:<token>` — z. B. „24000/1001fps“.

    Beim DV-Remux wird der HEVC-Stream als rohes Elementary-Stream-File
    extrahiert und neu gemuxt. Trägt dessen SPS/VUI keine Timing-Angabe, rät
    mkvmerge die Bildrate (Default 25 fps) → falsche Dauer/Ruckeln auf
    wählerischer Hardware. Geben wir die EXAKTE Quell-Bildrate mit, kann
    nichts mehr geraten werden.

    Bewusst konservativ: nur für erkannte Standard-Bildraten (Film/TV). Bei
    VFR oder exotischen Werten liefern wir None und überlassen mkvmerge das
    Feld — lieber nichts erzwingen als eine korrekte VUI-Angabe überschreiben.
    """
    if not frame_rate or "/" not in frame_rate:
        return None
    num_str, _, den_str = frame_rate.partition("/")
    try:
        num, den = int(num_str), int(den_str)
    except ValueError:
        return None
    if num <= 0 or den <= 0:
        return None
    fps = num / den
    if not any(abs(fps - std) < 0.02 for std in _STANDARD_FPS):
        return None
    return f"{num}/{den}fps"


def parse_timestamps_v2(text: str) -> list[float]:
    """Liest eine Zeitstempel-Datei „timestamp format v2“ (mkvextract
    timestamps_v2): ein Wert in ms pro Frame, sortiert zurückgegeben."""
    values = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            values.append(float(line))
    return sorted(values)


def constant_rate_offset(timestamps: list[float],
                         frame_rate: str) -> int | None:
    """Startversatz (ms), wenn die Quell-Zeitstempel lückenlos im Raster der
    bekannten Standard-Bildrate liegen — dann genügen beim DV-Remux
    `--default-duration` + `--sync`, und die exakte Bildrate bleibt im
    Header (eine Zeitstempel-Datei würde sie auf ganze ms runden: 42 ms
    statt 41,708 ms → Player melden 23,81 statt 23,976 fps).

    None bei Lücken, VFR, unbekannter Bildrate oder leerer Liste — dann
    braucht der Mux die exakten Zeitstempel. Toleranz 1 ms: Matroska
    speichert Zeitstempel üblicherweise auf ganze ms gerundet.
    """
    if not timestamps or default_duration_arg(frame_rate) is None:
        return None
    num, _, den = frame_rate.partition("/")
    frame_ms = 1000 * int(den) / int(num)
    start = timestamps[0]
    if any(abs(ts - (start + i * frame_ms)) > 1.0 + 1e-6
           for i, ts in enumerate(timestamps)):
        return None
    return round(start)


# ── Pipeline-Kommandos (reine Builder, vom Runner ausgeführt) ────────────


def build_extract_hevc_mkvextract(mkvextract: str, src: str, track_id: int,
                                  out_hevc: str,
                                  out_timestamps: str | None = None
                                  ) -> list[str]:
    """HEVC bitgenau via mkvextract ziehen — der native MKVToolNix-Round-Trip
    (mkvextract → mkvmerge) bewahrt die exakte NAL-/Parameter-Set-Struktur.
    Genau das brauchen wählerische Hardware-Decoder (Rockchip/ARM-Boxen),
    denen ffmpegs umgeschriebener Bitstream nicht schmeckt.

    `out_timestamps`: im selben Lauf die Quell-Zeitstempel der Spur sichern
    (timestamps_v2) — das rohe HEVC verliert Startversatz, Lücken und VFR."""
    cmd = [mkvextract, "--gui-mode", src, "tracks", f"{track_id}:{out_hevc}"]
    if out_timestamps:
        cmd += ["timestamps_v2", f"{track_id}:{out_timestamps}"]
    return cmd


def build_extract_hevc(ffmpeg: str, src: str, out_hevc: str) -> list[str]:
    """Fallback-Extraktion via ffmpeg (Annex-B), falls mkvextract fehlt."""
    return [ffmpeg, "-y", "-v", "error", "-i", src,
            "-map", "0:v:0", "-c:v", "copy",
            "-bsf:v", "hevc_mp4toannexb", "-f", "hevc",
            "-progress", "pipe:1", "-nostats", out_hevc]


def build_dovi_remove(dovi_tool: str, in_hevc: str, out_hevc: str) -> list[str]:
    """Modus „hdr10“: RPU + EL entfernen — übrig bleibt der HDR10-BL."""
    return [dovi_tool, "remove", "-i", in_hevc, "-o", out_hevc]
