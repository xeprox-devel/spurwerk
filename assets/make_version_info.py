"""Erzeugt die PyInstaller-Versionsdatei aus version.py.

Damit zeigen die Windows-Dateieigenschaften der Spurwerk.exe
(Rechtsklick → Eigenschaften → Details) Version, Produktname usw.
Aufruf durch build.ps1 — Ausgabe: build/file_version_info.txt
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from version import APP_NAME, __version__  # noqa: E402


def file_version(version: str) -> tuple[int, int, int, int]:
    """'2.1.0-rc1' → (2, 1, 0, 0): Windows braucht vier Zahlen, Zusätze wie
    '-rc1' oder '+build' bleiben nur im Text (FileVersion/ProductVersion)."""
    nums = []
    for part in version.split(".")[:3]:
        m = re.match(r"\d+", part)
        if not m:
            break
        nums.append(min(int(m.group()), 0xFFFF))
        if m.end() < len(part):     # '0-rc1' → Rest ist kein Versionsteil mehr
            break
    if not nums:
        raise ValueError(f"Versionsnummer nicht lesbar: {version!r}")
    return tuple((nums + [0, 0, 0])[:3] + [0])


def render(app_name: str, version: str) -> str:
    version_tuple = file_version(version)
    return f"""# UTF-8
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
                     '{app_name} — MKV Remuxer & Audio-Studio'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('ProductName', '{app_name}'),
        StringStruct('ProductVersion', '{version}'),
        StringStruct('LegalCopyright', '© xeproX-deveL'),
        StringStruct('OriginalFilename', '{app_name}.exe')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ])
"""


def main(out: Path = ROOT / "build" / "file_version_info.txt") -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(APP_NAME, __version__), encoding="utf-8")
    print(f"Versionsdatei geschrieben: {out} ({__version__})")


if __name__ == "__main__":
    main()
