"""Dateinamen aus Release-/Scene-Namen bereinigen (offline).

Beispiel:
  Obsession.Du.sollst.mich.lieben.2025.UHD.WEB-DL.2160p.HEVC.DV.HDR10Plus...
  → Obsession Du sollst mich lieben (2025)

Rein lokal, ohne Netz: Titel = alles vor der Jahreszahl, Punkte/Unterstriche
werden zu Leerzeichen. Die exakte Schreibweise (z. B. „Obsession – Du sollst
mich lieben") kennt nur eine Online-Datenbank; das ist bewusst nicht Teil
dieser Funktion.
"""

from __future__ import annotations

import re

_YEAR = re.compile(r"[.\s_(\[]((?:19|20)\d{2})[.\s_)\]]")
# Tags, die (auch ohne Jahr) den Titel beenden
_TAG = re.compile(
    r"\b(2160p|1080p|720p|480p|uhd|hdr10?\+?|hdr10plus|dv|dolby|web[-.]?dl|"
    r"webrip|bluray|bd(?:remux|rip)?|remux|hevc|h\.?26[45]|x26[45]|avc|"
    r"eac3|e-ac3|ac3|dts(?:-hd)?|truehd|atmos|aac|ddp?5|flac|multi|dual|dl|"
    r"german|english|complete|repack|proper|internal|unrated|extended)\b",
    re.IGNORECASE)
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def clean_title(stem: str) -> tuple[str, str | None]:
    """Zerlegt einen Dateinamen-Stamm in (Titel, Jahr|None)."""
    text = stem.replace("_", ".")
    year = None
    m = _YEAR.search(text)
    if m:
        year = m.group(1)
        text = text[:m.start()]
    else:
        # kein Jahr: beim ersten bekannten Tag abschneiden
        t = _TAG.search(text)
        if t:
            text = text[:t.start()]
    title = re.sub(r"[.\s]+", " ", text).strip(" -.")
    return title, year


def clean_filename(name: str, keep_ext: str | None = None) -> str:
    """„Release.Name.2025.UHD…mkv" → „Release Name (2025).mkv"."""
    from pathlib import Path
    p = Path(name)
    ext = keep_ext if keep_ext is not None else p.suffix
    title, _year = clean_title(p.stem)       # Jahr nur zur Suche, nicht im Namen
    if not title:
        title = p.stem                       # nichts erkannt: unverändert
    clean = _ILLEGAL.sub("", title).strip()
    return f"{clean}{ext}"


def output_filename(stem: str, source_suffix: str, to_mp4: bool) -> str:
    """Baut den Ausgabedateinamen aus dem (bereits bereinigten oder per TMDb
    ermittelten) Titel-Stamm plus Endung.

    Der Video-Modus bestimmt AUSSCHLIESSLICH die Endung: DV → Profil 8.1
    erzwingt .mp4, alles andere behält die Quell-Endung (.mkv). Kein
    Klammer-Suffix mehr im Namen — früher wurde beim HDR10-/DV-Remux
    „… [HDR10].mkv" bzw. „… [DV8.1].mp4" angehängt; das verschmutzte den
    sauberen Titel und war unerwünscht. Der Modus zeigt sich jetzt nur noch
    an der Endung."""
    ext = ".mp4" if to_mp4 else source_suffix
    return f"{stem}{ext}"
