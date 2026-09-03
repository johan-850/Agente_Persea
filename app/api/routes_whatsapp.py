from fastapi import APIRouter, Form, Response
from twilio.twiml.messaging_response import MessagingResponse

from app.services.monitoreo_service import procesar_mensaje_monitoreo
from app.services.resumen_service import enviar_resumen_diario

router = APIRouter()


@router.post("/whatsapp/webhook")
def recibir_mensaje_whatsapp(From: str = Form(...), Body: str = Form(...)):
    procesar_mensaje_monitoreo(texto=Body, remitente=From)
    return Response(content=str(MessagingResponse()), media_type="application/xml")


@router.post("/tareas/resumen-diario")
def disparar_resumen_diario(fecha: str | None = None):
    texto = enviar_resumen_diario(fecha)
    return {"enviado": True, "resumen": texto}
