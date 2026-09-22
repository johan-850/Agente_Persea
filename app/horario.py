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


def ahora() -> datetime:
    """La hora en las fincas, no la del servidor."""
    return datetime.now(ZONA)


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
