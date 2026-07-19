# GERAM CORE OS

GERAM CORE OS es un entorno local-first para flujos de desarrollo asistidos en
Linux y Windows 11. En Windows el cliente Electron es nativo y el backend se
ejecuta en WSL2 para conservar el mismo aislamiento Bubblewrap. El backend y el
HUD se sirven únicamente en loopback; no deben exponerse públicamente.

## Alcance validado para Build Week

Esta entrega habilita dos flujos de A.R.E.S.:

1. propuesta de edición sobre archivos existentes, diff revisable, aprobación
   explícita del usuario local y aplicación controlada;
2. ejecución limitada de un archivo de `unittest` Python mediante TestRunSpec,
   Sandbox Guard, Bubblewrap y Terminal Watcher.

No existe shell general, ejecución de argv aportado por el usuario, otros
runners, creación de archivos desde A.R.E.S. ni aprobación automática.

El guion sin credenciales ni red externa está en
[`docs/BUILD_WEEK_DEMO.md`](docs/BUILD_WEEK_DEMO.md).

## Requisitos del sistema

El entorno Linux validado es Linux Mint 22.3, Python 3.12 y Bubblewrap 0.9.0.
El Test Runner requiere específicamente:

- Linux con namespaces de usuario disponibles;
- `python3`, soporte para `venv` y `pip`;
- el ejecutable `bwrap` instalado por el sistema;
- las dependencias fijadas en `requirements.txt`.

Node sólo es necesario para Electron o para la comprobación sintáctica del
cliente. `pytest` no es una dependencia del repositorio y no se usa para la
validación canónica.

`poppler-utils` proporciona `pdftotext`, usado para extraer texto de adjuntos
PDF sin subir el documento a un servicio de extracción. Las imágenes y el
audio sólo se envían cuando el usuario pulsa enviar y el proveedor de I.R.I.S.
declara la modalidad correspondiente. La salida de voz usa la síntesis del
navegador, por lo que no requiere Piper ni un servicio TTS adicional.

### Windows 11

La distribución Windows usa un instalador NSIS y requiere WSL2. Ejecuta una vez
`windows/GERAM-Windows-Setup.ps1` desde PowerShell; el script instala o valida
Ubuntu, Python, Bubblewrap, Poppler, Git y Node dentro de WSL. El instalador
Electron arranca después el backend administrado exclusivamente por `wsl.exe`
y conserva los datos en `~/.local/share/geram-core-os` de ese usuario WSL.

No existe un fallback inseguro a PowerShell para ejecutar A.R.E.S.: si WSL2 o
Bubblewrap faltan, el backend no se inicia. Consulta `windows/README.md`.

En distribuciones basadas en Ubuntu, los paquetes del sistema se pueden
preparar con:

```bash
sudo apt install python3 python3-venv bubblewrap poppler-utils
```

Después, desde la raíz del repositorio:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
/usr/bin/bwrap --version
```

No se necesita ninguna credencial para ejecutar las pruebas o el smoke
sintético. Una propuesta real generada desde el HUD sí requiere configurar el
provider seleccionado por A.R.E.S.; si no está disponible, la propuesta falla
de forma cerrada y no modifica archivos.

## Arranque canónico

El único arranque aprobado para los dos flujos es:

```bash
venv/bin/python launcher.py start
venv/bin/python launcher.py status
```

El launcher fija `127.0.0.1`, deshabilita proxy headers y ejecuta exactamente un
worker. No se debe arrancar manualmente Uvicorn, usar `--workers` con un valor
mayor que 1, activar reload ni publicar el servicio en `0.0.0.0`: las propuestas
y sus tokens viven en la memoria de un único proceso.

Health check local, sin depender de `curl`:

```bash
venv/bin/python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health')))"
```

Apagado:

```bash
venv/bin/python launcher.py stop
```

## Aplicación de escritorio en Linux Mint

La entrada de escritorio versionada está en `linux/geram-core-os.desktop` y usa
el icono local `static/favicon.svg`. Para instalarla sólo para el usuario actual:

```bash
install -Dm644 linux/geram-core-os.desktop ~/.local/share/applications/geram-core-os.desktop
install -Dm755 linux/geram-core-os.desktop "$HOME/Desktop/GERAM CORE OS.desktop"
gio set "$HOME/Desktop/GERAM CORE OS.desktop" metadata::trusted true
update-desktop-database ~/.local/share/applications
```

Después se puede abrir **GERAM CORE OS** desde el menú de aplicaciones o el
icono del escritorio, sin mantener una terminal abierta. El launcher:

- rechaza ejecución como root y valida la raíz exacta del proyecto;
- reutiliza el `BackendLauncher`, su identidad de proceso y su health check;
- no adopta ni detiene el `server.py` antiguo;
- mantiene un lock durante toda la sesión y Electron añade un segundo lock de
  instancia para impedir ventanas duplicadas;
- hereda a Electron sólo variables gráficas permitidas, no credenciales ni
  proxies;
- detiene el backend al cerrar la ventana sólo si esa sesión lo inició.

Cerrar con `Ctrl+Q` o mediante:

```bash
./salir_app.sh
```

Los eventos de arranque se registran sin contenido de archivos, entorno ni
secretos en `logs/desktop_launcher.log` con permisos `0600`. Los fallos se
muestran como una notificación local. La entrada `.desktop` contiene la ruta
absoluta de este checkout; si el repositorio se mueve, se deben actualizar sus
campos `Exec`, `TryExec`, `Icon` y `Path` antes de reinstalarla.

El puerto configurado debe estar libre o pertenecer a una instancia validada de
GERAM CORE OS. Si otro proceso —incluido el `server.py` antiguo— lo ocupa, el
arranque se rechaza y ese proceso no se adopta ni se detiene.

## Flujo de edición aprobado

`POST /api/ares/proposals` lee únicamente los archivos existentes y autorizados
del workspace, solicita una respuesta estructurada al provider y devuelve un
diff unificado sin escribir. La interfaz exige después dos acciones distintas:

1. `POST /api/ares/proposals/approve`, con el digest y los archivos exactamente
   revisados, emite un token de un solo uso;
2. `POST /api/ares/proposals/apply` comprueba nuevamente digest, token y versiones
   base antes de escribir.

Los endpoints mutables requieren host y origen local. Traversal, rutas
absolutas, binarios, symlinks externos, archivos sensibles, campos adicionales,
propuestas caducadas y conflictos se rechazan. Apply sin aprobación no escribe.

Las propuestas se conservan sólo en memoria: caducan a los 300 segundos, hay un
máximo de 32 y desaparecen al reiniciar. El servidor debe seguir usando un solo
worker. Ante un fallo de rollback se devuelve `rollback_failed` y se requiere
revisión manual de los archivos afectados.

## Test Runner Python limitado

`POST /api/ares/tests` acepta exclusivamente:

- `runner: "python_unittest"`;
- un target relativo, existente y terminado en `.py` dentro del workspace;
- un timeout entre 0 y 60 segundos.

El usuario no controla shell, argv, cwd, entorno, mounts ni flags. Bubblewrap es
obligatorio: el workspace entra de sólo lectura, el entorno se reconstruye con
una allowlist, se usa `--unshare-all` sin `--share-net`, y Terminal Watcher
trunca/sanitiza salida y limpia descendientes. Si Bubblewrap no está disponible
o no cumple el prefijo esperado, el resultado es `sandbox_unavailable` y no se
inicia ningún proceso en el host.

## Validación reproducible

Ejecutar cada comando por separado:

```bash
./venv/bin/python -m unittest -v tests.test_ares_edits tests.test_ares_test_runner
./venv/bin/python -m unittest -v tests.test_ares_server_smoke
./venv/bin/python -m unittest -v tests.test_ares_server_smoke
./venv/bin/python -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q app tests
./venv/bin/python -m compileall -q app tests
node --check static/ares-workspace.js
node --test electron/test/*.test.js
git diff --check
```

La suite de Node incluye una prueba de comportamiento que abre Electron y pulsa
Agents y Settings cuando hay una sesión gráfica disponible. No se debe
sustituir la validación Python por `pytest`.

## Workspace y seguridad local

`GERAM_WORKSPACE_ROOT` define el único proyecto visible. Vacío usa
`~/geram-workspace`; el código interno sólo se desbloquea mediante Modo
Desarrollador. Una ruta alternativa debe existir y no ser un directorio
sensible del sistema. El workspace excluye secretos, metadata
Git, bases de datos, logs, dependencias, caches, entornos virtuales y artefactos
runtime. Sólo expone texto UTF-8 y guardado con versiones optimistas.

Las credenciales gestionadas por el credential pool se almacenan fuera del
repositorio mediante el directorio de datos del usuario. La configuración local
en `.env` está ignorada por Git y no debe copiarse a fixtures, documentación,
capturas o guiones de demo.

Las preferencias de VOICE, VISION y OFFLINE, así como la activación del roster,
se guardan con permisos `0600` bajo el directorio de datos del usuario. Cada
cuenta del sistema operativo obtiene su propio estado al instalar o descargar
GERAM; esos estados no se escriben en el repositorio.
El perfil y el progreso de onboarding también viven en
`LOCAL_DATA_DIR/config/user-config.json`; una `.geram-config.json` antigua se
copia automáticamente una vez, sin borrar el original.

## Agentes e integraciones

El roster descubre los módulos Python incluidos en el directorio `agents/` sin
importarlos, por lo que todos se muestran aunque no estén cargados. Además une
las definiciones de Agent Factory almacenadas en el directorio de datos del
usuario. El HUD distingue `available`, `loaded`, sistema y personalizado; no
presenta un módulo instalado como si ya estuviera ejecutándose.
Deshabilitar un agente es una decisión de ejecución: descarga un módulo activo,
bloquea su carga futura y niega contexto e integraciones para esa definición.

El Integration Hub ejecuta acciones delimitadas y reales para Spotify, Notion,
Telegram, Supabase, Google Calendar y un vault local de Obsidian. Toda acción
requiere el permiso específico del agente y las mutaciones requieren aprobación
explícita. Las respuestas nunca incluyen credenciales.

Las comprobaciones contra servicios reales son explícitamente opt-in y sólo
usan acciones de lectura:

```bash
GERAM_LIVE_INTEGRATION_TESTS=1 \
GERAM_LIVE_SUPABASE_TABLE=tabla_de_prueba \
./venv/bin/python -m unittest -v tests.test_integrations_live
```

Se requieren credenciales de prueba para las seis integraciones. La suite
normal omite este módulo y nunca realiza llamadas externas.

## Onboarding, respaldo y recuperación

El primer arranque abre un asistente por usuario que comprueba plataforma,
sandbox, proveedores, Ollama, PDF, cámara y micrófono. Los permisos multimedia
se solicitan sólo al pulsar su prueba y Electron los concede únicamente al HUD
loopback.

Settings → Profile, appearance & privacy permite crear backups y restaurarlos.
Incluyen perfil, estados, roster, agentes/skills personalizados y extensiones
declarativas. Excluyen credenciales, tokens, adjuntos pendientes y archivos del
workspace. Cada restauración valida rutas, tamaños y SHA-256 y crea primero un
backup de seguridad. El diagnóstico local no devuelve rutas ni secretos.

## Releases Linux y Windows

El payload versionado contiene código y wheels Python para instalación offline:

```bash
./venv/bin/python scripts/prepare_release_payload.py --download-wheels
cd electron
npm run dist:linux
# En un runner Windows:
npm run dist:windows
```

Electron Builder genera AppImage, `.deb` y NSIS `.exe`. Una actualización
reemplaza sólo el backend empaquetado, conserva `.env` y mantiene todo el estado
por usuario. `scripts/release_artifacts.py dist` crea `SHA256SUMS`; `--sign`
añade una firma GPG separada y `--verify` comprueba ambos. El workflow de release
acepta `WINDOWS_CSC_LINK`, `WINDOWS_CSC_KEY_PASSWORD` y
`GERAM_GPG_PRIVATE_KEY` como secretos de firma, nunca como archivos del repo.

## Extensiones

GERAM mantiene deliberadamente un modelo declarativo: temas, snippets,
gramáticas TextMate y configuraciones de lenguaje. No ejecuta comandos,
debuggers, language servers ni código arbitrario de extensiones VS Code. Un
extension host completo implicaría otra frontera de procesos y permisos y no se
simula en esta aplicación.

## Limitaciones aceptadas

- El aislamiento de red impide alcanzar el host o redes externas, pero no
  bloquea crear sockets internos en el namespace.
- No hay cuotas kernel/cgroup efectivas para procesos, CPU o memoria; el runner
  limitado es apropiado sólo para la demo local y un workspace de confianza.
- Una avería del filesystem que impida también el rollback puede dejar una
  aplicación multarchivo parcial, reportada como `rollback_failed`.
- Reiniciar el único worker invalida todas las propuestas y aprobaciones.
- No se ha validado esta entrega como servicio público ni como backend
  multiusuario. Windows requiere Windows 11, WSL2 y una distribución compatible.

## Componentes principales

- `launcher.py`: arranque, identidad y cierre del backend local.
- `app/api/ares_edits.py`: contratos de propuestas, aprobación, aplicación y
  endpoint del runner.
- `app/core/workspace.py`: autoridad de rutas y escrituras controladas.
- `app/core/sandbox_guard.py`: validación cerrada del target.
- `app/core/sandbox_backend.py`: prefijo Bubblewrap obligatorio.
- `app/api/terminal_watcher.py`: timeout, cancelación, salida y cleanup.
- `static/ares-workspace.js`: cliente A.R.E.S. con aprobación y apply separados.
