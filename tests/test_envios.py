"""Saber si la alerta llego, no solo si la mandamos.

Antes, si fallaban la plantilla y el texto libre, quedaba una linea de log y
nada mas: nadie revisa los logs de un servidor para enterarse de que no le
avisaron de un foco de Heilipus. Y si la tabla de administradores estaba
vacia, el bucle no hacia nada y la alerta no existia para nadie.

Meta acepta el mensaje y devuelve un identificador; despues manda por el
webhook como le fue. Eso ya nos llegaba y se descartaba.

Usa la base real (crea y borra sus propias filas) pero no manda WhatsApp: el
envio esta interceptado. Correr:  python tests/test_envios.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db.supabase_client import get_client  # noqa: E402
from app.services import envios_service, meta_whatsapp_service  # noqa: E402

TIPO = "prueba_envios"
ADMIN = "+570000000123"
CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def limpiar():
    get_client().table("envios").delete().eq("tipo", TIPO).execute()


def filas():
    return (
        get_client().table("envios").select("*").eq("tipo", TIPO)
        .order("id").execute().data
    )


def main() -> int:
    limpiar()
    cli = get_client()

    # --- Se finge la lista de administradores y el envio a Meta ---
    meta_whatsapp_service._administradores = lambda: [ADMIN]

    print("LA PLANTILLA SALE BIEN")
    meta_whatsapp_service.enviar_plantilla = lambda n, nom, p: "wamid.PRUEBA_OK"
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="respaldo", tipo=TIPO, referencia="monitoreo:1"
    )
    f = filas()
    revisar("queda registrado un envio", len(f), 1)
    revisar("con el id que devolvio Meta", f[0]["wamid"], "wamid.PRUEBA_OK")
    revisar("en estado aceptado", f[0]["estado"], "aceptado")
    revisar("y con la referencia del lote", f[0]["referencia"], "monitoreo:1")

    print("\nLLEGAN LOS ACUSES DE META POR EL WEBHOOK")
    envios_service.actualizar_estado("wamid.PRUEBA_OK", "sent")
    revisar("sent -> enviado", filas()[0]["estado"], "enviado")
    envios_service.actualizar_estado("wamid.PRUEBA_OK", "read")
    revisar("read -> leido", filas()[0]["estado"], "leido")
    # Los acuses pueden llegar desordenados: no se retrocede.
    envios_service.actualizar_estado("wamid.PRUEBA_OK", "delivered")
    revisar("un acuse atrasado no retrocede el estado", filas()[0]["estado"], "leido")

    print("\nLA PLANTILLA FALLA Y SALVA EL TEXTO LIBRE")
    limpiar()

    def plantilla_rota(n, nom, p):
        raise RuntimeError("plantilla sin aprobar")

    meta_whatsapp_service.enviar_plantilla = plantilla_rota
    meta_whatsapp_service.enviar_mensaje = lambda n, t: "wamid.PRUEBA_LIBRE"
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="respaldo", tipo=TIPO
    )
    f = filas()
    revisar("se registra el envio por texto libre", f[0]["wamid"], "wamid.PRUEBA_LIBRE")
    revisar("sin plantilla asociada", f[0]["plantilla"], None)
    revisar("y queda dicho por que", "plantilla sin aprobar" in (f[0]["detalle"] or ""), True)

    print("\nFALLAN LOS DOS CAMINOS")
    limpiar()

    def libre_roto(n, t):
        raise RuntimeError("fuera de la ventana de 24h")

    meta_whatsapp_service.enviar_mensaje = libre_roto
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="respaldo", tipo=TIPO
    )
    f = filas()
    revisar("queda constancia del fallo", f[0]["estado"], "fallido")
    revisar("con los dos errores", "ventana de 24h" in (f[0]["detalle"] or ""), True)

    print("\nNO HAY ADMINISTRADORES ACTIVOS")
    limpiar()
    meta_whatsapp_service._administradores = lambda: []
    meta_whatsapp_service.enviar_plantilla_a_administradores(
        "plantilla_x", ["a"], respaldo="respaldo", tipo=TIPO
    )
    f = filas()
    revisar("no pasa en silencio", len(f), 1)
    revisar("se marca como fallido", f[0]["estado"], "fallido")
    revisar("diciendo que no hay a quien avisar",
            "administradores activos" in (f[0]["detalle"] or ""), True)

    print("\nUN ACUSE DE UN MENSAJE QUE NO MANDAMOS NOSOTROS")
    antes = len(filas())
    envios_service.actualizar_estado("wamid.DE_OTRO", "delivered")
    revisar("se ignora sin romper nada", len(filas()), antes)

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
