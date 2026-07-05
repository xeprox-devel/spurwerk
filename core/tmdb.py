"""Optionaler Online-Titelabgleich über The Movie Database (TMDb).

Aus einem Release-Dateinamen wird der kanonische Filmtitel ermittelt
(z. B. „Obsession – Du sollst mich lieben (2025)"). Rein optional: ohne
API-Key oder bei jedem Netz-/Parsefehler gibt es None zurück, und der
Aufrufer nutzt dann die Offline-Bereinigung.

Nur der bereinigte Suchtitel + Jahr werden an TMDb gesendet.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .naming import _ILLEGAL, clean_title

SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
USER_AGENT = "Spurwerk/1.0"

# Eingebauter API-Key (wie bei Jellyfin) — damit Endnutzer sich NICHT
# registrieren müssen. Wird vom Verteiler EINMALIG mit einem kostenlosen
# TMDb-v3-Key befüllt (themoviedb.org → Einstellungen → API). Bleibt er
# leer, muss der Nutzer seinen eigenen Key eintragen oder es läuft offline.
BUILTIN_KEY = ""


def resolved_key(user_key: str = "") -> str:
    """Nutzer-Key hat Vorrang, sonst der eingebaute Key."""
    return (user_key.strip() or BUILTIN_KEY).strip()


def search_movie(api_key: str, query: str, year: str | None = None,
                 lang: str = "de-DE", timeout: float = 8.0) -> list[dict]:
    """Ruft die TMDb-Filmsuche auf. Wirft nie — liefert [] bei jedem Fehler."""
    if not api_key or not query:
        return []
    params = {"api_key": api_key, "query": query, "language": lang,
              "include_adult": "false"}
    if year:
        params["year"] = year
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results") or []
    except Exception:
        return []


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


def canonical_name(api_key: str, filename: str,
                   lang: str = "de-DE") -> str | None:
    """„Film.2025.UHD.WEB-DL…mkv" → „Kanonischer Titel (2025)" oder None."""
    from pathlib import Path
    title, year = clean_title(Path(filename).stem)
    if not title:
        return None
    results = search_movie(api_key, title, year, lang)
    if not results and year:
        results = search_movie(api_key, title, None, lang)  # ohne Jahr erneut
    best = _pick(results, year)
    if not best:
        return None
    name = best.get("title") or best.get("original_title")
    if not name:
        return None
    release_year = str(best.get("release_date", ""))[:4]
    clean = f"{name} ({release_year})" if release_year else name
    return _ILLEGAL.sub("", clean).strip()
