"""DV/HDR-Remux: Parser, Sperr-Logik, Kommandobau + End-to-End.

Der End-to-End-Test nutzt film_dv.mkv (synthetisches DV 8.1 via
dovi_tool inject-rpu) und prüft: nach Modus „hdr10“ ist die DOVI-
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

    def test_profil5_sperrt_hdr10(self):
        info = dv.parse_stream({
            "codec_name": "hevc",
            "side_data_list": [{
                "side_data_type": "DOVI configuration record",
                "dv_profile": 5, "el_present_flag": 0,
                "bl_present_flag": 1}],
        })
        assert "Profil 5" in info.hdr10_blocked_reason()

    def test_kein_dv(self):
        info = dv.parse_stream({"codec_name": "hevc",
                                "color_transfer": "smpte2084"})
        assert not info.has_dv and info.hdr10
        assert "nichts zu entfernen" in info.hdr10_blocked_reason()

    def test_avc_gesperrt(self):
        info = dv.parse_stream({"codec_name": "h264"})
        assert "HEVC" in info.hdr10_blocked_reason()

    def test_frame_rate_wird_erfasst(self):
        info = dv.parse_stream({"codec_name": "hevc",
                                "r_frame_rate": "24000/1001"})
        assert info.frame_rate == "24000/1001"

    def test_ohne_frame_rate_leer(self):
        info = dv.parse_stream({"codec_name": "hevc"})
        assert info.frame_rate == ""


class TestDefaultDuration:
    """Timing-Absicherung: exakte Bildrate nur bei Standard-Raten."""

    def test_standard_raten_exakt(self):
        assert dv.default_duration_arg("24000/1001") == "24000/1001fps"
        assert dv.default_duration_arg("25/1") == "25/1fps"
        assert dv.default_duration_arg("30000/1001") == "30000/1001fps"
        assert dv.default_duration_arg("60/1") == "60/1fps"

    def test_exotische_rate_wird_verworfen(self):
        # kein Erzwingen bei ungewöhnlichen Raten (lieber mkvmerge lassen)
        assert dv.default_duration_arg("1000/1") is None
        assert dv.default_duration_arg("15/1") is None

    def test_unbrauchbar_ergibt_none(self):
        assert dv.default_duration_arg("") is None
        assert dv.default_duration_arg("24") is None      # kein Bruch
        assert dv.default_duration_arg("24/0") is None    # Nenner 0
        assert dv.default_duration_arg("abc/def") is None


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

    def test_default_duration_bei_bekannter_bildrate(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        plan.dv = dv.DVInfo(codec="hevc", frame_rate="24000/1001")
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {},
                                 video_file="C:/tmp/clean.hevc")
        assert cmd[cmd.index("--default-duration") + 1] == "0:24000/1001fps"
        # muss VOR der Video-Eingabedatei stehen
        assert cmd.index("--default-duration") < cmd.index("C:/tmp/clean.hevc")

    def test_keine_default_duration_ohne_dv_info(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {},
                                 video_file="C:/tmp/clean.hevc")
        assert "--default-duration" not in cmd


class TestEndungsNormalisierung:
    """Die Ausgabe ist immer eine MKV — eine fremde Endung (z. B. manuell
    gesetztes „X.mp4“) wird VOR der Kollisionsprüfung auf „.mkv“
    normalisiert, damit die Prüfung die echten Ausgabepfade sieht."""

    def _plan(self, path: str, out: str, mode: str):
        from tests.helpers import media, track
        m = media(track(0, "video", codec="V_MPEGH/ISO/HEVC"),
                  track(1, "audio", "de", codec="A_AC3", channels=6),
                  path=path)
        plan = build_plan(m, profile_de(stereo_policy="never"))
        plan.video_mode = mode
        plan.output_path = out
        return plan

    def test_fremde_endung_wird_mkv(self):
        plan = self._plan("C:/in/a.mkv", "C:/out/Film.mp4",
                          dv.VIDEO_MODE_COPY)
        JobRunner.normalize_output_extension(plan)
        assert plan.output_path.endswith(".mkv")

    def test_hdr10_modus_bleibt_mkv(self):
        plan = self._plan("C:/in/a.mkv", "C:/out/Film.mkv",
                          dv.VIDEO_MODE_HDR10)
        JobRunner.normalize_output_extension(plan)
        assert plan.output_path == "C:/out/Film.mkv"   # unverändert

    def test_kollision_nach_normalisierung_erkannt(self):
        import queue as q
        from core.model import FileStatus
        a = self._plan("C:/in/a.mkv", "C:/out/Film.mkv", dv.VIDEO_MODE_COPY)
        b = self._plan("C:/in/b.mkv", "C:/out/Film.mp4", dv.VIDEO_MODE_COPY)
        runner = JobRunner({}, q.Queue())
        for plan in (a, b):
            runner.normalize_output_extension(plan)
        runner._mark_output_collisions([a, b])
        assert b.output_path.endswith(".mkv")   # „.mp4“ wurde normalisiert
        assert b.status is FileStatus.ERROR     # Kollision erkannt
        assert a.status is not FileStatus.ERROR


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
