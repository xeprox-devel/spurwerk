"""Einklappbare Sektion mit Chevron-Kopfzeile."""

from __future__ import annotations

from typing import Callable

import ttkbootstrap as ttk


class CollapsibleSection(ttk.Frame):
    """Kopfzeile (▸/▾ Titel) + Inhalt; meldet Strukturwechsel nach außen,
    damit das Fenster seine Höhe nachziehen kann."""

    def __init__(self, master, title: str, *, expanded: bool = False,
                 on_toggle: Callable[[bool], None] | None = None):
        super().__init__(master)
        self._title = title
        self._expanded = expanded
        self._on_toggle = on_toggle

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._header = ttk.Button(
            self, text=self._header_text(), bootstyle="secondary-link",
            command=self.toggle, cursor="hand2")
        self._header.grid(row=0, column=0, sticky="w")

        self.body = ttk.Frame(self)
        if expanded:
            self.body.grid(row=1, column=0, sticky="nsew")

    def _header_text(self) -> str:
        return f"{'▾' if self._expanded else '▸'}  {self._title}"

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_title(self, title: str) -> None:
        self._title = title
        self._header.configure(text=self._header_text())

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded:
            self.body.grid(row=1, column=0, sticky="nsew")
        else:
            self.body.grid_remove()
        self._header.configure(text=self._header_text())
        if self._on_toggle:
            self._on_toggle(expanded)
