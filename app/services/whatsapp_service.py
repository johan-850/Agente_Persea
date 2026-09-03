import os

from twilio.rest import Client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    return _client


def _formatear_whatsapp(numero: str) -> str:
    return numero if numero.startswith("whatsapp:") else f"whatsapp:{numero}"


def enviar_mensaje(numero_destino: str, texto: str) -> None:
    get_client().messages.create(
        from_=_formatear_whatsapp(os.environ["TWILIO_WHATSAPP_NUMBER"]),
        to=_formatear_whatsapp(numero_destino),
        body=texto,
    )


def enviar_a_administradores(texto: str) -> None:
    from app.services.admin_service import obtener_numeros_administradores

    for numero in obtener_numeros_administradores():
        enviar_mensaje(numero, texto)
