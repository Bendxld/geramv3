(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root, root.document); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function parentPath(path) {
    var parts = String(path || '').split('/'); parts.pop(); return parts.join('/');
  }
  function basename(path) { return String(path || '').split('/').pop() || ''; }
  function duplicateName(path) {
    var name = basename(path), dot = name.lastIndexOf('.');
    return dot > 0 ? name.slice(0, dot) + ' copy' + name.slice(dot) : name + ' copy';
  }
  function remapPath(path, oldPath, newPath, type) {
    if (path === oldPath) { return newPath; }
    return type === 'directory' && path.indexOf(oldPath + '/') === 0 ? newPath + path.slice(oldPath.length) : path;
  }
  function dirtyPathsFor(documents, path, type) {
    var prefix = path + '/';
    return Array.from(documents.values()).filter(function(documentState) {
      return documentState.modified && (documentState.path === path || (type === 'directory' && documentState.path.indexOf(prefix) === 0));
    }).map(function(documentState) { return documentState.path; });
  }

  function initialize(windowObject, documentObject) {
    var controller = windowObject.GeramWorkspaceController;
    if (!controller || !controller.treeElement || documentObject.getElementById('workspaceOpsToolbar')) { return null; }
    var selection = null, dragged = null, dialogResolve = null;
    var tree = controller.treeElement;

    function request(url, payload) {
      return windowObject.fetch(url, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      }).then(function(response) {
        if (response.ok) { return response.json(); }
        return response.json().then(function(value) {
          var detail = value && value.detail; var error = new Error(detail && detail.code || 'operation_failed'); error.code = error.message; throw error;
        });
      });
    }

    var toolbar = documentObject.createElement('div'); toolbar.id = 'workspaceOpsToolbar'; toolbar.className = 'workspace-ops-toolbar';
    function toolbarButton(label, title, action) {
      var button = documentObject.createElement('button'); button.type = 'button'; button.textContent = label; button.title = title; button.addEventListener('click', action); toolbar.appendChild(button);
    }
    toolbarButton('+ File', 'Create file', function() { createItem('file'); });
    toolbarButton('+ Folder', 'Create folder', function() { createItem('directory'); });
    toolbarButton('↻', 'Refrescar explorador', function() { controller.reloadTree(); });
    tree.parentNode.insertBefore(toolbar, tree);

    var overlay = documentObject.createElement('section'); overlay.className = 'workspace-ops-overlay'; overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true');
    var box = documentObject.createElement('div'); box.className = 'workspace-ops-dialog'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    var heading = documentObject.createElement('h2'); var message = documentObject.createElement('p');
    var label = documentObject.createElement('label'); label.textContent = 'Nombre';
    var input = documentObject.createElement('input'); input.type = 'text'; input.maxLength = 120; input.autocomplete = 'off'; input.spellcheck = false; label.appendChild(input);
    var destinationLabel = documentObject.createElement('label'); destinationLabel.textContent = 'Mover a';
    var destination = documentObject.createElement('select'); destinationLabel.appendChild(destination);
    var status = documentObject.createElement('p'); status.className = 'workspace-ops-status'; status.setAttribute('role', 'status');
    var actions = documentObject.createElement('div'); actions.className = 'workspace-ops-actions';
    var confirmButton = documentObject.createElement('button'); confirmButton.type = 'button'; confirmButton.textContent = 'Continue';
    var cancelButton = documentObject.createElement('button'); cancelButton.type = 'button'; cancelButton.textContent = 'Cancel';
    actions.appendChild(confirmButton); actions.appendChild(cancelButton);
    [heading, message, label, destinationLabel, status, actions].forEach(function(item) { box.appendChild(item); }); overlay.appendChild(box); documentObject.body.appendChild(overlay);

    function closeDialog(value) {
      overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); status.textContent = '';
      if (dialogResolve) { var resolve = dialogResolve; dialogResolve = null; resolve(value); }
    }
    cancelButton.addEventListener('click', function() { closeDialog(null); });
    overlay.addEventListener('keydown', function(event) { if (event.key === 'Escape') { event.preventDefault(); closeDialog(null); } });
    function promptForm(options) {
      heading.textContent = options.title; message.textContent = options.message || '';
      label.hidden = !options.name; destinationLabel.hidden = !options.destinations;
      label.style.display = label.hidden ? 'none' : ''; destinationLabel.style.display = destinationLabel.hidden ? 'none' : '';
      input.value = options.value || ''; confirmButton.textContent = options.confirm || 'Continue';
      while (destination.firstChild) { destination.removeChild(destination.firstChild); }
      (options.destinations || []).forEach(function(path) { var item = documentObject.createElement('option'); item.value = path; item.textContent = path || '/'; destination.appendChild(item); });
      overlay.hidden = false; overlay.setAttribute('aria-hidden', 'false');
      windowObject.setTimeout(function() { (options.name ? input : confirmButton).focus(); if (options.name) { input.select(); } }, 0);
      return new Promise(function(resolve) {
        dialogResolve = resolve;
        confirmButton.onclick = function() { closeDialog({ name: input.value, destination: destination.value }); };
      });
    }

    var menu = documentObject.createElement('div'); menu.className = 'workspace-ops-menu'; menu.hidden = true; menu.setAttribute('role', 'menu'); documentObject.body.appendChild(menu);
    function menuAction(labelText, action, disabled) {
      var button = documentObject.createElement('button'); button.type = 'button'; button.textContent = labelText; button.disabled = Boolean(disabled); button.addEventListener('click', function() { menu.hidden = true; action(); }); menu.appendChild(button);
    }
    function showMenu(event, item) {
      selection = item; while (menu.firstChild) { menu.removeChild(menu.firstChild); }
      menuAction('New file', function() { createItem('file'); }, false);
      menuAction('New folder', function() { createItem('directory'); }, false);
      menuAction('Rename', startInlineRename, !item);
      menuAction('Mover a…', moveSelected, !item);
      menuAction('Duplicar', duplicateSelected, !item || item.type !== 'file');
      menuAction('Delete', deleteSelected, !item);
      menuAction('Copy relative path', copyPath, !item);
      menu.hidden = false; menu.style.left = event.clientX + 'px'; menu.style.top = event.clientY + 'px';
      var first = menu.querySelector('button:not(:disabled)'); if (first) { first.focus(); }
    }

    function selectedParent() {
      if (!selection) { return ''; }
      return selection.type === 'directory' ? selection.path : parentPath(selection.path);
    }
    function dirtyPaths(path, type) {
      return dirtyPathsFor(controller.state.documents, path, type);
    }
    function ensureClean(path, type) {
      var dirty = dirtyPaths(path, type); if (!dirty.length) { return Promise.resolve(true); }
      if (!windowObject.confirm('There are unsaved changes in ' + dirty.length + ' file(s). Save them before continuing?')) { return Promise.resolve(false); }
      var original = controller.activePath();
      return dirty.reduce(function(chain, dirtyPath) {
        return chain.then(function(ok) {
          if (!ok) { return false; }
          controller.state.activate(dirtyPath);
          return controller.navigate(dirtyPath, 1, 1).then(function() { return controller.save(); }).then(function(result) { return Boolean(result && result.ok); });
        });
      }, Promise.resolve(true)).then(function(ok) {
        if (ok && original && controller.state.has(original)) { return controller.navigate(original, 1, 1).then(function() { return true; }); }
        return ok;
      });
    }
    function notifyChanged(detail) {
      windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-paths-changed', { detail: detail }));
      controller.reloadTree();
    }
    function errorMessage(error) {
      var messages = {
        invalid_name: 'The name is invalid.', name_collision: 'An item with that name already exists.',
        circular_move: 'A folder cannot be moved inside itself.', protected_path: 'The path is protected.',
        operation_conflict: 'The item changed; try again.', symlink_not_allowed: 'Symbolic links are not allowed.'
      };
      windowObject.alert(messages[error.code] || 'The operation could not be completed.');
    }

    function createItem(type) {
      var parent = selectedParent();
      promptForm({ title: type === 'file' ? 'CREATE FILE' : 'CREATE FOLDER', message: 'Location: ' + (parent || '/'), name: true, confirm: 'Create' }).then(function(value) {
        if (!value) { return; }
        return request('/api/workspace/operations/create', { parent: parent, name: value.name, type: type }).then(function(result) {
          notifyChanged({ created: [result] });
          if (type === 'file') { return controller.api.read(result.path).then(function(file) { controller.state.load(file); return controller.navigate(result.path, 1, 1); }); }
        });
      }).catch(errorMessage);
    }

    function renameTo(name) {
      if (!selection) { return; }
      ensureClean(selection.path, selection.type).then(function(ok) {
        if (!ok) { return; }
        return request('/api/workspace/operations/move/preview', { source: selection.path, destination_parent: parentPath(selection.path), name: name }).then(function(preview) {
          return promptForm({ title: 'CONFIRM RENAME', message: preview.source + ' → ' + preview.destination, confirm: 'Rename' }).then(function(answer) {
            if (!answer) { return; }
            return request('/api/workspace/operations/move/apply', { token: preview.token }).then(function(result) {
              return controller.remapDocuments(result.old_path, result.new_path, result.type).then(function() {
                selection = { path: result.new_path, type: result.type, name: basename(result.new_path) };
                notifyChanged({ mappings: [{ oldPath: result.old_path, newPath: result.new_path, type: result.type }] });
              });
            });
          });
        });
      }).catch(errorMessage);
    }
    function startInlineRename() {
      if (!selection) { return; }
      var button = Array.from(tree.querySelectorAll('[data-path]')).find(function(candidate) {
        return candidate.dataset.path === selection.path;
      });
      if (!button) { return; }
      var edit = documentObject.createElement('input'); edit.className = 'workspace-inline-name'; edit.value = basename(selection.path); edit.maxLength = 120;
      button.replaceWith(edit); edit.focus(); edit.select();
      edit.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') { event.preventDefault(); renameTo(edit.value); }
        else if (event.key === 'Escape') { event.preventDefault(); controller.reloadTree(); }
      });
      edit.addEventListener('blur', function() { if (edit.isConnected) { controller.reloadTree(); } });
    }

    function listDirectories() {
      return controller.api.tree().then(function(payload) {
        return [''].concat((payload.entries || []).filter(function(entry) { return entry.type === 'directory'; }).map(function(entry) { return entry.path; }));
      });
    }
    function moveItem(item, destinationParent) {
      return ensureClean(item.path, item.type).then(function(ok) {
        if (!ok) { return; }
        return request('/api/workspace/operations/move/preview', { source: item.path, destination_parent: destinationParent }).then(function(preview) {
          return promptForm({ title: 'CONFIRMAR MOVIMIENTO', message: preview.source + ' → ' + preview.destination + ' (' + preview.count + ' elemento(s))', confirm: 'Mover' }).then(function(answer) {
            if (!answer) { return; }
            return request('/api/workspace/operations/move/apply', { token: preview.token }).then(function(result) {
              return controller.remapDocuments(result.old_path, result.new_path, result.type).then(function() {
                selection = { path: result.new_path, type: result.type, name: basename(result.new_path) };
                notifyChanged({ mappings: [{ oldPath: result.old_path, newPath: result.new_path, type: result.type }] });
              });
            });
          });
        });
      });
    }
    function moveSelected() {
      if (!selection) { return; }
      listDirectories().then(function(directories) {
        return promptForm({ title: 'MOVE TO…', message: 'Source: ' + selection.path, destinations: directories, confirm: 'Preview' });
      }).then(function(value) { if (value) { return moveItem(selection, value.destination); } }).catch(errorMessage);
    }
    function duplicateSelected() {
      if (!selection || selection.type !== 'file') { return; }
      promptForm({ title: 'DUPLICATE FILE', message: 'Source: ' + selection.path, name: true, value: duplicateName(selection.path), confirm: 'Duplicate' }).then(function(value) {
        if (!value) { return; }
        return request('/api/workspace/operations/duplicate', { source: selection.path, name: value.name }).then(function(result) {
          notifyChanged({ created: [result] });
        });
      }).catch(errorMessage);
    }
    function deleteSelected() {
      if (!selection) { return; }
      var target = selection;
      ensureClean(target.path, target.type).then(function(ok) {
        if (!ok) { return; }
        return request('/api/workspace/operations/delete/preview', { path: target.path }).then(function(preview) {
          return promptForm({ title: 'CONFIRM DELETION', message: preview.path + ' · ' + preview.count + ' item(s). This action requires explicit approval.', confirm: 'Delete' }).then(function(answer) {
            if (!answer) { return; }
            return request('/api/workspace/operations/delete/apply', { token: preview.token }).then(function(result) {
              return controller.removeDocuments(result.path, result.type).then(function() {
                selection = null; notifyChanged({ removed: [{ path: result.path, type: result.type }] });
              });
            });
          });
        });
      }).catch(errorMessage);
    }
    function copyPath() {
      if (!selection || !windowObject.navigator.clipboard) { return; }
      windowObject.navigator.clipboard.writeText(selection.path).catch(function() { windowObject.alert('The path could not be copied.'); });
    }

    windowObject.addEventListener('geram:workspace-selection', function(event) { selection = event.detail; });
    windowObject.addEventListener('geram:workspace-tree-rendered', function() {
      if (!selection) { return; }
      Array.from(tree.querySelectorAll('[data-path]')).forEach(function(button) {
        button.classList.toggle('activo', button.dataset.path === selection.path);
      });
    });
    tree.addEventListener('contextmenu', function(event) {
      var button = event.target.closest && event.target.closest('[data-path]'); if (!button) { return; }
      event.preventDefault(); showMenu(event, { path: button.dataset.path, type: button.dataset.type, name: basename(button.dataset.path) });
    });
    tree.addEventListener('dragstart', function(event) {
      var button = event.target.closest && event.target.closest('[data-path]'); if (!button) { return; }
      dragged = { path: button.dataset.path, type: button.dataset.type };
      event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', dragged.path);
    });
    tree.addEventListener('dragover', function(event) {
      var button = event.target.closest && event.target.closest('[data-type="directory"]'); if (button && dragged) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; }
    });
    tree.addEventListener('drop', function(event) {
      var button = event.target.closest && event.target.closest('[data-type="directory"]'); if (!button || !dragged) { return; }
      event.preventDefault(); var item = dragged; dragged = null; moveItem(item, button.dataset.path).catch(errorMessage);
    });
    documentObject.addEventListener('click', function(event) { if (!menu.contains(event.target)) { menu.hidden = true; } });
    documentObject.addEventListener('keydown', function(event) {
      if (event.key === 'F2' && selection) { event.preventDefault(); startInlineRename(); }
      else if (event.key === 'Delete' && selection && !event.ctrlKey && !event.metaKey) { event.preventDefault(); deleteSelected(); }
    }, true);

    var api = { createItem: createItem, renameTo: renameTo, moveItem: moveItem, deleteSelected: deleteSelected, duplicateSelected: duplicateSelected };
    windowObject.GeramWorkspaceFileOperations = api; return api;
  }

  return { initialize: initialize, parentPath: parentPath, basename: basename, duplicateName: duplicateName, remapPath: remapPath, dirtyPathsFor: dirtyPathsFor };
});
