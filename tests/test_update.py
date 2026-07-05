"""Update-Prüfung: Versionsvergleich. Der Netzabruf (check_latest) wird
bewusst nicht getestet — er ist per Konstruktion fehlertolerant (None)."""

from core import update


class TestParseVersion:
    def test_mit_und_ohne_v_praefix(self):
        assert update.parse_version("v1.2.3") == (1, 2, 3)
        assert update.parse_version("1.2.3") == (1, 2, 3)

    def test_suffix_wird_abgeschnitten(self):
        assert update.parse_version("1.2.0-beta") == (1, 2, 0)
        assert update.parse_version("2.0") == (2, 0)

    def test_muell_ergibt_leer(self):
        assert update.parse_version("") == ()
        assert update.parse_version("abc") == ()


class TestIsNewer:
    def test_echt_neuer(self):
        assert update.is_newer("1.1.0", "1.0.1")
        assert update.is_newer("v1.1.0", "1.0.1")

    def test_numerisch_nicht_lexikografisch(self):
        # 1.10.0 ist neuer als 1.9.0 (Zahl, nicht String)
        assert update.is_newer("1.10.0", "1.9.0")

    def test_gleich_oder_aelter_ist_nicht_neuer(self):
        assert not update.is_newer("1.0.1", "1.0.1")
        assert not update.is_newer("1.0.0", "1.0.1")

    def test_leere_latest_ist_nie_neuer(self):
        assert not update.is_newer("", "1.0.0")
