"""Comprueba que el agente distinga un reporte de campo de la conversacion.

Por el chat pasa de todo: saludos, preguntas, coordinacion del dia e
instrucciones de los administradores. Guardar eso como monitoreo ensucia el
historial y, peor, hace correr las reglas duras sobre el texto: un mensaje que
solo MENCIONA una plaga cuarentenaria disparaba alerta.

A diferencia de test_alertas_monitoreo.py, esta prueba llama al modelo y por
tanto consume API. Correr a proposito:

    python tests/test_clasificacion_mensajes.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.services.monitoreo_ia_service import extraer_reportes_monitoreo  # noqa: E402

# (descripcion, mensaje, se_espera_reporte)
CASOS = [
    (
        "Reporte de bordeo con hallazgos",
        "Buenas tardes, finca La Rivera, el día de hoy se inicia jornada continuando "
        "con el bordeo de la línea 1 a la 7, en el lote 18.\nDonde solo se observa una "
        "afectación por stenoma en rama hasta donde se monitorea.\nSe observan focos de "
        "ácaro bordo a monte, árboles cloróticos y desfoliados, caída de cuaje, daños "
        "por marceño en rama y fruta, chancro, bruggmaniella y *ramas que necesitan "
        "realce con fruta tocando el suelo*\nNo se finaliza lote\nHasta finalizar "
        "jornada, se contó con 1 monitora.",
        True,
    ),
    (
        "Reporte corto de monitoreo general",
        "Finca la linda, monitoreo lote #8, se observa mosca blanca y arboles "
        "cloroticos. Se finaliza lote. 1 monitora",
        True,
    ),
    (
        "Seguimiento de un foco: es una observacion de campo",
        "Buenos días. !\nFinca Rivera.\nPara reportar q se sigue encontrando individuos "
        "de monalonion en lote #14 en el mismo foco de ayer (3 ninfas y 1 adulto)",
        True,
    ),
    (
        "Instruccion del administrador: menciona stenoma pero nadie lo observo",
        "Valentina buenos días, gracias por comunicar su inquietud, lo que podemos "
        "hacer es que nos dediquemos solo a revisar fruta, dejemos por ahora el stenoma "
        "que veamos en las ramas, ya luego les haríamos manejo, pero lo principal es "
        "que evitemos en lo posible enviar fruta con stenoma al acopio",
        False,
    ),
    (
        "Saludo suelto",
        "Buenas tardes",
        False,
    ),
    (
        "Mensaje sin contenido",
        "f",
        False,
    ),
    (
        "Pregunta al agente",
        "me puedes mostrar el reporte real",
        False,
    ),
    (
        "Coordinacion del dia",
        "Listo, ya vamos saliendo para el lote, cualquier cosa les aviso",
        False,
    ),
]


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Falta ANTHROPIC_API_KEY: esta prueba necesita llamar al modelo.")
        return 1

    fallos = 0
    for descripcion, mensaje, espera_reporte in CASOS:
        reportes = extraer_reportes_monitoreo(mensaje)
        hubo_reporte = bool(reportes)
        if hubo_reporte != espera_reporte:
            fallos += 1
            print(f"  FALLA: {descripcion}")
            print(f"    esperado reporte={espera_reporte}, obtenido {hubo_reporte}")
            for r in reportes:
                print(f"      lote={r.get('lote')!r} plagas={r.get('plagas_observadas')}")
        else:
            estado = f"reporte ({len(reportes)} lote/s)" if hubo_reporte else "conversacion"
            print(f"  ok: {descripcion} -> {estado}")

    print()
    if fallos:
        print(f"{fallos} de {len(CASOS)} casos fallaron")
        return 1
    print(f"{len(CASOS)} casos OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
