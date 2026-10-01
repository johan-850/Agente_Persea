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
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app import horario  # noqa: E402
from app.services import consultas_service  # noqa: E402
from app.services.consultas_service import (  # noqa: E402
    ACCIONES,
    CONSULTAS,
    HERRAMIENTAS,
    MAX_FILAS,
    _actividad,
    _actividad_por_finca,
    _alertas_recientes,
    _buscar_en,
    _buscar_plaga,
    _estado_de_lote,
    _reportes_del_dia,
    _todas,
)
from app.services.resumen_service import _monitoreos_del_dia, reportes_por_lote  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


print("CADA HERRAMIENTA DECLARADA TIENE SU CONSULTA O SU ACCION")
declaradas = {h["name"] for h in HERRAMIENTAS}
revisar("los nombres coinciden", declaradas, set(CONSULTAS) | set(ACCIONES))
revisar("ninguna esta en los dos lados", set(CONSULTAS) & set(ACCIONES), set())
revisar("todas son invocables",
        all(callable(f) for f in [*CONSULTAS.values(), *ACCIONES.values()]), True)

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


def fila(id_, hora_utc, finca, lote, plagas, alerta=False):
    return {"id": id_, "fecha_hora": f"2026-09-30T{hora_utc}:00+00:00", "finca": finca, "lote": lote,
            "plagas_observadas": plagas, "es_alerta": alerta}


print("\nCUENTA COMO EL RESUMEN: UN REPORTE POR LOTE Y DIA")
# El 30 de septiembre de la simulacion: a "¿cuanto llevamos hoy?" el bot
# respondia 14 reportes mientras el resumen decia 9 lotes.
dia = [
    fila(1, "14:40", "la linda", "10", ["Heilipus elegans - 2 larvas"], alerta=True),
    fila(2, "21:00", "la linda", "10", ["Heilipus elegans - 2 larvas en tallo", "mosca blanca"], alerta=True),
    fila(3, "20:50", "la linda", "9", ["sphaceloma"]),
]
revisar("el aviso de mediodia y el cierre son un reporte",
        _actividad(dia)["la linda"], {"reportes": 2, "lotes_distintos": 2, "lotes": ["10", "9"], "alertas": 1})
revisar("y el mismo lote en dos dias, dos",
        _actividad([*dia, {**fila(4, "15:00", "la linda", "10", ["suelda"]),
                           "fecha_hora": "2026-10-01T15:00:00+00:00"}])["la linda"]["reportes"], 3)
del_dia = _reportes_del_dia("2026-09-30")
revisar("lo de un dia cuenta los mismos lotes que su resumen",
        del_dia["total_lotes"], len(reportes_por_lote(_monitoreos_del_dia("2026-09-30"))))
revisar("y dice cuantos alertaron", "con_alerta" in del_dia, True)

print("\nLA BUSQUEDA NO DEPENDE DE TILDES NI MAYUSCULAS")
filas = [
    fila(1, "15:00", "alfa", "12", ["acaro - severidad 2"]),
    fila(2, "16:00", "alfa", "14", ["Ácaro - severidad 1-2"]),
    fila(3, "17:00", "rivera", "7", ["ácaro - poca población", "pseudocercospora"]),
    fila(4, "18:00", "rivera", "8", ["mosca blanca - baja"]),
]
revisar("'ácaro' encuentra las tres formas", _buscar_en(filas, "ácaro")["total_apariciones"], 3)
revisar("'acaro' tambien", _buscar_en(filas, "acaro")["total_apariciones"], 3)
revisar("y 'ÁCARO'", _buscar_en(filas, "ÁCARO")["lotes_distintos"], ["alfa 12", "alfa 14", "rivera 7"])
revisar("contra la base, con tilde o sin ella encuentra lo mismo",
        _buscar_plaga("ácaro", 60)["total_apariciones"], _buscar_plaga("acaro", 60)["total_apariciones"])

print("\nDICE SI ALERTA ESA PLAGA, NO SI EL REPORTE ALERTO POR OTRA")
# Rivera 7 alerto por stenoma. Preguntando por acaro, el modelo leia "alerto"
# y contestaba que el acaro habia alertado.
con_stenoma = [fila(1, "21:05", "rivera", "7", ["Stenoma catenifer - 1 larva viva", "ácaro - poca población"],
                    alerta=True)]
revisar("el acaro de un lote que alerto por stenoma no alerta",
        _buscar_en(con_stenoma, "acaro")["apariciones"][0]["alerta_por_esta_plaga"], False)
revisar("el stenoma si", _buscar_en(con_stenoma, "stenoma")["apariciones"][0]["alerta_por_esta_plaga"], True)
revisar("y un foco ACTIVO de acaro tambien",
        _buscar_en([fila(2, "15:00", "alfa", "5", ["acaro - foco ACTIVO"], alerta=True)], "acaro")
        ["apariciones"][0]["alerta_por_esta_plaga"], True)

print("\nEL MODELO SABE QUE DIA ES")
# Sin la fecha, a "¿que entro el 30 de septiembre?" consulto el de 2024.
horario.ahora = lambda: datetime(2026, 9, 30, 19, 0, tzinfo=horario.ZONA)
hoy_texto = consultas_service._fecha_de_hoy()
revisar("con el dia de la semana y la fecha", "miercoles 30 de septiembre de 2026" in hoy_texto, True)
revisar("y en el formato de las herramientas", "2026-09-30" in hoy_texto, True)
enviado = {}
consultas_service.modelo_ia.conversar_con_herramientas = (
    lambda sistema, *a, **k: enviado.update(sistema=sistema) or "ok"
)
consultas_service._enviar = lambda texto, remitente: texto
consultas_service.responder("¿que entro ayer?", "whatsapp:+573159793011")
revisar("y le llega al modelo en cada consulta", "2026-09-30" in enviado.get("sistema", ""), True)

print("\nLAS CONSULTAS LARGAS NO SE CORTAN EN MIL")


class _Consulta:
    """Una consulta falsa que, como la API, devuelve como mucho mil filas."""

    def __init__(self, datos):
        self.datos = datos

    def range(self, desde, hasta):
        self.pagina = self.datos[desde:min(hasta + 1, desde + 1000)]
        return self

    def execute(self):
        return type("Respuesta", (), {"data": self.pagina})()


revisar("2.500 filas llegan las 2.500", len(_todas(lambda: _Consulta(list(range(2500))))), 2500)
revisar("en orden y sin repetir", _todas(lambda: _Consulta(list(range(2500)))), list(range(2500)))
revisar("exactamente mil tambien", len(_todas(lambda: _Consulta(list(range(1000))))), 1000)
revisar("y ninguna, ninguna", _todas(lambda: _Consulta([])), [])


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
