#!/bin/bash
# ============================================================
# GERAM · lanzador UNIFICADO (desarrollador al frente)
# ------------------------------------------------------------
# Abre el entorno de DESARROLLO (GERAM CORE OS / A.R.E.S.) como app
# principal —su propia ventana Electron en el puerto 8000— y, en
# segundo plano, se asegura de que el asistente IRIS esté corriendo
# como complemento en el puerto 8010.
#
# Es el único icono del escritorio (GERAM). core-os no se toca: se
# lanza con su propio launcher tal cual.
# ============================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) IRIS (complemento) en 8010 — se arranca solo si no responde ya,
#    para no levantar una segunda instancia (autostart podría tenerlo
#    corriendo). No bloquea: queda en segundo plano.
if ! curl -s -m 2 http://localhost:8010/stats >/dev/null 2>&1; then
  nohup "$DIR/iniciar.sh" >> "$DIR/iniciar.log" 2>&1 &
  disown
fi

# 2) App de desarrollador AL FRENTE: su launcher arranca el backend en
#    8000 y abre la ventana Electron. exec para que GERAM sea ese proceso.
exec "$DIR/geram-core-os/iniciar_app.sh"
