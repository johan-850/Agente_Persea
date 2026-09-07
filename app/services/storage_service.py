"""Archivo de fotos en Supabase Storage.

El bucket es privado: las fotos pueden mostrar trabajadores y detalles de las
fincas, asi que no quedan detras de una URL publica. En la base solo se guarda
la ruta, y el enlace para verlas se firma en el momento con vencimiento.

Storage es una cuota aparte de la base de datos (1 GB vs 500 MB en el plan
gratuito), asi que las fotos no consumen espacio de las tablas.
"""

import os

from app.db.supabase_client import get_client

BUCKET = os.environ.get("SUPABASE_BUCKET_FOTOS", "fotos-monitoreo")

# Vigencia del enlace firmado: suficiente para revisar una foto desde una
# alerta o un reporte sin dejar un enlace valido para siempre.
VIGENCIA_ENLACE_SEG = 60 * 60 * 24 * 7


def subir_foto(ruta: str, contenido: bytes, mime_type: str) -> str:
    """Sube la foto al bucket y devuelve la ruta con la que quedo guardada."""
    get_client().storage.from_(BUCKET).upload(
        ruta,
        contenido,
        {"content-type": mime_type, "upsert": "true"},
    )
    return ruta


def url_firmada(ruta: str, vigencia_seg: int = VIGENCIA_ENLACE_SEG) -> str:
    datos = get_client().storage.from_(BUCKET).create_signed_url(ruta, vigencia_seg)
    return datos["signedURL"]
