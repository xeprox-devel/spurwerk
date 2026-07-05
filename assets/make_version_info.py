"""Erzeugt die PyInstaller-Versionsdatei aus version.py.

Damit zeigen die Windows-Dateieigenschaften der Spurwerk.exe
(Rechtsklick → Eigenschaften → Details) Version, Produktname usw.
Aufruf durch build.ps1 — Ausgabe: build/file_version_info.txt
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from version import APP_NAME, __version__  # noqa: E402

parts = [int(p) for p in __version__.split(".")[:3]] + [0]
version_tuple = tuple(parts[:4])

TEMPLATE = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704b0', [
        StringStruct('CompanyName', 'xeproX-deveL'),
        StringStruct('FileDescription',
                     '{APP_NAME} — MKV Remuxer & Audio-Studio'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{__version__}'),
        StringStruct('LegalCopyright', '© xeproX-deveL'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ])
"""

out = ROOT / "build" / "file_version_info.txt"
out.parent.mkdir(exist_ok=True)
out.write_text(TEMPLATE, encoding="utf-8")
print(f"Versionsdatei geschrieben: {out} ({__version__})")
