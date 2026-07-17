# Cerebro de Archivos 🧠

Visualizador tipo "cerebro / red neuronal" de tu sistema de archivos. La
carpeta raíz (por defecto, todo tu home) es el núcleo central, las carpetas
de primer nivel orbitan alrededor como sub-núcleos separados ("lóbulos"), y
cada carpeta/archivo cuelga de su padre como una neurona más. Todo se mueve
con una simulación de física (d3-force) y se actualiza solo cuando agregás,
borrás o modificás archivos.

## Instalación

```bash
cd proyectos/cerebro_archivos
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Cómo correrlo

```bash
python server.py
```

Va a imprimir algo como:

```
Vigilando: /home/mauri
Abrí http://127.0.0.1:8420 en tu navegador
Vigilando 297 carpetas (excluyendo ocultas y basura conocida)
```

Abrí esa URL en el navegador y vas a ver el cerebro con sus nodos. También
podés usar el acceso directo de escritorio (`abrir_cerebro.sh` +
`~/Desktop/Cerebro-de-Archivos.desktop`) si lo tenés instalado.

## Qué escanea por defecto

Por defecto vigila **todo tu home** (`~`), mostrando la jerarquía completa:
Documentos, Descargas, Imágenes, Escritorio, tus proyectos, todo.

Para no saturarse con basura de sistema, siempre ignora:

- Cualquier carpeta oculta (nombre que empieza con `.`) — cubre `.cache`,
  `.config`, `.local`, `.git`, `.mozilla`, `.thunderbird`, etc.
- `node_modules`, `__pycache__`, `venv`, `.venv`, `snap`
- `Tela-icon-theme` (un tema de iconos del sistema con ~27.000 archivos que
  no aporta nada a "tus archivos" — si tenés otras carpetas así, sumalas a
  `EXCLUDE_DIR_NAMES` en `server.py`)

## Cómo cambiar la carpeta que vigila

Dos formas, elegí la que prefieras:

**1) Archivo `.env` (recomendado, no toca el código):**

```bash
cp .env.example .env
```

Editá `.env` y cambiá:

```
CEREBRO_WATCH_DIR=/ruta/a/la/carpeta/que/quieras/vigilar
```

**2) Variable de entorno al lanzarlo:**

```bash
CEREBRO_WATCH_DIR=/home/mauri/Documentos python server.py
```

**3) Editando la constante directamente** en `server.py`, bloque `CONFIG` al
principio del archivo (`WATCH_DIR`).

Otras variables configurables (en `.env` o como variables de entorno):

| Variable | Qué hace | Default |
|---|---|---|
| `CEREBRO_WATCH_DIR` | carpeta raíz a vigilar | `~` (todo el home) |
| `CEREBRO_HOST` | host del servidor | `127.0.0.1` |
| `CEREBRO_PORT` | puerto del servidor | `8420` |
| `CEREBRO_MAX_DEPTH` | profundidad máxima de carpetas a escanear | `20` |
| `CEREBRO_MAX_CHILDREN` | hijos máximos por carpeta antes de agrupar en "+N más" | `150` |
| `CEREBRO_MAX_NODES` | tope total de nodos escaneados (protección de rendimiento) | `6000` |

`MAX_NODES` es el total que el backend *conoce*, no lo que se *renderiza*: por
defecto el frontend solo muestra 2 niveles de profundidad (ver abajo), así
que aunque haya miles de nodos cargados, la mayoría queda oculta hasta que
hacés click para expandir.

## Colores por lóbulo

Cada carpeta principal (primer nivel de tu home) es un "lóbulo" con su
propia familia de color: todo lo que hay adentro (subcarpetas y archivos)
comparte esa tonalidad, aclarada para los archivos. Se detecta por
palabras clave en el nombre (funciona en español e inglés):

| Carpeta | Color |
|---|---|
| Documentos / Documents | azul |
| Descargas / Downloads | rojo/coral |
| Imágenes / Pictures | verde |
| Escritorio / Desktop | morado |
| Proyectos / geram* | cian/turquesa |
| Música / Music | rosa |
| Videos / Movies | naranja |
| cualquier otra | color estable de una paleta automática (mismo nombre → mismo color siempre) |

Las reglas están en `CONFIG.lobulos.reglas` (arriba de todo en
`js/cerebro.js`) — agregá una entrada `{ patrones: [/tu_regex/i], color:
"#hex" }` si querés que otra carpeta tuya tenga un color fijo en vez del
automático. El color de TIPO de archivo (pdf/imagen/código/etc., ya no
pinta el relleno) se conserva como un anillo fino alrededor de cada
archivo — la leyenda de abajo muestra ambos: lóbulos y tipos.

## Comportamiento y física configurables

En `js/cerebro.js`, dentro de `CONFIG`:

- `CONFIG.fisica` — repulsión entre carpetas/archivos, cohesión con el
  padre, distancia radial por profundidad, escala por distancia,
  amortiguación (qué tan lento/calmo se mueve todo)
- `CONFIG.organico` — el balanceo perpetuo y suave de cada nodo (para que
  se sienta como un organismo flotando, no algo estático)
- `CONFIG.comportamiento.profundidadInicial` — cuántos niveles se muestran
  expandidos por defecto (2)
- `CONFIG.comportamiento.umbralAdvertencia` — a partir de cuántos nodos
  visibles aparece el aviso de rendimiento (150)
- `CONFIG.hover` — cuánto crece un nodo al pasarle el mouse y qué tan
  rápido converge esa animación
- `CONFIG.glow`, `CONFIG.pulso`, `CONFIG.radio` — brillo, sinapsis, tamaños
- `CONFIG.animacion.abanicoDistancia` / `abanicoGiroInicial` — qué tan
  lejos y con cuánto "giro espiral" nace cada nodo nuevo desde su padre

## Controles

- **Arrastrar el fondo**: mover la cámara (pan)
- **Rueda del mouse**: zoom in/out
- **Arrastrar un nodo**: reacomodarlo (vuelve a moverse solo al soltarlo)
- **Hover sobre un nodo**: se ilumina, muestra su nombre y resalta sus conexiones
- **Click en una carpeta**: la colapsa/expande (oculta o muestra sus hijos).
  Por defecto solo se ven 2 niveles; el resto ya está cargado pero oculto
  hasta que expandís
- **Click en un nodo "+N más"**: cuando una carpeta tiene muchos archivos
  directos, el resto se agrupa en un nodo así — click para traerlos
- **Click en un archivo**: aparece un menú para abrirlo con la app por
  defecto del sistema
- **Buscador (arriba)**: escribí un nombre y Enter — expande automáticamente
  las carpetas necesarias, resalta el nodo con un anillo pulsante y centra
  la cámara en él
- **"Expandir todo" / "Colapsar todo"**: muestra u oculta toda la
  jerarquía de una

## Aviso de rendimiento

Si en algún momento hay más de `CEREBRO_MAX_NODES` visibles a la vez (por
ejemplo, tras "Expandir todo" en un home grande), aparece un aviso arriba
sugiriendo colapsar alguna carpeta, con un botón para hacerlo directo.

## Actualización automática

El backend usa `watchdog` (inotify) para detectar cambios en la carpeta
vigilada y empuja el árbol actualizado a todos los navegadores conectados
por WebSocket — sin polling, así que es instantáneo (no cada X segundos) y
no gasta CPU revisando nada activamente. No hace falta recargar la página:

- **Archivo nuevo** → su nodo nace con una animación de crecimiento desde
  su carpeta padre (con un pulso de luz)
- **Archivo borrado** → su nodo se desvanece (fade out) en su última
  posición conocida
- **Archivo/carpeta movido** → es el **mismo nodo** el que se reconecta a
  su nueva carpeta padre (con un anillo celeste momentáneo), no un
  borrado+alta — conserva su posición en pantalla y la física lo va
  acercando suavemente a su nuevo padre
- **Carpeta nueva** → aparece un nuevo sub-núcleo con la misma animación
  de nacimiento
- **Renombrado** → mismo mecanismo que "movido" (un rename es un move
  dentro de la misma carpeta): el nodo se actualiza en el lugar, sin
  parpadear su posición
- **Altas masivas** (ej. descomprimir un zip con 50 archivos) → no nacen
  todos de golpe: cada uno espera un poco más que el anterior
  (`CONFIG.animacion.escalonadoMs` en `cerebro.js`) para que se vea como
  sinapsis que se van encendiendo una por una
- El indicador **"● en vivo"** parpadea brevemente cada vez que se aplica
  un cambio real, para confirmar que está sincronizado

Solo se re-anima lo que cambió: el resto del árbol no se vuelve a dibujar
ni pierde su posición en la simulación de física.

Las carpetas excluidas (ocultas, `node_modules`, etc.) ni siquiera se
vigilan, para no gastar recursos de sistema en ellas. Los watches de
inotify se administran carpeta por carpeta (no `recursive=True` sobre todo
el árbol) para no perder tiempo/recursos en las excluidas; cuando aparece
una carpeta nueva (creada o movida desde afuera), se le agrega su propio
watch al vuelo — incluyendo el caso de borrar y volver a crear una carpeta
con el mismo nombre, que se maneja explícitamente para que no quede
"vigilando en el aire".

Los IDs de los nodos se basan en la ruta del archivo (no en un contador), así
que se mantienen estables entre escaneos — eso es lo que permite distinguir
"nodo nuevo" de "nodo que ya existía" (y ahora también "nodo movido") al
compararlos. Watchdog además reporta explícitamente los renombres/movidas
(`src_path` → `dest_path`) para que el frontend pueda re-clavar el mismo
objeto bajo su nueva ruta en vez de tratarlo como alta+baja.

## Rendimiento

Pensado para correr fluido en un i3 con 8GB, incluso vigilando todo el home:

- El escaneo recorre en **anchura** (BFS), no en profundidad: así, si una
  carpeta es enorme, no le come todo el presupuesto de nodos a las demás
  carpetas del primer nivel
- Por defecto solo se **renderizan y simulan físicamente 2 niveles de
  profundidad** — el resto del árbol ya está en memoria pero no entra a la
  simulación hasta que lo expandís, así el costo real (física + dibujo) es
  proporcional a lo que se ve, no al total de archivos
- La simulación de física se dibuja a un máximo de 30fps
- Solo se muestran etiquetas de texto en las carpetas (nodos grandes), el
  núcleo central, el nodo bajo el mouse, y el resultado resaltado de una
  búsqueda — los archivos (nodos chicos) solo muestran su nombre en hover
- Los nodos lejos del núcleo central se ven más chicos (efecto de
  perspectiva)
- Las carpetas se repelen mucho más fuerte que los archivos entre sí, lo
  que separa la red en "lóbulos" bien diferenciados en vez de amontonarse
- Si una carpeta tiene más de `CEREBRO_MAX_CHILDREN` archivos directos, se
  agrupan en un solo nodo "+N más" que podés expandir con un click
- `CEREBRO_MAX_NODES` pone un techo duro al total de nodos conocidos
- El watchdog solo pone vigilancia (inotify) en carpetas reales, nunca en
  las excluidas — así no se desperdician watches en carpetas de basura

## Estructura del proyecto

```
cerebro_archivos/
├── index.html          # el visualizador
├── css/style.css
├── js/cerebro.js        # física del grafo + render en canvas + animaciones
├── server.py            # FastAPI + escaneo BFS + watchdog + WebSocket
├── requirements.txt
├── .env.example
├── icono.png            # logo para el acceso directo de escritorio
├── abrir_cerebro.sh      # lanzador usado por el acceso directo
└── README.md
```
