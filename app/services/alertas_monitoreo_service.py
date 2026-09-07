"""Reglas duras de alerta para reportes de monitoreo de plagas.

Distintas de alertas_service.py (labor): en monitoreo la palabra "daño" es
vocabulario rutinario (aparece en casi todo hallazgo normal), asi que NO se
usa como disparador aqui. En cambio "activo" es el marcador que el propio
equipo de monitoreo usa para senalar un foco urgente (ej. "foco de escamas
ACTIVO"), y es una senal mucho mas confiable en este dominio.

Las plagas cuarentenarias tienen umbral de dano 0% segun el PLAN MIPE: basta
su presencia, sin importar como se describa.
"""

import re
import unicodedata

from app.services.alertas_service import (
    GRUPOS_SIN_ESPECIE,
    PALABRAS_ACCIDENTE,
    PLAGAS_CUARENTENARIAS,
)

_PATRON_ACTIVO = re.compile(r"\bactivo[s]?\b", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes. Las monitoras escriben indistintamente
    "acaro"/"ácaro" o "pseudocercospora"/"pseudocercóspora".
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


# Danos visibles que el PLAN MIPE asocia a las plagas cuarentenarias:
# perforaciones y galerias de los barrenadores (Heilipus, Stenoma), aserrin de
# las larvas, exudaciones en tallo, y la cera y melaza de cochinillas y escamas.
#
# Se comparan contra la DESCRIPCION de la foto, no contra el reporte escrito.
# No identifican especie: solo indican que vale la pena que alguien mire el
# lote, por eso la alerta que generan es de prioridad media.
PATRONES_DANO_FOTO = [
    (r"perforacion|perforad", "perforaciones"),
    (r"galeria", "galerias"),
    (r"aserrin", "aserrin de larva"),
    (r"exudacion|exudad|gomosis", "exudaciones"),
    (r"larva", "larvas visibles"),
    (r"cera blanca|ceros[oa]|algodonos", "secrecion cerosa"),
    (r"melaza|fumagina", "melaza o fumagina"),
]


def evaluar_dano_en_foto(descripcion: str | None) -> str | None:
    """Devuelve el motivo si la descripcion de una foto sugiere dano compatible
    con plaga cuarentenaria, o None si no coincide con ningun patron.
    """
    if not descripcion:
        return None

    texto = normalizar(descripcion)
    motivos = [motivo for patron, motivo in PATRONES_DANO_FOTO if re.search(patron, texto)]
    return ", ".join(motivos) if motivos else None


def evaluar_alerta_monitoreo(texto: str) -> tuple[bool, str | None, str | None]:
    """Devuelve (es_alerta, tipo_alerta, prioridad) segun el texto completo
    del mensaje. Ver alertas_service.evaluar_alerta para la justificacion de
    por que existen reglas duras ademas del criterio de la IA.
    """
    texto_normalizado = normalizar(texto)

    for plaga in PLAGAS_CUARENTENARIAS:
        if plaga in texto_normalizado:
            return True, "plaga_cuarentenaria", "alta"

    for palabra in PALABRAS_ACCIDENTE:
        if normalizar(palabra) in texto_normalizado:
            return True, "accidente", "alta"

    if _PATRON_ACTIVO.search(texto_normalizado):
        return True, "foco_activo", "alta"

    # Un grupo sin especie no confirma cuarentena, pero tampoco la descarta.
    # Se avisa con menor prioridad para que se verifique en campo.
    for grupo in GRUPOS_SIN_ESPECIE:
        if re.search(rf"\b{grupo}\b", texto_normalizado):
            return True, "posible_plaga_cuarentenaria", "media"

    return False, None, None
