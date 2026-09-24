"""Las migraciones tienen que reproducir la base que esta funcionando.

Es facil aplicar un ALTER a mano en el SQL Editor para desatascar algo y
olvidarse de llevarlo al repo. Cuando eso pasa, una instalacion nueva sale
distinta de la que funciona y falla en cosas raras: una columna que no existe,
un insert que revienta en produccion y no en pruebas.

Esta prueba compara las columnas declaradas en supabase/migraciones con las que
Supabase publica en su OpenAPI. Lee la base, no la modifica.

Correr:  python tests/test_migraciones.py
"""

import json
import os
import re
import sys
import urllib.request

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, RAIZ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(RAIZ, ".env"))

MIGRACIONES = os.path.join(RAIZ, "supabase", "migraciones")

# Se retiro con el flujo de reportes de labores: ninguna migracion la crea, y
# en las bases viejas sigue ahi con los datos de aquellas pruebas.
TABLAS_RETIRADAS = {"reportes"}


def columnas_declaradas() -> dict[str, set]:
    """Las columnas que crean las migraciones, por tabla."""
    declaradas: dict[str, set] = {}

    for archivo in sorted(os.listdir(MIGRACIONES)):
        if not archivo.endswith(".sql") or archivo.startswith("opcional"):
            continue

        sql = open(os.path.join(MIGRACIONES, archivo), encoding="utf-8").read()
        # Fuera los comentarios, que llevan nombres de columna en la prosa.
        limpio = "\n".join(linea.split("--")[0] for linea in sql.splitlines())

        for bloque in re.finditer(
            r"create table if not exists (\w+)\s*\((.*?)\n\);", limpio, re.S
        ):
            tabla, cuerpo = bloque.group(1), bloque.group(2)
            for linea in cuerpo.splitlines():
                linea = linea.strip().rstrip(",")
                if not linea:
                    continue
                nombre = linea.split()[0]
                if nombre.lower() in ("primary", "unique", "foreign", "constraint", "check"):
                    continue
                declaradas.setdefault(tabla, set()).add(nombre)

        for bloque in re.finditer(r"alter table (\w+)(.*?);", limpio, re.S):
            tabla, cuerpo = bloque.group(1), bloque.group(2)
            for col in re.finditer(r"add column if not exists (\w+)", cuerpo):
                declaradas.setdefault(tabla, set()).add(col.group(1))

    return declaradas


def columnas_reales() -> dict[str, set]:
    """Las columnas que hay en la base, segun el OpenAPI de PostgREST."""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    clave = os.environ["SUPABASE_KEY"]
    peticion = urllib.request.Request(
        f"{url}/rest/v1/",
        headers={
            "apikey": clave,
            "Authorization": f"Bearer {clave}",
            "Accept": "application/openapi+json",
        },
    )
    with urllib.request.urlopen(peticion, timeout=40) as respuesta:
        spec = json.loads(respuesta.read())

    defs = spec.get("definitions") or spec.get("components", {}).get("schemas", {})
    return {
        tabla: set(d.get("properties", {}))
        for tabla, d in defs.items()
        if tabla not in TABLAS_RETIRADAS
    }


def main() -> int:
    if not os.environ.get("SUPABASE_URL"):
        print("Falta SUPABASE_URL: esta prueba necesita leer la base.")
        return 1

    declaradas = columnas_declaradas()
    reales = columnas_reales()
    fallos = 0

    print("TABLAS")
    faltan_en_migraciones = set(reales) - set(declaradas)
    sobran_en_migraciones = set(declaradas) - set(reales)

    if faltan_en_migraciones:
        fallos += 1
        print(f"  FALLA: la base tiene tablas que ninguna migracion crea: "
              f"{sorted(faltan_en_migraciones)}")
    if sobran_en_migraciones:
        fallos += 1
        print(f"  FALLA: las migraciones crean tablas que no estan en la base: "
              f"{sorted(sobran_en_migraciones)}")
    if not faltan_en_migraciones and not sobran_en_migraciones:
        print(f"  ok: las mismas {len(reales)} tablas -> {sorted(reales)}")

    print("\nCOLUMNAS")
    for tabla in sorted(set(declaradas) & set(reales)):
        faltan = reales[tabla] - declaradas[tabla]
        sobran = declaradas[tabla] - reales[tabla]
        if faltan:
            fallos += 1
            print(f"  FALLA: {tabla} tiene en la base y no en las migraciones: {sorted(faltan)}")
        if sobran:
            fallos += 1
            print(f"  FALLA: {tabla} tiene en las migraciones y no en la base: {sorted(sobran)}")
        if not faltan and not sobran:
            print(f"  ok: {tabla} ({len(reales[tabla])} columnas)")

    print()
    if fallos:
        print(f"{fallos} diferencia(s): una instalacion nueva no saldria igual a la actual.")
        return 1
    print("Las migraciones reproducen exactamente el esquema en uso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
