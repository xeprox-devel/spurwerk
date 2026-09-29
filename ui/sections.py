"""Einklappbare Sektion mit Chevron-Kopfzeile."""

from __future__ import annotations

from typing import Callable

import ttkbootstrap as ttk

# Hinweis in der Kopfzeile, wenn der aufgeklappte Inhalt keinen Platz hat
NO_ROOM = "Fenster zu niedrig"


class CollapsibleSection(ttk.Frame):
    """Kopfzeile (▸/▾ Titel) + Inhalt; meldet Strukturwechsel nach außen,
    damit das Fenster seine Höhe nachziehen kann.

    Verteilt jemand die Fensterhöhe (Hauptfenster, siehe ui/layout.py),
    entscheidet er per set_room(), ob der aufgeklappte Inhalt Platz hat —
    ohne Platz bleibt nur die Kopfzeile, und sie sagt, warum."""

    def __init__(self, master, title: str, *, expanded: bool = False,
                 on_toggle: Callable[[bool], None] | None = None):
        super().__init__(master)
        self._title = title
        self._expanded = expanded
        self._on_toggle = on_toggle
        # None = (noch) nicht entschieden: Inhalt bleibt verborgen, bis die
        # Höhenverteilung Platz meldet — so blitzt er beim Aufklappen nicht
        # kurz in voller Höhe auf. Ohne Höhenverteilung gilt immer True.
        self._room: bool | None = True
        self._managed = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # takefocus=False: kein gepunkteter Fokusrahmen nach dem Klick —
        # die Kopfzeile ist reine Maus-Bedienung. Hover-Farbe kommt aus
        # ttkbootstraps „info“, das in theme.py bewusst dem Akzent-Cyan
        # entspricht.
        self._header = ttk.Button(
            self, text=self._header_text(), bootstyle="secondary-link",
            command=self.toggle, cursor="hand2", takefocus=False)
        self._header.grid(row=0, column=0, sticky="w")

        self.body = ttk.Frame(self)
        self._sync_body()

    def _header_text(self) -> str:
        text = f"{'▾' if self._expanded else '▸'}  {self._title}"
        if self._expanded and self._room is False:
            text += f"  ·  {NO_ROOM}"
        return text

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def body_shown(self) -> bool:
        return bool(self.body.winfo_manager())

    def head_height(self) -> int:
        """Angeforderte Höhe der Kopfzeile (Pixel)."""
        return self._header.winfo_reqheight()

    def set_title(self, title: str) -> None:
        self._title = title
        self._header.configure(text=self._header_text())

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded and self._managed:
            self._room = None     # entscheidet gleich die Höhenverteilung
        self._sync_body()
        if self._on_toggle:
            self._on_toggle(expanded)

    def set_room(self, room: bool) -> None:
        """Von der Höhenverteilung: Hat der aufgeklappte Inhalt Platz?"""
        self._managed = True
        if room is not self._room:
            self._room = room
            self._sync_body()

    def _sync_body(self) -> None:
        show = bool(self._expanded and self._room)
        if show and not self.body_shown:
            self.body.grid(row=1, column=0, sticky="nsew")
        elif not show and self.body_shown:
            self.body.grid_remove()
        self._header.configure(text=self._header_text())
