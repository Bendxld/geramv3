# Guion reproducible de demostración

Este guion demuestra los dos flujos aprobados sin credenciales reales, sin
providers externos y sin modificar archivos del producto. El servidor Uvicorn,
los endpoints, Workspace Service, Bubblewrap y Terminal Watcher son reales; el
único provider se sustituye dentro del proceso de demo por una respuesta
sintética determinista.

## Preparación

Desde la raíz del repositorio:

```bash
test "$(uname -s)" = Linux
test -x ./venv/bin/python
test -x /usr/bin/bwrap
/usr/bin/bwrap --version
./venv/bin/python launcher.py status
git status --short --branch
```

Si el launcher informa que GERAM está iniciado, detenerlo antes de la demo para
evitar confundir procesos:

```bash
./venv/bin/python launcher.py stop
```

## Demostración guiada

Ejecutar:

```bash
./venv/bin/python scripts/build_week_demo.py
```

El guion imprime y verifica, en este orden:

1. arranque de un servidor real en `127.0.0.1` y respuesta del health check;
2. creación de una propuesta sobre `smoke_edit.py` en un directorio temporal;
3. diff unificado visible mientras el archivo conserva el contenido base;
4. respuesta `409 proposal_not_approved` al intentar apply sin aprobación;
5. aprobación explícita como petición independiente, todavía sin escritura;
6. apply con token de un uso y cambio esperado del archivo;
7. `409 version_conflict` si el archivo base cambia antes del apply, sin pisar el
   contenido local;
8. ejecución de `test_smoke_runner.py` mediante Bubblewrap, con red del host
   inaccesible y `cleanup_status: clean`;
9. rechazo de `.env.py` antes de iniciar un proceso;
10. `sandbox_unavailable` y `cleanup_status: not_started` cuando se simula la
    ausencia de Bubblewrap;
11. restauración y eliminación de archivos/directorios temporales y ausencia del
    proceso descendiente sintético.

No se imprimen tokens de aprobación. El fallo de Bubblewrap se simula sólo en el
servidor temporal del guion; no se renombra ni desinstala `/usr/bin/bwrap`.

## Assurance repetible

Después de la narración, ejecutar dos veces el smoke integral, que añade
contratos estrictos, origen local, reinicio, capacidad de 32 propuestas y
carreras de apply/cancel:

```bash
./venv/bin/python -m unittest -v tests.test_ares_server_smoke
./venv/bin/python -m unittest -v tests.test_ares_server_smoke
```

La salida esperada en cada ronda termina en `OK` con una prueba ejecutada.

El smoke sintético es la demostración reproducible de arranque, edición y runner
sin red. El arranque canónico del producto se documenta en `README.md`; usar el
HUD para generar una propuesta real requiere un provider configurado y por tanto
queda fuera de este guion offline.
