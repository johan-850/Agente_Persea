"""Subida de archivos a Google Drive con OAuth de usuario.

Se usa OAuth y no una cuenta de servicio porque las cuentas de servicio no
tienen cuota propia en Drive: subir a "Mi unidad" falla, y las Unidades
compartidas (que si funcionarian) solo existen en Google Workspace.

El refresh token se obtiene una sola vez con scripts/autorizar_drive.py.
"""

import json
import logging
import os
import time

import httpx

logger = logging.getLogger("drive")

URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_SUBIDA = "https://www.googleapis.com/upload/drive/v3/files"

# Se renueva un poco antes de que expire para no cortar una subida a la mitad.
MARGEN_EXPIRACION_SEG = 60

_token_cache: dict = {"valor": None, "expira_en": 0.0}


def _access_token() -> str:
    if _token_cache["valor"] and time.time() < _token_cache["expira_en"]:
        return _token_cache["valor"]

    respuesta = httpx.post(
        URL_TOKEN,
        data={
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    _token_cache["valor"] = datos["access_token"]
    _token_cache["expira_en"] = time.time() + datos.get("expires_in", 3600) - MARGEN_EXPIRACION_SEG
    return _token_cache["valor"]


def subir_archivo(nombre: str, contenido: bytes, mime_type: str) -> dict:
    """Sube el archivo y devuelve {id, url}. La carpeta destino sale de
    GOOGLE_DRIVE_FOLDER_ID; si no esta definida, va a la raiz de la unidad.
    """
    metadatos = {"name": nombre}
    carpeta = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if carpeta:
        metadatos["parents"] = [carpeta]

    archivos = {
        "metadata": ("metadata.json", json.dumps(metadatos), "application/json"),
        "file": (nombre, contenido, mime_type),
    }

    respuesta = httpx.post(
        URL_SUBIDA,
        params={"uploadType": "multipart", "fields": "id,webViewLink"},
        headers={"Authorization": f"Bearer {_access_token()}"},
        files=archivos,
        timeout=120,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    return {"id": datos["id"], "url": datos.get("webViewLink")}
