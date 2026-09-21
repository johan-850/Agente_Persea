"""Reglas duras de alerta para reportes de monitoreo de plagas.

Distintas de alertas_service.py (labor): en monitoreo la palabra "daño" es
vocabulario rutinario (aparece en casi todo hallazgo normal), asi que NO se
usa como disparador aqui. En cambio "activo" es el marcador que el propio
equipo de monitoreo usa para senalar un foco urgente (ej. "foco de escamas
ACTIVO"), y es una senal mucho mas confiable en este dominio.

Las plagas cuarentenarias tienen umbral de dano 0% segun el PLAN MIPE: basta
su presencia, sin importar como se describa.
"""

import logging
import re
import unicodedata

from app.services.alertas_service import (
    GRUPOS_SIN_ESPECIE,
    PALABRAS_ACCIDENTE,
    PLAGAS_CUARENTENARIAS,
)

logger = logging.getLogger("alertas_monitoreo")

_PATRON_ACTIVO = re.compile(r"\bactivo[s]?\b", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes. Las monitoras escriben indistintamente
    "acaro"/"ácaro" o "pseudocercospora"/"pseudocercóspora".
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


# Danos visibles que el PLAN MIPE asocia a las plagas cuarentenarias. El modelo
# de vision los reporta como lista cerrada (ver vision_service.DANOS_VISIBLES).
#
# Antes se buscaban con expresiones regulares sobre la prosa de la descripcion,
# y eso alertaba al reves de lo que decia la foto: una descripcion que terminaba
# en "las ramas muestran estructura integra SIN perforaciones ni exudaciones"
# disparaba alerta por "perforaciones" y "exudaciones", porque las palabras
# estaban ahi aunque fueran negadas. Dos de las alertas de un mismo dia fueron
# plantas explicitamente sanas.
#
# Quien miro la imagen es el modelo; que diga el que vio el dano y no una
# expresion regular leyendo su redaccion.
#
# La distincion de organo sigue importando y ahora viaja en el propio nombre del
# dano: Heilipus lauri ataca el fruto, Stenoma catenifer fruto y ramas delgadas,
# Heilipus elegans tallo y ramas. Una perforacion en HOJA es otra cosa
# (comedores de follaje, minadores) y no debe alertar.
DANOS_RELEVANTES = {
    "perforacion_en_fruto_rama_o_tallo": "perforaciones en fruto, rama o tallo",
    "galeria_en_fruto_rama_o_tallo": "galerias en fruto, rama o tallo",
    "larva_en_fruto_rama_o_tallo": "larvas en fruto, rama o tallo",
    "aserrin": "aserrin de larva",
    "exudacion_o_gomosis": "exudaciones o gomosis",
    "secrecion_cerosa_o_algodonosa": "secrecion cerosa o algodonosa",
    "melaza_o_fumagina": "melaza o fumagina",
}


def evaluar_dano_en_foto(
    descripcion: str | None,
    plagas_sugeridas: list | None = None,
    danos_observados: list | None = None,
) -> str | None:
    """Devuelve el motivo si una foto sugiere dano compatible con plaga
    cuarentenaria, o None si no hay indicios.

    Orden de decision:

    1. Si alguna candidata propuesta es cuarentenaria, se alerta.
    2. Si el modelo propuso candidatas y NINGUNA es cuarentenaria, no se
       alerta: miro la imagen completa y concluyo otra cosa.
    3. Sin candidatas, deciden los danos que el modelo reporto haber visto.

    `descripcion` ya no participa en la decision: se conserva en el registro
    para que un humano pueda revisar, pero no se le buscan patrones.
    """
    sugeridas = [str(s) for s in (plagas_sugeridas or [])]
    cuarentenarias = [
        s for s in sugeridas if any(p in normalizar(s) for p in PLAGAS_CUARENTENARIAS)
    ]

    motivos = [
        DANOS_RELEVANTES[d] for d in (danos_observados or []) if d in DANOS_RELEVANTES
    ]

    if cuarentenarias:
        return ", ".join(motivos + [f"candidata cuarentenaria: {s}" for s in cuarentenarias])

    if sugeridas:
        if motivos:
            logger.info(
                "Dano visible (%s) descartado: el modelo propuso candidatas no "
                "cuarentenarias (%s)",
                ", ".join(motivos),
                ", ".join(sugeridas),
            )
        return None

    return ", ".join(motivos) if motivos else None


def hallazgos_que_alertan(plagas: list | None) -> list:
    """Cuales de los hallazgos del lote son los que disparan la alerta.

    Sirve para encabezar el aviso con lo que importa: un reporte de bordeo
    trae quince hallazgos rutinarios y el stenoma quedaba sepultado en el
    medio, o directamente cortado por el limite de caracteres.
    """
    return [p for p in (plagas or []) if evaluar_alerta_monitoreo(str(p))[0]]


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
