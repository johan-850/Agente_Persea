"""Quien puede llamar al agente: firma de Meta y clave de la API.

El servidor se expone por un tunel publico. Sin esto, cualquiera que averigue
la URL puede hacer un POST con un reporte inventado —se extrae, se guarda y
dispara una alerta real de WhatsApp a los administradores— o leer el historial
completo de las fincas y sacar enlaces a las fotos, que estan en un bucket
privado justamente para que no circulen.

Las dos puertas se tratan distinto a proposito:

- El webhook de Meta es el camino por donde entran los reportes. Si no hay
  secreto configurado se acepta igual, avisando en cada evento: dejar al
  agente sordo es peor que el riesgo mientras se configura. En cuanto hay
  secreto, se exige.
- La API REST es una comodidad, no hace falta para que el agente funcione.
  Si no hay clave configurada no se responde nada: cerrada por defecto.
"""

import hashlib
import hmac
import logging
import os

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("seguridad")

CABECERA_FIRMA = "x-hub-signature-256"
CABECERA_API = "X-API-Key"


async def verificar_firma_meta(request: Request) -> bytes:
    """Devuelve el cuerpo crudo del evento si viene firmado por Meta.

    La firma se calcula sobre los BYTES tal como llegaron. Si se parsea el
    JSON y se vuelve a serializar, el orden de las claves y los espacios
    cambian, el HMAC da distinto y nunca coincidiria: por eso esta funcion
    devuelve el cuerpo y quien la usa parsea desde ahi.
    """
    cuerpo = await request.body()
    secreto = os.environ.get("META_APP_SECRET")

    if not secreto:
        logger.warning(
            "META_APP_SECRET sin configurar: se acepta el evento sin comprobar "
            "que venga de Meta. Cualquiera que conozca la URL puede inyectar un reporte."
        )
        return cuerpo

    recibida = request.headers.get(CABECERA_FIRMA, "")
    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(recibida.encode(), esperada.encode()):
        logger.warning(
            "Evento rechazado: la firma no coincide (cabecera=%r, %d bytes de cuerpo)",
            recibida[:24],
            len(cuerpo),
        )
        raise HTTPException(status_code=403, detail="Firma invalida")

    return cuerpo


def exigir_api_key(x_api_key: str = Header(default="", alias=CABECERA_API)) -> None:
    """Protege los endpoints REST. Cerrada si no hay clave configurada."""
    esperada = os.environ.get("API_TOKEN")

    if not esperada:
        logger.error("API_TOKEN sin configurar: la API REST queda cerrada")
        raise HTTPException(status_code=503, detail="API sin configurar")

    if not hmac.compare_digest(x_api_key.encode(), esperada.encode()):
        raise HTTPException(status_code=401, detail=f"Falta o no coincide {CABECERA_API}")
