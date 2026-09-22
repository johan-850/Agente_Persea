"""Procesa las fotos que llegan por WhatsApp: las archiva, las describe y las
liga al reporte al que pertenecen.
"""

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.services import meta_whatsapp_service, storage_service, vision_service
from app.services.alertas_monitoreo_service import DANOS_RELEVANTES, evaluar_dano_en_foto

logger = logging.getLogger("fotos")

# Las monitoras mandan la foto en un mensaje aparte del texto, casi siempre
# seguido. Se busca el ultimo reporte de esa misma persona en esta ventana.
VENTANA_ASOCIACION = timedelta(hours=2)

# Una monitora manda varias fotos seguidas del mismo lote. Avisar por cada una
# convierte un hallazgo en cinco mensajes seguidos y el administrador deja de
# leerlos: un lote llego a disparar tres avisos en cuatro minutos. Dentro de
# esta ventana se avisa una vez y las demas fotos quedan registradas en la
# base, donde se pueden consultar todas juntas.
VENTANA_AVISO_REPETIDO = timedelta(minutes=30)

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


def _monitoreo_relacionado(remitente: str) -> dict | None:
    """Ultimo reporte del mismo remitente dentro de la ventana.

    Es una heuristica: si la monitora manda las fotos antes del texto, o pasan
    mas de dos horas, la foto queda sin asociar. Se prefiere eso a colgarla del
    reporte equivocado.
    """
    desde = (datetime.now(timezone.utc) - VENTANA_ASOCIACION).isoformat()
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, finca, lote, es_alerta")
        .eq("remitente", remitente)
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _ya_hubo_aviso_reciente(monitoreo: dict | None, remitente: str) -> bool:
    """Si ya se aviso por otra foto de la misma visita, no se repite.

    Se consulta ANTES de insertar la foto actual, para que no se encuentre a
    si misma.
    """
    desde = (datetime.now(timezone.utc) - VENTANA_AVISO_REPETIDO).isoformat()
    consulta = (
        get_client()
        .table("fotos")
        .select("id")
        .eq("es_alerta", True)
        .gte("fecha_hora", desde)
    )
    if monitoreo:
        consulta = consulta.eq("monitoreo_id", monitoreo["id"])
    else:
        consulta = consulta.eq("remitente", remitente).is_("monitoreo_id", "null")

    return bool(consulta.limit(1).execute().data)


def _ruta_archivo(monitoreo: dict | None, media_id: str, mime_type: str) -> str:
    """Ruta dentro del bucket, agrupada por mes y con finca y lote en el nombre
    para poder ubicar una foto sin consultar la base.
    """
    ahora = datetime.now(timezone.utc)
    extension = EXTENSIONES.get(mime_type, "bin")
    sufijo = media_id[-8:]

    if monitoreo:
        finca = _limpiar_para_nombre(monitoreo.get("finca"), "sin-finca")
        lote = _limpiar_para_nombre(monitoreo.get("lote"), "sin-lote")
        nombre = f"{ahora:%Y-%m-%d}_{finca}_lote-{lote}_{sufijo}.{extension}"
    else:
        nombre = f"{ahora:%Y-%m-%d}_sin-reporte_{sufijo}.{extension}"

    return f"{ahora:%Y/%m}/{nombre}"


def procesar_foto(media_id: str, remitente: str, caption: str | None = None) -> dict:
    """Descarga la foto, la describe, la archiva y la registra.

    Cada paso opcional (descripcion, archivo) se protege por separado: si el
    archivo falla no se pierde la descripcion, y si la descripcion falla la
    foto igual queda archivada.
    """
    contenido, mime_type = meta_whatsapp_service.descargar_media(media_id)
    monitoreo = _monitoreo_relacionado(remitente)

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
            _ruta_archivo(monitoreo, media_id, mime_type), contenido, mime_type
        )
    except Exception:
        logger.exception("No se pudo archivar la foto %s", media_id)

    motivo_alerta = evaluar_dano_en_foto(descripcion, plagas_sugeridas, danos_observados)

    # Se consulta antes del insert para que la foto actual no cuente.
    hubo_aviso_reciente = _ya_hubo_aviso_reciente(monitoreo, remitente) if motivo_alerta else False

    registro = {
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
                foto.get("remitente") or "desconocido",
            ],
            respaldo=respaldo,
            tipo="alerta_foto",
            referencia=f"foto:{foto.get('id')}",
        )
    except Exception:
        logger.exception("No se pudo avisar del dano visto en la foto %s", foto.get("id"))
