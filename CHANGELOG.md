# Changelog

Alle nennenswerten Änderungen an Spurwerk. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (MAJOR.MINOR.PATCH).

## [Unreleased]

### Behoben
- **Spurtabelle verschwand bei knapper Fensterhöhe** (z. B. Laptop mit
  1366×768, Protokoll offen, Audio-Konvertierung sichtbar). Die Höhe wird
  jetzt nach Vorrang verteilt: Zuerst schrumpft das Protokoll bis auf
  seine Kopfzeile, dann die Spurtabelle von 6 auf 4 Zeilen, zuletzt die
  Dateiliste auf 3. Start, Fortschritt, Profil, Audio-Konvertierung,
  Legende und Hinweise werden nie beschnitten. Mindest- und Fenstergröße
  richten sich nach dem Gezeigten, der Skalierung und dem Arbeitsbereich
  des Monitors — nichts rutscht mehr unter die Taskleiste. Ist der
  Bildschirm dafür zu klein, weicht das Protokoll ganz; die Statuszeile
  sagt es.
- **Das Fenster wächst beim Laden von Dateien wieder automatisch mit** —
  seit 2.1.0 hielt Spurwerk die eigenen Größenanpassungen fälschlich für
  einen Eingriff des Nutzers und stellte das Mitwachsen ein.
- **Fenster auf einem Monitor links oder oberhalb des Hauptmonitors**
  öffnet wieder an seinem Platz. Die gespeicherte Position wurde nicht
  erkannt (Tk schreibt sie als „+-1750+60“), das Fenster landete an der
  automatischen Position — die Korrektur aus 2.0.0 griff dadurch nie.

## [2.1.0] — 2026-09-29

### Hinzugefügt
- **Werkzeuge aktualisieren:** Der Werkzeuge-Dialog (⚙) vergleicht die
  installierten Versionen von MKVToolNix, FFmpeg und dovi_tool mit den
  offiziellen Quellen und zeigt pro Werkzeug „✓ aktuell" oder „⬆ Version
  … verfügbar". Ein Klick aktualisiert einzeln, „Alle aktualisieren"
  alles auf einmal — wie beim Erst-Download SHA-256-geprüft. Findet die
  Startprüfung neue Versionen, erscheint oben ein ▲-Hinweis, der direkt
  in den Dialog führt. Entwicklungs-Builds (z. B. FFmpeg-Git-Snapshots)
  werden ehrlich als „nicht vergleichbar" geführt statt geraten.
  Die Prüfung hängt am bestehenden Schalter „Beim Start nach Updates
  suchen" im Über-Dialog.
- **Dateien auf einem nicht verbundenen Laufwerk (USB/NAS)** gehen nicht
  mehr verloren: Sie stehen nach dem Start mit „Laufwerk fehlt" in der
  Liste und behalten ihre Einstellungen. Ist das Laufwerk wieder da, liest
  Spurwerk sie von selbst ein — nach wenigen Sekunden, beim Zurückkehren
  ins Fenster sofort. Ist das Laufwerk da, die Datei aber nicht
  (verschoben oder gelöscht), steht „Datei fehlt" in der Liste. Der Start
  überspringt solche Dateien mit Hinweis im Protokoll; „Entfernen" nimmt
  einzelne heraus, „Leeren" fragt vorher nach — auch, solange die Prüfung
  noch läuft. Geprüft wird im Hintergrund, ein nicht erreichbares
  Netzlaufwerk bremst den Start nicht mehr aus.
- **USB-Platte unter anderem Laufwerksbuchstaben** (F: statt E:): Spurwerk
  findet die wartende Datei dort selbst und liest sie mit allen
  Einstellungen ein, am selben Platz der Warteschlange; eine manuell
  gewählte Ausgabe auf der alten Platte zieht mit. Übernommen wird nur ein
  eindeutiger Fund (gleiche Dateigröße) — liegt die Datei auf mehreren
  Laufwerken, sagt das Protokoll es an und die Zeile wartet weiter. Ein
  getrenntes Netzlaufwerk, das nicht antwortet, hält weder die Suche noch
  die Prüfung der übrigen Zeilen auf.
- **„Datei neu zuordnen …"** (Rechtsklick auf eine Zeile mit „Laufwerk
  fehlt" oder „Datei fehlt"): Datei am neuen Ort auswählen, die
  Einstellungen bleiben. Steht die gewählte Datei schon in der
  Warteschlange, ändert sich nichts.
- **Fester Ausgabeordner auf einem getrennten NAS** lässt den
  Programmstart nicht mehr hängen und wird nicht mehr still auf
  „Quellordner" zurückgesetzt: Der Ordner bleibt eingestellt, der Knopf
  zeigt „⚠ nicht erreichbar", das Protokoll sagt es an, und Start
  verweigert mit klarer Meldung, bis der Ordner wieder erreichbar ist
  (Spurwerk prüft das selbst) oder ein anderer gewählt wird. Auch die
  Frage „Ausgabedatei existiert bereits" prüft jetzt im Hintergrund.
  Ein gelöschter Ausgabeordner auf einem vorhandenen Laufwerk bleibt
  ebenfalls eingestellt und wird beim Start wieder angelegt.

### Geändert
- **dovi_tool-Downloads werden jetzt per SHA-256 geprüft** (Prüfsumme aus
  den GitHub-Release-Daten) — bisher kam dovi_tool als einziges Werkzeug
  ungeprüft.
- **Update-Hinweise oben einheitlich mit ▲** (neue Spurwerk-Version wie
  neue Werkzeuge) — das bisherige Zeichen ⭑ wurde in der fetten
  Kopfzeilen-Schrift nur als winziger Punkt dargestellt.

### Entfernt
- **32-bit-Windows (x86):** Spurwerk gibt es nur noch als 64-bit-EXE. Der
  angekündigte, aber nie veröffentlichte x86-Build entfällt samt den
  32-bit-Werkzeugquellen (darunter ein seit 2023 nicht mehr gepflegter
  32-bit-FFmpeg-Build ohne Prüfsummen).

### Behoben
- **Werkzeuge-Dialog: Meldungen verschwanden nach etwa einer Sekunde** —
  „Fertig" und vor allem Download-Fehler wurden von der anschließenden
  Neuprüfung sofort wieder gelöscht. Sie bleiben jetzt stehen.
- **Werkzeug-Downloads während einer laufenden Verarbeitung** sind jetzt
  gesperrt (mit Hinweis) — vorher konnte der Dialog eine gerade genutzte
  EXE ersetzen wollen.
- **Werkzeuge-Dialog während eines Downloads geschlossen:** Das
  Hauptfenster erfährt jetzt trotzdem von den neu installierten
  Werkzeugen (vorher „mkvmerge fehlt" bis zum Neustart). Der Dialog prüft
  beim Öffnen außerdem selbst nach, statt einem veralteten Stand zu trauen.
- **Keine 100-MB-Reste mehr in tools/:** Scheitert das Entpacken (EXE in
  Benutzung, Platte voll), wird die halbe `.part`-Datei aufgeräumt.
- **Downloads ohne Prüfsumme werden angesagt** statt still als
  „SHA-256-geprüft" zu gelten (nur, wenn eine Prüfsummen-Datei gerade
  nicht abrufbar ist). dovi_tool bekommt seine Prüfsumme notfalls von der
  normalen Release-Seite, wenn die GitHub-API ausgelastet ist.
- **Updates tauschen ein Werkzeug-Paket ganz oder gar nicht** (z. B.
  ffmpeg + ffprobe) — scheitert ein Schritt, bleibt der alte Stand
  vollständig erhalten. Das klappt auch, während Spurwerk gerade Dateien
  analysiert: Die alte EXE wird beiseitegelegt statt überschrieben.
- **Ein FFmpeg-Update weicht nie auf einen Entwicklungs-Snapshot aus:**
  Die GitHub-Ersatzquelle gibt es nur noch bei der Ersteinrichtung und
  nur, wenn gyan.dev nicht erreichbar ist — ein Prüfsummen-Fehler wird
  gemeldet, nicht umgangen.
- **„Alle aktualisieren" installiert kein bewusst weggelassenes
  dovi_tool mit**; Knöpfe sind während eines Downloads sichtbar gesperrt,
  und eine gescheiterte Update-Prüfung zeigt nicht mehr den alten Stand
  an, als wäre gerade geprüft worden.
- **Selbst gewähltes FFmpeg:** Ein `ffprobe.exe` im selben Ordner wird
  mitgenommen (vorher blieb die DV-Analyse gesperrt). Aktualisieren
  verwirft die eigenen Pfade für ffmpeg UND ffprobe gemeinsam — kein
  Versionsmix mehr.
- **Pfad selbst wählen in einem schreibgeschützten Ordner** tat
  scheinbar nichts; jetzt gilt der Pfad für die Sitzung, mit Hinweis.
- Über-Dialog: sagt jetzt richtig, dass nur die Werkzeuge geladen werden
  und die übrigen Bibliotheken eingebaut sind.
- **„DV/HDR → HDR10" behält das Timing der Videospur:** Startet das Bild
  in der Quelle später als der Ton, hat es Lücken oder eine wechselnde
  Bildrate, laufen Bild und Ton nach dem Umbau nicht mehr auseinander. Bei
  gleichmäßiger Bildrate bleibt die exakte Bildrate erhalten.
- **Wiederhergestellte Jobs** werden wieder nach den Regeln ihres eigenen
  Profils aufgebaut — vorher galt das gerade aktive Profil, und die Datei
  bekam andere Spuren, als ihr Profilname versprach. Eine Ausgabe ohne
  Standard-Audiospur ist ausgeschlossen.
- **Die Warteschlange bleibt erhalten,** auch wenn Spurwerk vor dem Ende
  der Analyse beendet wird; Dateien mit Scan-Fehler bleiben samt
  Einstellungen gespeichert. Ist mkvmerge neu eingerichtet, werden
  fehlgeschlagene Dateien automatisch neu analysiert.
- **Keine Ausgabe überschreibt mehr die Quelle eines anderen Jobs**
  (z. B. „Film.mkv" und „Film_remux.mkv" im selben Ordner): Vor dem Start
  nennt eine Meldung beide Dateien, im Lauf wird der Job übersprungen.
- **Drag & Drop** übernimmt Dateien und Ordner mit geschweiften Klammern
  im Namen (Plex/Jellyfin: „Dune (2021) {imdb-tt1160419}.mkv"), statt sie
  still zu verwerfen; Elemente ohne MKV meldet das Protokoll als
  übersprungen. Lässt sich die Drag-&-Drop-Erweiterung nicht laden,
  startet Spurwerk trotzdem (Dateien dann über die Buttons).
- **Eine Tonspur „Director's Cut"** gilt nicht mehr als Kommentarspur und
  wird nicht mehr verworfen.
- **Fehler und Warnungen von mkvmerge/mkvextract** nennen im Protokoll
  jetzt den echten Grund (bisher blieb der Text leer).
- **Konvertierte Spuren** heißen nach ihrem echten Layout („AAC 5.1"
  statt „AAC 7.1" bei einer 5.1-Quelle; eigene Namen bleiben), Mono bleibt
  Mono, und die volle Sprachkennung (es-419, pt-BR) bleibt erhalten.
- **Einstellungen (config.json)** werden atomar gespeichert, die vorige
  gute Fassung bleibt als config.json.bak. Eine beschädigte Datei
  verhindert den Start nicht mehr und wird als config.json.defekt-…
  beiseitegelegt statt still überschrieben; eine config.json aus einer
  neueren Version setzt nicht mehr alle Profile zurück.
- **Titel-Bereinigung:** Eine Zahl im Titel gilt nicht mehr als
  Erscheinungsjahr („Blade Runner 2049", „Wonder Woman 1984"), „Film.2025.mkv"
  wird erkannt, keine offene Klammer mehr. TMDb übernimmt ohne Jahres-
  treffer nur noch einen passenden Titel (auch mit Akzenten und „&"), und
  ein vertippter eigener API-Key wird durch den eingebauten ersetzt — mit
  Hinweis im Protokoll.
- **Kleinere Bedienfehler:** Klick auf eine noch analysierende Datei
  bearbeitet jetzt diese Datei; F5 übernimmt einen gerade getippten
  Spurnamen; ein Start direkt nach einem Lauf wiederholt die fertigen
  Dateien nicht; „Dateinamen bereinigen" bei schon sauberem Namen scheitert
  nicht mehr an „identisch mit der Quelle"; eine Störung bei der Analyse
  lässt keine Datei mehr auf „wird analysiert …" hängen; lassen sich
  Einstellungen nicht speichern (schreibgeschützter Ordner), sagt das
  Protokoll es einmalig.
- **Beim Start springt das Fenster nicht mehr** — kein leeres
  Mini-Fenster vorab, die dunkle Titelleiste bleibt.
- Der TMDb-Titelabgleich läuft erst nach der Analyse und bremst bei
  langsamem Netz keine weiteren Scans mehr.

### Entwicklung
- `tests/smoke_ui.py` leitet die Konfiguration in einen Temp-Ordner um —
  der Sichtcheck überschrieb bisher die echte `config.json`.
- **build.ps1** meldet „Build fertig" nur nach einem echten Neubau (bricht
  bei fehlender .venv, falschem Python oder Fehlern ab und prüft die
  EXE-Version), verträgt Vorabversionen wie „2.1.0-rc1" und sagt beim
  TMDb-Key die Wahrheit; `.\build.ps1 -OhneKey` baut ohne eingebauten Key.
- **Reproduzierbarer Build:** Abhängigkeiten mit Obergrenzen (ttkbootstrap
  1.x, tkinterdnd2 0.6.x, Pillow ≤ 12), PyInstaller 6.22.3 gepinnt;
  DEVELOPMENT.md nennt Python 3.14 (64 bit, nicht 3.14t).
- EXE gut 4 MB kleiner (ungenutzte Pillow-Codecs raus, UPX aus); jedes
  Release enthält THIRD_PARTY_LICENSES.txt mit den Lizenzhinweisen aller
  eingebetteten Komponenten.
- 452 automatisierte Tests (vorher 123), die Oberflächen-Tests
  eingeschlossen.

## [2.0.0] — 2026-07-06

### Geändert
- **„DV/HDR → HDR10" entschärft jetzt auch die Untertitel-Automatik:**
  Bild-Untertitel (PGS/VobSub) verlieren im Kompatibilitätsmodus ihre
  Default-/Forced-Markierung — sie bleiben vollständig in der Datei,
  springen aber nicht mehr automatisch an. Der Grund aus der Praxis:
  Eine automatisch aktive Bild-Spur zwingt Player wie Jellyfin zum
  Einbrennen (Transkodierung des kompletten 4K-Videos) — die Wiedergabe
  startet dann je nach Server gar nicht. Gibt es eine Textspur gleicher
  Sprache, übernimmt die die Automatik (bevorzugt die passende
  Forced-Spur) — Zwangs-Untertitel funktionieren damit weiter, nur eben
  als Text im Direct Play. Vorschau und Protokoll sagen an, was passiert.
- **Radikale Vereinfachung der Video-Optionen:** Es gibt nur noch zwei
  Wahlmöglichkeiten pro Datei — **Original kopieren** oder
  **„DV/HDR → HDR10"** (Dolby-Vision-Daten entfernen, reines HDR10 im
  MKV). Jede Ausgabe läuft damit garantiert überall — auch auf
  Einplatinen-Playern (ROCK64 & Co.) und älteren TVs; Untertitel, Ton
  und Kapitel bleiben automatisch 1:1 erhalten. HDR10+ bleibt erhalten,
  Profil 5 bleibt mit Begründung gesperrt (kein HDR10-Fallback — ohne
  DV-Daten wären die Farben kaputt).

- **Große Konsistenz-Runde durch die komplette Oberfläche:** eine
  Sprache (durchgängig „Werkzeuge", „Untertitel", „Protokoll" — nie
  mehr Tools/Subs/Log; echte Pluralformen statt „Datei(en)"), ein
  Design (Akzent-Cyan als eine Linie für Buttons, Fortschritt und
  Protokoll — Lila/Indigo wurde komplett aus der Farbwelt entfernt;
  Grün/Rot/Amber bleiben Ergebnis, Fehler, Warnung), und
  Selbsterklärung überall: Tooltips auf allen Symbolen, „▶ Start (F5)"
  zeigt sein Tastenkürzel, eine Legende erklärt die Spurtabelle
  (✓/＋/★/R/M), die Vorschau zeigt bei festem Ausgabeordner den
  kompletten Zielpfad.

### Entfernt
- **Die DV-Ausgabemodi „DV → Profil 8.1 (MP4)" und „DV → Profil 8.1
  (MKV)"** samt OCR-Untertitel-Pipeline (PGS → Text) und
  Tesseract-Integration — ersatzlos. Der ehrliche Grund: Praxistests
  auf realen Geräten zeigten, dass DV-Ausgaben je nach Player
  unabspielbar sind (MP4 mit Textspur: Datei startet gar nicht;
  DV-Reste im MKV: Ton ohne Bild). Statt Spezialwegen mit Fußnoten
  gibt es jetzt die Garantie-Schiene: Kopieren = alles bleibt,
  „DV/HDR → HDR10" = läuft überall.

### Behoben
- **Ausgabe-Menü: Häkchen zeigten den gespeicherten Zustand nicht**
  (Dateinamen bereinigen, TMDb) — die Menü-Variablen wurden vom
  Garbage Collector eingesammelt, bevor das Menü sie lesen konnte.
  Jetzt zeigen die Optionen ihren echten Zustand.
- **„Neue Spur als Standard-Audiospur"** zeigte beim Wechsel zwischen
  Dateien nicht den Zustand der gerade markierten Datei.
- **„Ausgabename/-ort ändern …" war während eines laufenden Jobs
  möglich** — Vorschau und tatsächliche Ausgabe konnten auseinanderlaufen.
  Jetzt gesperrt, solange verarbeitet wird.
- **Strg+O funktionierte mit aktivem Caps Lock falsch** (öffnete den
  Ordner- statt des Datei-Dialogs).
- **Fenster-Merken auf mehreren Monitoren:** Die gespeicherte Position
  wurde beim Start auf den Hauptmonitor gezwungen (Zweitmonitor links
  war unmöglich); der Maximiert-Zustand ging verloren. Beides behoben.

### Qualität
- 123 automatisierte Tests (Unit + End-to-End mit echten Tools),
  inklusive Nachbau des realen Jellyfin-Falls, der die neue
  Untertitel-Automatik motiviert hat.

## [1.1.0] — 2026-07-05

### Hinzugefügt
- **Update-Hinweis**: Spurwerk prüft beim Start still, ob eine neuere
  Version veröffentlicht wurde, und zeigt sie als klickbaren Hinweis oben
  im Fenster an. Genau eine Anfrage an GitHub, ohne Tracking; abschaltbar
  im „Über"-Dialog.
- **Fenstergröße und -position werden gemerkt** und beim nächsten Start
  wiederhergestellt (mit Sicherung gegen abgesteckte Monitore).
- **Tastenkürzel**: `F5` startet, `Strg+O` fügt Dateien hinzu,
  `Strg+Umschalt+O` einen Ordner, `Entf` entfernt die markierte Datei.

### Behoben
- **Videomodus verschmutzte den Dateinamen** nicht mehr: Beim „DV
  entfernen → HDR10" hängte Spurwerk „ [HDR10]" an den Namen (analog
  „ [DV8.1]" bei Profil 8.1). Der saubere Titel bleibt jetzt sauber — der
  Modus zeigt sich nur noch an der Endung (`.mkv` bzw. `.mp4`).

### Geändert
- **Timing-Absicherung beim DV-Remux**: Dem roh extrahierten HEVC-Stream
  wird die exakte Quell-Bildrate mitgegeben (`--default-duration`), damit
  mkvmerge sie nie raten muss. Konservativ nur bei erkannten
  Standard-Bildraten (Film/TV) — VFR/Exotisches bleibt unangetastet.

## [1.0.1] — 2026-07-05

### Hinzugefügt
- **Dolby Vision → Profil 8.1 (MP4)** — ganz ohne MP4Box: FFmpeg (8.1+)
  schreibt die DV-Signalisierung selbst. MP4-taugliches Audio (AAC/AC3/
  E-AC3, inkl. Atmos) wird 1:1 kopiert, TrueHD/DTS nach E-AC3 gewandelt,
  Text-Untertitel zu mov_text; Bild-Untertitel (PGS) werden mit Hinweis
  weggelassen. Der Video-Codec ist damit pro Datei frei wählbar:
  **Kopieren** (DV + HDR10 unangetastet), **DV → HDR10** oder
  **DV → 8.1 (MP4)**.
- **Sitzung wird gemerkt**: Offene Jobs samt Konfiguration (Profil,
  Video-Modus, Spur-Overrides, Ausgabename) überleben das Schließen und
  sind beim nächsten Start wieder da; erledigte Jobs verschwinden.
- **Fester Ausgabeordner** bleibt dauerhaft gespeichert (grün umrandeter
  „Ausgabe"-Button).
- **Dateinamen bereinigen** (optional): „Film.2025.UHD.WEB-DL…mkv" →
  „Film.mkv".
- **Online-Titelabgleich (TMDb, optional)**: liefert den exakten Filmtitel
  (z. B. „Obsession – Du sollst mich lieben"). Ein **eingebauter API-Key**
  kann mitgeliefert werden (wie bei Jellyfin) — dann ohne Registrierung;
  ein eigener Key hat Vorrang. Ohne Key/Netz greift die Offline-Bereinigung.
  Es wird nur der Suchtitel + Jahr gesendet.
- Modus A zeigt den PGS-Untertitel-Hinweis schon in der Vorschau.

### Behoben
- **DV-Remux-Ausgabe lief auf wählerischen Hardware-Playern nicht**
  (Rockchip/ARM-Boxen wie ROCK64), obwohl der Stream valide war und auf
  PC-Playern (VLC) lief. Die HEVC-Extraktion nutzt jetzt **mkvextract**
  (nativer MKVToolNix-Round-Trip, exakte Stream-Struktur) statt ffmpegs
  umgeschriebenem Bitstream; ffmpeg bleibt Fallback.
- **DV → 8.1 (MP4) konnte abstürzen**, wenn nach der Modus-Wahl noch
  Profil oder Ausgabeordner geändert wurde (Ausgabepfad fiel auf `.mkv`
  zurück, der MP4-Mux scheitert im Matroska-Container). Die Endung wird
  jetzt hart erzwungen.
- **DV-Analyse blieb gesperrt, wenn `ffprobe.exe` fehlte**, obwohl die
  FFmpeg-Zeile „gefunden" zeigte. Die FFmpeg-Zeile prüft ffprobe jetzt mit
  und lädt es bei Bedarf nach.
- **Sitzungs-Wiederherstellung und früher Drag&Drop scheiterten am Scan**,
  weil die Tool-Erkennung noch lief. Scans warten jetzt darauf.

### Geändert
- Bereinigte/TMDb-Dateinamen ohne „_remux"-Suffix; der Name enthält nur
  noch den Titel (kein Jahr).

## [1.0.0] — 2026-07-04

Erste öffentliche Version. Spurwerk ist der Nachfolger des internen
„MKV Audio Remuxer Pro" — komplett neu aufgebaut.

### Funktionen
- **Verlustfreier Remux**: Spuren per Checkbox an-/abwählen, ein einziger
  mkvmerge-Durchlauf, Video/Audio bleiben bitgenau unangetastet
- **Audio-Konvertierung** pro Spur: Kopieren, Kopie + Konvertierung oder
  Ersetzen — Ziel AC3/E-AC3/AAC in 2.0, 5.1 oder 7.1 (7.1 nur AAC,
  FFmpeg kann kein E-AC3 7.1; nie Upmix), Downmix-Presets Loro/Pro/
  LFE-Boost, A/V-Sync bleibt erhalten (Startversatz wird übernommen)
- **Sprachregel-Profile** („Deutsch bevorzugt" u. a.) mit Klartext-Satz,
  automatischer Vorauswahl, ⚠-Abweichler-Markierung und geschützten
  manuellen Eingriffen (R/M-Herkunft); eigene Profile speicherbar
- **Job-Queue wie MKVToolNix**: jede Datei trägt ihre eigene Konfiguration
  (Profil + Zielformat), ein Start arbeitet alles ab, Erledigtes verlässt
  die Liste, Fehler bleiben sichtbar
- **Dolby-Vision-Kompatibilitäts-Remux (verlustfrei)**: DV Profil 7
  erkennen und auf Wunsch entfernen → reines HDR10, Atmos/TrueHD und
  Untertitel bleiben 1:1; Profil 5 wird mit Begründung gesperrt.
  DV → Profil 8.1 (MP4) vorbereitet (benötigt manuell installiertes
  MP4Box/GPAC)
- **Ein-Klick-Einrichtung**: MKVToolNix, FFmpeg und dovi_tool werden auf
  Wunsch automatisch geladen (SHA-256-geprüft, passend zur Windows-
  Architektur 64/32-bit) — nichts wird mitgeliefert (GPL-sauber)
- Dunkles „Nachtcyan"-Design, Fenster passt sich dem Inhalt an,
  Fortschritt pro Datei + gesamt, farbiges Protokoll

### Qualität
- 64 automatisierte Tests (Unit + End-to-End mit echten Tools auf
  generierten Test-MKVs), Multi-Agent-Code-Review mit 17 behobenen
  Funden vor dem Release
