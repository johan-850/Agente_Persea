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
    (
        "Un grupo sin especie alerta, pero con menor prioridad",
        "lote #7 se observa presencia de cochinilla en pedunculos",
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
]


# Descripciones de fotos. La descripcion la produce el modelo de vision, que
# tiene prohibido nombrar especies, asi que aqui solo se buscan danos visibles.
CASOS_FOTO = [
    (
        "Perforaciones en fruto: dano tipico de los barrenadores del plan",
        "Se observan frutos de aguacate Hass con multiples perforaciones pequenas y "
        "oscuras, acompanadas de exudaciones blanquecinas alrededor de las lesiones.",
        [],
        True,
    ),
    (
        "Cera blanca de cochinilla",
        "Rama con presencia de insectos cubiertos de una secrecion cerosa blanca, "
        "con acumulacion de melaza en la superficie.",
        [],
        True,
    ),
    (
        "Candidata cuarentenaria aunque la descripcion no traiga patron",
        "Rama con pequenos insectos inmoviles adheridos a la corteza.",
        ["Ceroplastes rubens (escama cerosa roja)"],
        True,
    ),
    (
        "Candidata NO cuarentenaria no debe alertar",
        "Hoja con puntos rojizos en el enves y telarana fina.",
        ["Oligonychus yothersi (acaro cafe)"],
        False,
    ),
    (
        "Perforaciones en HOJA son comedores de follaje, no barrenadores",
        "Hoja de aguacate con multiples perforaciones circulares de bordes limpios y "
        "oscurecidos, distribuidas en el limbo foliar. Se observa un insecto rojo-"
        "amarillento sobre la vena central.",
        ["Monalonion velezangeli", "Diabrotica balteata"],
        False,
    ),
    (
        "Larvas en HOJA tampoco alertan",
        "Hoja con varias larvas verdes alimentandose del borde del limbo.",
        [],
        False,
    ),
    (
        "Larvas dentro del fruto si alertan",
        "Fruto abierto con una larva blanca en el interior de la pulpa.",
        [],
        True,
    ),
    (
        "Manchas foliares: son enfermedades comunes, no cuarentenarias",
        "Hoja con manchas pequenas de color cafe oscuro, de bordes irregulares y "
        "halo clorotico alrededor.",
        ["Pseudocercospora purpurea (mancha angular de la hoja)"],
        False,
    ),
    (
        "Foto sin cultivo",
        "Se observa una persona de pie en un camino de tierra, sin cultivo visible.",
        [],
        False,
    ),
    (
        "Sin descripcion ni candidatas",
        None,
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
    print("PATRONES DE DANO EN FOTOS")
    for descripcion, texto, sugeridas, esperado in CASOS_FOTO:
        motivo = evaluar_dano_en_foto(texto, sugeridas)
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
