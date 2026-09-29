"""Build-Befunde: Versionsdatei, Lizenzhinweise, Abhängigkeits-Pins und
build.ps1 (bricht ab statt 'Build fertig' zu melden, kein alter Key/keine
alte EXE). Alles offline; build.ps1 läuft in einer Wegwerf-Kopie unter
tmp_path mit einer .venv ohne PyInstaller — gebaut wird dabei nichts."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_befunde_{name}", ROOT / "assets" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mvi = _load("make_version_info")
tpl = _load("third_party_licenses")


# ── Versionsdatei ─────────────────────────────────────────────────────────

class TestFileVersion:
    def test_vorabversion_stuerzt_nicht_ab(self):
        assert mvi.file_version("2.1.0-rc1") == (2, 1, 0, 0)
        assert mvi.file_version("2.1.0+build.5") == (2, 1, 0, 0)
        assert mvi.file_version("1.2rc1") == (1, 2, 0, 0)

    def test_normale_versionen(self):
        assert mvi.file_version("2.0.0") == (2, 0, 0, 0)
        assert mvi.file_version("2.1") == (2, 1, 0, 0)     # immer 4 Zahlen
        assert mvi.file_version("3.4.5.6") == (3, 4, 5, 0)

    def test_unlesbar_ist_klarer_fehler(self):
        with pytest.raises(ValueError):
            mvi.file_version("abc")

    def test_render_ist_gueltige_versionsdatei(self, tmp_path):
        text = mvi.render("Spurwerk", "2.1.0-rc1")
        ast.parse(text, mode="eval")
        assert "filevers=(2, 1, 0, 0)" in text
        assert "StringStruct('ProductVersion', '2.1.0-rc1')" in text
        # Wenn PyInstaller da ist: genau so einlesen wie beim Build
        try:
            from PyInstaller.utils.win32 import versioninfo
        except ImportError:
            return
        f = tmp_path / "file_version_info.txt"
        f.write_text(text, encoding="utf-8")
        info = versioninfo.load_version_info_from_text_file(str(f))
        assert (info.ffi.fileVersionMS, info.ffi.fileVersionLS) == (
            (2 << 16) | 1, 0)

    def test_main_schreibt_aktuelle_version(self, tmp_path):
        from version import __version__
        out = tmp_path / "build" / "file_version_info.txt"
        mvi.main(out)
        assert f"'FileVersion', '{__version__}'" in out.read_text("utf-8")


# ── Abhängigkeiten ────────────────────────────────────────────────────────

def _reqs(name: str) -> dict[str, str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    out = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            pkg = line.split(";")[0]
            for op in ("==", ">=", "<", "~="):
                pkg = pkg.split(op)[0]
            out[pkg.strip().lower()] = line
    return out


def test_laufzeit_abhaengigkeiten_haben_obergrenzen():
    req = _reqs("requirements.txt")
    assert "<2" in req["ttkbootstrap"]
    assert ">=0.6" in req["tkinterdnd2"] and "<0.7" in req["tkinterdnd2"]
    assert "<" in req["pillow"]


def test_pyinstaller_exakt_gepinnt():
    dev = _reqs("requirements-dev.txt")
    assert "==" in dev["pyinstaller"]
    assert "-r requirements.txt" in (ROOT / "requirements-dev.txt").read_text(
        encoding="utf-8")


# ── Lizenzhinweise ────────────────────────────────────────────────────────

def _dist(site: Path, name: str, version: str, meta: list[str],
          files: dict[str, str]) -> None:
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    head = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    (info / "METADATA").write_text("\n".join(head + meta) + "\n",
                                   encoding="utf-8")
    record = [f"{info.name}/METADATA,,"]
    for rel, text in files.items():
        (info / rel).parent.mkdir(parents=True, exist_ok=True)
        (info / rel).write_text(text, encoding="utf-8")
        record.append(f"{info.name}/{rel},,")
    (info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")


@pytest.fixture
def fake_site(tmp_path):
    site = tmp_path / "site"
    _dist(site, "alphapkg", "1.0",
          ["License-Expression: MIT", "License-File: LICENSE",
           "Project-URL: Homepage, https://example.org/alpha",
           "Requires-Dist: betapkg>=1",
           'Requires-Dist: gammapkg; extra == "docs"',
           'Requires-Dist: deltapkg; sys_platform == "nirgendwo"'],
          {"licenses/LICENSE": "ALPHA LICENSE TEXT"})
    # älteres Wheel: kein License-File-Eintrag, Datei direkt in der dist-info
    _dist(site, "betapkg", "2.0",
          ["Classifier: License :: OSI Approved :: BSD License"],
          {"LICENSE.txt": "BETA LICENSE TEXT"})
    _dist(site, "gammapkg", "1.0", [], {})
    _dist(site, "deltapkg", "1.0", [], {})
    _dist(site, "bootpkg", "6.0",
          ["License: GPL with bootloader exception",
           "License-File: COPYING.txt"],
          {"COPYING.txt": "BOOT LICENSE TEXT"})
    req = tmp_path / "requirements.txt"
    req.write_text("# Kommentar\nalphapkg>=1,<2  # Laufzeit\n",
                   encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text(
        "-r requirements.txt\npytest>=8\n", encoding="utf-8")
    return site, req


def test_requirements_mit_verweis(fake_site):
    _, req = fake_site
    assert tpl.requirement_names(req.parent / "requirements-dev.txt") == [
        "alphapkg", "pytest"]


def test_lizenzhinweise_enthalten_eingebettete_pakete(fake_site):
    site, req = fake_site
    text = tpl.build_text(req, path=[str(site)], extra=("bootpkg",))
    assert "alphapkg 1.0 — MIT" in text
    assert "ALPHA LICENSE TEXT" in text
    assert "Projekt: https://example.org/alpha" in text
    assert "betapkg 2.0 — BSD License" in text          # Abhängigkeit
    assert "BETA LICENSE TEXT" in text
    assert "bootpkg 6.0 (Bootloader der EXE)" in text
    assert "BOOT LICENSE TEXT" in text
    assert "gammapkg" not in text      # nur über ein Extra verlangt
    assert "deltapkg" not in text      # Marker trifft nicht zu
    # Python-Lizenz (inkl. OpenSSL, Tcl/Tk) und Verweis auf die Werkzeuge
    py = ".".join(str(v) for v in sys.version_info[:3])
    assert f"Python {py} — PSF License" in text
    if (Path(sys.base_prefix) / "LICENSE.txt").is_file():
        assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in text
    assert "Tcl/Tk" in text
    assert "https://mkvtoolnix.download/" in text
    assert "https://ffmpeg.org/legal.html" in text
    assert "https://github.com/quietvoid/dovi_tool" in text


def test_fehlendes_paket_bricht_ab(fake_site, tmp_path):
    site, _ = fake_site
    req = tmp_path / "fehlt.txt"
    req.write_text("gibtsnichtpkg\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        tpl.build_text(req, path=[str(site)], extra=())
    _, req = fake_site
    with pytest.raises(SystemExit):
        tpl.build_text(req, path=[str(site)], extra=("gibtsnichtpkg",))


def test_tcl_verweis_trotz_zeilenumbruch(fake_site, monkeypatch):
    """In LICENSE.txt steht 'Regents of the University of\\nCalifornia' —
    der Tcl/Tk-Abschnitt muss trotzdem auf den enthaltenen Text verweisen."""
    site, req = fake_site
    monkeypatch.setattr(tpl, "python_license", lambda: (
        "LICENSE.txt", "PSF ...\nThis software is copyrighted by the Regents "
        "of the University of\nCalifornia, Sun Microsystems, Inc.\n"))
    text = tpl.build_text(req, path=[str(site)], extra=())
    tcl = text.rpartition("\nTcl/Tk")[2]         # der Tcl/Tk-Abschnitt
    assert "steht im Python-Abschnitt oben" in tcl
    assert "tcl-lang.org" not in tcl


def test_tcl_ohne_python_lizenz_verweist_auf_url(fake_site, monkeypatch):
    site, req = fake_site
    monkeypatch.setattr(tpl, "python_license", lambda: ("", ""))
    text = tpl.build_text(req, path=[str(site)], extra=())
    tcl = text.rpartition("\nTcl/Tk")[2]
    assert "https://www.tcl-lang.org/software/tcltk/license.html" in tcl
    assert "Python-Abschnitt" not in tcl
    assert "https://docs.python.org/3/license.html" in text


def test_main_schreibt_datei(fake_site, tmp_path, monkeypatch):
    site, req = fake_site
    out = tmp_path / "dist" / "THIRD_PARTY_LICENSES.txt"
    orig = tpl.build_text
    monkeypatch.setattr(tpl, "build_text",
                        lambda: orig(req, path=[str(site)], extra=("bootpkg",)))
    tpl.main(out)
    raw = out.read_bytes()
    assert b"ALPHA LICENSE TEXT" in raw
    assert b"\r\n" in raw                  # Windows-Editor-freundlich


# ── build.ps1 ─────────────────────────────────────────────────────────────

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
_BUILD_PY_OK = (sys.version_info[:2] == (3, 14)
                and not sysconfig.get_config_var("Py_GIL_DISABLED"))

needs_ps = pytest.mark.skipif(os.name != "nt" or not POWERSHELL,
                              reason="build.ps1 braucht Windows-PowerShell")


def _run_build(proj: Path, key: str | None = None, *args: str):
    env = {k: v for k, v in os.environ.items() if k != "SPURWERK_TMDB_KEY"}
    if key is not None:
        env["SPURWERK_TMDB_KEY"] = key
    (proj / "pyi_args.json").unlink(missing_ok=True)
    # bewusst aus einem anderen Ordner starten: build.ps1 muss selbst in
    # seinen Projektordner wechseln
    r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(proj / "build.ps1"), *args],
                       cwd=proj.parent, env=env, capture_output=True,
                       timeout=180)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    return r.returncode, out


def _pyi_args(proj: Path) -> list[str]:
    """Die Argumente, mit denen build.ps1 das (falsche) PyInstaller rief."""
    return json.loads((proj / "pyi_args.json").read_text(encoding="utf-8"))


def _excluded(args: list[str]) -> list[str]:
    return [b for a, b in zip(args, args[1:]) if a == "--exclude-module"]


def _project(base: Path) -> Path:
    proj = base / "proj"
    (proj / "assets").mkdir(parents=True)
    (proj / "core").mkdir()
    shutil.copy2(ROOT / "build.ps1", proj / "build.ps1")
    shutil.copy2(ROOT / "version.py", proj / "version.py")
    shutil.copy2(ROOT / "assets" / "make_version_info.py",
                 proj / "assets" / "make_version_info.py")
    return proj


_ALTER_KEY = 'KEY = "alter_key"\n'


def _stale(proj: Path, key: bool = True) -> None:
    """Reste eines früheren Builds, die nie ausgeliefert werden dürfen —
    und (optional) die gitignorte Key-Datei, die nie gelöscht werden darf."""
    files = [("dist/Spurwerk.exe", "ALTE EXE"),
             ("dist/THIRD_PARTY_LICENSES.txt", "ALT"),
             ("build/file_version_info.txt", "ALTE VERSION")]
    if key:
        files.append(("core/_apikey.py", _ALTER_KEY))
    else:
        (proj / "core" / "_apikey.py").unlink(missing_ok=True)
    for rel, text in files:
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(text, encoding="utf-8", newline="")


def _alte_artefakte_weg(proj: Path) -> None:
    assert not (proj / "dist" / "Spurwerk.exe").exists()
    assert not (proj / "dist" / "THIRD_PARTY_LICENSES.txt").exists()
    info = proj / "build" / "file_version_info.txt"
    assert not info.exists() or "ALTE VERSION" not in info.read_text("utf-8")


def _key_datei(proj: Path) -> str:
    return (proj / "core" / "_apikey.py").read_text("utf-8")


@pytest.fixture(scope="module")
def proj_mit_venv(tmp_path_factory):
    if os.name != "nt" or not POWERSHELL or not _BUILD_PY_OK:
        pytest.skip("braucht Windows-PowerShell und CPython 3.14 (GIL)")
    proj = _project(tmp_path_factory.mktemp("build"))
    # .venv mit einem falschen PyInstaller: alles bis zum PyInstaller-Aufruf
    # läuft echt; der Aufruf merkt sich seine Argumente und scheitert, dann
    # muss build.ps1 abbrechen
    venv = proj / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                   check=True, timeout=120)
    fake = venv / "Lib" / "site-packages" / "PyInstaller"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("", encoding="utf-8")
    (fake / "__main__.py").write_text(
        "import json, sys\n"
        f"with open({str(proj / 'pyi_args.json')!r}, 'w', "
        "encoding='utf-8') as f:\n"
        "    json.dump(sys.argv[1:], f)\n"
        "sys.exit(3)\n", encoding="utf-8")
    return proj


@needs_ps
def test_ohne_venv_kein_build_fertig(tmp_path):
    proj = _project(tmp_path)
    _stale(proj)
    code, out = _run_build(proj)
    assert code != 0
    assert "Build fertig" not in out
    assert ".venv" in out
    # auch ein früher Abbruch lässt keine alte EXE zum Ausliefern liegen
    _alte_artefakte_weg(proj)
    assert _key_datei(proj) == _ALTER_KEY


@needs_ps
def test_alter_exitcode_taeuscht_kein_build_fertig(tmp_path):
    """Befund-Szenario: pytest (Exit 0) direkt vor build.ps1 in derselben
    Sitzung, keine .venv — früher stand am Ende trotzdem 'Build fertig'."""
    proj = _project(tmp_path)
    _stale(proj)
    env = {k: v for k, v in os.environ.items() if k != "SPURWERK_TMDB_KEY"}
    r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command",
                        f"cmd /c exit 0; & '{proj / 'build.ps1'}'"],
                       cwd=proj.parent, env=env, capture_output=True,
                       timeout=180)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    assert r.returncode != 0
    assert "Build fertig" not in out
    _alte_artefakte_weg(proj)


@needs_ps
def test_fehlschlag_meldet_nicht_fertig_und_raeumt_auf(proj_mit_venv):
    proj = proj_mit_venv
    _stale(proj)
    code, out = _run_build(proj)
    assert code != 0, out
    assert "Build fertig" not in out
    assert "PyInstaller fehlgeschlagen (Exit-Code 3)" in out
    # alte EXE/Lizenzdatei weg, Versionsdatei frisch aus version.py
    _alte_artefakte_weg(proj)
    from version import __version__
    info = (proj / "build" / "file_version_info.txt").read_text("utf-8")
    assert f"'ProductVersion', '{__version__}'" in info
    assert _pyi_args(proj)[-1] == "main.py"


@needs_ps
def test_vorhandene_key_datei_bleibt_und_meldung_stimmt(proj_mit_venv):
    """Ohne SPURWERK_TMDB_KEY: die vorhandene core/_apikey.py (oft die einzige
    Kopie des Keys) wird nicht gelöscht, sondern eingebettet — und so gemeldet."""
    proj = proj_mit_venv
    _stale(proj)
    code, out = _run_build(proj)
    assert code != 0 and "Build fertig" not in out
    assert _key_datei(proj) == _ALTER_KEY
    assert "TMDb-Key eingebettet (aus vorhandener core" in out
    assert "ohne eingebauten Key" not in out
    args = _pyi_args(proj)
    assert "--hidden-import=core._apikey" in args
    assert "core._apikey" not in _excluded(args)


@needs_ps
def test_key_aus_umgebung_wird_geschrieben(proj_mit_venv):
    proj = proj_mit_venv
    _stale(proj)
    code, out = _run_build(proj, key="neuer_key_123")
    assert code != 0 and "Build fertig" not in out
    key_file = proj / "core" / "_apikey.py"
    assert "neuer_key_123" in key_file.read_text(encoding="utf-8-sig")
    assert "TMDb-Key eingebettet (aus SPURWERK_TMDB_KEY" in out
    assert "ohne eingebauten Key" not in out
    assert "--hidden-import=core._apikey" in _pyi_args(proj)


@needs_ps
def test_ohne_key_schalter_laesst_datei_liegen(proj_mit_venv):
    """-OhneKey: Release ohne Key, auch wenn Variable und Datei da sind —
    die Datei bleibt unverändert liegen, PyInstaller lässt das Modul weg."""
    proj = proj_mit_venv
    _stale(proj)
    code, out = _run_build(proj, "neuer_key_123", "-OhneKey")
    assert code != 0 and "Build fertig" not in out
    assert _key_datei(proj) == _ALTER_KEY
    assert "ohne eingebauten Key" in out
    assert "TMDb-Key eingebettet" not in out
    args = _pyi_args(proj)
    assert "core._apikey" in _excluded(args)
    assert "--hidden-import=core._apikey" not in args


@needs_ps
def test_ohne_variable_und_datei_kein_key(proj_mit_venv):
    proj = proj_mit_venv
    _stale(proj, key=False)
    code, out = _run_build(proj)
    assert code != 0 and "Build fertig" not in out
    assert not (proj / "core" / "_apikey.py").exists()
    assert "Release ohne eingebauten Key" in out
    assert "TMDb-Key eingebettet" not in out
    args = _pyi_args(proj)
    assert "--hidden-import=core._apikey" not in args
    assert "core._apikey" not in _excluded(args)
