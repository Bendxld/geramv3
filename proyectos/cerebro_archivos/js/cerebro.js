/**
 * Cerebro de Archivos — grafo de fuerzas dibujado en canvas 2D.
 * Física con d3-force; render/interacción manual (sin DOM por nodo) para
 * poder mantener 30fps con cientos de nodos en hardware modesto.
 */

// ============================== CONFIG ==============================
const CONFIG = {
  // colores de TIPO de archivo — ya no pintan el relleno del nodo (eso lo
  // decide el lóbulo, ver CONFIG.lobulos), pero se siguen usando para el
  // anillo fino de cada archivo y la leyenda de tipos
  categorias: {
    pdf: "#ff6b5e",
    imagen: "#54e08d",
    codigo: "#8f5cff",
    doc: "#4d8dff",
    video: "#ff9d3d",
    audio: "#ff5ec4",
    otro: "#9aa4b2",
  },
  nucleo: "#fff6e0",
  more: "#6b7690",
  // lóbulos: cada carpeta principal (profundidad 1) de la raíz es un
  // "lóbulo" con su propia familia de color — se detecta por palabras
  // clave en el nombre (funciona en español e inglés) y si ninguna
  // coincide, se asigna un color estable de la paleta automática según
  // un hash del nombre (mismo nombre → mismo color siempre)
  lobulos: {
    reglas: [
      { patrones: [/documen/i], color: "#4d8dff" }, // Documentos/Documents → azul
      { patrones: [/descarga/i, /download/i], color: "#ff6b5e" }, // Descargas/Downloads → rojo/coral
      { patrones: [/imag/i, /pictur/i, /foto/i], color: "#54e08d" }, // Imágenes/Pictures → verde
      { patrones: [/escritorio/i, /desktop/i], color: "#b083ff" }, // Escritorio/Desktop → morado
      { patrones: [/proyecto/i, /geram/i, /^project/i], color: "#37e0d6" }, // Proyectos/geram* → cian/turquesa
      { patrones: [/m[uú]sica/i, /music/i, /audio/i], color: "#ff5ec4" }, // Música/Music → rosa
      { patrones: [/v[ií]deo/i, /movies?/i, /pel[ií]cula/i], color: "#ff9d3d" }, // Videos/Movies → naranja
    ],
    paletaAutomatica: [
      "#e0c341", "#7fc7ff", "#ff8fa3", "#8fffb0", "#c792ff",
      "#ffb454", "#5ee6c8", "#ff7edb", "#a3ff7e", "#7e9bff",
    ],
    // cuánto se aclara (mezcla hacia blanco) el color del lóbulo para los
    // archivos, para que se vean como un tono "hijo" más claro del padre
    aclaradoArchivo: 0.44,
  },
  radio: {
    root: 42,
    carpetaDepth1: 18,
    carpeta: 11,
    archivoBase: 5,
    archivoMax: 13,
    more: 9,
  },
  fisica: {
    // las carpetas repelen mucho más fuerte que los archivos: eso es lo
    // que separa los "lóbulos" del cerebro entre sí en vez de que todo
    // se amontone en una sola bola
    chargeCarpetaBase: -230,
    chargeArchivoBase: -48,
    chargePorProfundidad: 8, // se va suavizando en profundidad (menos negativo)
    linkDistanceBase: 46,
    linkDistancePorProfundidad: 10,
    linkStrength: 0.75,
    collidePadding: 8,
    radialBase: 125,
    radialPorProfundidad: 95,
    radialStrength: 0.35,
    // cohesión: cada nodo es levemente atraído hacia su carpeta padre,
    // así los hijos "orbitan" pegados a su padre en vez de dispersarse
    cohesionStrength: 0.12,
    alphaDecay: 0.021,
    velocityDecay: 0.42, // más amortiguación = movimiento más lento y calmo, como flotando
    // nodos lejos del núcleo central se ven (y se sienten al clickear)
    // más chicos, como en perspectiva
    distanciaEscalaMin: 0.55,
    distanciaEscalaDivisor: 1500,
  },
  organico: {
    // pequeño balanceo perpetuo (visual, no físico) para que el cerebro
    // nunca se sienta 100% estático, como un organismo flotando
    amplitud: 1.6,
    velocidad: 1 / 3800,
  },
  comportamiento: {
    profundidadInicial: 2, // cuántos niveles se muestran expandidos por defecto
    umbralAdvertencia: 150, // nodos visibles a la vez antes de avisar
  },
  fps: 30,
  glow: {
    normal: 10,
    hover: 26,
    root: 30, // base; el núcleo además "respira" (ver dibujarNucleo)
  },
  pulso: {
    intervaloMs: 220,
    porTanda: [1, 2],
    duracionMs: [900, 1600],
    tamano: 2.6,
  },
  animacion: {
    nacimientoMs: 650,
    muerteMs: 500,
    // cascada: cuando llegan muchos nodos nuevos de golpe (ej. descomprimir
    // un zip), no nacen todos a la vez — cada uno espera un poco más que
    // el anterior, como sinapsis que se van encendiendo una por una
    escalonadoMs: 70,
    escalonadoMax: 40, // a partir de este índice todos arrancan juntos (evita esperas eternas)
    reconectadoMs: 1800, // cuánto dura el anillo de "este nodo se movió/renombró"
    // al nacer, cada nodo nuevo se abre en abanico/espiral alrededor de su
    // padre en vez de aparecer en un punto random — ver birthStart/fx/fy
    abanicoDistancia: 62,
    abanicoGiroInicial: 0.9, // radianes de "giro" extra que se deshace al asentarse (efecto espiral)
  },
  hover: {
    escalaObjetivo: 1.22,
    suavizado: 0.16, // qué tan rápido converge el crecimiento al pasar el mouse
  },
  zoom: { min: 0.15, max: 4 },
};
// ======================================================================

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const menu = document.getElementById("menu-contextual");
const btnAbrir = document.getElementById("btn-abrir");
const elRuta = document.getElementById("ruta");
const elStats = document.getElementById("stats");
const elConexion = document.getElementById("estado-conexion");
const buscador = document.getElementById("buscador");
const btnExpandirTodo = document.getElementById("btn-expandir-todo");
const btnColapsarTodo = document.getElementById("btn-colapsar-todo");
const avisoRendimiento = document.getElementById("aviso-rendimiento");
const avisoTexto = document.getElementById("aviso-texto");
const btnAvisoColapsar = document.getElementById("btn-aviso-colapsar");
const btnAvisoCerrar = document.getElementById("btn-aviso-cerrar");
const contenedorLeyendaLobulos = document.getElementById("leyenda-lobulos");

let dpr = window.devicePixelRatio || 1;
let width = window.innerWidth;
let height = window.innerHeight;

// ------------------------- estado del grafo -------------------------
const nodesById = new Map(); // id -> nodo (objeto vivo, conserva x/y entre updates)
let visibleNodes = [];
let visibleLinks = [];
let dying = []; // nodos que se están desvaneciendo
let pulses = []; // impulsos de luz viajando por las sinapsis
const collapsed = new Set(); // ids de carpetas colapsadas
const expandedFolders = new Map(); // path -> true, carpetas expandidas manualmente ("+N más")

let rootId = "root";
let hoveredNode = null;
let contextNode = null;
let resaltados = new Set(); // ids resaltados por la última búsqueda
let resaltadoHasta = 0; // timestamp (rAF) hasta el que se muestra el resaltado
let ahora = 0; // timestamp del frame actual, para animaciones basadas en tiempo
let camAnim = null; // {fromX,fromY,fromK,toX,toY,toK,start,dur} — animación de "centrar cámara"
let siguiendoId = null; // id de nodo que la cámara sigue suavemente mientras dura el resaltado
let reconectados = new Map(); // id -> timestamp hasta el que se muestra el anillo de "se movió"

const view = { x: width / 2, y: height / 2, k: 1 };
let dragging = null; // nodo siendo arrastrado
let panning = false;
let panStart = null;
let mouseDownPos = null;
let mouseMoved = false;

const simulation = d3
  .forceSimulation([])
  .alphaDecay(CONFIG.fisica.alphaDecay)
  .velocityDecay(CONFIG.fisica.velocityDecay)
  .force("link", d3.forceLink([]).id((d) => d.id).distance(linkDistance).strength(CONFIG.fisica.linkStrength))
  .force("charge", d3.forceManyBody().strength(chargeStrength))
  .force("collide", d3.forceCollide((d) => nodeRadius(d) + CONFIG.fisica.collidePadding))
  .force("radial", d3.forceRadial((d) => radialRadius(d.depth), 0, 0).strength(CONFIG.fisica.radialStrength))
  .force("cohesionX", d3.forceX(cohesionObjetivoX).strength(cohesionFuerza))
  .force("cohesionY", d3.forceY(cohesionObjetivoY).strength(cohesionFuerza))
  .stop();

function linkDistance(l) {
  const depth = Math.max(l.source.depth || 0, l.target.depth || 0);
  return CONFIG.fisica.linkDistanceBase + depth * CONFIG.fisica.linkDistancePorProfundidad;
}
function chargeStrength(d) {
  const base = d.type === "carpeta" ? CONFIG.fisica.chargeCarpetaBase : CONFIG.fisica.chargeArchivoBase;
  return base + d.depth * CONFIG.fisica.chargePorProfundidad;
}
function radialRadius(depth) {
  if (depth === 0) return 0;
  return CONFIG.fisica.radialBase + (depth - 1) * CONFIG.fisica.radialPorProfundidad;
}
function cohesionObjetivoX(d) {
  const padre = d.parent && nodesById.get(d.parent);
  return padre ? padre.x : 0;
}
function cohesionObjetivoY(d) {
  const padre = d.parent && nodesById.get(d.parent);
  return padre ? padre.y : 0;
}
function cohesionFuerza(d) {
  return d.parent ? CONFIG.fisica.cohesionStrength : 0;
}

function nodeRadius(n) {
  let r;
  if (n.type === "more") r = CONFIG.radio.more;
  else if (n.id === rootId) r = CONFIG.radio.root;
  else if (n.type === "carpeta") r = n.depth === 1 ? CONFIG.radio.carpetaDepth1 : CONFIG.radio.carpeta;
  else {
    const escala = Math.min(1, Math.log10((n.size || 0) + 1) / 7);
    r = CONFIG.radio.archivoBase + escala * (CONFIG.radio.archivoMax - CONFIG.radio.archivoBase);
  }
  if (n.birthT !== undefined && n.birthT < 1) {
    const ease = 1 - Math.pow(1 - n.birthT, 3);
    r *= ease;
  }
  if (n.id !== rootId && n.x !== undefined) {
    const dist = Math.hypot(n.x, n.y);
    const factorDistancia = Math.max(
      CONFIG.fisica.distanciaEscalaMin,
      1 - dist / CONFIG.fisica.distanciaEscalaDivisor
    );
    r *= factorDistancia;
  }
  return Math.max(1.5, r);
}

// ------------------------------ color por lóbulo ------------------------------
const lobuloColorCache = new Map(); // id del ancestro-lóbulo -> color hex

function hexARgb(hex) {
  const limpio = hex.replace("#", "");
  return {
    r: parseInt(limpio.substring(0, 2), 16),
    g: parseInt(limpio.substring(2, 4), 16),
    b: parseInt(limpio.substring(4, 6), 16),
  };
}

function aclararColor(hex, factor) {
  const { r, g, b } = hexARgb(hex);
  const nr = Math.round(r + (255 - r) * factor);
  const ng = Math.round(g + (255 - g) * factor);
  const nb = Math.round(b + (255 - b) * factor);
  return `rgb(${nr},${ng},${nb})`;
}

function oscurecerColor(hex, factor) {
  const { r, g, b } = hexARgb(hex);
  return `rgb(${Math.round(r * (1 - factor))},${Math.round(g * (1 - factor))},${Math.round(b * (1 - factor))})`;
}

function asignarColorLobulo(nombre) {
  for (const regla of CONFIG.lobulos.reglas) {
    if (regla.patrones.some((re) => re.test(nombre))) return regla.color;
  }
  // sin coincidencia: color estable de la paleta automática según un hash
  // del nombre (mismo nombre siempre da el mismo color, entre sesiones)
  let hash = 0;
  for (let i = 0; i < nombre.length; i++) hash = (hash * 31 + nombre.charCodeAt(i)) | 0;
  const paleta = CONFIG.lobulos.paletaAutomatica;
  return paleta[Math.abs(hash) % paleta.length];
}

// encuentra el ancestro de profundidad 1 de un nodo (el "lóbulo" al que
// pertenece) subiendo por la cadena de padres; si el nodo mismo es de
// profundidad <=1 (incluida la raíz), es su propio lóbulo
function idDeLobulo(n) {
  let actual = n;
  let saltos = 0;
  while (actual && actual.depth > 1 && saltos < 64) {
    actual = nodesById.get(actual.parent);
    saltos++;
  }
  return actual ? actual.id : n.id;
}

function colorDeLobulo(n) {
  if (n.id === rootId) return CONFIG.nucleo;
  const lobuloId = idDeLobulo(n);
  if (lobuloId === rootId) return CONFIG.nucleo;
  let color = lobuloColorCache.get(lobuloId);
  if (!color) {
    const nodoLobulo = nodesById.get(lobuloId);
    color = asignarColorLobulo(nodoLobulo ? nodoLobulo.name : "?");
    lobuloColorCache.set(lobuloId, color);
  }
  return color;
}

// el color de cada nodo se cachea en el propio objeto: recalcular el hex a
// RGB y mezclar canales en cada frame para cientos de nodos era el mayor
// costo del render. Solo se invalida si el nodo se reconecta a otra
// carpeta (ver applyStructure), que es lo único que puede cambiarle el
// lóbulo.
function nodeColor(n) {
  if (n.id === rootId) return CONFIG.nucleo;
  if (n.type === "more") return CONFIG.more;
  if (n._colorCache) return n._colorCache;
  const base = colorDeLobulo(n);
  const color = n.type === "carpeta" ? base : aclararColor(base, CONFIG.lobulos.aclaradoArchivo);
  n._colorCache = color;
  return color;
}

// color ya en formato rgba con la transparencia de las conexiones no
// resaltadas — cacheado junto con nodeColor para no rearmar el string en
// cada frame para cada link (la mayoría no están resaltados)
function colorDesvanecido(n) {
  if (n._colorDesvanecido) return n._colorDesvanecido;
  const c = colorConAlpha(nodeColor(n), 0.16);
  n._colorDesvanecido = c;
  return c;
}

// admite tanto "#rrggbb" como "rgb(r,g,b)" (lo que devuelve aclararColor)
function colorARgbObj(color) {
  if (color.startsWith("#")) return hexARgb(color);
  const partes = color.slice(color.indexOf("(") + 1, color.indexOf(")")).split(",");
  return { r: +partes[0], g: +partes[1], b: +partes[2] };
}
function colorConAlpha(color, alpha) {
  const { r, g, b } = colorARgbObj(color);
  return `rgba(${r},${g},${b},${alpha})`;
}
function mezclarColor(colorA, colorB, t) {
  const a = colorARgbObj(colorA);
  const b = colorARgbObj(colorB);
  const r = Math.round(a.r + (b.r - a.r) * t);
  const g = Math.round(a.g + (b.g - a.g) * t);
  const bl = Math.round(a.b + (b.b - a.b) * t);
  return `rgb(${r},${g},${bl})`;
}
// ángulo estable [0, 2π) a partir de un string, para que el abanico de
// nacimiento de cada carpeta empiece en una orientación distinta pero
// siempre la misma para esa carpeta
function hashAngulo(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = (hash * 31 + str.charCodeAt(i)) | 0;
  return (Math.abs(hash) % 360) * (Math.PI / 180);
}

// posición "visual" de un nodo: la real más un balanceo suave y perpetuo
// (no físico, no se guarda) para que el cerebro nunca se sienta 100%
// estático, como un organismo flotando. La raíz y los nodos muriendo no
// se balancean (la raíz respira por su cuenta, ver dibujarNucleo).
function posVisual(n) {
  if (n.id === rootId || n.deathT !== undefined) return [n.x, n.y];
  if (n._swayFrame === ahora) return [n._vx, n._vy]; // ya calculado en este mismo frame
  if (n._faseSway === undefined) n._faseSway = hashAngulo(n.id);
  const sx = n.x + Math.sin(ahora * CONFIG.organico.velocidad + n._faseSway) * CONFIG.organico.amplitud;
  const sy = n.y + Math.cos(ahora * CONFIG.organico.velocidad * 1.3 + n._faseSway) * CONFIG.organico.amplitud;
  n._vx = sx;
  n._vy = sy;
  n._swayFrame = ahora;
  return [sx, sy];
}

// ---------------------------- diffing de datos ----------------------------
// `enVivo` distingue la carga inicial (sin cascada, aparece todo de una)
// de una actualización empujada por watchdog en caliente (con cascada y
// parpadeo). Devuelve true si hubo algún cambio real (alta/baja/movida),
// para que el que llama sepa si vale la pena parpadear el indicador.
function applyStructure(data, enVivo) {
  rootId = data.nodes.find((n) => n.parent === null && n.type === "carpeta" && !n.id.endsWith("::more"))?.id || "root";
  elRuta.textContent = data.root_path;

  // movidos/renombrados: watchdog los reporta como (ruta vieja -> ruta
  // nueva). Re-clavamos el MISMO objeto de nodo bajo la nueva clave para
  // que el próximo paso (altas/actualizaciones) lo reconozca como
  // "ya existía" en vez de matarlo y crear uno nuevo — así conserva su
  // posición en pantalla y solo se reconecta a su carpeta padre.
  let huboMovidos = false;
  for (const { desde, hacia } of data.movidos || []) {
    const prefijo = desde + "/";
    for (const clave of [...nodesById.keys()]) {
      let nuevaClave = null;
      if (clave === desde) nuevaClave = hacia;
      else if (clave.startsWith(prefijo)) nuevaClave = hacia + clave.slice(desde.length);
      if (nuevaClave && nuevaClave !== clave && !nodesById.has(nuevaClave)) {
        const nodo = nodesById.get(clave);
        nodesById.delete(clave);
        nodo.id = nuevaClave;
        nodo._colorCache = null; // puede haber cambiado de lóbulo al moverse
        nodo._colorDesvanecido = null;
        nodesById.set(nuevaClave, nodo);
        reconectados.set(nuevaClave, ahora + CONFIG.animacion.reconectadoMs);
        huboMovidos = true;
      }
    }
  }

  const incomingIds = new Set(data.nodes.map((n) => n.id));
  let huboAltas = false;
  let indiceNuevo = 0;

  // pre-pass: agrupar las altas nuevas por padre para poder abrirlas en
  // abanico (cada hermano nuevo apunta a un ángulo distinto alrededor del
  // padre) en vez de tirarlas todas en un punto random
  const nuevosPorPadre = new Map();
  for (const raw of data.nodes) {
    if (!nodesById.has(raw.id)) {
      if (!nuevosPorPadre.has(raw.parent)) nuevosPorPadre.set(raw.parent, []);
      nuevosPorPadre.get(raw.parent).push(raw.id);
    }
  }

  // altas / actualizaciones
  for (const raw of data.nodes) {
    const existing = nodesById.get(raw.id);
    if (existing) {
      Object.assign(existing, {
        name: raw.name,
        parent: raw.parent,
        type: raw.type,
        category: raw.category,
        path: raw.path,
        depth: raw.depth,
        size: raw.size,
        extra_count: raw.extra_count,
      });
    } else {
      huboAltas = true;
      const parent = raw.parent ? nodesById.get(raw.parent) : null;
      // cascada: en una actualización en vivo, cada nodo nuevo espera un
      // poco más que el anterior antes de empezar a "nacer" (sinapsis
      // encendiéndose una por una en vez de todas de golpe)
      const escalon = enVivo ? Math.min(indiceNuevo++, CONFIG.animacion.escalonadoMax) : 0;
      const demora = escalon * CONFIG.animacion.escalonadoMs;
      const hermanos = nuevosPorPadre.get(raw.parent) || [raw.id];
      const indiceHermano = hermanos.indexOf(raw.id);
      const anguloAbanico = (indiceHermano / hermanos.length) * Math.PI * 2 + hashAngulo(raw.parent || "");
      nodesById.set(raw.id, {
        ...raw,
        x: parent ? parent.x : 0,
        y: parent ? parent.y : 0,
        fx: parent ? parent.x : 0,
        fy: parent ? parent.y : 0,
        vx: 0,
        vy: 0,
        birthT: 0,
        birthStart: ahora + demora,
        _isNew: true,
        _fanAngle: anguloAbanico,
        _fanDist: CONFIG.animacion.abanicoDistancia,
      });
      // por defecto solo se ve hasta profundidadInicial niveles: cualquier
      // carpeta nueva más profunda que eso nace ya colapsada, así el
      // usuario la expande con un click en vez de que aparezcan de golpe
      // cientos de nodos la primera vez que se abre el cerebro
      if (raw.type === "carpeta" && raw.depth >= CONFIG.comportamiento.profundidadInicial) {
        collapsed.add(raw.id);
      }
    }
  }

  // bajas (existían y ya no vinieron en este escaneo => se borraron del disco)
  let huboBajas = false;
  for (const [id, n] of nodesById) {
    if (!incomingIds.has(id)) {
      nodesById.delete(id);
      n.deathT = 0;
      n.startX = n.x;
      n.startY = n.y;
      dying.push(n);
      huboBajas = true;
    }
  }

  // si una carpeta expandida manualmente volvió a mostrar su nodo "+N más",
  // la re-expandimos automáticamente para no perder el estado del usuario
  for (const n of nodesById.values()) {
    if (n.type === "more" && expandedFolders.has(n.path)) {
      expandirCarpeta(n, true);
    }
  }

  refreshVisible();
  if (simulation.alpha() < 0.4) simulation.alpha(0.4);
  simulation.restart();

  return huboAltas || huboBajas || huboMovidos;
}

function refreshVisible() {
  const childrenMap = new Map();
  for (const n of nodesById.values()) {
    if (n.parent) {
      if (!childrenMap.has(n.parent)) childrenMap.set(n.parent, []);
      childrenMap.get(n.parent).push(n.id);
    }
  }

  const hidden = new Set();
  const marcarDescendencia = (id) => {
    const hijos = childrenMap.get(id) || [];
    for (const hijoId of hijos) {
      if (hidden.has(hijoId)) continue;
      hidden.add(hijoId);
      marcarDescendencia(hijoId);
    }
  };
  for (const id of collapsed) marcarDescendencia(id);

  visibleNodes = [...nodesById.values()].filter((n) => !hidden.has(n.id));
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  visibleLinks = visibleNodes
    .filter((n) => n.parent && visibleIds.has(n.parent))
    .map((n) => ({ source: n.parent, target: n.id, depth: n.depth }));

  simulation.nodes(visibleNodes);
  simulation.force("link").links(visibleLinks);

  const root = nodesById.get(rootId);
  if (root) {
    root.fx = 0;
    root.fy = 0;
  }

  let archivosTotales = 0;
  let carpetasTotales = 0;
  for (const n of nodesById.values()) {
    if (n.type === "archivo") archivosTotales++;
    else if (n.type === "carpeta") carpetasTotales++;
  }
  const archivosVisibles = visibleNodes.filter((n) => n.type === "archivo").length;
  elStats.textContent = `Mostrando ${archivosVisibles} de ${archivosTotales} archivos · ${carpetasTotales} carpetas en total`;

  if (visibleNodes.length > CONFIG.comportamiento.umbralAdvertencia) {
    avisoTexto.textContent = `Mostrando ${visibleNodes.length} nodos a la vez — puede ir lento en equipos modestos. Probá colapsar alguna carpeta.`;
    avisoRendimiento.classList.remove("oculto");
  } else {
    avisoRendimiento.classList.add("oculto");
  }

  actualizarLeyendaLobulos();
}

// agrega a la leyenda una entrada por cada carpeta principal (lóbulo) que
// se vaya descubriendo — solo agrega las nuevas, no reconstruye todo cada
// vez, así no parpadea
const lobulosEnLeyenda = new Set();
function actualizarLeyendaLobulos() {
  for (const n of nodesById.values()) {
    if (n.type === "carpeta" && n.depth === 1 && !lobulosEnLeyenda.has(n.id)) {
      lobulosEnLeyenda.add(n.id);
      const item = document.createElement("div");
      item.className = "item";
      const punto = document.createElement("span");
      punto.className = "dot";
      punto.style.background = colorDeLobulo(n);
      punto.style.color = colorDeLobulo(n);
      item.appendChild(punto);
      item.appendChild(document.createTextNode(n.name));
      contenedorLeyendaLobulos.appendChild(item);
    }
  }
}

async function expandirCarpeta(moreNode, silencioso) {
  expandedFolders.set(moreNode.path, true);
  try {
    const res = await fetch(`/api/carpeta?path=${encodeURIComponent(moreNode.path)}`);
    if (!res.ok) return;
    const data = await res.json();
    const parentId = moreNode.parent;
    nodesById.delete(moreNode.id);
    const nuevos = data.nodes.filter((raw) => !nodesById.has(raw.id));
    const anguloBase = hashAngulo(parentId || "");
    nuevos.forEach((raw, indice) => {
      const pin = !silencioso;
      const angulo = (indice / Math.max(1, nuevos.length)) * Math.PI * 2 + anguloBase;
      nodesById.set(raw.id, {
        ...raw,
        parent: parentId,
        depth: moreNode.depth,
        x: moreNode.x + (pin ? 0 : (Math.random() - 0.5) * 30),
        y: moreNode.y + (pin ? 0 : (Math.random() - 0.5) * 30),
        fx: pin ? moreNode.x : null,
        fy: pin ? moreNode.y : null,
        vx: 0,
        vy: 0,
        birthT: silencioso ? 1 : 0,
        birthStart: ahora,
        _isNew: !silencioso,
        _fanAngle: angulo,
        _fanDist: CONFIG.animacion.abanicoDistancia,
      });
    });
    refreshVisible();
    simulation.alpha(0.5).restart();
  } catch (e) {
    console.error("no se pudo expandir carpeta", e);
  }
}

// ------------------------------- pulsos -------------------------------
let acumuladorPulso = 0;
function actualizarPulsos(dtMs) {
  acumuladorPulso += dtMs;
  if (acumuladorPulso >= CONFIG.pulso.intervaloMs && visibleLinks.length) {
    acumuladorPulso = 0;
    const cantidad =
      CONFIG.pulso.porTanda[0] +
      Math.floor(Math.random() * (CONFIG.pulso.porTanda[1] - CONFIG.pulso.porTanda[0] + 1));
    for (let i = 0; i < cantidad; i++) {
      if (pulses.length > 60) break;
      const link = visibleLinks[Math.floor(Math.random() * visibleLinks.length)];
      const dur = CONFIG.pulso.duracionMs[0] + Math.random() * (CONFIG.pulso.duracionMs[1] - CONFIG.pulso.duracionMs[0]);
      pulses.push({ link, t: 0, dur });
    }
  }
  pulses.forEach((p) => (p.t += dtMs / p.dur));
  pulses = pulses.filter((p) => p.t < 1);
}

// ------------------------------- render -------------------------------
function resize() {
  dpr = window.devicePixelRatio || 1;
  width = window.innerWidth;
  height = window.innerHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  simulation.force("radial").x(0).y(0);
}
window.addEventListener("resize", resize);
resize();

function worldToScreen(x, y) {
  return [x * view.k + view.x, y * view.k + view.y];
}
function screenToWorld(x, y) {
  return [(x - view.x) / view.k, (y - view.y) / view.k];
}

function dibujarLink(l, resaltado) {
  const s = nodesById.get(typeof l.source === "object" ? l.source.id : l.source) || l.source;
  const t = nodesById.get(typeof l.target === "object" ? l.target.id : l.target) || l.target;
  if (!s || !t || s.x === undefined || t.x === undefined) return;
  const [sx, sy] = posVisual(s);
  const [tx, ty] = posVisual(t);
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(tx, ty);
  if (resaltado) {
    // el degradado (más caro de armar) solo se usa para las pocas
    // conexiones resaltadas por el hover; el resto usa un color sólido
    // para no crear cientos de gradientes por frame
    const grad = ctx.createLinearGradient(sx, sy, tx, ty);
    grad.addColorStop(0, colorConAlpha(nodeColor(s), 0.7));
    grad.addColorStop(1, colorConAlpha(nodeColor(t), 0.7));
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.9 / view.k;
  } else {
    ctx.strokeStyle = colorDesvanecido(t);
    ctx.lineWidth = 0.9 / view.k;
  }
  ctx.stroke();
}

function dibujarPulso(p) {
  const s = nodesById.get(typeof p.link.source === "object" ? p.link.source.id : p.link.source);
  const t = nodesById.get(typeof p.link.target === "object" ? p.link.target.id : p.link.target);
  if (!s || !t) return;
  const [sx, sy] = posVisual(s);
  const [tx, ty] = posVisual(t);
  const x = sx + (tx - sx) * p.t;
  const y = sy + (ty - sy) * p.t;
  const alpha = Math.sin(Math.PI * p.t); // aparece y se apaga suave en el camino
  const color = mezclarColor(nodeColor(s), nodeColor(t), p.t); // la señal va tomando el color del destino
  ctx.save();
  ctx.shadowColor = color;
  ctx.shadowBlur = 13;
  ctx.fillStyle = colorConAlpha(color, alpha);
  ctx.beginPath();
  ctx.arc(x, y, CONFIG.pulso.tamano / view.k, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// núcleo central: más grande, con un halo que "respira" lento y un anillo
// de energía con guiones que giran alrededor — se dibuja aparte del resto
// de los nodos porque es el único elemento con esta puesta en escena
function dibujarNucleo(n) {
  const respiracion = 0.5 + 0.5 * Math.sin(ahora / 1600); // 0..1, ciclo lento
  const rBase = nodeRadius(n) * (1 + 0.07 * respiracion);
  const [x, y] = [n.x, n.y];

  const haloR = rBase * (2.3 + 0.35 * respiracion);
  const halo = ctx.createRadialGradient(x, y, rBase * 0.5, x, y, haloR);
  halo.addColorStop(0, "rgba(255,246,224,0.32)");
  halo.addColorStop(1, "rgba(255,246,224,0)");
  ctx.save();
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(x, y, haloR, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.strokeStyle = "rgba(255,232,190,0.6)";
  ctx.lineWidth = 1.6 / view.k;
  ctx.setLineDash([7 / view.k, 9 / view.k]);
  ctx.lineDashOffset = -(ahora / 35);
  ctx.beginPath();
  ctx.arc(x, y, rBase + 13 / view.k, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  ctx.save();
  ctx.shadowColor = CONFIG.nucleo;
  ctx.shadowBlur = (CONFIG.glow.root + 12 * respiracion) / Math.sqrt(view.k);
  ctx.fillStyle = CONFIG.nucleo;
  ctx.beginPath();
  ctx.arc(x, y, rBase, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  return rBase;
}

function dibujarNodo(n) {
  const esRoot = n.id === rootId;
  const esHover = n === hoveredNode;
  const esResaltado = resaltados.has(n.id) && ahora < resaltadoHasta;
  const finReconexion = reconectados.get(n.id);
  const esReconectado = finReconexion !== undefined && ahora < finReconexion;

  // crecimiento suave al pasar el mouse (no toca nodeRadius, que además
  // alimenta la física — esto es puramente cosmético)
  if (n._hoverScale === undefined) n._hoverScale = 1;
  const objetivoEscala = esHover && !esRoot ? CONFIG.hover.escalaObjetivo : 1;
  n._hoverScale += (objetivoEscala - n._hoverScale) * CONFIG.hover.suavizado;

  const [x, y] = posVisual(n);
  let r;

  ctx.save();
  ctx.globalAlpha = n.deathT !== undefined ? 1 - n.deathT : 1;

  if (esRoot) {
    r = dibujarNucleo(n);
  } else {
    r = nodeRadius(n) * n._hoverScale;
    const color = nodeColor(n);
    // los nodos más profundos brillan un poco menos: refuerza la sensación
    // de profundidad además del achique por distancia que ya hace nodeRadius
    const caidaProfundidad = Math.max(0.45, 1 - n.depth * 0.055);
    ctx.shadowColor = color;
    ctx.shadowBlur =
      ((esHover || esResaltado || esReconectado ? CONFIG.glow.hover : CONFIG.glow.normal) * caidaProfundidad) /
      Math.sqrt(view.k);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();

    if (n.type === "archivo") {
      // anillo fino con el color de categoría (pdf/imagen/código/...): el
      // relleno ahora es el color del lóbulo, este anillo mantiene visible
      // el tipo de archivo a quien lo busque
      ctx.shadowBlur = 0;
      ctx.strokeStyle = CONFIG.categorias[n.category] || CONFIG.categorias.otro;
      ctx.globalAlpha = (n.deathT !== undefined ? 1 - n.deathT : 1) * 0.8;
      ctx.lineWidth = 1.3 / view.k;
      ctx.beginPath();
      ctx.arc(x, y, r + 1.6 / view.k, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = n.deathT !== undefined ? 1 - n.deathT : 1;
    }
  }

  if (esHover || esRoot) {
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255,255,255,0.5)";
    ctx.lineWidth = 1.5 / view.k;
    ctx.beginPath();
    ctx.arc(x, y, r + 3 / view.k, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (esResaltado) {
    // anillo pulsante alrededor del resultado de búsqueda
    const pulso = 1 + 0.25 * Math.sin(ahora / 120);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255,220,120,0.9)";
    ctx.lineWidth = 2 / view.k;
    ctx.beginPath();
    ctx.arc(x, y, (r + 7) * pulso, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (esReconectado) {
    // anillo celeste: este nodo se acaba de mover/renombrar y se está
    // reacomodando hacia su (nueva) carpeta padre
    const pulso = 1 + 0.2 * Math.sin(ahora / 90);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(120,220,255,0.85)";
    ctx.lineWidth = 2 / view.k;
    ctx.beginPath();
    ctx.arc(x, y, (r + 6) * pulso, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();

  const mostrarLabel = esHover || esRoot || esResaltado || esReconectado || n.type === "carpeta" || n.type === "more";
  if (mostrarLabel && view.k > 0.35) {
    ctx.save();
    ctx.globalAlpha = n.deathT !== undefined ? 1 - n.deathT : 1;
    ctx.font = `${esRoot ? 13 : 11}px "Segoe UI", sans-serif`;
    ctx.fillStyle = "rgba(230,236,255,0.9)";
    ctx.textAlign = "center";
    ctx.shadowColor = "rgba(0,0,0,0.9)";
    ctx.shadowBlur = 4;
    ctx.fillText(recortar(n.name, 26), x, y - r - 8 / view.k);
    ctx.restore();
  }
}

function recortar(str, max) {
  if (!str) return "";
  return str.length > max ? str.slice(0, max - 1) + "…" : str;
}

let ultimoFrame = 0;
function render(t) {
  requestAnimationFrame(render);
  const dt = t - ultimoFrame;
  if (dt < 1000 / CONFIG.fps) return;
  ultimoFrame = t;
  ahora = t;

  if (camAnim) {
    const p = Math.min(1, (t - camAnim.start) / camAnim.dur);
    const ease = 1 - Math.pow(1 - p, 3);
    view.x = camAnim.fromX + (camAnim.toX - camAnim.fromX) * ease;
    view.y = camAnim.fromY + (camAnim.toY - camAnim.fromY) * ease;
    view.k = camAnim.fromK + (camAnim.toK - camAnim.fromK) * ease;
    if (p >= 1) camAnim = null;
  } else if (siguiendoId) {
    // sigue al nodo resaltado por la búsqueda mientras la física todavía
    // lo está acomodando, si no se nos escapa del centro apenas se mueve
    if (ahora >= resaltadoHasta) {
      siguiendoId = null;
    } else {
      const nodo = nodesById.get(siguiendoId);
      if (nodo) {
        const objetivoX = width / 2 - nodo.x * view.k;
        const objetivoY = height / 2 - nodo.y * view.k;
        view.x += (objetivoX - view.x) * 0.18;
        view.y += (objetivoY - view.y) * 0.18;
      }
    }
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.translate(view.x, view.y);
  ctx.scale(view.k, view.k);

  actualizarPulsos(dt);

  const idsConectados = new Set();
  if (hoveredNode) {
    idsConectados.add(hoveredNode.id);
    for (const l of visibleLinks) {
      const sId = typeof l.source === "object" ? l.source.id : l.source;
      const tId = typeof l.target === "object" ? l.target.id : l.target;
      if (sId === hoveredNode.id) idsConectados.add(tId);
      if (tId === hoveredNode.id) idsConectados.add(sId);
    }
  }

  for (const l of visibleLinks) {
    const sId = typeof l.source === "object" ? l.source.id : l.source;
    const tId = typeof l.target === "object" ? l.target.id : l.target;
    dibujarLink(l, hoveredNode && (sId === hoveredNode.id || tId === hoveredNode.id));
  }
  for (const p of pulses) dibujarPulso(p);

  // nodos muriendo (fade out en su última posición conocida)
  for (const n of dying) {
    n.deathT += dt / CONFIG.animacion.muerteMs;
    n.x = n.startX;
    n.y = n.startY;
    dibujarNodo(n);
  }
  dying = dying.filter((n) => n.deathT < 1);

  for (const n of visibleNodes) {
    if (n._isNew && ahora >= (n.birthStart ?? 0)) {
      n.birthT += dt / CONFIG.animacion.nacimientoMs;
      if (n.birthT >= 1) {
        n.birthT = 1;
        n._isNew = false;
        n.fx = null;
        n.fy = null; // suelta el pin: la física toma el control desde acá
      } else if (n._fanAngle !== undefined) {
        // abanico/espiral: nace pegado al padre y se abre hacia su
        // posición final girando levemente, como una sinapsis que se
        // despliega en vez de aparecer de golpe
        const padre = nodesById.get(n.parent);
        if (padre) {
          const ease = 1 - Math.pow(1 - n.birthT, 3);
          const giro = (1 - ease) * CONFIG.animacion.abanicoGiroInicial;
          const dist = n._fanDist * ease;
          const angulo = n._fanAngle + giro;
          n.fx = padre.x + Math.cos(angulo) * dist;
          n.fy = padre.y + Math.sin(angulo) * dist;
          n.x = n.fx;
          n.y = n.fy;
        }
      }
    }
    dibujarNodo(n);
  }

  ctx.restore();
}
requestAnimationFrame(render);

function tick() {
  // el layout se recalcula solo; el render loop lee las posiciones cada frame
}
simulation.on("tick", tick);

// ------------------------------ interacción ------------------------------
function nodoEnPosicion(sx, sy) {
  const [wx, wy] = screenToWorld(sx, sy);
  let mejor = null;
  let mejorDist = Infinity;
  for (const n of visibleNodes) {
    const r = nodeRadius(n) + 3;
    const d = Math.hypot(n.x - wx, n.y - wy);
    if (d <= r && d < mejorDist) {
      mejor = n;
      mejorDist = d;
    }
  }
  return mejor;
}

canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  if (mouseDownPos) {
    const dist = Math.hypot(e.clientX - mouseDownPos[0], e.clientY - mouseDownPos[1]);
    if (dist > 4) mouseMoved = true;
  }

  if (dragging) {
    const [wx, wy] = screenToWorld(sx, sy);
    dragging.fx = wx;
    dragging.fy = wy;
    simulation.alpha(Math.max(simulation.alpha(), 0.15));
    return;
  }
  if (panning) {
    view.x = panStart.vx + (e.clientX - panStart.mx);
    view.y = panStart.vy + (e.clientY - panStart.my);
    return;
  }

  const n = nodoEnPosicion(sx, sy);
  hoveredNode = n;
  if (n) {
    canvas.style.cursor = "pointer";
    tooltip.classList.remove("oculto");
    tooltip.style.left = e.clientX + "px";
    tooltip.style.top = e.clientY + "px";
    const tipoLegible = { carpeta: "Carpeta", archivo: "Archivo", more: "Más elementos" }[n.type] || n.type;
    const categoriaLegible = {
      pdf: "PDF", imagen: "Imagen", codigo: "Código", doc: "Documento",
      video: "Video", audio: "Música", otro: "Otro",
    }[n.category];
    tooltip.innerHTML = `<div class="nombre">${escapeHtml(n.name)}</div><div class="meta">${tipoLegible}${
      n.type === "archivo" ? " · " + categoriaLegible + " · " + formatBytes(n.size) : ""
    }</div>`;
  } else {
    canvas.style.cursor = panning ? "grabbing" : "grab";
    tooltip.classList.add("oculto");
  }
});

canvas.addEventListener("mousedown", (e) => {
  mouseDownPos = [e.clientX, e.clientY];
  mouseMoved = false;
  ocultarMenu();
  const rect = canvas.getBoundingClientRect();
  const n = nodoEnPosicion(e.clientX - rect.left, e.clientY - rect.top);
  if (n && n.id !== rootId) {
    dragging = n;
  } else if (n && n.id === rootId) {
    // el núcleo central no se arrastra, pero permite iniciar pan igual
    panning = true;
    panStart = { mx: e.clientX, my: e.clientY, vx: view.x, vy: view.y };
  } else {
    panning = true;
    panStart = { mx: e.clientX, my: e.clientY, vx: view.x, vy: view.y };
  }
});

window.addEventListener("mouseup", (e) => {
  if (dragging) {
    dragging.fx = null;
    dragging.fy = null;
  }
  if (!mouseMoved && mouseDownPos) {
    const rect = canvas.getBoundingClientRect();
    const n = nodoEnPosicion(e.clientX - rect.left, e.clientY - rect.top);
    if (n) manejarClick(n, e);
  }
  dragging = null;
  panning = false;
  mouseDownPos = null;
});

canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;
  const [wx, wy] = screenToWorld(sx, sy);
  const factor = Math.exp(-e.deltaY * 0.0012);
  view.k = Math.min(CONFIG.zoom.max, Math.max(CONFIG.zoom.min, view.k * factor));
  view.x = sx - wx * view.k;
  view.y = sy - wy * view.k;
}, { passive: false });

function manejarClick(n, e) {
  if (n.type === "carpeta" && n.id !== rootId) {
    if (collapsed.has(n.id)) collapsed.delete(n.id);
    else collapsed.add(n.id);
    refreshVisible();
    simulation.alpha(0.5).restart();
  } else if (n.type === "more") {
    hoveredNode = null;
    tooltip.classList.add("oculto");
    expandirCarpeta(n, false);
  } else if (n.type === "archivo") {
    contextNode = n;
    menu.classList.remove("oculto");
    menu.style.left = e.clientX + "px";
    menu.style.top = e.clientY + "px";
    suprimirCierreMenu = true;
  }
}

let suprimirCierreMenu = false;
function ocultarMenu() {
  menu.classList.add("oculto");
  contextNode = null;
}
document.addEventListener("click", (e) => {
  if (suprimirCierreMenu) {
    suprimirCierreMenu = false;
    return;
  }
  if (!menu.contains(e.target)) ocultarMenu();
});
btnAbrir.addEventListener("click", async () => {
  if (!contextNode) return;
  try {
    await fetch("/api/abrir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: contextNode.path }),
    });
  } catch (err) {
    console.error(err);
  }
  ocultarMenu();
});

// ------------------------- expandir/colapsar todo -------------------------
function expandirTodo() {
  collapsed.clear();
  refreshVisible();
  simulation.alpha(0.6).restart();
}

function colapsarTodo() {
  collapsed.clear();
  for (const n of nodesById.values()) {
    if (n.type === "carpeta" && n.id !== rootId) collapsed.add(n.id);
  }
  refreshVisible();
  simulation.alpha(0.6).restart();
}

btnExpandirTodo.addEventListener("click", expandirTodo);
btnColapsarTodo.addEventListener("click", colapsarTodo);
btnAvisoColapsar.addEventListener("click", colapsarTodo);
btnAvisoCerrar.addEventListener("click", () => avisoRendimiento.classList.add("oculto"));

// ------------------------------- búsqueda -------------------------------
function centrarEn(nodo) {
  const targetK = Math.max(view.k, 0.8);
  camAnim = {
    fromX: view.x, fromY: view.y, fromK: view.k,
    toX: width / 2 - nodo.x * targetK, toY: height / 2 - nodo.y * targetK, toK: targetK,
    start: ahora, dur: 650,
  };
  // una vez terminado el salto inicial, la cámara sigue al nodo suavemente
  // mientras la física todavía lo esté acomodando (ver render())
  siguiendoId = nodo.id;
}

function buscarNodo(query) {
  query = query.trim().toLowerCase();
  if (!query) return;

  const candidatos = [...nodesById.values()].filter(
    (n) => n.type !== "more" && n.name.toLowerCase().includes(query)
  );
  if (!candidatos.length) {
    buscador.classList.remove("sin-resultado");
    void buscador.offsetWidth; // reinicia la animación si se busca dos veces seguidas
    buscador.classList.add("sin-resultado");
    return;
  }
  candidatos.sort((a, b) => a.name.length - b.name.length);
  const objetivo = candidatos[0];

  // expande todos los ancestros del nodo encontrado para que sea visible
  let actual = objetivo;
  while (actual && actual.parent) {
    collapsed.delete(actual.parent);
    actual = nodesById.get(actual.parent);
  }
  refreshVisible();
  simulation.alpha(0.3).restart();

  resaltados = new Set(candidatos.map((c) => c.id));
  resaltadoHasta = ahora + 3500;
  centrarEn(objetivo);
}

buscador.addEventListener("keydown", (e) => {
  if (e.key === "Enter") buscarNodo(buscador.value);
});
buscador.addEventListener("input", () => buscador.classList.remove("sin-resultado"));

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}
function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

// ------------------------------- red / datos -------------------------------
let ws = null;
function conectarWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    elConexion.textContent = "● en vivo";
    elConexion.className = "conectado";
  };
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === "estructura") {
      const huboCambios = applyStructure(data, true);
      if (huboCambios) parpadearEnVivo();
    }
  };
  ws.onclose = () => {
    elConexion.textContent = "● reconectando…";
    elConexion.className = "desconectado";
    setTimeout(conectarWebSocket, 1500);
  };
  ws.onerror = () => ws.close();
}

// destella el indicador "en vivo" cada vez que se aplica un cambio real
// (alta/baja/movida) detectado por watchdog, para confirmar que está
// sincronizado sin que el usuario tenga que adivinar
function parpadearEnVivo() {
  elConexion.classList.remove("parpadeo");
  void elConexion.offsetWidth; // fuerza reflow para poder reiniciar la animación
  elConexion.classList.add("parpadeo");
}

async function cargaInicial() {
  try {
    const res = await fetch("/api/estructura");
    const data = await res.json();
    applyStructure(data, false);
  } catch (e) {
    elRuta.textContent = "Error al cargar la estructura";
    console.error(e);
  }
  conectarWebSocket();
}

cargaInicial();
