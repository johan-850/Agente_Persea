"""La jornada de campo, en la zona horaria de las fincas.

El servidor puede estar en cualquier parte, y en un despliegue en la nube casi
siempre esta en UTC. La jornada de las monitoras, en cambio, es siempre la de
Colombia: de 7:00 a 16:30, y el resumen al cierre.

Dos cosas dependian de la hora del servidor y se rompen en cuanto el servidor
deja de estar en Colombia:

- El resumen diario se programa a la hora local del proceso. En un servidor
  UTC, HORA_RESUMEN_DIARIO=17 dispara a las 12:00 de Colombia, a media
  jornada, con la mitad de los reportes sin llegar.
- El dia que se consulta se armaba comparando contra "2026-09-22T00:00:00"
  pelado. fecha_hora se guarda en UTC, asi que eso es medianoche UTC: las
  19:00 del dia anterior en Colombia. El dia consultado quedaba corrido cinco
  horas.

Aqui el dia es el dia de la finca, y de ahi se derivan los limites en UTC para
consultar.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Bogota")

# Jornada de campo. No se usa para filtrar —un reporte que llega tarde se
# guarda igual— pero documenta contra que se diseño el horario del resumen.
JORNADA_INICIO = time(7, 0)
JORNADA_FIN = time(16, 30)

# La noche, en que el agente no le escribe a nadie por su cuenta. El 29 de
# septiembre, a la 1:55 de la mañana, le llego a un administrador la respuesta
# a una pregunta de seis dias antes. De noche solo se le contesta a quien
# acaba de escribir, que por eso mismo esta despierto; las alertas esperan a
# que termine (ver meta_whatsapp_service.despachar_aplazados).
SILENCIO_INICIO = time(20, 0)
SILENCIO_FIN = time(6, 0)


def ahora() -> datetime:
    """La hora en las fincas, no la del servidor."""
    return datetime.now(ZONA)


def es_hora_de_silencio(hora: time) -> bool:
    """Si esa hora del dia cae en la noche. El tramo cruza la medianoche."""
    return hora >= SILENCIO_INICIO or hora < SILENCIO_FIN


def en_silencio(momento: datetime | None = None) -> bool:
    """Si ese instante —por defecto, ahora— es de noche en las fincas."""
    return es_hora_de_silencio((momento or ahora()).astimezone(ZONA).time())


def fecha_de(momento: datetime) -> str:
    """El dia de las fincas en que cae ese instante, en formato ISO."""
    return momento.astimezone(ZONA).date().isoformat()


def hoy() -> str:
    """El dia de hoy en las fincas, en formato ISO."""
    return ahora().date().isoformat()


def limites_utc(fecha: str) -> tuple[str, str]:
    """(inicio, fin) de ese dia EN COLOMBIA, expresados en UTC.

    El fin es exclusivo: es la medianoche del dia siguiente, para que un
    registro justo en el limite no se cuente en los dos dias.
    """
    dia = date.fromisoformat(fecha)
    inicio = datetime.combine(dia, time.min, tzinfo=ZONA)
    fin = inicio + timedelta(days=1)
    return (
        inicio.astimezone(timezone.utc).isoformat(),
        fin.astimezone(timezone.utc).isoformat(),
    )


MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def semana_de(fecha: str) -> tuple[str, str]:
    """(lunes, viernes) de la semana laboral a la que pertenece esa fecha."""
    dia = date.fromisoformat(fecha)
    lunes = dia - timedelta(days=dia.weekday())
    return lunes.isoformat(), (lunes + timedelta(days=4)).isoformat()


def limites_semana_utc(fecha: str) -> tuple[str, str]:
    """(inicio, fin) de la semana laboral de esa fecha, en UTC.

    De lunes 00:00 a sabado 00:00 hora Colombia. El sabado es el limite
    exclusivo: si alguien reporta un sabado por la manana entra en la semana
    que acaba de terminar, que es donde lo buscaria un administrador.
    """
    lunes, _ = semana_de(fecha)
    inicio = datetime.combine(date.fromisoformat(lunes), time.min, tzinfo=ZONA)
    fin = inicio + timedelta(days=5)
    return (
        inicio.astimezone(timezone.utc).isoformat(),
        fin.astimezone(timezone.utc).isoformat(),
    )


def rango_legible(desde: str, hasta: str) -> str:
    """'22 al 26 de septiembre', o con los dos meses si la semana los cruza."""
    a = date.fromisoformat(desde)
    b = date.fromisoformat(hasta)
    if a.month == b.month:
        return f"{a.day} al {b.day} de {MESES[a.month - 1]}"
    return f"{a.day} de {MESES[a.month - 1]} al {b.day} de {MESES[b.month - 1]}"


def cuando_legible(momento: datetime | str) -> str:
    """'el 23 de septiembre a las 19:40', en hora de las fincas.

    Acepta el datetime o el texto ISO con que la base devuelve fecha_hora.
    """
    if isinstance(momento, str):
        momento = datetime.fromisoformat(momento)
    local = momento.astimezone(ZONA)
    return f"el {local.day} de {MESES[local.month - 1]} a las {local:%H:%M}"
