"""Los mensajes que quedan a medias no se pierden ni se procesan dos veces.

Con despliegue continuo el proceso se reinicia en cada actualizacion, y
durante unos segundos conviven el viejo y el nuevo. Tres cosas tienen que
aguantar eso:

- Un mensaje que falla queda pendiente. Antes se borraba su registro para que
  Meta lo reenviara, pero a Meta ya se le habia respondido 200 y no reenvia:
  el reporte se perdia.
- La recuperacion no toma lo que alguien todavia tiene entre manos: ni lo que
  espera en la cola de este proceso, ni lo que el proceso viejo sigue
  procesando durante el despliegue.
- Si dos procesos van por el mismo pendiente, solo uno se lo lleva.

La primera parte no toca la base. La segunda prueba la toma contra la base de
desarrollo, con filas propias que borra al terminar. Correr:
    python tests/test_recuperacion.py
"""

import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services import cola_mensajes as cola  # noqa: E402
from app.services import idempotencia_service as idem  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


# --------------------------------------------------------------------------
# La cola, sin base de datos.
# --------------------------------------------------------------------------
marcados: list[str] = []
cola.marcar_procesado = marcados.append
procesados: list[str] = []


def procesar(mensaje):
    procesados.append(mensaje["id"])


print("EN ORDEN, Y CERRANDO LO QUE TERMINA")
for i in range(5):
    cola.encolar(procesar, {"id": f"w{i}"})
revisar("la cola se vacia", cola.esperar_vaciado(5), True)
# Copias: revisar() guarda lo que recibe y compara al final, y estas listas
# siguen creciendo en los casos de abajo.
revisar("en el orden de llegada", list(procesados), [f"w{i}" for i in range(5)])
revisar("cada uno queda cerrado", list(marcados), [f"w{i}" for i in range(5)])

print("\nUN FALLO NO BORRA NI CIERRA")


def revienta(mensaje):
    raise RuntimeError("corte con Supabase")


cola.encolar(revienta, {"id": "w-falla"})
cola.esperar_vaciado(5)
revisar("el que fallo no se cierra: sigue pendiente para reintentarlo",
        "w-falla" in marcados, False)
revisar("y ya no existe la funcion que lo borraba", hasattr(idem, "liberar"), False)
cola.encolar(procesar, {"id": "w-despues"})
cola.esperar_vaciado(5)
revisar("el hilo sigue vivo despues del fallo", procesados[-1], "w-despues")

print("\nLA RECUPERACION NO TOMA LO QUE ESTA EN CURSO")
suelta = threading.Event()


def lento(mensaje):
    suelta.wait(5)
    procesados.append(mensaje["id"])


cola.encolar(lento, {"id": "w-lento"})
cola.encolar(procesar, {"id": "w-esperando"})
tomados: list[tuple[str, int]] = []
cola.pendientes = lambda: [
    {"wamid": "w-lento", "payload": {"id": "w-lento"}, "intentos": 0},
    {"wamid": "w-esperando", "payload": {"id": "w-esperando"}, "intentos": 0},
    {"wamid": "w-abandonado", "payload": {"id": "w-abandonado"}, "intentos": 1},
]
cola.tomar_para_reintento = lambda wamid, intentos: tomados.append((wamid, intentos)) or True
recuperados = cola.recuperar_pendientes(procesar)
revisar("salta el que se esta procesando y el que espera en la cola",
        [w for w, _ in tomados], ["w-abandonado"])
revisar("toma el abandonado con su contador", list(tomados), [("w-abandonado", 1)])
revisar("y cuenta solo ese", recuperados, 1)
suelta.set()
cola.esperar_vaciado(5)
revisar("ninguno se proceso dos veces",
        [procesados.count(w) for w in ("w-lento", "w-esperando", "w-abandonado")], [1, 1, 1])

print("\nSI OTRO PROCESO LO TOMO PRIMERO, SE DEJA")
cola.pendientes = lambda: [{"wamid": "w-ajeno", "payload": {"id": "w-ajeno"}, "intentos": 0}]
cola.tomar_para_reintento = lambda wamid, intentos: False
revisar("no lo encola", cola.recuperar_pendientes(procesar), 0)
cola.esperar_vaciado(5)
revisar("ni lo procesa", "w-ajeno" in procesados, False)

print("\nAL APAGAR SE ESPERA A LA COLA, CON TOPE")
frena = threading.Event()
cola.encolar(lambda m: frena.wait(5), {"id": "w-frenado"})
revisar("si no alcanza a vaciarse, lo dice", cola.esperar_vaciado(0.3), False)
frena.set()
revisar("y cuando termina, tambien", cola.esperar_vaciado(5), True)


# --------------------------------------------------------------------------
# La toma contra la base de verdad.
# --------------------------------------------------------------------------
print("\nCONTRA LA BASE: QUE SE CONSIDERA ABANDONADO")
if not os.environ.get("SUPABASE_URL"):
    print("  (sin SUPABASE_URL: se salta la parte de base)")
else:
    from app.db.supabase_client import get_client

    tabla = get_client().table("mensajes_procesados")
    prefijo = f"test-recuperacion-{uuid.uuid4().hex[:8]}"
    ahora = datetime.now(timezone.utc)
    hace = lambda minutos: (ahora - timedelta(minutes=minutos)).isoformat()  # noqa: E731

    filas = {
        "reciente": {"recibido_en": hace(1), "intentos": 0},
        "viejo": {"recibido_en": hace(20), "intentos": 0},
        "cerrado": {"recibido_en": hace(20), "intentos": 0, "procesado_en": hace(19)},
        "agotado": {"recibido_en": hace(20), "intentos": idem.MAX_INTENTOS},
        "sin_mensaje": {"recibido_en": hace(20), "intentos": 0, "payload": None},
        "disputado": {"recibido_en": hace(20), "intentos": 0},
    }
    try:
        for nombre, fila in filas.items():
            wamid = f"{prefijo}-{nombre}"
            # Sin "from": si algo lo procesara por error, sale sin hacer nada.
            tabla.insert({"wamid": wamid, "payload": {"id": wamid}, **fila}).execute()

        encontrados = {
            f["wamid"].removeprefix(prefijo + "-")
            for f in idem.pendientes(limite=1000)
            if f["wamid"].startswith(prefijo)
        }
        revisar("toma el pendiente viejo", "viejo" in encontrados, True)
        revisar("no toma el reciente: puede estar en curso en otro proceso",
                "reciente" in encontrados, False)
        revisar("no toma el ya procesado", "cerrado" in encontrados, False)
        revisar("no toma el que agoto los intentos", "agotado" in encontrados, False)
        revisar("no toma uno sin mensaje guardado", "sin_mensaje" in encontrados, False)

        print("\nCONTRA LA BASE: LA TOMA ES DE UNO SOLO")
        viejo = f"{prefijo}-viejo"
        revisar("el primero se lo lleva", idem.tomar_para_reintento(viejo, 0), True)
        revisar("el segundo con el mismo contador no", idem.tomar_para_reintento(viejo, 0), False)
        revisar("el contador subio", tabla.select("intentos").eq("wamid", viejo).execute().data[0]["intentos"], 1)
        revisar("con el contador nuevo si se puede", idem.tomar_para_reintento(viejo, 1), True)

        disputado = f"{prefijo}-disputado"
        ganadores = []
        salida = threading.Barrier(8)

        def competir():
            salida.wait()
            if idem.tomar_para_reintento(disputado, 0):
                ganadores.append(1)

        hilos = [threading.Thread(target=competir) for _ in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
        revisar("ocho procesos a la vez: se lo lleva exactamente uno", len(ganadores), 1)
    finally:
        tabla.delete().like("wamid", f"{prefijo}-%").execute()
        quedan = tabla.select("wamid").like("wamid", f"{prefijo}-%").execute().data
        revisar("no deja filas de prueba en la base", quedan, [])


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
