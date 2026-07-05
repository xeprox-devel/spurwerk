# Spurwerk-Release-Build (Windows x64)
# Aufruf:  .\build.ps1        ->  dist\Spurwerk.exe
#
# Fuer den x86-Build dieselben Schritte in einer 32-bit-Python-Installation
# ausfuehren (venv32 anlegen, requirements installieren, build.ps1 starten).

$python = ".\.venv\Scripts\python.exe"

& $python assets\make_version_info.py

& $python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name "Spurwerk" `
    --icon "spurwerk.ico" `
    --add-data "spurwerk.ico;." `
    --version-file "build\file_version_info.txt" `
    --collect-all tkinterdnd2 `
    main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build fertig: dist\Spurwerk.exe"
    Write-Host "Hinweis: tools/ wird NICHT eingebettet - die EXE laedt die"
    Write-Host "Tools beim Erststart selbst (GPL-sauber fuer die Verteilung)."
}
