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
   19. Control por gestos (Fase H, NUEVO)
   20. Dashboard de agentes (NUEVO)
   21. Settings unificados
   ============================================================ */

// ===================== 0. KIOSK: BLOQUEA CLIC DERECHO =====================
// No existe una flag de línea de comandos en Chromium/Brave para
// desactivar el menú contextual del sistema — se bloquea aquí, a nivel
// de página, para el modo kiosk (ver iniciar_kiosk.sh). No afecta
// F12/Ctrl+Shift+I (DevTools): esos son atajos de teclado, no pasan
// por el evento 'contextmenu'.
document.addEventListener('contextmenu', function(e) { e.preventDefault(); });

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

function formatUptime(totalSeconds) {
  var s = Math.max(0, Math.floor(Number(totalSeconds || 0)));
  var h = String(Math.floor(s / 3600)).padStart(2, '0');
  var m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  var x = String(s % 60).padStart(2, '0');
  return h + ':' + m + ':' + x;
}

// ===================== 3. ESTADÍSTICAS Y MEDIDORES =====================
var LARGO_ARCO = 150.8;

function gauge(idArco, idAguja, idNum, v) {
  var g = $(idArco), a = $(idAguja), n = $(idNum);
  if (!g) return;
  g.style.strokeDashoffset = LARGO_ARCO * (1 - v);
  a.style.transform = 'rotate(' + ((v - 0.5) * 180) + 'deg)';
  n.textContent = Math.round(v * 100) + '%';
}

// Pone todos los indicadores en estado "sin conexión" cuando el
// WebSocket de telemetría (/ws/hud) no está conectado.
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

// Mismo mapeo de campos que ya funcionaba por polling: GERAM CORE OS
// /telemetry/snapshot (app/api/telemetry.py::get_snapshot) regresa
// {cpu_percent, ram_percent, ram_used_mb, ram_total_mb}. Ahora llega
// por WebSocket en vez de fetch, pero el shape es el mismo.
function pintarTelemetria(d) {
  $('#bCpu').style.width = d.cpu_percent + '%';
  $('#vCpu').textContent = d.cpu_percent.toFixed(0) + '%';
  $('#bRam').style.width = d.ram_percent + '%';
  $('#vRam').textContent = d.ram_percent.toFixed(0) + '%';
  $('#vUp').textContent = formatUptime(d.system_uptime_seconds);

  var network = Number(d.network_kbs || 0);
  $('#bRed').style.width = Math.min(100, network / 10) + '%';
  $('#vRed').textContent = network.toFixed(1) + ' KB/s';
  $('#vTemp').textContent = d.temperature_c == null ? 'N/D' : Number(d.temperature_c).toFixed(1) + '°C';
  var power = Math.max(0, Math.min(100, Number(d.power_percent || 0)));
  $('#pwr').textContent = 'PWR ' + power.toFixed(0) + '%';
  gauge('#gEner', '#aEner', '#nEner', power / 100);
  gauge('#gApi', '#aApi', '#nApi', Math.max(0, Math.min(100, Number(d.disk_percent || 0))) / 100);
}

// ===================== 3b. WEBSOCKET DE TELEMETRÍA (/ws/hud) =====================
// Reemplaza el polling anterior (fetch cada 2s a /telemetry/snapshot) por
// un canal en tiempo real: el backend hace broadcast de un snapshot cada
// TELEMETRY_INTERVAL_SECONDS (ver app/websocket/hud_socket.py). Si se
// desconecta, se cae al mismo fallback OFFLINE de antes y reintenta solo.
var RECONEXION_WS_MS = 3000;
var socketTelemetria = null;
var reconexionWsTimeoutId = null;

function conectarWebSocketTelemetria() {
  var protocolo = (location.protocol === 'https:') ? 'wss:' : 'ws:';
  socketTelemetria = new WebSocket(protocolo + '//' + location.host + '/ws/hud');

  socketTelemetria.onopen = function() {
    esc('TELEMETRÍA: WEBSOCKET CONECTADO');
  };

  socketTelemetria.onmessage = function(evento) {
    var mensaje;
    try {
      mensaje = JSON.parse(evento.data);
    } catch (e) {
      return;
    }
    if (mensaje.type === 'telemetry' && mensaje.data) {
      pintarTelemetria(mensaje.data);
    }
  };

  socketTelemetria.onclose = function() {
    statsSinConexion();
    esc('TELEMETRÍA: WEBSOCKET DESCONECTADO, reintentando...');
    clearTimeout(reconexionWsTimeoutId);
    reconexionWsTimeoutId = setTimeout(conectarWebSocketTelemetria, RECONEXION_WS_MS);
  };

  socketTelemetria.onerror = function() {
    // onclose ya se dispara después de onerror — ahí se maneja el
    // fallback OFFLINE y el reintento, no hace falta duplicarlo aquí.
    socketTelemetria.close();
  };
}
conectarWebSocketTelemetria();

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

  var firmaEl = $('.firma');
  if (firmaEl && firmaEl.firstChild) {
    firmaEl.firstChild.textContent = 'GERAM CORE OS v3 · NODE: ' + nombre + ' · LOCAL CORE ';
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
    })
    .catch(function(err) {
      esc('ERROR AL LEER /info: ' + err.message);
    });
}
// ===================== 4. CONSOLA DE LOG =====================
var log = $('#log');
function esc(linea) {
  var p = document.createElement('p');
  p.textContent = '> ' + linea;
  log.appendChild(p);
  while (log.children.length > 9) { log.removeChild(log.firstChild); }
}
window.geramLog = esc;

function INSTANCIA_HERMANA() {
  return NOMBRE_INSTANCIA === 'ARES' ? 'IRIS' : 'ARES';
}

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

var URL_AUDIO = '/api/media/audio';
var grabadora = null;
var trozosAudio = [];

function iniciarGrabacion() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    esc('ERROR: this browser does not support audio recording');
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
  esc('MIC: TRANSCRIBIENDO…');

  fetch(URL_AUDIO, {
    method: 'POST',
    headers: { 'Content-Type': blob.type || 'audio/webm' },
    body: blob
  })
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

function guardarEstadoRuntime(cambios) {
  return fetch('/api/runtime/state', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios)
  }).then(function(res) {
    if (!res.ok) { throw new Error('HTTP ' + res.status); }
    return res.json();
  });
}

function capturarImagenCamara() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return Promise.reject(new Error('Camera capture is not supported'));
  }
  return navigator.mediaDevices.getUserMedia({ video: true }).then(function(stream) {
    return new Promise(function(resolve, reject) {
      var video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      function cerrar() { stream.getTracks().forEach(function(track) { track.stop(); }); }
      video.addEventListener('loadedmetadata', function() {
        video.play().then(function() {
          var canvas = document.createElement('canvas');
          canvas.width = Math.min(video.videoWidth || 1280, 1920);
          canvas.height = Math.round(canvas.width * ((video.videoHeight || 720) / (video.videoWidth || 1280)));
          canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function(blob) {
            cerrar();
            if (!blob) { reject(new Error('Camera frame could not be encoded')); return; }
            subirAdjunto(blob, 'camera-capture.jpg');
            resolve();
          }, 'image/jpeg', 0.9);
        }).catch(function(error) { cerrar(); reject(error); });
      }, { once: true });
      video.addEventListener('error', function() { cerrar(); reject(new Error('Camera capture failed')); }, { once: true });
    });
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
      guardarEstadoRuntime({ voice_enabled: estaActivo }).catch(function(err) {
        btn.classList.toggle('activo', !estaActivo);
        vozActiva = !estaActivo;
        esc('ERROR AL GUARDAR VOZ: ' + err.message);
      });
      esc(vozActiva ? 'VOZ ACTIVADA: ' + NOMBRE_INSTANCIA + ' HABLARÁ SUS RESPUESTAS' : 'VOZ DESACTIVADA');
      return;
    }

    if (sentido === 'vista') {
      guardarEstadoRuntime({ vision_enabled: estaActivo }).catch(function(err) {
        btn.classList.toggle('activo', !estaActivo);
        esc('ERROR AL GUARDAR VISIÓN: ' + err.message);
      });
      if (estaActivo) {
        esc('VISIÓN: CAPTURANDO UNA IMAGEN…');
        capturarImagenCamara().then(function() {
          esc('VISIÓN: IMAGEN ADJUNTA, LISTA PARA ENVIAR');
        }).catch(function(err) {
          btn.classList.remove('activo');
          guardarEstadoRuntime({ vision_enabled: false }).catch(function() {});
          esc('ERROR DE CÁMARA: ' + err.message);
        });
      } else {
        esc('VISIÓN DESACTIVADA');
      }
      return;
    }

    if (sentido === 'gestos') {
      // Independiente de VISTA a propósito (ver PASO 3.5): control por
      // gestos y "tomar fotos/mírame" son dos cámaras separadas que no
      // pueden estar abiertas al mismo tiempo (ver gesture_agent.py).
      toggleGestos(estaActivo);
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
var URL_CHAT = '/orchestrator/route'; // antes '/chat' (server.py viejo) — repuntado al orquestador de GERAM CORE OS

// --- Adjuntos (imagen pegada con Ctrl+V, o PDF por botón/drag&drop) ---
// El backend guarda el archivo como "pendiente" (agents/adjuntos_agent.py)
// y NO gasta tokens hasta que el usuario le da enviar en el chat — acá
// solo se sube el archivo y se muestra el chip, nada más.
var URL_ADJUNTAR = '/api/media/attachments';
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

function subirAdjunto(archivo, nombreForzado) {
  if (!archivo) return;
  var nombre = nombreForzado || archivo.name || 'attachment';

  esc('SUBIENDO ADJUNTO: ' + nombre);
  fetch(URL_ADJUNTAR + '?filename=' + encodeURIComponent(nombre), {
    method: 'POST',
    headers: { 'Content-Type': archivo.type || 'application/octet-stream' },
    body: archivo
  })
    .then(function(res) {
      if (!res.ok) { return res.json().then(function(d) { throw new Error((d.detail && d.detail.message) || ('HTTP ' + res.status)); }); }
      return res.json();
    })
    .then(function(d) {
      adjuntoPendiente = d;
      mostrarChipAdjunto(d.nombre);
      chatInput.placeholder = 'Ask something about the attachment, or just hit send…';
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
  fetch(URL_ADJUNTAR, { method: 'DELETE' }).catch(function() {});
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

// Marcador GENÉRICO que director.marcador_imagen() deja al final de la
// respuesta cuando trae una imagen que mostrar — "[IMAGEN:/figura]"
// ("dibújame X", ver figura_agent.py), "[IMAGEN:/foto]" ("toma foto",
// ver observador.py), etc. Mismo criterio que ya usa
// esMensajeDeConfirmacion con "CONFIRMAR": un token reconocible dentro
// del texto en vez de un canal aparte.
var PATRON_MARCADOR_IMAGEN = /\[IMAGEN:([^\]]+)\]/;

function extraerRutaImagen(texto) {
  var coincidencia = texto.match(PATRON_MARCADOR_IMAGEN);
  return coincidencia ? coincidencia[1] : null;
}

// ARREGLO 4: mensajes largos (+500 caracteres) llevan más espacio
// entre líneas (ver .chat-msg.mensaje-largo en style.css) para que un
// párrafo largo de IRIS no se sienta apretado.
var LIMITE_MENSAJE_LARGO = 500;

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
    img.addEventListener('load', function() {
      chatHistorial.scrollTop = chatHistorial.scrollHeight;
    });
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

  // Auto-scroll al último mensaje (scroll-behavior:smooth en CSS lo
  // anima en vez de saltar en seco).
  chatHistorial.scrollTop = chatHistorial.scrollHeight;

  // Mantener solo los últimos 20 mensajes en pantalla
  while (chatHistorial.children.length > 20) {
    chatHistorial.removeChild(chatHistorial.firstChild);
  }
}

function hablarConVozDelNavegador(texto) {
  if (!window.speechSynthesis) {
    esc('ERROR: this browser has no native speech synthesis either.');
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
  hablarConVozDelNavegador(texto);
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
  var usarAdjunto = Boolean(adjuntoPendiente);
  agregarMensaje((usarAdjunto ? '📎 ' + adjuntoPendiente.nombre + '\n' : '') + texto, 'usuario');
  chatInput.value = '';
  chatInput.placeholder = placeholderNormal;
  ocultarChipAdjunto(); // el backend ya lo limpia al procesar; esto solo sincroniza la UI

  // Log en consola
  esc('USUARIO: ' + texto.substring(0, 40) + (texto.length > 40 ? '...' : ''));
  if (window.setEstadoNucleo) { window.setEstadoNucleo('pensando'); }

  fetch(URL_CHAT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: texto, source: 'hud_local', use_pending_attachment: usarAdjunto })
  })
    .then(function(res) {
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.json();
    })
    .then(function(d) {
      // El orquestador nuevo regresa {mode, session_id, result, metadata}.
      // result.text llega de Gemini (modo iris). Si tocó modo ares
      // (Codex, todavía stub) o Gemini tronó, result.message trae el
      // detalle en vez de un texto de respuesta real.
      var respuestaOrquestador = (d.result && (d.result.text || d.result.message))
        || 'ERROR: the orchestrator returned no usable response.';

      var textoRespuesta = respuestaOrquestador;

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
    })
    .catch(function(err) {
      agregarMensaje('OFFLINE', 'iris');
      esc('ERROR AL CONTACTAR /orchestrator/route: ' + err.message);
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
var efecto3d = false; // GERAM v3: modo 3D eliminado — siempre apagado.

// (El toggle 3D y su efecto de parallax fueron removidos en v3:
// "desarrollador al frente". Se conserva `efecto3d = false` porque el
// bucle de animación de abajo lo consulta; con esto la escena nunca se
// inclina y el editor es el protagonista.)

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
// runtime-status.js builds this sequence from the real local status API.
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
  input.placeholder = 'Password';

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
          error.textContent = 'Incorrect password';
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
// DESACTIVADO: /lock-status y /unlock no implementados en GERAM CORE
// OS todavía. Sin este poll, verificarLock()/mostrarPantallaBloqueo()
// nunca se llaman, así que la pantalla de bloqueo nunca se crea ni
// se dispara ningún fetch a rutas inexistentes. Funciones intactas.
// TODO: rehabilitar si se necesita post-hackathon.
// setInterval(verificarLock, 5000);
// verificarLock();

// ===================== 13. TOGGLE MODO OFFLINE MANUAL =====================
// El botón no existe en el HTML original, así que se crea por JS y se
// inserta junto a MIC/VOZ/VISTA, reusando la clase .sentido para que
// se vea igual.
var URL_MODO_OFFLINE = '/api/runtime/state';

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
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ offline_forced: forzarNuevo })
    })
      .then(function(res) {
        if (!res.ok) { throw new Error('HTTP ' + res.status); }
        return res.json();
      })
      .then(function(d) {
        btn.classList.toggle('activo', d.offline_forced);
        esc(d.offline_forced ? 'MODO OFFLINE FORZADO: USANDO OLLAMA' : 'MODO OFFLINE DESACTIVADO: USANDO EL PROVEEDOR CONFIGURADO');
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
      btn.classList.toggle('activo', d.offline_forced);
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

// GERAM v3: el toggle Día/Noche fue eliminado. La paleta oscura es
// permanente (ver style.css: el <body> ya no recibe nunca .modo-dia).
// El núcleo (sección 15) toma su color de la variable CSS --principal,
// así que sigue funcionando sin necesidad del evento 'geram:tema-cambiado'.

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
// DESACTIVADO: /recordatorios/avisos no implementado en GERAM CORE OS
// todavía. Función intacta, solo se deja de invocar.
// TODO: rehabilitar si se necesita post-hackathon.
// setInterval(revisarAvisosRecordatorios, 20000);
// revisarAvisosRecordatorios();

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
// DESACTIVADO: /proactividad/avisos no implementado en GERAM CORE OS
// todavía. Función intacta, solo se deja de invocar.
// TODO: rehabilitar si se necesita post-hackathon.
// setInterval(revisarAvisosProactividad, 20000);
// revisarAvisosProactividad();

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


// ===================== 19. CONTROL POR GESTOS (Fase H) =====================
// gesture_agent.py hace TODO en Python: detecta el gesto Y ejecuta la
// acción real server-side (control_agent.py/lock_agent.py) — este
// archivo ya NO decide qué hacer con cada gesto, solo hace polling
// para el toast visual y las 2 cosas que son exclusivas del navegador:
// click en el botón MIC (el MediaRecorder vive en el DOM, Python no
// puede tocarlo) y mostrar/hablar el resultado de SHAKA (screenshot +
// Gemini Vision, la única acción de gestos que gasta tokens).
var URL_GESTOS_INICIAR = '/gestos/iniciar';
var URL_GESTOS_DETENER = '/gestos/detener';
var URL_GESTOS_ACTUAL = '/gestos/actual';
var URL_CONTROL_ESTADO_UI = '/control/estado-ui';

var btnGestosEl = $('#btn-gestos');
var toastGestoEl = $('#toastGesto');
var pollGestosId = null;
var toastGestoTimeoutId = null;

// Qué hace cada gesto — se usa para el toast (nombre + acción)
// además del nombre crudo. Los gestos que no aparecen acá (click,
// scroll_*, modo_mouse_*) ya se explican solos en el toast con su
// nombre, no necesitan descripción aparte.
var DESCRIPCION_GESTO = {
  mano_abierta: 'turns the microphone on',
  'puño': 'turns the microphone off',
  pulgar_arriba: 'volume up',
  pulgar_abajo: 'volume down',
  swipe: 'expands / collapses the panel',
  wave: 'emergency lock',
  modo_mouse_activado: 'mouse mode on',
  modo_mouse_salir: 'mouse mode off',
  shaka: 'analysing your screen with Gemini Vision…',
  rock: 'play / pause',
  tres_dedos: 'next tab',
  pinch: 'mutes / unmutes audio',
  toggle_dia_noche: 'toggles day / night mode',
  activar_mic: 'turns the microphone on'
};

function mostrarToastGesto(nombre) {
  var descripcion = DESCRIPCION_GESTO[nombre];
  toastGestoEl.textContent = nombre.replace(/_/g, ' ').toUpperCase() + (descripcion ? ' — ' + descripcion : '');
  toastGestoEl.classList.add('visible');
  clearTimeout(toastGestoTimeoutId);
  toastGestoTimeoutId = setTimeout(function() { toastGestoEl.classList.remove('visible'); }, 1500);
}

function ejecutarAccionGesto(gesto, resultado) {
  mostrarToastGesto(gesto);
  esc('GESTO DETECTADO: ' + gesto.toUpperCase());

  // mano_abierta/activar_mic (índice quieto 3s) / puño: el click real
  // del botón MIC solo puede pasar acá — Python no controla el
  // MediaRecorder del navegador (ver control_agent.activar_mic, que es
  // solo un puente liviano).
  if (gesto === 'mano_abierta' || gesto === 'activar_mic') {
    if (!micGrabando) { btnMicEl.click(); }
  } else if (gesto === 'puño') {
    if (micGrabando) { btnMicEl.click(); }
  } else if (gesto === 'swipe') {
    // SWIPE reusa la misma clase 'expandido' que el modo hablando (ver
    // sección 6/18) como un toggle manual aparte — a propósito NO se
    // sincroniza por poll (ver sincronizarEstadoUI más abajo, que
    // deliberadamente NO toca 'expandido' para no pelearse con el
    // auto-entra/auto-sale de cuando IRIS habla).
    document.body.classList.toggle('expandido');
  }

  // 'resultado' solo viene poblado para SHAKA (texto de Gemini Vision,
  // puede tardar y llega en un poll posterior) y para el mensaje fijo
  // de activar_mic por índice quieto ("Te escucho, jefe.") — el resto
  // de gestos ya ejecutó su acción real del lado de Python.
  if (resultado) {
    agregarMensaje(resultado, 'iris');
    reproducirRespuesta(resultado);
  }
}

function pollearGestoActual() {
  fetch(URL_GESTOS_ACTUAL)
    .then(function(res) { return res.json(); })
    .then(function(d) { if (d.gesto) { ejecutarAccionGesto(d.gesto, d.resultado); } })
    .catch(function(err) { esc('ERROR AL LEER /gestos/actual: ' + err.message); });
}

// modo_dia/voz_activa/gestos_activo se sincronizan por poll (pueden
// cambiar desde cualquier canal — gesto, voz/texto, Telegram — sin que
// este HUD se entere de otra forma). 'expandido' NO se incluye a
// propósito: entra/sale sola junto con el estado "hablando" (sección
// 6/18) y forzarla cada 2s pelearía con eso — el SWIPE la togglea
// directo arriba, sin pasar por acá. mic_solicitud es "leer y limpia"
// (no un estado persistente que comparar): si trae "activar"/
// "desactivar" se simula el click en el botón MIC UNA sola vez, igual
// que ya hace ejecutarAccionGesto() con el gesto de mano abierta (el
// MediaRecorder real vive en el navegador, Python no lo controla
// directo).
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

      if (btnGestosEl && d.gestos_activo !== btnGestosEl.classList.contains('activo')) {
        btnGestosEl.classList.toggle('activo', d.gestos_activo);
        aplicarEstadoGestos(d.gestos_activo);
      }

      if (d.mic_solicitud === 'activar' && !micGrabando) {
        btnMicEl.click();
      } else if (d.mic_solicitud === 'desactivar' && micGrabando) {
        btnMicEl.click();
      }
    })
    .catch(function() { /* silencioso: no es crítico, /stats ya avisa si el server está caído */ });
}
// DESACTIVADO: /control/estado-ui no implementado en GERAM CORE OS
// todavía. Función intacta, solo se deja de invocar.
// TODO: rehabilitar si se necesita post-hackathon.
// setInterval(sincronizarEstadoUI, 2000);
// sincronizarEstadoUI();

// Efectos secundarios de "gestos encendidos/apagados" (arrancar/parar
// el polling de toasts) separados de toggleGestos para que
// sincronizarEstadoUI también los pueda aplicar cuando GESTOS se
// activó desde otro canal (voz/texto/Telegram) y no desde este click
// — ahí el POST a /gestos/iniciar|detener ya se hizo del lado del
// director, solo falta que ESTE navegador reaccione.
function aplicarEstadoGestos(activo) {
  if (activo) {
    esc('GESTOS ACTIVADOS');
    // DESACTIVADO: /gestos/actual no implementado en GERAM CORE OS
    // todavía. Poll comentado (no borrado) para no generar 404 en
    // consola; el toggle visual de GESTOS sigue funcionando.
    // TODO: rehabilitar si se necesita post-hackathon.
    // if (!pollGestosId) { pollGestosId = setInterval(pollearGestoActual, 300); }
  } else {
    esc('GESTOS DESACTIVADOS');
    clearInterval(pollGestosId);
    pollGestosId = null;
  }
}

function toggleGestos(activar) {
  var url = activar ? URL_GESTOS_INICIAR : URL_GESTOS_DETENER;
  fetch(url, { method: 'POST' })
    .then(function(res) {
      if (!res.ok) { return res.json().then(function(d) { throw new Error(d.detail || ('HTTP ' + res.status)); }); }
      return res.json();
    })
    .then(function() { aplicarEstadoGestos(activar); })
    .catch(function(err) {
      esc('ERROR AL ' + (activar ? 'ACTIVAR' : 'DESACTIVAR') + ' GESTOS: ' + err.message);
      // El toggle visual ya se aplicó en el handler genérico de botonesSentido
      // (sección 8) antes de llegar acá — si el backend no pudo (ej. cámara
      // ocupada por VISTA/observador), hay que revertirlo para que el botón
      // no quede "prendido" mintiendo sobre el estado real.
      if (activar) { btnGestosEl.classList.remove('activo'); }
    });
}

// ===================== 20. DASHBOARD DE AGENTES =====================
// The Core scans the trusted bundled directory without importing modules and
// merges portable Agent Factory definitions. Enable/disable state is stored in
// the current OS user's GERAM data directory.
var AGENT_ROSTER_URL = '/api/agents/roster';

function prettificarNombreAgente(nombre) {
  var limpio = nombre.replace(/_agent$/, '').replace(/_/g, ' ');
  return limpio.toUpperCase();
}

var dashboardGrid = $('#dashboardGrid');
var dashboardConteo = $('#dashboardConteo');

function _tarjetaAgente(agente) {
  var card = document.createElement('div');
  card.className = 'dashboard-card' + (!agente.enabled ? ' suspendido' : '');

  var dot = document.createElement('span');
  dot.className = 'dot';
  if (!agente.enabled) { dot.style.background = '#888'; dot.style.boxShadow = 'none'; }

  var texto = document.createElement('span');
  texto.className = 'dashboard-card-nombre';
  texto.style.flex = '1';
  texto.textContent = agente.etiqueta || prettificarNombreAgente(agente.nombre);

  card.appendChild(dot);
  card.appendChild(texto);

  var statusBadge = document.createElement('span');
  statusBadge.className = 'dashboard-card-badge';
  statusBadge.textContent = agente.loaded ? 'loaded' : (agente.origin || agente.status || 'available');
  statusBadge.title = agente.loaded ? 'Module loaded in this process' : 'Available for this user';
  card.appendChild(statusBadge);

  if (agente.nucleo) {
    var badge = document.createElement('span');
    badge.className = 'dashboard-card-badge core';
    badge.textContent = 'core';
    badge.title = 'Core agent — always on';
    card.appendChild(badge);
  } else {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dashboard-card-toggle ' + (agente.enabled ? 'is-on' : 'is-off');
    btn.textContent = agente.enabled ? 'Disable' : 'Enable';
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      btn.disabled = true;
      btn.textContent = '…';
      toggleAgente(agente.id, agente.enabled);
    });
    card.appendChild(btn);
  }
  return card;
}

function renderDashboardAgentes(agentes) {
  if (!dashboardGrid) { return; }
  dashboardGrid.innerHTML = '';
  var activos = 0;
  agentes.forEach(function(agente) {
    if (agente.enabled) { activos++; }
    dashboardGrid.appendChild(_tarjetaAgente(agente));
  });
  if (dashboardConteo) { dashboardConteo.textContent = activos + '/' + agentes.length; }
}

function _mensajeDashboard(texto) {
  if (!dashboardGrid) { return; }
  dashboardGrid.innerHTML = '';
  var p = document.createElement('p');
  p.className = 'dashboard-hint';
  p.textContent = texto;
  dashboardGrid.appendChild(p);
}

function cargarAgentes() {
  if (!dashboardGrid) { return; }
  dashboardGrid.setAttribute('aria-busy', 'true');
  fetch(AGENT_ROSTER_URL, { cache: 'no-store' })
    .then(function(res) { if (!res.ok) { throw new Error('HTTP ' + res.status); } return res.json(); })
    .then(function(d) { renderDashboardAgentes(d.agents || []); })
    .catch(function() {
      _mensajeDashboard('The local agent roster could not be loaded.');
      if (dashboardConteo) { dashboardConteo.textContent = '0/0'; }
    })
    .then(function() { dashboardGrid.setAttribute('aria-busy', 'false'); });
}

var TRUST_METRICS_URL = '/api/ares/proposals/metrics';
function cargarConfianza() {
  fetch(TRUST_METRICS_URL, { cache: 'no-store' })
    .then(function(res) { return res.ok ? res.json() : null; })
    .then(function(d) {
      if (!d) { return; }
      var set = function(id, val) {
        var el = document.getElementById(id);
        if (el) { el.textContent = (val === null || val === undefined) ? '0' : val; }
      };
      set('trustProposals', d.proposals_total);
      set('trustApplied', d.applied);
      set('trustConflicts', d.conflicts);
      set('trustNoApproval', d.writes_without_approval);
    })
    .catch(function() {});
}

function toggleAgente(agentId, estabaHabilitado) {
  fetch(AGENT_ROSTER_URL + '/' + encodeURIComponent(agentId), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: !estabaHabilitado })
  })
    .then(function(res) { if (!res.ok) { throw new Error('HTTP ' + res.status); } return res.json(); })
    .then(function() { cargarAgentes(); })
    .catch(function() { cargarAgentes(); });
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
    cargarAgentes();
    cargarConfianza();
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

// ===================== 22. SETTINGS PANEL =====================
// The provider catalog is authoritative. Saved sensitive values arrive masked
// and are posted only when the user replaces them with a different value.
(function() {
  var overlay = $('#configPanel');
  var btnAbrir = $('#toggleConfig');
  var btnCerrar = $('#configCerrar');
  var fondo = $('#configFondo');
  var cuerpo = $('#configCuerpo');
  var estadoEl = $('#configEstado');
  var btnGuardar = $('#configGuardar');
  if (!overlay || !btnAbrir || !cuerpo || !btnGuardar) { return; }

  var ROLES = [
    {
      id: 'iris',
      label: 'I.R.I.S.',
      providerField: 'IRIS_PROVIDER',
      modelField: 'IRIS_MODEL',
      fallbackField: 'IRIS_FALLBACK_PROVIDER'
    },
    {
      id: 'ares',
      label: 'A.R.E.S.',
      providerField: 'ARES_PROVIDER',
      modelField: 'ARES_MODEL',
      fallbackField: 'ARES_FALLBACK_PROVIDER'
    }
  ];

  // Integraciones agrupadas por servicio: cada grupo es un item del sidebar
  // externo (debajo de "API IA"). Un grupo con `info` en vez de `campos` es
  // solo informativo (p.ej. Google Calendar, que usa credenciales OAuth por
  // archivo, no una API key en este panel).
  var GRUPOS_INTEGRACIONES = [
    { id: 'notion', label: 'Notion', campos: [
      { field: 'NOTION_API_KEY', label: 'Notion API key' },
      { field: 'NOTION_DATABASE_ID', label: 'Notion database ID' }
    ] },
    { id: 'telegram', label: 'Telegram', campos: [
      { field: 'TELEGRAM_BOT_TOKEN', label: 'Telegram bot token' },
      { field: 'TELEGRAM_ALLOWED_CHAT_IDS', label: 'Telegram allowed chat IDs' }
    ] },
    { id: 'supabase', label: 'Supabase', campos: [
      { field: 'SUPABASE_URL', label: 'Supabase URL' },
      { field: 'SUPABASE_KEY', label: 'Supabase key' }
    ] },
    { id: 'google-calendar', label: 'Google Calendar', campos: [
      { field: 'GOOGLE_CALENDAR_ACCESS_TOKEN', label: 'OAuth access token' },
      { field: 'GOOGLE_CALENDAR_ID', label: 'Calendar ID' },
      { field: 'GOOGLE_ACCOUNT_EMAIL', label: 'Google account email' }
    ] },
    { id: 'spotify', label: 'Spotify', campos: [
      { field: 'SPOTIFY_ACCESS_TOKEN', label: 'Spotify access token' }
    ] },
    { id: 'obsidian', label: 'Obsidian', campos: [
      { field: 'OBSIDIAN_VAULT_PATH', label: 'Obsidian vault path' }
    ] }
  ];

  // Lista plana derivada, para cargar/guardar valores por campo sin cambios.
  var CAMPOS_INTEGRACIONES = [];
  GRUPOS_INTEGRACIONES.forEach(function(grupo) {
    (grupo.campos || []).forEach(function(campo) { CAMPOS_INTEGRACIONES.push(campo); });
  });

  var catalogo = [];
  var catalogoPorId = {};
  var memoriaModelos = { iris: {}, ares: {} };
  var cargando = false;
  var guardando = false;
  var configuracionLista = false;
  var catalogoListo = false;
  var credencialesPool = [];
  var poolGuardando = false;

  function crearElemento(tag, clase, texto) {
    var elemento = document.createElement(tag);
    if (clase) { elemento.className = clase; }
    if (typeof texto === 'string') { elemento.textContent = texto; }
    return elemento;
  }

  function crearSeccion(id, titulo, ayuda) {
    var seccion = crearElemento('section', 'config-seccion');
    seccion.id = id;

    var encabezado = crearElemento('h3', 'config-seccion-titulo', titulo);
    seccion.appendChild(encabezado);

    if (ayuda) {
      seccion.appendChild(crearElemento('p', 'config-seccion-ayuda', ayuda));
    }

    var error = crearElemento('p', 'config-seccion-error');
    error.id = id + 'Error';
    error.setAttribute('role', 'alert');
    seccion.appendChild(error);

    var contenido = crearElemento('div', 'config-seccion-contenido');
    seccion.appendChild(contenido);
    cuerpo.appendChild(seccion);
    return { seccion: seccion, contenido: contenido, error: error };
  }

  function crearErrorCampo(field) {
    var error = crearElemento('p', 'config-campo-error');
    error.id = 'configError' + field;
    error.dataset.errorCampo = field;
    error.setAttribute('role', 'alert');
    return error;
  }

  function crearControlRol(role, field, labelText, type) {
    var zona = crearElemento('div', 'config-control');
    var id = 'config' + field;
    var label = crearElemento('label', '', labelText);
    label.htmlFor = id;

    var control;
    if (type === 'select') {
      control = crearElemento('select', 'config-select');
    } else {
      control = crearElemento('input', 'config-input');
      control.type = 'text';
      control.autocomplete = 'off';
      control.spellcheck = false;
    }

    control.id = id;
    control.dataset.campo = field;
    control.dataset.role = role.id;
    control.dataset.original = '';
    control.disabled = true;

    var error = crearErrorCampo(field);
    control.setAttribute('aria-describedby', error.id);
    zona.appendChild(label);
    zona.appendChild(control);
    zona.appendChild(error);
    return zona;
  }

  function crearTarjetaRol(role) {
    var tarjeta = crearElemento('fieldset', 'config-rol');
    tarjeta.dataset.roleCard = role.id;
    tarjeta.appendChild(crearElemento('legend', '', role.label));
    tarjeta.appendChild(
      crearControlRol(role, role.providerField, 'Primary provider', 'select')
    );
    tarjeta.appendChild(
      crearControlRol(role, role.modelField, 'Model', 'input')
    );
    tarjeta.appendChild(
      crearControlRol(role, role.fallbackField, 'Fallback provider', 'select')
    );

    var advertencia = crearElemento('p', 'config-advertencia');
    advertencia.dataset.roleWarning = role.id;
    advertencia.setAttribute('aria-live', 'polite');
    tarjeta.appendChild(advertencia);
    return tarjeta;
  }

  function mostrarNotaCampo(input, mensaje) {
    var error = cuerpo.querySelector('[data-error-campo="' + input.dataset.campo + '"]');
    if (!error) { return; }
    error.textContent = mensaje;
    error.classList.add('activo');
  }

  function ocultarNotaCampo(input) {
    input.classList.remove('invalido');
    input.removeAttribute('aria-invalid');
    var error = cuerpo.querySelector('[data-error-campo="' + input.dataset.campo + '"]');
    if (!error) { return; }
    error.textContent = '';
    error.classList.remove('activo');
  }

  function crearCampoSeguro(definicion) {
    var fila = crearElemento('div', 'config-campo');
    var id = 'config' + definicion.field;
    var label = crearElemento('label', '', definicion.label);
    label.htmlFor = id;

    var zona = crearElemento('div', 'config-input-zona');
    var input = crearElemento('input', 'config-input');
    input.id = id;
    input.type = 'password';
    input.dataset.campo = definicion.field;
    input.dataset.original = '';
    input.dataset.savedMasked = 'false';
    input.autocomplete = 'new-password';
    input.spellcheck = false;
    input.disabled = true;

    var error = crearErrorCampo(definicion.field);
    input.setAttribute('aria-describedby', error.id);

    var btnVer = crearElemento('button', 'config-mostrar', 'VER');
    btnVer.type = 'button';
    btnVer.disabled = true;
    btnVer.setAttribute('aria-controls', id);
    btnVer.setAttribute('aria-label', 'Mostrar valor nuevo de ' + definicion.label);
    btnVer.addEventListener('click', function() {
      var esValorGuardado = input.dataset.savedMasked === 'true' &&
        input.value === input.dataset.original;
      if (esValorGuardado) {
        input.type = 'password';
        btnVer.textContent = 'VER';
        mostrarNotaCampo(input, 'Saved values stay masked. Type a replacement to inspect it.');
        return;
      }
      ocultarNotaCampo(input);
      var mostrando = input.type === 'text';
      input.type = mostrando ? 'password' : 'text';
      btnVer.textContent = mostrando ? 'VER' : 'OCULTAR';
    });

    input.addEventListener('input', function() {
      ocultarNotaCampo(input);
      if (input.value === input.dataset.original) {
        input.type = 'password';
        btnVer.textContent = 'VER';
      }
    });

    input.addEventListener('focus', function() {
      if (input.dataset.savedMasked === 'true' && input.value === input.dataset.original) {
        input.select();
      }
    });

    zona.appendChild(input);
    zona.appendChild(btnVer);
    fila.appendChild(label);
    fila.appendChild(zona);
    fila.appendChild(error);
    return fila;
  }

  function construirPanel() {
    // Personal settings are authored in index.html for accessible labels.
    // Preserve that live section (and its listeners) while rebuilding the
    // provider-driven pages around it.
    var geramSettingsSection = $('#configGeramSettings');
    if (geramSettingsSection && geramSettingsSection.parentNode) {
      geramSettingsSection.parentNode.removeChild(geramSettingsSection);
    }
    cuerpo.innerHTML = '';
    catalogo = [];
    catalogoPorId = {};
    memoriaModelos = { iris: {}, ares: {} };
    catalogoListo = false;
    configuracionLista = false;
    credencialesPool = [];

    var seccionOverview = crearSeccion(
      'configAiOverview',
      'AI provider directory',
      'Choose a provider, then assign it to I.R.I.S. or A.R.E.S. Local providers do not require an API key.'
    );
    var requiredCard = crearElemento('div', 'config-required-card');
    requiredCard.id = 'configAiRequired';
    var requiredCopy = crearElemento('div');
    requiredCopy.appendChild(crearElemento('strong', '', 'At least one AI provider is required'));
    requiredCopy.appendChild(crearElemento('p', '', 'Configure a role with an available provider before using chat or code proposals.'));
    requiredCard.appendChild(requiredCopy);
    var requiredStatus = crearElemento('span', 'config-required-status', 'Review roles');
    requiredStatus.id = 'configAiRequiredStatus';
    requiredCard.appendChild(requiredStatus);
    seccionOverview.contenido.appendChild(requiredCard);
    var directory = crearElemento('div', 'config-provider-directory');
    directory.id = 'configProviderDirectory';
    seccionOverview.contenido.appendChild(directory);

    var seccionRoles = crearSeccion(
      'configAiRoles',
      'AI Roles',
      'I.R.I.S. and A.R.E.S. are roles. Each role can use a different AI provider.'
    );
    var rolesGrid = crearElemento('div', 'config-roles-grid');
    ROLES.forEach(function(role) {
      rolesGrid.appendChild(crearTarjetaRol(role));
    });
    seccionRoles.contenido.appendChild(rolesGrid);

    var seccionCredenciales = crearSeccion(
      'configProviderCredentials',
      'Provider Credentials',
      'Credential pools improve resilience and project separation. They do not increase provider limits or bypass billing or terms.'
    );
    var contenedorPools = crearElemento('div', 'config-pools');
    contenedorPools.id = 'configCredentialPools';
    contenedorPools.appendChild(
      crearElemento('p', 'config-pool-vacio', 'Loading credential pools...')
    );
    seccionCredenciales.contenido.appendChild(contenedorPools);

    var seccionIntegraciones = crearSeccion(
      'configIntegrations',
      'Integrations',
      'Connect apps and data sources. Credentials stay masked and are stored only on this device.'
    );
    GRUPOS_INTEGRACIONES.forEach(function(grupo) {
      var bloque = crearElemento('div', 'config-integracion');
      bloque.dataset.integration = grupo.id;
      var estadoIntegracion = crearElemento('p', 'config-seccion-ayuda', 'Connection state: checking…');
      estadoIntegracion.id = 'configIntegrationStatus-' + grupo.id;
      estadoIntegracion.setAttribute('role', 'status');
      bloque.appendChild(estadoIntegracion);
      if (grupo.info) {
        bloque.appendChild(crearElemento('p', 'config-seccion-ayuda', grupo.info));
      } else {
        var grid = crearElemento('div', 'config-grid');
        (grupo.campos || []).forEach(function(definicion) {
          grid.appendChild(crearCampoSeguro(definicion));
        });
        bloque.appendChild(grid);
      }
      seccionIntegraciones.contenido.appendChild(bloque);
    });

    if (geramSettingsSection) { cuerpo.appendChild(geramSettingsSection); }

    conectarEventosRoles();
  }

  function obtenerControl(field) {
    return cuerpo.querySelector('[data-campo="' + field + '"]');
  }

  function obtenerSpec(providerId) {
    return catalogoPorId[providerId] || null;
  }

  function opcionExiste(select, value) {
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].value === value) { return true; }
    }
    return false;
  }

  function mostrarAdvertenciaRol(roleId, mensaje) {
    var advertencia = cuerpo.querySelector('[data-role-warning="' + roleId + '"]');
    if (advertencia) { advertencia.textContent = mensaje || ''; }
  }

  function actualizarOpcionesFallback(role) {
    var primary = obtenerControl(role.providerField);
    var fallback = obtenerControl(role.fallbackField);
    if (!primary || !fallback) { return; }

    for (var i = 0; i < fallback.options.length; i++) {
      var option = fallback.options[i];
      if (!option.value) {
        option.disabled = false;
        continue;
      }
      var spec = obtenerSpec(option.value);
      option.disabled = !spec || !spec.implementation_available ||
        option.value === primary.value;
    }
  }

  function manejarCambioProveedor(role) {
    var primary = obtenerControl(role.providerField);
    var model = obtenerControl(role.modelField);
    var fallback = obtenerControl(role.fallbackField);
    if (!primary || !model || !fallback) { return; }

    ocultarNotaCampo(primary);
    var anterior = primary.dataset.previousProvider || primary.dataset.original || '';
    var nuevo = primary.value;
    var modeloActual = model.value;
    if (anterior) { memoriaModelos[role.id][anterior] = modeloActual; }

    var specAnterior = obtenerSpec(anterior);
    var specNuevo = obtenerSpec(nuevo);
    if (!modeloActual.trim() ||
        (specAnterior && modeloActual === specAnterior.default_model)) {
      model.value = memoriaModelos[role.id][nuevo] ||
        (specNuevo ? specNuevo.default_model : modeloActual);
    }
    primary.dataset.previousProvider = nuevo;

    if (fallback.value && fallback.value === nuevo) {
      fallback.value = '';
      mostrarAdvertenciaRol(
        role.id,
        'Fallback cleared because it matched the new primary provider.'
      );
    } else {
      mostrarAdvertenciaRol(role.id, '');
    }
    actualizarOpcionesFallback(role);
    actualizarResumenAi();
  }

  function conectarEventosRoles() {
    ROLES.forEach(function(role) {
      var primary = obtenerControl(role.providerField);
      var model = obtenerControl(role.modelField);
      var fallback = obtenerControl(role.fallbackField);

      primary.addEventListener('change', function() {
        manejarCambioProveedor(role);
      });
      fallback.addEventListener('change', function() {
        ocultarNotaCampo(fallback);
        mostrarAdvertenciaRol(role.id, '');
      });
      model.addEventListener('input', function() {
        ocultarNotaCampo(model);
        if (primary.value) {
          memoriaModelos[role.id][primary.value] = model.value;
        }
      });
    });
  }

  function normalizarCatalogo(data) {
    if (!Array.isArray(data)) { throw new Error('invalid_catalog'); }
    var resultado = [];
    var vistos = {};

    data.forEach(function(item) {
      if (!item || typeof item.provider_id !== 'string' ||
          typeof item.display_label !== 'string' ||
          typeof item.default_model !== 'string') {
        return;
      }
      var providerId = item.provider_id.trim().toLowerCase();
      if (!providerId || vistos[providerId]) { return; }
      vistos[providerId] = true;
      resultado.push({
        provider_id: providerId,
        display_label: item.display_label,
        default_model: item.default_model,
        requires_api_key: item.requires_api_key === true,
        implementation_available: item.implementation_available === true
      });
    });

    if (!resultado.length) { throw new Error('empty_catalog'); }
    return resultado;
  }

  function llenarSelectsCatalogo(data) {
    catalogo = normalizarCatalogo(data);
    catalogoPorId = {};
    catalogo.forEach(function(spec) { catalogoPorId[spec.provider_id] = spec; });
    catalogoListo = true;
    renderizarDirectorioProveedores();

    ROLES.forEach(function(role) {
      var primary = obtenerControl(role.providerField);
      var fallback = obtenerControl(role.fallbackField);
      primary.innerHTML = '';
      fallback.innerHTML = '';

      var none = crearElemento('option', '', 'None');
      none.value = '';
      fallback.appendChild(none);

      catalogo.forEach(function(spec) {
        var suffix = spec.implementation_available ? '' : ' — Coming soon';
        var primaryOption = crearElemento(
          'option',
          '',
          spec.display_label + suffix
        );
        primaryOption.value = spec.provider_id;
        primaryOption.disabled = !spec.implementation_available;
        primary.appendChild(primaryOption);

        var fallbackOption = primaryOption.cloneNode(true);
        fallback.appendChild(fallbackOption);
      });

      primary.disabled = false;
      fallback.disabled = false;
      obtenerControl(role.modelField).disabled = false;
    });
  }

  function providerHint(spec) {
    if (spec.provider_id === 'ollama') { return 'Local · no API key'; }
    if (spec.provider_id === 'gemini' || spec.provider_id === 'groq') {
      return 'Recommended · free tier';
    }
    return spec.requires_api_key ? 'Cloud · API key required' : 'No API key required';
  }

  function renderizarDirectorioProveedores() {
    var directory = $('#configProviderDirectory');
    if (!directory) { return; }
    directory.textContent = '';
    catalogo.forEach(function(spec) {
      var card = crearElemento('button', 'config-provider-card');
      card.type = 'button';
      card.dataset.providerId = spec.provider_id;
      card.disabled = !spec.implementation_available;
      if (!spec.implementation_available) { card.classList.add('no-disponible'); }
      card.appendChild(crearElemento('span', 'config-provider-logo', spec.display_label.slice(0, 2).toUpperCase()));
      var copy = crearElemento('span', 'config-provider-copy');
      copy.appendChild(crearElemento('strong', '', spec.display_label));
      copy.appendChild(crearElemento('small', '', spec.default_model));
      card.appendChild(copy);
      var hint = providerHint(spec);
      var badge = crearElemento(
        'span',
        'config-provider-badge' + (hint.indexOf('Recommended') === 0 ? ' recomendado' : ''),
        hint
      );
      card.appendChild(badge);
      card.addEventListener('click', function() {
        if (!spec.implementation_available) { return; }
        navConfig.vista = 'ai';
        navConfig.proveedor = spec.requires_api_key ? spec.provider_id : '__roles__';
        aplicarVistaConfig();
      });
      directory.appendChild(card);
    });
  }

  function actualizarResumenAi() {
    var iris = obtenerControl('IRIS_PROVIDER');
    var ares = obtenerControl('ARES_PROVIDER');
    var configured = Boolean((iris && iris.value) || (ares && ares.value));
    var card = $('#configAiRequired');
    var status = $('#configAiRequiredStatus');
    if (card) { card.classList.toggle('completo', configured); }
    if (status) { status.textContent = configured ? 'Configured' : 'Review roles'; }
    var providers = cuerpo.querySelectorAll('#configProviderDirectory [data-provider-id]');
    Array.prototype.forEach.call(providers, function(providerCard) {
      providerCard.classList.toggle(
        'seleccionado',
        Boolean((iris && iris.value === providerCard.dataset.providerId) ||
          (ares && ares.value === providerCard.dataset.providerId))
      );
    });
  }

  function normalizarCredencialesPool(data) {
    if (!data || !Array.isArray(data.credentials)) {
      throw new Error('invalid_credential_pool');
    }
    var estadosPermitidos = {
      healthy: true,
      disabled: true,
      invalid: true,
      cooldown: true,
      daily_cap_reached: true
    };
    return data.credentials.map(function(item) {
      if (!item || typeof item.credential_id !== 'string' ||
          !/^[0-9a-f-]{36}$/i.test(item.credential_id) ||
          typeof item.provider !== 'string' ||
          typeof item.label !== 'string' ||
          typeof item.fingerprint !== 'string' ||
          typeof item.health_status !== 'string' ||
          !estadosPermitidos[item.health_status]) {
        throw new Error('invalid_credential_metadata');
      }
      return {
        credential_id: item.credential_id,
        provider: item.provider.toLowerCase(),
        label: item.label,
        enabled: item.enabled === true,
        priority: Number.isInteger(item.priority) ? item.priority : 100,
        created_at: typeof item.created_at === 'string' ? item.created_at : '',
        last_used_at: typeof item.last_used_at === 'string' ? item.last_used_at : '',
        last_success_at: typeof item.last_success_at === 'string' ? item.last_success_at : '',
        last_failure_at: typeof item.last_failure_at === 'string' ? item.last_failure_at : '',
        fingerprint: /^fp_[0-9a-f]{16}$/i.test(item.fingerprint) ?
          item.fingerprint : 'unavailable',
        failure_count: Number.isInteger(item.failure_count) ? item.failure_count : 0,
        cooldown_until: typeof item.cooldown_until === 'string' ? item.cooldown_until : '',
        invalid: item.invalid === true,
        daily_request_cap: Number.isInteger(item.daily_request_cap) ?
          item.daily_request_cap : null,
        daily_request_count: Number.isInteger(item.daily_request_count) ?
          item.daily_request_count : 0,
        health_status: item.health_status
      };
    });
  }

  function textoEstadoPool(estado) {
    var textos = {
      healthy: 'Healthy',
      disabled: 'Disabled',
      invalid: 'Needs replacement',
      cooldown: 'Cooling down',
      daily_cap_reached: 'Daily cap reached'
    };
    return textos[estado] || 'Unavailable';
  }

  function mostrarErrorPool(mensaje) {
    var error = $('#configProviderCredentialsError');
    if (!error) { return; }
    error.textContent = mensaje || '';
    error.classList.toggle('activo', Boolean(mensaje));
  }

  function establecerPoolOcupado(ocupado) {
    poolGuardando = ocupado;
    var seccion = $('#configProviderCredentials');
    if (seccion) {
      var controles = seccion.querySelectorAll('button, input');
      Array.prototype.forEach.call(controles, function(control) {
        if (ocupado) {
          control.dataset.poolDisabledBefore = control.disabled ? 'true' : 'false';
          control.disabled = true;
        } else if (typeof control.dataset.poolDisabledBefore === 'string') {
          control.disabled = control.dataset.poolDisabledBefore === 'true';
          delete control.dataset.poolDisabledBefore;
        }
      });
    }
    actualizarBotonGuardar();
  }

  function solicitarAccionPool(url, method, payload) {
    var opciones = { method: method, headers: {} };
    if (payload) {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.body = JSON.stringify(payload);
    }
    return fetch(url, opciones).then(function(response) {
      if (!response.ok) { throw new Error('credential_request_failed'); }
      return response.json().catch(function() { return {}; });
    });
  }

  function recargarCredencialesPool() {
    return solicitarJSON('/config/provider-keys').then(function(data) {
      credencialesPool = normalizarCredencialesPool(data);
      renderizarCredencialesPool();
    });
  }

  function limpiarSecretosNuevosPool() {
    var seccion = $('#configProviderCredentials');
    if (!seccion) { return; }
    var secretos = seccion.querySelectorAll('[data-pool-secret="true"]');
    Array.prototype.forEach.call(secretos, function(input) {
      input.value = '';
      input.type = 'password';
    });
  }

  function ejecutarAccionPool(crearSolicitud) {
    if (poolGuardando || cargando || guardando) { return; }
    mostrarErrorPool('');
    establecerPoolOcupado(true);
    crearSolicitud()
      .then(function() {
        limpiarSecretosNuevosPool();
        return recargarCredencialesPool();
      })
      .then(function() {
        establecerPoolOcupado(false);
      })
      .catch(function() {
        establecerPoolOcupado(false);
        mostrarErrorPool('Credential change could not be saved. Review the fields and try again.');
      });
  }

  function crearCampoPool(id, etiqueta, tipo) {
    var zona = crearElemento('div', 'config-pool-campo');
    var label = crearElemento('label', '', etiqueta);
    label.htmlFor = id;
    var input = crearElemento('input', 'config-input');
    input.id = id;
    input.type = tipo || 'text';
    input.spellcheck = false;
    zona.appendChild(label);
    zona.appendChild(input);
    return { zona: zona, input: input };
  }

  function conectarVisibilidadNueva(input, boton) {
    boton.addEventListener('click', function() {
      var mostrando = input.type === 'text';
      input.type = mostrando ? 'password' : 'text';
      boton.textContent = mostrando ? 'SHOW' : 'HIDE';
    });
  }

  function numeroPool(input, valorPredeterminado) {
    if (!input.value.trim()) { return valorPredeterminado; }
    var valor = Number(input.value);
    return Number.isInteger(valor) ? valor : NaN;
  }

  function abrirFormularioAgregar(spec, tarjeta) {
    var existente = tarjeta.querySelector('.config-pool-form');
    if (existente) { existente.remove(); }
    var form = crearElemento('form', 'config-pool-form');
    var baseId = 'poolAdd' + spec.provider_id;
    var labelField = crearCampoPool(baseId + 'Label', 'Label', 'text');
    var secretField = crearCampoPool(baseId + 'Secret', 'New API credential', 'password');
    var priorityField = crearCampoPool(baseId + 'Priority', 'Priority (lower first)', 'number');
    var capField = crearCampoPool(baseId + 'Cap', 'Daily request cap (optional)', 'number');
    labelField.input.maxLength = 80;
    labelField.input.value = spec.display_label + ' project';
    secretField.input.autocomplete = 'new-password';
    secretField.input.dataset.poolSecret = 'true';
    priorityField.input.min = '0';
    priorityField.input.max = '1000';
    priorityField.input.value = '100';
    capField.input.min = '1';

    var secretZone = crearElemento('div', 'config-input-zona');
    secretField.zona.removeChild(secretField.input);
    secretZone.appendChild(secretField.input);
    var show = crearElemento('button', 'config-mostrar', 'SHOW');
    show.type = 'button';
    show.setAttribute('aria-label', 'Show newly typed credential');
    conectarVisibilidadNueva(secretField.input, show);
    secretZone.appendChild(show);
    secretField.zona.appendChild(secretZone);

    var grid = crearElemento('div', 'config-pool-form-grid');
    grid.appendChild(labelField.zona);
    grid.appendChild(secretField.zona);
    grid.appendChild(priorityField.zona);
    grid.appendChild(capField.zona);
    form.appendChild(grid);

    var acciones = crearElemento('div', 'config-pool-acciones');
    var guardar = crearElemento('button', 'config-pool-boton principal', 'Add credential');
    guardar.type = 'submit';
    var cancelar = crearElemento('button', 'config-pool-boton', 'Cancel');
    cancelar.type = 'button';
    cancelar.addEventListener('click', function() { form.remove(); });
    acciones.appendChild(guardar);
    acciones.appendChild(cancelar);
    form.appendChild(acciones);

    form.addEventListener('submit', function(event) {
      event.preventDefault();
      var priority = numeroPool(priorityField.input, 100);
      var cap = numeroPool(capField.input, null);
      if (!labelField.input.value.trim() || !secretField.input.value ||
          Number.isNaN(priority) || Number.isNaN(cap)) {
        mostrarErrorPool('Enter a label, a complete credential, and valid numeric limits.');
        return;
      }
      var payload = {
        provider: spec.provider_id,
        label: labelField.input.value.trim(),
        secret: secretField.input.value,
        enabled: true,
        priority: priority,
        daily_request_cap: cap
      };
      ejecutarAccionPool(function() {
        return solicitarAccionPool('/config/provider-keys', 'POST', payload);
      });
    });

    tarjeta.appendChild(form);
    labelField.input.focus();
  }

  function abrirFormularioReemplazo(credencial, fila) {
    var existente = fila.querySelector('.config-pool-replace');
    if (existente) { existente.remove(); }
    var form = crearElemento('form', 'config-pool-replace');
    var id = 'poolReplace' + credencial.credential_id.replace(/-/g, '');
    var campo = crearCampoPool(id, 'Replacement credential', 'password');
    campo.input.autocomplete = 'new-password';
    campo.input.dataset.poolSecret = 'true';
    var zona = crearElemento('div', 'config-input-zona');
    campo.zona.removeChild(campo.input);
    zona.appendChild(campo.input);
    var show = crearElemento('button', 'config-mostrar', 'SHOW');
    show.type = 'button';
    show.setAttribute('aria-label', 'Show newly typed replacement credential');
    conectarVisibilidadNueva(campo.input, show);
    zona.appendChild(show);
    campo.zona.appendChild(zona);
    form.appendChild(campo.zona);

    var acciones = crearElemento('div', 'config-pool-acciones');
    var guardar = crearElemento('button', 'config-pool-boton principal', 'Replace');
    guardar.type = 'submit';
    var cancelar = crearElemento('button', 'config-pool-boton', 'Cancel');
    cancelar.type = 'button';
    cancelar.addEventListener('click', function() { form.remove(); });
    acciones.appendChild(guardar);
    acciones.appendChild(cancelar);
    form.appendChild(acciones);

    form.addEventListener('submit', function(event) {
      event.preventDefault();
      if (!campo.input.value) {
        mostrarErrorPool('Enter the complete replacement credential.');
        return;
      }
      ejecutarAccionPool(function() {
        return solicitarAccionPool(
          '/config/provider-keys/' + encodeURIComponent(credencial.credential_id),
          'PATCH',
          { secret: campo.input.value }
        );
      });
    });
    fila.appendChild(form);
    campo.input.focus();
  }

  function crearFilaCredencial(credencial) {
    var fila = crearElemento('article', 'config-pool-entry');
    var idSeguro = credencial.credential_id.replace(/-/g, '');
    var encabezado = crearElemento('div', 'config-pool-entry-header');
    encabezado.appendChild(crearElemento('strong', '', credencial.label));
    encabezado.appendChild(
      crearElemento(
        'span',
        'config-pool-status estado-' + credencial.health_status,
        textoEstadoPool(credencial.health_status)
      )
    );
    fila.appendChild(encabezado);

    var resumen = crearElemento('p', 'config-pool-meta');
    var uso = credencial.daily_request_cap === null ?
      String(credencial.daily_request_count) :
      credencial.daily_request_count + '/' + credencial.daily_request_cap;
    resumen.textContent = 'ID ' + credencial.fingerprint + ' · Today ' + uso;
    if (credencial.cooldown_until) {
      resumen.textContent += ' · Cooldown until ' + credencial.cooldown_until;
    } else if (credencial.last_success_at) {
      resumen.textContent += ' · Last success ' + credencial.last_success_at;
    }
    fila.appendChild(resumen);

    var campos = crearElemento('div', 'config-pool-entry-grid');
    var labelField = crearCampoPool('poolLabel' + idSeguro, 'Label', 'text');
    var priorityField = crearCampoPool('poolPriority' + idSeguro, 'Priority (lower first)', 'number');
    var capField = crearCampoPool('poolCap' + idSeguro, 'Daily cap', 'number');
    labelField.input.value = credencial.label;
    labelField.input.maxLength = 80;
    priorityField.input.value = String(credencial.priority);
    priorityField.input.min = '0';
    priorityField.input.max = '1000';
    capField.input.value = credencial.daily_request_cap === null ?
      '' : String(credencial.daily_request_cap);
    capField.input.min = '1';
    campos.appendChild(labelField.zona);
    campos.appendChild(priorityField.zona);
    campos.appendChild(capField.zona);
    fila.appendChild(campos);

    var acciones = crearElemento('div', 'config-pool-acciones');
    var guardar = crearElemento('button', 'config-pool-boton principal', 'Save details');
    guardar.type = 'button';
    guardar.addEventListener('click', function() {
      var priority = numeroPool(priorityField.input, 100);
      var cap = numeroPool(capField.input, null);
      if (!labelField.input.value.trim() || Number.isNaN(priority) || Number.isNaN(cap)) {
        mostrarErrorPool('Enter a label and valid numeric limits.');
        return;
      }
      ejecutarAccionPool(function() {
        return solicitarAccionPool(
          '/config/provider-keys/' + encodeURIComponent(credencial.credential_id),
          'PATCH',
          {
            label: labelField.input.value.trim(),
            priority: priority,
            daily_request_cap: cap
          }
        );
      });
    });

    var toggle = crearElemento(
      'button',
      'config-pool-boton',
      credencial.enabled ? 'Disable' : 'Enable'
    );
    toggle.type = 'button';
    toggle.disabled = credencial.invalid;
    if (credencial.invalid) {
      toggle.title = 'Replace this credential before enabling it.';
    }
    toggle.addEventListener('click', function() {
      ejecutarAccionPool(function() {
        return solicitarAccionPool(
          '/config/provider-keys/' + encodeURIComponent(credencial.credential_id),
          'PATCH',
          { enabled: !credencial.enabled }
        );
      });
    });

    var reemplazar = crearElemento('button', 'config-pool-boton', 'Replace key');
    reemplazar.type = 'button';
    reemplazar.addEventListener('click', function() {
      abrirFormularioReemplazo(credencial, fila);
    });
    var eliminar = crearElemento('button', 'config-pool-boton peligro', 'Remove');
    eliminar.type = 'button';
    eliminar.addEventListener('click', function() {
      if (!window.confirm('Remove credential "' + credencial.label + '"?')) { return; }
      ejecutarAccionPool(function() {
        return solicitarAccionPool(
          '/config/provider-keys/' + encodeURIComponent(credencial.credential_id),
          'DELETE'
        );
      });
    });

    acciones.appendChild(guardar);
    acciones.appendChild(toggle);
    acciones.appendChild(reemplazar);
    acciones.appendChild(eliminar);
    fila.appendChild(acciones);
    return fila;
  }

  function renderizarCredencialesPool() {
    var contenedor = $('#configCredentialPools');
    if (!contenedor || !catalogoListo) { return; }
    contenedor.innerHTML = '';
    catalogo.forEach(function(spec) {
      if (!spec.requires_api_key) { return; }
      var tarjeta = crearElemento('section', 'config-pool-provider');
      tarjeta.dataset.providerId = spec.provider_id;
      var encabezado = crearElemento('div', 'config-pool-provider-header');
      encabezado.appendChild(
        crearElemento('h4', 'config-pool-provider-title', spec.display_label)
      );
      var agregar = crearElemento('button', 'config-pool-boton principal', 'Add key');
      agregar.type = 'button';
      agregar.disabled = !spec.implementation_available;
      agregar.addEventListener('click', function() {
        abrirFormularioAgregar(spec, tarjeta);
      });
      encabezado.appendChild(agregar);
      tarjeta.appendChild(encabezado);

      var registros = credencialesPool.filter(function(credencial) {
        return credencial.provider === spec.provider_id;
      });
      if (!registros.length) {
        tarjeta.appendChild(
          crearElemento(
            'p',
            'config-pool-vacio',
            'No pool credentials. The legacy environment credential remains available only while this pool is empty.'
          )
        );
      } else {
        registros.forEach(function(credencial) {
          tarjeta.appendChild(crearFilaCredencial(credencial));
        });
      }
      contenedor.appendChild(tarjeta);
    });
    // El sub-sidebar de proveedores depende de este catálogo; (re)constrúyelo
    // y reaplica el filtro de tarjeta activa tras cada re-render del pool.
    construirSubnavProveedores();
    aplicarVistaConfig();
  }

  function aplicarValorSeguro(field, value) {
    var input = obtenerControl(field);
    if (!input) { return; }
    var valor = typeof value === 'string' ? value : '';
    input.value = valor;
    input.dataset.original = valor;
    input.dataset.savedMasked = valor ? 'true' : 'false';
    input.type = 'password';
    input.disabled = false;
    var boton = input.parentElement.querySelector('.config-mostrar');
    if (boton) {
      boton.textContent = 'VER';
      boton.disabled = false;
    }
  }

  function deshabilitarRole(role, disabled) {
    obtenerControl(role.providerField).disabled = disabled;
    obtenerControl(role.modelField).disabled = disabled;
    obtenerControl(role.fallbackField).disabled = disabled;
  }

  function aplicarConfiguracion(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('invalid_configuration');
    }

    ROLES.forEach(function(role) {
      var primary = obtenerControl(role.providerField);
      var model = obtenerControl(role.modelField);
      var fallback = obtenerControl(role.fallbackField);
      var primaryValue = typeof data[role.providerField] === 'string' ?
        data[role.providerField].toLowerCase() : '';
      var modelValue = typeof data[role.modelField] === 'string' ?
        data[role.modelField] : '';
      var fallbackValue = typeof data[role.fallbackField] === 'string' ?
        data[role.fallbackField].toLowerCase() : '';

      primary.dataset.original = primaryValue;
      primary.dataset.previousProvider = primaryValue;
      model.value = modelValue;
      model.dataset.original = modelValue;
      fallback.dataset.original = fallbackValue;
      if (primaryValue) { memoriaModelos[role.id][primaryValue] = modelValue; }

      if (!catalogoListo) {
        deshabilitarRole(role, true);
        return;
      }
      if (!opcionExiste(primary, primaryValue)) {
        deshabilitarRole(role, true);
        var aiError = $('#configAiRolesError');
        aiError.textContent = 'A configured provider is missing from the local catalog.';
        aiError.classList.add('activo');
        return;
      }
      if (fallbackValue && !opcionExiste(fallback, fallbackValue)) {
        deshabilitarRole(role, true);
        var fallbackError = $('#configAiRolesError');
        fallbackError.textContent = 'A configured fallback is missing from the local catalog.';
        fallbackError.classList.add('activo');
        return;
      }

      primary.value = primaryValue;
      fallback.value = fallbackValue;
      actualizarOpcionesFallback(role);
    });

    CAMPOS_INTEGRACIONES.forEach(function(definicion) {
      aplicarValorSeguro(definicion.field, data[definicion.field]);
    });
    actualizarResumenAi();
    configuracionLista = true;
  }

  function solicitarJSON(url) {
    return fetch(url, { cache: 'no-store' }).then(function(response) {
      if (!response.ok) { throw new Error('request_failed'); }
      return response.json().catch(function() {
        throw new Error('invalid_json');
      });
    });
  }

  function actualizarBotonGuardar() {
    btnGuardar.disabled = cargando || guardando || poolGuardando || !configuracionLista;
  }

  function cargarConfiguracion() {
    if (cargando || guardando || poolGuardando) { return; }
    construirPanel();
    aplicarVistaConfig();
    cargando = true;
    cuerpo.setAttribute('aria-busy', 'true');
    estadoEl.textContent = 'Loading configuration...';
    actualizarBotonGuardar();

    var providersRequest = solicitarJSON('/config/providers')
      .then(function(data) { return { ok: true, data: data }; })
      .catch(function() { return { ok: false }; });
    var keysRequest = solicitarJSON('/config/keys')
      .then(function(data) { return { ok: true, data: data }; })
      .catch(function() { return { ok: false }; });
    var poolRequest = solicitarJSON('/config/provider-keys')
      .then(function(data) { return { ok: true, data: data }; })
      .catch(function() { return { ok: false }; });

    Promise.all([providersRequest, keysRequest, poolRequest]).then(function(resultados) {
      var providerResult = resultados[0];
      var keysResult = resultados[1];
      var poolResult = resultados[2];
      var aiError = $('#configAiRolesError');
      var poolError = $('#configProviderCredentialsError');

      if (providerResult.ok) {
        try {
          llenarSelectsCatalogo(providerResult.data);
        } catch (_errorCatalogo) {
          providerResult.ok = false;
        }
      }
      if (!providerResult.ok) {
        aiError.textContent = 'Provider catalog unavailable. Other settings remain editable.';
        aiError.classList.add('activo');
      }

      if (providerResult.ok && poolResult.ok) {
        try {
          credencialesPool = normalizarCredencialesPool(poolResult.data);
          renderizarCredencialesPool();
        } catch (_errorPool) {
          poolResult.ok = false;
        }
      }
      if (!poolResult.ok || !providerResult.ok) {
        poolError.textContent = 'Credential pools are unavailable. Other settings remain editable.';
        poolError.classList.add('activo');
      }

      if (keysResult.ok) {
        try {
          aplicarConfiguracion(keysResult.data);
          estadoEl.textContent = providerResult.ok ? '' : 'AI provider catalog unavailable.';
        } catch (_errorConfiguracion) {
          configuracionLista = false;
          estadoEl.textContent = 'Could not load the local configuration.';
        }
      } else {
        configuracionLista = false;
        estadoEl.textContent = 'Could not load the local configuration.';
      }

      cargando = false;
      cuerpo.setAttribute('aria-busy', 'false');
      actualizarBotonGuardar();
    });
  }

  function recolectarCambios() {
    var cambios = {};
    var controles = cuerpo.querySelectorAll('[data-campo]');
    Array.prototype.forEach.call(controles, function(control) {
      if (control.disabled) { return; }
      var original = typeof control.dataset.original === 'string' ?
        control.dataset.original : '';
      if (control.value !== original) {
        cambios[control.dataset.campo] = control.value;
      }
    });
    return cambios;
  }

  function limpiarErroresValidacion() {
    var controles = cuerpo.querySelectorAll('[data-campo]');
    Array.prototype.forEach.call(controles, function(control) {
      ocultarNotaCampo(control);
    });
    if (catalogoListo) {
      var aiError = $('#configAiRolesError');
      aiError.textContent = '';
      aiError.classList.remove('activo');
    }
  }

  function mensajeValidacion(code) {
    var mensajes = {
      missing_provider_key: 'Add the required provider credential before saving.',
      unsupported_provider: 'Choose a provider available in the local catalog.',
      identical_primary_fallback: 'Primary and fallback providers must be different.',
      missing_model: 'Enter a model for this role.',
      invalid_model: 'Use a valid model identifier without control characters.',
      model_too_long: 'The model identifier is too long.',
      invalid_timeout: 'The provider timeout is outside the allowed range.'
    };
    return mensajes[code] || 'Review the highlighted setting.';
  }

  function extraerValidacion(data) {
    var detail = data && data.detail;
    if (!detail || Array.isArray(detail) || typeof detail !== 'object') {
      return { field: '', code: '' };
    }
    var field = typeof detail.field === 'string' &&
      /^[A-Z0-9_]+$/.test(detail.field) ? detail.field : '';
    var code = typeof detail.code === 'string' ? detail.code : '';
    return { field: field, code: code };
  }

  function procesarRespuestaGuardado(response) {
    if (response.ok) {
      return response.json().catch(function() { return {}; });
    }
    if (response.status === 422) {
      return response.json()
        .catch(function() { return null; })
        .then(function(data) {
          var error = new Error('validation_failed');
          error.validation = extraerValidacion(data);
          throw error;
        });
    }
    throw new Error('save_failed');
  }

  function mostrarErrorValidacion(validation) {
    var mensaje = mensajeValidacion(validation.code);
    var control = validation.field ? obtenerControl(validation.field) : null;
    if (control) {
      control.classList.add('invalido');
      control.setAttribute('aria-invalid', 'true');
      mostrarNotaCampo(control, mensaje);
      control.focus();
      estadoEl.textContent = 'Revisa el campo resaltado.';
      return;
    }
    var aiError = $('#configAiRolesError');
    aiError.textContent = mensaje;
    aiError.classList.add('activo');
    estadoEl.textContent = 'Check the AI Roles configuration.';
  }

  // Poll health until the existing restart flow brings the backend back.
  function esperarReinicioYRecargar() {
    var intentos = 0;
    var MAX_INTENTOS = 30;

    var intervalo = setInterval(function() {
      intentos++;
      fetch('/health', { cache: 'no-store' })
        .then(function(response) {
          if (response.ok) {
            clearInterval(intervalo);
            estadoEl.textContent = 'Backend arriba, recargando...';
            location.reload();
          }
        })
        .catch(function() {
          // The backend is expected to be temporarily unavailable while restarting.
        });

      if (intentos >= MAX_INTENTOS) {
        clearInterval(intervalo);
        guardando = false;
        estadoEl.textContent = 'ERROR: the backend did not respond again after ' + MAX_INTENTOS + 's. Revisa el log.';
        actualizarBotonGuardar();
      }
    }, 1000);
  }

  function guardarYReiniciar() {
    if (cargando || guardando || !configuracionLista) { return; }
    limpiarErroresValidacion();
    var cambios = recolectarCambios();

    if (Object.keys(cambios).length === 0) {
      estadoEl.textContent = 'No hay cambios que guardar.';
      return;
    }

    guardando = true;
    estadoEl.textContent = 'Saving...';
    actualizarBotonGuardar();

    fetch('/config/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cambios)
    })
      .then(procesarRespuestaGuardado)
      .then(function() {
        estadoEl.textContent = 'Reiniciando el backend...';
        return fetch('/config/restart', { method: 'POST' });
      })
      .then(function(response) {
        if (!response.ok) { throw new Error('restart_failed'); }
        esperarReinicioYRecargar();
      })
      .catch(function(error) {
        guardando = false;
        if (error.validation) {
          mostrarErrorValidacion(error.validation);
        } else {
          estadoEl.textContent = 'Could not save the configuration. Try again.';
        }
        actualizarBotonGuardar();
      });
  }

  // ---- Navegación: sidebar externo (API IA + integraciones) + sub-sidebar
  //      de proveedores de IA. Solo muestra/oculta secciones ya construidas;
  //      no toca la lógica de pools, guardado ni validación. ----
  var navConfig = { vista: 'ai', proveedor: '__overview__', integracion: null };

  function porId(elId) { return document.getElementById(elId); }

  function mostrarSeccionConfig(elId, visible) {
    var seccion = porId(elId);
    if (seccion) { seccion.hidden = !visible; }
  }

  function crearItemNav(clase, etiqueta, onClick) {
    var boton = crearElemento('button', clase);
    boton.type = 'button';
    boton.appendChild(crearElemento('span', 'config-nav-txt', etiqueta));
    boton.addEventListener('click', onClick);
    return boton;
  }

  function construirNavExterna() {
    var barra = porId('configSidebar');
    if (!barra) { return; }
    barra.innerHTML = '';
    barra.appendChild(crearElemento('p', 'config-nav-grupo', 'AI'));
    var itemAi = crearItemNav('config-nav-item', 'API IA', function() {
      navConfig.vista = 'ai';
      if (!navConfig.proveedor) { navConfig.proveedor = '__overview__'; }
      aplicarVistaConfig();
    });
    itemAi.dataset.nav = 'ai';
    itemAi.dataset.configView = 'ai';
    barra.appendChild(itemAi);

    barra.appendChild(crearElemento('p', 'config-nav-grupo', 'Integrations'));
    GRUPOS_INTEGRACIONES.forEach(function(grupo) {
      var item = crearItemNav('config-nav-item', grupo.label, function() {
        navConfig.vista = 'int';
        navConfig.integracion = grupo.id;
        aplicarVistaConfig();
      });
      item.dataset.nav = 'int:' + grupo.id;
      item.dataset.configView = 'integrations';
      barra.appendChild(item);
    });

    barra.appendChild(crearElemento('p', 'config-nav-grupo', 'GERAM'));
    var itemGeram = crearItemNav('config-nav-item', 'Profile & privacy', function() {
      navConfig.vista = 'geram';
      aplicarVistaConfig();
    });
    itemGeram.dataset.nav = 'geram';
    itemGeram.dataset.configView = 'geram';
    barra.appendChild(itemGeram);

    barra.appendChild(crearElemento(
      'p', 'config-sidebar-note',
      'Credentials stay masked and are stored only on this device.'
    ));
  }

  function construirSubnavProveedores() {
    var sub = porId('configSubsidebar');
    if (!sub) { return; }
    sub.innerHTML = '';
    sub.appendChild(crearElemento('p', 'config-nav-grupo', 'AI providers'));
    var itemOverview = crearItemNav('config-subnav-item', 'Provider directory', function() {
      navConfig.proveedor = '__overview__';
      aplicarVistaConfig();
    });
    itemOverview.dataset.sub = '__overview__';
    sub.appendChild(itemOverview);
    var itemRoles = crearItemNav('config-subnav-item', 'Roles (IRIS / A.R.E.S.)', function() {
      navConfig.proveedor = '__roles__';
      aplicarVistaConfig();
    });
    itemRoles.dataset.sub = '__roles__';
    sub.appendChild(itemRoles);

    catalogo.forEach(function(spec) {
      if (!spec.requires_api_key) { return; }
      var item = crearItemNav('config-subnav-item', spec.display_label, function() {
        navConfig.proveedor = spec.provider_id;
        aplicarVistaConfig();
      });
      item.dataset.sub = spec.provider_id;
      sub.appendChild(item);
    });
  }

  function actualizarActivosNav() {
    var externos = document.querySelectorAll('#configSidebar .config-nav-item');
    Array.prototype.forEach.call(externos, function(boton) {
      var activo = (navConfig.vista === 'ai' && boton.dataset.nav === 'ai') ||
        (navConfig.vista === 'int' && boton.dataset.nav === 'int:' + navConfig.integracion) ||
        (navConfig.vista === 'geram' && boton.dataset.nav === 'geram');
      boton.classList.toggle('activo', activo);
      if (activo) { boton.setAttribute('aria-current', 'page'); }
      else { boton.removeAttribute('aria-current'); }
    });
    var subs = document.querySelectorAll('#configSubsidebar .config-subnav-item');
    Array.prototype.forEach.call(subs, function(boton) {
      boton.classList.toggle(
        'activo',
        navConfig.vista === 'ai' && boton.dataset.sub === navConfig.proveedor
      );
    });
  }

  function actualizarEncabezadoNav() {
    var titulo = $('#configViewTitle');
    var descripcion = $('#configViewDescription');
    if (!titulo || !descripcion) { return; }
    if (navConfig.vista === 'int') {
      var grupo = null;
      GRUPOS_INTEGRACIONES.forEach(function(g) {
        if (g.id === navConfig.integracion) { grupo = g; }
      });
      titulo.textContent = grupo ? grupo.label : 'Integrations';
      descripcion.textContent = 'Connect this service. Credentials stay on this device.';
      return;
    }
    if (navConfig.vista === 'geram') {
      titulo.textContent = 'Profile, appearance & privacy';
      descripcion.textContent = 'Personalize GERAM and control which local paths remain blocked.';
      return;
    }
    if (navConfig.proveedor === '__overview__') {
      titulo.textContent = 'AI provider directory';
      descripcion.textContent = 'Online and local providers available to I.R.I.S. and A.R.E.S.';
      return;
    }
    if (navConfig.proveedor === '__roles__') {
      titulo.textContent = 'AI roles';
      descripcion.textContent =
        'Assign a primary and fallback AI provider to I.R.I.S. and A.R.E.S.';
      return;
    }
    var spec = obtenerSpec(navConfig.proveedor);
    titulo.textContent = spec ? spec.display_label : 'AI provider';
    descripcion.textContent =
      'Add one or more API keys. Multiple keys of the same provider rotate in a round-robin pool.';
  }

  function aplicarVistaConfig() {
    var esAi = navConfig.vista === 'ai';
    var esGeram = navConfig.vista === 'geram';
    var sub = porId('configSubsidebar');
    if (sub) { sub.hidden = !esAi; }

    var enRoles = esAi && navConfig.proveedor === '__roles__';
    var enOverview = esAi && navConfig.proveedor === '__overview__';
    var enProveedor = esAi && navConfig.proveedor &&
      navConfig.proveedor !== '__roles__' && navConfig.proveedor !== '__overview__';

    mostrarSeccionConfig('configAiOverview', enOverview);
    mostrarSeccionConfig('configAiRoles', enRoles);
    mostrarSeccionConfig('configProviderCredentials', enProveedor);
    mostrarSeccionConfig('configIntegrations', navConfig.vista === 'int');
    mostrarSeccionConfig('configGeramSettings', esGeram);
    var footer = porId('configFooter');
    if (footer) { footer.hidden = esGeram; }

    if (enProveedor) {
      var cards = document.querySelectorAll('#configCredentialPools .config-pool-provider');
      Array.prototype.forEach.call(cards, function(card) {
        card.hidden = card.dataset.providerId !== navConfig.proveedor;
      });
    }
    if (!esAi) {
      var grupos = document.querySelectorAll('#configIntegrations [data-integration]');
      Array.prototype.forEach.call(grupos, function(g) {
        g.hidden = g.dataset.integration !== navConfig.integracion;
      });
    }
    if (esGeram && window.GeramSettings && typeof window.GeramSettings.load === 'function') {
      window.GeramSettings.load();
    }
    actualizarActivosNav();
    actualizarEncabezadoNav();
  }

  function configurarNavegacion() {
    construirNavExterna();
    construirSubnavProveedores();
    aplicarVistaConfig();
  }

  function abrirConfig() {
    overlay.classList.add('activo');
    overlay.setAttribute('aria-hidden', 'false');
    btnAbrir.classList.add('activo');
    btnAbrir.setAttribute('aria-expanded', 'true');
    cargarConfiguracion();
    fetch('/api/gcs/integrations', { cache: 'no-store' })
      .then(function(response) { return response.ok ? response.json() : Promise.reject(new Error('status')); })
      .then(function(payload) {
        (payload.integrations || []).forEach(function(item) {
          var status = document.getElementById('configIntegrationStatus-' + item.id);
          if (status) { status.textContent = 'Connection state: ' + String(item.state || 'available'); }
        });
      })
      .catch(function() {
        GRUPOS_INTEGRACIONES.forEach(function(group) {
          var status = document.getElementById('configIntegrationStatus-' + group.id);
          if (status) { status.textContent = 'Connection state: unavailable'; }
        });
      });
    if (btnCerrar) { btnCerrar.focus(); }
  }

  function cerrarConfig() {
    overlay.classList.remove('activo');
    overlay.setAttribute('aria-hidden', 'true');
    btnAbrir.classList.remove('activo');
    btnAbrir.setAttribute('aria-expanded', 'false');
    btnAbrir.focus();
  }

  construirPanel();
  configurarNavegacion();
  actualizarBotonGuardar();

  btnAbrir.addEventListener('click', function() {
    if (overlay.classList.contains('activo')) { cerrarConfig(); } else { abrirConfig(); }
  });
  if (btnCerrar) { btnCerrar.addEventListener('click', cerrarConfig); }
  if (fondo) { fondo.addEventListener('click', cerrarConfig); }
  btnGuardar.addEventListener('click', guardarYReiniciar);
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && overlay.classList.contains('activo')) {
      cerrarConfig();
    }
  });
})();

// ===================== MODO DESARROLLADOR AL FRENTE (GERAM v3) =====================
// El workspace (árbol de archivos + Monaco + A.R.E.S.) es la vista principal.
// Al terminar el boot se abre reutilizando su propio toggle, así no se duplica
// su lógica de carga (árbol y Monaco). El HUD del
// asistente IRIS queda como panel secundario. El botón conserva el workspace y
// cambia únicamente el perfil visible entre IRIS y A.R.E.S.
(function() {
  if (!document.body.classList.contains('modo-dev')) { return; }

  function activarPerfil(perfil) {
    var perfilAres = perfil === 'ares';
    var panelAres = document.getElementById('inlineAiBar');
    var etiqueta = document.getElementById('perfilActivo');

    document.body.classList.toggle('perfil-ares', perfilAres);
    document.body.classList.toggle('perfil-iris', !perfilAres);
    document.body.classList.remove('iris-visible');

    if (panelAres) { panelAres.setAttribute('aria-hidden', perfilAres ? 'false' : 'true'); }
    if (btnIris) {
      btnIris.dataset.profile = perfilAres ? 'ares' : 'iris';
      btnIris.classList.toggle('activo', perfilAres);
      btnIris.setAttribute('aria-label', 'Perfil activo: ' + (perfilAres ? 'A.R.E.S.' : 'IRIS'));
    }
    if (etiqueta) { etiqueta.textContent = perfilAres ? 'A.R.E.S.' : 'IRIS'; }

    // El workspace nunca se cierra ni se reconstruye. Monaco conserva su
    // modelo/archivo y sólo recalcula geometría al quedar visible de nuevo.
    if (perfilAres && window.GeramWorkspaceController) {
      window.GeramWorkspaceController.editorReady.then(function(adapter) {
        window.requestAnimationFrame(function() {
          adapter.layout();
          adapter.focus();
        });
      }).catch(function() { /* el fallback del editor conserva su estado */ });
    }
  }

  // Un único listener controla el perfil; no dispara clicks del workspace ni
  // registra nuevamente los handlers de A.R.E.S.
  var btnIris = document.getElementById('toggleIris');
  if (btnIris) {
    btnIris.addEventListener('click', function() {
      activarPerfil(btnIris.dataset.profile === 'ares' ? 'iris' : 'ares');
    });
  }
  activarPerfil('ares');

  // Abre el workspace disparando el MISMO click que usa su botón interno para
  // reutilizar la carga del árbol y el layout de Monaco. Terminal Watcher se
  // abre solo cuando la persona lo solicita desde la Activity Bar.
  function abrirVistaDev() {
    var wsPanel = document.getElementById('workspacePanel');
    var wsToggle = document.getElementById('toggleWorkspace');
    if (wsToggle && wsPanel && !wsPanel.classList.contains('activo')) { wsToggle.click(); }
  }

  if (document.body.classList.contains('listo')) {
    abrirVistaDev();
  } else {
    // El boot agrega la clase 'listo' al <body> al terminar; lo observamos.
    var obs = new MutationObserver(function() {
      if (document.body.classList.contains('listo')) { obs.disconnect(); abrirVistaDev(); }
    });
    obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
})();
