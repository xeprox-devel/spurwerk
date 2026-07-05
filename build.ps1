# Spurwerk-Release-Build (Windows x64)
# Aufruf:  .\build.ps1        ->  dist\Spurwerk.exe
#
# Fuer den x86-Build dieselben Schritte in einer 32-bit-Python-Installation
# ausfuehren (venv32 anlegen, requirements installieren, build.ps1 starten).

$python = ".\.venv\Scripts\python.exe"

# TMDb-Key (optional) aus der Umgebung in die gitignorte Key-Datei schreiben,
# damit der gebaute Release ihn eingebaut hat - der Quellcode bleibt key-frei.
if ($env:SPURWERK_TMDB_KEY) {
    "KEY = `"$($env:SPURWERK_TMDB_KEY)`"" | Out-File -Encoding utf8 "core\_apikey.py"
    Write-Host "TMDb-Key eingebettet (core\_apikey.py)."
} else {
    Write-Host "Kein SPURWERK_TMDB_KEY gesetzt - Release ohne eingebauten Key."
}

& $python assets\make_version_info.py

# Optionales Key-Modul nur einbinden, wenn es existiert (try/except-Import
# wird von PyInstaller sonst nicht automatisch erkannt)
$extra = @()
if (Test-Path "core\_apikey.py") { $extra += "--hidden-import=core._apikey" }

& $python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name "Spurwerk" `
    --icon "spurwerk.ico" `
    --add-data "spurwerk.ico;." `
    --version-file "build\file_version_info.txt" `
    --collect-all tkinterdnd2 `
    @extra `
    main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build fertig: dist\Spurwerk.exe"
    Write-Host "Hinweis: tools/ wird NICHT eingebettet - die EXE laedt die"
    Write-Host "Tools beim Erststart selbst (GPL-sauber fuer die Verteilung)."
}
