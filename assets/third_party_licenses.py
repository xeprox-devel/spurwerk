"""Schreibt dist/THIRD_PARTY_LICENSES.txt — die Lizenzhinweise aller
Fremdkomponenten, die in der Spurwerk.exe stecken.

Aufruf durch build.ps1 mit dem Build-Python (.venv), nach PyInstaller:
dieselbe Umgebung, aus der PyInstaller eingebettet hat, liefert hier die
Versionen und Lizenztexte (importlib.metadata). Die Datei gehört zu jedem
Release dazu.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from version import APP_NAME, __version__  # noqa: E402

SOURCE_URL = "https://github.com/xeprox-devel/spurwerk"
LINE = "=" * 78

# Eingebettet, aber nicht über requirements.txt: der Bootloader der EXE
EXTRA_DISTS = ("pyinstaller",)

# NICHT eingebettet — Spurwerk lädt sie auf Wunsch von den Projektquellen;
# es gelten deren eigene Lizenzen
EXTERNAL_TOOLS = (
    ("MKVToolNix (mkvmerge, mkvextract)", "GPL-2.0",
     "https://mkvtoolnix.download/"),
    ("FFmpeg (ffmpeg, ffprobe)", "GPL (FFmpeg-Builds mit GPL-Komponenten)",
     "https://ffmpeg.org/legal.html"),
    ("dovi_tool", "MIT", "https://github.com/quietvoid/dovi_tool"),
)

_LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _find(name: str, path: list[str] | None) -> metadata.Distribution | None:
    where = {} if path is None else {"path": path}    # None → sys.path
    return next(iter(metadata.Distribution.discover(name=name, **where)),
                None)


def requirement_names(req_file: Path) -> list[str]:
    """Paketnamen aus einer requirements-Datei (inkl. '-r'-Verweisen)."""
    names: list[str] = []
    for raw in req_file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            names += requirement_names(req_file.parent / line.split(None, 1)[1])
            continue
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if m:
            names.append(m.group())
    return names


def _marker_ok(marker: str) -> bool:
    """Umgebungs-Marker auswerten (sys_platform, python_version …).
    Ohne 'packaging' im Zweifel mitnehmen — lieber ein Hinweis zu viel."""
    try:
        from packaging.markers import Marker
    except ImportError:
        return True
    try:
        return Marker(marker).evaluate()
    except Exception:
        return True


def _dependencies(dist: metadata.Distribution) -> list[str]:
    deps = []
    for req in dist.requires or []:
        spec, _, marker = req.partition(";")
        if "extra" in marker:        # optionale Extras landen nicht in der EXE
            continue
        if marker.strip() and not _marker_ok(marker.strip()):
            continue
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
        if m:
            deps.append(m.group(1))
    return deps


def collect(names: list[str], path: list[str] | None = None,
            ) -> list[metadata.Distribution]:
    """Die genannten Pakete samt Laufzeit-Abhängigkeiten. Ein fehlendes
    Top-Level-Paket ist ein Fehler (die Liste wäre sonst unvollständig)."""
    found: dict[str, metadata.Distribution] = {}
    todo = [(n, True) for n in names]
    while todo:
        name, required = todo.pop(0)
        if _norm(name) in found:
            continue
        dist = _find(name, path)
        if dist is None:
            if required:
                raise SystemExit(f"Paket nicht installiert: {name} — "
                                 f"Lizenzhinweise wären unvollständig.")
            continue
        found[_norm(name)] = dist
        todo += [(d, False) for d in _dependencies(dist)]
    return sorted(found.values(), key=lambda d: _norm(d.metadata["Name"]))


def license_summary(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    lic = (md.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 200:
        return lic
    classifiers = [c.rsplit("::", 1)[-1].strip()
                   for c in md.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return ", ".join(classifiers) or "siehe Lizenztext"


def homepage(dist: metadata.Distribution) -> str:
    md = dist.metadata
    if md.get("Home-page"):
        return md["Home-page"]
    urls = [u.split(",", 1) for u in md.get_all("Project-URL") or []]
    for wanted in ("homepage", "source", "source code", "repository"):
        for label, url in urls:
            if label.strip().lower() == wanted:
                return url.strip()
    return urls[0][1].strip() if urls else ""


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """Lizenzdateien aus der dist-info (Metadata 2.4: unter 'licenses/')."""
    texts: list[tuple[str, str]] = []
    for name in dist.metadata.get_all("License-File") or []:
        for candidate in (f"licenses/{name}", name):
            try:
                text = dist.read_text(candidate)
            except (OSError, UnicodeDecodeError):
                text = None
            if text:
                texts.append((name, text))
                break
    if texts:
        return texts
    # ältere Wheels ohne License-File-Eintrag: Dateien direkt in der dist-info
    for f in dist.files or []:
        if (len(f.parts) >= 2 and f.parts[0].endswith(".dist-info")
                and _LICENSE_NAME.match(f.name)):
            try:
                texts.append((f.name, Path(f.locate()).read_text(
                    encoding="utf-8", errors="replace")))
            except OSError:
                pass
    return texts


def python_license() -> tuple[str, str]:
    """(Quelle, Text) der CPython-Lizenz. Die Windows-Installation von
    python.org enthält darin auch OpenSSL, libffi, bzip2, Tcl und Tk."""
    for cand in (Path(sys.base_prefix) / "LICENSE.txt",
                 Path(sys.base_prefix) / "LICENSE"):
        if cand.is_file():
            return str(cand), cand.read_text(encoding="utf-8",
                                             errors="replace")
    return "", ""


def tcl_version() -> str:
    try:
        import tkinter
        return str(tkinter.Tcl().call("info", "patchlevel"))
    except Exception:
        return ""


def _section(title: str) -> list[str]:
    return ["", LINE, title, LINE, ""]


def build_text(req_file: Path = ROOT / "requirements.txt",
               path: list[str] | None = None,
               extra: tuple[str, ...] = EXTRA_DISTS) -> str:
    dists = collect(requirement_names(req_file), path)
    extras = []
    for name in extra:          # nur das Paket selbst, nicht seine Build-Deps
        dist = _find(name, path)
        if dist is None:
            raise SystemExit(f"Paket nicht installiert: {name} — "
                             f"Lizenzhinweise wären unvollständig.")
        extras.append(dist)

    py_src, py_text = python_license()
    tcl = tcl_version()
    py_ver = ".".join(str(v) for v in sys.version_info[:3])

    out = [
        f"{APP_NAME} {__version__} — Lizenzhinweise für eingebettete "
        f"Fremdkomponenten",
        "",
        f"{APP_NAME} selbst steht unter der GNU GPL-3.0 (siehe LICENSE im "
        f"Quelltext).",
        f"Quelltext: {SOURCE_URL}",
        "",
        f"Die Datei {APP_NAME}.exe enthält außerdem die folgenden Komponenten "
        "unter ihren eigenen Lizenzen:",
        "",
        f"  - Python {py_ver} (Interpreter und Standardbibliothek, "
        "inkl. OpenSSL, libffi, bzip2 u. a.)",
        f"  - Tcl/Tk {tcl or '(Version unbekannt)'} (über tkinter)",
    ]
    for d in dists:
        out.append(f"  - {d.metadata['Name']} {d.version} — "
                   f"{license_summary(d)}")
    for d in extras:
        out.append(f"  - {d.metadata['Name']} {d.version} (Bootloader der "
                   f"EXE) — {license_summary(d)}")
    out.append("  - tkdnd (Georgios Petasis, über tkinterdnd2) — "
               "BSD-artige Lizenz, https://github.com/petasis/tkdnd")

    out += _section("Nicht eingebettet: externe Werkzeuge")
    out += [
        f"{APP_NAME} enthält die folgenden Werkzeuge NICHT, sondern lädt sie "
        "auf Wunsch",
        "von den Projektquellen in den Ordner tools/. Für sie gelten "
        "ausschließlich ihre",
        "eigenen Lizenzen; Lizenztexte und Quelltext gibt es bei den "
        "Projekten:",
        "",
    ]
    out += [f"  - {name} — {lic}: {url}" for name, lic, url in EXTERNAL_TOOLS]

    for d in dists + extras:
        out += _section(f"{d.metadata['Name']} {d.version} — "
                        f"{license_summary(d)}")
        if homepage(d):
            out += [f"Projekt: {homepage(d)}", ""]
        texts = license_texts(d)
        if not texts:
            out.append("(Kein Lizenztext im Paket — siehe Projektseite.)")
        for name, text in texts:
            out += [f"--- {name} ---", "", text.rstrip(), ""]

    out += _section(f"Python {py_ver} — PSF License und Lizenzen der "
                    "mitgelieferten Bibliotheken")
    if py_text:
        out += [f"(aus {Path(py_src).name} der Python-Installation)", "",
                py_text.rstrip()]
    else:
        out.append("Lizenztext: https://docs.python.org/3/license.html")

    out += _section(f"Tcl/Tk {tcl}".rstrip())
    # Zeilenumbrüche egal: in LICENSE.txt steht "University of\nCalifornia"
    if "Regents of the University of California" in " ".join(py_text.split()):
        out.append("BSD-artige Lizenz. Der Lizenztext von Tcl und Tk steht "
                   "im Python-Abschnitt oben")
        out.append("(\"This software is copyrighted by the Regents of the "
                   "University of California …\").")
    else:
        out.append("BSD-artige Lizenz: "
                   "https://www.tcl-lang.org/software/tcltk/license.html")
    out.append("")
    return "\n".join(out)


def main(out: Path = ROOT / "dist" / "THIRD_PARTY_LICENSES.txt") -> None:
    text = build_text()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\r\n")   # für Editor
    print(f"Lizenzhinweise geschrieben: {out}")


if __name__ == "__main__":
    main()
