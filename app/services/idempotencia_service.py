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
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client

logger = logging.getLogger("idempotencia")

# Cuantas veces se reintenta un mensaje que quedo a medias antes de darlo por
# perdido. Sin tope, un mensaje que tumbe el proceso se reintenta en cada
# arranque y el agente no vuelve a procesar nada.
MAX_INTENTOS = 3

# Un pendiente mas nuevo que esto puede estar procesandose todavia: en la cola
# de este proceso detras de una rafaga de fotos, o en el proceso viejo durante
# un despliegue, que sigue vivo unos segundos mientras arranca el nuevo. Tomarlo
# ahi lo procesaria dos veces. Ningun mensaje tarda tanto; una rafaga de 30
# fotos se despacha en unos cuatro minutos.
ANTIGUEDAD_PARA_RECUPERAR = timedelta(minutes=10)


def reclamar(wamid: str, mensaje: dict | None = None) -> bool:
    """Marca un mensaje como en proceso. Devuelve False si ya estaba.

    Guarda tambien el mensaje crudo: si el proceso se reinicia con la cola
    llena —y con despliegue continuo un reinicio es cada actualizacion— esos
    mensajes estaban solo en memoria y se perdian, ademas con su wamid ya
    reclamado. Desde la base se recuperan al arrancar y cada pocos minutos.

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


def pendientes(
    limite: int = 50, antiguedad: timedelta = ANTIGUEDAD_PARA_RECUPERAR
) -> list[dict]:
    """Mensajes reclamados que nunca llegaron a cerrarse, y que ya nadie esta
    procesando.

    Son los que estaban en la cola cuando el proceso murio, y los que fallaron
    por algo pasajero: un corte con Supabase, el modelo saturado. Se descartan
    los que ya fallaron varias veces: si un mensaje tumba el proceso,
    reintentarlo sin fin deja al agente en un bucle sin procesar nada mas.
    """
    corte = (datetime.now(timezone.utc) - antiguedad).isoformat()
    try:
        return (
            get_client()
            .table("mensajes_procesados")
            .select("wamid, payload, intentos")
            .is_("procesado_en", "null")
            .not_.is_("payload", "null")
            .lt("intentos", MAX_INTENTOS)
            .lt("recibido_en", corte)
            .order("recibido_en")
            .limit(limite)
            .execute()
            .data
        )
    except Exception:
        logger.exception("No se pudieron consultar los mensajes pendientes")
        return []


def tomar_para_reintento(wamid: str, intentos: int) -> bool:
    """Cuenta el intento y se queda con el mensaje, si nadie lo tomo antes.

    Es una comparacion-y-cambio: solo sube el contador si sigue en el valor
    que se leyo. Si durante un despliegue los dos procesos intentan recuperar
    el mismo mensaje, Postgres serializa los dos UPDATE y el segundo ya no
    encuentra la fila con ese valor: no le devuelve nada y no lo procesa.

    Ante un fallo de base devuelve False: el mensaje sigue pendiente y se
    intenta en la proxima vuelta, que es mejor que procesarlo dos veces.
    """
    try:
        resultado = (
            get_client()
            .table("mensajes_procesados")
            .update({"intentos": intentos + 1})
            .eq("wamid", wamid)
            .eq("intentos", intentos)
            .is_("procesado_en", "null")
            .execute()
        )
    except Exception:
        logger.exception("No se pudo tomar el wamid %s para reintentarlo", wamid)
        return False

    if not resultado.data:
        return False
    if intentos + 1 >= MAX_INTENTOS:
        logger.warning(
            "Ultimo intento para el mensaje %s: si falla otra vez queda sin procesar "
            "y hay que revisarlo a mano (procesado_en vacio en mensajes_procesados)",
            wamid,
        )
    return True
