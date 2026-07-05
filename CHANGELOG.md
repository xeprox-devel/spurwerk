# Changelog

Alle nennenswerten Änderungen an Spurwerk. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (MAJOR.MINOR.PATCH).

## [Unreleased]

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
