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

        brand = ttk.Frame(bar)
        brand.grid(row=0, column=0, sticky="w")
        ttk.Label(brand, text="SPUR", font=("Segoe UI", 13, "bold")
                  ).pack(side="left")
        ttk.Label(brand, text="WERK", font=("Segoe UI", 13, "bold"),
                  foreground=theme.COLORS["primary"]).pack(side="left")

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
        for text, cmd, style in [
                ("+ Dateien", self._add_files_dialog, "primary-outline"),
                ("+ Ordner", self._add_folder_dialog, "primary-outline"),
                ("− Entfernen", self._remove_selected, "secondary-outline"),
                ("Leeren", self._clear_files, "secondary-outline")]:
            ttk.Button(fbtn, text=text, bootstyle=style, command=cmd,
                       ).pack(side="left", padx=(6, 0))
        self.output_btn = ttk.Button(fbtn, text="Ausgabe: Quellordner  ▾",
                                     bootstyle="secondary-outline",
                                     command=self._output_menu)
        self.output_btn.pack(side="left", padx=(18, 0))

        self.file_list = FileList(self.work, on_select=self._on_file_selected)
        self.file_list.grid(row=1, column=0, sticky="nsew", pady=(4, 10))

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
        ttk.Button(rules, text="Bearbeiten …", bootstyle="secondary-outline",
                   command=self._edit_rules).grid(row=0, column=3, padx=(8, 0))
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
        ttk.Button(tbtn, text="Alle an", bootstyle="secondary-outline",
                   command=lambda: self.track_table.set_all(True)
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(tbtn, text="Alle aus", bootstyle="secondary-outline",
                   command=lambda: self.track_table.set_all(False)
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(tbtn, text="↺ Regel", bootstyle="secondary-outline",
                   command=self._reset_selected_to_rule
                   ).pack(side="left", padx=(6, 0))

        self.track_table = TrackTable(tracks_frame,
                                      on_change=self._on_plan_edited)
        self.track_table.grid(row=1, column=0, sticky="nsew", pady=(4, 2))

        self.preview_label = ttk.Label(tracks_frame, foreground=theme.MUTED)
        self.preview_label.grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.warn_label = ttk.Label(tracks_frame,
                                    foreground=theme.COLORS["warning"])
        self.warn_label.grid(row=3, column=0, sticky="w")

        # ── Stereo-Panel (nur sichtbar, wenn relevant) ───────────────────
        self.stereo_panel = ttk.Labelframe(
            self.work, text=" Stereo-Konvertierung ", padding=(12, 8))
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

        self.stereo_default_var = ttk.BooleanVar(
            value=self.profile.stereo_make_default)
        ttk.Checkbutton(
            row2, text="Neue Stereospur als Standard-Audiospur",
            variable=self.stereo_default_var, bootstyle="primary",
            command=self._on_stereo_default_toggled).pack(side="left")

        self._refresh_bitrates()

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
            text += f" · {stereo}× Stereo"
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
        parts = [f"{counts['video']}× Video"]
        stereo = plan.stereo_sources()
        audio_part = f"{counts['audio']}× Audio"
        if stereo:
            langs = ", ".join(display_name(t.lang) for t in stereo)
            audio_part += (f" (NEU: {langs} Stereo "
                           f"{self.stereo.codec.upper()} {self.stereo.bitrate})")
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
        any_stereo = any(p and p.stereo_sources() for p in self.plans.values())
        visible = bool(self.stereo_panel.winfo_manager())
        count = sum(len(p.stereo_sources())
                    for p in self.plans.values() if p)
        self.stereo_panel.configure(
            text=f" Stereo-Konvertierung — wirkt auf {count} Spur(en) ")
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
            text += f" · {stereo} Stereo-Konvertierung{'en' if stereo != 1 else ''}"
        running = self._worker is not None and self._worker.is_alive()
        self.start_btn.configure(text=text,
                                 state="disabled" if running else "normal")

    # ══ Dateien hinzufügen / entfernen ═══════════════════════════════════

    def add_files(self, paths: list[str]) -> None:
        added = [p for p in paths
                 if p.lower().endswith(".mkv") and p not in self.plans]
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
                self.ui_q.put(("SCANNED", path, media))
            except ScanError as exc:
                self.ui_q.put(("SCAN_FAILED", path, str(exc)))

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
        self.plans.clear()
        self.selected = None
        self.file_list.clear()
        self._sync_state()
        self._refresh_all()

    def _on_file_selected(self, path: str) -> None:
        self.selected = path
        self._refresh_all()

    # ══ Regeln / Profil ══════════════════════════════════════════════════

    def _on_profile_changed(self, _event=None) -> None:
        self.profile = self.cfg.profile(self.profile_cb.get())
        self.cfg.active_profile = self.profile.name
        self.stereo = replace(self.profile.stereo)
        self.codec_cb.set(OUTPUT_CODECS[self.stereo.codec]["label"])
        self.preset_cb.set(DOWNMIX_PRESETS[self.stereo.downmix_preset]["label"])
        self.trackname_var.set(self.stereo.track_name)
        self.stereo_default_var.set(self.profile.stereo_make_default)
        self._refresh_bitrates()
        for path, plan in self.plans.items():
            if plan is not None:
                reapply_rules(plan, self.profile)
                plan.output_path = self.profile.output.output_path_for(path)
        self._refresh_all()

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
        appconfig.save(self.cfg)
        self._on_profile_changed()
        if not self.plans:
            self._sync_state()   # Leerzustand-Beschreibung aktualisieren

    def _reset_selected_to_rule(self) -> None:
        plan = self._selected_plan()
        if plan is not None:
            reset_manual(plan, self.profile)
            self._refresh_all()

    def _on_plan_edited(self) -> None:
        plan = self._selected_plan()
        if plan is not None:
            self._update_file_row(self.selected, plan)
        self._update_preview()
        self._update_stereo_panel_visibility()
        self._update_start_button()

    # ══ Stereo-Einstellungen ═════════════════════════════════════════════

    def _refresh_bitrates(self) -> None:
        info = OUTPUT_CODECS[self.stereo.codec]
        self.bitrate_cb.configure(values=info["bitrates"])
        if self.stereo.bitrate not in info["bitrates"]:
            self.stereo.bitrate = info["default_bitrate"]
        self.bitrate_cb.set(self.stereo.bitrate)

    def _on_stereo_changed(self, _event=None) -> None:
        self.stereo.codec = self._codec_by_label[self.codec_cb.get()]
        self._refresh_bitrates()
        self.stereo.bitrate = self.bitrate_cb.get()
        self.stereo.downmix_preset = self._preset_by_label[self.preset_cb.get()]
        self.stereo.track_name = self.trackname_var.get().strip() or "Stereo"
        self._update_preview()

    def _on_stereo_default_toggled(self) -> None:
        make_default = self.stereo_default_var.get()
        for plan in self.plans.values():
            if plan is None:
                continue
            stereo = plan.stereo_sources()
            if not stereo:
                continue
            if make_default:
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
        self.profile.output.directory = folder
        label = Path(folder).name if folder else "Quellordner"
        self.output_btn.configure(text=f"Ausgabe: {label}  ▾")
        for path, plan in self.plans.items():
            if plan is not None:
                plan.output_path = self.profile.output.output_path_for(path)
        self._update_preview()

    # ══ Start / Abbruch ══════════════════════════════════════════════════

    def _start(self) -> None:
        plans = [p for p in self.plans.values() if p is not None]
        if not plans:
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
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.runner = JobRunner(self.tools, self.ui_q, self.cancel)
        self._worker = threading.Thread(
            target=self.runner.run, args=(plans, self.stereo), daemon=True)
        self._worker.start()

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
                self._update_file_row(path, plan)
            if status is FileStatus.ERROR and error:
                self.log.set_expanded(True)
        elif kind == "SCANNED":
            path, media = msg[1], msg[2]
            plan = build_plan(media, self.profile)
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
            self.file_list.update_file(path, plan_text=error,
                                       status="Scan-Fehler", tag="error")
            self.log.log(f"{Path(path).name}: {error}", "error")
        elif kind == "TOOLS":
            self.tool_status = msg[1]
            self._update_tool_chips()
        elif kind == "BATCH_DONE":
            self._on_batch_done(msg[1], msg[2], msg[3])

    def _on_batch_done(self, success: int, total: int, cancelled: bool) -> None:
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
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

    # ══ Tools ════════════════════════════════════════════════════════════

    def _probe_tools(self) -> None:
        self.tools = toolchain.detect_tools(appconfig.base_path(),
                                            self.cfg.tools)
        self.ui_q.put(("TOOLS", toolchain.probe_all(self.tools)))

    def _update_tool_chips(self) -> None:
        for name, status in self.tool_status.items():
            chip = self.tool_chips[name]
            if status.ok:
                chip.configure(image=self._dot_ok,
                               text=f" {name} {status.version}")
            else:
                chip.configure(image=self._dot_bad, text=f" {name} fehlt")
        self._update_onboarding()

    def _update_onboarding(self) -> None:
        missing = (not self.tool_status
                   or any(not s.ok for s in self.tool_status.values()))
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

    def on_close(self) -> None:
        self.cfg.log_expanded = self.log.expanded
        appconfig.save(self.cfg)
