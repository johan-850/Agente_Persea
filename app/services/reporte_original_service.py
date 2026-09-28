"""El reporte tal como lo escribio la monitora, para el administrador que lo pida.

La alerta dice lo que el agente entendio del reporte: finca, lote, hallazgos.
Pero la extraccion puede equivocarse, y ante una cuarentenaria el
administrador quiere leer lo que la monitora escribio de verdad, con sus
palabras, y ver las fotos que mando antes de decidir a donde ir.

Se pide de dos formas:

- Respondiendo a la alerta en WhatsApp (mantener presionado -> Responder),
  con cualquier texto. La respuesta trae el identificador del mensaje citado,
  y cada alerta quedo registrada en envios con ese identificador y el reporte
  o la foto que la disparo. No hay que escribir finca ni lote.
- Pidiendolo por escrito ("el reporte original del 14 de rivera"): lo resuelve
  la consulta mostrar_reporte_original.

El texto va tal cual, sin pasar por el modelo. Si se lo diera a redactar lo
resumiria, y lo que se pidio es justamente el original.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_client
from app.horario import ZONA, limites_utc
from app.services import envios_service, meta_whatsapp_service, storage_service
from app.services.admin_service import es_administrador

logger = logging.getLogger("reporte_original")

# Los mensajes del agente que, citados, piden ver su reporte. Responder a un
# resumen o a una pregunta de lote no: esos siguen su camino normal.
TIPOS_CON_REPORTE = {"alerta_reporte", "alerta_foto", "complemento_lote"}

_REFERENCIA = re.compile(r"^(monitoreo|foto):(\d+)$")

# Un reporte puede traer 25 fotos; mandarlas todas inunda el chat. Van primero
# las que mostraron daño, que son las que explican la alerta.
MAX_FOTOS = 5

# El enlace firmado solo tiene que durar lo que tarda Meta en descargar la
# imagen al enviarla.
VIGENCIA_ENLACE_SEG = 60 * 60

# Si no dicen el dia, se busca el reporte mas reciente de ese lote hasta aqui.
DIAS_HACIA_ATRAS = 30

# Con dia explicito puede haber varios del mismo lote (general y bordeo).
MAX_REPORTES_POR_PEDIDO = 3


# --------------------------------------------------------------------------
# Lecturas. Aparte para que las pruebas las sustituyan sin tocar la base.
# --------------------------------------------------------------------------


def _envio(wamid: str) -> dict | None:
    filas = (
        get_client().table("envios").select("tipo, referencia").eq("wamid", wamid).limit(1).execute().data
    )
    return filas[0] if filas else None


def _monitoreo(monitoreo_id: int) -> dict | None:
    filas = (
        get_client()
        .table("monitoreos")
        .select("id, fecha_hora, remitente, texto_original, finca, lote, es_alerta")
        .eq("id", monitoreo_id)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _foto(foto_id: int) -> dict | None:
    filas = (
        get_client()
        .table("fotos")
        .select("id, monitoreo_id, storage_path, descripcion, plagas_sugeridas, es_alerta, caption")
        .eq("id", foto_id)
        .limit(1)
        .execute()
        .data
    )
    return filas[0] if filas else None


def _fotos_del_reporte(monitoreo_id: int) -> list[dict]:
    return (
        get_client()
        .table("fotos")
        .select("id, monitoreo_id, storage_path, descripcion, plagas_sugeridas, es_alerta, caption")
        .eq("monitoreo_id", monitoreo_id)
        .order("fecha_hora")
        .execute()
        .data
    )


def _reportes_del_lote(lote: str, finca: str | None, desde: str, hasta: str | None) -> list[dict]:
    consulta = (
        get_client()
        .table("monitoreos")
        .select("id, fecha_hora, finca, lote")
        .eq("lote", str(lote))
        .gte("fecha_hora", desde)
    )
    if hasta:
        consulta = consulta.lt("fecha_hora", hasta)
    if finca:
        consulta = consulta.ilike("finca", f"%{finca}%")
    return consulta.order("fecha_hora", desc=True).limit(MAX_REPORTES_POR_PEDIDO).execute().data


# --------------------------------------------------------------------------
# Armado y envio.
# --------------------------------------------------------------------------


def _cuando(fecha_hora) -> str:
    momento = datetime.fromisoformat(str(fecha_hora)).astimezone(ZONA)
    return momento.strftime("%Y-%m-%d a las %H:%M")


def encabezado(monitoreo: dict) -> str:
    finca = monitoreo.get("finca") or "finca sin especificar"
    lote = monitoreo.get("lote") or "sin lote"
    quien = str(monitoreo.get("remitente") or "desconocido").replace("whatsapp:", "")
    return (
        f"📄 *Reporte original* — {finca}, lote {lote}\n"
        f"{_cuando(monitoreo['fecha_hora'])} · {quien}\n"
        "Tal como lo escribió la monitora:"
    )


def trozos(texto: str, largo: int = meta_whatsapp_service.LARGO_MAXIMO_TEXTO) -> list[str]:
    """Parte un texto largo en mensajes que WhatsApp acepte, por saltos de
    linea cuando se puede, para no cortar una frase por la mitad."""
    partes, actual = [], ""
    for linea in texto.splitlines(keepends=True):
        while len(linea) > largo:
            if actual:
                partes.append(actual)
                actual = ""
            partes.append(linea[:largo])
            linea = linea[largo:]
        if len(actual) + len(linea) > largo:
            partes.append(actual)
            actual = ""
        actual += linea
    if actual:
        partes.append(actual)
    return partes or [""]


def leyenda(foto: dict) -> str:
    """Lo que se vio en la foto. Las candidatas van como lo que son: hipotesis
    del modelo sobre una imagen, a confirmar en campo."""
    partes = []
    if foto.get("es_alerta"):
        partes.append("📷 Con posible daño")
    if foto.get("descripcion"):
        partes.append(str(foto["descripcion"]))
    if foto.get("es_alerta") and foto.get("plagas_sugeridas"):
        partes.append("Compatible con: " + ", ".join(str(p) for p in foto["plagas_sugeridas"]))
    return "\n".join(partes)[: meta_whatsapp_service.LARGO_MAXIMO_LEYENDA]


def _mandar_texto(destinatario: str, texto: str, referencia: str) -> None:
    wamid = meta_whatsapp_service.enviar_mensaje(destinatario, texto)
    envios_service.registrar("reporte_original", destinatario, "aceptado", wamid=wamid, referencia=referencia)


def _mandar_foto(destinatario: str, foto: dict) -> bool:
    if not foto.get("storage_path"):
        # Se describio pero no se archivo (fallo la subida): no hay que mandar.
        return False
    enlace = storage_service.url_firmada(foto["storage_path"], VIGENCIA_ENLACE_SEG)
    wamid = meta_whatsapp_service.enviar_imagen(destinatario, enlace, leyenda(foto))
    envios_service.registrar(
        "reporte_original", destinatario, "aceptado", wamid=wamid, referencia=f"foto:{foto['id']}"
    )
    return True


def enviar_reporte(monitoreo_id: int, destinatario: str, foto_citada: dict | None = None) -> dict:
    """Manda el reporte tal cual y sus fotos. Devuelve lo que se mando.

    Si se pidio a partir de una foto, esa va primero: es la que el
    administrador tenia delante cuando pregunto.
    """
    monitoreo = _monitoreo(monitoreo_id)
    if not monitoreo:
        return {"reportes": 0, "fotos": 0}

    referencia = f"monitoreo:{monitoreo_id}"
    _mandar_texto(destinatario, encabezado(monitoreo), referencia)
    for parte in trozos(monitoreo.get("texto_original") or "(el reporte llegó sin texto)"):
        _mandar_texto(destinatario, parte, referencia)

    fotos = _fotos_del_reporte(monitoreo_id)
    if foto_citada:
        fotos = [f for f in fotos if f["id"] != foto_citada["id"]]
    # sorted es estable: dentro de cada grupo se conserva el orden de llegada.
    fotos = sorted(fotos, key=lambda f: not f.get("es_alerta"))
    if foto_citada:
        fotos = [foto_citada, *fotos]

    enviadas = 0
    for foto in fotos[:MAX_FOTOS]:
        try:
            enviadas += _mandar_foto(destinatario, foto)
        except Exception:
            logger.exception("No se pudo mandar la foto %s del reporte %s", foto.get("id"), monitoreo_id)

    restantes = len(fotos) - min(len(fotos), MAX_FOTOS)
    if restantes:
        _mandar_texto(
            destinatario,
            f"El reporte tiene {len(fotos)} fotos; te mandé las {MAX_FOTOS} primeras, "
            "con las de daño adelante.",
            referencia,
        )

    return {
        "reportes": 1,
        "fotos": enviadas,
        "fotos_del_reporte": len(fotos),
        "finca": monitoreo.get("finca"),
        "lote": monitoreo.get("lote"),
        "dia": _cuando(monitoreo["fecha_hora"])[:10],
    }


def _enviar_foto_sola(foto: dict, destinatario: str) -> None:
    _mandar_texto(
        destinatario,
        "📷 Esta foto llegó sin un reporte escrito al que asociarla. Es lo único que hay:",
        f"foto:{foto['id']}",
    )
    if not _mandar_foto(destinatario, foto):
        _mandar_texto(destinatario, "La foto no quedó archivada, así que no la puedo mostrar.", f"foto:{foto['id']}")


# --------------------------------------------------------------------------
# Las dos formas de pedirlo.
# --------------------------------------------------------------------------


def responder_a_mensaje_citado(wamid_citado: str, remitente: str) -> bool:
    """Si un administrador respondio a una alerta, le manda su reporte.

    Devuelve True si lo atendio. False si no era una alerta o no es
    administrador: el mensaje sigue entonces su camino normal.
    """
    envio = _envio(wamid_citado)
    if not envio or envio.get("tipo") not in TIPOS_CON_REPORTE:
        return False
    coincide = _REFERENCIA.match(str(envio.get("referencia") or ""))
    if not coincide:
        return False
    if not es_administrador(remitente):
        return False

    clase, identificador = coincide.group(1), int(coincide.group(2))
    referencia = f"{clase}:{identificador}"
    logger.info("%s pidio el reporte de la alerta %s", remitente, referencia)
    no_esta = "No encontré el reporte de esa alerta: puede que se haya borrado de la base."

    if clase == "monitoreo":
        if not enviar_reporte(identificador, remitente)["reportes"]:
            _mandar_texto(remitente, no_esta, referencia)
        return True

    foto = _foto(identificador)
    if not foto:
        _mandar_texto(remitente, no_esta, referencia)
        return True
    if foto.get("monitoreo_id"):
        enviar_reporte(foto["monitoreo_id"], remitente, foto_citada=foto)
    else:
        _enviar_foto_sola(foto, remitente)
    return True


def mostrar_por_lote(
    lote: str, destinatario: str, finca: str | None = None, fecha: str | None = None
) -> dict:
    """La consulta mostrar_reporte_original: busca y manda.

    Con fecha, los reportes de ese lote en ese dia. Sin fecha, el mas reciente
    de los ultimos 30 dias, que es lo que se quiere al preguntar por una alerta
    que acaba de llegar.
    """
    if fecha:
        desde, hasta = limites_utc(fecha)
        reportes = _reportes_del_lote(lote, finca, desde, hasta)
    else:
        desde = (datetime.now(timezone.utc) - timedelta(days=DIAS_HACIA_ATRAS)).isoformat()
        reportes = _reportes_del_lote(lote, finca, desde, None)[:1]

    if not reportes:
        return {"encontrados": 0, "enviado": False}

    enviados = [enviar_reporte(r["id"], destinatario) for r in reportes]
    return {
        "encontrados": len(reportes),
        "enviado": True,
        "reportes": [
            {"finca": e.get("finca"), "lote": e.get("lote"), "dia": e.get("dia"), "fotos_enviadas": e.get("fotos")}
            for e in enviados
        ],
    }
