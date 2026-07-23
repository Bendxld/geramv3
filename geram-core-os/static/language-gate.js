// ============================================================
// GERAM CORE OS · language-gate.js
// Pantalla de selección de idioma que aparece ANTES del manual/setup, solo
// mientras el usuario no haya elegido idioma todavía (localStorage vacío).
// Cubre todo con el z-index más alto; al elegir, aplica la traducción a toda
// la UI (incluidos el setup y el manual que ya estén montados), sincroniza el
// idioma del asistente y se cierra dejando ver la interfaz ya traducida.
// ============================================================
(function (root) {
  'use strict';

  var doc = root.document;

  function boot() {
    var i18n = root.GeramI18n;
    var gate = doc.getElementById('langGate');
    if (!gate || !i18n) { return; }

    // Ya eligió antes: no molestar, la UI ya se tradujo en i18n.init().
    if (i18n.hasChoice()) { return; }

    gate.classList.add('activo');
    gate.setAttribute('aria-hidden', 'false');

    var botones = gate.querySelectorAll('[data-lang]');
    Array.prototype.forEach.call(botones, function (btn) {
      btn.addEventListener('click', function () {
        i18n.setLanguage(btn.getAttribute('data-lang'));
        gate.classList.remove('activo');
        gate.setAttribute('aria-hidden', 'true');
      });
    });
  }

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
