"""Las cuatro fincas tienen que quedar siempre con el mismo nombre.

En un solo dia la misma finca entro como "Rivera", "rivera", "La Rivera",
"la rivera" y "Ribera", y buena vista como "buenavista" y "buena vista". Asi
no se puede agrupar por finca, ni filtrar su historial, ni contar cuantos
lotes lleva el dia: el resumen diario listaba la misma finca cinco veces.

No llama al modelo. Correr:  python tests/test_normalizacion_finca.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.monitoreo_ia_service import _normalizar_finca  # noqa: E402

CASOS = [
    # Las cinco formas de la misma finca vistas en reportes reales
    ("Rivera", "rivera"),
    ("rivera", "rivera"),
    ("La Rivera", "rivera"),
    ("la rivera", "rivera"),
    ("Ribera", "rivera"),
    ("finca Ribera", "rivera"),
    # buena vista, junta y separada
    ("buenavista", "buena vista"),
    ("buena vista", "buena vista"),
    ("Buena Vista", "buena vista"),
    # las otras dos
    ("la linda", "la linda"),
    ("LA LINDA", "la linda"),
    ("  La Linda  ", "la linda"),
    ("alfa", "alfa"),
    # Una finca desconocida se conserva tal cual: puede ser un predio nuevo o
    # arrendado, y perder el dato seria peor que no normalizarlo.
    ("El Retiro", "El Retiro"),
    # Vacios
    (None, None),
    ("", None),
    ("   ", None),
]


def main() -> int:
    fallos = 0
    for entrada, esperado in CASOS:
        obtenido = _normalizar_finca(entrada)
        if obtenido != esperado:
            fallos += 1
            print(f"  FALLA: {entrada!r} -> {obtenido!r}, se esperaba {esperado!r}")
        else:
            print(f"  ok: {str(entrada)!r:<16} -> {obtenido!r}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
