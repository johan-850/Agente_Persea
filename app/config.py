"""Toda la configuracion del agente, en un solo sitio.

El objetivo es que poner esto a operar sea cambiar credenciales y nada mas:
una base de datos nueva, una clave de Anthropic nueva, el numero de WhatsApp
del cliente, y arranca. Nada del entorno de desarrollo debe quedar clavado en
el codigo.

Antes las variables se leian en once sitios distintos con `os.environ.get` y
sin comprobar nada. Eso tiene dos problemas en un despliegue:

- Un valor que falta no se nota hasta que alguien manda un mensaje y algo
  revienta a media noche, con el error enterrado en un log.
- No hay forma de saber que hace falta configurar sin leerse el codigo entero.

Aqui esta declarado que es obligatorio, que es recomendable y que tiene un
valor por defecto razonable. `revisar()` lo comprueba al arrancar y dice todo
lo que falta de una vez, en vez de fallar en el primer tropiezo.
"""

import os
from dataclasses import dataclass


def _texto(nombre: str, defecto: str = "") -> str:
    return (os.environ.get(nombre) or defecto).strip()


def _entero(nombre: str, defecto: int) -> int:
    valor = _texto(nombre)
    try:
        return int(valor) if valor else defecto
    except ValueError:
        return defecto


# --------------------------------------------------------------------------
# Base de datos y archivos
# --------------------------------------------------------------------------
SUPABASE_URL = _texto("SUPABASE_URL")
# La service_role, no la anon: con la anon, RLS bloquea los inserts.
SUPABASE_KEY = _texto("SUPABASE_KEY")
BUCKET_FOTOS = _texto("SUPABASE_BUCKET_FOTOS", "fotos-monitoreo")

# --------------------------------------------------------------------------
# Modelo de lenguaje
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY = _texto("ANTHROPIC_API_KEY")
# Cambiarlo aqui afecta a las tres tareas: extraccion, fotos y consultas.
MODELO_IA = _texto("MODELO_IA", "claude-haiku-4-5-20251001")

# --------------------------------------------------------------------------
# WhatsApp (Meta Cloud API)
# --------------------------------------------------------------------------
META_ACCESS_TOKEN = _texto("META_ACCESS_TOKEN")
META_PHONE_NUMBER_ID = _texto("META_PHONE_NUMBER_ID")
# Cadena arbitraria; tiene que coincidir con la registrada en el webhook.
META_VERIFY_TOKEN = _texto("META_VERIFY_TOKEN")
# Sin esto el webhook acepta eventos sin comprobar que vengan de Meta.
META_APP_SECRET = _texto("META_APP_SECRET")
# La cuenta de WhatsApp Business que contiene el numero. Solo hace falta para
# crear las plantillas; el agente la registra en el log al llegar el primer
# mensaje, porque el API no la expone con los permisos del token.
META_WABA_ID = _texto("META_WABA_ID")

# --------------------------------------------------------------------------
# API REST
# --------------------------------------------------------------------------
# Sin clave, la API queda cerrada: no hace falta para que el agente funcione.
API_TOKEN = _texto("API_TOKEN")

# --------------------------------------------------------------------------
# Horario de la operacion
# --------------------------------------------------------------------------
# La zona de las fincas, no la del servidor. En un servidor UTC, un resumen
# programado a las 18:00 saldria a las 13:00 de Colombia.
ZONA_HORARIA = _texto("ZONA_HORARIA", "America/Bogota")
HORA_RESUMEN_DIARIO = _entero("HORA_RESUMEN_DIARIO", 18)
JORNADA_INICIO = _texto("JORNADA_INICIO", "07:00")
JORNADA_FIN = _texto("JORNADA_FIN", "16:30")

NIVEL_LOG = _texto("NIVEL_LOG", "INFO")


@dataclass
class Revision:
    faltantes: list[str]
    avisos: list[str]

    @property
    def puede_arrancar(self) -> bool:
        return not self.faltantes

    def informe(self) -> str:
        lineas = []
        if self.faltantes:
            lineas.append("Falta configurar (el agente no puede funcionar sin esto):")
            lineas += [f"  - {f}" for f in self.faltantes]
        if self.avisos:
            if lineas:
                lineas.append("")
            lineas.append("Funciona, pero conviene revisar:")
            lineas += [f"  - {a}" for a in self.avisos]
        return "\n".join(lineas) or "Configuracion completa."


def revisar() -> Revision:
    """Que falta para operar. Se llama al arrancar."""
    faltantes = []
    avisos = []

    obligatorias = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "META_ACCESS_TOKEN": META_ACCESS_TOKEN,
        "META_PHONE_NUMBER_ID": META_PHONE_NUMBER_ID,
        "META_VERIFY_TOKEN": META_VERIFY_TOKEN,
    }
    for nombre, valor in obligatorias.items():
        if not valor:
            faltantes.append(nombre)

    # Errores de copiado que cuestan una tarde de depuracion.
    if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
        faltantes.append("SUPABASE_URL: tiene que empezar por https://")
    if SUPABASE_KEY and len(SUPABASE_KEY) < 100:
        avisos.append(
            "SUPABASE_KEY parece corta. Tiene que ser la service_role; "
            "con la anon, RLS bloquea los inserts y no se guarda nada"
        )

    if not META_APP_SECRET:
        avisos.append(
            "META_APP_SECRET vacio: el webhook acepta eventos sin comprobar que "
            "vengan de Meta, y el servidor esta expuesto a internet"
        )
    if not API_TOKEN:
        avisos.append("API_TOKEN vacio: la API REST responde 503 a todo")
    if not META_WABA_ID:
        avisos.append(
            "META_WABA_ID vacio: no se pueden crear plantillas con "
            "scripts/crear_plantillas.py. Aparece en el log al llegar el primer mensaje"
        )

    if not 0 <= HORA_RESUMEN_DIARIO <= 23:
        faltantes.append(f"HORA_RESUMEN_DIARIO fuera de rango: {HORA_RESUMEN_DIARIO}")

    return Revision(faltantes=faltantes, avisos=avisos)
