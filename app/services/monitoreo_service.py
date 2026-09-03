from datetime import datetime, timezone

from app.db.supabase_client import get_client
from app.services import meta_whatsapp_service as whatsapp_service
from app.services.alertas_monitoreo_service import evaluar_alerta_monitoreo
from app.services.monitoreo_ia_service import extraer_reportes_monitoreo


def procesar_mensaje_monitoreo(texto: str, remitente: str) -> list[dict]:
    extraidos = extraer_reportes_monitoreo(texto)

    es_alerta_regla, tipo_alerta_regla, prioridad_regla = evaluar_alerta_monitoreo(texto)

    guardados = []
    for extraido in extraidos:
        if es_alerta_regla:
            extraido["es_alerta"] = True
            extraido["tipo_alerta"] = extraido.get("tipo_alerta") or tipo_alerta_regla
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
    plagas = ", ".join(monitoreo.get("plagas_observadas") or []) or "no especificado"
    remitente = monitoreo.get("remitente") or "desconocido"

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
