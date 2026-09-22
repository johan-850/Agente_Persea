"""El resumen semanal tiene que decir algo que los cinco diarios no dicen.

Un diario lista lote por lote lo de ese dia. La semana aporta dos cosas que
solo se ven mirandola entera: en cuantos lotes se disperso cada cuarentenaria,
y que lotes siguen alertando dia tras dia.

No llama a la base ni al modelo: se le pasan los registros. Correr:
    python tests/test_resumen_semanal.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.resumen_semanal_service import (  # noqa: E402
    _cuarentenarias_de_la_semana,
    _detalle_plano,
    _lotes_persistentes,
    formatear,
)


def monitoreo(dia, finca, lote, plagas, alerta=True):
    return {
        "id": abs(hash((dia, finca, lote))) % 10000,
        # Las 14:00 de Colombia son las 19:00 UTC: dentro de la jornada.
        "fecha_hora": f"2026-09-{dia}T19:00:00+00:00",
        "finca": finca,
        "lote": lote,
        "es_alerta": alerta,
        "plagas_observadas": plagas,
    }


SEMANA = [
    # Stenoma repartido en tres fincas: eso es dispersion
    monitoreo("21", "rivera", "5", ["stenoma en rama", "suelda"]),
    monitoreo("21", "alfa", "8", ["Stenoma catenifer - en fruto"]),
    monitoreo("22", "la linda", "3", ["stenoma - daños viejos"]),
    # El mismo lote alertando dos dias: eso es persistencia
    monitoreo("22", "rivera", "14", ["Stenoma catenifer - foco ACTIVO (4 larvas)"]),
    monitoreo("23", "rivera", "14", ["stenoma en rama"]),
    # Heilipus, con un foco activo
    monitoreo("23", "rivera", "16", ["Heilipus lauri - foco ACTIVO con larva"]),
    # Lotes de numero alto y bajo en la misma finca, para el orden
    monitoreo("24", "alfa", "10", ["stenoma en rama"]),
    monitoreo("24", "alfa", "2", ["stenoma en rama"]),
    # Rutina: no alerta y no debe aparecer entre las cuarentenarias
    monitoreo("25", "buena vista", "4", ["acaro - severidad 3", "mosca blanca"], alerta=False),
]

FOTOS = [{"id": i, "monitoreo_id": 1, "es_alerta": i % 3 == 0} for i in range(1, 13)]

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


grupos = _cuarentenarias_de_la_semana(SEMANA)

# rivera 5, alfa 8, la linda 3, rivera 14, alfa 10, alfa 2. El lote 14 aparece
# dos dias pero cuenta una vez: lo que se mide aqui es en cuantos lotes se
# disperso, no cuantas veces se reporto.
revisar("agrupa stenoma de las tres fincas", len(grupos["Stenoma catenifer"]), 6)
revisar("agrupa heilipus aparte", len(grupos["Heilipus (barrenadores)"]), 1)
revisar("un lote rutinario no entra", "buena vista 4" in grupos.get("Stenoma catenifer", {}), False)
revisar("recuerda que el foco estaba ACTIVO", grupos["Stenoma catenifer"]["rivera 14"], True)
revisar("y que en otro lote no lo estaba", grupos["Stenoma catenifer"]["rivera 5"], False)

persistentes = dict(_lotes_persistentes(SEMANA))
revisar("detecta el lote que alerto dos dias", persistentes.get("rivera 14"), 2)
revisar("un lote de un solo dia no es persistente", "rivera 5" in persistentes, False)

texto = formatear("2026-09-21", "2026-09-25", SEMANA, FOTOS)
revisar("el periodo se lee en castellano", "21 al 25 de septiembre" in texto, True)
revisar("el lote 2 va antes que el 10", texto.index("alfa 2") < texto.index("alfa 10"), True)
revisar("marca el foco activo", "rivera 14 (ACTIVO)" in texto, True)
revisar("avisa de la persistencia", "rivera 14 — 2 días" in texto, True)
revisar("cuenta las fotos con daño", "4 con daño compatible" in texto, True)

plano = _detalle_plano(SEMANA, FOTOS)
revisar("el detalle corto encabeza con la plaga mas dispersa",
        plano.startswith("Stenoma catenifer en 6 lote(s)"), True)
revisar("el detalle corto cabe en el parametro", len(plano) <= 300, True)

vacio = formatear("2026-09-21", "2026-09-25", [], [])
revisar("una semana sin reportes se dice y ya", "No se recibieron reportes" in vacio, True)

sin_alertas = formatear(
    "2026-09-21", "2026-09-25",
    [monitoreo("21", "alfa", "1", ["acaro"], alerta=False)], [],
)
revisar("una semana limpia lo dice explicitamente",
        "Ninguna plaga cuarentenaria" in sin_alertas, True)


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
