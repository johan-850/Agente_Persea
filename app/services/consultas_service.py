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

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import horario
from app.db.supabase_client import get_client
from app.horario import ZONA, hoy, limites_utc
from app.services import meta_whatsapp_service, modelo_ia, reporte_original_service
# Vive en admin_service; se importa aqui porque monitoreo_service y las
# pruebas lo buscan en este modulo.
from app.services.admin_service import es_administrador  # noqa: F401
from app.services.alertas_monitoreo_service import evaluar_alerta_monitoreo, normalizar
from app.services.resumen_service import reportes_por_lote

logger = logging.getLogger("consultas")

# Tope de filas por consulta. Evita que "todo lo de este mes" se coma el
# contexto del modelo y acabe en una respuesta cortada.
MAX_FILAS = 40

# Cuantas veces puede el modelo pedir datos antes de responder. Con dos rondas
# alcanza para preguntar por un lote y luego por sus fotos.
MAX_RONDAS = 3


# La API de Supabase devuelve como mucho mil filas por consulta, y corta sin
# avisar: una busqueda de varios meses responderia con las primeras mil como
# si fueran todas.
_PAGINA = 1000


def _desde(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, dias))).isoformat()


def _todas(armar) -> list[dict]:
    """Todas las filas de la consulta que arma `armar`, de mil en mil.

    `armar` devuelve la consulta nueva cada vez: el constructor de supabase-py
    acumula parametros, asi que no se puede reutilizar entre paginas.
    """
    filas: list[dict] = []
    while True:
        pagina = armar().range(len(filas), len(filas) + _PAGINA - 1).execute().data
        filas += pagina
        if len(pagina) < _PAGINA:
            return filas


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
    filas = _todas(
        lambda: get_client()
        .table("monitoreos")
        .select("fecha_hora, finca, lote, plagas_observadas, es_alerta")
        .gte("fecha_hora", _desde(dias))
        .order("fecha_hora", desc=True)
        .order("id", desc=True)
    )
    return _buscar_en(filas, plaga)


def _buscar_en(filas: list[dict], plaga: str) -> dict:
    """La busqueda sobre filas ya leidas, sin tildes ni mayusculas.

    Las monitoras escriben "acaro" y "ácaro" indistintamente, y la busqueda
    comparaba tal cual: "¿donde ha salido ácaro?" encontraba 22 apariciones
    y "acaro" 18, y cada una dejaba afuera a la otra.
    """
    termino = normalizar(str(plaga)).strip()
    encontrados = []
    for f in filas:
        coincide = [p for p in (f.get("plagas_observadas") or []) if termino in normalizar(str(p))]
        if coincide:
            encontrados.append({
                "dia": _dia_local(f["fecha_hora"]),
                "finca": f.get("finca"),
                "lote": f.get("lote"),
                "hallazgos": coincide,
                # Si alerta ESTA plaga, no si el reporte alerto por otra cosa:
                # con "poca poblacion de acaro" en un lote con stenoma, el
                # modelo contestaba que el acaro habia alertado.
                "alerta_por_esta_plaga": any(evaluar_alerta_monitoreo(str(h))[0] for h in coincide),
            })

    lotes = {f"{e['finca']} {e['lote']}" for e in encontrados}
    return {
        "apariciones": encontrados[:MAX_FILAS],
        "total_apariciones": len(encontrados),
        "lotes_distintos": sorted(lotes),
    }


def _actividad_por_finca(dias: int = 7) -> dict:
    filas = _todas(
        lambda: get_client()
        .table("monitoreos")
        .select("id, fecha_hora, finca, lote, es_alerta, plagas_observadas")
        .gte("fecha_hora", _desde(dias))
        .order("id")
    )
    return _actividad(filas)


def _actividad(filas: list[dict]) -> dict:
    """Por finca: reportes de lote, lotes distintos y cuantos alertaron.

    Cuenta como el resumen: el aviso de mediodia y el cierre del mismo lote,
    el mismo dia, son un reporte. Contaba mensajes, y a "¿cuanto llevamos
    hoy?" respondia 14 mientras el resumen de ese dia decia 9 lotes.
    """
    resumen: dict = defaultdict(lambda: {"reportes": 0, "lotes": set(), "alertas": 0})
    for f in reportes_por_lote(filas):
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


def _reportes_del_dia(fecha: str | None = None) -> dict:
    """Lo reportado en un dia, un registro por lote como en el resumen.

    El total va aparte de la lista, por lo mismo que en estado_de_lote: si la
    lista se recorta sin decirlo, el modelo cuenta lo que ve.
    """
    fecha = fecha or hoy()
    desde, hasta = limites_utc(fecha)
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, fecha_hora, finca, lote, tipo_labor, lote_finalizado, plagas_observadas, "
                "es_alerta, tipo_alerta, prioridad")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .execute()
        .data
    )
    lotes = sorted(reportes_por_lote(filas), key=lambda l: (str(l.get("finca") or ""), str(l.get("lote") or "")))
    campos = ("finca", "lote", "tipo_labor", "lote_finalizado", "plagas_observadas", "es_alerta")
    return {
        "lotes": [{c: l.get(c) for c in campos} for l in lotes[:MAX_FILAS]],
        "total_lotes": len(lotes),
        "con_alerta": sum(1 for l in lotes if l.get("es_alerta")),
    }


CONSULTAS = {
    "estado_de_lote": _estado_de_lote,
    "alertas_recientes": _alertas_recientes,
    "buscar_plaga": _buscar_plaga,
    "actividad_por_finca": _actividad_por_finca,
    "reportes_del_dia": _reportes_del_dia,
}

# Las que no solo leen: le mandan algo a quien pregunto, asi que reciben su
# numero. Mostrar el reporte original es una de estas porque el texto tiene que
# llegar tal cual; si volviera al modelo para que lo redacte, lo resumiria.
ACCIONES = {
    "mostrar_reporte_original": reporte_original_service.mostrar_por_lote,
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
            "Cuanto se monitoreo por finca: reportes de lote (uno por lote y dia, "
            "aunque lleguen el aviso de mediodia y el cierre), lotes distintos y "
            "cuantos alertaron. Para '¿cuanto llevamos esta semana?' o '¿que lotes "
            "se han visto?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"dias": {"type": "integer", "description": "7 por defecto."}},
        },
    },
    {
        "name": "reportes_del_dia",
        "description": (
            "Lo reportado en un dia concreto, un registro por lote, con el total "
            "de lotes y cuantos alertaron. Para '¿que entro hoy?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": ["string", "null"], "description": "AAAA-MM-DD. Null = hoy."}
            },
        },
    },
    {
        "name": "mostrar_reporte_original",
        "description": (
            "Le MANDA al administrador el reporte tal como lo escribio la monitora, "
            "con sus fotos. Para 'muestrame el reporte del 14', 'quiero ver el "
            "reporte original de la alerta de rivera', 'que escribio exactamente la "
            "monitora en el 8' o 'mandame las fotos del lote 3'. El envio lo hace "
            "la herramienta: tu solo confirmas en una linea."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lote": {"type": "string", "description": "Solo el numero, sin '#'."},
                "finca": {"type": ["string", "null"],
                          "description": "la linda, alfa, buena vista o rivera. Null si no la dicen."},
                "fecha": {"type": ["string", "null"],
                          "description": "AAAA-MM-DD. Null = el reporte mas reciente de ese lote."},
            },
            "required": ["lote"],
        },
    },
]

SYSTEM_PROMPT = """Eres el asistente de monitoreo de plagas de Agricola Persea,
una finca de aguacate Hass. Respondes por WhatsApp a los administradores, que
preguntan por lo que reportaron las monitoras en campo.

Las cuatro fincas son: la linda, alfa, buena vista y rivera.

Un numero suelto ("el 15", "el #8", "en el 3") es un lote, nunca una fecha:
asi hablan en campo. Si no dicen la finca, consulta sin ella en vez de
preguntarla; las herramientas buscan el lote en todas las fincas.

Para responder consulta los datos con las herramientas. Nunca inventes cifras
ni hallazgos: si la consulta no devuelve nada, dilo con esas palabras.

Al responder:
- Escribe para WhatsApp: pocas lineas, sin markdown de titulos, sin tablas.
  Puedes usar *negrita* de WhatsApp con un asterisco a cada lado.
- Ve directo al dato que preguntaron. Nada de "segun los registros consultados".
- Las plagas cuarentenarias del plan (Heilipus, Stenoma, Maconellicoccus,
  Pseudococcus, Ceroplastes, Saissetia) tienen umbral cero: si aparecen,
  dilo primero.
- Si piden ver el reporte original, completo, "lo que escribio la monitora" o
  las fotos de un lote, usa mostrar_reporte_original. La herramienta ya le
  manda el texto tal cual y las fotos: no lo repitas ni lo resumas, solo
  confirma en una linea que se envio (o di que no hay reporte de ese lote).
- Si la pregunta no se puede responder con los datos de monitoreo, dilo en una
  linea y menciona que si puedes consultar: estado de un lote, alertas
  recientes, donde ha salido una plaga, actividad por finca, lo reportado en
  un dia, y el reporte original de un lote con sus fotos. Recuerda que tambien
  pueden responder directamente a una alerta para ver su reporte.
- No mas de 1200 caracteres."""


_DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def _fecha_de_hoy() -> str:
    """Que dia es, dicho para el modelo, que por si solo no lo sabe.

    A "¿que entro el 30 de septiembre?" consulto el 30 de septiembre de 2024 y
    respondio que no habia reportes. Con "ayer" o "el lunes" pasaba lo mismo.
    """
    dia = horario.ahora()
    return (
        f"Hoy es {_DIAS_SEMANA[dia.weekday()]} {dia.day} de {horario.MESES[dia.month - 1]} "
        f"de {dia.year} ({dia.date().isoformat()}) en las fincas. Las fechas que te pidan "
        "('hoy', 'ayer', 'el lunes', 'el 30 de septiembre') se cuentan desde este dia, y "
        "una fecha sin año es la mas reciente que no este en el futuro."
    )


def responder(pregunta: str, remitente: str) -> str | None:
    """Contesta la pregunta de un administrador con datos de la base.

    Devuelve lo que respondio, o None si no se pudo.
    """

    def ejecutar(nombre: str, argumentos: dict) -> dict:
        logger.info("Consulta de %s: %s(%s)", remitente, nombre, argumentos)
        try:
            if nombre in ACCIONES:
                return ACCIONES[nombre](destinatario=remitente, **argumentos)
            return CONSULTAS[nombre](**argumentos)
        except Exception as error:
            # El modelo recibe el error y puede decirlo, en vez de inventar.
            logger.exception("Fallo la consulta %s", nombre)
            return {"error": str(error)}

    try:
        texto = modelo_ia.conversar_con_herramientas(
            f"{SYSTEM_PROMPT}\n\n{_fecha_de_hoy()}", pregunta, HERRAMIENTAS, ejecutar, max_rondas=MAX_RONDAS
        )
    except Exception:
        logger.exception("No se pudo responder la consulta de %s", remitente)
        return None

    if texto:
        return _enviar(texto, remitente)

    # Agoto las rondas o respondio en blanco. Antes el segundo caso quedaba en
    # silencio y el administrador no sabia si el bot lo habia leido.
    logger.warning("La consulta de %s quedo sin respuesta tras %d rondas", remitente, MAX_RONDAS)
    return _enviar(
        "No pude resolver esa consulta. Prueba con algo mas concreto, "
        "por ejemplo: ¿como va el lote 14 de rivera?",
        remitente,
    )


def _enviar(texto: str, remitente: str) -> str:
    try:
        meta_whatsapp_service.enviar_mensaje(remitente, texto)
    except Exception:
        logger.exception("No se pudo enviar la respuesta a %s", remitente)
    return texto
