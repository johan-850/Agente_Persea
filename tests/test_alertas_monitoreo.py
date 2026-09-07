"""Pruebas de las reglas duras de alerta de monitoreo.

Son la red de seguridad del sistema: si fallan, una plaga cuarentenaria puede
pasar desapercibida. Los casos salen de reportes reales de campo.

Correr:  python tests/test_alertas_monitoreo.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.alertas_monitoreo_service import evaluar_alerta_monitoreo  # noqa: E402

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


def main() -> int:
    fallos = 0
    for descripcion, texto, esperado in CASOS:
        es_alerta, tipo, prioridad = evaluar_alerta_monitoreo(texto)
        if es_alerta != esperado:
            fallos += 1
            print(f"FALLA: {descripcion}")
            print(f"  esperado es_alerta={esperado}, obtenido {es_alerta} ({tipo})")
        else:
            print(f"ok: {descripcion} -> {tipo or 'sin alerta'}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
