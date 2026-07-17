# ============================================================
# GERAM OS v2 · finance_agent.py
# Finanzas personales completas de Mauri (no solo un negocio): toda
# entrada/salida de dinero, guardada en Notion (database
# NOTION_FINANZAS_DB_ID) — igual que pendientes_agent.py, y a
# diferencia de memory.py/reminder_agent.py, que siguen en Supabase.
# Mismo patrón de properties auto-creadas que pendientes_agent (ver
# _asegurar_propiedades): Tipo/Categoría son "select" de texto libre
# (Notion crea la opción sola si no existe), así que categorías nuevas
# no rompen nada, igual que antes con la columna libre de Supabase.
# ============================================================

import calendar
import logging
from datetime import date, timedelta

import config
from agents import notion_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finance_agent")

# Semana (lunes en ISO) para la que ya se avisó el límite de gasto —
# compartido entre la vía reactiva (director._procesar_finanzas, en cada
# gasto nuevo) y la vía proactiva (proactividad_agent, cada 5 min): la
# que dispare primero "gana" la semana, para no avisar el mismo límite
# dos veces.
_semana_avisada = None

# Categorías predefinidas, solo como referencia/sugerencia para el
# parser de lenguaje natural (director._PROMPT_PARSEAR_FINANZAS) y
# como opciones iniciales del select "Categoría" en Notion — el
# usuario puede usar categorías nuevas que no estén aquí sin que nada
# se rompa (Notion agrega la opción sola al escribir la página).
CATEGORIAS_INGRESO = ("negocio", "trabajo", "mesada", "otro")
CATEGORIAS_GASTO = ("comida", "transporte", "materiales", "escuela", "gym", "ropa", "entretenimiento", "negocio_inversion", "otro")

# Definición de las properties que este agente necesita en el database
# de Notion. asegurar_propiedades_database() solo agrega las que
# falten, nunca pisa una que el usuario ya tenga configurada.
_PROPIEDADES_REQUERIDAS = {
    "Tipo": {
        "select": {
            "options": [
                {"name": "ingreso", "color": "green"},
                {"name": "gasto", "color": "red"},
            ]
        }
    },
    "Monto": {"number": {"format": "number"}},
    "Categoría": {
        "select": {
            "options": [{"name": c} for c in dict.fromkeys(CATEGORIAS_INGRESO + CATEGORIAS_GASTO)]
        }
    },
    "Descripción": {"rich_text": {}},
    "Fecha": {"date": {}},
    "Instancia": {"rich_text": {}},
}


def _asegurar_propiedades():
    resultado = notion_agent.asegurar_propiedades_database(config.NOTION_FINANZAS_DB_ID, _PROPIEDADES_REQUERIDAS)
    if resultado.get("error"):
        log.error("finance_agent: no se pudieron preparar las properties del database (%s)", resultado["error"])
    return resultado


def _rango_mes(mes=None):
    """(desde, hasta) en ISO de un mes del año ACTUAL (mes=None -> el
    mes en curso; 1-12 para otro mes de este mismo año)."""
    hoy = date.today()
    numero_mes = mes or hoy.month
    primer_dia = date(hoy.year, numero_mes, 1)
    ultimo_dia = date(hoy.year, numero_mes, calendar.monthrange(hoy.year, numero_mes)[1])
    return primer_dia.isoformat(), ultimo_dia.isoformat()


def _rango_semana():
    """(desde, hasta) en ISO de la semana actual (lunes a domingo)."""
    hoy = date.today()
    inicio = hoy - timedelta(days=hoy.weekday())
    fin = inicio + timedelta(days=6)
    return inicio.isoformat(), fin.isoformat()


def _texto_de(propiedad):
    """Extrae el texto plano de una property rich_text cruda de Notion
    (lista de fragmentos), o "" si está vacía/ausente."""
    fragmentos = (propiedad or {}).get("rich_text", [])
    return "".join(f.get("plain_text", "") for f in fragmentos)


def _pagina_a_movimiento(pagina):
    """Convierte una 'page' cruda de Notion al mismo shape de dict que
    antes devolvía la fila de Supabase: {"tipo","cantidad","categoria",
    "descripcion","fecha"} — para no tener que tocar el resto de este
    archivo, que ya sabe trabajar con ese shape."""
    props = pagina.get("properties", {})
    tipo = ((props.get("Tipo") or {}).get("select") or {}).get("name", "gasto")
    cantidad = (props.get("Monto") or {}).get("number") or 0
    categoria = ((props.get("Categoría") or {}).get("select") or {}).get("name", "otro")
    descripcion = _texto_de(props.get("Descripción"))
    fecha = ((props.get("Fecha") or {}).get("date") or {}).get("start", "")
    return {"tipo": tipo, "cantidad": cantidad, "categoria": categoria, "descripcion": descripcion, "fecha": fecha}


def _movimientos_entre(desde, hasta):
    """Todos los movimientos (cualquier instancia) con fecha en
    [desde, hasta]. Devuelve la lista o {"error": "..."}."""
    if not config.NOTION_FINANZAS_DB_ID:
        return {"error": "falta NOTION_FINANZAS_DB_ID en .env"}

    filtro = {"and": [
        {"property": "Fecha", "date": {"on_or_after": desde}},
        {"property": "Fecha", "date": {"on_or_before": hasta}},
    ]}
    resultados = notion_agent.consultar_database(config.NOTION_FINANZAS_DB_ID, filtro=filtro)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados
    return [_pagina_a_movimiento(p) for p in resultados]


def _registrar_movimiento(tipo, cantidad, descripcion, categoria):
    if not config.NOTION_FINANZAS_DB_ID:
        return {"error": "falta NOTION_FINANZAS_DB_ID en .env"}

    aseguradas = _asegurar_propiedades()
    if aseguradas.get("error"):
        return {"error": f"no pude preparar el database de Notion: {aseguradas['error']}"}

    descripcion = descripcion or ""
    categoria = categoria or "otro"
    hoy = date.today().isoformat()
    titulo = descripcion.strip() or f"{tipo} {cantidad}"

    propiedades_extra = {
        "Tipo": {"select": {"name": tipo}},
        "Monto": {"number": float(cantidad)},
        "Categoría": {"select": {"name": categoria}},
        "Descripción": {"rich_text": [{"type": "text", "text": {"content": descripcion[:2000]}}]},
        "Fecha": {"date": {"start": hoy}},
        "Instancia": {"rich_text": [{"type": "text", "text": {"content": config.INSTANCE_NAME or ""}}]},
    }
    resultado = notion_agent.crear_pagina_con_propiedades(config.NOTION_FINANZAS_DB_ID, titulo=titulo, propiedades_extra=propiedades_extra)
    if resultado.get("error"):
        log.error("finance_agent: no se pudo registrar el movimiento (%s)", resultado["error"])
        return {"error": resultado["error"]}

    return {
        "id": resultado["id"], "tipo": tipo, "cantidad": float(cantidad),
        "categoria": categoria, "descripcion": descripcion, "fecha": hoy,
    }


def registrar_ingreso(cantidad, descripcion, categoria="otro"):
    """"Me cayeron 500 de las aguas" -> registra un ingreso. Devuelve
    la fila creada (con "id") o {"error": "..."}."""
    return _registrar_movimiento("ingreso", cantidad, descripcion, categoria)


def registrar_gasto(cantidad, descripcion, categoria="otro"):
    """"Gasté 200 en jamaica" -> registra un gasto. Devuelve la fila
    creada (con "id") o {"error": "..."}."""
    return _registrar_movimiento("gasto", cantidad, descripcion, categoria)


def balance_actual():
    """Ingresos - gastos del MES ACTUAL. Devuelve un float, o
    {"error": "..."} si Notion falla."""
    movimientos = _movimientos_entre(*_rango_mes())
    if isinstance(movimientos, dict):
        return movimientos
    ingresos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "ingreso")
    gastos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "gasto")
    return round(ingresos - gastos, 2)


def balance_actual_texto():
    balance = balance_actual()
    if isinstance(balance, dict):
        return f"No pude calcular tu balance: {balance['error']}"
    if balance < 0:
        return f"Vas en números rojos este mes: -${abs(balance):.2f}, jefe."
    return f"Tu balance de este mes es ${balance:.2f}, jefe."


def resumen_mes(mes=None):
    """Resumen del mes (mes=None -> el actual, o 1-12 para otro mes de
    este año): total ingresos, total gastos, balance, y desglose por
    tipo:categoría. Devuelve dict o {"error": "..."}."""
    desde, hasta = _rango_mes(mes)
    movimientos = _movimientos_entre(desde, hasta)
    if isinstance(movimientos, dict):
        return movimientos

    total_ingresos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "ingreso")
    total_gastos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "gasto")

    desglose = {}
    for m in movimientos:
        clave = f"{m['tipo']}:{m['categoria']}"
        desglose[clave] = desglose.get(clave, 0) + m["cantidad"]

    return {
        "desde": desde, "hasta": hasta,
        "total_ingresos": round(total_ingresos, 2),
        "total_gastos": round(total_gastos, 2),
        "balance": round(total_ingresos - total_gastos, 2),
        "desglose": {k: round(v, 2) for k, v in desglose.items()},
    }


def _resumen_periodo_texto(resumen, etiqueta):
    if isinstance(resumen, dict) and resumen.get("error"):
        return f"No pude armar el resumen: {resumen['error']}"

    lineas = [
        f"Resumen de {etiqueta} ({resumen['desde']} a {resumen['hasta']}):",
        f"Ingresos: ${resumen['total_ingresos']:.2f}",
        f"Gastos: ${resumen['total_gastos']:.2f}",
        f"Balance: ${resumen['balance']:.2f}",
    ]
    if resumen["desglose"]:
        lineas.append("\nPor categoría:")
        for clave, monto in sorted(resumen["desglose"].items(), key=lambda kv: -kv[1]):
            tipo, categoria = clave.split(":", 1)
            signo = "+" if tipo == "ingreso" else "-"
            lineas.append(f"  {signo}${monto:.2f} {categoria}")
    return "\n".join(lineas)


def resumen_mes_texto(mes=None):
    return _resumen_periodo_texto(resumen_mes(mes), "este mes")


def resumen_semana():
    """Igual que resumen_mes() pero de la semana actual (lunes a domingo)."""
    desde, hasta = _rango_semana()
    movimientos = _movimientos_entre(desde, hasta)
    if isinstance(movimientos, dict):
        return movimientos

    total_ingresos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "ingreso")
    total_gastos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "gasto")
    desglose = {}
    for m in movimientos:
        clave = f"{m['tipo']}:{m['categoria']}"
        desglose[clave] = desglose.get(clave, 0) + m["cantidad"]

    return {
        "desde": desde, "hasta": hasta,
        "total_ingresos": round(total_ingresos, 2),
        "total_gastos": round(total_gastos, 2),
        "balance": round(total_ingresos - total_gastos, 2),
        "desglose": {k: round(v, 2) for k, v in desglose.items()},
    }


def resumen_semana_texto():
    return _resumen_periodo_texto(resumen_semana(), "esta semana")


def historial(limite=20):
    """Últimos `limite` movimientos (cualquier instancia), más
    recientes primero. Devuelve la lista o {"error": "..."}."""
    if not config.NOTION_FINANZAS_DB_ID:
        return {"error": "falta NOTION_FINANZAS_DB_ID en .env"}

    ordenar_por = [
        {"property": "Fecha", "direction": "descending"},
        {"timestamp": "created_time", "direction": "descending"},
    ]
    resultados = notion_agent.consultar_database(config.NOTION_FINANZAS_DB_ID, ordenar_por=ordenar_por)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados
    return [_pagina_a_movimiento(p) for p in resultados[:limite]]


def historial_texto(limite=20):
    movimientos = historial(limite)
    if isinstance(movimientos, dict):
        return f"No pude leer tu historial: {movimientos['error']}"
    if not movimientos:
        return "No tienes movimientos registrados, jefe."

    lineas = []
    for m in movimientos:
        signo = "+" if m["tipo"] == "ingreso" else "-"
        lineas.append(f"{m['fecha']}: {signo}${m['cantidad']:.2f} {m['categoria']} — {m['descripcion']}")
    return "Tu historial reciente:\n" + "\n".join(lineas)


def ganancia_negocio(nombre_negocio=None):
    """Ingresos - gastos de categoría 'negocio'/'negocio_inversion' de
    TODO el historial (no solo el mes). No hay un campo de "negocio"
    separado, así que si se da `nombre_negocio` se filtra además por
    descripción (ej. "aguas", "ropa") para separar negocios entre sí.
    Devuelve {"ingresos","gastos","ganancia_neta","movimientos"} o
    {"error": "..."}."""
    if not config.NOTION_FINANZAS_DB_ID:
        return {"error": "falta NOTION_FINANZAS_DB_ID en .env"}

    filtro_categoria = {"or": [
        {"property": "Categoría", "select": {"equals": "negocio"}},
        {"property": "Categoría", "select": {"equals": "negocio_inversion"}},
    ]}
    filtro = filtro_categoria
    if nombre_negocio:
        filtro = {"and": [filtro_categoria, {"property": "Descripción", "rich_text": {"contains": nombre_negocio}}]}

    resultados = notion_agent.consultar_database(config.NOTION_FINANZAS_DB_ID, filtro=filtro)
    if isinstance(resultados, dict) and resultados.get("error"):
        return resultados

    movimientos = [_pagina_a_movimiento(p) for p in resultados]
    ingresos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "ingreso")
    gastos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "gasto")
    return {
        "ingresos": round(ingresos, 2),
        "gastos": round(gastos, 2),
        "ganancia_neta": round(ingresos - gastos, 2),
        "movimientos": len(movimientos),
    }


def ganancia_negocio_texto(nombre_negocio=None):
    resultado = ganancia_negocio(nombre_negocio)
    if isinstance(resultado, dict) and resultado.get("error"):
        return f"No pude calcular la ganancia: {resultado['error']}"
    nombre = f" de {nombre_negocio}" if nombre_negocio else " de tus negocios"
    return (
        f"Ganancia neta{nombre}: ${resultado['ganancia_neta']:.2f} "
        f"(ingresos ${resultado['ingresos']:.2f}, gastos ${resultado['gastos']:.2f}, "
        f"{resultado['movimientos']} movimientos)."
    )


def alerta_gastos():
    """Si los gastos de la semana ACTUAL superan config.ALERTA_GASTO_SEMANAL
    Y no se ha avisado ya esa semana, devuelve el texto de aviso (y marca
    la semana como avisada); si no se pasó del límite, ya se avisó esta
    semana, o no hay umbral/Notion falla, devuelve None."""
    global _semana_avisada
    umbral = config.ALERTA_GASTO_SEMANAL
    if not umbral:
        return None

    desde, hasta = _rango_semana()
    movimientos = _movimientos_entre(desde, hasta)
    if isinstance(movimientos, dict):
        return None

    gastos = sum(m["cantidad"] for m in movimientos if m["tipo"] == "gasto")
    if gastos > umbral and _semana_avisada != desde:
        _semana_avisada = desde
        return f"Jefe, llevas ${gastos:.2f} gastados esta semana, te pasaste del límite de ${umbral:.2f}."
    return None


def resumen_para_briefing():
    """Texto corto para daily_briefing_agent: gasto de la semana +
    balance del mes. Nunca lanza excepción, degrada con texto claro si
    Notion falla."""
    movimientos_semana = _movimientos_entre(*_rango_semana())
    balance = balance_actual()
    if isinstance(movimientos_semana, dict) or isinstance(balance, dict):
        return "no disponible (Notion con error)"

    gastos_semana = sum(m["cantidad"] for m in movimientos_semana if m["tipo"] == "gasto")
    return f"llevas ${gastos_semana:.2f} gastados esta semana, tu balance del mes es ${balance:.2f}"
