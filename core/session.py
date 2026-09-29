"""Job-Queue-Logik ohne tkinter: Sitzung speichern/wiederherstellen, Zeilen
auf nicht verbundenen Laufwerken und die Prüfungen vor dem Start.

Reine Logik — die UI ruft sie beim Speichern, Wiederherstellen und
Starten. Gespeichert wird nur die leichte Konfiguration; die schweren
MediaInfo-Daten werden beim Neustart per Neu-Scan geholt.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
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
                 pending: Mapping[str, dict]) -> list[dict]:
    """Alle offenen Jobs für config.json, in der Reihenfolge der Liste:
    - gescannte Pläne (außer erledigten) → frisch serialisiert,
    - Zeilen ohne Plan (noch nicht oder erfolglos gescannt, Laufwerk nicht
      verbunden) → die gespeicherte Konfiguration unverändert weiter, sonst
      ginge die Warteschlange schon beim Start, durch einen Scan-Fehler
      oder eine abgezogene USB-Platte verloren."""
    jobs: list[dict] = []
    for path, plan in plans.items():
        if plan is None:
            jobs.append(pending.get(path) or {"path": path})
        elif plan.status is not FileStatus.DONE:
            jobs.append(serialize_plan(plan))
    return jobs


def restorable_jobs(entries: Iterable, listed: Iterable[str] = (),
                    ) -> list[tuple[str, dict]]:
    """Gespeicherte Sitzung → (Pfad, Job) in Warteschlangen-Reihenfolge.
    Einträge ohne Pfad fallen weg, jede Datei kommt einmal (Schreibweise
    egal), schon gelistete gar nicht. Der Pfad wird nur als Text
    normalisiert — ein Dateizugriff könnte an einem getrennten
    Netzlaufwerk hängen."""
    seen = {_key(path) for path in listed}
    jobs: list[tuple[str, dict]] = []
    for job in entries:
        path = job.get("path") if isinstance(job, dict) else None
        if not path or not isinstance(path, str):
            continue
        key = _key(path)
        if key in seen:
            continue
        seen.add(key)
        jobs.append((os.path.normpath(os.path.abspath(path)), job))
    return jobs


# ── Quellen auf nicht verbundenen Laufwerken ──────────────────────────────


def source_exists(path: str) -> bool:
    """Ist die Quelldatei erreichbar? Kann an einem getrennten
    Netzlaufwerk viele Sekunden hängen — nur im Hintergrund aufrufen."""
    try:
        return os.path.exists(path)
    except (OSError, ValueError):
        return False


def drive_root(path: str) -> str:
    """Wurzel des Laufwerks bzw. der Netzfreigabe: „E:\\“, „\\\\nas\\filme\\“.
    Nur Text, kein Dateizugriff."""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return drive + os.sep if drive else os.sep


def by_drive(paths: Iterable[str]) -> list[list[str]]:
    """Pfade je Laufwerk bzw. Netzfreigabe (Reihenfolge bleibt): So wartet
    die Prüfung einer USB-Platte nicht auf ein hängendes NAS."""
    groups: dict[str, list[str]] = {}
    for path in paths:
        groups.setdefault(os.path.normcase(drive_root(path)), []).append(path)
    return list(groups.values())


class SourceWatch:
    """Buchführung für Zeilen der Warteschlange, deren Quelle (noch) nicht
    erreichbar ist — ohne tkinter. Die UI holt sich, was geprüft wird
    (begin_check), und erfährt je Befund, was aus der Zeile wird
    (result). Ihr gespeicherter Job bleibt dabei unangetastet."""

    # Zustände einer Zeile — NO_DRIVE und NO_FILE sind auch die Befunde
    # einer Prüfung (probe_sources), dazu REACHABLE
    CHECKING = "prüfen"    # Startprüfung läuft noch
    NO_DRIVE = "kein Laufwerk"   # Laufwerk/Freigabe nicht verbunden
    NO_FILE = "keine Datei"      # Laufwerk da, Datei nicht (verschoben?)
    REACHABLE = "erreichbar"

    # Ergebnisse von result(), außer dem neuen Zustand NO_DRIVE/NO_FILE
    FOUND = "gefunden"     # Startprüfung: Quelle da → normal einlesen
    BACK = "wieder da"     # Quelle wieder erreichbar → einlesen

    def __init__(self) -> None:
        self._state: dict[str, str] = {}
        self._new: dict[str, str] = {}   # erstmals fehlend (diese Prüfung)
        self.checking = False            # höchstens eine Prüfung zur Zeit

    def __contains__(self, path: object) -> bool:
        return path in self._state

    def __iter__(self):
        return iter(list(self._state))

    def __len__(self) -> int:
        return len(self._state)

    def watch(self, path: str) -> None:
        """Neue Zeile aus der Sitzung — Quelle noch ungeprüft."""
        self._state[path] = self.CHECKING

    def state(self, path: str) -> str | None:
        return self._state.get(path)

    def waiting(self) -> list[str]:
        """Geprüfte Zeilen, deren Quelle fehlt — sie prüft der Takt erneut
        (ohne die noch ungeprüften)."""
        return [p for p, s in self._state.items() if s != self.CHECKING]

    def counts(self) -> dict[str, int]:
        """Zeilen je Zustand — nur vorkommende (für Rückfrage/Protokoll)."""
        counts: dict[str, int] = {}
        for state in self._state.values():
            counts[state] = counts.get(state, 0) + 1
        return counts

    def discard(self, path: str) -> None:
        self._state.pop(path, None)
        self._new.pop(path, None)

    def clear(self) -> None:
        """Alle Zeilen weg — eine laufende Prüfung bleibt vermerkt, ihr
        Abschluss kommt noch (end_check)."""
        self._state.clear()
        self._new.clear()

    def begin_check(self) -> list[str]:
        """Pfade für die nächste Prüfung. Leer — und dann startet keine —,
        solange eine läuft oder keine Zeile wartet."""
        if self.checking or not self._state:
            return []
        self.checking = True
        return list(self._state)

    def end_check(self) -> dict[str, int]:
        """Prüfung fertig → wie viele Zeilen dabei erstmals als fehlend
        erkannt wurden, je Zustand (für die Meldung nach dem Start)."""
        self.checking = False
        new: dict[str, int] = {}
        for state in self._new.values():
            new[state] = new.get(state, 0) + 1
        self._new.clear()
        return new

    def result(self, path: str, finding: str) -> str | None:
        """Befund einer Prüfung → FOUND/BACK (Zeile wird ein normaler Job
        und verlässt die Buchführung), der neue Zustand NO_DRIVE/NO_FILE
        (Zeile anpassen) oder None (nichts zu tun: unverändert, inzwischen
        entfernt oder eingelesen)."""
        state = self._state.get(path)
        if state is None or finding == state:
            return None
        if finding == self.REACHABLE:
            del self._state[path]
            self._new.pop(path, None)
            return self.FOUND if state == self.CHECKING else self.BACK
        if state == self.CHECKING:
            self._new[path] = finding
        self._state[path] = finding
        return finding


def probe_sources(paths: Iterable[str]) -> Iterator[tuple[str, str]]:
    """(Pfad, Befund) je Quelle: REACHABLE, NO_DRIVE oder NO_FILE. Kann an
    einem getrennten Netzlaufwerk hängen — nur im Hintergrund. Fehlt die
    Datei, klärt die Wurzel ihres Laufwerks, ob das Laufwerk fehlt oder nur
    die Datei (verschoben/gelöscht); ein fehlendes Laufwerk wird je Prüfung
    einmal gefragt, nicht für jede seiner Dateien."""
    drives: dict[str, bool] = {}   # Laufwerk erreichbar?
    for path in paths:
        root = drive_root(path)
        key = os.path.normcase(root)
        if drives.get(key) is False:
            yield path, SourceWatch.NO_DRIVE
        elif source_exists(path):
            drives[key] = True
            yield path, SourceWatch.REACHABLE
        else:
            if key not in drives:
                drives[key] = source_exists(root)
            yield path, (SourceWatch.NO_FILE if drives[key]
                         else SourceWatch.NO_DRIVE)


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
