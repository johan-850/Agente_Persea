"""Cola de procesamiento en segundo plano para los mensajes de WhatsApp.

Procesar un mensaje cuesta segundos: extraccion con Claude, y si trae foto
tambien descarga del media, vision y subida a Storage. Meta no espera tanto por
la confirmacion del webhook, asi que si se procesa antes de responder 200 el
evento se reenvia y se duplica todo.

Aqui el webhook solo encola y responde. Un unico hilo consume la cola, lo que
ademas conserva el orden de llegada: si una monitora manda el reporte y despues
las fotos, el monitoreo existe cuando llegan las fotos y se pueden asociar.
"""

import logging
import queue
import threading
from typing import Callable

logger = logging.getLogger("cola_mensajes")

_cola: "queue.Queue[tuple[Callable[[dict], None], dict]]" = queue.Queue()
_hilo: threading.Thread | None = None
_candado = threading.Lock()


def _bucle() -> None:
    while True:
        manejador, mensaje = _cola.get()
        try:
            manejador(mensaje)
        except Exception:
            # Un fallo no puede matar al hilo: se perderian todos los mensajes
            # siguientes sin que nadie se entere.
            logger.exception("Fallo procesando el mensaje %s", mensaje.get("id"))
        finally:
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
    _cola.put((manejador, mensaje))
    return _cola.qsize()


def pendientes() -> int:
    return _cola.qsize()
