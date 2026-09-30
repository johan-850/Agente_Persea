"""El ACTIVO lo escribe la monitora, no el modelo.

ACTIVO es el marcador con que el equipo señala un foco urgente, y dispara una
alerta aunque la plaga no sea cuarentenaria. En la simulacion del 29 de
septiembre una monitora escribio "foco marcado en la línea 4" y el registro
quedo "foco ACTIVO". Con stenoma no cambio nada, porque alerta igual; con
acaro habria sido una alerta falsa.

No llama a la base ni al modelo: se le pasa lo que el modelo habria
extraido. Correr:  python tests/test_activo_inventado.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.alertas_monitoreo_service import evaluar_alerta_monitoreo  # noqa: E402
from app.services.monitoreo_ia_service import _sin_activo_inventado  # noqa: E402
from app.services.monitoreo_service import _texto_del_lote  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def extraido(plagas, es_alerta=False, tipo=None, prioridad=None, nota=None):
    return {
        "finca": "alfa", "lote": "12", "plagas_observadas": list(plagas), "nota": nota,
        "es_alerta": es_alerta, "tipo_alerta": tipo, "prioridad": prioridad,
    }


print("LO QUE PASO EL 29")
texto = (
    "Buenas tardes\nFinca rivera\nSe continúa monitoreo general en el lote #7 donde se evidencia:\n"
    "· Stenoma en rama, foco marcado en la línea 4 (1 larva viva)\n· Poca población de ácaro"
)
r = _sin_activo_inventado(
    extraido(["Stenoma catenifer - foco ACTIVO en rama línea 4 (1 larva viva)", "acaro - poca poblacion"],
             True, "plaga cuarentenaria", "alta"),
    texto,
)
revisar("se quita el ACTIVO que no escribio",
        r["plagas_observadas"][0], "Stenoma catenifer - foco en rama línea 4 (1 larva viva)")
revisar("lo demas queda igual", r["plagas_observadas"][1], "acaro - poca poblacion")
revisar("la alerta sigue: era por la cuarentenaria, no por el ACTIVO",
        (r["es_alerta"], r["tipo_alerta"]), (True, "plaga cuarentenaria"))

print("\nCON UNA PLAGA QUE NO ES CUARENTENARIA")
texto = "Finca alfa lote #12, en la línea 3 hay un foco marcado de ácaro, severidad 2. 1 monitora"
r = _sin_activo_inventado(extraido(["acaro - foco ACTIVO, severidad 2"], True, "foco activo", "alta"), texto)
revisar("se quita el ACTIVO", r["plagas_observadas"], ["acaro - foco, severidad 2"])
revisar("y la alerta del modelo, que era por el",
        (r["es_alerta"], r["tipo_alerta"], r["prioridad"]), (False, None, None))
revisar("las reglas tampoco alertan con lo que queda", evaluar_alerta_monitoreo(_texto_del_lote(r))[0], False)

print("\nSI LA MONITORA LO ESCRIBIO, NO SE TOCA")
texto = "Alfa lote #5: se encontró un foco de mosca blanca ACTIVO en la línea 3"
original = extraido(["mosca blanca - foco ACTIVO"], True, "foco_activo", "alta")
revisar("se conserva todo", _sin_activo_inventado(dict(original), texto), original)
revisar("aunque lo escriba en minuscula",
        _sin_activo_inventado(dict(original), texto.replace("ACTIVO", "activo"))["plagas_observadas"],
        ["mosca blanca - foco ACTIVO"])
revisar("'inactivo' no es ACTIVO",
        _sin_activo_inventado(extraido(["acaro - foco ACTIVO"]), "foco de acaro inactivo")["plagas_observadas"],
        ["acaro - foco"])

print("\nLOS BORDES")
sin_nada = extraido(["trips - severidad 2"])
revisar("sin ACTIVO en ningun lado no cambia nada", _sin_activo_inventado(dict(sin_nada), "lote 3 trips"), sin_nada)
revisar("un hallazgo que solo decia ACTIVO desaparece",
        _sin_activo_inventado(extraido(["ACTIVO", "trips"]), "lote 3 trips")["plagas_observadas"], ["trips"])
revisar("la nota tambien se limpia",
        _sin_activo_inventado(extraido([], nota="foco ACTIVO en la linea 3"), "foco en la linea 3")["nota"],
        "foco en la linea 3")


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
