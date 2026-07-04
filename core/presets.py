"""Codec- und Downmix-Presets.

Hinweis zum Altcode: Der frühere „native AC3-Downmix" über `-dmix_mode loro`
setzte nur Downmix-*Metadaten* in den Bitstream und mischte ohne `-ac 2`
nichts herunter (Ausgabe blieb 5.1). Deshalb nutzen hier alle Codecs
einheitlich den Pan-Filter.
"""

from __future__ import annotations

OUTPUT_CODECS: dict[str, dict] = {
    "ac3": {
        "label": "AC3 (Dolby Digital)",
        "ext": ".ac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k"],
        "default_bitrate": "640k",
    },
    "eac3": {
        "label": "E-AC3 (Dolby Digital+)",
        "ext": ".eac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k", "768k"],
        "default_bitrate": "640k",
    },
    "aac": {
        "label": "AAC",
        "ext": ".m4a",
        "bitrates": ["128k", "160k", "192k", "256k", "320k"],
        "default_bitrate": "256k",
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
