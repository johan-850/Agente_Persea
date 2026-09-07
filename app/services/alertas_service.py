"""Reglas duras de alerta. Se aplican ademas del criterio de la IA para
no depender solo del modelo en algo critico (falsos negativos son costosos).
"""

# Plagas cuarentenarias del PLAN MIPE de Agricola Persea (aguacate Hass).
# Umbral de dano 0%: cualquier presencia genera accion de manejo, sin importar
# si el reporte la describe como foco activo o no.
#
# Se incluyen nombre cientifico, genero y nombre comun porque las monitoras
# escriben indistintamente ("stenoma en rama", "barrenador de tallo").
# Todo en minuscula y sin tildes: el texto se normaliza antes de comparar.
PLAGAS_CUARENTENARIAS = [
    # Heilipus lauri (barrenador de semilla) y H. elegans (barrenador de tallo)
    "heilipus",
    "barrenador de semilla",
    "barrenador de tallo",
    # Stenoma catenifer (pasador del fruto)
    "stenoma",
    "pasador del fruto",
    # Maconellicoccus hirsutus (cochinilla rosada del hibisco)
    "maconellicoccus",
    "cochinilla rosada",
    # Pseudococcus jackbeardsleyi y P. landoi (cochinillas harinosas)
    "pseudococcus",
    "jackbeardsleyi",
    "landoi",
    # Ceroplastes rubens (escama cerosa roja)
    "ceroplastes",
    "escama cerosa",
    "escama roja",
    # Saissetia batesi (escama hemisferica del aguacate)
    "saissetia",
    "escama hemisferica",
]

# Terminos de grupo que NO identifican especie. Una "escama" o una "cochinilla"
# puede ser cuarentenaria (Ceroplastes, Saissetia, Pseudococcus, Maconellicoccus)
# o no serlo, y del texto no hay forma de saberlo. Se alerta igual, pero con
# menor prioridad y marcada como pendiente de confirmar en campo.
GRUPOS_SIN_ESPECIE = [
    "escama",
    "escamas",
    "cochinilla",
    "cochinillas",
    "piojo harinoso",
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
