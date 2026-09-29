"""Drag & Drop — abgelegte Pfade auswerten (kein ttkbootstrap-Import, testbar).

tkdnd liefert `event.data` als Tcl-Liste: Pfade mit Leerzeichen stehen in
geschweiften Klammern, Klammern IM Namen (Plex/Jellyfin „{imdb-tt…}“)
bleiben darin verschachtelt, unbalancierte Klammern maskiert Tcl mit
Backslash. Korrekt zerlegen kann das nur Tcls eigener Listen-Parser
(`tk.splitlist`) — ein Regex zerschneidet solche Namen stillschweigend.
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable, Iterable
from pathlib import Path


def load_tkdnd(root, require: Callable) -> bool:
    """tkdnd ins Tk-Fenster laden; False statt Absturz, wenn das scheitert.

    tkinterdnd2 0.4/0.5 bringt nur tkdnd für Tcl 8 mit — unter Tcl 9
    (Python 3.14) wirft `_require` RuntimeError. Die App startet dann eben
    ohne Drag&Drop (der Leerzustand wirbt nicht dafür)."""
    try:
        root.TkdndVersion = require(root)
    except (RuntimeError, tkinter.TclError):
        return False
    return True


def split_drop_data(data, splitlist: Callable) -> list[str]:
    """`event.data` (Tcl-Liste) → einzelne Pfade, Maskierung aufgelöst."""
    try:
        items = splitlist(data)
    except tkinter.TclError:
        # keine gültige Tcl-Liste (tkdnd liefert immer eine) → als ein Pfad
        items = (data,)
    return [str(item) for item in items if str(item)]


def mkv_paths(items: Iterable[str]) -> tuple[list[str], list[str]]:
    """Abgelegte Pfade → (MKV-Dateien, übersprungene Elemente).

    Ordner steuern alle *.mkv darin bei (sortiert, nicht rekursiv);
    übersprungen wird, was weder MKV-Datei noch Ordner mit MKVs ist."""
    files: list[str] = []
    skipped: list[str] = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            found = sorted(str(f) for f in path.glob("*.mkv"))
            if found:
                files += found
            else:
                skipped.append(item)
        elif item.lower().endswith(".mkv"):
            files.append(item)
        else:
            skipped.append(item)
    return files, skipped
