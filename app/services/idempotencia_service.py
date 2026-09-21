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

from app.db.supabase_client import get_client

logger = logging.getLogger("idempotencia")


def reclamar(wamid: str) -> bool:
    """Marca un mensaje como procesado. Devuelve False si ya lo estaba.

    Ante un fallo de base de datos devuelve True: preferimos arriesgar un
    duplicado a perder un reporte de campo.
    """
    try:
        resultado = (
            get_client()
            .table("mensajes_procesados")
            .upsert({"wamid": wamid}, on_conflict="wamid", ignore_duplicates=True)
            .execute()
        )
    except Exception:
        logger.exception("No se pudo registrar el wamid %s; se procesa igual", wamid)
        return True

    # Con ignore_duplicates PostgREST no devuelve fila cuando ya existia.
    return bool(resultado.data)
