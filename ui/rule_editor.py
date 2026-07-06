"""Regel-Editor: klickbare Sprachregeln statt kryptischer Syntax.

Werksprofile sind schreibgeschützt — Änderungen daran werden als neues
Profil gespeichert. Eigene Profile lassen sich direkt ändern und löschen.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace

import ttkbootstrap as ttk
from ttkbootstrap.dialogs import Messagebox

from core.langs import DISPLAY_NAMES, display_name
from core.model import RuleProfile

from . import theme

_LANG_CHOICES = [c for c in DISPLAY_NAMES if c != "und"]


class RuleEditorDialog(ttk.Toplevel):
    """result: None (abgebrochen) oder Tupel (aktion, profil) mit
    aktion ∈ {"apply", "new", "delete"}."""

    def __init__(self, master, profile: RuleProfile,
                 existing_names: list[str]):
        super().__init__(title=f"Regeln — {profile.name}", master=master,
                         resizable=(False, False))
        self.result: tuple[str, RuleProfile] | None = None
        self._source = profile
        self._existing = set(existing_names)
        self._langs: list[str] = list(profile.lang_priority)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self._build_lang_box(body)
        self._build_audio_box(body)
        self._build_stereo_box(body)
        self._build_sub_box(body)
        self._build_output_box(body)
        self._build_buttons(body)

        self.transient(master)
        self.grab_set()
        theme.apply_dark_titlebar(self)
        self.place_window_center()

    # ── Abschnitte ────────────────────────────────────────────────────────

    def _build_lang_box(self, parent) -> None:
        box = ttk.Labelframe(parent, text=" Sprach-Priorität ", padding=10)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))

        self.lang_list = tk.Listbox(
            box, height=4, width=22, activestyle="none", relief="flat",
            bg=theme.COLORS["inputbg"], fg=theme.COLORS["fg"],
            selectbackground=theme.COLORS["selectbg"],
            selectforeground=theme.COLORS["selectfg"],
            highlightthickness=0)
        self.lang_list.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._refresh_langs()

        col = ttk.Frame(box)
        col.grid(row=0, column=1, rowspan=3, sticky="n", padx=(8, 0))
        for text, cmd in [("↑", lambda: self._move_lang(-1)),
                          ("↓", lambda: self._move_lang(+1)),
                          ("−", self._remove_lang)]:
            ttk.Button(col, text=text, width=3,
                       bootstyle="secondary-outline", command=cmd
                       ).pack(pady=1)

        add_row = ttk.Frame(box)
        add_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.lang_cb = ttk.Combobox(
            add_row, state="readonly", width=16,
            values=[display_name(c) for c in _LANG_CHOICES])
        self.lang_cb.pack(side="left")
        ttk.Button(add_row, text="+ Hinzufügen", bootstyle="primary-outline",
                   command=self._add_lang).pack(side="left", padx=(6, 0))

    def _build_audio_box(self, parent) -> None:
        box = ttk.Labelframe(parent, text=" Audiospuren ", padding=10)
        box.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        p = self._source
        self.audio_policy = ttk.StringVar(value=p.audio_policy)
        ttk.Radiobutton(box, text="Nur bevorzugte Sprachen behalten",
                        variable=self.audio_policy, value="preferred_only",
                        bootstyle="primary").pack(anchor="w", pady=2)
        ttk.Radiobutton(box, text="Alle Audiospuren behalten",
                        variable=self.audio_policy, value="all",
                        bootstyle="primary").pack(anchor="w", pady=2)
        self.und_keep = ttk.BooleanVar(value=p.und_audio == "keep")
        ttk.Checkbutton(box, text="Spuren ohne Sprachkennung (und) behalten",
                        variable=self.und_keep, bootstyle="primary"
                        ).pack(anchor="w", pady=(8, 2))
        self.drop_comm = ttk.BooleanVar(value=p.drop_commentary)
        ttk.Checkbutton(box, text="Kommentarspuren automatisch entfernen",
                        variable=self.drop_comm, bootstyle="primary"
                        ).pack(anchor="w", pady=2)

    def _build_stereo_box(self, parent) -> None:
        box = ttk.Labelframe(parent,
                             text=" Konvertierung (bei Mehrkanal-Quellen) ",
                             padding=10)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        p = self._source
        self.stereo_policy = ttk.StringVar(value=p.stereo_policy)
        for text, value in [
                ("Konvertierte Kopie zusätzlich (Original bleibt)", "add"),
                ("Durch konvertierte Spur ersetzen", "replace"),
                ("Keine Konvertierung (nur remuxen)", "never")]:
            ttk.Radiobutton(box, text=text, variable=self.stereo_policy,
                            value=value, bootstyle="primary"
                            ).pack(anchor="w", pady=2)
        self.stereo_default = ttk.BooleanVar(value=p.stereo_make_default)
        ttk.Checkbutton(box, text="Neue Spur als Standard-Audiospur",
                        variable=self.stereo_default, bootstyle="primary"
                        ).pack(anchor="w", pady=(8, 2))
        ttk.Label(box, text="Zielformat/Kanäle: im Panel "
                            "„Audio-Konvertierung“ des Hauptfensters —\n"
                            "es erscheint, sobald bei der markierten Datei "
                            "eine Konvertierung ansteht.",
                  foreground=theme.MUTED, justify="left"
                  ).pack(anchor="w", pady=(4, 0))

    def _build_sub_box(self, parent) -> None:
        box = ttk.Labelframe(parent, text=" Untertitel ", padding=10)
        box.grid(row=1, column=1, sticky="nsew", pady=(0, 8))
        p = self._source
        self.sub_policy = ttk.StringVar(value=p.sub_policy)
        for text, value in [("Bevorzugte Sprachen", "preferred"),
                            ("Nur erzwungene (forced)", "forced_only"),
                            ("Alle behalten", "all"),
                            ("Keine", "none")]:
            ttk.Radiobutton(box, text=text, variable=self.sub_policy,
                            value=value, bootstyle="primary"
                            ).pack(anchor="w", pady=2)
        self.keep_forced = ttk.BooleanVar(value=p.keep_forced_subs)
        ttk.Checkbutton(box, text="Erzwungene Untertitel (forced) bevorzugter "
                                  "Sprachen immer behalten",
                        variable=self.keep_forced, bootstyle="primary"
                        ).pack(anchor="w", pady=(8, 2))

    def _build_output_box(self, parent) -> None:
        box = ttk.Labelframe(parent, text=" Ausgabe ", padding=10)
        box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(box, text="Dateinamen-Suffix:").pack(side="left")
        self.suffix_var = ttk.StringVar(value=self._source.output.suffix)
        ttk.Entry(box, textvariable=self.suffix_var, width=16
                  ).pack(side="left", padx=(6, 12))
        ttk.Label(box, text="(z. B. „_remux“ → Film_remux.mkv)",
                  foreground=theme.MUTED).pack(side="left")

    def _build_buttons(self, parent) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        bar.columnconfigure(0, weight=1)

        if self._source.builtin:
            ttk.Label(bar, text="Werksprofil — Änderungen als neues Profil "
                                "speichern", foreground=theme.MUTED
                      ).grid(row=0, column=0, sticky="w")
        else:
            ttk.Button(bar, text="Profil löschen", bootstyle="danger-outline",
                       command=self._delete).grid(row=0, column=0, sticky="w")

        right = ttk.Frame(bar)
        right.grid(row=0, column=1, sticky="e")
        ttk.Button(right, text="Abbrechen", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(right, text="Als neues Profil speichern …",
                   bootstyle="primary-outline",
                   command=self._save_as_new).pack(side="left", padx=(0, 6))
        if not self._source.builtin:
            ttk.Button(right, text="Übernehmen", bootstyle="primary",
                       command=self._apply).pack(side="left")

    # ── Sprachliste ───────────────────────────────────────────────────────

    def _refresh_langs(self) -> None:
        self.lang_list.delete(0, "end")
        for i, code in enumerate(self._langs):
            self.lang_list.insert("end", f" {i + 1}.  {display_name(code)}")

    def _add_lang(self) -> None:
        label = self.lang_cb.get()
        for code in _LANG_CHOICES:
            if display_name(code) == label and code not in self._langs:
                self._langs.append(code)
        self._refresh_langs()

    def _remove_lang(self) -> None:
        sel = self.lang_list.curselection()
        if sel and len(self._langs) > 1:
            del self._langs[sel[0]]
            self._refresh_langs()

    def _move_lang(self, delta: int) -> None:
        sel = self.lang_list.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + delta
        if 0 <= j < len(self._langs):
            self._langs[i], self._langs[j] = self._langs[j], self._langs[i]
            self._refresh_langs()
            self.lang_list.selection_set(j)

    # ── Ergebnis ──────────────────────────────────────────────────────────

    def _collect(self, name: str, builtin: bool = False) -> RuleProfile:
        return replace(
            self._source.copy(),
            name=name,
            lang_priority=list(self._langs),
            audio_policy=self.audio_policy.get(),
            stereo_policy=self.stereo_policy.get(),
            sub_policy=self.sub_policy.get(),
            keep_forced_subs=self.keep_forced.get(),
            drop_commentary=self.drop_comm.get(),
            und_audio="keep" if self.und_keep.get() else "drop",
            stereo_make_default=self.stereo_default.get(),
            output=replace(self._source.output,
                           suffix=self.suffix_var.get().strip() or "_remux"),
            builtin=builtin,
        )

    def _apply(self) -> None:
        self.result = ("apply", self._collect(self._source.name))
        self.destroy()

    def _save_as_new(self) -> None:
        dialog = _NameDialog(self, self._existing)
        self.wait_window(dialog)
        if dialog.name:
            self.result = ("new", self._collect(dialog.name))
            self.destroy()

    def _delete(self) -> None:
        answer = Messagebox.yesno(
            f"Profil „{self._source.name}“ wirklich löschen?",
            "Profil löschen", parent=self)
        if answer in ("Ja", "Yes"):
            self.result = ("delete", self._source)
            self.destroy()


class _NameDialog(ttk.Toplevel):
    def __init__(self, master, existing: set[str]):
        super().__init__(title="Profilname", master=master,
                         resizable=(False, False))
        self.name: str | None = None
        self._existing = existing

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Name des neuen Profils:").pack(anchor="w")
        self.var = ttk.StringVar()
        entry = ttk.Entry(body, textvariable=self.var, width=34)
        entry.pack(pady=8)
        entry.focus_set()
        self.hint = ttk.Label(body, text="", foreground=theme.COLORS["danger"])
        self.hint.pack(anchor="w")
        bar = ttk.Frame(body)
        bar.pack(anchor="e", pady=(8, 0))
        ttk.Button(bar, text="Abbrechen", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Speichern", bootstyle="primary",
                   command=self._ok).pack(side="left")
        entry.bind("<Return>", lambda _e: self._ok())

        self.transient(master)
        self.grab_set()
        theme.apply_dark_titlebar(self)
        self.place_window_center()

    def _ok(self) -> None:
        name = self.var.get().strip()
        if not name:
            self.hint.configure(text="Bitte einen Namen eingeben.")
            return
        if name in self._existing:
            self.hint.configure(text="Diesen Namen gibt es schon.")
            return
        self.name = name
        self.destroy()
