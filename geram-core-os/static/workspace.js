/* GERAM CORE OS local workspace UI.
 *
 * WorkspaceApi owns HTTP communication. TemporaryEditorState owns per-file,
 * in-memory state. GeramMonacoEditor owns only editor models and view events.
 * File content is never persisted or logged by this module.
 */
(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = exported;
  }
  if (root) {
    root.GeramWorkspace = exported;
    if (root.document) { exported.initializeWorkspace(root.document, root); }
  }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function TemporaryEditorState(confirmSwitch) {
    this.activePath = '';
    this.documents = new Map();
    this.confirmSwitch = confirmSwitch || function() { return true; };
  }

  TemporaryEditorState.prototype.activeDocument = function() {
    return this.documents.get(this.activePath) || null;
  };

  Object.defineProperties(TemporaryEditorState.prototype, {
    currentContent: {
      get: function() {
        var documentState = this.activeDocument();
        return documentState ? documentState.currentContent : '';
      }
    },
    savedContent: {
      get: function() {
        var documentState = this.activeDocument();
        return documentState ? documentState.savedContent : '';
      }
    },
    version: {
      get: function() {
        var documentState = this.activeDocument();
        return documentState ? documentState.version : '';
      }
    },
    modified: {
      get: function() {
        var documentState = this.activeDocument();
        return Boolean(documentState && documentState.modified);
      }
    },
    saving: {
      get: function() {
        var documentState = this.activeDocument();
        return Boolean(documentState && documentState.saving);
      }
    },
    saveError: {
      get: function() {
        var documentState = this.activeDocument();
        return documentState ? documentState.saveError : '';
      }
    }
  });

  TemporaryEditorState.prototype.canOpen = function(path) {
    if (!this.modified || !this.activePath || this.activePath === path) { return true; }
    return this.confirmSwitch();
  };

  TemporaryEditorState.prototype.load = function(file) {
    var existing = this.documents.get(file.path);
    if (existing) {
      this.activePath = file.path;
      return existing;
    }
    var documentState = {
      path: file.path,
      currentContent: file.content,
      savedContent: file.content,
      version: file.version,
      modified: false,
      saving: false,
      saveError: ''
    };
    this.documents.set(file.path, documentState);
    this.activePath = file.path;
    return documentState;
  };

  TemporaryEditorState.prototype.has = function(path) {
    return this.documents.has(path);
  };

  TemporaryEditorState.prototype.activate = function(path) {
    if (!this.documents.has(path)) { return null; }
    this.activePath = path;
    return this.documents.get(path);
  };

  TemporaryEditorState.prototype.edit = function(content, path) {
    var documentState = this.documents.get(path || this.activePath);
    if (!documentState) { return; }
    documentState.currentContent = content;
    documentState.modified = content !== documentState.savedContent;
    documentState.saveError = '';
  };

  TemporaryEditorState.prototype.beginSave = function() {
    var documentState = this.activeDocument();
    if (!documentState || !documentState.modified || documentState.saving) { return null; }
    documentState.saving = true;
    documentState.saveError = '';
    return {
      path: documentState.path,
      content: documentState.currentContent,
      baseVersion: documentState.version
    };
  };

  TemporaryEditorState.prototype.finishSave = function(snapshot, version) {
    var documentState = snapshot && this.documents.get(snapshot.path);
    if (!documentState) { return; }
    documentState.savedContent = snapshot.content;
    documentState.version = version;
    documentState.modified = documentState.currentContent !== documentState.savedContent;
    documentState.saving = false;
    documentState.saveError = '';
  };

  TemporaryEditorState.prototype.failSave = function(code, snapshot) {
    var documentState = snapshot ? this.documents.get(snapshot.path) : this.activeDocument();
    if (!documentState) { return; }
    documentState.saving = false;
    documentState.saveError = code || 'save_failed';
    documentState.modified = documentState.currentContent !== documentState.savedContent;
  };

  TemporaryEditorState.prototype.hasModifiedDocuments = function() {
    var modified = false;
    this.documents.forEach(function(documentState) {
      if (documentState.modified) { modified = true; }
    });
    return modified;
  };

  TemporaryEditorState.prototype.destroy = function() {
    this.documents.clear();
    this.activePath = '';
  };

  function safeErrorCode(response, fallback) {
    return response.json().then(function(payload) {
      var detail = payload && payload.detail;
      if (detail && typeof detail.code === 'string' && /^[a-z_]+$/.test(detail.code)) {
        return detail.code;
      }
      return fallback;
    }).catch(function() { return fallback; });
  }

  function WorkspaceApi(fetchFunction) {
    this.fetchFunction = fetchFunction;
  }

  WorkspaceApi.prototype.tree = function() {
    return this.fetchFunction('/api/workspace/tree', { cache: 'no-store' })
      .then(function(response) {
        if (!response.ok) {
          return safeErrorCode(response, 'tree_failed').then(function(code) {
            var error = new Error(code); error.code = code; throw error;
          });
        }
        return response.json();
      });
  };

  WorkspaceApi.prototype.read = function(path) {
    return this.fetchFunction('/api/workspace/file?path=' + encodeURIComponent(path), {
      cache: 'no-store'
    }).then(function(response) {
      if (!response.ok) {
        return safeErrorCode(response, 'read_failed').then(function(code) {
          var error = new Error(code); error.code = code; throw error;
        });
      }
      return response.json();
    });
  };

  WorkspaceApi.prototype.save = function(snapshot) {
    return this.fetchFunction('/api/workspace/file', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: snapshot.path,
        content: snapshot.content,
        base_version: snapshot.baseVersion
      })
    }).then(function(response) {
      if (!response.ok) {
        return safeErrorCode(response, 'save_failed').then(function(code) {
          var error = new Error(code); error.code = code; throw error;
        });
      }
      return response.json();
    });
  };

  function createTreeButton(documentObject, entry, onOpen, onSelect) {
    var button = documentObject.createElement('button');
    button.type = 'button';
    button.className = 'workspace-nodo ' +
      (entry.type === 'directory' ? 'directory' : 'file');
    button.style.paddingLeft = String(8 + Math.max(0, Number(entry.depth) - 1) * 14) + 'px';
    button.setAttribute('role', 'treeitem');
    button.setAttribute('data-path', entry.path);
    button.setAttribute('data-type', entry.type);
    button.draggable = true;
    button.textContent = (entry.type === 'directory' ? '▸ ' : '· ') + entry.name;
    if (entry.editable === false) {
      button.disabled = true;
      if (entry.editable === false) {
        button.setAttribute('aria-label', entry.name + ', non-editable file');
      }
    } else {
      button.addEventListener('click', function() {
        if (typeof onSelect === 'function') { onSelect(entry, button); }
        if (entry.type === 'file') { onOpen(entry.path, button); }
      });
    }
    return button;
  }

  function initializeWorkspace(documentObject, windowObject) {
    var panel = documentObject.getElementById('workspacePanel');
    if (!panel || panel.getAttribute('data-workspace-ready') === 'true') { return null; }
    panel.setAttribute('data-workspace-ready', 'true');

    var toggle = documentObject.getElementById('toggleWorkspace');
    var close = documentObject.getElementById('workspaceCerrar');
    var backdrop = documentObject.getElementById('workspaceFondo');
    var treeElement = documentObject.getElementById('workspaceArbol');
    var loadingElement = documentObject.getElementById('workspaceCarga');
    var pathElement = documentObject.getElementById('workspaceRuta');
    var modifiedElement = documentObject.getElementById('workspaceModificado');
    var editorSurface = documentObject.getElementById('workspaceEditorSuperficie');
    var monacoContainer = documentObject.getElementById('workspaceMonaco');
    var editorLoadingElement = documentObject.getElementById('workspaceEditorCarga');
    var textarea = documentObject.getElementById('workspaceTexto');
    var statusElement = documentObject.getElementById('workspaceEstado');
    var saveButton = documentObject.getElementById('workspaceGuardar');
    var api = new WorkspaceApi(windowObject.fetch.bind(windowObject));
    var activeButton = null;
    var loadingTree = false;
    var openRequest = 0;
    var editorAdapter = null;
    var editorModule = windowObject.GeramMonacoEditor;
    var state = new TemporaryEditorState(function() {
      return windowObject.confirm(
        (windowObject.GeramI18n && windowObject.GeramI18n.t)
          ? windowObject.GeramI18n.t('ws.confirmswitch')
          : 'There are unsaved changes. Switch files and keep them pending?'
      );
    });

    // Traducción de los textos generados aquí (los estáticos van por data-i18n
    // en index.html; estos se re-escriben en runtime y revertirían el idioma).
    function T(key, fallback) {
      return (windowObject.GeramI18n && windowObject.GeramI18n.t) ? windowObject.GeramI18n.t(key) : fallback;
    }

    function setStatus(message, isError) {
      statusElement.textContent = message || '';
      statusElement.classList.toggle('error', Boolean(isError));
    }

    function renderState() {
      pathElement.textContent = state.activePath || T('ws.nofile', 'No file open');
      modifiedElement.textContent = state.modified ? T('ws.unsaved', 'UNSAVED CHANGES') : '';
      saveButton.disabled = !state.activePath || !state.modified || state.saving;
      editorSurface.setAttribute('aria-busy', state.saving ? 'true' : 'false');
      if (editorAdapter) {
        editorAdapter.setReadOnly(!state.activePath || state.saving);
      }
      windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-state', {
        detail: { path: state.activePath || '', modified: Boolean(state.modified), saving: Boolean(state.saving) }
      }));
    }

    function activateButton(button) {
      if (activeButton) { activeButton.classList.remove('activo'); }
      activeButton = button;
      if (activeButton) { activeButton.classList.add('activo'); }
    }

    function activateDocument(path, button) {
      var documentState = state.activate(path);
      if (!documentState) { return; }
      activateButton(button);
      editorReady.then(function(adapter) {
        adapter.openDocument(documentState);
        adapter.setReadOnly(documentState.saving);
        adapter.focus();
        adapter.layout();
      });
      renderState();
      setStatus('', false);
    }

    function openFile(path, button) {
      if (state.activePath === path) {
        editorReady.then(function(adapter) { adapter.focus(); });
        return;
      }
      if (!state.canOpen(path)) { return; }
      openRequest += 1;
      if (state.has(path)) {
        activateDocument(path, button);
        return;
      }
      var request = openRequest;
      setStatus('Opening file...', false);
      api.read(path).then(function(file) {
        if (request !== openRequest) { return; }
        var documentState = state.load(file);
        activateButton(button);
        return editorReady.then(function(adapter) {
          adapter.openDocument(documentState);
          renderState();
          setStatus('', false);
          adapter.focus();
          adapter.layout();
        });
      }).catch(function(error) {
        if (request !== openRequest) { return; }
        var messages = {
          binary_file: 'The file is not editable text.',
          file_too_large: 'The file exceeds the editing limit.',
          protected_path: 'The path is protected.',
          symlink_not_allowed: 'Symbolic links are not editable.'
        };
        setStatus(messages[error.code] || 'The file could not be opened.', true);
      });
    }

    function renderTree(payload) {
      while (treeElement.firstChild) { treeElement.removeChild(treeElement.firstChild); }
      var entries = payload && Array.isArray(payload.entries) ? payload.entries : [];
      entries.forEach(function(entry) {
        if (!entry || typeof entry.name !== 'string' || typeof entry.path !== 'string') { return; }
        treeElement.appendChild(createTreeButton(documentObject, entry, openFile, function(selected, button) {
          windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-selection', {
            detail: { path: selected.path, type: selected.type, name: selected.name }
          }));
          activateButton(button);
        }));
      });
      loadingElement.textContent = payload && payload.truncated ?
        'View limited for safety.' : String(entries.length) + ' local entries.';
      windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-tree-rendered', {
        detail: { count: entries.length }
      }));
    }

    function loadTree() {
      if (loadingTree) { return; }
      loadingTree = true;
      loadingElement.textContent = 'Loading workspace...';
      api.tree().then(function(payload) {
        renderTree(payload);
      }).catch(function() {
        loadingElement.textContent = 'The local workspace could not be loaded.';
      }).then(function() {
        loadingTree = false;
      });
    }

    function saveActive() {
      if (editorAdapter && state.activePath) {
        state.edit(editorAdapter.getContent(), state.activePath);
      }
      var snapshot = state.beginSave();
      if (!snapshot) { return Promise.resolve({ ok: true, skipped: true }); }
      renderState();
      setStatus('Saving...', false);
      return api.save(snapshot).then(function(result) {
        state.finishSave(snapshot, result.version);
        if (editorAdapter) { editorAdapter.markSaved(snapshot.path, snapshot.content); }
        renderState();
        var documentState = state.documents.get(snapshot.path);
        setStatus(
          documentState && documentState.modified ?
            'Saved; newer changes remain.' : 'File saved.',
          false
        );
        return { ok: true, path: snapshot.path, version: result.version };
      }).catch(function(error) {
        state.failSave(error.code, snapshot);
        renderState();
        setStatus(
          error.code === 'version_conflict' ?
            'Conflict: the file changed outside the editor. Your content was preserved.' :
            'Could not save. Your content was preserved.',
          true
        );
        return { ok: false, path: snapshot.path, error: error.code || 'save_failed' };
      });
    }

    function remapDocuments(oldPath, newPath, itemType) {
      var prefix = oldPath + '/';
      var mappings = [];
      Array.from(state.documents.keys()).forEach(function(path) {
        if (path !== oldPath && !(itemType === 'directory' && path.indexOf(prefix) === 0)) { return; }
        var next = path === oldPath ? newPath : newPath + path.slice(oldPath.length);
        var documentState = state.documents.get(path);
        state.documents.delete(path); documentState.path = next; state.documents.set(next, documentState);
        mappings.push({ oldPath: path, newPath: next, documentState: documentState });
      });
      if (state.activePath === oldPath || (itemType === 'directory' && state.activePath.indexOf(prefix) === 0)) {
        state.activePath = state.activePath === oldPath ? newPath : newPath + state.activePath.slice(oldPath.length);
      }
      return editorReady.then(function(adapter) {
        if (typeof adapter.remapDocuments === 'function') { adapter.remapDocuments(mappings, state.activePath); }
        renderState(); return mappings;
      });
    }

    function removeDocuments(path, itemType) {
      var prefix = path + '/', removed = [];
      Array.from(state.documents.keys()).forEach(function(openPath) {
        if (openPath === path || (itemType === 'directory' && openPath.indexOf(prefix) === 0)) {
          state.documents.delete(openPath); removed.push(openPath);
        }
      });
      if (removed.indexOf(state.activePath) >= 0) { state.activePath = ''; }
      return editorReady.then(function(adapter) {
        if (typeof adapter.closeDocuments === 'function') { adapter.closeDocuments(removed); }
        renderState(); return removed;
      });
    }

    function reloadDocuments(paths) {
      var requested = paths && paths.length ? new Set(paths) : null;
      var targets = Array.from(state.documents.keys()).filter(function(path) {
        return !requested || requested.has(path);
      });
      var removed = [];
      return targets.reduce(function(chain, path) {
        return chain.then(function() {
          var documentState = state.documents.get(path);
          if (!documentState || documentState.modified) { return; }
          return api.read(path).then(function(file) {
            documentState.currentContent = file.content;
            documentState.savedContent = file.content;
            documentState.version = file.version;
            documentState.modified = false;
            documentState.saving = false;
            documentState.saveError = '';
            if (editorAdapter) {
              editorAdapter.setContent(file.content, { path: path, saved: true });
              editorAdapter.markSaved(path, file.content);
            }
          }).catch(function(error) {
            if (error.code !== 'not_found') { throw error; }
            state.documents.delete(path); removed.push(path);
            if (state.activePath === path) { state.activePath = ''; }
          });
        });
      }, Promise.resolve()).then(function() {
        if (removed.length && editorAdapter && typeof editorAdapter.closeDocuments === 'function') {
          editorAdapter.closeDocuments(removed);
        }
        renderState(); return { reloaded: targets.filter(function(path) { return removed.indexOf(path) < 0; }), removed: removed };
      });
    }

    function openPanel() {
      panel.classList.add('activo');
      panel.setAttribute('aria-hidden', 'false');
      toggle.classList.add('activo');
      loadTree();
      close.focus();
      editorReady.then(function(adapter) {
        windowObject.requestAnimationFrame(function() { adapter.layout(); });
      });
    }

    function closePanel() {
      if (state.hasModifiedDocuments() && !windowObject.confirm('There are unsaved changes. Close the workspace?')) {
        return;
      }
      panel.classList.remove('activo');
      panel.setAttribute('aria-hidden', 'true');
      toggle.classList.remove('activo');
      toggle.focus();
    }

    function documentInfo(path) {
      var documentState = state.documents.get(path);
      if (!documentState) { return null; }
      return {
        path: documentState.path,
        version: documentState.version,
        modified: Boolean(documentState.modified),
        content: documentState.currentContent
      };
    }

    function applyAresChanges(changes) {
      if (!Array.isArray(changes) || !changes.length) {
        throw new Error('invalid_ares_changes');
      }
      changes.forEach(function(change) {
        var documentState = state.documents.get(change.path);
        if (documentState && documentState.modified) {
          throw new Error('local_changes');
        }
      });
      changes.forEach(function(change) {
        var documentState = state.documents.get(change.path);
        if (documentState) {
          documentState.currentContent = change.content;
          documentState.savedContent = change.content;
          documentState.version = change.version;
          documentState.modified = false;
          documentState.saving = false;
          documentState.saveError = '';
        }
        if (editorAdapter) {
          editorAdapter.setContent(change.content, { path: change.path, saved: true });
          editorAdapter.markSaved(change.path, change.content);
        }
      });
      renderState();
    }

    function navigateTo(path, line, column) {
      var documentState = state.activate(path);
      if (!documentState) { return Promise.resolve(false); }
      activateButton(null);
      return editorReady.then(function(adapter) {
        adapter.openDocument(documentState);
        adapter.setReadOnly(documentState.saving);
        var revealed = typeof adapter.revealLocation === 'function' ?
          adapter.revealLocation(path, line, column) : false;
        renderState();
        return revealed;
      }).catch(function() { return false; });
    }

    var editorReady;
    if (!editorModule || typeof editorModule.initializeEditor !== 'function') {
      editorReady = Promise.reject(new Error('editor_adapter_unavailable'));
      setStatus('The local editor could not be initialized.', true);
    } else {
      editorReady = editorModule.initializeEditor({
        windowObject: windowObject,
        container: monacoContainer,
        textarea: textarea,
        loadingElement: editorLoadingElement,
        lightTheme: documentObject.body.classList.contains('modo-dia'),
        onSave: saveActive,
        onChange: function(path, content) {
          state.edit(content, path);
          if (state.activePath === path) { renderState(); }
        },
        onFallback: function() {
          setStatus('Monaco no pudo cargar. Editor de respaldo activo.', true);
        }
      }).then(function(result) {
        editorAdapter = result.adapter;
        renderState();
        return editorAdapter;
      });
    }

    var themeObserver = null;
    if (typeof windowObject.MutationObserver === 'function') {
      themeObserver = new windowObject.MutationObserver(function() {
        editorReady.then(function(adapter) {
          adapter.setTheme(documentObject.body.classList.contains('modo-dia'));
        });
      });
      themeObserver.observe(documentObject.body, { attributes: true, attributeFilter: ['class'] });
    }

    saveButton.addEventListener('click', saveActive);
    toggle.addEventListener('click', function() {
      if (panel.classList.contains('activo')) { closePanel(); } else { openPanel(); }
    });
    close.addEventListener('click', closePanel);
    backdrop.addEventListener('click', closePanel);
    documentObject.addEventListener('keydown', function(event) {
      if (!panel.classList.contains('activo')) { return; }
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 's') {
        event.preventDefault();
        if (!editorSurface.contains(event.target)) { saveActive(); }
      } else if (event.key === 'Escape') {
        closePanel();
      }
    });

    var destroyed = false;
    function destroyWorkspace() {
      if (destroyed) { return; }
      destroyed = true;
      if (themeObserver) { themeObserver.disconnect(); }
      editorReady.then(function(adapter) { adapter.destroy(); });
      state.destroy();
    }
    windowObject.addEventListener('beforeunload', destroyWorkspace, { once: true });

    renderState();
    var controller = {
      api: api,
      state: state,
      editorReady: editorReady,
      save: saveActive,
      open: openFile,
      destroy: destroyWorkspace,
      activePath: function() { return state.activePath; },
      documentInfo: documentInfo,
      hasLocalChanges: function(path) {
        var info = documentInfo(path);
        return Boolean(info && info.modified);
      },
      applyAresChanges: applyAresChanges,
      navigate: navigateTo,
      reloadTree: loadTree,
      refreshState: renderState,
      remapDocuments: remapDocuments,
      removeDocuments: removeDocuments,
      reloadDocuments: reloadDocuments,
      treeElement: treeElement
    };
    windowObject.GeramWorkspaceController = controller;
    return controller;
  }

  return {
    TemporaryEditorState: TemporaryEditorState,
    WorkspaceApi: WorkspaceApi,
    createTreeButton: createTreeButton,
    initializeWorkspace: initializeWorkspace
  };
});
