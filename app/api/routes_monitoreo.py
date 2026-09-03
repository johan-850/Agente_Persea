from fastapi import APIRouter

from app.db.supabase_client import get_client
from app.models.reporte import ReporteEntrada
from app.services.monitoreo_service import procesar_mensaje_monitoreo

router = APIRouter()


@router.post("/monitoreos")
def crear_monitoreo(entrada: ReporteEntrada):
    return procesar_mensaje_monitoreo(entrada.texto, entrada.remitente)


@router.get("/monitoreos")
def listar_monitoreos(fecha: str | None = None):
    query = get_client().table("monitoreos").select("*")
    if fecha:
        query = query.gte("fecha_hora", f"{fecha}T00:00:00").lte(
            "fecha_hora", f"{fecha}T23:59:59"
        )
    return query.order("fecha_hora", desc=True).execute().data


@router.get("/alertas-monitoreo")
def listar_alertas_monitoreo():
    return (
        get_client()
        .table("monitoreos")
        .select("*")
        .eq("es_alerta", True)
        .order("fecha_hora", desc=True)
        .execute()
        .data
    )
