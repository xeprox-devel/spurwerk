# Spurwerk

**MKV Remuxer & Audio-Studio für Windows** — Spuren stellen. Verlustfrei.

Spurwerk kuratiert MKV-Dateien in einem Durchgang: unerwünschte Audio- und
Untertitelspuren abwählen (verlustfreier Remux), auf Wunsch aus der
5.1/7.1-Spur eine hochwertige Stereo-Version erzeugen — als zusätzliche
Kopie oder als Ersatz. Eine Sprachregel-Automatik trifft die Auswahl für
ganze Serienstaffeln, jede Datei bleibt per Spurtabelle übersteuerbar.

## Warum noch ein MKV-Tool?

Kein verbreitetes Tool kann alle vier Dinge gleichzeitig:

1. **Verlustfreier Remux** mit Spur-Checkboxen (ein einziger mkvmerge-Lauf,
   Video bleibt bitgenau unangetastet)
2. **Selektive Stereo-Konvertierung pro Spur** im selben Durchlauf
   (Loro/Pro/LFE-Boost-Downmix via FFmpeg; AC3, E-AC3 oder AAC)
3. **Sprachregeln mit Live-Vorschau**: Profile wie „Deutsch bevorzugt"
   füllen die Spurtabelle automatisch, Abweichler werden markiert (⚠),
   manuelle Eingriffe sind geschützt (R/M-Herkunft)
4. **Ein-Klick-Einrichtung**: fehlende Tools (MKVToolNix, FFmpeg) lädt die
   App selbst — mit SHA-256-Prüfung, passend zur Windows-Architektur

Dazu: Batch als Normalfall (eine Datei = Batch mit einem Eintrag, jede
Datei mit eigener Job-Konfiguration), A/V-Sync-erhaltend, deterministische
Default-Spur-Flags, deutsche Oberfläche im dunklen „Nachtcyan"-Theme.

**Dolby-Vision-Kompatibilitäts-Remux (verlustfrei):** 4K-MKVs mit
DV Profil 7 (UHD-Blu-ray) zeigen auf vielen Geräten Grün-/Lilastich.
Spurwerk erkennt das Profil automatisch (Diagnose in der Vorschauzeile)
und entfernt auf Wunsch die DV-Metadaten (RPU+EL) per dovi_tool —
übrig bleibt der bitidentische HDR10-Base-Layer, Atmos/TrueHD und
Untertitel bleiben 1:1 erhalten. Profil 5 (kein HDR10-Fallback) wird
mit Begründung gesperrt statt kaputte Farben zu erzeugen. Das Video
wird dabei **nie** neu encodiert.

## Start

**Aus dem Quellcode** (Python ≥ 3.10):

```
pip install -r requirements.txt
python main.py
```

Beim ersten Start bietet Spurwerk an, MKVToolNix und FFmpeg (~195 MB,
einmalig) in den Ordner `tools/` zu laden. Wer die Tools schon hat, wählt
die Pfade über das ⚙-Symbol.

## Bedienung in einem Satz

MKV-Dateien ins Fenster ziehen → Profil prüfen (der Klartext-Satz sagt,
was passieren wird) → ggf. einzelne Spuren in der Tabelle umstellen →
**Start**.

### Aktionen pro Audiospur

| Aktion | Bedeutung |
|---|---|
| Kopieren | verlustfrei übernehmen |
| Kopie + Stereo | Original behalten **und** Stereo-Version zusätzlich |
| → Stereo ersetzen | nur die Stereo-Version übernehmen |
| Entfernen | Spur fällt weg |

Profile lassen sich unter **Bearbeiten…** anpassen und als eigene Presets
speichern (Werksprofile sind schreibgeschützt).

## Entwicklung

```
pip install -r requirements-dev.txt
python tests/make_fixtures.py     # Test-MKVs erzeugen (braucht tools/)
python -m pytest tests            # 38 Tests: Unit + End-to-End
python tests/smoke_ui.py <ordner> # UI-Screenshots für den Sichtcheck
```

Architektur: `core/` (Datenmodell, Regel-Engine, Kommandobau, Runner,
Downloader — komplett UI-frei und getestet), `ui/` (ttkbootstrap-Widgets),
`config.py` (config.json). Details im [UMSETZUNGSPLAN.md](UMSETZUNGSPLAN.md).

## Hinweise

- **MKVToolNix** (mkvtoolnix.download) und **FFmpeg** (gyan.dev / BtbN)
  sind eigenständige freie Software unter GPL. Spurwerk liefert sie nicht
  mit, sondern lädt sie auf Wunsch von den offiziellen Quellen.
- Unsignierte Downloads/EXEs können von Virenscannern oder SmartScreen
  angehalten werden — die App prüft alle Downloads per SHA-256 gegen die
  offiziellen Prüfsummen.

---
© xeproX · gebaut mit Python, tkinter/ttkbootstrap, MKVToolNix und FFmpeg
