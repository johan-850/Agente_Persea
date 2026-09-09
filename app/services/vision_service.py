"""Descripcion de las fotos que acompanan los reportes de monitoreo.

Devuelve dos cosas separadas a proposito:

- descripcion: lo observable en la foto (parte de la planta, tipo de dano,
  extension). Es lo unico que se afirma.
- plagas_sugeridas: candidatas del catalogo del PLAN MIPE compatibles con ese
  dano. Son HIPOTESIS, no identificaciones, y se guardan en un campo aparte
  para que nunca se confundan con lo que reporto la monitora.

La separacion importa porque el plan distingue especies por detalles que no
salen de una foto de WhatsApp: Pseudococcus jackbeardsleyi se diferencia de
P. longispinus contando pares de filamentos de cera, y una es cuarentenaria y
la otra no. La confirmacion la hace el agronomo en campo.
"""

import base64
import logging
import os

from app.services.ia_service import get_client
from app.services.monitoreo_ia_service import CATALOGO_PLAGAS

logger = logging.getLogger("vision")

MODEL = "claude-haiku-4-5-20251001"

# Limite defensivo: la API rechaza imagenes muy grandes y las fotos de WhatsApp
# rara vez pasan de 2 MB.
MAX_BYTES = 4_500_000

MIME_SOPORTADOS = {"image/jpeg", "image/png", "image/gif", "image/webp"}

PROMPT = f"""Estas viendo una foto tomada por una monitora de campo en un cultivo
de aguacate Hass, que acompana un reporte de monitoreo de plagas.

Devuelve dos cosas:

1. descripcion: 1 o 2 frases en espanol sobre lo OBSERVABLE. Que parte de la
   planta aparece (hoja, rama, fruto, tallo, raiz, suelo), que dano o sintoma
   se ve (perforaciones, manchas, clorosis, defoliacion, exudaciones, aserrin,
   presencia de insectos o larvas) y su extension aparente. Aqui NO nombres
   plagas: describe lo que se ve, no lo que crees que lo causo.
   Si la foto no muestra cultivo ni dano (una persona, un paisaje, un
   documento), dilo en pocas palabras.

2. plagas_sugeridas: lista de plagas o enfermedades del catalogo de abajo
   COMPATIBLES con el dano visible. Son hipotesis para que el agronomo
   verifique, no un diagnostico.
   Reglas:
   - Usa unicamente nombres del catalogo.
   - Incluye una candidata solo si el dano visible corresponde de verdad al
     que esa plaga produce.
   - Si varias son compatibles, incluyelas todas: es preferible una lista
     corta de candidatas a una identificacion unica y equivocada.
   - Si no hay dano visible, o el dano no permite acotar candidatas, devuelve
     la lista vacia. Una lista vacia es una respuesta valida y frecuente.

CATALOGO DE PLAGAS Y ENFERMEDADES DEL CULTIVO
{CATALOGO_PLAGAS}"""

DESCRIPCION_TOOL = {
    "name": "describir_foto",
    "description": "Registra lo observado en una foto de monitoreo de campo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "descripcion": {"type": "string"},
            "plagas_sugeridas": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["descripcion", "plagas_sugeridas"],
    },
}


def describir_foto(contenido: bytes, mime_type: str) -> dict | None:
    """Devuelve {descripcion, plagas_sugeridas}, o None si no se puede procesar."""
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
        max_tokens=600,
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
        tools=[DESCRIPCION_TOOL],
        tool_choice={"type": "tool", "name": "describir_foto"},
    )

    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            datos = bloque.input
            return {
                "descripcion": (datos.get("descripcion") or "").strip() or None,
                "plagas_sugeridas": datos.get("plagas_sugeridas") or [],
            }

    return None
