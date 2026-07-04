"""Mitgelieferte Regel-Profile (Werks-Presets, schreibgeschützt)."""

from __future__ import annotations

from .model import OutputSettings, RuleProfile, StereoSettings


def builtin_profiles() -> list[RuleProfile]:
    return [
        RuleProfile(
            name="Deutsch bevorzugt",
            lang_priority=["de"],
            audio_policy="preferred_only",
            stereo_policy="add",
            sub_policy="preferred",
            builtin=True,
        ),
        RuleProfile(
            name="Deutsch + Englisch",
            lang_priority=["de", "en"],
            audio_policy="preferred_only",
            stereo_policy="add",
            sub_policy="preferred",
            builtin=True,
        ),
        RuleProfile(
            name="Nur remuxen — alles behalten",
            lang_priority=["de", "en"],
            audio_policy="all",
            stereo_policy="never",
            sub_policy="all",
            drop_commentary=False,
            builtin=True,
        ),
        RuleProfile(
            name="Deutsch — nur Stereo (kompakt)",
            lang_priority=["de"],
            audio_policy="preferred_only",
            stereo_policy="replace",
            sub_policy="preferred",
            builtin=True,
        ),
    ]


def describe(profile: RuleProfile) -> str:
    """Der Klartext-Satz für die Regelzeile."""
    from .langs import display_name
    langs = " + ".join(display_name(c) for c in profile.lang_priority)

    if profile.audio_policy == "all":
        audio = "Behalte alle Audiospuren"
    else:
        audio = f"Behalte {langs}-Audio"

    fmt = profile.stereo.short_label()
    stereo = {
        "add": f"Mehrkanal → zusätzlich {fmt}-Kopie",
        "replace": f"Mehrkanal → durch {fmt} ersetzen",
        "never": "keine Konvertierung (verlustfrei)",
    }[profile.stereo_policy]

    subs = {
        "preferred": f"Subs: {langs}",
        "forced_only": "Subs: nur forced",
        "all": "Subs: alle",
        "none": "Subs: keine",
    }[profile.sub_policy]

    parts = [audio, stereo, subs]
    if profile.drop_commentary:
        parts.append("Kommentarspuren raus")
    return " · ".join(parts)
