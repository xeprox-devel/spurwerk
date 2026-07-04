"""Baukasten für In-Memory-Testdaten (ohne echte MKV-Dateien)."""

from __future__ import annotations

from core.model import MediaInfo, RuleProfile, Track


def track(tid: int, ttype: str, lang: str = "und", *, codec: str = "?",
          name: str = "", channels: int | None = None, default: bool = False,
          forced: bool = False, delay_ns: int | None = None) -> Track:
    return Track(id=tid, type=ttype, codec_id=codec, codec_name=codec,
                 lang=lang, name=name, channels=channels, default=default,
                 forced=forced, minimum_timestamp_ns=delay_ns)


def media(*tracks: Track, path: str = "C:/filme/test.mkv",
          chapters: bool = False, duration: float = 100.0) -> MediaInfo:
    return MediaInfo(path=path, tracks=tuple(tracks),
                     has_chapters=chapters, duration_s=duration)


def film_std() -> MediaInfo:
    """Nachbau des film_std.mkv-Fixtures: V + de5.1 + en5.1 + fr2.0-Kommentar
    + de-Sub(forced) + en-Sub."""
    return media(
        track(0, "video", codec="V_MPEG4/ISO/AVC"),
        track(1, "audio", "de", codec="A_AC3", channels=6, default=True,
              name="Surround"),
        track(2, "audio", "en", codec="A_AC3", channels=6),
        track(3, "audio", "fr", codec="A_AAC", channels=2, name="Kommentar"),
        track(4, "subtitles", "de", codec="S_TEXT/UTF8", forced=True,
              default=True),
        track(5, "subtitles", "en", codec="S_TEXT/UTF8"),
        chapters=True,
    )


def profile_de(**overrides) -> RuleProfile:
    """Testprofil: nur Deutsch behalten, Stereo-Kopie zusätzlich."""
    defaults = dict(name="Test DE", lang_priority=["de"],
                    audio_policy="preferred_only", stereo_policy="add",
                    sub_policy="preferred", drop_commentary=True)
    defaults.update(overrides)
    return RuleProfile(**defaults)
