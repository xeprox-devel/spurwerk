"""Spurwerk-Theme „Nachtcyan“ + Checkbox-Grafiken.

Eine Farbquelle für alles: ttkbootstrap-Widgets, Checkbox-Images (Pillow),
Log-Tags und Status-Chips. Farbsemantik: Cyan ist exklusiv für „neu
erzeugt“ reserviert, Grün = behalten/verlustfrei, Rot = entfernen.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from PIL import Image, ImageDraw
from PIL.ImageTk import PhotoImage
from ttkbootstrap import utility
from ttkbootstrap.style import Style, ThemeDefinition

THEME_NAME = "spurwerk-dark"

# „Nachtcyan“: Akzent #22d3ee von ricardo-rehfeldt.de (--accent), Grund als
# cyan-getöntes Nachtblau statt neutralem Grau; Grün ist ein echtes Grün.
COLORS = {
    "primary":  "#22d3ee",   # Akzent-Cyan — exklusiv für „neu erzeugt“
    "secondary": "#44545e",
    "success":  "#22c55e",   # behalten / verlustfrei (richtiges Grün)
    "info":     "#22d3ee",   # bewusst = Akzent-Cyan: Lila/Indigo kommt in
                             # Spurwerk nicht vor (Nutzerentscheid) — auch
                             # ttkbootstrap-interne info-Verwendungen
                             # (Link-Hover, Fokusring) landen so auf der Linie
    "warning":  "#f59e0b",   # Amber wie auf der Webseite
    "danger":   "#ff5370",   # entfernen / Fehler
    "light":    "#a9bac4",
    "dark":     "#14212a",
    "bg":       "#0d151a",
    "fg":       "#e6edf2",
    "selectbg": "#0e4653",   # abgedunkeltes Cyan: Selektion + readonly-Felder
    "selectfg": "#ffffff",
    "border":   "#24333d",
    "inputfg":  "#e6edf2",
    "inputbg":  "#14212a",
    "active":   "#24333d",
}

# Zusatzfarben außerhalb des ttkbootstrap-Schemas
MUTED = "#5f717c"        # abgewählte Spuren, Nebentexte (von der Webseite)

# Dunkle Tinte auf der jeweiligen Füllfarbe (Checkbox-Glyphen)
INK_ON_SUCCESS = "#0b2c22"   # Häkchen auf Grün
INK_ON_PRIMARY = "#083344"   # Plus auf Cyan


def register(style: Style) -> None:
    """Registriert das Theme und aktiviert es."""
    style.register_theme(ThemeDefinition(THEME_NAME, COLORS, "dark"))
    style.theme_use(THEME_NAME)


def make_check_images(master: tk.Misc) -> dict[str, PhotoImage]:
    """Checkbox-Grafiken für die Spurtabelle, DPI-skaliert und theme-genau.

    Zustände: on (grün ✓ = behalten), stereo (cyan + = neu erzeugt),
    off (leer = abgewählt). Referenzen müssen gehalten werden!
    """
    size = utility.scale_size(master, 16)
    scale = 4  # supersampling gegen Treppchen

    def base(fill: str | None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [scale, scale, size * scale - scale, size * scale - scale],
            radius=3 * scale, width=2 * scale,
            outline=COLORS["border"], fill=fill)
        return img, draw

    def finish(img: Image.Image) -> PhotoImage:
        return PhotoImage(img.resize((size, size), Image.LANCZOS))

    s = size * scale
    images: dict[str, PhotoImage] = {}

    img, draw = base(COLORS["success"])
    draw.line([(s * .26, s * .52), (s * .44, s * .70), (s * .76, s * .30)],
              fill=INK_ON_SUCCESS, width=2 * scale)
    images["on"] = finish(img)

    img, draw = base(COLORS["primary"])
    draw.line([(s * .5, s * .28), (s * .5, s * .72)], fill=INK_ON_PRIMARY,
              width=2 * scale)
    draw.line([(s * .28, s * .5), (s * .72, s * .5)], fill=INK_ON_PRIMARY,
              width=2 * scale)
    images["stereo"] = finish(img)

    img, _ = base(None)
    images["off"] = finish(img)

    return images


def make_status_dot(master: tk.Misc, color: str) -> PhotoImage:
    """Kleiner runder Punkt für Status-Chips (Tools ok/fehlt, Dateistatus)."""
    size = utility.scale_size(master, 9)
    scale = 4
    img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([scale, scale, size * scale - scale, size * scale - scale],
                 fill=color)
    return PhotoImage(img.resize((size, size), Image.LANCZOS))


def apply_dark_titlebar(window: tk.Misc) -> None:
    """Windows-DWM-Hack: dunkle Titelleiste (Attribut 20, ältere Builds 19).

    Das Attribut sitzt am Fensterrahmen, den Tk erst beim ersten Anzeigen
    anlegt. Ein noch LEERES, nie gezeigtes Fenster (Hauptfenster: Aufruf vor
    dem Aufbau) bleibt dafür durchsichtig, bis das Start-Layout steht —
    sonst blitzt ein leeres Mini-Fenster auf, das nach dem Aufbau wächst und
    springt. Dialoge (schon gefüllt) wie bisher.
    """
    if sys.platform != "win32":
        return
    hidden = False
    try:
        hidden = (not window.winfo_ismapped()
                  and window.state() == "normal"
                  and not window.winfo_children())
        if hidden:
            # durchsichtig statt withdraw: Tk führt Größe/Position nur für
            # angezeigte Fenster nach — so zentriert das Start-Layout richtig
            window.attributes("-alpha", 0.0)
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value),
                    ctypes.sizeof(value)) == 0:
                break
    except (OSError, tk.TclError):
        pass
    if hidden:
        _show_after_first_layout(window)


def _show_after_first_layout(window: tk.Misc) -> None:
    """Macht das vorbereitete Fenster im ZWEITEN Timer-Durchlauf sichtbar:
    Der erste enthält das Start-Layout der App (after(0) — Größe, gemerkte
    Position, Zentrieren); danach erscheint das Fenster gleich fertig an
    seinem Platz."""
    def show() -> None:
        try:
            window.update_idletasks()   # ausstehende Geometrie zuerst
            window.attributes("-alpha", 1.0)
            _drop_layered_style(window)
        except (OSError, tk.TclError):
            pass   # Fenster schon geschlossen

    window.after(0, lambda: window.after(0, show))


def _drop_layered_style(window: tk.Misc) -> None:
    """Tk lässt nach „-alpha 1.0“ den Layered-Stil stehen; für ein wieder
    deckendes Fenster empfiehlt Microsoft, ihn zu entfernen und neu zu
    zeichnen — das Fenster ist danach wieder genau wie vorher."""
    gwl_exstyle, ws_ex_layered = -20, 0x00080000
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id())
    exstyle = user32.GetWindowLongW(hwnd, gwl_exstyle)
    if exstyle & ws_ex_layered:
        user32.SetWindowLongW(hwnd, gwl_exstyle, exstyle & ~ws_ex_layered)
        # RDW_ERASE | RDW_INVALIDATE | RDW_FRAME | RDW_ALLCHILDREN
        user32.RedrawWindow(hwnd, None, None, 0x4 | 0x1 | 0x400 | 0x80)
