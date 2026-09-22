"""Resumen de la semana laboral, que sale los viernes al cierre.

No es el resumen diario cinco veces. Un diario lista lote por lote lo que se
observo ese dia; con cincuenta reportes en la semana eso es ilegible y ademas
no responde lo que un administrador se pregunta el viernes:

  - en cuantos lotes aparecio cada cuarentenaria (dispersion)
  - que lotes siguen alertando dia tras dia (persistencia)
  - que tanto se cubrio, por finca

Esas tres cosas solo se ven mirando la semana entera, que es justamente lo que
el diario no puede hacer.
"""

import logging
from collections import defaultdict
from datetime import datetime

from app.db.supabase_client import get_client
from app.horario import (
    ZONA,
    hoy,
    limites_semana_utc,
    rango_legible,
    semana_de,
)
from app.services import meta_whatsapp_service as whatsapp_service
from app.services.alertas_monitoreo_service import (
    grupo_cuarentenaria,
    hallazgos_que_alertan,
)

logger = logging.getLogger("resumen_semanal")


def _dia_local(fecha_hora: str) -> str:
    """El dia en las fincas de un instante guardado en UTC."""
    return datetime.fromisoformat(str(fecha_hora)).astimezone(ZONA).date().isoformat()


def _registros(desde: str, hasta: str) -> tuple[list[dict], list[dict]]:
    cli = get_client()
    monitoreos = (
        cli.table("monitoreos")
        .select("id, fecha_hora, finca, lote, es_alerta, plagas_observadas")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .order("fecha_hora")
        .execute()
        .data
    )
    fotos = (
        cli.table("fotos")
        .select("id, monitoreo_id, es_alerta")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .execute()
        .data
    )
    return monitoreos, fotos


def _ubicacion(monitoreo: dict) -> str:
    finca = monitoreo.get("finca") or "finca sin especificar"
    return f"{finca} {monitoreo.get('lote') or 'sin lote'}"


def _orden_natural(ubicacion: str) -> tuple:
    """Para que el lote 8 vaya antes que el 10 y no al reves.

    Ordenar como texto pone "alfa 10" delante de "alfa 8", que al leerlo
    parece un error de datos.
    """
    finca, _, lote = ubicacion.rpartition(" ")
    return (finca, 0, int(lote)) if lote.isdigit() else (finca, 1, lote)


def _cuarentenarias_de_la_semana(monitoreos: list[dict]) -> dict:
    """Por plaga: en que lotes aparecio y en cuales estaba ACTIVO."""
    grupos: dict[str, dict[str, bool]] = defaultdict(dict)
    for m in monitoreos:
        if not m.get("es_alerta"):
            continue
        for hallazgo in hallazgos_que_alertan(m.get("plagas_observadas")):
            grupo = grupo_cuarentenaria(hallazgo)
            if not grupo:
                continue
            donde = _ubicacion(m)
            activo = "activo" in str(hallazgo).lower()
            # Si en algun reporte de ese lote estaba activo, se conserva.
            grupos[grupo][donde] = grupos[grupo].get(donde, False) or activo
    return grupos


def _lotes_persistentes(monitoreos: list[dict]) -> list[tuple[str, int]]:
    """Lotes que alertaron en mas de un dia de la semana."""
    dias: dict[str, set] = defaultdict(set)
    for m in monitoreos:
        if m.get("es_alerta"):
            dias[_ubicacion(m)].add(_dia_local(m["fecha_hora"]))
    repetidos = [(donde, len(ds)) for donde, ds in dias.items() if len(ds) > 1]
    return sorted(repetidos, key=lambda x: -x[1])


def _por_finca(monitoreos: list[dict]) -> dict:
    resumen: dict[str, dict] = defaultdict(lambda: {"reportes": 0, "lotes": set(), "alertas": 0})
    for m in monitoreos:
        finca = m.get("finca") or "finca sin especificar"
        entrada = resumen[finca]
        entrada["reportes"] += 1
        if m.get("lote"):
            entrada["lotes"].add(m["lote"])
        entrada["alertas"] += bool(m.get("es_alerta"))
    return resumen


def formatear(desde: str, hasta: str, monitoreos: list[dict], fotos: list[dict]) -> str:
    periodo = rango_legible(desde, hasta)
    if not monitoreos:
        return f"📅 Resumen semanal — {periodo}\nNo se recibieron reportes esta semana."

    lotes = {_ubicacion(m) for m in monitoreos if m.get("lote")}
    lineas = [
        f"📅 *Resumen semanal — {periodo}*",
        f"\n{len(monitoreos)} reportes de lote, {len(lotes)} lotes distintos, "
        f"{len(_por_finca(monitoreos))} fincas.",
    ]

    cuarentenarias = _cuarentenarias_de_la_semana(monitoreos)
    if cuarentenarias:
        lineas.append("\n🚨 *Cuarentenarias de la semana*")
        for plaga, donde in sorted(cuarentenarias.items(), key=lambda x: -len(x[1])):
            sitios = [
                f"{d} (ACTIVO)" if donde[d] else d
                for d in sorted(donde, key=_orden_natural)
            ]
            lineas.append(f"  {plaga} — {len(donde)} lote(s)")
            lineas.append(f"     {', '.join(sitios)}")
    else:
        lineas.append("\n✅ Ninguna plaga cuarentenaria esta semana.")

    persistentes = _lotes_persistentes(monitoreos)
    if persistentes:
        lineas.append("\n🔁 *Lotes que alertaron más de un día*")
        for donde, dias in persistentes:
            lineas.append(f"  {donde} — {dias} días")

    con_dano = sum(1 for f in fotos if f.get("es_alerta"))
    if fotos:
        lineas.append(f"\n📷 {len(fotos)} fotos recibidas, {con_dano} con daño compatible.")

    lineas.append("\n*Por finca*")
    for finca, datos in sorted(_por_finca(monitoreos).items()):
        alerta = f", {datos['alertas']} con alerta" if datos["alertas"] else ""
        lineas.append(
            f"  {finca} — {datos['reportes']} reportes, {len(datos['lotes'])} lotes{alerta}"
        )

    return "\n".join(lineas)


def _detalle_plano(monitoreos: list[dict], fotos: list[dict]) -> str:
    """Version corta para el parametro de plantilla, que se corta en 300.

    Va primero la dispersion de las cuarentenarias: es lo unico que el
    administrador no puede deducir de los resumenes diarios que ya recibio.
    """
    cuarentenarias = _cuarentenarias_de_la_semana(monitoreos)
    partes = [
        f"{plaga} en {len(donde)} lote(s)"
        for plaga, donde in sorted(cuarentenarias.items(), key=lambda x: -len(x[1]))
    ]
    if not partes:
        partes.append("sin plagas cuarentenarias")

    lotes = {_ubicacion(m) for m in monitoreos if m.get("lote")}
    con_dano = sum(1 for f in fotos if f.get("es_alerta"))
    partes.append(f"{len(lotes)} lotes monitoreados, {con_dano} fotos con daño")
    return "; ".join(partes)


def enviar_resumen_semanal(fecha: str | None = None) -> str:
    """Manda el resumen de la semana laboral a la que pertenece esa fecha."""
    fecha = fecha or hoy()
    lunes, viernes = semana_de(fecha)
    desde, hasta = limites_semana_utc(fecha)

    monitoreos, fotos = _registros(desde, hasta)
    texto = formatear(lunes, viernes, monitoreos, fotos)
    alertas = [m for m in monitoreos if m.get("es_alerta")]

    logger.info(
        "Resumen semanal %s a %s: %d reportes, %d alertas, %d fotos",
        lunes, viernes, len(monitoreos), len(alertas), len(fotos),
    )

    whatsapp_service.enviar_plantilla_a_administradores(
        whatsapp_service.PLANTILLA_SEMANAL,
        [
            rango_legible(lunes, viernes),
            str(len(monitoreos)),
            str(len(alertas)),
            _detalle_plano(monitoreos, fotos),
        ],
        respaldo=texto,
        tipo="resumen_semanal",
        referencia=f"{lunes}/{viernes}",
    )
    return texto
