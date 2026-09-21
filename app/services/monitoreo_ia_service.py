import logging
import os
import re
import unicodedata

from app.services.ia_service import get_client

logger = logging.getLogger("monitoreo_ia")

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

# Las cuatro fincas de Agricola Persea, con las formas en que aparecen escritas
# en los reportes. Sin normalizar, una sola finca entraba como "Rivera",
# "rivera", "La Rivera", "la rivera" y "Ribera": no se puede agrupar por finca,
# filtrar su historial ni contar cuantos lotes lleva el dia.
FINCAS = {
    "la linda": ("la linda", "linda"),
    "alfa": ("alfa", "alpha"),
    "buena vista": ("buena vista", "buenavista", "buena-vista"),
    "rivera": ("rivera", "la rivera", "ribera", "la ribera"),
}

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

PRIMERO decide si el mensaje es realmente un reporte de campo y ponlo en
"es_reporte_de_campo". Por el mismo chat pasa mucha conversacion que NO es un
reporte: saludos, preguntas, confirmaciones ("ya voy", "listo"), coordinacion
del dia e instrucciones de los administradores al equipo.

Un reporte de campo es alguien contando lo que OBSERVO en el lote. Hablar de
una plaga no es observarla: "dejemos por ahora el stenoma que veamos en las
ramas, lo principal es no enviar fruta con stenoma al acopio" es una
instruccion, no un hallazgo, y va con es_reporte_de_campo=false.

Cuando es_reporte_de_campo sea false, devuelve "reportes" vacio y no extraigas
nada mas. En la duda, si el mensaje no describe ninguna observacion concreta en
un lote, marcalo como false.

IMPORTANTE: un solo mensaje puede reportar sobre VARIOS lotes distintos (ej.
"se finaliza lote #13... se pasa a realizar esta misma labor al lote #14...").
Debes devolver un elemento en "reportes" por CADA lote mencionado.

Para cada lote extrae:
- finca: una de estas cuatro, en minuscula y tal como aparecen aqui:
  {", ".join(FINCAS)}. Las monitoras las escriben de muchas formas
  ("La Rivera", "Ribera", "buenavista"): devuelve siempre la forma canonica.
  Si nombran una finca que no esta en la lista, escribela tal cual.
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
  Usa el catalogo de abajo para corregir la ESCRITURA de un nombre que ya
  corresponde a una entrada del catalogo ("pseudocercosphora" ->
  "pseudocercospora", "cefaleurus" -> "cephaleuros", "laury" -> "lauri"), y
  conserva siempre el descriptor de severidad que puso la monitora.
  NUNCA cambies una especie por otra. Si la monitora nombra algo que no esta
  en el catalogo —"heilipus leopardo", "tetraleurodes", "marceño"— dejalo tal
  como lo escribio; no lo sustituyas por la entrada mas parecida. Confundir
  Heilipus leopardo con Heilipus lauri manda al agronomo a buscar la plaga
  equivocada.
  Si un hallazgo es de una especie y otro de otra, van en elementos
  separados, cada uno con lo que el texto dice de ESA especie.
- nota: contexto adicional relevante que no encaje en los campos anteriores
  (interrupciones por clima, transiciones entre lotes, conteos especificos
  como numero de larvas encontradas, etc). Puede ser null.
- es_alerta: true SOLO por una de estas tres razones, y ninguna otra:
    (a) una de las ocho plagas CUARENTENARIAS del catalogo aparece en ESE lote,
    (b) el reporte marca un foco como "ACTIVO" en ESE lote,
    (c) hay un accidente o una persona herida.
  Una poblacion alta, una severidad 4 o mucho daño NO son alerta si la plaga
  no es cuarentenaria: son hallazgos rutinarios que van al resumen diario.
  Copturomimus perseae, acaro, mosca blanca, trips, monalonion, bruggmanniella
  y las enfermedades del catalogo NO disparan alerta por numerosos que sean.
  Si dudas, pon false: la alerta interrumpe a un administrador y de tanto
  interrumpir deja de leerlas.
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
            "es_reporte_de_campo": {
                "type": "boolean",
                "description": (
                    "true solo si el mensaje describe observaciones hechas en el lote. "
                    "false para saludos, preguntas, coordinacion e instrucciones, aunque "
                    "mencionen plagas."
                ),
            },
            "reportes": {
                "type": "array",
                "description": "Un elemento por cada lote distinto mencionado en el mensaje. Vacio si no es un reporte de campo.",
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
        "required": ["es_reporte_de_campo", "reportes"],
    },
}

_CAMPOS_TEXTO = ("finca", "lote", "tipo_labor", "nota", "tipo_alerta", "prioridad")


def _normalizar_finca(valor) -> str | None:
    """Lleva el nombre de la finca a una de las cuatro formas canonicas.

    Si no reconoce el nombre lo deja como vino: puede ser una finca nueva o un
    predio arrendado, y perder el dato seria peor que tenerlo sin normalizar.
    """
    if not isinstance(valor, str) or not valor.strip():
        return None

    plano = unicodedata.normalize("NFD", valor.strip().lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    plano = re.sub(r"\s+", " ", plano.replace("finca", "").strip())

    for canonica, variantes in FINCAS.items():
        if plano in variantes:
            return canonica

    logger.info("Finca no reconocida, se guarda tal cual: %r", valor)
    return valor.strip()


def _normalizar(item: dict) -> dict:
    for campo in _CAMPOS_TEXTO:
        valor = item.get(campo)
        if isinstance(valor, str) and valor.strip().lower() in PLACEHOLDERS_INVALIDOS:
            item[campo] = None

    item["finca"] = _normalizar_finca(item.get("finca"))

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
    """Devuelve un reporte por lote, o lista vacia si el mensaje no es un
    reporte de campo.

    Por el chat pasa mucha conversacion suelta. Guardarla como monitoreo no
    solo ensucia el historial y el resumen diario: las reglas duras corren
    sobre el texto, asi que un administrador escribiendo "dejemos por ahora el
    stenoma de las ramas" disparaba una alerta de plaga cuarentenaria.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return [_extraccion_simulada(texto)]

    respuesta = get_client().messages.create(
        model=MODEL,
        max_tokens=2048,
        # Extraer campos de un reporte es determinista: el mismo texto debe
        # dar siempre los mismos datos.
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}],
        tools=[REPORTE_MONITOREO_TOOL],
        tool_choice={"type": "tool", "name": "extraer_reportes_monitoreo"},
    )
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            if not bloque.input.get("es_reporte_de_campo"):
                logger.info("Mensaje descartado, no es un reporte: %r", texto[:120])
                return []
            reportes = bloque.input.get("reportes") or []
            if not reportes:
                # Dijo que si es reporte pero no extrajo lotes. Se guarda el
                # texto crudo antes que perder un hallazgo.
                return [_extraccion_simulada(texto)]
            return [_normalizar(r) for r in reportes]
    raise ValueError("Claude no devolvio una extraccion estructurada")
