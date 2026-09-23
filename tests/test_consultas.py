"""Los administradores preguntan por los datos desde WhatsApp.

Dos cosas que importan aqui:

- Solo los administradores. Una monitora que escriba una pregunta no debe
  recibir el historial de las fincas.
- Las consultas recortan las listas que devuelven, y el total tiene que viajar
  aparte. Si solo se manda la lista recortada, el modelo cuenta los elementos
  que ve y responde ese numero: con 14 fotos dañadas y una muestra de 10,
  contestaba "10 mostraron daño". Un dato mal que nadie nota.

Usa la base real para leer, pero no escribe nada ni manda WhatsApp.
Correr:  python tests/test_consultas.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services import consultas_service  # noqa: E402
from app.services.consultas_service import (  # noqa: E402
    CONSULTAS,
    HERRAMIENTAS,
    MAX_FILAS,
    _actividad_por_finca,
    _alertas_recientes,
    _buscar_plaga,
    _estado_de_lote,
)

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


print("CADA HERRAMIENTA DECLARADA TIENE SU CONSULTA")
declaradas = {h["name"] for h in HERRAMIENTAS}
revisar("los nombres coinciden", declaradas, set(CONSULTAS))
revisar("todas son invocables", all(callable(f) for f in CONSULTAS.values()), True)

print("\nEL TOTAL VIAJA APARTE DE LA MUESTRA")
estado = _estado_de_lote("18", "rivera")
revisar("estado_de_lote trae el total de fotos con daño",
        "fotos_con_dano_total" in estado, True)
revisar("y la muestra va en otra clave",
        "muestra_de_fotos_con_dano" in estado, True)
revisar("el total no puede ser menor que la muestra",
        estado["fotos_con_dano_total"] >= len(estado["muestra_de_fotos_con_dano"]), True)
revisar("ni mayor que el total de fotos",
        estado["fotos_con_dano_total"] <= estado["fotos_totales"], True)

alertas = _alertas_recientes(30)
revisar("alertas_recientes dice cuantas hay en total", "total" in alertas, True)
revisar("y cuantas esta mostrando", "mostradas" in alertas, True)
revisar("la muestra respeta el tope", alertas["mostradas"] <= MAX_FILAS, True)
revisar("el total no es menor que lo mostrado",
        alertas["total"] >= alertas["mostradas"], True)

plaga = _buscar_plaga("stenoma", 30)
revisar("buscar_plaga cuenta las apariciones", "total_apariciones" in plaga, True)
revisar("y lista los lotes distintos", isinstance(plaga["lotes_distintos"], list), True)

print("\nSOLO RESPONDE A ADMINISTRADORES")
revisar("el numero registrado si",
        consultas_service.es_administrador("whatsapp:+573159793011"), True)
revisar("un numero cualquiera no",
        consultas_service.es_administrador("whatsapp:+573001112233"), False)
revisar("un valor vacio no", consultas_service.es_administrador(""), False)
revisar("el formato con prefijo no importa",
        consultas_service.es_administrador("+57 315 979 3011"), True)

print("\nUN LOTE QUE NO EXISTE NO REVIENTA")
vacio = _estado_de_lote("999", "rivera")
revisar("devuelve la estructura igual, sin reportes", vacio["reportes"], [])
revisar("y sin fotos", vacio["fotos_con_dano_total"], 0)

print("\nLA ACTIVIDAD POR FINCA CUENTA LOTES DISTINTOS, NO REPORTES")
actividad = _actividad_por_finca(30)
for finca, datos in actividad.items():
    revisar(f"{finca}: los lotes distintos no superan los reportes",
            datos["lotes_distintos"] <= datos["reportes"], True)
    revisar(f"{finca}: las alertas no superan los reportes",
            datos["alertas"] <= datos["reportes"], True)


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
