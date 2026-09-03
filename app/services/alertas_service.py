"""Reglas duras de alerta. Se aplican ademas del criterio de la IA para
no depender solo del modelo en algo critico (falsos negativos son costosos).
"""

# TODO: completar con la lista oficial de plagas cuarentenarias del cultivo.
PLAGAS_CUARENTENARIAS = [
    "heilipus elegans",
]

FRASES_FOCO_ACTIVO = [
    "foco activo",
    "continua activo",
    "sigue activo",
    "daños",
    "danos",
]

PALABRAS_ACCIDENTE = [
    "accidente",
    "herido",
    "herida",
    "lesion",
    "lesión",
    "emergencia",
]


def evaluar_alerta(texto: str) -> tuple[bool, str | None, str | None]:
    """Devuelve (es_alerta, tipo_alerta, prioridad) basado en reglas duras.

    No reemplaza la clasificacion de la IA: si la IA marca alerta pero las
    reglas no encuentran nada, se respeta igual el criterio de la IA aguas
    arriba (ver ia_service). Esta funcion sirve para forzar alerta aunque
    la IA no la haya detectado.
    """
    texto_normalizado = texto.lower()

    for plaga in PLAGAS_CUARENTENARIAS:
        if plaga in texto_normalizado:
            for frase in FRASES_FOCO_ACTIVO:
                if frase in texto_normalizado:
                    return True, "plaga_cuarentenaria", "alta"
            return True, "plaga_cuarentenaria", "media"

    for palabra in PALABRAS_ACCIDENTE:
        if palabra in texto_normalizado:
            return True, "accidente", "alta"

    return False, None, None
