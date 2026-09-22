"""Descarta los reenvios de Meta.

Meta entrega cada evento "al menos una vez": si el webhook tarda en confirmar,
o si hubo un corte y se reconecta, reenvia el mismo mensaje. Sin este filtro un
solo reporte se guarda varias veces, cada copia dispara su propia alerta y cada
foto se vuelve a pasar por el modelo de vision (que no es determinista, asi que
la misma imagen termina con candidatas distintas en cada copia).

El wamid es el identificador que Meta le da a cada mensaje y se repite igual en
todos los reenvios, asi que sirve de llave.
"""

import logging
from datetime import datetime, timezone

from app.db.supabase_client import get_client

logger = logging.getLogger("idempotencia")

# Cuantas veces se reintenta un mensaje que quedo a medias antes de darlo por
# perdido. Sin tope, un mensaje que tumbe el proceso se reintenta en cada
# arranque y el agente no vuelve a procesar nada.
MAX_INTENTOS = 3


def reclamar(wamid: str, mensaje: dict | None = None) -> bool:
    """Marca un mensaje como en proceso. Devuelve False si ya estaba.

    Guarda tambien el mensaje crudo: si el proceso se reinicia con la cola
    llena —y con despliegue continuo un reinicio es cada actualizacion— esos
    mensajes estaban solo en memoria y se perdian, ademas con su wamid ya
    reclamado. Desde la base se pueden recuperar al arrancar.

    Ante un fallo de base de datos devuelve True: preferimos arriesgar un
    duplicado a perder un reporte de campo.
    """
    fila = {"wamid": wamid}
    if mensaje is not None:
        fila["payload"] = mensaje

    try:
        resultado = (
            get_client()
            .table("mensajes_procesados")
            .upsert(fila, on_conflict="wamid", ignore_duplicates=True)
            .execute()
        )
    except Exception:
        logger.exception("No se pudo registrar el wamid %s; se procesa igual", wamid)
        return True

    # Con ignore_duplicates PostgREST no devuelve fila cuando ya existia.
    return bool(resultado.data)


def marcar_procesado(wamid: str) -> None:
    """Cierra el mensaje para que no se reintente al arrancar."""
    try:
        (
            get_client()
            .table("mensajes_procesados")
            .update({"procesado_en": datetime.now(timezone.utc).isoformat()})
            .eq("wamid", wamid)
            .execute()
        )
    except Exception:
        logger.exception("No se pudo cerrar el wamid %s", wamid)


def pendientes(limite: int = 50) -> list[dict]:
    """Mensajes reclamados que nunca llegaron a cerrarse.

    Son los que estaban en la cola cuando el proceso murio. Se descartan los
    que ya fallaron varias veces: si un mensaje tumba el proceso, reintentarlo
    en cada arranque deja al agente en un bucle sin procesar nada mas.
    """
    try:
        return (
            get_client()
            .table("mensajes_procesados")
            .select("wamid, payload, intentos")
            .is_("procesado_en", "null")
            .not_.is_("payload", "null")
            .lt("intentos", MAX_INTENTOS)
            .order("recibido_en")
            .limit(limite)
            .execute()
            .data
        )
    except Exception:
        logger.exception("No se pudieron consultar los mensajes pendientes")
        return []


def contar_intento(wamid: str, intentos: int) -> None:
    try:
        (
            get_client()
            .table("mensajes_procesados")
            .update({"intentos": intentos + 1})
            .eq("wamid", wamid)
            .execute()
        )
    except Exception:
        logger.exception("No se pudo contar el intento del wamid %s", wamid)


def liberar(wamid: str) -> None:
    """Suelta el wamid para que el mensaje se pueda volver a procesar.

    Se reclama antes de procesar, no despues, porque si no los reenvios que
    llegan mientras el mensaje aun se procesa lo duplicarian. El precio es que
    un fallo dejaria el mensaje reclamado y perdido para siempre: ya paso una
    vez, con un reporte de campo que murio en un corte de conexion con
    Supabase.
    """
    try:
        get_client().table("mensajes_procesados").delete().eq("wamid", wamid).execute()
        logger.info("wamid %s liberado, se puede reprocesar", wamid)
    except Exception:
        logger.exception("No se pudo liberar el wamid %s", wamid)
