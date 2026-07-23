// ============================================================
// GERAM CORE OS · open-folder.js
// Selector de carpeta de trabajo, estilo "Open Folder" de VS Code: navega
// el disco, elige una carpeta y el explorador entero pasa a apuntar ahí.
//
// Todo el texto se inserta con textContent: los nombres de carpeta son datos
// del usuario y nunca se interpretan como HTML. La validación real vive en el
// backend (app/core/workspace_root.py); aquí sólo reflejamos lo que responde.
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }

  var documentObject = root.document;
  var API = '/api/workspace/root';
  var overlay = null;
  var listElement = null;
  var pathElement = null;
  var openButton = null;
  var noteElement = null;
  var currentPath = '';
  var currentUsable = false;

  function crear(tag, clase, texto) {
    var el = documentObject.createElement(tag);
    if (clase) { el.className = clase; }
    if (texto !== undefined) { el.textContent = texto; }
    return el;
  }

  function avisar(mensaje) {
    if (root.GeramVscodeChrome && typeof root.GeramVscodeChrome.toast === 'function') {
      root.GeramVscodeChrome.toast(mensaje);
      return;
    }
    if (noteElement) { noteElement.textContent = mensaje; }
  }

  // ---- Petición ----
  function pedir(url, opciones) {
    return fetch(url, opciones || {}).then(function (respuesta) {
      return respuesta.json().catch(function () { return {}; }).then(function (cuerpo) {
        if (!respuesta.ok) {
          var detalle = cuerpo && cuerpo.detail;
          var mensaje = (detalle && detalle.message) || 'The folder could not be opened';
          throw new Error(mensaje);
        }
        return cuerpo;
      });
    });
  }

  // ---- Navegación ----
  function navegar(ruta) {
    var url = API + '/browse' + (ruta ? '?path=' + encodeURIComponent(ruta) : '');
    return pedir(url).then(function (datos) {
      currentPath = datos.path || '';
      currentUsable = Boolean(datos.usable);
      pathElement.textContent = currentPath;
      openButton.disabled = !currentUsable;
      noteElement.textContent = currentUsable
        ? ''
        : 'This folder is too broad or protected — choose a project folder inside it.';

      while (listElement.firstChild) { listElement.removeChild(listElement.firstChild); }

      if (datos.parent) {
        var arriba = crear('button', 'of-item of-arriba', '.. (up one level)');
        arriba.type = 'button';
        arriba.addEventListener('click', function () { navegar(datos.parent); });
        listElement.appendChild(arriba);
      }
      (datos.folders || []).forEach(function (carpeta) {
        var boton = crear('button', 'of-item', carpeta.name);
        boton.type = 'button';
        boton.title = carpeta.path;
        boton.addEventListener('click', function () { navegar(carpeta.path); });
        listElement.appendChild(boton);
      });
      if (!(datos.folders || []).length) {
        listElement.appendChild(crear('p', 'of-vacio', 'No subfolders here.'));
      }
      if (datos.truncated) {
        listElement.appendChild(crear('p', 'of-vacio', 'Too many subfolders — only the first ones are shown.'));
      }
    }).catch(function (error) {
      noteElement.textContent = error.message || 'That folder could not be read';
    });
  }

  // ---- Abrir la carpeta seleccionada ----
  function abrir() {
    if (!currentPath || !currentUsable) { return; }
    openButton.disabled = true;
    pedir(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: currentPath })
    }).then(function (datos) {
      cerrar();
      // El árbol, la selección y los documentos abiertos pertenecían a la
      // carpeta anterior: se sueltan igual que al elegir por el diálogo nativo.
      aplicarCarpeta(datos.path || currentPath);
    }).catch(function (error) {
      openButton.disabled = false;
      noteElement.textContent = error.message || 'The folder could not be opened';
    });
  }

  // ---- Construcción del diálogo ----
  function construir() {
    if (overlay) { return overlay; }
    overlay = crear('div', 'of-overlay');
    overlay.id = 'openFolderOverlay';

    var fondo = crear('div', 'of-fondo');
    fondo.addEventListener('click', cerrar);
    overlay.appendChild(fondo);

    var caja = crear('div', 'of-caja');
    caja.setAttribute('role', 'dialog');
    caja.setAttribute('aria-modal', 'true');
    caja.setAttribute('aria-label', 'Open folder');

    var encabezado = crear('div', 'of-header');
    encabezado.appendChild(crear('h2', 'panel-titulo', 'OPEN FOLDER'));
    var cerrarBoton = crear('button', 'of-cerrar', '×');
    cerrarBoton.type = 'button';
    cerrarBoton.title = 'Close';
    cerrarBoton.setAttribute('aria-label', 'Close');
    cerrarBoton.addEventListener('click', cerrar);
    encabezado.appendChild(cerrarBoton);
    caja.appendChild(encabezado);

    pathElement = crear('p', 'of-ruta', '');
    caja.appendChild(pathElement);

    listElement = crear('div', 'of-lista');
    caja.appendChild(listElement);

    noteElement = crear('p', 'of-nota', '');
    noteElement.setAttribute('role', 'status');
    noteElement.setAttribute('aria-live', 'polite');
    caja.appendChild(noteElement);

    var pie = crear('div', 'of-pie');
    var nativo = crear('button', 'of-btn of-nativo', 'System dialog…');
    nativo.type = 'button';
    nativo.title = 'Open your desktop file manager to pick a folder';
    nativo.addEventListener('click', function () {
      elegirConDialogoDelSistema().then(function (resuelto) {
        if (resuelto) { cerrar(); }
      }).catch(function (error) {
        noteElement.textContent = error.message || 'The system dialog is not available here';
      });
    });
    pie.appendChild(nativo);
    var cancelar = crear('button', 'of-btn', 'Cancel');
    cancelar.type = 'button';
    cancelar.addEventListener('click', cerrar);
    openButton = crear('button', 'of-btn principal', 'Open this folder');
    openButton.type = 'button';
    openButton.addEventListener('click', abrir);
    pie.appendChild(cancelar);
    pie.appendChild(openButton);
    caja.appendChild(pie);

    overlay.appendChild(caja);
    documentObject.body.appendChild(overlay);
    return overlay;
  }

  function alPulsarTecla(evento) {
    if (evento.key === 'Escape') { cerrar(); }
  }

  function cerrar() {
    if (overlay) { overlay.hidden = true; }
    documentObject.removeEventListener('keydown', alPulsarTecla);
  }

  // ---- Aplicar una carpeta ya elegida (por el diálogo nativo) ----
  function aplicarCarpeta(ruta) {
    avisar('Workspace: ' + ruta);
    // La selección del árbol apunta al workspace anterior: si sobrevive, el
    // siguiente "crear carpeta" la manda como padre y el backend responde 404.
    root.dispatchEvent(new root.CustomEvent('geram:workspace-selection', { detail: null }));
    var controlador = root.GeramWorkspaceController;
    if (controlador && typeof controlador.reloadTree === 'function') {
      controlador.reloadTree();
      if (typeof controlador.refreshState === 'function') { controlador.refreshState(); }
    } else {
      root.location.reload();
    }
  }

  // ---- Diálogo nativo del sistema (Thunar/Explorer/Finder) ----
  // Es lo que espera cualquiera: el selector de carpetas del escritorio. Si
  // el backend no puede abrirlo (sin entorno gráfico, sin zenity/kdialog),
  // caemos al navegador de carpetas propio en lugar de dejar al usuario sin
  // salida.
  function elegirConDialogoDelSistema() {
    return pedir(API + '/pick', { method: 'POST' }).then(function (datos) {
      if (datos && datos.cancelled) { return true; }  // canceló: no abrimos nada más
      if (datos && datos.path) { aplicarCarpeta(datos.path); return true; }
      return false;
    });
  }

  function abrirSelector() {
    pedir(API + '/native').then(function (estado) {
      if (!estado || !estado.available) { mostrar(); return; }
      elegirConDialogoDelSistema().then(function (resuelto) {
        if (!resuelto) { mostrar(); }
      }).catch(function () {
        // El diálogo del sistema falló en caliente: navegador propio.
        mostrar();
      });
    }).catch(function () { mostrar(); });
  }

  function mostrar() {
    construir();
    overlay.hidden = false;
    documentObject.addEventListener('keydown', alPulsarTecla);
    noteElement.textContent = '';
    // Arranca en la carpeta actual para que se vea dónde estás parado.
    pedir(API).then(function (datos) {
      return navegar(datos && datos.path ? datos.path : '');
    }).catch(function () { return navegar(''); });
  }

  root.GeramOpenFolder = {
    open: abrirSelector,      // intenta el diálogo del sistema primero
    browse: mostrar,          // navegador de carpetas propio (respaldo)
    close: cerrar
  };
}(typeof window !== 'undefined' ? window : null));
