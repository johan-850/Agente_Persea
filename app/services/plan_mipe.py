"""Datos del PLAN MIPE de Agricola Persea (aguacate Hass).

Es el documento que define que plagas son cuarentenarias y con que umbral se
actua. Aqui vive solo el dato; las reglas que lo usan estan en
alertas_monitoreo_service.

Antes esto estaba dentro de alertas_service.py, junto a las reglas del flujo
de labores que ya no existe.
"""

# Plagas cuarentenarias: umbral de dano 0%. Cualquier presencia genera accion
# de manejo, sin importar si el reporte la describe como foco activo o no.
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

# Nombres de grupo que no dicen la especie, pero que en este cultivo son
# cuarentenarios de todos modos.
#
# De las ocho plagas cuarentenarias del plan, CINCO son cochinillas o escamas:
# Maconellicoccus hirsutus (cochinilla rosada), Pseudococcus jackbeardsleyi y
# P. landoi (cochinillas harinosas), Ceroplastes rubens (escama cerosa roja) y
# Saissetia batesi (escama hemisferica). Y en todo el catalogo del plan no
# aparece ninguna cochinilla ni escama que NO sea cuarentenaria para aguacate
# Hass.
#
# Por eso "se observan cochinillas", sin mas, se trata como cuarentenaria y no
# como sospecha: por el plan, es presuntamente una de las cinco. Lo que queda
# pendiente es cual, no si lo es. Antes esto alertaba con prioridad media y se
# quedaba corto.
GRUPOS_CUARENTENARIOS_SIN_ESPECIE = [
    "escama",
    "escamas",
    "cochinilla",
    "cochinillas",
    "piojo harinoso",
]

PALABRAS_ACCIDENTE = [
    "accidente",
    "herido",
    "herida",
    "lesion",
    "lesión",
    "emergencia",
]
