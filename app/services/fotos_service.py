"""Procesa las fotos que llegan por WhatsApp: las archiva, las describe y las
liga al reporte al que pertenecen.
"""

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.horario import cuando_legible
from app.services import (
    envios_service,
    meta_whatsapp_service,
    storage_service,
    vision_service,
)
from app.services.alertas_monitoreo_service import DANOS_RELEVANTES, evaluar_dano_en_foto

logger = logging.getLogger("fotos")

TIPO_PREGUNTA_FOTOS = "pregunta_lote_foto"

# Las monitoras mandan la foto en un mensaje aparte del texto, casi siempre
# seguido. Se busca el ultimo reporte de esa misma persona en esta ventana.
VENTANA_ASOCIACION = timedelta(hours=2)

# Una monitora manda varias fotos seguidas del mismo lote. Avisar por cada una
# convierte un hallazgo en cinco mensajes seguidos y el administrador deja de
# leerlos: un lote llego a disparar tres avisos en cuatro minutos. Dentro de
# esta ventana se avisa una vez y las demas fotos quedan registradas en la
# base, donde se pueden consultar todas juntas.
VENTANA_AVISO_REPETIDO = timedelta(minutes=30)

# Cuando llegan fotos sueltas y esa persona reporto varios lotes seguidos, la
# heuristica no tiene forma de saber a cual pertenecen: se las cuelga todas al
# ultimo. Un dia las 25 fotos de la jornada acabaron en el lote 15. En vez de
# adivinar se pregunta, una sola vez por tanda.
VENTANA_PREGUNTA_FOTOS = timedelta(minutes=30)

EXTENSIONES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _limpiar_para_nombre(valor: str | None, defecto: str) -> str:
    if not valor:
        return defecto
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", str(valor).lower())
        if unicodedata.category(c) != "Mn"
    )
    limpio = re.sub(r"[^a-z0-9]+", "-", sin_tildes).strip("-")
    return limpio or defecto


def _monitoreo_relacionado(remitente: str, momento: datetime) -> dict | None:
    """Ultimo reporte del mismo remitente en las dos horas previas a la foto.

    Es una heuristica: si la monitora manda las fotos antes del texto, o pasan
    mas de dos horas, la foto queda sin asociar. Se prefiere eso a colgarla del
    reporte equivocado.

    La ventana se cuenta desde que se mando la foto, no desde que llego: una
    foto que Meta entrega con dias de atraso no puede terminar colgada del
    reporte que la misma monitora mando hoy.
    """
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, finca, lote, es_alerta")
        .eq("remitente", remitente)
        .gte("fecha_hora", (momento - VENTANA_ASOCIACION).isoformat())
        .lte("fecha_hora", momento.isoformat())
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _ya_hubo_aviso_reciente(monitoreo: dict | None, remitente: str, momento: datetime) -> bool:
    """Si ya se aviso por otra foto de la misma visita, no se repite.

    Se consulta ANTES de insertar la foto actual, para que no se encuentre a
    si misma.

    La visita se cuenta alrededor de la foto y no solo hacia atras: si la foto
    llego tarde, otra de la misma visita pudo haber avisado antes que ella.
    """
    consulta = (
        get_client()
        .table("fotos")
        .select("id")
        .eq("es_alerta", True)
        .gte("fecha_hora", (momento - VENTANA_AVISO_REPETIDO).isoformat())
        .lte("fecha_hora", (momento + VENTANA_AVISO_REPETIDO).isoformat())
    )
    if monitoreo:
        consulta = consulta.eq("monitoreo_id", monitoreo["id"])
    else:
        consulta = consulta.eq("remitente", remitente).is_("monitoreo_id", "null")

    return bool(consulta.limit(1).execute().data)


def _lotes_candidatos(remitente: str) -> list[dict]:
    """Los lotes distintos que esa persona reporto dentro de la ventana."""
    desde = (datetime.now(timezone.utc) - VENTANA_ASOCIACION).isoformat()
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, finca, lote")
        .eq("remitente", remitente)
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .execute()
        .data
    )
    vistos, candidatos = set(), []
    for f in filas:
        clave = (f.get("finca"), f.get("lote"))
        if f.get("lote") and clave not in vistos:
            vistos.add(clave)
            candidatos.append(f)
    return candidatos


def _ya_se_pregunto_por_fotos(remitente: str) -> bool:
    """Si ya se le pregunto por esta tanda de fotos.

    Se mira en envios, que es donde queda registrado todo lo que manda el
    agente: con 25 fotos seguidas, preguntar por cada una seria insufrible.
    """
    desde = (datetime.now(timezone.utc) - VENTANA_PREGUNTA_FOTOS).isoformat()
    filas = (
        get_client()
        .table("envios")
        .select("id")
        .eq("tipo", TIPO_PREGUNTA_FOTOS)
        .eq("destinatario", remitente)
        .gte("fecha_hora", desde)
        .limit(1)
        .execute()
        .data
    )
    return bool(filas)


def _preguntar_de_que_lote_son(remitente: str, candidatos: list[dict]) -> None:
    opciones = ", ".join(
        f"{c.get('finca') or 'sin finca'} {c['lote']}" for c in candidatos[:8]
    )
    texto = (
        "Recibí tus fotos, pero no vienen con texto y hoy reportaste varios lotes, "
        "así que no sé a cuál corresponden.\n"
        f"¿De qué lote son? Reportaste: {opciones}.\n"
        "Puedes responderme solo con el número."
    )
    try:
        wamid = meta_whatsapp_service.enviar_mensaje(remitente, texto)
        envios_service.registrar(
            TIPO_PREGUNTA_FOTOS, remitente, "aceptado", wamid=wamid,
            detalle=f"{len(candidatos)} lotes posibles",
        )
        logger.info("Se pregunto a %s de que lote son las fotos", remitente)
    except Exception:
        logger.exception("No se pudo preguntar a %s por el lote de las fotos", remitente)


def fotos_sin_confirmar(remitente: str) -> list[dict]:
    """Fotos recientes de esa persona que llegaron sueltas, sin texto."""
    desde = (datetime.now(timezone.utc) - VENTANA_PREGUNTA_FOTOS).isoformat()
    return (
        get_client()
        .table("fotos")
        .select("id, monitoreo_id, storage_path")
        .eq("remitente", remitente)
        .is_("caption", "null")
        .gte("fecha_hora", desde)
        .execute()
        .data
    )


def reasignar_fotos(remitente: str, monitoreo: dict) -> int:
    """Cuelga del lote indicado las fotos sueltas recientes. Devuelve cuantas."""
    fotos = fotos_sin_confirmar(remitente)
    pendientes = [f for f in fotos if f.get("monitoreo_id") != monitoreo["id"]]
    if not pendientes:
        return 0

    get_client().table("fotos").update({"monitoreo_id": monitoreo["id"]}).in_(
        "id", [f["id"] for f in pendientes]
    ).execute()
    logger.info(
        "Se reasignaron %d fotos de %s al monitoreo %s",
        len(pendientes), remitente, monitoreo["id"],
    )
    return len(pendientes)


def _ruta_archivo(monitoreo: dict | None, media_id: str, mime_type: str, momento: datetime) -> str:
    """Ruta dentro del bucket, agrupada por mes y con finca y lote en el nombre
    para poder ubicar una foto sin consultar la base.

    La fecha es la de la foto, que es la del registro, y no la de llegada.
    """
    extension = EXTENSIONES.get(mime_type, "bin")
    sufijo = media_id[-8:]

    if monitoreo:
        finca = _limpiar_para_nombre(monitoreo.get("finca"), "sin-finca")
        lote = _limpiar_para_nombre(monitoreo.get("lote"), "sin-lote")
        nombre = f"{momento:%Y-%m-%d}_{finca}_lote-{lote}_{sufijo}.{extension}"
    else:
        nombre = f"{momento:%Y-%m-%d}_sin-reporte_{sufijo}.{extension}"

    return f"{momento:%Y/%m}/{nombre}"


def procesar_foto(
    media_id: str,
    remitente: str,
    caption: str | None = None,
    enviado_en: datetime | None = None,
    responder: bool = True,
) -> dict:
    """Descarga la foto, la describe, la archiva y la registra.

    Cada paso opcional (descripcion, archivo) se protege por separado: si el
    archivo falla no se pierde la descripcion, y si la descripcion falla la
    foto igual queda archivada.

    `enviado_en` y `responder` como en procesar_mensaje_monitoreo: la foto se
    registra con la hora en que se mando, y si llego tarde no se le pregunta
    nada a la monitora.
    """
    momento = (enviado_en or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contenido, mime_type = meta_whatsapp_service.descargar_media(media_id)
    monitoreo = _monitoreo_relacionado(remitente, momento)

    descripcion = None
    plagas_sugeridas = []
    danos_observados = []
    try:
        visto = vision_service.describir_foto(contenido, mime_type)
        if visto:
            descripcion = visto["descripcion"]
            plagas_sugeridas = visto["plagas_sugeridas"]
            danos_observados = visto["danos_observados"]
    except Exception:
        logger.exception("No se pudo describir la foto %s", media_id)

    storage_path = None
    try:
        storage_path = storage_service.subir_foto(
            _ruta_archivo(monitoreo, media_id, mime_type, momento), contenido, mime_type
        )
    except Exception:
        logger.exception("No se pudo archivar la foto %s", media_id)

    motivo_alerta = evaluar_dano_en_foto(descripcion, plagas_sugeridas, danos_observados)

    # Se consulta antes del insert para que la foto actual no cuente.
    hubo_aviso_reciente = (
        _ya_hubo_aviso_reciente(monitoreo, remitente, momento) if motivo_alerta else False
    )

    registro = {
        "fecha_hora": momento.isoformat(),
        "remitente": remitente,
        "media_id": media_id,
        "caption": caption,
        "monitoreo_id": monitoreo["id"] if monitoreo else None,
        "storage_path": storage_path,
        "descripcion": descripcion,
        # Hipotesis del modelo, en campo aparte: nunca se mezclan con las
        # plagas que reporto la monitora en el texto.
        "plagas_sugeridas": plagas_sugeridas,
        "es_alerta": bool(motivo_alerta),
        "motivo_alerta": motivo_alerta,
    }

    guardada = get_client().table("fotos").insert(registro).execute().data[0]

    # Foto suelta, sin texto, y esa persona reporto varios lotes: la
    # asociacion es una apuesta. Se pregunta antes que colgarla del lote
    # equivocado, que despues nadie corrige porque nadie lo nota.
    if not caption and responder:
        candidatos = _lotes_candidatos(remitente)
        if len(candidatos) > 1 and not _ya_se_pregunto_por_fotos(remitente):
            _preguntar_de_que_lote_son(remitente, candidatos)

    if motivo_alerta:
        # Si el reporte escrito ya genero alerta, el administrador ya fue
        # avisado de ese lote y repetir seria ruido.
        if monitoreo and monitoreo.get("es_alerta"):
            logger.info(
                "Foto %s con dano, sin aviso: el lote ya alerto por el reporte escrito",
                guardada.get("id"),
            )
        elif hubo_aviso_reciente:
            logger.info(
                "Foto %s con dano, sin aviso: ya se aviso por otra foto de esta visita",
                guardada.get("id"),
            )
        else:
            _notificar_dano_en_foto(guardada, monitoreo, motivo_alerta, danos_observados)

    return guardada


def _notificar_dano_en_foto(
    foto: dict, monitoreo: dict | None, motivo: str, danos: list | None = None
) -> None:
    """Avisa que una foto muestra dano compatible con plaga cuarentenaria.

    Prioridad media y redactado como algo a verificar. Las candidatas van con
    "compatible con": son hipotesis del modelo sobre una foto, no una
    identificacion, y el plan distingue varias de estas especies por detalles
    que no salen de una imagen.

    El hallazgo que se manda es el dano concreto y las candidatas, no la
    descripcion completa: esta ocupaba los 300 caracteres del parametro con
    prosa sobre el follaje y el administrador tenia que leerla entera para
    saber que se vio.
    """
    finca = (monitoreo or {}).get("finca") or "no especificada"
    lote = (monitoreo or {}).get("lote") or "no especificado"
    descripcion = foto.get("descripcion") or "sin descripcion"
    sugeridas = foto.get("plagas_sugeridas") or []
    remitente = foto.get("remitente") or "desconocido"
    # Con la hora de la foto, por lo mismo que la alerta de un reporte: puede
    # salir en la mañana por una foto de anoche, o por una que llego tarde.
    quien = f"{remitente} {cuando_legible(foto['fecha_hora'])}" if foto.get("fecha_hora") else remitente

    vistos = [DANOS_RELEVANTES[d] for d in (danos or []) if d in DANOS_RELEVANTES]
    partes = []
    if vistos:
        partes.append(f"Daño visible: {', '.join(vistos)}")
    if sugeridas:
        partes.append(f"compatible con {', '.join(sugeridas)}")
    hallazgo = ". ".join(partes) if partes else motivo

    respaldo = (
        f"📷 Foto con posible daño de plaga cuarentenaria\n"
        f"Finca: {finca}\n"
        f"Lote: {lote}\n"
        f"{hallazgo}\n"
        f"Descripción: {descripcion}\n"
        f"Enviada por {quien}\n"
        "A confirmar en campo."
    )

    try:
        meta_whatsapp_service.enviar_plantilla_a_administradores(
            meta_whatsapp_service.PLANTILLA_ALERTA,
            [
                "media",
                finca,
                lote,
                hallazgo,
                "posible daño de plaga cuarentenaria en foto, a confirmar en campo",
                quien,
            ],
            respaldo=respaldo,
            tipo="alerta_foto",
            referencia=f"foto:{foto.get('id')}",
        )
    except Exception:
        logger.exception("No se pudo avisar del dano visto en la foto %s", foto.get("id"))
