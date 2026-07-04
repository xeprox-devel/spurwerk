"""App-Shell: Fenster, Theme, Drag&Drop, automatische Fenstergröße."""

from __future__ import annotations

import re
from pathlib import Path

import ttkbootstrap as ttk

import config as appconfig
from ui import theme
from ui.main_window import MainWindow

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    from tkinterdnd2.TkinterDnD import DnDWrapper
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

    class DnDWrapper:  # Fallback ohne Drag&Drop
        pass

_DROP_RE = re.compile(r"\{([^}]+)\}|(\S+)")


class SpurwerkApp(ttk.Window, DnDWrapper):
    """tb.Window + DnDWrapper — exakt das Muster von TkinterDnD.Tk,
    nur mit ttkbootstrap.Window (HiDPI, Theme, place_window_center)."""

    def __init__(self) -> None:
        super().__init__(title="Spurwerk", themename="darkly",
                         iconphoto=None, hdpi=True)
        theme.register(self.style)
        theme.apply_dark_titlebar(self)
        self._set_icon()

        self._auto_size: tuple[int, int] | None = None
        self._user_resized = False
        self._mapped = False

        if DND_AVAILABLE:
            self.TkdndVersion = TkinterDnD._require(self)

        self.cfg = appconfig.load()
        self.main = MainWindow(self, self.cfg)
        self.main.pack(fill="both", expand=True)

        if DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)
        self.after(0, self._first_layout)

    # ── Fenstergröße ──────────────────────────────────────────────────────

    def _first_layout(self) -> None:
        self.autosize(allow_shrink=True)
        self.place_window_center()
        self._mapped = True

    def autosize(self, allow_shrink: bool = False) -> None:
        """Fenster an den Inhalt anpassen — wächst automatisch, schrumpft nur
        beim Rückfall in den Leerzustand; Nutzer-Resize gewinnt immer."""
        if self._user_resized:
            return
        self.update_idletasks()
        req_w, req_h = self.winfo_reqwidth(), self.winfo_reqheight()
        scr_w, scr_h = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(max(req_w, 900), int(scr_w * 0.92))
        h = min(max(req_h, 420), int(scr_h * 0.90))
        if self._mapped and not allow_shrink:
            w = max(w, self.winfo_width())
            h = max(h, self.winfo_height())
        if (w, h) != (self.winfo_width(), self.winfo_height()):
            self.geometry(f"{w}x{h}")
        self._auto_size = (w, h)
        self.minsize(min(900, w), min(420, h))

    def _on_configure(self, event) -> None:
        if (event.widget is self and self._mapped
                and self._auto_size is not None):
            dw = abs(event.width - self._auto_size[0])
            dh = abs(event.height - self._auto_size[1])
            if dw > 24 or dh > 24:
                self._user_resized = True

    # ── Drag & Drop ───────────────────────────────────────────────────────

    def _on_drop(self, event) -> None:
        paths = [(m[0] or m[1]).strip()
                 for m in _DROP_RE.findall(event.data)]
        files: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                files += sorted(str(f) for f in path.glob("*.mkv"))
            elif p.lower().endswith(".mkv"):
                files.append(p)
        if files:
            self.main.add_files(files)

    # ── Sonstiges ─────────────────────────────────────────────────────────

    def _set_icon(self) -> None:
        icon = appconfig.base_path() / "audio_logo.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass

    def _on_close(self) -> None:
        if self.main.on_close():
            self.destroy()
