"""Reglas duras de alerta para reportes de monitoreo de plagas.

En monitoreo la palabra "daño" es vocabulario rutinario —aparece en casi todo
hallazgo normal— asi que NO se usa como disparador. En cambio "activo" es el
marcador que el propio equipo usa para senalar un foco urgente (ej. "foco de
escamas ACTIVO"), y es una senal mucho mas confiable en este dominio.

Estas reglas existen ademas del criterio del modelo porque aqui un falso
negativo cuesta caro: una cuarentenaria que pasa desapercibida sigue
extendiendose. El modelo puede equivocarse; la lista del plan no.

Las plagas cuarentenarias tienen umbral de dano 0% segun el PLAN MIPE: basta
su presencia, sin importar como se describa.
"""

import logging
import re
import unicodedata

from app.services.plan_mipe import (
    GRUPOS_CUARENTENARIOS_SIN_ESPECIE,
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


# Varios nombres del PLAN MIPE apuntan a la misma plaga: "barrenador de
# semilla" es Heilipus lauri, "escama cerosa" es Ceroplastes rubens. Para el
# resumen semanal se agrupan, porque lo que importa ahi no es como la escribio
# cada monitora sino en cuantos lotes apareció.
GRUPO_CUARENTENARIA = {
    "heilipus": "Heilipus (barrenadores)",
    "barrenador de semilla": "Heilipus (barrenadores)",
    "barrenador de tallo": "Heilipus (barrenadores)",
    "stenoma": "Stenoma catenifer",
    "pasador del fruto": "Stenoma catenifer",
    "maconellicoccus": "Maconellicoccus hirsutus",
    "cochinilla rosada": "Maconellicoccus hirsutus",
    "pseudococcus": "Pseudococcus (cochinillas harinosas)",
    "jackbeardsleyi": "Pseudococcus (cochinillas harinosas)",
    "landoi": "Pseudococcus (cochinillas harinosas)",
    "ceroplastes": "Ceroplastes rubens",
    "escama cerosa": "Ceroplastes rubens",
    "escama roja": "Ceroplastes rubens",
    "saissetia": "Saissetia batesi",
    "escama hemisferica": "Saissetia batesi",
}


def grupo_cuarentenaria(texto: str) -> str | None:
    """A que plaga cuarentenaria corresponde ese hallazgo, si a alguna."""
    plano = normalizar(str(texto))
    for termino, grupo in GRUPO_CUARENTENARIA.items():
        if termino in plano:
            return grupo
    return None


def hallazgos_que_alertan(plagas: list | None) -> list:
    """Cuales de los hallazgos del lote son los que disparan la alerta.

    Sirve para encabezar el aviso con lo que importa: un reporte de bordeo
    trae quince hallazgos rutinarios y el stenoma quedaba sepultado en el
    medio, o directamente cortado por el limite de caracteres.
    """
    return [p for p in (plagas or []) if evaluar_alerta_monitoreo(str(p))[0]]


def evaluar_alerta_monitoreo(texto: str) -> tuple[bool, str | None, str | None]:
    """Devuelve (es_alerta, tipo_alerta, prioridad) para el texto que se le pase.

    Se evalua por lote, no sobre el mensaje entero: un mensaje suele cubrir
    varios lotes y evaluarlo completo contagiaba la alerta a todos.
    """
    texto_normalizado = normalizar(texto)

    for plaga in PLAGAS_CUARENTENARIAS:
        if plaga in texto_normalizado:
            return True, "plaga_cuarentenaria", "alta"

    # Cochinillas y escamas sin especie. El plan no tiene ninguna que no sea
    # cuarentenaria en aguacate Hass, asi que va en alta igual que las
    # nombradas: lo que falta por confirmar es cual de las cinco, no si lo es.
    for grupo in GRUPOS_CUARENTENARIOS_SIN_ESPECIE:
        if re.search(rf"\b{grupo}\b", texto_normalizado):
            return True, "plaga_cuarentenaria_sin_especie", "alta"

    for palabra in PALABRAS_ACCIDENTE:
        if normalizar(palabra) in texto_normalizado:
            return True, "accidente", "alta"

    if _PATRON_ACTIVO.search(texto_normalizado):
        return True, "foco_activo", "alta"

    return False, None, None
