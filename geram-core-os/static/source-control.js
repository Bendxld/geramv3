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

    var openButton = element('button', 'source-control-open', 'Source Control');
    openButton.type = 'button'; openButton.title = 'Source Control local (Ctrl+Shift+G)';
    var badge = element('span', 'source-control-badge', '0'); badge.hidden = true; openButton.appendChild(badge);
    header.insertBefore(openButton, header.lastElementChild);

    var panel = element('section', 'source-control-panel'); panel.id = 'sourceControlPanel'; panel.hidden = true;
    panel.setAttribute('aria-hidden', 'true'); panel.setAttribute('aria-label', 'Source Control local');
    var panelHead = element('div', 'source-control-head');
    var title = element('h3', '', 'SOURCE CONTROL · LOCAL');
    var branch = element('span', 'source-control-branch', 'No repository');
    var refresh = element('button', '', '↻'); refresh.type = 'button'; refresh.title = 'Refresh Source Control';
    var close = element('button', '', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close Source Control');
    panelHead.appendChild(title); panelHead.appendChild(branch); panelHead.appendChild(refresh); panelHead.appendChild(close);
    var notice = element('p', 'source-control-notice', 'User-initiated local Git operations. A.R.E.S. does not perform these actions.');
    var state = element('p', 'source-control-state', 'Waiting to load.'); state.setAttribute('role', 'status'); state.setAttribute('aria-live', 'polite');
    var list = element('ul', 'source-control-list'); list.setAttribute('aria-label', 'Repository changes');
    var toolbar = element('div', 'source-control-toolbar');
    function action(label, handler) { var button = element('button', '', label); button.type = 'button'; button.addEventListener('click', handler); toolbar.appendChild(button); return button; }
    var stageButton = action('Stage selected', function() { mutateSelection('/stage', false); });
    var unstageButton = action('Unstage selected', function() { mutateSelection('/unstage', true); });
    var commitButton = action('Commit…', commitFlow);
    var branchButton = action('Branches…', branchFlow);
    var newBranchButton = action('New branch…', newBranchFlow);
    panel.appendChild(panelHead); panel.appendChild(notice); panel.appendChild(state); panel.appendChild(list); panel.appendChild(toolbar);

    var diffPanel = element('section', 'source-control-diff'); diffPanel.hidden = true;
    var diffHead = element('div', 'source-control-diff-head');
    var diffTitle = element('strong', '', 'GIT DIFF'); var hunkNav = element('div', 'source-control-hunks');
    var diffClose = element('button', '', '×'); diffClose.type = 'button'; diffClose.setAttribute('aria-label', 'Close Git diff');
    var diffText = element('pre', 'source-control-diff-text');
    diffHead.appendChild(diffTitle); diffHead.appendChild(hunkNav); diffHead.appendChild(diffClose); diffPanel.appendChild(diffHead); diffPanel.appendChild(diffText);
    panel.appendChild(diffPanel); documentObject.body.appendChild(panel);

    var overlay = element('section', 'source-control-overlay'); overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true');
    var dialog = element('div', 'source-control-dialog'); dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true');
    var dialogTitle = element('h3'); var dialogMessage = element('p'); var dialogLabel = element('label', '', 'Value');
    var dialogInput = element('input'); dialogInput.type = 'text'; dialogInput.maxLength = 200; dialogInput.autocomplete = 'off'; dialogLabel.appendChild(dialogInput);
    var dialogSelect = element('select'); var dialogActions = element('div', 'source-control-dialog-actions');
    var dialogConfirm = element('button', '', 'Continue'); dialogConfirm.type = 'button'; var dialogCancel = element('button', '', 'Cancel'); dialogCancel.type = 'button';
    dialogActions.appendChild(dialogConfirm); dialogActions.appendChild(dialogCancel);
    [dialogTitle, dialogMessage, dialogLabel, dialogSelect, dialogActions].forEach(function(node) { dialog.appendChild(node); }); overlay.appendChild(dialog); documentObject.body.appendChild(overlay);
    var resolveDialog = null;
    function ask(options) {
      dialogTitle.textContent = options.title; dialogMessage.textContent = options.message || '';
      dialogLabel.hidden = !options.input; dialogSelect.hidden = !options.choices; dialogInput.value = options.value || '';
      dialogLabel.style.display = options.input ? '' : 'none'; dialogSelect.style.display = options.choices ? '' : 'none';
      dialogLabel.firstChild.nodeValue = (options.label || 'Value');
      while (dialogSelect.firstChild) { dialogSelect.removeChild(dialogSelect.firstChild); }
      (options.choices || []).forEach(function(value) { var item = element('option', '', value); item.value = value; dialogSelect.appendChild(item); });
      dialogConfirm.textContent = options.confirm || 'Continue'; overlay.hidden = false; overlay.setAttribute('aria-hidden', 'false');
      windowObject.setTimeout(function() { (options.input ? dialogInput : options.choices ? dialogSelect : dialogConfirm).focus(); }, 0);
      return new Promise(function(resolve) { resolveDialog = resolve; dialogConfirm.onclick = function() { finishDialog({ value: dialogInput.value, choice: dialogSelect.value }); }; });
    }
    function finishDialog(value) { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); if (resolveDialog) { var resolve = resolveDialog; resolveDialog = null; resolve(value); } }
    dialogCancel.addEventListener('click', function() { finishDialog(null); });

    function messageFor(error) {
      var messages = {
        git_repository_not_found: 'The active file does not belong to a workspace Git repository.',
        unsafe_repository: 'The repository does not meet the security policy.', unsafe_repository_config: 'The Git configuration can execute code and was blocked.',
        unsafe_repository_attributes: 'Executable Git attributes were blocked.', dirty_worktree: 'Switch branches only with a clean worktree.',
        empty_commit: 'There are no staged changes to commit.', git_operation_conflict: 'The Git state changed; review it again.',
        git_timeout: 'The Git operation exceeded the time limit.'
      };
      return messages[error.code] || 'The local Git operation could not be completed.';
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
        state.textContent = payload.restricted ? payload.restricted + ' protected change(s), unavailable.' : '✓ Clean repository';
        state.classList.toggle('error', Boolean(payload.restricted)); return;
      }
      state.textContent = payload.conflicts ? payload.conflicts + ' conflict(s)' : payload.entries.length + ' change(s)'; state.classList.toggle('error', payload.conflicts > 0);
      payload.entries.forEach(function(item) {
        var row = element('li', 'source-control-item');
        var checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.setAttribute('aria-label', 'Select ' + item.path);
        checkbox.addEventListener('change', function() { if (checkbox.checked) { selected.add(item.path); } else { selected.delete(item.path); } });
        var name = element('button', 'source-control-file', item.path); name.type = 'button'; name.title = 'Open diff for ' + item.path;
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
      state.textContent = 'Checking repository…'; state.classList.remove('error');
      return api('/status?project=' + encodeURIComponent(project())).then(renderStatus).catch(function(error) {
        statusData = null; repository = ''; branch.textContent = 'No repository'; updateBadge(); fail(error);
      });
    }
    function scheduleRefresh() { if (refreshTimer) { windowObject.clearTimeout(refreshTimer); } refreshTimer = windowObject.setTimeout(function() { if (!panel.hidden) { refreshStatus(); } }, 180); }
    function selectedItems(staged) {
      if (!statusData) { return []; }
      return statusData.entries.filter(function(item) { return selected.has(item.path) && item.staged === staged; }).map(function(item) { return item.path; });
    }
    function blockDirty(paths) {
      var dirty = dirtyWorkspacePaths(controller.state.documents, repository, paths);
      if (dirty.length) { state.textContent = 'Save or discard Monaco changes before this operation.'; state.classList.add('error'); return true; }
      return false;
    }
    function mutateSelection(endpoint, staged) {
      var paths = selectedItems(staged); if (!paths.length) { state.textContent = 'Select files compatible with this action.'; return; }
      if (endpoint === '/stage' && blockDirty(paths)) { return; }
      post(endpoint, { project: project(), paths: paths }).then(function(result) { diffPanel.hidden = true; renderStatus(result); }).catch(fail);
    }
    function openDiff(item, forceStaged) {
      var staged = forceStaged === true || (item.staged && item.worktree === '.');
      state.textContent = 'Generating local diff…';
      api('/diff?project=' + encodeURIComponent(project()) + '&path=' + encodeURIComponent(item.path) + '&staged=' + String(staged)).then(function(result) {
        diffPanel.hidden = false; diffTitle.textContent = (result.staged ? 'INDEX → HEAD · ' : 'WORKTREE → INDEX · ') + result.path;
        diffText.textContent = result.diff || 'No text differences.';
        while (hunkNav.firstChild) { hunkNav.removeChild(hunkNav.firstChild); }
        parseHunks(result.diff).forEach(function(line) {
          var button = element('button', '', 'L' + line); button.type = 'button'; button.addEventListener('click', function() {
            controller.navigate(joinPath(repository, result.path), line, 1);
          }); hunkNav.appendChild(button);
        });
        state.textContent = 'Local Git diff. No changes were applied.';
      }).catch(fail);
    }
    function commitFlow() {
      ask({ title: 'LOCAL COMMIT', message: 'A message is required. Amend, signing, push, and hooks are not allowed.', input: true, label: 'Message', confirm: 'Preview' }).then(function(answer) {
        if (!answer) { return; }
        return post('/commit/preview', { project: project(), message: answer.value }).then(function(preview) {
          return ask({ title: 'APPROVE COMMIT', message: preview.files.length + ' staged file(s) · “' + preview.message + '”', confirm: 'Create local commit' }).then(function(approval) {
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
        return ask({ title: 'LOCAL BRANCHES', message: 'Select an existing branch. Force is not used.', choices: names, confirm: 'Switch branch' }).then(function(answer) {
          if (answer) { return switchBranch(answer.choice, false); }
        });
      }).catch(fail);
    }
    function newBranchFlow() {
      ask({ title: 'NEW LOCAL BRANCH', message: 'No branches will be deleted and force will not be used.', input: true, label: 'Name', confirm: 'Create and switch' }).then(function(created) {
        if (created) { return switchBranch(created.value, true); }
      }).catch(fail);
    }
    function switchBranch(name, create) {
      if (anyDirty()) { state.textContent = 'Save or discard all Monaco changes before switching branches.'; state.classList.add('error'); return Promise.resolve(); }
      return ask({ title: 'CONFIRM BRANCH SWITCH', message: (create ? 'Create and switch to ' : 'Switch to ') + name, confirm: 'Confirm' }).then(function(approval) {
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
        diffPanel.hidden = false; diffTitle.textContent = 'DISCARD PREVIEW · ' + preview.path; diffText.textContent = preview.diff;
        return ask({ title: 'DISCARD CHANGES', message: preview.path + ' · This action restores only this file and does not use reset or clean.', confirm: 'Discard file' }).then(function(approval) {
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
