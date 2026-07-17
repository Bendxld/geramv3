// ============================================================
// GERAM CORE OS · skills-panel.js
// Pestañas Agentes / Skills dentro del dashboard.
//   · Agentes: "Incluidos" (roster de /info, lo pinta renderDashboardAgentes)
//     + "Mis agentes": definiciones portables del Agent Factory de GCS
//     (/api/gcs/agents). Crear / editar / borrar los propios.
//   · Skills: catálogo de GCS (/api/gcs/skills). Crear / editar / borrar los
//     propios. Los de sistema son de solo lectura.
// Agentes y skills se guardan como JSON en el data dir del usuario (fuera del
// repo), así que cada persona que descargue GERAM edita los suyos localmente.
// ============================================================
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  var overlay = $('dashboardAgentes');
  if (!overlay) { return; }

  function api(url, opts) {
    return fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts))
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
    var base = (s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
    return base.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
  }

  // Enlaza el input Nombre con el de ID: mientras no toquen el ID a mano,
  // se autogenera desde el nombre. En modo edición el ID queda bloqueado.
  function autoId(nombreEl, idEl) {
    var tocado = { v: false };
    idEl.addEventListener('input', function () { tocado.v = true; });
    nombreEl.addEventListener('input', function () {
      if (!tocado.v && !idEl.readOnly) { idEl.value = slug(nombreEl.value); }
    });
    return tocado;
  }

  // ----------------------------------------------------------- pestañas
  var tabAgentes = $('tabAgentes'), tabSkills = $('tabSkills');
  var paneAgentes = $('paneAgentes'), paneSkills = $('paneSkills');
  var skillsCargados = false;

  function activarTab(cual) {
    var esSkills = cual === 'skills';
    if (tabAgentes) { tabAgentes.classList.toggle('activo', !esSkills); }
    if (tabSkills) { tabSkills.classList.toggle('activo', esSkills); }
    if (paneAgentes) { paneAgentes.hidden = esSkills; }
    if (paneSkills) { paneSkills.hidden = !esSkills; }
    if (esSkills && !skillsCargados) { cargarSkills(); }
  }
  if (tabAgentes) { tabAgentes.addEventListener('click', function () { activarTab('agentes'); }); }
  if (tabSkills) { tabSkills.addEventListener('click', function () { activarTab('skills'); }); }

  // Crea una tarjeta (agente o skill) con badges y, si es propia, botones
  // de editar y borrar.
  function tarjeta(item, badges, esPropio, onEditar, onBorrar) {
    var card = document.createElement('div');
    card.className = 'skill-card';
    var top = document.createElement('div');
    top.className = 'skill-card-top';

    var nombre = document.createElement('b');
    nombre.className = 'skill-nombre';
    nombre.textContent = item.name || item.id;
    top.appendChild(nombre);

    badges.forEach(function (b) {
      var span = document.createElement('span');
      span.className = 'skill-badge ' + b.cls;
      span.textContent = b.txt;
      top.appendChild(span);
    });

    if (esPropio) {
      var acciones = document.createElement('span');
      acciones.className = 'skill-acciones';
      var edit = document.createElement('button');
      edit.className = 'skill-editar'; edit.type = 'button';
      edit.title = 'Editar'; edit.setAttribute('aria-label', 'Editar'); edit.textContent = '✎';
      edit.addEventListener('click', onEditar);
      var del = document.createElement('button');
      del.className = 'skill-borrar'; del.type = 'button';
      del.title = 'Borrar'; del.setAttribute('aria-label', 'Borrar'); del.textContent = '×';
      del.addEventListener('click', onBorrar);
      acciones.appendChild(edit); acciones.appendChild(del);
      top.appendChild(acciones);
    }
    card.appendChild(top);

    var desc = document.createElement('p');
    desc.className = 'skill-desc';
    desc.textContent = item.description || 'No description.';
    card.appendChild(desc);
    return card;
  }

  // ==================================================================
  // SKILLS  (/api/gcs/skills)
  // ==================================================================
  var skLista = $('skillsLista'), skConteo = $('skillsConteo');
  var skNuevoBtn = $('skillsNuevoBtn'), skForm = $('skillsForm'), skEstado = $('skillsFormEstado');
  var skNombre = $('skillNombre'), skId = $('skillId'), skPerfil = $('skillPerfil');
  var skDesc = $('skillDesc'), skBody = $('skillBody'), skGuardar = $('skillsGuardar');
  var skEditando = null;
  if (skNombre && skId) { autoId(skNombre, skId); }

  function cargarSkills() {
    if (!skLista) { return; }
    skLista.innerHTML = '<p class="skills-cargando">Loading skills…</p>';
    api('/api/gcs/skills', { method: 'GET' }).then(function (d) {
      skillsCargados = true;
      var skills = (d && d.skills) || [];
      if (skConteo) { skConteo.textContent = String(skills.length); }
      renderSkills(skills);
    }).catch(function (err) {
      skLista.innerHTML = '<p class="skills-error">Could not load: ' + err.message + '</p>';
    });
  }

  function renderSkills(skills) {
    if (!skills.length) { skLista.innerHTML = '<p class="skills-vacio">There are no skills yet. Create your own.</p>'; return; }
    skLista.innerHTML = '';
    skills.forEach(function (s) {
      var esCustom = (s.origin || 'custom') === 'custom';
      var badges = [
        { cls: 'skill-badge-' + (esCustom ? 'custom' : 'system'), txt: esCustom ? 'yours' : 'system' },
        { cls: 'skill-badge-perfil', txt: (s.profile || 'any').toUpperCase() }
      ];
      skLista.appendChild(tarjeta(s, badges, esCustom,
        function () { editarSkill(s.id); },
        function () { borrarSkill(s.id, s.name || s.id); }));
    });
  }

  function abrirSkillForm() { if (skForm) { skForm.hidden = false; } if (skNuevoBtn) { skNuevoBtn.hidden = true; } if (skEstado) { skEstado.textContent = ''; } }
  function cerrarSkillForm() {
    if (skForm) { skForm.hidden = true; skForm.reset(); }
    if (skId) { skId.readOnly = false; }
    if (skGuardar) { skGuardar.textContent = 'Save skill'; }
    if (skNuevoBtn) { skNuevoBtn.hidden = false; }
    skEditando = null;
  }

  function editarSkill(id) {
    api('/api/gcs/skills/' + encodeURIComponent(id), { method: 'GET' }).then(function (s) {
      skEditando = s;
      skNombre.value = s.name || '';
      skId.value = s.id; skId.readOnly = true;
      if (skPerfil) { skPerfil.value = s.profile || 'any'; }
      skDesc.value = s.description || '';
      skBody.value = s.body || '';
      if (skGuardar) { skGuardar.textContent = 'Save changes'; }
      abrirSkillForm();
    }).catch(function (err) { window.alert('Could not open for editing: ' + err.message); });
  }

  function borrarSkill(id, nombre) {
    if (!window.confirm('Delete the skill “' + nombre + '”?')) { return; }
    api('/api/gcs/skills/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(cargarSkills).catch(function (err) { window.alert('Could not delete: ' + err.message); });
  }

  if (skNuevoBtn) { skNuevoBtn.addEventListener('click', abrirSkillForm); }
  if ($('skillsCancelar')) { $('skillsCancelar').addEventListener('click', cerrarSkillForm); }
  if (skForm) {
    skForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var base = skEditando || {};
      var payload = Object.assign({}, base, {
        id: (skId.value || '').trim(),
        name: (skNombre.value || '').trim(),
        description: (skDesc.value || '').trim(),
        profile: (skPerfil && skPerfil.value) || 'any',
        body: skBody.value || ''
      });
      if (!payload.id || !payload.name) { if (skEstado) { skEstado.textContent = 'Nombre e ID son obligatorios.'; } return; }
      if (skEstado) { skEstado.textContent = 'Saving…'; }
      api('/api/gcs/skills', { method: 'POST', body: JSON.stringify(payload) })
        .then(function () { cerrarSkillForm(); cargarSkills(); })
        .catch(function (err) { if (skEstado) { skEstado.textContent = 'Could not save: ' + err.message; } });
    });
  }

  // ==================================================================
  // MIS AGENTES  (Agent Factory de GCS · /api/gcs/agents)
  // ==================================================================
  var agLista = $('agentesMiosLista');
  var agNuevoBtn = $('agentesNuevoBtn'), agForm = $('agentesForm'), agEstado = $('agentesFormEstado');
  var agNombre = $('agenteNombre'), agId = $('agenteId'), agPerfil = $('agentePerfil');
  var agDesc = $('agenteDesc'), agGuardar = $('agentesGuardar');
  var agEditando = null;
  if (agNombre && agId) { autoId(agNombre, agId); }

  function cargarAgentes() {
    if (!agLista) { return; }
    agLista.innerHTML = '<p class="skills-cargando">Loading…</p>';
    api('/api/gcs/agents', { method: 'GET' }).then(function (d) {
      var propios = ((d && d.agents) || []).filter(function (a) { return (a.origin || 'custom') === 'custom'; });
      renderAgentes(propios);
    }).catch(function (err) {
      agLista.innerHTML = '<p class="skills-error">Could not load: ' + err.message + '</p>';
    });
  }

  function renderAgentes(agentes) {
    if (!agentes.length) { agLista.innerHTML = '<p class="skills-vacio">You do not have any custom agents yet. Create one.</p>'; return; }
    agLista.innerHTML = '';
    agentes.forEach(function (a) {
      var badges = [{ cls: 'skill-badge-perfil', txt: (a.profile || 'iris').toUpperCase() }];
      if (a.skills && a.skills.length) { badges.push({ cls: 'skill-badge-skills', txt: a.skills.length + ' skill' + (a.skills.length > 1 ? 's' : '') }); }
      agLista.appendChild(tarjeta(a, badges, true,
        function () { editarAgente(a); },
        function () { borrarAgente(a.id, a.name || a.id); }));
    });
  }

  function abrirAgForm() { if (agForm) { agForm.hidden = false; } if (agNuevoBtn) { agNuevoBtn.hidden = true; } if (agEstado) { agEstado.textContent = ''; } }
  function cerrarAgForm() {
    if (agForm) { agForm.hidden = true; agForm.reset(); }
    if (agId) { agId.readOnly = false; }
    if (agGuardar) { agGuardar.textContent = 'Create agent'; }
    if (agNuevoBtn) { agNuevoBtn.hidden = false; }
    agEditando = null;
  }

  function editarAgente(a) {
    agEditando = a;  // summary trae todos los campos (skills, tools, permisos…)
    agNombre.value = a.name || '';
    agId.value = a.id; agId.readOnly = true;
    if (agPerfil) { agPerfil.value = a.profile || 'iris'; }
    agDesc.value = a.description || '';
    if (agGuardar) { agGuardar.textContent = 'Save changes'; }
    abrirAgForm();
  }

  function borrarAgente(id, nombre) {
    if (!window.confirm('Delete the agent “' + nombre + '”?')) { return; }
    api('/api/gcs/agents/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(cargarAgentes).catch(function (err) { window.alert('Could not delete: ' + err.message); });
  }

  if (agNuevoBtn) { agNuevoBtn.addEventListener('click', abrirAgForm); }
  if ($('agentesCancelar')) { $('agentesCancelar').addEventListener('click', cerrarAgForm); }
  if (agForm) {
    agForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var base = agEditando || {};
      var payload = Object.assign({}, base, {
        id: (agId.value || '').trim(),
        name: (agNombre.value || '').trim(),
        profile: (agPerfil && agPerfil.value) || 'iris',
        description: (agDesc.value || '').trim()
      });
      if (!payload.id || !payload.name) { if (agEstado) { agEstado.textContent = 'Nombre e ID son obligatorios.'; } return; }
      if (agEstado) { agEstado.textContent = 'Saving…'; }
      api('/api/gcs/agents', { method: 'POST', body: JSON.stringify(payload) })
        .then(function () { cerrarAgForm(); cargarAgentes(); })
        .catch(function (err) { if (agEstado) { agEstado.textContent = 'Could not save: ' + err.message; } });
    });
  }

  cargarAgentes();
})();
