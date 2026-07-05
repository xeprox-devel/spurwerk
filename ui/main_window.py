"""Hauptfenster: Dateiliste → Regeln → Spurtabelle → Start.

Ein mentales Modell, kein Moduswechsel: Die Dateiliste ist immer ein Batch
(notfalls mit einem Eintrag), die Ausgabe wird pro Spur definiert, und der
Start-Button sagt vorher exakt, was passieren wird.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.widgets import Floodgauge

try:
    from ttkbootstrap.widgets import ToastNotification
except ImportError:  # ältere 1.x
    from ttkbootstrap.toast import ToastNotification

import config as appconfig
from core import dv as dv_analysis
from core import tools as toolchain
from core.langs import display_name
from core.model import FilePlan, FileStatus, RuleProfile
from core.planner import build_plan, reapply_rules, reset_manual
from core.presets import DOWNMIX_PRESETS, OUTPUT_CODECS
from core.profiles import describe
from core.runner import JobRunner
from core.scanner import ScanError, scan_file

from . import theme
from .file_list import FileList
from .logpanel import LogPanel
from .track_table import TrackTable

_STATUS_TAGS = {
    FileStatus.DONE: "done", FileStatus.ERROR: "error",
    FileStatus.RUNNING: "running", FileStatus.SKIPPED: "dim",
    FileStatus.SCANNING: "dim", FileStatus.SCAN_ERROR: "error",
}


class MainWindow(ttk.Frame):
    def __init__(self, master, cfg: appconfig.AppConfig):
        super().__init__(master, padding=(12, 8))
        self.cfg = cfg
        self.profile: RuleProfile = cfg.profile(cfg.active_profile)
        self.stereo = replace(self.profile.stereo)

        self.plans: dict[str, FilePlan] = {}
        self.selected: str | None = None

        self.ui_q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.runner: JobRunner | None = None
        self._worker: threading.Thread | None = None
        self._scan_sem = threading.Semaphore(3)
        self.tools: dict[str, str] = {}
        self.tool_status: dict[str, toolchain.ToolStatus] = {}
        self.output_dir = ""          # App-Zustand, überlebt Profilwechsel
        self._running = False
        self._lock_buttons: list = []   # während des Laufs gesperrt
        self._lock_combos: list = []

        self.columnconfigure(0, weight=1)
        self._build_header()
        self._build_empty_state()
        self._build_workspace()
        self._sync_state()

        self.after(80, self._poll_queue)
        threading.Thread(target=self._probe_tools, daemon=True).start()

    # ══ Aufbau ═══════════════════════════════════════════════════════════

    def _build_header(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.columnconfigure(1, weight=1)

        from version import __version__
        brand = ttk.Frame(bar)
        brand.grid(row=0, column=0, sticky="w")
        ttk.Label(brand, text="SPUR", font=("Segoe UI", 13, "bold")
                  ).pack(side="left")
        ttk.Label(brand, text="WERK", font=("Segoe UI", 13, "bold"),
                  foreground=theme.COLORS["primary"]).pack(side="left")
        ttk.Label(brand, text=f"  v{__version__}", font=("Segoe UI", 9),
                  foreground=theme.MUTED).pack(side="left", anchor="s",
                                               pady=(0, 2))

        chips = ttk.Frame(bar)
        chips.grid(row=0, column=2, sticky="e")
        self._dot_ok = theme.make_status_dot(self, theme.COLORS["success"])
        self._dot_bad = theme.make_status_dot(self, theme.COLORS["danger"])
        self.tool_chips: dict[str, ttk.Label] = {}
        for name in toolchain.REQUIRED:
            chip = ttk.Label(chips, text=f" {name}: prüfe …",
                             image=self._dot_bad, compound="left",
                             cursor="hand2")
            chip.pack(side="left", padx=(0, 12))
            chip.bind("<Button-1>", lambda _e: self._open_tool_manager())
            self.tool_chips[name] = chip

        ttk.Button(chips, text="⚙", width=3, bootstyle="secondary-outline",
                   command=self._open_tool_manager).pack(side="left")

    def _build_empty_state(self) -> None:
        from .tool_setup import OnboardingCard
        self.empty = ttk.Frame(self)
        self.empty.columnconfigure(0, weight=1)

        self.onboarding = OnboardingCard(
            self.empty,
            on_download=lambda: self._open_tool_manager(auto_download=True),
            on_manual=self._open_tool_manager)
        # wird erst gegridet, wenn Tools fehlen (_update_onboarding)

        zone = ttk.Frame(self.empty, padding=40, bootstyle="dark")
        zone.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        zone.columnconfigure(0, weight=1)
        ttk.Label(zone, text="MKV-Dateien hierher ziehen",
                  font=("Segoe UI", 14, "bold"), bootstyle="inverse-dark",
                  anchor="center").grid(row=0, column=0, pady=(8, 2))
        ttk.Label(zone, text="oder über die Buttons öffnen",
                  bootstyle="inverse-dark", foreground=theme.MUTED,
                  anchor="center").grid(row=1, column=0, pady=(0, 14))
        buttons = ttk.Frame(zone, bootstyle="dark")
        buttons.grid(row=2, column=0, pady=(0, 8))
        ttk.Button(buttons, text="Dateien öffnen …", bootstyle="primary",
                   command=self._add_files_dialog).pack(side="left", padx=6)
        ttk.Button(buttons, text="Ordner öffnen …",
                   bootstyle="primary-outline",
                   command=self._add_folder_dialog).pack(side="left", padx=6)

        self.empty_rule = ttk.Label(self.empty, foreground=theme.MUTED,
                                    anchor="center", justify="center")
        self.empty_rule.grid(row=2, column=0, pady=(6, 12))

    def _build_workspace(self) -> None:
        self.work = ttk.Frame(self)
        self.work.columnconfigure(0, weight=1)
        self.work.rowconfigure(3, weight=1)   # Spurtabelle wächst

        # ── Dateien ───────────────────────────────────────────────────────
        files_head = ttk.Frame(self.work)
        files_head.grid(row=0, column=0, sticky="ew")
        files_head.columnconfigure(1, weight=1)
        self.files_label = ttk.Label(files_head, text="DATEIEN",
                                     font=("Segoe UI", 9, "bold"),
                                     foreground=theme.MUTED)
        self.files_label.grid(row=0, column=0, sticky="w")

        fbtn = ttk.Frame(files_head)
        fbtn.grid(row=0, column=2, sticky="e")
        for text, cmd, style, lockable in [
                ("+ Dateien", self._add_files_dialog, "primary-outline", False),
                ("+ Ordner", self._add_folder_dialog, "primary-outline", False),
                ("− Entfernen", self._remove_selected, "secondary-outline", True),
                ("Leeren", self._clear_files, "secondary-outline", True)]:
            btn = ttk.Button(fbtn, text=text, bootstyle=style, command=cmd)
            btn.pack(side="left", padx=(6, 0))
            if lockable:
                self._lock_buttons.append(btn)
        self.output_btn = ttk.Button(fbtn, text="Ausgabe: Quellordner  ▾",
                                     bootstyle="secondary-outline",
                                     command=self._output_menu)
        self.output_btn.pack(side="left", padx=(18, 0))
        self._lock_buttons.append(self.output_btn)

        self.file_list = FileList(self.work, on_select=self._on_file_selected)
        self.file_list.grid(row=1, column=0, sticky="nsew", pady=(4, 10))
        self.file_list.tree.bind("<Button-3>", self._file_context_menu)

        # ── Regeln ────────────────────────────────────────────────────────
        rules = ttk.Frame(self.work)
        rules.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        rules.columnconfigure(2, weight=1)
        ttk.Label(rules, text="Profil:").grid(row=0, column=0, padx=(0, 6))
        self.profile_cb = ttk.Combobox(
            rules, state="readonly", width=30,
            values=[p.name for p in self.cfg.all_profiles()])
        self.profile_cb.set(self.profile.name)
        self.profile_cb.grid(row=0, column=1)
        self.profile_cb.bind("<<ComboboxSelected>>", self._on_profile_changed)
        self._lock_combos.append(self.profile_cb)
        edit_btn = ttk.Button(rules, text="Bearbeiten …",
                              bootstyle="secondary-outline",
                              command=self._edit_rules)
        edit_btn.grid(row=0, column=3, padx=(8, 0))
        self._lock_buttons.append(edit_btn)
        apply_all_btn = ttk.Button(rules, text="Auf alle Dateien",
                                   bootstyle="secondary-outline",
                                   command=self._apply_to_all)
        apply_all_btn.grid(row=0, column=4, padx=(6, 0))
        self._lock_buttons.append(apply_all_btn)
        self.rule_label = ttk.Label(rules, foreground=theme.MUTED)
        self.rule_label.grid(row=0, column=2, sticky="w", padx=(14, 0))

        # ── Spuren ────────────────────────────────────────────────────────
        tracks_frame = ttk.Frame(self.work)
        tracks_frame.grid(row=3, column=0, sticky="nsew")
        tracks_frame.columnconfigure(0, weight=1)
        tracks_frame.rowconfigure(1, weight=1)

        head = ttk.Frame(tracks_frame)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.tracks_label = ttk.Label(head, text="SPUREN",
                                      font=("Segoe UI", 9, "bold"),
                                      foreground=theme.MUTED)
        self.tracks_label.grid(row=0, column=0, sticky="w")
        tbtn = ttk.Frame(head)
        tbtn.grid(row=0, column=1, sticky="e")
        for text, cmd in [
                ("Alle an", lambda: self.track_table.set_all(True)),
                ("Alle aus", lambda: self.track_table.set_all(False)),
                ("↺ Regel", self._reset_selected_to_rule)]:
            btn = ttk.Button(tbtn, text=text, bootstyle="secondary-outline",
                             command=cmd)
            btn.pack(side="left", padx=(6, 0))
            self._lock_buttons.append(btn)

        self.track_table = TrackTable(tracks_frame,
                                      on_change=self._on_plan_edited)
        self.track_table.grid(row=1, column=0, sticky="nsew", pady=(4, 2))

        self.preview_label = ttk.Label(tracks_frame, foreground=theme.MUTED)
        self.preview_label.grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.warn_label = ttk.Label(tracks_frame,
                                    foreground=theme.COLORS["warning"])
        self.warn_label.grid(row=3, column=0, sticky="w")

        # ── Konvertierungs-Panel (nur sichtbar, wenn relevant) ──────────
        self.stereo_panel = ttk.Labelframe(
            self.work, text=" Audio-Konvertierung ", padding=(12, 8))
        self.stereo_panel.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._build_stereo_panel(self.stereo_panel)

        # ── Start + Fortschritt ───────────────────────────────────────────
        startbar = ttk.Frame(self.work)
        startbar.grid(row=5, column=0, sticky="ew", pady=(12, 6))
        startbar.columnconfigure(0, weight=1)
        self.start_btn = ttk.Button(startbar, text="▶  Start",
                                    bootstyle="primary",
                                    command=self._start)
        self.start_btn.grid(row=0, column=0, sticky="ew", ipady=4)
        self.cancel_btn = ttk.Button(startbar, text="⏹  Abbrechen",
                                     bootstyle="danger-outline",
                                     state="disabled", command=self._cancel)
        self.cancel_btn.grid(row=0, column=1, padx=(8, 0), ipady=4, ipadx=8)

        progress = ttk.Frame(self.work)
        progress.grid(row=6, column=0, sticky="ew")
        progress.columnconfigure(0, weight=3)
        progress.columnconfigure(1, weight=2)
        self.gauge_file = Floodgauge(progress, mask="Datei  {}%",
                                     bootstyle="primary", value=0,
                                     font=("Segoe UI", 9))
        self.gauge_file.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.gauge_total = Floodgauge(progress, mask="Gesamt  {}%",
                                      bootstyle="success", value=0,
                                      font=("Segoe UI", 9))
        self.gauge_total.grid(row=0, column=1, sticky="ew")
        self.status_label = ttk.Label(progress, foreground=theme.MUTED)
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="w",
                               pady=(2, 0))

        # ── Protokoll ─────────────────────────────────────────────────────
        self.log = LogPanel(self.work, expanded=self.cfg.log_expanded,
                            on_toggle=lambda _e: self._autosize())
        self.log.grid(row=7, column=0, sticky="nsew", pady=(6, 0))

    def _build_stereo_panel(self, panel: ttk.Labelframe) -> None:
        self._codec_by_label = {v["label"]: k for k, v in OUTPUT_CODECS.items()}
        self._preset_by_label = {v["label"]: k
                                 for k, v in DOWNMIX_PRESETS.items()}

        row1 = ttk.Frame(panel)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Codec:").pack(side="left")
        self.codec_cb = ttk.Combobox(
            row1, state="readonly", width=24,
            values=[v["label"] for v in OUTPUT_CODECS.values()])
        self.codec_cb.set(OUTPUT_CODECS[self.stereo.codec]["label"])
        self.codec_cb.pack(side="left", padx=(6, 18))
        self.codec_cb.bind("<<ComboboxSelected>>", self._on_stereo_changed)

        ttk.Label(row1, text="Kanäle:").pack(side="left")
        self.channels_cb = ttk.Combobox(row1, state="readonly", width=6)
        self.channels_cb.pack(side="left", padx=(6, 18))
        self.channels_cb.bind("<<ComboboxSelected>>", self._on_stereo_changed)

        ttk.Label(row1, text="Bitrate:").pack(side="left")
        self.bitrate_cb = ttk.Combobox(row1, state="readonly", width=8)
        self.bitrate_cb.pack(side="left", padx=(6, 18))
        self.bitrate_cb.bind("<<ComboboxSelected>>", self._on_stereo_changed)

        ttk.Label(row1, text="Downmix:").pack(side="left")
        self.preset_cb = ttk.Combobox(
            row1, state="readonly", width=26,
            values=[v["label"] for v in DOWNMIX_PRESETS.values()])
        self.preset_cb.set(DOWNMIX_PRESETS[self.stereo.downmix_preset]["label"])
        self.preset_cb.pack(side="left", padx=(6, 0))
        self.preset_cb.bind("<<ComboboxSelected>>", self._on_stereo_changed)

        row2 = ttk.Frame(panel)
        row2.pack(fill="x", pady=(6, 2))
        ttk.Label(row2, text="Spurname:").pack(side="left")
        self.trackname_var = ttk.StringVar(value=self.stereo.track_name)
        entry = ttk.Entry(row2, textvariable=self.trackname_var, width=24)
        entry.pack(side="left", padx=(6, 18))
        entry.bind("<FocusOut>", self._on_stereo_changed)
        self._lock_buttons.append(entry)

        self.stereo_default_var = ttk.BooleanVar(
            value=self.profile.stereo_make_default)
        default_cb = ttk.Checkbutton(
            row2, text="Neue Stereospur als Standard-Audiospur",
            variable=self.stereo_default_var, bootstyle="primary",
            command=self._on_stereo_default_toggled)
        default_cb.pack(side="left")
        self._lock_buttons.append(default_cb)
        self._lock_combos += [self.codec_cb, self.bitrate_cb, self.preset_cb]

        self.preset_hint = ttk.Label(panel, foreground=theme.MUTED)
        self.preset_hint.pack(anchor="w", pady=(6, 0))

        self._last_suggested = self.stereo.suggested_track_name()
        self._lock_combos.append(self.channels_cb)
        self._refresh_channels()
        self._refresh_bitrates()
        self._refresh_preset_hint()
        self.track_table.convert_label = self.stereo.short_label()

    # ══ Zustand / Anzeige ════════════════════════════════════════════════

    def _sync_state(self) -> None:
        """Leerzustand ↔ Arbeitsansicht."""
        if self.plans:
            self.empty.grid_forget()
            self.work.grid(row=1, column=0, sticky="nsew")
            self.rowconfigure(1, weight=1)
        else:
            self.work.grid_forget()
            self.empty.grid(row=1, column=0, sticky="nsew")
            self.empty_rule.configure(
                text=f"Aktives Profil „{self.profile.name}“:\n"
                     f"{describe(self.profile)}")
        self._autosize(allow_shrink=not self.plans)

    def _autosize(self, allow_shrink: bool = False) -> None:
        top = self.winfo_toplevel()
        if hasattr(top, "autosize"):
            top.autosize(allow_shrink=allow_shrink)

    def _selected_plan(self) -> FilePlan | None:
        return self.plans.get(self.selected) if self.selected else None

    def _refresh_all(self) -> None:
        """Nach Profil-/Planänderungen: alles Abgeleitete neu zeichnen."""
        self.rule_label.configure(text="» " + describe(self.profile) + " «")
        self.files_label.configure(text=f"DATEIEN ({len(self.plans)})")
        for path, plan in self.plans.items():
            if plan is not None:
                self._update_file_row(path, plan)
        plan = self._selected_plan()
        self.tracks_label.configure(
            text=("SPUREN · " + Path(self.selected).name) if plan else "SPUREN")
        self.track_table.set_plan(plan)
        self._update_preview()
        self._update_stereo_panel_visibility()
        self._update_start_button()

    def _update_file_row(self, path: str, plan: FilePlan) -> None:
        total = len(plan.media.tracks)
        kept = sum(len(plan.kept_ids(t)) for t in ("video", "audio", "subtitles"))
        stereo = len(plan.stereo_sources())
        text = f"{kept}/{total} Spuren"
        if stereo:
            text += f" · {stereo}× {plan.stereo.short_label()}"
        if plan.profile_name:
            text += f" · {plan.profile_name}"
        tag = _STATUS_TAGS.get(plan.status, "")
        if plan.warnings and plan.status is FileStatus.READY:
            text += "  ⚠"
            tag = "warn"
        self.file_list.update_file(
            path, duration=plan.media.duration_s, plan_text=text,
            status=plan.status.value, tag=tag)

    def _update_preview(self) -> None:
        plan = self._selected_plan()
        if plan is None:
            self.preview_label.configure(text="")
            self.warn_label.configure(text="")
            return
        counts = plan.output_track_count
        video_part = f"{counts['video']}× Video"
        if plan.video_mode == dv_analysis.VIDEO_MODE_HDR10:
            video_part += " (DV entfernt → HDR10, verlustfrei)"
        elif plan.video_mode == dv_analysis.VIDEO_MODE_DV81:
            video_part += " (DV → Profil 8.1)"
        elif plan.dv is not None and plan.dv.describe():
            video_part += f" ({plan.dv.describe()})"
        parts = [video_part]
        stereo = plan.stereo_sources()
        audio_part = f"{counts['audio']}× Audio"
        if stereo:
            langs = ", ".join(display_name(t.lang) for t in stereo)
            audio_part += (f" (NEU: {langs} {plan.stereo.short_label()} "
                           f"{plan.stereo.bitrate})")
        parts.append(audio_part)
        parts.append(f"{counts['subtitles']}× Untertitel")
        if plan.media.has_chapters:
            parts.append("Kapitel ✓")
        self.preview_label.configure(
            text="Ausgabe: " + " · ".join(parts)
                 + f"   →   {Path(plan.output_path).name}")
        self.warn_label.configure(
            text=("⚠ " + "  ·  ".join(plan.warnings)) if plan.warnings else "")

    def _update_stereo_panel_visibility(self) -> None:
        # Das Panel zeigt und editiert die Konfiguration der AUSGEWÄHLTEN Datei
        plan = self._selected_plan()
        any_stereo = bool(plan and plan.stereo_sources())
        visible = bool(self.stereo_panel.winfo_manager())
        if plan is not None:
            count = len(plan.stereo_sources())
            self.stereo_panel.configure(
                text=f" Audio-Konvertierung · {Path(plan.media.path).name} "
                     f"— wirkt auf {count} Spur(en) dieser Datei ")
        if any_stereo and not visible:
            self.stereo_panel.grid(row=4, column=0, sticky="ew", pady=(10, 0))
            self._autosize()
        elif not any_stereo and visible:
            self.stereo_panel.grid_remove()

    def _update_start_button(self) -> None:
        ready = [p for p in self.plans.values()
                 if p and p.status not in (FileStatus.RUNNING,)]
        lossless = sum(len(p.kept_ids(t)) for p in ready if p
                       for t in ("video", "audio", "subtitles"))
        stereo = sum(len(p.stereo_sources()) for p in ready if p)
        n = len(ready)
        if n == 0:
            self.start_btn.configure(text="▶  Start", state="disabled")
            return
        text = f"▶  Start — {n} Datei{'en' if n != 1 else ''}"
        text += f" · {lossless} Spuren verlustfrei"
        if stereo:
            labels = {p.stereo.short_label() for p in ready
                      if p.stereo_sources()}
            target = (f" → {labels.pop()}" if len(labels) == 1
                      else " (Ziel je Datei)")
            text += (f" · {stereo} Konvertierung{'en' if stereo != 1 else ''}"
                     f"{target}")
        self.start_btn.configure(
            text=text, state="disabled" if self._running else "normal")

    # ══ Dateien hinzufügen / entfernen ═══════════════════════════════════

    def add_files(self, paths: list[str]) -> None:
        # Pfade kanonisieren: sonst landet dieselbe Datei über Slash-Form
        # oder Groß-/Kleinschreibung doppelt in der Liste
        known = {p.lower() for p in self.plans}
        added: list[str] = []
        for raw in paths:
            if not raw.lower().endswith(".mkv"):
                continue
            try:
                path = str(Path(raw).resolve())
            except OSError:
                path = str(Path(raw))
            if path.lower() in known:
                continue
            known.add(path.lower())
            added.append(path)
        if not added:
            return
        for path in added:
            self.plans[path] = None
            if not self.file_list.contains(path):
                self.file_list.add_file(path)
            threading.Thread(target=self._scan_worker, args=(path,),
                             daemon=True).start()
        self._sync_state()
        self._refresh_all()
        self.log.log(f"{len(added)} Datei(en) hinzugefügt.", "info")

    def _scan_worker(self, path: str) -> None:
        with self._scan_sem:
            mkvmerge = self.tools.get("mkvmerge", "")
            try:
                media = scan_file(mkvmerge or "mkvmerge", path)
            except ScanError as exc:
                self.ui_q.put(("SCAN_FAILED", path, str(exc)))
                return
            dv_info = None
            ffprobe = self.tools.get("ffprobe", "")
            if ffprobe and media.by_type("video"):
                try:
                    dv_info = dv_analysis.analyze(ffprobe, path)
                except dv_analysis.DVError:
                    dv_info = None   # DV-Analyse ist optional, nie blockierend
            self.ui_q.put(("SCANNED", path, media, dv_info))

    def _add_files_dialog(self) -> None:
        paths = filedialog.askopenfilenames(
            filetypes=[("MKV-Dateien", "*.mkv"), ("Alle Dateien", "*.*")])
        if paths:
            self.add_files(list(paths))

    def _add_folder_dialog(self) -> None:
        folder = filedialog.askdirectory(title="Ordner mit MKV-Dateien wählen")
        if folder:
            files = sorted(str(p) for p in Path(folder).glob("*.mkv"))
            self.add_files(files)

    def _remove_selected(self) -> None:
        if self._running:
            return
        for path in self.file_list.remove_selected():
            self.plans.pop(path, None)
            if self.selected == path:
                self.selected = None
        if self.selected is None and self.plans:
            first = next(iter(self.plans))
            self.selected = first
            self.file_list.select(first)
        self._sync_state()
        self._refresh_all()

    def _clear_files(self) -> None:
        if self._running:
            return
        self.plans.clear()
        self.selected = None
        self.file_list.clear()
        self._sync_state()
        self._refresh_all()

    def _on_file_selected(self, path: str) -> None:
        self.selected = path
        plan = self.plans.get(path)
        if plan is not None:
            # Panel & Profil zeigen die Konfiguration DIESER Datei;
            # self.stereo ist eine Referenz — Panel-Änderungen landen direkt
            # im Plan der Datei (Job-Queue-Prinzip)
            self.profile = self.cfg.profile(
                plan.profile_name or self.cfg.active_profile)
            self.profile.output.directory = self.output_dir
            self.stereo = plan.stereo
            self._sync_panel_from_state()
        self._refresh_all()

    def _sync_panel_from_state(self) -> None:
        """Comboboxen/Felder auf self.profile + self.stereo stellen,
        ohne Änderungs-Handler auszulösen."""
        self.profile_cb.set(self.profile.name)
        self.codec_cb.set(OUTPUT_CODECS[self.stereo.codec]["label"])
        self.preset_cb.set(DOWNMIX_PRESETS[self.stereo.downmix_preset]["label"])
        self.trackname_var.set(self.stereo.track_name)
        self._last_suggested = self.stereo.suggested_track_name()
        self._refresh_channels()
        self._refresh_bitrates()
        self._refresh_preset_hint()
        self.preset_cb.configure(
            state="disabled" if (self.stereo.channels != "2.0"
                                 or self._running) else "readonly")
        self.track_table.convert_label = self.stereo.short_label()

    def _file_context_menu(self, event) -> None:
        import os
        import tkinter as tk
        path = self.file_list.tree.identify_row(event.y)
        if not path:
            return
        self.file_list.select(path)
        plan = self.plans.get(path)
        menu = tk.Menu(self, tearoff=0)
        if plan is not None:
            menu.add_command(label="Ausgabename/-ort ändern …",
                             command=lambda: self._change_output(plan))
            menu.add_command(
                label="Ausgabeordner öffnen",
                command=lambda: os.startfile(Path(plan.output_path).parent))
        menu.add_command(label="Quellordner öffnen",
                         command=lambda: os.startfile(Path(path).parent))
        menu.add_separator()
        menu.add_command(label="Aus der Liste entfernen",
                         command=self._remove_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _change_output(self, plan: FilePlan) -> None:
        current = Path(plan.output_path)
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Ausgabedatei wählen",
            initialdir=str(current.parent), initialfile=current.name,
            defaultextension=".mkv",
            filetypes=[("MKV-Dateien", "*.mkv")])
        if chosen:
            plan.output_path = chosen
            plan.output_manual = True
            self._update_preview()

    # ══ Regeln / Profil ══════════════════════════════════════════════════

    def _on_profile_changed(self, _event=None) -> None:
        """Profilwechsel gilt für die AUSGEWÄHLTE Datei (Job-Queue-Prinzip);
        ohne Auswahl stellt er die Vorlage für neue Dateien um."""
        self.profile = self.cfg.profile(self.profile_cb.get())
        self.cfg.active_profile = self.profile.name
        # fester Ausgabeordner ist App-Zustand und überlebt den Wechsel
        self.profile.output.directory = self.output_dir

        plan = self._selected_plan()
        if plan is not None:
            plan.profile_name = self.profile.name
            plan.stereo = replace(self.profile.stereo)
            self.stereo = plan.stereo
            reapply_rules(plan, self.profile)
            if not plan.output_manual:
                plan.output_path = self.profile.output.output_path_for(
                    plan.media.path)
        else:
            self.stereo = replace(self.profile.stereo)

        self.stereo_default_var.set(self.profile.stereo_make_default)
        self._sync_panel_from_state()
        self._refresh_all()

    def _apply_to_all(self) -> None:
        """Aktuelles Profil + Konvertierungs-Einstellungen auf alle Dateien
        übertragen (manuelle Spur-Overrides bleiben geschützt)."""
        for path, plan in self.plans.items():
            if plan is None:
                continue
            plan.profile_name = self.profile.name
            plan.stereo = replace(self.stereo)
            reapply_rules(plan, self.profile)
            if not plan.output_manual:
                plan.output_path = self.profile.output.output_path_for(path)
        selected = self._selected_plan()
        if selected is not None:
            self.stereo = selected.stereo
        self._refresh_all()
        self.log.log(f"Profil „{self.profile.name}“ + Einstellungen auf "
                     f"alle Dateien angewendet.", "info")

    def _edit_rules(self) -> None:
        from .rule_editor import RuleEditorDialog
        dialog = RuleEditorDialog(
            self, self.profile,
            existing_names=[p.name for p in self.cfg.all_profiles()])
        self.wait_window(dialog)
        if dialog.result is None:
            return
        action, profile = dialog.result

        if action == "apply":
            self.cfg.user_profiles = [
                profile if p.name == profile.name else p
                for p in self.cfg.user_profiles]
            self.profile = profile
        elif action == "new":
            self.cfg.user_profiles.append(profile)
            self.profile = profile
        elif action == "delete":
            self.cfg.user_profiles = [
                p for p in self.cfg.user_profiles if p.name != profile.name]
            self.profile = self.cfg.all_profiles()[0]

        self.cfg.active_profile = self.profile.name
        self.profile_cb.configure(
            values=[p.name for p in self.cfg.all_profiles()])
        self.profile_cb.set(self.profile.name)
        try:
            appconfig.save(self.cfg)
        except OSError as exc:
            self.log.log(f"Konfiguration nicht speicherbar: {exc}", "error")
        self._on_profile_changed()
        if not self.plans:
            self._sync_state()   # Leerzustand-Beschreibung aktualisieren

    def _reset_selected_to_rule(self) -> None:
        plan = self._selected_plan()
        if plan is not None:
            reset_manual(plan, self.profile)
            self._refresh_all()

    def _refresh_output_name(self, plan: FilePlan) -> None:
        """Dateiname folgt dem Video-Modus: „ [HDR10].mkv“ / „ [DV8.1].mp4“."""
        if plan.output_manual:
            return
        base = Path(self.profile.output.output_path_for(plan.media.path))
        if plan.video_mode == dv_analysis.VIDEO_MODE_HDR10:
            name = f"{base.stem} [HDR10].mkv"
        elif plan.video_mode == dv_analysis.VIDEO_MODE_DV81:
            name = f"{base.stem} [DV8.1].mp4"
        else:
            name = base.name
        plan.output_path = str(base.with_name(name))

    def _on_plan_edited(self) -> None:
        plan = self._selected_plan()
        if plan is not None:
            self._refresh_output_name(plan)
            self._update_file_row(self.selected, plan)
        self._update_preview()
        self._update_stereo_panel_visibility()
        self._update_start_button()

    # ══ Stereo-Einstellungen ═════════════════════════════════════════════

    def _refresh_channels(self) -> None:
        targets = OUTPUT_CODECS[self.stereo.codec]["channel_targets"]
        self.channels_cb.configure(values=targets)
        if self.stereo.channels not in targets:
            self.stereo.channels = targets[-1]   # 7.1→5.1 beim Codec-Wechsel
        self.channels_cb.set(self.stereo.channels)

    def _refresh_bitrates(self) -> None:
        info = OUTPUT_CODECS[self.stereo.codec]
        self.bitrate_cb.configure(values=info["bitrates"])
        if self.stereo.bitrate not in info["bitrates"]:
            self.stereo.bitrate = info["default_bitrate"]
        self.bitrate_cb.set(self.stereo.bitrate)

    def _on_stereo_changed(self, _event=None) -> None:
        self.stereo.codec = self._codec_by_label[self.codec_cb.get()]
        self.stereo.channels = self.channels_cb.get() or self.stereo.channels
        self._refresh_channels()
        self._refresh_bitrates()
        self.stereo.bitrate = self.bitrate_cb.get()
        self.stereo.downmix_preset = self._preset_by_label[self.preset_cb.get()]

        # Spurname folgt dem Vorschlag, solange der Nutzer ihn nicht anfasst
        suggested = self.stereo.suggested_track_name()
        current = self.trackname_var.get().strip()
        if current in ("", self._last_suggested):
            self.trackname_var.set(suggested)
        self._last_suggested = suggested
        self.stereo.track_name = (self.trackname_var.get().strip()
                                  or suggested)

        # Downmix-Preset wirkt nur beim Ziel 2.0
        self.preset_cb.configure(
            state="disabled" if (self.stereo.channels != "2.0"
                                 or self._running) else "readonly")
        self.track_table.convert_label = self.stereo.short_label()
        self.track_table.refresh()
        self._refresh_preset_hint()
        self._update_preview()

    def _refresh_preset_hint(self) -> None:
        if self.stereo.channels == "2.0":
            hint = DOWNMIX_PRESETS[self.stereo.downmix_preset]["hint"]
        else:
            hint = (f"Ziel {self.stereo.channels}: FFmpeg mischt mit Standard-"
                    f"Koeffizienten; kein Upmix — Quellen mit weniger Kanälen "
                    f"behalten ihr Layout.")
        if self.stereo.codec in ("ac3", "eac3"):
            hint += "  ·  AC3/E-AC3: maximal 5.1 (echtes 7.1 nur als AAC)."
        self.preset_hint.configure(text="ⓘ " + hint)

    def _on_stereo_default_toggled(self) -> None:
        """Wirkt — wie das ganze Panel — nur auf die ausgewählte Datei."""
        plan = self._selected_plan()
        if plan is None:
            return
        stereo = plan.stereo_sources()
        if not stereo:
            return
        if self.stereo_default_var.get():
            plan.set_default_audio(stereo[0].id, on_stereo=True)
        else:
            plan.default_audio_source = None
            plan._ensure_default_valid()
            if plan.default_audio_is_stereo and plan.kept_ids("audio"):
                plan.set_default_audio(plan.kept_ids("audio")[0],
                                       on_stereo=False)
        self.track_table.refresh()
        self._update_preview()

    # ══ Ausgabe-Ziel ═════════════════════════════════════════════════════

    def _output_menu(self) -> None:
        import tkinter as tk
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Quellordner (Suffix „_remux“)",
                         command=lambda: self._set_output_dir(""))
        menu.add_command(label="Fester Ordner wählen …",
                         command=self._choose_output_dir)
        menu.tk_popup(self.output_btn.winfo_rootx(),
                      self.output_btn.winfo_rooty()
                      + self.output_btn.winfo_height())

    def _choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Ausgabeordner wählen")
        if folder:
            self._set_output_dir(folder)

    def _set_output_dir(self, folder: str) -> None:
        self.output_dir = folder
        self.profile.output.directory = folder
        label = Path(folder).name if folder else "Quellordner"
        self.output_btn.configure(text=f"Ausgabe: {label}  ▾")
        for path, plan in self.plans.items():
            if plan is not None and not plan.output_manual:
                plan.output_path = self.profile.output.output_path_for(path)
        self._update_preview()

    # ══ Start / Abbruch ══════════════════════════════════════════════════

    def _start(self) -> None:
        import copy
        import os
        plans = [p for p in self.plans.values() if p is not None]
        if not plans or self._running:
            return
        needs_ffmpeg = any(p.stereo_sources() for p in plans)
        missing = [n for n in ("mkvmerge",)
                   + (("ffmpeg",) if needs_ffmpeg else ())
                   if not self.tool_status.get(n)
                   or not self.tool_status[n].ok]
        if missing:
            Messagebox.show_error(
                f"Benötigte Tools fehlen: {', '.join(missing)}.\n"
                f"Bitte über das ⚙-Symbol einrichten.", "Tools fehlen",
                parent=self)
            return

        # Ausgabe-Kollisionen (gleicher Dateiname aus verschiedenen Ordnern
        # bei festem Ausgabeordner) vor dem Start abfangen
        seen: dict[str, str] = {}
        for p in plans:
            key = os.path.normcase(os.path.abspath(p.output_path))
            if key in seen:
                Messagebox.show_error(
                    f"Zwei Dateien hätten dieselbe Ausgabedatei:\n"
                    f"{Path(seen[key]).name}  und  {Path(p.media.path).name}\n"
                    f"→ {Path(p.output_path).name}\n\n"
                    f"Bitte Ausgabename oder -ordner anpassen "
                    f"(Rechtsklick auf die Datei).", "Ausgabe-Kollision",
                    parent=self)
                return
            seen[key] = p.media.path

        existing = [p for p in plans if Path(p.output_path).exists()]
        if existing:
            answer = Messagebox.yesno(
                f"{len(existing)} Ausgabedatei(en) existieren bereits.\n"
                f"Überschreiben?", "Ausgabe vorhanden", parent=self)
            if answer not in ("Ja", "Yes"):
                return

        self.cancel.clear()
        self.log.clear()
        for plan in plans:
            plan.status = FileStatus.WAITING
            self._update_file_row(plan.media.path, plan)
        self.gauge_file.configure(value=0)
        self.gauge_total.configure(value=0)
        self._set_running(True)

        # Snapshot: Der Worker arbeitet auf Kopien — die UI ist zusätzlich
        # gesperrt, aber selbst wenn etwas durchrutscht, bleibt der Lauf
        # von Modelländerungen isoliert.
        run_plans = [copy.deepcopy(p) for p in plans]
        self.runner = JobRunner(self.tools, self.ui_q, self.cancel)
        self._worker = threading.Thread(
            target=self.runner.run, args=(run_plans,), daemon=True)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        self._running = running
        widget_state = "disabled" if running else "normal"
        combo_state = "disabled" if running else "readonly"
        for widget in self._lock_buttons:
            widget.configure(state=widget_state)
        for combo in self._lock_combos:
            combo.configure(state=combo_state)
        self.track_table.locked = running
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        if not running:
            # Zustandsabhängige Feinheiten wiederherstellen (Preset-Sperre)
            self._on_stereo_changed()

    def _cancel(self) -> None:
        self.cancel.set()
        if self.runner:
            self.runner.terminate_active()
        self.log.log("Abbruch angefordert …", "error")

    # ══ Queue-Verarbeitung ═══════════════════════════════════════════════

    def _poll_queue(self) -> None:
        try:
            for _ in range(80):
                msg = self.ui_q.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        finally:
            self.after(80, self._poll_queue)

    def _handle_message(self, msg: tuple) -> None:
        kind = msg[0]
        if kind == "LOG":
            self.log.log(msg[1], msg[2] if len(msg) > 2 else None)
        elif kind == "STATUS":
            self.status_label.configure(text=msg[1])
        elif kind == "PROGRESS_FILE":
            self.gauge_file.configure(value=msg[1])
        elif kind == "PROGRESS_TOTAL":
            self.gauge_total.configure(value=msg[1])
        elif kind == "FILE_STATUS":
            _, path, status, error = msg
            plan = self.plans.get(path)
            if plan:
                # Runner arbeitet auf Kopien — Status aufs Original spiegeln
                plan.status = status
                plan.error = error
                self._update_file_row(path, plan)
            if status is FileStatus.ERROR and error:
                self.log.set_expanded(True)
        elif kind == "SCANNED":
            path, media = msg[1], msg[2]
            if path not in self.plans:
                return   # Datei wurde während des Scans entfernt
            plan = build_plan(media, self.profile)
            # neue Dateien erben die gerade sichtbare Konfiguration
            plan.stereo = replace(self.stereo)
            plan.profile_name = self.profile.name
            plan.dv = msg[3] if len(msg) > 3 else None
            if plan.dv is not None and plan.dv.dv_profile == 7:
                plan.warnings.append(
                    "Dolby Vision Profil 7 erkannt — viele Geräte zeigen "
                    "das aus MKV falsch an. Rechtsklick auf die Videospur "
                    "→ „DV entfernen (HDR10)“.")
            self.plans[path] = plan
            self._update_file_row(path, plan)
            for warning in plan.warnings:
                self.log.log(f"{Path(path).name}: {warning}", "step")
            if self.selected is None:
                self.selected = path
                self.file_list.select(path)
            self._refresh_all()
            self._autosize()
        elif kind == "SCAN_FAILED":
            path, error = msg[1], msg[2]
            if path not in self.plans:
                return   # Datei wurde während des Scans entfernt
            self.file_list.update_file(path, plan_text=error,
                                       status="Scan-Fehler", tag="error")
            self.log.log(f"{Path(path).name}: {error}", "error")
        elif kind == "TOOLS":
            self.tool_status = msg[1]
            self._update_tool_chips()
        elif kind == "BATCH_DONE":
            self._on_batch_done(msg[1], msg[2], msg[3])

    def _on_batch_done(self, success: int, total: int, cancelled: bool) -> None:
        self._set_running(False)
        self.status_label.configure(text="")
        self._update_start_button()
        if cancelled:
            message, style = "Abgebrochen.", "warning"
        elif success == total:
            message = (f"{total} Datei{'en' if total != 1 else ''} "
                       f"erfolgreich verarbeitet.")
            style = "success"
        else:
            message = (f"{success}/{total} erfolgreich — "
                       f"{total - success} Fehler, siehe Protokoll.")
            style = "danger"
            self.log.set_expanded(True)
        self.log.log(message, "success" if style == "success" else "error")
        try:
            ToastNotification(title="Spurwerk", message=message,
                              duration=4000, bootstyle=style).show_toast()
        except Exception:
            pass  # Toast ist Komfort, nie ein Absturzgrund
        if success:
            # erledigte Dateien verlassen die Warteschlange (kurz verzögert,
            # damit der grüne „fertig“-Status sichtbar bleibt)
            self.after(1500, self._remove_done_files)

    def _remove_done_files(self) -> None:
        """Job-Queue-Verhalten: erfolgreich verarbeitete Dateien fliegen aus
        der Liste — Fehler und Übersprungenes bleiben sichtbar stehen.
        Die QUELLDATEIEN werden selbstverständlich nicht angetastet."""
        done = [path for path, plan in self.plans.items()
                if plan and plan.status is FileStatus.DONE]
        if not done:
            return
        for path in done:
            self.plans.pop(path, None)
            self.file_list.remove(path)
        self.log.log(f"{len(done)} erledigte Datei(en) aus der Liste "
                     f"entfernt.", "dim")
        if self.selected not in self.plans:
            self.selected = next(iter(self.plans), None)
            if self.selected:
                self.file_list.select(self.selected)
        self._sync_state()
        self._refresh_all()

    # ══ Tools ════════════════════════════════════════════════════════════

    def _probe_tools(self) -> None:
        self.tools = toolchain.detect_tools(appconfig.base_path(),
                                            self.cfg.tools)
        self.ui_q.put(("TOOLS", toolchain.probe_all(self.tools)))

    def _update_tool_chips(self) -> None:
        for name, status in self.tool_status.items():
            chip = self.tool_chips.get(name)
            if chip is None:
                continue   # optionale Tools (dovi_tool, …) haben keinen Chip
            if status.ok:
                chip.configure(image=self._dot_ok,
                               text=f" {name} {status.version}")
            else:
                chip.configure(image=self._dot_bad, text=f" {name} fehlt")
        self.track_table.dovi_ok = bool(
            self.tool_status.get("dovi_tool")
            and self.tool_status["dovi_tool"].ok)
        self.track_table.mp4box_ok = bool(
            self.tool_status.get("mp4box")
            and self.tool_status["mp4box"].ok)
        self._update_onboarding()

    def _update_onboarding(self) -> None:
        # Nur PFLICHT-Tools entscheiden übers Onboarding — optionale
        # (dovi_tool, mp4box) fehlen zu dürfen ist Normalzustand
        missing = (not self.tool_status
                   or any(not self.tool_status[n].ok
                          for n in toolchain.REQUIRED
                          if n in self.tool_status))
        if missing and not self.plans:
            self.onboarding.grid(row=0, column=0, sticky="ew", pady=(4, 10))
        else:
            self.onboarding.grid_forget()
        self._autosize()

    def _open_tool_manager(self, auto_download: bool = False) -> None:
        from .tool_setup import ToolManagerDialog
        dialog = ToolManagerDialog(
            self, self.cfg, self.tool_status,
            on_changed=lambda: threading.Thread(
                target=self._probe_tools, daemon=True).start())
        if auto_download:
            dialog.after(300, lambda: dialog._download(only_missing=True))

    # ══ Persistenz ═══════════════════════════════════════════════════════

    def on_close(self) -> bool:
        """True = schließen erlaubt. Laufende Jobs werden erst bestätigt,
        dann sauber terminiert; ein Speicherfehler blockiert nie das Beenden."""
        if self._worker is not None and self._worker.is_alive():
            answer = Messagebox.yesno(
                "Die Verarbeitung läuft noch — wirklich beenden?\n"
                "Die aktuelle Datei wird abgebrochen und aufgeräumt.",
                "Spurwerk beenden", parent=self)
            if answer not in ("Ja", "Yes"):
                return False
            self.cancel.set()
            if self.runner:
                self.runner.terminate_active()
            self._worker.join(timeout=3)
        self.cfg.log_expanded = self.log.expanded
        try:
            appconfig.save(self.cfg)
        except OSError:
            pass  # z. B. schreibgeschützter Ordner — Beenden geht trotzdem
        return True
