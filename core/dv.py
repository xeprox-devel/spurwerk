"""Dolby-Vision-/HDR-Analyse und -Pipeline (verlustfrei, kein Re-Encoding).

Fachlicher Kern (siehe Feature-Spec „DV/HDR-Kompatibilitäts-Remux"):
UHD-Blu-ray-Remuxes tragen oft DV **Profil 7** (Dual-Layer BL+EL+RPU), das
aus MKV kaum ein Gerät korrekt abspielt (Grün-/Lilastich). Zwei Reparaturen,
beide ohne das Videobild anzufassen:

  „hdr10"  RPU+EL entfernen → reiner HDR10-Base-Layer, MKV bleibt MKV.
           100 % verlustfrei. GESPERRT bei Profil 5 (kein HDR10-Fallback —
           ohne RPU sind die Farben kaputt).
  „dv81"   RPU von Profil 7 → 8.1 umrechnen, EL verwerfen → MP4 mit
           DV 8.1 + HDR10-Fallback. Bei FEL-Quellen gehen nur die
           EL-Verfeinerungsdaten verloren (visuell vernachlässigbar).

Alle Erkennungs-Details (ffprobe side_data „DOVI configuration record")
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
VIDEO_MODE_DV81 = "dv81"


@dataclass(frozen=True)
class DVInfo:
    """Ergebnis der Video-Analyse (erste Videospur)."""

    codec: str = ""                 # ffprobe codec_name, z. B. "hevc"
    dv_profile: int | None = None   # 5 / 7 / 8 / … oder None (kein DV)
    el_present: bool = False        # Enhancement-Layer vorhanden (Profil 7)
    bl_present: bool = False
    compat_id: int | None = None    # dv_bl_signal_compatibility_id
    hdr10: bool = False             # color_transfer == smpte2084 (PQ)

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

    def dv81_blocked_reason(self) -> str | None:
        if not self.is_hevc:
            return "DV-Remux ist nur für HEVC definiert."
        if not self.has_dv:
            return "Kein Dolby Vision vorhanden."
        if self.dv_profile == 5:
            return ("Profil 5: keine RPU-Konvertierung nach 8.1 möglich — "
                    "nur Container-Wechsel (nicht implementiert).")
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
    )


# ── Pipeline-Kommandos (reine Builder, vom Runner ausgeführt) ────────────


def build_extract_hevc_mkvextract(mkvextract: str, src: str, track_id: int,
                                  out_hevc: str) -> list[str]:
    """HEVC bitgenau via mkvextract ziehen — der native MKVToolNix-Round-Trip
    (mkvextract → mkvmerge) bewahrt die exakte NAL-/Parameter-Set-Struktur.
    Genau das brauchen wählerische Hardware-Decoder (Rockchip/ARM-Boxen),
    denen ffmpegs umgeschriebener Bitstream nicht schmeckt."""
    return [mkvextract, "tracks", src, "--gui-mode",
            f"{track_id}:{out_hevc}"]


def build_extract_hevc(ffmpeg: str, src: str, out_hevc: str) -> list[str]:
    """Fallback-Extraktion via ffmpeg (Annex-B), falls mkvextract fehlt."""
    return [ffmpeg, "-y", "-v", "error", "-i", src,
            "-map", "0:v:0", "-c:v", "copy",
            "-bsf:v", "hevc_mp4toannexb", "-f", "hevc",
            "-progress", "pipe:1", "-nostats", out_hevc]


def build_dovi_remove(dovi_tool: str, in_hevc: str, out_hevc: str) -> list[str]:
    """Modus „hdr10": RPU + EL entfernen — übrig bleibt der HDR10-BL."""
    return [dovi_tool, "remove", "-i", in_hevc, "-o", out_hevc]


def build_dovi_convert(dovi_tool: str, in_hevc: str,
                       out_hevc: str) -> list[str]:
    """Modus „dv81": RPU Profil 7 → 8.1, EL verwerfen (-m 2 + --discard)."""
    return [dovi_tool, "-m", "2", "convert", "--discard",
            "-i", in_hevc, "-o", out_hevc]


# ── Modus A: DV-8.1-MP4 (nur ffmpeg — MP4Box wird nicht benötigt) ─────────

# Audio-Codecs, die MP4 sauber trägt → 1:1 kopieren; alles andere
# (TrueHD, DTS, FLAC, PCM …) wird nach E-AC3 gewandelt (Spec 6.3).
MP4_AUDIO_CODECS = {"A_AAC", "A_AC3", "A_EAC3", "A_OPUS"}
# Text-Untertitel → mov_text; Bild-Untertitel (PGS/VobSub) kann MP4 nicht.
MP4_TEXT_SUBS = {"S_TEXT/UTF8", "S_TEXT/ASS", "S_TEXT/SSA", "S_TEXT/USF"}


def mp4_audio_compatible(codec_id: str) -> bool:
    return codec_id in MP4_AUDIO_CODECS


def mp4_sub_compatible(codec_id: str) -> bool:
    return codec_id in MP4_TEXT_SUBS


def build_ffmpeg_dv_mp4(ffmpeg: str, video_hevc: str, plan,
                        stereo_files: dict[int, str], out_mp4: str,
                        stereo_bitrate: str = "640k") -> tuple[list[str], list[str]]:
    """Ein ffmpeg-Lauf: DV-8.1-Video (dovi_rpu) + MP4-taugliches Audio +
    Text-Untertitel + Kapitel → MP4. Rückgabe: (argv, warnungen).

    Eingaben: 0 = bereinigtes/konvertiertes HEVC, 1 = Original-MKV,
    2.. = erzeugte Stereo-Dateien (in Anhäng-Reihenfolge).
    """
    media = plan.media
    warnings: list[str] = []

    inputs = [video_hevc, media.path]
    stereo_tracks = plan.stereo_sources()
    stereo_fid: dict[int, int] = {}
    for t in stereo_tracks:
        stereo_fid[t.id] = len(inputs)
        inputs.append(stereo_files[t.id])

    cmd = [ffmpeg, "-y", "-v", "error",
           "-progress", "pipe:1", "-nostats"]
    for path in inputs:
        cmd += ["-i", path]

    # Video: DV-RPU in dvvC-Box schreiben, bitgenau
    cmd += ["-map", "0:v:0", "-c:v", "copy",
            "-bsf:v", "dovi_rpu", "-strict", "unofficial", "-tag:v", "dvh1"]

    out_audio = 0
    # Original-Audiospuren (behalten) — kompatible kopieren, sonst E-AC3
    for tid in plan.kept_ids("audio"):
        track = media.track(tid)
        src_idx = media.ffmpeg_audio_index(tid)
        cmd += ["-map", f"1:a:{src_idx}"]
        if mp4_audio_compatible(track.codec_id):
            cmd += [f"-c:a:{out_audio}", "copy"]
        else:
            cmd += [f"-c:a:{out_audio}", "eac3", f"-b:a:{out_audio}", "640k"]
            warnings.append(
                f"Audiospur {tid} ({track.codec_name}) ist nicht MP4-tauglich "
                f"→ nach E-AC3 gewandelt (einziger nicht-verlustfreie Schritt).")
        if track.lang != "und":
            cmd += [f"-metadata:s:a:{out_audio}", f"language={track.lang}"]
        out_audio += 1

    # Erzeugte Stereo-/Downmix-Spuren (bereits MP4-tauglich)
    for track in stereo_tracks:
        cmd += ["-map", f"{stereo_fid[track.id]}:a:0",
                f"-c:a:{out_audio}", "copy"]
        if track.lang != "und":
            cmd += [f"-metadata:s:a:{out_audio}", f"language={track.lang}"]
        out_audio += 1

    # Untertitel: Text → mov_text; Bild-Untertitel kann MP4 nicht
    out_sub = 0
    for tid in plan.kept_ids("subtitles"):
        track = media.track(tid)
        if not mp4_sub_compatible(track.codec_id):
            warnings.append(
                f"Untertitel {tid} ({track.codec_name}) ist nicht MP4-tauglich "
                f"→ weggelassen (MKV-Modus behält es).")
            continue
        cmd += ["-map", f"1:s:{media.ffmpeg_sub_index(tid)}",
                f"-c:s:{out_sub}", "mov_text"]
        if track.lang != "und":
            cmd += [f"-metadata:s:s:{out_sub}", f"language={track.lang}"]
        out_sub += 1

    cmd += ["-map_chapters", "1", out_mp4]
    return cmd, warnings
