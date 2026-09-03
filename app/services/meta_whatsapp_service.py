import logging
import os

import httpx

logger = logging.getLogger("meta_whatsapp")

IDIOMA_PLANTILLA = "es"

# Nombres exactos de las plantillas aprobadas en Meta. Si no coinciden, el envio
# cae al respaldo de texto libre (que solo llega dentro de la ventana de 24h).
PLANTILLA_ALERTA = "reporte_monitoreo_alerta"
PLANTILLA_RESUMEN = "reporte_monitoreo_resumen"

# Limite defensivo por parametro: el cuerpo completo de una plantilla no puede
# pasar de 1024 caracteres.
MAX_LARGO_PARAMETRO = 300


def _url() -> str:
    phone_number_id = os.environ["META_PHONE_NUMBER_ID"]
    return f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['META_ACCESS_TOKEN']}"}


def _numero(numero_destino: str) -> str:
    return numero_destino.replace("whatsapp:", "").lstrip("+")


def limpiar_parametro(valor, maximo: int = MAX_LARGO_PARAMETRO) -> str:
    """WhatsApp rechaza parametros de plantilla con saltos de linea, tabs o
    mas de 4 espacios seguidos, asi que se colapsa todo a espacios simples.
    """
    limpio = " ".join(str(valor or "").split())
    if len(limpio) > maximo:
        limpio = limpio[: maximo - 3].rstrip() + "..."
    return limpio or "no especificado"


def enviar_mensaje(numero_destino: str, texto: str) -> None:
    """Mensaje libre. Solo se entrega si el destinatario le escribio al bot en
    las ultimas 24 horas (ventana de atencion de WhatsApp).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": _numero(numero_destino),
        "type": "text",
        "text": {"body": texto},
    }
    respuesta = httpx.post(_url(), headers=_headers(), json=payload, timeout=30)
    respuesta.raise_for_status()


def enviar_plantilla(numero_destino: str, nombre: str, parametros: list) -> None:
    """Plantilla aprobada por Meta. A diferencia del mensaje libre, se entrega
    aunque el destinatario no haya escrito en las ultimas 24 horas.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": _numero(numero_destino),
        "type": "template",
        "template": {
            "name": nombre,
            "language": {"code": IDIOMA_PLANTILLA},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": limpiar_parametro(p)} for p in parametros
                    ],
                }
            ],
        },
    }
    respuesta = httpx.post(_url(), headers=_headers(), json=payload, timeout=30)
    respuesta.raise_for_status()


def _administradores() -> list:
    from app.services.admin_service import obtener_numeros_administradores

    return obtener_numeros_administradores()


def enviar_a_administradores(texto: str) -> None:
    for numero in _administradores():
        enviar_mensaje(numero, texto)


def enviar_plantilla_a_administradores(nombre: str, parametros: list, respaldo: str) -> None:
    """Envia la plantilla a cada administrador. Si la plantilla falla (aun sin
    aprobar, sin metodo de pago, etc.) se intenta el mensaje libre como ultimo
    recurso: llega solo si la ventana de 24h esta abierta, pero es preferible a
    perder una alerta silenciosamente.
    """
    for numero in _administradores():
        try:
            enviar_plantilla(numero, nombre, parametros)
        except Exception:
            logger.exception("Fallo la plantilla '%s' hacia %s, se intenta texto libre", nombre, numero)
            try:
                enviar_mensaje(numero, respaldo)
            except Exception:
                logger.exception("Tampoco se pudo enviar el texto libre hacia %s", numero)
