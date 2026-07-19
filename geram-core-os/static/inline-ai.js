// ============================================================
// GERAM CORE OS · inline-ai.js (v3, Paso 3)
// Barra de comandos inline estilo Cursor/VS Code (Ctrl+I): punto de
// entrada unificado de A.R.E.S. sobre el ARCHIVO ACTIVO del editor.
//
// Flujo: instrucción -> POST /api/ares/proposals (archivo actual +
// selección/cursor; el system prompt del usuario lo inyecta el backend,
// ver Paso 2) -> diff en Monaco (createDiffEditor, original vs propuesta)
// -> Aceptar (approve+apply, escribe disco SOLO aquí) o Rechazar.
// Tras Aceptar: botón para correr el Test Runner (Bubblewrap) sobre el
// archivo. Reusa los mismos endpoints y el controller que ares-workspace.js;
// nada se escribe en disco sin un clic explícito en Aceptar.
// ============================================================
(function (root) {
  'use strict';
  if (!root || !root.document) { return; }
  var documentObject = root.document;
  var $ = function (id) { return documentObject.getElementById(id); };

  var controller = root.GeramWorkspaceController;
  var input = $('inlineAiInput');
  var sendBtn = $('inlineAiSend');
  var runFileBtn = $('inlineAiRunFile');
  var runTestsBtn = $('inlineAiRunTests');
  var statusEl = $('inlineAiStatus');
  var diffPanel = $('inlineAiDiff');
  var diffEditorContainer = $('inlineAiDiffEditor');
  var diffTextEl = $('inlineAiDiffText');
  var summaryEl = $('inlineAiSummary');
  var warningsEl = $('inlineAiWarnings');
  var acceptBtn = $('inlineAiAccept');
  var rejectBtn = $('inlineAiReject');
  var executionEl = $('inlineAiExecution');
  var executionStateEl = $('inlineAiExecutionState');
  var executionMetaEl = $('inlineAiExecutionMeta');
  var stdoutEl = $('inlineAiStdout');
  var stderrEl = $('inlineAiStderr');
  var cancelRunBtn = $('inlineAiCancelRun');
  var fixBtn = $('inlineAiFix');
  if (!controller || !input || !sendBtn || !diffPanel) { return; }

  var proposal = null;        // respuesta de /proposals
  var approval = null;        // respuesta de /approve (token)
  var busy = false;
  var lastAcceptedPath = '';  // para el botón de tests
  var currentRunId = '';
  var lastRunner = '';        // runner de la última ejecución (para el loop de fix)
  // Loop test->fix: cada iteración propone un arreglo desde el fallo capturado;
  // el humano aprueba cada apply. Acotado para no correr indefinidamente.
  var MAX_FIX_ROUNDS = 3;
  var fixLoop = { round: 0, path: '', failure: '' };
  var runPollTimer = null;
  var diffEditor = null, originalModel = null, modifiedModel = null;

  var MESSAGES = {
    context_too_large: 'The file is too large for A.R.E.S.',
    file_too_large: 'The file exceeds the allowed limit.',
    invalid_provider_response: 'A.R.E.S. returned an invalid proposal.',
    provider_response_not_text: 'A.R.E.S. returned an unsupported response format.',
    provider_response_encoding: 'A.R.E.S. returned text with invalid encoding.',
    provider_response_too_large: 'The A.R.E.S. proposal exceeds the allowed limit.',
    provider_response_truncated: 'The A.R.E.S. response was truncated; try a smaller change.',
    provider_response_ambiguous: 'A.R.E.S. added text outside the required JSON.',
    provider_response_invalid_json: 'A.R.E.S. returned invalid JSON.',
    provider_response_schema_invalid: 'The A.R.E.S. response does not meet the editing contract.',
    provider_response_path_invalid: 'A.R.E.S. proposed a disallowed path.',
    provider_response_incomplete: 'A.R.E.S. omitted one of the selected files.',
    provider_unavailable: 'A.R.E.S. is currently unavailable.',
    invalid_path: 'The active file does not have a valid path inside the workspace.',
    protected_path: 'The active file is protected and A.R.E.S. cannot modify it.',
    proposal_too_large: 'The proposal exceeds the allowed limit.',
    proposal_capacity: 'A.R.E.S. has too many pending proposals; discard one and try again.',
    proposal_not_found: 'The proposal no longer exists on the backend. Generate a new one.',
    proposal_rejected: 'The proposal was rejected and can no longer be applied.',
    proposal_cancelled: 'The proposal was cancelled and can no longer be applied.',
    proposal_conflicted: 'The proposal conflicts with the current file. Generate a new one.',
    proposal_failed: 'The proposal failed safely and was not applied.',
    proposal_digest_mismatch: 'The proposal changed after review. Generate a new one.',
    proposal_integrity_failed: 'The integrity check failed; no changes were applied.',
    approval_token_invalid: 'The approval is no longer valid. Generate a new proposal.',
    approval_mismatch: 'The approval does not match the reviewed diff.',
    diff_too_large: 'The diff exceeds the allowed limit.',
    proposal_base_conflict: 'The file changed on disk; reopen it.',
    proposal_expired: 'The proposal expired; request it again.',
    version_conflict: 'The file changed; your local content was preserved.'
  };
  function safeMessage(errorOrCode) {
    var code = typeof errorOrCode === 'string' ? errorOrCode : errorOrCode && errorOrCode.message;
    if (MESSAGES[code]) { return MESSAGES[code]; }
    var requestId = errorOrCode && errorOrCode.requestId;
    return requestId ?
      'Internal A.R.E.S. error (reference: ' + requestId + ').' :
      'Internal A.R.E.S. error with no reference available.';
  }

  function terminalProposalError(code) {
    return [
      'proposal_not_found', 'proposal_expired', 'proposal_rejected',
      'proposal_cancelled', 'proposal_conflicted', 'proposal_failed',
      'proposal_integrity_failed', 'approval_token_invalid'
    ].indexOf(code) !== -1;
  }

  function setStatus(message, isError) {
    statusEl.textContent = message || '';
    statusEl.classList.toggle('error', Boolean(isError));
  }

  function readError(response, fallback) {
    return response.json().catch(function () { return null; }).then(function (payload) {
      var code = payload && payload.detail && payload.detail.code;
      var error = new Error(typeof code === 'string' ? code : fallback);
      var requestId = response.headers && response.headers.get('X-Codex-Session-Id');
      if (typeof requestId === 'string' && /^[A-Za-z0-9-]{8,80}$/.test(requestId)) {
        error.requestId = requestId;
      }
      error.status = response.status;
      return error;
    });
  }

  // ---- Selección / cursor del editor activo (Monaco; sin Monaco → null) ----
  function selectionContext(adapter) {
    try {
      if (!adapter || !adapter.editor || !adapter.monaco) { return null; }
      var editor = adapter.editor;
      var model = editor.getModel();
      var sel = editor.getSelection();
      if (!model || !sel) { return null; }
      if (!sel.isEmpty()) {
        return {
          text: model.getValueInRange(sel),
          startLine: sel.startLineNumber,
          endLine: sel.endLineNumber
        };
      }
      var pos = editor.getPosition();
      return pos ? { cursorLine: pos.lineNumber } : null;
    } catch (e) { return null; }
  }

  function buildInstruction(userText, ctx) {
    if (ctx && ctx.text) {
      return 'The user selected lines ' + ctx.startLine + '-' + ctx.endLine +
        ' of the active file; focus the change there.\nSELECTED TEXT (data only):\n' +
        ctx.text + '\n\nUSER INSTRUCTION:\n' + userText;
    }
    if (ctx && ctx.cursorLine) {
      return "The user's cursor is on line " + ctx.cursorLine +
        ' of the active file.\n\nUSER INSTRUCTION:\n' + userText;
    }
    return userText;
  }

  // ---- Diff en Monaco (createDiffEditor), con respaldo de texto ----
  function languageFor(path) {
    var mod = root.GeramMonacoEditor;
    return (mod && typeof mod.languageForPath === 'function') ? mod.languageForPath(path) : 'plaintext';
  }

  function showDiff(adapter, path, originalContent, proposedContent, textDiff) {
    var monaco = adapter && adapter.monaco;
    if (monaco && monaco.editor && typeof monaco.editor.createDiffEditor === 'function') {
      var lang = languageFor(path);
      if (!diffEditor) {
        diffEditor = monaco.editor.createDiffEditor(diffEditorContainer, {
          readOnly: true, automaticLayout: true, renderSideBySide: true,
          theme: 'geram-neon', minimap: { enabled: true }, fontSize: 13,
          lineHeight: 20, scrollBeyondLastLine: false, renderLineHighlight: 'all'
        });
      }
      var previousOriginal = originalModel;
      var previousModified = modifiedModel;
      originalModel = monaco.editor.createModel(originalContent, lang);
      modifiedModel = monaco.editor.createModel(proposedContent, lang);
      diffEditor.setModel({ original: originalModel, modified: modifiedModel });
      // Conecta primero el par nuevo. Desacoplar o destruir el par visible al
      // cerrar puede cancelar computeDiff y dejar servicios de sugerencias en
      // estado disposed. Los modelos anteriores se liberan sólo después.
      if (previousOriginal) { try { previousOriginal.dispose(); } catch (e) { /* noop */ } }
      if (previousModified) { try { previousModified.dispose(); } catch (e) { /* noop */ } }
      diffEditorContainer.hidden = false;
      diffTextEl.hidden = true;
    } else {
      // Respaldo (Monaco no disponible): diff unificado como texto.
      diffTextEl.textContent = String(textDiff || '');
      diffTextEl.hidden = false;
      diffEditorContainer.hidden = true;
    }
    diffPanel.hidden = false;
  }

  function closeDiff() {
    diffPanel.hidden = true;
    while (warningsEl.firstChild) { warningsEl.removeChild(warningsEl.firstChild); }
    summaryEl.textContent = '';
  }

  function renderWarnings(list) {
    while (warningsEl.firstChild) { warningsEl.removeChild(warningsEl.firstChild); }
    (list || []).forEach(function (item) {
      var li = documentObject.createElement('li');
      li.textContent = item;
      warningsEl.appendChild(li);
    });
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    input.disabled = value;
    acceptBtn.disabled = value;
    rejectBtn.disabled = value;
    if (runFileBtn) { runFileBtn.disabled = value; }
    if (runTestsBtn) { runTestsBtn.disabled = value; }
  }

  function renderExecution(data) {
    if (!executionEl) { return; }
    executionEl.hidden = false;
    var state = data && data.status ? data.status : 'unavailable';
    var pending = state === 'queued' || state === 'running';
    var succeeded = state === 'succeeded';
    executionStateEl.textContent = pending ? '● Running…' : (succeeded ? '✔ Success' : '✖ Error');
    var exitCode = data && data.returncode;
    if (exitCode === undefined) { exitCode = data && data.exit_code; }
    var duration = data && typeof data.duration_seconds === 'number' ? data.duration_seconds.toFixed(2) + ' s' : '—';
    executionMetaEl.textContent = 'runner: ' + ((data && (data.runner || data.purpose)) || '—') +
      ' · exit code: ' + (exitCode === null || exitCode === undefined ? '—' : exitCode) +
      ' · duration: ' + duration + ' · sandbox_backend: ' + ((data && data.sandbox_backend) || '—') +
      ' · cleanup: ' + ((data && data.cleanup_status) || '—');
    stdoutEl.textContent = (data && data.stdout) || '';
    stderrEl.textContent = (data && data.stderr) || (data && data.error) || '';
    cancelRunBtn.hidden = !pending;
  }

  function pollRun() {
    if (!currentRunId) { return; }
    root.fetch('/api/terminal-watcher/runs/' + encodeURIComponent(currentRunId), { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) { throw new Error('test_failed'); }
        return response.json();
      }).then(function (data) {
        renderExecution(data);
        if (data.status === 'queued' || data.status === 'running') {
          runPollTimer = root.setTimeout(pollRun, 250);
          return;
        }
        currentRunId = '';
        setBusy(false);
        var cancelled = data.status === 'cancelled';
        if (data.status === 'succeeded') {
          if (fixLoop.round > 0) {
            var rounds = fixLoop.round;
            fixLoop = { round: 0, path: '', failure: '' };
            if (fixBtn) { fixBtn.hidden = true; }
            setStatus('Tests pass ✓ — fixed in ' + rounds + ' round' + (rounds === 1 ? '' : 's') + '.', false);
          } else {
            setStatus('Safe run completed.', false);
          }
        } else if (cancelled) {
          setStatus('Run cancelled.', false);
        } else {
          setStatus('The safe run ended with an error.', true);
          // Only unittest failures drive the fix loop.
          if (lastRunner === 'python_unittest') { offerFix(data); }
        }
      }).catch(function () {
        currentRunId = '';
        setBusy(false);
        setStatus('The safe run could not be queried.', true);
      });
  }

  // ---- 1) Enviar instrucción -> propuesta + diff ----
  // ¿La instrucción pide crear un proyecto desde cero? (vs. editar el activo)
  function isCreateProjectIntent(text) {
    return /\b(crea|cr[eé]ame|gen[eé]ra(me)?|h[aá]z(me)?|nuevo|create|scaffold|arma(me)?)\b[\s\S]*\b(proyecto|proyect|app|aplicaci[oó]n|api|servidor|server|sitio|web)\b/i.test(text);
  }

  // Creación ASÍNCRONA vía MODAL in-app (window.prompt NO funciona en Electron).
  // El backend estructura las carpetas en segundo plano; al terminar se refresca
  // SOLO el árbol del explorador (no se recarga la app ni se abre nada a la fuerza).
  var pendingProjectInstruction = '';
  function openProjectModal(instruction) {
    pendingProjectInstruction = instruction || '';
    var modal = $('projModal');
    if (!modal) { return; }
    var estado = $('projModalEstado');
    if (estado) { estado.textContent = ''; estado.classList.remove('error'); }
    modal.classList.add('activo');
    modal.setAttribute('aria-hidden', 'false');
    var nombre = $('projNombreInput');
    if (nombre) { nombre.focus(); nombre.select(); }
  }
  function closeProjectModal() {
    var modal = $('projModal');
    if (modal) { modal.classList.remove('activo'); modal.setAttribute('aria-hidden', 'true'); }
  }
  function submitProject() {
    var nombre = $('projNombreInput');
    var tipo = $('projTipoSelect');
    var estado = $('projModalEstado');
    var name = nombre ? nombre.value.trim() : '';
    if (!name) { if (estado) { estado.textContent = 'Enter a folder name.'; estado.classList.add('error'); } return; }
    var payload = { name: name, instruction: pendingProjectInstruction };
    if (tipo && tipo.value) { payload.template = tipo.value; }
    if (estado) { estado.textContent = 'Creating…'; estado.classList.remove('error'); }
    root.fetch('/api/ares/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
    }).then(function (res) {
      if (!res.ok) {
        var det = res.data && res.data.detail ? (res.data.detail.message || res.data.detail.code || ('HTTP ' + res.status)) : ('HTTP ' + res.status);
        throw new Error(det);
      }
      closeProjectModal();
      if (nombre) { nombre.value = ''; }
      setStatus('Project "' + res.data.directory + '" (' + res.data.template + ') created. It will appear in the explorer.', false);
      // Refresco del árbol tras dar tiempo a la escritura de fondo.
      var controller = root.GeramWorkspaceController;
      if (controller && controller.reloadTree) { root.setTimeout(function () { controller.reloadTree(); }, 900); }
    }).catch(function (err) {
      if (estado) { estado.textContent = 'Could not create: ' + err.message; estado.classList.add('error'); }
    });
  }
  function createProject(instruction) { openProjectModal(instruction); }
  function refreshExplorer() {
    var controller = root.GeramWorkspaceController;
    if (controller && controller.reloadTree) { controller.reloadTree(); setStatus('Explorer refreshed.', false); }
  }

  // Shared final rendering for both the streaming and non-streaming paths.
  function renderProposal(adapter, path, info, data) {
    proposal = data;
    approval = null;
    var change = null;
    for (var i = 0; i < (data.changes || []).length; i += 1) {
      if (data.changes[i].path === path) { change = data.changes[i]; break; }
    }
    if (!change && data.changes && data.changes.length) { change = data.changes[0]; }
    if (!change) { throw new Error('invalid_provider_response'); }
    summaryEl.classList.remove('ares-streaming');
    summaryEl.textContent = data.summary || '';
    renderWarnings(data.warnings);
    showDiff(adapter, path, info.content, change.content, data.diff);
    setStatus('Review the diff. Accept (Ctrl+Enter) writes to disk; Reject (Esc) discards it.', false);
  }

  // Live view of A.R.E.S. writing the proposal. Display-only: the streamed text
  // is never applied; the diff replaces it once the validated proposal arrives.
  function showStreaming(text) {
    summaryEl.classList.add('ares-streaming');
    summaryEl.textContent = text.length > 600 ? text.slice(text.length - 600) : text;
  }
  function clearStreaming() {
    summaryEl.classList.remove('ares-streaming');
    summaryEl.textContent = '';
  }

  function postProposal(body, adapter, path, info) {
    return root.fetch('/api/ares/proposals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (response) {
      if (!response.ok) { return readError(response, 'proposal_failed').then(function (err) { throw err; }); }
      return response.json();
    }).then(function (data) { renderProposal(adapter, path, info, data); });
  }

  // ---- Shared SSE plumbing ----
  function parseSseBlock(block) {
    var evName = '', dataText = '';
    var lines = block.split('\n');
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i];
      if (line.indexOf('event:') === 0) { evName = line.slice(6).trim(); }
      else if (line.indexOf('data:') === 0) { dataText += line.slice(5).trim(); }
    }
    var data = null;
    if (dataText) { try { data = JSON.parse(dataText); } catch (e) { data = null; } }
    return { event: evName, data: data };
  }

  // Drives a fetch Response body as SSE. `onBlock(block)` returns null to keep
  // reading, or a terminal outcome: {done:true} | {fallback:true} | {error}.
  function pumpSse(response, onBlock) {
    if (!response.ok || !response.body || !response.body.getReader) {
      return Promise.reject({ __fallback: true });
    }
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    var settled = false;
    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) {
          if (!settled) { return Promise.reject({ __fallback: true }); }
          return null;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        var idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          var block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          var outcome = onBlock(block);
          if (outcome) {
            settled = true;
            try { reader.cancel(); } catch (e) {}
            if (outcome.done) { return null; }
            if (outcome.fallback) { return Promise.reject({ __fallback: true }); }
            throw new Error(outcome.error);
          }
        }
        return pump();
      });
    }
    return pump();
  }

  function shortArg(argStr) {
    if (typeof argStr !== 'string' || !argStr) { return ''; }
    try { var o = JSON.parse(argStr); return o.path || o.query || o.prefix || ''; }
    catch (e) { return ''; }
  }

  function sseUnavailable() {
    return !root.fetch || typeof TextDecoder === 'undefined';
  }

  // Token streaming of the proposal (no tools). Falls back with {__fallback:true}.
  function streamProposal(body, adapter, path, info) {
    if (sseUnavailable()) { return Promise.reject({ __fallback: true }); }
    var streamed = '';
    function onBlock(block) {
      var p = parseSseBlock(block);
      if (!p.event) { return null; }
      if (p.event === 'delta') {
        if (p.data && typeof p.data.text === 'string') { streamed += p.data.text; showStreaming(streamed); }
        return null;
      }
      if (p.event === 'proposal') { renderProposal(adapter, path, info, p.data); return { done: true }; }
      if (p.event === 'streaming_unsupported') { return { fallback: true }; }
      if (p.event === 'error') { return { error: (p.data && p.data.code) || 'provider_unavailable' }; }
      return null;
    }
    return root.fetch('/api/ares/proposals/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (response) { return pumpSse(response, onBlock); },
      function () { return Promise.reject({ __fallback: true }); });
  }

  // Agentic path: A.R.E.S. calls read-only tools before proposing. Each tool
  // call is shown live. Falls back with {__fallback:true} when tools are
  // unsupported by the configured provider.
  function agenticProposal(body, adapter, path, info) {
    if (sseUnavailable()) { return Promise.reject({ __fallback: true }); }
    var log = [];
    function onBlock(block) {
      var p = parseSseBlock(block);
      if (!p.event) { return null; }
      if (p.event === 'tool_call') {
        var arg = shortArg(p.data && p.data.arguments);
        log.push('\u{1F50D} ' + ((p.data && p.data.name) || 'tool') + (arg ? '  ' + arg : ''));
        showStreaming(log.join('\n'));
        return null;
      }
      if (p.event === 'tool_result') { return null; }
      if (p.event === 'proposal') { renderProposal(adapter, path, info, p.data); return { done: true }; }
      if (p.event === 'tools_unsupported') { return { fallback: true }; }
      if (p.event === 'error') { return { error: (p.data && p.data.code) || 'provider_unavailable' }; }
      return null;
    }
    return root.fetch('/api/ares/proposals/agentic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (response) {
      setStatus('A.R.E.S. is inspecting the workspace…', false);
      return pumpSse(response, onBlock);
    }, function () { return Promise.reject({ __fallback: true }); });
  }

  // Shared proposal flow. `rawInstruction` is either the user's typed request
  // or a machine-built fix instruction; both go through the agentic -> stream
  // -> POST chain and land on renderProposal, i.e. the same approve/apply gate.
  function runProposalFlow(rawInstruction, path, info) {
    runFileBtn.hidden = true;
    runTestsBtn.hidden = true;
    setBusy(true);
    setStatus('A.R.E.S. is generating the proposal…', false);

    return controller.editorReady.catch(function () { return null; }).then(function (adapter) {
      var ctx = selectionContext(adapter);
      var instruction = buildInstruction(rawInstruction, ctx);
      var body = { instruction: instruction, files: [{ path: path, base_version: info.version }] };
      // Prefer the agentic tool loop; degrade to token streaming, then to the
      // plain POST, whenever the configured provider does not support a step.
      return agenticProposal(body, adapter, path, info).catch(function (error) {
        if (error && error.__fallback) {
          clearStreaming();
          setStatus('A.R.E.S. is generating the proposal…', false);
          return streamProposal(body, adapter, path, info);
        }
        throw error;
      }).catch(function (error) {
        if (error && error.__fallback) {
          clearStreaming();
          setStatus('A.R.E.S. is generating the proposal…', false);
          return postProposal(body, adapter, path, info);
        }
        throw error;
      });
    }).catch(function (error) {
      proposal = null; approval = null;
      closeDiff();
      clearStreaming();
      setStatus(safeMessage(error), true);
    }).then(function () { setBusy(false); });
  }

  function submit() {
    if (busy) { return; }
    var text = input.value.trim();
    if (!text) { return; }
    if (isCreateProjectIntent(text)) { createProject(text); return; }
    var path = controller.activePath();
    var info = path ? controller.documentInfo(path) : null;
    if (!info) { setStatus('Open a file from the explorer before requesting a change.', true); return; }
    if (info.modified) { setStatus('Save your local changes before requesting a proposal.', true); return; }
    // A fresh typed instruction starts a new task: reset the fix loop.
    fixLoop = { round: 0, path: '', failure: '' };
    if (fixBtn) { fixBtn.hidden = true; }
    runProposalFlow(text, path, info);
  }

  // ---- Loop test -> fix (human approves every apply) ----
  function offerFix(runData) {
    var out = ((runData && runData.stdout) || '') + '\n' + ((runData && runData.stderr) || (runData && runData.error) || '');
    fixLoop.failure = out.slice(-4000);
    fixLoop.path = lastAcceptedPath || controller.activePath() || '';
    if (!fixBtn) { return; }
    fixBtn.hidden = fixLoop.round >= MAX_FIX_ROUNDS || !fixLoop.path;
    fixBtn.textContent = fixLoop.round > 0
      ? ('↻ Fix with A.R.E.S. (round ' + (fixLoop.round + 1) + '/' + MAX_FIX_ROUNDS + ')')
      : '↻ Fix with A.R.E.S.';
  }

  function startFix() {
    if (busy) { return; }
    if (fixLoop.round >= MAX_FIX_ROUNDS) {
      setStatus('Reached the fix limit (' + MAX_FIX_ROUNDS + '); review the failure manually.', true);
      return;
    }
    var path = fixLoop.path || controller.activePath();
    var info = path ? controller.documentInfo(path) : null;
    if (!info) { setStatus('Open the failing file before requesting a fix.', true); return; }
    if (info.modified) { setStatus('Save your local changes before requesting a fix.', true); return; }
    fixLoop.round += 1;
    if (fixBtn) { fixBtn.hidden = true; }
    var instruction = 'The unittest run failed. Fix the code so the tests pass. Do not change the '
      + 'tests unless they are clearly wrong. Use the read-only tools to inspect the failing file and '
      + 'its test if needed. Failure output:\n\n' + fixLoop.failure;
    runProposalFlow(instruction, path, info);
  }

  // ---- 2) Aceptar: approve + apply (única escritura a disco) ----
  function accept() {
    if (!proposal || busy) { return; }
    for (var i = 0; i < (proposal.changes || []).length; i += 1) {
      if (controller.hasLocalChanges(proposal.changes[i].path)) {
        setStatus('There are unsaved local changes; the proposal was not applied.', true);
        return;
      }
    }
    setBusy(true);
    setStatus('Approving and applying…', false);
    root.fetch('/api/ares/proposals/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        proposal_id: proposal.proposal_id,
        proposal_digest: proposal.proposal_digest,
        approval: true,
        approved_by: 'local_user',
        files: proposal.files
      })
    }).then(function (response) {
      if (!response.ok) { return readError(response, 'approval_failed').then(function (err) { throw err; }); }
      return response.json();
    }).then(function (data) {
      approval = data;
      return root.fetch('/api/ares/proposals/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: proposal.proposal_id,
          proposal_digest: proposal.proposal_digest,
          approval_token: approval.approval_token
        })
      });
    }).then(function (response) {
      if (!response.ok) { return readError(response, 'apply_failed').then(function (err) { throw err; }); }
      return response.json();
    }).then(function (data) {
      controller.applyAresChanges(data.files);
      lastAcceptedPath = controller.activePath();
      proposal = null; approval = null;
      closeDiff();
      input.value = '';
      syncRunControls();
      if (fixLoop.round > 0 && /\.py$/i.test(lastAcceptedPath)) {
        // In a fix loop: close it by re-running the tests once busy clears.
        setStatus('Fix applied — re-running tests…', false);
        root.setTimeout(runTests, 300);
      } else {
        setStatus(/\.(?:py|js)$/i.test(lastAcceptedPath) ? 'Changes saved. You can now run the file in Bubblewrap.' : 'Changes saved; the secure runner supports Python and JavaScript files.', false);
      }
    }).catch(function (error) {
      if (terminalProposalError(error.message)) {
        proposal = null; approval = null; closeDiff();
      }
      setStatus(safeMessage(error), true);
    }).then(function () { setBusy(false); });
  }

  // ---- 2b) Rechazar: descarta, sin tocar disco ----
  function reject() {
    if (!proposal || busy) { closeDiff(); return; }
    setBusy(true);
    root.fetch('/api/ares/proposals/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proposal_id: proposal.proposal_id, rejection: true, rejected_by: 'local_user' })
    }).then(function (response) {
      if (!response.ok) { return readError(response, 'reject_failed').then(function (err) { throw err; }); }
      proposal = null; approval = null;
      closeDiff();
      setStatus('Proposal discarded.', false);
    }).catch(function (error) {
      // Aunque el rechazo remoto falle, cerramos el diff local (nada se escribió).
      proposal = null; approval = null; closeDiff();
      setStatus(safeMessage(error), true);
    }).then(function () { setBusy(false); });
  }

  // ---- 4) Runner cerrado (Bubblewrap) sobre el archivo aceptado ----
  function syncRunControls() {
    var path = controller.activePath();
    lastAcceptedPath = path || '';
    runFileBtn.hidden = !/\.(?:py|js)$/i.test(lastAcceptedPath);
    runTestsBtn.hidden = !/\.py$/i.test(lastAcceptedPath);
  }

  function ensureSaved(path) {
    var info = controller.documentInfo(path);
    if (!info || !info.modified) { return Promise.resolve(true); }
    if (!root.confirm('There are unsaved changes. Save them before running?')) {
      setStatus('Run cancelled: the file has unsaved changes.', false);
      return Promise.resolve(false);
    }
    setStatus('Saving before running…', false);
    return controller.save().then(function (result) {
      if (!result || !result.ok) {
        setStatus('Not run: the current version could not be saved.', true);
        return false;
      }
      var current = controller.documentInfo(path);
      if (!current || current.modified) {
        setStatus('Not run: unsaved changes still exist.', true);
        return false;
      }
      return true;
    });
  }

  function runSecure(runner) {
    var activePath = controller.activePath();
    if (busy || !activePath) { return; }
    lastAcceptedPath = activePath;
    lastRunner = runner;
    if (fixBtn) { fixBtn.hidden = true; }
    setBusy(true);
    ensureSaved(activePath).then(function (ready) {
      if (!ready) { setBusy(false); return null; }
      setStatus('Running in the sandbox…', false);
      renderExecution({ status: 'queued', runner: runner, sandbox_backend: 'bubblewrap', cleanup_status: 'pending' });
      return root.fetch('/api/ares/tests/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: 'local', runner: runner, target: activePath, timeout_seconds: 30 })
      });
    }).then(function (response) {
      if (!response) { return null; }
      if (!response.ok) { return readError(response, 'test_failed').then(function (err) { throw err; }); }
      return response.json();
    }).then(function (data) {
      if (!data) { return; }
      renderExecution(data);
      if (!data.run_id || (data.status !== 'queued' && data.status !== 'running')) {
        setBusy(false);
        setStatus('The secure runner rejected the run.', true);
        return;
      }
      currentRunId = data.run_id;
      pollRun();
    }).catch(function (error) {
      renderExecution({ status: 'unavailable', error: safeMessage(error), cleanup_status: 'not_started' });
      setStatus('Secure runner: ' + safeMessage(error), true);
      setBusy(false);
    });
  }

  function runFile() {
    var path = controller.activePath();
    runSecure(/\.js$/i.test(path || '') ? 'node_script' : 'python_file');
  }
  function runTests() { runSecure('python_unittest'); }

  function cancelRun() {
    if (!currentRunId) { return; }
    root.fetch('/api/terminal-watcher/runs/' + encodeURIComponent(currentRunId) + '/cancel', { method: 'POST' })
      .then(function () { if (runPollTimer) { root.clearTimeout(runPollTimer); } pollRun(); })
      .catch(function () { setStatus('The run could not be cancelled.', true); });
  }

  // ---- Wiring: botones + atajos de teclado ----
  sendBtn.addEventListener('click', submit);
  acceptBtn.addEventListener('click', accept);
  rejectBtn.addEventListener('click', reject);
  runFileBtn.addEventListener('click', runFile);
  runTestsBtn.addEventListener('click', runTests);
  cancelRunBtn.addEventListener('click', cancelRun);
  if (fixBtn) { fixBtn.addEventListener('click', startFix); }
  root.addEventListener('geram:workspace-state', syncRunControls);
  syncRunControls();

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });

  // Modal de nuevo proyecto + botones del explorador (nuevo / refrescar).
  var projCrear = $('projCrear'); if (projCrear) { projCrear.addEventListener('click', submitProject); }
  var projCancelar = $('projCancelar'); if (projCancelar) { projCancelar.addEventListener('click', closeProjectModal); }
  var projCerrar = $('projModalCerrar'); if (projCerrar) { projCerrar.addEventListener('click', closeProjectModal); }
  var projFondo = $('projModalFondo'); if (projFondo) { projFondo.addEventListener('click', closeProjectModal); }
  var projNombre = $('projNombreInput'); if (projNombre) { projNombre.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); submitProject(); } else if (e.key === 'Escape') { closeProjectModal(); } }); }
  var btnNuevoProj = $('workspaceNuevoProyecto'); if (btnNuevoProj) { btnNuevoProj.addEventListener('click', function () { openProjectModal(''); }); }
  var btnRefrescar = $('workspaceRefrescar'); if (btnRefrescar) { btnRefrescar.addEventListener('click', refreshExplorer); }
  // Expuesto para el menú/atajos de vscode-chrome.js (New Project).
  root.GeramNewProject = function () { openProjectModal(''); };
  root.GeramRefreshExplorer = refreshExplorer;

  // Ctrl+I (o Cmd+I): enfoca la barra de comandos de IA, estilo Cursor. En
  // fase de CAPTURA para interceptarlo antes de que Monaco (con foco en el
  // editor) lo consuma como comando propio.
  documentObject.addEventListener('keydown', function (event) {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'i') {
      event.preventDefault();
      event.stopPropagation();
      input.focus();
      input.select();
    }
  }, true);

  // Atajos globales cuando el diff está abierto: Ctrl/Cmd+Enter acepta, Esc rechaza.
  documentObject.addEventListener('keydown', function (event) {
    if (diffPanel.hidden) { return; }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); accept(); }
    else if (event.key === 'Escape') { event.preventDefault(); reject(); }
  });
})(typeof window !== 'undefined' ? window : null);
