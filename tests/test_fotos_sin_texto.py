"""Fotos que llegan sueltas: el agente pregunta de que lote son.

Cuando una monitora manda varios reportes seguidos y despues las fotos sin
texto, la heuristica de asociacion no tiene forma de saber a cual pertenece
cada una: se las cuelga todas al ultimo reporte. Un dia las 25 fotos de la
jornada acabaron en el lote 15.

Colgarlas del lote equivocado es peor que no colgarlas: manda al agronomo al
lote que no es, y nadie lo corrige porque nadie lo nota. Asi que se pregunta.

Crea sus propios registros y los borra al terminar. No manda WhatsApp.
Correr:  python tests/test_fotos_sin_texto.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db.supabase_client import get_client  # noqa: E402
from app.services import fotos_service, meta_whatsapp_service, monitoreo_service  # noqa: E402

REMITENTE = "whatsapp:+570000000777"
CASOS = []
enviados = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def limpiar(cli):
    ids = [f["id"] for f in cli.table("fotos").select("id").eq("remitente", REMITENTE).execute().data]
    if ids:
        cli.table("fotos").delete().in_("id", ids).execute()
    cli.table("monitoreos").delete().eq("remitente", REMITENTE).execute()
    cli.table("envios").delete().eq("destinatario", REMITENTE).execute()


def main() -> int:
    cli = get_client()
    meta_whatsapp_service.enviar_mensaje = lambda n, t: enviados.append(t) or "wamid.PRUEBA"

    limpiar(cli)
    ahora = datetime.now(timezone.utc).isoformat()

    # Dos reportes de lotes distintos, como los que llegan seguidos
    monitoreos = []
    for finca, lote in (("alfa", "3"), ("la linda", "15")):
        fila = cli.table("monitoreos").insert({
            "fecha_hora": ahora,
            "remitente": REMITENTE,
            "texto_original": f"PRUEBA finca {finca} lote {lote}",
            "finca": finca,
            "lote": lote,
            "plagas_observadas": ["acaro"],
        }).execute().data[0]
        monitoreos.append(fila)

    # Tres fotos sueltas, sin texto: la heuristica las cuelga del ultimo
    ultimo = monitoreos[-1]
    for i in range(3):
        cli.table("fotos").insert({
            "fecha_hora": ahora,
            "remitente": REMITENTE,
            "media_id": f"prueba-{i}",
            "caption": None,
            "monitoreo_id": ultimo["id"],
        }).execute()

    print("HAY AMBIGUEDAD: se reportaron dos lotes")
    candidatos = fotos_service._lotes_candidatos(REMITENTE)
    revisar("se ven los dos lotes como candidatos", len(candidatos), 2)
    revisar("todavia no se ha preguntado",
            fotos_service._ya_se_pregunto_por_fotos(REMITENTE), False)

    print("\nSE PREGUNTA UNA SOLA VEZ")
    enviados.clear()
    fotos_service._preguntar_de_que_lote_son(REMITENTE, candidatos)
    revisar("se mando la pregunta", len(enviados), 1)
    pregunta = enviados[0] if enviados else ""
    revisar("nombra los dos lotes", "alfa 3" in pregunta and "la linda 15" in pregunta, True)
    revisar("queda registrada, para no repetirla",
            fotos_service._ya_se_pregunto_por_fotos(REMITENTE), True)

    print("\nLA MONITORA RESPONDE CON EL LOTE")
    sueltas = fotos_service.fotos_sin_confirmar(REMITENTE)
    revisar("hay tres fotos sueltas", len(sueltas), 3)
    revisar("colgadas del ultimo reporte",
            {f["monitoreo_id"] for f in sueltas}, {ultimo["id"]})

    enviados.clear()
    destino = monitoreos[0]          # alfa 3, que NO es donde estaban
    consumido = monitoreo_service._completar_lote_pendiente("3", REMITENTE)
    revisar("el mensaje se consume como respuesta, no como reporte", consumido, True)
    revisar("se confirma a la monitora", len(enviados), 1)

    despues = fotos_service.fotos_sin_confirmar(REMITENTE)
    revisar("las tres quedaron en el lote indicado",
            {f["monitoreo_id"] for f in despues}, {destino["id"]})

    print("\nUN NUMERO SUELTO SIN NADA PENDIENTE NO HACE NADA")
    cli.table("fotos").delete().eq("remitente", REMITENTE).execute()
    revisar("no se consume", monitoreo_service._completar_lote_pendiente("3", REMITENTE), False)

    print("\nSIN AMBIGUEDAD NO SE PREGUNTA")
    cli.table("monitoreos").delete().eq("id", monitoreos[1]["id"]).execute()
    revisar("con un solo lote reportado, un solo candidato",
            len(fotos_service._lotes_candidatos(REMITENTE)), 1)

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
