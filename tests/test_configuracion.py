"""La configuracion y la puerta hacia el modelo.

Lo que se protege aqui es que desplegar sea configurar credenciales y nada
mas. Eso depende de tres cosas que se rompen sin hacer ruido:

- Que falte algo obligatorio y el agente arranque igual, respondiendo "ok"
  mientras pierde reportes. revisar() tiene que decirlo todo de una vez.
- Que alguien vuelva a leer una variable directo del entorno en otro archivo,
  con su propio valor por defecto. Asi se desvio la hora del resumen.
- Que alguien vuelva a llamar al proveedor desde un servicio, y cambiar de
  modelo deje de ser tocar un archivo.

No llama a la base ni al modelo: el cliente del modelo se sustituye por uno
falso. Correr:  python tests/test_configuracion.py
"""

import base64
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import config  # noqa: E402

CASOS = []


def revisar(descripcion, obtenido, esperado):
    CASOS.append((descripcion, obtenido, esperado))


def jwt(rol: str) -> str:
    """Una clave clasica de Supabase con ese rol. La firma no se verifica."""
    carga = base64.urlsafe_b64encode(json.dumps({"role": rol}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{carga}.firma"


COMPLETA = {
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_KEY": "sb_secret_" + "x" * 32,
    "ANTHROPIC_API_KEY": "sk-ant-api03-xxxx",
    "META_ACCESS_TOKEN": "EAAB",
    "META_PHONE_NUMBER_ID": "123",
    "META_VERIFY_TOKEN": "verifica",
    "META_APP_SECRET": "secreto",
    "META_WABA_ID": "456",
    "API_TOKEN": "clave",
}
TODAS = set(COMPLETA) | {"SUPABASE_BUCKET_FOTOS", "MODELO_IA", "HORA_RESUMEN_DIARIO", "NIVEL_LOG", "PORT"}


def entorno(**valores):
    """Deja el entorno exactamente con esos valores de configuracion."""
    for nombre in TODAS:
        os.environ.pop(nombre, None)
    for nombre, valor in valores.items():
        os.environ[nombre] = valor


print("QUE HACE FALTA PARA ARRANCAR")
entorno(**COMPLETA)
r = config.revisar()
revisar("con todo configurado arranca", r.puede_arrancar, True)
revisar("y no avisa nada", r.avisos, [])

entorno()
r = config.revisar()
revisar("sin nada no arranca", r.puede_arrancar, False)
revisar("y dice todas las que faltan de una vez, no la primera",
        set(r.faltantes), set(config.OBLIGATORIAS))

for nombre in config.OBLIGATORIAS:
    entorno(**{k: v for k, v in COMPLETA.items() if k != nombre})
    revisar(f"sin {nombre} no arranca", config.revisar().faltantes, [nombre])

entorno(**{**COMPLETA, "SUPABASE_URL": "   "})
revisar("un valor en blanco cuenta como vacio", config.revisar().faltantes, ["SUPABASE_URL"])

print("\nERRORES DE COPIADO")
entorno(**{**COMPLETA, "SUPABASE_URL": "abc.supabase.co"})
revisar("URL sin https no arranca", config.revisar().puede_arrancar, False)

print("\nQUE CLAVE DE LA BASE ES")
revisar("la secret nueva se reconoce", config.tipo_de_clave_bd("sb_secret_abc"), "secret")
revisar("la publishable nueva se reconoce", config.tipo_de_clave_bd("sb_publishable_abc"), "publishable")
revisar("la clasica se lee por su rol: service_role", config.tipo_de_clave_bd(jwt("service_role")), "service_role")
revisar("la clasica se lee por su rol: anon", config.tipo_de_clave_bd(jwt("anon")), "anon")
revisar("algo mal copiado no pasa por clave", config.tipo_de_clave_bd("eyJhbGciOi.corta"), "desconocida")

for clave, nombre in ((jwt("anon"), "anon"), ("sb_publishable_abc", "publishable")):
    entorno(**{**COMPLETA, "SUPABASE_KEY": clave})
    r = config.revisar()
    revisar(f"con la publica ({nombre}) no arranca: los inserts no pasarian", r.puede_arrancar, False)
    revisar(f"y dice que hace falta la secret ({nombre})",
            any("sb_secret_" in f for f in r.faltantes), True)

entorno(**{**COMPLETA, "SUPABASE_KEY": jwt("service_role")})
r = config.revisar()
revisar("la service_role clasica todavia arranca", r.puede_arrancar, True)
revisar("pero avisa que Supabase la retira", any("2026" in a for a in r.avisos), True)

entorno(**{**COMPLETA, "SUPABASE_KEY": "algo-mal-copiado"})
revisar("una clave con formato raro avisa",
        any("formato" in a for a in config.revisar().avisos), True)
entorno(**{**COMPLETA, "ANTHROPIC_API_KEY": "api03-xxxx"})
revisar("clave del modelo cortada avisa",
        any("sk-ant-" in a for a in config.revisar().avisos), True)
for hora in ("17h", "25", "-1"):
    entorno(**{**COMPLETA, "HORA_RESUMEN_DIARIO": hora})
    revisar(f"hora {hora!r} no arranca", config.revisar().puede_arrancar, False)

print("\nLO RECOMENDABLE AVISA PERO NO FRENA")
for nombre in ("META_APP_SECRET", "API_TOKEN", "META_WABA_ID"):
    entorno(**{k: v for k, v in COMPLETA.items() if k != nombre})
    r = config.revisar()
    revisar(f"sin {nombre} arranca", r.puede_arrancar, True)
    revisar(f"sin {nombre} avisa", any(nombre in a for a in r.avisos), True)

print("\nVALORES POR DEFECTO")
entorno(**COMPLETA)
revisar("la hora por defecto es 18", config.HORA_RESUMEN_DIARIO, 18)
revisar("la hora es un numero", isinstance(config.HORA_RESUMEN_DIARIO, int), True)
revisar("el modelo por defecto es Haiku 4.5", config.MODELO_IA, "claude-haiku-4-5-20251001")
revisar("el bucket por defecto", config.BUCKET_FOTOS, "fotos-monitoreo")
revisar("una obligatoria ausente vale vacio, no None", config.SUPABASE_URL, "https://abc.supabase.co")

print("\nSE LEE AL PEDIRLO, NO AL IMPORTAR")
os.environ["MODELO_IA"] = "otro-modelo"
revisar("cambiar el entorno despues de importar se ve", config.MODELO_IA, "otro-modelo")
os.environ["HORA_RESUMEN_DIARIO"] = "6"
revisar("la hora tambien", config.HORA_RESUMEN_DIARIO, 6)
os.environ["SUPABASE_BUCKET_FOTOS"] = "otro-bucket"
revisar("el bucket sale de SUPABASE_BUCKET_FOTOS", config.BUCKET_FOTOS, "otro-bucket")
try:
    config.NO_EXISTE
    revisar("pedir una variable que no esta declarada falla", False, True)
except AttributeError:
    revisar("pedir una variable que no esta declarada falla", True, True)

print("\nUNA SOLA PUERTA AL ENTORNO Y AL PROVEEDOR")
fuentes = {p: p.read_text(encoding="utf-8") for p in (RAIZ / "app").rglob("*.py")}
# Sin esto, las tres de abajo pasarian en vacio si la ruta estuviera mal.
revisar("se revisa el codigo de verdad", len(fuentes) > 15, True)
leen_entorno = sorted(
    p.relative_to(RAIZ).as_posix() for p, codigo in fuentes.items()
    if re.search(r"os\.environ|os\.getenv", codigo) and p.name != "config.py"
)
revisar("solo config.py lee el entorno", leen_entorno, [])
importan_proveedor = sorted(
    p.relative_to(RAIZ).as_posix() for p, codigo in fuentes.items()
    if re.search(r"^\s*(import anthropic|from anthropic)", codigo, re.M)
)
revisar("solo modelo_ia.py habla con el proveedor", importan_proveedor, ["app/services/modelo_ia.py"])
con_modelo_clavado = sorted(
    p.relative_to(RAIZ).as_posix() for p, codigo in fuentes.items()
    if "claude-" in codigo and p.name != "config.py"
)
revisar("el nombre del modelo solo esta en config.py", con_modelo_clavado, [])


# --------------------------------------------------------------------------
# La conversacion con herramientas, con un proveedor falso.
# --------------------------------------------------------------------------
entorno(**COMPLETA)
from app.services import consultas_service, modelo_ia  # noqa: E402


class ModeloFalso:
    """Responde con lo que se le programe y guarda lo que le mandaron."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Copia: la conversacion es una lista que se sigue modificando.
        self.llamadas.append(json.loads(json.dumps(kwargs, default=lambda o: repr(o))))
        return self.respuestas.pop(0)


def pide(nombre, argumentos, id_="t1"):
    bloque = SimpleNamespace(type="tool_use", name=nombre, input=argumentos, id=id_)
    return SimpleNamespace(stop_reason="tool_use", content=[bloque])


def contesta(texto):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=texto)])


print("\nLAS CONSULTAS PASAN POR LA CAPA")
falso = ModeloFalso([pide("estado_de_lote", {"lote": "14"}), contesta("Lote 14: sin alertas.")])
modelo_ia._cliente = falso
enviados = []
consultas_service._enviar = lambda texto, remitente: enviados.append(texto) or texto
consultas_service.CONSULTAS["estado_de_lote"] = lambda **kw: {"lote": kw["lote"], "fecha": object()}

consultas_service.responder("como va el lote 14", "whatsapp:+57300")
revisar("responde lo que dijo el modelo", list(enviados), ["Lote 14: sin alertas."])
revisar("usa el modelo de la configuracion", falso.llamadas[0]["model"], "claude-haiku-4-5-20251001")
revisar("con temperatura 0", falso.llamadas[0]["temperature"], 0)
resultado = falso.llamadas[1]["messages"][-1]["content"][0]
revisar("el resultado de la consulta viaja como texto, no como dict",
        isinstance(resultado["content"], str), True)
revisar("y es JSON que se puede leer", json.loads(resultado["content"])["lote"], "14")
revisar("va atado a la herramienta que lo pidio", resultado["tool_use_id"], "t1")

print("\nSI LA CONSULTA FALLA, EL MODELO SE ENTERA")
falso = ModeloFalso([pide("estado_de_lote", {"lote": "14"}), contesta("No pude leer el lote.")])
modelo_ia._cliente = falso


def revienta(**_):
    raise RuntimeError("base caida")


consultas_service.CONSULTAS["estado_de_lote"] = revienta
enviados.clear()
consultas_service.responder("como va el lote 14", "whatsapp:+57300")
resultado = falso.llamadas[1]["messages"][-1]["content"][0]
revisar("recibe el error en vez de romper la conversacion",
        json.loads(resultado["content"]), {"error": "base caida"})
revisar("y el administrador recibe respuesta", list(enviados), ["No pude leer el lote."])

print("\nSI NO HAY RESPUESTA, SE DICE")
modelo_ia._cliente = ModeloFalso([pide("estado_de_lote", {"lote": "1"}, f"t{i}") for i in range(3)])
consultas_service.CONSULTAS["estado_de_lote"] = lambda **kw: {}
enviados.clear()
consultas_service.responder("?", "whatsapp:+57300")
revisar("agotar las rondas no queda en silencio",
        len(enviados) == 1 and "No pude resolver" in enviados[0], True)

modelo_ia._cliente = ModeloFalso([contesta("   ")])
enviados.clear()
consultas_service.responder("?", "whatsapp:+57300")
revisar("una respuesta en blanco tampoco",
        len(enviados) == 1 and "No pude resolver" in enviados[0], True)

print("\nLAS FOTOS PASAN POR LA CAPA")
from app.services import vision_service  # noqa: E402

bloque = SimpleNamespace(type="tool_use", name="describir_foto", id="f1", input={
    "descripcion": " Fruto con perforacion. ",
    "danos_observados": ["perforacion_en_fruto_rama_o_tallo", "inventado"],
    "plagas_sugeridas": ["Stenoma catenifer"],
})
falso = ModeloFalso([SimpleNamespace(stop_reason="tool_use", content=[bloque])])
modelo_ia._cliente = falso
visto = vision_service.describir_foto(b"\xff\xd8jpeg", "image/jpeg")
revisar("devuelve la descripcion limpia", visto["descripcion"], "Fruto con perforacion.")
revisar("descarta daños fuera de la lista cerrada",
        visto["danos_observados"], ["perforacion_en_fruto_rama_o_tallo"])
imagen = falso.llamadas[0]["messages"][0]["content"][0]
revisar("la foto viaja como imagen", imagen["type"], "image")
revisar("con su tipo", imagen["source"]["media_type"], "image/jpeg")
revisar("forzando la herramienta", falso.llamadas[0]["tool_choice"]["name"], "describir_foto")

os.environ.pop("ANTHROPIC_API_KEY")
revisar("sin clave la foto se archiva sin descripcion, no revienta",
        vision_service.describir_foto(b"x", "image/jpeg"), None)

print("\nEL SERVIDOR NO ARRANCA A MEDIAS")
from app import main  # noqa: E402  (carga el .env al importarse)

entorno(**{k: v for k, v in COMPLETA.items() if k not in ("SUPABASE_KEY", "META_ACCESS_TOKEN")})
try:
    main.revisar_configuracion()
    revisar("sin lo obligatorio el arranque se niega", "arranco", "se nego")
except RuntimeError as error:
    revisar("sin lo obligatorio el arranque se niega", "se nego", "se nego")
    revisar("y nombra todo lo que falta", "SUPABASE_KEY" in str(error) and "META_ACCESS_TOKEN" in str(error), True)

entorno(**COMPLETA)
try:
    main.revisar_configuracion()
    revisar("con todo configurado arranca", True, True)
except RuntimeError:
    revisar("con todo configurado arranca", False, True)

print("\nEL SERVIDOR DICE QUE VERSION CORRE")
os.environ.pop("RAILWAY_GIT_COMMIT_SHA", None)
revisar("en local dice local", main.health()["version"], "local")
os.environ["RAILWAY_GIT_COMMIT_SHA"] = "6560f11c0ffee"
revisar("desplegado dice el commit, corto", main.health()["version"], "6560f11")
os.environ.pop("RAILWAY_GIT_COMMIT_SHA")


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
