"""El resumen diario, para que diga algo.

Cada foto propone sus candidatas por separado. Juntandolas todas, un lote con
cinco fotos dañadas listaba diez especies —practicamente el catalogo
cuarentenario entero— y eso no informa: quien lo lee aprende a saltarselo.
Lo que aporta señal es la repeticion. Si tres de cinco fotos apuntan a
Heilipus, eso es un indicio; una sola que menciona Saissetia entre otras nueve
es ruido.

Y cuenta lotes, no mensajes: el aviso de mediodia y el cierre del mismo lote
son un reporte.

No llama a la base ni al modelo. Correr:  python tests/test_resumen_diario.py
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.resumen_service import (  # noqa: E402
    _formatear_resumen,
    _fotos_de,
    _fotos_por_reporte,
    _lotes_que_atender,
    _resumir_candidatas,
    _texto_fotos,
    reportes_por_lote,
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

print("\nUN LOTE ES UN REPORTE, AUNQUE LLEGUEN DOS MENSAJES")


def fila(id_, hora_utc, finca, lote, plagas, alerta=False, finalizado=None, dia="29"):
    return {
        "id": id_, "fecha_hora": f"2026-09-{dia}T{hora_utc}:00+00:00", "finca": finca, "lote": lote,
        "plagas_observadas": plagas, "es_alerta": alerta, "lote_finalizado": finalizado, "tipo_alerta": None,
    }


# El 29 de septiembre de la simulacion, en pequeño. Rivera 7 y alfa 5 avisaron
# a mediodia y lo repitieron en el cierre; el resumen dijo "4 con alerta" por
# dos hallazgos. Las horas son UTC: de 10:45 a 16:35 en Colombia.
DIA = [
    fila(1, "15:45", "rivera", "7", ["Stenoma catenifer - 3 ramas afectadas, 1 larva viva"], alerta=True),
    fila(2, "16:20", "alfa", "12", ["acaro - severidad 2"]),
    fila(3, "16:55", "alfa", "5", ["mosca blanca - foco ACTIVO"], alerta=True),
    fila(4, "17:40", "rivera", "18", ["Monalonion velezangeli - 2 ninfas y 1 adulto"]),
    fila(5, "21:05", "rivera", "7", ["Stenoma catenifer - foco marcado en la línea 4", "acaro - poca población"],
         alerta=True, finalizado=False),
    fila(6, "21:12", "alfa", "12", ["ácaro - severidad 1-2-3", "mosca blanca - baja"], finalizado=True),
    fila(7, "21:20", "alfa", "5", ["mosca blanca - foco ACTIVO", "trips"], alerta=True, finalizado=False),
    fila(8, "21:35", "rivera", "18", ["caída de cuaje", "chancro"], finalizado=False),
    # Sin lote: no hay como saber si son del mismo.
    fila(9, "20:55", "buena vista", None, ["mosca blanca - baja"]),
    fila(10, "20:58", "buena vista", None, ["bruggmaniella"]),
]
lotes = reportes_por_lote(DIA)
por_lote = {(l["finca"], l["lote"]): l for l in lotes if l["lote"]}

revisar("diez mensajes son seis lotes", len(lotes), 6)
revisar("dos con alerta, no cuatro", sum(1 for l in lotes if l["es_alerta"]), 2)
atender = _lotes_que_atender(lotes)
revisar("cada lote aparece una vez entre los que requieren atencion",
        (atender.count("rivera lote 7"), atender.count("alfa lote 5")), (1, 1))
revisar("el hallazgo repetido queda con la descripcion mas reciente",
        por_lote[("rivera", "7")]["plagas_observadas"][0], "Stenoma catenifer - foco marcado en la línea 4")
revisar("y el acaro de alfa 12, con la del cierre",
        por_lote[("alfa", "12")]["plagas_observadas"][0], "ácaro - severidad 1-2-3")
revisar("lo que se aviso a mediodia y el cierre olvido no se pierde",
        "Monalonion velezangeli - 2 ninfas y 1 adulto" in por_lote[("rivera", "18")]["plagas_observadas"], True)
revisar("el estado del lote es el del cierre", por_lote[("alfa", "12")]["lote_finalizado"], True)
revisar("los reportes sin lote no se juntan", sum(1 for l in lotes if not l["lote"]), 2)
revisar("juntar lo ya juntado no cambia nada",
        sorted(tuple(l["ids"]) for l in reportes_por_lote(lotes)), sorted(tuple(l["ids"]) for l in lotes))
activo_y_despues = reportes_por_lote([
    fila(1, "15:00", "alfa", "5", ["mosca blanca - foco ACTIVO"], alerta=True),
    fila(2, "21:00", "alfa", "5", ["mosca blanca - foco controlado"]),
])
revisar("un foco que estuvo ACTIVO no se borra porque el cierre no lo repita",
        activo_y_despues[0]["plagas_observadas"], ["mosca blanca - foco ACTIVO", "mosca blanca - foco controlado"])
dicho_distinto = reportes_por_lote([
    fila(1, "17:15", "buena vista", "8", ["cochinilla"], alerta=True),
    fila(2, "21:30", "buena vista", "8", ["cochinilla en pedúnculos de 2 frutos", "suelda"], alerta=True),
])
revisar("el mismo hallazgo dicho de dos formas va una vez, con la descripcion del cierre",
        _lotes_que_atender(dicho_distinto), "buena vista lote 8 - cochinilla en pedúnculos de 2 frutos")
mediodia_sin_labor = fila(1, "18:40", "rivera", "20", ["marceño en rama y fruta"])
cierre_de_bordeo = {**fila(2, "21:40", "rivera", "20", ["chancro"]), "tipo_labor": "bordeo"}
revisar("la labor del lote es la del cierre, aunque el aviso de mediodia no la diga",
        reportes_por_lote([{**mediodia_sin_labor, "tipo_labor": None}, cierre_de_bordeo])[0]["tipo_labor"], "bordeo")
revisar("y no se pierde si despues llega otro aviso sin labor",
        reportes_por_lote([cierre_de_bordeo, {**fila(3, "21:50", "rivera", "20", ["platinota"]), "tipo_labor": None}])
        [0]["tipo_labor"], "bordeo")
revisar("el mismo lote en dos dias son dos reportes",
        len(reportes_por_lote([fila(1, "15:00", "rivera", "14", ["stenoma"]),
                               fila(2, "15:00", "rivera", "14", ["stenoma"], dia="30")])), 2)

fotos_del_dia = [{"monitoreo_id": 1, "es_alerta": True, "plagas_sugeridas": []},
                 {"monitoreo_id": 5, "es_alerta": False, "plagas_sugeridas": []}]
revisar("las fotos del lote suman las de sus dos reportes",
        _fotos_de(_fotos_por_reporte(fotos_del_dia), por_lote[("rivera", "7")])["total"], 2)
texto = _formatear_resumen("2026-09-29", lotes, fotos_del_dia)
revisar("el texto libre cuenta lotes", "6 lote(s) reportado(s)" in texto, True)
revisar("y dos que requieren atencion", "2 lote(s) requieren atención" in texto, True)


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
