"""Golden-Tests für den Kommandobau (ffmpeg + mkvmerge)."""

from pathlib import Path

from core.commands import (build_ffmpeg_downmix, build_mkvmerge_mux,
                           stereo_temp_name)
from core.model import Action, StereoSettings
from core.planner import build_plan
from tests.helpers import film_std, media, profile_de, track


def arg_after(cmd, flag, n=0):
    """Wert nach dem (n+1)-ten Vorkommen von `flag`."""
    hits = [i for i, a in enumerate(cmd) if a == flag]
    return cmd[hits[n] + 1]


class TestMkvmergeMux:
    def test_remux_only_ein_durchlauf(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {})

        assert cmd[:2] == ["mkvmerge", "--gui-mode"]
        assert arg_after(cmd, "-o") == str(Path("C:/filme/test_remux.mkv"))
        assert arg_after(cmd, "--video-tracks") == "0"
        assert arg_after(cmd, "--audio-tracks") == "1"
        assert arg_after(cmd, "--subtitle-tracks") == "4"
        assert arg_after(cmd, "--default-track-flag") == "1:yes"
        assert "--track-order" not in cmd
        assert cmd[-1] == "C:/filme/test.mkv"

    def test_stereo_add_haengt_datei_an(self):
        plan = build_plan(film_std(), profile_de())
        settings = StereoSettings(codec="ac3", track_name="Stereo AC3")
        stereo_file = "C:/tmp/stereo_track1.ac3"
        cmd = build_mkvmerge_mux("mkvmerge", plan, settings, {1: stereo_file})

        assert stereo_file in cmd
        assert arg_after(cmd, "--language") == "0:de"
        assert arg_after(cmd, "--track-name") == "0:Stereo AC3"
        # Quellspur 1 verliert das Default-Flag, Stereo-Datei bekommt es
        flags = [cmd[i + 1] for i, a in enumerate(cmd)
                 if a == "--default-track-flag"]
        assert "1:no" in flags and "0:yes" in flags
        # Stereo (Datei 1) direkt hinter der Quellspur, vor dem Sub
        assert arg_after(cmd, "--track-order") == "0:0,0:1,1:0,0:4"

    def test_stereo_replace_ohne_quellaudio(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="replace"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/tmp/stereo_track1.ac3"})
        assert "--no-audio" in cmd
        assert "--audio-tracks" not in cmd
        assert arg_after(cmd, "--track-order") == "0:0,1:0,0:4"

    def test_delay_wird_uebertragen(self):
        m = media(track(0, "video"),
                  track(1, "audio", "de", channels=6, delay_ns=500_000_000))
        plan = build_plan(m, profile_de())
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/tmp/s.ac3"})
        assert arg_after(cmd, "--sync") == "0:500"

    def test_kein_delay_kein_sync(self):
        plan = build_plan(film_std(), profile_de())
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/tmp/s.ac3"})
        assert "--sync" not in cmd

    def test_keine_subs_no_subtitles(self):
        plan = build_plan(film_std(), profile_de(sub_policy="none",
                                                 keep_forced_subs=False,
                                                 stereo_policy="never"))
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(), {})
        assert "--no-subtitles" in cmd

    def test_und_sprache_bleibt_und(self):
        m = media(track(0, "video"), track(1, "audio", "und", channels=6))
        plan = build_plan(m, profile_de())
        cmd = build_mkvmerge_mux("mkvmerge", plan, StereoSettings(),
                                 {1: "C:/tmp/s.ac3"})
        assert arg_after(cmd, "--language") == "0:und"


class TestFfmpegDownmix:
    def test_mehrkanal_loro_pan_filter(self):
        plan = build_plan(film_std(), profile_de())
        t = plan.media.track(1)
        cmd = build_ffmpeg_downmix("ffmpeg", plan, t,
                                   StereoSettings(downmix_preset="loro"),
                                   "out.ac3")
        assert arg_after(cmd, "-map") == "0:a:0"
        pan = arg_after(cmd, "-af")
        assert pan.startswith("pan=stereo|")
        # Regressionstest gegen den Altcode-Bug: nie Metadaten-Downmix ohne Filter
        assert "-dmix_mode" not in cmd
        assert arg_after(cmd, "-c:a") == "ac3"
        assert arg_after(cmd, "-b:a") == "640k"

    def test_map_zaehlt_nur_audiospuren(self):
        # Track-ID 2 ist die ZWEITE Audiospur → ffmpeg-Index 0:a:1
        plan = build_plan(film_std(), profile_de(audio_policy="all",
                                                 drop_commentary=False))
        t = plan.media.track(2)
        cmd = build_ffmpeg_downmix("ffmpeg", plan, t, StereoSettings(), "o.ac3")
        assert arg_after(cmd, "-map") == "0:a:1"

    def test_stereoquelle_kein_filter(self):
        m = media(track(0, "video"), track(1, "audio", "de", channels=2))
        plan = build_plan(m, profile_de())
        plan.set_action(1, Action.STEREO_ADD)
        cmd = build_ffmpeg_downmix("ffmpeg", plan, m.track(1),
                                   StereoSettings(), "o.ac3")
        assert "-af" not in cmd
        assert arg_after(cmd, "-ac") == "2"

    def test_passthrough_nur_ac2(self):
        plan = build_plan(film_std(), profile_de())
        cmd = build_ffmpeg_downmix(
            "ffmpeg", plan, plan.media.track(1),
            StereoSettings(downmix_preset="passthrough"), "o.ac3")
        assert "-af" not in cmd
        assert arg_after(cmd, "-ac") == "2"

    def test_temp_name_pro_spur(self):
        assert stereo_temp_name(film_std().track(1),
                                StereoSettings(codec="eac3")) \
            == "stereo_track1.eac3"
