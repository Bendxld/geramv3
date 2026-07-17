# GERAM CORE OS — Build Week Definition of Done

Actualizado: 2026-07-15. Este documento registra evidencia observada; no declara
que el producto ni la entrega estén terminados.

Estados: **comprobado**, **pendiente**, **bloqueado**, **no iniciado**.

## Producto

| Punto | Estado | Evidencia o condición pendiente |
|---|---|---|
| Lanzador distingue GERAM CORE OS del `server.py` antiguo | comprobado | `tests/test_launcher.py`; `python -m unittest -v tests.test_launcher` (15 pruebas) |
| Aplicación abre confiablemente | comprobado | Launcher Linux Mint validado desde `.desktop`: puerto libre, backend existente, puerto ajeno, segundo clic sin duplicado, cierre/reapertura y cleanup; smoke Electron temporal previo `105`/`106`/`107` |
| Configuración de proveedores funciona | comprobado | `tests/test_provider_configuration.py`; suite Python de 141 pruebas previa a Monaco |
| Gestión segura de múltiples credenciales | comprobado | `tests/test_credential_pool.py`; suite Python de 141 pruebas previa a Monaco |
| A.R.E.S. puede leer y modificar archivos dentro del workspace permitido | comprobado | `tests/test_ares_edits.py` (23 pruebas) y smoke HTTP real: diff previo, aprobación/aplicación separadas, digest, token de un uso, expiración, conflicto, carreras, rollback y error explícito si también falla la restauración |
| Monaco permite explorar y editar archivos | comprobado | Smoke Electron `105`: árbol filtrado, Python/JavaScript, modelos, guardado por botón y Ctrl+S, conflicto, vacío, binario, temas, resize y fallback; repeticiones normales `106`/`107` sin errores |
| Terminal Watcher captura stdout, stderr, comando y resultado | comprobado | `tests/test_terminal_watcher.py` (7 pruebas); timeout y cancelación reportan motivo y cleanup, salida UTF-8 acotada/sanitizada y el perfil `python_unittest` no hace spawn sin prefijo Bubblewrap validado |
| Sandbox Guard bloquea comandos o rutas no autorizadas | comprobado | `app/core/sandbox_guard.py`, `tests/test_sandbox_guard.py` (5 pruebas); target Python canónico/existente, traversal, flags, sensibles y symlinks externos fallan cerrados; symlink interno a `.py` permanece permitido |
| Sandbox Tester verifica aislamiento adversarial | pendiente | El smoke real prueba que el unittest no alcanza el puerto del host bajo `--unshare-all` y sin `--share-net`; siguen pendientes cuotas kernel/cgroup para procesos y memoria |
| Test Runner mínimo funcional | comprobado | Sólo `python_unittest`; argv/cwd/env/mounts son internos, Bubblewrap confiable es obligatorio, `--` cierra flags y no existe fallback al host |
| Aislamiento adversarial completo del Test Runner | pendiente | `tests/test_ares_test_runner.py` y smoke real cubren secretos, sensibles, red host, symlinks, timeout, cancelación, descendientes resistentes y proceso ajeno intacto; faltan límites efectivos de fork/CPU/memoria |
| Integración A.R.E.S. → Test Runner | comprobado | `POST /api/ares/tests`; 10 pruebas adversariales y dos rondas de servidor real con Bubblewrap. Contrato/origin estrictos, sólo `python_unittest`, fail-closed sin backend y cleanup sin procesos residuales |
| Git muestra diff antes de confirmar cambios | comprobado | `POST /api/ares/proposals` genera en servidor un diff unificado estilo Git, sanitizado y acotado, antes de habilitar aprobación; el digest liga exactamente diff, archivos y contenido propuesto |
| Commits requieren aprobación explícita del usuario | no iniciado | No existe evidencia de una función de producto dedicada |

## Calidad y seguridad

| Punto | Estado | Evidencia o condición pendiente |
|---|---|---|
| Todas las pruebas automatizadas pasan | comprobado | Validación final 2026-07-15: foco edición/runner 33/33, smoke real 1/1 dos veces (6.120 s y 6.205 s), suite Python 204/204 y demo sintética 11/11; no hay `pytest` ni script Node de pruebas |
| No hay secretos registrados en Git | comprobado | Escaneo de worktree y staged 2026-07-15: claves privadas, AWS, GitHub, OpenAI, Google y Slack, cero coincidencias |
| No se exponen secretos en logs, errores, navegador o almacenamiento | comprobado | El router A.R.E.S. sanitiza también errores 422 sin reflejar `input`; auditoría sólo guarda estado/actor/fecha, el token se almacena como digest y el smoke confirma ausencia de secretos sintéticos y rutas absolutas |
| Servicios locales validan host/origin | comprobado | `tests/test_security.py`, `tests/test_workspace.py` y tests Electron de política loopback |
| No existen errores importantes en consola | comprobado | Smoke `105`: sólo respuestas 415/409 esperadas, bloqueo CSP externo esperado y una cancelación interna de modelo; `106`/`107`: cero errores, excepciones o fallos de red |
| Worktree final limpio | comprobado | Verificación posterior al commit único registrada en el reporte de entrega; no se usaron reset, clean, amend, rebase ni descarte de cambios |
| Demo completa funciona tres veces consecutivas | pendiente | El guion terminal pasó una vez y el smoke real dos veces; aún falta una demo completa del HUD validada por otra persona |
| Otra persona instala y prueba usando sólo README | no iniciado | Sin evidencia de instalación independiente |

## Entrega

| Punto | Estado | Evidencia o condición pendiente |
|---|---|---|
| README completo | comprobado | Requisitos Linux/Bubblewrap, instalación, launcher de un worker, `unittest`, flujos fail-closed y riesgos documentados; falta validación independiente por otra persona |
| Plataformas compatibles documentadas | comprobado | Aplicación orientada a Linux; Test Runner explícitamente limitado a Linux con Bubblewrap y namespaces disponibles |
| Método sencillo para jueces | comprobado | `docs/BUILD_WEEK_DEMO.md` y `scripts/build_week_demo.py` ejecutan una demo sintética local, sin credenciales ni red externa, con cleanup verificado |
| Licencia apropiada | pendiente | Monaco conserva MIT y avisos; falta decisión/licencia global del proyecto |
| Video público menor de tres minutos | no iniciado | Sin evidencia |
| Video muestra el producto funcionando | no iniciado | Sin evidencia |
| Video explica uso de Codex y GPT-5.6 | no iniciado | Sin evidencia |
| Session ID de `/feedback` guardado | no iniciado | Sin evidencia |
| Descripción Devpost completa | no iniciado | Sin evidencia |
| Campos Developer Tools incluyen instalación y pruebas | no iniciado | Sin evidencia |
| Tag o release final | no iniciado | Sin evidencia |
| Entrega enviada y enlaces verificados | no iniciado | Sin evidencia |
