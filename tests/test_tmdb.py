"""TMDb-Titelabgleich: Auswahl-Logik + Robustheit (ohne echtes Netz)."""

from core import tmdb


SAMPLE = [
    {"id": 1, "title": "Obsession – Du sollst mich lieben",
     "original_title": "Obsession", "release_date": "2025-06-20"},
    {"id": 2, "title": "Obsession", "original_title": "Obsession",
     "release_date": "1976-08-01"},
]


def test_pick_bevorzugt_jahr():
    assert tmdb._pick(SAMPLE, "2025")["id"] == 1
    assert tmdb._pick(SAMPLE, "1976")["id"] == 2


def test_pick_ohne_jahr_nimmt_erstes():
    assert tmdb._pick(SAMPLE, None)["id"] == 1


def test_pick_leer():
    assert tmdb._pick([], "2025") is None


def test_canonical_name_baut_titel(monkeypatch):
    monkeypatch.setattr(tmdb, "search_movie",
                        lambda *a, **k: SAMPLE)
    got = tmdb.canonical_name(
        "KEY",
        "Obsession.Du.sollst.mich.lieben.2025.UHD.WEB-DL.2160p.HEVC.mkv")
    assert got == "Obsession – Du sollst mich lieben (2025)"


def test_ohne_key_kein_call():
    # search_movie ohne Key liefert [] ohne Netzzugriff
    assert tmdb.search_movie("", "irgendwas") == []


def test_resolved_key_vorrang(monkeypatch):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "builtin")
    assert tmdb.resolved_key("meiner") == "meiner"   # Nutzer-Key gewinnt
    assert tmdb.resolved_key("") == "builtin"         # sonst eingebauter
    assert tmdb.resolved_key("  ") == "builtin"


def test_resolved_key_leer_wenn_nichts(monkeypatch):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "")
    assert tmdb.resolved_key("") == ""


def test_netzfehler_liefert_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("kein Netz")
    monkeypatch.setattr(tmdb.urllib.request, "urlopen", boom)
    assert tmdb.search_movie("KEY", "Film") == []          # wirft nicht
    assert tmdb.canonical_name("KEY", "Film.2020.mkv") is None


def test_illegale_zeichen_raus(monkeypatch):
    monkeypatch.setattr(tmdb, "search_movie", lambda *a, **k: [
        {"title": "A: B / C", "release_date": "2020-01-01"}])
    got = tmdb.canonical_name("KEY", "A.B.C.2020.mkv")
    assert ":" not in got and "/" not in got
