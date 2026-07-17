#!/bin/bash
# ============================================================
# GERAM OS v2 · reiniciar_geram.sh
# Fuerza un reinicio completo: mata cualquier server.py que esté
# corriendo y lo vuelve a levantar antes de abrir el HUD.
#
# Por qué existe aparte de abrir_geram.sh (el icono normal del
# escritorio): ese script solo arranca el servidor "si hace falta" —
# si ya está corriendo, simplemente abre el navegador y ya, sin
# reiniciar nada. Eso está bien para el uso diario, pero Python NO
# recarga los agentes solo porque el archivo cambió en disco — después
# de editar cualquier agente/director.py hay que matar el proceso
# viejo para que el código nuevo se cargue. Para eso es este script.
# ============================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://localhost:8010"

echo "Deteniendo GERAM OS si estaba corriendo..."
pkill -f "python3 server.py" 2>/dev/null
for i in $(seq 1 10); do
  pgrep -f "python3 server.py" >/dev/null 2>&1 || break
  sleep 1
done
# Por si algo se quedó pegado tras los 10s de espera.
pkill -9 -f "python3 server.py" 2>/dev/null

echo "Arrancando GERAM OS..."
nohup "$DIR/iniciar.sh" >> "$DIR/iniciar.log" 2>&1 &
disown

# Espera a que el servidor conteste antes de abrir el navegador (máx 20s)
for i in $(seq 1 20); do
  curl -s -m 1 "$URL" >/dev/null 2>&1 && break
  sleep 1
done

# Mismo orden que abrir_geram.sh: Firefox no está instalado en esta
# máquina (solo Brave), se cae a xdg-open si no se encuentra ninguno.
if command -v firefox >/dev/null 2>&1; then
  firefox "$URL" &
elif command -v brave-browser >/dev/null 2>&1; then
  brave-browser "$URL" &
else
  xdg-open "$URL" &
fi
