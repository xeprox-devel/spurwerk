"""Erzeugt spurwerk.ico — die Bildmarke als Multi-Size-Windows-Icon.

Aufruf:  python assets/make_icon.py

Design (Brand-Sheet „Nachtcyan“): abgerundetes nachtblaues Quadrat mit
Gleisplan — eine gedimmte Spur, eine helle Spur, und am Weichenpunkt
zweigt die Cyan-Spur ab (= die neu erzeugte Spur, das eine Ding, das nur
Spurwerk macht). Jede Größe wird einzeln gerendert (16 px braucht andere
Strichstärken als 256 px), 8-fach supersampled.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "spurwerk.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]

# Farben spiegeln ui/theme.py COLORS — pro Zeile der zugehörige Schlüssel.
# (Bewusst KEIN theme-Import: das Skript bleibt standalone lauffähig.)
BG = "#0d151a"      # COLORS["bg"]
STEEL = "#44545e"   # COLORS["secondary"] — nicht theme.MUTED (#5f717c)!
LIGHT = "#e6edf2"   # COLORS["fg"]
CYAN = "#22d3ee"    # COLORS["primary"]


def _bezier(p0, p1, p2, p3, steps: int = 32) -> list[tuple[float, float]]:
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = (u**3 * p0[0] + 3 * u**2 * t * p1[0]
             + 3 * u * t**2 * p2[0] + t**3 * p3[0])
        y = (u**3 * p0[1] + 3 * u**2 * t * p1[1]
             + 3 * u * t**2 * p2[1] + t**3 * p3[1])
        points.append((x, y))
    return points


def _round_line(draw: ImageDraw.ImageDraw, points, color, width) -> None:
    draw.line(points, fill=color, width=width, joint="curve")
    for x, y in (points[0], points[-1]):
        r = width / 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def render(size: int) -> Image.Image:
    ss = 8
    s = size * ss
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BG)

    # bei winzigen Größen dickere Striche, sonst verschwimmt der Plan
    width = round(s * (0.14 if size <= 24 else 0.11))
    y_top, y_bot = s * 0.36, s * 0.64
    x0, x1 = s * 0.18, s * 0.82

    _round_line(draw, [(x0, y_top), (x1, y_top)], STEEL, width)
    _round_line(draw, [(x0, y_bot), (x1, y_bot)], LIGHT, width)

    branch_start = (s * 0.38, y_bot)
    curve = _bezier(branch_start, (s * 0.56, y_bot),
                    (s * 0.50, y_top), (s * 0.66, y_top))
    _round_line(draw, curve + [(x1, y_top)], CYAN, width)

    if size >= 32:  # Weichenpunkt erst, wenn er auflösbar ist
        r = width * 0.95
        x, y = branch_start
        draw.ellipse([x - r, y - r, x + r, y + r], fill=BG,
                     outline=CYAN, width=round(width * 0.55))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    images = {size: render(size) for size in SIZES}
    largest = images[SIZES[-1]]
    largest.save(OUT, format="ICO",
                 sizes=[(size, size) for size in SIZES],
                 append_images=[images[size] for size in SIZES[:-1]])
    print(f"{OUT.name} geschrieben ({OUT.stat().st_size // 1024} kB, "
          f"Größen: {', '.join(str(size) for size in SIZES)})")


if __name__ == "__main__":
    main()
