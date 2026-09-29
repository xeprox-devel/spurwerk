"""Jobs auf nicht verbundenen Laufwerken (USB/NAS): sichtbar in der
Warteschlange, automatisch zurück, sobald das Laufwerk wieder da ist.

Die Logik (core/session.py) läuft überall. Die UI-Tests brauchen
ttkbootstrap und ein Tk-Display; sie nutzen die Fixtures aus
test_befunde_hauptfenster.py (config.json IMMER in tmp_path, keine echten
Scans/Werkzeuge). Dort gilt jeder Ordner direkt unter tmp_path als eigenes
Laufwerk: tmp_path/"E_weg"/"film.mkv" liegt auf einem nicht verbundenen,
bis der Ordner angelegt wird; eine fehlende Datei direkt unter tmp_path
liegt auf einem verbundenen („Datei fehlt“). Echte Laufwerksbuchstaben
spielen keine Rolle.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import session
from core.model import Action
from core.planner import build_plan
from core.session import SourceWatch
from tests import test_befunde_hauptfenster as hauptfenster
from tests.helpers import film_std, profile_de
from tests.test_befunde_hauptfenster import (
    REMUX, _add, _log_text, _pump_sources, _restore, _run_start,
    _saved_session, _scanned, _shown, _tools_ok, _wait_for, builtin, film_at)

# dieselben Fixtures wie dort: config.json in tmp_path, Scans ersetzt
tk_root = hauptfenster.tk_root
make_win = hauptfenster.make_win
win = hauptfenster.win

# ══ Logik ohne Tk ════════════════════════════════════════════════════════


W = SourceWatch


def test_watch_startpruefung_befunde():
    watch = SourceWatch()
    for path in "ABC":
        watch.watch(path)
    assert watch.state("A") == W.CHECKING
    assert watch.waiting() == []          # ungeprüft wartet noch nicht
    assert watch.counts() == {W.CHECKING: 3}
    assert watch.begin_check() == ["A", "B", "C"]
    assert watch.result("A", W.REACHABLE) == W.FOUND
    assert watch.result("B", W.NO_DRIVE) == W.NO_DRIVE
    assert watch.result("C", W.NO_FILE) == W.NO_FILE
    # erstmals fehlend — für die Meldung nach dem Start
    assert watch.end_check() == {W.NO_DRIVE: 1, W.NO_FILE: 1}
    assert "A" not in watch and watch.waiting() == ["B", "C"]
    assert watch.counts() == {W.NO_DRIVE: 1, W.NO_FILE: 1}


def test_watch_laufwerk_wieder_da_oder_weiter_weg():
    watch = SourceWatch()
    watch.watch("B")
    watch.begin_check()
    watch.result("B", W.NO_DRIVE)
    watch.end_check()
    watch.begin_check()
    assert watch.result("B", W.NO_DRIVE) is None      # fehlt weiter
    assert watch.result("B", W.NO_FILE) == W.NO_FILE  # Laufwerk da, Datei nicht
    assert watch.result("B", W.NO_FILE) is None
    assert watch.result("B", W.REACHABLE) == W.BACK
    assert len(watch) == 0
    assert watch.result("B", W.REACHABLE) is None     # schon eingelesen
    assert watch.end_check() == {}   # kein Erstbefund in späteren Prüfungen


def test_watch_eine_pruefung_zur_zeit_und_keine_ohne_zeilen():
    watch = SourceWatch()
    assert watch.begin_check() == [] and not watch.checking
    watch.watch("A")
    assert watch.begin_check() == ["A"]
    assert watch.begin_check() == []              # läuft schon
    watch.clear()                                 # „Leeren“ während Prüfung
    assert watch.checking                         # Abschluss kommt noch
    assert watch.result("A", W.REACHABLE) is None  # entfernte Zeile: nichts
    assert watch.end_check() == {}
    assert watch.begin_check() == [] and not watch.checking


def test_watch_entfernte_zeile_wird_ignoriert():
    watch = SourceWatch()
    watch.watch("A")
    watch.watch("B")
    watch.begin_check()
    watch.result("B", W.NO_DRIVE)
    watch.discard("A")
    watch.discard("B")                            # vor dem Abschluss entfernt
    assert watch.result("A", W.REACHABLE) is None and "A" not in watch
    assert watch.end_check() == {} and watch.counts() == {}


def test_befund_laufwerk_fehlt_oder_nur_die_datei(monkeypatch):
    present = {"C:/", "C:/da.mkv", "D:/"}
    asked: list[str] = []

    def exists(path):
        asked.append(path)
        return path in present

    monkeypatch.setattr(session, "source_exists", exists)
    monkeypatch.setattr(session, "drive_root", lambda p: p[:2] + "/")
    found = list(session.probe_sources(
        ["C:/da.mkv", "C:/weg.mkv", "E:/a.mkv", "E:/b.mkv", "D:/x.mkv"]))
    assert found == [("C:/da.mkv", W.REACHABLE), ("C:/weg.mkv", W.NO_FILE),
                     ("E:/a.mkv", W.NO_DRIVE), ("E:/b.mkv", W.NO_DRIVE),
                     ("D:/x.mkv", W.NO_FILE)]
    # C: ist durch da.mkv schon als erreichbar bekannt; das fehlende E:
    # wird einmal gefragt — b.mkv wartet nicht noch einmal darauf
    assert asked == ["C:/da.mkv", "C:/weg.mkv", "E:/a.mkv", "E:/",
                     "D:/x.mkv", "D:/"]


def test_befund_vorhandene_datei_ist_immer_erreichbar(monkeypatch):
    # auch wenn die Wurzel nicht abfragbar wäre — die Datei zählt
    monkeypatch.setattr(session, "source_exists", lambda p: p == "E:/a.mkv")
    monkeypatch.setattr(session, "drive_root", lambda p: p[:2] + "/")
    assert list(session.probe_sources(["E:/a.mkv"])) == [
        ("E:/a.mkv", W.REACHABLE)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Pfade")
def test_laufwerkswurzel():
    assert session.drive_root("E:\\usb\\a.mkv") == "E:\\"
    assert session.drive_root("e:/usb/b.mkv") == "e:\\"
    assert session.drive_root("\\\\nas\\filme\\c.mkv") == "\\\\nas\\filme\\"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Pfade")
def test_pruefung_je_laufwerk_gruppiert():
    paths = ["E:\\usb\\a.mkv", "C:\\filme\\x.mkv", "e:/usb/b.mkv",
             "\\\\nas\\filme\\c.mkv", "\\\\NAS\\Filme\\d.mkv"]
    assert session.by_drive(paths) == [
        ["E:\\usb\\a.mkv", "e:/usb/b.mkv"], ["C:\\filme\\x.mkv"],
        ["\\\\nas\\filme\\c.mkv", "\\\\NAS\\Filme\\d.mkv"]]


def test_quelle_erreichbar(tmp_path):
    present = tmp_path / "da.mkv"
    present.write_bytes(b"")
    assert session.source_exists(str(present))
    assert not session.source_exists(str(tmp_path / "E_weg" / "film.mkv"))
    assert not session.source_exists("kaputt\0.mkv")


def test_sitzung_haelt_reihenfolge_und_wartende_jobs_unveraendert():
    ready = build_plan(film_std(), profile_de())          # C:/filme/test.mkv
    waiting = {"path": "E:/usb/a.mkv", "profile_name": "P",
               "overrides": {"1": "drop"}, "output_manual": True}
    plans = {"E:/usb/a.mkv": None, "C:/filme/test.mkv": ready,
             "E:/usb/c.mkv": None}
    jobs = session.session_jobs(plans, {"E:/usb/a.mkv": waiting})
    assert [j["path"] for j in jobs] == [
        "E:/usb/a.mkv", "C:/filme/test.mkv", "E:/usb/c.mkv"]
    assert jobs[0] is waiting


# ══ UI ═══════════════════════════════════════════════════════════════════


def _job(path: str, **extra) -> dict:
    """Voll konfigurierter Job der letzten Sitzung (Profil „Nur remuxen“,
    Spur 1 manuell raus)."""
    job = session.serialize_plan(build_plan(film_at(path), builtin(REMUX)))
    job["overrides"] = {"1": "drop"}
    job.update(extra)
    return job


def _row(win, path: str) -> tuple[str, str, tuple]:
    tree = win.file_list.tree
    return (tree.set(path, "plan"), tree.set(path, "status"),
            tuple(tree.item(path, "tags")))


def _pump_until(win, cond, timeout: float = 3.0) -> None:
    """Worker-Meldungen abarbeiten, bis `cond()` gilt."""
    import queue
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "Zeitüberschreitung"
        try:
            win._handle_message(win.ui_q.get(timeout=0.02))
        except queue.Empty:
            pass


def _gone(tmp_path: Path, name: str = "film.mkv") -> str:
    """Pfad auf einem „nicht verbundenen Laufwerk“."""
    return str(tmp_path / "E_weg" / name)


def _here(tmp_path: Path, name: str) -> str:
    src = tmp_path / name
    src.write_bytes(b"")
    return str(src.resolve())


def _menu(win, path: str) -> dict[str, tuple[int, str]]:
    menu = win._file_menu(path)
    entries = {}
    for i in range(menu.index("end") + 1):
        if menu.type(i) == "command":
            entries[menu.entrycget(i, "label")] = (
                i, str(menu.entrycget(i, "state")))
    entries["_menu"] = menu
    return entries


# 1 · sichtbar ─────────────────────────────────────────────────────────────


def test_ui_wartende_zeile_steht_sichtbar_in_der_warteschlange(win, tmp_path):
    gone = _gone(tmp_path)
    here = _here(tmp_path, "da.mkv")
    job = _job(gone)
    win.cfg.session = [job, {"path": here}]
    win._restore_session()
    # sofort in der Liste, in Sitzungs-Reihenfolge — geprüft wird danach
    assert win.file_list.paths() == [gone, here]
    assert _row(win, gone)[1] == "wird geprüft"
    _pump_sources(win)
    assert _row(win, gone) == (
        "wartet auf das Laufwerk · Einstellungen gespeichert",
        "Laufwerk fehlt", ("warn",))
    assert _row(win, here)[1] == "wird gescannt"
    _wait_for(lambda: win.scans == [here])
    assert win._pending_restore[gone] is job          # voller Job bleibt
    assert win.plans[gone] is None
    assert "1 Datei der letzten Sitzung wartet auf ihr Laufwerk" \
        in _log_text(win)
    assert "2 Jobs aus der letzten Sitzung wiederhergestellt" \
        in _log_text(win)


# 2 · automatisch zurück ───────────────────────────────────────────────────


def test_ui_pruefung_laeuft_im_hintergrund_und_nie_doppelt(win, tmp_path,
                                                        monkeypatch):
    gone = _gone(tmp_path)
    gate = threading.Event()
    calls: list[tuple[str, bool]] = []

    def slow_exists(path):   # getrenntes NAS: hängt, bis „Timeout“
        calls.append((path, threading.current_thread()
                      is threading.main_thread()))
        gate.wait(5)
        return False

    monkeypatch.setattr(session, "source_exists", slow_exists)
    win.cfg.session = [{"path": gone}]
    started = time.monotonic()
    win._restore_session()                    # blockiert den Tk-Thread nicht
    assert time.monotonic() - started < 1.0
    _wait_for(lambda: len(calls) == 1)
    assert win._watch.checking
    win._check_sources()                      # Takt, Fokus, Menü: keine
    win._on_focus_in(SimpleNamespace(widget=win.winfo_toplevel()))
    time.sleep(0.05)                          # zweite Prüfung daneben
    assert len(calls) == 1
    gate.set()
    _pump_sources(win)
    # Datei, dann ihr Laufwerk — nie im Tk-Thread
    assert calls == [(gone, False), (str(tmp_path / "E_weg"), False)]
    assert _row(win, gone)[1] == "Laufwerk fehlt"


def test_ui_laufwerk_wieder_da_liest_ueber_die_wiederherstellung_ein(
        win, tmp_path):
    gone = _gone(tmp_path)
    out = str(tmp_path / "aus" / "Mein Film.mkv")
    job = _job(gone, output_manual=True, output_path=out)
    win.cfg.session = [job]
    _restore(win)
    assert win.scans == []

    Path(gone).parent.mkdir()                 # Laufwerk wieder verbunden
    Path(gone).write_bytes(b"")
    win._check_sources()
    _pump_sources(win)
    assert "Laufwerk wieder da: film.mkv wird eingelesen" in _log_text(win)
    _wait_for(lambda: win.scans == [gone])
    assert gone not in win._watch
    assert _row(win, gone)[1] == "wird gescannt"
    _scanned(win, gone)
    plan = win.plans[gone]
    assert plan.profile_name == REMUX                 # Profil DES Jobs
    assert plan.decisions[1].action is Action.DROP    # manuelle Änderung
    assert plan.output_manual and plan.output_path == out
    assert gone not in win._pending_restore
    assert win._watch_after is None                   # nichts wartet mehr


def test_ui_wieder_da_aber_scan_scheitert_job_bleibt(win, tmp_path):
    gone = _gone(tmp_path)
    job = _job(gone)
    win.cfg.session = [job]
    _restore(win)
    Path(gone).parent.mkdir()
    Path(gone).write_bytes(b"")
    win._check_sources()
    _pump_sources(win)
    win._handle_message(("SCAN_FAILED", gone, "kein MKV"))
    win._safe_save()
    assert _saved_session(tmp_path) == [job]
    assert _row(win, gone)[1] == "Scan-Fehler"


def test_ui_takt_nur_solange_zeilen_warten(win, tmp_path, monkeypatch):
    gone = _gone(tmp_path)
    win.cfg.session = [{"path": gone}]
    _restore(win)
    assert win._watch_after is not None               # nächste in 5 s
    win.file_list.select(gone)
    win._remove_selected()
    calls = []
    monkeypatch.setattr(session, "source_exists",
                        lambda p: calls.append(p) or False)
    win._on_source_timer()                            # Takt läuft ab
    assert not win._watch.checking and calls == []
    assert win._watch_after is None                   # und endet


def test_ui_keine_pruefung_ohne_wartende_zeilen(win, tmp_path, monkeypatch):
    here = _here(tmp_path, "da.mkv")
    win.cfg.session = [{"path": here}]
    _restore(win)
    assert win._watch_after is None
    calls = []
    monkeypatch.setattr(session, "source_exists",
                        lambda p: calls.append(p) or True)
    win._check_sources()
    win._on_focus_in(SimpleNamespace(widget=win.winfo_toplevel()))
    assert not win._watch.checking and calls == []


def test_ui_fokus_aufs_fenster_prueft_sofort(win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [{"path": gone}]
    _restore(win)
    timer = win._watch_after
    # Fokuswechsel innerhalb des Fensters zählt nicht
    win._on_focus_in(SimpleNamespace(widget=win.file_list.tree))
    assert not win._watch.checking and win._watch_after == timer
    Path(gone).parent.mkdir()
    Path(gone).write_bytes(b"")
    win._on_focus_in(SimpleNamespace(widget=win.winfo_toplevel()))
    assert win._watch.checking
    _pump_sources(win)
    _wait_for(lambda: win.scans == [gone])


def test_ui_haengendes_laufwerk_haelt_andere_nicht_auf(win, tmp_path,
                                                      monkeypatch):
    # zwei „Laufwerke“: NAS (hängt) und USB (da)
    nas = str(tmp_path / "NAS" / "nas.mkv")
    (tmp_path / "USB").mkdir()
    usb = _here(tmp_path, "USB/usb.mkv")
    gate = threading.Event()
    real_exists = session.source_exists

    def exists(path):
        if path.startswith(str(tmp_path / "NAS")):
            gate.wait(5)
            return False
        return real_exists(path)

    monkeypatch.setattr(session, "source_exists", exists)
    win.cfg.session = [{"path": nas}, {"path": usb}]
    win._restore_session()
    _pump_until(win, lambda: win.scans == [usb])
    assert win._watch.checking and _row(win, nas)[1] == "wird geprüft"
    gate.set()
    _pump_sources(win)
    assert _row(win, nas)[1] == "Laufwerk fehlt"


def test_ui_entfernte_zeile_waehrend_pruefung_bleibt_weg(win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [{"path": gone}]
    _restore(win)
    win.file_list.select(gone)
    win._remove_selected()
    win._handle_message(("SOURCE", gone, W.REACHABLE))  # späte Meldung
    assert win.scans == [] and gone not in win.plans
    assert not win.file_list.contains(gone)


# Laufwerk da, Datei nicht: kein falsches Versprechen ─────────────────────


def test_ui_datei_fehlt_bei_verbundenem_laufwerk(win, tmp_path):
    # tmp_path ist das (verbundene) Laufwerk — die Datei wurde umbenannt
    gone = str(tmp_path / "umbenannt.mkv")
    job = _job(gone)
    win.cfg.session = [job]
    _restore(win)
    assert _row(win, gone) == (
        "Datei nicht gefunden · Einstellungen gespeichert", "Datei fehlt",
        ("warn",))
    log = _log_text(win)
    assert ("1 Datei der letzten Sitzung nicht gefunden, obwohl das "
            "Laufwerk da ist (verschoben oder gelöscht?)") in log
    assert "wartet auf ihr Laufwerk" not in log
    win.file_list.select(gone)
    win._on_file_selected(gone)
    note = win.warn_label.cget("text")
    assert note.startswith("⚠ Datei nicht gefunden, das Laufwerk ist da — "
                           "verschoben, umbenannt oder gelöscht?")
    assert "Laufwerk nicht verbunden" not in note
    assert not _shown(win.stereo_panel)
    win._safe_save()
    assert _saved_session(tmp_path) == [job]          # bleibt gespeichert
    assert win._watch_after is not None               # wird weiter geprüft

    Path(gone).write_bytes(b"")                       # wieder am alten Ort
    win._check_sources()
    _pump_sources(win)
    assert "Datei wieder gefunden: umbenannt.mkv wird eingelesen" \
        in _log_text(win)
    _wait_for(lambda: win.scans == [gone])
    _scanned(win, gone)
    assert win.plans[gone].profile_name == REMUX


def test_ui_laufwerk_wieder_da_aber_datei_nicht(win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [{"path": gone}]
    _restore(win)
    assert _row(win, gone)[1] == "Laufwerk fehlt"
    Path(gone).parent.mkdir()           # Laufwerk da, Datei nicht darauf
    win._check_sources()
    _pump_sources(win)
    assert _row(win, gone)[1] == "Datei fehlt"
    assert ("Laufwerk wieder da, film.mkv dort aber nicht gefunden — "
            "verschoben oder gelöscht?") in _log_text(win)
    assert win.scans == [] and gone in win._watch
    Path(gone).parent.rmdir()           # Laufwerk wieder abgezogen
    win._check_sources()
    _pump_sources(win)
    assert _row(win, gone)[1] == "Laufwerk fehlt"


# 3 · Start ────────────────────────────────────────────────────────────────


def test_ui_start_uebergeht_wartende_zeilen_mit_hinweis(win, tmp_path):
    gone = _gone(tmp_path)
    here = _here(tmp_path, "da.mkv")
    win.cfg.session = [{"path": gone}, {"path": here}]
    _restore(win)
    _scanned(win, here)
    _tools_ok(win)
    text = win.start_btn.cget("text")
    assert "— 1 Datei ·" in text                      # nur die bereite
    _run_start(win)
    (run,) = win.runs
    assert [p.media.path for p in run] == [here]
    assert ("1 Datei übersprungen — Laufwerk nicht verbunden; sie bleibt "
            "in der Warteschlange") in _log_text(win)
    assert _row(win, gone)[1] == "Laufwerk fehlt"     # unverändert
    assert win.plans[gone] is None


def _blocked_exists(monkeypatch, tmp_path, folder: str) -> threading.Event:
    """„Laufwerk“ tmp_path/folder hängt (wie ein NAS bis zum Timeout), bis
    das zurückgegebene Event gesetzt wird — dann fehlt es. Alle anderen
    Pfade wie echt."""
    gate = threading.Event()
    real_exists = session.source_exists
    hanging = str(tmp_path / folder)

    def exists(path):
        if path.startswith(hanging):
            gate.wait(5)
            return False
        return real_exists(path)

    monkeypatch.setattr(session, "source_exists", exists)
    return gate


def test_ui_start_waehrend_der_startpruefung_nennt_die_zeile(win, tmp_path,
                                                            monkeypatch):
    nas = str(tmp_path / "NAS" / "film.mkv")
    here = _here(tmp_path, "da.mkv")
    gate = _blocked_exists(monkeypatch, tmp_path, "NAS")
    win.cfg.session = [{"path": nas}, {"path": here}]
    win._restore_session()
    _pump_until(win, lambda: win.scans == [here])
    _scanned(win, here)
    assert _row(win, nas)[1] == "wird geprüft"
    _tools_ok(win)
    _run_start(win)
    (run,) = win.runs
    assert [p.media.path for p in run] == [here]
    assert ("1 Datei übersprungen — Quelle wird noch geprüft; sie bleibt in "
            "der Warteschlange") in _log_text(win)
    gate.set()
    _pump_sources(win)
    assert _row(win, nas)[1] == "Laufwerk fehlt"


def test_ui_leeren_waehrend_der_startpruefung_fragt(win, tmp_path,
                                                   monkeypatch):
    nas = str(tmp_path / "NAS" / "film.mkv")
    gate = _blocked_exists(monkeypatch, tmp_path, "NAS")
    job = _job(nas)
    win.cfg.session = [job]
    win._restore_session()
    win._safe_save()
    assert _row(win, nas)[1] == "wird geprüft"
    win.messagebox.answer = "Nein"
    win._clear_files()
    ((kind, title, message),) = win.messages
    assert (kind, title) == ("yesno", "Liste leeren")
    assert message.startswith("1 Datei wird noch geprüft — ihre gespeicherten "
                              "Einstellungen gehen verloren.")
    assert win.file_list.paths() == [nas] and nas in win._watch
    assert _saved_session(tmp_path) == [job]

    win.messagebox.answer = "Ja"
    win._clear_files()
    assert win.file_list.paths() == [] and _saved_session(tmp_path) == []
    gate.set()
    _pump_sources(win)                        # später Befund: nichts mehr
    assert win.file_list.paths() == [] and win.scans == []


def test_ui_gemischte_zeilen_rueckfrage_und_startprotokoll(win, tmp_path,
                                                          monkeypatch):
    usb = _gone(tmp_path, "usb.mkv")                  # Laufwerk fehlt
    moved = str(tmp_path / "verschoben.mkv")          # Datei fehlt
    nas = str(tmp_path / "NAS" / "nas.mkv")           # hängt noch
    here = _here(tmp_path, "da.mkv")
    gate = _blocked_exists(monkeypatch, tmp_path, "NAS")
    win.cfg.session = [{"path": p} for p in (usb, moved, nas, here)]
    win._restore_session()
    _pump_until(win, lambda: win.scans == [here]
                and _row(win, usb)[1] == "Laufwerk fehlt"
                and _row(win, moved)[1] == "Datei fehlt")
    assert _row(win, nas)[1] == "wird geprüft"
    _scanned(win, here)

    win.messagebox.answer = "Nein"
    win._clear_files()
    ((_kind, _title, message),) = win.messages
    assert message.startswith(
        "1 Datei wartet auf ein nicht verbundenes Laufwerk, 1 Datei wurde "
        "nicht gefunden und 1 Datei wird noch geprüft — ihre gespeicherten "
        "Einstellungen gehen verloren.")
    assert win.file_list.paths() == [usb, moved, nas, here]

    _tools_ok(win)
    _run_start(win)
    assert [p.media.path for p in win.runs[0]] == [here]
    assert ("3 Dateien übersprungen — Laufwerk nicht verbunden, Datei nicht "
            "gefunden oder Quelle wird noch geprüft; sie bleiben in der "
            "Warteschlange") in _log_text(win)
    gate.set()
    _pump_sources(win)


def test_ui_nur_wartende_zeilen_start_gesperrt(win, tmp_path):
    win.cfg.session = [{"path": _gone(tmp_path)}]
    _restore(win)
    assert str(win.start_btn.cget("state")) == "disabled"
    assert win.start_btn.cget("text") == "▶  Start (F5)"
    _tools_ok(win)
    win._start()
    assert win.runs == [] and win._worker is None


# 4 · nur ausdrücklich entfernen ───────────────────────────────────────────


def test_ui_entfernen_button_nimmt_wartende_zeile_heraus(win, tmp_path):
    gone = _gone(tmp_path)
    here = _here(tmp_path, "da.mkv")
    win.cfg.session = [{"path": gone}, {"path": here}]
    _restore(win)
    win.file_list.select(gone)
    (button,) = [b for b in win._lock_buttons
                 if str(b.cget("text")) == "− Entfernen"]
    button.invoke()
    assert win.file_list.paths() == [here] and gone not in win._watch
    assert [j["path"] for j in _saved_session(tmp_path)] == [here]
    # die Entf-Taste ruft dasselbe
    assert win.file_list.tree.bind("<Key-Delete>")


def test_ui_kontextmenue_einer_wartenden_zeile(win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [{"path": gone}]
    _restore(win)
    entries = _menu(win, gone)
    assert entries["Jetzt erneut prüfen"][1] == "normal"
    for label in ("Ausgabename/-ort ändern …", "Ausgabeordner öffnen",
                  "Quellordner öffnen"):
        assert entries[label][1] == "disabled"
    assert entries["Aus der Liste entfernen"][1] == "normal"

    entries["_menu"].invoke(entries["Jetzt erneut prüfen"][0])
    assert win._watch.checking
    busy = _menu(win, gone)                            # Prüfung läuft
    assert busy["Quelle wird gerade geprüft …"][1] == "disabled"
    _pump_sources(win)

    win.file_list.select(gone)
    menu = _menu(win, gone)
    menu["_menu"].invoke(menu["Aus der Liste entfernen"][0])
    assert win.file_list.paths() == [] and _saved_session(tmp_path) == []


def test_ui_kontextmenue_normaler_zeile_unveraendert(win, tmp_path):
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    entries = _menu(win, path)
    assert "Jetzt erneut prüfen" not in entries
    assert entries["Ausgabename/-ort ändern …"][1] == "normal"
    assert entries["Quellordner öffnen"][1] == "normal"


def test_ui_leeren_fragt_bei_wartenden_zeilen_nein_aendert_nichts(win,
                                                                 tmp_path):
    a, b = _gone(tmp_path, "a.mkv"), _gone(tmp_path, "b.mkv")
    here = _here(tmp_path, "da.mkv")
    jobs = [_job(a), {"path": here}, _job(b)]
    win.cfg.session = jobs
    _restore(win)
    _scanned(win, here)
    win._safe_save()
    before = _saved_session(tmp_path)
    win.messagebox.answer = "Nein"
    win._clear_files()
    ((kind, title, message),) = win.messages
    assert (kind, title) == ("yesno", "Liste leeren")
    assert message.startswith("2 Dateien warten auf ein nicht verbundenes "
                              "Laufwerk — ihre gespeicherten Einstellungen "
                              "gehen verloren.")
    assert "Trotzdem leeren?" in message
    assert win.file_list.paths() == [a, here, b]
    assert win._watch.waiting() == [a, b] and here in win.plans
    assert _saved_session(tmp_path) == before

    win.messagebox.answer = "Ja"
    win._clear_files()
    assert win.file_list.paths() == [] and not win.plans
    assert len(win._watch) == 0 and _saved_session(tmp_path) == []


def test_ui_leeren_ohne_wartende_zeilen_fragt_nicht(win, tmp_path):
    _add(win, tmp_path / "a.mkv")
    win._clear_files()
    assert win.messages == [] and not win.plans


# 5 · gespeichert bis entfernt, geleert oder eingelesen ───────────────────


def test_ui_wartende_jobs_bleiben_in_reihenfolge_gespeichert(win, tmp_path):
    a, c = _gone(tmp_path, "a.mkv"), _gone(tmp_path, "c.mkv")
    b = _here(tmp_path, "b.mkv")
    job_a, job_c = _job(a), _job(c, output_manual=True)
    win.cfg.session = [job_a, {"path": b}, job_c]
    _restore(win)
    _scanned(win, b)
    (d,) = _add(win, tmp_path / "d.mkv")               # neu → ans Ende
    win._safe_save()
    saved = _saved_session(tmp_path)
    assert [j["path"] for j in saved] == [a, b, c, d]
    assert saved[0] == job_a and saved[2] == job_c     # unverändert

    # Laufwerk von a wieder da → eingelesen → ab jetzt normal gespeichert
    Path(a).parent.mkdir()
    Path(a).write_bytes(b"")
    win._check_sources()
    _pump_sources(win)
    win._safe_save()
    assert _saved_session(tmp_path)[0] == job_a        # noch ungescannt
    _scanned(win, a)
    win._safe_save()
    saved = _saved_session(tmp_path)
    assert [j["path"] for j in saved] == [a, b, c, d]  # Platz bleibt
    assert saved[0] == session.serialize_plan(win.plans[a])
    assert saved[2] == job_c


# 6 · Auswahl ──────────────────────────────────────────────────────────────


def test_ui_auswahl_wartender_zeile_zeigt_hinweis_und_sperrt_panel(
        win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [_job(gone)]
    _restore(win)
    (other,) = _add(win, tmp_path / "anderer.mkv")
    _scanned(win, other)                               # wird markiert
    plan = win.plans[other]
    assert plan.stereo_sources() and _shown(win.stereo_panel)
    name_before = plan.stereo.track_name
    before = {tid: (d.action, d.origin) for tid, d in plan.decisions.items()}
    default_before = (plan.default_audio_source, plan.default_audio_is_stereo)

    win.file_list.select(gone)
    win._on_file_selected(gone)
    assert win.track_table.tree.get_children() == ()   # keine Spuren
    assert win.tracks_label.cget("text") == "SPUREN · film.mkv"
    assert win.warn_label.cget("text") == (
        "⚠ Laufwerk nicht verbunden — sobald es wieder da ist, auch unter "
        "einem anderen Buchstaben, liest Spurwerk die Datei automatisch "
        "ein; sonst Rechtsklick → „Datei neu zuordnen …“.")
    assert f"Profil „{REMUX}“" in win.preview_label.cget("text")
    assert not _shown(win.stereo_panel)
    # nichts landet versehentlich im Plan der zuvor markierten Datei
    assert win.stereo is not plan.stereo
    win.trackname_var.set("Nachtmodus")
    win._on_stereo_changed()
    win.stereo_default_var.set(not plan.default_audio_is_stereo)
    win._on_stereo_default_toggled()
    win.track_table.set_all(False)
    win._reset_selected_to_rule()
    assert plan.stereo.track_name == name_before
    assert {tid: (d.action, d.origin)
            for tid, d in plan.decisions.items()} == before
    assert (plan.default_audio_source,
            plan.default_audio_is_stereo) == default_before
    # der gespeicherte Job der wartenden Zeile bleibt ebenso unberührt
    assert win._pending_restore[gone] == _job(gone)


def test_ui_auswahl_wartender_zeile_zeigt_ihr_profil_gesperrt(win, tmp_path):
    from core.profiles import describe
    gone = _gone(tmp_path)
    win.cfg.session = [_job(gone)]                     # Profil „Nur remuxen“
    _restore(win)
    (other,) = _add(win, tmp_path / "anderer.mkv")
    _scanned(win, other)
    active = win.cfg.active_profile
    other_profile = win.plans[other].profile_name
    assert other_profile != REMUX

    def profile_buttons() -> set[str]:
        return {str(b.cget("state")) for b in win._profile_buttons}

    assert profile_buttons() == {"normal"}
    win._on_file_selected(gone)
    assert win.profile_cb.get() == REMUX
    assert str(win.profile_cb.cget("state")) == "disabled"
    assert win.rule_label.cget("text") == describe(builtin(REMUX))
    assert win.cfg.active_profile == active            # nur Anzeige
    # „Bearbeiten …“/„Auf alle Dateien“ gälten der Vorlage, nicht dem
    # angezeigten Profil — gesperrt wie die Box
    assert profile_buttons() == {"disabled"}
    win._set_running(True)
    win._set_running(False)                            # Lauf-Ende: bleibt zu
    assert str(win.profile_cb.cget("state")) == "disabled"
    assert profile_buttons() == {"disabled"}

    win._on_file_selected(other)
    assert win.profile_cb.get() == other_profile
    assert str(win.profile_cb.cget("state")) == "readonly"
    assert profile_buttons() == {"normal"}


def test_ui_auswahl_wartender_zeile_aendert_die_vorlage_nicht(win, tmp_path):
    gone = _gone(tmp_path)
    win.cfg.session = [_job(gone)]                     # Profil „Nur remuxen“
    _restore(win)
    template = win.profile.name
    assert template != REMUX
    win.file_list.select(gone)
    win._on_file_selected(gone)
    assert win.profile_cb.get() == REMUX               # Anzeige: Job-Profil
    assert win.profile.name == template                # Vorlage bleibt

    # neue Datei, während die wartende Zeile markiert ist: Vorlage
    (new,) = _add(win, tmp_path / "neu.mkv")
    _scanned(win, new)
    assert win.plans[new].profile_name == template
    assert win.selected == gone and win.profile_cb.get() == REMUX

    # Laufwerk wieder da, Zeile noch markiert: bis ihr Plan steht, zeigt
    # die Box wieder die Vorlage (entsperrt) — dann das Profil des Plans
    Path(gone).parent.mkdir()
    Path(gone).write_bytes(b"")
    win._check_sources()
    _pump_sources(win)
    assert win.profile_cb.get() == template
    assert str(win.profile_cb.cget("state")) == "readonly"
    assert {str(b.cget("state")) for b in win._profile_buttons} == {"normal"}
    _scanned(win, gone)
    assert win.profile_cb.get() == REMUX
    assert win.plans[gone].profile_name == REMUX


def test_ui_auswahl_waehrend_der_startpruefung(win, tmp_path, monkeypatch):
    gone = _gone(tmp_path)
    gate = threading.Event()
    monkeypatch.setattr(session, "source_exists",
                        lambda _p: gate.wait(5) and False)
    win.cfg.session = [{"path": gone}]
    win._restore_session()
    win._on_file_selected(gone)
    assert win.warn_label.cget("text") == "Quelle wird geprüft …"
    gate.set()
    _pump_sources(win)
    assert "Laufwerk nicht verbunden" in win.warn_label.cget("text")


# 7 · Aufgeräumt: kein Sonderhinweis mehr im Leerzustand ──────────────────


def test_ui_startwarnung_und_wartende_zeilen(make_win, tmp_path):
    win = make_win(load_notice="config.json war beschädigt.")
    assert _shown(win.empty_notice)                    # Leerzustand: sichtbar
    win.cfg.session = [{"path": _gone(tmp_path)}]
    _restore(win)
    # Arbeitsansicht mit der wartenden Zeile — die Warnung steht im
    # (aufgeklappten) Protokoll
    assert _shown(win.work) and not _shown(win.empty_notice)
    assert "config.json war beschädigt" in _log_text(win)
    assert win.log.expanded
