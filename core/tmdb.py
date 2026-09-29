"""Optionaler Online-Titelabgleich über The Movie Database (TMDb).

Aus einem Release-Dateinamen wird der kanonische Filmtitel ermittelt
(z. B. „Obsession – Du sollst mich lieben (2025)“). Rein optional: ohne
API-Key oder bei jedem Netz-/Parsefehler gibt es None zurück, und der
Aufrufer nutzt dann die Offline-Bereinigung.

Nur der bereinigte Suchtitel + Jahr werden an TMDb gesendet.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from version import USER_AGENT

from .naming import _ILLEGAL, clean_title

SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

# Eingebauter API-Key (wie bei Jellyfin) — damit Endnutzer sich NICHT
# registrieren müssen. Der öffentliche Quellcode bleibt KEY-FREI: der Key
# wird beim Build aus der Umgebungsvariable SPURWERK_TMDB_KEY in das
# gitignorte Modul core/_apikey.py geschrieben (siehe build.ps1). Ohne
# eingebauten Key nutzt der Anwender seinen eigenen Key oder es läuft
# offline weiter.
try:
    from ._apikey import KEY as BUILTIN_KEY   # nur im gebauten Release
except ImportError:
    BUILTIN_KEY = ""

# Keys, die TMDb in dieser Sitzung abgelehnt hat (HTTP 401): ein vertippter
# eigener Key darf den funktionierenden eingebauten nicht stumm aushebeln.
_rejected: set[str] = set()
_notices: list[str] = []
_lock = threading.Lock()


class _KeyRejected(Exception):
    pass


def resolved_key(user_key: str = "") -> str:
    """Nutzer-Key hat Vorrang, sonst der eingebaute Key."""
    return (user_key.strip() or BUILTIN_KEY).strip()


def search_movie(api_key: str, query: str, year: str | None = None,
                 lang: str = "de-DE", timeout: float = 8.0) -> list[dict]:
    """Ruft die TMDb-Filmsuche auf. Wirft nie — liefert [] bei jedem Fehler.
    Lehnt TMDb den Key ab (HTTP 401), springt der eingebaute Key ein (falls
    vorhanden); den Hinweis dazu liefert take_notice()."""
    if not api_key or not query:
        return []
    for key in _candidates(api_key):
        try:
            return _request(key, query, year, lang, timeout)
        except _KeyRejected:
            _reject(key)          # nächster Kandidat: der eingebaute Key
        except Exception:
            return []
    return []


def _candidates(api_key: str) -> list[str]:
    keys = dict.fromkeys(k for k in (api_key.strip(), BUILTIN_KEY.strip()) if k)
    with _lock:
        return [k for k in keys if k not in _rejected]


def _request(api_key: str, query: str, year: str | None, lang: str,
             timeout: float) -> list[dict]:
    params = {"api_key": api_key, "query": query, "language": lang,
              "include_adult": "false"}
    if year:
        params["year"] = year
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise _KeyRejected from exc
        raise
    return data.get("results") or []


def _reject(key: str) -> None:
    """Merkt sich einen abgelehnten Key und legt EINEN Hinweis dafür ab."""
    with _lock:
        if key in _rejected:
            return
        _rejected.add(key)
        if key == BUILTIN_KEY.strip():
            msg = ("TMDb lehnt den eingebauten API-Key ab — Titel werden "
                   "offline bereinigt.")
        elif BUILTIN_KEY.strip():
            msg = ("TMDb lehnt den eigenen API-Key ab — es wird der "
                   "eingebaute Key verwendet. Bitte unter „TMDb-API-Key "
                   "eingeben …“ prüfen.")
        else:
            msg = ("TMDb lehnt den eigenen API-Key ab — Titel werden offline "
                   "bereinigt. Bitte unter „TMDb-API-Key eingeben …“ prüfen.")
        _notices.append(msg)


def take_notice() -> str | None:
    """Holt den nächsten noch nicht gemeldeten Key-Hinweis (für das
    Protokoll) — jeder Hinweis kommt genau einmal, sonst None."""
    with _lock:
        return _notices.pop(0) if _notices else None


def _pick(results: list[dict], year: str | None) -> dict | None:
    """Bestes Ergebnis: bevorzugt exakte Jahres-Übereinstimmung, sonst das
    populärste (TMDb sortiert bereits nach Relevanz)."""
    if not results:
        return None
    if year:
        for r in results:
            if str(r.get("release_date", "")).startswith(year):
                return r
    return results[0]


def _norm(text: str) -> str:
    """Titel vergleichbar machen: klein, ohne Satzzeichen, Umlaute wie in
    Release-Namen üblich ausgeschrieben, übrige Akzente weg („Amélie“ →
    „amelie“), „&“/„und“ wie „and“."""
    text = unicodedata.normalize("NFC", text).casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("&", " and ")):
        text = text.replace(a, b)
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    return " ".join("and" if w == "und" else w
                    for w in re.findall(r"\w+", text))


def _pick_by_title(results: list[dict], query: str) -> dict | None:
    """Nur ein Treffer, dessen Titel zur Suche passt — kein beliebiger."""
    want = _norm(query)
    return next((r for r in results
                 if want in (_norm(r.get("title") or ""),
                             _norm(r.get("original_title") or ""))), None)


def canonical_name(api_key: str, filename: str,
                   lang: str = "de-DE") -> str | None:
    """„Film.2025.UHD.WEB-DL…mkv“ → „Kanonischer Titel (2025)“ oder None."""
    from pathlib import Path
    title, year = clean_title(Path(filename).stem)
    if not title:
        return None
    results = search_movie(api_key, title, year, lang)
    if results:
        best = _pick(results, year)
    elif year:
        # Mit Jahr nichts gefunden: ohne Jahr nur einen Film mit passendem
        # Titel nehmen — sonst lieber offline bleiben als irgendeinen Film
        best = _pick_by_title(search_movie(api_key, title, None, lang), title)
    else:
        best = None
    if not best:
        return None
    name = best.get("title") or best.get("original_title")
    if not name:
        return None
    return _ILLEGAL.sub("", name).strip()   # nur der Titel, ohne Jahr
