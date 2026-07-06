"""Fenster-Geometrie: Parsen und Klemmen auf den sichtbaren Bereich."""

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
        assert clamp_geometry("1000x700-50-50", 1920, 1080) \
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


class TestVirtuellerDesktop:
    """Multi-Monitor: der virtuelle Desktop kann einen negativen Ursprung
    haben (Zweitmonitor links/oben vom Primärmonitor)."""

    def test_fenster_auf_zweitmonitor_links_bleibt(self):
        # Desktop: 2×1920 nebeneinander, linker Monitor beginnt bei -1920
        assert clamp_geometry("1200x800-1920+60", 3840, 1080,
                              screen_x=-1920) == "1200x800-1920+60"

    def test_zu_weit_links_klemmt_an_virtuellen_rand(self):
        assert clamp_geometry("1000x700-5000+100", 3840, 1080,
                              screen_x=-1920) == "1000x700-1920+100"

    def test_zu_weit_rechts_klemmt_an_virtuellen_rand(self):
        # rechter Rand: -1920 + 3840 - 1000 = 920
        assert clamp_geometry("1000x700+5000+100", 3840, 1080,
                              screen_x=-1920) == "1000x700+920+100"

    def test_monitor_oberhalb_erlaubt_negatives_y(self):
        # Desktop: 2×1080 übereinander, oberer Monitor beginnt bei -1080
        assert clamp_geometry("1000x700+100-500", 1920, 2160,
                              screen_y=-1080) == "1000x700+100-500"

    def test_ein_monitor_fall_bleibt_unveraendert(self):
        # Ohne screen_x/screen_y gilt exakt das alte Verhalten
        assert clamp_geometry("1000x700-50-50", 1920, 1080,
                              screen_x=0, screen_y=0) == "1000x700+0+0"
