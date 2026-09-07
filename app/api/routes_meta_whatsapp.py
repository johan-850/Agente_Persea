import logging
import os

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("meta_webhook")

from app.services.fotos_service import procesar_foto
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
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            valor = change.get("value", {})
            for estado in valor.get("statuses", []):
                logger.warning("ESTADO DE MENSAJE: %s", estado)
            for mensaje in valor.get("messages", []):
                try:
                    _procesar_mensaje(mensaje)
                except Exception:
                    # Devolver 500 haria que Meta reintente y, si falla seguido,
                    # desactive la suscripcion del webhook. Se registra el error
                    # y se responde 200 igual.
                    logger.exception("Fallo procesando mensaje: %s", mensaje.get("id"))

    return Response(status_code=200)
