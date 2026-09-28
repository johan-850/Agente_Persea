"""El administrador pide el reporte original y le llega tal cual.

Dos caminos: respondiendo a la alerta en WhatsApp, o pidiendolo por escrito.
Lo que se protege:

- El texto llega exacto, sin pasar por el modelo: se pidio el original.
- Van las fotos del reporte, primero las de daño, con tope.
- Solo lo atiende si es un administrador y si lo citado es una alerta.
  Responder a un resumen o a la pregunta de lote sigue su camino normal.

No toca la base ni manda nada: se sustituyen las lecturas y los envios.
Correr:  python tests/test_reporte_original.py
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import routes_meta_whatsapp as rutas  # noqa: E402
from app.services import (  # noqa: E402
    consultas_service,
    envios_service,
    meta_whatsapp_service,
    modelo_ia,
    storage_service,
)
from app.services import reporte_original_service as ro  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


# --------------------------------------------------------------------------
# Datos y envios de mentira.
# --------------------------------------------------------------------------
TEXTO = (
    "Buenas tardes\nFinca rivera\nSe continua con monitoreo especifico en lote #14 "
    "donde se evidencia:\n· Un foco de escamas ACTIVO\n· Stenoma en fruto\nNo se finaliza lote"
)
MONITOREOS = {
    92: {"id": 92, "fecha_hora": "2026-09-28T20:55:57+00:00", "remitente": "whatsapp:+573001112233",
         "texto_original": TEXTO, "finca": "rivera", "lote": "14", "es_alerta": True},
}


def foto(id_, dano=False, archivada=True, monitoreo=92):
    return {"id": id_, "monitoreo_id": monitoreo, "es_alerta": dano,
            "storage_path": f"2026/09/f{id_}.jpg" if archivada else None,
            "descripcion": f"descripcion {id_}", "plagas_sugeridas": ["Stenoma catenifer"] if dano else [],
            "caption": None}


FOTOS = [foto(1), foto(2), foto(3, archivada=False), foto(4, dano=True), foto(5), foto(6, dano=True),
         foto(7), foto(8)]
FOTOS_POR_ID = {f["id"]: f for f in FOTOS} | {50: foto(50, dano=True, monitoreo=None)}
ENVIOS = {
    "wamid.ALERTA": {"tipo": "alerta_reporte", "referencia": "monitoreo:92"},
    "wamid.ALERTA_FOTO": {"tipo": "alerta_foto", "referencia": "foto:6"},
    "wamid.FOTO_SUELTA": {"tipo": "alerta_foto", "referencia": "foto:50"},
    "wamid.COMPLEMENTO": {"tipo": "complemento_lote", "referencia": "monitoreo:92"},
    "wamid.BORRADO": {"tipo": "alerta_reporte", "referencia": "monitoreo:999"},
    "wamid.RESUMEN": {"tipo": "resumen_diario", "referencia": "2026-09-28"},
    "wamid.PREGUNTA": {"tipo": "pregunta_lote_foto", "referencia": None},
}

ro._envio = ENVIOS.get
ro._monitoreo = MONITOREOS.get
ro._foto = FOTOS_POR_ID.get
ro._fotos_del_reporte = lambda mid: [f for f in FOTOS if f["monitoreo_id"] == mid]
ADMIN = "whatsapp:+573159793011"
ro.es_administrador = lambda remitente: remitente == ADMIN

enviados: list[tuple] = []
meta_whatsapp_service.enviar_mensaje = lambda numero, texto: enviados.append(("texto", numero, texto)) or "wamid.X"
meta_whatsapp_service.enviar_imagen = (
    lambda numero, enlace, leyenda="": enviados.append(("imagen", numero, enlace, leyenda)) or "wamid.X"
)
storage_service.url_firmada = lambda ruta, vigencia=0: f"https://firmado/{ruta}?token=abc"
envios_service.registrar = lambda *a, **k: None


def textos():
    return [e[2] for e in enviados if e[0] == "texto"]


def imagenes():
    return [e[2].split("/")[-1].split("?")[0] for e in enviados if e[0] == "imagen"]


# --------------------------------------------------------------------------
print("RESPONDER A UNA ALERTA DE REPORTE")
enviados.clear()
revisar("lo atiende", ro.responder_a_mensaje_citado("wamid.ALERTA", ADMIN), True)
revisar("todo va al que pregunto", {e[1] for e in enviados}, {ADMIN})
revisar("primero dice de que reporte se trata",
        "rivera, lote 14" in textos()[0] and "Reporte original" in textos()[0], True)
revisar("con la hora de Colombia, no la del servidor", "2026-09-28 a las 15:55" in textos()[0], True)
revisar("y quien lo mando", "+573001112233" in textos()[0], True)
revisar("el texto llega exacto, sin tocar", textos()[1], TEXTO)
revisar("las fotos con daño van primero", imagenes()[:2], ["f4.jpg", "f6.jpg"])
revisar("no pasa del tope de fotos", len(imagenes()) <= ro.MAX_FOTOS, True)
revisar("la que no se archivo se salta sin romper nada", "f3.jpg" in imagenes(), False)
revisar("avisa cuantas fotos quedaron sin mandar",
        any("tiene 8 fotos" in t for t in textos()), True)
leyendas = {e[2].split("/")[-1].split("?")[0]: e[3] for e in enviados if e[0] == "imagen"}
revisar("la foto con daño dice sus candidatas como hipotesis",
        "Compatible con: Stenoma catenifer" in leyendas["f4.jpg"], True)
revisar("la foto sin daño no inventa candidatas", "Compatible" in leyendas["f1.jpg"], False)

print("\nRESPONDER A UNA ALERTA DE FOTO")
enviados.clear()
revisar("lo atiende", ro.responder_a_mensaje_citado("wamid.ALERTA_FOTO", ADMIN), True)
revisar("manda el reporte al que pertenece la foto", textos()[1], TEXTO)
revisar("la foto citada va primero", imagenes()[0], "f6.jpg")
revisar("y no se repite", imagenes().count("f6.jpg"), 1)

enviados.clear()
ro.responder_a_mensaje_citado("wamid.FOTO_SUELTA", ADMIN)
revisar("una foto sin reporte se manda sola, y lo dice",
        (imagenes(), "sin un reporte" in textos()[0]), (["f50.jpg"], True))

print("\nOTRAS ALERTAS Y LO QUE NO SE ATIENDE")
enviados.clear()
revisar("el complemento de lote tambien lleva a su reporte",
        ro.responder_a_mensaje_citado("wamid.COMPLEMENTO", ADMIN), True)
enviados.clear()
revisar("si el reporte ya no existe, lo atiende", ro.responder_a_mensaje_citado("wamid.BORRADO", ADMIN), True)
revisar("y avisa en vez de callar", "No encontré" in textos()[0], True)
for wamid, que in (("wamid.RESUMEN", "un resumen"), ("wamid.PREGUNTA", "la pregunta de lote"),
                   ("wamid.DESCONOCIDO", "un mensaje que no es nuestro")):
    enviados.clear()
    revisar(f"responder a {que} sigue su camino normal",
            (ro.responder_a_mensaje_citado(wamid, ADMIN), list(enviados)), (False, []))
enviados.clear()
revisar("una monitora que cita una alerta no la ve",
        (ro.responder_a_mensaje_citado("wamid.ALERTA", "whatsapp:+573001112233"), list(enviados)), (False, []))

print("\nTEXTOS LARGOS")
largo = "\n".join(f"linea {i}: " + "x" * 90 for i in range(100))
partes = ro.trozos(largo)
revisar("se parte en mensajes que WhatsApp acepta",
        all(len(p) <= meta_whatsapp_service.LARGO_MAXIMO_TEXTO for p in partes), True)
revisar("en mas de uno", len(partes) > 1, True)
revisar("sin perder ni un caracter", "".join(partes), largo)
revisar("cortando por lineas, no a mitad", all(p.endswith("\n") for p in partes[:-1]), True)
sin_saltos = "y" * 9000
revisar("una sola linea enorme tambien se parte sin perder nada",
        "".join(ro.trozos(sin_saltos)) == sin_saltos and max(map(len, ro.trozos(sin_saltos))) <= 4000, True)

print("\nPEDIRLO POR ESCRITO")
pedidos = []


def reportes_del_lote(lote, finca, desde, hasta):
    pedidos.append((lote, finca, hasta is not None))
    return [{"id": 92, "fecha_hora": MONITOREOS[92]["fecha_hora"], "finca": "rivera", "lote": "14"}]


ro._reportes_del_lote = reportes_del_lote
enviados.clear()
r = ro.mostrar_por_lote("14", ADMIN, finca="rivera")
revisar("sin fecha busca el mas reciente del lote", (pedidos[-1], r["encontrados"]), (("14", "rivera", False), 1))
revisar("y lo manda tal cual", textos()[1], TEXTO)
revisar("le dice al modelo que ya se envio, no el texto", ("enviado" in r, "texto_original" in str(r)), (True, False))
ro.mostrar_por_lote("14", ADMIN, fecha="2026-09-28")
revisar("con fecha busca en ese dia", pedidos[-1][2], True)
ro._reportes_del_lote = lambda *a: []
enviados.clear()
revisar("si no hay reporte, no manda nada y lo dice", (ro.mostrar_por_lote("99", ADMIN), list(enviados)),
        ({"encontrados": 0, "enviado": False}, []))

print("\nLA CONSULTA LE PASA EL NUMERO DE QUIEN PREGUNTA")
revisar("esta entre las herramientas del modelo",
        "mostrar_reporte_original" in [h["name"] for h in consultas_service.HERRAMIENTAS], True)
recibido = {}
consultas_service.ACCIONES["mostrar_reporte_original"] = (
    lambda destinatario, **kw: recibido.update(destinatario=destinatario, **kw) or {"enviado": True}
)
bloque = SimpleNamespace(type="tool_use", name="mostrar_reporte_original", id="t1",
                         input={"lote": "14", "finca": "rivera", "fecha": None})
respuestas = [SimpleNamespace(stop_reason="tool_use", content=[bloque]),
              SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Listo, te lo mandé.")])]
modelo_ia._cliente = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: respuestas.pop(0)))
consultas_service._enviar = lambda texto, remitente: texto
consultas_service.responder("muestrame el reporte original del 14 de rivera", ADMIN)
revisar("la accion recibe a quien mandarle", recibido.get("destinatario"), ADMIN)
revisar("y lo que pidio el modelo", (recibido.get("lote"), recibido.get("finca")), ("14", "rivera"))

print("\nEN LA ENTRADA DEL WEBHOOK")
atendidos, procesados = [], []
rutas.responder_a_mensaje_citado = lambda wamid, remitente: atendidos.append(wamid) or wamid == "wamid.ALERTA"
rutas.procesar_mensaje_monitoreo = lambda texto, remitente: procesados.append(texto)
rutas._procesar_mensaje({"from": "573159793011", "type": "text", "text": {"body": "ver"},
                         "context": {"id": "wamid.ALERTA"}})
revisar("una respuesta a una alerta no llega a procesarse como reporte", (list(atendidos), list(procesados)),
        (["wamid.ALERTA"], []))
rutas._procesar_mensaje({"from": "573159793011", "type": "text", "text": {"body": "¿y hoy?"},
                         "context": {"id": "wamid.RESUMEN"}})
revisar("una respuesta a otra cosa sigue como mensaje normal", list(procesados), ["¿y hoy?"])
atendidos.clear()
rutas._procesar_mensaje({"from": "573159793011", "type": "text", "text": {"body": "Finca alfa lote 3"}})
revisar("un mensaje que no cita nada ni pregunta por alertas", (list(atendidos), procesados[-1]),
        ([], "Finca alfa lote 3"))


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
