# Changelog

Alle nennenswerten Änderungen an Spurwerk. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (MAJOR.MINOR.PATCH).

## [Unreleased]
_(hier landen Änderungen für die nächste Version)_

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
