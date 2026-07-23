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

Write-Host "==> [1/4] GERAM CORE OS (:8000) — venv + dependencias"
& $py.Source -m venv geram-core-os\venv
& geram-core-os\venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& geram-core-os\venv\Scripts\python.exe -m pip install -r geram-core-os\requirements.txt

Write-Host "==> [2/4] Configuracion"
if (Test-Path .env) {
  Write-Host "    .env ya existe — lo dejo como esta."
} else {
  Copy-Item .env.example .env
  Write-Host "    creado .env desde la plantilla (todas las claves son opcionales)."
}

# pdftotext (poppler) habilita adjuntar PDFs al chat. bubblewrap no aplica en
# Windows: el sandbox del runner es de Linux. Solo informamos; no instalamos
# nada por tu cuenta.
Write-Host "==> [3/4] Paquetes del sistema (PDFs)"
if (Get-Command pdftotext -ErrorAction SilentlyContinue) {
  Write-Host "    OK pdftotext ya esta instalado."
} else {
  Write-Host "    Falta pdftotext (poppler) — sin el no se pueden adjuntar PDFs al chat."
  if (Get-Command scoop -ErrorAction SilentlyContinue) {
    Write-Host "    Para instalarlo:  scoop install poppler"
  } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Host "    Para instalarlo:  choco install poppler"
  } else {
    Write-Host "    Instalalo con scoop ('scoop install poppler'), con choco"
    Write-Host "    ('choco install poppler'), o descarga poppler para Windows y"
    Write-Host "    agrega su carpeta bin al PATH."
  }
  Write-Host "    (Opcional: el resto de la app funciona sin el.)"
}

# Ollama: chat local sin API key (opcional). Con tus keys no hace falta.
# 'ollama pull' trae la ultima version del modelo, asi que tambien lo actualiza.
Write-Host "==> [4/4] Ollama (chat local, sin API key — opcional)"
$modelo = "llama3.2:1b"
$envLine = Select-String -Path .env -Pattern '^OLLAMA_MODEL=(.+)$' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($envLine) { $modelo = $envLine.Matches[0].Groups[1].Value.Trim() }

if (Get-Command ollama -ErrorAction SilentlyContinue) {
  Write-Host "    OK Ollama ya esta instalado."
  $r = Read-Host "    Bajo/actualizo el modelo '$modelo' (~1.3 GB)? [s/N]"
  if ($r -match '^[sSyY]') {
    try { ollama pull $modelo } catch { Write-Host "    No se pudo bajar el modelo. Luego: ollama pull $modelo" }
  } else {
    Write-Host "    Saltado. Para bajarlo luego: ollama pull $modelo"
  }
} else {
  Write-Host "    Ollama no esta instalado. Sin el, para chatear necesitas una API key (Gemini/Groq gratis)."
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $r = Read-Host "    Instalo Ollama ahora con winget? [s/N]"
    if ($r -match '^[sSyY]') {
      try {
        winget install --id Ollama.Ollama -e --source winget
        Write-Host "    Instalado. Reabri la terminal y corre:  ollama pull $modelo"
      } catch { Write-Host "    No se pudo instalar. Descargalo de https://ollama.com/download" }
    } else {
      Write-Host "    Saltado. Para instalarlo: winget install Ollama.Ollama  (o https://ollama.com/download)"
    }
  } else {
    Write-Host "    Instalalo desde https://ollama.com/download (o 'winget install Ollama.Ollama')."
    Write-Host "    Luego:  ollama pull $modelo"
  }
}

Write-Host ""
Write-Host "OK. Para arrancar GERAM CORE OS en el navegador:"
Write-Host "  cd geram-core-os"
Write-Host "  .\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Write-Host "  luego abri http://localhost:8000 en Chrome/Edge."
Write-Host ""
Write-Host "Nota: IRIS y el runner en sandbox son de Linux; no se instalan aqui."
