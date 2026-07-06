"""Serialisierung offener Jobs für die Sitzungs-Wiederherstellung.

Reine Funktionen (kein tkinter) — die UI ruft sie beim Speichern und beim
Wiederherstellen. Gespeichert wird nur die leichte Konfiguration; die
schweren MediaInfo-Daten werden beim Neustart per Neu-Scan geholt.
"""

from __future__ import annotations

from dataclasses import asdict, fields

from .dv import VIDEO_MODE_COPY, VIDEO_MODE_HDR10
from .model import Action, FilePlan, Origin, StereoSettings


def serialize_plan(plan: FilePlan) -> dict:
    return {
        "path": plan.media.path,
        "profile_name": plan.profile_name,
        "video_mode": plan.video_mode,
        "canonical_name": plan.canonical_name,
        "output_path": plan.output_path,
        "output_manual": plan.output_manual,
        "stereo": asdict(plan.stereo),
        "overrides": {str(tid): dec.action.value
                      for tid, dec in plan.decisions.items()
                      if dec.origin is Origin.MANUAL},
        "default_audio_source": plan.default_audio_source,
        "default_audio_is_stereo": plan.default_audio_is_stereo,
    }


def restore_plan(plan: FilePlan, job: dict) -> None:
    """Legt die gespeicherte Konfiguration auf einen frisch gescannten Plan.
    Defekte/veraltete Einträge werden toleriert (Plan bleibt beim Default)."""
    try:
        plan.profile_name = job.get("profile_name", plan.profile_name)

        known = {f.name for f in fields(StereoSettings)}
        stereo_data = {k: v for k, v in job.get("stereo", {}).items()
                       if k in known}
        if stereo_data:
            plan.stereo = StereoSettings(**stereo_data)

        valid_ids = {t.id for t in plan.media.tracks}
        for tid_str, action in job.get("overrides", {}).items():
            tid = int(tid_str)
            if tid in valid_ids:
                plan.set_action(tid, Action(action), Origin.MANUAL)

        # Unbekannte Modi (z. B. „dv81“ aus älteren Ständen) → sicher „copy“
        mode = job.get("video_mode", VIDEO_MODE_COPY)
        plan.video_mode = (mode if mode in (VIDEO_MODE_COPY, VIDEO_MODE_HDR10)
                           else VIDEO_MODE_COPY)
        plan.canonical_name = job.get("canonical_name", "")

        src = job.get("default_audio_source")
        if src is not None and any(t.id == src
                                   for t in plan.media.audio_tracks):
            plan.default_audio_source = src
            plan.default_audio_is_stereo = bool(
                job.get("default_audio_is_stereo"))
    except (ValueError, KeyError, TypeError):
        pass
