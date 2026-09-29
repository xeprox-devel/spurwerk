"""Dateinamen aus Release-/Scene-Namen bereinigen (offline).

Beispiel:
  Obsession.Du.sollst.mich.lieben.2025.UHD.WEB-DL.2160p.HEVC.DV.HDR10Plus...
  → Obsession Du sollst mich lieben

Rein lokal, ohne Netz: Titel = alles vor der Jahreszahl, Punkte/Unterstriche
werden zu Leerzeichen. Die exakte Schreibweise (z. B. „Obsession – Du sollst
mich lieben") kennt nur eine Online-Datenbank; das ist bewusst nicht Teil
dieser Funktion.
"""

from __future__ import annotations

import re
from datetime import date

# Jahreszahl mit Trenner davor und Trenner/Ende danach (Lookarounds, damit
# direkt aufeinanderfolgende Zahlen wie „2049.2017“ beide gefunden werden)
_YEAR = re.compile(r"(?<=[.\s_(\[])((?:19|20)\d{2})(?=[.\s_)\]]|$)")
_SEP = re.compile(r"[.\s_()\[\]-]*")
# Tags, die (auch ohne Jahr) den Titel beenden
_TAG = re.compile(
    r"\b(2160p|1080p|720p|480p|uhd|hdr10?\+?|hdr10plus|dv|dolby|web[-.]?dl|"
    r"webrip|bluray|bd(?:remux|rip)?|remux|hevc|h\.?26[45]|x26[45]|avc|"
    r"eac3|e-ac3|ac3|dts(?:-hd)?|truehd|atmos|aac|ddp?5|flac|multi|dual|dl|"
    r"german|english|complete|repack|proper|internal|unrated|extended|"
    r"director'?s?[.\s-]?cut)\b",
    re.IGNORECASE)
# Auflösung/Quelle/Codec stehen in keinem Titel: dahinter beginnt sicher
# der Release-Teil (anders als bei „German“, „Dual“ … im Titel)
_TECH = re.compile(
    r"\b(2160p|1080p|720p|480p|web[-.]?dl|webrip|bluray|bd(?:remux|rip)|"
    r"remux|hevc|h\.?26[45]|x26[45])\b", re.IGNORECASE)
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def _pick_year(text: str) -> re.Match | None:
    """Das Erscheinungsjahr ist die LETZTE plausible Jahreszahl — bevorzugt
    eine, auf die ein bekannter Tag oder das Ende folgt. Zahlen davor gehören
    zum Titel („Blade.Runner.2049.2017…“, „Wonder.Woman.1984.2020…“).
    Liegt zwischen zwei Zahlen schon ein Tag („Film.1999.Extended.2020…“)
    oder steht eine Zahl hinter Auflösung/Codec („Film.1080p.2020“), war
    der Titel davor zu Ende — solche späteren Zahlen zählen nicht."""
    latest = date.today().year + 1
    cands: list[re.Match] = []
    for m in _YEAR.finditer(text):
        head = text[:m.start()]
        if int(m.group(1)) > latest or not _strip_title(head):
            continue
        if _TECH.search(head) or (
                cands and _TAG.search(text[cands[0].end():m.start()])):
            break
        cands.append(m)
    for m in reversed(cands):
        rest = text[_SEP.match(text, m.end()).end():]
        if not rest or _TAG.match(rest):
            return m
    return cands[-1] if cands else None


def _strip_title(text: str) -> str:
    # Punkte/Leerzeichen vereinheitlichen, offene Klammern/Striche am Ende weg
    return re.sub(r"[.\s]+", " ", text).rstrip(" -.([{").strip(" -.")


def clean_title(stem: str) -> tuple[str, str | None]:
    """Zerlegt einen Dateinamen-Stamm in (Titel, Jahr|None)."""
    text = stem.replace("_", ".")
    year = None
    m = _pick_year(text)
    if m:
        year = m.group(1)
        text = text[:m.start()]
    else:
        # kein Jahr: beim ersten bekannten Tag abschneiden
        t = _TAG.search(text)
        if t:
            text = text[:t.start()]
    return _strip_title(text), year


def clean_filename(name: str) -> str:
    """„Release.Name.2025.UHD…mkv“ → „Release Name.mkv“ (Endung bleibt)."""
    from pathlib import Path
    p = Path(name)
    title, _year = clean_title(p.stem)       # Jahr nur zur Suche, nicht im Namen
    if not title:
        title = p.stem                       # nichts erkannt: unverändert
    clean = _ILLEGAL.sub("", title).strip()
    return f"{clean}{p.suffix}"
