"""Befunde Drag&Drop: Tcl-Listen-Parsing (Klammern im Namen) und ein
tkdnd, das nicht lädt (tkinterdnd2 0.4/0.5 unter Tcl 9).

Der Parser-Teil läuft mit tkinter.Tcl() im System-Python (ohne
ttkbootstrap); der App-Teil wird ohne ttkbootstrap/tkinterdnd2 übersprungen.
"""

from __future__ import annotations

import json
import re
import tkinter
from types import SimpleNamespace

import pytest

from ui.drop import load_tkdnd, mkv_paths, split_drop_data


@pytest.fixture(scope="module")
def tcl():
    return tkinter.Tcl()


def tcl_list(tcl, paths: list[str]) -> str:
    """Stringform einer Tcl-Liste — genau so setzt tkdnd %D ins Bind-Skript
    ein (Tcls eigene Listen-Quotierung, keine Nachbildung)."""
    tcl.setvar("spurwerk_drop", tuple(paths))
    return tcl.eval("string cat $spurwerk_drop")


# ── Zerlegen (tk.splitlist statt Regex) ────────────────────────────────────


class TestSplitDropData:
    def test_datei_mit_klammern_und_zweite_datei(self, tcl):
        data = "{C:/Filme/Dune (2021) {imdb-tt1160419}.mkv} C:/a.mkv"
        assert split_drop_data(data, tcl.splitlist) == [
            "C:/Filme/Dune (2021) {imdb-tt1160419}.mkv", "C:/a.mkv"]

    def test_ordner_mit_klammern(self, tcl):
        data = "{C:/Filme/Dune Part Two (2024) {tmdb-693134}}"
        assert split_drop_data(data, tcl.splitlist) == [
            "C:/Filme/Dune Part Two (2024) {tmdb-693134}"]

    def test_unbalancierte_klammer_ist_backslash_maskiert(self, tcl):
        # Tcl maskiert einzelne Klammern mit Backslash — der muss weg
        data = r"C:/Filme/kaputt\ \{\ klammer.mkv C:/Filme/zu\}.mkv"
        assert split_drop_data(data, tcl.splitlist) == [
            "C:/Filme/kaputt { klammer.mkv", "C:/Filme/zu}.mkv"]

    def test_leerzeichen(self, tcl):
        data = "{C:/Filme/mit leer.mkv} {D:/Serien/Staffel 1} C:/ohne.mkv"
        assert split_drop_data(data, tcl.splitlist) == [
            "C:/Filme/mit leer.mkv", "D:/Serien/Staffel 1", "C:/ohne.mkv"]

    def test_rundreise_ueber_echte_tcl_quotierung(self, tcl):
        paths = [
            "C:/Filme/Dune (2021) {imdb-tt1160419}.mkv",
            "C:/Filme/Dune Part Two (2024) {tmdb-693134}",
            "C:/Filme/kaputt { klammer.mkv",
            "C:/Filme/x}y{z.mkv",
            "{C:/start.mkv",
            r"C:\Filme\Windows Pfad {edition-Director's Cut}.mkv",
            "C:/Filme/$dollar [x] \"quote\";.mkv",
            "C:/a.mkv",
        ]
        data = tcl_list(tcl, paths)
        assert split_drop_data(data, tcl.splitlist) == paths

    def test_alter_regex_haette_zerschnitten(self, tcl):
        # Beleg für den Befund: der frühere Regex liefert Bruchstücke
        data = tcl_list(tcl, ["C:/Filme/Dune (2021) {imdb-tt1160419}.mkv"])
        old = [(m[0] or m[1]).strip()
               for m in re.findall(r"\{([^}]+)\}|(\S+)", data)]
        assert not any(p.lower().endswith(".mkv") for p in old)
        assert split_drop_data(data, tcl.splitlist)[0].endswith(".mkv")

    def test_ungueltige_liste_wird_ein_pfad(self, tcl):
        assert split_drop_data("{C:/a.mkv", tcl.splitlist) == ["{C:/a.mkv"]

    def test_leer(self, tcl):
        assert split_drop_data("", tcl.splitlist) == []


# ── Auswerten (Ordner, .mkv-Filter) ────────────────────────────────────────


class TestMkvPaths:
    def test_ordner_mit_klammern_liefert_alle_mkv_sortiert(self, tmp_path):
        folder = tmp_path / "Dune Part Two (2024) {tmdb-693134}"
        folder.mkdir()
        for name in ("b.mkv", "a {x}.mkv", "c.mkv", "notiz.txt"):
            (folder / name).write_bytes(b"")
        files, skipped = mkv_paths([str(folder)])
        assert files == sorted(str(folder / n)
                               for n in ("a {x}.mkv", "b.mkv", "c.mkv"))
        assert skipped == []

    def test_mkv_filter_und_uebersprungene(self, tmp_path):
        empty = tmp_path / "leer {x}"
        empty.mkdir()
        mkv = str(tmp_path / "Dune (2021) {imdb-tt1160419}.MKV")
        files, skipped = mkv_paths([mkv, str(tmp_path / "clip.mp4"),
                                    str(empty)])
        assert files == [mkv]
        assert skipped == [str(tmp_path / "clip.mp4"), str(empty)]

    def test_ende_zu_ende_wie_tkdnd(self, tcl, tmp_path):
        folder = tmp_path / "Serie {tvdb-81189}"
        folder.mkdir()
        (folder / "S01E01 {x}.mkv").write_bytes(b"")
        single = str(tmp_path / "Film (2021) {imdb-tt1}.mkv")
        data = tcl_list(tcl, [single, str(folder)])
        files, skipped = mkv_paths(split_drop_data(data, tcl.splitlist))
        assert files == [single, str(folder / "S01E01 {x}.mkv")]
        assert skipped == []


# ── tkdnd lädt nicht (tkinterdnd2 0.4/0.5 unter Tcl 9) ─────────────────────


def _require_wie_tkinterdnd2(root):
    """Verhalten von tkinterdnd2.TkinterDnD._require unter Tcl 9: das
    `package require tkdnd` scheitert (TclError) und wird zu RuntimeError.
    Bewusst ohne echtes `package require` — das verstellt unter Tcl 9 den
    Interpreter-Zustand, und spätere Tk-Fenster im Testlauf scheitern."""
    raise RuntimeError("Unable to load tkdnd library.")


class TestLoadTkdnd:
    # load_tkdnd setzt nur ein Attribut und fängt Ausnahmen ab — eine
    # Attrappe genügt, ein echter Interpreter ist nicht nötig
    def test_runtimeerror_heisst_ohne_drag_and_drop(self):
        assert load_tkdnd(SimpleNamespace(), _require_wie_tkinterdnd2) is False

    def test_tclerror_heisst_ohne_drag_and_drop(self):
        def require(root):
            raise tkinter.TclError("couldn't load library")
        assert load_tkdnd(SimpleNamespace(), require) is False

    def test_erfolg_merkt_version(self):
        root = SimpleNamespace()
        assert load_tkdnd(root, lambda r: "2.9.5") is True
        assert root.TkdndVersion == "2.9.5"


# ── App: startet trotz kaputtem tkdnd, Drop mit Klammern ───────────────────


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """app importieren — echte config.json bleibt unberührt."""
    pytest.importorskip("ttkbootstrap")
    pytest.importorskip("tkinterdnd2")
    import config as appconfig
    monkeypatch.setattr(appconfig, "base_path", lambda: tmp_path)
    monkeypatch.setattr(appconfig, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(appconfig, "LEGACY_INI", tmp_path / "config.ini")
    (tmp_path / "config.json").write_text(
        json.dumps({"version": 1, "check_updates": False}), encoding="utf-8")
    import app
    from ui.main_window import MainWindow
    # offline und ohne Hintergrund-Aufrufe externer Programme
    monkeypatch.setattr(MainWindow, "_probe_tools", lambda self: None)
    monkeypatch.setattr(MainWindow, "_check_updates", lambda self: None)
    yield app
    # ttkbootstrap hält seinen Style als Singleton am ersten Tk-Fenster —
    # nach destroy() scheiterte sonst jedes spätere Fenster im selben
    # Testlauf („application has been destroyed“)
    from ttkbootstrap.style import Style
    Style.instance = None


def _make_app(app_module):
    try:
        return app_module.SpurwerkApp()
    except tkinter.TclError as exc:   # kein Display
        pytest.skip(f"Tk nicht verfügbar: {exc}")


class TestApp:
    def test_startet_ohne_drag_and_drop_wenn_tkdnd_scheitert(
            self, app_module, monkeypatch):
        def kaputt(root):
            raise RuntimeError("Unable to load tkdnd library.")
        monkeypatch.setattr(app_module.TkinterDnD, "_require", kaputt)
        win = _make_app(app_module)
        try:
            assert win._dnd_ok is False
            assert win.main._dnd_ok is False
        finally:
            win.destroy()

    def test_drop_mit_klammern_fuegt_dateien_hinzu(
            self, app_module, monkeypatch, tmp_path):
        win = _make_app(app_module)
        try:
            added: list[list[str]] = []
            monkeypatch.setattr(win.main, "add_files", added.append)
            logged: list[tuple] = []
            monkeypatch.setattr(win.main.log, "log",
                                lambda *a: logged.append(a))
            folder = tmp_path / "Dune Part Two (2024) {tmdb-693134}"
            folder.mkdir()
            (folder / "film.mkv").write_bytes(b"")
            single = str(tmp_path / "Dune (2021) {imdb-tt1160419}.mkv")
            other = str(tmp_path / "trailer.mp4")
            data = tcl_list(win, [single, str(folder), other])
            win._on_drop(SimpleNamespace(data=data))
            assert added == [[single, str(folder / "film.mkv")]]
            assert len(logged) == 1 and "trailer.mp4" in logged[0][0]
        finally:
            win.destroy()
