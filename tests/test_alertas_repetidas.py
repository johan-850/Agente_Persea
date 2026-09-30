"""La misma alerta no se manda dos veces en el dia.

La monitora avisa un hallazgo cuando lo encuentra y lo vuelve a contar en el
reporte de cierre. Cada mensaje disparaba su alerta: el 29 de septiembre, en
la simulacion de ocho monitoras, llegaron cuatro alertas por dos hallazgos.
Una alerta que se repite enseña a no leerlas, y entonces tampoco se lee la
que importa.

Lo que se protege:
- Que el mismo hallazgo, en el mismo lote y el mismo dia, avise una vez,
  aunque la monitora lo escriba distinto.
- Que un hallazgo nuevo en ese lote avise, igual que el mismo en otro lote o
  al dia siguiente.
- Que un accidente avise siempre, y que si el primer aviso fallo, el segundo
  salga.

Usa la base real (crea y borra sus propias filas) pero no manda WhatsApp ni
llama al modelo. Correr:  python tests/test_alertas_repetidas.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app import horario  # noqa: E402
from app.db.supabase_client import get_client  # noqa: E402
from app.services import meta_whatsapp_service, monitoreo_service  # noqa: E402
from app.services.alertas_monitoreo_service import clave_de_alerta  # noqa: E402

# Una finca que no existe, para no cruzarse con los reportes de verdad ni con
# los de la simulacion, que tambien hablan del lote 7.
FINCA = "prueba repetidas"
REMITENTE = "whatsapp:+570000000666"
ADMIN = "+570000000665"
CASOS = []

MEDIODIA = datetime(2026, 9, 29, 11, 0, tzinfo=horario.ZONA)
CIERRE = datetime(2026, 9, 29, 16, 5, tzinfo=horario.ZONA)
OTRO_DIA = datetime(2026, 9, 30, 10, 0, tzinfo=horario.ZONA)

# De dia: de noche las alertas se aplazan en vez de salir.
horario.ahora = lambda: MEDIODIA


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def limpiar(cli):
    ids = [m["id"] for m in cli.table("monitoreos").select("id").eq("finca", FINCA).execute().data]
    if ids:
        cli.table("envios").delete().in_("referencia", [f"monitoreo:{i}" for i in ids]).execute()
    cli.table("monitoreos").delete().eq("finca", FINCA).execute()
    cli.table("envios").delete().eq("destinatario", ADMIN).execute()


alertas = []


def reporte(texto, plagas, lote="1", momento=MEDIODIA):
    """Procesa un reporte como si llegara por WhatsApp. Devuelve cuantas alertas salieron."""
    monitoreo_service.extraer_reportes_monitoreo = lambda t: [
        {"finca": FINCA, "lote": lote, "plagas_observadas": list(plagas)}
    ]
    antes = len(alertas)
    monitoreo_service.procesar_mensaje_monitoreo(texto, REMITENTE, enviado_en=momento, responder=False)
    return len(alertas) - antes


def falla(*_):
    raise RuntimeError("Meta caido")


print("QUE HALLAZGOS SON EL MISMO")


def mismo(a, b):
    return clave_de_alerta(a) is not None and clave_de_alerta(a) == clave_de_alerta(b)


revisar("stenoma dicho de dos formas",
        mismo("Stenoma catenifer - 3 ramas afectadas", "stenoma en rama, foco marcado"), True)
revisar("heilipus por su nombre y por su nombre comun",
        mismo("Heilipus elegans - 2 larvas", "barrenador de tallo en el lote"), True)
revisar("un foco ACTIVO escrito de dos formas",
        mismo("mosca blanca - foco ACTIVO", "Focos de Mosca blanca ACTIVO"), True)
revisar("focos ACTIVOS de plagas distintas no",
        mismo("mosca blanca - foco ACTIVO", "acaro - foco ACTIVO"), False)
revisar("una cuarentenaria manda sobre el ACTIVO que la acompaña",
        clave_de_alerta("Stenoma catenifer - foco ACTIVO"), "Stenoma catenifer")
revisar("lo que no alerta no tiene clave", clave_de_alerta("acaro - severidad 3"), None)


def main() -> int:
    cli = get_client()
    limpiar(cli)

    meta_whatsapp_service._administradores = lambda: [ADMIN]
    meta_whatsapp_service.enviar_plantilla = (
        lambda numero, nombre, params: alertas.append(params) or f"wamid.REPETIDA.{len(alertas)}"
    )
    meta_whatsapp_service.enviar_mensaje = lambda numero, texto: "wamid.REPETIDA.LIBRE"

    print("\nEL MISMO HALLAZGO EN DOS MENSAJES")
    revisar("el aviso de mediodia alerta",
            reporte("PRUEBA rep 1", ["Stenoma catenifer - 3 ramas afectadas, 1 larva viva"]), 1)
    revisar("el cierre que lo repite con otras palabras, no",
            reporte("PRUEBA rep 2", ["stenoma en rama, foco marcado en la línea 4", "acaro - severidad 1"],
                    momento=CIERRE), 0)
    guardadas = (
        cli.table("monitoreos").select("id").eq("finca", FINCA).eq("lote", "1").eq("es_alerta", True)
        .execute().data
    )
    revisar("pero el reporte queda guardado como alerta, para el resumen", len(guardadas), 2)

    print("\nLO NUEVO SI AVISA")
    revisar("una cuarentenaria nueva en el mismo lote",
            reporte("PRUEBA rep 3", ["stenoma en rama", "Heilipus elegans - 2 larvas en tallo"],
                    momento=CIERRE), 1)
    revisar("el mismo hallazgo en otro lote", reporte("PRUEBA rep 4", ["stenoma en rama"], lote="2"), 1)
    revisar("el mismo lote al dia siguiente",
            reporte("PRUEBA rep 5", ["stenoma en rama"], momento=OTRO_DIA), 1)

    print("\nFOCOS ACTIVOS")
    revisar("un foco ACTIVO avisa", reporte("PRUEBA rep 6", ["mosca blanca - foco ACTIVO"], lote="3"), 1)
    revisar("el cierre que lo repite no",
            reporte("PRUEBA rep 7", ["Focos de Mosca blanca ACTIVO", "trips"], lote="3", momento=CIERRE), 0)
    revisar("un foco ACTIVO de otra plaga si",
            reporte("PRUEBA rep 8", ["acaro - foco ACTIVO"], lote="3", momento=CIERRE), 1)

    print("\nLO QUE AVISA SIEMPRE")
    revisar("un accidente", reporte("PRUEBA rep 9", ["accidente, un trabajador herido"], lote="4"), 1)
    revisar("y el mismo accidente contado en el cierre",
            reporte("PRUEBA rep 10", ["el trabajador herido fue llevado al puesto de salud"], lote="4",
                    momento=CIERRE), 1)
    revisar("un reporte sin lote", reporte("PRUEBA rep 11", ["stenoma en rama"], lote=None), 1)
    revisar("y otro sin lote: no hay como saber si es el mismo",
            reporte("PRUEBA rep 12", ["stenoma en rama"], lote=None, momento=CIERRE), 1)

    print("\nSI EL PRIMER AVISO FALLO, EL SEGUNDO SALE")
    enviar_plantilla = meta_whatsapp_service.enviar_plantilla
    enviar_mensaje = meta_whatsapp_service.enviar_mensaje
    meta_whatsapp_service.enviar_plantilla = falla
    meta_whatsapp_service.enviar_mensaje = falla
    revisar("con Meta caido no sale nada",
            reporte("PRUEBA rep 13", ["cochinilla en pedúnculos"], lote="5"), 0)
    meta_whatsapp_service.enviar_plantilla = enviar_plantilla
    meta_whatsapp_service.enviar_mensaje = enviar_mensaje
    revisar("el cierre avisa, porque nadie se entero",
            reporte("PRUEBA rep 14", ["cochinilla en pedúnculos de 2 frutos"], lote="5", momento=CIERRE), 1)

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
