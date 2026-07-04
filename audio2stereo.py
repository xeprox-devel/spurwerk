import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
import subprocess
import json
import os
import shutil
import configparser
import threading
import queue
import sys

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# ─── Konstanten ───────────────────────────────────────────────────────────────

LANG_CODES = {
    "Deutsch":  ['ger', 'deu', 'de'],
    "Englisch": ['eng', 'en'],
    "Alle":     None,
}

CODEC_EXT = {
    'A_AC3':         '.ac3',
    'A_EAC3':        '.eac3',
    'A_DTS':         '.dts',
    'A_TRUEHD':      '.truehd',
    'A_AAC':         '.aac',
    'A_VORBIS':      '.ogg',
    'A_OPUS':        '.opus',
    'A_FLAC':        '.flac',
    'A_PCM_INT_LIT': '.wav',
    'A_PCM_INT_BIG': '.wav',
}

OUTPUT_CODECS = {
    "AC3 (Dolby Digital)":    {
        "codec": "ac3",  "ext": ".ac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k"],
        "default_br": "640k",
    },
    "E-AC3 (Dolby Digital+)": {
        "codec": "eac3", "ext": ".eac3",
        "bitrates": ["192k", "256k", "384k", "448k", "640k", "768k"],
        "default_br": "640k",
    },
    "AAC": {
        "codec": "aac",  "ext": ".m4a",
        "bitrates": ["128k", "160k", "192k", "256k", "320k"],
        "default_br": "256k",
    },
}

DOWNMIX_PRESETS = {
    "Loro (ITU Standard)":        "loro",
    "Pro Downmix + Kompressor":   "pro",
    "LFE-Boost":                  "lfeboost",
    "Passthrough (kein Downmix)": "passthrough",
}

# Pan-Filter für universellen Downmix (funktioniert für 5.1 und 7.1)
# Nicht vorhandene Kanäle werden von FFmpeg als 0 behandelt
_LORO_FILTER    = (
    "pan=stereo|"
    "FL=0.707*FC+0.707*FL+0.707*SL+0.707*BL+0.5*LFE|"
    "FR=0.707*FC+0.707*FR+0.707*SR+0.707*BR+0.5*LFE"
)
_PRO_FILTER     = (
    "pan=stereo|"
    "FL=1.414*FC+0.707*FL+0.5*BL+0.5*SL+0.5*LFE|"
    "FR=1.414*FC+0.707*FR+0.5*BR+0.5*SR+0.5*LFE,"
    "acompressor=ratio=4"
)
_LFEBOOST_FILTER = (
    "pan=stereo|"
    "FL=0.707*FL+0.707*FC+0.707*BL+0.5*LFE|"
    "FR=0.707*FR+0.707*FC+0.707*BR+0.5*LFE,"
    "volume=1.5"
)


# ─── Haupt-App ────────────────────────────────────────────────────────────────

class MKVConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MKV Audio Remuxer Pro  ·  by xeproX")
        self.root.geometry("1100x920")
        self.root.minsize(900, 720)

        try:
            self.root.iconbitmap(
                os.path.join(self._get_base_path(), "audio_logo.ico")
            )
        except Exception:
            pass

        # ── Instanzvariablen ──────────────────────────────────────────────────
        self.config_file   = os.path.join(self._get_base_path(), "config.ini")
        self._track_lock   = threading.Lock()
        self._cancel_flag  = threading.Event()
        self._active_proc  = None

        self.language_var  = ttk.StringVar(value="Deutsch")
        self.preset_var    = ttk.StringVar(value="Loro (ITU Standard)")
        self.codec_var     = ttk.StringVar(value="AC3 (Dolby Digital)")
        self.bitrate_var   = ttk.StringVar(value="640k")

        self.selected_track_var  = ttk.StringVar()
        self.track_map           = {}

        self.batch_files          = []
        self.batch_output_dir_var = ttk.StringVar()

        self.log_queue = queue.Queue()

        self._create_widgets()
        self._load_config()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.root.after(100, self._process_queue)

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    def _get_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _get_temp_dir(self):
        return os.path.join(self._get_base_path(), "temp_mkv_process")

    # ── Widget-Erstellung ─────────────────────────────────────────────────────

    def _create_widgets(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=6)

        self._create_tools_frame(main)
        self._create_settings_frame(main)
        self._create_notebook(main)
        self._create_convert_bar(main)
        self._create_progress_frame(main)
        self._create_log_frame(main)

    def _create_tools_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Tool-Pfade", padding=(10, 5))
        frame.pack(fill="x", pady=(0, 5))
        frame.columnconfigure(1, weight=1)

        self._tool_entries = {}
        tools = [
            ("mkvmerge.exe",   "mkvmerge"),
            ("mkvextract.exe", "mkvextract"),
            ("ffmpeg.exe",     "ffmpeg"),
            ("ffprobe.exe",    "ffprobe"),
        ]
        for row, (filename, key) in enumerate(tools):
            ttk.Label(frame, text=f"{filename}:").grid(
                row=row, column=0, sticky="w", padx=5, pady=3)
            entry = ttk.Entry(frame)
            entry.grid(row=row, column=1, sticky="ew", padx=5)
            ttk.Button(
                frame, text="...", width=4, bootstyle="secondary-outline",
                command=lambda e=entry, f=filename: self._select_tool(e, f),
            ).grid(row=row, column=2, padx=(0, 5))
            self._tool_entries[key] = entry

    def _create_settings_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Konvertierungseinstellungen", padding=(10, 5))
        frame.pack(fill="x", pady=(0, 5))

        r1 = ttk.Frame(frame)
        r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="Sprache:").pack(side="left", padx=(5, 2))
        lang_cb = ttk.Combobox(
            r1, textvariable=self.language_var,
            values=list(LANG_CODES.keys()), state="readonly", width=12)
        lang_cb.pack(side="left", padx=(0, 20))

        ttk.Label(r1, text="Downmix-Preset:").pack(side="left", padx=(0, 2))
        ttk.Combobox(
            r1, textvariable=self.preset_var,
            values=list(DOWNMIX_PRESETS.keys()), state="readonly", width=30,
        ).pack(side="left", padx=(0, 5))

        r2 = ttk.Frame(frame)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Ausgabe-Codec:").pack(side="left", padx=(5, 2))
        codec_cb = ttk.Combobox(
            r2, textvariable=self.codec_var,
            values=list(OUTPUT_CODECS.keys()), state="readonly", width=30)
        codec_cb.pack(side="left", padx=(0, 20))
        codec_cb.bind("<<ComboboxSelected>>", lambda _: self._update_bitrates())

        ttk.Label(r2, text="Bitrate:").pack(side="left", padx=(0, 2))
        self.bitrate_cb = ttk.Combobox(
            r2, textvariable=self.bitrate_var, state="readonly", width=10)
        self.bitrate_cb.pack(side="left")
        self._update_bitrates()

    def _update_bitrates(self):
        info = OUTPUT_CODECS[self.codec_var.get()]
        self.bitrate_cb['values'] = info['bitrates']
        if self.bitrate_var.get() not in info['bitrates']:
            self.bitrate_var.set(info['default_br'])

    def _create_notebook(self, parent):
        self.notebook = ttk.Notebook(parent, bootstyle="primary")
        self.notebook.pack(fill="x", pady=(0, 5))

        single_tab = ttk.Frame(self.notebook, padding=(10, 8))
        self.notebook.add(single_tab, text="  Einzeldatei  ")
        self._create_single_tab(single_tab)

        batch_tab = ttk.Frame(self.notebook, padding=(10, 8))
        self.notebook.add(batch_tab, text="  Batch  ")
        self._create_batch_tab(batch_tab)

    def _create_single_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Eingabedatei (.mkv):").grid(
            row=0, column=0, sticky="w", padx=5, pady=4)
        self.input_entry = ttk.Entry(parent)
        self.input_entry.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(
            parent, text="...", width=4, bootstyle="secondary-outline",
            command=self._select_input_file,
        ).grid(row=0, column=2, padx=(0, 5))

        ttk.Label(parent, text="Quell-Audiospur:").grid(
            row=1, column=0, sticky="w", padx=5, pady=4)
        self.track_combo = ttk.Combobox(
            parent, textvariable=self.selected_track_var, state="readonly")
        self.track_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5)

        ttk.Label(parent, text="Ausgabedatei (.mkv):").grid(
            row=2, column=0, sticky="w", padx=5, pady=4)
        self.output_entry = ttk.Entry(parent)
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=5)

        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=2, column=2, padx=(0, 5))
        ttk.Button(btn_frame, text="...", width=4, bootstyle="secondary-outline",
                   command=self._select_output_file).pack(side="left")
        ttk.Button(btn_frame, text="Auto", width=6, bootstyle="info-outline",
                   command=self._auto_output_path).pack(side="left", padx=2)

        # Trace: Sprachänderung → neu scannen
        self.language_var.trace_add("write", lambda *_: self._on_lang_changed())

    def _create_batch_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(parent)
        list_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.batch_listbox = tk.Listbox(
            list_frame, selectmode="extended",
            bg="#1a2533", fg="#d0e0f0", height=7,
            selectbackground="#375a7f", activestyle="none",
            relief="flat", font=("Consolas", 9),
        )
        self.batch_listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self.batch_listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.batch_listbox.config(yscrollcommand=sb.set)

        if DND_AVAILABLE:
            self.batch_listbox.drop_target_register(DND_FILES)
            self.batch_listbox.dnd_bind('<<Drop>>', self._on_batch_drop)
            ttk.Label(list_frame,
                      text="  MKV-Dateien hier hineinziehen oder Buttons verwenden",
                      bootstyle="secondary").grid(row=1, column=0, sticky="w")
        else:
            ttk.Label(list_frame,
                      text="  Dateien über Buttons hinzufügen (tkinterdnd2 nicht installiert)",
                      bootstyle="secondary").grid(row=1, column=0, sticky="w")

        btn_col = ttk.Frame(parent)
        btn_col.grid(row=0, column=1, sticky="n", padx=(8, 0))
        for text, cmd, style in [
            ("+ Dateien",   self._batch_add_files,    "primary-outline"),
            ("+ Ordner",    self._batch_add_folder,   "primary-outline"),
            ("↑ Nach oben", self._batch_move_up,      "secondary-outline"),
            ("↓ Nach unten",self._batch_move_down,    "secondary-outline"),
            ("− Entfernen", self._batch_remove_sel,   "danger-outline"),
            ("Alle löschen",self._batch_clear,        "danger-outline"),
        ]:
            ttk.Button(btn_col, text=text, width=13, bootstyle=style,
                       command=cmd).pack(pady=2, fill="x")

        out_frame = ttk.Frame(parent)
        out_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        out_frame.columnconfigure(1, weight=1)
        ttk.Label(out_frame, text="Ausgabeordner:").grid(
            row=0, column=0, sticky="w", padx=5)
        ttk.Entry(out_frame, textvariable=self.batch_output_dir_var).grid(
            row=0, column=1, sticky="ew", padx=5)
        ttk.Button(out_frame, text="...", width=4, bootstyle="secondary-outline",
                   command=self._select_batch_output_dir).grid(
            row=0, column=2, padx=(0, 5))
        ttk.Label(out_frame,
                  text="  (leer = gleicher Ordner wie die Quelldatei)",
                  bootstyle="secondary").grid(row=1, column=1, sticky="w", padx=5)

    def _create_convert_bar(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 4))

        self.convert_btn = ttk.Button(
            frame, text="▶  Konvertieren starten",
            command=self._run_conversion, bootstyle="success")
        self.convert_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.cancel_btn = ttk.Button(
            frame, text="⏹  Abbrechen",
            command=self._cancel_conversion,
            bootstyle="danger-outline", state="disabled")
        self.cancel_btn.pack(side="left", ipadx=10)

    def _create_progress_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Fortschritt", padding=(10, 4))
        frame.pack(fill="x", pady=(0, 4))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Aktuell:", width=8).grid(
            row=0, column=0, sticky="w", padx=5)
        self.progress_file = ttk.Progressbar(
            frame, maximum=100, bootstyle="info-striped")
        self.progress_file.grid(row=0, column=1, sticky="ew", padx=5, pady=3)
        self.lbl_file_pct = ttk.Label(frame, text="  0%", width=6)
        self.lbl_file_pct.grid(row=0, column=2, padx=(0, 5))

        ttk.Label(frame, text="Gesamt:", width=8).grid(
            row=1, column=0, sticky="w", padx=5)
        self.progress_total = ttk.Progressbar(
            frame, maximum=100, bootstyle="success-striped")
        self.progress_total.grid(row=1, column=1, sticky="ew", padx=5, pady=3)
        self.lbl_total_pct = ttk.Label(frame, text="  0%", width=6)
        self.lbl_total_pct.grid(row=1, column=2, padx=(0, 5))

        self.lbl_status = ttk.Label(frame, text="", bootstyle="secondary")
        self.lbl_status.grid(row=2, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 2))

    def _create_log_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Protokoll", padding=(5, 5))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            frame, wrap="word", height=14, state="disabled",
            bg="#1a2533", fg="#d0e0f0", relief="flat",
            font=("Consolas", 9), insertbackground="white")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        self.log_text.tag_config("error",   foreground="#e74c3c")
        self.log_text.tag_config("success", foreground="#2ecc71")
        self.log_text.tag_config("info",    foreground="#5dade2")
        self.log_text.tag_config("step",    foreground="#f0b429")
        self.log_text.tag_config("dim",     foreground="#7f8c8d")

        ttk.Button(frame, text="Log leeren", bootstyle="secondary-link",
                   command=self._clear_log).grid(row=1, column=0, sticky="e")

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, message, tag=None):
        self.log_text.config(state="normal")
        if tag:
            self.log_text.insert("end", message + "\n", tag)
        else:
            self.log_text.insert("end", message + "\n")
        self.log_text.yview("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _process_queue(self):
        try:
            for _ in range(30):  # max 30 Nachrichten pro Zyklus
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple):
                    kind = msg[0]
                    if kind == "LOG":
                        self._log(msg[1], msg[2] if len(msg) > 2 else None)
                    elif kind == "STATUS":
                        self.lbl_status.config(text=msg[1])
                    elif kind == "PROGRESS_FILE":
                        v = msg[1]
                        self.progress_file["value"] = v
                        self.lbl_file_pct.config(text=f"{v:3d}%")
                    elif kind == "PROGRESS_TOTAL":
                        v = msg[1]
                        self.progress_total["value"] = v
                        self.lbl_total_pct.config(text=f"{v:3d}%")
                    elif kind == "ERROR_DIALOG":
                        messagebox.showerror("Fehler", msg[1])
                elif msg == "START":
                    self.convert_btn.config(state="disabled")
                    self.cancel_btn.config(state="normal")
                    self.progress_file["value"] = 0
                    self.progress_total["value"] = 0
                    self.lbl_file_pct.config(text="  0%")
                    self.lbl_total_pct.config(text="  0%")
                elif msg == "FINISH":
                    self.convert_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
                elif msg == "SUCCESS":
                    messagebox.showinfo(
                        "Fertig", "Konvertierung erfolgreich abgeschlossen!")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    # ── Konfiguration ─────────────────────────────────────────────────────────

    def _load_config(self):
        cfg = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            cfg.read(self.config_file, encoding="utf-8")
            for key, entry in self._tool_entries.items():
                val = cfg.get("Pfade", key, fallback="")
                if val:
                    entry.insert(0, val)
            self.language_var.set(
                cfg.get("Einstellungen", "sprache", fallback="Deutsch"))
            self.preset_var.set(
                cfg.get("Einstellungen", "preset", fallback="Loro (ITU Standard)"))
            self.codec_var.set(
                cfg.get("Einstellungen", "codec", fallback="AC3 (Dolby Digital)"))
            self.bitrate_var.set(
                cfg.get("Einstellungen", "bitrate", fallback="640k"))
            self.batch_output_dir_var.set(
                cfg.get("Einstellungen", "batch_output_dir", fallback=""))
            self._update_bitrates()
            self._log("Konfiguration geladen.", "info")
            if not any(e.get() for e in self._tool_entries.values()):
                self._autodetect_tools()
        else:
            self._autodetect_tools()

    def _save_config(self):
        cfg = configparser.ConfigParser()
        cfg["Pfade"] = {k: e.get() for k, e in self._tool_entries.items()}
        cfg["Einstellungen"] = {
            "sprache":          self.language_var.get(),
            "preset":           self.preset_var.get(),
            "codec":            self.codec_var.get(),
            "bitrate":          self.bitrate_var.get(),
            "batch_output_dir": self.batch_output_dir_var.get(),
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            cfg.write(f)

    def _autodetect_tools(self):
        tools_dir = os.path.join(self._get_base_path(), "tools")
        found = 0
        for key, entry in self._tool_entries.items():
            candidate = os.path.join(tools_dir, f"{key}.exe")
            if os.path.exists(candidate):
                entry.delete(0, "end")
                entry.insert(0, candidate)
                found += 1
        if found:
            self._log(f"{found} Tools im 'tools'-Ordner automatisch gefunden.", "info")
        else:
            self._log(
                "Keine Tools gefunden. Bitte Pfade manuell konfigurieren.", "error")

    def _on_closing(self):
        self._save_config()
        self.root.destroy()

    # ── Datei-Auswahl ─────────────────────────────────────────────────────────

    def _select_tool(self, entry, filename):
        path = filedialog.askopenfilename(
            title=f"Wählen Sie '{filename}'",
            filetypes=[("Anwendung", "*.exe"), ("Alle Dateien", "*.*")])
        if path:
            if os.path.basename(path).lower() == filename.lower():
                entry.delete(0, "end")
                entry.insert(0, path)
            else:
                messagebox.showerror(
                    "Falsche Datei",
                    f"Erwartet: '{filename}'\nGewählt: '{os.path.basename(path)}'")

    def _select_input_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("MKV-Dateien", "*.mkv"), ("Alle Dateien", "*.*")])
        if path:
            self.input_entry.delete(0, "end")
            self.input_entry.insert(0, path)
            self._auto_output_path()
            self._scan_file(path)

    def _auto_output_path(self):
        inp = self.input_entry.get().strip()
        if not inp:
            return
        base, _ = os.path.splitext(inp)
        self.output_entry.delete(0, "end")
        self.output_entry.insert(0, base + "_stereo.mkv")

    def _select_output_file(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".mkv",
            filetypes=[("MKV-Dateien", "*.mkv"), ("Alle Dateien", "*.*")])
        if path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, path)

    def _select_batch_output_dir(self):
        path = filedialog.askdirectory(title="Ausgabeordner wählen")
        if path:
            self.batch_output_dir_var.set(path)

    # ── Batch-Verwaltung ──────────────────────────────────────────────────────

    def _batch_add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("MKV-Dateien", "*.mkv"), ("Alle Dateien", "*.*")])
        added = 0
        for p in paths:
            if p not in self.batch_files:
                self.batch_files.append(p)
                self.batch_listbox.insert("end", os.path.basename(p))
                added += 1
        if added:
            self._log(f"{added} Datei(en) zur Batch-Liste hinzugefügt.", "info")

    def _batch_add_folder(self):
        folder = filedialog.askdirectory(title="Ordner mit MKV-Dateien wählen")
        if not folder:
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".mkv"):
                full = os.path.join(folder, name)
                if full not in self.batch_files:
                    self.batch_files.append(full)
                    self.batch_listbox.insert("end", name)
                    added += 1
        self._log(
            f"{added} Datei(en) aus '{os.path.basename(folder)}' hinzugefügt.", "info")

    def _batch_remove_sel(self):
        sel = list(self.batch_listbox.curselection())
        for i in reversed(sel):
            self.batch_listbox.delete(i)
            del self.batch_files[i]

    def _batch_move_up(self):
        sel = list(self.batch_listbox.curselection())
        if not sel or sel[0] == 0:
            return
        for i in sel:
            if i == 0:
                continue
            text = self.batch_listbox.get(i)
            self.batch_listbox.delete(i)
            self.batch_listbox.insert(i - 1, text)
            self.batch_files[i], self.batch_files[i - 1] = (
                self.batch_files[i - 1], self.batch_files[i])
            self.batch_listbox.selection_set(i - 1)

    def _batch_move_down(self):
        sel = list(self.batch_listbox.curselection())
        if not sel or sel[-1] == self.batch_listbox.size() - 1:
            return
        for i in reversed(sel):
            if i == self.batch_listbox.size() - 1:
                continue
            text = self.batch_listbox.get(i)
            self.batch_listbox.delete(i)
            self.batch_listbox.insert(i + 1, text)
            self.batch_files[i], self.batch_files[i + 1] = (
                self.batch_files[i + 1], self.batch_files[i])
            self.batch_listbox.selection_set(i + 1)

    def _batch_clear(self):
        self.batch_files.clear()
        self.batch_listbox.delete(0, "end")

    def _on_batch_drop(self, event):
        import re
        matches = re.findall(r'\{([^}]+)\}|(\S+)', event.data)
        added = 0
        for m in matches:
            path = (m[0] or m[1]).strip()
            if path.lower().endswith(".mkv") and path not in self.batch_files:
                self.batch_files.append(path)
                self.batch_listbox.insert("end", os.path.basename(path))
                added += 1
        if added:
            self._log(f"{added} Datei(en) per Drag & Drop hinzugefügt.", "info")

    # ── Track-Scan ────────────────────────────────────────────────────────────

    def _on_lang_changed(self):
        inp = self.input_entry.get().strip()
        if inp and os.path.exists(inp):
            self._scan_file(inp)

    def _scan_file(self, file_path):
        mkvmerge = self._tool_entries["mkvmerge"].get().strip() or "mkvmerge"
        with self._track_lock:
            self.track_combo["values"] = []
            self.selected_track_var.set("Scanne...")
            self.track_map = {}

        def worker():
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(
                    [mkvmerge, "-J", file_path],
                    capture_output=True, text=True, check=True,
                    creationflags=flags, encoding="utf-8")
                info = json.loads(result.stdout)
                tracks = []
                for t in info.get("tracks", []):
                    if t["type"] == "audio":
                        tid   = t["id"]
                        lang  = t["properties"].get("language", "und")
                        codec = t["properties"].get("codec_id", "?")
                        ch    = t["properties"].get("audio_channels", "?")
                        name  = t["properties"].get("track_name", "")
                        label = (f"ID {tid}: [{lang}]  {codec}  {ch}ch"
                                 + (f"  '{name}'" if name else ""))
                        tracks.append(
                            {"label": label, "id": tid,
                             "lang": lang, "codec": codec})
                self.root.after(0, lambda: self._populate_tracks(tracks))
            except Exception as e:
                self.root.after(
                    0, lambda: self.selected_track_var.set(f"Scan-Fehler: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_tracks(self, tracks):
        with self._track_lock:
            labels = [t["label"] for t in tracks]
            self.track_combo["values"] = labels
            self.track_map = {t["label"]: t for t in tracks}

        pref   = self.language_var.get()
        codes  = LANG_CODES.get(pref)
        sel    = 0
        if codes:
            for i, t in enumerate(tracks):
                if t["lang"] in codes:
                    sel = i
                    break

        if tracks:
            self.track_combo.current(sel)
        else:
            self.selected_track_var.set("Keine Audiospuren gefunden")

    # ── Konvertierung starten ─────────────────────────────────────────────────

    def _get_tools(self):
        return {k: e.get().strip() for k, e in self._tool_entries.items()}

    def _validate_tools(self, tools):
        for key, path in tools.items():
            if not path:
                messagebox.showerror(
                    "Tool fehlt", f"Pfad für '{key}.exe' ist leer.")
                return False
            if not os.path.exists(path):
                messagebox.showerror(
                    "Tool nicht gefunden",
                    f"'{key}.exe' wurde nicht gefunden:\n{path}")
                return False
        return True

    def _run_conversion(self):
        self._clear_log()
        self._cancel_flag.clear()

        tools = self._get_tools()
        if not self._validate_tools(tools):
            return

        is_batch = self.notebook.index("current") == 1
        forced_track = None

        if is_batch:
            if not self.batch_files:
                messagebox.showerror("Fehler", "Keine Dateien in der Batch-Liste.")
                return
            files      = list(self.batch_files)
            output_dir = self.batch_output_dir_var.get().strip() or None
        else:
            inp = self.input_entry.get().strip()
            out = self.output_entry.get().strip()
            if not inp or not out:
                messagebox.showerror(
                    "Fehler", "Bitte Eingabe- und Ausgabedatei angeben.")
                return
            if not os.path.exists(inp):
                messagebox.showerror(
                    "Fehler", f"Eingabedatei nicht gefunden:\n{inp}")
                return
            files      = [(inp, out)]
            output_dir = None
            with self._track_lock:
                sel = self.selected_track_var.get()
                forced_track = self.track_map.get(sel)

        settings = {
            "tools":         tools,
            "preset":        DOWNMIX_PRESETS[self.preset_var.get()],
            "codec":         OUTPUT_CODECS[self.codec_var.get()],
            "bitrate":       self.bitrate_var.get(),
            "lang":          self.language_var.get(),
            "forced_track":  forced_track,
        }

        self.log_queue.put("START")
        threading.Thread(
            target=self._batch_worker,
            args=(files, output_dir, settings, is_batch),
            daemon=True,
        ).start()

    def _cancel_conversion(self):
        self._cancel_flag.set()
        proc = self._active_proc
        if proc and proc.poll() is None:
            proc.terminate()
        self.log_queue.put(("LOG", "Abbruch wurde angefordert...", "error"))

    # ── Batch-Worker ──────────────────────────────────────────────────────────

    def _batch_worker(self, files, output_dir, settings, is_batch):
        total   = len(files)
        success = 0

        for idx, item in enumerate(files):
            if self._cancel_flag.is_set():
                self.log_queue.put(("LOG", "Konvertierung abgebrochen.", "error"))
                break

            if is_batch:
                inp     = item
                base    = os.path.splitext(os.path.basename(inp))[0]
                out_dir = output_dir or os.path.dirname(inp)
                out     = os.path.join(out_dir, base + "_stereo.mkv")
            else:
                inp, out = item

            total_pct = int(idx / total * 100)
            self.log_queue.put(("PROGRESS_TOTAL", total_pct))
            self.log_queue.put(("LOG", f"\n{'─' * 62}", "dim"))
            self.log_queue.put((
                "LOG",
                f"Datei {idx + 1}/{total}: {os.path.basename(inp)}", "step"))
            self.log_queue.put((
                "STATUS",
                f"Verarbeite {idx + 1}/{total}: {os.path.basename(inp)}"))

            ok = self._convert_single(inp, out, settings)
            if ok:
                success += 1

        self.log_queue.put(("PROGRESS_FILE",  100))
        self.log_queue.put(("PROGRESS_TOTAL", 100))
        self.log_queue.put(("LOG", f"\n{'─' * 62}", "dim"))

        if not self._cancel_flag.is_set():
            if success == total:
                msg = (f"Alle {total} Datei(en) erfolgreich konvertiert."
                       if total > 1 else "Konvertierung erfolgreich.")
                self.log_queue.put(("LOG", msg, "success"))
                self.log_queue.put("SUCCESS")
            else:
                self.log_queue.put((
                    "LOG",
                    f"{success}/{total} erfolgreich, "
                    f"{total - success} fehlgeschlagen.", "error"))
                self.log_queue.put(("ERROR_DIALOG",
                    f"{success}/{total} Dateien konnten konvertiert werden.\n"
                    f"{total - success} fehlgeschlagen. Siehe Protokoll."))

        self.log_queue.put(("STATUS", ""))
        self.log_queue.put("FINISH")

    # ── Einzelkonvertierung ───────────────────────────────────────────────────

    def _convert_single(self, input_path, output_path, settings):
        tools         = settings["tools"]
        preset        = settings["preset"]
        codec_info    = settings["codec"]
        bitrate       = settings["bitrate"]
        lang          = settings["lang"]
        forced_track  = settings["forced_track"]

        temp_dir = self._get_temp_dir()
        success  = False
        step_n   = [0]

        def step(msg):
            step_n[0] += 1
            self.log_queue.put(("LOG", f"  [{step_n[0]}] {msg}", "step"))

        def info(msg):
            self.log_queue.put(("LOG", f"      {msg}"))

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        try:
            os.makedirs(temp_dir, exist_ok=True)

            # ── Schritt 1: MKV analysieren ────────────────────────────────
            step("Analysiere MKV-Spuren...")
            result = subprocess.run(
                [tools["mkvmerge"], "-J", input_path],
                capture_output=True, text=True, check=True,
                creationflags=flags, encoding="utf-8")
            mkv_info = json.loads(result.stdout)

            video_id    = None
            audio_id    = None
            audio_codec = None
            sub_ids     = []
            lang_codes  = LANG_CODES.get(lang)

            for t in mkv_info.get("tracks", []):
                tid   = str(t["id"])
                ttyp  = t["type"]
                tlng  = t["properties"].get("language", "und")

                if ttyp == "video" and video_id is None:
                    video_id = tid

                elif ttyp == "audio" and audio_id is None:
                    if forced_track is not None:
                        if str(forced_track["id"]) == tid:
                            audio_id    = tid
                            audio_codec = forced_track["codec"]
                    else:
                        if lang_codes is None or tlng in lang_codes:
                            audio_id    = tid
                            audio_codec = t["properties"].get("codec_id", "A_AC3")

                elif ttyp == "subtitles":
                    if lang_codes is None or tlng in lang_codes:
                        sub_ids.append(tid)

            if not video_id:
                raise ValueError("Keine Videospur in der Datei gefunden.")
            if not audio_id:
                # Fallback: erste verfügbare Audiospur
                for t in mkv_info.get("tracks", []):
                    if t["type"] == "audio":
                        audio_id    = str(t["id"])
                        audio_codec = t["properties"].get("codec_id", "A_AC3")
                        info(f"Warnung: Keine Spur für '{lang}' → nutze erste "
                             f"verfügbare Spur (ID {audio_id}).")
                        break
                if not audio_id:
                    raise ValueError("Keine Audiospur in der Datei gefunden.")

            chapters = bool(mkv_info.get("chapters"))
            info(f"Video: ID {video_id}  |  Audio: ID {audio_id} ({audio_codec})"
                 f"  |  Subs: {', '.join(sub_ids) or '–'}"
                 f"  |  Kapitel: {'ja' if chapters else 'nein'}")

            # ── Schritt 2: Audio extrahieren ──────────────────────────────
            step("Extrahiere Audiospur...")
            ext        = CODEC_EXT.get(audio_codec, ".bin")
            temp_audio = os.path.join(temp_dir, f"audio{ext}")

            subprocess.run(
                [tools["mkvextract"], "tracks", input_path,
                 f"{audio_id}:{temp_audio}"],
                check=True, creationflags=flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # ── Schritt 3: Audioformat analysieren (ffprobe) ──────────────
            step("Analysiere Audioformat (ffprobe)...")
            probe = subprocess.run(
                [tools["ffprobe"], "-v", "quiet",
                 "-print_format", "json",
                 "-show_streams", "-show_format",
                 temp_audio],
                capture_output=True, text=True, check=True,
                creationflags=flags, encoding="utf-8")
            probe_data = json.loads(probe.stdout)
            streams    = probe_data.get("streams", [])

            if not streams:
                raise ValueError(
                    "ffprobe konnte keinen Stream in der Audiodatei finden.")

            audio_stream = streams[0]
            channels     = audio_stream.get("channels", 2)
            codec_name   = audio_stream.get("codec_name", "?").upper()
            duration_s   = float(
                probe_data.get("format", {}).get("duration", 0)
                or audio_stream.get("duration", 0)
                or 0)

            info(f"Format: {codec_name}  |  Kanäle: {channels}"
                 f"  |  Dauer: {duration_s:.1f}s")

            # ── Schritt 4: FFmpeg – Konvertierung ─────────────────────────
            target_codec = codec_info["codec"].upper()
            step(f"Konvertiere → {target_codec} {bitrate} Stereo "
                 f"(Preset: {preset})...")

            temp_stereo  = os.path.join(temp_dir, f"stereo{codec_info['ext']}")
            ffmpeg_cmd   = self._build_ffmpeg_cmd(
                tools["ffmpeg"], temp_audio, temp_stereo,
                channels, preset, codec_info, bitrate)

            self._run_ffmpeg_with_progress(ffmpeg_cmd, duration_s, flags)
            info("Audiokonvertierung abgeschlossen.")

            # ── Schritt 5: MKV zusammenfügen ──────────────────────────────
            step("Füge MKV zusammen (mkvmerge)...")
            merge_cmd = [
                tools["mkvmerge"], "-o", output_path,
                "--video-tracks", video_id,
            ]
            if sub_ids:
                merge_cmd.extend(["--subtitle-tracks", ",".join(sub_ids)])
            else:
                merge_cmd.append("--no-subtitles")
            if not chapters:
                merge_cmd.append("--no-chapters")

            merge_cmd.extend(["--no-audio", input_path])

            out_lang = {"Deutsch": "ger", "Englisch": "eng"}.get(lang, "und")
            merge_cmd.extend([
                "--language",      f"0:{out_lang}",
                "--track-name",    f"0:Stereo {target_codec}",
                "--default-track", "0:yes",
                temp_stereo,
            ])

            mux_result = subprocess.run(
                merge_cmd, capture_output=True, text=True,
                creationflags=flags, encoding="utf-8")
            # mkvmerge gibt Exit-Code 1 als Warnung zurück, 2 = Fehler
            if mux_result.returncode >= 2:
                raise subprocess.CalledProcessError(
                    mux_result.returncode, merge_cmd, stderr=mux_result.stderr)
            if mux_result.returncode == 1:
                info(f"mkvmerge Warnung: {mux_result.stderr.strip()[:200]}")

            info(f"Ausgabe: {output_path}")
            success = True

        except (subprocess.CalledProcessError, ValueError,
                json.JSONDecodeError, OSError) as e:
            msg = str(e)
            self.log_queue.put(("LOG", f"      FEHLER: {msg}", "error"))
            if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                stderr = (e.stderr if isinstance(e.stderr, str)
                          else e.stderr.decode("utf-8", errors="ignore"))
                if stderr.strip():
                    self.log_queue.put((
                        "LOG",
                        f"      stderr: {stderr.strip()[:600]}", "error"))
            # Unvollständige Ausgabedatei entfernen
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    self.log_queue.put((
                        "LOG", "      Unvollständige Ausgabedatei gelöscht.", "info"))
                except OSError:
                    pass
        finally:
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

        return success

    # ── FFmpeg-Kommando aufbauen ───────────────────────────────────────────────

    def _build_ffmpeg_cmd(self, ffmpeg_exe, src, dst,
                          channels, preset, codec_info, bitrate):
        c   = codec_info["codec"]
        cmd = [ffmpeg_exe, "-y", "-i", src,
               "-progress", "pipe:1", "-nostats"]

        needs_downmix = channels > 2

        if not needs_downmix or preset == "passthrough":
            # Bereits Stereo oder kein Downmix gewünscht
            cmd.extend(["-c:a", c, "-b:a", bitrate, "-ac", "2"])

        elif preset == "loro" and c == "ac3":
            # Nativer AC3-Encoder-Downmix (höchste Qualität für AC3)
            cmd.extend([
                "-dmix_mode",     "loro",
                "-loro_cmixlev",  "0.707",
                "-loro_surmixlev","0.707",
                "-c:a", c, "-b:a", bitrate,
            ])

        elif preset == "loro":
            # Loro-Filter für andere Codecs (AAC, EAC3)
            cmd.extend(["-af", _LORO_FILTER, "-c:a", c, "-b:a", bitrate])

        elif preset == "pro":
            cmd.extend(["-filter_complex", _PRO_FILTER,
                        "-c:a", c, "-b:a", bitrate])

        elif preset == "lfeboost":
            cmd.extend(["-af", _LFEBOOST_FILTER,
                        "-c:a", c, "-b:a", bitrate])

        else:
            cmd.extend(["-af", _LORO_FILTER, "-c:a", c, "-b:a", bitrate])

        cmd.append(dst)
        return cmd

    # ── FFmpeg ausführen + Fortschritt lesen ─────────────────────────────────

    def _run_ffmpeg_with_progress(self, cmd, duration_s, flags):
        self.log_queue.put(("PROGRESS_FILE", 0))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            text=True, encoding="utf-8", errors="ignore",
        )
        self._active_proc = proc

        try:
            for line in proc.stdout:
                if self._cancel_flag.is_set():
                    proc.terminate()
                    break
                line = line.strip()
                if line.startswith("out_time_ms=") and duration_s > 0:
                    val = line.split("=", 1)[1]
                    if val not in ("N/A", ""):
                        try:
                            elapsed_us = int(val)
                            pct = min(
                                99,
                                int(elapsed_us / (duration_s * 1_000_000) * 100))
                            self.log_queue.put(("PROGRESS_FILE", pct))
                        except ValueError:
                            pass
            proc.wait()
        finally:
            self._active_proc = None

        if proc.returncode != 0 and not self._cancel_flag.is_set():
            stderr_data = proc.stderr.read() if proc.stderr else ""
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, stderr=stderr_data)

        self.log_queue.put(("PROGRESS_FILE", 100))


# ─── Einstiegspunkt ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
        ttk.Style(theme="darkly")
    else:
        root = ttk.Window(themename="darkly")

    app = MKVConverterApp(root)
    root.mainloop()
