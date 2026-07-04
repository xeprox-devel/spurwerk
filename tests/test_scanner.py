"""Parser-Tests (ohne Prozessstart) + Sprachnormalisierung."""

from core.langs import display_name, normalize
from core.scanner import parse_mkvmerge_json

SAMPLE = {
    "container": {"recognized": True, "supported": True,
                  "properties": {"duration": 4_006_000_000, "title": "Test"}},
    "chapters": [{"num_entries": 2}],
    "attachments": [],
    "tracks": [
        {"id": 0, "type": "video", "codec": "AVC/H.264",
         "properties": {"codec_id": "V_MPEG4/ISO/AVC", "language": "und",
                        "language_ietf": "und", "minimum_timestamp": 0}},
        {"id": 1, "type": "audio", "codec": "AC-3",
         "properties": {"codec_id": "A_AC3", "language": "ger",
                        "language_ietf": "de", "audio_channels": 6,
                        "default_track": True, "forced_track": False,
                        "minimum_timestamp": 500_000_000,
                        "track_name": "Surround"}},
        {"id": 2, "type": "subtitles", "codec": "SubRip/SRT",
         "properties": {"codec_id": "S_TEXT/UTF8", "language": "fre",
                        "forced_track": True}},
    ],
}


def test_parse_vollstaendig():
    info = parse_mkvmerge_json(SAMPLE, "x.mkv")
    assert info.duration_s == 4.006
    assert info.has_chapters is True
    assert info.title == "Test"

    audio = info.track(1)
    assert audio.lang == "de"                 # language_ietf hat Vorrang
    assert audio.channels == 6
    assert audio.default is True
    assert audio.delay_ms == 500
    assert audio.is_multichannel

    sub = info.track(2)
    assert sub.lang == "fr"                   # "fre" → "fr" ohne ietf
    assert sub.forced is True

    assert info.ffmpeg_audio_index(1) == 0


def test_normalisierung():
    assert normalize("ger") == "de"
    assert normalize("deu") == "de"
    assert normalize("ger", "de-DE") == "de"
    assert normalize("jpn") == "ja"
    assert normalize(None) == "und"
    assert normalize("und", "und") == "und"
    assert normalize("xyz") == "xyz"          # unbekannt: unverändert lassen
    assert display_name("de") == "Deutsch"
