"""Descripcion de las fotos que acompanan los reportes de monitoreo.

La descripcion es contexto de apoyo del reporte escrito, NO un diagnostico.
Un modelo de proposito general no distingue de forma confiable especies
cercanas a partir de una foto (un picudo de otro, una escama de otra), y una
decision fitosanitaria basada en eso seria un error. Por eso el prompt pide
describir lo observable y prohibe afirmar especies.
"""

import base64
import logging
import os

from app.services.ia_service import get_client

logger = logging.getLogger("vision")

MODEL = "claude-haiku-4-5-20251001"

# Limite defensivo: la API rechaza imagenes muy grandes y las fotos de WhatsApp
# rara vez pasan de 2 MB.
MAX_BYTES = 4_500_000

MIME_SOPORTADOS = {"image/jpeg", "image/png", "image/gif", "image/webp"}

PROMPT = """Estas viendo una foto tomada por una monitora de campo en un cultivo
de aguacate Hass, que acompana un reporte de monitoreo de plagas.

Describe en 1 o 2 frases lo que se observa, en espanol y en terminos concretos:
que parte de la planta aparece (hoja, rama, fruto, tallo, raiz, suelo), que tipo
de dano o sintoma es visible (perforaciones, manchas, clorosis, defoliacion,
exudaciones, presencia de insectos o larvas) y su extension aparente.

NO afirmes que especie de plaga es. Si se ve un insecto, describelo por su
aspecto ("larva blanca de unos 2 cm", "insecto escamoso blanco") sin nombrarlo.
La identificacion la hace el agronomo; tu descripcion es solo apoyo.

Si la foto no muestra cultivo ni dano (una persona, un paisaje, un documento),
dilo en pocas palabras."""


def describir_foto(contenido: bytes, mime_type: str) -> str | None:
    """Devuelve una descripcion breve, o None si no se puede procesar."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    if mime_type not in MIME_SOPORTADOS:
        logger.warning("Formato no soportado para descripcion: %s", mime_type)
        return None

    if len(contenido) > MAX_BYTES:
        logger.warning("Foto de %s bytes, se omite la descripcion", len(contenido))
        return None

    respuesta = get_client().messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64.b64encode(contenido).decode(),
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    partes = [bloque.text for bloque in respuesta.content if bloque.type == "text"]
    texto = " ".join(partes).strip()
    return texto or None
