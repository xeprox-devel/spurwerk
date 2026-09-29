"""Regel-Engine: RuleProfile × MediaInfo → FilePlan.

Reine Funktionen ohne Seiteneffekte — die komplette Automatik-Logik ist
damit headless testbar. Manuelle Übersteuerungen (Origin.MANUAL) werden
von `reapply_rules` respektiert.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .langs import UND, display_name
from .model import (Action, FilePlan, MediaInfo, Origin, RuleProfile, Track,
                    TrackDecision)

# Nur echte Kommentar-Wörter: „Director's Cut“/„Regiefassung“ ist die
# Filmfassung, keine Kommentarspur — die Hauptspur darf nie wegfallen.
_COMMENTARY_RE = re.compile(
    r"kommentar|commentary|director[’'´`]?s?\s+(?:audio\s+)?comment",
    re.IGNORECASE)


def is_commentary(track: Track) -> bool:
    return bool(track.name and _COMMENTARY_RE.search(track.name))


def build_plan(media: MediaInfo, profile: RuleProfile) -> FilePlan:
    """Erzeugt den automatischen Plan für eine Datei. Die Datei bekommt
    eine EIGENE Kopie der Konvertierungs-Einstellungen (Job-Queue-Prinzip:
    jede Datei im Batch kann anders konfiguriert sein)."""
    plan = FilePlan(media=media,
                    output_path=profile.output.output_path_for(media.path),
                    stereo=replace(profile.stereo),
                    profile_name=profile.name)
    _apply(plan, profile)
    return plan


def reapply_rules(plan: FilePlan, profile: RuleProfile) -> None:
    """Wendet die Regeln neu an, lässt manuelle Entscheidungen unangetastet."""
    manual = {tid: dec for tid, dec in plan.decisions.items()
              if dec.origin is Origin.MANUAL}
    _apply(plan, profile)
    plan.decisions.update(manual)
    plan._ensure_default_valid()


def reset_manual(plan: FilePlan, profile: RuleProfile) -> None:
    """Verwirft alle manuellen Übersteuerungen der Datei."""
    _apply(plan, profile)


# ── Kernlogik ─────────────────────────────────────────────────────────────


def _apply(plan: FilePlan, profile: RuleProfile) -> None:
    media = plan.media
    plan.warnings = []
    decisions: dict[int, TrackDecision] = {}

    for t in media.by_type("video"):
        decisions[t.id] = TrackDecision(Action.COPY)

    audio_kept = _decide_audio(media, profile, decisions, plan.warnings)
    _decide_stereo(media, profile, decisions, audio_kept, plan.warnings)
    _decide_subs(media, profile, decisions)

    # Alles ohne Entscheidung (unbekannte Typen) bleibt erhalten
    for t in media.tracks:
        decisions.setdefault(t.id, TrackDecision(Action.COPY))

    plan.decisions = decisions
    _decide_default_audio(plan, profile)


def _decide_audio(media: MediaInfo, profile: RuleProfile,
                  decisions: dict[int, TrackDecision],
                  warnings: list[str]) -> list[Track]:
    audio = list(media.audio_tracks)
    if not audio:
        warnings.append("Datei enthält keine Audiospur.")
        return []

    kept: list[Track] = []
    for t in audio:
        if profile.drop_commentary and is_commentary(t):
            decisions[t.id] = TrackDecision(Action.DROP)
            continue
        if profile.audio_policy == "all":
            keep = True
        else:  # preferred_only
            keep = (t.lang in profile.lang_priority
                    or (t.lang == UND and profile.und_audio == "keep"))
        decisions[t.id] = TrackDecision(Action.COPY if keep else Action.DROP)
        if keep:
            kept.append(t)

    if not kept:
        # Fallback: nie stumm eine tonlose Datei bauen — erste Spur behalten
        first = audio[0]
        decisions[first.id] = TrackDecision(Action.COPY)
        kept = [first]
        wanted = ", ".join(display_name(c) for c in profile.lang_priority)
        warnings.append(
            f"Keine Audiospur in {wanted} gefunden — "
            f"erste Spur ({display_name(first.lang)}) wird behalten.")

    for t in kept:
        if t.lang == UND:
            warnings.append(
                f"Audiospur {t.id} hat keine Sprachkennung (und) — bitte prüfen.")

    # Abweichler: mehrere behaltene Spuren derselben Top-Sprache
    top = _top_lang(kept, profile)
    same = [t for t in kept if t.lang == top]
    if len(same) > 1:
        warnings.append(
            f"{len(same)} Audiospuren in {display_name(top)} — "
            f"Auswahl bitte prüfen (Spuren {', '.join(str(t.id) for t in same)}).")
    return kept


def _top_lang(kept: list[Track], profile: RuleProfile) -> str:
    for lang in profile.lang_priority:
        if any(t.lang == lang for t in kept):
            return lang
    return kept[0].lang if kept else UND


def _decide_stereo(media: MediaInfo, profile: RuleProfile,
                   decisions: dict[int, TrackDecision],
                   kept: list[Track], warnings: list[str]) -> None:
    if profile.stereo_policy == "never" or not kept:
        return
    top = _top_lang(kept, profile)
    target = next((t for t in kept if t.lang == top and t.is_multichannel), None)
    if target is None:
        return  # Top-Sprache ist bereits Stereo/Mono — nichts zu tun
    action = (Action.STEREO_ADD if profile.stereo_policy == "add"
              else Action.STEREO_REPLACE)
    decisions[target.id] = TrackDecision(action)


def _decide_subs(media: MediaInfo, profile: RuleProfile,
                 decisions: dict[int, TrackDecision]) -> None:
    for t in media.by_type("subtitles"):
        if profile.sub_policy == "all":
            keep = True
        elif profile.sub_policy == "none":
            keep = False
        elif profile.sub_policy == "forced_only":
            keep = t.forced and t.lang in profile.lang_priority
        else:  # preferred
            keep = t.lang in profile.lang_priority
        if profile.keep_forced_subs and t.forced and t.lang in profile.lang_priority:
            keep = True
        decisions[t.id] = TrackDecision(Action.COPY if keep else Action.DROP)


def _decide_default_audio(plan: FilePlan, profile: RuleProfile) -> None:
    """Bestimmt die eine Default-Audiospur der Ausgabe."""
    stereo = plan.stereo_sources()
    if stereo and profile.stereo_make_default:
        plan.default_audio_source = stereo[0].id
        plan.default_audio_is_stereo = True
        return
    kept = plan.kept_ids("audio")
    if kept:
        top = _top_lang([plan.media.track(i) for i in kept], profile)
        first_top = next((i for i in kept
                          if plan.media.track(i).lang == top), kept[0])
        plan.default_audio_source = first_top
        plan.default_audio_is_stereo = False
    elif stereo:
        plan.default_audio_source = stereo[0].id
        plan.default_audio_is_stereo = True
    else:
        plan.default_audio_source = None
        plan.default_audio_is_stereo = False
