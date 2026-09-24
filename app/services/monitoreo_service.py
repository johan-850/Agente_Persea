import logging
import re
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.horario import hoy, limites_utc
from app.services import consultas_service, fotos_service
from app.services import meta_whatsapp_service as whatsapp_service
from app.services.alertas_monitoreo_service import (
    evaluar_alerta_monitoreo,
    hallazgos_que_alertan,
)
from app.services.monitoreo_ia_service import extraer_reportes_monitoreo

logger = logging.getLogger("monitoreo")

# Cuanto se espera la respuesta al lote que se pidio. Pasado eso, un numero
# suelto ya no se interpreta como respuesta: la monitora siguio con otra cosa
# y seria peor asociarlo al reporte equivocado.
VENTANA_RESPUESTA_LOTE = timedelta(hours=2)

# Una respuesta al lote es corta. Un reporte completo tambien dice "lote #10",
# asi que el largo es lo que distingue "12" de un reporte de jornada.
_MAX_LARGO_RESPUESTA = 60
_SOLO_NUMERO = re.compile(r"^\s*#?\s*(\d{1,3})\s*$")
_MENCIONA_LOTE = re.compile(r"\blote\s*#?\s*(\d{1,3})\b", re.IGNORECASE)


def _lote_en_respuesta(texto: str | None) -> str | None:
    """El numero de lote si el mensaje parece la respuesta a nuestra pregunta.

    Devuelve None ante cualquier duda: colgar un numero del reporte equivocado
    es peor que dejar el reporte sin lote.
    """
    if not texto or len(texto) > _MAX_LARGO_RESPUESTA:
        return None

    coincidencia = _SOLO_NUMERO.match(texto)
    if coincidencia:
        return coincidencia.group(1)

    coincidencia = _MENCIONA_LOTE.search(texto)
    if coincidencia:
        return coincidencia.group(1)

    return None


def _reporte_sin_lote_reciente(remitente: str) -> dict | None:
    desde = (datetime.now(timezone.utc) - VENTANA_RESPUESTA_LOTE).isoformat()
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, finca, es_alerta, tipo_alerta, plagas_observadas")
        .eq("remitente", remitente)
        .is_("lote", "null")
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _asignar_lote_a_fotos(lote: str, remitente: str) -> bool:
    """Cuelga del lote indicado las fotos sueltas que llegaron sin texto.

    Devuelve True si el mensaje se consumio como respuesta, para no guardarlo
    ademas como reporte.
    """
    desde, _ = limites_utc(hoy())
    destino = (
        get_client()
        .table("monitoreos")
        .select("id, finca, lote")
        .eq("remitente", remitente)
        .eq("lote", str(lote))
        .gte("fecha_hora", desde)
        .order("fecha_hora", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not destino:
        return False

    monitoreo = destino[0]
    cuantas = fotos_service.reasignar_fotos(remitente, monitoreo)
    if not cuantas:
        return False

    finca = monitoreo.get("finca") or "sin finca"
    try:
        whatsapp_service.enviar_mensaje(
            remitente,
            f"Listo, quedaron {cuantas} foto(s) asociadas a finca {finca}, lote {lote}.",
        )
    except Exception:
        logger.exception("No se pudo confirmar la asignacion de fotos a %s", remitente)
    return True


def _completar_lote_pendiente(texto: str, remitente: str) -> bool:
    """Si el mensaje responde al lote que pedimos, lo completa y avisa.

    Devuelve True cuando se consumio como respuesta, para no guardarlo ademas
    como si fuera un reporte nuevo.
    """
    lote = _lote_en_respuesta(texto)
    if not lote:
        return False

    pendiente = _reporte_sin_lote_reciente(remitente)
    if not pendiente:
        # Puede ser la respuesta a "¿de que lote son estas fotos?".
        return _asignar_lote_a_fotos(lote, remitente)

    get_client().table("monitoreos").update({"lote": lote}).eq("id", pendiente["id"]).execute()
    finca = pendiente.get("finca") or "sin finca"
    logger.info("Reporte %s completado con el lote %s", pendiente["id"], lote)

    try:
        whatsapp_service.enviar_mensaje(
            remitente, f"Listo, el reporte de finca {finca} quedó registrado en el lote {lote}."
        )
    except Exception:
        logger.exception("No se pudo confirmar el lote a %s", remitente)

    # Si ese reporte ya habia disparado alerta, los administradores la
    # recibieron con "lote no especificado" y no sabrian a donde ir.
    if pendiente.get("es_alerta"):
        criticos = hallazgos_que_alertan(pendiente.get("plagas_observadas"))
        detalle = "; ".join(str(c) for c in criticos) or (pendiente.get("tipo_alerta") or "")
        try:
            whatsapp_service.enviar_a_administradores(
                f"📍 Complemento de la alerta de finca {finca}: corresponde al *lote {lote}*.\n"
                f"{detalle}",
                tipo="complemento_lote",
                referencia=f"monitoreo:{pendiente['id']}",
            )
        except Exception:
            logger.exception("No se pudo complementar la alerta del reporte %s", pendiente["id"])

    return True


def _pedir_lote(remitente: str, sin_lote: list[dict]) -> None:
    """Le pide a la monitora el lote que falta.

    Una sola pregunta por mensaje, no por reporte: si un mensaje cubre tres
    lotes y ninguno trae numero, preguntar tres veces es ruido.
    """
    fincas = sorted({str(r["finca"]) for r in sin_lote if r.get("finca")})
    de_finca = f" de finca {', '.join(fincas)}" if fincas else ""
    urgencia = (
        " Es un hallazgo que hay que revisar, así que ayuda saberlo pronto."
        if any(r.get("es_alerta") for r in sin_lote)
        else ""
    )

    try:
        whatsapp_service.enviar_mensaje(
            remitente,
            f"Recibí tu reporte{de_finca}, pero no encontré el número de lote.{urgencia}\n"
            "¿A qué lote corresponde? Puedes responderme solo con el número.",
        )
        logger.info("Se pidio el lote a %s (%d reporte/s sin lote)", remitente, len(sin_lote))
    except Exception:
        logger.exception("No se pudo pedir el lote a %s", remitente)


def _ya_se_registro_hoy(texto: str, remitente: str) -> dict | None:
    """El mismo reporte, de la misma persona, ya guardado hoy.

    El descarte por wamid solo atrapa los reenvios de Meta. Si la monitora
    cree que su reporte no entro y lo manda de nuevo, es un mensaje distinto
    con otro wamid: se guardaba dos veces y podia alertar dos veces.

    Se comparan los textos en memoria y no con un filtro en la consulta
    porque un reporte de jornada pasa del millar de caracteres y no tiene por
    que caber en una URL.
    """
    desde, hasta = limites_utc(hoy())
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, lote, texto_original")
        .eq("remitente", remitente)
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .execute()
        .data
    )
    for fila in filas:
        if fila.get("texto_original") == texto:
            return fila
    return None


def _texto_del_lote(extraido: dict) -> str:
    """Lo que la extraccion asigno a ESE lote, para evaluarlo por separado."""
    partes = [
        *(extraido.get("plagas_observadas") or []),
        extraido.get("nota") or "",
        extraido.get("tipo_alerta") or "",
    ]
    return " ".join(str(p) for p in partes)


def procesar_mensaje_monitoreo(texto: str, remitente: str) -> list[dict]:
    """Guarda un registro por lote y avisa solo de los lotes que lo ameritan.

    Las reglas duras se evaluan por lote, no sobre el mensaje completo. Un
    mensaje suele cubrir varios lotes ("termino el #10 y paso al #3"), y
    evaluarlo entero contagiaba la alerta a todos: el lote 10, con acaro y
    mosca blanca, salio marcado como plaga cuarentenaria porque el lote 3 del
    mismo mensaje tenia stenoma.
    """
    # Puede ser la respuesta al lote que pedimos, no un reporte nuevo.
    if _completar_lote_pendiente(texto, remitente):
        return []

    repetido = _ya_se_registro_hoy(texto, remitente)
    if repetido:
        logger.info(
            "Reporte repetido de %s, ya guardado como %s; no se duplica",
            remitente,
            repetido["id"],
        )
        try:
            lote = repetido.get("lote")
            whatsapp_service.enviar_mensaje(
                remitente,
                f"Ese reporte ya lo tenía registrado{f' (lote {lote})' if lote else ''}, "
                "así que no lo dupliqué. Si querías corregir algo, dime qué cambia.",
            )
        except Exception:
            logger.exception("No se pudo avisar del reporte repetido a %s", remitente)
        return []

    extraidos = extraer_reportes_monitoreo(texto)

    if not extraidos:
        # No es un reporte de campo. Si quien escribe es administrador, lo que
        # mando es una pregunta sobre los datos.
        #
        # El enganche va aqui y no en el despachador porque es aqui donde ya
        # se sabe que no era un reporte: decidirlo antes obligaria a clasificar
        # el mensaje dos veces, una llamada al modelo de mas por cada mensaje.
        if consultas_service.es_administrador(remitente):
            consultas_service.responder(texto, remitente)
        return []

    por_lote = [evaluar_alerta_monitoreo(_texto_del_lote(e)) for e in extraidos]
    algun_lote_alerto = any(alerta[0] for alerta in por_lote)

    # Red de seguridad: si el mensaje menciona algo grave que la extraccion no
    # llevo a ningun lote (un accidente suele quedar fuera de plagas_observadas),
    # se avisa en todos antes que perderlo.
    del_mensaje = evaluar_alerta_monitoreo(texto)

    guardados = []
    for extraido, (es_alerta_regla, tipo_regla, prioridad_regla) in zip(extraidos, por_lote):
        if not es_alerta_regla and del_mensaje[0] and not algun_lote_alerto:
            es_alerta_regla, tipo_regla, prioridad_regla = del_mensaje
            logger.warning(
                "El mensaje dispara '%s' pero la extraccion no lo asigno a ningun "
                "lote; se avisa en todos por precaucion",
                tipo_regla,
            )

        if es_alerta_regla:
            extraido["es_alerta"] = True
            extraido["tipo_alerta"] = extraido.get("tipo_alerta") or tipo_regla
            extraido["prioridad"] = extraido.get("prioridad") or prioridad_regla
        elif extraido.get("es_alerta"):
            # El modelo alerto por su cuenta y ninguna regla lo respalda. El
            # codigo solo sabia escalar: una alerta suya pasaba tal cual, y asi
            # un reporte de copturomimus perseae —que no es cuarentenaria— salio
            # como prioridad alta. El prompt ya acota el criterio, pero un
            # prompt no es una garantia y una regresion lo trae de vuelta.
            #
            # No se silencia: el modelo puede cachar una cuarentenaria escrita
            # de una forma que la lista de reglas no reconoce. Se baja a media y
            # se dice de donde viene, para que no se lea como un hallazgo
            # confirmado del catalogo.
            extraido["prioridad"] = "media"
            extraido["tipo_alerta"] = (
                f"{extraido.get('tipo_alerta') or 'hallazgo'} (criterio del modelo, "
                "sin coincidencia con el catalogo de cuarentenarias)"
            )
            logger.warning(
                "Alerta sin respaldo de las reglas, se baja a media: finca=%r lote=%r %r",
                extraido.get("finca"),
                extraido.get("lote"),
                extraido.get("plagas_observadas"),
            )

        registro = {
            "fecha_hora": datetime.now(timezone.utc).isoformat(),
            "remitente": remitente,
            "texto_original": texto,
            **extraido,
        }

        resultado = get_client().table("monitoreos").insert(registro).execute()
        guardado = resultado.data[0]
        guardados.append(guardado)

        if guardado.get("es_alerta"):
            _notificar_alerta(guardado)

    sin_lote = [g for g in guardados if not g.get("lote")]
    if sin_lote:
        _pedir_lote(remitente, sin_lote)

    return guardados


def _notificar_alerta(monitoreo: dict) -> None:
    prioridad = monitoreo.get("prioridad") or "sin prioridad"
    tipo_alerta = monitoreo.get("tipo_alerta") or "no especificado"
    finca = monitoreo.get("finca") or "no especificada"
    lote = monitoreo.get("lote") or "no especificado"
    remitente = monitoreo.get("remitente") or "desconocido"

    # El hallazgo que disparo la alerta va primero. Un bordeo trae quince
    # hallazgos rutinarios y el stenoma quedaba en el medio de la lista, o
    # cortado por el limite de 300 caracteres del parametro.
    observados = monitoreo.get("plagas_observadas") or []
    criticos = hallazgos_que_alertan(observados)
    resto = [p for p in observados if p not in criticos]
    plagas = ", ".join([*criticos, *resto]) or "no especificado"

    respaldo = (
        f"🚨 ALERTA ({prioridad})\n"
        f"Tipo: {tipo_alerta}\n"
        f"Finca: {finca}\n"
        f"Lote: {lote}\n"
        f"Plagas/hallazgos: {plagas}\n"
        f"Reporte original:\n{monitoreo['texto_original']}"
    )

    whatsapp_service.enviar_plantilla_a_administradores(
        whatsapp_service.PLANTILLA_ALERTA,
        [prioridad, finca, lote, plagas, tipo_alerta, remitente],
        respaldo=respaldo,
        tipo="alerta_reporte",
        referencia=f"monitoreo:{monitoreo.get('id')}",
    )
