"""Job-Queue-Logik ohne tkinter: Sitzung speichern/wiederherstellen und die
Prüfungen vor dem Start.

Reine Funktionen — die UI ruft sie beim Speichern, Wiederherstellen und
Starten. Gespeichert wird nur die leichte Konfiguration; die schweren
MediaInfo-Daten werden beim Neustart per Neu-Scan geholt.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, fields
from pathlib import Path

from .dv import VIDEO_MODE_COPY, VIDEO_MODE_HDR10
from .model import (Action, FilePlan, FileStatus, MediaInfo, Origin,
                    RuleProfile, StereoSettings)
from .planner import build_plan


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
    Defekte/veraltete Einträge werden toleriert (Plan bleibt beim Default).
    Die Invariante „genau eine Standard-Audiospur“ hält danach immer."""
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

        # Gespeicherte Standard-Spur nur über die Plan-API: passt sie nicht
        # mehr zu den Aktionen (Spur ohne Konvertierung, Original entfernt),
        # bleibt die Regel-Vorgabe — nie eine Ausgabe ohne Standard-Audio
        src = job.get("default_audio_source")
        if src is not None and any(t.id == src
                                   for t in plan.media.audio_tracks):
            try:
                plan.set_default_audio(
                    src, on_stereo=bool(job.get("default_audio_is_stereo")))
            except ValueError:
                pass
    except (ValueError, KeyError, TypeError):
        pass
    plan._ensure_default_valid()


def restore_job_plan(media: MediaInfo, job: dict,
                     profile: RuleProfile) -> FilePlan:
    """Plan für einen wiederhergestellten Job: die Regeln SEINES Profils
    (nicht des gerade aktiven), darauf die gespeicherte Konfiguration.
    `profile` ist das aufgelöste Job-Profil — fehlt es inzwischen, liefert
    AppConfig.profile() ein Ersatzprofil; der Plan trägt dann dessen Namen,
    damit Beschriftung und angewandte Regeln übereinstimmen."""
    plan = build_plan(media, profile)
    restore_plan(plan, job)
    plan.profile_name = profile.name
    return plan


# ── Sitzung speichern ─────────────────────────────────────────────────────


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def session_jobs(plans: Mapping[str, FilePlan | None],
                 pending: Mapping[str, dict],
                 deferred: Iterable[dict] = ()) -> list[dict]:
    """Alle offenen Jobs für config.json:
    - gescannte Pläne (außer erledigten) → frisch serialisiert,
    - noch nicht oder erfolglos gescannte (Plan None) → die gespeicherte
      Konfiguration unverändert weiter, sonst ginge die Warteschlange
      schon beim Start (oder durch einen Scan-Fehler) verloren,
    - zurückgestellte Jobs (Quelle gerade nicht erreichbar) → bleiben, bis
      das Laufwerk wieder da ist."""
    jobs: list[dict] = []
    for path, plan in plans.items():
        if plan is None:
            jobs.append(pending.get(path) or {"path": path})
        elif plan.status is not FileStatus.DONE:
            jobs.append(serialize_plan(plan))
    listed = {_key(path) for path in plans}
    jobs += [job for job in deferred
             if _key(str(job.get("path", ""))) not in listed]
    return jobs


def split_reachable(jobs: Iterable[dict],
                    exists: Callable[[str], bool] = os.path.exists,
                    ) -> tuple[list[dict], list[dict]]:
    """Gespeicherte Jobs → (erreichbar, zurückgestellt). Zurückgestellt ist
    ein Job, dessen Quelle gerade fehlt (USB-Platte/NAS nicht verbunden);
    Einträge ohne Pfad fallen weg."""
    reachable: list[dict] = []
    deferred: list[dict] = []
    for job in jobs:
        path = job.get("path", "") if isinstance(job, dict) else ""
        if not path:
            continue
        (reachable if exists(path) else deferred).append(job)
    return reachable, deferred


def pop_job(jobs: list[dict], path: str) -> dict | None:
    """Entnimmt den gespeicherten Job zu `path` (Schreibweise egal)."""
    key = _key(path)
    for i, job in enumerate(jobs):
        if _key(str(job.get("path", ""))) == key:
            return jobs.pop(i)
    return None


# ── Vor dem Start ─────────────────────────────────────────────────────────


def runnable_plans(plans: Iterable[FilePlan | None]) -> list[FilePlan]:
    """Was ein Start verarbeitet: gescannte, noch nicht erledigte Pläne
    (erledigte stehen bis zum Aufräumen noch kurz in der Liste)."""
    return [p for p in plans
            if p is not None and p.status is not FileStatus.DONE]


def output_conflict(plans: Iterable[FilePlan], sources: Iterable[str],
                    ) -> tuple[FilePlan, str, bool] | None:
    """Erste Ausgabe-Kollision vor dem Start, sonst None.
    Ergebnis (plan, andere Datei, ist_quelle):
    ist_quelle=True  → die Ausgabe von `plan` wäre die QUELLDATEI eines
                       anderen Jobs der Liste (dessen Original wäre weg),
    ist_quelle=False → zwei Jobs hätten dieselbe Ausgabedatei."""
    plans = list(plans)
    source_keys = {_key(s): s for s in sources}
    for plan in plans:
        other = source_keys.get(_key(plan.output_path))
        if other is not None and _key(other) != _key(plan.media.path):
            return plan, other, True
    seen: dict[str, str] = {}
    for plan in plans:
        key = _key(plan.output_path)
        if key in seen:
            return plan, seen[key], False
        seen[key] = plan.media.path
    return None


def distinct_output(output: str, source: str, suffix: str) -> str:
    """Ausgabepfad, der nie die Quelle selbst ist: Ergibt der bereinigte
    Name exakt die Quelldatei (schon sauberer Name im Quellordner), kommt
    das Profil-Suffix doch dazu („Film.mkv“ → „Film_remux.mkv“)."""
    if _key(output) != _key(source):
        return output
    out = Path(output)
    return str(out.with_name(out.stem + suffix + out.suffix))
