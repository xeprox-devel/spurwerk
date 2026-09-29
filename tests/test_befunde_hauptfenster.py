"""Befunde „Hauptfenster“: Sitzung wiederherstellen/speichern, Prüfungen vor
dem Start, Scan-Ablauf, Speicherfehler und die dunkle Titelleiste.

Die reine Logik (core/session.py) läuft überall. Die UI-Tests brauchen
ttkbootstrap und ein Tk-Display — im System-Python ohne ttkbootstrap werden
sie übersprungen. Sie biegen config.CONFIG_FILE/base_path IMMER auf tmp_path
um und starten weder Scans noch Werkzeuge (Worker ersetzt).
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

from core import session
from core.model import Action, FileStatus
from core.planner import build_plan
from core.profiles import builtin_profiles
from tests.helpers import film_std, media, profile_de, track

REMUX = "Nur remuxen — alles behalten"
DE_EN = "Deutsch + Englisch"
DE = "Deutsch bevorzugt"


def builtin(name: str):
    return next(p for p in builtin_profiles() if p.name == name)


def film_at(path: str):
    return dataclasses.replace(film_std(), path=path)


def actions(plan) -> dict:
    return {tid: dec.action for tid, dec in plan.decisions.items()}


# ══ 1 · Wiederherstellung mit dem Profil des Jobs ════════════════════════


def test_wiederherstellung_nutzt_regeln_des_job_profils():
    # Sitzung 1: Datei mit „Nur remuxen“ (alles behalten, nichts konvertiert)
    original = build_plan(film_std(), builtin(REMUX))
    job = session.serialize_plan(original)
    # Neustart — maßgeblich ist das Profil DES JOBS, nicht das aktive
    restored = session.restore_job_plan(film_std(), job,
                                        builtin(job["profile_name"]))
    assert restored.profile_name == REMUX
    assert actions(restored) == actions(original)
    assert not restored.stereo_sources()


def test_review_szenario_standard_auf_stereo_kopie_bleibt_gueltig():
    original = build_plan(film_std(), builtin(DE_EN))
    assert (original.default_audio_source,
            original.default_audio_is_stereo) == (1, True)
    job = session.serialize_plan(original)
    restored = session.restore_job_plan(film_std(), job, builtin(DE_EN))
    assert restored.decisions[1].action is Action.STEREO_ADD
    assert restored.decisions[3].action is Action.DROP   # Kommentar
    assert (restored.default_audio_source,
            restored.default_audio_is_stereo) == (1, True)


def test_geloeschtes_profil_beschriftung_folgt_dem_ersatzprofil():
    job = session.serialize_plan(build_plan(film_std(), profile_de()))
    fallback = builtin_profiles()[0]   # AppConfig.profile() für Unbekanntes
    restored = session.restore_job_plan(film_std(), job, fallback)
    assert restored.profile_name == fallback.name


def test_standard_auf_nicht_vorhandener_kopie_wird_verworfen():
    plan = build_plan(film_std(), builtin(REMUX))       # keine Konvertierung
    session.restore_plan(plan, {"default_audio_source": 1,
                                "default_audio_is_stereo": True})
    # nie eine Ausgabe ohne Standard-Audiospur → Regel-Vorgabe bleibt
    assert plan.default_audio_is_stereo is False
    assert plan.default_audio_source in plan.kept_ids("audio")


def test_standard_auf_entferntem_original_wird_verworfen():
    plan = build_plan(film_std(), profile_de())         # en (2) fällt weg
    session.restore_plan(plan, {"default_audio_source": 2,
                                "default_audio_is_stereo": False})
    assert (plan.default_audio_source, plan.default_audio_is_stereo) \
        == (1, True)


def test_gueltiger_gespeicherter_standard_bleibt():
    plan = build_plan(film_std(), builtin(REMUX))
    session.restore_plan(plan, {"default_audio_source": 2,
                                "default_audio_is_stereo": False})
    assert (plan.default_audio_source, plan.default_audio_is_stereo) \
        == (2, False)


def test_invariante_haelt_auch_nach_defektem_eintrag():
    plan = build_plan(film_std(), builtin(REMUX))
    plan.default_audio_source = 99                      # kaputter Zustand
    session.restore_plan(plan, {"overrides": {"x": "quatsch"}})
    assert plan.default_audio_source in plan.kept_ids("audio")


# ══ 2/3 · Sitzung speichern: ungescannte, fehlgeschlagene, unerreichbare ═


def test_sitzung_behaelt_ungescannte_und_fehlgeschlagene_jobs():
    done = build_plan(media(track(0, "video"),
                            track(1, "audio", "de", channels=2),
                            path="C:/f/fertig.mkv"), profile_de())
    done.status = FileStatus.DONE
    ready = build_plan(film_std(), profile_de())         # C:/filme/test.mkv
    pending = {"path": "C:/f/wartet.mkv", "profile_name": "P",
               "overrides": {"1": "drop"}}
    plans = {"C:/f/fertig.mkv": done, "C:/filme/test.mkv": ready,
             "C:/f/wartet.mkv": None, "C:/f/neu.mkv": None}
    jobs = session.session_jobs(plans, {"C:/f/wartet.mkv": pending})
    assert [j["path"] for j in jobs] == [
        "C:/filme/test.mkv", "C:/f/wartet.mkv", "C:/f/neu.mkv"]
    assert jobs[1] is pending            # Konfiguration unverändert weiter
    assert jobs[2] == {"path": "C:/f/neu.mkv"}


def test_wiederherstellbare_jobs_ohne_pfad_fallen_weg():
    # Ob die Quelle erreichbar ist, entscheidet erst die Hintergrund-
    # Prüfung — hier fällt nur Unbrauchbares weg, die Reihenfolge bleibt
    jobs = [{"path": "C:/da.mkv"}, {"path": "E:/usb/weg.mkv", "x": 1},
            {"path": ""}, {}, "kaputt", {"path": 7}]
    assert [job for _p, job in session.restorable_jobs(jobs)] == [
        {"path": "C:/da.mkv"}, {"path": "E:/usb/weg.mkv", "x": 1}]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Pfade")
def test_wiederherstellbare_jobs_einmal_unabhaengig_von_schreibweise():
    first = {"path": "E:/USB/Film.mkv", "profile_name": "P"}
    jobs = [first, {"path": "e:\\usb\\film.mkv"}, {"path": "C:/x/a.mkv"}]
    # der Pfad wird nur als Text normalisiert (kein Dateizugriff), der
    # gespeicherte Job bleibt unverändert
    assert session.restorable_jobs(jobs, listed=["c:\\X\\A.mkv"]) == [
        ("E:\\USB\\Film.mkv", first)]


# ══ 6 · Start verarbeitet keine erledigten Dateien ═══════════════════════


def test_start_verarbeitet_keine_erledigten_dateien():
    done = build_plan(film_std(), profile_de())
    done.status = FileStatus.DONE
    failed = build_plan(film_std(), profile_de())
    failed.status = FileStatus.ERROR
    assert session.runnable_plans([done, None, failed]) == [failed]


# ══ 8 · Saubere Namen im Quellordner ═════════════════════════════════════


def test_bereinigter_name_gleich_quelle_bekommt_das_suffix():
    assert session.distinct_output(
        "C:/filme/Inception.mkv", "C:/filme/Inception.mkv", "_remux") \
        == str(Path("C:/filme/Inception_remux.mkv"))


def test_bereinigter_name_anders_als_quelle_bleibt():
    assert session.distinct_output(
        "C:/filme/Inception (2010).mkv", "C:/filme/Inception.2010.mkv",
        "_remux") == "C:/filme/Inception (2010).mkv"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Pfade")
def test_bereinigter_name_gleich_quelle_auch_in_anderer_schreibweise():
    assert session.distinct_output(
        "C:/Filme/inception.mkv", "c:\\filme\\Inception.mkv", "_remux") \
        == str(Path("C:/Filme/inception_remux.mkv"))


# ══ 9 · Kollision mit der Quelldatei eines anderen Jobs ══════════════════


def _plan_at(src: str, out: str):
    plan = build_plan(film_at(src), profile_de())
    plan.output_path = out
    return plan


def test_ausgabe_gleich_quelle_eines_anderen_jobs():
    a = _plan_at("C:/x/Film.mkv", "C:/x/Film_remux.mkv")
    b = _plan_at("C:/x/Film_remux.mkv", "C:/x/Film_remux_remux.mkv")
    assert session.output_conflict(
        [a, b], ["C:/x/Film.mkv", "C:/x/Film_remux.mkv"]) \
        == (a, "C:/x/Film_remux.mkv", True)


def test_ausgabe_gleich_quelle_eines_noch_ungescannten_jobs():
    a = _plan_at("C:/x/Film.mkv", "C:/x/Film_remux.mkv")
    # B steht (noch ohne Plan) nur in der Liste
    assert session.output_conflict(
        [a], ["C:/x/Film.mkv", "C:/x/Film_remux.mkv"]) \
        == (a, "C:/x/Film_remux.mkv", True)


def test_eigene_quelle_als_ausgabe_meldet_weiter_der_runner():
    a = _plan_at("C:/x/Film.mkv", "C:/x/Film.mkv")
    assert session.output_conflict([a], ["C:/x/Film.mkv"]) is None


def test_zwei_jobs_mit_gleicher_ausgabe():
    a = _plan_at("C:/a/Film.mkv", "D:/out/Film.mkv")
    b = _plan_at("C:/b/Film.mkv", "D:/out/Film.mkv")
    assert session.output_conflict([a, b], [a.media.path, b.media.path]) \
        == (b, "C:/a/Film.mkv", False)


def test_keine_kollision():
    a = _plan_at("C:/a/Film.mkv", "C:/a/Film_remux.mkv")
    b = _plan_at("C:/b/Film.mkv", "C:/b/Film_remux.mkv")
    assert session.output_conflict([a, b], [a.media.path, b.media.path]) \
        is None


# ══ UI (ttkbootstrap + Tk-Display) ═══════════════════════════════════════


def _cancel_afters(root) -> None:
    # direkt über Tcl: after_cancel() löschte auch die Tcl-Befehle fremder
    # Widgets, deren destroy() dann scheitert
    for aid in root.tk.splitlist(root.tk.call("after", "info")):
        root.tk.call("after", "cancel", aid)


def _drain(q: queue.Queue) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def _wait_for(cond, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "Zeitüberschreitung"
        time.sleep(0.01)


def _log_text(win) -> str:
    return win.log.text.get("1.0", "end")


def _test_drive_root(base: Path, real):
    """Laufwerke unter tmp_path simulieren: Jeder Ordner direkt darunter
    gilt als eigenes Laufwerk — tmp_path/"E_weg"/"film.mkv" liegt auf einem
    nicht verbundenen, bis der Ordner angelegt wird. Dateien direkt unter
    tmp_path liegen auf einem verbundenen; alles andere wie echt."""
    bases = [base, base.resolve()]

    def drive_root(path: str) -> str:
        full = Path(os.path.abspath(path))
        for b in bases:
            if full.is_relative_to(b):
                parts = full.relative_to(b).parts
                return str(b / parts[0]) if len(parts) > 1 else str(b)
        return real(path)
    return drive_root


@pytest.fixture(scope="module")
def tk_root():
    ttk = pytest.importorskip("ttkbootstrap")
    import tkinter as tk
    try:
        root = ttk.Window(themename="darkly")
    except tk.TclError as exc:
        # kein Display — oder eine frühere Testdatei hat ein ttkbootstrap-
        # Fenster zerstört (Style-Singleton am toten Tk): dann einzeln laufen
        pytest.skip(f"Tk/ttkbootstrap nicht verfügbar: {exc}")
    from ui import theme
    theme.register(root.style)
    root.withdraw()
    yield root
    _cancel_afters(root)
    root.destroy()
    # ttkbootstrap hält seinen Style als Singleton am ersten Fenster — ohne
    # Zurücksetzen scheiterte das Fenster der nächsten Testdatei
    from ttkbootstrap.style import Style
    Style.instance = None


@pytest.fixture
def make_win(tk_root, tmp_path, monkeypatch):
    import config as appconfig
    from core.runner import JobRunner
    from ui import main_window as mw

    # Nie die echte config.json des Nutzers anfassen
    monkeypatch.setattr(appconfig, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(appconfig, "LEGACY_INI", tmp_path / "config.ini")
    monkeypatch.setattr(appconfig, "base_path", lambda: tmp_path)
    # „Laufwerke“ sind Ordner unter tmp_path — nie echte Laufwerksbuchstaben;
    # auch die Suche unter anderem Buchstaben sieht keine (Tests stellen
    # simulierte ein, siehe test_laufwerk_ausgabe.py)
    monkeypatch.setattr(session, "drive_root",
                        _test_drive_root(tmp_path, session.drive_root))
    monkeypatch.setattr(session, "present_drives", lambda: [])

    real_scan_worker = mw.MainWindow._scan_worker
    started: list[str] = []
    monkeypatch.setattr(mw.MainWindow, "_probe_tools", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_scan_worker",
                        lambda self, path: started.append(path))

    class FakeMessagebox:
        calls: list = []
        answer = "Ja"                    # Antwort auf yesno (Test stellt um)

        @classmethod
        def show_error(cls, message, title=None, **_kw):
            cls.calls.append(("error", title, message))

        @classmethod
        def yesno(cls, message, title=None, **_kw):
            cls.calls.append(("yesno", title, message))
            return cls.answer

    class FakeToast:
        def __init__(self, **_kw):
            pass

        def show_toast(self):
            pass

    class CapturingRunner(JobRunner):
        runs: list = []

        def run(self, plans):
            type(self).runs.append(plans)
            return 0

    monkeypatch.setattr(mw, "Messagebox", FakeMessagebox)
    monkeypatch.setattr(mw, "ToastNotification", FakeToast)
    monkeypatch.setattr(mw, "JobRunner", CapturingRunner)
    windows = []

    def make(**cfg_kwargs):
        cfg = appconfig.AppConfig(check_updates=False, **cfg_kwargs)
        win = mw.MainWindow(tk_root, cfg, dnd_ok=False)
        _cancel_afters(tk_root)          # Queue/Restore steuert der Test
        win.scans = started
        win.real_scan_worker = lambda path: real_scan_worker(win, path)
        win.messages = FakeMessagebox.calls
        win.messagebox = FakeMessagebox
        win.runs = CapturingRunner.runs
        windows.append(win)
        return win

    yield make
    _cancel_afters(tk_root)
    for win in windows:
        win.destroy()


@pytest.fixture
def win(make_win):
    return make_win()


def _tools_ok(win) -> None:
    from core.tools import ToolStatus
    win.tool_status = {"mkvmerge": ToolStatus("mkvmerge", "m", "94.0"),
                       "ffmpeg": ToolStatus("ffmpeg", "f", "7.1")}


def _add(win, *files: Path) -> list[str]:
    for f in files:
        f.write_bytes(b"")
    win.add_files([str(f) for f in files])
    return [str(f.resolve()) for f in files]


def _scanned(win, path: str) -> None:
    win._handle_message(("SCANNED", path, film_at(path), None))


def _saved_session(tmp_path: Path) -> list[dict]:
    return json.loads((tmp_path / "config.json").read_text("utf-8"))["session"]


def _pump_sources(win, timeout: float = 3.0) -> None:
    """Die laufende Quellen-Prüfung abschließen: Worker-Meldungen wie
    _poll_queue abarbeiten, bis „SOURCE_DONE“ verarbeitet ist — und die
    anschließende Suche unter anderen Laufwerksbuchstaben („MOVED“)."""
    end = time.monotonic() + timeout
    while win._watch.checking or win._watch.searching:
        assert time.monotonic() < end, "Zeitüberschreitung"
        try:
            win._handle_message(win.ui_q.get(timeout=0.02))
        except queue.Empty:
            pass


def _restore(win) -> None:
    """Sitzung wiederherstellen wie beim Start — samt Hintergrund-Prüfung
    der Quellen (erreichbare werden danach gescannt)."""
    win._restore_session()
    _pump_sources(win)


def _run_start(win, timeout: float = 3.0) -> None:
    """Start wie F5 — die Überschreib-Prüfung läuft im Hintergrund: ihre
    Antwort abarbeiten, dann den Lauf (falls einer beginnt) abwarten."""
    win._start()
    end = time.monotonic() + timeout
    while win._starting:
        assert time.monotonic() < end, "Zeitüberschreitung"
        try:
            win._handle_message(win.ui_q.get(timeout=0.02))
        except queue.Empty:
            pass
    if win._worker is not None:
        win._worker.join(timeout)


# 1 ─────────────────────────────────────────────────────────────────────────


def test_ui_wiederherstellung_baut_mit_dem_job_profil(win, tmp_path):
    src = tmp_path / "film.mkv"
    src.write_bytes(b"")
    path = str(src.resolve())
    job = session.serialize_plan(build_plan(film_at(path), builtin(REMUX)))
    win.cfg.active_profile = DE                    # inzwischen aktiv
    win.cfg.session = [job]
    _restore(win)
    _scanned(win, path)
    plan = win.plans[path]
    assert plan.profile_name == REMUX
    assert all(a is Action.COPY for a in actions(plan).values())
    # die (erste) Datei ist markiert: Profil und Anzeige folgen IHR
    assert win.profile.name == REMUX and win.profile_cb.get() == REMUX


def test_ui_wiederherstellung_aendert_profil_der_markierung_nicht(win,
                                                                 tmp_path):
    a, b = tmp_path / "a.mkv", tmp_path / "b.mkv"
    for f in (a, b):
        f.write_bytes(b"")
    pa, pb = str(a.resolve()), str(b.resolve())
    win.cfg.session = [
        session.serialize_plan(build_plan(film_at(pa), builtin(DE))),
        session.serialize_plan(build_plan(film_at(pb), builtin(REMUX)))]
    _restore(win)
    _scanned(win, pa)                               # a wird markiert
    _scanned(win, pb)                               # b nicht markiert
    assert win.selected == pa
    assert win.profile.name == DE and win.profile_cb.get() == DE
    assert win.plans[pb].profile_name == REMUX
    assert not win.plans[pb].stereo_sources()


# 2 ─────────────────────────────────────────────────────────────────────────


def test_ui_warteschlange_ueberlebt_speichern_vor_dem_scan(win, tmp_path):
    (path,) = _add(win, tmp_path / "a.mkv")
    assert [j["path"] for j in _saved_session(tmp_path)] == [path]


def test_ui_fehlgeschlagener_scan_bleibt_und_laesst_sich_wiederholen(
        win, tmp_path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"")
    path = str(src.resolve())
    job = {"path": path, "profile_name": REMUX, "overrides": {"1": "drop"}}
    win.cfg.session = [job]
    _restore(win)
    _wait_for(lambda: win.scans == [path])
    win._handle_message(("SCAN_FAILED", path, "mkvmerge nicht gefunden"))
    win._safe_save()
    assert _saved_session(tmp_path) == [job]       # samt Konfiguration

    win.add_files([str(src)])                      # erneut hinzufügen
    _wait_for(lambda: win.scans == [path, path])
    assert win.file_list.tree.set(path, "status") == "wird gescannt"
    assert "erneut analysiert" in _log_text(win)

    win._handle_message(("SCAN_FAILED", path, "mkvmerge nicht gefunden"))
    from core.tools import ToolStatus
    win._handle_message(("TOOLS", {
        "mkvmerge": ToolStatus("mkvmerge", "m", "")}))     # noch kaputt
    time.sleep(0.05)
    assert len(win.scans) == 2
    win._handle_message(("TOOLS", {
        "mkvmerge": ToolStatus("mkvmerge", "m", "94.0")}))
    _wait_for(lambda: len(win.scans) == 3)
    _scanned(win, path)                            # Konfiguration kommt an
    assert win.plans[path].profile_name == REMUX
    assert win.plans[path].decisions[1].action is Action.DROP


def test_ui_unveraendertes_mkvmerge_scannt_kaputte_datei_nicht_neu(
        win, tmp_path):
    from core.tools import ToolStatus
    (path,) = _add(win, tmp_path / "kaputt.mkv")
    win._handle_message(("SCAN_FAILED", path, "kein MKV"))
    ok = {"mkvmerge": ToolStatus("mkvmerge", "m", "94.0")}
    win._handle_message(("TOOLS", ok))             # erste Erkennung
    _wait_for(lambda: len(win.scans) == 2)
    win._handle_message(("SCAN_FAILED", path, "kein MKV"))
    for _ in range(3):                             # Werkzeuge geschlossen
        win._handle_message(("TOOLS", {
            "mkvmerge": ToolStatus("mkvmerge", "m", "94.0")}))
    time.sleep(0.05)
    assert len(win.scans) == 2
    assert _log_text(win).count("erneut analysiert") == 1
    win._handle_message(("TOOLS", {                # mkvmerge aktualisiert
        "mkvmerge": ToolStatus("mkvmerge", "m", "95.0")}))
    _wait_for(lambda: len(win.scans) == 3)


# 3 ─────────────────────────────────────────────────────────────────────────


def test_ui_unerreichbare_jobs_bleiben_gespeichert(win, tmp_path):
    # (Ausführlich: tests/test_offline_jobs.py)
    missing = tmp_path / "usb" / "weg.mkv"
    present = tmp_path / "da.mkv"
    present.write_bytes(b"")
    gone_job = {"path": str(missing), "profile_name": REMUX}
    win.cfg.session = [gone_job, {"path": str(present.resolve())}]
    _restore(win)
    assert "1 Datei der letzten Sitzung wartet auf ihr Laufwerk" \
        in _log_text(win)
    assert win.file_list.tree.set(str(missing), "status") == "Laufwerk fehlt"
    win._safe_save()
    assert _saved_session(tmp_path)[0] == gone_job

    # Laufwerk wieder da: Hinzufügen bringt die gespeicherte Konfiguration mit
    missing.parent.mkdir()
    (path,) = _add(win, missing)
    _scanned(win, path)
    assert win.plans[path].profile_name == REMUX
    win._safe_save()
    paths = [j["path"] for j in _saved_session(tmp_path)]
    assert len(paths) == len(set(paths)) == 2


def test_ui_leeren_verwirft_wartende_jobs_nach_rueckfrage(win, tmp_path):
    # Laufwerk (tmp_path) da, Datei nicht: fragt ebenso
    win.cfg.session = [{"path": str(tmp_path / "weg.mkv")}]
    _restore(win)
    assert win.file_list.tree.set(str(tmp_path / "weg.mkv"), "status") \
        == "Datei fehlt"
    win._clear_files()                             # Rückfrage: „Ja“
    assert [m[:2] for m in win.messages] == [("yesno", "Liste leeren")]
    assert _saved_session(tmp_path) == []


def _shown(widget) -> bool:
    return widget.winfo_manager() != ""


def test_ui_alle_jobs_unerreichbar_stehen_sichtbar_in_der_liste(win,
                                                                tmp_path):
    # Typischer USB-Fall: ALLE Jobs fehlen → trotzdem Arbeitsansicht mit
    # den wartenden Zeilen (Protokoll und „Leeren“ erreichbar) — kein
    # Leerzustand mit Sonderhinweis mehr
    paths = [str(tmp_path / "usb" / "a.mkv"), str(tmp_path / "usb" / "b.mkv")]
    win.cfg.session = [{"path": p} for p in paths]
    _restore(win)
    assert _shown(win.work) and not _shown(win.empty)
    assert win.file_list.paths() == paths
    assert not _shown(win.empty_notice)
    assert not hasattr(win, "discard_deferred_btn")
    assert win.files_label.cget("text") == "DATEIEN (2)"


def test_ui_wartende_zeile_bleibt_nach_entfernen_einer_anderen(win,
                                                               tmp_path):
    gone = str(tmp_path / "usb" / "weg.mkv")
    win.cfg.session = [{"path": gone}]
    _restore(win)
    (path,) = _add(win, tmp_path / "anderer.mkv")
    win.file_list.select(path)
    win._remove_selected()
    assert win.file_list.paths() == [gone] and _shown(win.work)
    assert list(win.plans) == [gone]


# 4 ─────────────────────────────────────────────────────────────────────────


def test_ui_markierung_waehrend_scan_bindet_panel_an_neue_datei(win,
                                                              tmp_path):
    pa, pb = _add(win, tmp_path / "a.mkv", tmp_path / "b.mkv")
    _scanned(win, pa)
    assert win.selected == pa
    win._on_file_selected(pb)                      # b wird noch gescannt
    _scanned(win, pb)
    assert win.stereo is win.plans[pb].stereo
    win.trackname_var.set("Nachtmodus")
    win._on_stereo_changed()
    assert win.plans[pb].stereo.track_name == "Nachtmodus"
    assert win.plans[pa].stereo.track_name != "Nachtmodus"


# 5 ─────────────────────────────────────────────────────────────────────────


def test_ui_f5_uebernimmt_getippten_spurnamen(win, tmp_path):
    (path,) = _add(win, tmp_path / "a.mkv")
    _scanned(win, path)
    assert win.plans[path].stereo_sources()
    _tools_ok(win)
    win.trackname_var.set("Deutsch Stereo (Nachtmodus)")   # kein FocusOut
    _run_start(win)
    (run,) = win.runs
    assert run[0].stereo.track_name == "Deutsch Stereo (Nachtmodus)"


# 6 ─────────────────────────────────────────────────────────────────────────


def test_ui_start_kurz_nach_lauf_verarbeitet_fertige_nicht_erneut(win,
                                                                 tmp_path):
    pa, pb = _add(win, tmp_path / "a.mkv", tmp_path / "b.mkv")
    _scanned(win, pa)
    _scanned(win, pb)
    win.plans[pa].status = FileStatus.DONE
    win._on_batch_done(1, 1, False)                # Aufräumen erst in 1,5 s
    assert win._done_removal is not None
    _tools_ok(win)
    _run_start(win)
    (run,) = win.runs
    assert [p.media.path for p in run] == [pb]
    assert pa not in win.plans and win._done_removal is None


# 7 ─────────────────────────────────────────────────────────────────────────


def test_ui_tmdb_nach_dem_scan_ausserhalb_des_scan_platzes(win, tmp_path,
                                                          monkeypatch):
    from core import tmdb
    from ui import main_window as mw
    (path,) = _add(win, tmp_path / "a.mkv")
    win.cfg.online_names = True
    win._scan_sem = threading.Semaphore(1)
    seen = {}

    def fake_canonical(_key, _name, *_a, **_k):
        free = win._scan_sem.acquire(blocking=False)
        if free:
            win._scan_sem.release()
        seen["frei"] = free
        seen["schon gemeldet"] = [m[0] for m in list(win.ui_q.queue)]
        return "Film"

    monkeypatch.setattr(tmdb, "resolved_key", lambda _k="": "KEY")
    monkeypatch.setattr(tmdb, "canonical_name", fake_canonical)
    monkeypatch.setattr(mw, "scan_file", lambda _m, p: film_at(p))
    win._tools_ready.set()
    win.real_scan_worker(path)
    assert seen == {"frei": True, "schon gemeldet": ["SCANNED"]}
    assert [m[0] for m in _drain(win.ui_q)] == ["SCANNED", "CANONICAL"]


def test_ui_tmdb_titel_nach_start_erst_nach_dem_lauf(win, tmp_path):
    # Der Titel kann jetzt NACH dem Start eintreffen: Der Lauf schreibt den
    # bisherigen Namen — die Liste darf nicht einen anderen zeigen
    pa, pb = _add(win, tmp_path / "The.Film.2010.1080p.mkv",
                  tmp_path / "Other.Film.2011.mkv")
    _scanned(win, pa)
    _scanned(win, pb)
    _tools_ok(win)
    _run_start(win)
    (run,) = win.runs
    written = {p.media.path: p.output_path for p in run}
    assert win._running
    win._handle_message(("CANONICAL", pa, "Der Film (2010)"))
    win._handle_message(("CANONICAL", pb, "Ein Film (2011)"))
    for path in (pa, pb):
        assert win.plans[path].output_path == written[path]
        assert win.plans[path].canonical_name == ""
    # während des Laufs hinzugefügt (nicht im Lauf) → Titel sofort
    (pc,) = _add(win, tmp_path / "Third.Film.2012.mkv")
    _scanned(win, pc)
    win._handle_message(("CANONICAL", pc, "Dritter Film (2012)"))
    assert Path(win.plans[pc].output_path).name == "Dritter Film (2012).mkv"

    win._handle_message(("FILE_STATUS", pa, FileStatus.DONE, ""))
    win._handle_message(("FILE_STATUS", pb, FileStatus.ERROR, "kaputt"))
    win._on_batch_done(1, 2, False)
    # fertig: bleibt beim geschriebenen Namen; Fehler: nächster Versuch
    # mit dem TMDb-Titel
    assert win.plans[pa].output_path == written[pa]
    assert Path(win.plans[pb].output_path).name == "Ein Film (2011).mkv"
    assert win._late_titles == {}


def test_ui_tmdb_hinweis_landet_im_protokoll(win, monkeypatch):
    from core import tmdb
    notices = ["TMDb lehnt den eigenen API-Key ab."]
    monkeypatch.setattr(tmdb, "canonical_name", lambda *_a, **_k: None)
    monkeypatch.setattr(tmdb, "take_notice",
                        lambda: notices.pop(0) if notices else None,
                        raising=False)
    win._title_worker("C:/x/Film.mkv")
    assert _drain(win.ui_q) == [
        ("LOG", "⚠ TMDb lehnt den eigenen API-Key ab.", "warn")]


def test_ui_config_hinweis_landet_einmal_im_protokoll(make_win):
    win = make_win(load_notice="config.json war beschädigt — es gelten die "
                               "Standardeinstellungen.")
    assert _log_text(win).count("config.json war beschädigt") == 1
    assert win.cfg.load_notice == "" and win.log.expanded


def test_ui_config_hinweis_im_leerzustand_sichtbar(make_win, tmp_path):
    # Eine zurückgesetzte config.json hat keine Sitzung → Leerzustand; das
    # Protokoll ist dort unsichtbar, der Hinweis muss trotzdem ankommen
    win = make_win(load_notice="config.json war beschädigt.")
    assert _shown(win.empty_notice)
    assert "config.json war beschädigt" in win.empty_notice.cget("text")
    (path,) = _add(win, tmp_path / "a.mkv")        # ab jetzt: Protokoll
    win.file_list.select(path)
    win._remove_selected()
    assert not _shown(win.empty_notice)           # nicht ewig wiederholen


# 8 ─────────────────────────────────────────────────────────────────────────


def test_ui_saubere_namen_im_quellordner_nie_gleich_quelle(win, tmp_path):
    (path,) = _add(win, tmp_path / "Inception.mkv")
    _scanned(win, path)
    win.cfg.clean_names = True
    plan = win.plans[path]
    win._refresh_output_name(plan)
    assert plan.output_path == str(tmp_path.resolve() / "Inception_remux.mkv")


# 9 ─────────────────────────────────────────────────────────────────────────


def test_ui_kollision_mit_quelldatei_eines_anderen_jobs(win, tmp_path):
    pa, pb = _add(win, tmp_path / "Film.mkv", tmp_path / "Film_remux.mkv")
    _scanned(win, pa)
    _scanned(win, pb)
    _tools_ok(win)
    win._start()
    (call,) = win.messages
    kind, title, message = call
    assert (kind, title) == ("error", "Ausgabe-Kollision")
    assert "„Film.mkv“" in message and "Quelldatei" in message
    assert "„Film_remux.mkv“" in message
    assert win.runs == [] and not win._running


# 10 ────────────────────────────────────────────────────────────────────────


def test_ui_unerwarteter_scanfehler_meldet_scan_failed(win, tmp_path,
                                                      monkeypatch):
    from ui import main_window as mw

    def boom(_mkvmerge, _path):
        raise RuntimeError("unerwartet")

    monkeypatch.setattr(mw, "scan_file", boom)
    win._tools_ready.set()
    win.real_scan_worker(str(tmp_path / "a.mkv"))
    (msg,) = _drain(win.ui_q)
    assert msg[0] == "SCAN_FAILED" and "unerwartet" in msg[2]
    assert win._scan_sem.acquire(blocking=False)   # Platz wieder frei


# 11 ────────────────────────────────────────────────────────────────────────


def test_ui_speicherfehler_wird_einmal_gemeldet(win, tmp_path, monkeypatch):
    import config as appconfig
    monkeypatch.setattr(appconfig, "CONFIG_FILE",
                        tmp_path / "fehlt" / "config.json")
    win._safe_save()
    win._safe_save()
    text = _log_text(win)
    assert text.count("lassen sich nicht in") == 1
    assert "beschreibbaren Ordner" in text and win.log.expanded
    # im Leerzustand (z. B. gleich nach „Leeren“) ist das Protokoll
    # unsichtbar — die Warnung steht dann unter der Ablage
    assert not win.plans and _shown(win.empty_notice)
    assert "lassen sich nicht in" in win.empty_notice.cget("text")


# 12 ────────────────────────────────────────────────────────────────────────


def _frame_state(window):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetParent.restype = wintypes.HWND
    hwnd = user32.GetParent(window.winfo_id())
    dark = ctypes.c_int(-1)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
    layered = bool(user32.GetWindowLongW(hwnd, -20) & 0x00080000)
    return dark.value, layered


@pytest.mark.skipif(sys.platform != "win32", reason="DWM nur unter Windows")
def test_titelleiste_leeres_fenster_erst_nach_dem_start_layout_sichtbar(
        tk_root):
    import tkinter as tk
    from ui import theme
    top = tk.Toplevel(tk_root)
    try:
        theme.apply_dark_titlebar(top)
        # Rahmen existiert schon (dunkel), ist aber noch durchsichtig — kein
        # leeres Mini-Fenster, das nach dem Aufbau springt
        assert float(top.attributes("-alpha")) == 0.0
        assert _frame_state(top)[0] == 1
        tk.Label(top, text="Inhalt").pack(padx=80, pady=80)   # „Aufbau“
        for _ in range(3):
            top.update()
            time.sleep(0.02)
        assert float(top.attributes("-alpha")) == 1.0
        assert _frame_state(top) == (1, False)   # dunkel, nicht layered
    finally:
        top.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="DWM nur unter Windows")
def test_titelleiste_dialog_mit_inhalt_wie_bisher(tk_root):
    import tkinter as tk
    from ui import theme
    top = tk.Toplevel(tk_root)
    try:
        tk.Label(top, text="Dialog").pack()
        theme.apply_dark_titlebar(top)
        assert top.winfo_ismapped()
        assert float(top.attributes("-alpha")) == 1.0
        assert _frame_state(top) == (1, False)
    finally:
        top.destroy()


def test_session_modul_bleibt_ohne_tkinter():
    # core/ ist UI-frei — auch das erweiterte session-Modul
    import subprocess
    code = ("import sys; import core.session; "
            "sys.exit(1 if 'tkinter' in sys.modules else 0)")
    root = Path(__file__).resolve().parents[1]
    assert subprocess.run([sys.executable, "-c", code], cwd=root,
                          env={**os.environ, "PYTHONPATH": str(root)}
                          ).returncode == 0
