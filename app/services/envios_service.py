"""Registro de lo que el agente manda a los administradores.

El sistema existe para avisar, y hasta ahora no habia forma de saber si el
aviso llegaba: si fallaban la plantilla y el texto libre, quedaba una linea de
log y nada mas. Nadie revisa los logs de un servidor para enterarse de que no
le avisaron de un foco de Heilipus.

Meta devuelve un identificador al aceptar cada mensaje, y despues manda por el
webhook como le fue (sent, delivered, read, failed). Ese segundo dato ya nos
llegaba y se tiraba al log. Cruzandolo con lo que registramos al enviar, el
estado final dice si el administrador lo recibio de verdad, no solo si
nosotros lo pusimos en la cola de Meta.
"""

import logging

from app import horario
from app.db.supabase_client import get_client

logger = logging.getLogger("envios")

# Como llama Meta a cada estado, y como lo guardamos.
ESTADOS_META = {
    "sent": "enviado",
    "delivered": "entregado",
    "read": "leido",
    "failed": "fallido",
}

# Orden de avance. Los estados llegan por webhook y pueden cruzarse: no se
# retrocede de "leido" a "enviado" porque llego tarde el evento anterior.
_ORDEN = {"aceptado": 0, "enviado": 1, "entregado": 2, "leido": 3, "fallido": 4}


def registrar(
    tipo: str,
    destinatario: str,
    estado: str,
    plantilla: str | None = None,
    wamid: str | None = None,
    detalle: str | None = None,
    referencia: str | None = None,
) -> bool:
    """Deja constancia de un envio. Nunca interrumpe el aviso.

    Si falla el registro se avisa y se sigue: perder la auditoria es malo,
    pero no mandar la alerta por no poder auditarla es peor.
    """
    try:
        get_client().table("envios").insert({
            "tipo": tipo,
            "referencia": referencia,
            "destinatario": destinatario,
            "plantilla": plantilla,
            "wamid": wamid,
            "estado": estado,
            "detalle": (detalle or "")[:500] or None,
        }).execute()
        return True
    except Exception:
        logger.exception("No se pudo registrar el envio a %s (%s)", destinatario, tipo)
        return False


# --------------------------------------------------------------------------
# Lo que espera a que termine la noche: aplazado -> enviando -> aceptado.
# Ver meta_whatsapp_service.despachar_aplazados.
# --------------------------------------------------------------------------


def aplazar(
    tipo: str, destinatarios: list, contenido: dict, referencia: str | None = None
) -> bool:
    """Guarda un aviso por destinatario para mandarlo despues. True si quedo.

    Van todos en un solo insert: o se aplaza para todos o para ninguno. Si
    falla, quien lo llama lo manda ya a todos, y nadie se queda sin el aviso
    mientras otro lo recibe.
    """
    if not destinatarios:
        return True
    try:
        get_client().table("envios").insert([
            {
                "tipo": tipo,
                "referencia": referencia,
                "destinatario": destinatario,
                "estado": "aplazado",
                "contenido": contenido,
            }
            for destinatario in destinatarios
        ]).execute()
        return True
    except Exception:
        logger.exception("No se pudo aplazar el aviso %s (%s)", tipo, referencia)
        return False


def aplazados(limite: int = 50) -> list[dict]:
    """Los avisos que siguen esperando, en el orden en que se aplazaron."""
    try:
        return (
            get_client()
            .table("envios")
            .select("id, tipo, referencia, destinatario, contenido")
            .eq("estado", "aplazado")
            .order("id")
            .limit(limite)
            .execute()
            .data
        )
    except Exception:
        logger.exception("No se pudieron consultar los envios aplazados")
        return []


def tomar_aplazado(envio_id: int) -> bool:
    """Se queda con un aviso aplazado, si nadie lo tomo antes.

    Es una comparacion-y-cambio, como tomar_para_reintento en idempotencia:
    el UPDATE solo pasa si la fila sigue en "aplazado". Durante un despliegue
    corren dos procesos y los dos buscan aplazados; Postgres serializa los dos
    UPDATE y el segundo ya no encuentra la fila, asi que el aviso sale una vez.
    """
    try:
        resultado = (
            get_client()
            .table("envios")
            .update({"estado": "enviando"})
            .eq("id", envio_id)
            .eq("estado", "aplazado")
            .execute()
        )
    except Exception:
        logger.exception("No se pudo tomar el envio aplazado %s", envio_id)
        return False
    return bool(resultado.data)


def completar_aplazado(
    envio_id: int,
    estado: str,
    plantilla: str | None = None,
    wamid: str | None = None,
    detalle: str | None = None,
) -> None:
    """Deja en la fila como salio el aviso.

    La hora pasa a ser la del envio real: la fila dice cuando le llego al
    administrador, que es lo que se mira para saber si algo salio de noche.
    Que espero se sigue viendo en contenido, que solo tienen las aplazadas.
    """
    try:
        get_client().table("envios").update({
            "estado": estado,
            "plantilla": plantilla,
            "wamid": wamid,
            "detalle": (detalle or "")[:500] or None,
            "fecha_hora": horario.ahora().isoformat(),
        }).eq("id", envio_id).execute()
    except Exception:
        logger.exception("No se pudo registrar como salio el envio aplazado %s", envio_id)


def actualizar_estado(wamid: str, estado_meta: str, detalle: str | None = None) -> None:
    """Aplica al registro el estado que reporta Meta por el webhook."""
    estado = ESTADOS_META.get(estado_meta)
    if not estado:
        return

    try:
        filas = (
            get_client()
            .table("envios")
            .select("id, estado")
            .eq("wamid", wamid)
            .limit(1)
            .execute()
            .data
        )
        if not filas:
            # Normal: son los acuses de mensajes que no mandamos nosotros.
            return

        actual = filas[0]
        if _ORDEN.get(estado, 0) <= _ORDEN.get(actual["estado"], 0):
            return

        get_client().table("envios").update(
            {"estado": estado, "detalle": detalle}
        ).eq("id", actual["id"]).execute()

        if estado == "fallido":
            logger.error("Meta no pudo entregar el envio %s: %s", actual["id"], detalle)
        else:
            logger.info("Envio %s -> %s", actual["id"], estado)
    except Exception:
        logger.exception("No se pudo actualizar el estado del wamid %s", wamid)


def sin_entregar(horas: int = 24) -> list[dict]:
    """Envios que se aceptaron pero nunca confirmaron entrega.

    Son los candidatos a revisar: el mensaje entro a Meta y ahi se quedo.
    """
    from datetime import datetime, timedelta, timezone

    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    try:
        return (
            get_client()
            .table("envios")
            .select("*")
            .in_("estado", ["aceptado", "enviado", "fallido"])
            .gte("fecha_hora", desde)
            .order("fecha_hora", desc=True)
            .execute()
            .data
        )
    except Exception:
        logger.exception("No se pudieron consultar los envios sin entregar")
        return []
