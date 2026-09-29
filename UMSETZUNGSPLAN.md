# Umsetzungsplan — Spurwerk *(vormals „MKV Audio Remuxer Pro")*

Stand: 2026-07-04 · Basis: `audio2stereo.py` (~1100 Zeilen, ttkbootstrap/tkinter)
Recherche-Grundlage: Alle Download-URLs, Archivstrukturen und Framework-Fähigkeiten wurden
am 04.07.2026 **real per HTTP verifiziert** (inkl. Testdownload + Entpacken + Starten der EXEs).

---

## 1. Ziel & Leitidee

Aus dem Ein-Zweck-Konverter („eine Audiospur → Stereo") wird ein **Remux-Werkzeug mit
integrierter Stereo-Konvertierung**, das sich durch vier Dinge vom Markt abhebt
(Ergebnis der Konkurrenzanalyse — kein einziges Tool kann mehr als zwei davon gleichzeitig):

1. **Verlustfreier Remux mit Spur-Checkboxen** (MKVToolNix-Domäne, aber radikal aufgeräumt)
2. **Selektive Stereo-Konvertierung pro Spur im selben Durchlauf** (HandBrake-Domäne, aber ohne Video-Re-Encoding — HandBrake kann prinzipbedingt kein Video-Passthrough)
3. **Regelbasierte Sprach-Automatik mit Live-Vorschau und manueller Übersteuerung** (MakeMKV hat Regeln, aber als kryptische Syntax ohne Feedback)
4. **Moderne, deutschsprachige, selbsterklärende Dark-UI + Ein-Klick-Tool-Downloader** (kein Konkurrent lädt seine Binaries selbst nach)

**Das zentrale Bedienprinzip:** Die Ausgabe wird **pro Spur** definiert. Jede Spur hat eine
Checkbox (kommt mit / kommt weg) und jede Audiospur zusätzlich eine Aktion:

| Aktion | Bedeutung |
|---|---|
| `Kopieren` | verlustfrei übernehmen (Standard) |
| `Kopie + Stereo` | Original behalten **und** Stereo-Version zusätzlich einmuxen |
| `→ Stereo ersetzen` | nur die Stereo-Version übernehmen |
| `Entfernen` | Spur fällt weg |

Damit sind „nur remuxen", „Stereo hinzufügen" und der heutige Workflow („ersetzen")
**ein einziges mentales Modell** statt drei Modi. Reine Remux-Jobs laufen als **ein einziger
mkvmerge-Durchlauf** (kein Extrahieren, kein FFmpeg, sekundenschnell, bitgenau).

---

## 2. Verifizierte Rahmenbedingungen (Recherche-Ergebnis)

### 2.1 Tool-Downloads (alle URLs am 04.07.2026 geprüft, Status 200)

**MKVToolNix** (mkvmerge.exe + mkvextract.exe, ~40 MB entpackt):
- Version ermitteln: `https://mkvtoolnix.download/latest-release.xml.gz` (273 B, gzip-XML, Feld `latest-source/version`, aktuell `99.0`) — diese URL nutzt MKVToolNix selbst für den Update-Check → langzeitstabil
- Download: `https://mkvtoolnix.download/windows/releases/{v}/mkvtoolnix-64-bit-{v}.zip` (88,7 MB)
  - **Wichtig: Die ZIP-Variante existiert (seit v92.0)** und enthält nur STORED/DEFLATE → Pythons `zipfile` genügt, **kein py7zr nötig** (das 7z wäre zwar 3× kleiner, nutzt aber BCJ2 — py7zr 1.1.3 scheitert daran nachweislich mit `UnsupportedCompressionMethodError`)
- Checksumme: `.../sha256sums.txt` (Format `hash␣␣dateiname`)
- Archivstruktur: `mkvtoolnix/mkvmerge.exe`, `mkvtoolnix/mkvextract.exe` — **statisch gelinkt, null DLLs**; beide EXEs wurden real einzeln in einen leeren Ordner extrahiert und erfolgreich gestartet

**FFmpeg** (ffmpeg.exe + ffprobe.exe, ~194 MB entpackt):
- Primär: `https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip` (105 MB, echtes Stable-Release 8.1.2, versionsunabhängige URL)
  - Checksumme: gleiche URL + `.sha256` (nur Hex-Digest, eine Zeile)
  - Version: `https://www.gyan.dev/ffmpeg/builds/release-version` (Plaintext `8.1.2`)
  - **Achtung:** Top-Ordner im Archiv ist versioniert (`ffmpeg-8.1.2-essentials_build/bin/…`) → beim Entpacken per Muster `*/bin/ffmpeg.exe` suchen, nie hart codieren
- Fallback: `https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip` (160 MB, GitHub-CDN = höchste Verfügbarkeit; git-master-Snapshot; Checksummen: `.../latest/download/checksums.sha256`, Format `hash␣␣name`; kein API-Call/Rate-Limit — der latest-Redirect ist ein normaler Web-Redirect)
- Beide .sha256-Formate unterscheiden sich → Parser muss beide können

**32-bit-Quellen** (für Systeme mit 32-bit-Windows, verifiziert 04.07.2026) — *aufgehoben am 29.09.2026: kein x86-Build mehr, siehe Entscheidung 14*:
- MKVToolNix: gleiches Muster, `mkvtoolnix-32-bit-{v}.zip` (84,4 MB, HTTP 200)
- FFmpeg: `https://github.com/sudo-nautilus/FFmpeg-Builds-Win32/releases/latest/download/ffmpeg-master-latest-win32-gpl.zip` (92,7 MB, HTTP 200; aktiv gepflegter Community-Fork des BtbN-Buildsystems — gyan.dev und BtbN selbst bauen nur noch x64)

### 2.2 ttkbootstrap 1.20.4 (aktuell, aktiv gepflegt, Python ≥3.10, Dependency nur Pillow)

- **`Tableview` ist ungeeignet für die Spurliste**: intern `show=HEADINGS`, keine Images/Widgets in Zellen. → Eigenes `ttk.Treeview` mit `show="tree headings"` + **Pillow-generierten Checkbox-Bildern** in Spalte #0 (theme-genau gefärbt aus `style.colors`, DPI-skaliert via `utility.scale_size`; bei `<<ThemeChanged>>` neu generieren; Bild-Referenzen halten!)
- Verfügbar & dark-tauglich: `ToastNotification`, `ToolTip`, `Floodgauge` (Text im Balken), `ScrolledFrame`, theme-konforme `Messagebox`. Neue Importpfade: `from ttkbootstrap.widgets import …` (alte Pfade nur noch Deprecation-Shims)
- **Eigenes Theme** zur Laufzeit: `style.register_theme(ThemeDefinition("spurwerk-dark", COLORS, "dark"))` — dieselben Farben für Checkbox-Images, Log-Tags und Status-Chips = konsistentes Design (Token-Werte: siehe Entscheidung 13 in Abschnitt 8)
- **Drag&Drop + ttkbootstrap sauber kombiniert**: `class App(tb.Window)` + `self.TkdndVersion = TkinterDnD._require(self)` im `__init__` → man behält `hdpi=True`, `minsize`, `place_window_center` (heutiges Muster `TkinterDnD.Tk()` verliert das)
- **HiDPI**: `tb.Window(hdpi=True)` ruft `SetProcessDPIAware` auf; eigene Pixelmaße durch `utility.scale_size()` schicken
- **Dunkle Titelleiste** gibt es nur per DWM-Hack: `DwmSetWindowAttribute(hwnd, 20, 1)` (ältere Win10-Builds: Attribut 19) — lohnt sich, sonst weiße Leiste über dunkler App
- **Grenzen (Design realistisch halten):** keine echten Widgets in Treeview-Zellen (Aktions-Editor = Combobox-Overlay via `bbox()` oder `tk.Menu` an der Zelle), nur Spalte #0 kann Bilder tragen, keine Animationen/Acrylic, Tk ist single-threaded (Queue+`after()`-Muster der App ist genau richtig und bleibt)

### 2.3 Fenstergröße (bestätigter Weg)

Kein hartes `geometry("1100x920")` mehr:
```python
root.update_idletasks()
w = min(root.winfo_reqwidth(),  int(root.winfo_screenwidth()  * 0.92))
h = min(root.winfo_reqheight(), int(root.winfo_screenheight() * 0.90))  # Taskleiste!
root.geometry(f"{w}x{h}"); root.minsize(min(w, 960), min(h, 600))
```
Regeln: **im laufenden Betrieb nur automatisch wachsen, nie schrumpfen** (kein Springen);
einzige Ausnahme ist der explizite Rückfall in den Leerzustand („Alle löschen"), wo das
Fenster wieder kompakt werden darf. Anpassung nur bei Strukturwechseln (Sektion auf/zu,
Datei geladen), Deckel = Arbeitsbereich, und sobald der Nutzer selbst zieht, gewinnt der
Nutzer (Auto-Height für die Session aus). Nur Spurtabelle und Log scrollen intern —
das Fenster selbst nie.

---

## 3. UI-Konzept (Synthese aus 3 unabhängigen Design-Entwürfen)

Gewählt: **tabellen-zentriertes Cockpit** (Entwurf „Spurpult") kombiniert mit der
**Klartext-Vorschau** aus dem Entwurf „Gefuehrter Flow". Auf den dritten Entwurf
(getrennter Einfach-/Experten-Modus mit Kacheln) wird bewusst verzichtet: zwei Ansichten
desselben Modells sind das größte Divergenz-Risiko und die Profil-Combobox leistet
dasselbe mit einem Bruchteil der Komplexität.

### 3.1 Hauptfenster (Normalzustand)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ MKV Audio Remuxer Pro          Tools: [● MKVToolNix 99.0] [● FFmpeg 8.1.2]      [⚙] │  Kopf: Status-Chips
├──────────────────────────────────────────────────────────────────────────────────────┤  (grün=ok, rot=fehlt,
│ DATEIEN (2)  [+ Dateien] [+ Ordner] [−] [Leeren]     Ausgabe: [Quellordner, "_remux"▾]│   Klick = Tool-Manager)
│ ┌──┬────────────────────────────────┬───────┬──────────────────────────┬──────────┐  │
│ │▸ │ Der.Film.2024.German.mkv       │ 2:14h │ 4/9 Spuren · 1× Stereo   │ ● läuft  │  │  Dateiliste = immer
│ │  │ Serie.S01E02.mkv               │ 0:43h │ 3/6 Spuren · 1× Stereo ⚠ │ ○ wartet │  │  Batch (1..n), ganzes
│ └──┴────────────────────────────────┴───────┴──────────────────────────┴──────────┘  │  Fenster ist Drop-Ziel
├──────────────────────────────────────────────────────────────────────────────────────┤
│ REGELN  Profil: [Deutsch bevorzugt ▾]  [Bearbeiten…]                                 │  aktive Regel als
│ » Behalte DE-Audio + DE-Subs · 5.1 → zusätzlich Stereo-Kopie · Rest entfernen «      │  Klartext-Satz
├──────────────────────────────────────────────────────────────────────────────────────┤
│ SPUREN · Der.Film.2024.German.mkv                    [Alle an] [Alle aus] [↺ Regel]  │
│ ┌────┬────┬─────┬────────────┬─────────┬───────┬────────────┬───────────────────┬───┐│
│ │ ☑  │ ID │ Typ │ Codec      │ Sprache │ Kanäle│ Name       │ Aktion            │ Q ││  DAS HERZSTÜCK:
│ ├────┼────┼─────┼────────────┼─────────┼───────┼────────────┼───────────────────┼───┤│  eigenes Treeview-
│ │[✔] │ 0  │ 🎬  │ HEVC 10bit │  —      │  —    │ Main       │ Kopieren          │ R ││  Widget, Checkbox-
│ │[✔] │ 1  │ 🔊  │ E-AC3      │  de     │ 5.1   │ Surround   │ Kopie + Stereo  ▾ │ R ││  Images in #0,
│ │[✔] │ 2  │ 🔊  │ DTS-HD MA  │  en     │ 7.1   │ Original   │ Kopieren        ▾ │ M ││  Aktions-Overlay
│ │[ ] │ 3  │ 🔊  │ AAC        │  fr     │ 2.0   │ Kommentar  │ —                 │ R ││  in der Zelle
│ │[✔] │ 4  │ 💬  │ SubRip     │  de     │  —    │ Forced     │ Kopieren          │ R ││
│ │[ ] │ 5  │ 💬  │ PGS        │  en     │  —    │ Full       │ —                 │ R ││  Q: R=Regel, M=Manuell
│ └────┴────┴─────┴────────────┴─────────┴───────┴────────────┴───────────────────┴───┘│
│ Ausgabe: 1× Video · 2× Audio (davon NEU: de Stereo AC3 640k) · 1× Sub · Kapitel ✓    │  Live-Vorschauzeile
├──────────────────────────────────────────────────────────────────────────────────────┤
│ STEREO-KONVERTIERUNG (wirkt auf 1 Spur)          ← nur sichtbar, wenn ≥1 Stereo-     │
│ Codec [AC3 (Dolby Digital) ▾] Bitrate [640k ▾] Downmix [Loro (ITU) ▾]     Aktion     │
│ Spurname [Stereo AC3        ]  [✔] Neue Stereospur als Standard-Audiospur            │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ [ ▶  START — 2 Dateien · 7 Spuren verlustfrei · 2 Stereo-Konvertierungen ]  [⏹]      │  sprechender Button
│ Gesamt ▓▓▓▓░░░░░░░░ 21% — Datei 1/2: FFmpeg-Downmix Spur 1 → AC3 640k … 48%          │  Floodgauge
│ ▸ Protokoll (23)                                                                     │  eingeklappt = 1 Zeile
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Leerzustand (Tools ok, keine Datei)

Dateiliste + Spurtabelle verschmelzen zu **einer großen gestrichelten Drop-Zone**
(„MKV-Dateien hierher ziehen — oder [Dateien öffnen…] [Ordner öffnen…]"), darunter die
aktive Regel als Satz mit [Regeln ändern]. Rest ausgeblendet, Fenster kompakt.

### 3.3 Erststart (tools/ leer) — Onboarding statt Fehlermeldung

```
│  Willkommen! Die App braucht zwei freie Open-Source-Werkzeuge (GPL):                 │
│    [ ] MKVToolNix (Analyse & Muxen)   — nicht gefunden                               │
│    [ ] FFmpeg     (Stereo-Downmix)    — nicht gefunden                               │
│                                                                                      │
│    [ ⬇  Tools jetzt herunterladen (~195 MB, einmalig) ]                              │
│    MKVToolNix 99.0  ▓▓▓▓▓▓▓▓░░░░ 62% — prüfe SHA-256 …                               │
│    FFmpeg 8.1.2     ░░░░░░░░░░░░ wartet                                              │
│                                                                                      │
│    Ich habe die Tools schon:  [Pfade selbst wählen…]     Quellen & Lizenzen ▾        │
```
Dateien dürfen schon **vor** dem Download hineingezogen werden (Status „wartet auf Tools",
Scan startet automatisch danach). Die heutigen vier Pfad-Eingabezeilen verschwinden aus dem
Hauptfenster in den Tool-Manager-Dialog (Zahnrad / Klick auf Status-Chip): Pfad, Version,
Testlauf-Ergebnis, [Erneut herunterladen] / [Pfad ändern] / [Auf Update prüfen].

**Abgestufte Nutzbarkeit:** Reiner Remux braucht nur MKVToolNix. Schlägt (nur) der
FFmpeg-Download fehl, bleibt die App im Remux-Modus voll nutzbar — Stereo-Aktionen sind
dann ausgegraut mit Hinweis „benötigt FFmpeg [Herunterladen]" statt Komplett-Blockade.

### 3.4 Kern-Interaktionen

- **Null-Denk-Pfad:** Datei(en) reinziehen → Scan + Regel automatisch → Vorschauzeile & sprechender START-Button zeigen exakt, was passieren wird → 1 Klick. Das Default-Profil „Deutsch bevorzugt" reproduziert den heutigen Workflow.
- **Checkbox-Toggle:** Klick auf Spalte #0 (Leertaste togglet Auswahl); abgewählte Zeilen gedimmt, Aktion „—", Herkunft springt auf `M`.
- **Audio-Aktion:** Klick auf die Aktion-Zelle → readonly-Combobox exakt über der Zelle (`tree.bbox()`), Optionen kontextabhängig (bei 2.0-Quellen entfällt Downmix-Auswahl). Overlay schließt zuverlässig bei Scroll/Resize/Fokusverlust/Dateiwechsel.
- **Regeln:** Profil-Combobox (mitgeliefert: „Deutsch bevorzugt", „DE+EN behalten", „Alles behalten", „Nur remuxen") + Dialog: Sprach-Prioritätenliste, Audio-/Untertitel-Politik pro Sprache, Stereo-Politik (hinzufügen/ersetzen/nie), Umgang mit `und`-Spuren, „Forced-Subs immer behalten", Kommentarspur-Heuristik (`/kommentar|commentary/i`). „↺ Regel" setzt nur `M`-Zeilen der aktiven Datei zurück; Regel neu anwenden überschreibt **nur** `R`-Zeilen — manuelle Eingriffe sind geschützt.
- **Batch-Abweichler:** Dateien, bei denen die Regel nicht sauber greift („kein Deutsch gefunden", „2 deutsche Spuren"), bekommen ⚠ in der Plan-Spalte — nur die muss man sich ansehen. Kontextmenü: „Diese Spurauswahl als Muster auf alle anwenden" (Matching über Typ+Sprache, **nie** über Track-ID).
- **Fehler-UX:** Ein Fehler stoppt nur die betroffene Datei, nie den Batch. Zeile wird rot mit Kurzgrund, Klick springt zur getaggten Stelle im Log (klappt bei Fehlern selbst auf). Abschluss als Toast („7/8 fertig, 1 Fehler — [Ordner öffnen]") statt modaler Box. Existierende Ausgabedatei → Sammel-Dialog Überschreiben/Umbenennen/Überspringen. mkvmerge-Exit 1 bleibt Warnung (gelb), ≥2 Fehler.

---

## 4. Architektur & Datenmodell

### 4.1 Modulstruktur (Aufteilung der einen Datei)

```
MKV Audio Remuxer/
├── main.py                  # Entry-Point: DPI, Theme, App starten
├── app.py                   # App(tb.Window)-Shell: DnD-Mixin, Fenster-Sizing, Titelleisten-Hack
├── config.py                # Settings + Profile (JSON; einmaliger Import der alten config.ini)
├── core/
│   ├── model.py             # Dataclasses: Track, TrackDecision, FilePlan, RuleProfile, StereoSettings
│   ├── scanner.py           # mkvmerge -J → MediaInfo (threaded Scan-Queue, max. N parallel)
│   ├── planner.py           # RuleProfile × MediaInfo → FilePlan (PURE FUNKTION, unit-testbar)
│   ├── commands.py          # Kommando-Builder mkvmerge/mkvextract/ffmpeg (PURE, unit-testbar)
│   ├── runner.py            # JobRunner: Worker-Thread, Fortschritt, Cancel, Queue → UI
│   ├── tools.py             # Erkennung, Validierung, --version-Parsing, Pfad-Persistenz
│   └── downloader.py        # Download + SHA256 + Extraktion (siehe Abschnitt 6)
└── ui/
    ├── theme.py             # ThemeDefinition "remuxerdark", Farben, Checkbox-Image-Fabrik
    ├── main_window.py       # Layout-Komposition der Sektionen
    ├── track_table.py       # DAS gekapselte Treeview-Widget (Checkboxen, Aktions-Overlay, Gruppen)
    ├── file_list.py         # Dateiliste mit Status/Plan-Spalte
    ├── sections.py          # CollapsibleSection (Chevron, meldet Strukturwechsel für Auto-Height)
    ├── dialogs.py           # Regel-Editor, Tool-Manager, Download-Dialog, Konflikt-Dialog
    └── logpanel.py          # farbiges Log (Tags aus theme.py), Fortschrittsleiste
```

**Eiserne Regel:** UI liest und schreibt ausschließlich das Datenmodell; `planner.py` und
`commands.py` sind reine Funktionen ohne tkinter-Import → automatisiert testbar.

### 4.2 Datenmodell (Kern)

```python
class Action(Enum):
    COPY = "copy"; STEREO_ADD = "stereo_add"; STEREO_REPLACE = "stereo_replace"; DROP = "drop"

class Origin(Enum):
    RULE = "R"; MANUAL = "M"

@dataclass
class Track:            # aus mkvmerge -J
    id: int; type: str; codec_id: str; lang: str; name: str
    channels: int | None; default: bool; forced: bool
    minimum_timestamp_ns: int | None   # Startversatz → --sync beim Mux (A/V-Sync!)

@dataclass
class TrackDecision:
    action: Action; origin: Origin; make_default: bool = False

@dataclass
class FilePlan:
    path: str; tracks: list[Track]; decisions: dict[int, TrackDecision]
    warnings: list[str]            # "kein Deutsch gefunden" etc. → ⚠ in der Liste
    output_path: str; status: str  # wartet/läuft/fertig/fehler/übersprungen

@dataclass
class RuleProfile:
    name: str
    lang_priority: list[str]           # ["de", "en"]
    audio_policy: str                  # preferred_only | preferred_plus_en | all
    stereo_policy: str                 # add | replace | never (greift bei >2 Kanälen)
    sub_policy: str                    # preferred | forced_only | all | none
    drop_commentary: bool
    stereo: StereoSettings             # codec, bitrate, downmix_preset, track_name
    output: OutputSettings             # suffix, zielordner (leer = Quellordner)
```

`StereoSettings` gilt **global pro Job** (ein Codec/Bitrate/Preset für alle Stereo-Aktionen —
der Panel-Titel zeigt „wirkt auf n Spuren"). Das Default-Flag hat genau **eine** Quelle:
`TrackDecision.make_default`; die Checkbox „Neue Stereospur als Standard" im Stereo-Panel
schreibt in die betreffende TrackDecision durch.

Das Modell erzwingt Invarianten, die mkvmerge zur Laufzeit **nicht** anmeckert (doppelte
oder fehlende Default-Flags gehen dort still durch!): genau **eine** Default-Audiospur,
mindestens eine aktive Spur, Ziel ≠ Quelle.

### 4.3 Job-Pipeline (pro Datei)

1. **Nur-Remux-Plan** (keine Stereo-Aktion): ein einziger mkvmerge-Lauf —
   `mkvmerge -o out --audio-tracks 1,2 --subtitle-tracks 4 --video-tracks 0 input.mkv`
   (Kapitel/Anhänge bleiben automatisch erhalten; `--no-…` nur für explizit Abgewähltes).
2. **Mit Stereo-Aktionen:** FFmpeg liest die Spur **direkt aus der MKV**
   (`-i input.mkv -map 0:a:{n}`) statt des bisherigen mkvextract-Umwegs — das eliminiert
   den Temp-Extraktionsschritt, das `CODEC_EXT`-Mapping samt `.bin`-Fallback und eine
   ganze Fehlerklasse. Die Downmix-Presets Loro/Pro/LFE-Boost/Passthrough werden aus dem
   Altcode übernommen — **mit einer wichtigen Korrektur:** Der bisherige „native
   AC3-Downmix"-Zweig (`-dmix_mode loro` …, Z. 1017–1024) ist ein **Bug im Altcode**:
   diese Optionen schreiben nur Downmix-*Metadaten* in den Bitstream, mischen aber nichts
   herunter — ohne `-ac 2` ist die Ausgabe dort real 5.1 statt Stereo. Dieser Zweig wird
   **nicht** übernommen; alle Codecs nutzen einheitlich den Pan-Filter.
   Danach **ein** finaler mkvmerge-Lauf: Quelle (mit Spurauswahl) + n Stereo-Dateien, mit
   `--language 0:{quellsprache}` (von der Quellspur geerbt, nicht mehr pauschal „ger"),
   `--track-name` und `--track-order` über Dateigrenzen.
   **Audio-Delay:** Roh-Streams (.ac3/.eac3/.m4a) tragen keine Timestamps — hat die
   Quellspur einen Startversatz (`minimum_timestamp` aus `mkvmerge -J`, bei BD-Remuxes
   üblich), wird er beim Mux per `--sync 0:{delay_ms}` auf die Stereo-Eingabe übertragen,
   sonst droht A/V-Desync.
   **Default-Flags:** mkvmerge kopiert die Flags der Quellspuren unverändert und meldet
   doppelte/fehlende Defaults **nicht** — `commands.py` setzt deshalb
   `--default-track-flag {id}:yes|no` **deterministisch für jede übernommene Audiospur
   der Quelldatei** und für die neuen Stereo-Dateien, sodass exakt eine Default-Audiospur
   entsteht (die Invariante sichert das Modell, die Tests verifizieren die Ausgabe).
3. **Fortschritt:** FFmpeg wie bisher über `-progress pipe:1`; mkvmerge über `--gui-mode`
   (`#GUI#progress 42%`-Zeilen; Fallback: normale `Progress:`-Zeilen parsen) — damit bekommt
   auch reiner Remux einen echten Fortschrittsbalken.
4. Temp-Dateien in `%TEMP%` je Job-UUID (nicht mehr im App-Ordner), Aufräumen im `finally`;
   unvollständige Ausgaben werden gelöscht (wie heute).

---

## 5. Umsetzungsphasen

Jede Phase endet lauffähig und wird einzeln verifiziert. Reihenfolge = Risiko zuerst dort
senken, wo alles andere draufbaut.

### Phase 0 — Fundament (klein, aber Pflicht)
- `git init` + `.gitignore` (tools/, temp, __pycache__, config.json) — das Projekt ist bisher **kein** Git-Repo; ohne Historie ist der Umbau unnötig riskant
- Modulstruktur aus 4.1 anlegen, bestehenden Code **verhaltensneutral** aufteilen (Logik unverändert kopieren, nur Imports/Struktur)
- `requirements.txt`: `ttkbootstrap>=1.20.4`, `tkinterdnd2` (Pillow kommt als ttkbootstrap-Dependency mit)
- Fixture-Skript `tests/make_fixtures.py`: erzeugt per ffmpeg (`testsrc`/`sine`) + mkvmerge kleine Test-MKVs mit definierten Spurkombis (de/en/fr-Audio 5.1+2.0, Subs, forced, Kommentarspur, `und`-Sprache, ohne-Deutsch-Fall, **eine Audiospur mit Startversatz** via `mkvmerge --sync` für den A/V-Sync-Test)
- **Akzeptanz:** App startet und konvertiert wie vorher; Fixtures existieren

### Phase 1 — Neues Herz: Modell, Planner, Kommandobau (kein UI-Umbau)
- `model.py`, `planner.py`, `commands.py` implementieren + Unit-Tests (Golden-Tests: Fixture-Scan → erwartete Kommandozeilen)
- `runner.py`: bestehende Worker-/Queue-Logik auf FilePlan umstellen; Nur-Remux-Pfad (ein mkvmerge-Lauf) und Multi-Stereo-Pfad; mkvmerge `--gui-mode`-Fortschritt
- Deterministische Default-Flag-Vergabe (`--default-track-flag` für **alle** übernommenen Audiospuren, siehe 4.3) + `--sync`-Delay-Übernahme; Golden-Tests: „genau ein Default nach Kopie+Stereo", „Default wandert bei Abwahl der bisherigen Default-Spur", „Delay bleibt erhalten"
- **Akzeptanz:** Alte UI läuft auf neuer Engine; zusätzlich per Testskript: reiner Remux + „Kopie + Stereo" auf Fixtures korrekt — verifiziert per `mkvmerge -J`/`ffprobe` der **Ausgabe**: Spurzahl, Sprachen, Default-Flags, **`channels == 2` auf jeder neuen Stereospur** (fängt genau die Fehlerklasse des Altcode-Bugs aus 4.3) und erhaltener Startversatz

### Phase 2 — Neue UI-Shell
- `theme.py`: eigenes Dark-Theme registrieren, Checkbox-Image-Fabrik, Farbsemantik (grün=behalten, akzent=neu, rot=entfernen — identisch in Tabelle, Vorschauzeile, Log)
- `track_table.py` als **eigenständiges, gekapseltes Widget** zuerst (größtes UI-Risiko): Checkbox-Spalte, Aktions-Overlay, Gruppierung Video/Audio/Subs, Tastatur (Leertaste), Hover-Cursor; separat testbar per Demo-Skript
- `main_window.py`: Kopfzeile mit Status-Chips, vereinheitlichte Dateiliste (Tabs entfallen), Regel-Zeile, kontextabhängiges Stereo-Panel, sprechender START-Button, Floodgauge, einklappbares Log, Leerzustand-Dropzone
- Auto-Fenstergröße nach 2.3 + dunkle Titelleiste + HiDPI
- **Akzeptanz:** kompletter Durchstich Datei→Tabelle→Start→Ausgabe in neuer UI; Fenster passt sich Leerzustand/Normalzustand/Log-auf sauber an; 1366×768-Laptop-Check

### Phase 3 — Regel-Engine & Profile
- Regel-Editor-Dialog, mitgelieferte Profile, Persistenz in `config.json` (einmaliger Import der alten `config.ini`-Werte)
- Live-Anwendung auf alle Dateien, R/M-Herkunft, Schutz manueller Overrides, ⚠-Abweichler-Erkennung, „Muster auf alle anwenden" (Typ+Sprache-Matching)
- Vorschauzeile + Plan-Spalte + START-Text aus dem echten Plan generiert
- **Akzeptanz:** Batch mit heterogenen Fixtures: Regel greift, Abweichler markiert, Override überlebt Regelwechsel, „↺ Regel" setzt nur M-Zeilen zurück

### Phase 4 — Tool-Downloader & Onboarding
- `downloader.py` nach Spezifikation in Abschnitt 6 (nur stdlib!)
- Onboarding-Karte (3.3), Download-Dialog mit zwei Floodgauges, Abbruch, Retry, Quellen-/Lizenzanzeige (GPL-Hinweis + Quelltext-Links — auch wenn beim Nachladen keine Distributionspflicht besteht, gehört der Hinweis zum guten Ton)
- Tool-Manager-Dialog ersetzt den permanenten Pfad-Frame; „Auf Update prüfen" (Versions-Endpoints vergleichen)
- **Akzeptanz:** tools/ leeren → Erststart-Flow → Download → Selbsttest (`--version`) → Chips grün → Konvertierung läuft. Fehlerfälle: Netz aus (klare Meldung + manueller Pfad), Checksummen-Mismatch (Abbruch + einmal Retry), 404 (Browser-Fallback auf downloads.html)

### Phase 5 — Feinschliff („höchstes Niveau" passiert hier)
- Tooltips mit Klartext-Subtext an jeder Option („Downmix Pro: Center lauter für Dialogverständlichkeit")
- Toasts statt Erfolgs-Messageboxen; [Ordner öffnen] nach Abschluss; Taskbar-Flash bei Fertig im Hintergrund
- Doppelklick = Spur umbenennen; Kontextmenüs; „Nur diese Spur behalten"
- Pro-Datei-Ausgabe: Kontextmenü „Ausgabename/-ort ändern…" in der Dateiliste (ersetzt die freie Ausgabewahl des alten Einzeldatei-Tabs; `FilePlan.output_path` existiert dafür bereits)
- Leere-/Fehler-/Warte-Zustände konsistent; alle Strings einmal durchgehen (eine Terminologie: Spur, behalten, entfernen, verlustfrei)
- Optional (wenn Spurgrößen in `mkvmerge -J`-Statistiken vorhanden): „ca. −1,1 GB"-Schätzung in der Vorschauzeile, sonst weglassen — nie raten
- **Akzeptanz:** 15-Minuten-Fremdtest: eine unbeteiligte Person muss ohne Erklärung eine Serie auf „nur Deutsch + Stereo-Kopie" bringen können

### Phase 6 — Packaging & Verteilung
- PyInstaller `--onefile --noconsole` + Spurwerk-Icon; tkinterdnd2-Hook prüfen; HTTPS im gefrorenen Build testen (Zertifikat-Store)
- ~~**Zwei Builds:** x64 (primär) und x86 (für 32-bit-Windows; braucht eine separate 32-bit-Python-Installation zum Bauen)~~ — *aufgehoben am 29.09.2026: nur x64*
- Versionsnummer in App + Fenstertitel; kurzes README (Screenshots, Tool-Quellen, Lizenzen)
- Virenscanner-Realität: unsignierte PyInstaller-EXEs schlagen gern an → Hinweis im README; optional später Code-Signing
- **Akzeptanz:** frische Windows-VM ohne Python: EXE starten → Onboarding → Download → Konvertierung erfolgreich

**Grobe Aufwandsverteilung** (relativ): Phase 1 ≈ 25%, Phase 2 ≈ 30%, Phase 3 ≈ 15%,
Phase 4 ≈ 15%, Phase 0/5/6 zusammen ≈ 15%. Die Phasen 1–4 sind einzeln pausierbar —
nach jeder Phase existiert eine nutzbare App.

---

## 6. Tool-Downloader — Detailspezifikation

Komplett **ohne Drittabhängigkeiten** (urllib.request, gzip, xml.etree, hashlib, zipfile).
Der ganze Ablauf wurde in der Recherche real durchgespielt (Download → Hash → Extrakt → Start).

```
MKVToolNix:
 1. GET latest-release.xml.gz → gzip → XML → version (z.B. "99.0")
 2. zip_url = f".../windows/releases/{v}/mkvtoolnix-64-bit-{v}.zip"
 3. GET f".../{v}/sha256sums.txt" → Zeile des ZIP → Soll-Hash
 4. Stream-Download in tools/.dl/mkvtoolnix.zip.part (1-MB-Chunks,
    sha256 im Stream mitrechnen, Fortschritt aus Content-Length)
 5. Hash-Vergleich (Mismatch → löschen, 1× Retry, dann Fehler)
 6. zipfile: NUR Member "mkvtoolnix/mkvmerge.exe" + "mkvtoolnix/mkvextract.exe"
    per z.open() + shutil.copyfileobj flach nach tools/ (kein Vollentpacken der 226 MB)
 7. Selbsttest: "tools/mkvmerge.exe --version" → "mkvmerge v99.0 …" parsen, anzeigen

FFmpeg:
 1. Primär gyan.dev essentials.zip; Soll-Hash aus <url>.sha256 (nur Digest);
    Version aus /release-version
 2. Bei Netz-/HTTP-Fehler: Fallback BtbN latest win64-gpl.zip + checksums.sha256
    (Format "hash  name" → beide Parser)
 3. Extraktion per Suffix-Match: Member endet auf "bin/ffmpeg.exe" / "bin/ffprobe.exe"
    (Top-Ordner ist bei gyan versioniert!) → flach nach tools/
```

*Aufgehoben am 29.09.2026 — es gibt nur noch x64, der Downloader lädt immer die x64-Builds:*
Architektur-Wahl: Der Downloader ermittelt zuerst die **OS-Architektur** (64/32-bit-Windows,
nicht die Python-Bitness) und wählt danach die URL-Sätze aus 2.1 — auf 32-bit-Windows also
`mkvtoolnix-32-bit-{v}.zip` und den sudo-nautilus-win32-Build (Member-Pfade sind identisch).

Querschnitt: User-Agent-Header setzen (CDN-Schutz), Timeout 30 s, Download abbrechbar
(Cancel-Flag wie bei der Konvertierung), alles im Worker-Thread über die bestehende
Queue → UI. Fehlerpfade: kein Netz / 404 (Zeitfenster direkt nach Release) / Proxy →
klare Meldung + Buttons [Erneut versuchen] [Download-Seite im Browser öffnen]
[Pfade selbst wählen…]. `ffplay.exe` wird nicht mehr benötigt (nirgends im Code verwendet).

---

## 7. Risiken & Gegenmaßnahmen (konsolidiert aus allen Entwürfen)

| Risiko | Gegenmaßnahme |
|---|---|
| Treeview-Zell-Interaktion (Overlay-Combobox) ist die häufigste Quelle subtiler UI-Bugs | `track_table.py` als isoliertes Widget mit eigenem Demo-/Testskript **zuerst** bauen; Overlay schließt bei Scroll/Resize/Fokusverlust/Dateiwechsel; Alternativ-Pfad: `tk.Menu` an der Zelle (simpler, immer korrekt positioniert) |
| Auto-Resize flackert / überläuft kleine Bildschirme | nur wachsen, Strukturwechsel-getriggert, Deckel 90% Bildschirm, Nutzer-Resize gewinnt; 1366×768 als Pflicht-Testfall |
| Download-URLs/Muster ändern sich irgendwann | Version immer dynamisch auflösen (XML/Plaintext-Endpoints), 404-Fallback auf Browser, manueller Pfad bleibt gleichwertiger Weg; URL-Konstanten zentral in `downloader.py` |
| mkvmerge-Kommandobau mit mehreren Eingaben (Default-Flags, `--track-order` über Dateigrenzen) | Invarianten im Modell erzwingen (genau 1 Default-Audio), Golden-Tests der Kommandozeilen, Ausgabe-Verifikation per `mkvmerge -J` in den Tests |
| Batch-Overrides an Track-IDs binden → Fehlzuordnung bei heterogenen Dateien | Overrides strikt pro Datei; „auf alle anwenden" nur über Typ+Sprache; Abweichler sichtbar (⚠) statt stiller Heuristik |
| Funktionszuwachs zerstört die heutige 3-Klick-Einfachheit | Default-Profil reproduziert den Alt-Workflow exakt; Fremdtest in Phase 5 als hartes Kriterium |
| „→ Stereo ersetzen" verwirft Originalton endgültig | Default in Regeln ist „Kopie + Stereo"; einmalige (nicht nervende) Bestätigung, wenn ALLE Originale ersetzt würden |
| 50+ Dateien: Scan-Dauer | Scan-Queue mit begrenzter Parallelität, Abbruch, sichtbarer Pro-Datei-Status |
| Virenscanner/SmartScreen beim Downloader & bei der verteilten EXE | Checksummen-Prüfung + klare Fehlertexte; README-Hinweis; Code-Signing als spätere Option |

---

## 8. Getroffene Entscheidungen (Veto jederzeit möglich)

1. **Ein Modus, keine Einfach/Experten-Umschaltung** — die Profil-Combobox + Klartext-Vorschau leisten den „Einfach-Modus" ohne zweite Ansicht (Divergenz-Risiko).
2. **Stack bleibt Python + ttkbootstrap** — ein Rewrite (z.B. PySide6) brächte hübschere Widgets, kostet aber den kompletten funktionierenden Unterbau; „höchstes Niveau" wird hier über Layout-Disziplin, eigenes Theme, Farbsemantik und Micro-UX erreicht. Die Recherche bestätigt: alles Geplante ist mit ttkbootstrap 1.20.4 machbar.
3. **MKVToolNix als ZIP** (nicht 7z + py7zr) — stdlib genügt, py7zr scheitert nachweislich am BCJ2-Filter.
4. **FFmpeg primär von gyan.dev** (echtes Stable-Release, kleiner), BtbN als Fallback.
5. **config.ini → config.json** (Profile brauchen verschachtelte Strukturen); Alt-Werte werden einmalig importiert.
6. **Neue Stereospur erbt die Sprache der Quellspur** statt fix „ger/eng".
7. **`ffplay.exe` entfällt** aus Tools-Erkennung und Download (ungenutzt).
8. **Stereo-Extraktion direkt per FFmpeg aus der MKV** (`-map 0:a:n`) — `mkvextract` fällt aus der Pipeline (wird aber weiter mit heruntergeladen: kostet im selben ZIP nichts und hält die Tür für spätere Extraktions-Features offen).
9. **Kapitel und Anhänge werden immer übernommen** — bewusste Vereinfachung gegenüber MKVToolNix; eine An-/Abwahl dafür kann später als kleine Option nachgerüstet werden.
10. **Die ↑/↓-Batch-Umsortierung des Altcodes entfällt** — die Reihenfolge beeinflusst nur die Abarbeitung, nicht das Ergebnis; wer sie braucht, bekommt später Drag-Sort in der Dateiliste.
11. **Ein globales Stereo-Setting pro Job** (Codec/Bitrate/Preset gelten für alle Stereo-Aktionen) — unterschiedliche Codecs pro Spur wären Modell- und UI-Komplexität ohne realen Anwendungsfall.

12. **Branding: „Spurwerk"** (entschieden 2026-07-04). Fenstertitel „Spurwerk", Beschreibung „Spurwerk — MKV Remuxer & Audio-Studio". Namens-Kollisionscheck durchgeführt: frei („Stellwerk" war der erste Kandidat, ist aber von Modellbahn-Software besetzt). Bildmarke: Gleisplan mit abzweigender violetter Spur (= die neue Stereospur); Brand-Sheet mit Wortmarke, Icon-Konzept und allen Tokens liegt als Artifact vor.
13. **Akzentfarbe: „Nachtviolett"** (entschieden 2026-07-04). Theme-Name `spurwerk-dark`; Grund ist ein violett-stichiges Schwarz statt neutralem Grau. Kerntoken: primary `#8b5cf6`, selectbg/hover `#6d28d9`, bg `#14121a`, Fläche/inputbg `#1c1926`, border `#2c2838`, fg `#e9e6f2`, success `#2dd4a7`, danger `#ff5370`, warning `#f5a623`, info `#4aa8ff`. **Farb-Semantik:** Violett ist exklusiv für „neu erzeugt" reserviert (Stereo-Spur, Primäraktionen), Grün = behalten/verlustfrei, Rot = entfernen — identisch in Tabelle, Vorschau, Log und Toasts.
14. ~~**32-bit-Windows wird unterstützt**~~ — **aufgehoben am 29.09.2026 (Nutzerentscheidung): nur noch der 64-bit-Build.** Ein x86-Release wurde nie veröffentlicht, und die 32-bit-FFmpeg-Quelle ist seit 2023 ungepflegt und ohne Prüfsummen. Ursprüngliche Entscheidung (entschieden 2026-07-04): Verifiziert am 04.07.2026: MKVToolNix gibt es als 32-bit-ZIP im selben URL-Muster (`mkvtoolnix-32-bit-{v}.zip`, 84,4 MB, HTTP 200); für FFmpeg existiert kein gyan.dev/BtbN-32-bit-Build mehr, aber der aktiv gepflegte Community-Fork **sudo-nautilus/FFmpeg-Builds-Win32** liefert eine stabile latest-URL (`.../releases/latest/download/ffmpeg-master-latest-win32-gpl.zip`, 92,7 MB, HTTP 200). Der Downloader wählt die Quelle nach **OS-Architektur** (nicht Python-Bitness — ein 32-bit-Prozess auf 64-bit-Windows startet problemlos 64-bit-Tools; entscheidend ist `PROCESSOR_ARCHITEW6432`/`platform.machine()` des OS). Phase 6 liefert zwei PyInstaller-Builds (x64 + x86; der x86-Build braucht eine 32-bit-Python-Installation). Restrisiko: Der win32-FFmpeg-Fork ist ein Community-Projekt — beim Implementieren prüfen, ob dessen Release eine `checksums.sha256` mitliefert; sonst Download ohne Hash-Prüfung nur nach Nutzer-Bestätigung + manueller Pfad als Ausweg.
