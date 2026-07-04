"""Spurwerk-Theme „Nachtviolett" + Checkbox-Grafiken.

Eine Farbquelle für alles: ttkbootstrap-Widgets, Checkbox-Images (Pillow),
Log-Tags und Status-Chips. Farbsemantik: Violett ist exklusiv für „neu
erzeugt" reserviert, Grün = behalten/verlustfrei, Rot = entfernen.
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

COLORS = {
    "primary":  "#8b5cf6",   # Akzent-Violett — exklusiv für „neu erzeugt"
    "secondary": "#4a4458",
    "success":  "#2dd4a7",   # behalten / verlustfrei
    "info":     "#4aa8ff",
    "warning":  "#f5a623",
    "danger":   "#ff5370",   # entfernen / Fehler
    "light":    "#ada8bc",
    "dark":     "#1c1926",
    "bg":       "#14121a",
    "fg":       "#e9e6f2",
    "selectbg": "#3b2a63",   # abgedunkeltes Violett: Selektion + readonly-Felder
    "selectfg": "#ffffff",
    "border":   "#2c2838",
    "inputfg":  "#e9e6f2",
    "inputbg":  "#1c1926",
    "active":   "#2c2838",
}

# Zusatzfarben außerhalb des ttkbootstrap-Schemas
MUTED = "#6b6478"        # abgewählte Spuren, Nebentexte
SURFACE_ALT = "#211d2b"  # Zeilentrenner


def register(style: Style) -> None:
    """Registriert das Theme und aktiviert es."""
    style.register_theme(ThemeDefinition(THEME_NAME, COLORS, "dark"))
    style.theme_use(THEME_NAME)


def make_check_images(master: tk.Misc) -> dict[str, PhotoImage]:
    """Checkbox-Grafiken für die Spurtabelle, DPI-skaliert und theme-genau.

    Zustände: on (grün ✓ = behalten), stereo (violett + = neu erzeugt),
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
              fill="#0b2c22", width=2 * scale)
    images["on"] = finish(img)

    img, draw = base(COLORS["primary"])
    draw.line([(s * .5, s * .28), (s * .5, s * .72)], fill="#f5f3ff",
              width=2 * scale)
    draw.line([(s * .28, s * .5), (s * .72, s * .5)], fill="#f5f3ff",
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
    """Windows-DWM-Hack: dunkle Titelleiste (Attribut 20, ältere Builds 19)."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value),
                    ctypes.sizeof(value)) == 0:
                break
    except OSError:
        pass
