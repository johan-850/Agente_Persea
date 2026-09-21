"""Cuando un reporte llega sin lote, el agente lo pide y espera el numero.

El riesgo esta en confundirse: si un mensaje cualquiera se toma por respuesta,
el numero se cuelga del reporte equivocado y el agronomo va al lote que no es.
Ante la duda se devuelve None y el reporte se queda sin lote, que es
recuperable; una asociacion errada no se nota.

No llama al modelo. Correr:  python tests/test_respuesta_lote.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.monitoreo_service import _lote_en_respuesta  # noqa: E402

CASOS = [
    # Lo que de verdad responde una monitora
    ("12", "12"),
    ("  7  ", "7"),
    ("#14", "14"),
    ("lote 12", "12"),
    ("Lote #3", "3"),
    ("el lote 18", "18"),
    ("es el lote 9", "9"),
    ("perdón, lote 5", "5"),
    # Un reporte completo NO es una respuesta, aunque nombre el lote: si se
    # tomara como tal, el reporte se perderia y el numero iria a otro sitio.
    (
        "Buenas tardes finca la linda, monitoreo general lote #10 donde se observa "
        "acaro severidad 1-2-3, mosca blanca baja, thrips en floracion. 1 monitora",
        None,
    ),
    (
        "Buenas tardes, finca La Rivera, se inicia jornada continuando con el bordeo "
        "de la línea 1 a la 7, en el lote 18. Se observa stenoma en rama.",
        None,
    ),
    # Mensajes con numeros que no son el lote
    ("ya voy en 10 minutos", None),
    ("se contó con 2 monitoras", None),
    ("listo", None),
    ("buenas tardes", None),
    # Vacios
    (None, None),
    ("", None),
]


def main() -> int:
    fallos = 0
    for entrada, esperado in CASOS:
        obtenido = _lote_en_respuesta(entrada)
        if obtenido != esperado:
            fallos += 1
            print(f"  FALLA: {str(entrada)[:60]!r} -> {obtenido!r}, se esperaba {esperado!r}")
        else:
            etiqueta = "lote " + obtenido if obtenido else "no es respuesta"
            print(f"  ok: {str(entrada)[:52]!r:<56} -> {etiqueta}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
