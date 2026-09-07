"""Autorizacion inicial de Google Drive. Se corre UNA sola vez.

Abre el navegador, pide permiso sobre tu cuenta de Drive y devuelve un refresh
token que hay que pegar en el .env. A partir de ahi el agente renueva solo sus
credenciales y no vuelve a necesitar intervencion.

Requisitos previos (en console.cloud.google.com):
  1. Crear un proyecto.
  2. Habilitar la API "Google Drive API".
  3. Credenciales -> Crear credenciales -> ID de cliente de OAuth
     -> Tipo de aplicacion: "Aplicacion de escritorio".
  4. Copiar el ID de cliente y el secreto al .env como GOOGLE_CLIENT_ID y
     GOOGLE_CLIENT_SECRET.

Uso:
    python scripts/autorizar_drive.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit(
        "Falta la dependencia de autorizacion. Instalala con:\n"
        "    pip install google-auth-oauthlib"
    )

# drive.file limita el acceso a los archivos que crea esta misma app: el agente
# no puede ver ni tocar el resto de tu Drive.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> int:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not (client_id and client_secret):
        print("Faltan GOOGLE_CLIENT_ID y/o GOOGLE_CLIENT_SECRET en el .env")
        return 1

    configuracion = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flujo = InstalledAppFlow.from_client_config(configuracion, SCOPES)
    # access_type=offline y prompt=consent son necesarios para que Google
    # devuelva refresh token (si no, solo manda uno la primera vez de todas).
    credenciales = flujo.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    if not credenciales.refresh_token:
        print("Google no devolvio refresh token. Revoca el acceso en")
        print("https://myaccount.google.com/permissions y vuelve a intentar.")
        return 1

    print()
    print("Listo. Agrega esta linea al .env:")
    print()
    print(f"GOOGLE_REFRESH_TOKEN={credenciales.refresh_token}")
    print()
    print("Opcional: crea una carpeta en Drive para las fotos, abrela y copia")
    print("el id que aparece en la URL despues de /folders/ en:")
    print()
    print("GOOGLE_DRIVE_FOLDER_ID=<id de la carpeta>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
