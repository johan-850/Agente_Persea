"""Procesa las fotos que llegan por WhatsApp: las archiva, las describe y las
liga al reporte al que pertenecen.
"""

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.services import meta_whatsapp_service, storage_service, vision_service
from app.services.alertas_monitoreo_service import evaluar_dano_en_foto

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
        .select("id, finca, lote, es_alerta")
        .eq("remitente", remitente)
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


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
    try:
        descripcion = vision_service.describir_foto(contenido, mime_type)
    except Exception:
        logger.exception("No se pudo describir la foto %s", media_id)

    storage_path = None
    try:
        storage_path = storage_service.subir_foto(
            _ruta_archivo(monitoreo, media_id, mime_type), contenido, mime_type
        )
    except Exception:
        logger.exception("No se pudo archivar la foto %s", media_id)

    motivo_alerta = evaluar_dano_en_foto(descripcion)

    registro = {
        "remitente": remitente,
        "media_id": media_id,
        "caption": caption,
        "monitoreo_id": monitoreo["id"] if monitoreo else None,
        "storage_path": storage_path,
        "descripcion": descripcion,
        "es_alerta": bool(motivo_alerta),
        "motivo_alerta": motivo_alerta,
    }

    guardada = get_client().table("fotos").insert(registro).execute().data[0]

    # Si el reporte escrito ya genero alerta, el administrador ya fue avisado
    # de ese lote y repetir seria ruido.
    if motivo_alerta and not (monitoreo and monitoreo.get("es_alerta")):
        _notificar_dano_en_foto(guardada, monitoreo, motivo_alerta)

    return guardada


def _notificar_dano_en_foto(foto: dict, monitoreo: dict | None, motivo: str) -> None:
    """Avisa que una foto muestra dano compatible con plaga cuarentenaria.

    Prioridad media y redactado como algo a verificar, no como diagnostico: la
    descripcion viene de un modelo que tiene prohibido afirmar especies.
    """
    descripcion = foto.get("descripcion") or "sin descripcion"
    respaldo = (
        f"📷 Foto con posible dano de plaga cuarentenaria ({motivo})\n"
        f"Finca: {(monitoreo or {}).get('finca') or 'no especificada'}\n"
        f"Lote: {(monitoreo or {}).get('lote') or 'no especificado'}\n"
        f"Descripcion: {descripcion}\n"
        "Verificar en campo."
    )

    try:
        meta_whatsapp_service.enviar_plantilla_a_administradores(
            meta_whatsapp_service.PLANTILLA_ALERTA,
            [
                "media",
                (monitoreo or {}).get("finca") or "no especificada",
                (monitoreo or {}).get("lote") or "no especificado",
                f"foto sugiere {motivo}: {descripcion}",
                "posible dano de plaga cuarentenaria, verificar en campo",
                foto.get("remitente") or "desconocido",
            ],
            respaldo=respaldo,
        )
    except Exception:
        logger.exception("No se pudo avisar del dano visto en la foto %s", foto.get("id"))
