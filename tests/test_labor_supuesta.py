"""La labor se guarda si el mensaje la dice, no por defecto.

Un aviso a mitad de jornada ("Reporto hallazgo en finca rivera lote #7") no
dice que labor se estaba haciendo, y el modelo ponia "monitoreo general". En
la simulacion del 29 y 30 de septiembre, el hallazgo de mediodia de un bordeo
quedo guardado como monitoreo general: una consulta como "cuantos bordeos
hubo" contaria mal.

No llama a la base ni al modelo: se le pasa lo que el modelo habria
extraido. Correr:  python tests/test_labor_supuesta.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.monitoreo_ia_service import _sin_labor_supuesta  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def labor(texto, supuesta):
    return _sin_labor_supuesta({"tipo_labor": supuesta}, texto)["tipo_labor"]


print("SI EL MENSAJE NO LA DICE, QUEDA VACIA")
revisar("un aviso de mediodia",
        labor("Reporto hallazgo en finca rivera lote #7: en la línea 4 se encontró stenoma en rama",
              "monitoreo general"), None)
revisar("el hallazgo de mediodia del bordeo de rivera 20",
        labor("Rivera lote 20, en la línea 6 marceño en rama y fruta, y platinota", "monitoreo general"), None)
revisar("'se informa para aplicación' es una recomendacion, no la labor",
        labor("Finca alfa lote 5, seguimiento al foco de mosca blanca de ayer. Se informa para aplicación.",
              "monitoreo específico"), None)

print("\nSI LA DICE, QUEDA LA DEL MODELO")
revisar("un cierre de bordeo",
        labor("Buenas tardes, finca La Rivera, bordeo lote #20 de la línea 1 a la 8", "bordeo"), "bordeo")
revisar("'monitoreo' a secas: general o especifico lo lee el modelo",
        labor("Finca la linda, monitoreo lote #8, se observa mosca blanca", "monitoreo general"),
        "monitoreo general")
revisar("la labor dicha una vez vale para el otro lote del mensaje",
        labor("Se inicia jornada continuando con monitoreo específico en lote #13... Se pasa a realizar "
              "esta misma labor al lote #14", "monitoreo específico"), "monitoreo específico")
revisar("con tilde o sin ella", labor("Capacitación en finca alfa, lote 3", "capacitación"), "capacitación")
revisar("la aplicacion con dron", labor("Aplicación con dron en el lote 4", "aplicación con dron"),
        "aplicación con dron")
revisar("vacia sigue vacia", labor("Reporto hallazgo en el lote 7", None), None)


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
