"""Job-Queue-Logik ohne tkinter: Sitzung speichern/wiederherstellen, Zeilen
auf nicht verbundenen Laufwerken (auch unter neuem Laufwerksbuchstaben),
der feste Ausgabeordner und die Prüfungen vor dem Start.

Reine Logik — die UI ruft sie beim Speichern, Wiederherstellen und
Starten. Gespeichert wird nur die leichte Konfiguration; die schweren
MediaInfo-Daten werden beim Neustart per Neu-Scan geholt.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, fields
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


def find_listed(path: str, listed: Iterable[str]) -> str | None:
    """Der Eintrag aus `listed`, der dieselbe Datei meint (Schreibweise
    egal), sonst None. Nur Text."""
    key = _key(path)
    return next((p for p in listed if _key(p) == key), None)


def session_jobs(plans: Mapping[str, FilePlan | None],
                 pending: Mapping[str, dict],
                 identity: Mapping[str, dict] | None = None) -> list[dict]:
    """Alle offenen Jobs für config.json, in der Reihenfolge der Liste:
    - gescannte Pläne (außer erledigten) → frisch serialisiert, dazu Größe
      und Änderungszeit der Quelle aus `identity` (source_identity),
    - Zeilen ohne Plan (noch nicht oder erfolglos gescannt, Laufwerk nicht
      verbunden) → die gespeicherte Konfiguration unverändert weiter, sonst
      ginge die Warteschlange schon beim Start, durch einen Scan-Fehler
      oder eine abgezogene USB-Platte verloren."""
    identity = identity or {}
    jobs: list[dict] = []
    for path, plan in plans.items():
        if plan is None:
            jobs.append(pending.get(path) or {"path": path})
        elif plan.status is not FileStatus.DONE:
            jobs.append({**serialize_plan(plan), **identity.get(path, {})})
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
        self._notes: set[tuple[str, str]] = set()   # schon gemeldet (note)
        self.checking = False            # höchstens eine Prüfung zur Zeit
        self.searching = False           # … und eine Suche (begin_search)

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
        self._notes = {n for n in self._notes if n[0] != path}

    def clear(self) -> None:
        """Alle Zeilen weg — eine laufende Prüfung oder Suche bleibt
        vermerkt, ihr Abschluss kommt noch (end_check/end_search)."""
        self._state.clear()
        self._new.clear()
        self._notes.clear()

    def note(self, path: str, what: str) -> bool:
        """True beim ersten Mal je Zeile und Anlass — für Protokoll-
        Hinweise, die jede Prüfung erneut fände (z. B. mehrere Kandidaten
        auf anderen Laufwerken). Für Zeilen außerhalb der Buchführung
        False."""
        if path not in self._state or (path, what) in self._notes:
            return False
        self._notes.add((path, what))
        return True

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

    def begin_search(self) -> list[str]:
        """Zeilen „Laufwerk fehlt“ mit Laufwerksbuchstaben für die Suche
        unter den anderen Buchstaben (MovedSearch). Getrennt von der
        Prüfung: Ein hängendes Kandidaten-Laufwerk hält so nie die Prüfung
        auf. Leer — dann startet keine —, solange eine Suche läuft oder
        keine solche Zeile wartet."""
        if self.searching:
            return []
        paths = [p for p, s in self._state.items()
                 if s == self.NO_DRIVE and drive_letter(p)]
        self.searching = bool(paths)
        return paths

    def end_search(self) -> None:
        self.searching = False

    def result(self, path: str, finding: str) -> str | None:
        """Befund einer Prüfung → FOUND/BACK (Zeile wird ein normaler Job
        und verlässt die Buchführung), der neue Zustand NO_DRIVE/NO_FILE
        (Zeile anpassen) oder None (nichts zu tun: unverändert, inzwischen
        entfernt oder eingelesen)."""
        state = self._state.get(path)
        if state is None or finding == state:
            return None
        if finding == self.REACHABLE:
            self.discard(path)
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


# ── Laufwerk unter anderem Buchstaben zurück ──────────────────────────────

# Größe und Änderungszeit der Quelle im gespeicherten Job — daran erkennt
# Spurwerk die Datei wieder, wenn ihre USB-Platte als F: statt E: kommt.
# Entscheidend ist die Größe: Die Änderungszeit einer FAT/exFAT-Platte
# verschiebt Windows mit der Sommerzeit um eine Stunde.
SOURCE_SIZE = "source_size"
SOURCE_MTIME = "source_mtime"


def source_identity(path: str) -> dict:
    """{SOURCE_SIZE, SOURCE_MTIME} der Quelle für den gespeicherten Job,
    leer, wenn sie nicht lesbar ist. Dateizugriff — nur im Hintergrund."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return {}
    return {SOURCE_SIZE: info.st_size, SOURCE_MTIME: int(info.st_mtime)}


def recorded_size(job: Mapping) -> int | None:
    """Die im Job gespeicherte Quellgröße — None bei älteren Jobs (oder
    einem unbrauchbaren Wert)."""
    size = job.get(SOURCE_SIZE)
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    return None


def file_size(path: str) -> int | None:
    """Größe einer vorhandenen Datei, sonst None. Kann an einem getrennten
    Netzlaufwerk hängen — nur im Hintergrund."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


def quiet_drive_errors() -> None:
    """Für den aufrufenden Faden keine Windows-Fehlerfenster („Kein
    Datenträger im Laufwerk“): Leere Kartenleser- oder DVD-Laufwerke
    werden im Hintergrund nur gefragt, nie angemahnt."""
    try:
        import ctypes
        # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
        ctypes.windll.kernel32.SetThreadErrorMode(0x0001 | 0x8000, None)
    except (AttributeError, OSError):   # kein Windows
        pass


def present_drives() -> list[str]:
    """Wurzeln der Laufwerksbuchstaben, die Windows gerade kennt („C:\\“, …).
    Fragt nur die Liste ab, nicht die Laufwerke selbst — hängt also auch
    dann nicht, wenn ein verbundenes Netzlaufwerk getrennt ist."""
    try:
        return list(os.listdrives())
    except (AttributeError, OSError):   # kein Windows
        return []


def drive_letter(path: str) -> str:
    """„E:“ für einen Pfad mit Laufwerksbuchstaben, sonst "" (UNC-Pfad).
    Nur Text."""
    drive = os.path.splitdrive(path)[0]
    return drive.upper() if len(drive) == 2 and drive[1] == ":" else ""


def moved_candidates(path: str, drives: Iterable[str]) -> list[str]:
    """Derselbe Pfad auf jedem anderen der `drives`: „E:\\usb\\a.mkv“ →
    „F:\\usb\\a.mkv“, … Nur Text; UNC-Pfade haben keine Kandidaten."""
    letter = drive_letter(path)
    if not letter:
        return []
    rest = os.path.splitdrive(os.path.normpath(path))[1]
    out: list[str] = []
    for root in drives:
        other = drive_letter(root)
        if other and other != letter and other + rest not in out:
            out.append(other + rest)
    return out


SEARCH_DEADLINE = 2.5   # s: so lange wartet die Suche auf ein Laufwerk


@dataclass
class MovedFinds:
    """Ergebnis einer Suche (MovedSearch.run)."""
    # {Pfad: [(Kandidat, Größe), …]} — nur Pfade mit Fund, nur von
    # Laufwerken, die geantwortet haben
    found: dict[str, list[tuple[str, int]]]
    # Pfade, für die ein eben verstummtes Laufwerk noch einen Kandidaten
    # haben könnte — für sie wählt diese Suche nicht
    unsure: set[str]
    # Laufwerksbuchstaben, die eben verstummt sind (fürs Protokoll, einmal)
    silent: list[str]


class MovedSearch:
    """Sucht die Quellen wartender „Laufwerk fehlt“-Zeilen unter den
    anderen Laufwerksbuchstaben — ohne tkinter; `run` läuft im Hintergrund,
    eine Suche zur Zeit (SourceWatch.begin_search).

    Je Kandidaten-Laufwerk ein eigener Faden (wie by_drive), der zuerst die
    Wurzel fragt und nur dann seine Kandidaten. Die Suche wartet höchstens
    `deadline` Sekunden: Ein Laufwerk, das bis dahin nicht antwortet
    (getrenntes Netzlaufwerk bis zu seinem Timeout, anlaufende USB-Platte),
    hält weder die übrigen noch die Prüfung der Zeilen auf. Es gilt dann
    als stumm und wird erst wieder gefragt, wenn seine Anfrage zurück ist —
    nie mehrere hängende Fäden je Laufwerk.

    Nie geraten: Verstummt ein Laufwerk, wählt diese Suche für die Pfade,
    die dort einen Kandidaten haben könnten, nicht (eine anlaufende Platte
    antwortet bis zur nächsten). Schweigt es weiter, zählt es wie ein
    getrenntes Laufwerk nicht mit — bis es wieder antwortet."""

    def __init__(self, deadline: float = SEARCH_DEADLINE) -> None:
        self.deadline = deadline
        self._lock = threading.Lock()
        self._busy: set[str] = set()     # Anfrage an das Laufwerk läuft
        self._silent: set[str] = set()   # stumm, bis es wieder antwortet

    def run(self, paths: Iterable[str], drives: Iterable[str],
            ) -> MovedFinds:
        """Derselbe Pfad auf den anderen `drives` (present_drives) für jede
        der `paths`. Dauert höchstens `deadline` — nur im Hintergrund."""
        paths, drives = list(paths), list(drives)
        per_drive: dict[str, list[tuple[str, str]]] = {}
        for path in paths:
            for candidate in moved_candidates(path, drives):
                per_drive.setdefault(drive_letter(candidate), []).append(
                    (path, candidate))
        answers: dict[str, list[tuple[str, str, int]]] = {}
        with self._lock:
            # abgezogen: Kommt der Buchstabe wieder, ist es ein neues Laufwerk
            self._silent &= {drive_letter(d) for d in drives}
            known = set(self._silent)
            asked = [d for d in per_drive if d not in self._busy]
            self._busy.update(asked)
        threads = [threading.Thread(target=self._ask, daemon=True,
                                    args=(d, per_drive[d], answers))
                   for d in asked]
        for thread in threads:
            thread.start()
        end = time.monotonic() + self.deadline
        for thread in threads:
            thread.join(max(0.0, end - time.monotonic()))
        with self._lock:
            answered = dict(answers)
            silent = sorted(d for d in per_drive if d not in answered)
            # nur, wessen Anfrage noch läuft — wer eben noch antwortete, nicht
            self._silent.update(d for d in silent if d in self._busy)
        found: dict[str, list[tuple[str, int]]] = {}
        for finds in answered.values():
            for path, candidate, size in finds:
                found.setdefault(path, []).append((candidate, size))
        new = [d for d in silent if d not in known]
        return MovedFinds(
            {path: sorted(found[path]) for path in paths if path in found},
            {path for d in new for path, _c in per_drive[d]}, new)

    def _ask(self, letter: str, pairs: list[tuple[str, str]],
             answers: dict) -> None:
        """Ein Kandidaten-Laufwerk fragen (eigener Faden)."""
        quiet_drive_errors()
        present, finds = False, None
        try:
            present = source_exists(drive_root(pairs[0][1]))
            finds = [(path, candidate, size) for path, candidate in pairs
                     if present
                     and (size := file_size(candidate)) is not None]
        finally:
            with self._lock:             # Antwort und Buchführung zugleich
                if finds is not None:
                    answers[letter] = finds
                self._busy.discard(letter)
                if present:              # antwortet wieder: nicht mehr stumm
                    self._silent.discard(letter)


def first_reachable(folders: Iterable[str], deadline: float) -> str | None:
    """Der erste der `folders` (Reihenfolge = Vorrang), der binnen
    `deadline` Sekunden als vorhanden antwortet, sonst None. Je Ordner ein
    eigener Faden — ein getrenntes NAS hält die übrigen nicht auf. Nur im
    Hintergrund."""
    folders = list(dict.fromkeys(folders))
    answers: dict[str, bool] = {}

    def ask(folder: str) -> None:
        quiet_drive_errors()
        answers[folder] = source_exists(folder)

    threads = [threading.Thread(target=ask, args=(f,), daemon=True)
               for f in folders]
    for thread in threads:
        thread.start()
    end = time.monotonic() + deadline
    for folder, thread in zip(folders, threads):
        thread.join(max(0.0, end - time.monotonic()))
        if answers.get(folder):
            return folder
    return None


def match_moved(found: Iterable[tuple[str, int]], size: int | None,
                ) -> tuple[str | None, list[str]]:
    """Wird eine wartende Quelle unter einem anderen Laufwerksbuchstaben
    übernommen? Nie geraten: Mit gespeicherter Größe zählen nur Kandidaten
    genau dieser Größe, ohne (ältere Jobs) alle. → (neuer Pfad, [ihn]) bei
    genau einem, sonst (None, die passenden Kandidaten) — ab zwei
    mehrdeutig, dann wählt der Nutzer („Datei neu zuordnen …“)."""
    matching = [path for path, found_size in found
                if size is None or found_size == size]
    return (matching[0] if len(matching) == 1 else None), matching


def remap_drive(path: str, old: str, new: str) -> str:
    """`path` vom Laufwerksbuchstaben von `old` auf den von `new` — nur,
    wenn er dort liegt und sich der Buchstabe ändert. Nur Text."""
    old_letter, new_letter = drive_letter(old), drive_letter(new)
    if (not old_letter or not new_letter or old_letter == new_letter
            or drive_letter(path) != old_letter):
        return path
    return new_letter + os.path.splitdrive(path)[1]


def relocate_job(job: Mapping, old: str, new: str, *,
                 drive_gone: bool) -> dict:
    """Gespeicherter Job einer Zeile, deren Quelle jetzt unter `new` liegt:
    alle Einstellungen bleiben. Fehlt das alte Laufwerk (`drive_gone`),
    zieht eine Ausgabe auf seinem Buchstaben mit um („E:\\aus\\x.mkv“ →
    „F:\\aus\\x.mkv“); jede andere bleibt. Eine nicht manuelle Ausgabe
    leitet die UI nach dem Einlesen ohnehin neu ab (Quell- bzw. fester
    Ordner)."""
    moved = dict(job)
    moved["path"] = new
    output = job.get("output_path")
    if drive_gone and isinstance(output, str):
        moved["output_path"] = remap_drive(output, old, new)
    return moved


# ── Fester Ausgabeordner ──────────────────────────────────────────────────


def probe_output_dir(folder: str) -> str:
    """Befund für den festen Ausgabeordner: REACHABLE, NO_FILE (Laufwerk
    da, Ordner fehlt — der Lauf legt ihn wie bisher an) oder NO_DRIVE
    (Laufwerk bzw. Netzfreigabe nicht erreichbar). Kann an einem
    getrennten NAS hängen — nur im Hintergrund."""
    if source_exists(folder):
        return SourceWatch.REACHABLE
    return (SourceWatch.NO_FILE if source_exists(drive_root(folder))
            else SourceWatch.NO_DRIVE)


def outputs_on_drive(plans: Iterable[FilePlan], folder: str,
                     ) -> list[FilePlan]:
    """Pläne, deren Ausgabe auf dem Laufwerk bzw. der Freigabe von `folder`
    liegt — ist der Ausgabeordner unerreichbar, sind sie es auch. Nur
    Text."""
    key = os.path.normcase(drive_root(folder))
    return [plan for plan in plans
            if os.path.normcase(drive_root(plan.output_path)) == key]


class OutputDirWatch:
    """Erreichbarkeit des festen Ausgabeordners — ohne tkinter. Ein
    unerreichbarer Ordner wird nie verworfen: Er bleibt eingestellt, die UI
    zeigt einen Hinweis und der Start verweigert, bis eine Prüfung ihn
    wieder findet oder der Nutzer einen anderen Ordner wählt. Zustände wie
    bei SourceWatch; None = kein fester Ordner."""

    def __init__(self) -> None:
        self.folder = ""
        self.state: str | None = None
        self.checking = False            # höchstens eine Prüfung zur Zeit

    def set_folder(self, folder: str, state: str = SourceWatch.CHECKING,
                   ) -> None:
        """Neuer Ordner — beim Programmstart ungeprüft (CHECKING), eben im
        Dialog gewählt REACHABLE. Ein Befund zum vorigen zählt nicht mehr."""
        self.folder = folder
        self.state = state if folder else None

    @property
    def unreachable(self) -> bool:
        return self.state == SourceWatch.NO_DRIVE

    def begin_check(self) -> str:
        """Ordner für die nächste Prüfung — leer (dann startet keine),
        solange eine läuft oder kein fester Ordner eingestellt ist."""
        if self.checking or not self.folder:
            return ""
        self.checking = True
        return self.folder

    def end_check(self) -> None:
        self.checking = False

    def result(self, folder: str, finding: str) -> str | None:
        """Befund einer Prüfung (auch der vor dem Start) → der bisherige
        Zustand, wenn sich etwas geändert hat (Hinweis/Protokoll anpassen),
        sonst None — ebenso für einen inzwischen abgewählten Ordner."""
        if folder != self.folder or finding == self.state:
            return None
        before, self.state = self.state, finding
        return before


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
