"""Persistenz: config.json (mit einmaligem Import der alten config.ini)."""

from __future__ import annotations

import configparser
import dataclasses
import json
import sys
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
    session: list[dict] = field(default_factory=list)  # offene Jobs

    def all_profiles(self) -> list[RuleProfile]:
        return builtin_profiles() + self.user_profiles

    def profile(self, name: str) -> RuleProfile:
        for p in self.all_profiles():
            if p.name == name:
                return p
        return self.all_profiles()[0]


def load() -> AppConfig:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return _from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            pass  # defekte Config: mit Defaults starten statt crashen
    cfg = AppConfig()
    _import_legacy_ini(cfg)
    return cfg


def save(cfg: AppConfig) -> None:
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
        "session": cfg.session,
        "user_profiles": [_profile_to_dict(p) for p in cfg.user_profiles],
    }
    CONFIG_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Serialisierung ────────────────────────────────────────────────────────


def _profile_to_dict(p: RuleProfile) -> dict:
    d = dataclasses.asdict(p)
    d.pop("builtin", None)
    return d


def _profile_from_dict(d: dict) -> RuleProfile:
    stereo = StereoSettings(**d.pop("stereo", {}))
    output = OutputSettings(**d.pop("output", {}))
    d.pop("builtin", None)
    known = {f.name for f in dataclasses.fields(RuleProfile)}
    clean = {k: v for k, v in d.items() if k in known}
    return RuleProfile(**clean, stereo=stereo, output=output)


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
