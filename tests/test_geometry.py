"""Fenster-Geometrie: Parsen und Klemmen auf den sichtbaren Bildschirm."""

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
