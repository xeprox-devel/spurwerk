"""Einklappbares Protokoll mit Farbtags aus dem Theme."""

from __future__ import annotations

from tkinter import scrolledtext
from typing import Callable

import ttkbootstrap as ttk

from . import theme
from .layout import LOG_LINES
from .sections import NO_ROOM, CollapsibleSection


class LogPanel(CollapsibleSection):
    def __init__(self, master, *, expanded: bool = False,
                 on_toggle: Callable[[bool], None] | None = None,
                 on_notice: Callable[[], None] | None = None):
        super().__init__(master, "Protokoll", expanded=expanded,
                         on_toggle=on_toggle)
        self._count = 0
        # letzter Ausweg der Höhenverteilung: samt Kopfzeile ausgeblendet —
        # on_notice meldet jede Änderung des Hinweises dafür (notice)
        self._hidden = False
        self._on_notice = on_notice

        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)

        # Standard-Textfarbe Cyan — dieselbe Farbfamilie wie die
        # „+ Dateien …“-Buttons (Nutzerentscheid: ein Akzent, eine Linie).
        # height = natürliche Zeilenzahl; bei knapper Fensterhöhe setzt die
        # Höhenverteilung weniger (fit)
        self.text = scrolledtext.ScrolledText(
            self.body, wrap="word", height=LOG_LINES[0], state="disabled",
            bg=theme.COLORS["dark"], fg=theme.COLORS["primary"],
            insertbackground=theme.COLORS["primary"], relief="flat",
            font=("Cascadia Mono", 9), borderwidth=0)
        self.text.grid(row=0, column=0, sticky="nsew", pady=(2, 0))

        # Ein Tag, eine Bedeutung: step = Prozessschritt (hell, hebt sich
        # vom Cyan-Standard ab), warn = Warnung (Amber), new = neu erzeugte
        # Spur/Datei (Cyan wie der Standard).
        self.text.tag_config("error", foreground=theme.COLORS["danger"])
        self.text.tag_config("success", foreground=theme.COLORS["success"])
        # Hinweise laufen im Standard-Cyan mit (Nutzerentscheid) — nur
        # Fehler/Erfolg/Warnung und Schritt-Zeilen stechen heraus.
        self.text.tag_config("info", foreground=theme.COLORS["primary"])
        self.text.tag_config("step", foreground=theme.COLORS["fg"])
        self.text.tag_config("warn", foreground=theme.COLORS["warning"])
        self.text.tag_config("new", foreground=theme.COLORS["primary"])
        self.text.tag_config("dim", foreground=theme.MUTED)

        ttk.Button(self.body, text="Protokoll leeren",
                   bootstyle="secondary-link",
                   command=self.clear).grid(row=1, column=0, sticky="e")

    def fit(self, lines: int, visible: bool = True) -> None:
        """Von der Höhenverteilung (ui/layout.py): `lines` Textzeilen für den
        aufgeklappten Inhalt, 0 = nur die Kopfzeile; visible=False blendet
        das Protokoll ganz aus (letzter Ausweg bei zu kleinem Bildschirm).
        Gesetzt wird nur, was sich ändert."""
        if visible and not self.winfo_manager():
            self.grid()               # gemerkte Grid-Optionen
        elif not visible and self.winfo_manager():
            self.grid_remove()
        if lines and int(self.text.cget("height")) != lines:
            self.text.configure(height=lines)
        self.set_room(lines > 0)
        if self._hidden != (not visible):
            self._hidden = not visible
            self._notify()

    @property
    def notice(self) -> str:
        """Hinweis für die Statuszeile, solange das Protokoll ganz
        ausgeblendet ist — sonst leer. Er zählt mit: Neue Meldungen fallen
        auch ohne sichtbares Protokoll auf."""
        if not self._hidden:
            return ""
        return f"⚠ {self._title} ausgeblendet · {NO_ROOM}"

    def _notify(self) -> None:
        if self._on_notice:
            self._on_notice()

    def log(self, message: str, tag: str | None = None) -> None:
        self.text.config(state="normal")
        self.text.insert("end", message + "\n", tag or ())
        self.text.yview("end")
        self.text.config(state="disabled")
        self._count += 1
        self.set_title(f"Protokoll ({self._count})")
        if self._hidden:
            self._notify()

    def clear(self) -> None:
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._count = 0
        self.set_title("Protokoll")
        if self._hidden:
            self._notify()
