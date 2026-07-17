# GERAM CORE OS v3 — Manual de A.R.E.S.

## Qué es A.R.E.S.

A.R.E.S. es el rol profesional de desarrollo de GERAM CORE OS. Trabaja dentro del workspace autorizado, analiza únicamente los archivos seleccionados y genera propuestas de cambio revisables. No puede aprobar sus propias propuestas ni escribir cambios silenciosamente.

## Flujo recomendado

1. Abre en Explorer los archivos relacionados con el cambio.
2. Guarda tus cambios pendientes con `Ctrl+S`.
3. Agrega a contexto solo los archivos necesarios.
4. Describe un resultado concreto en la barra de A.R.E.S.
5. Genera la propuesta y revisa el diff completo.
6. Aprueba la propuesta si coincide con lo solicitado.
7. Presiona **Apply proposal** como acción separada.
8. Ejecuta diagnósticos o pruebas y revisa el resultado.

## Editor y lenguajes

El workspace usa Monaco y mantiene documentos abiertos en memoria:

- Python con Pyright local.
- JavaScript y TypeScript con servicios de lenguaje locales.
- Validación de HTML, CSS y JSON.
- Resaltado para Markdown, Shell, YAML, Dockerfile y otros archivos de texto.
- Cierre automático de etiquetas en HTML, XML, SVG, Vue, Svelte, JSX y TSX.
- Emmet con `Tab`.
- Problems, búsqueda, Source Control y Preview.

## Propuestas y diffs

Una propuesta contiene un manifiesto de archivos, hashes del estado base y un diff unificado. La aprobación queda ligada exactamente a esa propuesta. Si un archivo cambia antes de aplicar, GERAM devuelve un conflicto en vez de sobrescribirlo.

Las propuestas pueden rechazarse. En cambios de varios archivos, GERAM intenta restaurar lo ya escrito si una escritura posterior falla y reporta de forma explícita cualquier problema de recuperación.

## Ejecución segura

Terminal Watcher admite únicamente perfiles cerrados:

| Perfil | Objetivo |
|---|---|
| Python file | Un archivo `.py` autorizado |
| Python unittest | Pruebas `unittest` de un archivo `.py` |
| Node script | Un archivo `.js` autorizado |

La salida se limita y sanea, los procesos tienen timeout y el usuario puede cancelarlos. Este flujo no acepta comandos de shell arbitrarios.

## Source Control y Preview

Source Control muestra los cambios del repositorio para revisión. Problems recopila diagnósticos locales sin incluir el código en metadatos del DOM. Preview permanece en esta computadora; compartir en línea requiere una acción explícita y puede detenerse desde su panel.

## Proveedores de IA

Configura A.R.E.S. en **Settings → AI APIs**. OpenAI, Gemini y Groq están disponibles. Ollama está preparado como proveedor local preliminar, sin API key, pero permanece deshabilitado en la interfaz hasta completar detección del servicio, modelos instalados y failover.

## Límites de seguridad

- Solo rutas relativas dentro del workspace autorizado.
- Archivos sensibles y rutas bloqueadas quedan fuera del editor y del contexto de IA.
- Se rechazan traversal, rutas absolutas, symlinks inseguros y archivos binarios o demasiado grandes.
- El contenido de los archivos se trata como datos no confiables, no como instrucciones con autoridad.
- Las credenciales nunca se incluyen completas en prompts, respuestas o metadatos públicos.
- A.R.E.S. no puede autoaprobar, autoaplicar ni ampliar los perfiles de ejecución.

---

GERAM CORE OS v3 — A.R.E.S. propone; el usuario decide.
