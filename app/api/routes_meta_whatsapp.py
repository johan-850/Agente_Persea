import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("meta_webhook")

from app import config, horario
from app.api.seguridad import verificar_firma_meta
from app.services.cola_mensajes import encolar, recuperar_pendientes
from app.services import meta_whatsapp_service
from app.services.envios_service import actualizar_estado
from app.services.fotos_service import procesar_foto
from app.services.idempotencia_service import reclamar
from app.services.monitoreo_service import procesar_mensaje_monitoreo
from app.services.reporte_original_service import responder_a_mensaje_citado

router = APIRouter()

# La WABA a la que pertenece el numero no se puede consultar con los permisos
# del token, pero viene en cada evento. Se registra una vez por arranque: hace
# falta para crear plantillas en la cuenta correcta.
_wabas_vistas: set[str] = set()


def recuperar_cola() -> int:
    """Se llama al arrancar: reencola lo que quedo a medias."""
    return recuperar_pendientes(_procesar_mensaje)


# Lo que el agente aun no sabe leer, y como se lo explica a quien lo manda.
# Antes se ignoraban sin decir nada: la monitora mandaba un video del daño,
# no pasaba nada, y ella daba por hecho que habia quedado registrado.
NO_SOPORTADO = {
    "video": "los videos",
    "audio": "las notas de voz",
    "document": "los documentos",
    "sticker": "los stickers",
    "location": "las ubicaciones",
    "contacts": "los contactos",
}


# Cuanto puede tardar un mensaje en llegar y todavia merecer respuesta.
#
# Meta reintenta durante dias lo que no logro entregar. Una pregunta del 23 de
# septiembre, mandada mientras el agente estaba apagado, llego el 29 a la 1:55
# de la mañana y el agente la contesto como si fuera nueva. Ya habian llegado
# otras dos de esa noche, 20 y 22 horas tarde, pero de dia y nadie lo noto.
# Lo normal es que un mensaje llegue en segundos, y la recuperacion de
# pendientes lo reintenta dentro de la primera media hora; pasada una hora ya
# no hay conversacion a la que contestar.
RETRASO_MAXIMO_PARA_RESPONDER = timedelta(hours=1)


def momento_de_envio(mensaje: dict) -> datetime:
    """Cuando lo mando la persona, segun Meta, que no es cuando nos llego."""
    try:
        return datetime.fromtimestamp(int(mensaje["timestamp"]), timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return horario.ahora().astimezone(timezone.utc)


def _procesar_mensaje(mensaje: dict) -> None:
    numero = mensaje.get("from")
    if not numero:
        return
    remitente = f"whatsapp:+{numero}"
    tipo = mensaje.get("type")

    # Un mensaje que llega tarde se registra igual —un reporte es un reporte—
    # y con la hora en que se mando. Lo que no se hace es contestarle a quien
    # lo mando como si la conversacion siguiera abierta.
    enviado_en = momento_de_envio(mensaje)
    atraso = horario.ahora() - enviado_en
    responder = atraso <= RETRASO_MAXIMO_PARA_RESPONDER
    if not responder:
        minutos = atraso.total_seconds() / 60
        logger.warning(
            "El mensaje %s de %s llego %s tarde (se mando %s): se registra, pero no se contesta",
            mensaje.get("id"),
            remitente,
            f"{minutos:.0f} min" if minutos < 120 else f"{minutos / 60:.1f} h",
            horario.cuando_legible(enviado_en),
        )

    if tipo == "image":
        imagen = mensaje.get("image", {})
        media_id = imagen.get("id")
        caption = imagen.get("caption")
        if not media_id:
            return
        # Si la foto trae caption con el reporte, se procesa primero para que
        # exista el monitoreo al que la foto se va a asociar.
        if caption:
            procesar_mensaje_monitoreo(
                texto=caption, remitente=remitente, enviado_en=enviado_en, responder=responder
            )
        procesar_foto(
            media_id=media_id,
            remitente=remitente,
            caption=caption,
            enviado_en=enviado_en,
            responder=responder,
        )
        return

    if tipo == "text":
        # Un administrador que responde a una alerta quiere ver su reporte.
        # Se resuelve antes que nada: el texto de la respuesta ("ver", "?") no
        # es un reporte ni una pregunta que el modelo sepa leer.
        citado = (mensaje.get("context") or {}).get("id")
        if citado and responder_a_mensaje_citado(citado, remitente, responder=responder):
            return
        texto = mensaje.get("text", {}).get("body")
        if texto:
            procesar_mensaje_monitoreo(
                texto=texto, remitente=remitente, enviado_en=enviado_en, responder=responder
            )
        return

    if tipo in NO_SOPORTADO:
        if responder:
            _avisar_no_soportado(remitente, tipo)
        return

    logger.warning("Tipo de mensaje desconocido, se ignora: %r", tipo)


def _avisar_no_soportado(remitente: str, tipo: str) -> None:
    """Responde en vez de callar.

    El caption de un video si se lee, porque llega como texto del mensaje; lo
    que no se puede es mirar el video.
    """
    logger.info("Mensaje de tipo %s de %s: no se procesa, se avisa", tipo, remitente)
    que = NO_SOPORTADO[tipo]
    try:
        meta_whatsapp_service.enviar_mensaje(
            remitente,
            f"Recibí tu mensaje, pero todavía no puedo leer {que}: solo texto y fotos.\n"
            "Si el hallazgo se ve en una foto, mándamela y la reviso. "
            "Si prefieres, escríbeme el reporte y lo registro igual.",
        )
    except Exception:
        logger.exception("No se pudo avisar a %s sobre el %s", remitente, tipo)


@router.get("/meta/webhook")
def verificar_webhook_meta(request: Request):
    params = request.query_params
    esperado = config.META_VERIFY_TOKEN
    # Sin token configurado no se verifica nada: si no, un token vacio en la
    # peticion coincidiria con el vacio de la configuracion y cualquiera
    # podria registrar el webhook.
    if (
        esperado
        and params.get("hub.mode") == "subscribe"
        and hmac.compare_digest(params.get("hub.verify_token", ""), esperado)
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/meta/webhook")
async def recibir_mensaje_meta(cuerpo: bytes = Depends(verificar_firma_meta)):
    """Confirma de inmediato y deja el trabajo pesado a la cola.

    Procesar aqui mismo tardaba entre 4 y 6 segundos por mensaje; Meta no
    alcanzaba a recibir el 200, reenviaba el evento y cada reenvio volvia a
    guardar el reporte y a repetir la alerta.

    El cuerpo llega como bytes desde la verificacion de firma, que necesita
    los datos tal como los mando Meta.

    Nunca se devuelve 500 por un fallo de procesamiento: si el webhook falla
    seguido, Meta desactiva la suscripcion y dejan de llegar los reportes. La
    firma invalida si corta antes, con 403, porque eso no viene de Meta.
    """
    payload = json.loads(cuerpo)

    for entry in payload.get("entry", []):
        waba_id = entry.get("id")
        if waba_id and waba_id not in _wabas_vistas:
            _wabas_vistas.add(waba_id)
            logger.info("Eventos recibidos de la WABA %s", waba_id)

        for change in entry.get("changes", []):
            valor = change.get("value", {})
            # Los acuses de entrega de lo que nosotros mandamos. Se cruzan
            # con la tabla envios por el id que Meta asigno al aceptarlo, y
            # son la unica forma de saber si la alerta llego al telefono del
            # administrador y no solo a la cola de Meta.
            for estado in valor.get("statuses", []):
                wamid_envio = estado.get("id")
                if not wamid_envio:
                    continue
                errores = estado.get("errors") or []
                detalle = "; ".join(
                    str(e.get("title") or e.get("message") or e) for e in errores
                ) or None
                await run_in_threadpool(
                    actualizar_estado, wamid_envio, estado.get("status", ""), detalle
                )
            for mensaje in valor.get("messages", []):
                wamid = mensaje.get("id")
                # run_in_threadpool: el cliente de Supabase es sincrono y
                # bloquearia el bucle de eventos de todas las peticiones.
                if wamid and not await run_in_threadpool(reclamar, wamid, mensaje):
                    logger.info("Reenvio de %s descartado, ya se habia procesado", wamid)
                    continue
                logger.info(
                    "Mensaje %s encolado (%d en cola)",
                    wamid,
                    encolar(_procesar_mensaje, mensaje),
                )

    return Response(status_code=200)
