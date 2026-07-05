# Changelog

Alle nennenswerten Änderungen an Spurwerk. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (MAJOR.MINOR.PATCH).

## [Unreleased]

### Hinzugefügt
- **Sitzung wird gemerkt**: Offene (noch nicht gestartete) Jobs samt ihrer
  Konfiguration — Profil, Zielformat/Video-Modus, Spur-Overrides,
  Ausgabename — überleben das Schließen und sind beim nächsten Start
  wieder da (Quelldateien werden dafür neu eingelesen). Erledigte Jobs
  verschwinden.
- **Fester Ausgabeordner bleibt dauerhaft** gespeichert und ist am
  grün umrandeten „Ausgabe"-Button erkennbar (bis man ihn ändert).
- **Dateinamen bereinigen** (Ausgabe-Menü, optional): macht aus
  „Film.2025.UHD.WEB-DL.HEVC…mkv" ein sauberes „Film (2025).mkv".
- **Online-Titelabgleich (TMDb, optional)**: liefert den exakten,
  kanonischen Filmtitel (z. B. „Obsession – Du sollst mich lieben
  (2025)"). Wie Jellyfin kann ein **eingebauter API-Key** mitgeliefert
  werden — dann muss sich der Endnutzer NICHT registrieren; ein eigener
  Key ist optional und hat Vorrang. Läuft im Hintergrund beim Scan; ohne
  Key oder bei Netzfehlern greift die Offline-Bereinigung. Es wird nur
  der Suchtitel + Jahr gesendet.
- Modus A zeigt den PGS-Untertitel-Hinweis jetzt schon in der Vorschau
  (nicht erst während des Laufs).

### Behoben
- **Sitzungs-Wiederherstellung und ein Drag&Drop direkt nach dem Start
  scheiterten am Scan**, weil die Tool-Erkennung noch lief. Scans warten
  jetzt auf die fertige Tool-Erkennung.
- **Dolby Vision → Profil 8.1 (MP4)** ist jetzt voll nutzbar — **ohne
  MP4Box**. FFmpeg (8.1+) schreibt die DV-Signalisierung selbst; die
  Pipeline (Video bitgenau + dovi_tool-Konvertierung bei Profil 7 +
  MP4-Mux) läuft mit den Werkzeugen, die Spurwerk ohnehin lädt. MP4-
  taugliches Audio (AAC/AC3/E-AC3, inkl. Atmos in E-AC3) wird 1:1
  kopiert, TrueHD/DTS nach E-AC3 gewandelt, Text-Untertitel zu mov_text;
  Bild-Untertitel (PGS) und nicht MP4-taugliche Spuren werden mit Hinweis
  weggelassen (dafür ist der MKV-Modus da). Quellen, die bereits Profil 8
  sind, werden nur umverpackt (keine RPU-Konvertierung).
- Der Video-Codec ist damit pro Datei frei wählbar: **unangetastet
  übernehmen** (Kopieren, behält DV/HDR10+ komplett), **DV → HDR10**
  (MKV, verlustfrei) oder **DV → 8.1 (MP4)**.

### Behoben
- **DV-Remux-Ausgabe lief auf manchen Hardware-Playern (Rockchip/ARM-Boxen
  wie ROCK64) nicht**, obwohl der Stream valide war und auf PC-Playern
  (VLC) lief. Die HEVC-Extraktion nutzt jetzt **mkvextract** (der native
  MKVToolNix-Round-Trip bewahrt die exakte Stream-Struktur) statt ffmpegs
  umgeschriebenem Bitstream; ffmpeg bleibt Fallback, falls mkvextract fehlt.
- **DV → 8.1 (MP4) scheiterte, wenn nach der Modus-Wahl noch das Profil
  gewechselt, „Auf alle Dateien" geklickt oder der Ausgabeordner geändert
  wurde**: Der Ausgabepfad fiel dann auf `.mkv` zurück, und der MP4-Mux
  (dvh1-Tag/mov_text) bricht im Matroska-Container ab. Jetzt behalten alle
  diese Aktionen die DV-Endung, und der Runner erzwingt zusätzlich hart
  `.mp4` für DV-8.1 bzw. `.mkv` sonst — so kann diese Kombination nie mehr
  crashen.
- **DV-Analyse blieb ohne Grund gesperrt, wenn `ffprobe.exe` fehlte**,
  obwohl die FFmpeg-Zeile „gefunden" zeigte (ältere Downloads hatten
  ffprobe nicht mitgebracht). Die FFmpeg-Zeile prüft jetzt ffprobe mit
  und fordert bei Bedarf zum Neu-Download auf; „Fehlende Tools
  herunterladen" holt ffprobe nach.

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
