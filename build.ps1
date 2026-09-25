$ErrorActionPreference = "Stop"

$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt pyinstaller

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
Remove-Item -Force "Umbra PDF.spec" -ErrorAction SilentlyContinue

& $Python packaging/export_icon.py

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "Umbra PDF" `
  --icon "assets/umbra_pdf.ico" `
  --version-file "packaging/version_info.txt" `
  --collect-all fitz `
  --collect-all pymupdf `
  "umbra.py"

Write-Host ""
Write-Host "Build concluido: dist/Umbra PDF.exe" -ForegroundColor Green
