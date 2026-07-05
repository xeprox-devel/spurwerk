"""Kommandozeilen-Bau für ffmpeg und mkvmerge.

Reine Funktionen: FilePlan rein, fertige argv-Listen raus. Die Golden-Tests
in tests/test_commands.py verifizieren jede Kommandoform.
"""

from __future__ import annotations

from .dv import default_duration_arg
from .model import FilePlan, StereoSettings, Track
from .presets import CHANNEL_TARGETS, DOWNMIX_PRESETS, OUTPUT_CODECS


def stereo_temp_name(track: Track, settings: StereoSettings) -> str:
    """Dateiname der temporären Konvertierungs-Datei für eine Quellspur."""
    ext = OUTPUT_CODECS[settings.codec]["ext"]
    return f"convert_track{track.id}{ext}"


def effective_channels(track: Track, settings: StereoSettings) -> int:
    """Effektives Ziel-Layout: min(Quelle, Ziel, Codec-Maximum) — nie Upmix,
    und AC3/E-AC3 enden ehrlich bei 5.1 (FFmpeg kann kein E-AC3 7.1)."""
    source = track.channels or 2
    target = CHANNEL_TARGETS[settings.channels]
    codec_max = OUTPUT_CODECS[settings.codec]["max_channels"]
    return min(source, target, codec_max)


def build_ffmpeg_downmix(ffmpeg: str, plan: FilePlan, track: Track,
                         settings: StereoSettings, out_path: str) -> list[str]:
    """Konvertierung einer Audiospur direkt aus der MKV — auf das
    Ziel-Layout (2.0 mit Downmix-Preset, 5.1/7.1 per FFmpeg-Remix)."""
    audio_index = plan.media.ffmpeg_audio_index(track.id)
    cmd = [ffmpeg, "-y", "-v", "error",
           "-i", plan.media.path,
           "-map", f"0:a:{audio_index}",
           "-progress", "pipe:1", "-nostats"]

    target = effective_channels(track, settings)
    pan_filter = DOWNMIX_PRESETS[settings.downmix_preset]["filter"]
    if target <= 2:
        if track.is_multichannel and pan_filter:
            cmd += ["-af", pan_filter]
        else:
            # Quelle ist bereits <=2 Kanäle oder Passthrough-Preset
            cmd += ["-ac", "2"]
    else:
        # Mehrkanal-Ziel (z. B. DTS 5.1 → DD 5.1, E-AC3 7.1 → 5.1):
        # FFmpeg mischt mit Standard-Koeffizienten aufs Ziel-Layout
        cmd += ["-ac", str(target)]

    cmd += ["-c:a", settings.codec, "-b:a", settings.bitrate, out_path]
    return cmd


def build_mkvmerge_mux(mkvmerge: str, plan: FilePlan, settings: StereoSettings,
                       stereo_files: dict[int, str],
                       video_file: str | None = None) -> list[str]:
    """Der eine finale Mux-Lauf: Quelle (mit Spurauswahl) + n Stereo-Dateien.

    `stereo_files` bildet Quell-Track-ID → Pfad der erzeugten Stereo-Datei ab.
    `video_file` (DV/HDR-Remux): ersetzt die Videospur der Quelle durch den
    bereinigten HEVC-Stream — die Quelle liefert dann nur noch Audio/Subs/
    Kapitel (--no-video), das Video kommt als eigene Eingabedatei davor.
    """
    media = plan.media
    cmd = [mkvmerge, "--gui-mode", "-o", plan.output_path]

    # Datei-IDs für --track-order: [video_file,] Quelle, Stereo-Dateien …
    source_fid = 1 if video_file else 0

    if video_file:
        first_video = next(iter(media.by_type("video")), None)
        if first_video is not None:
            if first_video.lang != "und":
                cmd += ["--language", f"0:{first_video.lang}"]
            if first_video.name:
                cmd += ["--track-name", f"0:{first_video.name}"]
        # Timing-Absicherung: dem roh extrahierten HEVC die exakte
        # Quell-Bildrate mitgeben, damit mkvmerge sie nicht raten muss.
        frame_rate = getattr(plan.dv, "frame_rate", "") if plan.dv else ""
        duration = default_duration_arg(frame_rate)
        if duration:
            cmd += ["--default-duration", f"0:{duration}"]
        cmd += ["--default-track-flag", "0:yes", video_file]

    # ── Spurauswahl der Quelldatei ────────────────────────────────────────
    kept_video = plan.kept_ids("video")
    kept_audio = plan.kept_ids("audio")
    kept_subs = plan.kept_ids("subtitles")

    if video_file:
        cmd += ["--no-video"]
    else:
        cmd += (["--video-tracks", _ids(kept_video)] if kept_video
                else ["--no-video"])
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

    if stereo_tracks or video_file:
        cmd += ["--track-order",
                _track_order(plan, stereo_tracks, source_fid, video_file)]

    return cmd


def _ids(track_ids: list[int]) -> str:
    return ",".join(str(i) for i in track_ids)


def _track_order(plan: FilePlan, stereo_tracks: list[Track],
                 source_fid: int = 0, video_file: str | None = None) -> str:
    """Reihenfolge: Video → Audio (Stereo direkt hinter/statt der Quelle) → Subs.

    Datei-IDs: [0 = bereinigtes Video,] source_fid = Quelle, danach die
    Stereo-Dateien in Anhäng-Reihenfolge.
    """
    file_of_stereo = {t.id: source_fid + 1 + i
                      for i, t in enumerate(stereo_tracks)}
    order: list[str] = []
    if video_file:
        order.append("0:0")
    else:
        for t in plan.media.by_type("video"):
            if plan.decisions[t.id].action.keeps_original:
                order.append(f"{source_fid}:{t.id}")
    for t in plan.media.audio_tracks:
        dec = plan.decisions[t.id]
        if dec.action.keeps_original:
            order.append(f"{source_fid}:{t.id}")
        if dec.action.is_stereo:
            order.append(f"{file_of_stereo[t.id]}:0")
    for t in plan.media.by_type("subtitles"):
        if plan.decisions[t.id].action.keeps_original:
            order.append(f"{source_fid}:{t.id}")
    return ",".join(order)
