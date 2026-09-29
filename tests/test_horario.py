"""El dia es el dia de la finca, no el del servidor.

fecha_hora se guarda en UTC. Comparar contra "2026-09-22T00:00:00" pelado
compara contra medianoche UTC, que en Colombia son las 19:00 del dia anterior:
el dia consultado quedaba corrido cinco horas.

Con la jornada real —7:00 a 16:30— eso todavia no mordia, porque todo cae
dentro del mismo dia UTC. Muerde al desplegar: un servidor en la nube corre en
UTC, y el resumen programado a las 17:00 saldria a las 12:00 de Colombia, a
media jornada.

No llama a la base ni al modelo. Correr:  python tests/test_horario.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.horario import (  # noqa: E402
    JORNADA_FIN,
    JORNADA_INICIO,
    ZONA,
    cuando_legible,
    en_silencio,
    fecha_de,
    limites_utc,
)

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


# Colombia es UTC-5 todo el año: no tiene horario de verano.
desde, hasta = limites_utc("2026-09-22")
revisar("el dia empieza a las 05:00 UTC", desde, "2026-09-22T05:00:00+00:00")
revisar("y termina a las 05:00 UTC del siguiente", hasta, "2026-09-23T05:00:00+00:00")


def dentro(iso_utc: str) -> bool:
    """Si ese instante UTC cae en el dia 2026-09-22 de las fincas."""
    return desde <= iso_utc < hasta


# Un dia de trabajo real, de 7:00 a 16:30 hora Colombia
inicio_jornada = datetime(2026, 9, 22, 7, 0, tzinfo=ZONA).astimezone(timezone.utc).isoformat()
fin_jornada = datetime(2026, 9, 22, 16, 30, tzinfo=ZONA).astimezone(timezone.utc).isoformat()
resumen = datetime(2026, 9, 22, 17, 0, tzinfo=ZONA).astimezone(timezone.utc).isoformat()

revisar("un reporte de las 7:00 cuenta en su dia", dentro(inicio_jornada), True)
revisar("uno de las 16:30 tambien", dentro(fin_jornada), True)
revisar("el resumen de las 17:00 cae en el mismo dia", dentro(resumen), True)

# Los bordes: aqui es donde fallaba la version anterior
antes = datetime(2026, 9, 21, 23, 59, tzinfo=ZONA).astimezone(timezone.utc).isoformat()
justo = datetime(2026, 9, 22, 0, 0, tzinfo=ZONA).astimezone(timezone.utc).isoformat()
tarde = datetime(2026, 9, 22, 19, 30, tzinfo=ZONA).astimezone(timezone.utc).isoformat()
manana = datetime(2026, 9, 23, 0, 0, tzinfo=ZONA).astimezone(timezone.utc).isoformat()

revisar("las 23:59 del dia anterior NO cuentan", dentro(antes), False)
revisar("la medianoche del dia si", dentro(justo), True)
revisar("un reporte de las 19:30 sigue siendo de ese dia", dentro(tarde), True)
revisar("la medianoche siguiente ya no", dentro(manana), False)

# La ventana vieja, para dejar constancia de que estaba corrida
vieja_desde, vieja_hasta = "2026-09-22T00:00:00", "2026-09-22T23:59:59"
revisar(
    "con la ventana vieja, un reporte de las 19:30 se perdia del dia",
    vieja_desde <= tarde <= vieja_hasta,
    False,
)

revisar("la jornada arranca a las 7:00", JORNADA_INICIO.strftime("%H:%M"), "07:00")
revisar("y cierra a las 16:30", JORNADA_FIN.strftime("%H:%M"), "16:30")

# La noche, en que las alertas esperan. Los bordes y la medianoche.
for hora, minuto, de_noche in (
    (19, 59, False),
    (20, 0, True),
    (23, 59, True),
    (0, 0, True),
    (1, 55, True),   # la hora a la que llego la respuesta del 29 de septiembre
    (5, 59, True),
    (6, 0, False),
    (12, 0, False),
    (18, 0, False),  # el resumen diario
    (18, 30, False),  # el semanal
):
    revisar(
        f"a las {hora:02d}:{minuto:02d} {'es' if de_noche else 'no es'} de noche",
        en_silencio(datetime(2026, 9, 29, hora, minute=minuto, tzinfo=ZONA)),
        de_noche,
    )

# El servidor vive en UTC: la noche es la de las fincas, no la suya.
revisar("las 06:55 UTC son la 1:55 en Colombia: de noche",
        en_silencio(datetime(2026, 9, 29, 6, 55, tzinfo=timezone.utc)), True)
revisar("las 01:00 UTC son las 20:00 del dia anterior: de noche",
        en_silencio(datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc)), True)
revisar("las 14:00 UTC son las 9:00: de dia",
        en_silencio(datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)), False)

revisar("la hora de un mensaje se dice en la de las fincas",
        cuando_legible(datetime(2026, 9, 24, 0, 40, 22, tzinfo=timezone.utc)),
        "el 23 de septiembre a las 19:40")
revisar("y se lee igual desde el texto que devuelve la base",
        cuando_legible("2026-09-24T00:40:22+00:00"), "el 23 de septiembre a las 19:40")
revisar("el dia de un mensaje es el de las fincas",
        fecha_de(datetime(2026, 9, 24, 0, 40, tzinfo=timezone.utc)), "2026-09-23")


def main() -> int:
    fallos = 0
    for descripcion, obtenido, esperado in CASOS:
        if obtenido != esperado:
            fallos += 1
            print(f"  FALLA: {descripcion} -> {obtenido!r}, se esperaba {esperado!r}")
        else:
            print(f"  ok: {descripcion}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
