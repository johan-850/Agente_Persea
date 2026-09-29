"""De noche las alertas esperan a la mañana.

El 29 de septiembre a la 1:55 de la mañana le llego a un administrador un
mensaje del agente. De noche el agente ya no le escribe a nadie por su
cuenta: las alertas quedan aplazadas en envios, con lo que habia que mandar,
y salen en la primera vuelta despues de las 6:00.

Lo que se protege:
- Que de noche una alerta no salga, y que tampoco se pierda.
- Que al amanecer salga una sola vez, aunque dos procesos la busquen a la
  vez, como pasa en cada despliegue.
- Que los resumenes, que tienen su hora configurada, no se aplacen.
- Que si no se puede guardar para despues, salga ya: tarde es mejor que nunca.

Usa la base real (crea y borra sus propias filas) pero no manda WhatsApp: el
envio esta interceptado. Necesita la migracion 006.
Correr:  python tests/test_silencio.py
"""

import os
import sys
import threading
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app import horario  # noqa: E402
from app.db.supabase_client import get_client  # noqa: E402
from app.services import (  # noqa: E402
    envios_service,
    meta_whatsapp_service,
    monitoreo_service,
    resumen_semanal_service,
    resumen_service,
)

TIPO = "prueba_silencio"
ADMINS = ["+570000000301", "+570000000302"]
ALERTA_DE_PRUEBA = 999999999
CASOS = []

NOCHE = datetime(2026, 9, 29, 1, 55, tzinfo=horario.ZONA)
MADRUGADA = datetime(2026, 9, 29, 5, 59, tzinfo=horario.ZONA)
AMANECER = datetime(2026, 9, 29, 6, 1, tzinfo=horario.ZONA)
MEDIODIA = datetime(2026, 9, 29, 12, 0, tzinfo=horario.ZONA)


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def a_las(momento):
    horario.ahora = lambda: momento


def limpiar():
    cli = get_client()
    cli.table("envios").delete().like("tipo", f"{TIPO}%").execute()
    cli.table("envios").delete().eq("referencia", f"monitoreo:{ALERTA_DE_PRUEBA}").execute()


def filas(tipo=TIPO):
    return get_client().table("envios").select("*").eq("tipo", tipo).order("id").execute().data


def main() -> int:
    limpiar()

    meta_whatsapp_service._administradores = lambda: list(ADMINS)
    plantillas, textos = [], []
    meta_whatsapp_service.enviar_plantilla = (
        lambda numero, nombre, params: plantillas.append((numero, nombre)) or f"wamid.P{len(plantillas)}"
    )
    meta_whatsapp_service.enviar_mensaje = (
        lambda numero, texto: textos.append((numero, texto)) or f"wamid.T{len(textos)}"
    )
    candidatas = (["plantilla_v2", "plantilla_v1"], [["alta", "alfa"], ["alta alfa"]])

    print("DE NOCHE LA ALERTA NO SALE")
    a_las(NOCHE)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        *candidatas, respaldo="respaldo libre", tipo=TIPO, referencia="monitoreo:1"
    )
    f = filas()
    revisar("a la 1:55 no se manda nada", (list(plantillas), list(textos)), ([], []))
    revisar("queda una por administrador", [x["destinatario"] for x in f], ADMINS)
    revisar("aplazadas", {x["estado"] for x in f}, {"aplazado"})
    revisar("con lo que habia que mandar, en orden de preferencia", f[0]["contenido"], {
        "candidatas": [["plantilla_v2", ["alta", "alfa"]], ["plantilla_v1", ["alta alfa"]]],
        "respaldo": "respaldo libre",
    })
    revisar("y con la referencia, para poder pedir despues el reporte original",
            {x["referencia"] for x in f}, {"monitoreo:1"})

    print("\nMIENTRAS SEA DE NOCHE, ESPERA")
    a_las(MADRUGADA)
    revisar("a las 5:59 no sale nada", meta_whatsapp_service.despachar_aplazados(), 0)
    revisar("ni se toca", {x["estado"] for x in filas()}, {"aplazado"})

    print("\nAL AMANECER SALE, UNA VEZ")
    a_las(AMANECER)
    revisar("a las 6:01 salen las dos", meta_whatsapp_service.despachar_aplazados(), 2)
    revisar("por la plantilla preferida, a cada administrador",
            list(plantillas), [(ADMINS[0], "plantilla_v2"), (ADMINS[1], "plantilla_v2")])
    f = filas()
    revisar("quedan aceptadas", {x["estado"] for x in f}, {"aceptado"})
    revisar("con el id de Meta, para cruzar los acuses", all(x["wamid"] for x in f), True)
    revisar("y la plantilla que salio", {x["plantilla"] for x in f}, {"plantilla_v2"})
    revisar("la hora es la del envio, no la de la noche",
            {datetime.fromisoformat(x["fecha_hora"]) for x in f}, {AMANECER})
    revisar("una segunda vuelta no repite nada", meta_whatsapp_service.despachar_aplazados(), 0)
    revisar("ni manda de nuevo", len(plantillas), 2)

    print("\nDOS PROCESOS BUSCANDOLAS A LA VEZ")
    limpiar()
    plantillas.clear()
    a_las(NOCHE)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="r", tipo=TIPO, referencia="foto:9"
    )
    primera = filas()[0]["id"]
    revisar("el primero que la toma se la queda", envios_service.tomar_aplazado(primera), True)
    revisar("el segundo ya no", envios_service.tomar_aplazado(primera), False)

    limpiar()
    a_las(NOCHE)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="r", tipo=TIPO, referencia="foto:10"
    )
    a_las(AMANECER)
    resultados = []
    hilos = [
        threading.Thread(target=lambda: resultados.append(meta_whatsapp_service.despachar_aplazados()))
        for _ in range(6)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    revisar("seis vueltas a la vez mandan cada alerta una sola vez", len(plantillas), 2)
    revisar("entre todas suman las dos", sum(resultados), 2)

    print("\nEL TEXTO LIBRE TAMBIEN ESPERA")
    limpiar()
    textos.clear()
    a_las(NOCHE)
    meta_whatsapp_service.enviar_a_administradores(
        "📍 Complemento: lote 3", tipo=TIPO, referencia="monitoreo:2"
    )
    revisar("de noche no sale", list(textos), [])
    a_las(AMANECER)
    meta_whatsapp_service.despachar_aplazados()
    revisar("al amanecer sale tal cual", [t for _, t in textos], ["📍 Complemento: lote 3"] * 2)
    f = filas()
    revisar("sin plantilla ni explicacion de fallo", {(x["plantilla"], x["detalle"]) for x in f}, {(None, None)})

    print("\nSI LA PLANTILLA FALLA AL AMANECER, SALVA EL TEXTO LIBRE")
    limpiar()
    textos.clear()
    a_las(NOCHE)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="respaldo", tipo=TIPO
    )
    enviar_plantilla = meta_whatsapp_service.enviar_plantilla

    def plantilla_rota(numero, nombre, params):
        raise RuntimeError("plantilla sin aprobar")

    meta_whatsapp_service.enviar_plantilla = plantilla_rota
    a_las(AMANECER)
    meta_whatsapp_service.despachar_aplazados()
    meta_whatsapp_service.enviar_plantilla = enviar_plantilla
    f = filas()
    revisar("sale por texto libre", [t for _, t in textos], ["respaldo"] * 2)
    revisar("y queda dicho por que", all("plantilla sin aprobar" in (x["detalle"] or "") for x in f), True)

    print("\nSI NO SE PUEDE GUARDAR PARA DESPUES, SALE YA")
    limpiar()
    plantillas.clear()
    a_las(NOCHE)
    aplazar = envios_service.aplazar
    envios_service.aplazar = lambda *a, **k: False
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="r", tipo=TIPO
    )
    envios_service.aplazar = aplazar
    revisar("sale de noche antes que perderse", len(plantillas), 2)
    revisar("y queda registrada como cualquier envio", {x["estado"] for x in filas()}, {"aceptado"})

    print("\nDE DIA NADA CAMBIA")
    limpiar()
    plantillas.clear()
    a_las(MEDIODIA)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="r", tipo=TIPO
    )
    f = filas()
    revisar("sale en el momento", len(plantillas), 2)
    revisar("sin pasar por aplazado", {(x["estado"], x["contenido"] is None) for x in f}, {("aceptado", True)})

    print("\nLOS RESUMENES NO ESPERAN")
    limpiar()
    plantillas.clear()
    a_las(NOCHE)
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_resumen", ["a"], respaldo="r", tipo=TIPO, aplazar_de_noche=False
    )
    revisar("con aplazar_de_noche=False sale aunque sea de noche", len(plantillas), 2)

    pedidos = []
    enviar_a_admins = meta_whatsapp_service.enviar_plantilla_a_administradores
    meta_whatsapp_service.enviar_plantilla_a_administradores = (
        lambda *a, **kw: pedidos.append(kw.get("aplazar_de_noche", True))
    )
    resumen_service.enviar_resumen_diario("2026-09-28")
    resumen_semanal_service.enviar_resumen_semanal("2026-09-25")
    meta_whatsapp_service.enviar_plantilla_a_administradores = enviar_a_admins
    revisar("el diario y el semanal lo piden asi", list(pedidos), [False, False])

    print("\nLAS ALERTAS SI ESPERAN, SIN PEDIRLO")
    plantillas.clear()
    a_las(NOCHE)
    monitoreo_service._notificar_alerta({
        "id": ALERTA_DE_PRUEBA,
        "fecha_hora": "2026-09-29T06:50:00+00:00",
        "remitente": "whatsapp:+570000000999",
        "texto_original": "PRUEBA finca alfa lote 3, stenoma en rama",
        "finca": "alfa",
        "lote": "3",
        "prioridad": "alta",
        "tipo_alerta": "plaga cuarentenaria",
        "plagas_observadas": ["stenoma en rama"],
    })
    f = filas("alerta_reporte")
    f = [x for x in f if x["referencia"] == f"monitoreo:{ALERTA_DE_PRUEBA}"]
    revisar("la alerta de un reporte de noche no sale", list(plantillas), [])
    revisar("queda aplazada para cada administrador", [x["estado"] for x in f], ["aplazado"] * 2)
    parametros = f[0]["contenido"]["candidatas"][0][1] if f else []
    revisar("y dice a que hora se reporto, porque se va a leer en la mañana",
            parametros[-1] if parametros else None, "whatsapp:+570000000999 el 29 de septiembre a las 01:50")

    limpiar()

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
