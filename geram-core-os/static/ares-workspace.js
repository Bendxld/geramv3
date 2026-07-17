/* Reviewable A.R.E.S. workspace proposals. Content stays in memory only. */
(function(root) {
  'use strict';
  if (!root || !root.document) { return; }
  var documentObject = root.document;
  var controller = root.GeramWorkspaceController;
  var instruction = documentObject.getElementById('workspaceAresInstruction');
  var addButton = documentObject.getElementById('workspaceAresAdd');
  var requestButton = documentObject.getElementById('workspaceAresRequest');
  var selectedList = documentObject.getElementById('workspaceAresSelected');
  var proposalPanel = documentObject.getElementById('workspaceAresProposal');
  var summary = documentObject.getElementById('workspaceAresSummary');
  var warnings = documentObject.getElementById('workspaceAresWarnings');
  var diff = documentObject.getElementById('workspaceAresDiff');
  var applyButton = documentObject.getElementById('workspaceAresApply');
  var rejectButton = documentObject.getElementById('workspaceAresReject');
  var status = documentObject.getElementById('workspaceAresStatus');
  if (!controller || !instruction || !addButton || !requestButton) { return; }

  var selected = new Map();
  var proposal = null;
  var approval = null;
  var busy = false;

  function setStatus(message, isError) {
    status.textContent = message || '';
    status.classList.toggle('error', Boolean(isError));
  }

  function safeMessage(code) {
    var messages = {
      context_too_large: 'Reduce the selected files.',
      file_too_large: 'A file exceeds the allowed limit.',
      invalid_provider_response: 'A.R.E.S. returned an invalid proposal.',
      provider_unavailable: 'A.R.E.S. is currently unavailable.',
      approval_already_recorded: 'The proposal has already been approved.',
      approval_already_used: 'The approval has already been used.',
      approval_mismatch: 'The approval does not match the reviewed diff.',
      approval_token_invalid: 'The approval is no longer valid.',
      diff_too_large: 'The diff exceeds the allowed limit.',
      proposal_base_conflict: 'The base version changed; reopen the file.',
      proposal_cancelled: 'The proposal was cancelled.',
      proposal_digest_mismatch: 'El diff revisado ya no coincide.',
      proposal_expired: 'The proposal expired.',
      proposal_integrity_failed: 'The proposal failed its integrity check.',
      proposal_not_approved: 'The proposal requires explicit approval.',
      proposal_not_found: 'The proposal is unknown.',
      proposal_rejected: 'The proposal was rejected.',
      rollback_failed: 'The restore did not finish; manually review the affected files.',
      version_conflict: 'The file changed; local content was preserved.'
    };
    return messages[code] || 'The A.R.E.S. operation could not be completed.';
  }

  function readError(response, fallback) {
    return response.json().then(function(payload) {
      var code = payload && payload.detail && payload.detail.code;
      return new Error(typeof code === 'string' ? code : fallback);
    }).catch(function() { return new Error(fallback); });
  }

  function renderSelected() {
    while (selectedList.firstChild) { selectedList.removeChild(selectedList.firstChild); }
    selected.forEach(function(item, path) {
      var row = documentObject.createElement('li');
      var label = documentObject.createElement('span');
      label.textContent = path;
      var remove = documentObject.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Quitar';
      remove.setAttribute('aria-label', 'Quitar ' + path);
      remove.addEventListener('click', function() { selected.delete(path); renderSelected(); });
      row.appendChild(label);
      row.appendChild(remove);
      selectedList.appendChild(row);
    });
    requestButton.disabled = busy || !instruction.value.trim() || selected.size === 0;
  }

  function addActive() {
    var path = controller.activePath();
    var info = path ? controller.documentInfo(path) : null;
    if (!info) { setStatus('Open a text file before including it.', true); return; }
    if (info.modified) { setStatus('Save or review local changes before requesting a proposal.', true); return; }
    if (selected.size >= 3 && !selected.has(path)) { setStatus('Maximum of 3 files per proposal.', true); return; }
    selected.set(path, { path: path, base_version: info.version });
    renderSelected();
    setStatus('', false);
  }

  function renderProposal(data) {
    proposal = data;
    approval = null;
    summary.textContent = data.summary;
    while (warnings.firstChild) { warnings.removeChild(warnings.firstChild); }
    (data.warnings || []).forEach(function(item) {
      var warning = documentObject.createElement('li');
      warning.textContent = item;
      warnings.appendChild(warning);
    });
    while (diff.firstChild) { diff.removeChild(diff.firstChild); }
    String(data.diff || '').split('\n').forEach(function(text) {
      var row = documentObject.createElement('div');
      row.className = 'workspace-ares-diff-line';
      if (text.startsWith('+') && !text.startsWith('+++')) { row.className += ' added'; }
      if (text.startsWith('-') && !text.startsWith('---')) { row.className += ' removed'; }
      row.textContent = text;
      diff.appendChild(row);
    });
    proposalPanel.hidden = false;
    applyButton.textContent = 'Approve proposal';
    applyButton.disabled = false;
    rejectButton.disabled = false;
  }

  function requestProposal() {
    if (busy || !instruction.value.trim() || selected.size === 0) { return; }
    busy = true;
    approval = null;
    proposalPanel.hidden = true;
    renderSelected();
    setStatus('Generating reviewable proposal…', false);
    fetch('/api/ares/proposals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction: instruction.value.trim(), files: Array.from(selected.values()) })
    }).then(function(response) {
      if (!response.ok) { return readError(response, 'proposal_failed').then(function(error) { throw error; }); }
      return response.json();
    }).then(function(data) {
      renderProposal(data);
      setStatus('Review the diff before applying it.', false);
    }).catch(function(error) {
      proposal = null;
      approval = null;
      setStatus(safeMessage(error.message), true);
    }).then(function() {
      busy = false;
      renderSelected();
    });
  }

  function rejectProposal() {
    if (!proposal || busy) { return; }
    busy = true;
    fetch('/api/ares/proposals/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: proposal.proposal_id, rejection: true, rejected_by: 'local_user' })
    }).then(function(response) {
      if (!response.ok) { return readError(response, 'proposal_failed').then(function(error) { throw error; }); }
      proposalPanel.hidden = true;
      proposal = null;
      approval = null;
      setStatus('Proposal rejected.', false);
    }).catch(function(error) { setStatus(safeMessage(error.message), true); })
      .then(function() { busy = false; });
  }

  function advanceProposal() {
    if (!proposal || busy) { return; }
    for (var index = 0; index < proposal.changes.length; index += 1) {
      if (controller.hasLocalChanges(proposal.changes[index].path)) {
        setStatus('There are local changes; the proposal was not applied.', true);
        return;
      }
    }
    busy = true;
    if (approval) {
      fetch('/api/ares/proposals/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: proposal.proposal_id,
          proposal_digest: proposal.proposal_digest,
          approval_token: approval.approval_token
        })
      }).then(function(response) {
        if (!response.ok) { return readError(response, 'apply_failed').then(function(error) { throw error; }); }
        return response.json();
      }).then(function(data) {
        controller.applyAresChanges(data.files);
        proposalPanel.hidden = true;
        proposal = null;
        approval = null;
        selected.clear();
        renderSelected();
        setStatus('Proposal applied and Monaco synchronized.', false);
      }).catch(function(error) {
        if (error.message === 'version_conflict' || error.message === 'proposal_integrity_failed' || error.message === 'proposal_expired') {
          proposal = null;
          approval = null;
          proposalPanel.hidden = true;
        }
        setStatus(safeMessage(error.message), true);
      }).then(function() { busy = false; renderSelected(); });
      return;
    }
    fetch('/api/ares/proposals/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        proposal_id: proposal.proposal_id,
        proposal_digest: proposal.proposal_digest,
        approval: true,
        approved_by: 'local_user',
        files: proposal.files
      })
    }).then(function(response) {
      if (!response.ok) { return readError(response, 'approval_failed').then(function(error) { throw error; }); }
      return response.json();
    }).then(function(data) {
      approval = data;
      applyButton.textContent = 'Apply proposal';
      setStatus('Proposal approved. Click Apply proposal to write the files.', false);
    }).catch(function(error) {
      if (error.message === 'version_conflict' || error.message === 'proposal_integrity_failed' || error.message === 'proposal_expired') {
        proposal = null;
        approval = null;
        proposalPanel.hidden = true;
      }
      setStatus(safeMessage(error.message), true);
    })
      .then(function() { busy = false; renderSelected(); });
  }

  addButton.addEventListener('click', addActive);
  requestButton.addEventListener('click', requestProposal);
  applyButton.addEventListener('click', advanceProposal);
  rejectButton.addEventListener('click', rejectProposal);
  instruction.addEventListener('input', renderSelected);
  renderSelected();
})(typeof window !== 'undefined' ? window : null);
