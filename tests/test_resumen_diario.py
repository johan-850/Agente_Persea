"""Las candidatas de las fotos, resumidas para que digan algo.

Cada foto propone sus candidatas por separado. Juntandolas todas, un lote con
cinco fotos dañadas listaba diez especies —practicamente el catalogo
cuarentenario entero— y eso no informa: quien lo lee aprende a saltarselo.

Lo que aporta señal es la repeticion. Si tres de cinco fotos apuntan a
Heilipus, eso es un indicio; una sola que menciona Saissetia entre otras nueve
es ruido.

No llama a la base ni al modelo. Correr:  python tests/test_resumen_diario.py
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.resumen_service import (  # noqa: E402
    _fotos_por_reporte,
    _resumir_candidatas,
    _texto_fotos,
)

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


print("QUE CANDIDATAS SE NOMBRAN")

# El caso real del lote 15: 5 fotos con daño, 10 especies propuestas, y solo
# tres de ellas aparecen mas de una vez.
real = Counter({
    "Heilipus elegans": 3, "Saissetia batesi": 2, "Stenoma catenifer": 2,
    "Astaena aff pygidialis": 1, "Monalonion velezangeli": 1, "Ceroplastes rubens": 1,
    "Pseudococcus landoi": 1, "Maconellicoccus hirsutus": 1,
    "Pseudococcus jackbeardsleyi": 1, "Heilipus lauri": 1,
})
texto = _resumir_candidatas(real, 5)
revisar("nombra la que mas se repite", "Heilipus elegans (3 de 5)" in texto, True)
revisar("y dice sobre cuantas fotos", "de 5" in texto, True)
revisar("descarta las que salen una sola vez",
        "Astaena aff pygidialis" not in texto, True)
revisar("no lista las diez", texto.count(",") <= 2, True)

revisar("sin candidatas no dice nada", _resumir_candidatas(Counter(), 3), "")
revisar("si ninguna se repite, no presume",
        _resumir_candidatas(Counter({"A": 1, "B": 1, "C": 1}), 1),
        "posibles: A, B")
revisar("una que se repite manda sobre las sueltas",
        _resumir_candidatas(Counter({"A": 3, "B": 1, "C": 1}), 5),
        "sobre todo A (3 de 5)")
revisar("se nombran como maximo tres",
        _resumir_candidatas(Counter({"A": 5, "B": 4, "C": 3, "D": 2}), 6).count("(") , 3)

print("\nLA LINEA COMPLETA DE FOTOS")
revisar("sin fotos no hay linea", _texto_fotos(None), "")
revisar("fotos sin daño solo se cuentan",
        _texto_fotos({"total": 8, "con_dano": 0, "candidatas": Counter()}),
        " [8 foto(s)]")
linea = _texto_fotos({"total": 25, "con_dano": 5, "candidatas": real})
revisar("con daño se dice cuantas de cuantas", "25 foto(s), 5 con daño" in linea, True)
revisar("y cabe en una linea legible", len(linea) < 140, True)

print("\nSE CUENTA POR FOTO, NO POR MENCION")
fotos = [
    {"monitoreo_id": 1, "es_alerta": True,
     # La misma candidata repetida dentro de UNA foto cuenta una vez: si no,
     # una sola foto insistente pareceria un patron.
     "plagas_sugeridas": ["Heilipus elegans", "Heilipus elegans", "Stenoma catenifer"]},
    {"monitoreo_id": 1, "es_alerta": True, "plagas_sugeridas": ["Heilipus elegans"]},
    {"monitoreo_id": 1, "es_alerta": False, "plagas_sugeridas": ["Chancro bacteriano"]},
]
entrada = _fotos_por_reporte(fotos)[1]
revisar("cuenta todas las fotos", entrada["total"], 3)
revisar("y solo las que tienen daño", entrada["con_dano"], 2)
revisar("una candidata repetida dentro de una foto cuenta una vez",
        entrada["candidatas"]["Heilipus elegans"], 2)
revisar("las de fotos sin daño no entran",
        "Chancro bacteriano" in entrada["candidatas"], False)


def main() -> int:
    fallos = 0
    for descripcion, obtenido, esperado in CASOS:
        if obtenido != esperado:
            fallos += 1
            print(f"  FALLA: {descripcion} -> {obtenido!r}, se esperaba {esperado!r}")
        else:
            print(f"  ok: {descripcion}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
