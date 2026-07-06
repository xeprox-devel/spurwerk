"""Sprachcode-Normalisierung — inkl. der norwegischen Varianten nb/nn."""

from core.langs import display_name, normalize


class TestNormalize:
    def test_iso2_bibliografisch_und_terminologisch(self):
        assert normalize("ger") == "de"
        assert normalize("deu") == "de"
        assert normalize("nor") == "no"

    def test_norwegische_varianten(self):
        # mkvmerge liefert für Bokmål/Nynorsk „nob“/„nno“ (639-2) bzw.
        # „nb“/„nn“ (IETF) — beide Wege müssen im selben Code enden.
        assert normalize("nob") == "nb"
        assert normalize("nno") == "nn"
        assert normalize(None, "nb-NO") == "nb"
        assert normalize(None, "nn") == "nn"

    def test_ietf_hat_vorrang(self):
        assert normalize("ger", "en-US") == "en"

    def test_leer_ergibt_und(self):
        assert normalize(None) == "und"
        assert normalize("") == "und"


class TestDisplayName:
    def test_bekannte_codes(self):
        assert display_name("de") == "Deutsch"
        assert display_name("no") == "Norwegisch"

    def test_norwegische_varianten_haben_klarnamen(self):
        # kein roher Code in der UI
        assert display_name("nb") == "Norwegisch (Bokmål)"
        assert display_name("nn") == "Norwegisch (Nynorsk)"

    def test_unbekannter_code_bleibt_sichtbar(self):
        assert display_name("xx") == "xx"
