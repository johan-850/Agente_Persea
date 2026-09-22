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
) -> None:
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
    except Exception:
        logger.exception("No se pudo registrar el envio a %s (%s)", destinatario, tipo)


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
