"""Fenster-Geometrie: Parsen und Klemmen auf den sichtbaren Bereich."""

import tkinter

import pytest

from ui.geometry import clamp_geometry


class TestClampGeometry:
    def test_sichtbare_geometrie_bleibt(self):
        assert clamp_geometry("1200x800+100+50", 1920, 1080) \
            == "1200x800+100+50"

    def test_offscreen_wird_hereingeholt(self):
        # Monitor abgesteckt: Fenster lag weit rechts/unten → zurück auf Screen
        assert clamp_geometry("1000x700+5000+3000", 1920, 1080) \
            == "1000x700+920+380"

    def test_negative_position_landet_bei_null(self):
        assert clamp_geometry("1000x700+-50+-50", 1920, 1080) \
            == "1000x700+0+0"

    def test_groesse_auf_screen_gedeckelt(self):
        assert clamp_geometry("3000x2000+0+0", 1920, 1080) \
            == "1920x1080+0+0"

    def test_minimum_wird_gehalten(self):
        assert clamp_geometry("100x100+0+0", 1920, 1080) == "900x420+0+0"

    def test_unbrauchbar_ergibt_none(self):
        assert clamp_geometry("", 1920, 1080) is None
        assert clamp_geometry("kaputt", 1920, 1080) is None
        assert clamp_geometry("1200x800", 1920, 1080) is None   # ohne Position
        assert clamp_geometry("0x0+0+0", 1920, 1080) is None

    def test_abstand_vom_rechten_rand_ist_keine_position(self):
        # „-1500+100“ heißt in Tk „1500 px vom RECHTEN Rand“ (gemessen:
        # landet bei x=651 auf einem 2560er-Monitor) — nie als x=-1500 lesen
        assert clamp_geometry("1000x700-1500+100", 3840, 1080,
                              screen_x=-1920) is None
        assert clamp_geometry("1000x700+100-500", 1920, 2160,
                              screen_y=-1080) is None


class TestVirtuellerDesktop:
    """Multi-Monitor: der virtuelle Desktop kann einen negativen Ursprung
    haben (Zweitmonitor links/oben vom Primärmonitor). Tk schreibt solche
    Positionen als „+-1920+60“ — genau diese Form wird gespeichert."""

    def test_fenster_auf_zweitmonitor_links_bleibt(self):
        # Desktop: 2×1920 nebeneinander, linker Monitor beginnt bei -1920
        assert clamp_geometry("1200x800+-1920+60", 3840, 1080,
                              screen_x=-1920) == "1200x800+-1920+60"

    def test_zu_weit_links_klemmt_an_virtuellen_rand(self):
        assert clamp_geometry("1000x700+-5000+100", 3840, 1080,
                              screen_x=-1920) == "1000x700+-1920+100"

    def test_zu_weit_rechts_klemmt_an_virtuellen_rand(self):
        # rechter Rand: -1920 + 3840 - 1000 = 920
        assert clamp_geometry("1000x700+5000+100", 3840, 1080,
                              screen_x=-1920) == "1000x700+920+100"

    def test_monitor_oberhalb_erlaubt_negatives_y(self):
        # Desktop: 2×1080 übereinander, oberer Monitor beginnt bei -1080
        assert clamp_geometry("1000x700+100+-500", 1920, 2160,
                              screen_y=-1080) == "1000x700+100+-500"

    def test_ein_monitor_fall_bleibt_unveraendert(self):
        # Ohne screen_x/screen_y gilt exakt das alte Verhalten
        assert clamp_geometry("1000x700+-50+-50", 1920, 1080,
                              screen_x=0, screen_y=0) == "1000x700+0+0"


def test_rundlauf_mit_echtem_tk():
    """Was Tk für ein Fenster links vom Hauptmonitor schreibt, wird
    unverändert wieder gelesen (Format am 29.09.2026 real gemessen)."""
    try:
        root = tkinter.Tk()
    except tkinter.TclError:   # kein Display
        pytest.skip("Tk nicht verfügbar")
    try:
        root.withdraw()
        root.geometry("400x300+-1500+100")
        root.update_idletasks()
        saved = root.geometry()
    finally:
        root.destroy()
    assert saved.endswith("+-1500+100")
    assert clamp_geometry(saved, 8320, 3840, min_w=100, min_h=100,
                          screen_x=-1920, screen_y=-1200) == saved
