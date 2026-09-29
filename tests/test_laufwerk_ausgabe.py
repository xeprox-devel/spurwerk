"""Laufwerk unter anderem Buchstaben (USB-Platte als F: statt E:), „Datei neu
zuordnen …“ und der feste Ausgabeordner auf einem getrennten NAS.

Die Logik (core/session.py) läuft überall. Die UI-Tests brauchen
ttkbootstrap und ein Tk-Display; sie nutzen die Fixtures aus
test_befunde_hauptfenster.py (config.json IMMER in tmp_path, keine echten
Scans/Werkzeuge). Laufwerksbuchstaben sind simuliert (FakeDrives): Welche
Wurzeln „verbunden“ sind und welche Dateien darauf liegen, bestimmt der
Test — echte Laufwerke fasst kein Test an, es entstehen auch keine
Laufwerkszuordnungen. Der Ausgabeordner „auf dem NAS“ liegt wie in
test_offline_jobs.py unter tmp_path/"NAS" (jeder Ordner direkt unter
tmp_path gilt dort als eigenes Laufwerk).
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import session
from core.model import Action
from core.planner import build_plan
from core.session import OutputDirWatch, SourceWatch
from tests import test_befunde_hauptfenster as hauptfenster
from tests.helpers import film_std, profile_de
from tests.test_befunde_hauptfenster import (
    REMUX, _add, _log_text, _pump_sources, _restore, _run_start,
    _saved_session, _scanned, _shown, _tools_ok, _wait_for, builtin, film_at)

# dieselben Fixtures wie dort: config.json in tmp_path, Scans ersetzt
tk_root = hauptfenster.tk_root
make_win = hauptfenster.make_win
win = hauptfenster.win

W = SourceWatch
windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="Windows-Pfade")


# ══ Logik ohne Tk: neuer Laufwerksbuchstabe ══════════════════════════════


@windows_only
def test_laufwerksbuchstabe_nur_aus_dem_text():
    assert session.drive_letter("e:\\usb\\a.mkv") == "E:"
    assert session.drive_letter("F:/x.mkv") == "F:"
    assert session.drive_letter("\\\\nas\\filme\\a.mkv") == ""


@windows_only
def test_kandidaten_derselbe_pfad_auf_den_anderen_laufwerken():
    drives = ["C:\\", "E:\\", "F:\\", "f:\\"]
    assert session.moved_candidates("E:\\usb\\Filme\\a.mkv", drives) == [
        "C:\\usb\\Filme\\a.mkv", "F:\\usb\\Filme\\a.mkv"]
    # UNC-Pfade: keine Suche
    assert session.moved_candidates("\\\\nas\\filme\\a.mkv", drives) == []


@windows_only
def test_suche_je_laufwerk_ein_faden_haengendes_haelt_andere_nicht_auf(
        monkeypatch):
    gate = threading.Event()
    asked: list[str] = []

    def exists(path):        # Z: = getrenntes Netzlaufwerk, hängt
        asked.append(path)
        if path.upper().startswith("Z:"):
            gate.wait(5)
            return False
        return path.upper() == "F:\\"

    def size(path):
        asked.append(path)
        return 1234 if path.upper() == "F:\\USB\\A.MKV" else None

    monkeypatch.setattr(session, "source_exists", exists)
    monkeypatch.setattr(session, "file_size", size)
    search = session.MovedSearch(deadline=0.3)
    lost = ["E:\\usb\\a.mkv", "E:\\usb\\b.mkv", "\\\\nas\\x\\c.mkv"]
    drives = ["C:\\", "E:\\", "F:\\", "Z:\\"]
    started = time.monotonic()
    finds = search.run(lost, drives)
    # Z: hält die Suche nicht über die Frist hinaus auf, F: hat geantwortet
    assert time.monotonic() - started < 2.0
    assert finds.found == {"E:\\usb\\a.mkv": [("F:\\usb\\a.mkv", 1234)]}
    # … Z: ist eben verstummt: Dort könnte ein zweiter Kandidat liegen —
    # diese Suche wählt für die E:-Dateien nicht (nie raten)
    assert finds.silent == ["Z:"]
    assert finds.unsure == {"E:\\usb\\a.mkv", "E:\\usb\\b.mkv"}
    # nächste Suche: Z: wird nicht erneut gefragt (seine Anfrage hängt
    # noch) und zählt als nicht verbunden — jetzt ist der Fund eindeutig
    finds = search.run(lost, drives)
    assert finds.found == {"E:\\usb\\a.mkv": [("F:\\usb\\a.mkv", 1234)]}
    assert finds.silent == [] and finds.unsure == set()
    # je Suche die Wurzel, nicht je Datei; ein fehlendes C: — seine Dateien
    # werden gar nicht erst gefragt
    assert [p for p in asked if p.upper().startswith("Z:")] == ["Z:\\"]
    assert [p for p in asked if p.upper().startswith("C:")] == ["C:\\"] * 2
    # Z: antwortet endlich („nicht da“): wieder gefragt, bleibt aber als
    # stumm bekannt — hängt es erneut, kein zweites Mal Warten/Protokoll
    gate.set()
    _wait_for(lambda: not search._busy)
    gate.clear()
    finds = search.run(lost, drives)
    assert [p for p in asked if p.upper().startswith("Z:")] == ["Z:\\"] * 2
    assert finds.silent == [] and finds.unsure == set()
    assert finds.found == {"E:\\usb\\a.mkv": [("F:\\usb\\a.mkv", 1234)]}
    gate.set()


@windows_only
def test_suche_anlaufende_platte_zaehlt_sobald_sie_antwortet(monkeypatch):
    gate = threading.Event()

    def exists(path):        # F: läuft an — antwortet erst nach der Frist
        if path.upper().startswith("F:"):
            gate.wait(5)
        return path.upper() == "F:\\"

    monkeypatch.setattr(session, "source_exists", exists)
    monkeypatch.setattr(session, "file_size",
                        lambda p: 1234 if p.upper() == "F:\\USB\\A.MKV"
                        else None)
    search = session.MovedSearch(deadline=0.2)
    lost, drives = ["E:\\usb\\a.mkv"], ["C:\\", "F:\\"]
    finds = search.run(lost, drives)
    assert finds.found == {} and finds.silent == ["F:"]
    assert finds.unsure == {"E:\\usb\\a.mkv"}
    gate.set()                                  # angelaufen: „da“
    _wait_for(lambda: not search._busy)
    finds = search.run(lost, drives)
    assert finds.found == {"E:\\usb\\a.mkv": [("F:\\usb\\a.mkv", 1234)]}
    assert finds.silent == [] and finds.unsure == set()


@windows_only
def test_suche_abgezogenes_stummes_laufwerk_ist_danach_neu(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(session, "source_exists",
                        lambda _p: gate.wait(5) and False)
    monkeypatch.setattr(session, "file_size", lambda _p: None)
    search = session.MovedSearch(deadline=0.1)

    def settle():                               # hängende Anfrage zurück
        gate.set()
        _wait_for(lambda: not search._busy)
        gate.clear()

    assert search.run(["E:\\a.mkv"], ["Z:\\"]).silent == ["Z:"]
    settle()
    assert search.run(["E:\\a.mkv"], ["Z:\\"]).silent == []   # bekannt
    settle()
    search.run(["E:\\a.mkv"], [])               # Z: nicht mehr in der Liste
    assert search.run(["E:\\a.mkv"], ["Z:\\"]).silent == ["Z:"]
    gate.set()


def test_suche_startet_nur_fuer_laufwerk_fehlt_mit_buchstaben():
    watch = SourceWatch()
    for path in ("E:\\a.mkv", "\\\\nas\\b.mkv", "D:\\c.mkv", "G:\\d.mkv"):
        watch.watch(path)
    watch.result("E:\\a.mkv", W.NO_DRIVE)
    watch.result("\\\\nas\\b.mkv", W.NO_DRIVE)       # UNC: keine Suche
    watch.result("D:\\c.mkv", W.NO_FILE)             # Laufwerk da
    assert watch.begin_search() == ["E:\\a.mkv"]     # G: noch ungeprüft
    assert watch.searching and watch.begin_search() == []   # eine zur Zeit
    assert not watch.checking                        # Prüfung unberührt
    watch.end_search()
    watch.discard("E:\\a.mkv")
    assert watch.begin_search() == [] and not watch.searching


def test_erster_erreichbarer_ordner(monkeypatch):
    gate = threading.Event()

    def exists(path):
        if path == "N:/nas":                     # getrenntes NAS hängt
            gate.wait(5)
        return path in ("N:/nas", "C:/lokal", "C:/home")

    monkeypatch.setattr(session, "source_exists", exists)
    started = time.monotonic()
    assert session.first_reachable(
        ["D:/weg", "N:/nas", "C:/lokal", "C:/home"], 0.2) == "C:/lokal"
    assert time.monotonic() - started < 2.0
    assert session.first_reachable(["D:/weg"], 0.2) is None
    gate.set()
    # Vorrang: antwortet der erste, gilt er
    assert session.first_reachable(["N:/nas", "C:/lokal"], 1.0) == "N:/nas"


def test_eindeutig_nur_mit_passender_groesse():
    found = [("F:\\a.mkv", 100), ("G:\\a.mkv", 200)]
    assert session.match_moved(found, 200) == ("G:\\a.mkv", ["G:\\a.mkv"])
    assert session.match_moved(found, 300) == (None, [])
    # zwei mit derselben Größe: nie raten
    assert session.match_moved(found + [("H:\\a.mkv", 200)], 200) == (
        None, ["G:\\a.mkv", "H:\\a.mkv"])


def test_aeltere_jobs_ohne_groesse_nur_bei_genau_einem_kandidaten():
    assert session.match_moved([("F:\\a.mkv", 5)], None) == (
        "F:\\a.mkv", ["F:\\a.mkv"])
    assert session.match_moved([("F:\\a.mkv", 5), ("G:\\a.mkv", 7)],
                               None) == (None, ["F:\\a.mkv", "G:\\a.mkv"])


def test_gespeicherte_groesse_nur_als_ganze_zahl():
    assert session.recorded_size({"source_size": 42}) == 42
    for bad in (True, -1, "42", 4.2, None):
        assert session.recorded_size({"source_size": bad}) is None
    assert session.recorded_size({}) is None


def test_groesse_und_aenderungszeit_der_quelle(tmp_path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x" * 1234)
    identity = session.source_identity(str(src))
    assert identity["source_size"] == 1234
    assert isinstance(identity["source_mtime"], int)
    assert session.source_identity(str(tmp_path / "weg.mkv")) == {}
    assert session.file_size(str(src)) == 1234
    assert session.file_size(str(tmp_path)) is None       # Ordner
    assert session.file_size(str(tmp_path / "weg.mkv")) is None


def test_sitzung_speichert_groesse_zum_gescannten_job():
    plan = build_plan(film_std(), profile_de())           # C:/filme/test.mkv
    waiting = {"path": "E:/usb/a.mkv", "source_size": 7}
    jobs = session.session_jobs(
        {"C:/filme/test.mkv": plan, "E:/usb/a.mkv": None},
        {"E:/usb/a.mkv": waiting},
        {"C:/filme/test.mkv": {"source_size": 99, "source_mtime": 5}})
    assert jobs[0] == {**session.serialize_plan(plan), "source_size": 99,
                       "source_mtime": 5}
    assert jobs[1] is waiting                             # unverändert


@windows_only
def test_suchfaden_ohne_windows_fehlerfenster():
    # leere Kartenleser/DVD-Laufwerke: nie „Kein Datenträger“-Fenster —
    # nur für den eigenen Faden (nie für den Tk-Thread)
    import ctypes
    get_mode = ctypes.windll.kernel32.GetThreadErrorMode
    before = get_mode()
    modes = []

    def worker():
        session.quiet_drive_errors()
        modes.append(get_mode())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(3)
    assert modes and modes[0] & 0x0001 and modes[0] & 0x8000
    assert get_mode() == before


def test_laufwerksliste_ohne_windows_leer(monkeypatch):
    monkeypatch.delattr(os, "listdrives", raising=False)
    assert session.present_drives() == []


@windows_only
def test_ausgabe_zieht_nur_vom_fehlenden_laufwerk_mit():
    job = {"path": "E:\\usb\\a.mkv", "output_manual": True,
           "output_path": "E:\\aus\\Film.mkv", "profile_name": "P"}
    moved = session.relocate_job(job, "E:\\usb\\a.mkv", "F:\\usb\\a.mkv",
                                 drive_gone=True)
    assert moved == {**job, "path": "F:\\usb\\a.mkv",
                     "output_path": "F:\\aus\\Film.mkv"}
    assert job["path"] == "E:\\usb\\a.mkv"                # Original bleibt
    # anderswo bleibt die Ausgabe — ebenso, wenn das Laufwerk gar nicht
    # fehlt („Datei fehlt“, neu zugeordnet)
    elsewhere = {**job, "output_path": "D:\\aus\\Film.mkv"}
    assert session.relocate_job(elsewhere, "E:\\usb\\a.mkv", "F:\\a.mkv",
                                drive_gone=True)["output_path"] \
        == "D:\\aus\\Film.mkv"
    assert session.relocate_job(job, "E:\\usb\\a.mkv", "F:\\a.mkv",
                                drive_gone=False)["output_path"] \
        == "E:\\aus\\Film.mkv"
    assert session.remap_drive("\\\\nas\\aus\\x.mkv", "E:\\a", "F:\\a") \
        == "\\\\nas\\aus\\x.mkv"


def test_hinweis_je_zeile_und_anlass_einmal():
    watch = SourceWatch()
    watch.watch("A")
    assert watch.note("A", "mehrdeutig")
    assert not watch.note("A", "mehrdeutig")
    assert watch.note("A", "doppelt")
    assert not watch.note("B", "mehrdeutig")      # keine wartende Zeile
    watch.discard("A")
    watch.watch("A")                              # neue Zeile, neues Glück
    assert watch.note("A", "mehrdeutig")


@windows_only
def test_bereits_gelistet_unabhaengig_von_schreibweise():
    listed = ["C:\\x.mkv", "F:\\usb\\A.mkv"]
    assert session.find_listed("f:/USB/a.mkv", listed) == "F:\\usb\\A.mkv"
    assert session.find_listed("F:\\usb\\b.mkv", ["F:\\usb\\a.mkv"]) is None


# ══ Logik ohne Tk: Ausgabeordner ═════════════════════════════════════════


def test_ausgabeordner_befund(monkeypatch):
    present = {"N:/", "N:/da", "D:/"}
    monkeypatch.setattr(session, "source_exists", lambda p: p in present)
    monkeypatch.setattr(session, "drive_root", lambda p: p[:2] + "/")
    assert session.probe_output_dir("N:/da") == W.REACHABLE
    assert session.probe_output_dir("D:/weg") == W.NO_FILE   # wird angelegt
    assert session.probe_output_dir("Q:/nas") == W.NO_DRIVE


def test_ausgaben_auf_dem_laufwerk_des_ordners(monkeypatch):
    monkeypatch.setattr(session, "drive_root", lambda p: p[:2] + "/")
    a = SimpleNamespace(output_path="N:/Filme/a.mkv")
    b = SimpleNamespace(output_path="C:/manuell/b.mkv")
    assert session.outputs_on_drive([a, b], "N:/Filme") == [a]


def test_ausgabeordner_zustand():
    watch = OutputDirWatch()
    assert watch.begin_check() == "" and watch.state is None   # Quellordner
    watch.set_folder("N:/Filme")                               # Programmstart
    assert watch.state == W.CHECKING and not watch.unreachable
    assert watch.begin_check() == "N:/Filme"
    assert watch.begin_check() == ""                           # läuft schon
    assert watch.result("N:/Filme", W.NO_DRIVE) == W.CHECKING
    watch.end_check()
    assert watch.unreachable
    assert watch.result("N:/Filme", W.NO_DRIVE) is None        # unverändert
    assert watch.result("N:/Filme", W.REACHABLE) == W.NO_DRIVE
    # Befund zu einem inzwischen abgewählten Ordner zählt nicht
    watch.set_folder("D:/neu", W.REACHABLE)
    assert watch.result("N:/Filme", W.NO_DRIVE) is None
    assert watch.state == W.REACHABLE
    watch.set_folder("")
    assert watch.state is None and not watch.unreachable


# ══ UI: simulierte Laufwerksbuchstaben ═══════════════════════════════════


class FakeDrives:
    """Verbundene Laufwerksbuchstaben („F:\\“) und ihre Dateien mit Größe —
    für source_exists/file_size/present_drives. Pfade unter tmp_path
    bleiben echt; alle anderen beantwortet nur diese Attrappe, kein echtes
    Laufwerk wird gefragt. `gates` lässt ein Laufwerk hängen."""

    def __init__(self, monkeypatch, tmp_path: Path, drives=(), files=None):
        self.drives = list(drives)
        self.files = dict(files or {})
        self.calls: list[tuple[str, bool]] = []    # (Pfad, im Tk-Thread?)
        self.gates: dict[str, threading.Event] = {}
        self._tmp = {os.path.normcase(str(tmp_path)),
                     os.path.normcase(str(tmp_path.resolve()))}
        self._real = (session.source_exists, session.file_size)
        monkeypatch.setattr(session, "present_drives",
                            lambda: list(self.drives))
        monkeypatch.setattr(session, "source_exists", self.exists)
        monkeypatch.setattr(session, "file_size", self.size)

    def _real_path(self, path: str) -> bool:
        return any(os.path.normcase(path).startswith(t) for t in self._tmp)

    def _connected(self, path: str) -> bool:
        self.calls.append((path, threading.current_thread()
                           is threading.main_thread()))
        letter = session.drive_letter(path)
        gate = self.gates.get(letter)
        if gate is not None:
            gate.wait(5)
        return bool(letter) and letter + "\\" in {d.upper()
                                                  for d in self.drives}

    def _file(self, path: str):
        return {os.path.normcase(k): v for k, v in self.files.items()}.get(
            os.path.normcase(path))

    def exists(self, path: str) -> bool:
        if self._real_path(path):
            return self._real[0](path)
        if not self._connected(path):
            return False
        return (os.path.normcase(path) == os.path.normcase(
            session.drive_letter(path) + "\\") or self._file(path) is not None)

    def size(self, path: str):
        if self._real_path(path):
            return self._real[1](path)
        return self._file(path) if self._connected(path) else None


E_FILM = "E:\\usb\\film.mkv"
F_FILM = "F:\\usb\\film.mkv"


def _job(path: str, **extra) -> dict:
    """Voll konfigurierter Job der letzten Sitzung (Profil „Nur remuxen“,
    Spur 1 manuell raus)."""
    job = session.serialize_plan(build_plan(film_at(path), builtin(REMUX)))
    job["overrides"] = {"1": "drop"}
    job.update(extra)
    return job


def _here(tmp_path: Path, name: str) -> str:
    src = tmp_path / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"")
    return str(src.resolve())


def _row(win, path: str) -> tuple[str, str]:
    tree = win.file_list.tree
    return tree.set(path, "plan"), tree.set(path, "status")


def _pump_until(win, cond, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "Zeitüberschreitung"
        try:
            win._handle_message(win.ui_q.get(timeout=0.02))
        except queue.Empty:
            pass


def _menu(win, path: str) -> dict:
    menu = win._file_menu(path)
    entries = {}
    for i in range(menu.index("end") + 1):
        if menu.type(i) == "command":
            entries[menu.entrycget(i, "label")] = (
                i, str(menu.entrycget(i, "state")))
    entries["_menu"] = menu
    return entries


# A3 · neuer Buchstabe: automatisch, am selben Platz, mit allen Einstellungen


@windows_only
def test_ui_usb_platte_als_f_statt_e_wird_eingelesen(win, tmp_path,
                                                     monkeypatch):
    a, b = _here(tmp_path, "a.mkv"), _here(tmp_path, "b.mkv")
    job = _job(E_FILM, source_size=1234, output_manual=True,
               output_path="E:\\aus\\Mein Film.mkv")
    FakeDrives(monkeypatch, tmp_path, drives=["C:\\", "F:\\"],
               files={F_FILM: 1234})
    win.cfg.session = [{"path": a}, job, {"path": b}]
    _restore(win)
    # dieselbe Zeile, derselbe Platz in der Warteschlange — neuer Pfad
    assert win.file_list.paths() == [a, F_FILM, b]
    assert list(win.plans) == [a, F_FILM, b]
    assert E_FILM not in win._watch and E_FILM not in win._pending_restore
    assert "Laufwerk E: ist jetzt F: — film.mkv wird eingelesen." \
        in _log_text(win)
    assert "Ausgabe folgt: F:\\aus\\Mein Film.mkv" in _log_text(win)
    assert _row(win, F_FILM) == ("wird analysiert …", "wird gescannt")
    _wait_for(lambda: sorted(win.scans) == sorted([a, b, F_FILM]))
    # die Sitzung führt den Job nur noch unter dem neuen Pfad
    saved = _saved_session(tmp_path)
    assert [j["path"] for j in saved] == [a, F_FILM, b]
    assert saved[1] == {**job, "path": F_FILM,
                        "output_path": "F:\\aus\\Mein Film.mkv"}

    _scanned(win, F_FILM)                  # Wiederherstellungsweg
    plan = win.plans[F_FILM]
    assert plan.profile_name == REMUX
    assert plan.decisions[1].action is Action.DROP
    assert plan.output_manual and plan.output_path == "F:\\aus\\Mein Film.mkv"
    win._safe_save()
    saved = _saved_session(tmp_path)
    assert [j["path"] for j in saved] == [a, F_FILM, b]
    assert saved[1]["source_size"] == 1234     # Größe bleibt am Job


@windows_only
def test_ui_ausgabe_aus_dem_quellordner_folgt_dem_neuen_ordner(
        win, tmp_path, monkeypatch):
    FakeDrives(monkeypatch, tmp_path, drives=["F:\\"],
               files={F_FILM: 1234})
    win.cfg.session = [_job(E_FILM, source_size=1234)]
    _restore(win)
    _scanned(win, F_FILM)
    assert win.plans[F_FILM].output_path == "F:\\usb\\film_remux.mkv"


@windows_only
def test_ui_manuelle_ausgabe_anderswo_bleibt(win, tmp_path, monkeypatch):
    FakeDrives(monkeypatch, tmp_path, drives=["F:\\"],
               files={F_FILM: 1234})
    out = str(tmp_path / "aus" / "Film.mkv")
    win.cfg.session = [_job(E_FILM, source_size=1234, output_manual=True,
                            output_path=out)]
    _restore(win)
    assert "Ausgabe folgt" not in _log_text(win)
    _scanned(win, F_FILM)
    assert win.plans[F_FILM].output_path == out


@windows_only
def test_ui_platte_kommt_spaeter_unter_neuem_buchstaben(win, tmp_path,
                                                       monkeypatch):
    drives = FakeDrives(monkeypatch, tmp_path, drives=["C:\\"])
    win.cfg.session = [_job(E_FILM, source_size=1234)]
    _restore(win)
    assert _row(win, E_FILM)[1] == "Laufwerk fehlt"
    win.file_list.select(E_FILM)
    win._on_file_selected(E_FILM)
    drives.drives.append("F:\\")                 # Platte eingesteckt
    drives.files[F_FILM] = 1234
    win._check_sources()
    _pump_sources(win)
    assert win.file_list.paths() == [F_FILM]
    assert win.selected == F_FILM                # Markierung zieht mit
    assert win.file_list.selected() == F_FILM
    _wait_for(lambda: win.scans == [F_FILM])
    # kein Zugriff im Tk-Thread
    assert drives.calls and not any(main for _p, main in drives.calls)


@windows_only
def test_ui_andere_groesse_wird_nicht_uebernommen(win, tmp_path,
                                                  monkeypatch):
    FakeDrives(monkeypatch, tmp_path, drives=["F:\\"], files={F_FILM: 999})
    win.cfg.session = [_job(E_FILM, source_size=1234)]
    _restore(win)
    assert win.file_list.paths() == [E_FILM]
    assert _row(win, E_FILM)[1] == "Laufwerk fehlt"
    assert win.scans == [] and "ist jetzt" not in _log_text(win)


@windows_only
def test_ui_aelterer_job_ohne_groesse_nur_bei_einem_kandidaten(
        win, tmp_path, monkeypatch):
    drives = FakeDrives(monkeypatch, tmp_path, drives=["F:\\", "G:\\"],
                        files={F_FILM: 1, "G:\\usb\\film.mkv": 2})
    win.cfg.session = [_job(E_FILM)]               # ohne source_size
    _restore(win)
    assert win.file_list.paths() == [E_FILM] and win.scans == []
    del drives.files["G:\\usb\\film.mkv"]          # nur noch einer
    win._check_sources()
    _pump_sources(win)
    assert win.file_list.paths() == [F_FILM]


@windows_only
def test_ui_mehrere_kandidaten_keine_wahl_protokoll_einmal(win, tmp_path,
                                                          monkeypatch):
    FakeDrives(monkeypatch, tmp_path, drives=["F:\\", "G:\\"],
               files={F_FILM: 1234, "G:\\usb\\film.mkv": 1234})
    job = _job(E_FILM, source_size=1234)
    win.cfg.session = [job]
    _restore(win)
    for _ in range(2):                              # zwei Takte
        win._check_sources()
        _pump_sources(win)
    assert win.file_list.paths() == [E_FILM]
    assert _row(win, E_FILM)[1] == "Laufwerk fehlt"
    assert win._pending_restore[E_FILM] is job and win.scans == []
    message = ("film.mkv: passende Datei auf mehreren Laufwerken gefunden "
               "(F: und G:) — Spurwerk wählt nicht selbst. Rechtsklick → "
               "„Datei neu zuordnen …“.")
    assert _log_text(win).count(message) == 1


@windows_only
def test_ui_neuer_ort_schon_in_der_liste(win, tmp_path, monkeypatch):
    FakeDrives(monkeypatch, tmp_path, drives=["F:\\"], files={F_FILM: 1234})
    win.cfg.session = [_job(E_FILM, source_size=1234), {"path": F_FILM}]
    _restore(win)
    win._check_sources()
    _pump_sources(win)
    assert win.file_list.paths() == [E_FILM, F_FILM]
    assert E_FILM in win._watch
    assert _log_text(win).count("film.mkv liegt jetzt unter F:\\usb\\"
                                "film.mkv, das steht aber schon in der "
                                "Warteschlange") == 1


@windows_only
def test_ui_unc_pfad_wird_nicht_umgedeutet(win, tmp_path, monkeypatch):
    drives = FakeDrives(monkeypatch, tmp_path, drives=["F:\\"])
    unc = "\\\\nas\\filme\\film.mkv"
    win.cfg.session = [{"path": unc}]
    _restore(win)
    assert _row(win, unc)[1] == "Laufwerk fehlt"
    assert not any(p.upper().startswith("F:") for p, _m in drives.calls)


@windows_only
def test_ui_haengendes_kandidaten_laufwerk_blockiert_nicht(win, tmp_path,
                                                          monkeypatch):
    drives = FakeDrives(monkeypatch, tmp_path, drives=["F:\\", "Z:\\"],
                        files={F_FILM: 1234})
    drives.gates["Z:"] = gate = threading.Event()    # hängt bis zum Testende
    win._moved_search.deadline = 0.2
    win.cfg.session = [_job(E_FILM, source_size=1234)]
    started = time.monotonic()
    _restore(win)                  # Prüfung und Suche enden trotz Z:
    assert time.monotonic() - started < 2.0
    # Z: ist eben verstummt — dort könnte ein zweiter Kandidat liegen: in
    # dieser Runde keine Wahl, das Protokoll sagt es einmal
    assert win.file_list.paths() == [E_FILM]
    assert _row(win, E_FILM)[1] == "Laufwerk fehlt"
    silent = ("Laufwerk Z: antwortet nicht (getrenntes Netzlaufwerk?) — "
              "Spurwerk sucht wartende Dateien vorerst ohne dieses Laufwerk.")
    assert _log_text(win).count(silent) == 1
    # nächster Takt: Z: hängt weiter, wird nicht erneut gefragt und zählt
    # nicht mehr mit — F: ist eindeutig
    win._check_sources()
    _pump_sources(win)
    assert time.monotonic() - started < 3.0
    assert win.file_list.paths() == [F_FILM]
    assert "Laufwerk E: ist jetzt F: — film.mkv wird eingelesen." \
        in _log_text(win)
    assert _log_text(win).count(silent) == 1
    assert [p for p, _m in drives.calls if p.upper().startswith("Z:")] \
        == ["Z:\\"]
    assert not any(main for _p, main in drives.calls)   # nie im Tk-Thread
    gate.set()


@windows_only
def test_ui_haengendes_fremdes_laufwerk_haelt_die_pruefung_nicht_auf(
        win, tmp_path, monkeypatch):
    # Laptop unterwegs: Z: ist ein getrenntes Netzlaufwerk (hängt bis zu
    # seinem Timeout), die USB-Platte kommt unter ihrem alten Buchstaben
    drives = FakeDrives(monkeypatch, tmp_path, drives=["C:\\", "Z:\\"])
    drives.gates["Z:"] = gate = threading.Event()
    win._moved_search.deadline = 0.2
    win.cfg.session = [_job(E_FILM, source_size=1234)]
    win._restore_session()
    _pump_until(win, lambda: not win._watch.checking, timeout=1.0)
    assert _row(win, E_FILM)[1] == "Laufwerk fehlt"
    assert "Jetzt erneut prüfen" in _menu(win, E_FILM)
    drives.drives.append("E:\\")                  # Platte wieder da
    drives.files[E_FILM] = 1234
    started = time.monotonic()
    win._on_focus_in(SimpleNamespace(widget=win.winfo_toplevel()))
    _pump_until(win, lambda: E_FILM not in win._watch, timeout=1.0)
    assert time.monotonic() - started < 1.0
    assert not gate.is_set()                      # Z: hängt noch immer
    assert "Laufwerk wieder da: film.mkv wird eingelesen." in _log_text(win)
    _wait_for(lambda: win.scans == [E_FILM])
    # die Suche der ersten Runde endet ebenso — Z: nur einmal gefragt
    _pump_sources(win)
    assert not win._watch.searching
    assert [p for p, _m in drives.calls if p.upper().startswith("Z:")] \
        == ["Z:\\"]
    gate.set()


# A2 · Größe wird beim Scan erfasst (im Hintergrund)


def test_ui_scan_erfasst_groesse_fuer_die_sitzung(win, tmp_path,
                                                  monkeypatch):
    from ui import main_window as mw
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x" * 321)
    path = str(src.resolve())
    win.add_files([path])
    monkeypatch.setattr(mw, "scan_file", lambda _m, p: film_at(p))
    win._tools_ready.set()
    win.real_scan_worker(path)                     # Hintergrund-Teil
    msg = win.ui_q.get_nowait()
    assert msg[0] == "SCANNED" and msg[4]["source_size"] == 321
    win._handle_message(msg)
    win._safe_save()
    (saved,) = _saved_session(tmp_path)
    assert saved["source_size"] == 321 and "source_mtime" in saved


def test_ui_groesse_des_jobs_bleibt_ohne_frischen_wert(win, tmp_path):
    path = _here(tmp_path, "a.mkv")
    win.cfg.session = [{"path": path, "source_size": 77}]
    _restore(win)
    _scanned(win, path)                           # ohne Größe gemeldet
    win._safe_save()
    assert _saved_session(tmp_path)[0]["source_size"] == 77


# A4 · „Datei neu zuordnen …“


def _choose(monkeypatch, result: str | None, seen: dict | None = None,
            during=None):
    """Datei-Dialog ersetzen: merkt sich die Argumente, liefert `result`."""
    from ui import main_window as mw

    def ask(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        if during is not None:
            during()
        return result or ""

    monkeypatch.setattr(mw.filedialog, "askopenfilename", ask)


def _relink(win, path: str) -> None:
    """„Datei neu zuordnen …“ wie aus dem Menü: Der Startordner wird im
    Hintergrund gesucht, dann öffnet der (ersetzte) Dialog."""
    win._relink(path)
    _pump_until(win, lambda: not win._relinking)


def test_ui_kontextmenue_datei_neu_zuordnen(win, tmp_path, monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")    # Laufwerk fehlt
    moved = str(tmp_path / "verschoben.mkv")       # Datei fehlt
    win.cfg.session = [{"path": gone}, {"path": moved}]
    _restore(win)
    for path in (gone, moved):
        assert _menu(win, path)["Datei neu zuordnen …"][1] == "normal"
    (normal,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, normal)
    assert "Datei neu zuordnen …" not in _menu(win, normal)
    # solange die Startprüfung läuft, ist der Zustand noch offen
    gate = threading.Event()
    monkeypatch.setattr(session, "source_exists", lambda _p: gate.wait(5)
                        and False)
    nas = str(tmp_path / "NAS" / "x.mkv")
    win.cfg.session = [{"path": nas}]
    win._restore_session()
    assert "Datei neu zuordnen …" not in _menu(win, nas)
    gate.set()
    _pump_sources(win)


def test_ui_neu_zuordnen_behaelt_einstellungen_und_platz(win, tmp_path,
                                                         monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    first, last = _here(tmp_path, "a.mkv"), _here(tmp_path, "z.mkv")
    new = _here(tmp_path, "Neu/Film (2010).mkv")
    job = _job(gone)
    win.cfg.session = [{"path": first}, job, {"path": last}]
    _restore(win)
    _scanned(win, first)
    seen: dict = {}
    _choose(monkeypatch, new.replace("\\", "/"), seen)
    entries = _menu(win, gone)
    entries["_menu"].invoke(entries["Datei neu zuordnen …"][0])
    _pump_until(win, lambda: not win._relinking)
    # Startordner: eine eingelesene Datei, nie das fehlende Laufwerk
    assert seen["initialdir"] == str(Path(first).parent)
    assert seen["filetypes"] == [("MKV-Dateien", "*.mkv")]
    assert win.file_list.paths() == [first, new, last]
    assert "film.mkv neu zugeordnet: " + new in _log_text(win)
    _wait_for(lambda: new in win.scans)
    assert [j["path"] for j in _saved_session(tmp_path)] == [first, new, last]
    _scanned(win, new)
    plan = win.plans[new]
    assert plan.profile_name == REMUX
    assert plan.decisions[1].action is Action.DROP


def test_ui_neu_zuordnen_ohne_eingelesene_datei_startet_im_benutzerordner(
        win, tmp_path, monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    win.cfg.session = [{"path": gone}]
    _restore(win)
    seen: dict = {}
    _choose(monkeypatch, None, seen)                  # abgebrochen
    _relink(win, gone)
    assert seen["initialdir"] == str(Path.home())
    assert win.file_list.paths() == [gone] and gone in win._watch


def test_ui_datei_fehlt_neu_zuordnen_startet_im_alten_ordner(win, tmp_path,
                                                            monkeypatch):
    moved = str(tmp_path / "Filme" / "film.mkv")
    (tmp_path / "Filme").mkdir()                      # Laufwerk da
    out = str(tmp_path / "aus" / "x.mkv")
    win.cfg.session = [_job(moved, output_manual=True, output_path=out)]
    _restore(win)
    assert _row(win, moved)[1] == "Datei fehlt"
    new = _here(tmp_path, "Filme/umbenannt.mkv")
    seen: dict = {}
    _choose(monkeypatch, new, seen)
    _relink(win, moved)
    assert seen["initialdir"] == str(tmp_path / "Filme")
    assert win._pending_restore[new]["output_path"] == out   # bleibt
    _scanned(win, new)
    assert win.plans[new].output_path == out


def test_ui_neu_zuordnen_auf_datei_der_liste_aendert_nichts(win, tmp_path,
                                                           monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    job = _job(gone)
    win.cfg.session = [job]
    _restore(win)
    (other,) = _add(win, tmp_path / "anderer.mkv")
    win._safe_save()
    before = _saved_session(tmp_path)
    _choose(monkeypatch, other.upper())               # andere Schreibweise
    _relink(win, gone)
    ((kind, title, message),) = win.messages
    assert (kind, title) == ("error", "Datei neu zuordnen")
    assert "steht schon in der Warteschlange" in message
    assert "Nichts geändert" in message
    assert win.file_list.paths() == [gone, other]
    assert win._pending_restore[gone] is job and gone in win._watch
    assert _saved_session(tmp_path) == before


def test_ui_neu_zuordnen_zeile_inzwischen_wiedergefunden(win, tmp_path,
                                                        monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    win.cfg.session = [{"path": gone}]
    _restore(win)
    new = _here(tmp_path, "b.mkv")

    def found_meanwhile():                            # Platte wieder da
        Path(gone).parent.mkdir()
        Path(gone).write_bytes(b"")
        win._check_sources()
        _pump_sources(win)

    _choose(monkeypatch, new, during=found_meanwhile)
    _relink(win, gone)
    assert win.file_list.paths() == [gone]
    assert "inzwischen wiedergefunden oder entfernt — nichts geändert" \
        in _log_text(win)


def test_ui_neu_zuordnen_nur_mkv(win, tmp_path, monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    win.cfg.session = [{"path": gone}]
    _restore(win)
    _choose(monkeypatch, str(tmp_path / "film.mp4"))
    _relink(win, gone)
    assert win.messages[-1][:2] == ("error", "Datei neu zuordnen")
    assert win.file_list.paths() == [gone]


def test_ui_neu_zuordnen_startordner_nie_auf_getrenntem_nas(win, tmp_path,
                                                           monkeypatch):
    # eine eingelesene Datei liegt auf dem NAS, das seither getrennt ist:
    # ihr Ordner wäre der erste Kandidat — der Dialog hinge daran
    from ui import main_window as mw
    monkeypatch.setattr(mw, "RELINK_FOLDER_S", 0.2)
    gone = str(tmp_path / "E_weg" / "film.mkv")
    local = _here(tmp_path, "lokal/a.mkv")
    nas = _here(tmp_path, "NAS/b.mkv")
    win.cfg.session = [{"path": local}, {"path": nas}, {"path": gone}]
    _restore(win)
    _scanned(win, local)
    _scanned(win, nas)                                # zuletzt eingelesen
    gate, calls = _hanging(monkeypatch, tmp_path)     # NAS jetzt getrennt
    seen: dict = {}
    _choose(monkeypatch, None, seen)
    started = time.monotonic()
    win._relink(gone)
    assert time.monotonic() - started < 0.5          # Tk-Thread wartet nie
    assert "initialdir" not in seen                  # Dialog noch nicht
    win._relink(gone)                                # zweimal: eine Suche
    _pump_until(win, lambda: not win._relinking)
    assert seen["initialdir"] == str(Path(local).parent)
    assert [p for p, _m in calls if p.startswith(str(tmp_path / "NAS"))] \
        == [str(Path(nas).parent)]
    assert not any(main for _p, main in calls)
    gate.set()


def test_ui_neu_zuordnen_zeile_waehrend_der_ordnersuche_entfernt(
        win, tmp_path, monkeypatch):
    gone = str(tmp_path / "E_weg" / "film.mkv")
    win.cfg.session = [{"path": gone}]
    _restore(win)
    seen: dict = {}
    _choose(monkeypatch, _here(tmp_path, "b.mkv"), seen)
    win._relink(gone)
    win.file_list.select(gone)
    win._remove_selected()
    _pump_until(win, lambda: not win._relinking)
    assert seen == {}                                # kein Dialog mehr
    assert win.file_list.paths() == []


# ══ UI: fester Ausgabeordner auf einem getrennten NAS ════════════════════


def _hanging(monkeypatch, tmp_path, folder: str = "NAS"):
    """tmp_path/folder hängt wie ein getrenntes NAS bis zum Timeout (bis
    das Event gesetzt wird) — dann fehlt es. Merkt sich, ob im Tk-Thread
    gefragt wurde."""
    gate = threading.Event()
    real_exists = session.source_exists
    hanging = str(tmp_path / folder)
    calls: list[tuple[str, bool]] = []

    def exists(path):
        calls.append((path, threading.current_thread()
                      is threading.main_thread()))
        if path.startswith(hanging):
            gate.wait(5)
            return False
        return real_exists(path)

    monkeypatch.setattr(session, "source_exists", exists)
    return gate, calls


def _nas(tmp_path) -> str:
    return str(tmp_path / "NAS" / "Filme")


def _settle_output(win) -> None:
    _pump_until(win, lambda: not win._out_watch.checking)


def test_ui_programmstart_haengt_nicht_am_ausgabeordner(make_win, tmp_path,
                                                        monkeypatch):
    gate, calls = _hanging(monkeypatch, tmp_path)
    started = time.monotonic()
    win = make_win(output_dir=_nas(tmp_path))
    assert time.monotonic() - started < 1.0
    _wait_for(lambda: calls)
    assert win._out_watch.checking
    assert win.output_btn.cget("text") == "Ausgabe: Filme  ▾"   # noch offen
    gate.set()
    _settle_output(win)
    assert not any(main for _p, main in calls)       # nie im Tk-Thread
    # bleibt eingestellt — sichtbar als unerreichbar
    assert win.output_dir == win.cfg.output_dir == _nas(tmp_path)
    assert win.profile.output.directory == _nas(tmp_path)
    assert win.output_btn.cget("text") == (
        "Ausgabe: Filme  ⚠ nicht erreichbar  ▾")
    assert "nicht erreichbar" in win._output_tip.text
    assert _log_text(win).count(f"Ausgabeordner „{_nas(tmp_path)}“ ist nicht "
                                f"erreichbar") == 1
    # im Leerzustand ist das Protokoll unsichtbar — der Hinweis steht dort
    assert _shown(win.empty_notice)
    win._safe_save()
    import json
    saved = json.loads((tmp_path / "config.json").read_text("utf-8"))
    assert saved["output_dir"] == _nas(tmp_path)


def _unreachable_win(make_win, tmp_path):
    win = make_win(output_dir=_nas(tmp_path))
    _settle_output(win)
    assert win._out_watch.unreachable
    return win


def test_ui_start_verweigert_ohne_zugriff_im_tk_thread(make_win, tmp_path,
                                                       monkeypatch):
    win = _unreachable_win(make_win, tmp_path)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    assert win.plans[path].output_path == str(Path(_nas(tmp_path))
                                              / "a_remux.mkv")
    assert win.warn_label.cget("text").startswith(
        "⚠ Ausgabeordner nicht erreichbar")
    _tools_ok(win)
    _gate, calls = _hanging(monkeypatch, tmp_path)
    win._start()
    ((kind, title, message),) = win.messages
    assert (kind, title) == ("error", "Ausgabeordner nicht erreichbar")
    assert message == (f"Ausgabeordner „{_nas(tmp_path)}“ ist nicht "
                       f"erreichbar — Laufwerk verbinden oder anderen "
                       f"Ordner wählen.")
    assert win.runs == [] and win._worker is None and not win._starting
    # frische Prüfung im Hintergrund angestoßen — der Tk-Thread fragt nie
    assert win._out_watch.checking
    _wait_for(lambda: calls)
    assert not any(main for _p, main in calls)
    _gate.set()
    _settle_output(win)
    assert win.output_dir == _nas(tmp_path)          # nichts zurückgesetzt


def test_ui_ausgabeordner_wieder_da_start_geht_wieder(make_win, tmp_path):
    win = _unreachable_win(make_win, tmp_path)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    _tools_ok(win)
    assert win._watch_after is not None               # Takt prüft weiter
    menu = _menu(win, path)
    assert menu["Ausgabeordner öffnen"][1] == "disabled"
    Path(_nas(tmp_path)).mkdir(parents=True)          # NAS wieder da
    win._on_focus_in(SimpleNamespace(widget=win.winfo_toplevel()))
    _settle_output(win)
    assert not win._out_watch.unreachable
    assert win.output_btn.cget("text") == "Ausgabe: Filme  ▾"
    assert f"Ausgabeordner „{_nas(tmp_path)}“ ist wieder erreichbar." \
        in _log_text(win)
    assert "nicht erreichbar" not in win.warn_label.cget("text")
    assert _menu(win, path)["Ausgabeordner öffnen"][1] == "normal"
    _run_start(win)
    (run,) = win.runs
    assert run[0].output_path == str(Path(_nas(tmp_path)) / "a_remux.mkv")


def test_ui_takt_prueft_den_ausgabeordner_nur_solange_er_fehlt(
        make_win, tmp_path):
    win = _unreachable_win(make_win, tmp_path)
    assert win._watch_after is not None
    Path(_nas(tmp_path)).mkdir(parents=True)
    win._on_source_timer()                            # Takt läuft ab
    assert win._out_watch.checking
    _settle_output(win)
    assert not win._out_watch.unreachable
    assert win._watch_after is None                   # und endet


def test_ui_leerzustand_hinweis_verschwindet_wenn_erreichbar(make_win,
                                                            tmp_path):
    win = _unreachable_win(make_win, tmp_path)
    assert "nicht erreichbar" in win.empty_notice.cget("text")
    (tmp_path / "NAS").mkdir()                   # Laufwerk da, Ordner nicht
    win._check_sources()
    _settle_output(win)
    assert not _shown(win.empty_notice)
    assert ("ist wieder erreichbar — der Ordner selbst fehlt, Spurwerk legt "
            "ihn beim Start an.") in _log_text(win)


def test_ui_anderer_ordner_oder_quellordner_hebt_sofort_auf(make_win,
                                                           tmp_path):
    win = _unreachable_win(make_win, tmp_path)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    _tools_ok(win)
    win._set_output_dir("")                           # „Quellordner“
    assert not win._out_watch.unreachable
    assert win.output_btn.cget("text") == "Ausgabe: Quellordner  ▾"
    assert "nicht erreichbar" not in win._output_tip.text
    _run_start(win)
    assert len(win.runs) == 1

    win2 = _unreachable_win(make_win, tmp_path)
    other = tmp_path / "anders"
    other.mkdir()
    win2._set_output_dir(str(other))                  # im Dialog gewählt
    assert not win2._out_watch.unreachable
    assert win2.output_btn.cget("text") == "Ausgabe: anders  ▾"


def test_ui_manuelle_ausgabe_anderswo_startet_trotzdem(make_win, tmp_path):
    win = _unreachable_win(make_win, tmp_path)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    plan = win.plans[path]
    plan.output_manual = True
    plan.output_path = str(tmp_path / "lokal" / "a.mkv")
    _tools_ok(win)
    _run_start(win)
    assert win.messages == [] and len(win.runs) == 1


def test_ui_geloeschter_ordner_auf_vorhandenem_laufwerk_bleibt(make_win,
                                                              tmp_path):
    folder = str(tmp_path / "Ausgabe")               # tmp_path ist da
    win = make_win(output_dir=folder)
    _settle_output(win)
    assert win.output_dir == win.cfg.output_dir == folder
    assert not win._out_watch.unreachable
    assert win.output_btn.cget("text") == "Ausgabe: Ausgabe  ▾"
    assert f"Ausgabeordner „{folder}“ existiert nicht mehr — Spurwerk legt " \
           f"ihn beim Start wieder an." in _log_text(win)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    _tools_ok(win)
    _run_start(win)
    (run,) = win.runs
    assert run[0].output_path == str(Path(folder) / "a_remux.mkv")


def test_ui_erreichbarer_ordner_wie_bisher(make_win, tmp_path):
    folder = tmp_path / "Ausgabe"
    folder.mkdir()
    win = make_win(output_dir=str(folder))
    _settle_output(win)
    assert win.output_btn.cget("text") == "Ausgabe: Ausgabe  ▾"
    assert "Ausgabeordner" not in _log_text(win)
    assert win._watch_after is None


def test_ui_start_prueft_frisch_im_hintergrund(make_win, tmp_path,
                                               monkeypatch):
    # letzter Stand „erreichbar“, inzwischen hängt das NAS: Start friert
    # das Fenster nicht ein, sondern verweigert nach der Prüfung
    Path(_nas(tmp_path)).mkdir(parents=True)
    win = make_win(output_dir=_nas(tmp_path))
    _settle_output(win)
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    _tools_ok(win)
    gate, calls = _hanging(monkeypatch, tmp_path)
    started = time.monotonic()
    win._start()
    assert time.monotonic() - started < 1.0
    assert win._starting
    assert win.start_btn.cget("text") == (
        "▶  Start (F5) — Ausgabe wird geprüft …")
    assert str(win.start_btn.cget("state")) == "disabled"
    win._start()                                      # F5 nochmal: nichts
    gate.set()
    _pump_until(win, lambda: not win._starting)
    assert not any(main for _p, main in calls)
    assert win.messages[-1][1] == "Ausgabeordner nicht erreichbar"
    assert win.runs == [] and win._out_watch.unreachable
    assert "⚠ nicht erreichbar" in win.output_btn.cget("text")


def test_ui_ueberschreib_frage_kommt_weiter(win, tmp_path):
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    Path(win.plans[path].output_path).write_bytes(b"alt")
    _tools_ok(win)
    win.messagebox.answer = "Nein"
    _run_start(win)
    ((kind, title, message),) = win.messages
    assert (kind, title) == ("yesno", "Ausgabe vorhanden")
    assert message.startswith("1 Ausgabedatei existiert bereits.")
    assert win.runs == [] and not win._running
    assert str(win.start_btn.cget("state")) == "normal"
    win.messagebox.answer = "Ja"
    _run_start(win)
    assert len(win.runs) == 1


def test_ui_gescheiterte_pruefung_startet_nichts(win, tmp_path, monkeypatch):
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    _tools_ok(win)

    def broken(_path):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(session, "source_exists", broken)
    _run_start(win)
    assert win.runs == [] and not win._running      # nie ungefragt
    assert "ließen sich vor dem Start nicht prüfen" in _log_text(win)
    assert str(win.start_btn.cget("state")) == "normal"


def test_ui_start_waehrend_der_pruefung_geaendert_prueft_neu(win, tmp_path):
    pa, pb = _add(win, tmp_path / "a.mkv", tmp_path / "b.mkv")
    _scanned(win, pa)
    _tools_ok(win)
    win._start()
    _scanned(win, pb)                          # kommt in der Zwischenzeit
    _run_start(win)
    (run,) = win.runs
    assert sorted(p.media.path for p in run) == sorted([pa, pb])
