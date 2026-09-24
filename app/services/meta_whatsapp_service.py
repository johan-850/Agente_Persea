import logging
import os
import time

import httpx

from app.services import envios_service

logger = logging.getLogger("meta_whatsapp")

# Un corte de red pasajero no es razon para perder una alerta.
INTENTOS_ENVIO = 3
ESPERA_REINTENTO_SEG = 2

IDIOMA_PLANTILLA = "es"

# Nombres exactos de las plantillas aprobadas en Meta. Si no coinciden, el envio
# cae al respaldo de texto libre (que solo llega dentro de la ventana de 24h).
PLANTILLA_ALERTA = "reporte_monitoreo_alerta"

# Los resumenes tienen dos versiones. Las v2 reparten la informacion en cinco
# huecos cortos en vez de meterla toda en uno: WhatsApp no admite saltos de
# linea DENTRO de un parametro, asi que la estructura tiene que estar en el
# cuerpo de la plantilla. Con un solo hueco, el detalle salia amontonado en una
# linea y cortado a media palabra a los 300 caracteres.
#
# Se intentan en orden: si la v2 todavia no esta aprobada, entra la vieja.
PLANTILLAS_RESUMEN = ["reporte_monitoreo_resumen_v2", "reporte_monitoreo_resumen"]
PLANTILLAS_SEMANAL = ["reporte_monitoreo_semanal_v2", "reporte_monitoreo_semanal"]

# Limite defensivo por parametro: el cuerpo completo de una plantilla no puede
# pasar de 1024 caracteres.
MAX_LARGO_PARAMETRO = 300


def _url() -> str:
    phone_number_id = os.environ["META_PHONE_NUMBER_ID"]
    return f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['META_ACCESS_TOKEN']}"}


def _numero(numero_destino: str) -> str:
    return numero_destino.replace("whatsapp:", "").lstrip("+")


def limpiar_parametro(valor, maximo: int = MAX_LARGO_PARAMETRO) -> str:
    """WhatsApp rechaza parametros de plantilla con saltos de linea, tabs o
    mas de 4 espacios seguidos, asi que se colapsa todo a espacios simples.
    """
    limpio = " ".join(str(valor or "").split())
    if len(limpio) > maximo:
        limpio = limpio[: maximo - 3].rstrip() + "..."
    return limpio or "no especificado"


def descargar_media(media_id: str) -> tuple[bytes, str]:
    """Descarga un archivo recibido por WhatsApp. Devuelve (bytes, mime_type).

    Son dos pasos: el webhook solo trae un media_id, hay que pedirle a Meta la
    URL temporal y descargarla con el mismo token (la URL sola no sirve).
    """
    respuesta = httpx.get(
        f"https://graph.facebook.com/v21.0/{media_id}",
        headers=_headers(),
        timeout=30,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    archivo = httpx.get(datos["url"], headers=_headers(), timeout=120)
    archivo.raise_for_status()

    return archivo.content, datos.get("mime_type", "image/jpeg")


def _enviar(payload: dict) -> str | None:
    """Manda el mensaje y devuelve el identificador que asigna Meta.

    Ese identificador es la llave para cruzar despues los acuses de entrega
    que llegan por el webhook.

    Se reintenta ante fallos de red porque un corte pasajero no es razon para
    perder una alerta. Un rechazo de Meta (4xx) no se reintenta: la plantilla
    no existe o el numero es invalido, y repetirlo da lo mismo.
    """
    ultimo_error = None
    for intento in range(INTENTOS_ENVIO):
        try:
            respuesta = httpx.post(_url(), headers=_headers(), json=payload, timeout=30)
            respuesta.raise_for_status()
            mensajes = respuesta.json().get("messages") or [{}]
            return mensajes[0].get("id")
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError as error:
            ultimo_error = error
            logger.warning(
                "Fallo de red al enviar (intento %d de %d): %s",
                intento + 1,
                INTENTOS_ENVIO,
                error,
            )
            if intento + 1 < INTENTOS_ENVIO:
                time.sleep(ESPERA_REINTENTO_SEG * (intento + 1))

    raise ultimo_error


def enviar_mensaje(numero_destino: str, texto: str) -> str | None:
    """Mensaje libre. Solo se entrega si el destinatario le escribio al bot en
    las ultimas 24 horas (ventana de atencion de WhatsApp).
    """
    return _enviar({
        "messaging_product": "whatsapp",
        "to": _numero(numero_destino),
        "type": "text",
        "text": {"body": texto},
    })


def enviar_plantilla(numero_destino: str, nombre: str, parametros: list) -> str | None:
    """Plantilla aprobada por Meta. A diferencia del mensaje libre, se entrega
    aunque el destinatario no haya escrito en las ultimas 24 horas.
    """
    return _enviar({
        "messaging_product": "whatsapp",
        "to": _numero(numero_destino),
        "type": "template",
        "template": {
            "name": nombre,
            "language": {"code": IDIOMA_PLANTILLA},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": limpiar_parametro(p)} for p in parametros
                    ],
                }
            ],
        },
    })


def _administradores() -> list:
    from app.services.admin_service import obtener_numeros_administradores

    return obtener_numeros_administradores()


def enviar_a_administradores(texto: str, tipo: str = "aviso", referencia: str | None = None) -> None:
    for numero in _administradores():
        try:
            wamid = enviar_mensaje(numero, texto)
            envios_service.registrar(tipo, numero, "aceptado", wamid=wamid, referencia=referencia)
        except Exception as error:
            logger.exception("No se pudo enviar el aviso a %s", numero)
            envios_service.registrar(
                tipo, numero, "fallido", detalle=str(error), referencia=referencia
            )


def enviar_plantilla_a_administradores(
    nombre,
    parametros: list,
    respaldo: str,
    tipo: str = "aviso",
    referencia: str | None = None,
) -> None:
    """Envia la plantilla a cada administrador y deja constancia del resultado.

    `nombre` y `parametros` pueden ser listas paralelas de candidatas, en orden
    de preferencia. Sirve para estrenar una plantilla sin esperar a que Meta la
    apruebe: se intenta la nueva y, si aun no esta lista, la que ya funciona.
    Cada una lleva sus propios parametros porque no tienen por que coincidir en
    numero de huecos.

    Si ninguna plantilla pasa se intenta el mensaje libre: llega solo si la
    ventana de 24h esta abierta, pero es preferible a perder una alerta en
    silencio.

    Cada intento queda en la tabla envios. Lo que se guarda al enviar es
    "aceptado", que solo dice que Meta lo recibio; el estado real lo traen
    despues los acuses por webhook.
    """
    candidatas = list(zip(nombre, parametros)) if isinstance(nombre, (list, tuple)) else [
        (nombre, parametros)
    ]

    numeros = _administradores()

    if not numeros:
        # El bucle sobre una lista vacia no hacia nada y no se notaba: la
        # alerta simplemente no existia para nadie.
        logger.error(
            "No hay administradores activos: el aviso '%s' no tiene a quien ir", tipo
        )
        envios_service.registrar(
            tipo, "(sin administradores)", "fallido",
            detalle="No hay administradores activos en la tabla", referencia=referencia,
        )
        return

    for numero in numeros:
        enviada = False
        fallo_plantilla = ""

        for plantilla, params in candidatas:
            try:
                wamid = enviar_plantilla(numero, plantilla, params)
                envios_service.registrar(
                    tipo, numero, "aceptado",
                    plantilla=plantilla, wamid=wamid, referencia=referencia,
                )
                enviada = True
                break
            except Exception as error:
                logger.warning(
                    "Fallo la plantilla '%s' hacia %s (%s)", plantilla, numero, error
                )
                fallo_plantilla = f"{plantilla}: {error}"

        if enviada:
            continue

        try:
            wamid = enviar_mensaje(numero, respaldo)
            envios_service.registrar(
                tipo, numero, "aceptado", wamid=wamid,
                detalle=f"texto libre; la plantilla fallo: {fallo_plantilla}",
                referencia=referencia,
            )
        except Exception as error:
            logger.exception("Tampoco se pudo enviar el texto libre hacia %s", numero)
            envios_service.registrar(
                tipo, numero, "fallido", plantilla=candidatas[0][0],
                detalle=f"plantilla: {fallo_plantilla} | texto libre: {error}",
                referencia=referencia,
            )
