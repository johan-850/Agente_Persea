"""Pruebas de las reglas duras de alerta de monitoreo.

Son la red de seguridad del sistema: si fallan, una plaga cuarentenaria puede
pasar desapercibida. Los casos salen de reportes reales de campo.

Correr:  python tests/test_alertas_monitoreo.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.alertas_monitoreo_service import (  # noqa: E402
    evaluar_alerta_monitoreo,
    evaluar_dano_en_foto,
)

CASOS = [
    (
        "Stenoma catenifer es cuarentenaria aunque el reporte no diga 'activo'",
        "Finca la rivera, lote #3, se observa stenoma en rama, suelda, mosca blanca, "
        "doctoriella sacc. Se finaliza lote.",
        True,
    ),
    (
        "Heilipus elegans es cuarentenaria",
        "reviso el foco de heilipus elegans este foco sigue activo, se encuentra 4 larvas",
        True,
    ),
    (
        "El marcador ACTIVO que usa el equipo dispara alerta",
        "lote #14: Un foco de escamas ACTIVO, Focos de Mosca blanca ACTIVO",
        True,
    ),
    # Cinco de las ocho cuarentenarias del PLAN MIPE son cochinillas o escamas,
    # y el plan no lista ninguna que no lo sea en aguacate Hass. Asi que un
    # nombre de grupo sin especie va en alta igual: lo que falta por confirmar
    # es cual de las cinco, no si es cuarentenaria.
    (
        "Una cochinilla sin especie es cuarentenaria por el plan",
        "lote #7 se observa presencia de cochinilla en pedunculos",
        True,
    ),
    (
        "Y una escama tambien",
        "lote #12: se observan escamas en el enves de las hojas",
        True,
    ),
    (
        "Las tildes no deben afectar la comparacion",
        "monitoreo específico de ácaro en el lote #16, muy baja población",
        False,
    ),
    (
        "Un reporte rutinario no debe alertar",
        "Buenas tardes, monitoreo lote #11: thrips, seudosercospora, cephaleuros, "
        "sphaceloma, suelda, gusanos, antrasnosis en pedunculo y hoja. Se finaliza lote. "
        "1 monitora",
        False,
    ),
    (
        "'dano' es vocabulario rutinario en monitoreo y no debe alertar",
        "lote #9: Daño por comedores de follaje (gusanos, compsus, pandeleteius), "
        "daño por trips, fruta con golpe de sol",
        False,
    ),
    (
        "Un accidente siempre alerta",
        "se reporta accidente en el lote 5, un trabajador herido",
        True,
    ),
    # Los dos lotes de un mismo mensaje del 21/09/2026. Antes la regla corria
    # sobre el mensaje completo y el lote 10 salia marcado como cuarentenaria
    # por culpa del stenoma del lote 3. Ahora se evalua lo de cada lote.
    (
        "Hallazgos del lote 10, sin nada cuarentenario: no debe alertar",
        "ácaro - severidad 1-2-3 mosca blanca - baja thrips - severidad 1-2-3 "
        "pseudocercospora en hoja cephaleuros árboles cloróticos",
        False,
    ),
    (
        "Hallazgos del lote 3 del mismo mensaje: ese si alerta",
        "stenoma - daños viejos en rama sin presencia de larva",
        True,
    ),
]


# Fotos. Lo que decide es danos_observados: la lista cerrada que reporta el
# modelo de vision, no la prosa de la descripcion. La descripcion se conserva
# solo para que un humano pueda revisar.
#
# (descripcion, plagas_sugeridas, danos_observados, se_espera_alerta)
CASOS_FOTO = [
    (
        "Perforaciones en fruto: dano tipico de los barrenadores del plan",
        "Se observan frutos de aguacate Hass con multiples perforaciones pequenas y "
        "oscuras, acompanadas de exudaciones blanquecinas alrededor de las lesiones.",
        [],
        ["perforacion_en_fruto_rama_o_tallo", "exudacion_o_gomosis"],
        True,
    ),
    (
        "Cera blanca de cochinilla",
        "Rama con presencia de insectos cubiertos de una secrecion cerosa blanca, "
        "con acumulacion de melaza en la superficie.",
        [],
        ["secrecion_cerosa_o_algodonosa", "melaza_o_fumagina"],
        True,
    ),
    (
        "Candidata cuarentenaria aunque no se reporte dano visible",
        "Rama con pequenos insectos inmoviles adheridos a la corteza.",
        ["Ceroplastes rubens (escama cerosa roja)"],
        [],
        True,
    ),
    (
        "Candidata NO cuarentenaria no debe alertar",
        "Hoja con puntos rojizos en el enves y telarana fina.",
        ["Oligonychus yothersi (acaro cafe)"],
        [],
        False,
    ),
    (
        "Perforaciones en HOJA: el modelo no las reporta, son comedores de follaje",
        "Hoja de aguacate con multiples perforaciones circulares de bordes limpios y "
        "oscurecidos, distribuidas en el limbo foliar.",
        ["Monalonion velezangeli", "Diabrotica balteata"],
        [],
        False,
    ),
    (
        "Larvas dentro del fruto si alertan",
        "Fruto abierto con una larva blanca en el interior de la pulpa.",
        [],
        ["larva_en_fruto_rama_o_tallo"],
        True,
    ),
    (
        "Candidatas no cuarentenarias descartan el dano observado",
        "Fruto con perforaciones en la superficie.",
        ["Diabrotica balteata"],
        ["perforacion_en_fruto_rama_o_tallo"],
        False,
    ),
    (
        "Sin candidatas, el dano observado alerta por si solo",
        "Fruto con perforaciones en la superficie.",
        [],
        ["perforacion_en_fruto_rama_o_tallo"],
        True,
    ),
    (
        "Una candidata cuarentenaria manda, aunque haya otras que no lo son",
        "Rama con pequenos insectos adheridos.",
        ["Oligonychus yothersi (acaro cafe)", "Saissetia batesi (escama hemisferica)"],
        [],
        True,
    ),
    (
        "Manchas foliares: son enfermedades comunes, no cuarentenarias",
        "Hoja con manchas pequenas de color cafe oscuro, de bordes irregulares y "
        "halo clorotico alrededor.",
        ["Pseudocercospora purpurea (mancha angular de la hoja)"],
        [],
        False,
    ),
    # Los dos casos que dispararon alertas sobre plantas sanas el 21/09/2026.
    # La descripcion NIEGA el dano y aun asi se alertaba, porque se buscaban
    # las palabras en la prosa.
    (
        "Descripcion que NIEGA perforaciones y exudaciones no debe alertar",
        "Se observan ramas y hojas del arbol de aguacate Hass en buen estado general, "
        "con follaje verde y sin sintomas evidentes de dano. Las hojas presentan "
        "coloracion normal y las ramas muestran estructura integra sin perforaciones, "
        "manchas, defoliaciones o exudaciones aparentes.",
        [],
        [],
        False,
    ),
    (
        "Cultivo sano descrito enumerando lo que NO tiene",
        "Cultivo de aguacate Hass en zona montanosa con buen desarrollo vegetativo. "
        "Se observan plantas con follaje verde y denso, sin sintomas evidentes de "
        "dano, defoliacion, manchas, perforaciones o presencia visible de plagas en "
        "hojas, ramas o tallos.",
        [],
        [],
        False,
    ),
    (
        "Foto sin cultivo",
        "Se observa una persona de pie en un camino de tierra, sin cultivo visible.",
        [],
        [],
        False,
    ),
    (
        "Sin descripcion, sin candidatas ni danos",
        None,
        [],
        [],
        False,
    ),
]


def main() -> int:
    fallos = 0

    print("REGLAS SOBRE EL REPORTE ESCRITO")
    for descripcion, texto, esperado in CASOS:
        es_alerta, tipo, prioridad = evaluar_alerta_monitoreo(texto)
        if es_alerta != esperado:
            fallos += 1
            print(f"  FALLA: {descripcion}")
            print(f"    esperado es_alerta={esperado}, obtenido {es_alerta} ({tipo})")
        else:
            print(f"  ok: {descripcion} -> {tipo or 'sin alerta'}")

    print()
    print("DANO VISIBLE EN FOTOS")
    for descripcion, texto, sugeridas, danos, esperado in CASOS_FOTO:
        motivo = evaluar_dano_en_foto(texto, sugeridas, danos)
        if bool(motivo) != esperado:
            fallos += 1
            print(f"  FALLA: {descripcion}")
            print(f"    esperado alerta={esperado}, obtenido {bool(motivo)} ({motivo})")
        else:
            print(f"  ok: {descripcion} -> {motivo or 'sin alerta'}")

    total = len(CASOS) + len(CASOS_FOTO)
    print()
    if fallos:
        print(f"{fallos} de {total} casos fallaron")
        return 1
    print(f"{total} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
