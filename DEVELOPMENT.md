# Spurwerk — Entwickler-Doku

## Setup & Start

Vorausgesetzt: **CPython 3.14, 64 bit** von python.org — nicht die
free-threaded Variante 3.14t (der `py`-Launcher wählt sie u. U. als
Standard, daher `-V:3.14`). Die venv heißt `.venv` und liegt im
Projektordner; `build.ps1` baut ausschließlich mit `.venv\Scripts\python.exe`
und bricht mit einem anderen Python ab.

```
py -V:3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python main.py
```

`requirements.txt` hält die eingebetteten Pakete in geprüften Grenzen
(ttkbootstrap 1.x; tkinterdnd2 0.6.x, ältere Versionen laden unter Tcl/Tk 9
kein tkdnd; Pillow bis 12.x), `requirements-dev.txt` pinnt PyInstaller exakt.
Grenzen anheben heißt: neu testen und neu bauen.

Tools (mkvmerge, ffmpeg, ffprobe, dovi_tool) gehören nach `tools/` —
die App lädt sie auch selbst über den Onboarding-Flow.

## Tests & Werkzeuge

```
python tests/make_fixtures.py      # Test-MKVs erzeugen (braucht tools/)
python -m pytest tests             # Unit + End-to-End (echte Tools)
python tests/smoke_ui.py <ordner>  # UI-Screenshots für den Sichtcheck
python assets/make_icon.py         # spurwerk.ico neu rendern
```

Die Fixtures decken ab: Sprachvarianten, 5.1/7.1, DTS, Audio-Delay
(A/V-Sync), `und`-Sprache, ohne-Deutsch, zwei deutsche Spuren und ein
synthetisches Dolby-Vision-8.1-File (dovi_tool generate + inject-rpu)
für den „DV/HDR → HDR10"-End-to-End-Test.

## Architektur

```
core/   Datenmodell, Regel-Engine (planner), Kommandobau (commands),
        Runner (Queue-Protokoll), Scanner (mkvmerge -J), DV-Analyse/
        Pipeline (dv), Tool-Erkennung + Downloader — komplett UI-frei
ui/     ttkbootstrap-Widgets: theme (Nachtcyan + Checkbox-Images),
        track_table (Herzstück), main_window, rule_editor, tool_setup
config.py   config.json (Profile, Tool-Pfade)
version.py  einzige Versionsquelle (App-Titel, Header, EXE-Metadaten)
```

Eiserne Regeln: UI spricht nur übers Datenmodell; `planner`/`commands`
sind pure Funktionen mit Golden-Tests; Worker-Threads kommunizieren
ausschließlich über die Queue (`after`-Polling); der Runner arbeitet auf
Plan-Kopien, die UI ist während eines Laufs gesperrt.

Hintergründe und alle Architektur-Entscheidungen: [UMSETZUNGSPLAN.md](UMSETZUNGSPLAN.md).

## Release bauen

```
.\build.ps1        # dist\Spurwerk.exe (x64, onefile, mit Versions-Metadaten)
                   # + dist\THIRD_PARTY_LICENSES.txt
```

`build.ps1` löscht als Erstes die alte `dist\Spurwerk.exe`,
`dist\THIRD_PARTY_LICENSES.txt` und `build\file_version_info.txt` und bricht
dann beim ersten Fehler ab (fehlende `.venv`, falsches Python, Fehler in
Versionsdatei oder PyInstaller). „Build fertig" heißt
also: die EXE ist in diesem Lauf entstanden und trägt die Version aus
`version.py` (wird nach dem Build geprüft). Vorabversionen wie `2.1.0-rc1`
gehen: die Datei-Version wird dann 2.1.0.0, der Text bleibt `2.1.0-rc1`.

**Lizenzhinweise:** `assets/third_party_licenses.py` schreibt beim Build
`dist\THIRD_PARTY_LICENSES.txt` — Lizenztexte der eingebetteten Pakete aus
der `.venv` (ttkbootstrap, tkinterdnd2/tkdnd, Pillow, PyInstaller-Bootloader),
die Python-Lizenz (enthält auch OpenSSL, libffi, Tcl/Tk) und den Verweis auf
die eigenen Lizenzen der extern geladenen Werkzeuge. Die Datei gehört zu
jedem Release dazu.

**TMDb-Key einbetten (optional, registrierungsfreier Titelabgleich):**
Der öffentliche Quellcode bleibt key-frei. Beim Build wird ein Key aus der
Umgebungsvariable in das gitignorte Modul `core/_apikey.py` geschrieben:

```
$env:SPURWERK_TMDB_KEY = "dein_tmdb_v3_key"; .\build.ps1
```

Ohne gesetzte Variable bettet `build.ps1` eine vorhandene `core/_apikey.py`
(z. B. aus einem früheren Build) ein und meldet das; gelöscht wird sie nie —
sie ist gitignort und oft die einzige Kopie des Keys. Gibt es weder Variable
noch Datei, entsteht ein Release ohne eingebauten Key (Anwender nutzt dann
eigenen Key oder die Offline-Bereinigung). Einen Release garantiert ohne Key
baut `.\build.ps1 -OhneKey` — die Datei bleibt liegen, kommt aber nicht in
die EXE.

Release-Ablauf: Version in `version.py` erhöhen → CHANGELOG-Eintrag aus
[Unreleased] machen → Tests laufen lassen → `build.ps1` → `git tag vX.Y.Z`
→ `Spurwerk.exe` und `THIRD_PARTY_LICENSES.txt` ans Release hängen.
Für den x86-Build dieselben Schritte in einer 32-bit-Python-Installation.
