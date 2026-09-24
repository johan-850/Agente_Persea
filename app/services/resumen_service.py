from collections import Counter

from app.db.supabase_client import get_client
from app.horario import hoy, limites_utc
from app.services import meta_whatsapp_service as whatsapp_service
from app.services.alertas_monitoreo_service import hallazgos_que_alertan


def _monitoreos_del_dia(fecha: str) -> list[dict]:
    desde, hasta = limites_utc(fecha)
    return (
        get_client()
        .table("monitoreos")
        .select("*")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .order("finca")
        .order("lote")
        .execute()
        .data
    )


def _fotos_del_dia(fecha: str) -> list[dict]:
    desde, hasta = limites_utc(fecha)
    return (
        get_client()
        .table("fotos")
        .select("id, monitoreo_id, es_alerta, plagas_sugeridas")
        .gte("fecha_hora", desde)
        .lt("fecha_hora", hasta)
        .execute()
        .data
    )


def _fotos_por_reporte(fotos: list[dict]) -> dict:
    """Cuantas fotos y cuantas con dano llegaron por cada reporte.

    Del lote solo se avisa una vez aunque lleguen quince fotos con dano, para
    no enterrar al administrador. Pero entonces el numero tiene que aparecer
    en algun lado: un lote con 13 de 31 fotos mostrando dano compatible con
    cuarentenaria no es lo mismo que uno con una sola.
    """
    resumen: dict = {}
    for foto in fotos:
        entrada = resumen.setdefault(
            foto.get("monitoreo_id"), {"total": 0, "con_dano": 0, "candidatas": Counter()}
        )
        entrada["total"] += 1
        if foto.get("es_alerta"):
            entrada["con_dano"] += 1
            # Se cuenta en cuantas fotos aparece cada una, no se juntan en un
            # conjunto: lo que dice algo es que se repita, no que aparezca.
            for candidata in set(str(c) for c in foto.get("plagas_sugeridas") or []):
                entrada["candidatas"][candidata] += 1
    return resumen


def _resumir_candidatas(conteo: Counter, con_dano: int) -> str:
    """Las candidatas que valen la pena nombrar.

    Cada foto propone las suyas por separado. Juntandolas todas, un lote con
    cinco fotos dañadas terminaba listando diez especies —practicamente el
    catalogo cuarentenario entero— y eso no dice nada: quien lo lee aprende a
    saltarselo.

    Lo que aporta señal es la repeticion. Si tres de cinco fotos apuntan a
    Heilipus, eso es un indicio; una sola foto que menciona Saissetia entre
    otras nueve es ruido. Asi que se nombran las que se repiten, con en cuantas
    fotos salieron; y si ninguna se repite, unas pocas sin presumir de nada.
    """
    if not conteo:
        return ""

    repetidas = [(c, n) for c, n in conteo.most_common() if n >= 2]
    if repetidas:
        partes = [f"{c} ({n} de {con_dano})" for c, n in repetidas[:3]]
        return "sobre todo " + ", ".join(partes)

    return "posibles: " + ", ".join(c for c, _ in conteo.most_common(2))


def _texto_fotos(entrada: dict | None) -> str:
    if not entrada:
        return ""
    if not entrada["con_dano"]:
        return f" [{entrada['total']} foto(s)]"

    detalle = f" [{entrada['total']} foto(s), {entrada['con_dano']} con daño"
    candidatas = _resumir_candidatas(entrada["candidatas"], entrada["con_dano"])
    if candidatas:
        detalle += f"; {candidatas}"
    return detalle + "]"


def _motivo_corto(monitoreo: dict, maximo: int = 90) -> str:
    """Que disparo la alerta, dicho con el hallazgo y no con la etiqueta.

    tipo_alerta lo redacta el modelo y sale distinto cada vez ("plaga
    cuarentenaria", "Plagas cuarentenarias detectadas", "plagas_cuarentenaria").
    El hallazgo en cambio dice la especie y el estado del foco, que es lo que
    el administrador necesita para decidir a donde ir.
    """
    criticos = hallazgos_que_alertan(monitoreo.get("plagas_observadas"))
    motivo = "; ".join(str(c) for c in criticos) or (monitoreo.get("tipo_alerta") or "alerta")
    if len(motivo) > maximo:
        motivo = motivo[: maximo - 3].rstrip() + "..."
    return motivo


def _formatear_resumen(fecha: str, monitoreos: list[dict], fotos: list[dict] | None = None) -> str:
    if not monitoreos:
        return f"📋 Resumen de monitoreo del día {fecha}\nNo se recibieron reportes."

    por_foto = _fotos_por_reporte(fotos or [])
    # "reportes de lote" y no "lotes": un mismo lote puede aparecer dos veces
    # en el dia si se le hizo monitoreo general y despues bordeo.
    lineas = [f"📋 Resumen de monitoreo del día {fecha} — {len(monitoreos)} reportes de lote"]

    # Las alertas arriba. Con 39 reportes, un 🚨 en la linea 27 no lo ve nadie.
    alertas = [item for item in monitoreos if item.get("es_alerta")]
    if alertas:
        lineas.append(f"\n🚨 *{len(alertas)} lote(s) requieren atención:*")
        for item in alertas:
            finca = item.get("finca") or "finca sin especificar"
            lote = item.get("lote") or "no indicado"
            lineas.append(f"  • {finca}, lote {lote} — {_motivo_corto(item)}")

    por_finca: dict[str, list[dict]] = {}
    for item in monitoreos:
        finca = item.get("finca") or "finca sin especificar"
        por_finca.setdefault(finca, []).append(item)

    lineas.append("\n*Detalle del día*")
    for finca, items in sorted(por_finca.items()):
        lineas.append(f"\n_{finca}_")
        for item in items:
            lote = item.get("lote") or "no indicado"
            estado = "✅ finalizado" if item.get("lote_finalizado") else "⏳ pendiente"
            marca_alerta = " 🚨" if item.get("es_alerta") else ""
            plagas = ", ".join(item.get("plagas_observadas") or []) or "sin hallazgos relevantes"
            lineas.append(
                f"  Lote {lote} ({estado}){marca_alerta}: {plagas}"
                f"{_texto_fotos(por_foto.get(item.get('id')))}"
            )

    sueltas = por_foto.get(None)
    if sueltas:
        lineas.append(f"\n📷 {sueltas['total']} foto(s) sin reporte asociado{_texto_fotos(sueltas)[1:]}")

    fotos_con_dano = sum(e["con_dano"] for e in por_foto.values())
    if alertas or fotos_con_dano:
        lineas.append(
            f"\n⚠️ {len(alertas)} alerta(s) por reporte y {fotos_con_dano} foto(s) con daño hoy."
        )

    return "\n".join(lineas)


def _formatear_detalle_plano(monitoreos: list[dict], fotos: list[dict] | None = None) -> str:
    """Version de una sola linea del resumen, para usarla como parametro de
    plantilla (WhatsApp no acepta saltos de linea en los parametros).

    El parametro se corta a 300 caracteres, asi que van primero los lotes que
    alertaron: son los que el administrador tiene que ver si o si.
    """
    if not monitoreos:
        return "sin reportes"

    por_foto = _fotos_por_reporte(fotos or [])

    def describir(item: dict) -> str:
        finca = item.get("finca") or "finca sin especificar"
        lote = item.get("lote") or "sin lote"
        estado = "finalizado" if item.get("lote_finalizado") else "pendiente"
        plagas = ", ".join(item.get("plagas_observadas") or []) or "sin hallazgos"
        entrada = por_foto.get(item.get("id"))
        fotos_txt = ""
        if entrada and entrada["con_dano"]:
            fotos_txt = f" ({entrada['con_dano']}/{entrada['total']} fotos con daño)"
        return f"{finca} lote {lote} ({estado}): {plagas}{fotos_txt}"

    con_alerta = [m for m in monitoreos if m.get("es_alerta")]
    resto = [m for m in monitoreos if not m.get("es_alerta")]

    return "; ".join(describir(m) for m in [*con_alerta, *resto])


def _lotes_que_atender(monitoreos: list[dict]) -> str:
    """Los lotes con alerta y que la disparo. Uno por lote, lo mas corto posible."""
    alertas = [m for m in monitoreos if m.get("es_alerta")]
    if not alertas:
        return "ninguno"

    partes = []
    for item in alertas:
        finca = item.get("finca") or "finca sin especificar"
        lote = item.get("lote") or "no indicado"
        partes.append(f"{finca} lote {lote} - {_motivo_corto(item, maximo=55)}")
    return " | ".join(partes)


def _cobertura(monitoreos: list[dict], fotos: list[dict] | None = None) -> str:
    """Cuanto se vio en cada finca. Va en su propio hueco de la plantilla."""
    por_finca: dict[str, set] = {}
    for item in monitoreos:
        finca = item.get("finca") or "finca sin especificar"
        por_finca.setdefault(finca, set()).add(item.get("lote") or "?")

    partes = [f"{finca} {len(lotes)} lote(s)" for finca, lotes in sorted(por_finca.items())]
    con_dano = sum(1 for f in (fotos or []) if f.get("es_alerta"))
    if fotos:
        partes.append(f"{len(fotos)} foto(s), {con_dano} con daño")
    return ", ".join(partes) or "sin reportes"


def enviar_resumen_diario(fecha: str | None = None) -> str:
    fecha = fecha or hoy()
    monitoreos = _monitoreos_del_dia(fecha)
    fotos = _fotos_del_dia(fecha)
    texto = _formatear_resumen(fecha, monitoreos, fotos)
    alertas = [item for item in monitoreos if item.get("es_alerta")]

    comunes = [fecha, str(len(monitoreos)), str(len(alertas))]

    whatsapp_service.enviar_plantilla_a_administradores(
        whatsapp_service.PLANTILLAS_RESUMEN,
        [
            # v2: cada cosa en su hueco, con el cuerpo de la plantilla poniendo
            # los saltos de linea que un parametro no puede llevar.
            comunes + [_lotes_que_atender(monitoreos), _cobertura(monitoreos, fotos)],
            # v1: todo en un solo hueco, por si la v2 aun no esta aprobada.
            comunes + [_formatear_detalle_plano(monitoreos, fotos)],
        ],
        respaldo=texto,
        tipo="resumen_diario",
        referencia=fecha,
    )
    return texto
