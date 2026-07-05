"""Erzeugt kleine Test-MKVs mit definierten Spurkombinationen.

Aufruf:  python tests/make_fixtures.py [--force]

Benötigt ffmpeg.exe und mkvmerge.exe im tools/-Ordner des Projekts.
Die Fixtures landen in tests/fixtures/ (gitignored, ~1 MB gesamt):

  film_std.mkv     Standardfall: Video + de 5.1 + en 5.1 + fr 2.0 "Kommentar"
                   + de-Sub (forced) + en-Sub + Kapitel
  serie_nodeu.mkv  kein Deutsch: en 5.1 + ja 2.0 + en-Sub
  film_delay.mkv   de 5.1 mit 500 ms Startversatz (--sync) → A/V-Sync-Test
  film_zweide.mkv  zwei deutsche Audiospuren (5.1 + 2.0 "Kommentar") → Abweichler
  film_und.mkv     Audiospur ohne Sprachkennung (und)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FFMPEG = TOOLS / "ffmpeg.exe"
MKVMERGE = TOOLS / "mkvmerge.exe"
OUT = ROOT / "tests" / "fixtures"
ASSETS = OUT / "_assets"

DURATION = "4"  # Sekunden

PAN_51 = "pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0"
PAN_71 = ("pan=7.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0|SL=c0|SR=c0")

SRT_DE = """1
00:00:00,500 --> 00:00:02,000
Hallo Welt

2
00:00:02,500 --> 00:00:03,500
Zweite Zeile
"""

SRT_EN = """1
00:00:00,500 --> 00:00:02,000
Hello world
"""

CHAPTERS = """CHAPTER01=00:00:00.000
CHAPTER01NAME=Anfang
CHAPTER02=00:00:02.000
CHAPTER02NAME=Mitte
"""


def run(cmd: list[str | Path]) -> None:
    result = subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8"
    )
    # mkvmerge: Exit-Code 1 ist nur eine Warnung
    limit = 1 if Path(cmd[0]).name == "mkvmerge.exe" else 0
    if result.returncode > limit:
        sys.exit(
            f"FEHLER ({Path(cmd[0]).name}, Exit {result.returncode}):\n"
            f"{' '.join(str(c) for c in cmd)}\n{result.stderr[-2000:]}"
        )


def make_assets() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    def ff(args: list[str | Path]) -> None:
        run([FFMPEG, "-y", "-v", "error", *args])

    ff(["-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=25:duration={DURATION}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        ASSETS / "video.mkv"])
    ff(["-f", "lavfi", "-i", f"sine=frequency=440:duration={DURATION}",
        "-af", PAN_51, "-c:a", "ac3", "-b:a", "192k", ASSETS / "a51.ac3"])
    ff(["-f", "lavfi", "-i", f"sine=frequency=330:duration={DURATION}",
        "-ac", "2", "-c:a", "aac", "-b:a", "96k", ASSETS / "a20.m4a"])
    ff(["-f", "lavfi", "-i", f"sine=frequency=550:duration={DURATION}",
        "-af", PAN_71, "-c:a", "aac", "-b:a", "256k", ASSETS / "a71.m4a"])
    # DTS-Core 5.1 (FFmpegs dca-Encoder ist experimentell, reicht als Quelle)
    ff(["-f", "lavfi", "-i", f"sine=frequency=660:duration={DURATION}",
        "-af", PAN_51, "-c:a", "dca", "-strict", "experimental",
        "-b:a", "768k", ASSETS / "a51.dts"])

    (ASSETS / "de.srt").write_text(SRT_DE, encoding="utf-8")
    (ASSETS / "en.srt").write_text(SRT_EN, encoding="utf-8")
    (ASSETS / "chapters.txt").write_text(CHAPTERS, encoding="utf-8")


def mux(name: str, args: list[str | Path]) -> None:
    run([MKVMERGE, "-o", OUT / name, *args])


def make_fixtures() -> None:
    video = ASSETS / "video.mkv"
    a51 = ASSETS / "a51.ac3"
    a20 = ASSETS / "a20.m4a"
    de_srt = ASSETS / "de.srt"
    en_srt = ASSETS / "en.srt"
    chapters = ASSETS / "chapters.txt"

    mux("film_std.mkv", [
        video,
        "--language", "0:de", "--track-name", "0:Surround",
        "--default-track-flag", "0:yes", a51,
        "--language", "0:en", "--default-track-flag", "0:no", a51,
        "--language", "0:fr", "--track-name", "0:Kommentar",
        "--default-track-flag", "0:no", a20,
        "--language", "0:de", "--forced-display-flag", "0:yes",
        "--default-track-flag", "0:yes", de_srt,
        "--language", "0:en", "--default-track-flag", "0:no", en_srt,
        "--chapters", chapters,
    ])

    mux("serie_nodeu.mkv", [
        video,
        "--language", "0:en", "--default-track-flag", "0:yes", a51,
        "--language", "0:ja", "--default-track-flag", "0:no", a20,
        "--language", "0:en", en_srt,
    ])

    mux("film_delay.mkv", [
        video,
        "--language", "0:de", "--sync", "0:500",
        "--default-track-flag", "0:yes", a51,
    ])

    mux("film_zweide.mkv", [
        video,
        "--language", "0:de", "--track-name", "0:Surround",
        "--default-track-flag", "0:yes", a51,
        "--language", "0:de", "--track-name", "0:Kommentar des Regisseurs",
        "--default-track-flag", "0:no", a20,
        "--language", "0:de", de_srt,
    ])

    mux("film_und.mkv", [
        video,
        "--language", "0:und", "--default-track-flag", "0:yes", a20,
    ])

    mux("film_71.mkv", [
        video,
        "--language", "0:de", "--track-name", "0:Surround 7.1",
        "--default-track-flag", "0:yes", ASSETS / "a71.m4a",
    ])

    mux("film_dts.mkv", [
        video,
        "--language", "0:de", "--track-name", "0:DTS Surround",
        "--default-track-flag", "0:yes", ASSETS / "a51.dts",
    ])

    make_dv_fixture()


def make_dv_fixture() -> None:
    """film_dv.mkv: HEVC-10bit mit HDR10-Signalisierung + injizierter
    DV-Profil-8.1-RPU (synthetisch via dovi_tool generate/inject-rpu).
    Wird übersprungen, wenn dovi_tool fehlt."""
    dovi = TOOLS / "dovi_tool.exe"
    if not dovi.exists():
        print("  (film_dv.mkv übersprungen — dovi_tool fehlt in tools/)")
        return

    x265 = ("log-level=error:colorprim=bt2020:transfer=smpte2084:"
            "colormatrix=bt2020nc:"
            "master-display=G(13250,34500)B(7500,3000)R(34000,16000)"
            "WP(15635,16450)L(10000000,1):max-cll=1000,400")
    hevc = ASSETS / "hdr10.hevc"
    run([FFMPEG, "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=24:duration={DURATION}",
         "-c:v", "libx265", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p10le", "-x265-params", x265,
         "-f", "hevc", hevc])

    rpu_cfg = ASSETS / "rpu.json"
    rpu_cfg.write_text(json.dumps({
        "cm_version": "V29", "profile": "8.1", "length": 96,
        "level6": {"max_display_mastering_luminance": 1000,
                   "min_display_mastering_luminance": 1,
                   "max_content_light_level": 1000,
                   "max_frame_average_light_level": 400},
    }), encoding="utf-8")
    rpu = ASSETS / "rpu.bin"
    run([dovi, "generate", "-j", rpu_cfg, "-o", rpu])
    dv_hevc = ASSETS / "dv81.hevc"
    run([dovi, "inject-rpu", "-i", hevc, "--rpu-in", rpu, "-o", dv_hevc])

    mux("film_dv.mkv", [
        dv_hevc,
        "--language", "0:de", "--default-track-flag", "0:yes",
        ASSETS / "a51.ac3",
    ])


def summary() -> None:
    for mkv in sorted(OUT.glob("*.mkv")):
        info = json.loads(subprocess.run(
            [str(MKVMERGE), "-J", str(mkv)],
            capture_output=True, text=True, encoding="utf-8").stdout)
        tracks = ", ".join(
            f"{t['type'][0].upper()}:{t['properties'].get('language', '?')}"
            for t in info["tracks"])
        chap = " +Kapitel" if info.get("chapters") else ""
        size_kb = mkv.stat().st_size // 1024
        print(f"  {mkv.name:20s} {size_kb:5d} kB  [{tracks}]{chap}")


def main() -> None:
    if not FFMPEG.exists() or not MKVMERGE.exists():
        sys.exit(f"Tools nicht gefunden in {TOOLS} — bitte zuerst bereitstellen.")
    force = "--force" in sys.argv
    existing = list(OUT.glob("*.mkv"))
    if existing and not force:
        print(f"{len(existing)} Fixtures vorhanden (--force zum Neuerzeugen).")
        summary()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    make_assets()
    make_fixtures()
    print("Fixtures erzeugt:")
    summary()


if __name__ == "__main__":
    main()
