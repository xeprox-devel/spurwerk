"""Tool-Manager + Erststart-Onboarding.

Der Erststart ohne Tools ist keine Fehlermeldung, sondern ein geführter
Weg: ein Klick lädt alle fehlenden Werkzeuge (MKVToolNix + FFmpeg, dazu
das optionale dovi_tool) mit SHA-256-Prüfung in tools/, alternativ wählt
man vorhandene EXEs von Hand. Reiner Remux funktioniert schon mit
MKVToolNix allein — FFmpeg wird nur für Audio-Konvertierung gebraucht,
dovi_tool nur für „DV/HDR → HDR10“.

Danach hält derselbe Dialog die Werkzeuge aktuell: Er vergleicht die
installierten Versionen mit den offiziellen Quellen und aktualisiert auf
Klick — einzeln oder alle auf einmal. Während einer laufenden Verarbeitung
bleibt das gesperrt (Windows kann eine laufende EXE nicht ersetzen).
"""

from __future__ import annotations

import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.widgets import Floodgauge

try:
    from ttkbootstrap.widgets import ToolTip
except ImportError:  # ältere 1.x
    from ttkbootstrap.tooltip import ToolTip

import config as appconfig
from core import downloader
from core import tools as toolchain

from . import theme

_TOOL_TITLES = {
    "mkvtoolnix": ("MKVToolNix", "Analyse & verlustfreies Muxen — Pflicht"),
    "ffmpeg": ("FFmpeg", "Audio-Konvertierung & DV-Analyse (ffprobe)"),
    "dovi_tool": ("dovi_tool",
                  "„DV/HDR → HDR10“ (Dolby-Vision-Daten entfernen) — optional"),
}
_TOOL_EXES = toolchain.KIND_EXE

# Beschriftung des Zeilen-Knopfs — eine Breite für alle, damit nichts springt
_ACTION_WIDTH = 15


def _tip(widget, text: str) -> None:
    ToolTip(widget, text=text, bootstyle="inverse-dark", delay=450,
            wraplength=340)


class ToolManagerDialog(ttk.Toplevel):
    """Pro Tool: Status, Version, Update-Stand, Pfad, Download. Läuft über
    eine eigene Queue + after-Polling (Tk bleibt single-threaded sauber).

    latest:    bereits bekannte neueste Versionen (Startprüfung) oder None
    on_latest: meldet ein frisches Prüfergebnis ans Hauptfenster zurück
    is_busy:   True, solange eine Verarbeitung läuft → Downloads gesperrt
    """

    def __init__(self, master, cfg: appconfig.AppConfig,
                 tool_status: dict[str, toolchain.ToolStatus],
                 on_changed, latest: dict[str, str | None] | None = None,
                 on_latest=None, is_busy=None):
        super().__init__(title="Werkzeuge", master=master,
                         resizable=(False, False))
        self.cfg = cfg
        self.on_changed = on_changed
        self.on_latest = on_latest
        self.is_busy = is_busy or (lambda: False)
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self._running = False
        self._checking = False
        # Ein Totalausfall (offline) gilt als „noch nicht geprüft“
        self._latest = latest if latest and any(latest.values()) else None

        self._dot_ok = theme.make_status_dot(self, theme.COLORS["success"])
        self._dot_bad = theme.make_status_dot(self, theme.COLORS["danger"])
        # neutraler Punkt für „noch ungeprüft“ — Rot erst bei echtem Befund
        self._dot_wait = theme.make_status_dot(self, theme.MUTED)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        self.rows: dict[str, dict] = {}
        for i, kind in enumerate(("mkvtoolnix", "ffmpeg", "dovi_tool")):
            self._build_row(body, i, kind)

        self.gauge = Floodgauge(body, mask="{}%", bootstyle="primary",
                                value=0, font=("Segoe UI", 9))
        self.step_label = ttk.Label(body, foreground=theme.MUTED)

        bar = ttk.Frame(body)
        bar.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        bar.columnconfigure(0, weight=1)
        # Hauptknopf passt sich an: Fehlendes laden, sonst aktualisieren
        self.main_btn = ttk.Button(bar, text="", bootstyle="primary",
                                   command=self._download)
        self.main_btn.grid(row=0, column=0, sticky="w")
        self.check_btn = ttk.Button(bar, text="⟳ Nach Updates suchen",
                                    bootstyle="secondary-link",
                                    command=self._check_updates)
        self.check_btn.grid(row=0, column=1, padx=(6, 0))
        _tip(self.check_btn, "Fragt die offiziellen Quellen nach der "
                             "neuesten Version — lädt noch nichts herunter.")
        ttk.Button(bar, text="Download-Seiten im Browser "
                             f"({len(downloader.DOWNLOAD_PAGES)} Tabs)",
                   bootstyle="secondary-link",
                   command=self._open_pages).grid(row=0, column=2, padx=6)
        ttk.Button(bar, text="Schließen", bootstyle="secondary-outline",
                   command=self._close).grid(row=0, column=3)

        note = ("Freie Software: MKVToolNix + FFmpeg (GPL), dovi_tool (MIT).\n"
                "Downloads werden per SHA-256 geprüft und nach tools/ "
                "entpackt; „Aktualisieren“ ersetzt\ndie vorhandene Version "
                "(auch einen selbst gewählten Pfad) durch die neue in tools/.")
        ttk.Label(body, text=note, foreground=theme.MUTED,
                  justify="left").grid(row=10, column=0, sticky="w",
                                       pady=(10, 0))

        self._refresh_status(tool_status)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.transient(master)
        self.grab_set()
        theme.apply_dark_titlebar(self)
        self.place_window_center()
        self.after(100, self._poll)
        # Der übergebene Stand kann leer (Startprüfung läuft noch) oder
        # veraltet sein — der Dialog prüft selbst nach
        self._reprobe(notify_main=False)
        if self.is_busy():
            self._message("Verarbeitung läuft — Laden und Aktualisieren "
                          "geht erst nach dem Lauf.", theme.COLORS["warning"])
        # Die Update-Prüfung folgt derselben Einstellung wie die der App
        # (Über-Dialog); abgeschaltet bleibt es beim Knopf „Nach Updates suchen“
        if self._latest is None and cfg.check_updates:
            self.after(150, self._check_updates)

    def _build_row(self, parent, index: int, kind: str) -> None:
        title, hint = _TOOL_TITLES[kind]
        exe = _TOOL_EXES[kind]
        frame = ttk.Labelframe(parent, text=f" {title} ", padding=10)
        frame.grid(row=index, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        status = ttk.Label(frame, text="…", image=self._dot_wait,
                           compound="left")
        status.grid(row=0, column=0, columnspan=2, sticky="w")
        update = ttk.Label(frame, text="", foreground=theme.MUTED)
        update.grid(row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Label(frame, text=hint, foreground=theme.MUTED
                  ).grid(row=1, column=0, columnspan=3, sticky="w",
                         pady=(0, 6))

        path_var = ttk.StringVar()
        entry = ttk.Entry(frame, textvariable=path_var)
        entry.grid(row=2, column=0, columnspan=2, sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=2, padx=(6, 0), sticky="e")
        browse = ttk.Button(buttons, text="…", width=3,
                            bootstyle="secondary-outline",
                            command=lambda k=kind: self._browse(k))
        browse.pack(side="left")
        _tip(browse, f"Vorhandene {exe}.exe selbst auswählen")
        action = None
        if not downloader.can_download(kind):
            ttk.Label(buttons, text="nur für 64-bit-Windows",
                      foreground=theme.MUTED).pack(side="left", padx=(8, 0))
        else:
            action = ttk.Button(buttons, text="⬇  Laden", width=_ACTION_WIDTH,
                                bootstyle="primary-outline",
                                command=lambda k=kind: self._download(only=k))
            action.pack(side="left", padx=(4, 0))
            _tip(action, "Neueste Version von der offiziellen Quelle laden "
                         "— ersetzt eine vorhandene.")

        self.rows[kind] = {"status": status, "update": update,
                           "path": path_var, "action": action}

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
        self._refresh_updates()

    def _refresh_updates(self) -> None:
        """Update-Spalte, Zeilen-Knöpfe und Hauptknopf aus Status + neuester
        Version ableiten — eine Stelle, damit alles zusammenpasst."""
        outdated = self._outdated()
        latest = self._latest or {}
        for kind, row in self.rows.items():
            info = self._status.get(_TOOL_EXES[kind])
            present = bool(info and info.ok)
            newest = latest.get(kind)
            if not present:
                text, color = "", theme.MUTED
            elif self._checking:
                text, color = "sucht Updates …", theme.MUTED
            elif self._latest is None:
                text, color = "", theme.MUTED
            elif kind in outdated:
                text = f"⬆ Version {newest} verfügbar"
                color = theme.COLORS["info"]
            elif toolchain.update_state(info.version,
                                        newest) == toolchain.CURRENT:
                text, color = "✓ aktuell", theme.COLORS["success"]
            elif newest:
                # Entwicklungs-Build (Datum/Git) — ehrlich: nicht vergleichbar
                text, color = f"Release {newest} verfügbar", theme.MUTED
            else:
                text, color = "Stand nicht prüfbar", theme.MUTED
            row["update"].configure(text=text, foreground=color)

            action = row["action"]
            if action is None:
                continue
            if not present:
                action.configure(text="⬇  Laden", bootstyle="primary-outline")
            elif kind in outdated:
                action.configure(text="⬆  Aktualisieren", bootstyle="primary")
            else:
                action.configure(text="⬇  Neu laden",
                                 bootstyle="secondary-outline")
        self._refresh_main_button()

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

        # was dieses System gar nicht laden kann (dovi_tool auf 32 bit),
        # zählt nicht als fehlend — sonst endete jeder Lauf mit einem Fehler
        return [k for k in self.rows
                if downloader.can_download(k) and incomplete(k)]

    def _outdated(self) -> list[str]:
        if not self._latest:
            return []
        return [u.kind for u in toolchain.pending_updates(self._status,
                                                          self._latest)
                if downloader.can_download(u.kind)]

    def _main_action(self) -> tuple[str, list[str]]:
        """(Beschriftung, Pakete) des Hauptknopfs."""
        missing = self._missing()
        outdated = [k for k in self._outdated() if k not in missing]
        kinds = missing + outdated
        if missing and outdated:
            return f"⬇  Fehlende laden + aktualisieren ({len(kinds)})", kinds
        if missing:
            return "⬇  Fehlende Werkzeuge herunterladen", kinds
        if outdated:
            return f"⬆  Alle aktualisieren ({len(outdated)})", kinds
        all_current = self._latest is not None and all(
            toolchain.update_state(
                self._status[_TOOL_EXES[k]].version,
                self._latest.get(k)) == toolchain.CURRENT
            for k in self.rows)
        return ("✓  Alles aktuell" if all_current
                else "✓  Alles vorhanden"), []

    def _refresh_main_button(self) -> None:
        text, kinds = self._main_action()
        self.main_btn.configure(
            text=text,
            state="normal" if kinds and not self._running else "disabled")

    def _message(self, text: str, color: str = theme.MUTED) -> None:
        """Reiner Hinweis ohne Fortschrittsbalken (der gehört zum Download)."""
        self.step_label.configure(text=text, foreground=color)
        self.step_label.grid(row=8, column=0, sticky="w")

    # ── Aktionen ──────────────────────────────────────────────────────────

    def _browse(self, kind: str) -> None:
        exe = _TOOL_EXES[kind]
        path = filedialog.askopenfilename(
            parent=self, title=f"{exe}.exe wählen",
            filetypes=[(f"{exe}.exe", f"{exe}.exe"), ("EXE", "*.exe")])
        if not path:
            return
        if Path(path).name.lower() != f"{exe}.exe":
            self._message(f"Erwartet wurde {exe}.exe.",
                          theme.COLORS["danger"])
            return
        self.cfg.tools[exe] = path
        try:
            appconfig.save(self.cfg)
        except OSError as exc:
            # schreibgeschützter Ordner: für diese Sitzung trotzdem nutzen
            self._message(f"Pfad gilt nur bis zum Beenden — Einstellungen "
                          f"nicht speicherbar ({exc}).",
                          theme.COLORS["warning"])
        self._reprobe()

    def _download(self, only: str | None = None,
                  only_missing: bool = False) -> None:
        """only: genau ein Paket · only_missing: nur Fehlendes (Onboarding)
        · sonst: was der Hauptknopf anbietet (Fehlendes + Veraltetes)."""
        if self._running:
            return
        if self.is_busy():
            self._message("Verarbeitung läuft — Laden und Aktualisieren "
                          "geht erst nach dem Lauf.", theme.COLORS["warning"])
            return
        if only:
            kinds = [only]
        elif only_missing:
            kinds = self._missing()
        else:
            kinds = self._main_action()[1]
        if not kinds:
            self._message("Alles vorhanden — nichts zu tun.")
            return
        self._running = True
        self.cancel.clear()
        self._refresh_main_button()
        self.gauge.configure(value=0)
        self._show_progress()
        threading.Thread(target=self._download_worker, args=(kinds,),
                         daemon=True).start()

    def _download_worker(self, kinds: list[str]) -> None:
        tools_dir = appconfig.base_path() / "tools"
        errors: list[str] = []
        unverified: list[str] = []
        changed = False
        try:
            for kind in kinds:
                title = _TOOL_TITLES[kind][0]
                try:
                    self.q.put(("STEP", f"{title}: starte Download …", None))
                    result = downloader.DOWNLOADERS[kind](
                        tools_dir,
                        lambda msg, pct: self.q.put(("STEP", msg, pct)),
                        self.cancel)
                    changed = True
                    if not result.verified:
                        unverified.append(title)
                    # veraltete manuelle Pfade nicht weiter bevorzugen —
                    # sonst überschatten sie die frisch geladenen EXEs
                    # (bei FFmpeg ffmpeg UND ffprobe, sonst Versionsmix)
                    stale = [exe for exe in toolchain.KIND_EXES[kind]
                             if self.cfg.tools.get(exe)]
                    if stale:
                        for exe in stale:
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
            if changed:
                # Hauptfenster neu prüfen lassen — auch wenn der Dialog
                # inzwischen geschlossen wurde (on_changed ist thread-sicher)
                self.on_changed()
            self.q.put(("DONE", errors, unverified))

    def _check_updates(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.check_btn.configure(state="disabled")
        self._refresh_updates()

        def worker() -> None:
            self.q.put(("LATEST", downloader.latest_versions()))
        threading.Thread(target=worker, daemon=True).start()

    def _show_progress(self) -> None:
        self.gauge.grid(row=7, column=0, sticky="ew", pady=(4, 2))
        self.step_label.grid(row=8, column=0, sticky="w")

    def _poll(self) -> None:
        if not self.winfo_exists():
            return   # Dialog geschlossen — ausstehende Meldungen verfallen
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "STEP":
                    _, text, pct = msg
                    self.step_label.configure(text=text,
                                              foreground=theme.MUTED)
                    self.gauge.configure(value=pct or 0)
                elif msg[0] == "STATUS":
                    self._refresh_status(msg[1])
                elif msg[0] == "LATEST":
                    self._on_latest(msg[1])
                elif msg[0] == "DONE":
                    _, errors, unverified = msg
                    self._running = False
                    self.gauge.configure(value=100 if not errors else 0)
                    if errors:
                        self.step_label.configure(
                            text="  |  ".join(errors),
                            foreground=theme.COLORS["danger"])
                    elif unverified:
                        # ehrlich statt „SHA-256-geprüft“ für alles
                        self.step_label.configure(
                            text="Fertig — ohne SHA-256-Prüfung geladen "
                                 "(keine Prüfsumme erhältlich): "
                                 f"{', '.join(unverified)}",
                            foreground=theme.COLORS["warning"])
                    else:
                        self.step_label.configure(
                            text="Fertig — Werkzeuge sind einsatzbereit.",
                            foreground=theme.COLORS["success"])
                    self._refresh_main_button()
                    # Hauptfenster wurde schon vom Worker benachrichtigt
                    self._reprobe(notify_main=False)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)

    def _on_latest(self, latest: dict[str, str | None]) -> None:
        self._checking = False
        self.check_btn.configure(state="normal")
        if any(latest.values()):
            self._latest = latest
            if self.on_latest is not None:
                self.on_latest(latest)
        elif self._latest is None:
            self._message("Update-Prüfung nicht möglich — keine Verbindung "
                          "zu den Quellen?")
        self._refresh_updates()

    def _reprobe(self, notify_main: bool = True) -> None:
        def worker() -> None:
            paths = toolchain.detect_tools(appconfig.base_path(),
                                           self.cfg.tools)
            # Ergebnis über die Queue — Tk nie aus dem Worker anfassen
            self.q.put(("STATUS", toolchain.probe_all(paths)))
        threading.Thread(target=worker, daemon=True).start()
        if notify_main:
            self.on_changed()

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
        # Bewusste Vereinfachung: FFmpeg wird hier als Pflicht kommuniziert,
        # weil tools.REQUIRED und die Header-Chips es so führen — technisch
        # erzwingt der Start es nur bei anstehender Audio-Konvertierung
        # (siehe Modul-Docstring).
        ttk.Label(
            self, bootstyle="inverse-dark", foreground=theme.MUTED,
            anchor="center", justify="center",
            text=("Zum Arbeiten braucht die App freie Open-Source-Werkzeuge, "
                  "die nicht mitgeliefert werden:\nMKVToolNix und FFmpeg "
                  "(Pflicht) sowie dovi_tool (optional, für "
                  "„DV/HDR → HDR10“).\nDer Download holt alles Fehlende "
                  "auf einmal — SHA-256-geprüft, nach tools/."),
        ).grid(row=1, column=0, pady=(0, 14))
        ttk.Button(self, text="⬇  Werkzeuge jetzt herunterladen  (einmalig)",
                   bootstyle="primary", command=on_download
                   ).grid(row=2, column=0, ipady=4, ipadx=10)
        ttk.Button(self,
                   text="Ich habe die Werkzeuge schon — Pfade selbst wählen …",
                   bootstyle="secondary-link", command=on_manual
                   ).grid(row=3, column=0, pady=(8, 4))
