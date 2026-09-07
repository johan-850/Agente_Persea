from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_client
from app.models.reporte import ReporteEntrada
from app.services import storage_service
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


@router.get("/fotos")
def listar_fotos(monitoreo_id: int | None = None, fecha: str | None = None):
    query = get_client().table("fotos").select("*")
    if monitoreo_id is not None:
        query = query.eq("monitoreo_id", monitoreo_id)
    if fecha:
        query = query.gte("fecha_hora", f"{fecha}T00:00:00").lte(
            "fecha_hora", f"{fecha}T23:59:59"
        )
    return query.order("fecha_hora", desc=True).execute().data


@router.get("/fotos/{foto_id}/enlace")
def enlace_foto(foto_id: int):
    """El bucket es privado, asi que el enlace se firma en el momento y vence."""
    filas = get_client().table("fotos").select("storage_path").eq("id", foto_id).execute().data
    if not filas:
        raise HTTPException(status_code=404, detail="Foto no encontrada")

    ruta = filas[0].get("storage_path")
    if not ruta:
        raise HTTPException(status_code=404, detail="La foto no quedo archivada")

    return {"url": storage_service.url_firmada(ruta)}
