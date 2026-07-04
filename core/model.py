"""Datenmodell von Spurwerk.

UI, Planner, Kommandobau und Runner kommunizieren ausschließlich über
diese Strukturen. Kein tkinter-Import — alles hier ist headless testbar.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


class Action(Enum):
    """Was mit einer Spur in der Ausgabe passiert."""

    COPY = "copy"                      # verlustfrei übernehmen
    STEREO_ADD = "stereo_add"          # Original behalten + Stereo-Kopie zusätzlich
    STEREO_REPLACE = "stereo_replace"  # nur die Stereo-Version übernehmen
    DROP = "drop"                      # Spur fällt weg

    @property
    def is_stereo(self) -> bool:
        return self in (Action.STEREO_ADD, Action.STEREO_REPLACE)

    @property
    def keeps_original(self) -> bool:
        return self in (Action.COPY, Action.STEREO_ADD)


class Origin(Enum):
    """Wer hat die Entscheidung getroffen — Regel oder Mensch."""

    RULE = "R"
    MANUAL = "M"


@dataclass(frozen=True)
class Track:
    """Eine Spur, wie `mkvmerge -J` sie beschreibt."""

    id: int
    type: str                    # "video" | "audio" | "subtitles"
    codec_id: str                # z.B. "A_AC3"
    codec_name: str              # menschenlesbar, z.B. "AC-3"
    lang: str                    # normalisiert ("de", "en", "und", …)
    name: str                    # Track-Titel oder ""
    channels: int | None         # nur Audio
    default: bool
    forced: bool
    minimum_timestamp_ns: int | None = None   # Startversatz (A/V-Sync!)

    @property
    def is_multichannel(self) -> bool:
        return self.type == "audio" and (self.channels or 0) > 2

    @property
    def delay_ms(self) -> int:
        return round((self.minimum_timestamp_ns or 0) / 1_000_000)


@dataclass(frozen=True)
class MediaInfo:
    """Scan-Ergebnis einer Datei."""

    path: str
    tracks: tuple[Track, ...]
    has_chapters: bool = False
    attachment_count: int = 0
    duration_s: float = 0.0
    title: str = ""

    def by_type(self, track_type: str) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.type == track_type)

    @property
    def audio_tracks(self) -> tuple[Track, ...]:
        return self.by_type("audio")

    def track(self, track_id: int) -> Track:
        for t in self.tracks:
            if t.id == track_id:
                return t
        raise KeyError(f"Track {track_id} nicht vorhanden")

    def ffmpeg_audio_index(self, track_id: int) -> int:
        """Index der Spur unter den Audiospuren (für ffmpeg `-map 0:a:N`)."""
        for i, t in enumerate(self.audio_tracks):
            if t.id == track_id:
                return i
        raise KeyError(f"Track {track_id} ist keine Audiospur")


@dataclass
class TrackDecision:
    action: Action
    origin: Origin = Origin.RULE


@dataclass
class StereoSettings:
    """Konvertierungs-Einstellungen — gelten global für alle
    Konvertier-Aktionen eines Jobs. `channels` ist das ZIEL-Layout;
    das effektive Layout ist immer min(Quelle, Ziel) — nie Upmix."""

    codec: str = "ac3"               # ac3 | eac3 | aac
    channels: str = "2.0"            # "2.0" | "5.1" | "7.1"
    bitrate: str = "640k"
    downmix_preset: str = "loro"     # loro | pro | lfeboost | passthrough (nur Ziel 2.0)
    track_name: str = "Stereo AC3"

    def suggested_track_name(self) -> str:
        from .presets import OUTPUT_CODECS
        short = OUTPUT_CODECS[self.codec]["short"]
        return (f"Stereo {short}" if self.channels == "2.0"
                else f"{short} {self.channels}")

    def display_track_name(self) -> str:
        return self.track_name or self.suggested_track_name()

    def short_label(self) -> str:
        """Kompakte Beschreibung, z. B. „E-AC3 5.1“ — für Tabelle & Vorschau."""
        from .presets import OUTPUT_CODECS
        return f"{OUTPUT_CODECS[self.codec]['short']} {self.channels}"


@dataclass
class OutputSettings:
    suffix: str = "_remux"
    directory: str = ""              # leer = Quellordner

    def output_path_for(self, source: str) -> str:
        src = Path(source)
        target_dir = Path(self.directory) if self.directory else src.parent
        return str(target_dir / f"{src.stem}{self.suffix}{src.suffix}")


class FileStatus(Enum):
    PENDING_TOOLS = "wartet auf Tools"
    SCANNING = "scanne"
    SCAN_ERROR = "Scan-Fehler"
    READY = "bereit"
    WAITING = "wartet"
    RUNNING = "läuft"
    DONE = "fertig"
    ERROR = "Fehler"
    SKIPPED = "übersprungen"


@dataclass
class FilePlan:
    """Der komplette Plan für eine Datei: Spuren + Entscheidungen."""

    media: MediaInfo
    decisions: dict[int, TrackDecision] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Genau EINE Standard-Audiospur in der Ausgabe (Invariante):
    default_audio_source: int | None = None   # Quell-Track-ID
    default_audio_is_stereo: bool = False     # Flag liegt auf der Stereo-Kopie
    output_path: str = ""
    output_manual: bool = False               # Nutzer hat den Pfad selbst gesetzt
    status: FileStatus = FileStatus.READY
    error: str = ""
    # Job-Queue-Prinzip: JEDE Datei trägt ihre eigene Konvertierungs-Config
    stereo: StereoSettings = field(default_factory=StereoSettings)
    profile_name: str = ""

    # ── Abfragen ──────────────────────────────────────────────────────────

    def decision(self, track_id: int) -> TrackDecision:
        return self.decisions[track_id]

    def kept_ids(self, track_type: str) -> list[int]:
        """Quellspuren dieses Typs, die (als Original) in die Ausgabe kommen."""
        return [t.id for t in self.media.by_type(track_type)
                if self.decisions[t.id].action.keeps_original]

    def stereo_sources(self) -> list[Track]:
        """Audiospuren, aus denen eine Stereo-Version erzeugt wird."""
        return [t for t in self.media.audio_tracks
                if self.decisions[t.id].action.is_stereo]

    @property
    def is_remux_only(self) -> bool:
        return not self.stereo_sources()

    @property
    def output_track_count(self) -> dict[str, int]:
        counts = {"video": len(self.kept_ids("video")),
                  "audio": len(self.kept_ids("audio")) + len(self.stereo_sources()),
                  "subtitles": len(self.kept_ids("subtitles"))}
        return counts

    def has_output(self) -> bool:
        return any(v > 0 for v in self.output_track_count.values())

    # ── Änderungen ────────────────────────────────────────────────────────

    def set_action(self, track_id: int, action: Action,
                   origin: Origin = Origin.MANUAL) -> None:
        track = self.media.track(track_id)
        if action.is_stereo and track.type != "audio":
            raise ValueError("Stereo-Aktionen gibt es nur für Audiospuren")
        self.decisions[track_id] = TrackDecision(action, origin)
        self._ensure_default_valid()

    def set_default_audio(self, track_id: int, on_stereo: bool) -> None:
        dec = self.decisions[track_id]
        if on_stereo and not dec.action.is_stereo:
            raise ValueError("Spur hat keine Stereo-Aktion")
        if not on_stereo and not dec.action.keeps_original:
            raise ValueError("Original dieser Spur ist nicht in der Ausgabe")
        self.default_audio_source = track_id
        self.default_audio_is_stereo = on_stereo

    def _ensure_default_valid(self) -> None:
        """Hält die Invariante: genau eine Default-Audiospur, sofern Audio da ist."""
        tid = self.default_audio_source
        if tid is not None:
            dec = self.decisions.get(tid)
            if dec is not None:
                if self.default_audio_is_stereo and dec.action.is_stereo:
                    return
                if not self.default_audio_is_stereo and dec.action.keeps_original:
                    return
        # Neu bestimmen: erste Stereo-Spur, sonst erste behaltene Originalspur
        for t in self.media.audio_tracks:
            if self.decisions[t.id].action.is_stereo:
                self.default_audio_source = t.id
                self.default_audio_is_stereo = True
                return
        for t in self.media.audio_tracks:
            if self.decisions[t.id].action.keeps_original:
                self.default_audio_source = t.id
                self.default_audio_is_stereo = False
                return
        self.default_audio_source = None
        self.default_audio_is_stereo = False


@dataclass
class RuleProfile:
    """Ein benanntes Regelwerk — füllt FilePlan.decisions automatisch."""

    name: str = "Deutsch bevorzugt"
    lang_priority: list[str] = field(default_factory=lambda: ["de", "en"])
    audio_policy: str = "preferred_only"   # preferred_only | all
    stereo_policy: str = "add"             # add | replace | never
    sub_policy: str = "preferred"          # preferred | forced_only | all | none
    keep_forced_subs: bool = True
    drop_commentary: bool = True
    und_audio: str = "keep"                # keep | drop
    stereo_make_default: bool = True
    stereo: StereoSettings = field(default_factory=StereoSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    builtin: bool = False

    def copy(self) -> "RuleProfile":
        return replace(
            self,
            lang_priority=list(self.lang_priority),
            stereo=replace(self.stereo),
            output=replace(self.output),
            builtin=False,
        )
