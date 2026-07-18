# ============================================================
# GERAM · setup.ps1  (Windows, PowerShell)
# Prepara la parte que corre en Windows: GERAM CORE OS (editor + IA +
# extensiones) en el navegador. Crea el venv, instala dependencias y el .env.
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# IRIS (voz, control del escritorio) y el runner en sandbox son de Linux — en
# Windows no se instalan por defecto (ver README).
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { Write-Error "No encuentro python. Instala Python 3.11+ y reintenta."; exit 1 }
Write-Host "==> Python: $(& $py.Source --version)"

Write-Host "==> [1/2] GERAM CORE OS (:8000) — venv + dependencias"
& $py.Source -m venv geram-core-os\venv
& geram-core-os\venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& geram-core-os\venv\Scripts\python.exe -m pip install -r geram-core-os\requirements.txt

Write-Host "==> [2/2] Configuracion"
if (Test-Path .env) {
  Write-Host "    .env ya existe — lo dejo como esta."
} else {
  Copy-Item .env.example .env
  Write-Host "    creado .env desde la plantilla (todas las claves son opcionales)."
}

Write-Host ""
Write-Host "OK. Para arrancar GERAM CORE OS en el navegador:"
Write-Host "  cd geram-core-os"
Write-Host "  .\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Write-Host "  luego abri http://localhost:8000 en Chrome/Edge."
Write-Host ""
Write-Host "Nota: IRIS y el runner en sandbox son de Linux; no se instalan aqui."
