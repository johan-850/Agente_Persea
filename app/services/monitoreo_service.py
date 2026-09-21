import logging
from datetime import datetime, timezone

from app.db.supabase_client import get_client
from app.services import meta_whatsapp_service as whatsapp_service
from app.services.alertas_monitoreo_service import (
    evaluar_alerta_monitoreo,
    hallazgos_que_alertan,
)
from app.services.monitoreo_ia_service import extraer_reportes_monitoreo

logger = logging.getLogger("monitoreo")


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
    extraidos = extraer_reportes_monitoreo(texto)

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
    )
