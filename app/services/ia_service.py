import os

import anthropic

MODEL = "claude-haiku-4-5-20251001"

_client: anthropic.Anthropic | None = None

TIPOS_LABOR = [
    "fertilización edáfica",
    "aplicación foliar/dron",
    "drench",
    "control de maleza",
    "monitoreo",
    "mantenimiento",
    "otro",
]

PLACEHOLDERS_INVALIDOS = {"<unknown>", "unknown", "n/a", "na", "no especificado", "no aplica", ""}

SYSTEM_PROMPT = f"""Eres un asistente que extrae datos estructurados de reportes
de labores agricolas de campo enviados por WhatsApp. Los mensajes son texto
libre, desordenado, con abreviaturas (blts=bultos, kls=kilos, lts=litros),
emojis y formatos distintos segun quien escribe.

Extrae los campos indicados en la herramienta. No inventes datos.

Reglas importantes:
- lote: devuelve SOLO el numero o identificador (ej. "14"), sin el simbolo #
  ni la palabra "lote".
- tipo_labor: elige exactamente una de estas categorias: {", ".join(TIPOS_LABOR)}.
  Si no encaja claramente en ninguna, usa "otro".
- insumos: SOLO productos quimicos o fertilizantes realmente aplicados, con su
  dosis (ej. crento proteccion solar, micronical, Maytins calcio, Fertigro,
  Alga Plex). NUNCA pongas "agua" como si fuera un producto, ni "canecas" ni
  "lanzas" en insumos - esos van en los campos separados canecas,
  litros_totales y lanzas.
- canecas: cantidad de canecas/tanques preparados o aplicados, si se menciona.
- litros_totales: litros totales de mezcla aplicada, si se menciona.
- lanzas: cantidad de lanzas o equipos de aspersion usados, si se menciona.
- Si un campo no aparece en el texto, usa null (o lista vacia si aplica).
  NUNCA escribas placeholders como "<UNKNOWN>", "N/A" o "no especificado" -
  siempre usa null.

Ademas evalua si el reporte describe algo distinto a una labor rutinaria:
plagas o focos de plaga activos, danos continuos en cultivo, accidentes,
heridos, o fallas graves. Si es asi, marca es_alerta=true y describe
tipo_alerta y prioridad (alta/media/baja).
"""

REPORTE_TOOL = {
    "name": "extraer_reporte",
    "description": "Extrae los datos estructurados de un reporte de labor agricola de campo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lote": {"type": ["string", "null"]},
            "tipo_labor": {"type": ["string", "null"], "enum": [*TIPOS_LABOR, None]},
            "supervisor": {"type": ["string", "null"]},
            "personas": {"type": "array", "items": {"type": "string"}},
            "cantidad_personas": {"type": ["integer", "null"]},
            "insumos": {
                "type": "array",
                "description": (
                    "Solo productos quimicos/fertilizantes realmente aplicados. "
                    "No incluir agua, canecas ni lanzas aqui."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "producto": {"type": "string"},
                        "cantidad": {"type": ["number", "null"]},
                        "unidad": {"type": ["string", "null"]},
                    },
                    "required": ["producto"],
                },
            },
            "canecas": {"type": ["number", "null"]},
            "litros_totales": {"type": ["number", "null"]},
            "lanzas": {"type": ["integer", "null"]},
            "hora_inicio": {"type": ["string", "null"]},
            "hora_fin": {"type": ["string", "null"]},
            "nota": {"type": ["string", "null"]},
            "es_alerta": {"type": "boolean"},
            "tipo_alerta": {"type": ["string", "null"]},
            "prioridad": {"type": ["string", "null"]},
        },
        "required": [
            "lote",
            "tipo_labor",
            "supervisor",
            "personas",
            "cantidad_personas",
            "insumos",
            "canecas",
            "litros_totales",
            "lanzas",
            "hora_inicio",
            "hora_fin",
            "nota",
            "es_alerta",
            "tipo_alerta",
            "prioridad",
        ],
    },
}

_CAMPOS_TEXTO = (
    "lote",
    "tipo_labor",
    "supervisor",
    "hora_inicio",
    "hora_fin",
    "nota",
    "tipo_alerta",
    "prioridad",
)


def _normalizar(extraido: dict) -> dict:
    for campo in _CAMPOS_TEXTO:
        valor = extraido.get(campo)
        if isinstance(valor, str) and valor.strip().lower() in PLACEHOLDERS_INVALIDOS:
            extraido[campo] = None

    lote = extraido.get("lote")
    if isinstance(lote, str):
        extraido["lote"] = lote.lstrip("#").strip() or None

    return extraido


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _extraccion_simulada(texto: str) -> dict:
    """Sin ANTHROPIC_API_KEY no se puede llamar a la IA. Se guarda el reporte
    completo en 'nota' sin desglosar campos, para no perder el dato y poder
    seguir probando el resto del flujo (webhook, Supabase, alertas, resumen).
    Las reglas duras de alertas_service igual se aplican sobre el texto crudo.
    """
    return {
        "lote": None,
        "tipo_labor": None,
        "supervisor": None,
        "personas": [],
        "cantidad_personas": None,
        "insumos": [],
        "canecas": None,
        "litros_totales": None,
        "lanzas": None,
        "hora_inicio": None,
        "hora_fin": None,
        "nota": texto,
        "es_alerta": False,
        "tipo_alerta": None,
        "prioridad": None,
    }


def extraer_reporte(texto: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _extraccion_simulada(texto)

    respuesta = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}],
        tools=[REPORTE_TOOL],
        tool_choice={"type": "tool", "name": "extraer_reporte"},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            return _normalizar(bloque.input)
    raise ValueError("Claude no devolvio una extraccion estructurada")
