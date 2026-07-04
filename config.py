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
    return AppConfig(
        tools=dict(data.get("tools", {})),
        active_profile=data.get("active_profile", "Deutsch bevorzugt"),
        log_expanded=bool(data.get("log_expanded", False)),
        user_profiles=[_profile_from_dict(p)
                       for p in data.get("user_profiles", [])],
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
