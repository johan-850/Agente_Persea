"""Cliente de Anthropic, compartido por los servicios que usan el modelo.

Se crea una sola vez: extraccion de reportes, descripcion de fotos y consultas
de los administradores pasan todas por aqui.

Antes vivia dentro de ia_service.py, junto a la extraccion de reportes de
labores que ya no existe.
"""

import os

import anthropic

MODEL = "claude-haiku-4-5-20251001"

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client
