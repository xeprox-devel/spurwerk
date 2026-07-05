"""Fenster-Geometrie merken — reine, testbare Logik (kein tkinter-Import).

Tk-Geometrien sehen aus wie „1200x800+120+60" (Breite×Höhe + X + Y). Beim
Wiederherstellen einer gespeicherten Geometrie muss sichergestellt sein, dass
das Fenster auf dem AKTUELLEN Bildschirm sichtbar landet — sonst öffnet es
sich nach einem Monitorwechsel (Notebook ohne Dock) komplett außerhalb.
"""

from __future__ import annotations

import re

_GEOM_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def clamp_geometry(geom: str, screen_w: int, screen_h: int,
                   min_w: int = 900, min_h: int = 420) -> str | None:
    """Prüft und klemmt „WxH+X+Y" auf den sichtbaren Bildschirm.

    Rückgabe: bereinigte Geometrie, oder None wenn unparsbar/unbrauchbar —
    dann fällt der Aufrufer auf die automatische Größe zurück.
    """
    if not geom:
        return None
    m = _GEOM_RE.match(geom.strip())
    if not m:
        return None
    w, h, x, y = (int(m.group(1)), int(m.group(2)),
                  int(m.group(3)), int(m.group(4)))
    if w <= 0 or h <= 0 or screen_w <= 0 or screen_h <= 0:
        return None
    # Größe: nicht kleiner als das Minimum, nicht größer als der Bildschirm
    w = max(min_w, min(w, screen_w))
    h = max(min_h, min(h, screen_h))
    # Position: so verschieben, dass das Fenster vollständig sichtbar bleibt
    x = max(0, min(x, screen_w - w))
    y = max(0, min(y, screen_h - h))
    return f"{w}x{h}+{x}+{y}"
