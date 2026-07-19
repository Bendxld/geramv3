// ============================================================
// GERAM CORE OS · workspace-upload.js
// Traer archivos y carpetas de tu disco al workspace: arrastrándolos sobre
// el explorador, o con el botón "Upload…" (que permite elegir una carpeta
// entera y conserva su estructura).
//
// Sube UN archivo por petición (/api/workspace/upload?path=…), igual que los
// adjuntos del chat: sin multipart, con el cuerpo acotado. La validación de
// rutas vive entera en el backend; aquí sólo se normaliza lo justo para
// construir la ruta relativa que el usuario está viendo.
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }

  var documentObject = root.document;
  var API = '/api/workspace/upload';

  // Cotas de cordura del lado del cliente. El backend impone las suyas; estas
  // existen para no lanzar 3.000 peticiones si alguien suelta node_modules.
  var MAX_ARCHIVOS = 300;
  var MAX_BYTES = 25 * 1024 * 1024;

  function avisar(mensaje) {
    if (root.GeramVscodeChrome && typeof root.GeramVscodeChrome.toast === 'function') {
      root.GeramVscodeChrome.toast(mensaje);
    }
  }

  function recargarArbol() {
    var controlador = root.GeramWorkspaceController;
    if (controlador && typeof controlador.reloadTree === 'function') {
      controlador.reloadTree();
    }
  }

  // Nombre seguro para UN componente de ruta. El backend rechaza lo que no
  // valga, pero limpiar aquí evita peticiones condenadas de antemano.
  function limpiarComponente(nombre) {
    return String(nombre || '')
      .replace(/[\\/]/g, '_')
      .replace(/^\.+$/, '_')
      .slice(0, 120);
  }

  function rutaRelativaDe(archivo) {
    // webkitRelativePath viene relleno al elegir una carpeta: conserva la
    // estructura ("mi-proyecto/src/app.py"). Si no, es un archivo suelto.
    var bruta = archivo.webkitRelativePath || archivo.name || 'archivo';
    return bruta.split('/').map(limpiarComponente).filter(Boolean).join('/');
  }

  function subirUno(archivo) {
    var ruta = rutaRelativaDe(archivo);
    if (!ruta) { return Promise.resolve({ ok: false, nombre: archivo.name, motivo: 'invalid_path' }); }
    if (archivo.size > MAX_BYTES) {
      return Promise.resolve({ ok: false, nombre: ruta, motivo: 'file_too_large' });
    }
    return fetch(API + '?path=' + encodeURIComponent(ruta), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: archivo
    }).then(function (respuesta) {
      if (respuesta.ok) { return { ok: true, nombre: ruta }; }
      return respuesta.json().catch(function () { return {}; }).then(function (cuerpo) {
        var detalle = cuerpo && cuerpo.detail;
        return { ok: false, nombre: ruta, motivo: (detalle && detalle.code) || 'upload_failed' };
      });
    }).catch(function () {
      return { ok: false, nombre: ruta, motivo: 'network' };
    });
  }

  function resumir(resultados) {
    var subidos = resultados.filter(function (r) { return r.ok; }).length;
    var fallidos = resultados.length - subidos;
    if (!fallidos) {
      avisar(subidos === 1 ? 'Uploaded 1 file' : 'Uploaded ' + subidos + ' files');
      return;
    }
    // Un motivo concreto ayuda mucho más que "fallaron 3".
    var yaExiste = resultados.filter(function (r) { return r.motivo === 'file_exists'; }).length;
    var grandes = resultados.filter(function (r) { return r.motivo === 'file_too_large'; }).length;
    var partes = [];
    if (subidos) { partes.push(subidos + ' uploaded'); }
    if (yaExiste) { partes.push(yaExiste + ' already existed'); }
    if (grandes) { partes.push(grandes + ' too large'); }
    var otros = fallidos - yaExiste - grandes;
    if (otros > 0) { partes.push(otros + ' failed'); }
    avisar(partes.join(', '));
  }

  // Las subidas van en serie a propósito: son escrituras en disco y da mejor
  // señal (y menos presión) que disparar cientos de peticiones a la vez.
  function subirTodos(archivos) {
    var lista = Array.prototype.slice.call(archivos || []);
    if (!lista.length) { return; }
    var recortado = lista.length > MAX_ARCHIVOS;
    if (recortado) { lista = lista.slice(0, MAX_ARCHIVOS); }
    avisar('Uploading ' + lista.length + (lista.length === 1 ? ' file…' : ' files…'));

    var resultados = [];
    var cadena = lista.reduce(function (previa, archivo) {
      return previa.then(function () {
        return subirUno(archivo).then(function (resultado) { resultados.push(resultado); });
      });
    }, Promise.resolve());

    cadena.then(function () {
      resumir(resultados);
      if (recortado) {
        avisar('Only the first ' + MAX_ARCHIVOS + ' files were uploaded');
      }
      recargarArbol();
    });
  }

  // ---- Arrastrar y soltar sobre el explorador ----
  function conectarArrastre(zona) {
    if (!zona) { return; }
    ['dragenter', 'dragover'].forEach(function (evento) {
      zona.addEventListener(evento, function (e) {
        // Sólo reaccionamos a archivos del sistema, no a arrastres internos
        // del árbol (mover ficheros ya tiene su propio flujo con aprobación).
        if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') === -1) { return; }
        e.preventDefault();
        zona.classList.add('subiendo-encima');
      });
    });
    ['dragleave', 'drop'].forEach(function (evento) {
      zona.addEventListener(evento, function () { zona.classList.remove('subiendo-encima'); });
    });
    zona.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) { return; }
      e.preventDefault();
      subirTodos(e.dataTransfer.files);
    });
  }

  // ---- Botón "Upload…" ----
  function crearEntrada(conCarpeta) {
    var entrada = documentObject.createElement('input');
    entrada.type = 'file';
    entrada.multiple = true;
    entrada.hidden = true;
    if (conCarpeta) {
      // Sube una carpeta entera conservando su estructura.
      entrada.webkitdirectory = true;
      entrada.setAttribute('webkitdirectory', '');
    }
    entrada.addEventListener('change', function () {
      subirTodos(entrada.files);
      entrada.value = '';
      if (entrada.parentNode) { entrada.parentNode.removeChild(entrada); }
    });
    documentObject.body.appendChild(entrada);
    return entrada;
  }

  function elegirArchivos() { crearEntrada(false).click(); }
  function elegirCarpeta() { crearEntrada(true).click(); }

  function inicializar() {
    conectarArrastre(documentObject.getElementById('workspaceArbol'));
  }

  if (documentObject.readyState === 'loading') {
    documentObject.addEventListener('DOMContentLoaded', inicializar);
  } else {
    inicializar();
  }

  root.GeramWorkspaceUpload = {
    files: elegirArchivos,
    folder: elegirCarpeta,
    uploadAll: subirTodos
  };
}(typeof window !== 'undefined' ? window : null));
