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
    plan = build_plan(media, profile)
    plan.output_path = str(tmp_path / f"out_{fixture}")
    runner = JobRunner(TOOLS, queue.Queue())
    ok = runner.run([plan], profile.stereo) == 1
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


def test_kein_deutsch_fallback(tmp_path):
    plan, ok = run_plan("serie_nodeu.mkv", profile_de(), tmp_path)
    assert ok, plan.error
    assert any("Keine Audiospur" in w for w in plan.warnings)
    out = scan_file(TOOLS["mkvmerge"], plan.output_path)
    assert any(t.lang == "en" for t in out.audio_tracks)


def test_fehler_isoliert_pro_datei(tmp_path):
    """Kaputte Datei bricht den Batch nicht ab."""
    media = scan_file(TOOLS["mkvmerge"], str(FIXTURES / "film_und.mkv"))
    bad = build_plan(media, profile_de(stereo_policy="never"))
    bad.output_path = str(FIXTURES / "film_und.mkv")   # Ziel = Quelle → Fehler

    good = build_plan(media, profile_de(stereo_policy="never"))
    good.output_path = str(tmp_path / "gut.mkv")

    runner = JobRunner(TOOLS, queue.Queue())
    assert runner.run([bad, good], StereoSettings()) == 1
    assert bad.status is FileStatus.ERROR
    assert good.status is FileStatus.DONE
    assert (FIXTURES / "film_und.mkv").stat().st_size > 0   # Quelle unversehrt
