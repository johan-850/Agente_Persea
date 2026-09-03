from datetime import datetime, timezone

from app.db.supabase_client import get_client
from app.services import alertas_service, ia_service, whatsapp_service


def procesar_reporte(texto: str, remitente: str) -> dict:
    extraido = ia_service.extraer_reporte(texto)

    es_alerta_regla, tipo_alerta_regla, prioridad_regla = alertas_service.evaluar_alerta(texto)
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

    resultado = get_client().table("reportes").insert(registro).execute()
    reporte_guardado = resultado.data[0]

    if reporte_guardado.get("es_alerta"):
        _notificar_alerta(reporte_guardado)

    return reporte_guardado


def _notificar_alerta(reporte: dict) -> None:
    mensaje = (
        "🚨 ALERTA "
        f"({reporte.get('prioridad') or 'sin prioridad'})\n"
        f"Tipo: {reporte.get('tipo_alerta') or 'no especificado'}\n"
        f"Lote: {reporte.get('lote') or 'no especificado'}\n"
        f"Reporte original:\n{reporte['texto_original']}"
    )
    whatsapp_service.enviar_a_administradores(mensaje)
