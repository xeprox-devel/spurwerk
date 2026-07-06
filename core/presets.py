"""Codec- und Downmix-Presets.

Hinweis zum Altcode: Der frühere „native AC3-Downmix“ über `-dmix_mode loro`
setzte nur Downmix-*Metadaten* in den Bitstream und mischte ohne `-ac 2`
nichts herunter (Ausgabe blieb 5.1). Deshalb nutzen hier alle Codecs
einheitlich den Pan-Filter.
"""

from __future__ import annotations

# Ziel-Kanallayouts. WICHTIG (lokal verifiziert): FFmpegs E-AC3-Encoder kann
# kein echtes 7.1 — er mischt still auf 5.1 herunter. AC3 endet per Spec bei
# 5.1. Echte 7.1-Ausgabe gibt es deshalb nur als AAC. Upmix gibt es nie:
# das effektive Ziel ist immer min(Quellkanäle, Zielkanäle).
CHANNEL_TARGETS: dict[str, int] = {"2.0": 2, "5.1": 6, "7.1": 8}

OUTPUT_CODECS: dict[str, dict] = {
    "ac3": {
        "label": "AC3 (Dolby Digital)",
        "short": "AC3",
        "ext": ".ac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k"],
        "default_bitrate": "640k",
        "channel_targets": ["2.0", "5.1"],
        "max_channels": 6,
    },
    "eac3": {
        "label": "E-AC3 (Dolby Digital+)",
        "short": "E-AC3",
        "ext": ".eac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k", "768k", "1024k"],
        "default_bitrate": "640k",
        "channel_targets": ["2.0", "5.1"],
        "max_channels": 6,
    },
    "aac": {
        "label": "AAC",
        "short": "AAC",
        "ext": ".m4a",
        "bitrates": ["128k", "160k", "192k", "256k", "320k", "384k", "512k"],
        "default_bitrate": "256k",
        "channel_targets": ["2.0", "5.1", "7.1"],
        "max_channels": 8,
    },
}

# Pan-Filter für universellen Downmix (5.1 und 7.1; fehlende Kanäle = 0)
_LORO = ("pan=stereo|"
         "FL=0.707*FC+0.707*FL+0.707*SL+0.707*BL+0.5*LFE|"
         "FR=0.707*FC+0.707*FR+0.707*SR+0.707*BR+0.5*LFE")
_PRO = ("pan=stereo|"
        "FL=1.414*FC+0.707*FL+0.5*BL+0.5*SL+0.5*LFE|"
        "FR=1.414*FC+0.707*FR+0.5*BR+0.5*SR+0.5*LFE,"
        "acompressor=ratio=4")
_LFEBOOST = ("pan=stereo|"
             "FL=0.707*FL+0.707*FC+0.707*BL+0.5*LFE|"
             "FR=0.707*FR+0.707*FC+0.707*BR+0.5*LFE,"
             "volume=1.5")

DOWNMIX_PRESETS: dict[str, dict] = {
    "loro": {
        "label": "Loro (ITU-Standard)",
        "hint": "Neutraler Referenz-Downmix nach ITU-Empfehlung.",
        "filter": _LORO,
    },
    "pro": {
        "label": "Pro Downmix + Kompressor",
        "hint": "Center lauter für Dialogverständlichkeit, Dynamik komprimiert.",
        "filter": _PRO,
    },
    "lfeboost": {
        "label": "LFE-Boost",
        "hint": "Subwoofer-Anteil betont, Gesamtpegel angehoben.",
        "filter": _LFEBOOST,
    },
    "passthrough": {
        "label": "Passthrough (kein Downmix)",
        "hint": "Nur Kanalreduktion auf 2.0 durch den Encoder, kein Filter.",
        "filter": None,
    },
}
