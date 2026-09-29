"""Höhenverteilung des Hauptfensters — reine, testbare Logik (kein tkinter).

Die Arbeitsansicht hat drei elastische Teile, jeweils in ganzen Zeilen:
Dateiliste, Spurtabelle (das Herzstück) und das aufgeklappte Protokoll.
Alles andere — Kopfleiste, Knopfzeilen, Profil, Legende, Vorschau, Audio-
Konvertierung, Start, Fortschritt, Abstände — ist starr und wird nie
beschnitten.

Reicht die Höhe nicht für alles in natürlicher Größe, geben die Teile in
fester Reihenfolge nach, jede Stufe erst, wenn die vorige ausgeschöpft ist:

1. das Protokoll: Textzeilen 9 → 3, dann nur noch seine Kopfzeile,
2. die Spurtabelle: 6 → 4 Zeilen,
3. die Dateiliste: 4 → 3 Zeilen.

Das ergibt die Mindesthöhe (`minimum`). Kleiner wird das Fenster nicht,
solange der Arbeitsbereich des Monitors sie hergibt. Ist er kleiner (sehr
hohe Skalierung, Mini-Bildschirm), greift der letzte Ausweg:

4. die Dateiliste geht auf 2 Zeilen (sie scrollt),
5. das Protokoll verschwindet samt Kopfzeile — die Statuszeile sagt es
   (LogPanel.notice), Meldungen gehen also nie unbemerkt unter,
6. die Spurtabelle geht auf 2 Zeilen (sie scrollt).

Reicht selbst das nicht, nimmt Tk den Rest von der Spurtabelle (ihre Zeile
trägt das Gewicht) — Start-Knopf und Fortschritt bleiben sichtbar.
Zusätzliche Höhe geht an die Spurtabelle; Dateiliste und Protokoll
behalten ihre natürliche Größe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator

# (natürlich, Minimum) in Zeilen
FILE_ROWS = (4, 3)
TRACK_ROWS = (6, 4)
LOG_LINES = (9, 3)      # weniger als 3 Textzeilen lohnen nicht → Kopfzeile
EMERGENCY_ROWS = 2      # letzter Ausweg für Datei- und Spurliste


@dataclass(frozen=True)
class Elastic:
    """Ein zeilenweise wachsender Teil: `base + rows · row` Pixel hoch, aber
    nie weniger als `floor` — ein Nachbar wie die Bildlaufleiste streckt ihn
    bei wenigen Zeilen auf seine eigene Mindesthöhe."""
    base: int       # Rahmen, Spaltenköpfe, starres Beiwerk
    row: int        # Pixel je Zeile
    natural: int
    minimum: int
    floor: int = 0

    def px(self, rows: int) -> int:
        return max(self.base + rows * self.row, self.floor)


@dataclass(frozen=True)
class Metrics:
    """Gemessene Höhen der Arbeitsansicht in Pixeln."""
    rigid: int              # alles Starre zusammen (samt Fensterrand)
    files: Elastic          # Dateiliste
    tracks: Elastic         # Spurtabelle
    log_head: int           # Protokoll-Kopfzeile samt Abstand darüber
    log: Elastic | None = None   # Protokoll-Inhalt; None = eingeklappt


@dataclass(frozen=True)
class Allocation:
    files: int
    tracks: int
    log_lines: int = 0      # 0 = vom Protokoll nur die Kopfzeile
    log_head: bool = True   # False = letzter Ausweg: Protokoll ausgeblendet


@dataclass(frozen=True)
class Needs:
    """Was das Gezeigte braucht (Pixel, Client-Bereich des Fensters)."""
    natural_w: int
    natural_h: int
    min_w: int
    min_h: int
    metrics: Metrics | None = None   # None = Leerzustand, nichts Elastisches


def height(m: Metrics, a: Allocation) -> int:
    """Gesamthöhe einer Zuteilung."""
    total = m.rigid + m.files.px(a.files) + m.tracks.px(a.tracks)
    if a.log_head:
        total += m.log_head
        if a.log_lines and m.log is not None:
            total += m.log.px(a.log_lines)
    return total


def natural(m: Metrics) -> Allocation:
    return Allocation(m.files.natural, m.tracks.natural,
                      m.log.natural if m.log is not None else 0)


def minimum(m: Metrics) -> Allocation:
    """Kleinste Zuteilung ohne letzten Ausweg — Protokoll-Kopfzeile bleibt."""
    return Allocation(m.files.minimum, m.tracks.minimum)


def _steps(m: Metrics) -> Iterator[dict]:
    """Die Abbau-Reihenfolge: je Schritt eine Zeile weniger (bzw. ein Teil
    weg). Wer früher kommt, gibt zuerst nach."""
    if m.log is not None:
        for lines in range(m.log.natural - 1, m.log.minimum - 1, -1):
            yield {"log_lines": lines}
        yield {"log_lines": 0}
    for rows in range(m.tracks.natural - 1, m.tracks.minimum - 1, -1):
        yield {"tracks": rows}
    for rows in range(m.files.natural - 1, m.files.minimum - 1, -1):
        yield {"files": rows}
    # letzter Ausweg — nur bei einem Arbeitsbereich unter der Mindesthöhe
    for rows in range(m.files.minimum - 1, EMERGENCY_ROWS - 1, -1):
        yield {"files": rows}
    yield {"log_head": False}
    for rows in range(m.tracks.minimum - 1, EMERGENCY_ROWS - 1, -1):
        yield {"tracks": rows}


def allocate(avail: int, m: Metrics) -> Allocation:
    """Größte Zuteilung nach Priorität, die in `avail` Pixel passt — die
    Abbau-Reihenfolge wird nur so weit wie nötig gegangen, also wächst die
    Zuteilung nie, wenn `avail` schrumpft. Was übrig bleibt (Reste unter
    einer Zeile, die frei gewordene Protokoll-Kopfzeile), bekommt die
    Spurtabelle über ihr Grid-Gewicht."""
    alloc = natural(m)
    for step in _steps(m):
        if height(m, alloc) <= avail:
            break
        alloc = replace(alloc, **step)
    return alloc
