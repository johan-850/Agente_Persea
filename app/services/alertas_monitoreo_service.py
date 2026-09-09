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


# Organos que atacan los barrenadores cuarentenarios segun el PLAN MIPE:
# Heilipus lauri el fruto, Stenoma catenifer fruto y ramas delgadas, Heilipus
# elegans tallo y ramas. Una perforacion o galeria en HOJA es otra cosa
# (comedores de follaje, minadores) y no debe alertar.
_ORGANOS_BARRENADOR = r"fruto|rama|tallo|corteza|semilla|peduncul|tronco"

# Ventana de caracteres alrededor del dano donde se busca el organo. Cubre una
# frase tipica sin cruzar a la siguiente.
_CERCANIA = 90

# Danos visibles que el plan asocia a las plagas cuarentenarias. La tercera
# columna indica si el dano solo cuenta cuando aparece sobre uno de los organos
# de arriba.
#
# Se comparan contra la DESCRIPCION de la foto, no contra el reporte escrito.
# No identifican especie: solo indican que vale la pena que alguien mire el
# lote, por eso la alerta que generan es de prioridad media.
PATRONES_DANO_FOTO = [
    (r"perforacion|perforad", "perforaciones", True),
    (r"galeria", "galerias", True),
    (r"larva", "larvas visibles", True),
    (r"aserrin", "aserrin de larva", False),
    (r"exudacion|exudad|gomosis", "exudaciones", False),
    (r"cera blanca|ceros[oa]|algodonos", "secrecion cerosa", False),
    (r"melaza|fumagina", "melaza o fumagina", False),
]


def _hay_dano(texto: str, patron: str, requiere_organo: bool) -> bool:
    if not requiere_organo:
        return bool(re.search(patron, texto))

    for coincidencia in re.finditer(patron, texto):
        inicio = max(0, coincidencia.start() - _CERCANIA)
        ventana = texto[inicio : coincidencia.end() + _CERCANIA]
        if re.search(_ORGANOS_BARRENADOR, ventana):
            return True
    return False


def evaluar_dano_en_foto(
    descripcion: str | None, plagas_sugeridas: list | None = None
) -> str | None:
    """Devuelve el motivo si una foto sugiere dano compatible con plaga
    cuarentenaria, o None si no hay indicios.

    Se miran dos cosas: los patrones de dano en la descripcion, y si alguna de
    las candidatas que propuso el modelo es cuarentenaria. Basta con una.
    """
    motivos = []

    if descripcion:
        texto = normalizar(descripcion)
        motivos += [
            motivo
            for patron, motivo, requiere_organo in PATRONES_DANO_FOTO
            if _hay_dano(texto, patron, requiere_organo)
        ]

    for sugerida in plagas_sugeridas or []:
        nombre = normalizar(str(sugerida))
        if any(plaga in nombre for plaga in PLAGAS_CUARENTENARIAS):
            motivos.append(f"candidata cuarentenaria: {sugerida}")

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
