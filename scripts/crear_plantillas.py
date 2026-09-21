"""Crea en Meta las plantillas que usa el agente para avisar a los administradores.

Hacen falta porque WhatsApp solo entrega texto libre dentro de las 24 horas
siguientes al ultimo mensaje del destinatario. Una alerta de madrugada o de fin
de semana cae fuera de esa ventana y solo llega si va como plantilla aprobada.

Es idempotente: si una plantilla ya existe, la reporta y sigue.

La WABA se pasa en META_WABA_ID y TIENE que ser la que contiene el numero del
agente. Una cuenta de Meta suele tener tambien la WABA de prueba que crea el
propio Meta, con su numero +1 555..., y las plantillas creadas ahi se quedan en
PENDING sin que nada las use: el envio resuelve la plantilla contra la WABA
dueña del numero, no contra la que uno mire en el panel. Por eso el script
verifica primero que META_PHONE_NUMBER_ID este en esa WABA y se niega a crear
nada si no lo esta.

Si no sabes el id: aparece en el log del agente al llegar el primer mensaje
("Eventos recibidos de la WABA ..."), porque Meta lo manda en cada evento.

Reglas de Meta que condicionan el texto de abajo:
  - una variable no puede ir al principio ni al final del cuerpo
  - los parametros no pueden traer saltos de linea, tabs ni mas de 4 espacios
    seguidos (de eso se encarga meta_whatsapp_service.limpiar_parametro)
  - la categoria UTILITY es la correcta para avisos operativos y no depende del
    consentimiento de marketing; MARKETING ademas se cobra aparte

Correr:  python scripts/crear_plantillas.py
         python scripts/crear_plantillas.py --estado   (solo consultar)
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services.meta_whatsapp_service import (  # noqa: E402
    IDIOMA_PLANTILLA,
    PLANTILLA_ALERTA,
    PLANTILLA_RESUMEN,
)

WABA_ID = os.environ.get("META_WABA_ID")
PHONE_ID = os.environ.get("META_PHONE_NUMBER_ID")
API = "https://graph.facebook.com/v21.0"


# El orden de las variables tiene que coincidir con la lista de parametros que
# arma cada emisor:
#   {{1}} prioridad   {{2}} finca   {{3}} lote
#   {{4}} hallazgos   {{5}} motivo  {{6}} quien reporto
# monitoreo_service._notificar_alerta y fotos_service._notificar_dano_en_foto
PLANTILLAS = [
    {
        "name": PLANTILLA_ALERTA,
        "language": IDIOMA_PLANTILLA,
        "category": "UTILITY",
        "components": [
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": "Alerta de monitoreo de plagas",
            },
            {
                "type": "BODY",
                "text": (
                    "Se registro una alerta de prioridad {{1}} en la finca {{2}}, "
                    "lote {{3}}.\n\n"
                    "Hallazgos: {{4}}\n\n"
                    "Motivo: {{5}}\n\n"
                    "Reportado por {{6}}. Revise el lote y confirme en campo."
                ),
                "example": {
                    "body_text": [[
                        "alta",
                        "La Rivera",
                        "18",
                        "stenoma catenifer en rama, acaro bordo a monte, chancro",
                        "plaga cuarentenaria",
                        "whatsapp:+573159793011",
                    ]]
                },
            },
            {"type": "FOOTER", "text": "Agente de monitoreo - Agricola Persea"},
        ],
    },
    # {{1}} fecha   {{2}} reportes del dia   {{3}} cuantos alertaron   {{4}} detalle
    # resumen_service.enviar_resumen_diario
    {
        "name": PLANTILLA_RESUMEN,
        "language": IDIOMA_PLANTILLA,
        "category": "UTILITY",
        "components": [
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": "Resumen diario de monitoreo",
            },
            {
                "type": "BODY",
                "text": (
                    "Cierre de jornada del {{1}}. Se registraron {{2}} reportes de "
                    "lote, de los cuales {{3}} generaron alerta.\n\n"
                    "Detalle: {{4}}\n\n"
                    "Consulte el historial completo en el sistema."
                ),
                "example": {
                    "body_text": [[
                        "2026-09-21",
                        "4",
                        "2",
                        "Rivera lote 6 (finalizado): stenoma en rama, acaro; buena vista "
                        "lote 5 (finalizado): alta poblacion de acaro, bruggmaniella",
                    ]]
                },
            },
            {"type": "FOOTER", "text": "Agente de monitoreo - Agricola Persea"},
        ],
    },
]


def _peticion(url: str, metodo: str = "GET", cuerpo: dict | None = None) -> dict:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        url,
        data=datos,
        method=metodo,
        headers={
            "Authorization": f"Bearer {os.environ['META_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error_http": json.loads(e.read().decode("utf-8", "replace") or "{}")}


def listar() -> dict:
    respuesta = _peticion(
        f"{API}/{WABA_ID}/message_templates"
        "?fields=name,status,category,language,rejected_reason&limit=100"
    )
    return {t["name"]: t for t in respuesta.get("data", [])}


def waba_contiene_el_numero() -> bool:
    """Que la WABA sea la dueña del numero del agente.

    Sin esto las plantillas se pueden crear en la WABA de prueba de Meta y
    quedarse ahi sin que nada las use.
    """
    respuesta = get(f"{API}/{WABA_ID}/phone_numbers?fields=id,display_phone_number")
    numeros = respuesta.get("data", [])
    if "error_http" in respuesta:
        print(f"  No se pudieron listar los numeros: {respuesta['error_http'].get('error', {}).get('message')}")
        return False

    for n in numeros:
        if n["id"] == PHONE_ID:
            print(f"  WABA {WABA_ID} contiene {n.get('display_phone_number')} (ok)\n")
            return True

    print(f"  La WABA {WABA_ID} NO contiene el numero {PHONE_ID}.")
    print(f"  Numeros que tiene: {[n.get('display_phone_number') for n in numeros]}")
    print("  Las plantillas creadas aqui no las usaria nadie. Revisa META_WABA_ID.")
    return False


def main() -> int:
    if not WABA_ID:
        print("Falta META_WABA_ID en el .env. Aparece en el log del agente al")
        print("llegar el primer mensaje: 'Eventos recibidos de la WABA ...'")
        return 1

    if "--estado" not in sys.argv and not waba_contiene_el_numero():
        return 1

    existentes = listar()

    if "--estado" not in sys.argv:
        for plantilla in PLANTILLAS:
            nombre = plantilla["name"]
            if nombre in existentes:
                print(f"  ya existe, no se toca: {nombre}")
                continue
            resultado = _peticion(
                f"{API}/{WABA_ID}/message_templates", "POST", plantilla
            )
            if "error_http" in resultado:
                error = resultado["error_http"].get("error", {})
                print(f"  FALLO {nombre}: {error.get('message')}")
                if error.get("error_user_msg"):
                    print(f"         {error['error_user_msg']}")
            else:
                print(f"  creada {nombre}: id={resultado.get('id')} "
                      f"estado={resultado.get('status')} categoria={resultado.get('category')}")
        existentes = listar()

    print("\nEstado de las plantillas del agente:")
    for plantilla in PLANTILLAS:
        actual = existentes.get(plantilla["name"])
        if not actual:
            print(f"  {plantilla['name']}: NO EXISTE")
            continue
        linea = (f"  {actual['name']}: {actual['status']} / {actual['category']} "
                 f"/ {actual['language']}")
        if actual.get("rejected_reason") and actual["rejected_reason"] != "NONE":
            linea += f"  rechazo={actual['rejected_reason']}"
        print(linea)

    otras = [n for n in existentes if n not in {p["name"] for p in PLANTILLAS}]
    if otras:
        print(f"\nOtras plantillas en la WABA (no las usa el agente): {', '.join(sorted(otras))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
