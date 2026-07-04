"""Kommandozeilen-Bau für ffmpeg und mkvmerge.

Reine Funktionen: FilePlan rein, fertige argv-Listen raus. Die Golden-Tests
in tests/test_commands.py verifizieren jede Kommandoform.
"""

from __future__ import annotations

from .model import FilePlan, StereoSettings, Track
from .presets import DOWNMIX_PRESETS, OUTPUT_CODECS


def stereo_temp_name(track: Track, settings: StereoSettings) -> str:
    """Dateiname der temporären Stereo-Datei für eine Quellspur."""
    ext = OUTPUT_CODECS[settings.codec]["ext"]
    return f"stereo_track{track.id}{ext}"


def build_ffmpeg_downmix(ffmpeg: str, plan: FilePlan, track: Track,
                         settings: StereoSettings, out_path: str) -> list[str]:
    """Downmix einer Audiospur direkt aus der MKV (kein mkvextract-Umweg)."""
    audio_index = plan.media.ffmpeg_audio_index(track.id)
    cmd = [ffmpeg, "-y", "-v", "error",
           "-i", plan.media.path,
           "-map", f"0:a:{audio_index}",
           "-progress", "pipe:1", "-nostats"]

    pan_filter = DOWNMIX_PRESETS[settings.downmix_preset]["filter"]
    if track.is_multichannel and pan_filter:
        cmd += ["-af", pan_filter]
    else:
        # Quelle ist bereits <=2 Kanäle oder Passthrough: Encoder reduziert
        cmd += ["-ac", "2"]

    cmd += ["-c:a", settings.codec, "-b:a", settings.bitrate, out_path]
    return cmd


def build_mkvmerge_mux(mkvmerge: str, plan: FilePlan, settings: StereoSettings,
                       stereo_files: dict[int, str]) -> list[str]:
    """Der eine finale Mux-Lauf: Quelle (mit Spurauswahl) + n Stereo-Dateien.

    `stereo_files` bildet Quell-Track-ID → Pfad der erzeugten Stereo-Datei ab.
    """
    media = plan.media
    cmd = [mkvmerge, "--gui-mode", "-o", plan.output_path]

    # ── Spurauswahl der Quelldatei ────────────────────────────────────────
    kept_video = plan.kept_ids("video")
    kept_audio = plan.kept_ids("audio")
    kept_subs = plan.kept_ids("subtitles")

    cmd += (["--video-tracks", _ids(kept_video)] if kept_video else ["--no-video"])
    cmd += (["--audio-tracks", _ids(kept_audio)] if kept_audio else ["--no-audio"])
    cmd += (["--subtitle-tracks", _ids(kept_subs)] if kept_subs else ["--no-subtitles"])

    # Default-Flags der Audiospuren deterministisch setzen — mkvmerge kopiert
    # sie sonst unverändert und meldet doppelte/fehlende Defaults nicht.
    for tid in kept_audio:
        is_default = (not plan.default_audio_is_stereo
                      and tid == plan.default_audio_source)
        cmd += ["--default-track-flag", f"{tid}:{'yes' if is_default else 'no'}"]

    cmd.append(media.path)

    # ── Neue Stereo-Spuren anhängen ───────────────────────────────────────
    stereo_tracks = plan.stereo_sources()
    for track in stereo_tracks:
        is_default = (plan.default_audio_is_stereo
                      and track.id == plan.default_audio_source)
        cmd += ["--language", f"0:{track.lang}",
                "--track-name", f"0:{settings.display_track_name()}",
                "--default-track-flag", f"0:{'yes' if is_default else 'no'}"]
        if track.delay_ms:
            cmd += ["--sync", f"0:{track.delay_ms}"]
        cmd.append(stereo_files[track.id])

    if stereo_tracks:
        cmd += ["--track-order", _track_order(plan, stereo_tracks)]

    return cmd


def _ids(track_ids: list[int]) -> str:
    return ",".join(str(i) for i in track_ids)


def _track_order(plan: FilePlan, stereo_tracks: list[Track]) -> str:
    """Reihenfolge: Video → Audio (Stereo direkt hinter/statt der Quelle) → Subs.

    Datei-IDs: 0 = Quelldatei, 1..n = Stereo-Dateien in Anhäng-Reihenfolge.
    """
    file_of_stereo = {t.id: i + 1 for i, t in enumerate(stereo_tracks)}
    order: list[str] = []
    for t in plan.media.by_type("video"):
        if plan.decisions[t.id].action.keeps_original:
            order.append(f"0:{t.id}")
    for t in plan.media.audio_tracks:
        dec = plan.decisions[t.id]
        if dec.action.keeps_original:
            order.append(f"0:{t.id}")
        if dec.action.is_stereo:
            order.append(f"{file_of_stereo[t.id]}:0")
    for t in plan.media.by_type("subtitles"):
        if plan.decisions[t.id].action.keeps_original:
            order.append(f"0:{t.id}")
    return ",".join(order)
