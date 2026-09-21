import logging
import os

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("meta_webhook")

from app.services.cola_mensajes import encolar
from app.services.fotos_service import procesar_foto
from app.services.idempotencia_service import reclamar
from app.services.monitoreo_service import procesar_mensaje_monitoreo

router = APIRouter()


def _procesar_mensaje(mensaje: dict) -> None:
    numero = mensaje.get("from")
    if not numero:
        return
    remitente = f"whatsapp:+{numero}"

    if mensaje.get("type") == "image":
        imagen = mensaje.get("image", {})
        media_id = imagen.get("id")
        caption = imagen.get("caption")
        if not media_id:
            return
        # Si la foto trae caption con el reporte, se procesa primero para que
        # exista el monitoreo al que la foto se va a asociar.
        if caption:
            procesar_mensaje_monitoreo(texto=caption, remitente=remitente)
        procesar_foto(media_id=media_id, remitente=remitente, caption=caption)
        return

    texto = mensaje.get("text", {}).get("body")
    if texto:
        procesar_mensaje_monitoreo(texto=texto, remitente=remitente)


@router.get("/meta/webhook")
def verificar_webhook_meta(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get(
        "hub.verify_token"
    ) == os.environ.get("META_VERIFY_TOKEN"):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/meta/webhook")
async def recibir_mensaje_meta(request: Request):
    """Confirma de inmediato y deja el trabajo pesado a la cola.

    Procesar aqui mismo tardaba entre 4 y 6 segundos por mensaje; Meta no
    alcanzaba a recibir el 200, reenviaba el evento y cada reenvio volvia a
    guardar el reporte y a repetir la alerta.

    Nunca se devuelve 500: si el webhook falla seguido, Meta desactiva la
    suscripcion y dejan de llegar los reportes.
    """
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            valor = change.get("value", {})
            for estado in valor.get("statuses", []):
                logger.debug("Estado de mensaje: %s", estado)
            for mensaje in valor.get("messages", []):
                wamid = mensaje.get("id")
                # run_in_threadpool: el cliente de Supabase es sincrono y
                # bloquearia el bucle de eventos de todas las peticiones.
                if wamid and not await run_in_threadpool(reclamar, wamid):
                    logger.info("Reenvio de %s descartado, ya se habia procesado", wamid)
                    continue
                pendientes = encolar(_procesar_mensaje, mensaje)
                logger.info("Mensaje %s encolado (%d en cola)", wamid, pendientes)

    return Response(status_code=200)
