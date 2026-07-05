"""Offline-Dateinamen-Bereinigung."""

from core.naming import clean_filename, clean_title


def test_release_name_nur_titel_ohne_jahr():
    raw = ("Obsession.Du.sollst.mich.lieben.2025.UHD.WEB-DL.2160p.HEVC.DV."
           "HDR10Plus.EAC3.DL.Remux-TvR.mkv")
    assert clean_filename(raw) == "Obsession Du sollst mich lieben.mkv"


def test_unterstriche_und_tags_ohne_jahr():
    assert clean_filename("Some_Movie_1080p_BluRay_x264-GRP.mkv") \
        == "Some Movie.mkv"


def test_jahr_erkennung():
    assert clean_title("Film.Title.2019.1080p")[1] == "2019"
    assert clean_title("Film.Title.1998.720p")[1] == "1998"


def test_endung_wird_uebernommen():
    assert clean_filename("X.Y.2021.2160p.mkv").endswith(".mkv")
    assert clean_filename("X.Y.2021.2160p.mkv", keep_ext=".mp4") \
        .endswith(".mp4")


def test_illegale_zeichen_entfernt():
    assert ":" not in clean_filename("A:B.2020.1080p.mkv")


def test_nichts_erkannt_bleibt_stabil():
    # kein Jahr, kein Tag → Titel unverändert (nur Punkte zu Leerzeichen)
    assert clean_filename("MeinUrlaubsvideo.mkv") == "MeinUrlaubsvideo.mkv"
