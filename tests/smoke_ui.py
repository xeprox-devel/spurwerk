"""UI-Smoke-Test: startet die App, lädt Fixtures, macht Screenshots.

Aufruf:  python tests/smoke_ui.py <ausgabeordner>
Kein automatischer Test — ein Entwickler-Werkzeug für den Sichtcheck.
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile  # noqa: E402

import config as appconfig  # noqa: E402

# Nie die echte config.json des Entwicklers überschreiben (Sitzung, Profile,
# Tool-Pfade) — der Sichtcheck speichert beim Laden und Beenden
appconfig.CONFIG_FILE = (Path(tempfile.mkdtemp(prefix="spurwerk-smoke-"))
                         / "config.json")

from PIL import ImageGrab  # noqa: E402

from app import SpurwerkApp  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
errors: list[str] = []


def grab(app, name: str) -> None:
    app.update_idletasks()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    ImageGrab.grab(bbox=(x - 8, y - 36, x + w + 8, y + h + 8)).save(OUT / name)
    print(f"Screenshot: {name} ({w}x{h})")


def main() -> None:
    app = SpurwerkApp()

    def step1() -> None:
        try:
            grab(app, "ui_empty.png")
            files = sorted(FIXTURES.glob("*.mkv"))
            app.main.add_files([str(f) for f in files])
            app.after(3000, step2)
        except Exception:
            errors.append(traceback.format_exc())
            app.destroy()

    def step2() -> None:
        try:
            grab(app, "ui_loaded.png")
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            app.destroy()

    app.after(900, step1)
    app.mainloop()

    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("Smoke-Test ok.")


if __name__ == "__main__":
    main()
