"""Toda la configuracion del agente, en un solo sitio.

El objetivo es que poner esto a operar sea cambiar credenciales y nada mas:
una base de datos nueva, una clave de Anthropic nueva, el numero de WhatsApp
del cliente, y arranca. Nada del entorno de desarrollo debe quedar clavado en
el codigo.

Antes las variables se leian en diez sitios distintos con `os.environ`, cada
uno con su propio valor por defecto. Eso tiene tres problemas en un despliegue:

- Un valor que falta no se nota hasta que alguien manda un mensaje y algo
  revienta a media noche, con el error enterrado en un log.
- No hay forma de saber que hace falta configurar sin leerse el codigo entero.
- Dos sitios con defectos distintos para la misma variable se desvian sin que
  nadie lo note. Paso con la hora del resumen: el codigo decia 18, el .env
  decia 17, y salio a las 17 durante dias.

Aqui esta declarado que existe, con que defecto, y `revisar()` lo comprueba al
arrancar y dice todo lo que falta de una vez, en vez de fallar en el primer
tropiezo.

Los valores se leen del entorno en el momento de pedirlos, no al importar este
modulo. Asi no importa en que orden se cargue el .env, y un test puede cambiar
una variable y ver el efecto sin recargar nada.
"""

import base64
import json
import os
from dataclasses import dataclass

# atributo -> (variable de entorno, valor por defecto)
_VARIABLES: dict[str, tuple[str, str | int]] = {
    # Base de datos y archivos. La service_role, no la anon: con la anon, RLS
    # bloquea los inserts y no se guarda nada.
    "SUPABASE_URL": ("SUPABASE_URL", ""),
    "SUPABASE_KEY": ("SUPABASE_KEY", ""),
    "BUCKET_FOTOS": ("SUPABASE_BUCKET_FOTOS", "fotos-monitoreo"),
    # Modelo de lenguaje. Cambiar MODELO_IA afecta a las tres tareas:
    # extraccion de reportes, fotos y consultas.
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY", ""),
    "MODELO_IA": ("MODELO_IA", "claude-haiku-4-5-20251001"),
    # WhatsApp (Meta Cloud API)
    "META_ACCESS_TOKEN": ("META_ACCESS_TOKEN", ""),
    "META_PHONE_NUMBER_ID": ("META_PHONE_NUMBER_ID", ""),
    "META_VERIFY_TOKEN": ("META_VERIFY_TOKEN", ""),
    "META_APP_SECRET": ("META_APP_SECRET", ""),
    # Solo lo usa scripts/crear_plantillas.py. El API no la expone con los
    # permisos del token; el agente la registra en el log al llegar el primer
    # mensaje.
    "META_WABA_ID": ("META_WABA_ID", ""),
    # API REST. Sin clave queda cerrada, no abierta.
    "API_TOKEN": ("API_TOKEN", ""),
    # Operacion. La zona horaria y la jornada NO son configurables: viven en
    # app/horario.py, porque las fincas estan en Colombia y un valor mal puesto
    # aqui correria el dia de todos los reportes.
    "HORA_RESUMEN_DIARIO": ("HORA_RESUMEN_DIARIO", 18),
    "NIVEL_LOG": ("NIVEL_LOG", "INFO"),
    # Lo asigna la plataforma de despliegue; en local se usa el 8000.
    "PUERTO": ("PORT", 8000),
    # El commit que esta corriendo. Railway lo pone en cada despliegue que sale
    # de GitHub; sirve para confirmar que un cambio ya esta en linea.
    "VERSION": ("RAILWAY_GIT_COMMIT_SHA", "local"),
}

# Sin estas el agente no hace su trabajo: no guarda, no lee o no avisa.
OBLIGATORIAS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "ANTHROPIC_API_KEY",
    "META_ACCESS_TOKEN",
    "META_PHONE_NUMBER_ID",
    "META_VERIFY_TOKEN",
)


def _crudo(atributo: str) -> str:
    variable, _ = _VARIABLES[atributo]
    return (os.environ.get(variable) or "").strip()


def __getattr__(atributo: str):
    if atributo not in _VARIABLES:
        raise AttributeError(f"app.config no tiene {atributo!r}")

    _, defecto = _VARIABLES[atributo]
    valor = _crudo(atributo)
    if not valor:
        return defecto
    if isinstance(defecto, int):
        # Un valor que no es numero no tumba el arranque, pero revisar() lo
        # reporta: no se queda en silencio con el defecto.
        try:
            return int(valor)
        except ValueError:
            return defecto
    return valor


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


def tipo_de_clave_bd(clave: str) -> str:
    """Que clave de Supabase es: 'secret', 'service_role', 'publishable',
    'anon' o 'desconocida'.

    Las clasicas son JWT y el rol va escrito adentro: se lee sin verificar la
    firma, que aqui no importa. Las nuevas no son JWT y se reconocen por el
    prefijo.
    """
    if clave.startswith("sb_secret_"):
        return "secret"
    if clave.startswith("sb_publishable_"):
        return "publishable"
    partes = clave.split(".")
    if len(partes) == 3:
        try:
            carga = partes[1] + "=" * (-len(partes[1]) % 4)
            rol = json.loads(base64.urlsafe_b64decode(carga)).get("role")
        except Exception:
            return "desconocida"
        if rol in ("service_role", "anon"):
            return rol
    return "desconocida"


def revisar() -> Revision:
    """Que falta para operar. Se llama al arrancar."""
    faltantes = [nombre for nombre in OBLIGATORIAS if not _crudo(nombre)]
    avisos = []

    # Errores de copiado que cuestan una tarde de depuracion.
    url = _crudo("SUPABASE_URL")
    if url and not url.startswith("https://"):
        faltantes.append("SUPABASE_URL: tiene que empezar por https://")

    clave_bd = _crudo("SUPABASE_KEY")
    tipo = tipo_de_clave_bd(clave_bd) if clave_bd else None
    if tipo in ("anon", "publishable"):
        # Con la publica las lecturas pueden funcionar y los inserts no: el
        # agente responderia a todo y no guardaria ningun reporte.
        faltantes.append(
            f"SUPABASE_KEY: es la clave publica ({tipo}); con ella RLS bloquea los "
            "inserts y no se guarda nada. Hace falta la secret (sb_secret_...)"
        )
    elif tipo == "service_role":
        avisos.append(
            "SUPABASE_KEY es la service_role clasica: funciona, pero Supabase la retira "
            "a fines de 2026. Cambiarla por una secret (sb_secret_...) de Settings > API Keys"
        )
    elif tipo == "desconocida":
        avisos.append(
            "SUPABASE_KEY no tiene el formato de ninguna clave de Supabase: revisar que "
            "se haya copiado entera"
        )

    clave_ia = _crudo("ANTHROPIC_API_KEY")
    if clave_ia and not clave_ia.startswith("sk-ant-"):
        avisos.append("ANTHROPIC_API_KEY no empieza por sk-ant-: revisa que se haya copiado entera")

    if not _crudo("META_APP_SECRET"):
        avisos.append(
            "META_APP_SECRET vacio: el webhook acepta eventos sin comprobar que "
            "vengan de Meta, y cualquiera que conozca la URL puede inyectar un reporte"
        )
    if not _crudo("API_TOKEN"):
        avisos.append("API_TOKEN vacio: la API REST responde 503 a todo")
    if not _crudo("META_WABA_ID"):
        avisos.append(
            "META_WABA_ID vacio: no se pueden crear plantillas con "
            "scripts/crear_plantillas.py. Aparece en el log al llegar el primer mensaje"
        )

    hora = _crudo("HORA_RESUMEN_DIARIO")
    if hora and (not hora.isdigit() or not 0 <= int(hora) <= 23):
        faltantes.append(f"HORA_RESUMEN_DIARIO tiene que ser una hora de 0 a 23, no {hora!r}")

    return Revision(faltantes=faltantes, avisos=avisos)
