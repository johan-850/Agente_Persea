"""Reglas duras de alerta para reportes de monitoreo de plagas.

Distintas de alertas_service.py (labor): en monitoreo la palabra "daño" es
vocabulario rutinario (aparece en casi todo hallazgo normal), asi que NO se
usa como disparador aqui. En cambio "activo" es el marcador que el propio
equipo de monitoreo usa para senalar un foco urgente (ej. "foco de escamas
ACTIVO"), y es una senal mucho mas confiable en este dominio.
"""

import re

from app.services.alertas_service import PALABRAS_ACCIDENTE, PLAGAS_CUARENTENARIAS

_PATRON_ACTIVO = re.compile(r"\bactivo[s]?\b", re.IGNORECASE)


def evaluar_alerta_monitoreo(texto: str) -> tuple[bool, str | None, str | None]:
    """Devuelve (es_alerta, tipo_alerta, prioridad) basado en reglas duras
    sobre el texto completo del mensaje. Ver alertas_service.evaluar_alerta
    para la justificacion general de por que existen reglas duras ademas
    del criterio de la IA.
    """
    texto_normalizado = texto.lower()

    for plaga in PLAGAS_CUARENTENARIAS:
        if plaga in texto_normalizado:
            return True, "plaga_cuarentenaria", "alta"

    if _PATRON_ACTIVO.search(texto):
        return True, "foco_activo", "alta"

    for palabra in PALABRAS_ACCIDENTE:
        if palabra in texto_normalizado:
            return True, "accidente", "alta"

    return False, None, None
