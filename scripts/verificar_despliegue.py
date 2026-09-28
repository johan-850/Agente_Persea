"""Comprueba una configuracion de produccion, antes y despues de desplegar.

  python scripts/verificar_despliegue.py
  python scripts/verificar_despliegue.py --env .env.produccion --url https://<dominio>

Antes de desplegar prueba cada credencial contra su servicio: la base y su
esquema, el bucket de fotos, los administradores, el numero de WhatsApp y sus
plantillas, y el modelo. Asi los errores de copiado aparecen aqui y no a las
18:00, cuando el resumen no sale.

Con --url comprueba ademas el servidor desplegado: que responde, que tiene el
mismo token de verificacion que Meta va a usar, que exige la firma de Meta y
que la API no esta abierta.

Nunca imprime un valor de configuracion: solo nombres y resultados.
"""

import argparse
import os
import secrets
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))

import httpx  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from app import config  # noqa: E402

GRAPH = "https://graph.facebook.com/v21.0"

resultados: list[tuple[str, str, str]] = []


def anotar(estado: str, nombre: str, detalle: str = "") -> None:
    resultados.append((estado, nombre, detalle))
    marca = {"ok": "  ok   ", "aviso": "  aviso", "falla": "  FALLA", "salta": "  --   "}[estado]
    print(f"{marca} {nombre}{': ' + detalle if detalle else ''}")


def cargar(archivo: str) -> None:
    """Deja en el entorno exactamente lo que dice el archivo.

    Lo que no este en el archivo se quita del entorno: si no, un valor
    heredado de la sesion podria hacer pasar la prueba con credenciales que
    no son las de produccion.
    """
    if not os.path.exists(archivo):
        print(f"No existe {archivo}. Copia .env.example con ese nombre y llenalo.")
        raise SystemExit(1)

    valores = dotenv_values(archivo)
    con_bom = [k for k in valores if k and k.startswith("﻿")]
    if con_bom:
        # Ya paso una vez: PowerShell guarda UTF-8 con BOM y la primera
        # variable queda con un caracter invisible delante del nombre.
        anotar("aviso", "archivo", "tiene BOM al inicio; se ignora, pero guardalo como UTF-8 sin BOM")
        valores = {k.lstrip("﻿"): v for k, v in valores.items()}

    for variable, _ in config._VARIABLES.values():
        os.environ.pop(variable, None)
    for clave, valor in valores.items():
        if clave and valor is not None:
            os.environ[clave] = valor


def enmascarar(numero: str) -> str:
    digitos = "".join(c for c in str(numero) if c.isdigit())
    return f"...{digitos[-4:]}" if len(digitos) >= 4 else "..."


def revisar_configuracion() -> set[str]:
    revision = config.revisar()
    if revision.faltantes:
        anotar("falla", "configuracion", "falta " + ", ".join(revision.faltantes))
    else:
        anotar("ok", "configuracion", "estan todas las obligatorias")
    for aviso in revision.avisos:
        anotar("aviso", "configuracion", aviso)
    return {f.split(":")[0] for f in revision.faltantes}


def revisar_base() -> None:
    from test_migraciones import columnas_declaradas, columnas_reales

    from app.db.supabase_client import get_client

    declaradas = columnas_declaradas()
    reales = columnas_reales()
    faltan = []
    for tabla, columnas in sorted(declaradas.items()):
        if tabla not in reales:
            faltan.append(f"tabla {tabla}")
        elif columnas - reales[tabla]:
            faltan.append(f"{tabla}: {', '.join(sorted(columnas - reales[tabla]))}")
    if faltan:
        anotar("falla", "esquema", "correr las migraciones que faltan -> " + "; ".join(faltan))
    else:
        anotar("ok", "esquema", f"las {len(declaradas)} tablas de las migraciones, completas")

    try:
        bucket = get_client().storage.get_bucket(config.BUCKET_FOTOS)
        if getattr(bucket, "public", False):
            anotar("falla", "bucket", f"{config.BUCKET_FOTOS} es PUBLICO: las fotos quedarian a la vista")
        else:
            anotar("ok", "bucket", f"{config.BUCKET_FOTOS}, privado")
    except Exception as error:
        anotar("falla", "bucket", f"{config.BUCKET_FOTOS} no existe o no se puede leer ({type(error).__name__})")

    admins = (
        get_client().table("administradores").select("numero").eq("activo", True).execute().data
    )
    if admins:
        numeros = ", ".join(enmascarar(a["numero"]) for a in admins)
        anotar("ok", "administradores", f"{len(admins)} activo(s): {numeros}")
    else:
        anotar(
            "aviso",
            "administradores",
            "ninguno activo: nadie recibe alertas ni resumenes. Cargarlos justo "
            "antes de apuntar el webhook, para que no llegue un resumen vacio antes",
        )


def revisar_whatsapp() -> None:
    cabeceras = {"Authorization": f"Bearer {config.META_ACCESS_TOKEN}"}
    numero = httpx.get(
        f"{GRAPH}/{config.META_PHONE_NUMBER_ID}",
        params={"fields": "display_phone_number,verified_name"},
        headers=cabeceras,
        timeout=20,
    )
    if numero.status_code != 200:
        error = numero.json().get("error", {}).get("message", numero.text[:120])
        anotar("falla", "whatsapp", f"el token no puede leer el numero: {error}")
        return
    datos = numero.json()
    anotar("ok", "whatsapp", f"{datos.get('display_phone_number')} ({datos.get('verified_name')})")

    if not config.META_WABA_ID:
        anotar("salta", "plantillas", "sin META_WABA_ID no se pueden revisar")
        return

    # La WABA tiene que contener el numero. Ya paso una vez consultar la WABA
    # de pruebas que Meta crea sola, y concluir que las plantillas no existian.
    telefonos = httpx.get(
        f"{GRAPH}/{config.META_WABA_ID}/phone_numbers", headers=cabeceras, timeout=20
    ).json()
    ids = {t.get("id") for t in telefonos.get("data", [])}
    if config.META_PHONE_NUMBER_ID not in ids:
        anotar("falla", "plantillas", "META_WABA_ID no es la cuenta que contiene este numero")
        return

    from app.services import meta_whatsapp_service as meta

    plantillas = httpx.get(
        f"{GRAPH}/{config.META_WABA_ID}/message_templates",
        params={"fields": "name,status", "limit": 200},
        headers=cabeceras,
        timeout=20,
    ).json()
    aprobadas = {p["name"] for p in plantillas.get("data", []) if p.get("status") == "APPROVED"}
    familias = {
        "alerta": [meta.PLANTILLA_ALERTA],
        "resumen diario": meta.PLANTILLAS_RESUMEN,
        "resumen semanal": meta.PLANTILLAS_SEMANAL,
    }
    faltan = [que for que, nombres in familias.items() if not aprobadas & set(nombres)]
    if faltan:
        anotar(
            "falla",
            "plantillas",
            "sin plantilla aprobada para " + ", ".join(faltan)
            + ". Fuera de la ventana de 24 h esos avisos no llegan",
        )
    else:
        anotar("ok", "plantillas", "alerta, resumen diario y semanal aprobadas")


def revisar_modelo() -> None:
    from app.services import modelo_ia

    try:
        anotar("ok", "modelo", f"{config.MODELO_IA} ({modelo_ia.verificar_modelo()})")
    except Exception as error:
        anotar("falla", "modelo", f"{config.MODELO_IA}: {type(error).__name__}, revisar la clave y el nombre")


def revisar_servidor(url: str) -> None:
    url = url.rstrip("/")
    try:
        salud = httpx.get(f"{url}/", timeout=30)
    except httpx.HTTPError as error:
        anotar("falla", "servidor", f"no responde ({type(error).__name__})")
        return
    if salud.status_code == 200 and salud.json().get("status") == "ok":
        anotar("ok", "servidor", f"responde, version {salud.json().get('version', '?')}")
    else:
        anotar("falla", "servidor", f"respondio {salud.status_code}")
        return

    # Lo mismo que hace Meta al registrar el webhook.
    reto = secrets.token_hex(8)
    verificacion = httpx.get(
        f"{url}/meta/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": config.META_VERIFY_TOKEN,
            "hub.challenge": reto,
        },
        timeout=30,
    )
    if verificacion.status_code == 200 and verificacion.text == reto:
        anotar("ok", "verificacion", "el servidor tiene el mismo META_VERIFY_TOKEN")
    else:
        anotar("falla", "verificacion", "el servidor rechaza el token: no coincide con el de la plataforma")

    # Un evento con firma falsa tiene que rebotar. Va vacio, asi que si el
    # servidor lo aceptara tampoco procesaria nada.
    firma = httpx.post(
        f"{url}/meta/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64},
        timeout=30,
    )
    if firma.status_code == 403:
        anotar("ok", "firma", "rechaza eventos sin la firma de Meta")
    else:
        anotar(
            "falla",
            "firma",
            f"acepto un evento con firma falsa ({firma.status_code}): falta META_APP_SECRET en la plataforma",
        )

    api = httpx.get(f"{url}/monitoreos", timeout=30)
    if api.status_code == 401:
        anotar("ok", "api", "cerrada sin la clave")
    elif api.status_code == 503:
        anotar("aviso", "api", "cerrada porque falta API_TOKEN en la plataforma")
    else:
        anotar("falla", "api", f"respondio {api.status_code} sin clave: los datos quedarian expuestos")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", default=".env.produccion", help="archivo con la configuracion de produccion")
    parser.add_argument("--url", help="URL publica del servidor desplegado")
    args = parser.parse_args()

    archivo = args.env if os.path.isabs(args.env) else os.path.join(RAIZ, args.env)
    print(f"Configuracion: {os.path.basename(archivo)}\n")
    cargar(archivo)

    faltantes = revisar_configuracion()

    if faltantes & {"SUPABASE_URL", "SUPABASE_KEY"}:
        anotar("salta", "base", "faltan las credenciales de la base")
    else:
        try:
            revisar_base()
        except Exception as error:
            anotar("falla", "base", f"no se pudo leer ({type(error).__name__}): revisar URL y service_role")

    if faltantes & {"META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID"}:
        anotar("salta", "whatsapp", "faltan las credenciales de WhatsApp")
    else:
        try:
            revisar_whatsapp()
        except Exception as error:
            anotar("falla", "whatsapp", f"no se pudo consultar a Meta ({type(error).__name__})")

    if "ANTHROPIC_API_KEY" in faltantes:
        anotar("salta", "modelo", "falta ANTHROPIC_API_KEY")
    else:
        revisar_modelo()

    if args.url:
        print()
        revisar_servidor(args.url)

    fallas = sum(1 for estado, _, _ in resultados if estado == "falla")
    avisos = sum(1 for estado, _, _ in resultados if estado == "aviso")
    print()
    if fallas:
        print(f"{fallas} falla(s): corregir antes de apuntar el webhook de Meta.")
        return 1
    print(f"Listo para operar{f' ({avisos} aviso(s) arriba)' if avisos else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
