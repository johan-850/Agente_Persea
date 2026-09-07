import os

from app.services.ia_service import get_client

MODEL = "claude-haiku-4-5-20251001"

TIPOS_LABOR_MONITOREO = [
    "monitoreo general",
    "monitoreo específico",
    "bordeo",
    "capacitación",
    "aplicación con dron",
    "otro",
]

PLACEHOLDERS_INVALIDOS = {"<unknown>", "unknown", "n/a", "na", "no especificado", "no aplica", ""}

# Catalogo del PLAN MIPE de Agricola Persea (aguacate Hass). Sirve para que el
# modelo normalice los nombres que las monitoras escriben de formas muy
# distintas ("pseudocercosphora", "cefaleurus", "acaro en ninfa y adulto").
CATALOGO_PLAGAS = """
Plagas CUARENTENARIAS (umbral 0%: cualquier presencia es alerta):
- Heilipus lauri (barrenador de semilla)
- Heilipus elegans (barrenador de tallo)
- Stenoma catenifer (pasador del fruto)
- Maconellicoccus hirsutus (cochinilla rosada del hibisco)
- Pseudococcus jackbeardsleyi (cochinilla harinosa de Jack Beardsley)
- Pseudococcus landoi (cochinilla harinosa de Lando)
- Ceroplastes rubens (escama cerosa roja)
- Saissetia batesi (escama hemisferica del aguacate)

Plagas de importancia economica (no cuarentenarias):
- Oligonychus yothersi (acaro cafe)
- Monalonion velezangeli
- Astaena aff pygidialis
- Amorbia emigratella / Platynota sp.
- Frankliniella occidentalis, Heliothrips haemorrhoidalis (trips)
- Compsus sp.
- Bruggmanniella perseae
- Diabrotica balteata
- Copturomimus perseae

Enfermedades:
- Verticillium dahliae (marchitamiento)
- Pseudocercospora purpurea (mancha angular de la hoja / peca del fruto)
- Colletotrichum gloeosporioides y C. acutatum (antracnosis)
- Phytophthora cinnamomi (pudricion de raiz)
- Chancro bacteriano (varias especies)

Otros hallazgos frecuentes que no son plagas del catalogo: mosca blanca,
cephaleuros, doctoriella sacc, sphaceloma, suelda, arboles cloroticos,
resiembras muertas, fruta con golpe de sol, arvenses, comedores de follaje.
"""

SYSTEM_PROMPT = f"""Eres un asistente que extrae datos estructurados de reportes
de monitoreo de plagas agricolas enviados por WhatsApp. Los mensajes son texto
libre, desordenado, con emojis, viñetas variadas y formatos distintos segun
quien escribe.

IMPORTANTE: un solo mensaje puede reportar sobre VARIOS lotes distintos (ej.
"se finaliza lote #13... se pasa a realizar esta misma labor al lote #14...").
Debes devolver un elemento en "reportes" por CADA lote mencionado.

Para cada lote extrae:
- finca: nombre de la finca mencionada (ej. "la linda", "rivera", "alfa").
  Si el mensaje no la menciona pero es claramente continuacion del mismo
  reporte, puedes dejarla null.
- lote: SOLO el numero o identificador (ej. "14"), sin el simbolo # ni la
  palabra "lote".
- tipo_labor: elige exactamente una de estas categorias: {", ".join(TIPOS_LABOR_MONITOREO)}.
  Si no encaja claramente, usa "otro".
- monitoras: cantidad de monitoras/personas que hicieron el monitoreo, si se
  menciona (ej. "se contó con 1 monitora" = 1).
- lote_finalizado: true si el texto dice "se finaliza lote" o similar; false
  si dice "no se finaliza lote", "no sé termina labor" o similar; null si no
  se menciona el estado.
- plagas_observadas: lista de strings, uno por cada plaga/problema mencionado
  para ESE lote, preservando detalles relevantes de severidad tal como
  aparecen en el texto (ej. "escamas - foco ACTIVO", "acaro - baja poblacion",
  "mosca blanca - alta poblacion"). Preserva la palabra "ACTIVO" en mayuscula
  si el texto la usa asi, es una senal importante. No inventes plagas que no
  esten en el texto.
  Usa el catalogo de abajo para normalizar nombres mal escritos o abreviados
  ("pseudocercosphora" -> "pseudocercospora", "cefaleurus" -> "cephaleuros"),
  pero conserva siempre el descriptor de severidad que puso la monitora.
- nota: contexto adicional relevante que no encaje en los campos anteriores
  (interrupciones por clima, transiciones entre lotes, conteos especificos
  como numero de larvas encontradas, etc). Puede ser null.
- es_alerta: true si en ESE lote se detecta una plaga cuarentenaria, un foco
  marcado como "ACTIVO", o algo grave (accidente, herido). false en caso
  contrario.
- tipo_alerta y prioridad (alta/media/baja): solo si es_alerta es true.

Si un campo no aplica, usa null (o lista vacia si aplica). NUNCA escribas
placeholders como "<UNKNOWN>", "N/A" o "no especificado" como valor - siempre
usa null. No inventes datos que no esten en el texto.

CATALOGO DE PLAGAS Y ENFERMEDADES DEL CULTIVO
{CATALOGO_PLAGAS}"""

REPORTE_MONITOREO_TOOL = {
    "name": "extraer_reportes_monitoreo",
    "description": "Extrae uno o mas reportes de monitoreo de plagas (uno por lote) de un mensaje de WhatsApp.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reportes": {
                "type": "array",
                "description": "Un elemento por cada lote distinto mencionado en el mensaje.",
                "items": {
                    "type": "object",
                    "properties": {
                        "finca": {"type": ["string", "null"]},
                        "lote": {"type": ["string", "null"]},
                        "tipo_labor": {
                            "type": ["string", "null"],
                            "enum": [*TIPOS_LABOR_MONITOREO, None],
                        },
                        "monitoras": {"type": ["integer", "null"]},
                        "lote_finalizado": {"type": ["boolean", "null"]},
                        "plagas_observadas": {"type": "array", "items": {"type": "string"}},
                        "nota": {"type": ["string", "null"]},
                        "es_alerta": {"type": "boolean"},
                        "tipo_alerta": {"type": ["string", "null"]},
                        "prioridad": {"type": ["string", "null"]},
                    },
                    "required": [
                        "finca",
                        "lote",
                        "tipo_labor",
                        "monitoras",
                        "lote_finalizado",
                        "plagas_observadas",
                        "nota",
                        "es_alerta",
                        "tipo_alerta",
                        "prioridad",
                    ],
                },
            },
        },
        "required": ["reportes"],
    },
}

_CAMPOS_TEXTO = ("finca", "lote", "tipo_labor", "nota", "tipo_alerta", "prioridad")


def _normalizar(item: dict) -> dict:
    for campo in _CAMPOS_TEXTO:
        valor = item.get(campo)
        if isinstance(valor, str) and valor.strip().lower() in PLACEHOLDERS_INVALIDOS:
            item[campo] = None

    lote = item.get("lote")
    if isinstance(lote, str):
        item["lote"] = lote.lstrip("#").strip() or None

    return item


def _extraccion_simulada(texto: str) -> dict:
    return {
        "finca": None,
        "lote": None,
        "tipo_labor": None,
        "monitoras": None,
        "lote_finalizado": None,
        "plagas_observadas": [],
        "nota": texto,
        "es_alerta": False,
        "tipo_alerta": None,
        "prioridad": None,
    }


def extraer_reportes_monitoreo(texto: str) -> list[dict]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return [_extraccion_simulada(texto)]

    respuesta = get_client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}],
        tools=[REPORTE_MONITOREO_TOOL],
        tool_choice={"type": "tool", "name": "extraer_reportes_monitoreo"},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            reportes = bloque.input.get("reportes") or []
            if not reportes:
                return [_extraccion_simulada(texto)]
            return [_normalizar(r) for r in reportes]
    raise ValueError("Claude no devolvio una extraccion estructurada")
