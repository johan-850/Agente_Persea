from app.db.supabase_client import get_client


def obtener_numeros_administradores() -> list[str]:
    resultado = (
        get_client()
        .table("administradores")
        .select("numero")
        .eq("activo", True)
        .execute()
    )
    return [fila["numero"] for fila in resultado.data]
