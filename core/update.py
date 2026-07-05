"""Update-Prüfung gegen die GitHub-Releases von Spurwerk.

Bewusst schlank und höflich: eine einzige, unauthentifizierte Anfrage beim
Start, keinerlei Telemetrie, kein Nutzer-Tracking. Jeder Fehler (kein Netz,
kein Release, Zeitüberschreitung) endet in None — der Aufrufer muss nie eine
Ausnahme fangen und die App startet auch offline normal.

Reiner Kern (`parse_version`, `is_newer`) ist ohne Netz testbar.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

REPO = "xeprox-devel/spurwerk"
_API = "https://api.github.com/repos/{repo}/releases/latest"
_RELEASES = "https://github.com/{repo}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    latest: str    # Anzeigeversion ohne führendes „v", z. B. „1.1.0"
    url: str       # Release-Seite zum Öffnen


def parse_version(text: str) -> tuple[int, ...]:
    """„v1.2.3" / „1.2.3-beta" → (1, 2, 3). Führendes „v" fällt weg, ab dem
    ersten nicht-numerischen Teil wird abgebrochen. Unbrauchbares ergibt ()."""
    parts: list[int] = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """True, wenn `latest` echt neuer als `current` ist (semantischer
    Zahlenvergleich, nicht lexikografisch: 1.10.0 > 1.9.0)."""
    latest_v = parse_version(latest)
    if not latest_v:
        return False
    return latest_v > parse_version(current)


def check_latest(current: str, repo: str = REPO,
                 timeout: float = 6.0) -> UpdateInfo | None:
    """Neueste Release-Version bei GitHub abfragen. Gibt None zurück bei
    Fehler, fehlendem Release ODER wenn bereits aktuell — nie eine Ausnahme."""
    try:
        req = urllib.request.Request(
            _API.format(repo=repo),
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"Spurwerk/{current}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name", "") or "")
    if not tag or not is_newer(tag, current):
        return None
    url = str(data.get("html_url", "") or _RELEASES.format(repo=repo))
    return UpdateInfo(latest=tag.strip().lstrip("vV"), url=url)
