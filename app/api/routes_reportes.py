from fastapi import APIRouter

from app.db.supabase_client import get_client
from app.models.reporte import ReporteEntrada
from app.services.reportes_service import procesar_reporte

router = APIRouter()


@router.post("/reportes")
def crear_reporte(entrada: ReporteEntrada):
    return procesar_reporte(entrada.texto, entrada.remitente)


@router.get("/reportes")
def listar_reportes(fecha: str | None = None):
    query = get_client().table("reportes").select("*")
    if fecha:
        query = query.gte("fecha_hora", f"{fecha}T00:00:00").lte(
            "fecha_hora", f"{fecha}T23:59:59"
        )
    return query.order("fecha_hora", desc=True).execute().data


@router.get("/alertas")
def listar_alertas():
    return (
        get_client()
        .table("reportes")
        .select("*")
        .eq("es_alerta", True)
        .order("fecha_hora", desc=True)
        .execute()
        .data
    )


@router.get("/resumen-dia")
def resumen_dia(fecha: str):
    reportes = (
        get_client()
        .table("reportes")
        .select("*")
        .gte("fecha_hora", f"{fecha}T00:00:00")
        .lte("fecha_hora", f"{fecha}T23:59:59")
        .execute()
        .data
    )

    resumen_por_lote: dict[str, list[dict]] = {}
    for reporte in reportes:
        lote = reporte.get("lote") or "sin_lote"
        resumen_por_lote.setdefault(lote, []).append(reporte)

    return resumen_por_lote
