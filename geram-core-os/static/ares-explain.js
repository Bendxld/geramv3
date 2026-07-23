/* Explicaciones de código de A.R.E.S. — sólo lectura.
 *
 * Este módulo NO aplica cambios, no toca el flujo de propuesta/diff y no
 * escribe en el workspace. Sólo pide una explicación, enseña antes qué se va
 * a enviar, y renderiza el resultado.
 *
 * Todo el contenido devuelto por el proveedor se inserta con textContent:
 * ni una sola ruta de este archivo construye HTML a partir de la respuesta.
 * Nada se guarda: el resultado vive en memoria y desaparece al recargar.
 */
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }

  var documentObject = root.document;
  var API = '/api/ares/explanations';

  var botonSeleccion = documentObject.getElementById('aresExplicaSeleccion');
  var botonArchivo = documentObject.getElementById('aresExplicaArchivo');
  var botonProyecto = documentObject.getElementById('aresExplicaProyecto');
  var selectorNivel = documentObject.getElementById('aresExplicaNivel');
  var casillaOffline = documentObject.getElementById('aresExplicaOffline');
  var cajaPreview = documentObject.getElementById('aresExplicaPreview');
  var cajaResultado = documentObject.getElementById('aresExplicaResultado');
  var estado = documentObject.getElementById('aresExplicaStatus');
  if (!botonSeleccion || !botonArchivo || !botonProyecto) { return; }

  var ocupado = false;
  var ultimaExplicacion = null;

  function t(key) {
    var i18n = root.GeramI18n;
    return (i18n && i18n.t) ? i18n.t(key) : key;
  }

  var MENSAJES = {
    empty_selection: 'ax.err.selection',
    empty_file: 'ax.err.file',
    empty_project: 'ax.err.project',
    not_found: 'ax.err.notfound',
    protected_path: 'ax.err.protected',
    excluded_path: 'ax.err.excluded',
    context_too_large: 'ax.err.toolarge',
    invalid_contract: 'ax.err.contract',
    invalid_reference: 'ax.err.reference',
    unsafe_content: 'ax.err.unsafe',
    provider_unavailable: 'ax.err.provider'
  };

  function crear(tag, clase, texto) {
    var el = documentObject.createElement(tag);
    if (clase) { el.className = clase; }
    if (texto !== undefined && texto !== null) { el.textContent = String(texto); }
    return el;
  }

  function vaciar(nodo) {
    while (nodo && nodo.firstChild) { nodo.removeChild(nodo.firstChild); }
  }

  function setEstado(mensaje, esError) {
    estado.textContent = mensaje || '';
    estado.classList.toggle('error', Boolean(esError));
  }

  function mensajeDe(codigo) {
    return t(MENSAJES[codigo] || 'ax.err.generic');
  }

  function pedir(ruta, cuerpo) {
    return fetch(ruta, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo)
    }).then(function (respuesta) {
      return respuesta.json().catch(function () { return {}; }).then(function (datos) {
        if (respuesta.ok) { return datos; }
        var detalle = datos && datos.detail;
        var codigo = (detalle && detalle.code) || 'error';
        throw new Error(mensajeDe(codigo));
      });
    });
  }

  // ---- Alcance a partir del editor ----
  function controlador() { return root.GeramWorkspaceController; }

  function rutaActiva() {
    var c = controlador();
    return (c && typeof c.activePath === 'function' && c.activePath()) || '';
  }

  // El controlador expone editorReady (una promesa), no el adaptador ya
  // resuelto: lo cacheamos en cuanto Monaco está listo. Este script puede
  // cargarse antes de que exista el controlador, así que el enganche se
  // reintenta hasta conseguirlo.
  var adaptadorEditor = null;
  var enganchado = false;
  function engancharEditor() {
    if (enganchado) { return; }
    var c = controlador();
    if (!c || !c.editorReady || typeof c.editorReady.then !== 'function') { return; }
    enganchado = true;
    c.editorReady.then(function (adaptador) { adaptadorEditor = adaptador; })
      .catch(function () { enganchado = false; });
  }
  engancharEditor();

  function seleccionActiva() {
    engancharEditor();
    var adaptador = adaptadorEditor;
    var editor = adaptador && adaptador.editor;
    if (!editor || typeof editor.getSelection !== 'function') { return null; }
    var rango = editor.getSelection();
    var modelo = typeof editor.getModel === 'function' ? editor.getModel() : null;
    if (!rango || !modelo || typeof modelo.getValueInRange !== 'function') { return null; }
    var texto = modelo.getValueInRange(rango);
    if (!texto || !texto.trim()) { return null; }
    return {
      selection: texto,
      start_line: rango.startLineNumber,
      end_line: rango.endLineNumber
    };
  }

  // Diagnósticos que el editor YA muestra para el archivo activo. Se mandan
  // con la petición porque son los que el usuario está viendo; el backend no
  // puede saberlos por su cuenta sin duplicar el trabajo de Monaco/Pyright.
  var SEVERIDADES = { 8: 'error', 4: 'warning', 2: 'info', 1: 'hint' };

  function diagnosticosActivos(ruta) {
    engancharEditor();
    var adaptador = adaptadorEditor;
    var monaco = adaptador && adaptador.monaco;
    if (!monaco || !monaco.editor || typeof monaco.editor.getModelMarkers !== 'function') {
      return [];
    }
    var marcadores;
    try {
      marcadores = monaco.editor.getModelMarkers({}) || [];
    } catch (error) {
      return [];
    }
    return marcadores.filter(function (m) {
      // Sólo los del archivo que se está explicando.
      return !ruta || (m.resource && String(m.resource.path || '').indexOf(ruta) !== -1);
    }).slice(0, 20).map(function (m) {
      return {
        severity: SEVERIDADES[m.severity] || 'info',
        line: m.startLineNumber || 0,
        message: String(m.message || '').slice(0, 500)
      };
    });
  }

  // ---- Preview del contexto (antes de enviar nada) ----
  // Cabecera con botón de plegar. El panel vive debajo del editor: si crece
  // sin límite, empuja el código fuera de la pantalla y no se puede seguir
  // escribiendo. Por eso todo lo que se pinta aquí se puede plegar, y además
  // tiene altura máxima con scroll propio (ver .ares-explica-cuerpo en CSS).
  function cabeceraPlegable(caja, titulo, cuerpo, alCerrar) {
    var cabecera = crear('div', 'ares-explica-cabecera');
    var plegar = crear('button', 'ares-explica-plegar', '▾');
    plegar.type = 'button';
    plegar.title = t('ax.collapse');
    plegar.setAttribute('aria-expanded', 'true');
    plegar.addEventListener('click', function () {
      var oculto = cuerpo.hidden;
      cuerpo.hidden = !oculto;
      plegar.textContent = oculto ? '▾' : '▸';
      plegar.setAttribute('aria-expanded', String(oculto));
    });
    cabecera.appendChild(plegar);
    cabecera.appendChild(crear('h4', null, titulo));
    var cerrar = crear('button', 'ares-explica-cerrar', '×');
    cerrar.type = 'button';
    cerrar.title = 'Hide';
    cerrar.setAttribute('aria-label', 'Hide ' + titulo);
    cerrar.addEventListener('click', function () {
      caja.hidden = true;
      if (alCerrar) { alCerrar(); }
    });
    cabecera.appendChild(cerrar);
    return cabecera;
  }

  function pintarPreview(preview) {
    vaciar(cajaPreview);
    cajaPreview.hidden = false;
    var cuerpo = crear('div', 'ares-explica-cuerpo');
    cajaPreview.appendChild(cabeceraPlegable(cajaPreview, t('ax.context'), cuerpo));
    cajaPreview.appendChild(cuerpo);
    var lista = crear('ul', 'ares-explica-preview-lista');

    function fila(etiqueta, valor) {
      var li = crear('li');
      li.appendChild(crear('span', 'ares-explica-clave', etiqueta));
      li.appendChild(crear('span', 'ares-explica-valor', valor));
      lista.appendChild(li);
    }

    fila(t('ax.provider'), preview.provider || t('ax.notconfigured'));
    fila('Model', preview.model || '(not configured)');
    fila('Scope', preview.scope);
    fila('Level', preview.level);
    fila(t('ax.selincluded'), preview.selection_included ? t('ax.yes') : t('ax.no'));
    if (preview.selection) {
      fila(t('ax.selection'), preview.selection.path + t('ax.lines') +
        preview.selection.start_line + '-' + preview.selection.end_line +
        (preview.selection.symbol ? ' · ' + preview.selection.symbol : ''));
    }
    fila(t('ax.filesincluded'), String((preview.files || []).length));
    (preview.files || []).forEach(function (archivo) {
      fila('· ' + archivo.path, archivo.chars + ' characters' + (archivo.truncated ? ' (truncated)' : ''));
    });
    if (preview.diagnostics) { fila(t('ax.diagnostics'), String(preview.diagnostics)); }
    if (preview.references) { fila(t('ax.occurrences'), String(preview.references)); }
    if (preview.changed_files) { fila(t('ax.gitmodified'), String(preview.changed_files)); }
    var fuentes = preview.sources || {};
    Object.keys(fuentes).forEach(function (clave) {
      fila('  source · ' + clave, fuentes[clave]);
    });
    fila(t('ax.size'), preview.approximate_chars + t('ax.chars'));
    fila(t('ax.secrets'), preview.secrets_excluded ? t('ax.secretsyes') : t('ax.no'));
    cuerpo.appendChild(lista);
    (preview.notes || []).forEach(function (nota) {
      cuerpo.appendChild(crear('p', 'ares-explica-nota', nota));
    });
  }

  // ---- Vista estructurada del resultado ----
  function seccionLista(titulo, valores) {
    if (!valores || !valores.length) { return null; }
    var bloque = crear('div', 'ares-explica-bloque');
    bloque.appendChild(crear('h4', null, titulo));
    var lista = crear('ul');
    valores.forEach(function (valor) { lista.appendChild(crear('li', null, valor)); });
    bloque.appendChild(lista);
    return bloque;
  }

  function seccionTexto(titulo, valor) {
    if (!valor) { return null; }
    var bloque = crear('div', 'ares-explica-bloque');
    bloque.appendChild(crear('h4', null, titulo));
    bloque.appendChild(crear('p', null, valor));
    return bloque;
  }

  // Abrir la ubicación citada. navigate() sólo revela dentro de documentos YA
  // cargados: si el archivo no está abierto, state.activate() devuelve falso y
  // la navegación fallaría en silencio. Por eso se abre primero y se reintenta
  // revelar, con un tope para no quedarse girando si el archivo no se puede
  // abrir (binario, protegido, borrado).
  function irAReferencia(ref) {
    var c = controlador();
    if (!c || typeof c.navigate !== 'function') { return; }

    function revelar(intentos) {
      c.navigate(ref.file, ref.start_line, 1).then(function (ok) {
        if (ok) { setEstado(t('ax.opened').replace('{ref}', ref.file + ':' + ref.start_line)); return; }
        if (intentos <= 0) {
          setEstado(t('ax.openfail').replace('{file}', ref.file), true);
          return;
        }
        root.setTimeout(function () { revelar(intentos - 1); }, 150);
      }).catch(function () {
        setEstado(t('ax.openfail').replace('{file}', ref.file), true);
      });
    }

    if (c.activePath && c.activePath() === ref.file) { revelar(0); return; }
    if (typeof c.open === 'function') { c.open(ref.file); }
    revelar(12);
  }

  function seccionReferencias(referencias) {
    if (!referencias || !referencias.length) { return null; }
    var bloque = crear('div', 'ares-explica-bloque');
    bloque.appendChild(crear('h4', null, t('ax.coderefs')));
    var lista = crear('ul', 'ares-explica-refs');
    referencias.forEach(function (ref) {
      var li = crear('li');
      var etiqueta = ref.file + ':' + ref.start_line +
        (ref.end_line !== ref.start_line ? '-' + ref.end_line : '') +
        (ref.symbol ? ' · ' + ref.symbol : '');
      var boton = crear('button', 'ares-explica-ir', etiqueta);
      boton.type = 'button';
      boton.title = t('ax.openat').replace('{file}', ref.file).replace('{line}', ref.start_line);
      boton.addEventListener('click', function () { irAReferencia(ref); });
      li.appendChild(boton);
      if (ref.claim) { li.appendChild(crear('span', 'ares-explica-claim', ref.claim)); }
      lista.appendChild(li);
    });
    bloque.appendChild(lista);
    return bloque;
  }

  function seccionInferencias(inferencias) {
    if (!inferencias || !inferencias.length) { return null; }
    var bloque = crear('div', 'ares-explica-bloque ares-explica-inferencias');
    bloque.appendChild(crear('h4', null, t('ax.inferences')));
    bloque.appendChild(crear('p', 'ares-explica-nota',
      t('ax.inferencesnote')));
    var lista = crear('ul');
    inferencias.forEach(function (inferencia) {
      var li = crear('li');
      li.appendChild(crear('span', 'ares-explica-confianza', 'confidence: ' + inferencia.confidence));
      li.appendChild(crear('span', 'ares-explica-inferencia-texto', inferencia.text));
      if (inferencia.evidence && inferencia.evidence.length) {
        var pruebas = crear('ul', 'ares-explica-evidencia');
        inferencia.evidence.forEach(function (e) { pruebas.appendChild(crear('li', null, e)); });
        li.appendChild(pruebas);
      }
      lista.appendChild(li);
    });
    bloque.appendChild(lista);
    return bloque;
  }

  function pintarResultado(datos) {
    var explicacion = datos.explanation || {};
    ultimaExplicacion = explicacion;
    vaciar(cajaResultado);
    cajaResultado.hidden = false;

    var cuerpo = crear('div', 'ares-explica-cuerpo');
    cajaResultado.appendChild(cabeceraPlegable(
      cajaResultado, datos.demo ? t('ax.explanationdemo') : t('ax.explanation'), cuerpo));
    cajaResultado.appendChild(cuerpo);

    if (datos.demo) {
      cuerpo.appendChild(crear('p', 'ares-explica-demo',
        t('ax.demotpl')));
    }

    [
      seccionTexto(t('ax.summary'), explicacion.summary),
      seccionTexto(t('ax.purpose'), explicacion.purpose),
      seccionLista('Flow', explicacion.flow),
      seccionLista(t('ax.inputs'), explicacion.inputs),
      seccionLista(t('ax.outputs'), explicacion.outputs),
      seccionLista(t('ax.deps'), explicacion.dependencies),
      seccionLista(t('explain.risks'), explicacion.risks),
      seccionReferencias(explicacion.references),
      seccionInferencias(explicacion.inferences)
    ].forEach(function (bloque) {
      if (bloque) { cuerpo.appendChild(bloque); }
    });

    // Acción separada y explícita: SÓLO copia un resumen al cuadro de
    // A.R.E.S. No ejecuta, no edita y no crea propuesta.
    var acciones = crear('div', 'ares-explica-actions');
    var usar = crear('button', null, t('ax.usetask'));
    usar.type = 'button';
    usar.addEventListener('click', usarParaTarea);
    acciones.appendChild(usar);
    // Cerrar el resultado Y el contexto de una vez: es lo que se quiere
    // cuando terminas de leer y vuelves a escribir código.
    var ocultar = crear('button', null, t('ax.hideall'));
    ocultar.type = 'button';
    ocultar.addEventListener('click', function () {
      cajaResultado.hidden = true;
      cajaPreview.hidden = true;
      setEstado('');
    });
    acciones.appendChild(ocultar);
    cuerpo.appendChild(acciones);
  }

  function usarParaTarea() {
    var caja = documentObject.getElementById('workspaceAresInstruction');
    if (!caja || !ultimaExplicacion) { return; }
    var partes = [];
    if (ultimaExplicacion.summary) { partes.push(ultimaExplicacion.summary); }
    if (ultimaExplicacion.risks && ultimaExplicacion.risks.length) {
      partes.push(t('ax.risksreported') + ultimaExplicacion.risks.join('; '));
    }
    caja.value = partes.join('\n\n');
    caja.focus();
    setEstado(t('ax.copied'));
  }

  // ---- Flujo ----
  function explicar(scope) {
    if (ocupado) { return; }
    var cuerpo = {
      scope: scope,
      level: selectorNivel ? selectorNivel.value : 'technical',
      offline: Boolean(casillaOffline && casillaOffline.checked)
    };

    if (scope === 'selection') {
      var seleccion = seleccionActiva();
      if (!seleccion) { setEstado(MENSAJES.empty_selection, true); return; }
      cuerpo.path = rutaActiva();
      cuerpo.selection = seleccion.selection;
      cuerpo.start_line = seleccion.start_line;
      cuerpo.end_line = seleccion.end_line;
      if (!cuerpo.path) { setEstado(t('ax.openselection'), true); return; }
      cuerpo.diagnostics = diagnosticosActivos(cuerpo.path);
    } else if (scope === 'file') {
      cuerpo.path = rutaActiva();
      if (!cuerpo.path) { setEstado(t('ax.openfile'), true); return; }
      cuerpo.diagnostics = diagnosticosActivos(cuerpo.path);
    }

    ocupado = true;
    setEstado(t('ax.preparing'));
    cajaResultado.hidden = true;

    // Preview SIEMPRE primero: el usuario ve qué se envía antes de enviarlo.
    pedir(API + '/preview', cuerpo).then(function (preview) {
      pintarPreview(preview);
      setEstado(cuerpo.offline ? t('ax.generatingdemo') : t('ax.asking'));
      return pedir(API, cuerpo);
    }).then(function (datos) {
      pintarResultado(datos);
      setEstado(datos.demo ? t('ax.demoready') : t('ax.ready'));
    }).catch(function (error) {
      setEstado(error.message, true);
    }).then(function () {
      ocupado = false;
    });
  }

  botonSeleccion.addEventListener('click', function () { explicar('selection'); });
  botonArchivo.addEventListener('click', function () { explicar('file'); });
  botonProyecto.addEventListener('click', function () { explicar('project'); });

  root.GeramAresExplain = {
    explain: explicar,
    lastExplanation: function () { return ultimaExplicacion; }
  };
}(typeof window !== 'undefined' ? window : null));
