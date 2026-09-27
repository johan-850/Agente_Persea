"""Cuando disparan los dos resumenes.

Dos cosas se habian desviado sin que nada avisara:

- La hora. El codigo trae 18 por defecto y el README dice 18, pero el .env
  tenia 17 de antes del cambio y el .env gana. Los resumenes salieron a las
  17:00 durante dias. Un test no puede leer el .env —no se versiona— pero si
  puede fijar que la funcion que programa respeta la hora que se le pasa.
- El dia. El diario no filtraba dia de la semana, asi que el domingo mandaba
  un "No se recibieron reportes". Ese mensaje no informa de nada y enseña a
  no abrir el de las 18:00, que es el que si hay que leer.

No levanta el servidor ni llama a la base. Correr:
    python tests/test_programacion.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

from app.horario import ZONA  # noqa: E402
from app.main import programar  # noqa: E402

CASOS = []

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

# Una semana conocida: lunes 21 a domingo 27 de septiembre de 2026.
SEMANA = {DIAS[d]: datetime(2026, 9, 21 + d, 12, 0, tzinfo=ZONA) for d in range(7)}


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def disparos(hora=18):
    """Los dos triggers, programados como en el arranque real."""
    planificador = BackgroundScheduler()
    programar(planificador, hora)
    return (
        planificador.get_job("resumen_diario").trigger,
        planificador.get_job("resumen_semanal").trigger,
    )


diario, semanal = disparos()


def siguiente(trigger, dia):
    """Cuando dispara por primera vez si lo miramos ese dia al mediodia."""
    return trigger.get_next_fire_time(None, SEMANA[dia])


print("EL DIARIO SALE AL CIERRE DE LA JORNADA")
revisar("a las 18:00, no a las 17:00", siguiente(diario, "lunes").hour, 18)
revisar("en punto", siguiente(diario, "lunes").minute, 0)
revisar("en hora de las fincas, no del servidor", str(diario.timezone), "America/Bogota")

print("\nDE LUNES A SABADO")
for dia in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado"):
    # Si dispara el mismo dia que lo miramos, ese dia tiene resumen.
    revisar(f"el {dia} hay resumen", siguiente(diario, dia).date(), SEMANA[dia].date())

print("\nEL DOMINGO NO")
domingo = siguiente(diario, "domingo")
revisar("el domingo no dispara", domingo.date() != SEMANA["domingo"].date(), True)
revisar("lo siguiente es el lunes", DIAS[domingo.weekday()], "lunes")
revisar("y es el lunes que viene, no el que paso", domingo.day, 28)

print("\nEL SEMANAL SOLO EL VIERNES")
revisar("el viernes dispara ese mismo dia",
        siguiente(semanal, "viernes").date(), SEMANA["viernes"].date())
revisar("es viernes", DIAS[siguiente(semanal, "lunes").weekday()], "viernes")
for dia in ("lunes", "martes", "miercoles", "jueves"):
    revisar(f"visto el {dia}, espera al viernes",
            siguiente(semanal, dia).date(), SEMANA["viernes"].date())
revisar("el sabado ya apunta a la semana siguiente",
        siguiente(semanal, "sabado").date() > SEMANA["sabado"].date(), True)

print("\nEL VIERNES NO SE PISAN")
revisar("el semanal sale despues del diario",
        siguiente(semanal, "viernes") > siguiente(diario, "viernes"), True)
revisar("media hora despues",
        (siguiente(semanal, "viernes") - siguiente(diario, "viernes")).seconds // 60, 30)

print("\nLA HORA ES LA QUE SE LE PASE")
otro_diario, otro_semanal = disparos(hora=6)
revisar("el diario obedece", siguiente(otro_diario, "lunes").hour, 6)
revisar("y el semanal va con el", siguiente(otro_semanal, "viernes").hour, 6)
revisar("conservando la media hora", siguiente(otro_semanal, "viernes").minute, 30)


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
