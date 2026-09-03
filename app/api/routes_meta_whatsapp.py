import logging
import os

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("meta_webhook")

from app.services.monitoreo_service import procesar_mensaje_monitoreo

router = APIRouter()


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
                texto = mensaje.get("text", {}).get("body")
                remitente = mensaje.get("from")
                if not (texto and remitente):
                    continue
                try:
                    procesar_mensaje_monitoreo(texto=texto, remitente=f"whatsapp:+{remitente}")
                except Exception:
                    # Devolver 500 haria que Meta reintente y, si falla seguido,
                    # desactive la suscripcion del webhook. Se registra el error
                    # y se responde 200 igual.
                    logger.exception("Fallo procesando mensaje de %s: %s", remitente, texto)

    return Response(status_code=200)
