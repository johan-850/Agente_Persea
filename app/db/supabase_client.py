import logging
import os

import httpx
from supabase import Client, create_client

logger = logging.getLogger("supabase_client")

_client: Client | None = None

# Supabase cierra las conexiones HTTP/2 que quedan inactivas, pero el cliente
# las guarda en el pool y las reutiliza: la peticion muere con "Server
# disconnected" a mitad de la respuesta. Con una rafaga de 21 mensajes eso
# costo un reporte perdido y una foto sin archivar.
#
# HTTP/1.1 no multiplexa, asi que httpcore detecta la conexion caida y abre
# otra en vez de fallar. Los reintentos cubren ademas el fallo al conectar,
# frecuente cuando el proyecto gratuito esta despertando.
REINTENTOS_CONEXION = 3


def _ajustar_transporte(sesion, nombre: str) -> None:
    """Cambia el transporte de una sesion httpx ya creada.

    supabase-py no expone el cliente httpx en ClientOptions, asi que hay que
    tocarlo por dentro. Si una version futura cambia la estructura, se registra
    y se sigue con el transporte por defecto: peor es no arrancar.
    """
    try:
        sesion._transport = httpx.HTTPTransport(http2=False, retries=REINTENTOS_CONEXION)
    except Exception:
        logger.warning(
            "No se pudo forzar HTTP/1.1 en la sesion de %s; "
            "pueden reaparecer los 'Server disconnected'",
            nombre,
            exc_info=True,
        )


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)

        for nombre, sesion in (
            ("postgrest", getattr(_client.postgrest, "session", None)),
            ("storage", getattr(_client.storage, "session", None)),
        ):
            if sesion is not None:
                _ajustar_transporte(sesion, nombre)

    return _client
