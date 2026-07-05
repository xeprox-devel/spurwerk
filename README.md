# Spurwerk

**Der einfache Weg, MKV-Filme aufzuräumen — ohne Qualitätsverlust.**

Spurwerk nimmt deine MKV-Dateien und macht sie so, wie du sie brauchst:
unnötige Sprachen raus, auf Wunsch eine kompatible Tonspur dazu, und
4K-Filme mit Farbstich-Problemen werden repariert. Das Videobild wird
dabei **niemals neu berechnet** — was reinkommt, kommt in Originalqualität
wieder raus. Deine Originaldateien bleiben immer unangetastet.

---

## Was kann Spurwerk?

**🧹 Ausmisten (verlustfrei):**
Ein Film hat 6 Sprachen und 12 Untertitel, du brauchst nur Deutsch?
Häkchen setzen, Start — fertig in Sekunden. Das nennt man „Remuxen":
Es wird nur neu verpackt, nichts umgerechnet.

**🔊 Kompatible Tonspur erzeugen:**
Dein Fernseher, deine Soundbar oder dein Tablet kann kein DTS oder kein
7.1? Spurwerk erzeugt aus der Originalspur eine Dolby-Digital- (AC3/E-AC3)
oder AAC-Spur — wahlweise in 5.1 oder Stereo, mit hochwertigen
Downmix-Profilen. Das Original kannst du behalten oder ersetzen.

**🎨 4K-Farbstich reparieren (Dolby Vision):**
Manche 4K-MKVs (Dolby Vision Profil 7) zeigen auf vielen Geräten einen
Grün-/Lilastich. Spurwerk erkennt das automatisch und entfernt auf
Wunsch die Dolby-Vision-Daten — übrig bleibt normales HDR10, das überall
läuft. Auch das: 100 % verlustfrei, Atmos-Ton und Untertitel bleiben.

**🗂 Viele Dateien auf einmal:**
Ganze Serienstaffel reinziehen, Regeln einmal festlegen (oder pro Datei
anpassen), ein Klick auf Start — Spurwerk arbeitet die Liste ab.
Erledigte Dateien verschwinden aus der Warteschlange, Fehler bleiben
sichtbar.

## So startest du

1. **`Spurwerk.exe` herunterladen** und in einen beliebigen Ordner legen
   (keine Installation nötig).
2. **Beim ersten Start** bietet Spurwerk an, die benötigten freien
   Werkzeuge (MKVToolNix, FFmpeg — zusammen ca. 195 MB) automatisch
   herunterzuladen. Ein Klick, einmalig, fertig.
3. **MKV-Dateien ins Fenster ziehen.** Spurwerk analysiert sie, wendet
   dein Profil an (z. B. „Deutsch bevorzugt") und zeigt dir in Klartext,
   was passieren wird. Passt? **Start.**

> **Windows-Hinweis:** Beim ersten Start kann Windows SmartScreen warnen
> („Unbekannter Herausgeber") — das ist bei kostenlosen Tools ohne
> teures Code-Zertifikat normal. Über „Weitere Informationen →
> Trotzdem ausführen" geht es weiter.

## Die Bedienung in einem Bild

- **Dateiliste oben:** deine Warteschlange. Jede Datei kann ihr eigenes
  Profil und Zielformat haben — die Plan-Spalte zeigt es an.
- **Profil-Zeile:** wählt die Automatik („Deutsch bevorzugt",
  „Nur remuxen — alles behalten", …). Über **Bearbeiten…** baust du
  eigene Profile, **Auf alle Dateien** überträgt die Einstellung.
- **Spurtabelle:** das Herzstück. Jede Zeile eine Spur — Häkchen =
  kommt mit. Klick auf die Aktion-Spalte einer Audiospur:
  *Kopieren*, *Kopie + Konvertierung* oder *Ersetzen*.
  Rechtsklick auf die Videospur: Dolby-Vision-Reparatur.
- **Start-Button:** sagt vorher exakt, was passiert
  („5 Dateien · 12 Spuren verlustfrei · 3 Konvertierungen → AC3 5.1").

## Häufige Fragen

**Werden meine Originaldateien verändert?**
Nein, niemals. Spurwerk schreibt immer neue Dateien (Standard:
`Film_remux.mkv` daneben). Ausgabeort und -name sind änderbar
(Rechtsklick auf die Datei).

**Was heißt „verlustfrei"?**
Beim Remuxen und bei der DV-Reparatur werden Video und Ton bitgenau
kopiert — null Qualitätsverlust. Nur wenn du bewusst eine neue Tonspur
erzeugst (z. B. DTS → Dolby Digital), wird diese eine Spur neu kodiert.

**Warum gibt es 7.1 nur als AAC?**
AC3 endet technisch bei 5.1, und FFmpeg kann kein echtes E-AC3 7.1
erzeugen. Spurwerk bietet ehrlich nur an, was wirklich geht — und
rechnet nie künstlich hoch (kein Fake-7.1).

**Warum ist „DV entfernen" bei manchen Dateien gesperrt?**
Dolby Vision **Profil 5** hat kein HDR10-Fallback — ohne die DV-Daten
wären die Farben kaputt. Spurwerk sperrt das und erklärt warum, statt
eine unbrauchbare Datei zu erzeugen.

**Welche Systemvoraussetzungen?**
Windows 10/11 (64-bit). Die Werkzeuge lädt Spurwerk selbst.

## Die Werkzeuge dahinter

Spurwerk orchestriert bewährte freie Software: **MKVToolNix**
(mkvtoolnix.download), **FFmpeg** (gyan.dev/BtbN) und **dovi_tool**
(quietvoid) — alle unter GPL/Open-Source-Lizenzen. Spurwerk liefert sie
nicht mit, sondern lädt sie auf Wunsch von den offiziellen Quellen,
geprüft per SHA-256. Für „DV → Profil 8.1 (MP4)" wird zusätzlich
**MP4Box** (gpac.io) benötigt — einmal installieren, Pfad im
⚙-Werkzeuge-Dialog wählen.

---

Version: siehe Titelleiste · Änderungen: [CHANGELOG.md](CHANGELOG.md) ·
Für Entwickler: [DEVELOPMENT.md](DEVELOPMENT.md)

© xeproX · gebaut mit Python & ttkbootstrap
