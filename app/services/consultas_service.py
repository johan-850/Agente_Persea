"""Los administradores le preguntan al bot por los datos, en castellano.

Hasta ahora el historial solo se alcanzaba por la API REST, con una clave y
sin ninguna interfaz. Un administrador que quiere saber como va el lote 14 no
va a armar un curl: va a escribirle al mismo numero de WhatsApp por donde le
llegan las alertas.

El modelo NO escribe SQL. Se le dan unas pocas consultas ya escritas y
parametrizadas, y el elige cual usar y con que argumentos. Eso deja fuera por
construccion cualquier lectura de tablas que no sean estas, cualquier
escritura, y las consultas raras que tumban la base; y ademas hace el
comportamiento predecible, que en algo que responde por WhatsApp importa mas
que la flexibilidad.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.horario import ZONA, hoy, limites_utc
from app.services import meta_whatsapp_service
from app.services.anthropic_client import MODEL, get_client as get_cliente_ia

logger = logging.getLogger("consultas")

# Tope de filas por consulta. Evita que "todo lo de este mes" se coma el
# contexto del modelo y acabe en una respuesta cortada.
MAX_FILAS = 40

# Cuantas veces puede el modelo pedir datos antes de responder. Con dos rondas
# alcanza para preguntar por un lote y luego por sus fotos.
MAX_RONDAS = 3


def _desde(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, dias))).isoformat()


def _dia_local(fecha_hora) -> str:
    return datetime.fromisoformat(str(fecha_hora)).astimezone(ZONA).date().isoformat()


# --------------------------------------------------------------------------
# Las consultas. Cada una devuelve datos crudos; redactar es cosa del modelo.
# --------------------------------------------------------------------------


def _estado_de_lote(lote: str, finca: str | None = None, dias: int = 30) -> dict:
    consulta = (
        get_client()
        .table("monitoreos")
        .select("id, fecha_hora, finca, lote, tipo_labor, lote_finalizado, "
                "plagas_observadas, es_alerta, tipo_alerta")
        .eq("lote", str(lote))
        .gte("fecha_hora", _desde(dias))
    )
    if finca:
        consulta = consulta.ilike("finca", f"%{finca}%")

    filas = consulta.order("fecha_hora", desc=True).limit(MAX_FILAS).execute().data
    for f in filas:
        f["dia"] = _dia_local(f.pop("fecha_hora"))

    ids = [f["id"] for f in filas]
    fotos = []
    if ids:
        fotos = (
            get_client()
            .table("fotos")
            .select("monitoreo_id, es_alerta, motivo_alerta")
            .in_("monitoreo_id", ids)
            .execute()
            .data
        )

    con_dano = [f for f in fotos if f.get("es_alerta")]
    return {
        "reportes": filas,
        "fotos_totales": len(fotos),
        # El total va aparte de la muestra: si solo se manda la lista recortada,
        # el modelo cuenta los elementos que ve y responde ese numero. Con 14
        # fotos dañadas y una muestra de 10, contestaba "10 mostraron daño".
        "fotos_con_dano_total": len(con_dano),
        "muestra_de_fotos_con_dano": con_dano[:10],
    }


def _alertas_recientes(dias: int = 7, finca: str | None = None) -> dict:
    consulta = (
        get_client()
        .table("monitoreos")
        .select("fecha_hora, finca, lote, tipo_alerta, prioridad, plagas_observadas", count="exact")
        .eq("es_alerta", True)
        .gte("fecha_hora", _desde(dias))
    )
    if finca:
        consulta = consulta.ilike("finca", f"%{finca}%")

    resultado = consulta.order("fecha_hora", desc=True).limit(MAX_FILAS).execute()
    filas = resultado.data
    for f in filas:
        f["dia"] = _dia_local(f.pop("fecha_hora"))

    # El total va aparte por lo mismo que en estado_de_lote: si se recorta la
    # lista sin decirlo, el modelo cuenta lo que ve y responde de menos.
    return {"alertas": filas, "total": resultado.count or len(filas), "mostradas": len(filas)}


def _buscar_plaga(plaga: str, dias: int = 30) -> dict:
    """En que lotes aparecio esa plaga. El filtro fino se hace en memoria
    porque plagas_observadas es una lista jsonb y no se puede buscar dentro
    con un ilike."""
    filas = (
        get_client()
        .table("monitoreos")
        .select("fecha_hora, finca, lote, plagas_observadas, es_alerta")
        .gte("fecha_hora", _desde(dias))
        .order("fecha_hora", desc=True)
        .execute()
        .data
    )

    termino = str(plaga).lower()
    encontrados = []
    for f in filas:
        coincide = [p for p in (f.get("plagas_observadas") or []) if termino in str(p).lower()]
        if coincide:
            encontrados.append({
                "dia": _dia_local(f["fecha_hora"]),
                "finca": f.get("finca"),
                "lote": f.get("lote"),
                "hallazgos": coincide,
                "alerto": f.get("es_alerta"),
            })

    lotes = {f"{e['finca']} {e['lote']}" for e in encontrados}
    return {
        "apariciones": encontrados[:MAX_FILAS],
        "total_apariciones": len(encontrados),
        "lotes_distintos": sorted(lotes),
    }


def _actividad_por_finca(dias: int = 7) -> dict:
    filas = (
        get_client()
        .table("monitoreos")
        .select("fecha_hora, finca, lote, es_alerta")
        .gte("fecha_hora", _desde(dias))
        .execute()
        .data
    )

    resumen: dict = defaultdict(lambda: {"reportes": 0, "lotes": set(), "alertas": 0})
    for f in filas:
        entrada = resumen[f.get("finca") or "sin finca"]
        entrada["reportes"] += 1
        if f.get("lote"):
            entrada["lotes"].add(f["lote"])
        entrada["alertas"] += bool(f.get("es_alerta"))

    return {
        finca: {
            "reportes": d["reportes"],
            "lotes_distintos": len(d["lotes"]),
            "lotes": sorted(d["lotes"]),
            "alertas": d["alertas"],
        }
        for finca, d in resumen.items()
    }


def _reportes_del_dia(fecha: str | None = None) -> list[dict]:
    fecha = fecha or hoy()
    desde, hasta = limites_utc(fecha)
    filas = (
        get_client()
        .table("monitoreos")
        .select("finca, lote, tipo_labor, lote_finalizado, plagas_observadas, es_alerta")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .order("finca")
        .limit(MAX_FILAS)
        .execute()
        .data
    )
    return filas


CONSULTAS = {
    "estado_de_lote": _estado_de_lote,
    "alertas_recientes": _alertas_recientes,
    "buscar_plaga": _buscar_plaga,
    "actividad_por_finca": _actividad_por_finca,
    "reportes_del_dia": _reportes_del_dia,
}

HERRAMIENTAS = [
    {
        "name": "estado_de_lote",
        "description": (
            "Que se ha reportado en un lote: fechas, labor, hallazgos, si alerto "
            "y cuantas fotos mostraron daño. Para preguntas como '¿como va el lote "
            "14?' o '¿que paso en el 18 de rivera?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lote": {"type": "string", "description": "Solo el numero, sin '#'."},
                "finca": {"type": ["string", "null"],
                          "description": "la linda, alfa, buena vista o rivera. Null si no la dicen."},
                "dias": {"type": "integer", "description": "Hacia atras. 30 por defecto."},
            },
            "required": ["lote"],
        },
    },
    {
        "name": "alertas_recientes",
        "description": (
            "Las alertas de los ultimos dias, con finca, lote y motivo. Para "
            "'¿que alertas hubo esta semana?' o '¿hay algo urgente en alfa?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {"type": "integer", "description": "7 por defecto."},
                "finca": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "buscar_plaga",
        "description": (
            "En que lotes aparecio una plaga y cuantas veces. Para '¿donde ha "
            "salido stenoma?' o '¿seguimos con heilipus en rivera?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plaga": {"type": "string", "description": "Nombre o parte del nombre."},
                "dias": {"type": "integer", "description": "30 por defecto."},
            },
            "required": ["plaga"],
        },
    },
    {
        "name": "actividad_por_finca",
        "description": (
            "Cuanto se monitoreo por finca: reportes, lotes distintos y alertas. "
            "Para '¿cuanto llevamos esta semana?' o '¿que lotes se han visto?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"dias": {"type": "integer", "description": "7 por defecto."}},
        },
    },
    {
        "name": "reportes_del_dia",
        "description": "Todo lo reportado en un dia concreto. Para '¿que entro hoy?'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": ["string", "null"], "description": "AAAA-MM-DD. Null = hoy."}
            },
        },
    },
]

SYSTEM_PROMPT = """Eres el asistente de monitoreo de plagas de Agricola Persea,
una finca de aguacate Hass. Respondes por WhatsApp a los administradores, que
preguntan por lo que reportaron las monitoras en campo.

Las cuatro fincas son: la linda, alfa, buena vista y rivera.

Para responder consulta los datos con las herramientas. Nunca inventes cifras
ni hallazgos: si la consulta no devuelve nada, dilo con esas palabras.

Al responder:
- Escribe para WhatsApp: pocas lineas, sin markdown de titulos, sin tablas.
  Puedes usar *negrita* de WhatsApp con un asterisco a cada lado.
- Ve directo al dato que preguntaron. Nada de "segun los registros consultados".
- Las plagas cuarentenarias del plan (Heilipus, Stenoma, Maconellicoccus,
  Pseudococcus, Ceroplastes, Saissetia) tienen umbral cero: si aparecen,
  dilo primero.
- Si la pregunta no se puede responder con los datos de monitoreo, dilo en una
  linea y menciona que si puedes consultar: estado de un lote, alertas
  recientes, donde ha salido una plaga, actividad por finca y lo reportado en
  un dia.
- No mas de 1200 caracteres."""


def es_administrador(remitente: str) -> bool:
    """Si ese numero esta en la tabla de administradores, activo."""
    numero = "".join(c for c in str(remitente) if c.isdigit())
    if not numero:
        return False
    try:
        filas = get_client().table("administradores").select("numero").eq("activo", True).execute().data
    except Exception:
        logger.exception("No se pudo comprobar si %s es administrador", remitente)
        return False

    return any("".join(c for c in str(f["numero"]) if c.isdigit()) == numero for f in filas)


def responder(pregunta: str, remitente: str) -> str | None:
    """Contesta la pregunta de un administrador con datos de la base.

    Devuelve lo que respondio, o None si no se pudo.
    """
    mensajes = [{"role": "user", "content": pregunta}]

    try:
        for _ in range(MAX_RONDAS):
            respuesta = get_cliente_ia().messages.create(
                model=MODEL,
                max_tokens=1200,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=mensajes,
                tools=HERRAMIENTAS,
            )

            if respuesta.stop_reason != "tool_use":
                texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
                return _enviar(texto, remitente) if texto else None

            mensajes.append({"role": "assistant", "content": respuesta.content})
            resultados = []
            for bloque in respuesta.content:
                if bloque.type != "tool_use":
                    continue
                logger.info("Consulta de %s: %s(%s)", remitente, bloque.name, bloque.input)
                try:
                    datos = CONSULTAS[bloque.name](**bloque.input)
                except Exception as error:
                    logger.exception("Fallo la consulta %s", bloque.name)
                    datos = {"error": str(error)}
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": json.dumps(datos, ensure_ascii=False, default=str),
                })
            mensajes.append({"role": "user", "content": resultados})

        logger.warning("La consulta de %s no se resolvio en %d rondas", remitente, MAX_RONDAS)
        return _enviar(
            "No pude resolver esa consulta. Prueba con algo mas concreto, "
            "por ejemplo: ¿como va el lote 14 de rivera?",
            remitente,
        )
    except Exception:
        logger.exception("No se pudo responder la consulta de %s", remitente)
        return None


def _enviar(texto: str, remitente: str) -> str:
    try:
        meta_whatsapp_service.enviar_mensaje(remitente, texto)
    except Exception:
        logger.exception("No se pudo enviar la respuesta a %s", remitente)
    return texto
