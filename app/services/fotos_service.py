"""Procesa las fotos que llegan por WhatsApp: las guarda en Drive, las
describe y las liga al reporte al que pertenecen.
"""

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.services import drive_service, meta_whatsapp_service, vision_service

logger = logging.getLogger("fotos")

# Las monitoras mandan la foto en un mensaje aparte del texto, casi siempre
# seguido. Se busca el ultimo reporte de esa misma persona en esta ventana.
VENTANA_ASOCIACION = timedelta(hours=2)

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
        .select("id, finca, lote")
        .eq("remitente", remitente)
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _nombre_archivo(monitoreo: dict | None, media_id: str, mime_type: str) -> str:
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    extension = EXTENSIONES.get(mime_type, "bin")

    if monitoreo:
        finca = _limpiar_para_nombre(monitoreo.get("finca"), "sin-finca")
        lote = _limpiar_para_nombre(monitoreo.get("lote"), "sin-lote")
        return f"{fecha}_{finca}_lote-{lote}_{media_id[-8:]}.{extension}"

    return f"{fecha}_sin-reporte_{media_id[-8:]}.{extension}"


def procesar_foto(media_id: str, remitente: str, caption: str | None = None) -> dict:
    """Descarga la foto, la describe, la sube a Drive y la registra.

    Cada paso opcional (descripcion, Drive) se protege por separado: si Drive
    falla no se pierde la descripcion, y si la descripcion falla la foto igual
    queda archivada.
    """
    contenido, mime_type = meta_whatsapp_service.descargar_media(media_id)
    monitoreo = _monitoreo_relacionado(remitente)

    descripcion = None
    try:
        descripcion = vision_service.describir_foto(contenido, mime_type)
    except Exception:
        logger.exception("No se pudo describir la foto %s", media_id)

    drive_file_id = None
    drive_url = None
    try:
        subido = drive_service.subir_archivo(
            _nombre_archivo(monitoreo, media_id, mime_type), contenido, mime_type
        )
        drive_file_id = subido["id"]
        drive_url = subido["url"]
    except Exception:
        logger.exception("No se pudo subir a Drive la foto %s", media_id)

    registro = {
        "remitente": remitente,
        "media_id": media_id,
        "caption": caption,
        "monitoreo_id": monitoreo["id"] if monitoreo else None,
        "drive_file_id": drive_file_id,
        "drive_url": drive_url,
        "descripcion": descripcion,
    }

    return get_client().table("fotos").insert(registro).execute().data[0]
