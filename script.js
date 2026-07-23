/* ============================================================
   GERAM OS v2 · NODO IRIS · script.js
   
   Módulos:
   1. Utilidades
   2. Reloj y uptime
   3. Estadísticas y medidores
   4. Consola de log
   5. Cinta de datos hex
   6. Análisis de voz (osciloscopio)
   7. Modos de uso (con color de acento)
   8. Botones de sentidos (toggle on/off)
   9. Chat / Subtítulos
   10. Retícula + Escena 3D (mouse tracking)
   11. Secuencia de arranque (boot)
   12. Bloqueo / standby
   13. Toggle modo offline manual
   14. Modo día / noche (NUEVO)
   15. Núcleo neuronal / canvas (NUEVO)
   16. Paneles expandibles (NUEVO)
   17. Avisos de recordatorios
   18. Núcleo + chat expandido al hablar (NUEVO)
   19. Sincronización de estado UI
   20. Dashboard de agentes (NUEVO)
   21. Examen interactivo (NUEVO)
   ============================================================ */

// ===================== 1. UTILIDADES =====================
var $ = function(s) { return document.querySelector(s); };
var $$ = function(s) { return document.querySelectorAll(s); };
var esEscritorio = window.matchMedia('(pointer:fine)').matches && window.innerWidth > 940;

// ===================== 2. RELOJ Y UPTIME =====================
function tic() {
  var d = new Date();
  $('#reloj').textContent = d.toLocaleTimeString('es-MX', { hour12: false });
  $('#fecha').textContent = d.toLocaleDateString('es-MX', {
    weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
  }).toUpperCase();
}
setInterval(tic, 1000);
tic();

var t0 = Date.now();
setInterval(function() {
  var s = Math.floor((Date.now() - t0) / 1000);
  var h = String(Math.floor(s / 3600)).padStart(2, '0');
  var m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  var x = String(s % 60).padStart(2, '0');
  $('#vUp').textContent = h + ':' + m + ':' + x;
}, 1000);

// ===================== 3. ESTADÍSTICAS Y MEDIDORES =====================
var LARGO_ARCO = 150.8;
var URL_STATS = '/stats';

function gauge(idArco, idAguja, idNum, v) {
  var g = $(idArco), a = $(idAguja), n = $(idNum);
  if (!g) return;
  g.style.strokeDashoffset = LARGO_ARCO * (1 - v);
  a.style.transform = 'rotate(' + ((v - 0.5) * 180) + 'deg)';
  n.textContent = Math.round(v * 100) + '%';
}

// Pone todos los indicadores en estado "sin conexión" cuando el
// servidor (server.py) no responde.
function statsSinConexion() {
  $('#bCpu').style.width = '0%';
  $('#vCpu').textContent = 'OFFLINE';
  $('#bRam').style.width = '0%';
  $('#vRam').textContent = 'OFFLINE';
  $('#bRed').style.width = '0%';
  $('#vRed').textContent = 'OFFLINE';
  $('#vTemp').textContent = 'OFFLINE';
  $('#pwr').textContent = 'PWR OFFLINE';
  gauge('#gEner', '#aEner', '#nEner', 0);
  gauge('#gApi',  '#aApi',  '#nApi',  0);
}

function stats() {
  fetch(URL_STATS)
    .then(function(res) {
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.json();
    })
    .then(function(d) {
      $('#bCpu').style.width = d.cpu + '%';
      $('#vCpu').textContent = d.cpu.toFixed(0) + '%';
      $('#bRam').style.width = d.ram + '%';
      $('#vRam').textContent = d.ram.toFixed(0) + '%';
      $('#bRed').style.width = Math.min(100, d.red_kbs / 9) + '%';
      $('#vRed').textContent = d.red_kbs.toFixed(0) + ' KB/s';
      $('#vTemp').textContent = d.temp.toFixed(0) + '\u00B0C';
      $('#pwr').textContent = 'PWR ' + d.pwr.toFixed(1) + '%';

      // gEner usa el nivel de "energía" (pwr) y gApi reutiliza el
      // % de disco usado, ya que no hay un endpoint de API que medir.
      gauge('#gEner', '#aEner', '#nEner', d.pwr / 100);
      gauge('#gApi',  '#aApi',  '#nApi',  d.disco / 100);
    })
    .catch(function(err) {
      statsSinConexion();
      esc('ERROR AL LEER ESTADÍSTICAS: ' + err.message);
    });
}
setInterval(stats, 2000);
stats();

// Nombre de la instancia (IRIS/ARES): se pide una sola vez al
// servidor en vez de dejarlo hardcodeado en el HTML. El HTML trae
// "IRIS" de relleno nada más para que no se vea vacío antes de que
// responda /info; en cuanto llega la respuesta, actualizarNombreEnHUD
// reemplaza TODOS los lugares donde aparece ese relleno (título,
// subtítulo, anillo del núcleo, nombre del núcleo, firma, primer
// mensaje del chat) por la instancia real (IRIS o ARES).
var NOMBRE_INSTANCIA = 'IRIS';

// "IRIS" -> "I.R.I.S.", "ARES" -> "A.R.E.S." (mismo estilo que ya
// traía el HTML a mano para el <title> y el boot sequence).
function formatoPuntos(nombre) {
  return nombre.split('').join('.') + '.';
}

function actualizarNombreEnHUD(nombre) {
  var punteado = formatoPuntos(nombre);

  var nombreEl = $('.nombre');
  if (nombreEl) { nombreEl.textContent = nombre; }

  document.title = 'GERAM OS · ' + punteado + ' · HUD';

  var subtituloEl = $('.subtitulo');
  if (subtituloEl) { subtituloEl.textContent = punteado + ' · SISTEMA HOLOGRÁFICO v2.1'; }

  var anilloTextoEl = document.querySelector('textPath');
  if (anilloTextoEl) {
    anilloTextoEl.textContent = anilloTextoEl.textContent.replace(/NODO \S+/, 'NODO ' + nombre);
  }

  var firmaEl = $('.firma');
  if (firmaEl && firmaEl.firstChild) {
    firmaEl.firstChild.textContent = 'GERAM OS v2 · NODO: ' + nombre + ' · SUPABASE SYNC ';
  }

  var chatQuienEl = document.querySelector('.chat-historial .chat-quien');
  if (chatQuienEl) { chatQuienEl.textContent = nombre; }
}

function cargarInfo() {
  fetch('/info')
    .then(function(res) { return res.json(); })
    .then(function(d) {
      NOMBRE_INSTANCIA = d.instancia;
      actualizarNombreEnHUD(NOMBRE_INSTANCIA);
      // Ver sección 20 (DASHBOARD DE AGENTES): renderDashboardAgentes
      // está definida más abajo en este mismo archivo (function
      // declaration, hoisted), así que ya existe para cuando esta
      // respuesta llegue.
      var activos = d.agentes_activos || [];
      renderDashboardAgentes(activos);
      actualizarConteoAnillo(activos.length);
    })
    .catch(function(err) {
      esc('ERROR AL LEER /info: ' + err.message);
    });
}
cargarInfo();

// ===================== 4. CONSOLA DE LOG =====================
var log = $('#log');
function esc(linea) {
  var p = document.createElement('p');
  p.textContent = '> ' + linea;
  log.appendChild(p);
  while (log.children.length > 9) { log.removeChild(log.firstChild); }
}

var frases = [
  'SUPABASE \u00B7 SINCRONIZACIÓN OK',
  'MEMORIA CLOUD ACTUALIZADA',
  'WHISPER: SIN ENTRADA DE VOZ',
  'BALANCEADOR: 5/5 NODOS ACTIVOS',
  'RESPALDO LOCAL COMPLETADO',
  'ESCANEO DE RED: SIN AMENAZAS',
  'AGENTE ESCUELA EN ESPERA',
  'RENDER HOLOGRÁFICO ESTABLE',
  // Referencia a la OTRA instancia (si corre IRIS, dice ARES y
  // viceversa — ver INSTANCIA_HERMANA), evaluada al momento de
  // mostrarse para que ya tenga el valor real de /info.
  function() { return 'ENLACE ' + INSTANCIA_HERMANA() + ': DISPONIBLE'; },
  'TTS PIPER: EN REPOSO',
  'OLLAMA: MODELO LOCAL CARGADO',
  'CONTEXT ENGINE: MODO ACTIVO'
];

function INSTANCIA_HERMANA() {
  return NOMBRE_INSTANCIA === 'ARES' ? 'IRIS' : 'ARES';
}

setInterval(function() {
  var r = Math.random();
  if (r < 0.18) {
    esc('PING API: ' + (60 + Math.floor(Math.random() * 90)) + 'ms');
  } else if (r < 0.34) {
    esc('GEMINI NODO ' + (1 + Math.floor(Math.random() * 5)) + ' \u2192 ROTACIÓN');
  } else {
    var frase = frases[Math.floor(Math.random() * frases.length)];
    esc(typeof frase === 'function' ? frase() : frase);
  }
}, 4300);

// ===================== 5. CINTA DE DATOS HEX =====================
var tk = '';
for (var i = 0; i < 24; i++) {
  tk += '0x' + Math.floor(Math.random() * 65535).toString(16).toUpperCase().padStart(4, '0') + '\u2002\u00B7\u2002';
}
$('#tickerA').textContent = tk;
$('#tickerB').textContent = tk;

// ===================== 6. ANÁLISIS DE VOZ (OSCILOSCOPIO REAL) =====================
// Web Audio API: un solo AudioContext compartido, con un AnalyserNode
// que apunta o al micrófono (mientras graba) o a la voz de IRIS
// (mientras reproduce su respuesta). dibujarOsc() (sección 10) lee
// de aquí; si no hay nada activo, dibuja silencio (línea plana).
var audioCtx = null;
var analizadorActivo = null;
var bufferAnalisis = null;
var micGrabando = false;
var irisHablando = false;
var fuenteMicActual = null;
var audioIrisActual = null; // <audio> con la voz TTS en curso, para poder cortarla desde el botón "volver"

function obtenerAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === 'suspended') { audioCtx.resume(); }
  return audioCtx;
}

function actualizarEstadoVoz() {
  var el = $('#vozEstado');
  if (!el) { return; }
  if (irisHablando) {
    el.textContent = 'IRIS HABLANDO…';
  } else if (micGrabando) {
    el.textContent = 'CAPTURANDO AUDIO…';
  } else {
    el.textContent = 'MIC APAGADO';
  }
}

function iniciarAnalisisMic(stream) {
  var ctxAudio = obtenerAudioCtx();
  fuenteMicActual = ctxAudio.createMediaStreamSource(stream);
  var analizador = ctxAudio.createAnalyser();
  analizador.fftSize = 512;
  fuenteMicActual.connect(analizador);
  analizadorActivo = analizador;
  bufferAnalisis = new Uint8Array(analizador.fftSize);
  micGrabando = true;
  actualizarEstadoVoz();
}

function detenerAnalisisMic() {
  if (fuenteMicActual) { fuenteMicActual.disconnect(); fuenteMicActual = null; }
  micGrabando = false;
  if (!irisHablando) { analizadorActivo = null; }
  actualizarEstadoVoz();
}

// Limpieza común de "IRIS terminó de hablar", usada tanto cuando el
// audio termina solo (evento 'ended') como cuando el usuario la corta
// a mano con el botón "volver" (ver detenerHablaIris más abajo).
// Quita 'expandido' aquí (además de en btnVolverNormal, que la quita
// de una para que el click se sienta instantáneo) para que el HUD
// SIEMPRE regrese solo a la vista normal en cuanto IRIS deja de
// hablar, sin que el jefe tenga que hacer click en nada.
function alTerminarHabla() {
  irisHablando = false;
  if (!micGrabando) { analizadorActivo = null; }
  actualizarEstadoVoz();
  if (window.setEstadoNucleo) { window.setEstadoNucleo(micGrabando ? 'escuchando' : 'idle'); }
  document.body.classList.remove('expandido');
}

function iniciarAnalisisAudio(audioEl) {
  var ctxAudio = obtenerAudioCtx();
  var fuente = ctxAudio.createMediaElementSource(audioEl);
  var analizador = ctxAudio.createAnalyser();
  analizador.fftSize = 512;
  fuente.connect(analizador);
  analizador.connect(ctxAudio.destination); // sin esto no se escucha
  analizadorActivo = analizador;
  bufferAnalisis = new Uint8Array(analizador.fftSize);
  irisHablando = true;
  audioIrisActual = audioEl;
  actualizarEstadoVoz();
  if (window.setEstadoNucleo) { window.setEstadoNucleo('hablando'); }
  // Modo expandido (núcleo + chat grandes, solo neuronas + chat
  // visibles vía 'hablando' en style.css) SOLO mientras IRIS habla
  // de verdad — se quita sola en alTerminarHabla().
  document.body.classList.add('expandido');

  audioEl.addEventListener('ended', alTerminarHabla);
}

// Corta la voz de IRIS a mitad de la respuesta (botón "volver" del
// modo hablando, sección 15/HTML) — funciona tanto con el <audio> de
// la voz TTS del servidor como con el respaldo speechSynthesis del
// navegador (hablarConVozDelNavegador). pause() no dispara 'ended',
// así que la limpieza de estado se llama a mano.
window.detenerHablaIris = function() {
  if (audioIrisActual && !audioIrisActual.paused) {
    audioIrisActual.pause();
    alTerminarHabla();
  }
  if (window.speechSynthesis) { window.speechSynthesis.cancel(); } // dispara onend, que ya limpia
};

actualizarEstadoVoz();

// Botón "volver" del modo hablando (ver style.css "MODO HABLANDO"):
// corta la voz de IRIS a la mitad y regresa al HUD normal de una.
// setEstadoNucleo se fuerza aparte porque detenerHablaIris() solo
// limpia si HAY audio sonando — si seguía en "pensando" (mandaste el
// mensaje pero la respuesta ni ha llegado) nada más lo saca de ahí.
var btnVolverNormal = $('#btnVolverNormal');
if (btnVolverNormal) {
  btnVolverNormal.addEventListener('click', function() {
    window.detenerHablaIris();
    if (window.setEstadoNucleo) { window.setEstadoNucleo(micGrabando ? 'escuchando' : 'idle'); }
    document.body.classList.remove('expandido');
  });
}

// ===================== 7. (MODOS ELIMINADOS - el director rutea por contexto) =====================

// ===================== 8. BOTONES DE SENTIDOS =====================
var botonesSentido = $$('.sentido');
var btnVozEl = $('#btn-voz');
var vozActiva = btnVozEl ? btnVozEl.classList.contains('activo') : false;

// El HTML trae #btn-mic marcado "activo" por defecto (antes solo
// indicaba "sentido disponible"). Ahora "activo" en MIC significa
// "grabando", así que forzamos que arranque apagado para no quedar
// desincronizados (si no, el primer clic intentaría detener una
// grabación que nunca empezó).
var btnMicEl = $('#btn-mic');
if (btnMicEl) { btnMicEl.classList.remove('activo'); }

var URL_AUDIO = '/audio';
var grabadora = null;
var trozosAudio = [];

function iniciarGrabacion() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    esc('ERROR: este navegador no soporta grabación de audio');
    return;
  }
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(function(stream) {
      trozosAudio = [];
      grabadora = new MediaRecorder(stream);
      grabadora.ondataavailable = function(e) { trozosAudio.push(e.data); };
      grabadora.onstop = function() {
        stream.getTracks().forEach(function(t) { t.stop(); });
        var blob = new Blob(trozosAudio, { type: 'audio/webm' });
        enviarAudioParaTranscribir(blob);
      };
      grabadora.start();
      iniciarAnalisisMic(stream);
      if (window.setEstadoNucleo) { window.setEstadoNucleo('escuchando'); }
      esc('MIC: GRABANDO…');
    })
    .catch(function(err) {
      esc('ERROR AL ACCEDER AL MICRÓFONO: ' + err.message);
    });
}

function detenerGrabacion() {
  if (grabadora && grabadora.state !== 'inactive') {
    grabadora.stop();
  }
  detenerAnalisisMic();
  if (window.setEstadoNucleo && !irisHablando) { window.setEstadoNucleo('idle'); }
}

function enviarAudioParaTranscribir(blob) {
  var datos = new FormData();
  datos.append('archivo', blob, 'grabacion.webm');
  esc('MIC: TRANSCRIBIENDO…');

  fetch(URL_AUDIO, { method: 'POST', body: datos })
    .then(function(res) {
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.json();
    })
    .then(function(d) {
      if (d.texto) {
        chatInput.value = d.texto;
        enviarMensaje();
      } else {
        esc('MIC: NO SE ENTENDIÓ NADA');
      }
    })
    .catch(function(err) {
      esc('ERROR AL TRANSCRIBIR AUDIO: ' + err.message);
    });
}

botonesSentido.forEach(function(btn) {
  btn.addEventListener('click', function() {
    // Click en CUALQUIER botón de sentido saca al núcleo/chat del modo
    // expandido antes de tiempo (salida manual — la automática es
    // cuando IRIS termina de hablar, ver sección 6/18).
    document.body.classList.remove('expandido');

    var estaActivo = btn.classList.toggle('activo');
    var sentido = btn.dataset.sentido;
    var nombre = sentido.toUpperCase();

    if (sentido === 'mic') {
      if (estaActivo) { iniciarGrabacion(); } else { detenerGrabacion(); }
      return;
    }

    if (sentido === 'voz') {
      vozActiva = estaActivo;
      // Igual que VISTA: sincroniza con control_agent.py para que
      // "cállate"/"activa tu voz" por texto/Telegram (ver
      // sincronizarEstadoUI más abajo) y el click de este botón
      // siempre cuenten la misma historia, sin importar el canal.
      fetch('/voz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activo: estaActivo })
      }).catch(function(err) { esc('ERROR AL SINCRONIZAR VOZ: ' + err.message); });
      esc(vozActiva ? 'VOZ ACTIVADA: ' + NOMBRE_INSTANCIA + ' HABLARÁ SUS RESPUESTAS' : 'VOZ DESACTIVADA');
      return;
    }

    if (sentido === 'vista') {
      // El backend (observador.py, Fase F) necesita saber si la
      // cámara está "prendida" para responder "activa mi vista
      // primero, jefe" en vez de intentar usarla apagada — el toggle
      // en sí es puramente visual aquí, por eso se sincroniza aparte.
      fetch('/vista', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activo: estaActivo })
      }).catch(function(err) { esc('ERROR AL SINCRONIZAR VISTA: ' + err.message); });
      esc(estaActivo ? 'VISTA ACTIVADA' : 'VISTA DESACTIVADA');
      return;
    }

    if (estaActivo) {
      esc('SENTIDO ACTIVADO: ' + nombre);
    } else {
      esc('SENTIDO DESACTIVADO: ' + nombre);
    }
  });
});

// ===================== 9. CHAT / SUBTÍTULOS =====================
var chatZona = $('#chatZona');
var chatHistorial = $('#chatHistorial');
var chatInput = $('#chatInput');
var chatEnviar = $('#chatEnviar');
var URL_CHAT = '/chat';

// --- Adjuntos (imagen pegada con Ctrl+V, o PDF por botón/drag&drop) ---
// El backend guarda el archivo como "pendiente" (agents/adjuntos_agent.py)
// y NO gasta tokens hasta que el usuario le da enviar en el chat — acá
// solo se sube el archivo y se muestra el chip, nada más.
var URL_ADJUNTAR = '/adjuntar';
var URL_ADJUNTAR_CANCELAR = '/adjuntar/cancelar';
var chatArchivoInput = $('#chatArchivoInput');
var chatAdjuntar = $('#chatAdjuntar');
var chatAdjuntoChip = $('#chatAdjuntoChip');
var chatAdjuntoNombre = $('#chatAdjuntoNombre');
var chatAdjuntoQuitar = $('#chatAdjuntoQuitar');
var adjuntoPendiente = null; // {tipo, nombre} mientras el chip está visible

function mostrarChipAdjunto(nombre) {
  chatAdjuntoNombre.textContent = '📎 ' + nombre;
  chatAdjuntoChip.style.display = 'flex';
}

function ocultarChipAdjunto() {
  chatAdjuntoChip.style.display = 'none';
  adjuntoPendiente = null;
}

function subirAdjunto(archivo) {
  if (!archivo) return;
  var formData = new FormData();
  formData.append('archivo', archivo, archivo.name || 'adjunto');

  esc('SUBIENDO ADJUNTO: ' + (archivo.name || 'sin nombre'));
  fetch(URL_ADJUNTAR, { method: 'POST', body: formData })
    .then(function(res) {
      if (!res.ok) { return res.json().then(function(d) { throw new Error(d.detail || ('HTTP ' + res.status)); }); }
      return res.json();
    })
    .then(function(d) {
      adjuntoPendiente = d;
      mostrarChipAdjunto(d.nombre);
      chatInput.placeholder = 'Pregunta algo sobre el adjunto, o dale enviar así nomás…';
      chatInput.focus();
    })
    .catch(function(err) {
      esc('ERROR AL ADJUNTAR: ' + err.message);
      agregarMensaje('No pude adjuntar ese archivo: ' + err.message, 'iris');
    });
}

chatAdjuntar.addEventListener('click', function() { chatArchivoInput.click(); });
chatArchivoInput.addEventListener('change', function() {
  if (this.files && this.files[0]) { subirAdjunto(this.files[0]); }
  this.value = ''; // permite volver a elegir el mismo archivo después
});

chatAdjuntoQuitar.addEventListener('click', function() {
  fetch(URL_ADJUNTAR_CANCELAR, { method: 'POST' }).catch(function() {});
  ocultarChipAdjunto();
  chatInput.placeholder = placeholderNormal;
});

// Pegar una imagen (Ctrl+V) directo en el input del chat.
chatInput.addEventListener('paste', function(e) {
  var items = (e.clipboardData || window.clipboardData).items;
  if (!items) return;
  for (var i = 0; i < items.length; i++) {
    if (items[i].type.indexOf('image') === 0) {
      subirAdjunto(items[i].getAsFile());
      e.preventDefault();
      break;
    }
  }
});

// Arrastrar y soltar un archivo (imagen o PDF) sobre la zona del chat.
chatZona.addEventListener('dragover', function(e) { e.preventDefault(); chatZona.classList.add('arrastrando'); });
chatZona.addEventListener('dragleave', function() { chatZona.classList.remove('arrastrando'); });
chatZona.addEventListener('drop', function(e) {
  e.preventDefault();
  chatZona.classList.remove('arrastrando');
  if (e.dataTransfer.files && e.dataTransfer.files[0]) { subirAdjunto(e.dataTransfer.files[0]); }
});

// --- Subir PDF para examen (botón aparte del de adjuntar normal) ---
// A diferencia de subirAdjunto(), esto NO gasta tokens ni queda como
// "pendiente" esperando una pregunta — solo se guarda en el server
// (examen_agent.RUTA_PDF_SUBIDO) para que "examen de este pdf" lo lea
// después (ver /subir-pdf en server.py).
var examenPdfInput = $('#examenPdfInput');
var examenPdfBoton = $('#examenPdfBoton');

examenPdfBoton.addEventListener('click', function() { examenPdfInput.click(); });
examenPdfInput.addEventListener('change', function() {
  var archivo = this.files && this.files[0];
  this.value = '';
  if (!archivo) return;

  var formData = new FormData();
  formData.append('archivo', archivo, archivo.name || 'documento.pdf');

  esc('SUBIENDO PDF PARA EXAMEN: ' + (archivo.name || 'sin nombre'));
  fetch('/subir-pdf', { method: 'POST', body: formData })
    .then(function(res) {
      if (!res.ok) { return res.json().then(function(d) { throw new Error(d.detail || ('HTTP ' + res.status)); }); }
      return res.json();
    })
    .then(function(d) {
      agregarMensaje('PDF "' + d.nombre + '" listo — dime "hazme un examen de este pdf" cuando quieras.', 'iris');
    })
    .catch(function(err) {
      esc('ERROR AL SUBIR PDF: ' + err.message);
      agregarMensaje('No pude subir ese PDF: ' + err.message, 'iris');
    });
});

// Marcador GENÉRICO que director.marcador_imagen() deja al final de la
// respuesta cuando trae una imagen que mostrar — "[IMAGEN:/figura]"
// ("dibújame X", ver figura_agent.py), "[IMAGEN:/foto]" ("toma foto",
// ver observador.py), etc. Mismo criterio que ya usa
// esMensajeDeConfirmacion con "CONFIRMAR": un token reconocible dentro
// del texto en vez de un canal aparte.
var PATRON_MARCADOR_IMAGEN = /\[IMAGEN:([^\]]+)\]/;

// Marcador de examen (ver director._procesar_examen/RUTA_PDF_SUBIDO):
// "[EXAMEN]" al final de la respuesta le dice al HUD que abra la vista
// de examen interactiva (sección 21) en vez de solo mostrar texto.
var PATRON_MARCADOR_EXAMEN = /\[EXAMEN\]/;

function extraerRutaImagen(texto) {
  var coincidencia = texto.match(PATRON_MARCADOR_IMAGEN);
  return coincidencia ? coincidencia[1] : null;
}

// ARREGLO 4: mensajes largos (+500 caracteres) llevan más espacio
// entre líneas (ver .chat-msg.mensaje-largo en style.css) para que un
// párrafo largo de IRIS no se sienta apretado.
var LIMITE_MENSAJE_LARGO = 500;

// El alto del historial y el tamaño de la letra cambian DESPUÉS de agregar el
// mensaje: al entrar/salir de 'expandido' u 'hablando' la letra crece de 12px
// a 16.5px con una transición de 0.6s (ver style.css). Un solo scrollTop se
// calcula con el layout viejo y la respuesta se queda debajo del área visible,
// mirando todavía los mensajes anteriores — hay que volver a pegarse al fondo
// cuando ese cambio termina.
function pegarAlFondo() {
  chatHistorial.scrollTop = chatHistorial.scrollHeight;
}

// transitionend burbujea desde cada .chat-msg, así que un solo listener en el
// contenedor cubre todas las transiciones de tamaño, incluidas las que
// disparan clases que se agregan mucho después de la respuesta.
chatHistorial.addEventListener('transitionend', pegarAlFondo);

function agregarMensaje(texto, quien, esConfirmacion) {
  var div = document.createElement('div');
  div.className = 'chat-msg ' + quien;
  if (texto.length > LIMITE_MENSAJE_LARGO) {
    div.classList.add('mensaje-largo');
  }

  var spanQuien = document.createElement('span');
  spanQuien.className = 'chat-quien';
  spanQuien.textContent = quien === 'iris' ? NOMBRE_INSTANCIA : 'TÚ';

  var spanTexto = document.createElement('span');
  spanTexto.className = 'chat-texto';

  var rutaImagen = extraerRutaImagen(texto);
  spanTexto.textContent = rutaImagen ? texto.replace(PATRON_MARCADOR_IMAGEN, '').trim() : texto;

  if (rutaImagen) {
    var img = document.createElement('img');
    // Cache-bust: la ruta del archivo en el server siempre es la
    // misma, así que sin esto el navegador podría mostrar la imagen
    // ANTERIOR cacheada en vez de la que se acaba de generar/tomar.
    img.src = rutaImagen + '?t=' + Date.now();
    img.alt = 'Imagen';
    // La imagen carga async y cambia el alto del historial DESPUÉS del
    // scroll de abajo (calculado con el alto de ANTES de que cargara)
    // — sin esto, una imagen puede quedar cortada arriba del scroll.
    img.addEventListener('load', pegarAlFondo);
    spanTexto.appendChild(document.createElement('br'));
    spanTexto.appendChild(img);
  }

  if (esConfirmacion) {
    // No hay una clase CSS para esto en el HTML original, así que se
    // resalta con estilo inline: quiere destacar que IRIS está
    // esperando que el usuario escriba CONFIRMAR o cancele.
    div.style.cssText = 'border-left:3px solid #ffb300;padding-left:8px;background:rgba(255,179,0,0.08);';
  }

  div.appendChild(spanQuien);
  div.appendChild(spanTexto);
  chatHistorial.appendChild(div);

  // Mantener solo los últimos 20 mensajes en pantalla. Va ANTES del scroll:
  // quitar mensajes de arriba cambia scrollHeight, y calcularlo después deja
  // el destino corto.
  while (chatHistorial.children.length > 20) {
    chatHistorial.removeChild(chatHistorial.firstChild);
  }

  // Auto-scroll al último mensaje (scroll-behavior:smooth en CSS lo
  // anima en vez de saltar en seco).
  pegarAlFondo();
  // El texto envuelve y el mensaje toma su alto real hasta el siguiente
  // frame; sin esto, un párrafo largo de IRIS aparece a medias.
  window.requestAnimationFrame(pegarAlFondo);
}

var URL_HABLAR = '/hablar';

// Respaldo de último recurso si /hablar falla (503: sin internet para
// edge-tts Y sin modelo de Piper instalado, ver habla.py). No compite
// con edge-tts/Piper (esos ya son mejores: voces neuronales reales
// contra la síntesis nativa del navegador, típicamente robótica en
// Linux); esto solo evita quedarse en silencio total en ese caso raro.
// No hay <audio> real de por medio, así que el osciloscopio (sección
// 6, iniciarAnalisisAudio) no puede engancharse a esta voz — se queda
// plano mientras habla, es el único costo del respaldo.
function hablarConVozDelNavegador(texto) {
  if (!window.speechSynthesis) {
    esc('ERROR: tampoco hay síntesis de voz nativa en este navegador.');
    return;
  }
  try {
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(texto);
    utterance.lang = 'es-MX';
    utterance.rate = 1.0;

    utterance.onstart = function() {
      irisHablando = true;
      actualizarEstadoVoz();
      if (window.setEstadoNucleo) { window.setEstadoNucleo('hablando'); }
      document.body.classList.add('expandido'); // mismo modo expandido que iniciarAnalisisAudio
    };
    utterance.onend = utterance.onerror = function() {
      irisHablando = false;
      actualizarEstadoVoz();
      if (window.setEstadoNucleo) { window.setEstadoNucleo(micGrabando ? 'escuchando' : 'idle'); }
      document.body.classList.remove('expandido');
    };

    window.speechSynthesis.speak(utterance);
  } catch (e) {
    esc('ERROR AL USAR LA VOZ DEL NAVEGADOR: ' + e.message);
  }
}

function reproducirRespuesta(texto) {
  fetch(URL_HABLAR, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto: texto })
  })
    .then(function(res) {
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.blob();
    })
    .then(function(blob) {
      var audio = new Audio(URL.createObjectURL(blob));
      iniciarAnalisisAudio(audio);
      audio.play();
    })
    .catch(function(err) {
      esc('ERROR AL GENERAR VOZ: ' + err.message + ' — uso la voz del navegador de respaldo');
      hablarConVozDelNavegador(texto);
    });
}

// Los mensajes de confirmación que arma director.py siempre incluyen
// literalmente la palabra CONFIRMAR en mayúsculas (ver
// director._pedir_confirmacion) — se usa eso para detectarlos aquí.
function esMensajeDeConfirmacion(texto) {
  return texto.indexOf('CONFIRMAR') !== -1;
}

var placeholderNormal = chatInput.placeholder;
var placeholderConfirmacion = 'Escribe CONFIRMAR o cualquier otra cosa para cancelar…';

function enviarMensaje() {
  var texto = chatInput.value.trim();
  // Sin adjunto pendiente, un mensaje vacío no manda nada (como antes).
  // Con adjunto pendiente, sí se puede dar enviar sin escribir nada —
  // es pedir el análisis/resumen genérico del adjunto.
  if (!texto && !adjuntoPendiente) return;

  // Mostrar mensaje del usuario (si venía con adjunto, se ve el chip
  // como parte del mensaje para que quede claro sobre qué preguntó)
  agregarMensaje((adjuntoPendiente ? '📎 ' + adjuntoPendiente.nombre + '\n' : '') + texto, 'usuario');
  chatInput.value = '';
  chatInput.placeholder = placeholderNormal;
  ocultarChipAdjunto(); // el backend ya lo limpia al procesar; esto solo sincroniza la UI

  // Log en consola
  esc('USUARIO: ' + texto.substring(0, 40) + (texto.length > 40 ? '...' : ''));
  if (window.setEstadoNucleo) { window.setEstadoNucleo('pensando'); }

  fetch(URL_CHAT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mensaje: texto })
  })
    .then(function(res) {
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.json();
    })
    .then(function(d) {
      var abreExamen = PATRON_MARCADOR_EXAMEN.test(d.respuesta);
      var textoRespuesta = abreExamen ? d.respuesta.replace(PATRON_MARCADOR_EXAMEN, '').trim() : d.respuesta;

      var esperandoConfirmacion = esMensajeDeConfirmacion(textoRespuesta);
      agregarMensaje(textoRespuesta, 'iris', esperandoConfirmacion);
      if (esperandoConfirmacion) {
        chatInput.placeholder = placeholderConfirmacion;
        chatInput.focus();
      }
      esc(NOMBRE_INSTANCIA + ': RESPUESTA ENVIADA');
      // No tiene caso narrar el marcador [IMAGEN:...] en voz alta — se
      // limpia antes de mandarlo a /hablar (ver agregarMensaje, que ya
      // lo quita del texto que se MUESTRA por su lado).
      // El modo expandido (núcleo + chat grandes, "solo neuronas y
      // chat") SOLO se activa si IRIS de verdad va a HABLAR esta
      // respuesta — se agrega/quita junto con el estado "hablando"
      // (ver iniciarAnalisisAudio/alTerminarHabla, sección 6, y
      // hablarConVozDelNavegador más abajo para el respaldo sin
      // <audio>) — con voz apagada, el HUD se queda normal.
      var textoHablado = textoRespuesta.replace(PATRON_MARCADOR_IMAGEN, '').trim();
      if (vozActiva && textoHablado) {
        reproducirRespuesta(textoHablado); // iniciarAnalisisAudio pone el núcleo en "hablando" + activa 'expandido'
      } else if (window.setEstadoNucleo) {
        window.setEstadoNucleo('idle');
      }

      // Ver sección 21: abre la vista de examen interactiva y arranca
      // en la primera pregunta (ya generada server-side, ver
      // examen_agent.iniciar_examen/director._procesar_examen).
      if (abreExamen && window.abrirExamen) { window.abrirExamen(); }
    })
    .catch(function(err) {
      agregarMensaje('OFFLINE', 'iris');
      esc('ERROR AL CONTACTAR /chat: ' + err.message);
      if (window.setEstadoNucleo) { window.setEstadoNucleo('error'); }
    });
}

chatEnviar.addEventListener('click', enviarMensaje);
chatInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    enviarMensaje();
  }
});

// ===================== 10. RETÍCULA + ESCENA 3D =====================
var escena = $('#escena');
var ret = $('#reticula');
var retCoords = $('#retCoords');
var mx = 0, my = 0, cx = 0, cy = 0;
var pmx = innerWidth / 2, pmy = innerHeight / 2, rx = pmx, ry = pmy;
var efecto3d = false; // apagado por defecto

// Toggle 3D
var btn3d = $('#toggle3d');
btn3d.addEventListener('click', function() {
  efecto3d = !efecto3d;
  btn3d.classList.toggle('activo', efecto3d);
  document.body.classList.toggle('con-3d', efecto3d);
  
  if (!efecto3d) {
    // Resetear posición de la escena al desactivar
    escena.style.transform = 'none';
  }
  
  esc('EFECTO 3D: ' + (efecto3d ? 'ACTIVADO' : 'DESACTIVADO'));
});

if (esEscritorio) {
  window.addEventListener('mousemove', function(e) {
    mx = e.clientX / innerWidth - 0.5;
    my = e.clientY / innerHeight - 0.5;
    pmx = e.clientX;
    pmy = e.clientY;
    document.body.classList.add('con-mouse');
  });
  
  document.addEventListener('mouseleave', function() {
    document.body.classList.remove('con-mouse');
    mx = 0;
    my = 0;
  });
}

// Osciloscopio: dibuja la onda real del AnalyserNode activo (mic o
// voz de IRIS, ver sección 6); si no hay ninguno, línea plana.
var osc = $('#osc'), ctx = osc.getContext('2d');
// Propiedades fijas del trazo: se fijan UNA vez (no en cada frame,
// como antes) porque no cambian entre dibujos — reasignarlas en cada
// frame era trabajo repetido sin ningún efecto visual extra.
ctx.strokeStyle = '#e84393';
ctx.lineWidth = 1.5;
ctx.shadowColor = 'rgba(232,67,147,0.8)';
ctx.shadowBlur = 6;

var oscPlano = false; // true cuando la última onda dibujada ya fue la línea plana de silencio

function dibujarOsc() {
  var hayAudio = analizadorActivo && bufferAnalisis;

  // Sin audio y la línea plana ya está dibujada: no hay nada nuevo que
  // pintar, así que nos ahorramos el clearRect+stroke (con shadowBlur,
  // que es la parte más cara) de este frame.
  if (!hayAudio && oscPlano) { return; }

  ctx.clearRect(0, 0, 256, 56);
  ctx.beginPath();

  if (hayAudio) {
    analizadorActivo.getByteTimeDomainData(bufferAnalisis);
    var pasos = bufferAnalisis.length;
    for (var i = 0; i < 256; i++) {
      var idx = Math.floor((i / 256) * pasos);
      var valor = (bufferAnalisis[idx] - 128) / 128; // rango -1..1
      var y = 28 + valor * 24;
      if (i === 0) { ctx.moveTo(i, y); } else { ctx.lineTo(i, y); }
    }
    oscPlano = false;
  } else {
    // Silencio: línea plana al centro del canvas.
    ctx.moveTo(0, 28);
    ctx.lineTo(256, 28);
    oscPlano = true;
  }

  ctx.stroke();
}

// Bucle principal de animación. Throttleado a ~30fps (igual que el
// núcleo neuronal, sección 15): sin esto corría a la frecuencia de
// refresco del monitor (60/120/144Hz), haciendo 2-4x más trabajo del
// necesario en pantallas rápidas para una animación que de todas
// formas no necesita más de 30fps para verse fluida.
var FPS_OBJETIVO_BUCLE = 30;
var INTERVALO_FRAME_BUCLE = 1000 / FPS_OBJETIVO_BUCLE;
var ultimoFrameBucle = 0;

function bucle(ahora) {
  requestAnimationFrame(bucle);
  if (ahora - ultimoFrameBucle < INTERVALO_FRAME_BUCLE) { return; }
  ultimoFrameBucle = ahora;

  if (esEscritorio) {
    // Retícula siempre sigue el mouse (es solo visual, no afecta nitidez)
    rx += (pmx - rx) * 0.16;
    ry += (pmy - ry) * 0.16;
    ret.style.transform = 'translate(' + (rx - 42).toFixed(1) + 'px,' + (ry - 42).toFixed(1) + 'px)';
    retCoords.textContent = 'X ' + rx.toFixed(0) + ' \u00B7 Y ' + ry.toFixed(0);
    
    // Tilt de la escena solo si 3D está activado
    if (efecto3d) {
      cx += (mx - cx) * 0.05;
      cy += (my - cy) * 0.05;
      escena.style.transform = 'rotateY(' + (cx * 8).toFixed(3) + 'deg) rotateX(' + (-cy * 6).toFixed(3) + 'deg)';
    }
  }
  dibujarOsc();
}
requestAnimationFrame(bucle);

// ===================== 11. SECUENCIA DE ARRANQUE =====================
var lineasBoot = [
  'INICIANDO GERAM OS v2.1 ...',
  'CARGANDO NÚCLEO .............. OK',
  'RENDER HOLOGRÁFICO .......... OK',
  'CALIBRANDO GIROSCOPIO ....... OK',
  'CONECTANDO SUPABASE ......... OK',
  'BALANCEADOR API ...... 5/5 NODOS',
  'AGENTES ................ EN LÍNEA',
  'STT · FASTER-WHISPER ...... LISTO',
  'TTS · PIPER ............... LISTO',
  'OLLAMA · MODELO LOCAL ..... LISTO',
  'SENTIDOS: MIC ✓  VOZ ✓  VISTA ○',
  // Estas dos usan la instancia real (NOMBRE_INSTANCIA, sección 3) en
  // vez de un string fijo, evaluadas hasta que les toca turno en el
  // setInterval de abajo — para entonces /info ya casi siempre
  // respondió, así que muestran IRIS o ARES según corresponda.
  function() { return 'ENLAZANDO NODO: ' + NOMBRE_INSTANCIA + ' ...... OK'; },
  '',
  function() { return formatoPuntos(NOMBRE_INSTANCIA) + ' EN LÍNEA'; },
  'A SUS ÓRDENES, JEFE.'
];

var bl = $('#bootLog'), li = 0;
var timerBoot = setInterval(function() {
  var linea = lineasBoot[li];
  if (typeof linea === 'function') { linea = linea(); }
  bl.textContent += '> ' + linea + '\n';
  li++;
  if (li >= lineasBoot.length) {
    clearInterval(timerBoot);
    setTimeout(function() {
      $('#boot').classList.add('fuera');
      document.body.classList.add('listo');
      esc('SISTEMA OPERATIVO · A SUS ÓRDENES, JEFE');
      intentarFullscreenTV();
    }, 650);
  }
}, 160);

// Pantallas grandes (TV, ver @media min-width:1920px en style.css):
// fullscreen automático. Los navegadores exigen un gesto de usuario
// real para conceder fullscreen — un timer del boot NO cuenta, así que
// esto es "mejor esfuerzo": puede fallar en silencio acá, pero el
// listener de abajo (primer click/tecla en la página) lo vuelve a
// intentar, y ESE sí cuenta como gesto de usuario — así igual se logra
// en la práctica en cuanto alguien toca la pantalla/control remoto.
function intentarFullscreenTV() {
  if (window.screen.width < 1920) { return; }
  if (document.fullscreenElement) { return; }
  if (!document.documentElement.requestFullscreen) { return; }
  document.documentElement.requestFullscreen().catch(function() {
    // Silencioso a propósito: sin gesto de usuario el navegador
    // rechaza la promesa, es esperado — el listener de abajo reintenta.
  });
}
document.addEventListener('click', intentarFullscreenTV, { once: true });
document.addEventListener('keydown', intentarFullscreenTV, { once: true });

// ===================== 12. BLOQUEO / STANDBY =====================
var URL_LOCK_STATUS = '/lock-status';
var URL_UNLOCK = '/unlock';
var overlayBloqueo = null;

function crearPantallaBloqueo() {
  if (overlayBloqueo) { return overlayBloqueo; }

  var overlay = document.createElement('div');
  overlay.id = 'overlayBloqueo';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;' +
    'align-items:center;justify-content:center;flex-direction:column;gap:16px;' +
    'background:rgba(4,10,10,0.94);backdrop-filter:blur(6px);' +
    'color:var(--principal,#e84393);font-family:inherit;text-align:center;padding:20px;';

  var titulo = document.createElement('div');
  titulo.style.cssText = 'font-size:1.4rem;letter-spacing:0.15em;';

  var sub = document.createElement('div');
  sub.textContent = 'INGRESA LA CONTRASEÑA PARA REACTIVAR';
  sub.style.cssText = 'opacity:0.7;font-size:0.8rem;letter-spacing:0.05em;';

  var input = document.createElement('input');
  input.type = 'password';
  input.className = 'chat-input';
  input.style.cssText = 'max-width:260px;text-align:center;';
  input.placeholder = 'Contraseña';

  var boton = document.createElement('button');
  boton.className = 'chat-enviar';
  boton.textContent = 'DESBLOQUEAR';
  boton.style.cssText = 'width:auto;padding:10px 24px;border-radius:8px;';

  var error = document.createElement('div');
  error.style.cssText = 'color:#ff5c5c;font-size:0.8rem;min-height:1em;';

  function intentarDesbloquear() {
    var intento = input.value;
    fetch(URL_UNLOCK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: intento })
    })
      .then(function(res) { return res.json(); })
      .then(function(d) {
        if (d.ok) {
          esc('DESBLOQUEO CORRECTO');
          ocultarPantallaBloqueo();
        } else {
          error.textContent = 'Contraseña incorrecta';
          input.value = '';
          input.focus();
        }
      })
      .catch(function(err) {
        error.textContent = 'ERROR: ' + err.message;
      });
  }

  boton.addEventListener('click', intentarDesbloquear);
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); intentarDesbloquear(); }
  });

  overlay.appendChild(titulo);
  overlay.appendChild(sub);
  overlay.appendChild(input);
  overlay.appendChild(boton);
  overlay.appendChild(error);
  document.body.appendChild(overlay);

  overlayBloqueo = overlay;
  overlayBloqueo.querySelector('div').textContent = NOMBRE_INSTANCIA + ' EN STANDBY';
  return overlay;
}

function mostrarPantallaBloqueo() {
  var overlay = crearPantallaBloqueo();
  overlay.style.display = 'flex';
  overlay.querySelector('input').focus();
}

function ocultarPantallaBloqueo() {
  if (overlayBloqueo) { overlayBloqueo.style.display = 'none'; }
}

function verificarLock() {
  fetch(URL_LOCK_STATUS)
    .then(function(res) { return res.json(); })
    .then(function(d) {
      if (d.bloqueado) {
        mostrarPantallaBloqueo();
      } else {
        ocultarPantallaBloqueo();
      }
    })
    .catch(function(err) {
      esc('ERROR AL LEER /lock-status: ' + err.message);
    });
}
setInterval(verificarLock, 5000);
verificarLock();

// ===================== 13. TOGGLE MODO OFFLINE MANUAL =====================
// El botón no existe en el HTML original, así que se crea por JS y se
// inserta junto a MIC/VOZ/VISTA, reusando la clase .sentido para que
// se vea igual.
var URL_MODO_OFFLINE = '/modo-offline';

function crearBotonOffline() {
  var contenedor = $('#sentidos');
  if (!contenedor || $('#btn-offline')) { return null; }

  var btn = document.createElement('button');
  btn.className = 'sentido';
  btn.id = 'btn-offline';
  btn.dataset.sentido = 'offline';
  btn.title = 'Forzar modo offline (Ollama)';
  btn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
    '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>' +
    '</svg><span>OFFLINE</span>';

  btn.addEventListener('click', function() {
    var forzarNuevo = !btn.classList.contains('activo');
    fetch(URL_MODO_OFFLINE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ forzar: forzarNuevo })
    })
      .then(function(res) {
        if (!res.ok) { throw new Error('HTTP ' + res.status); }
        return res.json();
      })
      .then(function(d) {
        btn.classList.toggle('activo', d.forzado_manual);
        esc(d.forzado_manual ? 'MODO OFFLINE FORZADO: USANDO OLLAMA' : 'MODO OFFLINE DESACTIVADO: USANDO GEMINI');
      })
      .catch(function(err) {
        esc('ERROR AL CAMBIAR MODO OFFLINE: ' + err.message);
      });
  });

  contenedor.appendChild(btn);
  return btn;
}

function sincronizarBotonOffline() {
  var btn = crearBotonOffline();
  if (!btn) { return; }

  fetch(URL_MODO_OFFLINE)
    .then(function(res) { return res.json(); })
    .then(function(d) {
      btn.classList.toggle('activo', d.forzado_manual);
    })
    .catch(function(err) {
      esc('ERROR AL LEER /modo-offline: ' + err.message);
    });
}
sincronizarBotonOffline();

// ===================== 14. MODO DÍA / NOCHE =====================
// El HUD entero ya lee sus colores de variables CSS; body.modo-dia
// (ver style.css) las pisa todas de un jalón. Aquí solo se persiste
// la preferencia y se le avisa al núcleo (sección 15) para que
// recoloree la red neuronal.
var CLAVE_MODO_DIA = 'geram_modo_dia';

// Utilidades de color que usa el canvas del núcleo para convertir
// --principal (hex) a rgb y armar sus propios rgba() por frame.
function hexToRgb(hex) {
  hex = hex.replace('#', '');
  return {
    r: parseInt(hex.substring(0, 2), 16),
    g: parseInt(hex.substring(2, 4), 16),
    b: parseInt(hex.substring(4, 6), 16)
  };
}
function rgbAFuncion(c, alfa) { return 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + alfa + ')'; }

var COLOR_PRINCIPAL_NOCHE = '#e84393';
var COLOR_PRINCIPAL_DIA = '#c0306a';

function aplicarModoDia(activar, guardar) {
  document.body.classList.toggle('modo-dia', activar);
  if (guardar !== false) { localStorage.setItem(CLAVE_MODO_DIA, activar ? '1' : '0'); }

  // El núcleo (sección 15) escucha esto para recolorear la red
  // neuronal sin tener que leer getComputedStyle en cada frame.
  document.dispatchEvent(new CustomEvent('geram:tema-cambiado', {
    detail: { color: activar ? COLOR_PRINCIPAL_DIA : COLOR_PRINCIPAL_NOCHE }
  }));
}

// Aplica el modo guardado ANTES del boot (el body sigue con
// opacity:0 hasta que termine, así que no hay parpadeo de un modo al
// otro aunque el usuario haya elegido modo día antes).
aplicarModoDia(localStorage.getItem(CLAVE_MODO_DIA) === '1', false);

var btnTema = $('#toggleTema');
if (btnTema) {
  btnTema.addEventListener('click', function() {
    var activar = !document.body.classList.contains('modo-dia');
    aplicarModoDia(activar);
    // Igual que VOZ/VISTA: sincroniza con control_agent.py para que
    // sincronizarEstadoUI() (poll cada 2s de /control/estado-ui) no
    // revierta el click de vuelta a los 2s por no saber que cambió
    // (antes esto era puramente local/localStorage).
    fetch('/modo-dia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activo: activar })
    }).catch(function(err) { esc('ERROR AL SINCRONIZAR MODO DÍA/NOCHE: ' + err.message); });
    esc(activar ? 'MODO DÍA ACTIVADO' : 'MODO NOCHE ACTIVADO');
  });
}

// ===================== 15. NÚCLEO NEURONAL / CANVAS =====================
// Reemplaza la esfera wireframe CSS por una red de nodos animada en
// Canvas 2D (más ligero que Three.js/WebGL para un i3 con 8GB).
// Estados: idle / escuchando / pensando / hablando / error, cambiables
// desde afuera con setEstadoNucleo(estado) (ver hooks en secciones 6, 8 y 9).
(function() {
  var canvas = $('#nucleoCanvas');
  if (!canvas) { return; }
  var ctx2 = canvas.getContext('2d');

  var NODOS_INICIAL = 50;   // dentro del rango pedido (40-60)
  var NODOS_MAX = 60;
  var NODOS_MIN = 20;       // piso de reducción automática por rendimiento
  var FPS_OBJETIVO = 30;    // throttle: no se dibuja más rápido que esto
  var INTERVALO_FRAME = 1000 / FPS_OBJETIVO;

  var ESTADOS = {
    idle:       { velRot: 0.05, amplitud: 0.035, radioEscala: 1.00, conexionDist: 0.55, agitacion: 0,     color: null },
    escuchando: { velRot: 0.05, amplitud: 0.025, radioEscala: 0.70, conexionDist: 0.62, agitacion: 0,     color: null },
    pensando:   { velRot: 0.24, amplitud: 0.08,  radioEscala: 1.04, conexionDist: 0.72, agitacion: 0.05,  color: null },
    hablando:   { velRot: 0.09, amplitud: 0.045, radioEscala: 1.00, conexionDist: 0.60, agitacion: 0,     color: null },
    error:      { velRot: 0.012, amplitud: 0.015, radioEscala: 0.88, conexionDist: 0.42, agitacion: 0,    color: '#ff4d4d' }
  };

  var estadoActual = 'idle';
  var colorActual = (getComputedStyle(document.body).getPropertyValue('--principal') || '#e84393').trim();
  document.addEventListener('geram:tema-cambiado', function(e) { colorActual = e.detail.color; });

  var nodos = [];
  function generarNodos(n) {
    var lista = [];
    var offset = 2 / n;
    var incremento = Math.PI * (3 - Math.sqrt(5)); // ángulo dorado: distribución pareja en la esfera
    for (var i = 0; i < n; i++) {
      var y = ((i * offset) - 1) + (offset / 2);
      var r = Math.sqrt(Math.max(0, 1 - y * y));
      var phi = i * incremento;
      lista.push({
        bx: Math.cos(phi) * r, by: y, bz: Math.sin(phi) * r,
        fase: Math.random() * Math.PI * 2,
        velFase: 0.5 + Math.random() * 0.7
      });
    }
    return lista;
  }
  nodos = generarNodos(NODOS_INICIAL);

  function ajustarTamCanvas() {
    var rect = canvas.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    ctx2.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  ajustarTamCanvas();
  window.addEventListener('resize', ajustarTamCanvas);

  var tiempoInicio = performance.now();
  var rotY = 0;
  var ultimoFrame = 0;
  var framesRecientes = [];

  function medirRendimientoYAjustar(ahora) {
    framesRecientes.push(ahora);
    while (framesRecientes.length && ahora - framesRecientes[0] > 1000) { framesRecientes.shift(); }
    if (ahora - tiempoInicio < 2000) { return; } // deja calentar antes de medir
    var fps = framesRecientes.length;
    if (fps > 0 && fps < 20 && nodos.length > NODOS_MIN) {
      nodos = generarNodos(Math.max(NODOS_MIN, nodos.length - 10));
      esc('NÚCLEO: FPS BAJO (' + fps + '), REDUCIENDO A ' + nodos.length + ' NODOS');
      framesRecientes = [];
    }
  }

  function dibujar(ahora) {
    var perfil = ESTADOS[estadoActual] || ESTADOS.idle;
    var t = (ahora - tiempoInicio) / 1000;
    rotY += perfil.velRot * (INTERVALO_FRAME / 1000);

    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) { return; }
    var cx = w / 2, cy = h / 2;
    var radioBase = Math.min(w, h) * 0.46;

    var escalaPulso = 1;
    if (estadoActual === 'hablando') {
      escalaPulso = 1 + 0.14 * Math.sin(t * 5.2); // pulso rítmico "al hablar"
    } else if (estadoActual === 'pensando') {
      escalaPulso = 1 + 0.05 * Math.sin(t * 9);
    }
    var radioEscala = perfil.radioEscala * escalaPulso;

    var color = perfil.color || colorActual;
    var rgb = hexToRgb(color.indexOf('#') === 0 ? color : colorActual);

    var proyectados = new Array(nodos.length);
    for (var i = 0; i < nodos.length; i++) {
      var n = nodos[i];
      var wob = 1 + perfil.amplitud * Math.sin(t * n.velFase + n.fase);
      var jx = 0, jy = 0;
      if (perfil.agitacion) {
        jx = Math.sin(t * 13 + n.fase) * perfil.agitacion;
        jy = Math.cos(t * 11 + n.fase) * perfil.agitacion;
      }
      var bx = n.bx + jx, by = n.by + jy, bz = n.bz;

      // Rotación orgánica lenta en Y (todo el núcleo "orbitando").
      var x = bx * Math.cos(rotY) + bz * Math.sin(rotY);
      var z = -bx * Math.sin(rotY) + bz * Math.cos(rotY);

      var factorPersp = 1 / (2 - z); // z en [-1,1] aprox: da profundidad simple
      var escala = wob * radioEscala * factorPersp;
      var brillo = 0.35 + 0.65 * ((z + 1) / 2);

      proyectados[i] = {
        px: cx + x * radioBase * escala,
        py: cy - by * radioBase * escala,
        brillo: brillo,
        r: 1.5 + brillo * 1.7
      };
    }

    ctx2.clearRect(0, 0, w, h);

    // Conexiones tipo constelación entre nodos cercanos en pantalla.
    var distMax = Math.min(w, h) * perfil.conexionDist * 0.5;
    ctx2.lineWidth = 1;
    for (var a = 0; a < proyectados.length; a++) {
      for (var b = a + 1; b < proyectados.length; b++) {
        var dx = proyectados[a].px - proyectados[b].px;
        var dy = proyectados[a].py - proyectados[b].py;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < distMax) {
          var op = (1 - d / distMax) * 0.35 * Math.min(proyectados[a].brillo, proyectados[b].brillo);
          ctx2.strokeStyle = rgbAFuncion(rgb, op.toFixed(3));
          ctx2.beginPath();
          ctx2.moveTo(proyectados[a].px, proyectados[a].py);
          ctx2.lineTo(proyectados[b].px, proyectados[b].py);
          ctx2.stroke();
        }
      }
    }

    // Nodos con glow suave. shadowBlur es caro en Canvas2D (recalcula
    // el blur en cada cambio), así que se fija UNA vez por frame en
    // vez de una vez por nodo — importante en CPUs modestas (i3).
    ctx2.shadowColor = rgbAFuncion(rgb, 0.9);
    ctx2.shadowBlur = 5;
    for (var k = 0; k < proyectados.length; k++) {
      var p = proyectados[k];
      ctx2.beginPath();
      ctx2.fillStyle = rgbAFuncion(rgb, (0.5 + p.brillo * 0.5).toFixed(3));
      ctx2.arc(p.px, p.py, p.r, 0, Math.PI * 2);
      ctx2.fill();
    }
    ctx2.shadowBlur = 0;
  }

  function bucleNucleo(ahora) {
    if (ahora - ultimoFrame >= INTERVALO_FRAME) {
      ultimoFrame = ahora;
      dibujar(ahora);
      medirRendimientoYAjustar(ahora);
    }
    requestAnimationFrame(bucleNucleo);
  }
  requestAnimationFrame(bucleNucleo);

  var timerErrorAutoReset = null;

  window.setEstadoNucleo = function(estado) {
    if (!ESTADOS[estado] || estado === estadoActual) { return; }
    estadoActual = estado;

    // El HUD se despeja desde el instante en que se manda el mensaje
    // ("pensando", ver script.js enviarMensaje) y no solo cuando
    // arranca el audio ("hablando") — así se siente instantáneo en vez
    // de esperar la ida y vuelta de red del chat + la síntesis de voz.
    // Solo quedan visibles la red neuronal (este canvas) y el chat
    // (ver CSS "MODO HABLANDO").
    document.body.classList.toggle('hablando', estado === 'hablando' || estado === 'pensando');

    if (timerErrorAutoReset) { clearTimeout(timerErrorAutoReset); timerErrorAutoReset = null; }
    if (estado === 'error') {
      timerErrorAutoReset = setTimeout(function() {
        if (estadoActual === 'error') { window.setEstadoNucleo('idle'); }
      }, 2500);
    }
  };
})();

// ===================== 16. PANELES EXPANDIBLES =====================
// Click en un panel lateral lo MUEVE (no lo clona, para no
// desincronizar los ids que script.js sigue actualizando en vivo:
// #reloj, #log, #vCpu, etc.) a #overlayPanel y lo agranda. Click en
// el fondo del overlay lo regresa a su lugar. La animación
// scale+translate es la técnica FLIP: se mide el rect antes/después
// del cambio de tamaño/posición y se anima la diferencia.
(function() {
  var overlayPanel = $('#overlayPanel');
  if (!overlayPanel) { return; }

  var expandido = null; // { panel, padre, siguienteHermano }

  function animarDesdeRect(panel, rectAntes) {
    var rectDespues = panel.getBoundingClientRect();
    var dx = (rectAntes.left + rectAntes.width / 2) - (rectDespues.left + rectDespues.width / 2);
    var dy = (rectAntes.top + rectAntes.height / 2) - (rectDespues.top + rectDespues.height / 2);
    var escalaX = rectAntes.width / rectDespues.width;
    var escalaY = rectAntes.height / rectDespues.height;

    panel.style.transition = 'none';
    panel.style.transform = 'translate(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px) scale(' + escalaX.toFixed(3) + ',' + escalaY.toFixed(3) + ')';

    // Doble rAF: el primero deja que el navegador aplique el
    // transform "sin transición" de arriba; el segundo, ya en el
    // frame siguiente, lo quita CON transición — eso es lo que anima.
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        panel.style.transition = '';
        panel.style.transform = '';
      });
    });
  }

  function expandirPanel(panel) {
    if (expandido) { return; }

    var rectAntes = panel.getBoundingClientRect();
    expandido = {
      panel: panel,
      padre: panel.parentNode,
      siguienteHermano: panel.nextSibling,
    };

    overlayPanel.appendChild(panel);
    panel.classList.add('panel-expandido');
    overlayPanel.classList.add('activo');

    animarDesdeRect(panel, rectAntes);
  }

  function colapsarPanel() {
    if (!expandido) { return; }
    var panel = expandido.panel;
    var rectAntes = panel.getBoundingClientRect();

    if (expandido.siguienteHermano) {
      expandido.padre.insertBefore(panel, expandido.siguienteHermano);
    } else {
      expandido.padre.appendChild(panel);
    }
    panel.classList.remove('panel-expandido');
    overlayPanel.classList.remove('activo');
    expandido = null;

    animarDesdeRect(panel, rectAntes);
  }

  $$('.col-izq .panel, .col-der .panel').forEach(function(panel) {
    panel.addEventListener('click', function() {
      if (panel.classList.contains('panel-expandido')) { return; }
      expandirPanel(panel);
    });
  });

  // Clic en el fondo del overlay (no en el panel) lo colapsa.
  overlayPanel.addEventListener('click', function(e) {
    if (e.target === overlayPanel) { colapsarPanel(); }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && expandido) { colapsarPanel(); }
  });
})();

// ===================== 17. AVISOS DE RECORDATORIOS =====================
// La voz del recordatorio ya se dice sola desde el checker en
// background del servidor (no depende de que este HUD esté abierto);
// esto solo hace poll para mostrar el texto en el chat cuando sí lo
// está. Mismo patrón que verificarLock().
var URL_RECORDATORIOS_AVISOS = '/recordatorios/avisos';

function revisarAvisosRecordatorios() {
  fetch(URL_RECORDATORIOS_AVISOS)
    .then(function(res) { return res.json(); })
    .then(function(d) {
      (d.avisos || []).forEach(function(texto) {
        agregarMensaje(texto, 'iris');
        esc('RECORDATORIO: ' + texto.substring(0, 40));
      });
    })
    .catch(function(err) {
      esc('ERROR AL LEER /recordatorios/avisos: ' + err.message);
    });
}
setInterval(revisarAvisosRecordatorios, 20000);
revisarAvisosRecordatorios();

// ===================== 17b. AVISOS DE PROACTIVIDAD =====================
// Mismo patrón que la sección 17, pero para proactividad_agent (gastos,
// batería, calendario, sesión larga sin parar). La voz también se dice
// sola desde el checker en background; esto solo pinta el texto en el
// chat.
var URL_PROACTIVIDAD_AVISOS = '/proactividad/avisos';

function revisarAvisosProactividad() {
  fetch(URL_PROACTIVIDAD_AVISOS)
    .then(function(res) { return res.json(); })
    .then(function(d) {
      (d.avisos || []).forEach(function(texto) {
        agregarMensaje(texto, 'iris');
        esc('PROACTIVIDAD: ' + texto.substring(0, 40));
      });
    })
    .catch(function(err) {
      esc('ERROR AL LEER /proactividad/avisos: ' + err.message);
    });
}
setInterval(revisarAvisosProactividad, 20000);
revisarAvisosProactividad();

// ===================== 18. NÚCLEO + CHAT EXPANDIDO AL HABLAR =====================
// La clase 'expandido' se agrega/quita sola junto con el estado
// "hablando" (ver sección 6: iniciarAnalisisAudio/alTerminarHabla, y
// hablarConVozDelNavegador para el respaldo sin <audio>) — entra en
// cuanto IRIS empieza a hablar de verdad y sale sola en cuanto
// termina, sin que el jefe tenga que hacer nada. Click en el núcleo o
// en un botón de sentido (sección 8) siguen siendo una salida manual
// ANTICIPADA, por si quiere volver al HUD normal antes de que termine
// la respuesta (no detienen el audio, solo el modo visual). CSS entero
// en style.css bajo "MODO EXPANDIDO".
var nucleoEl = $('.nucleo');
if (nucleoEl) {
  nucleoEl.addEventListener('click', function() {
    document.body.classList.remove('expandido');
  });
}


// ===================== 19. SINCRONIZACIÓN DE ESTADO UI =====================
var URL_CONTROL_ESTADO_UI = '/control/estado-ui';

// modo_dia/voz_activa se sincronizan por poll (pueden cambiar desde
// cualquier canal — voz/texto del HUD o Telegram — sin que este HUD se
// entere de otra forma). 'expandido' NO se incluye a propósito: entra/
// sale sola junto con el estado "hablando" (sección 6/18) y forzarla cada
// 2s pelearía con eso. mic_solicitud es "leer y limpia" (no un estado
// persistente que comparar): si trae "activar"/"desactivar" se simula el
// click en el botón MIC UNA sola vez (el MediaRecorder real vive en el
// navegador, Python no lo controla directo).
function sincronizarEstadoUI() {
  fetch(URL_CONTROL_ESTADO_UI)
    .then(function(res) { return res.json(); })
    .then(function(d) {
      if (d.modo_dia !== document.body.classList.contains('modo-dia')) { aplicarModoDia(d.modo_dia); }

      if (btnVozEl && d.voz_activa !== btnVozEl.classList.contains('activo')) {
        btnVozEl.classList.toggle('activo', d.voz_activa);
        vozActiva = d.voz_activa;
        esc(vozActiva ? 'VOZ ACTIVADA: ' + NOMBRE_INSTANCIA + ' HABLARÁ SUS RESPUESTAS' : 'VOZ DESACTIVADA');
      }

      if (d.mic_solicitud === 'activar' && !micGrabando) {
        btnMicEl.click();
      } else if (d.mic_solicitud === 'desactivar' && micGrabando) {
        btnMicEl.click();
      }
    })
    .catch(function() { /* silencioso: no es crítico, /stats ya avisa si el server está caído */ });
}
setInterval(sincronizarEstadoUI, 2000);
sincronizarEstadoUI();

// ===================== 20. DASHBOARD DE AGENTES =====================
// Botón junto al de modo día/noche (ver .controles-superiores):
// abre un overlay con la lista REAL de agentes activos que server.py
// ya expone en /info (AGENTES_ACTIVOS) — antes esa lista solo vivía
// hardcodeada por categorías en el panel lateral "AGENTES 27/27".
function prettificarNombreAgente(nombre) {
  var limpio = nombre.replace(/_agent$/, '').replace(/_/g, ' ');
  return limpio.toUpperCase();
}

var dashboardGrid = $('#dashboardGrid');
var dashboardConteo = $('#dashboardConteo');

// Conteo REAL de agentes en el anillo giratorio (antes decía "27 AGENTES"
// hardcodeado, aunque el número cambia según cuántos agentes tenga el usuario).
// Se llama desde el handler de /info con la cantidad de agentes activos. Si
// /info no responde, el anillo se queda en "AGENTES" sin número, no en una
// mentira fija.
function actualizarConteoAnillo(n) {
  var tp = document.getElementById('anilloAgentes');
  if (!tp || typeof n !== 'number') { return; }
  tp.textContent = tp.textContent.replace(/(\d+\s*)?AGENTES/i, n + ' AGENTES');
}

function renderDashboardAgentes(agentes) {
  if (!dashboardGrid) { return; }
  dashboardGrid.innerHTML = '';
  agentes.forEach(function(nombreAgente) {
    var card = document.createElement('div');
    card.className = 'dashboard-card';
    var dot = document.createElement('span');
    dot.className = 'dot';
    var texto = document.createElement('span');
    texto.textContent = prettificarNombreAgente(nombreAgente);
    card.appendChild(dot);
    card.appendChild(texto);
    dashboardGrid.appendChild(card);
  });
  if (dashboardConteo) { dashboardConteo.textContent = agentes.length + '/' + agentes.length; }
}

(function() {
  var overlay = $('#dashboardAgentes');
  var btnAbrir = $('#toggleAgentes');
  var btnCerrar = $('#dashboardCerrar');
  var fondo = $('#dashboardFondo');
  if (!overlay || !btnAbrir) { return; }

  function abrirDashboard() {
    overlay.classList.add('activo');
    btnAbrir.classList.add('activo');
  }
  function cerrarDashboard() {
    overlay.classList.remove('activo');
    btnAbrir.classList.remove('activo');
  }

  btnAbrir.addEventListener('click', function() {
    if (overlay.classList.contains('activo')) { cerrarDashboard(); } else { abrirDashboard(); }
  });
  if (btnCerrar) { btnCerrar.addEventListener('click', cerrarDashboard); }
  if (fondo) { fondo.addEventListener('click', cerrarDashboard); }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && overlay.classList.contains('activo')) { cerrarDashboard(); }
  });
})();

// ===================== 21. EXAMEN INTERACTIVO =====================
// "hazme un examen de X" (ver director._procesar_examen) deja el
// marcador "[EXAMEN]" en la respuesta de /chat (ver PATRON_MARCADOR_
// EXAMEN, sección 9) — window.abrirExamen() abre esta vista y consume
// /examen/actual, /examen/responder, /examen/cancelar (server.py).
// Un examen a la vez, mismo criterio que el resto del proyecto
// (adjuntos_agent._pendiente, observador._vista_activa).
(function() {
  var modal = $('#examenModal');
  var fondo = $('#examenFondo');
  var btnCerrar = $('#examenCerrar');
  var temaLabel = $('#examenTemaLabel');
  var progresoBarra = $('#examenProgresoBarra');
  var progresoTexto = $('#examenProgresoTexto');
  var cuerpo = $('#examenCuerpo');
  var preguntaEl = $('#examenPregunta');
  var opcionesEl = $('#examenOpciones');
  var feedbackEl = $('#examenFeedback');
  var feedbackTextoEl = $('#examenFeedbackTexto');
  var feedbackExplicacionEl = $('#examenFeedbackExplicacion');
  var btnSiguiente = $('#examenSiguiente');
  var finalEl = $('#examenFinal');
  var finalNotaEl = $('#examenFinalNota');
  var finalFallosEl = $('#examenFinalFallos');
  var btnCerrarFinal = $('#examenCerrarFinal');
  if (!modal) { return; }

  var examenTerminado = false;

  function mostrarPregunta() {
    finalEl.style.display = 'none';
    feedbackEl.style.display = 'none';
    cuerpo.style.display = 'block';
  }

  function renderPregunta(data) {
    examenTerminado = false;
    temaLabel.textContent = data.tema || '';
    preguntaEl.textContent = data.pregunta;
    progresoTexto.textContent = 'Pregunta ' + (data.indice + 1) + ' de ' + data.total;
    progresoBarra.style.width = Math.round((data.indice / data.total) * 100) + '%';

    opcionesEl.innerHTML = '';
    data.opciones.forEach(function(texto) {
      var letra = (texto.trim().charAt(0) || '').toUpperCase();
      var btn = document.createElement('button');
      btn.className = 'examen-opcion';
      btn.textContent = texto;
      btn.dataset.letra = letra;
      btn.addEventListener('click', function() { responderPregunta(letra, btn); });
      opcionesEl.appendChild(btn);
    });

    mostrarPregunta();
  }

  function cargarPreguntaActual() {
    fetch('/examen/actual')
      .then(function(res) { return res.json(); })
      .then(function(d) {
        if (!d.activo) { cerrarExamen(false); return; }
        renderPregunta(d);
      })
      .catch(function(err) { esc('ERROR AL CARGAR EL EXAMEN: ' + err.message); });
  }

  function responderPregunta(letra, btnClickeado) {
    var botones = opcionesEl.querySelectorAll('.examen-opcion');
    botones.forEach(function(b) { b.disabled = true; });

    fetch('/examen/responder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ respuesta: letra })
    })
      .then(function(res) {
        if (!res.ok) { return res.json().then(function(d) { throw new Error(d.detail || ('HTTP ' + res.status)); }); }
        return res.json();
      })
      .then(function(d) {
        botones.forEach(function(b) {
          if (b.dataset.letra === d.respuesta_correcta) { b.classList.add('correcta'); }
          else if (b === btnClickeado) { b.classList.add('incorrecta'); }
        });
        progresoBarra.style.width = '100%';

        feedbackTextoEl.textContent = d.correcto ? '✅ ¡Correcto!' : '❌ Incorrecto, la respuesta correcta era ' + d.respuesta_correcta + '.';
        feedbackTextoEl.className = 'examen-feedback-texto ' + (d.correcto ? 'ok' : 'mal');
        feedbackExplicacionEl.textContent = d.explicacion || '';
        btnSiguiente.textContent = d.terminado ? 'Ver resultado →' : 'Siguiente →';
        feedbackEl.style.display = 'block';

        examenTerminado = d.terminado;
        if (examenTerminado) { window._examenResultadoFinal = d; }
      })
      .catch(function(err) {
        esc('ERROR AL RESPONDER EXAMEN: ' + err.message);
        botones.forEach(function(b) { b.disabled = false; });
      });
  }

  function renderFinal(d) {
    cuerpo.style.display = 'none';
    feedbackEl.style.display = 'none';
    finalNotaEl.textContent = d.aciertos + '/' + d.total + ' aciertos';

    finalFallosEl.innerHTML = '';
    if (d.fallos && d.fallos.length) {
      var titulo = document.createElement('p');
      titulo.textContent = 'Repasa esto:';
      titulo.style.color = 'var(--texto)';
      finalFallosEl.appendChild(titulo);
      d.fallos.forEach(function(texto) {
        var p = document.createElement('p');
        p.textContent = '– ' + texto;
        finalFallosEl.appendChild(p);
      });
    } else {
      var p = document.createElement('p');
      p.textContent = '¡Las acertaste todas!';
      finalFallosEl.appendChild(p);
    }

    finalEl.style.display = 'block';
  }

  btnSiguiente.addEventListener('click', function() {
    if (examenTerminado) {
      renderFinal(window._examenResultadoFinal || { aciertos: 0, total: 0, fallos: [] });
    } else {
      cargarPreguntaActual();
    }
  });

  function cerrarExamen(avisarBackend) {
    modal.classList.remove('activo');
    if (avisarBackend !== false) {
      fetch('/examen/cancelar', { method: 'POST' }).catch(function() {});
    }
  }

  window.abrirExamen = function() {
    modal.classList.add('activo');
    cargarPreguntaActual();
  };

  btnCerrar.addEventListener('click', function() { cerrarExamen(true); });
  fondo.addEventListener('click', function() { cerrarExamen(true); });
  btnCerrarFinal.addEventListener('click', function() { cerrarExamen(false); });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && modal.classList.contains('activo')) { cerrarExamen(true); }
  });
})();
