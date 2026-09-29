"""Regressionstests zu den Prüfbefunden im Kern (core/).

1. DV/HDR → HDR10: Startversatz, Lücken und VFR der Quell-Videospur
   überleben den Umweg über den rohen HEVC-Stream.
2. mkvmerge/mkvextract-Meldungen kommen im --gui-mode über STDOUT — der
   Fehlertext darf nie leer sein.
3. Keine Ausgabe darf die Quelle eines anderen Jobs überschreiben.
4. Konvertierte Spur heißt nach dem ECHTEN Layout; Mono bleibt Mono.
5. IETF-Region/Schrift („es-419“) bleibt auf neu erzeugten Spuren erhalten.
6. scan_file macht aus jedem Startfehler von mkvmerge einen ScanError.

Die End-to-End-Tests bauen ihre Quellen selbst in tmp_path (wie
tests/make_fixtures.py) und überspringen sich, wenn Werkzeuge fehlen.
"""

import dataclasses
import json
import queue
import subprocess
import sys
from pathlib import Path

import pytest

from core import dv
from core import scanner as scanner_mod
from core.commands import build_ffmpeg_downmix, build_mkvmerge_mux
from core.model import Action, FileStatus, StereoSettings, Track
from core.planner import build_plan
from core.runner import JobError, JobRunner
from core.scanner import ScanError, parse_mkvmerge_json, scan_file
from tests.helpers import film_std, media, profile_de, track

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {name: str(ROOT / "tools" / f"{name}.exe")
         for name in ("mkvmerge", "mkvextract", "ffmpeg", "ffprobe",
                      "dovi_tool")}


def _have(*names: str) -> bool:
    return all(Path(TOOLS[n]).exists() for n in names)


def arg_after(cmd, flag, n=0):
    hits = [i for i, a in enumerate(cmd) if a == flag]
    return cmd[hits[n] + 1]


def _run(cmd) -> None:
    result = subprocess.run([str(c) for c in cmd], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    limit = 1 if Path(str(cmd[0])).stem == "mkvmerge" else 0   # 1 = Warnung
    assert result.returncode <= limit, (result.stdout[-800:]
                                        + result.stderr[-800:])


def _identify(path) -> dict:
    return json.loads(subprocess.run(
        [TOOLS["mkvmerge"], "-J", str(path)], capture_output=True,
        text=True, encoding="utf-8").stdout)


def _video_timestamps(path, tmp_path: Path) -> list[float]:
    out = tmp_path / f"ts_{Path(path).stem}.txt"
    _run([TOOLS["mkvextract"], str(path), "timestamps_v2", f"0:{out}"])
    return dv.parse_timestamps_v2(out.read_text(encoding="utf-8"))


# ══ 1. DV-Remux: Quell-Timing der Videospur ═══════════════════════════════


class TestZeitstempelAnalyse:
    def test_v2_datei_wird_gelesen_und_sortiert(self):
        text = "# timestamp format v2\n500\n583\n542\n\n625.5\n"
        assert dv.parse_timestamps_v2(text) == [500, 542, 583, 625.5]

    def test_cfr_mit_versatz_liefert_versatz(self):
        # 23,976 fps, auf ganze ms gerundet wie in echten MKVs
        ts = [round(500 + i * 1001 / 24) for i in range(2000)]
        assert dv.constant_rate_offset(ts, "24000/1001") == 500

    def test_cfr_ohne_versatz(self):
        ts = [round(i * 1000 / 24) for i in range(100)]
        assert dv.constant_rate_offset(ts, "24/1") == 0

    def test_luecke_braucht_exakte_zeitstempel(self):
        ts = [i * 1000 / 24 + (1000 if i >= 48 else 0) for i in range(96)]
        assert dv.constant_rate_offset(ts, "24/1") is None

    def test_vfr_braucht_exakte_zeitstempel(self):
        ts = [i * 40.0 for i in range(50)] + [2000 + i * 1000 / 60
                                              for i in range(50)]
        assert dv.constant_rate_offset(ts, "25/1") is None

    def test_unbekannte_bildrate_oder_leer(self):
        assert dv.constant_rate_offset([0, 40, 80], "") is None
        assert dv.constant_rate_offset([0, 40, 80], "1000/1") is None
        assert dv.constant_rate_offset([], "25/1") is None


class TestDvKommandos:
    def test_mkvextract_sichert_zeitstempel_im_selben_lauf(self):
        cmd = dv.build_extract_hevc_mkvextract(
            "mkvextract", "C:/in/a.mkv", 0, "C:/t/v.hevc",
            out_timestamps="C:/t/v_ts.txt")
        assert cmd[:4] == ["mkvextract", "--gui-mode", "C:/in/a.mkv",
                           "tracks"]
        assert arg_after(cmd, "tracks") == "0:C:/t/v.hevc"
        assert arg_after(cmd, "timestamps_v2") == "0:C:/t/v_ts.txt"

    @staticmethod
    def _plan(delay_ns=None):
        m = media(track(0, "video", codec="V_MPEGH/ISO/HEVC",
                        delay_ns=delay_ns),
                  track(1, "audio", "de", codec="A_AC3", channels=6))
        plan = build_plan(m, profile_de(stereo_policy="never"))
        plan.dv = dv.DVInfo(codec="hevc", frame_rate="24000/1001")
        return plan

    def test_zeitstempel_datei_ersetzt_bildrate(self):
        cmd = build_mkvmerge_mux("mkvmerge", self._plan(500_000_000),
                                 StereoSettings(), {},
                                 video_file="C:/t/clean.hevc",
                                 video_timestamps="C:/t/v_ts.txt")
        assert arg_after(cmd, "--timestamps") == "0:C:/t/v_ts.txt"
        assert cmd.index("--timestamps") < cmd.index("C:/t/clean.hevc")
        assert "--default-duration" not in cmd
        assert "--sync" not in cmd

    def test_cfr_bildrate_plus_gemessener_versatz(self):
        cmd = build_mkvmerge_mux("mkvmerge", self._plan(),
                                 StereoSettings(), {},
                                 video_file="C:/t/clean.hevc",
                                 video_sync_ms=500)
        assert arg_after(cmd, "--default-duration") == "0:24000/1001fps"
        assert arg_after(cmd, "--sync") == "0:500"
        assert cmd.index("--sync") < cmd.index("C:/t/clean.hevc")

    def test_ffmpeg_weg_nimmt_gescannten_versatz(self):
        cmd = build_mkvmerge_mux("mkvmerge", self._plan(500_000_000),
                                 StereoSettings(), {},
                                 video_file="C:/t/clean.hevc")
        assert arg_after(cmd, "--sync") == "0:500"

    def test_ohne_versatz_kein_sync(self):
        cmd = build_mkvmerge_mux("mkvmerge", self._plan(0),
                                 StereoSettings(), {},
                                 video_file="C:/t/clean.hevc",
                                 video_sync_ms=0)
        assert "--sync" not in cmd


needs_dv_tools = pytest.mark.skipif(
    not _have("mkvmerge", "mkvextract", "ffmpeg", "ffprobe", "dovi_tool"),
    reason="mkvmerge/mkvextract/ffmpeg/ffprobe/dovi_tool fehlen in tools/")


@pytest.fixture(scope="module")
def dv_quellen(tmp_path_factory):
    """Synthetisches DV 8.1 (wie make_fixtures.make_dv_fixture), einmal
    mit 500 ms spät startendem Bild, einmal mit 1-s-Lücke mitten im Bild."""
    base = tmp_path_factory.mktemp("dv_quellen")
    x265 = ("log-level=error:colorprim=bt2020:transfer=smpte2084:"
            "colormatrix=bt2020nc:"
            "master-display=G(13250,34500)B(7500,3000)R(34000,16000)"
            "WP(15635,16450)L(10000000,1):max-cll=1000,400")
    hevc = base / "hdr10.hevc"
    _run([TOOLS["ffmpeg"], "-y", "-v", "error", "-f", "lavfi",
          "-i", "testsrc2=size=320x180:rate=24:duration=4",
          "-c:v", "libx265", "-preset", "ultrafast",
          "-pix_fmt", "yuv420p10le", "-x265-params", x265,
          "-f", "hevc", hevc])
    rpu_cfg = base / "rpu.json"
    rpu_cfg.write_text(json.dumps({
        "cm_version": "V29", "profile": "8.1", "length": 96,
        "level6": {"max_display_mastering_luminance": 1000,
                   "min_display_mastering_luminance": 1,
                   "max_content_light_level": 1000,
                   "max_frame_average_light_level": 400},
    }), encoding="utf-8")
    rpu = base / "rpu.bin"
    _run([TOOLS["dovi_tool"], "generate", "-j", rpu_cfg, "-o", rpu])
    dv_hevc = base / "dv81.hevc"
    _run([TOOLS["dovi_tool"], "inject-rpu", "-i", hevc,
          "--rpu-in", rpu, "-o", dv_hevc])
    audio = base / "a20.ac3"
    _run([TOOLS["ffmpeg"], "-y", "-v", "error", "-f", "lavfi",
          "-i", "sine=frequency=440:duration=4", "-ac", "2",
          "-c:a", "ac3", "-b:a", "192k", audio])

    delay = base / "dv_spaet.mkv"
    _run([TOOLS["mkvmerge"], "-q", "-o", delay, "--sync", "0:500", dv_hevc,
          "--language", "0:de", "--default-track-flag", "0:yes", audio])

    gap_ts = base / "luecke.txt"
    gap_ts.write_text("# timestamp format v2\n" + "".join(
        f"{250 + i * 1000 / 24 + (1000 if i >= 48 else 0):.6f}\n"
        for i in range(96)), encoding="utf-8")
    gap = base / "dv_luecke.mkv"
    _run([TOOLS["mkvmerge"], "-q", "-o", gap, "--timestamps", f"0:{gap_ts}",
          dv_hevc, "--language", "0:de", "--default-track-flag", "0:yes",
          audio])
    return {"spaet": delay, "luecke": gap}


def _hdr10_remux(src: Path, out: Path, ohne_mkvextract: bool = False):
    m = scan_file(TOOLS["mkvmerge"], str(src))
    plan = build_plan(m, profile_de(stereo_policy="never"))
    plan.dv = dv.analyze(TOOLS["ffprobe"], str(src))
    plan.video_mode = dv.VIDEO_MODE_HDR10
    plan.output_path = str(out)
    runner = JobRunner(TOOLS, queue.Queue())
    if ohne_mkvextract:
        runner._mkvextract_path = lambda: None    # ffmpeg-Fallback erzwingen
    assert runner.run([plan]) == 1, plan.error
    return plan


def _min_ts(info: dict, track_type: str) -> int:
    t = next(t for t in info["tracks"] if t["type"] == track_type)
    return t["properties"].get("minimum_timestamp") or 0


def _video_prop(info: dict, key: str):
    t = next(t for t in info["tracks"] if t["type"] == "video")
    return t["properties"].get(key)


def _packet_pts(path) -> list[str]:
    """PTS jedes Video-Pakets in Dekodier-Reihenfolge — zeigt auch eine
    falsche Zuordnung Frame ↔ Zeitstempel (B-Frames!), die eine sortierte
    Liste verbergen würde."""
    out = subprocess.run(
        [TOOLS["ffprobe"], "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts", "-of", "json", str(path)],
        capture_output=True, text=True).stdout
    return [p.get("pts") for p in json.loads(out)["packets"]]


def _frame_rate(path) -> str:
    out = subprocess.run(
        [TOOLS["ffprobe"], "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "json",
         str(path)], capture_output=True, text=True).stdout
    return json.loads(out)["streams"][0]["r_frame_rate"]


@needs_dv_tools
class TestDvTimingEndToEnd:
    @pytest.mark.parametrize("ohne_mkvextract", [False, True],
                             ids=["mkvextract", "ffmpeg-fallback"])
    def test_startversatz_bleibt_erhalten(self, dv_quellen, tmp_path,
                                          ohne_mkvextract):
        src = dv_quellen["spaet"]
        plan = _hdr10_remux(src, tmp_path / "out [HDR10].mkv",
                            ohne_mkvextract)
        before, after = _identify(src), _identify(plan.output_path)
        assert not dv.analyze(TOOLS["ffprobe"], plan.output_path).has_dv

        assert abs(_min_ts(before, "video") - 500_000_000) <= 1_000_000
        assert abs(_min_ts(after, "video")
                   - _min_ts(before, "video")) <= 1_000_000
        # A/V-Versatz der Ausgabe = der der Quelle
        offset_src = _min_ts(before, "video") - _min_ts(before, "audio")
        offset_out = _min_ts(after, "video") - _min_ts(after, "audio")
        assert abs(offset_out - offset_src) <= 1_000_000
        # Die exakte Bildrate bleibt (Timing-Absicherung aus v1.1.0)
        assert (_video_prop(after, "default_duration")
                == _video_prop(before, "default_duration"))
        assert _frame_rate(plan.output_path) == _frame_rate(src) == "24/1"

    def test_cfr_quelle_frames_zeitgleich(self, dv_quellen, tmp_path):
        src = dv_quellen["spaet"]
        plan = _hdr10_remux(src, tmp_path / "out.mkv")
        pts = _packet_pts(src)
        assert len(pts) == 96
        assert _packet_pts(plan.output_path) == pts

    def test_luecke_bleibt_erhalten(self, dv_quellen, tmp_path):
        src = dv_quellen["luecke"]
        plan = _hdr10_remux(src, tmp_path / "out.mkv")
        pts = _packet_pts(src)
        assert len(pts) == 96
        assert _packet_pts(plan.output_path) == pts   # jeder Frame zeitgleich
        out_ts = _video_timestamps(plan.output_path, tmp_path)
        assert out_ts[48] - out_ts[47] > 1000       # die Lücke ist noch da
        assert abs(_identify(plan.output_path)["container"]["properties"]
                   ["duration"] - _identify(src)["container"]["properties"]
                   ["duration"]) < 50_000_000


# ══ 2. mkvmerge-/mkvextract-Meldungen (stdout im --gui-mode) ══════════════


def _fake_stream(lines: list[str], returncode: int, stderr: str = ""):
    def fake(cmd, progress_cb):
        for line in lines:
            progress_cb(line)
        return returncode, stderr
    return fake


class TestToolMeldungen:
    def test_gui_fehler_landet_im_jobfehler(self):
        runner = JobRunner({}, queue.Queue())
        runner._stream_process = _fake_stream([
            "mkvmerge v94.0 ('Initiate') 64-bit",
            "#GUI#progress 10%",
            "#GUI#error The type of file 'kaputt.mkv' could not be "
            "recognized.",
        ], 2)
        with pytest.raises(JobError) as exc:
            runner._run_mkvmerge(["mkvmerge"], 0, 100)
        assert str(exc.value) == ("mkvmerge-Fehler (Exit 2): The type of "
                                  "file 'kaputt.mkv' could not be "
                                  "recognized.")

    def test_mkvextract_praefix_wird_entfernt(self):
        runner = JobRunner({}, queue.Queue())
        runner._stream_process = _fake_stream([
            "#GUI#error (mkvextract) The file 'x.mkv' could not be opened "
            "for reading.",
        ], 2)
        with pytest.raises(JobError) as exc:
            runner._run_mkvmerge(["mkvextract"], 0, 100, tool="mkvextract")
        assert str(exc.value).endswith(
            ": The file 'x.mkv' could not be opened for reading.")

    def test_warnung_wird_protokolliert(self):
        q = queue.Queue()
        runner = JobRunner({}, q)
        runner._stream_process = _fake_stream([
            "#GUI#warning 'a.mkv': A track with the ID 99 was requested "
            "but not found in the file.",
            "Warning: zweite Warnung",
        ], 1)
        runner._run_mkvmerge(["mkvmerge"], 0, 100)
        logs = [m[1] for m in list(q.queue) if m[0] == "LOG"]
        assert logs == ["  ⚠ mkvmerge-Warnung: 'a.mkv': A track with the "
                        "ID 99 was requested but not found in the file.; "
                        "zweite Warnung"]

    def test_warnung_ohne_meldung_kein_haengender_doppelpunkt(self):
        q = queue.Queue()
        runner = JobRunner({}, q)
        runner._stream_process = _fake_stream([], 1)
        runner._run_mkvmerge(["mkvmerge"], 0, 100)
        logs = [m[1] for m in list(q.queue) if m[0] == "LOG"]
        assert logs == ["  ⚠ mkvmerge-Warnung"]

    def test_warnung_ohne_stdout_meldung_nimmt_stderr(self):
        q = queue.Queue()
        runner = JobRunner({}, q)
        runner._stream_process = _fake_stream([], 1, stderr="nur stderr\n")
        runner._run_mkvmerge(["mkvmerge"], 0, 100)
        logs = [m[1] for m in list(q.queue) if m[0] == "LOG"]
        assert logs == ["  ⚠ mkvmerge-Warnung: nur stderr"]

    def test_ohne_stdout_meldung_bleibt_stderr(self):
        runner = JobRunner({}, queue.Queue())
        runner._stream_process = _fake_stream([], 2, stderr="kaputt\n")
        with pytest.raises(JobError, match=r"Exit 2\): kaputt$"):
            runner._run_mkvmerge(["mkvmerge"], 0, 100)

    def test_ganz_ohne_meldung_kein_haengender_doppelpunkt(self):
        runner = JobRunner({}, queue.Queue())
        runner._stream_process = _fake_stream([], 2)
        with pytest.raises(JobError) as exc:
            runner._run_mkvmerge(["mkvmerge"], 0, 100)
        assert str(exc.value) == "mkvmerge-Fehler (Exit 2)"


@pytest.mark.skipif(not _have("mkvmerge", "mkvextract"),
                    reason="mkvmerge/mkvextract fehlen in tools/")
class TestToolMeldungenEchteWerkzeuge:
    def test_mkvmerge_fehler_hat_grund(self, tmp_path):
        bad = tmp_path / "kaputt.mkv"
        bad.write_bytes(b"das ist kein matroska")
        m = media(track(0, "video"),
                  track(1, "audio", "de", codec="A_AC3", channels=6),
                  path=str(bad))
        plan = build_plan(m, profile_de(stereo_policy="never"))
        plan.output_path = str(tmp_path / "out.mkv")
        assert JobRunner(TOOLS, queue.Queue()).run([plan]) == 0
        assert plan.status is FileStatus.ERROR
        prefix, _, reason = plan.error.partition("): ")
        assert prefix.startswith("mkvmerge-Fehler (Exit 2")
        assert "kaputt.mkv" in reason                 # echter Grund, nicht leer

    def test_mkvextract_fehler_hat_grund(self, tmp_path):
        bad = tmp_path / "kaputt.mkv"
        bad.write_bytes(b"das ist kein matroska")
        runner = JobRunner(TOOLS, queue.Queue())
        with pytest.raises(JobError) as exc:
            runner._run_mkvmerge(
                dv.build_extract_hevc_mkvextract(
                    TOOLS["mkvextract"], str(bad), 0,
                    str(tmp_path / "v.hevc"), str(tmp_path / "ts.txt")),
                0, 100, tool="mkvextract")
        _, _, reason = str(exc.value).partition("): ")
        assert "kaputt.mkv" in reason


# ══ 3. Ausgabe = Quelle eines anderen Jobs ════════════════════════════════


class TestAusgabeTrifftFremdeQuelle:
    @staticmethod
    def _plan(src: Path, out: Path):
        m = media(track(0, "video"),
                  track(1, "audio", "de", codec="A_AC3", channels=6),
                  path=str(src))
        plan = build_plan(m, profile_de(stereo_policy="never"))
        plan.output_path = str(out)
        return plan

    def test_suffix_ausgabe_waere_fremdes_original(self, tmp_path):
        film, remux = tmp_path / "Film.mkv", tmp_path / "Film_remux.mkv"
        film.write_bytes(b"a")
        remux.write_bytes(b"b")
        a = self._plan(film, remux)
        b = self._plan(remux, tmp_path / "Film_remux_remux.mkv")
        q = queue.Queue()
        JobRunner({}, q)._mark_output_collisions([a, b])
        assert a.status is FileStatus.ERROR
        assert "Film_remux.mkv" in a.error and "Warteschlange" in a.error
        assert b.status is not FileStatus.ERROR
        assert any(m[0] == "LOG" and "Übersprungen: Film.mkv" in m[1]
                   for m in list(q.queue))

    def test_auch_wenn_der_andere_job_vorher_laeuft(self, tmp_path):
        film, remux = tmp_path / "Film.mkv", tmp_path / "Film_remux.mkv"
        a = self._plan(film, tmp_path / "FILM_REMUX.MKV")   # andere Schreibung
        b = self._plan(remux, tmp_path / "anders.mkv")
        JobRunner({}, queue.Queue())._mark_output_collisions([b, a])
        assert a.status is FileStatus.ERROR
        assert b.status is not FileStatus.ERROR

    def test_gleiche_datei_ueber_harten_link(self, tmp_path):
        src_b = tmp_path / "B.mkv"
        src_b.write_bytes(b"original von B")
        alias = tmp_path / "alias.mkv"
        try:
            alias.hardlink_to(src_b)
        except OSError:
            pytest.skip("Dateisystem ohne harte Links")
        a = self._plan(tmp_path / "A.mkv", alias)
        b = self._plan(src_b, tmp_path / "B_remux.mkv")
        JobRunner({}, queue.Queue())._mark_output_collisions([a, b])
        assert a.status is FileStatus.ERROR
        assert "B.mkv" in a.error

    def test_eigene_quelle_und_doppelter_job_unveraendert(self, tmp_path):
        # Ziel = eigene Quelle bleibt Sache von _validate; dieselbe Datei
        # zweimal in der Warteschlange ist KEIN Fremd-Original
        src = tmp_path / "Film.mkv"
        src.write_bytes(b"a")
        own = self._plan(src, src)
        twin1 = self._plan(src, tmp_path / "x.mkv")
        twin2 = self._plan(src, tmp_path / "y.mkv")
        JobRunner({}, queue.Queue())._mark_output_collisions(
            [own, twin1, twin2])
        assert own.status is not FileStatus.ERROR
        assert twin1.status is not FileStatus.ERROR
        assert twin2.status is not FileStatus.ERROR

    def test_run_laesst_fremdes_original_unangetastet(self, tmp_path):
        film, remux = tmp_path / "Film.mkv", tmp_path / "Film_remux.mkv"
        remux.write_bytes(b"fremdes original")
        a = self._plan(film, remux)
        b = self._plan(remux, tmp_path / "Film_remux_remux.mkv")
        runner = JobRunner({}, queue.Queue())
        gestartet = []

        def fake_single(plan):
            # schreibt wie der echte Mux in den Ausgabepfad — ohne Schutz
            # wäre B's Original danach überschrieben
            gestartet.append(plan)
            Path(plan.output_path).write_bytes(b"ueberschrieben")
            plan.status = FileStatus.DONE
            return True

        runner._run_single = fake_single
        assert runner.run([a, b]) == 1
        assert gestartet == [b]                   # A nie gestartet
        assert a.status is FileStatus.ERROR
        assert b.status is FileStatus.DONE
        assert remux.read_bytes() == b"fremdes original"


# ══ 4. Spurname nach echtem Layout, nie Upmix ═════════════════════════════


class TestKonvertierteSpur:
    @staticmethod
    def _cmds(channels: int, settings: StereoSettings):
        m = media(track(0, "video"),
                  track(1, "audio", "de", codec="A_DTS", channels=channels))
        plan = build_plan(m, profile_de())
        plan.set_action(1, Action.STEREO_ADD)
        mux = build_mkvmerge_mux("mkvmerge", plan, settings,
                                 {1: "C:/t/c.bin"})
        ff = build_ffmpeg_downmix("ffmpeg", plan, m.track(1), settings,
                                  "o.bin")
        return mux, ff

    def test_51_quelle_ziel_71_heisst_51(self):
        s = StereoSettings(codec="aac", channels="7.1", bitrate="256k")
        s.track_name = s.suggested_track_name()          # wie die UI
        assert s.track_name == "AAC 7.1"
        mux, ff = self._cmds(6, s)
        assert arg_after(mux, "--track-name") == "0:AAC 5.1"
        assert arg_after(ff, "-ac") == "6"

    def test_stereo_quelle_ziel_51_heisst_stereo(self):
        s = StereoSettings(codec="ac3", channels="5.1", track_name="AC3 5.1")
        mux, _ = self._cmds(2, s)
        assert arg_after(mux, "--track-name") == "0:Stereo AC3"

    def test_leerer_name_folgt_effektivem_layout(self):
        s = StereoSettings(codec="eac3", channels="5.1", track_name="")
        mux, _ = self._cmds(8, s)
        assert arg_after(mux, "--track-name") == "0:E-AC3 5.1"

    def test_eigener_name_bleibt(self):
        s = StereoSettings(codec="aac", channels="7.1",
                           track_name="Kino-Mix")
        mux, _ = self._cmds(6, s)
        assert arg_after(mux, "--track-name") == "0:Kino-Mix"

    def test_mono_bleibt_mono(self):
        s = StereoSettings(codec="ac3", channels="2.0",
                           track_name="Stereo AC3")
        mux, ff = self._cmds(1, s)
        assert arg_after(ff, "-ac") == "1"               # kein Upmix auf 2.0
        assert "-af" not in ff
        assert arg_after(mux, "--track-name") == "0:Mono AC3"

    def test_stereo_quelle_weiter_ac2(self):
        _, ff = self._cmds(2, StereoSettings())
        assert arg_after(ff, "-ac") == "2"

    def test_protokoll_nennt_echtes_layout(self):
        s = StereoSettings(codec="aac", channels="7.1")
        assert s.short_label() == "AAC 7.1"            # Ziel (Tabelle/Profil)
        assert s.short_label(6) == "AAC 5.1"           # echtes Layout
        assert s.short_label(1) == "AAC 1.0"


@pytest.mark.skipif(not _have("mkvmerge", "ffmpeg"),
                    reason="mkvmerge/ffmpeg fehlen in tools/")
class TestKonvertierteSpurEndToEnd:
    def test_mono_und_region_bleiben(self, tmp_path):
        """Mono-Quelle, Region „es-419“: die neue Spur ist echtes Mono,
        heißt so und trägt den vollen Sprach-Tag."""
        mono = tmp_path / "mono.ac3"
        _run([TOOLS["ffmpeg"], "-y", "-v", "error", "-f", "lavfi",
              "-i", "sine=frequency=440:duration=2", "-ac", "1",
              "-c:a", "ac3", "-b:a", "96k", mono])
        src = tmp_path / "quelle.mkv"
        _run([TOOLS["mkvmerge"], "-q", "-o", src, "--language", "0:es-419",
              mono])
        m = scan_file(TOOLS["mkvmerge"], str(src))
        assert (m.audio_tracks[0].lang, m.audio_tracks[0].lang_tag) == (
            "es", "es-419")
        plan = build_plan(m, profile_de(lang_priority=["es"]))
        plan.set_action(m.audio_tracks[0].id, Action.STEREO_ADD)
        plan.output_path = str(tmp_path / "out.mkv")
        assert JobRunner(TOOLS, queue.Queue()).run([plan]) == 1, plan.error

        out = _identify(plan.output_path)
        converted = out["tracks"][-1]["properties"]
        assert converted["audio_channels"] == 1
        assert converted["track_name"] == "Mono AC3"
        assert converted["language_ietf"] == "es-419"


# ══ 5. IETF-Region/Schrift ═══════════════════════════════════════════════


def _tagged(tid, ttype, ietf, **kw) -> Track:
    lang = ietf.split("-", 1)[0]
    return dataclasses.replace(track(tid, ttype, lang, **kw), lang_tag=ietf)


class TestSprachTags:
    def test_scanner_behaelt_vollen_tag(self):
        data = {"container": {"recognized": True, "properties": {}},
                "tracks": [
                    {"id": 0, "type": "audio", "codec": "AC-3",
                     "properties": {"language": "spa",
                                    "language_ietf": "es-419",
                                    "audio_channels": 6}},
                    {"id": 1, "type": "audio", "codec": "AC-3",
                     "properties": {"language": "ger",
                                    "language_ietf": "und"}},
                    {"id": 2, "type": "audio", "codec": "AC-3",
                     "properties": {"language": "fre"}},
                ]}
        info = parse_mkvmerge_json(data, "x.mkv")
        es, de, fr = info.tracks
        assert (es.lang, es.lang_tag, es.language_tag) == (
            "es", "es-419", "es-419")
        assert (de.lang, de.lang_tag, de.language_tag) == ("de", "", "de")
        assert (fr.lang, fr.lang_tag, fr.language_tag) == ("fr", "", "fr")

    def test_konvertierte_spur_behaelt_region_regel_sieht_code(self):
        m = media(track(0, "video"),
                  _tagged(1, "audio", "es-419", codec="A_AC3", channels=6),
                  _tagged(2, "audio", "pt-BR", codec="A_AC3", channels=6))
        plan = build_plan(m, profile_de(lang_priority=["es"]))
        assert plan.decision(1).action is Action.STEREO_ADD   # Regel: „es“
        assert not plan.decision(2).action.keeps_original
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/t/s.ac3"})
        assert arg_after(cmd, "--language") == "0:es-419"

    def test_dv_videospur_behaelt_region(self):
        m = media(_tagged(0, "video", "pt-BR", codec="V_MPEGH/ISO/HEVC"),
                  track(1, "audio", "de", codec="A_AC3", channels=6))
        plan = build_plan(m, profile_de(stereo_policy="never"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {},
                                 video_file="C:/t/clean.hevc")
        assert arg_after(cmd, "--language") == "0:pt-BR"

    def test_ohne_ietf_bleibt_alles_wie_bisher(self):
        plan = build_plan(film_std(), profile_de())
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/t/s.ac3"})
        assert arg_after(cmd, "--language") == "0:de"


# ══ 6. scan_file: jeder Startfehler wird ScanError ═══════════════════════


class TestScanStartfehler:
    def test_verzeichnis_statt_exe(self, tmp_path):
        with pytest.raises(ScanError, match="lässt sich nicht starten"):
            scan_file(str(tmp_path), str(tmp_path / "x.mkv"))

    def test_beliebiger_oserror(self, monkeypatch):
        def boom(*_a, **_kw):
            raise OSError(216, "Diese Version ist nicht kompatibel")
        monkeypatch.setattr(scanner_mod.subprocess, "run", boom)
        with pytest.raises(ScanError) as exc:
            scan_file("C:/tools/mkvmerge.exe", "C:/x.mkv")
        assert "mkvmerge lässt sich nicht starten" in str(exc.value)
        assert "nicht kompatibel" in str(exc.value)

    def test_nicht_gefunden_bleibt_eigene_meldung(self, tmp_path):
        with pytest.raises(ScanError, match="nicht gefunden"):
            scan_file(str(tmp_path / "fehlt.exe"), str(tmp_path / "x.mkv"))

    def test_kaputtes_utf8_bricht_scan_nicht_ab(self, monkeypatch):
        """Die echte subprocess.run-Dekodierung mit den Argumenten von
        scan_file — nur das Kind ist ein Python, das ungültiges UTF-8
        in einem Spurnamen ausgibt."""
        real_run = subprocess.run
        payload = (b'{"container": {"recognized": true, "properties": {}},'
                   b' "tracks": [{"id": 0, "type": "audio", "codec": "AC-3",'
                   b' "properties": {"track_name": "Ton \xff"}}]}')
        child = f"import sys; sys.stdout.buffer.write({payload!r})"

        def fake_run(_cmd, **kwargs):
            return real_run([sys.executable, "-c", child], **kwargs)

        monkeypatch.setattr(scanner_mod.subprocess, "run", fake_run)
        info = scan_file("mkvmerge", "x.mkv")
        assert info.tracks[0].name.startswith("Ton ")
