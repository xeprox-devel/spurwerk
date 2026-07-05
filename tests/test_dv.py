"""DV/HDR-Remux: Parser, Sperr-Logik, Kommandobau + End-to-End.

Der End-to-End-Test nutzt film_dv.mkv (synthetisches DV 8.1 via
dovi_tool inject-rpu) und prüft: nach Modus „hdr10" ist die DOVI-
Signalisierung weg, HDR10 (PQ) bleibt, Audio bleibt 1:1.
"""

import queue
from pathlib import Path

import pytest

from core import dv
from core.commands import build_mkvmerge_mux
from core.model import StereoSettings
from core.planner import build_plan
from core.runner import JobRunner
from core.scanner import scan_file
from tests.helpers import film_std, profile_de

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {name: str(ROOT / "tools" / f"{name}.exe")
         for name in ("mkvmerge", "ffmpeg", "ffprobe", "dovi_tool")}
FIXTURES = ROOT / "tests" / "fixtures"
DV_FIXTURE = FIXTURES / "film_dv.mkv"


class TestParser:
    def test_profil7_erkennung(self):
        info = dv.parse_stream({
            "codec_name": "hevc", "color_transfer": "smpte2084",
            "side_data_list": [{
                "side_data_type": "DOVI configuration record",
                "dv_profile": 7, "el_present_flag": 1,
                "bl_present_flag": 1, "dv_bl_signal_compatibility_id": 6}],
        })
        assert info.dv_profile == 7 and info.el_present and info.hdr10
        assert "Profil 7" in info.describe() and "BL+EL+RPU" in info.describe()
        assert info.hdr10_blocked_reason() is None
        assert info.dv81_blocked_reason() is None

    def test_profil5_sperrt_hdr10(self):
        info = dv.parse_stream({
            "codec_name": "hevc",
            "side_data_list": [{
                "side_data_type": "DOVI configuration record",
                "dv_profile": 5, "el_present_flag": 0,
                "bl_present_flag": 1}],
        })
        assert "Profil 5" in info.hdr10_blocked_reason()
        assert info.dv81_blocked_reason() is not None

    def test_kein_dv(self):
        info = dv.parse_stream({"codec_name": "hevc",
                                "color_transfer": "smpte2084"})
        assert not info.has_dv and info.hdr10
        assert "nichts zu entfernen" in info.hdr10_blocked_reason()

    def test_avc_gesperrt(self):
        info = dv.parse_stream({"codec_name": "h264"})
        assert "HEVC" in info.hdr10_blocked_reason()


class TestMuxMitVideoErsatz:
    def test_video_file_ersetzt_quellvideo(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {},
                                 video_file="C:/tmp/clean.hevc")
        assert "--no-video" in cmd
        assert "--video-tracks" not in cmd
        assert cmd.index("C:/tmp/clean.hevc") < cmd.index("C:/filme/test.mkv")
        order = cmd[cmd.index("--track-order") + 1]
        assert order == "0:0,1:1,1:4"   # Video=Datei0, Audio/Sub aus Datei1

    def test_video_file_mit_stereo(self):
        plan = build_plan(film_std(), profile_de())
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/tmp/s.ac3"},
                                 video_file="C:/tmp/clean.hevc")
        order = cmd[cmd.index("--track-order") + 1]
        assert order == "0:0,1:1,2:0,1:4"   # Stereo-Datei rückt auf fid 2


class TestMp4Kommando:
    def test_dv_mp4_video_und_audio(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        cmd, warns = dv.build_ffmpeg_dv_mp4(
            "ffmpeg", "C:/tmp/dv81.hevc", plan, {}, "out.mp4")
        # Video mit DV-RPU-Filter, dvh1-Tag
        assert "dovi_rpu" in cmd and "-strict" in cmd
        assert cmd[cmd.index("-tag:v") + 1] == "dvh1"
        # AC3 (5.1 de) ist MP4-tauglich → copy, keine Warnung
        assert "-map" in cmd and "1:a:0" in cmd
        assert warns == []
        assert cmd[-1] == "out.mp4"
        assert cmd[cmd.index("-map_chapters") + 1] == "1"

    def test_incompatible_audio_wird_transkodiert(self):
        from tests.helpers import media, track
        m = media(track(0, "video", codec="V_MPEGH/ISO/HEVC"),
                  track(1, "audio", "de", codec="A_TRUEHD", channels=8))
        plan = build_plan(m, profile_de(stereo_policy="never"))
        cmd, warns = dv.build_ffmpeg_dv_mp4(
            "ffmpeg", "C:/tmp/v.hevc", plan, {}, "out.mp4")
        assert "eac3" in cmd                        # TrueHD → E-AC3
        assert any("nicht MP4-tauglich" in w for w in warns)

    def test_bild_untertitel_werden_weggelassen(self):
        from tests.helpers import media, track
        m = media(track(0, "video", codec="V_MPEGH/ISO/HEVC"),
                  track(1, "audio", "de", codec="A_AC3", channels=6),
                  track(2, "subtitles", "de", codec="S_HDMV/PGS"))
        plan = build_plan(m, profile_de(sub_policy="all",
                                        stereo_policy="never"))
        cmd, warns = dv.build_ffmpeg_dv_mp4(
            "ffmpeg", "C:/tmp/v.hevc", plan, {}, "out.mp4")
        assert "mov_text" not in cmd                # PGS nicht muxbar
        assert any("nicht MP4-tauglich" in w for w in warns)


needs_dv_stack = pytest.mark.skipif(
    not (DV_FIXTURE.exists() and Path(TOOLS["dovi_tool"]).exists()
         and Path(TOOLS["ffprobe"]).exists()),
    reason="film_dv.mkv oder dovi_tool/ffprobe fehlen")


@needs_dv_stack
class TestEndToEnd:
    def test_analyse_erkennt_dv(self):
        info = dv.analyze(TOOLS["ffprobe"], str(DV_FIXTURE))
        assert info.is_hevc
        assert info.dv_profile == 8
        assert info.hdr10                      # PQ-Signalisierung
        assert info.hdr10_blocked_reason() is None

    def test_hdr10_strip_verlustfrei(self, tmp_path):
        media = scan_file(TOOLS["mkvmerge"], str(DV_FIXTURE))
        plan = build_plan(media, profile_de(stereo_policy="never"))
        plan.dv = dv.analyze(TOOLS["ffprobe"], str(DV_FIXTURE))
        plan.video_mode = dv.VIDEO_MODE_HDR10
        plan.output_path = str(tmp_path / "out [HDR10].mkv")

        runner = JobRunner(TOOLS, queue.Queue())
        assert runner.run([plan]) == 1, plan.error

        # DV weg, HDR10 (PQ) bleibt, Audio 1:1 erhalten
        out_info = dv.analyze(TOOLS["ffprobe"], plan.output_path)
        assert not out_info.has_dv
        assert out_info.hdr10
        out_media = scan_file(TOOLS["mkvmerge"], plan.output_path)
        assert len(out_media.audio_tracks) == 1
        assert out_media.audio_tracks[0].codec_id == "A_AC3"
        assert abs(out_media.duration_s - media.duration_s) < 1.0

    def test_p5_wird_vom_runner_geblockt(self, tmp_path):
        import dataclasses
        media = scan_file(TOOLS["mkvmerge"], str(DV_FIXTURE))
        plan = build_plan(media, profile_de(stereo_policy="never"))
        plan.dv = dataclasses.replace(
            dv.analyze(TOOLS["ffprobe"], str(DV_FIXTURE)), dv_profile=5)
        plan.video_mode = dv.VIDEO_MODE_HDR10
        plan.output_path = str(tmp_path / "out.mkv")

        runner = JobRunner(TOOLS, queue.Queue())
        assert runner.run([plan]) == 0
        assert "Profil 5" in plan.error
        assert not Path(plan.output_path).exists()

    def test_dv81_mp4_mit_ffmpeg(self, tmp_path):
        """Modus A ohne MP4Box: DV-8.1-MP4 mit gültiger dvvC-Box, Audio drin,
        Video bitgenau (nur Metadaten/Container geändert)."""
        media = scan_file(TOOLS["mkvmerge"], str(DV_FIXTURE))
        plan = build_plan(media, profile_de(stereo_policy="never"))
        plan.dv = dv.analyze(TOOLS["ffprobe"], str(DV_FIXTURE))
        plan.video_mode = dv.VIDEO_MODE_DV81
        plan.output_path = str(tmp_path / "out [DV8.1].mp4")

        runner = JobRunner(TOOLS, queue.Queue())
        assert runner.run([plan]) == 1, plan.error

        out = dv.analyze(TOOLS["ffprobe"], plan.output_path)
        assert out.is_hevc
        assert out.dv_profile == 8          # dvvC-Box vorhanden, Profil 8
        assert not out.el_present
        # Audio ist im MP4 gelandet
        import json
        import subprocess
        data = json.loads(subprocess.run(
            [TOOLS["ffprobe"], "-v", "quiet", "-print_format", "json",
             "-show_streams", plan.output_path],
            capture_output=True, text=True).stdout)
        kinds = [s["codec_type"] for s in data["streams"]]
        assert "video" in kinds and "audio" in kinds

    def test_dv81_erzwingt_mp4_endung(self, tmp_path):
        """Regression: dv81 mit fälschlich .mkv-Ausgabepfad (z. B. nach
        Profilwechsel) muss trotzdem ein gültiges MP4 erzeugen — der
        dvh1-Tag scheitert sonst im Matroska-Muxer."""
        media = scan_file(TOOLS["mkvmerge"], str(DV_FIXTURE))
        plan = build_plan(media, profile_de(stereo_policy="never"))
        plan.dv = dv.analyze(TOOLS["ffprobe"], str(DV_FIXTURE))
        plan.video_mode = dv.VIDEO_MODE_DV81
        plan.output_path = str(tmp_path / "falsch.mkv")   # falsche Endung!

        runner = JobRunner(TOOLS, queue.Queue())
        assert runner.run([plan]) == 1, plan.error
        assert plan.output_path.endswith(".mp4")          # korrigiert
        assert Path(plan.output_path).exists()
        assert not (tmp_path / "falsch.mkv").exists()
