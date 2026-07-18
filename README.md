# GERAM

Entorno de desarrollo local con dos aplicaciones que arrancan juntas:

- **GERAM CORE OS (A.R.E.S.)** — el entorno de desarrollo: editor Monaco (estilo VS Code) con explorador de archivos, terminal en sandbox, control de versiones, e importación de **extensiones de VS Code** (temas, snippets, gramáticas). Backend FastAPI en el puerto **8000**, envuelto en una ventana **Electron**.
- **IRIS** — el asistente conversacional con voz y ~30 mini-agentes (calendario, Telegram, Notion, recordatorios, proactividad…). Backend Python en el puerto **8010**.

Todo corre **localmente** en tu máquina. Las apps se comunican entre sí en `localhost`.

```
  GERAM.desktop / geram.sh
        │
        ├─► IRIS            server.py            :8010   (asistente + agentes)
        └─► GERAM CORE OS   geram-core-os/       :8000   (FastAPI + Electron / A.R.E.S.)
```

> Repositorio **privado**. No incluye secretos: `.env` y `credenciales/` están en `.gitignore` — cada persona pone los suyos (ver [Configuración](#configuración)).

---

## Sistemas operativos

Las rutas son **portables** (relativas al repo y a tu carpeta personal), así que
funciona sin editar nada sin importar el usuario o dónde lo clones. Qué corre en
cada sistema:

| | **Linux (Mint / XFCE / etc.)** | **Windows** |
|---|---|---|
| Editor A.R.E.S. + IA + extensiones | ✅ (Electron o navegador) | ✅ (en el navegador) |
| Ícono de escritorio (un clic) | ✅ (`scripts/install-desktop.sh`) | ➖ (se abre en el navegador) |
| Asistente IRIS: voz, control del escritorio, portapapeles | ✅ | ➖ Linux-first (usa utilidades de Linux) |
| Runner de código en sandbox | ✅ (bubblewrap) | ➖ Linux-only |

En **Windows** usás la parte principal (editor + proveedores de IA +
extensiones) corriendo el backend de CORE OS y abriéndolo en el navegador. IRIS
y las features que controlan el escritorio son de Linux.

## Requisitos

- **Python 3.11+**
- **Node.js 18+** y **npm** (para la ventana Electron y sus assets de Monaco; en Windows en navegador no hace falta Electron)
- Opcionales, según qué features uses:
  - **[Ollama](https://ollama.com)** — para modelos de IA locales (sin API key).
  - `xclip`/`xsel` (Linux) — historial de portapapeles de IRIS.
  - Cuentas/API keys de los proveedores e integraciones que quieras (todo opcional).

---

## Instalación

```bash
git clone https://github.com/Bendxld/geramv3.git
cd geramv3

# 1) Backend de IRIS (:8010)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# 2) Backend de GERAM CORE OS (:8000)
cd geram-core-os
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# 3) Ventana Electron (instala Electron y prepara los assets de Monaco)
cd electron
npm install        # el postinstall prepara Monaco automáticamente
cd ../..

# 4) Configuración: copia la plantilla y rellena lo que uses
cp .env.example .env
$EDITOR .env
```

> **En Windows:** activá el venv con `venv\Scripts\activate` (en vez de
> `source venv/bin/activate`), y podés **saltarte el paso 3 (Electron)** — se usa
> en el navegador (ver [Cómo se usa → Windows](#windows-editor--ia--extensiones-en-el-navegador)).
> Solo necesitás el venv de `geram-core-os` para la parte principal.

---

## Configuración

Copia `.env.example` a `.env`. **Todas las claves son opcionales** — sin ninguna, GERAM arranca igual; cada integración se activa cuando pones su clave. Lo más común:

| Clave(s) | Para qué |
|---|---|
| `GEMINI_FREE_1…5`, `GROQ_FREE_1…5` | Proveedores de IA de IRIS (round-robin entre varias keys) |
| `OLLAMA_MODEL` | Modelo local de Ollama |
| `NOTION_API_KEY`, `TELEGRAM_BOT_TOKEN`, `SPOTIFY_*`, `GOOGLE_CALENDAR_CREDENTIALS_PATH` … | Integraciones de los agentes de IRIS |
| `PIPER_VOICE_PATH`, `EDGE_TTS_VOICE`, `WHISPER_MODEL_SIZE` | Voz (TTS/ASR) de IRIS |

**Proveedores de IA de A.R.E.S. (CORE OS)** se configuran **desde la interfaz**, no en `.env`: abre **Settings → API IA** y agrega tu key por proveedor (Anthropic/Claude, OpenAI, Gemini, Groq, Mistral, DeepSeek, xAI, Perplexity, Together, OpenRouter, Cerebras, Fireworks, Moonshot). Si pones **varias keys del mismo proveedor**, se usan en **round-robin**. Las credenciales quedan solo en tu equipo.

---

## Cómo se usa

### Linux

```bash
./geram.sh                      # lanzador unificado: IRIS (si hace falta) + A.R.E.S. (Electron)
./scripts/install-desktop.sh    # (opcional) crea el ícono "GERAM" con TU ruta real automáticamente
```

- **A.R.E.S. / CORE OS**: la ventana principal (editor + workspace).
- **IRIS**: panel secundario del asistente. Su HUD también responde en `http://localhost:8010`.
- Reiniciar todo: `./reiniciar_geram.sh`

### Windows (editor + IA + extensiones, en el navegador)

No hace falta Electron: se corre el backend y se abre en el navegador.

```powershell
cd geram-core-os
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Luego abrí **http://localhost:8000** en Chrome/Edge. Tenés el editor, los
proveedores de IA (Settings → API IA) y las extensiones. IRIS y el runner en
sandbox son de Linux.

---

## Funcionalidades

- **Editor de desarrollo (A.R.E.S.)**: Monaco, explorador, Source Control, Problems, preview en vivo, y un ejecutor de código en sandbox (Bubblewrap).
- **Proveedores de IA con round-robin**: 14 proveedores de texto seleccionables por rol (IRIS/A.R.E.S.), con pool de credenciales que rota entre varias keys.
- **Agentes**: dashboard para ver los agentes de IRIS y **suspender/reactivar** los de fondo; y un *Agent Factory* para **crear tus propios agentes y skills**.
- **Extensiones de VS Code**: importa un `.vsix` (o JSON) y usa sus **temas, snippets, gramáticas y configuraciones de lenguaje** en el editor; o crea los tuyos. *(Monaco no ejecuta el código de una extensión — comandos, vistas o language servers —, solo sus contribuciones declarativas.)*

---

## Estructura del repo

```
server.py              IRIS (FastAPI, :8010)
agents/                mini-agentes de IRIS
config/                configuración de IRIS
geram-core-os/         GERAM CORE OS / A.R.E.S.
  app/                 backend FastAPI (:8000) — API, providers, extensiones…
  static/              frontend del HUD (Monaco, paneles, vendored runtimes)
  electron/            ventana Electron + política de seguridad/CSP
geram.sh               lanzador unificado
requirements.txt       deps de IRIS   ·   geram-core-os/requirements.txt  deps de CORE OS
.env.example           plantilla de configuración (copiar a .env)
```

---

## Notas

- **Local-first / privado**: nada de tu código o credenciales sale del equipo salvo que tú configures una integración externa.
- **Sin secretos en el repo**: `.env`, `credenciales/`, `venv/`, `node_modules/`, `modelos/` están en `.gitignore`. Cada persona los genera localmente.
