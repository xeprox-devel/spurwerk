# Spurwerk — Entwickler-Doku

## Setup & Start

```
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
python main.py
```

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
(A/V-Sync), `und`-Sprache, ohne-Deutsch, zwei deutsche Spuren sowie ein
synthetisches Dolby-Vision-8.1-File (dovi_tool generate + inject-rpu).

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
```

**TMDb-Key einbetten (optional, registrierungsfreier Titelabgleich):**
Der öffentliche Quellcode bleibt key-frei. Beim Build wird ein Key aus der
Umgebungsvariable in das gitignorte Modul `core/_apikey.py` geschrieben:

```
$env:SPURWERK_TMDB_KEY = "dein_tmdb_v3_key"; .\build.ps1
```

Ohne gesetzte Variable entsteht ein Release ohne eingebauten Key (Anwender
nutzt dann eigenen Key oder die Offline-Bereinigung).

Release-Ablauf: Version in `version.py` erhöhen → CHANGELOG-Eintrag aus
[Unreleased] machen → Tests laufen lassen → `build.ps1` → `git tag vX.Y.Z`.
Für den x86-Build dieselben Schritte in einer 32-bit-Python-Installation.
