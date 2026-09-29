"""Höhenverteilung des Hauptfensters: Priorität, Mindestgröße, Arbeitsbereich,
letzter Ausweg (ui/layout.py, ui/geometry.py, app.py).

Die reine Logik läuft überall. Die Fenster-Tests brauchen ttkbootstrap und
ein Tk-Display — im System-Python ohne ttkbootstrap werden sie übersprungen.
Sie biegen config.CONFIG_FILE/base_path IMMER auf tmp_path um, starten weder
Scans noch Werkzeuge und bleiben unsichtbar (durchsichtiges Fenster).
Andere Windows-Skalierungen werden über Tks Skalierung nachgestellt: Schriften
und Bilder folgen ihr, Abstände in Pixeln bleiben — genau wie echt.
"""

from __future__ import annotations

import json
import time

import pytest

from tests.helpers import media, track
from ui import layout
from ui.geometry import (Frame, Rect, centered, client_limit, inside,
                         restored_width)

# ══ Reine Logik ═══════════════════════════════════════════════════════════


def metrics(*, log: bool = True, rigid: int = 570) -> layout.Metrics:
    """Die bei 125 % gemessenen Werte (Zeilen 20 px, Audio-Panel sichtbar)."""
    return layout.Metrics(
        rigid=rigid, files=layout.Elastic(38, 20, *layout.FILE_ROWS),
        tracks=layout.Elastic(38, 20, *layout.TRACK_ROWS), log_head=42,
        log=layout.Elastic(50, 20, *layout.LOG_LINES) if log else None)


M = metrics()
NATURAL = layout.height(M, layout.natural(M))        # 1118
MINIMUM = layout.height(M, layout.minimum(M))        # 828
FLOOR = layout.height(M, layout.Allocation(2, 2, 0, False))   # 726


def _alloc(avail: int, m: layout.Metrics = M) -> tuple:
    a = layout.allocate(avail, m)
    return a.log_lines, a.tracks, a.files, a.log_head


def test_natuerliche_und_mindesthoehe_wie_gemessen():
    assert (NATURAL, MINIMUM, FLOOR) == (1118, 828, 726)
    assert layout.natural(M) == layout.Allocation(4, 6, 9, True)
    assert layout.minimum(M) == layout.Allocation(3, 4, 0, True)


def test_genug_platz_alles_natuerlich():
    assert _alloc(NATURAL) == (9, 6, 4, True)
    assert _alloc(5000) == (9, 6, 4, True)   # Rest geht per Gewicht an Spuren


def test_nutzerbefund_1586x866():
    # vorher: Spurtabelle 0 Zeilen, Protokoll 9 Zeilen — jetzt umgekehrt
    assert _alloc(866) == (0, 4, 4, True)
    assert layout.height(M, layout.allocate(866, M)) <= 866


def test_reihenfolge_des_nachgebens():
    """Von groß nach klein, jede Stufe erst nach der vorigen: Protokoll-Text
    9 → 3, dann nur Kopfzeile; Spurtabelle 6 → 4; Dateiliste 4 → 3; letzter
    Ausweg: Dateiliste → 2, dann Kopfzeile weg, zuletzt Spurtabelle → 2."""
    seen: list[tuple] = []
    for avail in range(NATURAL + 50, FLOOR - 50, -1):
        a = _alloc(avail)
        if not seen or seen[-1] != a:
            seen.append(a)
    assert seen == [
        (9, 6, 4, True), (8, 6, 4, True), (7, 6, 4, True), (6, 6, 4, True),
        (5, 6, 4, True), (4, 6, 4, True), (3, 6, 4, True),
        (0, 6, 4, True), (0, 5, 4, True), (0, 4, 4, True), (0, 4, 3, True),
        (0, 4, 2, True), (0, 4, 2, False), (0, 3, 2, False),
        (0, 2, 2, False)]


def test_letzter_ausweg_behaelt_kopfzeile_so_lange_wie_moeglich():
    # eine Dateizeile (20 px) unter der Mindesthöhe: Kopfzeile bleibt
    assert _alloc(MINIMUM - 20) == (0, 4, 2, True)
    # erst darunter weicht sie — die Spurtabelle behält ihre 4 Zeilen
    assert _alloc(MINIMUM - 21) == (0, 4, 2, False)
    assert _alloc(MINIMUM - 20 - 42) == (0, 4, 2, False)
    assert _alloc(MINIMUM - 20 - 43) == (0, 3, 2, False)


@pytest.mark.parametrize("log", [True, False])
def test_zuteilung_passt_und_waechst_nie_beim_schrumpfen(log):
    m = metrics(log=log)
    prev = None
    for avail in range(1300, FLOOR - 1, -1):
        a = layout.allocate(avail, m)
        assert layout.height(m, a) <= avail
        if prev is not None:
            assert (a.log_lines, a.tracks, a.files, a.log_head) <= (
                prev.log_lines, prev.tracks, prev.files, prev.log_head)
            assert a.tracks <= prev.tracks and a.files <= prev.files
        prev = a


def test_prioritaeten_ueber_den_ganzen_bereich():
    for avail in range(FLOOR, NATURAL + 1):
        a = layout.allocate(avail, M)
        if a.log_lines:                        # Protokoll-Text nur mit ...
            assert (a.tracks, a.files) == (6, 4)   # ... vollen Tabellen
            assert a.log_lines >= 3
        if a.tracks < 6 or a.files < 4:
            assert a.log_lines == 0
        if a.log_head and a.files < 4:
            assert a.tracks == 4               # Spurtabelle gab zuerst nach
        if avail >= MINIMUM:                   # Mindesthöhe: nie beschnitten
            assert a.log_head and a.tracks >= 4 and a.files >= 3
        else:                                  # letzter Ausweg nur darunter:
            assert a.files == layout.EMERGENCY_ROWS    # zuerst Dateiliste,
        if not a.log_head:                     # dann Protokoll-Kopfzeile,
            assert a.files == layout.EMERGENCY_ROWS
        if a.tracks < 4:                       # zuletzt die Spurtabelle
            assert not a.log_head and a.files == layout.EMERGENCY_ROWS


def test_unter_dem_notfallboden_bleibt_der_boden():
    # noch kleiner: Tk nimmt den Rest von der Spurtabelle (Gewicht), nie
    # vom Start-Knopf — die Zuteilung selbst geht nicht unter 2 Zeilen
    assert _alloc(FLOOR - 200) == (0, 2, 2, False)


def test_eingeklapptes_protokoll_hat_dieselbe_mindesthoehe():
    closed = metrics(log=False)
    assert layout.height(closed, layout.minimum(closed)) == MINIMUM
    assert layout.height(closed, layout.natural(closed)) == 888
    assert _alloc(887, closed) == (0, 5, 4, True)


def test_bildlaufleiste_streckt_wenige_zeilen():
    """Gemessen bei 100 % (Tk) auf einem 125-%-Windows: Die Bildlaufleiste
    neben dem Protokoll ist 63 px hoch, 3 Textzeilen nur 60 — der Inhalt
    belegt dann ihre Höhe, nicht die lineare. Wer linear rechnet, gibt die
    3 px der Spurtabelle weg, und ihre 6. Zeile ist nicht mehr ganz zu
    sehen (Befund der Größenmatrix bei 1586×866 mit langem Hinweis)."""
    log = layout.Elastic(45, 16, *layout.LOG_LINES, floor=96)
    assert [log.px(n) for n in (1, 3, 4, 9)] == [96, 96, 109, 189]
    tree = layout.Elastic(33, 15, *layout.TRACK_ROWS, floor=50)
    assert [tree.px(n) for n in (1, 2, 6)] == [50, 63, 123]
    m = layout.Metrics(rigid=520, log_head=37, log=log, tracks=tree,
                       files=layout.Elastic(33, 15, *layout.FILE_ROWS,
                                            floor=50))
    a = layout.allocate(866, m)
    assert (a.log_lines, a.tracks, a.files) == (0, 6, 4)
    assert layout.height(m, a) <= 866
    assert layout.allocate(869, m).log_lines == 3        # passt genau


def test_ohne_audio_panel_weniger_starre_hoehe():
    small = metrics(rigid=412)                 # gemessen ohne Audio-Panel
    assert layout.height(small, layout.minimum(small)) == 670
    assert _alloc(866, small) == (4, 6, 4, True)   # 4 Protokoll-Zeilen


# ── Fenster im Arbeitsbereich ─────────────────────────────────────────────

WIN11_100 = Frame(left=1, top=31, right=1, bottom=1, dx=7)


def test_client_grenze_zieht_rahmen_ab():
    assert client_limit(Rect(0, 0, 1366, 728), WIN11_100) == (1364, 696)


def test_zentriert_im_arbeitsbereich():
    # sichtbarer Rahmen 1002×632 in 1920×1040
    assert centered(1000, 600, Rect(0, 0, 1920, 1040), WIN11_100) \
        == (459 - 7, 204)


def test_zu_hoch_zentriert_bleibt_titelleiste_erreichbar():
    assert centered(1000, 1200, Rect(0, 0, 1920, 1040), WIN11_100)[1] == 0


def test_wachsendes_fenster_rueckt_hoch_statt_unter_die_taskleiste():
    # Fenster weit unten, wächst auf 700 → rückt so weit hoch, dass es passt
    assert inside(100, 400, 1000, 700, Rect(0, 0, 1920, 1040), WIN11_100) \
        == (100, 1040 - 700 - 32)
    # passt es schon, bleibt es, wo es ist
    assert inside(100, 300, 1000, 700, Rect(0, 0, 1920, 1040), WIN11_100) \
        == (100, 300)


def test_zu_hohes_fenster_oben_ausgerichtet():
    assert inside(100, 300, 1000, 1100, Rect(0, 0, 1920, 1040),
                  WIN11_100)[1] == 0


def test_waagrecht_nur_verschoben_wenn_es_passt():
    work = Rect(0, 0, 1920, 1040)
    # ragt rechts hinaus, passt aber → nach links
    assert inside(1500, 0, 1000, 600, work, WIN11_100)[0] == 1920 - 1002 - 7
    # breiter als der Monitor (bewusst über zwei gezogen) → bleibt
    assert inside(-300, 0, 2500, 600, work, WIN11_100)[0] == -300


def test_gemerkte_breite_passt_auf_ihren_monitor():
    laptop, work = Rect(0, 0, 1366, 768), Rect(0, 0, 1366, 728)
    # auf Bildschirmbreite geklemmt: nur der Rahmen ragte hinaus
    assert restored_width(1366, laptop, work, WIN11_100) == 1364
    assert restored_width(1200, laptop, work, WIN11_100) == 1200
    # Taskleiste seitlich: das Fenster selbst ragte hinein
    side = Rect(62, 0, 1304, 768)
    assert restored_width(1366, laptop, side, WIN11_100) == 1302


def test_ueber_zwei_monitore_gezogene_breite_bleibt():
    monitor, work = Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040)
    assert restored_width(2500, monitor, work, WIN11_100) == 2500
    # nicht breiter als der Monitor → passend gemacht
    assert restored_width(1920, monitor, work, WIN11_100) == 1918


def test_arbeitsbereich_mit_negativem_ursprung():
    # Zweitmonitor links vom Primärmonitor
    left = Rect(-1920, 0, 1920, 1040)
    assert inside(-2500, 900, 800, 600, left, WIN11_100) \
        == (-1920 - 7, 1040 - 600 - 32)


# ══ Echte Fenster ═════════════════════════════════════════════════════════

DE_EN = "Deutsch + Englisch"       # Profil mit Stereo-Kopie → Audio-Panel


def _big_media(path: str):
    """14 Spuren: Video, 7× Audio (de/en Mehrkanal → Stereo-Kopie),
    6× Untertitel — mehr, als die Spurtabelle je ohne Scrollen zeigt."""
    langs = ["de", "en", "de", "fr", "es", "it", "ja"]
    audio = [track(i + 1, "audio", lang, codec="A_AC3",
                   channels=2 if i in (2, 6) else 6, default=i == 0,
                   name="Kommentar" if i == 2 else "")
             for i, lang in enumerate(langs)]
    subs = [track(8 + i, "subtitles", lang, codec="S_HDMV/PGS")
            for i, lang in enumerate(["de", "de", "en", "fr", "es", "it"])]
    return media(track(0, "video", codec="V_MPEGH/ISO/HEVC"), *audio, *subs,
                 path=path, chapters=True, duration=7200.0)


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """Die echte App — unsichtbar, ohne Werkzeuge/Scans/Update-Prüfung,
    Konfiguration in tmp_path. `percent` stellt eine Windows-Skalierung
    nach (Tk-Skalierung = dpi/72), `work` einen Monitor-Arbeitsbereich,
    `monitor`/`virtual` den ganzen Monitor bzw. den virtuellen Desktop."""
    ttk = pytest.importorskip("ttkbootstrap")
    import tkinter

    import config as appconfig
    monkeypatch.setattr(appconfig, "base_path", lambda: tmp_path)
    monkeypatch.setattr(appconfig, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(appconfig, "LEGACY_INI", tmp_path / "config.ini")
    import app
    from ui import main_window as mw
    from ui import theme
    monkeypatch.setattr(mw.MainWindow, "_probe_tools", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_check_updates", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_scan_worker",
                        lambda self, path: None)
    # durchsichtig bleiben: das Einblenden nach dem Start-Layout auslassen
    monkeypatch.setattr(theme, "_show_after_first_layout", lambda w: None)
    apps = []
    native: list = []     # Tk-Skalierung vor der Nachstellung

    def make(*, percent: int | None = None, work: Rect | None = None,
             monitor: Rect | None = None, virtual: Rect | None = None,
             **cfg):
        data = {"version": 1, "check_updates": False,
                "active_profile": DE_EN, "log_expanded": True, **cfg}
        (tmp_path / "config.json").write_text(json.dumps(data),
                                              encoding="utf-8")
        if percent:
            from ttkbootstrap import utility
            init = ttk.Window.__init__
            set_dpi = utility.enable_high_dpi_awareness

            def scaled(self, *a, **kw):
                kw["scaling"] = percent * 96 / 100 / 72
                init(self, *a, **kw)

            def remember(root=None, scaling=None):
                if root is not None:
                    native.append(root.tk.call("tk", "scaling"))
                set_dpi(root, scaling)
            monkeypatch.setattr(ttk.Window, "__init__", scaled)
            monkeypatch.setattr(utility, "enable_high_dpi_awareness",
                                remember)
        if work is not None:
            monkeypatch.setattr(app.SpurwerkApp, "_work_area",
                                lambda self, near=None: work)
        if monitor is not None:
            monkeypatch.setattr(app.SpurwerkApp, "_monitor_area",
                                lambda self, near=None: monitor)
        if virtual is not None:
            monkeypatch.setattr(
                app.SpurwerkApp, "_virtual_screen",
                lambda self: (virtual.x, virtual.y, virtual.w, virtual.h))
        try:
            window = app.SpurwerkApp()
        except tkinter.TclError as exc:   # kein Display
            pytest.skip(f"Tk nicht verfügbar: {exc}")
        apps.append(window)
        window.update()                   # _first_layout
        return window

    yield make
    for window in apps:
        try:
            # Tks Skalierung gilt für den ganzen Prozess (Bildschirm-Maße) —
            # zurückstellen, sonst erben spätere Fenster falsche Schriften
            if native:
                window.tk.call("tk", "scaling", native[0])
            # ausstehende Timer (Warteschlange, Sitzung) nicht ins nächste
            # Fenster tragen: Tcls Ereignisschleife teilen alle
            for aid in window.tk.splitlist(window.tk.call("after", "info")):
                window.tk.call("after", "cancel", aid)
            window.destroy()
        except tkinter.TclError:
            pass
    # ttkbootstrap hält seinen Style als Singleton am ersten Fenster
    from ttkbootstrap.style import Style
    Style.instance = None


def _load(app, tmp_path, n: int = 5) -> list[str]:
    """n Dateien mit großem Plan; die letzte ohne Konvertierung."""
    m = app.main
    paths = []
    for i in range(n):
        f = tmp_path / f"Film {i + 1} (2024).mkv"
        f.write_bytes(b"")
        paths.append(str(f.resolve()))
    m.add_files(paths)
    for p in paths:
        m._handle_message(("SCANNED", p, _big_media(p), None))
    m.file_list.select(paths[-1])
    app.update()
    m.track_table.set_all(True)            # alles kopieren → kein Panel
    m.file_list.select(paths[0])
    _settle(app)
    return paths


def _settle(app, rounds: int = 3) -> None:
    for _ in range(rounds):
        app.update()


def _resize(app, w: int, h: int) -> None:
    app.geometry(f"{w}x{h}+0+0")
    _settle(app)


def _rect(w) -> tuple[int, int, int, int]:
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return x, y, x + w.winfo_width(), y + w.winfo_height()


def _fully_visible(w) -> bool:
    """Abgebildet und ganz innerhalb jedes Vorfahren bis zum Fenster."""
    if not w.winfo_ismapped():
        return False
    x0, y0, x1, y1 = _rect(w)
    top, p = w.winfo_toplevel(), w
    while p is not top:
        p = p.nametowidget(p.winfo_parent())
        a0, b0, a1, b1 = _rect(p)
        if x0 < a0 or y0 < b0 or x1 > a1 or y1 > b1:
            return False
    return True


def _full_rows(tree, elastic: layout.Elastic) -> int:
    """Ganz sichtbare Zeilen: Unterkante über dem unteren Rand."""
    if not _fully_visible(tree):
        return 0
    boxes = [b for b in (tree.bbox(i) for i in tree.get_children()) if b]
    if not boxes:
        return 0
    bottom_border = elastic.base - min(b[1] for b in boxes)
    limit = tree.winfo_height() - bottom_border
    return sum(1 for b in boxes if b[1] + b[3] <= limit)


def _essentials(m) -> dict:
    parts = {"Kopfleiste": m._header_bar, "Dateiknöpfe": m._files_head,
             "Profil": m._rules, "Spurkopf": m._tracks_head,
             "Vorschau": m.preview_label, "Start": m.start_btn,
             "Abbrechen": m.cancel_btn, "Fortschritt": m.gauge_file,
             "Gesamt": m.gauge_total, "Status": m.status_label,
             "Legende": m._legend}
    if m.stereo_panel.winfo_manager():
        parts["Audio-Panel"] = m.stereo_panel
    if m.warn_label.winfo_manager():
        parts["Hinweis"] = m.warn_label
    return parts


def _check(app) -> dict:
    """Die Zusagen am echten Fenster prüfen; liefert die Messwerte."""
    m = app.main
    met = m.needs().metrics
    alloc = m.allocation
    h = app.winfo_height()
    tracks = _full_rows(m.track_table.tree, met.tracks)
    files = _full_rows(m.file_list.tree, met.files)
    hidden = [k for k, w in _essentials(m).items() if not _fully_visible(w)]
    assert not hidden, f"beschnitten bei {h}px: {hidden}"
    assert tracks >= alloc.tracks and files >= alloc.files
    if h >= layout.height(met, layout.minimum(met)):
        assert tracks >= 4 and files >= 3
        assert alloc.log_head and _fully_visible(m.log._header)
    if alloc.log_head:
        assert _fully_visible(m.log._header) and not m.log.notice
    else:                                  # letzter Ausweg: Statuszeile sagt es
        assert m.status_label.cget("text") == m.log.notice != ""
    if m.log.body_shown:                   # Protokoll gibt zuerst nach
        assert (alloc.tracks, alloc.files) == (6, 4)
    if alloc.log_head and alloc.files < 4:
        assert alloc.tracks == 4
    return dict(height=h, tracks=tracks, files=files, alloc=alloc)


# Testgrößen in logischen Pixeln (× Skalierung), dazu physisch
LOGICAL = {"1280x720-Laptop": (1280, 680), "1366x768-Laptop": (1366, 728),
           "1920x1080@125%": (1536, 824)}


@pytest.mark.parametrize("percent", [None, 100, 150, 200])
def test_spurtabelle_bleibt_bei_jeder_groesse_und_skalierung(
        make_app, tmp_path, percent):
    app = make_app(percent=percent)
    _load(app, tmp_path)
    m = app.main
    assert m.log.expanded and m.stereo_panel.winfo_manager()
    s = app.winfo_fpixels("1i") / 96
    lim_w, lim_h = client_limit(app._work_area(), app._measure_frame())
    sizes = [(round(w * s), round(h * s)) for w, h in LOGICAL.values()]
    sizes = [(w, h) for w, h in sizes if w <= lim_w and h <= lim_h]
    sizes += [(1586, 866), (300, 200)]     # Nutzerbefund; Minimum erzwingen
    for w, h in sizes:
        _resize(app, w, h)
        res = _check(app)
        min_w, min_h = app._min_size
        assert app.winfo_width() >= min_w and app.winfo_height() >= min_h
        assert res["tracks"] >= 4, (w, h, res)
    # bei der Mindestgröße: genau die Mindest-Zuteilung, Kopfzeile mit Hinweis
    assert m.allocation == layout.Allocation(3, 4, 0, True)
    assert "Fenster zu niedrig" in m.log._header.cget("text")


@pytest.mark.parametrize("percent", [None, 100, 200])
def test_modell_stimmt_mit_echten_hoehen(make_app, tmp_path, percent):
    """Für jede zulässige Zeilenzahl sagt das Modell die angeforderte Höhe
    jedes Teils exakt voraus — auch wo die Bildlaufleiste ihn streckt
    (100 % in Tk auf einem 125-%-Windows: 3 Protokollzeilen sind niedriger
    als sie) — und für jede Stufe die Höhe der ganzen Arbeitsansicht."""
    app = make_app(percent=percent)
    _load(app, tmp_path)
    m = app.main
    met = m.measure().metrics
    low = layout.EMERGENCY_ROWS
    for widget, box, part, rows in [
            (m.file_list.tree, m.file_list, met.files,
             range(low, layout.FILE_ROWS[0] + 1)),
            (m.track_table.tree, m.track_table, met.tracks,
             range(low, layout.TRACK_ROWS[0] + 1)),
            (m.log.text, m.log.body, met.log,
             range(layout.LOG_LINES[1], layout.LOG_LINES[0] + 1))]:
        keep = int(widget.cget("height"))
        for n in rows:
            widget.configure(height=n)
            app.update_idletasks()
            assert box.winfo_reqheight() == part.px(n), (str(box), n)
        widget.configure(height=keep)
    for alloc in (layout.natural(met), layout.Allocation(4, 6, 3),
                  layout.minimum(met), layout.Allocation(2, 4, 0, True),
                  layout.Allocation(2, 2, 0, False)):
        h = layout.height(met, alloc)
        m.fit(h)
        app.update_idletasks()
        assert m.allocation == alloc
        assert m.winfo_reqheight() == h, alloc


def test_protokoll_gibt_vor_den_tabellen_nach(make_app, tmp_path):
    """An jeder Stufengrenze (und 1 px darunter) zeigt das echte Fenster
    genau die Zuteilung, die ui/layout.py aus den Messwerten vorhersagt."""
    app = make_app()
    _load(app, tmp_path)
    m = app.main
    met = m.needs().metrics
    edges = {}                                 # Zuteilung → kleinste Höhe
    for h in range(layout.height(met, layout.natural(met)),
                   layout.height(met, layout.minimum(met)) - 1, -1):
        edges[layout.allocate(h, met)] = h
    seen = []
    min_h = layout.height(met, layout.minimum(met))
    for alloc, h in edges.items():
        # unter die Mindesthöhe lässt Tk das Fenster nicht (wm minsize)
        for height in (h, h - 1) if h > min_h else (h,):
            _resize(app, 1600, height)
            res = _check(app)
            assert app.winfo_height() == height
            assert m.allocation == layout.allocate(height, met)
            assert m.log.body_shown == (m.allocation.log_lines > 0)
            if height == h:
                assert m.allocation == alloc
            seen.append(m.allocation)
    assert [(a.log_lines, a.tracks, a.files) for a in edges] == [
        (9, 6, 4), (8, 6, 4), (7, 6, 4), (6, 6, 4), (5, 6, 4), (4, 6, 4),
        (3, 6, 4), (0, 6, 4), (0, 5, 4), (0, 4, 4), (0, 4, 3)]
    # wächst nie, während das Fenster schrumpft
    keys = [(a.log_head, a.log_lines, a.tracks, a.files) for a in seen]
    assert keys == sorted(keys, reverse=True)


def test_varianten_protokoll_zu_und_panel_aus(make_app, tmp_path):
    app = make_app()
    paths = _load(app, tmp_path)
    m = app.main
    mins = {}
    for log_open, sel in [(True, 0), (False, 0), (True, -1), (False, -1)]:
        m.file_list.select(paths[sel])
        m.log.set_expanded(log_open)
        _settle(app)
        panel = bool(m.stereo_panel.winfo_manager())
        assert panel == (sel == 0)
        mins[(log_open, panel)] = m.needs().min_h
        for w, h in [(1600, 850), (1708, 910), (1586, 866)]:
            _resize(app, w, h)
            assert _check(app)["tracks"] >= 4
    # Mindesthöhe hängt am Panel, nicht am Protokoll (das gibt ganz nach)
    assert mins[(True, True)] == mins[(False, True)]
    assert mins[(True, False)] == mins[(False, False)]
    assert mins[(True, False)] < mins[(True, True)]


def test_laptop_1366x768_bei_100_prozent_letzter_ausweg(make_app, tmp_path):
    # Arbeitsbereich 1366×728 (Taskleiste 40): mit Audio-Panel fehlen dem
    # Minimum ein paar Pixel → nur die Dateiliste gibt eine Zeile ab; die
    # Protokoll-Kopfzeile bleibt, die Spurtabelle behält 4 Zeilen
    work = Rect(0, 0, 1366, 728)
    app = make_app(percent=100, work=work)
    _load(app, tmp_path)
    m = app.main
    frame = app._measure_frame()
    lim_w, lim_h = client_limit(work, frame)
    assert m.needs().min_h > lim_h
    assert app._min_size[1] == lim_h            # Minimum gedeckelt
    assert app.winfo_height() == lim_h          # ganz ausgenutzt
    assert app.winfo_y() + frame.dy >= work.y
    assert (app.winfo_y() + frame.dy + frame.top + app.winfo_height()
            + frame.bottom) <= work.y + work.h  # nichts unter der Taskleiste
    res = _check(app)
    assert m.allocation == layout.Allocation(2, 4, 0, True)
    assert _fully_visible(m.log._header) and not m.log.notice
    assert m.status_label.cget("text") == ""
    assert res["tracks"] >= 4 and res["files"] >= 2


def test_winziger_arbeitsbereich_start_bleibt_sichtbar(make_app, tmp_path):
    # 1280×720 bei 100 % mit Audio-Panel: auch die Protokoll-Kopfzeile
    # weicht — die Statuszeile sagt es und zählt neue Meldungen mit
    work = Rect(0, 0, 1280, 680)
    app = make_app(percent=100, work=work)
    _load(app, tmp_path)
    m = app.main
    res = _check(app)                           # Start & Co. ganz sichtbar
    assert not m.allocation.log_head and not m.log.winfo_manager()
    assert m.allocation.files == layout.EMERGENCY_ROWS
    assert res["tracks"] >= 3                   # 2 zugeteilt + Rest
    notice = m.status_label.cget("text")
    assert notice == m.log.notice and "Protokoll" in notice
    assert "ausgeblendet" in notice and _fully_visible(m.status_label)
    m.log.log("Test-Fehler", "error")
    assert m.status_label.cget("text") == m.log.notice != notice
    # ein Lauf gehört der Statuszeile — danach kommt der Hinweis zurück
    m._running = True
    m._handle_message(("STATUS", "Datei 1/1"))
    m.log.log("noch eine Meldung")
    assert m.status_label.cget("text") == "Datei 1/1"
    m._running = False
    m.status_label.configure(text="")
    m._show_log_notice()
    assert m.status_label.cget("text") == m.log.notice
    # Platz → Kopfzeile zurück, Hinweis weg
    _resize(app, 1280, 1000)
    assert m.allocation.log_head and _fully_visible(m.log._header)
    assert m.status_label.cget("text") == "" and not m.log.notice


LONG_WARNING = ("Spur 3 hat eine Verzögerung von 120 ms — sie wird beim "
                "Remux übernommen, manche Player zeigen sie trotzdem "
                "unterschiedlich an. ") * 3


def _set_warning(app, text: str) -> None:
    """Hinweis unter der Spurtabelle wie aus einem Plan."""
    m = app.main
    m._selected_plan().warnings[:] = [text] if text else []
    m._update_preview()
    _settle(app)


def _wrap(w) -> int:
    return w.winfo_pixels(w.cget("wraplength"))


def test_leerer_hinweis_belegt_keinen_platz(make_app, tmp_path):
    app = make_app()
    _load(app, tmp_path)
    m = app.main
    _set_warning(app, "")
    assert m.warn_label.cget("text") == ""
    assert not m.warn_label.winfo_manager()     # keine Leerzeile
    empty = m.needs().min_h
    _set_warning(app, "Kurzer Hinweis")
    assert _fully_visible(m.warn_label)
    assert m.needs().min_h == empty + m.warn_label.winfo_reqheight()
    _set_warning(app, "")
    assert not m.warn_label.winfo_manager() and m.needs().min_h == empty


@pytest.mark.parametrize("percent", [None, 100, 200])
def test_hinweis_und_legende_nie_abgeschnitten(make_app, tmp_path, percent):
    """Bei der Mindestbreite (mit und ohne Audio-Panel) sind Legende und
    Hinweis ganz sichtbar; der Hinweis bricht auf die Tabellenbreite um —
    breiter gezogen braucht er weniger Zeilen, das Minimum sinkt mit."""
    app = make_app(percent=percent)
    paths = _load(app, tmp_path)
    m = app.main
    for sel in (0, -1):
        m.file_list.select(paths[sel])
        _settle(app)
        assert bool(m.stereo_panel.winfo_manager()) == (sel == 0)
        _set_warning(app, LONG_WARNING)
        _resize(app, 300, 200)                  # → Mindestgröße
        min_w, min_h = app._min_size
        assert (app.winfo_width(), app.winfo_height()) == (min_w, min_h)
        assert min_w >= m._legend.winfo_reqwidth() + 24
        assert _fully_visible(m._legend) and _fully_visible(m.warn_label)
        assert _wrap(m.warn_label) == app.winfo_width() - 24
        narrow = m.warn_label.winfo_reqheight()
        assert _check(app)["tracks"] >= 4
        _resize(app, min_w + 900, min_h + 100)
        assert _wrap(m.warn_label) == app.winfo_width() - 24
        assert _fully_visible(m.warn_label)
        wide = m.warn_label.winfo_reqheight()
        assert wide < narrow                    # weniger Zeilen …
        assert app._min_size[1] == min_h - (narrow - wide)   # … Minimum sinkt
        _check(app)


def test_gemerkte_breite_auf_einzelmonitor_begrenzt(make_app, tmp_path):
    # Einzelner Laptop-Monitor; die gemerkte Größe stammt von einem größeren
    screen = Rect(0, 0, 1366, 768)
    work = Rect(0, 0, 1366, 728)
    app = make_app(percent=100, work=work, monitor=screen, virtual=screen,
                   window_geometry="1586x1100+700+250")
    frame = app._measure_frame()
    left = app.winfo_x() + frame.dx
    right = left + frame.left + app.winfo_width() + frame.right
    assert work.x <= left and right <= work.x + work.w
    assert app.winfo_width() == client_limit(work, frame)[0]
    assert app._user_resized


def test_ueber_zwei_monitore_gezogenes_fenster_bleibt(make_app, tmp_path):
    monitor = Rect(0, 0, 1920, 1080)
    app = make_app(work=Rect(0, 0, 1920, 1040), monitor=monitor,
                   virtual=Rect(0, 0, 3840, 1080),
                   window_geometry="2500x900+100+50")
    assert app.winfo_width() == 2500
    assert app.winfo_x() == 100


def test_autosize_nutzt_arbeitsbereich_und_minimum(make_app, tmp_path):
    work = Rect(0, 0, 1600, 900)                # 1280×720 bei 125 %
    app = make_app(work=work)
    frame = app._measure_frame()
    # Leerzustand: klein und zentriert im Arbeitsbereich
    assert app.winfo_height() == app.main.needs().natural_h
    _load(app, tmp_path)
    lim_w, lim_h = client_limit(work, frame)
    assert app.main.needs().natural_h > lim_h
    assert app.winfo_height() == lim_h          # wächst bis zum Rand
    assert app.winfo_width() <= lim_w
    assert app.winfo_y() + frame.dy >= work.y
    assert (app.winfo_y() + frame.dy + frame.top + app.winfo_height()
            + frame.bottom) <= work.y + work.h
    _check(app)


def test_gemerkte_geometrie_auf_arbeitsbereich_begrenzt(make_app, tmp_path):
    work = Rect(0, 0, 1920, 1040)
    app = make_app(work=work, window_geometry="1500x1300+100+200")
    frame = app._measure_frame()
    assert app.winfo_width() == 1500            # Nutzergröße bleibt …
    assert app.winfo_height() == client_limit(work, frame)[1]   # … passt
    assert app.winfo_y() + frame.dy == work.y
    assert app._user_resized


def test_keine_rueckkopplung(make_app, tmp_path, monkeypatch):
    app = make_app()
    _load(app, tmp_path)
    m = app.main
    applied = []
    real_fit = type(m).fit

    def counting_fit(self, height):
        before = (self.file_list.tree.cget("height"),
                  self.track_table.tree.cget("height"),
                  self.log.body_shown, self.log.text.cget("height"))
        real_fit(self, height)
        after = (self.file_list.tree.cget("height"),
                  self.track_table.tree.cget("height"),
                  self.log.body_shown, self.log.text.cget("height"))
        applied.append(before != after)
    monkeypatch.setattr(type(m), "fit", counting_fit)
    for h in (1100, 866, 1000, 828):
        _resize(app, 1600, h)
        geometry, alloc = app.geometry(), m.allocation
        applied.clear()
        for _ in range(10):                     # Leerlauf: nichts ändert sich
            app.update()
            time.sleep(0.005)
        assert app.geometry() == geometry and m.allocation == alloc
        assert not any(applied) and app._fit_after is None


def test_aufklappen_ohne_platz_zeigt_nur_kopfzeile(make_app, tmp_path):
    app = make_app(log_expanded=False)
    _load(app, tmp_path)
    m = app.main
    _resize(app, 1600, 866)
    m.log.set_expanded(True)                    # synchron verteilt
    assert not m.log.body_shown
    assert "Fenster zu niedrig" in m.log._header.cget("text")
    _resize(app, 1600, 1118)                    # Platz → Text erscheint
    assert m.log.body_shown and m.allocation.log_lines == 9
    assert "Fenster zu niedrig" not in m.log._header.cget("text")
