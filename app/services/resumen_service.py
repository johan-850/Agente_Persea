from datetime import datetime

from app.db.supabase_client import get_client
from app.services import meta_whatsapp_service as whatsapp_service


def _monitoreos_del_dia(fecha: str) -> list[dict]:
    return (
        get_client()
        .table("monitoreos")
        .select("*")
        .gte("fecha_hora", f"{fecha}T00:00:00")
        .lte("fecha_hora", f"{fecha}T23:59:59")
        .order("finca")
        .order("lote")
        .execute()
        .data
    )


def _formatear_resumen(fecha: str, monitoreos: list[dict]) -> str:
    if not monitoreos:
        return f"📋 Resumen de monitoreo del día {fecha}\nNo se recibieron reportes."

    lineas = [f"📋 Resumen de monitoreo del día {fecha} — {len(monitoreos)} lotes reportados"]

    por_finca: dict[str, list[dict]] = {}
    for item in monitoreos:
        finca = item.get("finca") or "finca sin especificar"
        por_finca.setdefault(finca, []).append(item)

    for finca, items in sorted(por_finca.items()):
        lineas.append(f"\n*{finca}*")
        for item in items:
            lote = item.get("lote") or "sin lote"
            estado = "✅ finalizado" if item.get("lote_finalizado") else "⏳ pendiente"
            marca_alerta = " 🚨" if item.get("es_alerta") else ""
            plagas = ", ".join(item.get("plagas_observadas") or []) or "sin hallazgos relevantes"
            lineas.append(f"  Lote {lote} ({estado}){marca_alerta}: {plagas}")

    alertas = [item for item in monitoreos if item.get("es_alerta")]
    if alertas:
        lineas.append(f"\n⚠️ {len(alertas)} alerta(s) generada(s) hoy.")

    return "\n".join(lineas)


def _formatear_detalle_plano(monitoreos: list[dict]) -> str:
    """Version de una sola linea del resumen, para usarla como parametro de
    plantilla (WhatsApp no acepta saltos de linea en los parametros).
    """
    if not monitoreos:
        return "sin reportes"

    partes = []
    for item in monitoreos:
        finca = item.get("finca") or "finca sin especificar"
        lote = item.get("lote") or "sin lote"
        estado = "finalizado" if item.get("lote_finalizado") else "pendiente"
        plagas = ", ".join(item.get("plagas_observadas") or []) or "sin hallazgos"
        partes.append(f"{finca} lote {lote} ({estado}): {plagas}")

    return "; ".join(partes)


def enviar_resumen_diario(fecha: str | None = None) -> str:
    fecha = fecha or datetime.now().date().isoformat()
    monitoreos = _monitoreos_del_dia(fecha)
    texto = _formatear_resumen(fecha, monitoreos)
    alertas = [item for item in monitoreos if item.get("es_alerta")]

    whatsapp_service.enviar_plantilla_a_administradores(
        whatsapp_service.PLANTILLA_RESUMEN,
        [fecha, str(len(monitoreos)), str(len(alertas)), _formatear_detalle_plano(monitoreos)],
        respaldo=texto,
    )
    return texto
