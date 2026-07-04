"""End-to-End-Tests: echte Tools auf echten Fixture-MKVs.

Verifiziert die Ausgabe per erneutem `mkvmerge -J`-Scan — insbesondere
`channels == 2` auf jeder neuen Stereospur (Regressionsschutz gegen den
Altcode-Bug, bei dem „Stereo" real 5.1 blieb) und den erhaltenen
Startversatz (A/V-Sync).
"""

import queue
from pathlib import Path

import pytest

from core.model import FileStatus, StereoSettings
from core.planner import build_plan
from core.runner import JobRunner
from core.scanner import scan_file
from tests.helpers import profile_de

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {name: str(ROOT / "tools" / f"{name}.exe")
         for name in ("mkvmerge", "ffmpeg")}
FIXTURES = ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not (Path(TOOLS["mkvmerge"]).exists() and (FIXTURES / "film_std.mkv").exists()),
    reason="Tools oder Fixtures fehlen (tests/make_fixtures.py ausführen)")


def run_plan(fixture: str, profile, tmp_path: Path):
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / fixture))
    plan = build_plan(media, profile)   # Plan erbt profile.stereo als Kopie
    plan.output_path = str(tmp_path / f"out_{fixture}")
    runner = JobRunner(TOOLS, queue.Queue())
    ok = runner.run([plan]) == 1
    return plan, ok


def test_remux_only_verlustfrei(tmp_path):
    plan, ok = run_plan("film_std.mkv", profile_de(stereo_policy="never"),
                        tmp_path)
    assert ok, plan.error
    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    assert [t.type for t in out.tracks] == ["video", "audio", "subtitles"]
    audio = out.audio_tracks[0]
    assert audio.lang == "de"
    assert audio.codec_id == "A_AC3"       # unangetastet kopiert
    assert audio.channels == 6
    assert audio.default is True
    assert out.has_chapters                # Kapitel bleiben erhalten


def test_stereo_kopie_zusaetzlich(tmp_path):
    settings = StereoSettings(codec="ac3", bitrate="192k",
                              track_name="Stereo AC3")
    profile = profile_de()
    profile.stereo = settings
    plan, ok = run_plan("film_std.mkv", profile, tmp_path)
    assert ok, plan.error

    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    audios = out.audio_tracks
    assert len(audios) == 2
    original, stereo = audios              # Reihenfolge: Original, dann Stereo

    assert original.channels == 6
    assert original.default is False       # Flag ist gewandert
    assert stereo.channels == 2            # DER Regressionstest
    assert stereo.lang == "de"             # Sprache von der Quellspur geerbt
    assert stereo.name == "Stereo AC3"
    assert stereo.default is True

    subs = out.by_type("subtitles")
    assert len(subs) == 1 and subs[0].lang == "de"


def test_delay_bleibt_erhalten(tmp_path):
    plan, ok = run_plan("film_delay.mkv", profile_de(), tmp_path)
    assert ok, plan.error
    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    stereo = out.audio_tracks[-1]
    assert stereo.channels == 2
    assert abs(stereo.delay_ms - 500) <= 40   # --sync übertragen


def test_71_zu_dd51_konvertierung(tmp_path):
    """7.1-Quelle → E-AC3 5.1 als Kopie (Geräte-Kompatibilitäts-Fall)."""
    settings = StereoSettings(codec="eac3", channels="5.1", bitrate="640k",
                              track_name="E-AC3 5.1")
    profile = profile_de()
    profile.stereo = settings
    plan, ok = run_plan("film_71.mkv", profile, tmp_path)
    assert ok, plan.error

    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    audios = out.audio_tracks
    assert len(audios) == 2
    original, converted = audios
    assert original.channels == 8            # Original bleibt 7.1
    assert converted.channels == 6           # neue Spur ist echtes 5.1
    assert converted.codec_id == "A_EAC3"
    assert converted.name == "E-AC3 5.1"


def test_51_zu_dd51_formatwechsel(tmp_path):
    """AC3 5.1 → E-AC3 5.1: reiner Formatwechsel, Layout bleibt (DTS→DD-Fall)."""
    settings = StereoSettings(codec="eac3", channels="5.1", bitrate="640k",
                              track_name="E-AC3 5.1")
    profile = profile_de(stereo_policy="replace")
    profile.stereo = settings
    plan, ok = run_plan("film_std.mkv", profile, tmp_path)
    assert ok, plan.error

    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    converted = out.audio_tracks[0]
    assert converted.codec_id == "A_EAC3"
    assert converted.channels == 6


def test_dts_zu_dd51(tmp_path):
    """DTS 5.1 → E-AC3 5.1 als Kopie — der klassische DTS→DD-Fall."""
    settings = StereoSettings(codec="eac3", channels="5.1", bitrate="640k",
                              track_name="E-AC3 5.1")
    profile = profile_de()
    profile.stereo = settings
    plan, ok = run_plan("film_dts.mkv", profile, tmp_path)
    assert ok, plan.error

    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    audios = out.audio_tracks
    assert len(audios) == 2
    original, converted = audios
    assert original.codec_id == "A_DTS"      # Original bleibt DTS, bitgenau
    assert converted.codec_id == "A_EAC3"
    assert converted.channels == 6


def test_dts_zu_stereo(tmp_path):
    """DTS 5.1 → AC3 Stereo mit Downmix-Preset."""
    profile = profile_de()
    profile.stereo = StereoSettings(codec="ac3", channels="2.0",
                                    bitrate="192k", track_name="Stereo AC3")
    plan, ok = run_plan("film_dts.mkv", profile, tmp_path)
    assert ok, plan.error
    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    assert out.audio_tracks[-1].channels == 2


def test_kein_deutsch_fallback(tmp_path):
    plan, ok = run_plan("serie_nodeu.mkv", profile_de(), tmp_path)
    assert ok, plan.error
    assert any("Keine Audiospur" in w for w in plan.warnings)
    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    assert any(t.lang == "en" for t in out.audio_tracks)


def test_mkvmerge_fehler_wird_gemeldet(tmp_path):
    """Regression (Review-Fund 1): Subprozess-Exit-Codes dürfen nie
    verschluckt werden — kaputte Quelle ⇒ ERROR, nie DONE."""
    import dataclasses
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_std.mkv"))
    bad_src = tmp_path / "kaputt.mkv"
    bad_src.write_bytes(b"das ist kein matroska")
    plan = build_plan(dataclasses.replace(media, path=str(bad_src)),
                      profile_de(stereo_policy="never"))
    plan.output_path = str(tmp_path / "out.mkv")

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([plan]) == 0
    assert plan.status is FileStatus.ERROR
    assert "mkvmerge" in plan.error
    assert not Path(plan.output_path).exists()


def test_ffmpeg_fehler_wird_gemeldet(tmp_path):
    import dataclasses
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_std.mkv"))
    bad_src = tmp_path / "kaputt.mkv"
    bad_src.write_bytes(b"das ist kein matroska")
    plan = build_plan(dataclasses.replace(media, path=str(bad_src)),
                      profile_de())   # Stereo-Aktion ⇒ FFmpeg läuft zuerst
    plan.output_path = str(tmp_path / "out.mkv")

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([plan]) == 0
    assert plan.status is FileStatus.ERROR
    assert "FFmpeg" in plan.error


def test_altes_ergebnis_bleibt_bei_fruehem_fehler(tmp_path):
    """Regression (Review-Fund 8): Ein Fehler VOR dem Mux darf das intakte
    Ergebnis eines früheren Laufs nicht löschen."""
    import dataclasses
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_std.mkv"))
    bad_src = tmp_path / "kaputt.mkv"
    bad_src.write_bytes(b"kein matroska")
    old_output = tmp_path / "out.mkv"
    old_output.write_bytes(b"intaktes ergebnis von gestern")

    plan = build_plan(dataclasses.replace(media, path=str(bad_src)),
                      profile_de())   # FFmpeg scheitert vor dem Mux
    plan.output_path = str(old_output)

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([plan]) == 0
    assert plan.status is FileStatus.ERROR
    assert old_output.read_bytes() == b"intaktes ergebnis von gestern"


def test_ausgabe_kollision_im_batch(tmp_path):
    """Regression (Review-Fund): identischer Ausgabepfad zweier Dateien —
    die zweite darf das Ergebnis der ersten nicht überschreiben."""
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_std.mkv"))
    p1 = build_plan(media, profile_de(stereo_policy="never"))
    p2 = build_plan(media, profile_de(stereo_policy="never"))
    p1.output_path = str(tmp_path / "gleich.mkv")
    p2.output_path = str(tmp_path / "GLEICH.mkv")   # case-insensitiv gleich

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([p1, p2]) == 1
    assert p1.status is FileStatus.DONE
    assert p2.status is FileStatus.ERROR
    assert "kollidiert" in p2.error


def test_fehler_isoliert_pro_datei(tmp_path):
    """Kaputte Datei bricht den Batch nicht ab."""
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_und.mkv"))
    bad = build_plan(media, profile_de(stereo_policy="never"))
    bad.output_path = str(FIXTURES / "film_und.mkv")   # Ziel = Quelle → Fehler

    good = build_plan(media, profile_de(stereo_policy="never"))
    good.output_path = str(tmp_path / "gut.mkv")

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([bad, good]) == 1
    assert bad.status is FileStatus.ERROR
    assert good.status is FileStatus.DONE
    assert (FIXTURES / "film_und.mkv").stat().st_size > 0   # Quelle unversehrt


def test_batch_mit_config_pro_datei(tmp_path):
    """Job-Queue-Prinzip: zwei Dateien, zwei verschiedene Zielformate,
    EIN Start — jede wird mit ihrer eigenen Config verarbeitet."""
    m1 = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_std.mkv"))
    m2 = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_71.mkv"))

    p1 = build_plan(m1, profile_de())
    p1.stereo = StereoSettings(codec="ac3", channels="2.0", bitrate="192k",
                               track_name="Stereo AC3")
    p1.output_path = str(tmp_path / "a.mkv")

    p2 = build_plan(m2, profile_de())
    p2.stereo = StereoSettings(codec="eac3", channels="5.1", bitrate="640k",
                               track_name="E-AC3 5.1")
    p2.output_path = str(tmp_path / "b.mkv")

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([p1, p2]) == 2

    out1 = scan_file(TOOLS["mkvmerge"], p1.output_path).audio_tracks[-1]
    assert (out1.codec_id, out1.channels, out1.name) == ("A_AC3", 2,
                                                         "Stereo AC3")
    out2 = scan_file(TOOLS["mkvmerge"], p2.output_path).audio_tracks[-1]
    assert (out2.codec_id, out2.channels, out2.name) == ("A_EAC3", 6,
                                                         "E-AC3 5.1")
