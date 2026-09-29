"""Vereinheitlichte Dateiliste — Einzeldatei ist ein Batch mit einem Eintrag."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import ttkbootstrap as ttk
from ttkbootstrap import utility

from . import theme


def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d} h" if h else f"{m}:{s:02d} min"


class FileList(ttk.Frame):
    """Treeview: Dateiname | Dauer | Plan | Status. iid = Dateipfad."""

    def __init__(self, master, *, on_select: Callable[[str], None],
                 height: int = 4):
        super().__init__(master)
        self.on_select = on_select

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        scale = lambda px: utility.scale_size(self, px)  # noqa: E731
        self.tree = ttk.Treeview(
            self, columns=("dauer", "plan", "status"),
            show="tree headings", selectmode="browse", height=height)
        self.tree.heading("#0", text="Datei", anchor="w")
        self.tree.heading("dauer", text="Dauer", anchor="w")
        self.tree.heading("plan", text="Plan", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.column("#0", width=scale(300), stretch=True)
        self.tree.column("dauer", width=scale(80), stretch=False)
        self.tree.column("plan", width=scale(300), stretch=False)
        self.tree.column("status", width=scale(110), stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                           bootstyle="round-dark")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure("error", foreground=theme.COLORS["danger"])
        self.tree.tag_configure("done", foreground=theme.COLORS["success"])
        # „läuft“ im Akzent-Cyan — info entspricht in theme.py bewusst dem Akzent
        self.tree.tag_configure("running", foreground=theme.COLORS["info"])
        self.tree.tag_configure("warn", foreground=theme.COLORS["warning"])
        self.tree.tag_configure("dim", foreground=theme.MUTED)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    # ── API ───────────────────────────────────────────────────────────────

    def paths(self) -> list[str]:
        return list(self.tree.get_children())

    def contains(self, path: str) -> bool:
        return self.tree.exists(path)

    def add_file(self, path: str, *, plan_text: str = "wird analysiert …",
                 status: str = "wird gescannt", tag: str = "dim") -> None:
        self.tree.insert("", "end", iid=path, text=f" {Path(path).name}",
                         values=("—", plan_text, status),
                         tags=(tag,) if tag else ())

    def update_file(self, path: str, *, duration: float | None = None,
                    plan_text: str | None = None, status: str | None = None,
                    tag: str = "") -> None:
        if not self.tree.exists(path):
            return
        if duration is not None:
            self.tree.set(path, "dauer", _fmt_duration(duration))
        if plan_text is not None:
            self.tree.set(path, "plan", plan_text)
        if status is not None:
            self.tree.set(path, "status", status)
        self.tree.item(path, tags=(tag,) if tag else ())

    def rename(self, old: str, new: str, **row) -> None:
        """Zeile auf einen neuen Pfad umschlüsseln (iid = Pfad): gleicher
        Platz in der Liste, Markierung bleibt; `row` wie bei update_file."""
        tree = self.tree
        if not tree.exists(old) or tree.exists(new):
            return
        selected = old in tree.selection()
        tree.insert("", tree.index(old), iid=new, text=f" {Path(new).name}",
                    values=tree.item(old, "values"),
                    tags=tree.item(old, "tags"))
        if selected:
            tree.selection_set(new)
        tree.delete(old)
        if row:
            self.update_file(new, **row)

    def remove_selected(self) -> list[str]:
        removed = list(self.tree.selection())
        for iid in removed:
            self.tree.delete(iid)
        return removed

    def remove(self, path: str) -> None:
        if self.tree.exists(path):
            self.tree.delete(path)

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def select(self, path: str) -> None:
        if self.tree.exists(path):
            self.tree.selection_set(path)
            self.tree.see(path)

    def selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_select(self, _event) -> None:
        path = self.selected()
        if path:
            self.on_select(path)
