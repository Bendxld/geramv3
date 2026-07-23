(function(root, factory) {
  'use strict';
  var exported = factory();
  if (typeof module === 'object' && module.exports) { module.exports = exported; }
  if (root && root.document) { exported.initialize(root, root.document); }
})(typeof window !== 'undefined' ? window : null, function() {
  'use strict';

  function joinPath(root, path) { return root ? root + '/' + path : path; }
  function dirtyWorkspacePaths(documents, repository, paths) {
    var selected = new Set(paths.map(function(path) { return joinPath(repository, path); }));
    return Array.from(documents.values()).filter(function(documentState) {
      return documentState.modified && selected.has(documentState.path);
    }).map(function(documentState) { return documentState.path; });
  }
  function parseHunks(diff) {
    var hunks = [], expression = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/gm, match;
    while ((match = expression.exec(String(diff || '')))) { hunks.push(Number(match[1])); }
    return hunks;
  }

  function initialize(windowObject, documentObject) {
    var controller = windowObject.GeramWorkspaceController;
    if (!controller || documentObject.getElementById('sourceControlPanel')) { return null; }
    var workspaceBox = documentObject.querySelector('#workspacePanel .workspace-caja');
    var header = documentObject.querySelector('#workspacePanel .workspace-header');
    if (!workspaceBox || !header) { return null; }
    var statusData = null, repository = '', selected = new Set(), refreshTimer = null;

    function project() { return controller.activePath() || ''; }
    function api(path, options) {
      return windowObject.fetch('/api/source-control' + path, Object.assign({ credentials: 'same-origin', cache: 'no-store' }, options || {})).then(function(response) {
        if (response.ok) { return response.json(); }
        return response.json().then(function(payload) {
          var detail = payload && payload.detail; var error = new Error(detail && detail.code || 'source_control_failed');
          error.code = error.message; throw error;
        });
      });
    }
    function post(path, payload) {
      return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    }
    function element(tag, className, textValue) {
      var node = documentObject.createElement(tag); if (className) { node.className = className; }
      if (textValue !== undefined) { node.textContent = textValue; } return node;
    }

    function t(key) {
      var i18n = windowObject.GeramI18n;
      return (i18n && i18n.t) ? i18n.t(key) : key;
    }
    // Marca el nodo con data-i18n* para que i18n.apply() lo re-traduzca al
    // cambiar de idioma (la UI de este panel se construye en JS).
    function tag(node, key, attr) {
      node.setAttribute(attr ? ('data-i18n-' + attr) : 'data-i18n', key);
      if (!attr) { node.textContent = t(key); }
      else if (attr === 'title') { node.title = t(key); }
      else { node.setAttribute('aria-label', t(key)); }
      return node;
    }
    var openButton = element('button', 'source-control-open', 'Source Control'); tag(openButton, 'sc.open');
    openButton.type = 'button'; tag(openButton, 'sc.open.title', 'title');
    var badge = element('span', 'source-control-badge', '0'); badge.hidden = true; openButton.appendChild(badge);
    header.insertBefore(openButton, header.lastElementChild);

    var panel = element('section', 'source-control-panel'); panel.id = 'sourceControlPanel'; panel.hidden = true;
    panel.setAttribute('aria-hidden', 'true'); tag(panel, 'sc.panel.aria', 'aria');
    var panelHead = element('div', 'source-control-head');
    var title = element('h3', '', 'SOURCE CONTROL · LOCAL'); tag(title, 'sc.title');
    var branch = element('span', 'source-control-branch', t('sc.norepo'));
    var refresh = element('button', '', '↻'); refresh.type = 'button'; tag(refresh, 'sc.refresh.title', 'title');
    var close = element('button', '', '×'); close.type = 'button'; tag(close, 'sc.close.aria', 'aria');
    panelHead.appendChild(title); panelHead.appendChild(branch); panelHead.appendChild(refresh); panelHead.appendChild(close);
    var notice = element('p', 'source-control-notice', ''); tag(notice, 'sc.notice');
    var state = element('p', 'source-control-state', t('ws.waiting')); state.setAttribute('role', 'status'); state.setAttribute('aria-live', 'polite');
    var list = element('ul', 'source-control-list'); tag(list, 'sc.changes.aria', 'aria');
    var toolbar = element('div', 'source-control-toolbar');
    function action(label, handler) { var button = element('button', '', label); button.type = 'button'; button.addEventListener('click', handler); toolbar.appendChild(button); return button; }
    var stageButton = action(t('sc.stage'), function() { mutateSelection('/stage', false); }); stageButton.setAttribute('data-i18n', 'sc.stage');
    var unstageButton = action(t('sc.unstage'), function() { mutateSelection('/unstage', true); }); unstageButton.setAttribute('data-i18n', 'sc.unstage');
    var commitButton = action(t('sc.commit'), commitFlow); commitButton.setAttribute('data-i18n', 'sc.commit');
    var branchButton = action(t('sc.branches'), branchFlow); branchButton.setAttribute('data-i18n', 'sc.branches');
    var newBranchButton = action(t('sc.newbranch'), newBranchFlow); newBranchButton.setAttribute('data-i18n', 'sc.newbranch');
    panel.appendChild(panelHead); panel.appendChild(notice); panel.appendChild(state); panel.appendChild(list); panel.appendChild(toolbar);

    var diffPanel = element('section', 'source-control-diff'); diffPanel.hidden = true;
    var diffHead = element('div', 'source-control-diff-head');
    var diffTitle = element('strong', '', 'GIT DIFF'); var hunkNav = element('div', 'source-control-hunks');
    var diffClose = element('button', '', '×'); diffClose.type = 'button'; tag(diffClose, 'sc.diffclose.aria', 'aria');
    var diffText = element('pre', 'source-control-diff-text');
    diffHead.appendChild(diffTitle); diffHead.appendChild(hunkNav); diffHead.appendChild(diffClose); diffPanel.appendChild(diffHead); diffPanel.appendChild(diffText);
    panel.appendChild(diffPanel); documentObject.body.appendChild(panel);

    var overlay = element('section', 'source-control-overlay'); overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true');
    var dialog = element('div', 'source-control-dialog'); dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true');
    var dialogTitle = element('h3'); var dialogMessage = element('p'); var dialogLabel = element('label', '', t('sc.value'));
    var dialogInput = element('input'); dialogInput.type = 'text'; dialogInput.maxLength = 200; dialogInput.autocomplete = 'off'; dialogLabel.appendChild(dialogInput);
    var dialogSelect = element('select'); var dialogActions = element('div', 'source-control-dialog-actions');
    var dialogConfirm = element('button', '', t('sc.continue')); dialogConfirm.type = 'button'; var dialogCancel = element('button', '', ''); tag(dialogCancel, 'common.cancel'); dialogCancel.type = 'button';
    dialogActions.appendChild(dialogConfirm); dialogActions.appendChild(dialogCancel);
    [dialogTitle, dialogMessage, dialogLabel, dialogSelect, dialogActions].forEach(function(node) { dialog.appendChild(node); }); overlay.appendChild(dialog); documentObject.body.appendChild(overlay);
    var resolveDialog = null;
    function ask(options) {
      dialogTitle.textContent = options.title; dialogMessage.textContent = options.message || '';
      dialogLabel.hidden = !options.input; dialogSelect.hidden = !options.choices; dialogInput.value = options.value || '';
      dialogLabel.style.display = options.input ? '' : 'none'; dialogSelect.style.display = options.choices ? '' : 'none';
      dialogLabel.firstChild.nodeValue = (options.label || t('sc.value'));
      while (dialogSelect.firstChild) { dialogSelect.removeChild(dialogSelect.firstChild); }
      (options.choices || []).forEach(function(value) { var item = element('option', '', value); item.value = value; dialogSelect.appendChild(item); });
      dialogConfirm.textContent = options.confirm || t('sc.continue'); overlay.hidden = false; overlay.setAttribute('aria-hidden', 'false');
      windowObject.setTimeout(function() { (options.input ? dialogInput : options.choices ? dialogSelect : dialogConfirm).focus(); }, 0);
      return new Promise(function(resolve) { resolveDialog = resolve; dialogConfirm.onclick = function() { finishDialog({ value: dialogInput.value, choice: dialogSelect.value }); }; });
    }
    function finishDialog(value) { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); if (resolveDialog) { var resolve = resolveDialog; resolveDialog = null; resolve(value); } }
    dialogCancel.addEventListener('click', function() { finishDialog(null); });

    function messageFor(error) {
      var messages = {
        git_repository_not_found: t('sc.err.norepo'),
        unsafe_repository: t('sc.err.unsafe'), unsafe_repository_config: t('sc.err.unsafeconfig'),
        unsafe_repository_attributes: t('sc.err.unsafeattr'), dirty_worktree: t('sc.err.dirty'),
        empty_commit: t('sc.err.empty'), git_operation_conflict: t('sc.err.conflict'),
        git_timeout: t('sc.err.timeout')
      };
      return messages[error.code] || t('sc.err.generic');
    }
    function fail(error) { state.textContent = messageFor(error); state.classList.add('error'); }
    function updateBadge() {
      var count = statusData ? statusData.entries.length + (statusData.restricted || 0) : 0; badge.textContent = String(count); badge.hidden = count === 0;
      var activityBadge = documentObject.getElementById('actBadgeScm'); if (activityBadge) { activityBadge.textContent = String(count); activityBadge.hidden = count === 0; }
    }
    function statusKind(item) {
      if (item.kind === 'conflict') { return 'CONFLICT'; }
      if (item.kind === 'untracked') { return 'UNTRACKED'; }
      if (item.kind === 'deleted') { return 'DELETED'; }
      if (item.kind === 'renamed') { return 'RENAMED'; }
      return item.staged ? 'STAGED' : 'MODIFIED';
    }
    function renderStatus(payload) {
      statusData = payload; repository = payload.repository || ''; selected.clear();
      branch.textContent = payload.branch || 'Detached HEAD'; updateBadge();
      if (payload.clean) { diffPanel.hidden = true; }
      while (list.firstChild) { list.removeChild(list.firstChild); }
      if (!payload.entries.length) {
        state.textContent = payload.restricted ? t('sc.protected').replace('{n}', payload.restricted) : t('sc.clean');
        state.classList.toggle('error', Boolean(payload.restricted)); return;
      }
      state.textContent = payload.conflicts ? payload.conflicts + ' conflict(s)' : payload.entries.length + ' change(s)'; state.classList.toggle('error', payload.conflicts > 0);
      payload.entries.forEach(function(item) {
        var row = element('li', 'source-control-item');
        var checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.setAttribute('aria-label', 'Select ' + item.path);
        checkbox.addEventListener('change', function() { if (checkbox.checked) { selected.add(item.path); } else { selected.delete(item.path); } });
        var name = element('button', 'source-control-file', item.path); name.type = 'button'; name.title = t('sc.opendiff').replace('{path}', item.path);
        name.addEventListener('click', function() { openDiff(item); });
        var kind = element('span', 'source-control-kind', statusKind(item));
        var stagedDiff = element('button', 'source-control-staged-diff', 'Diff staged'); stagedDiff.type = 'button'; stagedDiff.hidden = !item.staged;
        stagedDiff.addEventListener('click', function() { openDiff(item, true); });
        var discard = element('button', 'source-control-discard', 'Discard'); discard.type = 'button';
        discard.hidden = item.worktree === '.' || item.worktree === '?' || item.kind === 'conflict';
        discard.addEventListener('click', function() { discardFlow(item); });
        row.appendChild(checkbox); row.appendChild(name); row.appendChild(kind); row.appendChild(stagedDiff); row.appendChild(discard); list.appendChild(row);
      });
    }
    function refreshStatus() {
      state.textContent = t('sc.checking'); state.classList.remove('error');
      return api('/status?project=' + encodeURIComponent(project())).then(renderStatus).catch(function(error) {
        statusData = null; repository = ''; branch.textContent = t('sc.norepo'); updateBadge(); fail(error);
      });
    }
    function scheduleRefresh() { if (refreshTimer) { windowObject.clearTimeout(refreshTimer); } refreshTimer = windowObject.setTimeout(function() { if (!panel.hidden) { refreshStatus(); } }, 180); }
    function selectedItems(staged) {
      if (!statusData) { return []; }
      return statusData.entries.filter(function(item) { return selected.has(item.path) && item.staged === staged; }).map(function(item) { return item.path; });
    }
    function blockDirty(paths) {
      var dirty = dirtyWorkspacePaths(controller.state.documents, repository, paths);
      if (dirty.length) { state.textContent = t('sc.savefirst'); state.classList.add('error'); return true; }
      return false;
    }
    function mutateSelection(endpoint, staged) {
      var paths = selectedItems(staged); if (!paths.length) { state.textContent = t('sc.selectfiles'); return; }
      if (endpoint === '/stage' && blockDirty(paths)) { return; }
      post(endpoint, { project: project(), paths: paths }).then(function(result) { diffPanel.hidden = true; renderStatus(result); }).catch(fail);
    }
    function openDiff(item, forceStaged) {
      var staged = forceStaged === true || (item.staged && item.worktree === '.');
      state.textContent = t('sc.gendiff');
      api('/diff?project=' + encodeURIComponent(project()) + '&path=' + encodeURIComponent(item.path) + '&staged=' + String(staged)).then(function(result) {
        diffPanel.hidden = false; diffTitle.textContent = (result.staged ? 'INDEX → HEAD · ' : 'WORKTREE → INDEX · ') + result.path;
        diffText.textContent = result.diff || 'No text differences.';
        while (hunkNav.firstChild) { hunkNav.removeChild(hunkNav.firstChild); }
        parseHunks(result.diff).forEach(function(line) {
          var button = element('button', '', 'L' + line); button.type = 'button'; button.addEventListener('click', function() {
            controller.navigate(joinPath(repository, result.path), line, 1);
          }); hunkNav.appendChild(button);
        });
        state.textContent = t('sc.nolocal');
      }).catch(fail);
    }
    function commitFlow() {
      ask({ title: t('sc.commit.title'), message: t('sc.commit.msg'), input: true, label: t('sc.message'), confirm: t('ws.preview') }).then(function(answer) {
        if (!answer) { return; }
        return post('/commit/preview', { project: project(), message: answer.value }).then(function(preview) {
          return ask({ title: t('sc.approve.title'), message: t('sc.stagedfiles').replace('{n}', preview.files.length) + '“' + preview.message + '”', confirm: t('sc.createcommit') }).then(function(approval) {
            if (!approval) { return; }
            return post('/commit/apply', { token: preview.token }).then(function(result) {
              state.textContent = '✓ Commit ' + result.hash + ' · ' + result.message; return refreshStatus();
            });
          });
        });
      }).catch(fail);
    }
    function anyDirty() { return Array.from(controller.state.documents.values()).some(function(documentState) { return documentState.modified; }); }
    function branchFlow() {
      api('/branches?project=' + encodeURIComponent(project())).then(function(result) {
        var names = result.branches.map(function(item) { return item.name; });
        return ask({ title: t('sc.branches.title'), message: t('sc.branches.msg'), choices: names, confirm: t('sc.switchbranch') }).then(function(answer) {
          if (answer) { return switchBranch(answer.choice, false); }
        });
      }).catch(fail);
    }
    function newBranchFlow() {
      ask({ title: t('sc.newbranch.title'), message: t('sc.newbranch.msg'), input: true, label: t('dash.f.name'), confirm: t('sc.createswitch') }).then(function(created) {
        if (created) { return switchBranch(created.value, true); }
      }).catch(fail);
    }
    function switchBranch(name, create) {
      if (anyDirty()) { state.textContent = t('sc.savebranches'); state.classList.add('error'); return Promise.resolve(); }
      return ask({ title: t('sc.confirmswitch'), message: (create ? t('sc.createswitchto') : t('sc.switchto')) + name, confirm: t('sc.confirm') }).then(function(approval) {
        if (!approval) { return; }
        return post('/switch', { project: project(), branch: name, create: create }).then(function(result) {
          return controller.reloadDocuments().then(function() {
            controller.reloadTree(); windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-paths-changed', { detail: { git: true } })); renderStatus(result);
          });
        });
      });
    }
    function discardFlow(item) {
      if (blockDirty([item.path])) { return; }
      post('/discard/preview', { project: project(), path: item.path }).then(function(preview) {
        diffPanel.hidden = false; diffTitle.textContent = t('sc.discardpreview') + preview.path; diffText.textContent = preview.diff;
        return ask({ title: t('sc.discard.title'), message: preview.path + t('sc.discard.msg'), confirm: t('sc.discardfile') }).then(function(approval) {
          if (!approval) { return; }
          return post('/discard/apply', { token: preview.token }).then(function(result) {
            return controller.reloadDocuments([joinPath(repository, result.path)]).then(function() {
              controller.reloadTree(); windowObject.dispatchEvent(new windowObject.CustomEvent('geram:workspace-paths-changed', { detail: { git: true } })); renderStatus(result.status);
            });
          });
        });
      }).catch(fail);
    }

    var activityButton = documentObject.querySelector('[data-act="scm"]');
    function setPanelOpen(open) {
      panel.hidden = !open;
      panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      if (activityButton) {
        activityButton.classList.toggle('activo', open);
        activityButton.setAttribute('aria-expanded', open ? 'true' : 'false');
      }
      if (open) { refreshStatus(); }
    }
    openButton.addEventListener('click', function() { setPanelOpen(true); });
    if (activityButton) {
      openButton.hidden = true;
      activityButton.addEventListener('click', function(event) {
        event.preventDefault(); event.stopImmediatePropagation();
        setPanelOpen(true);
      }, true);
    }
    close.addEventListener('click', function() { setPanelOpen(false); (activityButton || openButton).focus(); });
    refresh.addEventListener('click', refreshStatus); diffClose.addEventListener('click', function() { diffPanel.hidden = true; });
    windowObject.addEventListener('geram:workspace-paths-changed', scheduleRefresh);
    windowObject.addEventListener('geram:model-save', scheduleRefresh);
    windowObject.addEventListener('geram:workspace-state', scheduleRefresh);
    documentObject.addEventListener('keydown', function(event) {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && String(event.key).toLowerCase() === 'g') {
        event.preventDefault(); setPanelOpen(true);
      }
    }, true);
    refreshStatus();
    var apiObject = { refresh: refreshStatus, open: function() { setPanelOpen(true); }, openDiff: openDiff, close: function() { setPanelOpen(false); } };
    windowObject.GeramSourceControl = apiObject; return apiObject;
  }

  return { initialize: initialize, joinPath: joinPath, dirtyWorkspacePaths: dirtyWorkspacePaths, parseHunks: parseHunks };
});
