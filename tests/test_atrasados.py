"""Un mensaje que llega tarde se registra, pero no se contesta.

Meta reintenta durante dias lo que no logro entregar. El 29 de septiembre a la
1:55 de la mañana llego una pregunta que se habia mandado el 23 a las 19:40,
con el agente apagado, y el agente la contesto como si fuera nueva: al
administrador le llego de madrugada la respuesta a algo que habia preguntado
seis dias antes.

Lo que se protege:
- Que a quien mando un mensaje atrasado no se le conteste nada: ni la
  pregunta, ni el lote que falta, ni el reporte original, ni el aviso de que
  un audio no se puede leer.
- Que lo que trae se registre igual y con la hora en que se mando: un reporte
  atrasado cuenta en su dia y alerta diciendo cuando se hizo, y una foto
  atrasada no se cuelga del reporte de hoy.

Crea sus propios registros y los borra al terminar. No manda WhatsApp ni
llama al modelo. Correr:  python tests/test_atrasados.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app import horario  # noqa: E402
from app.api import routes_meta_whatsapp as rutas  # noqa: E402
from app.db.supabase_client import get_client  # noqa: E402
from app.services import (  # noqa: E402
    consultas_service,
    fotos_service,
    meta_whatsapp_service,
    monitoreo_service,
    reporte_original_service,
    storage_service,
    vision_service,
)

NUMERO = "570000000888"
REMITENTE = f"whatsapp:+{NUMERO}"
CASOS = []

# Lo que paso: se mando el 23 a las 19:40 y llego el 29 a la 1:55.
ENVIADO = datetime(2026, 9, 23, 19, 40, 22, tzinfo=horario.ZONA)
LLEGADA = datetime(2026, 9, 29, 1, 55, 17, tzinfo=horario.ZONA)


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def mensaje(tipo="text", enviado=ENVIADO, **extra):
    base = {"from": NUMERO, "id": "wamid.PRUEBA_ATRASO", "type": tipo}
    if enviado is not None:
        base["timestamp"] = str(int(enviado.timestamp()))
    if tipo == "text":
        base["text"] = {"body": extra.pop("texto", "En qué lotes hay stenoma ?")}
    return {**base, **extra}


def limpiar(cli):
    ids = [f["id"] for f in cli.table("fotos").select("id").eq("remitente", REMITENTE).execute().data]
    if ids:
        cli.table("fotos").delete().in_("id", ids).execute()
    cli.table("monitoreos").delete().eq("remitente", REMITENTE).execute()
    cli.table("envios").delete().eq("destinatario", REMITENTE).execute()


# --------------------------------------------------------------------------
# La entrada del webhook decide si se contesta. Sin base: los servicios se
# sustituyen por unos que anotan con que se los llamo.
# --------------------------------------------------------------------------

originales = {
    nombre: getattr(rutas, nombre)
    for nombre in ("procesar_mensaje_monitoreo", "procesar_foto", "responder_a_mensaje_citado",
                   "_avisar_no_soportado")
}
llamadas = []
rutas.procesar_mensaje_monitoreo = lambda **kw: llamadas.append(("texto", kw))
rutas.procesar_foto = lambda **kw: llamadas.append(("foto", kw))
rutas.responder_a_mensaje_citado = lambda wamid, remitente, **kw: llamadas.append(("citado", kw)) or True
rutas._avisar_no_soportado = lambda remitente, tipo: llamadas.append(("no_soportado", tipo))

horario.ahora = lambda: LLEGADA


def procesar(m):
    llamadas.clear()
    rutas._procesar_mensaje(m)
    return list(llamadas)


print("LA PREGUNTA DE ANOCHE")
hecho = procesar(mensaje())
revisar("se procesa, por si fuera un reporte", [q for q, _ in hecho], ["texto"])
revisar("pero sin contestarle a quien la mando", hecho[0][1]["responder"], False)
revisar("y con la hora en que se mando, no la de llegada",
        hecho[0][1]["enviado_en"], ENVIADO.astimezone(timezone.utc))

print("\nDONDE ESTA EL LIMITE")
for minutos, contesta in ((0, True), (2, True), (59, True), (61, False), (60 * 24, False)):
    hecho = procesar(mensaje(enviado=LLEGADA - timedelta(minutes=minutos)))
    revisar(f"con {minutos} min de atraso {'se contesta' if contesta else 'no se contesta'}",
            hecho[0][1]["responder"], contesta)
hecho = procesar(mensaje(enviado=LLEGADA + timedelta(seconds=3)))
revisar("un reloj de Meta un poco adelantado no cuenta como atraso", hecho[0][1]["responder"], True)
hecho = procesar(mensaje(enviado=None))
revisar("sin hora de Meta se toma como recien llegado", hecho[0][1]["responder"], True)

print("\nNINGUNA RESPUESTA SE ESCAPA")
revisar("un audio atrasado no recibe el aviso de que no se puede leer",
        procesar(mensaje(tipo="audio", audio={"id": "m1"})), [])
revisar("uno reciente si",
        procesar(mensaje(tipo="audio", enviado=LLEGADA, audio={"id": "m1"})), [("no_soportado", "audio")])
hecho = procesar(mensaje(context={"id": "wamid.ALERTA"}))
revisar("la respuesta atrasada a una alerta llega sin permiso de contestar",
        (hecho[0][0], hecho[0][1]["responder"]), ("citado", False))
hecho = procesar(mensaje(tipo="image", image={"id": "media1", "caption": "lote 3 stenoma"}))
revisar("una foto atrasada: el texto y la foto, sin contestar",
        [(q, kw["responder"]) for q, kw in hecho], [("texto", False), ("foto", False)])
revisar("y los dos con la hora en que se mando",
        {kw["enviado_en"] for _, kw in hecho}, {ENVIADO.astimezone(timezone.utc)})

for nombre, funcion in originales.items():
    setattr(rutas, nombre, funcion)

print("\nPEDIR EL REPORTE ORIGINAL TARDE")
mandados = []
reporte_original_service._envio = lambda w: {"tipo": "alerta_reporte", "referencia": "monitoreo:1"}
reporte_original_service.es_administrador = lambda r: True
reporte_original_service._mandar_texto = lambda *a: mandados.append(a)
reporte_original_service.enviar_reporte = lambda *a, **k: mandados.append(a) or {"reportes": 1}
revisar("se da por atendido, para que no siga como reporte",
        reporte_original_service.responder_a_mensaje_citado("wamid.X", REMITENTE, responder=False), True)
revisar("y no se manda nada", list(mandados), [])


# --------------------------------------------------------------------------
# Los servicios, contra la base real.
# --------------------------------------------------------------------------


def main() -> int:
    cli = get_client()
    limpiar(cli)

    enviados, alertas, consultas = [], [], []
    meta_whatsapp_service.enviar_mensaje = lambda n, t: enviados.append(t) or "wamid.PRUEBA"
    meta_whatsapp_service.enviar_plantilla_a_administradores = (
        lambda nombre, parametros, **kw: alertas.append(parametros)
    )
    consultas_service.es_administrador = lambda r: True
    consultas_service.responder = lambda texto, remitente: consultas.append(texto)

    print("\nLA PREGUNTA DE ANOCHE, HASTA EL FINAL")
    monitoreo_service.extraer_reportes_monitoreo = lambda texto: []
    monitoreo_service.procesar_mensaje_monitoreo(
        "En qué lotes hay stenoma ?", REMITENTE, enviado_en=ENVIADO, responder=False
    )
    revisar("no se le pregunta al modelo ni se contesta", (list(consultas), list(enviados)), ([], []))
    monitoreo_service.procesar_mensaje_monitoreo(
        "En qué lotes hay stenoma ?", REMITENTE, enviado_en=LLEGADA, responder=True
    )
    revisar("la misma pregunta a tiempo si se contesta", list(consultas), ["En qué lotes hay stenoma ?"])

    print("\nUN REPORTE ATRASADO, SIN LOTE Y CON STENOMA")
    texto = "PRUEBA finca alfa, se observa stenoma en rama"
    monitoreo_service.extraer_reportes_monitoreo = lambda t: [
        {"finca": "alfa", "lote": None, "plagas_observadas": ["stenoma en rama"]}
    ]
    guardados = monitoreo_service.procesar_mensaje_monitoreo(
        texto, REMITENTE, enviado_en=ENVIADO, responder=False
    )
    revisar("se guarda", len(guardados), 1)
    revisar("en el dia en que se mando, no en el que llego",
            horario.fecha_de(datetime.fromisoformat(guardados[0]["fecha_hora"])), "2026-09-23")
    revisar("no se le pide el lote a nadie", list(enviados), [])
    revisar("la alerta sale igual: nadie sabia del stenoma", len(alertas), 1)
    revisar("diciendo cuando se reporto",
            "el 23 de septiembre a las 19:40" in str(alertas[0][-1] if alertas else ""), True)

    print("\nY SI LLEGA OTRA COPIA DEL MISMO REPORTE")
    alertas.clear()
    otra = monitoreo_service.procesar_mensaje_monitoreo(
        texto, REMITENTE, enviado_en=ENVIADO + timedelta(minutes=3), responder=False
    )
    filas = cli.table("monitoreos").select("id").eq("remitente", REMITENTE).execute().data
    revisar("se reconoce en su dia y no se duplica", (otra, len(filas)), ([], 1))
    revisar("sin avisarle a nadie", (list(enviados), list(alertas)), ([], []))

    print("\nUNA FOTO ATRASADA")
    hace_poco = datetime.now(timezone.utc) - timedelta(minutes=10)
    for finca, lote, cuando in (("alfa", "3", hace_poco), ("rivera", "7", hace_poco + timedelta(minutes=5))):
        cli.table("monitoreos").insert({
            "fecha_hora": cuando.isoformat(), "remitente": REMITENTE,
            "texto_original": f"PRUEBA finca {finca} lote {lote}", "finca": finca, "lote": lote,
        }).execute()
    del_23 = guardados[0]["id"]

    rutas_subidas = []
    meta_whatsapp_service.descargar_media = lambda media_id: (b"imagen", "image/jpeg")
    vision_service.describir_foto = lambda contenido, mime: None
    storage_service.subir_foto = lambda ruta, contenido, mime: rutas_subidas.append(ruta) or ruta

    foto = fotos_service.procesar_foto("media-atrasada-1", REMITENTE, enviado_en=ENVIADO, responder=False)
    revisar("se cuelga del reporte de su dia, no del de hoy", foto["monitoreo_id"], del_23)
    revisar("queda con la hora en que se mando",
            datetime.fromisoformat(foto["fecha_hora"]), ENVIADO.astimezone(timezone.utc))
    revisar("y se archiva con esa fecha", "2026-09-24" in (rutas_subidas or [""])[0], True)
    revisar("no se pregunta de que lote es", list(enviados), [])

    print("\nUNA FOTO RECIENTE, CON DOS LOTES POSIBLES")
    ahora = datetime.now(timezone.utc)
    fotos_service.procesar_foto("media-reciente-1", REMITENTE, enviado_en=ahora, responder=False)
    revisar("sin permiso de contestar, no pregunta", list(enviados), [])
    fotos_service.procesar_foto("media-reciente-2", REMITENTE, enviado_en=ahora, responder=True)
    revisar("a tiempo, si pregunta de que lote es", len(enviados), 1)

    limpiar(cli)

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
