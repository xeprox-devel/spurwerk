"""App-Shell: Fenster, Theme, Drag&Drop, automatische Fenstergröße."""

from __future__ import annotations

import sys
from pathlib import Path

import ttkbootstrap as ttk

import config as appconfig
from ui import theme
from ui.drop import load_tkdnd, mkv_paths, split_drop_data
from ui.geometry import (Frame, Rect, centered, clamp_geometry, client_limit,
                         default_frame, inside, monitor_areas,
                         monitor_work_area, restored_width, split_geometry,
                         visible_bounds)
from ui.main_window import MainWindow
from version import APP_NAME, __version__

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    from tkinterdnd2.TkinterDnD import DnDWrapper
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

    class DnDWrapper:  # Fallback ohne Drag&Drop
        pass


class SpurwerkApp(ttk.Window, DnDWrapper):
    """tb.Window + DnDWrapper — exakt das Muster von TkinterDnD.Tk,
    nur mit ttkbootstrap.Window (HiDPI, Theme, place_window_center)."""

    def __init__(self) -> None:
        super().__init__(title=f"{APP_NAME} {__version__}",
                         themename="darkly", iconphoto=None, hdpi=True)
        theme.register(self.style)
        theme.apply_dark_titlebar(self)
        self._set_icon()

        self._auto_size: tuple[int, int] | None = None
        self._user_resized = False
        self._mapped = False
        self._min_size: tuple[int, int] | None = None   # zuletzt gesetzt
        self._frame = default_frame()     # sichtbarer Rahmen (gemessen)
        self._fit_after: str | None = None   # after_idle der Höhenverteilung
        # selbst gesetzte Größen, deren <Configure> noch aussteht — mehrere
        # Anpassungen kurz hintereinander (eine je eingelesener Datei) sind
        # so kein Nutzer-Resize, auch wenn ihre Ereignisse spät eintreffen
        self._own_sizes: set[tuple[int, int]] = set()

        # tkinterdnd2 importierbar heißt nicht, dass tkdnd lädt (0.4/0.5
        # unter Tcl 9) — dann ohne Drag&Drop starten statt abstürzen
        self._dnd_ok = DND_AVAILABLE and load_tkdnd(self, TkinterDnD._require)

        self.cfg = appconfig.load()
        # erst nach dem Aufbau gesetzt — bis dahin misst autosize() nichts
        self.main: MainWindow | None = None
        self.main = MainWindow(self, self.cfg, dnd_ok=self._dnd_ok)
        self.main.pack(fill="both", expand=True)

        if self._dnd_ok:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)
        self.after(0, self._first_layout)

    # ── Fenstergröße ──────────────────────────────────────────────────────
    # Tk-Größen meinen den Client-Bereich. Das Fenster ist nie kleiner als
    # das Minimum des Gezeigten (MainWindow.measure) und nie größer als der
    # Arbeitsbereich seines Monitors (ohne Taskleiste). Ist der kleiner als
    # das Minimum, gewinnt er — die Höhenverteilung greift dann zum letzten
    # Ausweg (ui/layout.py). Die Höhe innen verteilt MainWindow.fit: nach
    # jedem Strukturwechsel (autosize) und nach jeder Größenänderung
    # (<Configure>, entprellt).

    def _first_layout(self) -> None:
        needs = self.main.measure()
        vx, vy, vw, vh = self._virtual_screen()
        saved = clamp_geometry(self.cfg.window_geometry, vw, vh,
                               min_w=needs.min_w, min_h=needs.min_h,
                               screen_x=vx, screen_y=vy)
        if saved:
            # Gemerkte Größe/Position gewinnt über die Auto-Größe — begrenzt
            # auf den Arbeitsbereich ihres Monitors (nach einem
            # Monitorwechsel läge der Start-Knopf sonst unter der Taskleiste);
            # nur ein bewusst über mehrere Monitore gezogenes Fenster behält
            # seine Breite. Alles vorab rechnen und EINMAL setzen: eine
            # zweite Lage im selben Durchlauf überschriebe Windows mit der
            # Meldung der ersten.
            self._user_resized = True
            self._auto_size = None
            w, h, x, y = split_geometry(saved)
            near = Rect(x, y, w, h)
            work, frame = self._work_area(near=near), self._measure_frame()
            min_w, min_h = self._apply_minsize(needs, work, frame)
            w = max(min_w, restored_width(w, self._monitor_area(near=near),
                                          work, frame))
            if self.main.wrap_warning(w):
                needs = self.main.measure()
                min_w, min_h = self._apply_minsize(needs, work, frame)
            h = max(min_h, min(h, client_limit(work, frame)[1]))
            self._set_geometry(w, h, *inside(x, y, w, h, work, frame))
            self.main.fit(h)
        else:
            self.autosize(allow_shrink=True)
            self._center()
        # sofort anwenden (das Fenster ist noch durchsichtig): bliebe die
        # Lage bis zum Leerlauf liegen, überschriebe sie eine späte
        # Positionsmeldung vom ersten Anzeigen des Fensters
        self.update_idletasks()
        if self.cfg.window_zoomed:
            # Maximiert wiederherstellen — Auto-Size bleibt dabei außen vor
            self._user_resized = True
            self._auto_size = None
            self.state("zoomed")
        # Nutzer-Resize erst ab jetzt erkennen: Tk liefert die <Configure>-
        # Ereignisse aus dem Aufbau (Fenster folgte seinem Inhalt) erst nach
        # diesem Durchlauf aus — after_idle läuft, wenn keine mehr anstehen
        self.after_idle(self._set_mapped)

    def _set_mapped(self) -> None:
        self._mapped = True

    def _virtual_screen(self) -> tuple[int, int, int, int]:
        """Virtueller Desktop (alle Monitore): (x, y, w, h). Der Ursprung
        kann negativ sein (Zweitmonitor links/oben vom Primärmonitor).
        Fallback: Primärmonitor mit Ursprung (0, 0)."""
        if sys.platform == "win32":
            try:
                import ctypes
                metrics = ctypes.windll.user32.GetSystemMetrics
                x, y = metrics(76), metrics(77)   # SM_X/YVIRTUALSCREEN
                w, h = metrics(78), metrics(79)   # SM_CX/CYVIRTUALSCREEN
                if w > 0 and h > 0:
                    return x, y, w, h
            except OSError:
                pass
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def _hwnd(self) -> int:
        """Das echte Windows-Fenster: Tk legt um den Toplevel einen Rahmen."""
        if sys.platform != "win32":
            return 0
        import ctypes
        return ctypes.windll.user32.GetParent(self.winfo_id())

    def _work_area(self, near: Rect | None = None) -> Rect:
        """Arbeitsbereich (ohne Taskleiste) des Monitors, auf dem das Fenster
        — bzw. das Rechteck `near` — größtenteils liegt; Fallback: der ganze
        Bildschirm."""
        return (monitor_work_area(self._hwnd(), near)
                or Rect(0, 0, self.winfo_screenwidth(),
                        self.winfo_screenheight()))

    def _monitor_area(self, near: Rect | None = None) -> Rect:
        """Der ganze Monitor (samt Taskleiste) zu _work_area; Fallback: sein
        Arbeitsbereich."""
        areas = monitor_areas(self._hwnd(), near)
        return areas[0] if areas else self._work_area(near)

    def _measure_frame(self) -> Frame:
        """Sichtbaren Fensterrahmen messen (Titelleiste, Ränder, unsichtbare
        Greifränder) — nur im Normalzustand; sonst gilt der zuletzt
        gemessene bzw. die Schätzung aus den Systemmetriken."""
        if not (self.winfo_ismapped() and self.state() == "normal"):
            return self._frame
        bounds = visible_bounds(self._hwnd())
        if bounds is None:
            return self._frame
        x, y = self.winfo_rootx(), self.winfo_rooty()
        frame = Frame(left=x - bounds.x, top=y - bounds.y,
                      right=bounds.x + bounds.w - x - self.winfo_width(),
                      bottom=bounds.y + bounds.h - y - self.winfo_height(),
                      dx=bounds.x - self.winfo_x(),
                      dy=bounds.y - self.winfo_y())
        if all(0 <= v <= 200 for v in vars(frame).values()):   # plausibel
            self._frame = frame
        return self._frame

    def _apply_minsize(self, needs, work: Rect,
                       frame: Frame) -> tuple[int, int]:
        """Mindestgröße = Minimum des Gezeigten, gedeckelt durch den
        Arbeitsbereich; gesetzt nur bei Änderung."""
        lim_w, lim_h = client_limit(work, frame)
        size = (min(needs.min_w, lim_w), min(needs.min_h, lim_h))
        if size != self._min_size:
            self._min_size = size
            self.minsize(*size)
        return size

    def _resize(self, w: int, h: int, work: Rect, frame: Frame,
                move: bool = False) -> None:
        """Größe setzen — das Fenster rückt dabei so, dass sein sichtbarer
        Rahmen im Arbeitsbereich bleibt. Die Lage eines Fensters, dessen
        Größe bleibt, rührt das nur mit move=True an."""
        x, y = self.winfo_x(), self.winfo_y()
        size_changed = (w, h) != (self.winfo_width(), self.winfo_height())
        if not (size_changed or move):
            return
        nx, ny = inside(x, y, w, h, work, frame)
        if size_changed or (nx, ny) != (x, y):
            self._set_geometry(w, h, nx, ny)

    def _set_geometry(self, w: int, h: int, x: int, y: int) -> None:
        self._own_sizes.add((w, h))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _center(self) -> None:
        """Im Arbeitsbereich des Monitors zentrieren — nicht auf dem ganzen
        Bildschirm, sonst läge ein hohes Fenster unter der Taskleiste. Setzt
        die Größe mit: ab hier folgt das Fenster nie mehr von selbst seinem
        Inhalt (sonst wüchse es an Arbeitsbereich und Minimum vorbei)."""
        w, h = self._auto_size or (self.winfo_width(), self.winfo_height())
        x, y = centered(w, h, self._work_area(), self._measure_frame())
        self._set_geometry(w, h, x, y)

    def autosize(self, allow_shrink: bool = False) -> None:
        """Fenster an den Inhalt anpassen — wächst automatisch, schrumpft nur
        beim Rückfall in den Leerzustand; Nutzer-Resize gewinnt immer, wird
        aber aufs Minimum angehoben. Danach die Höhe innen verteilen."""
        if self.main is None:
            return                  # noch im Aufbau — _first_layout folgt
        if self._fit_after is not None:   # erledigt dieser Durchlauf mit
            self.after_cancel(self._fit_after)
            self._fit_after = None
        needs = self.main.measure()
        work, frame = self._work_area(), self._measure_frame()
        min_w, min_h = self._apply_minsize(needs, work, frame)
        cur_w, cur_h = self.winfo_width(), self.winfo_height()
        zoomed = self.state() == "zoomed"
        auto = not (zoomed or self._user_resized)
        lim_w, lim_h = client_limit(work, frame)
        # erst die Breite: sie bestimmt, wie hoch der umbrochene Hinweis
        # unter der Spurtabelle ist — und damit die Höhen
        if zoomed:
            w = cur_w               # maximiert: die Größe gibt Windows vor
        elif auto:
            w = min(max(needs.natural_w, min_w),
                    max(min_w, int(lim_w * 0.92)))
            if self._mapped and not allow_shrink:
                w = max(w, cur_w)
        else:
            w = max(cur_w, min_w)
        if self.main.wrap_warning(w):
            needs = self.main.measure()
            min_w, min_h = self._apply_minsize(needs, work, frame)
        if zoomed:
            h = cur_h
        elif auto:
            h = min(max(needs.natural_h, min_h), lim_h)
            if self._mapped and not allow_shrink:
                h = max(h, cur_h)
            self._auto_size = (w, h)
        else:
            h = max(cur_h, min_h)
        self._resize(w, h, work, frame)
        # mit der Zielhöhe verteilen — noch vor dem nächsten Zeichnen
        self.main.fit(h)

    def _on_configure(self, event) -> None:
        if event.widget is not self:
            return
        size = (event.width, event.height)
        if self._user_resized or size == self._auto_size:
            self._own_sizes.clear()     # die letzte eigene Größe ist da
        elif (self._mapped and self._auto_size is not None
                and size not in self._own_sizes):
            dw = abs(event.width - self._auto_size[0])
            dh = abs(event.height - self._auto_size[1])
            if dw > 24 or dh > 24:
                self._user_resized = True
        # Höhe neu verteilen — entprellt: einmal je Leerlauf
        if self._fit_after is None:
            self._fit_after = self.after_idle(self._fit)

    def _fit(self) -> None:
        """Nach einer Größenänderung (Nutzer, Maximieren, Monitorwechsel):
        Mindestgröße für den aktuellen Monitor prüfen, Höhe verteilen."""
        self._fit_after = None
        if self.main is None or not self._mapped:
            return
        if self.main.wrap_warning(self.winfo_width()):
            # andere Breite → Hinweis bricht anders um, braucht andere Höhe:
            # neu messen (Mindestgröße, ggf. aufs Minimum anheben), verteilen
            self.autosize()
            return
        self._apply_minsize(self.main.needs(), self._work_area(),
                            self._measure_frame())
        self.main.fit(self.winfo_height())

    # ── Drag & Drop ───────────────────────────────────────────────────────

    def _on_drop(self, event) -> None:
        # event.data ist eine Tcl-Liste → Tcls eigener Parser, kein Regex
        # (sonst zerfallen Namen mit „{imdb-tt…}“ stillschweigend)
        items = split_drop_data(event.data, self.tk.splitlist)
        files, skipped = mkv_paths(items)
        if files:
            self.main.add_files(files)
        if skipped:
            # Rückmeldung statt stillem Verwerfen (z. B. .mp4, leerer Ordner)
            names = ", ".join(Path(p).name or p for p in skipped[:3])
            more = f" (+{len(skipped) - 3} weitere)" if len(skipped) > 3 else ""
            self.main.log.log(
                f"Übersprungen (keine MKV-Datei): {names}{more}", "warn")

    # ── Sonstiges ─────────────────────────────────────────────────────────

    def _set_icon(self) -> None:
        # Im PyInstaller-Onefile-Build liegen eingebettete Dateien unter
        # sys._MEIPASS — NICHT neben der EXE (deshalb fehlte das Fenster-Icon)
        base = Path(getattr(sys, "_MEIPASS", appconfig.base_path()))
        icon = base / "spurwerk.ico"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except Exception:
                pass

    def _on_close(self) -> None:
        if self.main.on_close():
            self.destroy()

    def destroy(self) -> None:
        # keine Höhenverteilung mehr nach dem Schließen
        if getattr(self, "_fit_after", None) is not None:
            self.after_cancel(self._fit_after)
            self._fit_after = None
        super().destroy()
