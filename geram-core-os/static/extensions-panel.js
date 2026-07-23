// ============================================================
// GERAM CORE OS · extensions-panel.js
// Importar/crear/usar contribuciones DECLARATIVAS de extensiones de VS Code
// en Monaco: temas, snippets, gramáticas (TextMate) y configuración de
// lenguajes. Habla con /api/extensions/* (ver app/api/extensions.py). Monaco
// no puede correr el código de una .vsix; sí puede consumir estas piezas.
//   · Aplica al editor: defineTheme, registerCompletionItemProvider,
//     languages.register + setLanguageConfiguration, y (si el runtime
//     TextMate está cargado) tokenización por gramática.
//   · Panel: importar .vsix/JSON, listar, crear tema/snippet, borrar, y un
//     selector de tema.
// ============================================================
(function (windowObject, documentObject) {
  'use strict';

  var THEME_KEY = 'geram-tema-activo';
  var proveedoresSnippets = [];   // disposables de completion providers
  var lenguajesRegistrados = {};  // id -> true
  var temasDefinidos = {};        // themeName -> {label}
  var monacoRef = null;

  function $(id) { return documentObject.getElementById(id); }

  function api(url, opts) {
    return windowObject.fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}))
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          if (!r.ok) {
            var m = (b && b.detail && (b.detail.message || b.detail.code)) || ('Error ' + r.status);
            throw new Error(m);
          }
          return b;
        });
      });
  }

  function slug(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 90);
  }

  // ---- espera a que Monaco esté disponible (se carga al abrir el workspace)
  function conMonaco(cb) {
    if (monacoRef) { cb(monacoRef); return; }
    var intentos = 0;
    var timer = windowObject.setInterval(function () {
      intentos++;
      if (windowObject.monaco && windowObject.monaco.editor && windowObject.monaco.languages) {
        windowObject.clearInterval(timer);
        monacoRef = windowObject.monaco;
        cb(monacoRef);
      } else if (intentos > 600) {  // ~5 min; el editor puede no abrirse nunca
        windowObject.clearInterval(timer);
      }
    }, 500);
  }

  // ================= aplicar contribuciones a Monaco =================
  function convertirLanguageConfig(cfg) {
    if (!cfg || typeof cfg !== 'object') { return null; }
    var out = {};
    if (cfg.comments) { out.comments = cfg.comments; }
    if (Array.isArray(cfg.brackets)) { out.brackets = cfg.brackets; }
    function pares(lista) {
      return (lista || []).map(function (p) {
        if (Array.isArray(p)) { return { open: p[0], close: p[1] }; }
        if (p && p.open) { return { open: p.open, close: p.close }; }
        return null;
      }).filter(Boolean);
    }
    var ac = pares(cfg.autoClosingPairs);
    if (ac.length) { out.autoClosingPairs = ac; }
    var sp = pares(cfg.surroundingPairs);
    if (sp.length) { out.surroundingPairs = sp; }
    if (typeof cfg.wordPattern === 'string') {
      try { out.wordPattern = new RegExp(cfg.wordPattern); } catch (e) { /* ignora regex inválida */ }
    } else if (cfg.wordPattern && cfg.wordPattern.pattern) {
      try { out.wordPattern = new RegExp(cfg.wordPattern.pattern, cfg.wordPattern.flags || ''); } catch (e2) { /* noop */ }
    }
    return out;
  }

  function aplicarLenguajes(monaco) {
    return api('/api/extensions/languages').then(function (d) {
      (d.languages || []).forEach(function (lang) {
        if (!lang.id || lenguajesRegistrados[lang.id]) { return; }
        try {
          monaco.languages.register({ id: lang.id, extensions: lang.extensions || [], aliases: lang.aliases || [] });
          var cfg = convertirLanguageConfig(lang.configuration);
          if (cfg) { monaco.languages.setLanguageConfiguration(lang.id, cfg); }
          lenguajesRegistrados[lang.id] = true;
        } catch (e) { /* un lenguaje malo no debe tumbar el resto */ }
      });
    }).catch(function () { /* silencioso */ });
  }

  function aplicarTemas(monaco) {
    return api('/api/extensions/themes').then(function (d) {
      (d.themes || []).forEach(function (t) {
        var nombre = slug(t.extension + '-' + t.id) || slug(t.id);
        try {
          monaco.editor.defineTheme(nombre, {
            base: t.base || 'vs-dark', inherit: t.inherit !== false,
            rules: t.rules || [], colors: t.colors || {}
          });
          temasDefinidos[nombre] = { label: (t.label || t.id) + ' · ' + t.extension };
        } catch (e) { /* tema inválido: se omite */ }
      });
    }).catch(function () { /* silencioso */ });
  }

  var SNIPPETS_GLOBALES_EN = ['javascript', 'typescript', 'python', 'html', 'css', 'json', 'markdown', 'plaintext', 'shell'];

  function aplicarSnippets(monaco) {
    // Limpia providers previos para no duplicar al re-aplicar tras importar.
    proveedoresSnippets.forEach(function (d) { try { d.dispose(); } catch (e) { /* noop */ } });
    proveedoresSnippets = [];
    return api('/api/extensions/snippets').then(function (d) {
      var porLenguaje = {};
      var globales = [];
      (d.snippets || []).forEach(function (grupo) {
        var lista = Object.keys(grupo.snippets || {}).map(function (nombre) {
          var s = grupo.snippets[nombre]; return { prefix: s.prefix || nombre, body: s.body || '', description: s.description || '' };
        });
        if ((grupo.language || '*') === '*') { globales = globales.concat(lista); }
        else { (porLenguaje[grupo.language] = porLenguaje[grupo.language] || []).push.apply(porLenguaje[grupo.language], lista); }
      });
      var lenguajes = {};
      Object.keys(porLenguaje).forEach(function (l) { lenguajes[l] = true; });
      if (globales.length) { SNIPPETS_GLOBALES_EN.forEach(function (l) { lenguajes[l] = true; }); Object.keys(lenguajesRegistrados).forEach(function (l) { lenguajes[l] = true; }); }
      Object.keys(lenguajes).forEach(function (lang) {
        var lista = (porLenguaje[lang] || []).concat(globales);
        if (!lista.length) { return; }
        var disp = monaco.languages.registerCompletionItemProvider(lang, {
          provideCompletionItems: function (model, position) {
            var word = model.getWordUntilPosition(position);
            var range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
            return {
              suggestions: lista.map(function (s) {
                return {
                  label: s.prefix, kind: monaco.languages.CompletionItemKind.Snippet,
                  insertText: s.body, insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                  documentation: s.description, detail: 'snippet', range: range
                };
              })
            };
          }
        });
        proveedoresSnippets.push(disp);
      });
    }).catch(function () { /* silencioso */ });
  }

  function aplicarTodo() {
    conMonaco(function (monaco) {
      aplicarLenguajes(monaco)
        .then(function () { return aplicarTemas(monaco); })
        .then(function () { return aplicarSnippets(monaco); })
        .then(function () { return aplicarGramaticas(monaco); })
        .then(function () { poblarSelectorTemas(); restaurarTemaGuardado(monaco); });
    });
  }

  // Gramáticas TextMate: se activa solo si el runtime vendorizado está cargado
  // (ver static/vendor/textmate). Sin él, los lenguajes quedan registrados y
  // resaltan con el fallback básico de Monaco.
  function aplicarGramaticas(monaco) {
    if (!windowObject.GeramTextmate || typeof windowObject.GeramTextmate.wire !== 'function') {
      return Promise.resolve();
    }
    return api('/api/extensions/grammars').then(function (d) {
      try { return windowObject.GeramTextmate.wire(monaco, d.grammars || []); } catch (e) { /* noop */ }
    }).catch(function () { /* silencioso */ });
  }

  // ================= selector de tema =================
  function poblarSelectorTemas() {
    var sel = $('extTemaSelect');
    if (!sel) { return; }
    var actual = sel.value;
    sel.innerHTML = '';
    var base = [['geram-neon', 'GERAM Neon (default)'], ['vs-dark', 'VS Dark'], ['vs', 'VS Light'], ['hc-black', 'High Contrast']];
    base.forEach(function (o) { agregarOpcion(sel, o[0], o[1]); });
    Object.keys(temasDefinidos).forEach(function (name) { agregarOpcion(sel, name, temasDefinidos[name].label); });
    if (actual) { sel.value = actual; }
  }
  function agregarOpcion(sel, value, texto) {
    var o = documentObject.createElement('option'); o.value = value; o.textContent = texto; sel.appendChild(o);
  }
  function restaurarTemaGuardado(monaco) {
    var guardado = windowObject.localStorage ? windowObject.localStorage.getItem(THEME_KEY) : null;
    if (guardado) {
      try { monaco.editor.setTheme(guardado); var sel = $('extTemaSelect'); if (sel) { sel.value = guardado; } } catch (e) { /* tema ya no existe */ }
    }
  }
  function aplicarTemaSeleccionado() {
    var sel = $('extTemaSelect');
    if (!sel) { return; }
    conMonaco(function (monaco) {
      try {
        monaco.editor.setTheme(sel.value);
        if (windowObject.localStorage) { windowObject.localStorage.setItem(THEME_KEY, sel.value); }
        estado('Theme applied.', false);
      } catch (e) { estado('Could not apply theme: ' + e.message, true); }
    });
  }

  // ================= panel (DOM creado en JS) =================
  var panel = null;

  function estado(msg, err) {
    var el = $('extEstado'); if (!el) { return; }
    el.textContent = msg || ''; el.classList.toggle('error', !!err);
  }

  function construirPanel() {
    if (panel) { return panel; }
    panel = documentObject.createElement('div');
    panel.className = 'ext-panel';
    panel.id = 'extensionesPanel';
    panel.innerHTML = [
      '<div class="ext-fondo" id="extFondo"></div>',
      '<div class="ext-caja" role="dialog" aria-modal="true" aria-label="Declarative extensions">',
      '  <div class="ext-header"><h2 class="panel-titulo"><span class="dot"></span>DECLARATIVE EXTENSIONS</h2>',
      '    <button class="ext-cerrar" id="extCerrar" title="Close" aria-label="Close">&times;</button></div>',
      '  <div class="ext-cuerpo">',
      '    <p class="ext-nota"><b>Themes, snippets, grammars and language configuration only.</b> Import a VS Code .vsix or compatible JSON. Monaco cannot run extension commands, debuggers, views or language servers.</p>',
      '    <div class="ext-fila">',
      '      <input type="file" id="extFile" accept=".vsix,.json" class="ext-file">',
      '      <button id="extImportar" class="ext-btn principal" type="button">Import</button>',
      '    </div>',
      '    <div class="ext-fila"><label for="extTemaSelect">Editor theme</label>',
      '      <select id="extTemaSelect" class="ext-select"></select>',
      '      <button id="extAplicarTema" class="ext-btn" type="button">Apply</button></div>',
      '    <p class="ext-estado" id="extEstado" role="status" aria-live="polite"></p>',
      '    <details class="ext-crear"><summary>Create a theme</summary>',
      '      <div class="ext-form">',
      '        <input id="ctName" placeholder="Theme name" maxlength="60">',
      '        <div class="ext-colores">',
      '          <label>Background<input id="ctBg" type="color" value="#0a0a0f"></label>',
      '          <label>Text<input id="ctFg" type="color" value="#e6e6e6"></label>',
      '          <label>Comment<input id="ctComment" type="color" value="#6a737d"></label>',
      '          <label>Keyword<input id="ctKeyword" type="color" value="#e84393"></label>',
      '          <label>String<input id="ctString" type="color" value="#7bd88f"></label>',
      '        </div>',
      '        <button id="ctGuardar" class="ext-btn principal" type="button">Create theme</button>',
      '      </div></details>',
      '    <details class="ext-crear"><summary>Create a snippet</summary>',
      '      <div class="ext-form">',
      '        <input id="csLang" placeholder="Language id (e.g. python, * for all)" maxlength="40">',
      '        <input id="csPrefix" placeholder="Prefix (trigger)" maxlength="60">',
      '        <input id="csDesc" placeholder="Description" maxlength="120">',
      '        <textarea id="csBody" rows="4" placeholder="Body — use ${1:placeholder} tab stops"></textarea>',
      '        <button id="csGuardar" class="ext-btn principal" type="button">Create snippet</button>',
      '      </div></details>',
      '    <h3 class="ext-sub">Imported</h3>',
      '    <div id="extLista" class="ext-lista"></div>',
      '  </div>',
      '</div>'
    ].join('');
    documentObject.body.appendChild(panel);

    $('extCerrar').addEventListener('click', cerrar);
    $('extFondo').addEventListener('click', cerrar);
    $('extImportar').addEventListener('click', importar);
    $('extAplicarTema').addEventListener('click', aplicarTemaSeleccionado);
    $('ctGuardar').addEventListener('click', crearTema);
    $('csGuardar').addEventListener('click', crearSnippet);
    return panel;
  }

  function marcarBoton(abierto) {
    var toggle = $('toggleExtensiones');
    if (!toggle) { return; }
    toggle.classList.toggle('activo', abierto);
    toggle.setAttribute('aria-expanded', abierto ? 'true' : 'false');
  }

  function abrir() {
    construirPanel();
    panel.classList.add('activo');
    marcarBoton(true);
    poblarSelectorTemas();
    cargarLista();
  }
  function cerrar() {
    if (panel) { panel.classList.remove('activo'); }
    marcarBoton(false);
  }

  function importar() {
    var input = $('extFile');
    if (!input || !input.files || !input.files[0]) { estado('Pick a .vsix or JSON file first.', true); return; }
    var file = input.files[0];
    estado('Importing “' + file.name + '”…', false);
    windowObject.fetch('/api/extensions/import?filename=' + encodeURIComponent(file.name), { method: 'POST', body: file })
      .then(function (r) { return r.json().then(function (b) { if (!r.ok) { throw new Error((b.detail && b.detail.message) || ('Error ' + r.status)); } return b; }); })
      .then(function (b) {
        var e = b.extension || {};
        estado('Imported: ' + (e.name || e.id) + '  (' + (e.themes || []).length + ' themes, ' + (e.snippets || []).length + ' snippet sets, ' + (e.grammars || []).length + ' grammars).', false);
        input.value = '';
        aplicarTodo(); cargarLista();
      })
      .catch(function (err) { estado('Could not import: ' + err.message, true); });
  }

  function crearTema() {
    var name = ($('ctName').value || '').trim();
    if (!name) { estado('Theme name is required.', true); return; }
    var theme = {
      type: 'dark',
      colors: { 'editor.background': $('ctBg').value, 'editor.foreground': $('ctFg').value },
      tokenColors: [
        { scope: 'comment', settings: { foreground: $('ctComment').value, fontStyle: 'italic' } },
        { scope: ['keyword', 'storage', 'keyword.control'], settings: { foreground: $('ctKeyword').value } },
        { scope: ['string', 'string.quoted'], settings: { foreground: $('ctString').value } }
      ]
    };
    api('/api/extensions/theme', { method: 'POST', body: JSON.stringify({ id: slug(name), label: name, theme: theme }) })
      .then(function () { estado('Theme created.', false); aplicarTodo(); cargarLista(); })
      .catch(function (err) { estado('Could not create theme: ' + err.message, true); });
  }

  function crearSnippet() {
    var lang = ($('csLang').value || '*').trim() || '*';
    var prefix = ($('csPrefix').value || '').trim();
    var body = $('csBody').value || '';
    if (!prefix || !body) { estado('Prefix and body are required.', true); return; }
    var snippets = {}; snippets[prefix] = { prefix: prefix, body: body, description: ($('csDesc').value || '').trim() };
    api('/api/extensions/snippet', { method: 'POST', body: JSON.stringify({ id: slug(lang + '-' + prefix), language: lang, snippets: snippets }) })
      .then(function () { estado('Snippet created.', false); $('csPrefix').value = ''; $('csBody').value = ''; aplicarTodo(); cargarLista(); })
      .catch(function (err) { estado('Could not create snippet: ' + err.message, true); });
  }

  function cargarLista() {
    var cont = $('extLista'); if (!cont) { return; }
    function mensaje(texto) {
      cont.textContent = '';
      var parrafo = documentObject.createElement('p');
      parrafo.className = 'ext-vacio';
      parrafo.textContent = texto;
      cont.appendChild(parrafo);
    }
    mensaje('Loading…');
    api('/api/extensions').then(function (d) {
      var exts = d.extensions || [];
      if (!exts.length) { mensaje('No extensions imported yet.'); return; }
      cont.textContent = '';
      exts.forEach(function (e) {
        var card = documentObject.createElement('div'); card.className = 'ext-card';
        var head = documentObject.createElement('div'); head.className = 'ext-card-head';
        var nombre = documentObject.createElement('b'); nombre.textContent = e.name || e.id;
        var borrar = documentObject.createElement('button'); borrar.className = 'ext-card-del'; borrar.type = 'button'; borrar.textContent = '×'; borrar.title = (windowObject.GeramI18n ? windowObject.GeramI18n.t('aw.remove') : 'Remove');
        borrar.addEventListener('click', function () { eliminar(e.id); });
        head.appendChild(nombre); head.appendChild(borrar); card.appendChild(head);
        var meta = documentObject.createElement('p'); meta.className = 'ext-card-meta';
        meta.textContent = [
          (e.themes || []).length + ' themes',
          (e.snippets || []).reduce(function (a, s) { return a + (s.count || 0); }, 0) + ' snippets',
          (e.grammars || []).length + ' grammars',
          (e.languages || []).length + ' languages'
        ].join(' · ') + (e.origin ? '  [' + e.origin + ']' : '');
        card.appendChild(meta);
        cont.appendChild(card);
      });
    }).catch(function (err) { mensaje('Could not load: ' + err.message); });
  }

  function eliminar(id) {
    if (!windowObject.confirm(windowObject.GeramI18n ? windowObject.GeramI18n.t('ext.confirmremove') : 'Remove this extension?')) { return; }
    api('/api/extensions/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function () { aplicarTodo(); cargarLista(); })
      .catch(function (err) { estado('Could not remove: ' + err.message, true); });
  }

  // ================= init =================
  function init() {
    var toggle = $('toggleExtensiones');
    if (toggle) {
      toggle.addEventListener('click', function () {
        if (panel && panel.classList.contains('activo')) { cerrar(); } else { abrir(); }
      });
    }
    documentObject.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel && panel.classList.contains('activo')) { cerrar(); }
    });
    aplicarTodo();  // aplica lo ya importado al editor apenas Monaco esté listo
  }

  if (documentObject.readyState === 'loading') {
    documentObject.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})(window, document);
