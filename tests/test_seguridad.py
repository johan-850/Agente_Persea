"""El servidor se expone por un tunel publico: nadie de fuera debe poder
inyectar un reporte ni leer el historial.

Sin esto, un POST con un reporte inventado se extrae, se guarda y dispara una
alerta real de WhatsApp a los administradores.

Levanta la app de verdad con TestClient, asi que comprueba el cableado y no
solo las funciones sueltas. No manda mensajes ni escribe en la base: los casos
que pasan la autenticacion se cortan antes de hacer nada.

Correr:  python tests/test_seguridad.py
"""

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SECRETO = "secreto-de-prueba"
CLAVE = "clave-de-prueba"
os.environ["META_APP_SECRET"] = SECRETO
os.environ["API_TOKEN"] = CLAVE

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

cliente = TestClient(app)

# Un evento de estado de entrega: pasa por el webhook sin crear nada.
EVENTO = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "1390763609075768",
        "changes": [{
            "field": "messages",
            "value": {"messaging_product": "whatsapp", "statuses": [{"status": "delivered"}]},
        }],
    }],
}
CUERPO = json.dumps(EVENTO).encode()


def firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def main() -> int:
    resultados = []

    def comprobar(descripcion, obtenido, esperado):
        ok = obtenido == esperado
        resultados.append(ok)
        marca = "ok  " if ok else "FALLA"
        print(f"  {marca}: {descripcion} -> {obtenido} (esperado {esperado})")

    print("WEBHOOK DE META: solo eventos firmados por Meta")
    r = cliente.post("/meta/webhook", content=CUERPO,
                     headers={"X-Hub-Signature-256": firmar(CUERPO, SECRETO)})
    comprobar("firma correcta se acepta", r.status_code, 200)

    r = cliente.post("/meta/webhook", content=CUERPO,
                     headers={"X-Hub-Signature-256": firmar(CUERPO, "otro-secreto")})
    comprobar("firma de otro secreto se rechaza", r.status_code, 403)

    r = cliente.post("/meta/webhook", content=CUERPO)
    comprobar("sin firma se rechaza", r.status_code, 403)

    # El cuerpo alterado despues de firmar tiene que fallar: es el caso que
    # protege de que alguien reenvie un evento real con el texto cambiado.
    alterado = json.dumps({**EVENTO, "entry": []}).encode()
    r = cliente.post("/meta/webhook", content=alterado,
                     headers={"X-Hub-Signature-256": firmar(CUERPO, SECRETO)})
    comprobar("cuerpo alterado con firma valida se rechaza", r.status_code, 403)

    print("\nVERIFICACION DEL WEBHOOK (la que hace Meta al configurarlo)")
    r = cliente.get("/meta/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": os.environ.get("META_VERIFY_TOKEN", ""),
        "hub.challenge": "12345",
    })
    comprobar("token correcto devuelve el desafio", r.text, "12345")
    r = cliente.get("/meta/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "malo", "hub.challenge": "12345",
    })
    comprobar("token incorrecto se rechaza", r.status_code, 403)

    print("\nAPI REST: cerrada sin la clave")
    for ruta in ("/monitoreos", "/alertas-monitoreo", "/fotos", "/envios",
                 "/envios/sin-entregar"):
        comprobar(f"GET {ruta} sin clave", cliente.get(ruta).status_code, 401)

    comprobar("POST /monitoreos sin clave (inyectaba reportes)",
              cliente.post("/monitoreos", json={"texto": "x", "remitente": "y"}).status_code, 401)
    comprobar("POST /tareas/resumen-diario sin clave (disparaba el resumen)",
              cliente.post("/tareas/resumen-diario").status_code, 401)
    comprobar("clave incorrecta",
              cliente.get("/monitoreos", headers={"X-API-Key": "no-es"}).status_code, 401)

    r = cliente.get("/monitoreos", headers={"X-API-Key": CLAVE})
    resultados.append(r.status_code not in (401, 403, 503))
    print(f"  {'ok  ' if resultados[-1] else 'FALLA'}: clave correcta pasa la autenticacion -> {r.status_code}")

    print("\nLO QUE SIGUE ABIERTO A PROPOSITO")
    comprobar("GET / (latido del tunel)", cliente.get("/").status_code, 200)

    print("\nRUTAS ELIMINADAS")
    comprobar("POST /whatsapp/webhook (webhook de Twilio) ya no existe",
              cliente.post("/whatsapp/webhook", data={"From": "x", "Body": "y"}).status_code, 404)
    # El flujo de labores se quito: el proyecto abarca solo monitoreo.
    for ruta in ("/reportes", "/alertas", "/resumen-dia"):
        comprobar(f"GET {ruta} (flujo de labores) ya no existe",
                  cliente.get(ruta).status_code, 404)

    fallos = resultados.count(False)
    print()
    if fallos:
        print(f"{fallos} de {len(resultados)} casos fallaron")
        return 1
    print(f"{len(resultados)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
