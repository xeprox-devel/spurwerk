"""Tool-Manager + Erststart-Onboarding.

Der Erststart ohne Tools ist keine Fehlermeldung, sondern ein geführter
Weg: ein Klick lädt MKVToolNix + FFmpeg (mit SHA-256-Prüfung) in tools/,
alternativ wählt man vorhandene EXEs von Hand. Reiner Remux funktioniert
schon mit MKVToolNix allein — FFmpeg wird nur für Stereo gebraucht.
"""

from __future__ import annotations

import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.widgets import Floodgauge

import config as appconfig
from core import downloader
from core import tools as toolchain

from . import theme

_TOOL_TITLES = {
    "mkvtoolnix": ("MKVToolNix", "Analyse & verlustfreies Muxen — Pflicht"),
    "ffmpeg": ("FFmpeg", "Audio-Konvertierung & DV-Analyse (ffprobe)"),
    "dovi_tool": ("dovi_tool",
                  "Dolby-Vision-Remux (DV entfernen/8.1) — optional"),
    "mp4box": ("MP4Box (GPAC)",
               "DV 8.1 → MP4 — manuell installieren (gpac.io), Pfad wählen"),
}
_TOOL_EXES = {"mkvtoolnix": "mkvmerge", "ffmpeg": "ffmpeg",
              "dovi_tool": "dovi_tool", "mp4box": "mp4box"}


class ToolManagerDialog(ttk.Toplevel):
    """Pro Tool: Status, Version, Pfad, Download. Läuft über eine eigene
    Queue + after-Polling (Tk bleibt single-threaded sauber)."""

    def __init__(self, master, cfg: appconfig.AppConfig,
                 tool_status: dict[str, toolchain.ToolStatus],
                 on_changed):
        super().__init__(title="Werkzeuge", master=master,
                         resizable=(False, False))
        self.cfg = cfg
        self.on_changed = on_changed
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self._running = False

        self._dot_ok = theme.make_status_dot(self, theme.COLORS["success"])
        self._dot_bad = theme.make_status_dot(self, theme.COLORS["danger"])

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        self.rows: dict[str, dict] = {}
        for i, kind in enumerate(("mkvtoolnix", "ffmpeg", "dovi_tool",
                                  "mp4box")):
            self._build_row(body, i, kind)
        self._refresh_status(tool_status)

        self.gauge = Floodgauge(body, mask="{}%", bootstyle="primary",
                                value=0, font=("Segoe UI", 9))
        self.step_label = ttk.Label(body, foreground=theme.MUTED)

        bar = ttk.Frame(body)
        bar.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        bar.columnconfigure(0, weight=1)
        self.dl_all_btn = ttk.Button(
            bar, text="⬇  Fehlende Tools herunterladen", bootstyle="primary",
            command=lambda: self._download(only_missing=True))
        self.dl_all_btn.grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Download-Seiten im Browser",
                   bootstyle="secondary-link",
                   command=self._open_pages).grid(row=0, column=1, padx=6)
        ttk.Button(bar, text="Schließen", bootstyle="secondary-outline",
                   command=self._close).grid(row=0, column=2)

        note = ("Freie GPL-Software: MKVToolNix (mkvtoolnix.download) und "
                "FFmpeg (gyan.dev / BtbN).\nDownloads werden per SHA-256 "
                "geprüft und nach tools/ entpackt.")
        ttk.Label(body, text=note, foreground=theme.MUTED,
                  justify="left").grid(row=10, column=0, sticky="w",
                                       pady=(10, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.transient(master)
        self.grab_set()
        theme.apply_dark_titlebar(self)
        self.place_window_center()
        self.after(100, self._poll)

    def _build_row(self, parent, index: int, kind: str) -> None:
        title, hint = _TOOL_TITLES[kind]
        frame = ttk.Labelframe(parent, text=f" {title} ", padding=10)
        frame.grid(row=index, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        status = ttk.Label(frame, text="…", image=self._dot_bad,
                           compound="left")
        status.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text=hint, foreground=theme.MUTED
                  ).grid(row=1, column=0, columnspan=2, sticky="w",
                         pady=(0, 6))

        path_var = ttk.StringVar()
        entry = ttk.Entry(frame, textvariable=path_var)
        entry.grid(row=2, column=0, columnspan=2, sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=2, padx=(6, 0))
        ttk.Button(buttons, text="…", width=3, bootstyle="secondary-outline",
                   command=lambda k=kind: self._browse(k)).pack(side="left")
        if kind in downloader.DOWNLOADERS:
            ttk.Button(buttons, text="⬇", width=3,
                       bootstyle="primary-outline",
                       command=lambda k=kind: self._download(only=k)
                       ).pack(side="left", padx=(4, 0))

        self.rows[kind] = {"status": status, "path": path_var}

    # ── Statusanzeige ─────────────────────────────────────────────────────

    def _refresh_status(self, status: dict[str, toolchain.ToolStatus]) -> None:
        self._status = status
        for kind, row in self.rows.items():
            info = status.get(_TOOL_EXES[kind])
            # Der FFmpeg-Download liefert ffmpeg.exe UND ffprobe.exe (für die
            # DV-Analyse). Fehlt ffprobe, gilt die Zeile als unvollständig —
            # sonst bliebe die DV-Funktion ohne sichtbaren Grund gesperrt.
            ffprobe_missing = (kind == "ffmpeg"
                               and not (status.get("ffprobe")
                                        and status["ffprobe"].ok))
            if info and info.ok and not ffprobe_missing:
                row["status"].configure(
                    image=self._dot_ok,
                    text=f"  gefunden — Version {info.version}")
                row["path"].set(info.path)
            elif info and info.ok and ffprobe_missing:
                row["status"].configure(
                    image=self._dot_bad,
                    text="  unvollständig — ffprobe fehlt (für DV-Analyse) "
                         "→ neu herunterladen")
                row["path"].set(info.path)
            else:
                row["status"].configure(image=self._dot_bad,
                                        text="  nicht gefunden")

    def _missing(self) -> list[str]:
        def incomplete(kind: str) -> bool:
            info = self._status.get(_TOOL_EXES[kind])
            if not (info and info.ok):
                return True
            # ffprobe hängt am FFmpeg-Download
            if kind == "ffmpeg":
                pr = self._status.get("ffprobe")
                return not (pr and pr.ok)
            return False

        return [k for k in self.rows
                if k in downloader.DOWNLOADERS   # mp4box: nur manueller Pfad
                and incomplete(k)]

    # ── Aktionen ──────────────────────────────────────────────────────────

    def _browse(self, kind: str) -> None:
        exe = _TOOL_EXES[kind]
        path = filedialog.askopenfilename(
            parent=self, title=f"{exe}.exe wählen",
            filetypes=[(f"{exe}.exe", f"{exe}.exe"), ("EXE", "*.exe")])
        if not path:
            return
        if Path(path).name.lower() != f"{exe}.exe":
            self.step_label.configure(
                text=f"Erwartet wurde {exe}.exe.", foreground=theme.COLORS["danger"])
            self._show_progress()
            return
        self.cfg.tools[exe] = path
        appconfig.save(self.cfg)
        self._reprobe()

    def _download(self, only: str | None = None,
                  only_missing: bool = False) -> None:
        if self._running:
            return
        kinds = [only] if only else (self._missing() if only_missing
                                     else list(self.rows))
        if not kinds:
            self.step_label.configure(text="Alles vorhanden — nichts zu tun.",
                                      foreground=theme.MUTED)
            self._show_progress()
            return
        self._running = True
        self.cancel.clear()
        self.dl_all_btn.configure(state="disabled")
        self._show_progress()
        threading.Thread(target=self._download_worker, args=(kinds,),
                         daemon=True).start()

    def _download_worker(self, kinds: list[str]) -> None:
        tools_dir = appconfig.base_path() / "tools"
        errors: list[str] = []
        try:
            for kind in kinds:
                title = _TOOL_TITLES[kind][0]
                try:
                    self.q.put(("STEP", f"{title}: starte Download …", None))
                    downloader.DOWNLOADERS[kind](
                        tools_dir,
                        lambda msg, pct: self.q.put(("STEP", msg, pct)),
                        self.cancel)
                    # veralteten manuellen Pfad nicht weiter bevorzugen —
                    # sonst überschattet er die frisch geladene EXE
                    exe = _TOOL_EXES[kind]
                    if self.cfg.tools.get(exe):
                        self.cfg.tools.pop(exe, None)
                        try:
                            appconfig.save(self.cfg)
                        except OSError:
                            pass
                except downloader.DownloadError as exc:
                    errors.append(f"{title}: {exc}")
                except Exception as exc:  # Dialog darf nie hängen bleiben
                    errors.append(f"{title}: {exc}")
        finally:
            self.q.put(("DONE", errors))

    def _show_progress(self) -> None:
        self.gauge.grid(row=7, column=0, sticky="ew", pady=(4, 2))
        self.step_label.grid(row=8, column=0, sticky="w")

    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "STEP":
                    _, text, pct = msg
                    self.step_label.configure(text=text,
                                              foreground=theme.MUTED)
                    self.gauge.configure(value=pct or 0)
                elif msg[0] == "DONE":
                    errors = msg[1]
                    self._running = False
                    self.dl_all_btn.configure(state="normal")
                    self.gauge.configure(value=100 if not errors else 0)
                    if errors:
                        self.step_label.configure(
                            text="  |  ".join(errors),
                            foreground=theme.COLORS["danger"])
                    else:
                        self.step_label.configure(
                            text="Fertig — Tools sind einsatzbereit.",
                            foreground=theme.COLORS["success"])
                    self._reprobe()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)

    def _reprobe(self) -> None:
        def worker() -> None:
            paths = toolchain.detect_tools(appconfig.base_path(),
                                           self.cfg.tools)
            status = toolchain.probe_all(paths)
            self.q.put(("STEP", "", None))
            self.after(0, lambda: self._refresh_status(status))
            self.on_changed()
        threading.Thread(target=worker, daemon=True).start()

    def _open_pages(self) -> None:
        for url in downloader.DOWNLOAD_PAGES.values():
            webbrowser.open(url)

    def _close(self) -> None:
        self.cancel.set()
        self.destroy()


class OnboardingCard(ttk.Frame):
    """Erststart-Karte im Leerzustand, wenn Tools fehlen."""

    def __init__(self, master, on_download, on_manual):
        super().__init__(master, padding=24, bootstyle="dark")
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Willkommen bei Spurwerk!",
                  font=("Segoe UI", 14, "bold"), bootstyle="inverse-dark",
                  anchor="center").grid(row=0, column=0, pady=(4, 6))
        ttk.Label(
            self, bootstyle="inverse-dark", foreground=theme.MUTED,
            anchor="center", justify="center",
            text=("Zum Arbeiten braucht die App zwei freie Open-Source-"
                  "Werkzeuge (GPL),\ndie nicht mitgeliefert werden: "
                  "MKVToolNix und FFmpeg."),
        ).grid(row=1, column=0, pady=(0, 14))
        ttk.Button(self, text="⬇  Tools jetzt herunterladen  (~195 MB, einmalig)",
                   bootstyle="primary", command=on_download
                   ).grid(row=2, column=0, ipady=4, ipadx=10)
        ttk.Button(self, text="Ich habe die Tools schon — Pfade selbst wählen …",
                   bootstyle="secondary-link", command=on_manual
                   ).grid(row=3, column=0, pady=(8, 4))
