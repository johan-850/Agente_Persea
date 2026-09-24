"""La unica puerta del agente hacia el modelo de lenguaje.

Todo lo que el agente le pide a un modelo pasa por aqui: extraer los datos de
un reporte, describir una foto y responder las consultas de los
administradores. El resto del codigo no sabe que proveedor hay detras ni como
se llama el modelo.

Sirve para dos cosas:

- Desplegar es configurar. El modelo sale de MODELO_IA y la credencial de
  ANTHROPIC_API_KEY; no hay nombres de modelo repartidos por el codigo.
- Cambiar de proveedor queda acotado a este archivo. Las tres funciones de
  abajo son el contrato; los prompts, los catalogos y los esquemas de
  herramientas viven en los servicios que las llaman y no dependen de quien
  responda.

Si algun dia se evalua otro proveedor, lo que hay que medir no es si el codigo
compila sino si aguanta las tres tareas. La de fotos es la dificil: distinguir
una perforacion en fruto de una en hoja decide si se dispara una alerta
cuarentenaria o no.
"""

import base64
import logging

import anthropic

from app import config

logger = logging.getLogger("modelo_ia")

_cliente: anthropic.Anthropic | None = None


class ModeloNoConfigurado(RuntimeError):
    """Falta la credencial del modelo.

    Se lanza en vez de seguir en silencio: sin modelo, un reporte se guardaria
    sin extraer nada y sin evaluar alertas, y nadie se enteraria hasta que
    hiciera falta el dato.
    """


def _obtener_cliente() -> anthropic.Anthropic:
    global _cliente
    if _cliente is None:
        if not config.ANTHROPIC_API_KEY:
            raise ModeloNoConfigurado(
                "ANTHROPIC_API_KEY no esta configurada: el agente no puede leer "
                "reportes ni fotos"
            )
        _cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _cliente


def hay_modelo() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def extraer(system: str, texto: str, herramienta: dict, max_tokens: int = 2048) -> dict | None:
    """Saca datos estructurados de un texto.

    Se fuerza el uso de la herramienta para que la respuesta venga siempre con
    la forma del esquema, en vez de prosa que habria que parsear. temperature 0
    porque extraer campos es determinista: el mismo texto debe dar lo mismo.

    Devuelve el contenido de la herramienta, o None si el modelo no la uso.
    """
    respuesta = _obtener_cliente().messages.create(
        model=config.MODELO_IA,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": texto}],
        tools=[herramienta],
        tool_choice={"type": "tool", "name": herramienta["name"]},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            return bloque.input
    return None


def describir_imagen(
    contenido: bytes,
    mime_type: str,
    prompt: str,
    herramienta: dict,
    max_tokens: int = 600,
) -> dict | None:
    """Lo mismo, pero mirando una foto.

    Describir una imagen es observar, no redactar: con la temperatura por
    defecto la misma foto daba veredictos distintos en cada pasada.
    """
    respuesta = _obtener_cliente().messages.create(
        model=config.MODELO_IA,
        max_tokens=max_tokens,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64.b64encode(contenido).decode(),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        tools=[herramienta],
        tool_choice={"type": "tool", "name": herramienta["name"]},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            return bloque.input
    return None


def conversar_con_herramientas(
    system: str,
    pregunta: str,
    herramientas: list[dict],
    ejecutar,
    max_rondas: int = 3,
    max_tokens: int = 1200,
) -> str | None:
    """Responde una pregunta dejando que el modelo consulte datos.

    `ejecutar(nombre, argumentos) -> dict` corre la consulta que el modelo
    pida. Quien llama decide que consultas existen y que devuelven; aqui solo
    se lleva la conversacion.

    Devuelve el texto final, o None si el modelo agoto las rondas sin
    responder.
    """
    mensajes: list[dict] = [{"role": "user", "content": pregunta}]

    for _ in range(max_rondas):
        respuesta = _obtener_cliente().messages.create(
            model=config.MODELO_IA,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=mensajes,
            tools=herramientas,
        )

        if respuesta.stop_reason != "tool_use":
            texto = "".join(b.text for b in respuesta.content if b.type == "text")
            return texto.strip() or None

        mensajes.append({"role": "assistant", "content": respuesta.content})
        resultados = []
        for bloque in respuesta.content:
            if bloque.type != "tool_use":
                continue
            resultados.append({
                "type": "tool_result",
                "tool_use_id": bloque.id,
                "content": ejecutar(bloque.name, bloque.input),
            })
        mensajes.append({"role": "user", "content": resultados})

    return None
