"""Sprachcode-Normalisierung.

mkvmerge -J liefert `language` als ISO 639-2 (bibliografisch, z.B. "ger",
"fre") und — bei neueren Dateien — `language_ietf` (BCP 47, z.B. "de").
Intern rechnet Spurwerk durchgehend mit zweibuchstabigen Codes; unbekannte
Codes bleiben unverändert erhalten.
"""

from __future__ import annotations

# ISO 639-2 (bibliografisch UND terminologisch) → ISO 639-1
_ISO2_TO_ISO1 = {
    "ger": "de", "deu": "de",
    "eng": "en",
    "fre": "fr", "fra": "fr",
    "spa": "es",
    "ita": "it",
    "jpn": "ja",
    "chi": "zh", "zho": "zh",
    "rus": "ru",
    "por": "pt",
    "dut": "nl", "nld": "nl",
    "pol": "pl",
    "tur": "tr",
    "kor": "ko",
    "cze": "cs", "ces": "cs",
    "hun": "hu",
    "swe": "sv",
    "dan": "da",
    "nor": "no", "nob": "nb", "nno": "nn",
    "fin": "fi",
    "gre": "el", "ell": "el",
    "ara": "ar",
    "heb": "he",
    "tha": "th",
    "ukr": "uk",
    "rum": "ro", "ron": "ro",
}

UND = "und"

DISPLAY_NAMES = {
    "de": "Deutsch", "en": "Englisch", "fr": "Französisch", "es": "Spanisch",
    "it": "Italienisch", "ja": "Japanisch", "zh": "Chinesisch", "ru": "Russisch",
    "pt": "Portugiesisch", "nl": "Niederländisch", "pl": "Polnisch",
    "tr": "Türkisch", "ko": "Koreanisch", "cs": "Tschechisch", "hu": "Ungarisch",
    "sv": "Schwedisch", "da": "Dänisch", "no": "Norwegisch",
    "nb": "Norwegisch (Bokmål)", "nn": "Norwegisch (Nynorsk)",
    "fi": "Finnisch",
    "el": "Griechisch", "ar": "Arabisch", "he": "Hebräisch", "th": "Thai",
    "uk": "Ukrainisch", "ro": "Rumänisch", UND: "unbekannt",
}


def normalize(language: str | None, language_ietf: str | None = None) -> str:
    """Normalisiert auf einen zweibuchstabigen Code (oder "und").

    `language_ietf` hat Vorrang (bereits BCP 47); von "de-DE" bleibt "de".
    """
    if language_ietf and language_ietf != UND:
        return language_ietf.split("-", 1)[0].lower()
    if not language:
        return UND
    lang = language.lower()
    if lang == UND:
        return UND
    # Unbekannte ISO-639-2-Codes unverändert lassen — mkvmerge akzeptiert
    # sie als --language; ein erfundener 2-Buchstaben-Code wäre ungültig.
    return _ISO2_TO_ISO1.get(lang, lang)


def display_name(code: str) -> str:
    """Deutscher Anzeigename eines Sprachcodes ("de" → "Deutsch")."""
    return DISPLAY_NAMES.get(code, code)
