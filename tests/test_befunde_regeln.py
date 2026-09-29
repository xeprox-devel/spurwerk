"""Regressionstests zu den Prüfbefunden im Regel-/Namensbereich
(Kommentar-Filter, Titel-Bereinigung, TMDb-Key-Rückfall) — ohne Netz."""

import io
import json
import urllib.error
import urllib.parse
from datetime import date

import pytest

from core import naming, tmdb
from core.model import Action
from core.planner import build_plan, is_commentary
from core.profiles import builtin_profiles
from tests.helpers import media, track


# ── Kommentar-Filter: „Director's Cut“ ist keine Kommentarspur ────────────


def _profil(name):
    return next(p for p in builtin_profiles() if p.name == name)


def _directors_cut():
    return media(
        track(0, "video"),
        track(1, "audio", "de", channels=6,
              name="Deutsch DTS-HD MA 5.1 (Director's Cut)"),
        track(2, "audio", "en", channels=6, name="English 5.1"),
        track(3, "audio", "en", channels=2, name="Director's Commentary"))


@pytest.mark.parametrize("name", [
    "Deutsch DTS-HD MA 5.1 (Director's Cut)", "Directors Cut",
    "Director’s Cut", "Director's Fassung", "Regiefassung",
    "Extended Director's Cut", "Surround"])
def test_directors_cut_ist_kein_kommentar(name):
    assert not is_commentary(track(1, "audio", "de", name=name))


@pytest.mark.parametrize("name", [
    "Kommentar", "Audiokommentar", "Regiekommentar", "Commentary",
    "Director's Commentary", "Directors Comment", "Director’s Audio Comments"])
def test_kommentar_wird_erkannt(name):
    assert is_commentary(track(1, "audio", "de", name=name))


def test_deutsch_englisch_behaelt_deutsche_directors_cut_spur():
    plan = build_plan(_directors_cut(), _profil("Deutsch + Englisch"))
    assert plan.decisions[1].action is Action.STEREO_ADD   # de bleibt Top
    assert plan.decisions[2].action is Action.COPY
    assert plan.decisions[3].action is Action.DROP         # echter Kommentar
    assert plan.default_audio_source == 1
    assert plan.warnings == []


def test_deutsch_bevorzugt_ohne_widerspruechliche_warnung():
    plan = build_plan(_directors_cut(), _profil("Deutsch bevorzugt"))
    assert plan.decisions[1].action is Action.STEREO_ADD
    assert not any("Keine Audiospur" in w for w in plan.warnings)


# ── Titel-Bereinigung: Jahreszahl IM Titel ────────────────────────────────


@pytest.fixture
def heute_2026(monkeypatch):
    class _Datum(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 29)
    monkeypatch.setattr(naming, "date", _Datum)


@pytest.mark.parametrize("stem, erwartet", [
    ("Blade.Runner.2049.2017.German.DL.2160p.UHD.BluRay.HEVC-GRP",
     ("Blade Runner 2049", "2017")),
    ("Wonder.Woman.1984.2020.German.DL.2160p.WEB.h265",
     ("Wonder Woman 1984", "2020")),
    ("Space.1999.1975.German.DL.1080p.BluRay.x264", ("Space 1999", "1975")),
    ("2001.A.Space.Odyssey.1968.German.1080p", ("2001 A Space Odyssey", "1968")),
    ("1917.2019.German.DL.1080p", ("1917", "2019")),
    ("Film.2025", ("Film", "2025")),                    # Jahr direkt vor Endung
    ("Film (2020) [1080p]", ("Film", "2020")),
    ("Film [2160p]", ("Film", None)),                   # keine offene Klammer
    ("Film.(2160p)", ("Film", None)),
    ("Die.Hard.1988.Remastered.1080p", ("Die Hard", "1988")),
    # 2049 ist (noch) kein plausibles Erscheinungsjahr → gehört zum Titel
    ("Blade.Runner.2049.German.DL.2160p", ("Blade Runner 2049", None)),
    ("Pokemon.2000.Die.Macht.des.Einzelnen.1999.German.DL.1080p",
     ("Pokemon 2000 Die Macht des Einzelnen", "1999")),
    # Tag-Wörter im Titel beenden ihn nicht, solange ein Jahr folgt
    ("The.English.Patient.1996", ("The English Patient", "1996")),
    ("The.Good.German.2006.German.1080p", ("The Good German", "2006")),
    ("Internal.Affairs.1990", ("Internal Affairs", "1990")),
])
def test_clean_title_jahr_im_titel(heute_2026, stem, erwartet):
    assert naming.clean_title(stem) == erwartet


@pytest.mark.parametrize("stem, erwartet", [
    # Auf das frühere Jahr folgt schon ein Tag → es ist das Erscheinungsjahr
    ("Film.1999.Extended.2020.1080p", ("Film", "1999")),
    ("Das.Boot.1981.Directors.Cut.1997.German.1080p", ("Das Boot", "1981")),
    # Hinter Auflösung/Codec steht kein Titeljahr mehr
    ("Film.1080p.2020", ("Film", None)),
    ("Film.1080p.2020.German", ("Film", None)),
    ("Film.2019.1080p.2020", ("Film", "2019")),
    ("Film.Directors.Cut.German.1080p", ("Film", None)),
])
def test_clean_title_spaeteres_jahr_nach_tags(heute_2026, stem, erwartet):
    assert naming.clean_title(stem) == erwartet


def test_clean_filename_faelle(heute_2026):
    assert naming.clean_filename(
        "Blade.Runner.2049.2017.German.DL.2160p.mkv") == "Blade Runner 2049.mkv"
    assert naming.clean_filename("Film.2025.mkv") == "Film.mkv"
    assert naming.clean_filename("Film [2160p].mkv") == "Film.mkv"


# ── TMDb: kein beliebiger Treffer beim Rückfall ohne Jahr ─────────────────


def _suche(ohne_jahr):
    """Mit Jahr: nichts. Ohne Jahr: die übergebene Liste."""
    calls = []

    def fake(api_key, query, year=None, lang="de-DE", timeout=8.0):
        calls.append((query, year))
        return [] if year else ohne_jahr
    return fake, calls


def test_rueckfall_ohne_jahr_nimmt_keinen_fremden_film(monkeypatch):
    fake, calls = _suche([{"title": "Blade Runner",
                           "release_date": "1982-06-25"}])
    monkeypatch.setattr(tmdb, "search_movie", fake)
    got = tmdb.canonical_name(
        "KEY", "Blade.Runner.2049.2017.German.DL.2160p.mkv")
    assert got is None
    assert calls == [("Blade Runner 2049", "2017"), ("Blade Runner 2049", None)]


def test_rueckfall_ohne_jahr_mit_passendem_titel(monkeypatch):
    fake, _ = _suche([
        {"title": "Space Cowboys", "release_date": "2000-08-04"},
        {"title": "Mondbasis Alpha 1", "original_title": "Space: 1999",
         "release_date": "1975-09-04"}])
    monkeypatch.setattr(tmdb, "search_movie", fake)
    got = tmdb.canonical_name("KEY", "Space.1999.1976.German.DL.1080p.mkv")
    assert got == "Mondbasis Alpha 1"         # über den Originaltitel gefunden


def test_rueckfall_titelvergleich_mit_umlauten(monkeypatch):
    fake, _ = _suche([{"title": "Die Schöne und das Biest",
                       "release_date": "2017-03-16"}])
    monkeypatch.setattr(tmdb, "search_movie", fake)
    got = tmdb.canonical_name("KEY", "Die.Schoene.und.das.Biest.2016.mkv")
    assert got == "Die Schöne und das Biest"


@pytest.mark.parametrize("datei, titel", [
    ("Die.fabelhafte.Welt.der.Amelie.2002.German.1080p.mkv",
     "Die fabelhafte Welt der Amélie"),
    ("Fast.and.Furious.10.2022.German.2160p.mkv", "Fast & Furious 10"),
    ("Tom.und.Jerry.2020.German.1080p.mkv", "Tom & Jerry"),
])
def test_rueckfall_titelvergleich_akzente_und_kaufmanns_und(
        monkeypatch, datei, titel):
    fake, _ = _suche([{"title": "Irgendein anderer Film"},
                      {"title": titel, "release_date": "2001-04-25"}])
    monkeypatch.setattr(tmdb, "search_movie", fake)
    assert tmdb.canonical_name("KEY", datei) == titel


def test_titelvergleich_bleibt_exakt():
    assert tmdb._pick_by_title([{"title": "Blade Runner"}],
                               "Blade Runner 2049") is None
    assert tmdb._norm("Léon – Der Profi") == tmdb._norm("Leon Der Profi")


# ── TMDb: abgelehnter eigener Key → eingebauter Key ───────────────────────


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def netz(monkeypatch):
    """Falsches urlopen: Keys in `abgelehnt` → 401, `fehler` → 500."""
    monkeypatch.setattr(tmdb, "_rejected", set())
    monkeypatch.setattr(tmdb, "_notices", [])
    state = {"abgelehnt": {"FALSCH"}, "fehler": set(), "keys": []}

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        key = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["api_key"][0]
        state["keys"].append(key)
        if key in state["abgelehnt"]:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
        if key in state["fehler"]:
            raise urllib.error.HTTPError(url, 500, "Server Error", None, None)
        body = {"results": [{"title": f"Treffer {key}",
                             "release_date": "2020-01-01"}]}
        return _Antwort(json.dumps(body).encode("utf-8"))
    monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_urlopen)
    return state


def test_401_faellt_auf_eingebauten_key_zurueck(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "EINGEBAUT")
    got = tmdb.search_movie("FALSCH", "Film")
    assert got[0]["title"] == "Treffer EINGEBAUT"
    assert netz["keys"] == ["FALSCH", "EINGEBAUT"]
    notice = tmdb.take_notice()
    assert "eigenen API-Key" in notice and "eingebaute Key" in notice
    assert tmdb.take_notice() is None               # genau einmal
    # Der abgelehnte Key wird in dieser Sitzung nicht erneut gefragt
    tmdb.search_movie("FALSCH", "Film")
    assert netz["keys"] == ["FALSCH", "EINGEBAUT", "EINGEBAUT"]
    assert tmdb.take_notice() is None


def test_canonical_name_mit_abgelehntem_key(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "EINGEBAUT")
    assert tmdb.canonical_name("FALSCH", "Film.2020.mkv") == "Treffer EINGEBAUT"


def test_401_ohne_eingebauten_key_meldet_offline(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "")
    assert tmdb.search_movie("FALSCH", "Film") == []
    assert netz["keys"] == ["FALSCH"]
    assert "offline" in tmdb.take_notice()
    assert tmdb.search_movie("FALSCH", "Film") == []
    assert netz["keys"] == ["FALSCH"]               # kein erneuter Versuch


def test_eingebauter_key_abgelehnt(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "EINGEBAUT")
    netz["abgelehnt"].add("EINGEBAUT")
    assert tmdb.search_movie("EINGEBAUT", "Film") == []
    assert netz["keys"] == ["EINGEBAUT"]
    assert "eingebauten API-Key" in tmdb.take_notice()


def test_anderer_http_fehler_ist_keine_ablehnung(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "EINGEBAUT")
    netz["fehler"].add("MEINER")
    assert tmdb.search_movie("MEINER", "Film") == []
    assert netz["keys"] == ["MEINER"]               # kein Key-Wechsel bei 500
    assert tmdb.take_notice() is None
    assert tmdb._rejected == set()


def test_gueltiger_eigener_key_hat_vorrang(monkeypatch, netz):
    monkeypatch.setattr(tmdb, "BUILTIN_KEY", "EINGEBAUT")
    assert tmdb.search_movie("MEINER", "Film")[0]["title"] == "Treffer MEINER"
    assert netz["keys"] == ["MEINER"]
    assert tmdb.take_notice() is None
