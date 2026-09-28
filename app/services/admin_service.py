import logging

from app.db.supabase_client import get_client

logger = logging.getLogger("administradores")


def obtener_numeros_administradores() -> list[str]:
    resultado = (
        get_client()
        .table("administradores")
        .select("numero")
        .eq("activo", True)
        .execute()
    )
    return [fila["numero"] for fila in resultado.data]


def _digitos(numero) -> str:
    return "".join(c for c in str(numero) if c.isdigit())


def es_administrador(remitente: str) -> bool:
    """Si ese numero esta en la tabla de administradores, activo.

    Compara solo los digitos: WhatsApp manda "whatsapp:+57...", y en la tabla
    puede estar con espacios o sin el signo.
    """
    numero = _digitos(remitente)
    if not numero:
        return False
    try:
        numeros = obtener_numeros_administradores()
    except Exception:
        logger.exception("No se pudo comprobar si %s es administrador", remitente)
        return False

    return any(_digitos(n) == numero for n in numeros)
