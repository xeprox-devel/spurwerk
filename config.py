"""Persistenz: config.json (mit einmaligem Import der alten config.ini)."""

from __future__ import annotations

import configparser
import dataclasses
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.model import OutputSettings, RuleProfile, StereoSettings
from core.profiles import builtin_profiles


def base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_FILE = base_path() / "config.json"
LEGACY_INI = base_path() / "config.ini"

# save() läuft auch aus dem Download-Thread → Schreibvorgänge serialisieren
_SAVE_LOCK = threading.Lock()
# was beim Laden als defekt gilt (UnicodeDecodeError/JSONDecodeError sind
# ValueError; falsche Typen → TypeError/AttributeError)
_LOAD_ERRORS = (ValueError, OSError, KeyError, TypeError, AttributeError,
                RecursionError)


@dataclass
class AppConfig:
    tools: dict[str, str] = field(default_factory=dict)
    active_profile: str = "Deutsch bevorzugt"
    user_profiles: list[RuleProfile] = field(default_factory=list)
    log_expanded: bool = False
    output_dir: str = ""                       # fester Ausgabeordner (bleibt)
    clean_names: bool = False                  # Dateinamen bereinigen (offline)
    online_names: bool = False                 # zusätzlich TMDb-Abgleich
    tmdb_key: str = ""                         # TMDb-API-Key (v3)
    check_updates: bool = True                 # beim Start nach Updates sehen
    window_geometry: str = ""                  # zuletzt genutzte Fenstergröße/-position
    window_zoomed: bool = False                # Fenster war maximiert
    session: list[dict] = field(default_factory=list)  # offene Jobs
    load_notice: str = ""                      # Hinweis aus load() (nur Laufzeit)

    def all_profiles(self) -> list[RuleProfile]:
        return builtin_profiles() + self.user_profiles

    def profile(self, name: str) -> RuleProfile:
        for p in self.all_profiles():
            if p.name == name:
                return p
        return self.all_profiles()[0]


def load() -> AppConfig:
    """Lädt config.json. Eine defekte Datei wird beiseitegelegt (nie
    überschrieben), dann die Sicherung versucht, sonst Standardwerte —
    der Programmstart darf daran nie scheitern."""
    try:
        raw = _read_bytes(CONFIG_FILE)
    except OSError:
        return _recover("ließ sich nicht lesen")
    if raw is None:  # fehlt → bewusst auf Standard zurückgesetzt
        cfg = AppConfig()
        _import_legacy_ini(cfg)
        return cfg
    cfg = _parse(raw)
    return cfg if cfg is not None else _recover("war beschädigt")


def _recover(cause: str) -> AppConfig:
    """config.json unbrauchbar: beiseitelegen, dann Sicherung, sonst
    Standardwerte (mit Hinweis für die Oberfläche)."""
    aside = _set_aside(CONFIG_FILE)
    problem = (f"config.json {cause} und liegt jetzt als „{aside.name}“ "
               f"daneben" if aside is not None else f"config.json {cause}")
    backup = _backup_file()
    try:
        raw = _read_bytes(backup)
    except OSError:
        raw = None
    cfg = _parse(raw) if raw is not None else None
    if cfg is not None:
        # sofort zurückschreiben: sonst gälte nach einem Absturz vor dem
        # ersten Speichern „Datei fehlt“ = Standard, und das übernächste
        # save() überschriebe die gute Sicherung
        with _SAVE_LOCK:
            if not CONFIG_FILE.exists():  # nie über die defekte Datei
                try:
                    _write_atomic(CONFIG_FILE, raw)
                except OSError:
                    pass
        cfg.load_notice = (f"{problem} — die letzte Sicherung "
                           f"({backup.name}) wurde geladen.")
        return cfg
    cfg = AppConfig(load_notice=f"{problem} — es gelten die "
                                "Standardeinstellungen.")
    _import_legacy_ini(cfg)
    return cfg


def save(cfg: AppConfig) -> None:
    """Schreibt atomar (Temp-Datei + os.replace) — ein Absturz mitten im
    Schreiben hinterlässt nie eine halbe config.json. Die bisherige gute
    Fassung bleibt als config.json.bak erhalten."""
    with _SAVE_LOCK:
        data = {
            "version": 1,
            "tools": cfg.tools,
            "active_profile": cfg.active_profile,
            "log_expanded": cfg.log_expanded,
            "output_dir": cfg.output_dir,
            "clean_names": cfg.clean_names,
            "online_names": cfg.online_names,
            "tmdb_key": cfg.tmdb_key,
            "check_updates": cfg.check_updates,
            "window_geometry": cfg.window_geometry,
            "window_zoomed": cfg.window_zoomed,
            "session": cfg.session,
            "user_profiles": [_profile_to_dict(p) for p in cfg.user_profiles],
        }
        new = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        try:
            old = _read_bytes(CONFIG_FILE)
        except OSError:
            old = None
        if old == new:
            return  # unverändert → nichts schreiben, Sicherung bleibt
        if old is not None and _parse(old) is not None:
            try:  # nur eine lesbare Fassung wird zur Sicherung
                _write_atomic(_backup_file(), old)
            except OSError:
                pass  # Sicherung ist Zugabe, das Speichern selbst zählt
        _write_atomic(CONFIG_FILE, new)


# ── Dateien ───────────────────────────────────────────────────────────────


def _backup_file() -> Path:
    # immer neben CONFIG_FILE (Tests/Sichtcheck biegen nur CONFIG_FILE um)
    return CONFIG_FILE.with_name(CONFIG_FILE.name + ".bak")


def _write_atomic(path: Path, raw: bytes) -> None:
    # eindeutiger Temp-Name: eine zweite Spurwerk-Instanz im selben Ordner
    # darf die halbfertige Datei weder überschreiben noch wegbewegen
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                                suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows: Virenscanner/Indexer hält die Datei kurz offen
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _set_aside(path: Path) -> Path | None:
    """Defekte Datei umbenennen, damit das nächste save() sie nicht
    überschreibt. None, wenn das Umbenennen scheitert."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.defekt-{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.defekt-{stamp}-{n}")
    try:
        path.rename(target)
    except OSError:
        return None
    return target


def _read_bytes(path: Path) -> bytes | None:
    """Dateiinhalt, None wenn die Datei fehlt. Eine kurze Sperre (andere
    Instanz ersetzt gerade, Virenscanner) wird abgewartet, statt eine gute
    Datei als defekt beiseitezulegen; hält sie an, fliegt der OSError."""
    for attempt in range(5):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)
    return None


def _parse(raw: bytes) -> AppConfig | None:
    """AppConfig aus Dateiinhalt — None, wenn er nicht verwertbar ist."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))  # BOM (Editor) tolerieren
        if isinstance(data, dict):
            return _from_dict(data)
    except _LOAD_ERRORS:
        pass
    return None


# ── Serialisierung ────────────────────────────────────────────────────────


def _profile_to_dict(p: RuleProfile) -> dict:
    d = dataclasses.asdict(p)
    d.pop("builtin", None)
    return d


def _known(cls, d) -> dict:
    """Nur Felder, die dieser Build kennt — eine Config aus einer neueren
    Version darf nicht am unbekannten Schlüssel scheitern."""
    if not isinstance(d, dict):
        return {}
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in d.items() if k in names}


def _profile_from_dict(d: dict) -> RuleProfile:
    stereo = StereoSettings(**_known(StereoSettings, d.pop("stereo", {})))
    output = OutputSettings(**_known(OutputSettings, d.pop("output", {})))
    d.pop("builtin", None)
    return RuleProfile(**_known(RuleProfile, d), stereo=stereo, output=output)


def _from_dict(data: dict) -> AppConfig:
    profiles = [_profile_from_dict(p) for p in data.get("user_profiles", [])]
    # Namenskollision mit Werksprofilen würde das Nutzerprofil unerreichbar
    # verschatten (profile() nimmt den ersten Treffer) → umbenennen
    builtin_names = {p.name for p in builtin_profiles()}
    for profile in profiles:
        if profile.name in builtin_names:
            profile.name += " (eigenes)"
    return AppConfig(
        tools=dict(data.get("tools", {})),
        active_profile=data.get("active_profile", "Deutsch bevorzugt"),
        log_expanded=bool(data.get("log_expanded", False)),
        output_dir=data.get("output_dir", ""),
        clean_names=bool(data.get("clean_names", False)),
        online_names=bool(data.get("online_names", False)),
        tmdb_key=data.get("tmdb_key", ""),
        check_updates=bool(data.get("check_updates", True)),
        window_geometry=str(data.get("window_geometry", "")),
        window_zoomed=bool(data.get("window_zoomed", False)),
        session=list(data.get("session", [])),
        user_profiles=profiles,
    )


def _import_legacy_ini(cfg: AppConfig) -> None:
    """Übernimmt Tool-Pfade aus der alten config.ini (einmalig)."""
    if not LEGACY_INI.exists():
        return
    ini = configparser.ConfigParser()
    try:
        ini.read(LEGACY_INI, encoding="utf-8")
    except (configparser.Error, OSError):
        return
    for name in ("mkvmerge", "ffmpeg"):
        path = ini.get("Pfade", name, fallback="")
        if path and Path(path).exists():
            cfg.tools[name] = path
