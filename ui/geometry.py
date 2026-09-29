"""Fenster-Geometrie — reine, testbare Logik (kein tkinter-Import) plus die
Windows-Abfragen dazu (ctypes).

Tk-Geometrien sehen aus wie „1200x800+120+60“ (Breite×Höhe + X + Y). Beim
Wiederherstellen einer gespeicherten Geometrie muss sichergestellt sein, dass
das Fenster auf dem AKTUELLEN Bildschirm sichtbar landet — sonst öffnet es
sich nach einem Monitorwechsel (Notebook ohne Dock) komplett außerhalb.

Geklemmt wird gegen den VIRTUELLEN Desktop (alle Monitore zusammen): dessen
Ursprung kann negativ sein (Zweitmonitor links vom Primärmonitor). Die
ctypes-Werte dafür beschafft der Aufrufer (siehe app.py); ohne Angabe gilt
der Ein-Monitor-Fall mit Ursprung (0, 0).

Größe und Lage im laufenden Betrieb richten sich nach dem ARBEITSBEREICH des
Monitors (ohne Taskleiste) und dem sichtbaren Fensterrahmen: Tk-Größen
meinen nur den Client-Bereich, Tk-Positionen die linke obere Ecke samt der
unsichtbaren Greifränder von Windows 10/11.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

# Tk schreibt negative Positionen (Monitor links/oberhalb des Hauptmonitors)
# als „+-1500+100“. Ein nacktes „-1500“ heißt in Tk dagegen „Abstand vom
# RECHTEN/unteren Rand“ — das ist keine Position und wird nicht gelesen.
_GEOM_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


def clamp_geometry(geom: str, screen_w: int, screen_h: int,
                   min_w: int = 900, min_h: int = 420,
                   screen_x: int = 0, screen_y: int = 0) -> str | None:
    """Prüft und klemmt „WxH+X+Y“ auf den sichtbaren Bereich.

    `screen_x`/`screen_y` sind der Ursprung des virtuellen Desktops
    (0/0 bei einem Monitor, negativ bei einem Zweitmonitor links/oben).

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
    # Größe: nicht kleiner als das Minimum, nicht größer als der Desktop
    w = max(min_w, min(w, screen_w))
    h = max(min_h, min(h, screen_h))
    # Position: so verschieben, dass das Fenster vollständig sichtbar bleibt
    x = max(screen_x, min(x, screen_x + screen_w - w))
    y = max(screen_y, min(y, screen_y + screen_h - h))
    return f"{w}x{h}+{x}+{y}"   # Tk-Form, auch negativ: „+-1920+60“


# ── Arbeitsbereich und Fensterrahmen ───────────────────────────────────────


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Frame:
    """Sichtbarer Fensterrahmen um den Client-Bereich (Titelleiste, Ränder)
    und der Versatz `dx`/`dy` vom Tk-Ursprung („+X+Y“, mit unsichtbaren
    Greifrändern) zum sichtbaren Rahmen."""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    dx: int = 0
    dy: int = 0


def split_geometry(geom: str) -> tuple[int, int, int, int] | None:
    """„WxH+X+Y“ (wie clamp_geometry sie liefert) → (w, h, x, y)."""
    m = _GEOM_RE.match(geom.strip()) if geom else None
    return tuple(int(g) for g in m.groups()) if m else None


def client_limit(work: Rect, frame: Frame) -> tuple[int, int]:
    """Größter Client-Bereich, dessen sichtbarer Rahmen in `work` passt."""
    return (max(1, work.w - frame.left - frame.right),
            max(1, work.h - frame.top - frame.bottom))


def centered(w: int, h: int, work: Rect, frame: Frame) -> tuple[int, int]:
    """Tk-Position, die ein Fenster mit Client-Größe w×h im Arbeitsbereich
    zentriert — die Titelleiste bleibt dabei immer erreichbar."""
    vis_w = w + frame.left + frame.right
    vis_h = h + frame.top + frame.bottom
    return (work.x + max(0, (work.w - vis_w) // 2) - frame.dx,
            work.y + max(0, (work.h - vis_h) // 2) - frame.dy)


def restored_width(w: int, monitor: Rect, work: Rect, frame: Frame) -> int:
    """Gemerkte Client-Breite für ihren Monitor: Ist sie höchstens so breit
    wie der ganze Monitor, wird sie auf dessen Arbeitsbereich begrenzt —
    sonst ragte der Rahmen (bzw. bei seitlicher Taskleiste ein Stück des
    Fensters) über den Rand. Breiter als der Monitor heißt: bewusst über
    mehrere Monitore gezogen — dann bleibt sie."""
    if w <= monitor.w:
        return min(w, client_limit(work, frame)[0])
    return w


def inside(x: int, y: int, w: int, h: int, work: Rect,
           frame: Frame) -> tuple[int, int]:
    """Tk-Position so verschieben, dass der sichtbare Rahmen im Arbeitsbereich
    liegt. Senkrecht immer (oben hat Vorrang: Titelleiste); waagrecht nur,
    wenn das Fenster hineinpasst — ein bewusst über zwei Monitore gezogenes
    Fenster bleibt, wo es ist."""
    vis_x, vis_y = x + frame.dx, y + frame.dy
    vis_w = w + frame.left + frame.right
    vis_h = h + frame.top + frame.bottom
    if vis_w <= work.w:
        vis_x = max(work.x, min(vis_x, work.x + work.w - vis_w))
    vis_y = max(work.y, min(vis_y, work.y + work.h - vis_h))
    return vis_x - frame.dx, vis_y - frame.dy


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    # eigene DLL-Instanzen: Prototypen setzen, ohne die globalen
    # ctypes.windll-Funktionen anderer Module zu verändern
    _user32 = ctypes.WinDLL("user32")
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = wintypes.HMONITOR
    _user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT),
                                        wintypes.DWORD]
    _user32.MonitorFromRect.restype = wintypes.HMONITOR
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                        ctypes.POINTER(_MonitorInfo)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _dwmapi = ctypes.WinDLL("dwmapi")
    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def _rect(r) -> Rect | None:
    if r.right <= r.left or r.bottom <= r.top:
        return None
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def monitor_areas(hwnd: int = 0,
                  near: Rect | None = None) -> tuple[Rect, Rect] | None:
    """(ganzer Monitor, Arbeitsbereich ohne Taskleiste) des Monitors, auf
    dem das Fenster — bzw. das Rechteck `near` — größtenteils liegt; None
    außerhalb von Windows oder bei Fehlern."""
    if sys.platform != "win32" or not (hwnd or near):
        return None
    try:
        if near is not None:
            r = wintypes.RECT(near.x, near.y, near.x + near.w, near.y + near.h)
            monitor = _user32.MonitorFromRect(ctypes.byref(r), 2)
        else:
            monitor = _user32.MonitorFromWindow(hwnd, 2)  # …DEFAULTTONEAREST
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        if monitor and _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            whole, work = _rect(info.rcMonitor), _rect(info.rcWork)
            if whole and work:
                return whole, work
    except OSError:
        pass
    return None


def monitor_work_area(hwnd: int = 0, near: Rect | None = None) -> Rect | None:
    """Arbeitsbereich (ohne Taskleiste) des Monitors, auf dem das Fenster —
    bzw. das Rechteck `near` — größtenteils liegt; None außerhalb von
    Windows oder bei Fehlern."""
    areas = monitor_areas(hwnd, near)
    return areas[1] if areas else None


def visible_bounds(hwnd: int) -> Rect | None:
    """Sichtbare Fenstergrenzen laut DWM (ohne unsichtbare Greifränder) —
    None außerhalb von Windows oder bei Fehlern."""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        r = wintypes.RECT()
        if _dwmapi.DwmGetWindowAttribute(       # DWMWA_EXTENDED_FRAME_BOUNDS
                hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
            return _rect(r)
    except OSError:
        pass
    return None


def default_frame() -> Frame:
    """Rahmen-Schätzung aus den Systemmetriken, solange das Fenster noch
    nicht messbar ist (Titelleiste = Beschriftung + Rahmen + Polster)."""
    if sys.platform != "win32":
        return Frame()
    try:
        metric = ctypes.windll.user32.GetSystemMetrics
        edge = metric(33) + metric(92)       # SM_CYFRAME + SM_CXPADDEDBORDER
        return Frame(left=1, top=metric(4) + edge, right=1, bottom=1,
                     dx=max(0, edge - 1))    # SM_CYCAPTION
    except (OSError, AttributeError):
        return Frame()
