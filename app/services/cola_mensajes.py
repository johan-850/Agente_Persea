"""Cola de procesamiento en segundo plano para los mensajes de WhatsApp.

Procesar un mensaje cuesta segundos: extraccion con Claude, y si trae foto
tambien descarga del media, vision y subida a Storage. Meta no espera tanto por
la confirmacion del webhook, asi que si se procesa antes de responder 200 el
evento se reenvia y se duplica todo.

Aqui el webhook solo encola y responde. Un unico hilo consume la cola, lo que
ademas conserva el orden de llegada: si una monitora manda el reporte y despues
las fotos, el monitoreo existe cuando llegan las fotos y se pueden asociar. Por
eso el agente corre en UNA sola instancia: con dos, cada una tendria su cola y
el orden se perderia.

Un mensaje que falla no se suelta ni se borra: queda pendiente en la base, con
el mensaje crudo, y la recuperacion lo vuelve a intentar. A Meta ya se le
respondio 200, asi que no lo va a reenviar; si no lo reintentamos nosotros, el
reporte se pierde.
"""

import logging
import queue
import threading
import time
from typing import Callable

from app.services.idempotencia_service import (
    marcar_procesado,
    pendientes,
    tomar_para_reintento,
)

logger = logging.getLogger("cola_mensajes")

_cola: "queue.Queue[tuple[Callable[[dict], None], dict]]" = queue.Queue()
_hilo: threading.Thread | None = None
_candado = threading.Lock()

# Los mensajes que este proceso tiene entre manos: en la cola o procesandose.
# La recuperacion los salta; si no, un mensaje que espera detras de una rafaga
# larga pareceria abandonado y se encolaria dos veces.
_en_curso: set[str] = set()
_cambio_en_curso = threading.Condition(_candado)


def _clave(mensaje: dict) -> str:
    return mensaje.get("id") or f"sin-id-{id(mensaje)}"


def _bucle() -> None:
    while True:
        manejador, mensaje = _cola.get()
        wamid = mensaje.get("id")
        try:
            manejador(mensaje)
        except Exception:
            # Un fallo no puede matar al hilo: se perderian todos los mensajes
            # siguientes sin que nadie se entere.
            #
            # El mensaje sigue pendiente en la base y se reintenta en la
            # proxima recuperacion. Va completo al log por si tambien fallan
            # los reintentos.
            logger.exception(
                "Fallo procesando el mensaje %s; queda pendiente para reintentarlo. "
                "Contenido: %s",
                wamid,
                mensaje,
            )
        else:
            # Cerrarlo evita que se reintente.
            if wamid:
                marcar_procesado(wamid)
        finally:
            with _cambio_en_curso:
                _en_curso.discard(_clave(mensaje))
                _cambio_en_curso.notify_all()
            _cola.task_done()


def iniciar() -> None:
    global _hilo
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return
        _hilo = threading.Thread(target=_bucle, name="cola-mensajes", daemon=True)
        _hilo.start()


def encolar(manejador: Callable[[dict], None], mensaje: dict) -> int:
    """Agrega un mensaje a la cola y devuelve cuantos quedan pendientes."""
    iniciar()
    with _cambio_en_curso:
        _en_curso.add(_clave(mensaje))
    _cola.put((manejador, mensaje))
    return _cola.qsize()


def en_cola() -> int:
    return _cola.qsize()


def esperar_vaciado(segundos: float) -> bool:
    """Espera a que termine lo que hay en la cola. True si alcanzo.

    Se usa al apagar. En cada despliegue el proceso viejo recibe la orden de
    terminar con mensajes todavia en la cola; dejarlos terminar es mejor que
    cortarlos a medias y esperar a que la recuperacion los retome.
    """
    limite = time.monotonic() + segundos
    with _cambio_en_curso:
        while _en_curso:
            restante = limite - time.monotonic()
            if restante <= 0:
                return False
            _cambio_en_curso.wait(restante)
    return True


def recuperar_pendientes(manejador: Callable[[dict], None]) -> int:
    """Vuelve a encolar lo que quedo a medias o fallo.

    Corre al arrancar y cada pocos minutos. Sin esto, los mensajes que estaban
    en la cola cuando murio el proceso se perdian del todo: solo existian en
    memoria, y su wamid ya estaba reclamado, asi que ni un reenvio de Meta los
    habria recuperado.

    Solo toma pendientes con cierta antiguedad (ver ANTIGUEDAD_PARA_RECUPERAR)
    y solo si gana la toma en la base, para no procesar dos veces lo que otro
    proceso todavia tiene entre manos.
    """
    filas = pendientes()
    recuperados = 0

    for fila in filas:
        wamid = fila["wamid"]
        with _cambio_en_curso:
            if wamid in _en_curso:
                continue
        if not tomar_para_reintento(wamid, fila.get("intentos") or 0):
            continue
        encolar(manejador, fila["payload"])
        recuperados += 1

    if recuperados:
        logger.warning("Se recuperaron %d mensaje(s) que habian quedado sin procesar", recuperados)
    return recuperados
