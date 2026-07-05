"""„Über Spurwerk" — Identität, Entwickler-Zuordnung und die Attributionen
(GPL-Werkzeuge + TMDb), die die Hauptoberfläche sauber halten."""

from __future__ import annotations

import ttkbootstrap as ttk

from version import APP_NAME, __version__

from . import theme


class AboutDialog(ttk.Toplevel):
    def __init__(self, master, updates_enabled: bool = True,
                 on_toggle_updates=None):
        super().__init__(title=f"Über {APP_NAME}", master=master,
                         resizable=(False, False))
        self._on_toggle_updates = on_toggle_updates
        body = ttk.Frame(self, padding=(28, 22))
        body.pack(fill="both", expand=True)

        # ── Kopf: Wortmarke + Version ─────────────────────────────────────
        head = ttk.Frame(body)
        head.pack(anchor="center")
        ttk.Label(head, text="SPUR", font=("Segoe UI", 20, "bold")
                  ).pack(side="left")
        ttk.Label(head, text="WERK", font=("Segoe UI", 20, "bold"),
                  foreground=theme.COLORS["primary"]).pack(side="left")

        ttk.Label(body, text=f"Version {__version__}",
                  foreground=theme.MUTED).pack(anchor="center", pady=(2, 0))
        ttk.Label(body, text="MKV Remuxer & Audio-Studio",
                  font=("Segoe UI", 10)).pack(anchor="center", pady=(6, 0))
        ttk.Label(body, text="von xeproX-deveL", font=("Segoe UI", 10, "bold"),
                  foreground=theme.COLORS["primary"]).pack(anchor="center",
                                                           pady=(10, 0))
        ttk.Label(body, text="© 2026 xeproX-deveL · GNU GPL-3.0",
                  foreground=theme.MUTED).pack(anchor="center", pady=(2, 0))

        ttk.Separator(body, bootstyle="secondary").pack(fill="x", pady=16)

        # ── Credits (Pflicht-Attributionen) ───────────────────────────────
        credits = ttk.Frame(body)
        credits.pack(fill="x")
        ttk.Label(credits, text="Nutzt bewährte freie Software:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        for tool, src in (("MKVToolNix", "mkvtoolnix.download"),
                          ("FFmpeg", "gyan.dev / BtbN"),
                          ("dovi_tool", "quietvoid")):
            ttk.Label(credits, text=f"   •  {tool}  ·  {src}",
                      foreground=theme.MUTED).pack(anchor="w")
        ttk.Label(credits,
                  text="Alle unter eigenen Open-Source-Lizenzen; Spurwerk lädt "
                       "sie\nauf Wunsch von den offiziellen Quellen.",
                  foreground=theme.MUTED, justify="left").pack(anchor="w",
                                                              pady=(4, 0))

        ttk.Label(body,
                  text="Titelabgleich über die TMDb-API — dieses Produkt ist\n"
                       "nicht von TMDb unterstützt oder zertifiziert.",
                  foreground=theme.MUTED, justify="left").pack(anchor="w",
                                                              pady=(12, 0))

        # ── Einstellung: Update-Prüfung ───────────────────────────────────
        if on_toggle_updates is not None:
            ttk.Separator(body, bootstyle="secondary").pack(fill="x", pady=16)
            self._updates_var = ttk.BooleanVar(value=bool(updates_enabled))
            ttk.Checkbutton(
                body, text="Beim Start nach Updates suchen",
                variable=self._updates_var, bootstyle="round-toggle",
                command=lambda: on_toggle_updates(self._updates_var.get())
            ).pack(anchor="w")
            ttk.Label(body,
                      text="Eine einzige Anfrage an GitHub, ohne Tracking.",
                      foreground=theme.MUTED).pack(anchor="w", pady=(2, 0))

        ttk.Button(body, text="Schließen", bootstyle="primary",
                   command=self.destroy).pack(anchor="e", pady=(18, 0))

        self.transient(master)
        self.grab_set()
        theme.apply_dark_titlebar(self)
        self.place_window_center()
        self.bind("<Escape>", lambda _e: self.destroy())
