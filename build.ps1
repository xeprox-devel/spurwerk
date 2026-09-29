# Spurwerk-Release-Build (Windows x64)
# Aufruf:  .\build.ps1           ->  dist\Spurwerk.exe + dist\THIRD_PARTY_LICENSES.txt
#          .\build.ps1 -OhneKey  ->  dasselbe, sicher ohne eingebauten TMDb-Key
#
# Spurwerk gibt es nur als 64-bit-EXE (kein x86-Build, Entscheidung vom
# 29.09.2026).
#
# Erwartet .venv im Projektordner (Python 3.14, siehe DEVELOPMENT.md).
# Bricht beim ersten Fehler ab - "Build fertig" erscheint nur, wenn die EXE
# in diesem Lauf neu entstanden ist und die Version aus version.py traegt.

param([switch]$OhneKey)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    # Alte Artefakte zuerst weg: auch ein frueh abgebrochener Lauf (keine .venv,
    # falsches Python) darf keine EXE und keine Versionsdatei eines frueheren
    # Builds hinterlassen, die dann ausgeliefert wird.
    foreach ($alt in @("dist\Spurwerk.exe", "dist\THIRD_PARTY_LICENSES.txt", "build\file_version_info.txt")) {
        if (Test-Path $alt) { Remove-Item $alt -Force }
    }

    $python = ".\.venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        throw "Build-Python fehlt: $python - erst die .venv anlegen (siehe DEVELOPMENT.md)."
    }

    # Native Aufrufe: allein der Exit-Code zaehlt (PyInstaller loggt nach stderr,
    # das ist kein Fehler). Ein nicht startbarer Aufruf gilt ebenfalls als Fehler.
    function Invoke-Python([string]$Schritt, [string[]]$Argumente) {
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = -1
        & $python @Argumente
        if ($LASTEXITCODE -ne 0) {
            throw "$Schritt fehlgeschlagen (Exit-Code $LASTEXITCODE) - Build abgebrochen."
        }
    }

    # Reproduzierbar nur mit dem dokumentierten Python (der py-Launcher waehlt
    # u. U. das free-threaded 3.14t)
    $check = "import sys, sysconfig; print('Build-Python', sys.version); " +
             "ok = sys.version_info[:2] == (3, 14) and not sysconfig.get_config_var('Py_GIL_DISABLED'); " +
             "sys.exit(0 if ok else 'Build-Python muss CPython 3.14 sein (nicht free-threaded)')"
    Invoke-Python "Python-Pruefung" @("-c", $check)
    $version = Invoke-Python "Versionsabfrage" @("-c", "from version import __version__; print(__version__)")
    $version = "$version".Trim()

    # TMDb-Key (optional) aus der Umgebung in die gitignorte Key-Datei schreiben,
    # damit der gebaute Release ihn eingebaut hat - der Quellcode bleibt key-frei.
    # Eine vorhandene core\_apikey.py wird nie geloescht (sie ist oft die einzige
    # Kopie des Keys): ohne Variable wird sie eingebettet, mit -OhneKey bleibt
    # sie liegen und PyInstaller laesst das Modul weg. Die Meldung richtet sich
    # nach dem, was tatsaechlich in die EXE kommt.
    $extra = @()
    if ($OhneKey) {
        $extra += @("--exclude-module", "core._apikey")
        Write-Host "-OhneKey: Release ohne eingebauten Key (core\_apikey.py bleibt unangetastet)."
    } else {
        if ($env:SPURWERK_TMDB_KEY) {
            "KEY = `"$($env:SPURWERK_TMDB_KEY)`"" | Out-File -Encoding utf8 "core\_apikey.py"
            Write-Host "TMDb-Key eingebettet (aus SPURWERK_TMDB_KEY, core\_apikey.py)."
        } elseif (Test-Path "core\_apikey.py") {
            Write-Host "TMDb-Key eingebettet (aus vorhandener core\_apikey.py, SPURWERK_TMDB_KEY nicht gesetzt)."
            Write-Host "Release ohne Key: .\build.ps1 -OhneKey"
        } else {
            Write-Host "Kein SPURWERK_TMDB_KEY und keine core\_apikey.py - Release ohne eingebauten Key."
        }
        # core/tmdb.py importiert das Key-Modul optional per try/except
        if (Test-Path "core\_apikey.py") { $extra += "--hidden-import=core._apikey" }
    }

    Invoke-Python "Versionsdatei" @("assets\make_version_info.py")

    # --noupx: keine UPX-Kompression (Virenscanner-Fehlalarme, langsamerer Start).
    # Die Pillow-Codecs fuer AVIF und WebP (zusammen gut 4 MB in der EXE) nutzt
    # Spurwerk nicht - es zeichnet nur Oberflaechenbilder; Pillow laedt diese
    # Format-Plugins ohnehin nur optional (ImportError wird abgefangen).
    Invoke-Python "PyInstaller" (@("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole", "--noupx",
        "--name", "Spurwerk",
        "--icon", "spurwerk.ico",
        "--add-data", "spurwerk.ico;.",
        "--version-file", "build\file_version_info.txt",
        "--collect-all", "tkinterdnd2",
        "--exclude-module", "PIL._avif",
        "--exclude-module", "PIL._webp") + $extra + @("main.py"))

    if (-not (Test-Path "dist\Spurwerk.exe")) {
        throw "PyInstaller meldet Erfolg, aber dist\Spurwerk.exe fehlt."
    }
    $exeVersion = (Get-Item "dist\Spurwerk.exe").VersionInfo.ProductVersion
    if ($exeVersion -ne $version) {
        throw "dist\Spurwerk.exe traegt Version '$exeVersion', version.py sagt '$version'."
    }

    Invoke-Python "Lizenzhinweise" @("assets\third_party_licenses.py")

    Write-Host ""
    Write-Host "Build fertig: dist\Spurwerk.exe ($version)"
    Write-Host "Zum Release gehoert auch dist\THIRD_PARTY_LICENSES.txt (Lizenzhinweise"
    Write-Host "der eingebetteten Komponenten) - beide Dateien hochladen."
    Write-Host "Hinweis: tools/ wird NICHT eingebettet - die EXE laedt die"
    Write-Host "Werkzeuge beim Erststart selbst von den offiziellen Quellen."

} finally {
    Pop-Location
}
