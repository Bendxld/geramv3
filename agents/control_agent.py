# ============================================================
# GERAM OS v2 · control_agent.py
# Agente central de control remoto del equipo: pestañas, ventanas,
# media, audio/pantalla, mouse, escritura, sistema, archivos/captura y
# apps/web. Lo llaman director.py (voz/texto del HUD y Telegram) y
# telegram_agent.py (comandos directos).
#
# REGLA DE TOKENS: CERO tokens en TODO este archivo, con dos
# excepciones puntuales:
#   - screenshot_analizar() (delega en screenshot_agent, Gemini Vision).
#   - interpretar()/ejecutar_accion_confirmada() al final del archivo:
#     respaldo vía Gemini/Ollama para lo que NO tiene función
#     determinística propia (crear/borrar/mover/copiar/renombrar
#     archivos y carpetas, instalar/desinstalar paquetes, "ejecuta X"
#     arbitrario, cerrar una app por NOMBRE). Es la lógica que antes
#     vivía en system_control_agent.py, movida tal cual.
#
# Todas las funciones "de cara a voz/texto" devuelven un string listo
# para mostrarle al usuario y nunca lanzan excepción. Las excepciones
# son los getters obtener_modo_dia()/obtener_expandido() (booleanos
# puros, para que server.py arme JSON con ellos).
# ============================================================

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from urllib.parse import quote

import psutil

from agents import balancer, escuchar, lock_agent, observador, offline_agent, screenshot_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("control_agent")

def _detectar_display():
    """Encuentra el display X activo mirando los sockets reales en
    /tmp/.X11-unix (evita adivinar entre :0, :1, etc)."""
    try:
        sockets = os.listdir("/tmp/.X11-unix")
        numeros = sorted(int(s[1:]) for s in sockets if s.startswith("X") and s[1:].isdigit())
        if numeros:
            return f":{numeros[0]}"
    except OSError:
        pass
    return ":0"


def asegurar_entorno_grafico():
    """server.py normalmente corre sin la sesión gráfica heredada
    (systemd, otra terminal, etc.), así que xdotool/xdg-open/amixer y
    demás comandos gráficos no encuentran el display y fallan en
    silencio. Si DISPLAY/XAUTHORITY no están seteados en el entorno del
    proceso, los detecta y los define (setdefault: si ya estaban bien
    puestos, no los toca)."""
    os.environ.setdefault("DISPLAY", _detectar_display())
    if "XAUTHORITY" not in os.environ:
        candidato = os.path.expanduser("~/.Xauthority")
        if os.path.exists(candidato):
            os.environ["XAUTHORITY"] = candidato


def _lanzar(comando, shell=False):
    """Lanza un proceso desatendido (no bloquea, no espera salida),
    asegurando primero que tenga DISPLAY/XAUTHORITY para poder abrir
    ventanas aunque el servidor no haya heredado la sesión gráfica."""
    asegurar_entorno_grafico()
    try:
        subprocess.Popen(
            comando, shell=shell,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
        return True
    except Exception as e:
        log.error("control_agent: no se pudo lanzar %s (%s)", comando, e)
        return False


def _xdotool(args):
    """Corre `xdotool <args>` (args = lista, ej. ["click", "1"]).
    Devuelve {"ok": True} o {"error": "..."}, nunca lanza excepción."""
    asegurar_entorno_grafico()
    try:
        resultado = subprocess.run(
            ["xdotool", *args],
            capture_output=True, text=True, timeout=5, env=os.environ.copy(),
        )
        if resultado.returncode != 0:
            return {"error": resultado.stderr.strip()[:200] or "xdotool devolvió un error."}
        return {"ok": True}
    except FileNotFoundError:
        return {"error": "falta xdotool instalado. Instálalo con: sudo apt install xdotool"}
    except Exception as e:
        log.error("control_agent: xdotool %s falló (%s)", args, e)
        return {"error": str(e)}


def _xdotool_msg(args, mensaje_ok, verbo):
    resultado = _xdotool(args)
    return mensaje_ok if resultado.get("ok") else f"No pude {verbo}: {resultado.get('error')}"


def _tecla(combo):
    return _xdotool(["key", combo])


def _tecla_msg(combo, mensaje_ok, verbo):
    return _xdotool_msg(["key", combo], mensaje_ok, verbo)


# ------------------------------------------------------------
# PESTAÑAS
# ------------------------------------------------------------
def siguiente_pestana():
    return _tecla_msg("ctrl+Tab", "Cambié de pestaña.", "cambiar de pestaña")


def anterior_pestana():
    return _tecla_msg("ctrl+shift+Tab", "Cambié de pestaña.", "cambiar de pestaña")


def cerrar_pestana():
    return _tecla_msg("ctrl+w", "Cerré la pestaña.", "cerrar la pestaña")


def nueva_pestana():
    return _tecla_msg("ctrl+t", "Abrí una pestaña nueva.", "abrir una pestaña nueva")


def pantalla_completa():
    return _tecla_msg("F11", "Pantalla completa.", "poner pantalla completa")


# ------------------------------------------------------------
# VENTANAS
# ------------------------------------------------------------
def siguiente_ventana():
    return _tecla_msg("alt+Tab", "Cambié de ventana.", "cambiar de ventana")


def anterior_ventana():
    return _tecla_msg("alt+shift+Tab", "Cambié de ventana.", "cambiar de ventana")


def minimizar_ventana():
    return _xdotool_msg(
        ["getactivewindow", "windowminimize"], "Minimicé la ventana.", "minimizar la ventana",
    )


def maximizar_ventana():
    return _tecla_msg("super+Up", "Maximicé la ventana.", "maximizar la ventana")


def cerrar_ventana():
    """Cierra la ventana/app con foco (Alt+F4). SIEMPRE requiere
    CONFIRMAR — eso lo decide director.py, no esta función."""
    return _tecla_msg("alt+F4", "Cerré la ventana.", "cerrar la ventana")


def listar_ventanas():
    """wmctrl -l -> texto listo para mostrar, o mensaje de error."""
    try:
        resultado = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
        if resultado.returncode != 0:
            return f"No pude listar las ventanas: {resultado.stderr.strip()[:200] or 'wmctrl devolvió un error.'}"
        ventanas = []
        for linea in resultado.stdout.strip().splitlines():
            partes = linea.split(None, 3)
            if len(partes) == 4:
                ventanas.append(partes[3])
        if not ventanas:
            return "No encontré ventanas abiertas, jefe."
        return "Tienes abierto:\n" + "\n".join(f"- {v}" for v in ventanas)
    except FileNotFoundError:
        return "Falta wmctrl instalado. Instálalo con: sudo apt install wmctrl"
    except Exception as e:
        log.error("control_agent: no se pudo listar las ventanas (%s)", e)
        return f"No pude listar las ventanas: {e}"


_MAX_SALTOS_ANCESTROS = 6


def _cadena_ancestros(pid, max_saltos=_MAX_SALTOS_ANCESTROS):
    """PIDs de `pid` y hasta `max_saltos` ancestros — NO camina hasta
    PID 1: en Linux TODO proceso desciende de PID 1 eventualmente, así
    que sin este límite la intersección con cualquier ventana SIEMPRE
    sería no vacía (compartirían PID 1) y cerrar_todo_menos_servidor()
    jamás cerraría nada (se probó a mano, era exactamente lo que
    pasaba). El límite alcanza de sobra para detectar "esta ventana es
    la terminal que lanzó server.py" sin llegar a ancestros universales."""
    cadena = set()
    try:
        proceso = psutil.Process(pid)
    except psutil.Error:
        return cadena
    for _ in range(max_saltos):
        cadena.add(proceso.pid)
        try:
            siguiente = proceso.parent()
        except psutil.Error:
            break
        if siguiente is None or siguiente.pid <= 1:
            break
        proceso = siguiente
    return cadena


def _ancestros_de_este_proceso():
    """PIDs de este proceso (server.py) y sus ancestros cercanos —
    para que cerrar_todo_menos_servidor() sepa qué ventanas NO tocar."""
    return _cadena_ancestros(os.getpid())


def _listar_ventanas_cerrables():
    """wmctrl -lp (incluye PID) + psutil: devuelve [(id, titulo), ...]
    excluyendo las ventanas cuyo proceso (o algún ancestro cercano de
    ese proceso) es el propio server.py. Devuelve (lista, None) o
    (None, "mensaje de error")."""
    ancestros = _ancestros_de_este_proceso()
    try:
        resultado = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return None, "falta wmctrl instalado. Instálalo con: sudo apt install wmctrl"
    except Exception as e:
        return None, str(e)
    if resultado.returncode != 0:
        return None, resultado.stderr.strip()[:200] or "wmctrl devolvió un error."

    cerrables = []
    for linea in resultado.stdout.strip().splitlines():
        partes = linea.split(None, 4)
        if len(partes) < 5:
            continue
        id_ventana, _escritorio, pid_str, _host, titulo = partes
        try:
            pid_ventana = int(pid_str)
        except ValueError:
            continue

        cadena = _cadena_ancestros(pid_ventana)
        protegida = bool(cadena & ancestros)

        if not protegida:
            cerrables.append((id_ventana, titulo))

    return cerrables, None


def previsualizar_cierre_todo():
    """Para que director.py le muestre al usuario QUÉ va a cerrar
    antes de pedir CONFIRMAR (mitiga que la heurística de arriba no
    sea perfecta). Devuelve (lista_de_titulos, error|None)."""
    cerrables, error = _listar_ventanas_cerrables()
    if error:
        return None, error
    return [titulo for _id, titulo in cerrables], None


def cerrar_todo_menos_servidor():
    """Cierra TODAS las ventanas abiertas excepto las del proceso de
    este servidor. Se asume que director.py YA pidió CONFIRMAR y ya
    mostró la lista (ver previsualizar_cierre_todo)."""
    cerrables, error = _listar_ventanas_cerrables()
    if error:
        return f"No pude cerrar las ventanas: {error}"
    if not cerrables:
        return "No encontré ventanas para cerrar."

    fallos = 0
    for id_ventana, _titulo in cerrables:
        resultado = subprocess.run(
            ["wmctrl", "-ic", id_ventana], capture_output=True, text=True, timeout=5,
        )
        if resultado.returncode != 0:
            fallos += 1

    total = len(cerrables)
    if fallos:
        return f"Cerré {total - fallos} de {total} ventanas (fallaron {fallos})."
    return f"Listo, cerré {total} ventana{'s' if total != 1 else ''}."


# ------------------------------------------------------------
# MEDIA
# ------------------------------------------------------------
def play_pause():
    return _tecla_msg("XF86AudioPlay", "Play/Pause.", "pausar/reanudar")


def siguiente_track():
    return _tecla_msg("XF86AudioNext", "Siguiente canción.", "cambiar de canción")


def anterior_track():
    return _tecla_msg("XF86AudioPrev", "Canción anterior.", "cambiar de canción")


def abrir_en_youtube(busqueda):
    busqueda = (busqueda or "").strip()
    if not busqueda:
        return "¿Qué busco en YouTube, jefe?"
    url = f"https://www.youtube.com/results?search_query={quote(busqueda)}"
    return f"Buscando '{busqueda}' en YouTube." if abrir_url(url) else "No pude abrir YouTube."


def silenciar():
    """Mute toggle (amixer) — usado por voz/texto."""
    try:
        resultado = subprocess.run(
            ["amixer", "set", "Master", "toggle"], capture_output=True, text=True, timeout=5,
        )
        if resultado.returncode != 0:
            return f"No pude silenciar: {resultado.stderr.strip()[:200] or 'amixer devolvió un error.'}"
        return "Listo, silencié/activé el audio."
    except Exception as e:
        log.error("control_agent: no se pudo silenciar el audio (%s)", e)
        return f"No pude silenciar: {e}"


# ------------------------------------------------------------
# AUDIO Y PANTALLA
# ------------------------------------------------------------
def _ajustar_volumen(delta):
    try:
        resultado = subprocess.run(
            ["amixer", "set", "Master", f"{abs(delta)}%{'+' if delta > 0 else '-'}"],
            capture_output=True, text=True, timeout=5,
        )
        if resultado.returncode != 0:
            return {"error": resultado.stderr.strip()[:200] or "amixer devolvió un error."}
        return {"ok": True}
    except Exception as e:
        log.error("control_agent: no se pudo ajustar el volumen (%s)", e)
        return {"error": str(e)}


def subir_volumen():
    resultado = _ajustar_volumen(10)
    return "Subí el volumen." if resultado.get("ok") else f"No pude subir el volumen: {resultado.get('error')}"


def bajar_volumen():
    resultado = _ajustar_volumen(-10)
    return "Bajé el volumen." if resultado.get("ok") else f"No pude bajar el volumen: {resultado.get('error')}"


def set_volumen(porcentaje):
    """Fija el volumen a un valor ABSOLUTO 0-100 (a diferencia de
    _ajustar_volumen, que es relativo) — usado por /volumen <numero>
    en telegram_agent.py."""
    porcentaje = max(0, min(100, int(porcentaje)))
    try:
        resultado = subprocess.run(
            ["amixer", "set", "Master", f"{porcentaje}%"], capture_output=True, text=True, timeout=5,
        )
        if resultado.returncode != 0:
            return f"No pude fijar el volumen: {resultado.stderr.strip()[:200] or 'amixer devolvió un error.'}"
        return f"Volumen en {porcentaje}%."
    except Exception as e:
        log.error("control_agent: no se pudo fijar el volumen (%s)", e)
        return f"No pude fijar el volumen: {e}"


def _ajustar_brillo(direccion):
    asegurar_entorno_grafico()
    arg = "+10%" if direccion > 0 else "10%-"
    try:
        resultado = subprocess.run(
            ["brightnessctl", "set", arg], capture_output=True, text=True, timeout=5,
        )
        if resultado.returncode != 0:
            return {"error": resultado.stderr.strip()[:200] or "brightnessctl devolvió un error."}
        return {"ok": True}
    except FileNotFoundError:
        return {"error": "falta brightnessctl instalado. Instálalo con: sudo apt install brightnessctl"}
    except Exception as e:
        log.error("control_agent: no se pudo ajustar el brillo (%s)", e)
        return {"error": str(e)}


def subir_brillo():
    resultado = _ajustar_brillo(1)
    return "Subí el brillo." if resultado.get("ok") else f"No pude subir el brillo: {resultado.get('error')}"


def bajar_brillo():
    resultado = _ajustar_brillo(-1)
    return "Bajé el brillo." if resultado.get("ok") else f"No pude bajar el brillo: {resultado.get('error')}"


def apagar_pantalla():
    asegurar_entorno_grafico()
    try:
        resultado = subprocess.run(
            ["xset", "dpms", "force", "off"], capture_output=True, text=True, timeout=5, env=os.environ.copy(),
        )
        if resultado.returncode != 0:
            return f"No pude apagar la pantalla: {resultado.stderr.strip()[:200]}"
        return "Pantalla apagada."
    except Exception as e:
        log.error("control_agent: no se pudo apagar la pantalla (%s)", e)
        return f"No pude apagar la pantalla: {e}"


def prender_pantalla():
    asegurar_entorno_grafico()
    try:
        resultado = subprocess.run(
            ["xset", "dpms", "force", "on"], capture_output=True, text=True, timeout=5, env=os.environ.copy(),
        )
        if resultado.returncode != 0:
            return f"No pude prender la pantalla: {resultado.stderr.strip()[:200]}"
        return "Pantalla encendida."
    except Exception as e:
        log.error("control_agent: no se pudo prender la pantalla (%s)", e)
        return f"No pude prender la pantalla: {e}"


# _modo_dia/_expandido: estado real de módulo para que CUALQUIER
# canal (voz/texto, Telegram) pueda
# cambiarlo y el HUD lo refleje sin importar de dónde vino — ver
# GET /control/estado-ui en server.py, que el frontend poll-ea.
_modo_dia = False
_expandido = False


def establecer_modo_dia(activo):
    """FIJA el valor exacto del modo día/noche —
    lo usa POST /modo-dia en server.py para que el click del botón
    sol/luna del HUD quede reflejado acá y sincronizarEstadoUI() en
    script.js dejen de "pelearse" (el poll cada 2s revertía el botón
    porque el click de antes nunca le avisaba a este módulo)."""
    global _modo_dia
    _modo_dia = bool(activo)


def obtener_modo_dia():
    return _modo_dia


def obtener_expandido():
    return _expandido


# _voz_activa/_mic_solicitud: mismo criterio que _modo_dia/_expandido
# arriba — estado real de módulo para que "cállate"/"activa el
# micrófono" dichos por voz/texto del HUD O DESDE TELEGRAM tengan
# efecto real en el navegador, no solo en el canal donde se dijeron.
# _mic_solicitud es "leer y limpia": el frontend hace polling en /control/estado-ui
# y, si trae "activar"/"desactivar", simula el click en el botón MIC
# (el MediaRecorder real vive en el navegador, Python no lo controla).
_voz_activa = True
_mic_solicitud = None


def activar_voz():
    global _voz_activa
    _voz_activa = True
    return "Listo, ya puedo hablar mis respuestas."


def desactivar_voz():
    global _voz_activa
    _voz_activa = False
    return "Ok, me quedo callado. Sigo respondiendo por chat."


def obtener_voz_activa():
    return _voz_activa


def solicitar_mic_activar():
    global _mic_solicitud
    _mic_solicitud = "activar"
    return "Si tienes el HUD abierto, ya le prendí el micrófono."


def solicitar_mic_desactivar():
    global _mic_solicitud
    _mic_solicitud = "desactivar"
    return "Si tienes el HUD abierto, ya le apagué el micrófono."


def obtener_y_limpiar_solicitud_mic():
    global _mic_solicitud
    solicitud = _mic_solicitud
    _mic_solicitud = None
    return solicitud


# ------------------------------------------------------------
# MOUSE
# ------------------------------------------------------------
def click_mouse():
    return _xdotool_msg(["click", "1"], "Click.", "hacer click")


def click_derecho_mouse():
    return _xdotool_msg(["click", "3"], "Click derecho.", "hacer click derecho")


def doble_click():
    return _xdotool_msg(["click", "--repeat", "2", "1"], "Doble click.", "hacer doble click")


def scroll_arriba():
    return _xdotool_msg(["click", "4"], "Scroll arriba.", "hacer scroll")


def scroll_abajo():
    return _xdotool_msg(["click", "5"], "Scroll abajo.", "hacer scroll")


# ------------------------------------------------------------
# ESCRITURA
# ------------------------------------------------------------
_KEYSYMS_ESPECIALES = {
    "escape": "Escape", "esc": "Escape",
    "backspace": "BackSpace", "borra": "BackSpace",
    "delete": "Delete", "supr": "Delete",
    "tab": "Tab",
    "enter": "Return", "return": "Return",
    "selecciona todo": "ctrl+a", "seleccionar todo": "ctrl+a",
    "copia": "ctrl+c", "copiar": "ctrl+c",
    "pega": "ctrl+v", "pegar": "ctrl+v",
    "guarda": "ctrl+s", "guardar": "ctrl+s",
    "deshacer": "ctrl+z", "deshace": "ctrl+z",
}


def escribir_especial(tecla):
    """`tecla` puede ser un alias en español (ver _KEYSYMS_ESPECIALES,
    ej. "guarda" -> ctrl+s) o ya un keysym/combo de xdotool tal cual."""
    combo = _KEYSYMS_ESPECIALES.get(tecla.strip().lower(), tecla.strip())
    return _tecla_msg(combo, "Hecho.", f"mandar '{tecla}'")


def escribir_enter():
    return _tecla_msg("Return", "Enter.", "mandar enter")


def escribir_texto(texto):
    """Escribe `texto` en el campo con foco usando el portapapeles +
    Ctrl+V — NO `xdotool type`, que en equipos con acentos/UTF-8 según
    el layout activo puede perder o duplicar caracteres. Guarda el
    contenido actual del portapapeles y lo restaura después, para no
    pisar lo que el usuario tuviera copiado."""
    asegurar_entorno_grafico()
    if not texto or not texto.strip():
        return "¿Qué quieres que escriba, jefe?"

    anterior = None
    try:
        previo = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=5,
        )
        if previo.returncode == 0:
            anterior = previo.stdout
    except Exception:
        pass

    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"], input=texto, text=True, timeout=5, check=True,
        )
    except FileNotFoundError:
        return "Falta xclip instalado. Instálalo con: sudo apt install xclip"
    except Exception as e:
        return f"No pude preparar el texto para escribir: {e}"

    resultado = _tecla("ctrl+v")
    time.sleep(0.3)

    if anterior is not None:
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"], input=anterior, text=True, timeout=5,
            )
        except Exception:
            pass

    return "Listo, lo escribí." if resultado.get("ok") else f"No pude escribir el texto: {resultado.get('error')}"


def dictar():
    """Graba con el micrófono real (escuchar.escuchar_microfono, ya
    tiene detección de silencio propia) y lo escribe donde esté el
    foco — a diferencia de activar_mic()/desactivar_mic() (que son el
    puente liviano hacia el mic del NAVEGADOR), esto graba de verdad
    con el micrófono del sistema."""
    texto = escuchar.escuchar_microfono()
    if not texto or not texto.strip():
        return "No escuché nada, jefe."
    return escribir_texto(texto)


# ------------------------------------------------------------
# SISTEMA
# ------------------------------------------------------------
def _obtener_temperatura():
    try:
        temps = psutil.sensors_temperatures()
        for etiqueta in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if etiqueta in temps and temps[etiqueta]:
                return round(temps[etiqueta][0].current, 1)
        for lecturas in temps.values():
            if lecturas:
                return round(lecturas[0].current, 1)
    except (AttributeError, OSError):
        pass
    return round(38 + (psutil.cpu_percent(interval=None) * 0.25), 1)


def estado_sistema():
    """CPU/RAM/temp/uptime/disco — NO usa tokens, puro psutil."""
    cpu = psutil.cpu_percent(interval=0.2)
    ram = psutil.virtual_memory().percent
    disco = psutil.disk_usage("/").percent
    temp = _obtener_temperatura()
    segundos = int(time.time() - psutil.boot_time())
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return (
        f"CPU {cpu:.0f}% · RAM {ram:.0f}% · Disco {disco:.0f}% · "
        f"Temp {temp:.0f}°C · Uptime {h:02d}:{m:02d}:{s:02d}"
    )


def suspender():
    """Suspende el equipo — NO requiere confirmar, es reversible."""
    try:
        subprocess.Popen(["systemctl", "suspend"])
        return "Me pongo en reposo, jefe."
    except Exception as e:
        log.error("control_agent: no se pudo suspender (%s)", e)
        return f"No pude suspender: {e}"


def apagar():
    """Apaga el equipo de verdad. SIEMPRE requiere CONFIRMAR (con el
    diálogo especial que arma director.py sugiriendo reposo en vez de
    apagar) — esta función solo ejecuta, no pregunta nada."""
    try:
        subprocess.Popen(["systemctl", "poweroff"])
        return "Apagando el equipo, jefe. Hasta luego."
    except Exception as e:
        log.error("control_agent: no se pudo apagar (%s)", e)
        return f"No pude apagar: {e}"


def activar_mic():
    """Puente liviano: el navegador sigue haciendo la grabación real
    (MediaRecorder + faster-whisper vía /audio, sin cambios) — esta
    función existe para que director tenga un punto
    único de entrada sin acoplarse a cómo decide reaccionar el
    frontend. Para grabar de verdad con el micrófono del sistema y
    tipear el resultado, ver dictar()."""
    return "Micrófono activado."


def desactivar_mic():
    return "Micrófono desactivado."


def bloquear():
    lock_agent.forzar_bloqueo()
    return "Bloqueando el equipo, jefe."


# ------------------------------------------------------------
# ARCHIVOS Y CAPTURA
# ------------------------------------------------------------
def tomar_screenshot():
    """CERO tokens — solo captura, no analiza. Para análisis con
    Gemini Vision ver screenshot_analizar()."""
    resultado = screenshot_agent.capturar_pantalla()
    if resultado.get("error"):
        return f"No pude tomar la captura: {resultado['error']}"
    return f"Captura guardada en {resultado['ruta']}."


def tomar_foto_webcam():
    """CERO tokens — solo captura (fswebcam vía observador.py)."""
    resultado = observador.capturar_foto()
    if resultado.get("error"):
        return f"No pude tomar la foto: {resultado['error']}"
    return f"Foto guardada en {resultado['ruta']}."


def screenshot_analizar():
    """La ÚNICA función de este archivo que gasta tokens de Gemini
    (Gemini Vision, vía screenshot_agent.analizar_pantalla)."""
    return screenshot_agent.analizar_pantalla()


def leer_archivo(ruta):
    """Lee un .txt o .pdf local y devuelve su texto (recortado a 5000
    caracteres). NO usa tokens — solo extrae el texto, no lo resume."""
    ruta = os.path.expanduser((ruta or "").strip())
    if not ruta:
        return "¿Qué archivo quieres que lea, jefe?"
    if not os.path.exists(ruta):
        return f"No encuentro el archivo '{ruta}'."

    try:
        if ruta.lower().endswith(".pdf"):
            import pdfplumber
            partes = []
            with pdfplumber.open(ruta) as pdf:
                for pagina in pdf.pages:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina:
                        partes.append(texto_pagina)
            contenido = "\n".join(partes)
        else:
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                contenido = f.read()
    except Exception as e:
        log.error("control_agent: no se pudo leer '%s' (%s)", ruta, e)
        return f"No pude leer '{ruta}': {e}"

    if not contenido.strip():
        return f"'{ruta}' no tiene texto legible."
    return contenido[:5000]


_proceso_grabacion = None
_RUTA_GRABACION = "/tmp/geram_grabacion.mp4"


def grabar_pantalla():
    global _proceso_grabacion
    asegurar_entorno_grafico()
    if _proceso_grabacion is not None and _proceso_grabacion.poll() is None:
        return "Ya estoy grabando la pantalla, jefe."

    display = os.environ.get("DISPLAY", ":0")
    try:
        _proceso_grabacion = subprocess.Popen(
            ["ffmpeg", "-y", "-f", "x11grab", "-r", "15", "-i", display, _RUTA_GRABACION],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ.copy(),
        )
        return "Empecé a grabar la pantalla."
    except FileNotFoundError:
        return "Falta ffmpeg instalado. Instálalo con: sudo apt install ffmpeg"
    except Exception as e:
        log.error("control_agent: no se pudo empezar a grabar (%s)", e)
        return f"No pude empezar a grabar: {e}"


def parar_grabacion():
    global _proceso_grabacion
    if _proceso_grabacion is None or _proceso_grabacion.poll() is not None:
        _proceso_grabacion = None
        return "No hay ninguna grabación en curso."

    try:
        # SIGINT (no SIGTERM/kill -9): ffmpeg necesita esta señal para
        # cerrar bien el .mp4 (escribir el moov atom), si no el archivo
        # queda corrupto/ilegible.
        _proceso_grabacion.send_signal(signal.SIGINT)
        _proceso_grabacion.wait(timeout=10)
    except Exception as e:
        log.error("control_agent: no se pudo parar la grabación limpio, forzando (%s)", e)
        _proceso_grabacion.kill()

    ruta = _RUTA_GRABACION
    _proceso_grabacion = None
    return f"Grabación guardada en {ruta}."


def buscar_archivo(nombre):
    nombre = (nombre or "").strip()
    if not nombre:
        return "¿Qué archivo busco, jefe?"
    try:
        resultado = subprocess.run(
            ["find", "/home/mauri", "-iname", f"*{nombre}*"],
            capture_output=True, text=True, timeout=15,
        )
        rutas = [linea for linea in resultado.stdout.strip().splitlines() if linea][:20]
        if not rutas:
            return f"No encontré ningún archivo que coincida con '{nombre}'."
        return "Encontré esto:\n" + "\n".join(rutas)
    except subprocess.TimeoutExpired:
        return "La búsqueda tardó demasiado y se canceló."
    except Exception as e:
        log.error("control_agent: no se pudo buscar el archivo '%s' (%s)", nombre, e)
        return f"No pude buscar el archivo: {e}"


# ------------------------------------------------------------
# APPS Y WEB
# ------------------------------------------------------------
_DIRECTORIOS_DESKTOP = (
    os.path.expanduser("~/.local/share/applications"),
    "/usr/share/applications",
)
_PATRON_EXEC_PLACEHOLDER = re.compile(r"%[a-zA-Z]")

# Alias para nombres que el usuario dice/escribe pero que NO son
# substring literal del Name= real del .desktop (ver abrir_app) —
# típicamente porque el reconocimiento de voz transcribe mal el nombre
# de la app (ej. "Thunar" -> "Thunder", el gestor de archivos de XFCE
# de este equipo) o porque usa el nombre genérico en vez del propio
# (ej. "explorador de archivos"). Se resuelve ANTES de buscar en los
# .desktop, así que el valor debe ser una palabra que SÍ aparezca en
# el Name= real (para "thunar file manager" alcanza con "thunar").
_ALIAS_APPS = {
    "thunder files": "thunar", "thunder file": "thunar", "thunder": "thunar",
    "explorador de archivos": "thunar", "administrador de archivos": "thunar",
    "gestor de archivos": "thunar",
    # proyectos/cerebro_archivos (Cerebro-de-Archivos.desktop). El .desktop
    # ya matchea "cerebro de archivos" solo (substring de su Name=), pero
    # _quitar_palabra_clave NO saca artículos iniciales ("abre el cerebro
    # de archivos" queda como "el cerebro de archivos", que ya NO es
    # substring de "Cerebro de Archivos") — de ahí estas variantes.
    "el cerebro de archivos": "cerebro de archivos", "mi cerebro de archivos": "cerebro de archivos",
    "el cerebro": "cerebro de archivos", "mi cerebro": "cerebro de archivos", "cerebro": "cerebro de archivos",
}


def abrir_app(nombre):
    """Busca un .desktop cuyo Name= contenga `nombre` (insensible a
    mayúsculas) en las carpetas estándar de lanzadores y ejecuta su
    Exec=; si no encuentra nada, prueba `nombre` como ejecutable
    directo, y como último recurso xdg-open. CERO tokens (a diferencia
    de la vieja "abre X" que le pedía el comando a Gemini)."""
    asegurar_entorno_grafico()
    nombre = (nombre or "").strip()
    if not nombre:
        return "¿Qué aplicación abro, jefe?"
    clave = _ALIAS_APPS.get(nombre.lower(), nombre.lower())

    for directorio in _DIRECTORIOS_DESKTOP:
        if not os.path.isdir(directorio):
            continue
        try:
            archivos = os.listdir(directorio)
        except OSError:
            continue
        for archivo in archivos:
            if not archivo.endswith(".desktop"):
                continue
            try:
                with open(os.path.join(directorio, archivo), encoding="utf-8", errors="ignore") as f:
                    contenido = f.read()
            except OSError:
                continue

            nombre_app = None
            exec_cmd = None
            for linea in contenido.splitlines():
                if nombre_app is None and linea.startswith("Name="):
                    nombre_app = linea[len("Name="):].strip()
                elif exec_cmd is None and linea.startswith("Exec="):
                    exec_cmd = linea[len("Exec="):].strip()
                if nombre_app and exec_cmd:
                    break

            if nombre_app and clave in nombre_app.lower():
                if not exec_cmd:
                    continue
                exec_limpio = _PATRON_EXEC_PLACEHOLDER.sub("", exec_cmd).strip()
                if _lanzar(exec_limpio, shell=True):
                    return f"Abriendo {nombre_app}."
                return f"Encontré {nombre_app} pero no pude lanzarlo."

    ejecutable = shutil.which(clave)
    if ejecutable and _lanzar([ejecutable]):
        return f"Abriendo {nombre}."

    if _lanzar(["xdg-open", clave]):
        return f"Intentando abrir {nombre}."
    return f"No encontré ni pude abrir '{nombre}', jefe."


# Se prueban en este orden si xdg-open no encuentra un navegador
# "conocido" (ver abrir_url). brave-browser primero porque es el
# instalado en este equipo.
_NAVEGADORES_CONOCIDOS = ("brave-browser", "firefox", "chromium", "google-chrome")

# Alias chicos de sitios conocidos para "pon Netflix"/"abre YouTube" —
# si no matchea nada de acá, se trata como URL/dominio literal.
SITIOS_CONOCIDOS = {
    "netflix": "https://www.netflix.com",
    "youtube": "https://www.youtube.com",
    "spotify": "https://open.spotify.com",
    "gmail": "https://mail.google.com",
    "correo": "https://mail.google.com",
    "github": "https://github.com",
    "drive": "https://drive.google.com",
    "notion": "https://www.notion.so",
    "whatsapp": "https://web.whatsapp.com",
}


def abrir_url(url_o_nombre):
    """Abre una URL o un sitio conocido (ver SITIOS_CONOCIDOS) en un
    navegador, con logs detallados de cada método intentado
    (diagnóstico real: en este equipo, xdg-open pasaba por exo-open ->
    helper de XFCE mal configurado apuntando a un comando 'brave' que
    no existe -> xdg-open igual devolvía código 0, sin ningún error, y
    no abría nada).

    Por eso el ORDEN no es A->B->C tal cual: se prueba primero el
    método cuyo resultado SÍ se puede confirmar (B, llamar al binario
    del navegador directo — Python reporta un error real si no existe
    o no se puede lanzar), y xdg-open/os.system quedan de respaldo.

    IMPORTANTE: a diferencia del resto de este archivo, devuelve un
    BOOL (True/False), no un string — whatsapp_agent.py, classroom_agent.py
    y nexus_agent.py ya dependen de ese contrato (`if abrir_url(...):`),
    así que se mantiene tal cual para no romperlos.
    """
    asegurar_entorno_grafico()

    clave = (url_o_nombre or "").strip().lower()
    url = SITIOS_CONOCIDOS.get(clave, (url_o_nombre or "").strip())
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"

    log.info(
        "abrir_url: pidieron abrir '%s' (DISPLAY=%s XAUTHORITY=%s)",
        url, os.environ.get("DISPLAY"), os.environ.get("XAUTHORITY"),
    )

    # Método B: llamar al navegador directo. Se prueba primero porque
    # es el único cuyo éxito/fallo se puede confirmar de verdad.
    for navegador in _NAVEGADORES_CONOCIDOS:
        ruta = shutil.which(navegador)
        if not ruta:
            log.info("abrir_url: método B - '%s' no está instalado, sigo con el siguiente", navegador)
            continue
        try:
            subprocess.Popen(
                [ruta, url], env=os.environ.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info("abrir_url: método B OK - lancé '%s %s'", ruta, url)
            return True
        except Exception as e:
            log.error("abrir_url: método B falló con '%s' (%s: %s)", ruta, type(e).__name__, e)

    # Método A: xdg-open. Su código de salida NO es confiable (en este
    # equipo devolvía 0 aunque no abriera nada — exo-open se traga el
    # error), así que solo se usa si no hay ningún navegador conocido.
    try:
        resultado = subprocess.run(
            ["xdg-open", url], env=os.environ.copy(),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=5, text=True,
        )
        log.info(
            "abrir_url: método A (xdg-open) código=%s stderr=%r",
            resultado.returncode, resultado.stderr,
        )
        if resultado.returncode == 0:
            return True
    except Exception as e:
        log.error("abrir_url: método A (xdg-open) falló (%s: %s)", type(e).__name__, e)

    # Método C: os.system con DISPLAY inline, último recurso.
    try:
        display = os.environ.get("DISPLAY", ":0")
        comando = f'DISPLAY={display} xdg-open "{url}" &'
        codigo = os.system(comando)
        log.info("abrir_url: método C (os.system) comando=%r código=%s", comando, codigo)
        return True
    except Exception as e:
        log.error("abrir_url: método C (os.system) falló (%s: %s)", type(e).__name__, e)

    log.error("abrir_url: los 3 métodos fallaron para '%s'", url)
    return False


def abrir_archivo(ruta):
    """A diferencia del resto de "abrir" (_lanzar(), fire-and-forget),
    esta corre xdg-open EN PRIMER PLANO (subprocess.run, no Popen) para
    poder confirmar de verdad si abrió o no antes de responder — nunca
    dice "abriendo"/"intentando" sin haber comprobado el código de
    salida real."""
    ruta = os.path.expanduser((ruta or "").strip())
    if not ruta:
        return "¿Qué archivo abro, jefe?"
    if not os.path.exists(ruta):
        return f"No encuentro el archivo '{ruta}'."

    asegurar_entorno_grafico()
    try:
        resultado = subprocess.run(
            ["xdg-open", ruta], capture_output=True, text=True, timeout=10, env=os.environ.copy(),
        )
    except FileNotFoundError:
        return "No pude abrirlo: falta xdg-open instalado. Instálalo con: sudo apt install xdg-utils"
    except subprocess.TimeoutExpired:
        return f"No pude abrir '{ruta}': el comando tardó demasiado y se canceló."
    except Exception as e:
        log.error("control_agent: no se pudo abrir '%s' (%s)", ruta, e)
        return f"No pude abrir '{ruta}': {e}"

    if resultado.returncode != 0:
        return f"No pude abrir '{ruta}': {resultado.stderr.strip()[:200] or 'xdg-open devolvió un error.'}"
    return f"Abrí {ruta}."


# ============================================================
# RESPALDO VÍA GEMINI/OLLAMA (Q1 de la sesión de reorganización): para
# lo que NO tiene función determinística arriba — crear/borrar/mover/
# copiar/renombrar archivos y carpetas, instalar/desinstalar paquetes,
# "ejecuta X" arbitrario, cerrar una app por NOMBRE (no la ventana con
# foco, para eso está cerrar_ventana()). Movido tal cual desde
# system_control_agent.py — ver director.py para saber qué frases
# siguen llegando hasta acá.
# ============================================================

# Tipos de acción que solo abren algo (ventana/proceso propio, no
# necesitamos su salida): se lanzan desatendidos con _lanzar(). El
# resto ("comando", "buscar_archivo") corre en primer plano porque
# el usuario espera ver su salida (resultados de find, de amixer, etc).
_TIPOS_LANZAR_DESATENDIDO = {"abrir_url", "abrir_app", "abrir_archivo"}

# Capa de seguridad que NO depende de lo que responda el modelo: abrir
# algo (app/URL/archivo) o buscar archivos jamás pide confirmación,
# pase lo que pase en el JSON — no afectan la compu, no hay nada que
# confirmar. Es una whitelist, no una blacklist: si el modelo inventa
# un "tipo" nuevo que no está aquí, NO cae en esta lista y sigue de
# largo a la validación de _PATRONES_PELIGROSOS de abajo.
_TIPOS_SIEMPRE_SEGUROS = {"abrir_url", "abrir_app", "abrir_archivo", "buscar_archivo"}

# Y en la otra punta: si el comando generado toca algo que borra,
# apaga, reinicia, instala/desinstala paquetes o mata procesos, exige
# confirmación SIEMPRE, aunque el modelo haya mandado
# requiere_confirmacion=false (por error o por un prompt injection
# metido en el mensaje del usuario). \b para no matchear substrings
# sueltas (ej. que "kill" no dispare con "skill" o "killer").
_PATRONES_PELIGROSOS = [re.compile(p, re.I) for p in (
    r"\brm\b", r"\bmkfs\b", r"\bdd\s+if=", r"\bshred\b",
    r"\bshutdown\b", r"\bpoweroff\b", r"\breboot\b", r"\bhalt\b",
    r"\bsystemctl\s+(poweroff|reboot|suspend|hibernate|halt)\b",
    r"\bpkill\b", r"\bkill(all)?\b",
    r"\b(apt|apt-get|dpkg|snap|pip|pip3)\s+.*(install|remove|purge|uninstall)\b",
    r"\bchmod\s+-R\b", r"\bchown\s+-R\b",
    r"\buserdel\b", r"\bpasswd\b", r"\bvisudo\b",
    r"\biptables\b", r"\bufw\b", r"\bfdisk\b", r"\bparted\b", r"\bmkswap\b",
    r">\s*/dev/sd", r"\bmv\s+/(?!home/mauri)",
)]

SYSTEM_PROMPT_CONTROL = """Eres el agente de control de sistema de GERAM OS en Linux Mint.
Solo te llegan pedidos que NO tienen una función determinística propia:
crear/borrar/mover/copiar/renombrar archivos y carpetas, instalar/
desinstalar paquetes, cerrar una app por NOMBRE, o "ejecuta X" arbitrario.
Tu trabajo es generar el comando EXACTO de Linux para ejecutar
lo que el usuario pide. Responde SOLO con un JSON así:
{
  "tipo": "abrir_url" | "abrir_app" | "abrir_archivo" | "comando" | "buscar_archivo",
  "comando": "el comando exacto de Linux",
  "descripcion": "qué va a hacer este comando",
  "requiere_confirmacion": true | false
}

Reglas:
- Para cerrar una app por nombre usa: pkill -f nombre
- Para buscar archivos usa: find /home/mauri -iname
- Para crear archivos usa: touch (vacío) o echo "contenido" > ruta (con texto)
- Para crear carpetas usa: mkdir -p
- Para borrar/mover/copiar/renombrar archivos usa: rm/mv/cp
- Para instalar/desinstalar paquetes usa: sudo apt install/remove -y
- requiere_confirmacion = true SOLO para: cerrar apps, borrar
  archivos, instalar/desinstalar paquetes, ejecutar comandos
  potencialmente peligrosos
- requiere_confirmacion = false para: buscar archivos, crear archivos
  o carpetas, mover/copiar/renombrar archivos
- El usuario se llama mauri, su home es /home/mauri. Los nombres
  REALES de sus carpetas (NO los adivines traducidos al español,
  este equipo las tiene en inglés) son:
  /home/mauri/Desktop, /home/mauri/Documents, /home/mauri/Downloads,
  /home/mauri/Music, /home/mauri/Pictures, /home/mauri/Videos
- El sistema es Linux Mint con XFCE o similar
- SOLO responde el JSON, nada más"""


def _es_verdadero(valor):
    """Gemini/Ollama a veces devuelven "true"/"false" como string en
    vez de bool real; esto normaliza cualquiera de las dos formas."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "si", "sí", "1")
    return bool(valor)


def _es_peligroso(comando):
    """True si el comando toca algo que borra/apaga/reinicia/instala
    o mata procesos (ver _PATRONES_PELIGROSOS)."""
    return any(patron.search(comando) for patron in _PATRONES_PELIGROSOS)


def _decidir_confirmacion(tipo, comando, valor_del_modelo):
    """La palabra final sobre si hace falta CONFIRMAR no es del
    modelo: es de esta función. El modelo solo la sugiere.

    - abrir_app/abrir_url/abrir_archivo/buscar_archivo: NUNCA piden
      confirmación, no afectan la compu.
    - Si el comando matchea un patrón peligroso (borrar, apagar,
      reiniciar, instalar/desinstalar paquetes, matar procesos, etc.):
      SIEMPRE pide confirmación, aunque el modelo haya dicho que no.
    - Cualquier otro caso: se respeta lo que dijo el modelo (o True
      por defecto si no mandó el campo — ante la duda, mejor preguntar).
    """
    if tipo in _TIPOS_SIEMPRE_SEGUROS:
        return False
    if _es_peligroso(comando):
        return True
    return _es_verdadero(valor_del_modelo)


def _parsear_json_accion(texto):
    """Extrae el JSON de la respuesta del modelo, tolerando fences de
    markdown (```json ... ```) que a veces agrega aunque se le pida
    que no, o texto extra alrededor del bloque {...}."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.I)

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    coincidencia = re.search(r"\{.*\}", texto, re.S)
    if coincidencia:
        try:
            return json.loads(coincidencia.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _pedir_accion_al_modelo(mensaje_usuario):
    """Manda `mensaje_usuario` a Gemini para que genere el JSON de la
    acción. Si Gemini falla (todas las keys caídas / sin internet),
    reintenta con Ollama local."""
    respuesta = balancer.enviar_mensaje(
        prompt=mensaje_usuario, historial=[], system_instruction=SYSTEM_PROMPT_CONTROL,
    )

    if respuesta.startswith("ERROR:"):
        log.warning("control_agent: Gemini falló, probando Ollama para generar el comando")
        respuesta = offline_agent.obtener_respuesta_offline(
            prompt=mensaje_usuario, historial=[], system_instruction=SYSTEM_PROMPT_CONTROL,
        )

    return respuesta


_PATRON_URL = re.compile(r"https?://\S+")


def _extraer_url(comando):
    """Saca la URL del comando que generó el modelo (típicamente
    "xdg-open <url>"), o None si no encuentra ninguna."""
    coincidencia = _PATRON_URL.search(comando)
    return coincidencia.group(0).strip('"\'') if coincidencia else None


# Patrones para detectar qué archivo/carpeta creó un comando generado
# por el modelo (ver SYSTEM_PROMPT_CONTROL: "crear archivos usa touch/
# echo > ruta", "crear carpetas usa mkdir -p") — para que director.py
# pueda recordarlo como "último archivo creado" (ver
# context_engine.set_ultimo_archivo_creado) y un "ábrelo" después no
# tenga que pedir el nombre. Best-effort, no un parser de shell real.
_PATRON_REDIRECCION_ARCHIVO = re.compile(r">>?\s*(\"[^\"]+\"|'[^']+'|\S+)")
_PATRON_TOUCH = re.compile(r"\btouch\s+(\"[^\"]+\"|'[^']+'|\S+)")
_PATRON_MKDIR = re.compile(r"\bmkdir\s+(?:-p\s+)?(\"[^\"]+\"|'[^']+'|\S+)")


def _extraer_ruta_creada(comando):
    """Si `comando` crea un archivo o carpeta nuevo (touch, echo/cat con
    redirección '>'/'>>', mkdir -p), devuelve la ruta creada. None si no
    reconoce ningún patrón de creación."""
    coincidencia = (
        _PATRON_REDIRECCION_ARCHIVO.search(comando)
        or _PATRON_TOUCH.search(comando)
        or _PATRON_MKDIR.search(comando)
    )
    if not coincidencia:
        return None
    return os.path.expanduser(coincidencia.group(1).strip("'\""))


# Igual que arriba pero para DESCARGAS (BUG1: "descarga X de internet"
# puede caer aquí — a "ejecuta X arbitrario" — si no tiene función
# determinística propia como research_agent.py). Detecta wget -O/-o y
# curl -o/-O, los dos flags de salida más comunes que el modelo suele
# generar para bajar un archivo con nombre explícito.
_PATRON_WGET = re.compile(r"\bwget\b.*?-[Oo]\s+(\"[^\"]+\"|'[^']+'|\S+)")
_PATRON_CURL = re.compile(r"\bcurl\b.*?-[oO]\s+(\"[^\"]+\"|'[^']+'|\S+)")


def _extraer_ruta_descargada(comando):
    """Si `comando` descarga un archivo de internet (wget/curl con flag
    de salida explícita), devuelve la ruta de destino. None si no
    reconoce el patrón (ej. curl/wget sin -o, que solo imprime a
    stdout y no deja archivo que recordar)."""
    coincidencia = _PATRON_WGET.search(comando) or _PATRON_CURL.search(comando)
    if not coincidencia:
        return None
    return os.path.expanduser(coincidencia.group(1).strip("'\""))


def extraer_archivo_creado(accion):
    """Si `accion` (el dict de interpretar()/ejecutar_accion_confirmada)
    creó un archivo o carpeta nuevo, devuelve su ruta — usado por
    director.py para recordar "el último archivo creado". None si
    `accion` no es del tipo "comando" o no crea nada reconocible."""
    if not accion or accion.get("tipo") != "comando":
        return None
    return _extraer_ruta_creada(accion.get("comando") or "")


def extraer_archivo_descargado(accion):
    """Igual que extraer_archivo_creado pero para descargas (wget/curl,
    ver _extraer_ruta_descargada) — usado por director.py para
    recordar "el último archivo descargado" (BUG1, ver
    context_engine.set_ultimo_archivo_descargado)."""
    if not accion or accion.get("tipo") != "comando":
        return None
    return _extraer_ruta_descargada(accion.get("comando") or "")


def _ejecutar_accion(accion):
    """Ejecuta una acción ya parseada (dict con tipo/comando/descripcion)
    y devuelve el mensaje final para el usuario."""
    tipo = accion.get("tipo")
    comando = (accion.get("comando") or "").strip()
    descripcion = accion.get("descripcion") or comando

    if not comando:
        return "ERROR: el modelo no generó un comando para ejecutar."

    if tipo == "abrir_url":
        # No se ejecuta a ciegas el "xdg-open <url>" que generó el
        # modelo: xdg-open puede fallar en silencio (ver abrir_url).
        url = _extraer_url(comando) or comando
        if abrir_url(url):
            return descripcion
        return f"ERROR: no se pudo abrir '{url}' (revisa los logs de abrir_url)."

    if tipo in _TIPOS_LANZAR_DESATENDIDO:
        if _lanzar(comando, shell=True):
            return descripcion
        return f"ERROR: no se pudo ejecutar '{comando}'."

    # "comando" y "buscar_archivo" corren en primer plano (con límite
    # de 30s) porque el usuario espera ver su salida.
    asegurar_entorno_grafico()
    try:
        resultado = subprocess.run(
            comando, shell=True, capture_output=True, text=True, timeout=30,
        )
        texto = descripcion
        salida = resultado.stdout.strip()
        error = resultado.stderr.strip()
        if salida:
            texto += f"\n{salida[:1000]}"
        if error and resultado.returncode != 0:
            texto += f"\nError:\n{error[:1000]}"
        return texto
    except subprocess.TimeoutExpired:
        return "ERROR: el comando tardó más de 30s y se canceló."
    except Exception as e:
        return f"ERROR al ejecutar el comando: {e}"


def interpretar(mensaje_usuario):
    """Punto de entrada desde director.py: le pide a Gemini/Ollama el
    comando de Linux para lo que pidió el usuario y lo ejecuta directo
    si es seguro, o lo deja pendiente de confirmación si no.

    Devuelve {"requiere_confirmacion": bool, "mensaje": str, "accion": dict|None,
    "archivo_creado": str|None, "archivo_descargado": str|None}.
    `accion` solo viene poblado cuando requiere_confirmacion es True,
    para que director.py la guarde y la pase de vuelta a
    ejecutar_accion_confirmada() si el usuario escribe CONFIRMAR.
    """
    texto_crudo = _pedir_accion_al_modelo(mensaje_usuario)

    if texto_crudo.startswith("ERROR:"):
        return {"requiere_confirmacion": False, "mensaje": texto_crudo, "accion": None, "archivo_creado": None, "archivo_descargado": None}

    accion = _parsear_json_accion(texto_crudo)
    if not accion or not accion.get("comando"):
        log.error("control_agent: JSON inválido del modelo: %r", texto_crudo)
        return {
            "requiere_confirmacion": False,
            "mensaje": "ERROR: no entendí qué comando ejecutar (respuesta inválida del modelo).",
            "accion": None,
            "archivo_creado": None,
            "archivo_descargado": None,
        }

    # La decisión final no es del modelo (ver _decidir_confirmacion):
    # abrir cosas nunca confirma, y lo que borra/apaga/instala/mata
    # procesos siempre confirma, pase lo que pase en el JSON.
    if _decidir_confirmacion(accion.get("tipo"), accion["comando"], accion.get("requiere_confirmacion", True)):
        descripcion = accion.get("descripcion") or accion["comando"]
        mensaje = (
            f"¿Seguro que quieres que haga esto?\n{descripcion}\n`{accion['comando']}`\n"
            "Escribe CONFIRMAR para continuar o cualquier otra cosa para cancelar."
        )
        return {"requiere_confirmacion": True, "mensaje": mensaje, "accion": accion, "archivo_creado": None, "archivo_descargado": None}

    mensaje = _ejecutar_accion(accion)
    return {
        "requiere_confirmacion": False,
        "mensaje": mensaje,
        "accion": None,
        "archivo_creado": extraer_archivo_creado(accion),
        "archivo_descargado": extraer_archivo_descargado(accion),
    }


def ejecutar_accion_confirmada(accion):
    """Ejecuta una acción que ya fue confirmada por el usuario (ver
    director.py, que la guardó cuando interpretar() devolvió
    requiere_confirmacion=True)."""
    return _ejecutar_accion(accion)
