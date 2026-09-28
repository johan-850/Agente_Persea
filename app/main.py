import logging

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app import config  # noqa: E402

# Uvicorn configura sus propios loggers y deja los nuestros sin handler, asi
# que sin esto solo se veian los warnings. Se perdian justo las lineas que
# sirven para auditar por que el agente decidio algo: el reenvio que se
# descarto, el mensaje que no era un reporte, el patron de dano que se
# descarto porque el modelo propuso candidatas no cuarentenarias.
logging.basicConfig(
    level=config.NIVEL_LOG,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import Depends  # noqa: E402

from app.api.routes_meta_whatsapp import recuperar_cola  # noqa: E402
from app.api.routes_meta_whatsapp import router as meta_whatsapp_router  # noqa: E402
from app.api.routes_monitoreo import router as monitoreo_router  # noqa: E402
from app.api.seguridad import exigir_api_key  # noqa: E402
from app.horario import JORNADA_FIN, JORNADA_INICIO, ZONA  # noqa: E402
from app.services.resumen_semanal_service import enviar_resumen_semanal  # noqa: E402
from app.services.resumen_service import enviar_resumen_diario  # noqa: E402

app = FastAPI(title="Agente de Monitoreo - Reportes de Campo")

# Todo lo que lee o escribe datos va detras de la clave. El webhook de Meta no
# puede llevarla —lo llama Meta, no nosotros— y se protege con la firma del
# evento; /  queda abierto porque es el latido que consulta el tunel.
app.include_router(monitoreo_router, dependencies=[Depends(exigir_api_key)])
app.include_router(meta_whatsapp_router)

scheduler = BackgroundScheduler()

# Dias en que hay jornada de campo. El resumen diario es el cierre de la
# jornada, asi que sin este filtro el domingo llegaba un "No se recibieron
# reportes": un mensaje que no informa de nada y que enseña a no abrir el de
# las 18:00, que es justo el que si hay que leer.
DIAS_DE_JORNADA = "mon-sat"


def programar(planificador, hora: int) -> None:
    """Registra los dos resumenes en el planificador que se le pase.

    Va aparte del arranque para poder comprobar en que dias y a que hora
    disparan sin levantar el servidor. La hora salia una hora antes de lo
    acordado porque estaba puesta en el .env y ahi nadie la revisaba.
    """
    # La hora es la de las fincas, no la del servidor. Sin timezone explicito,
    # un servidor en UTC dispararia el resumen de las 18:00 a las 13:00 de
    # Colombia, a media jornada y con la mitad de los reportes sin llegar.
    planificador.add_job(
        enviar_resumen_diario,
        "cron",
        day_of_week=DIAS_DE_JORNADA,
        hour=hora,
        minute=0,
        timezone=ZONA,
        id="resumen_diario",
    )

    # El semanal sale media hora despues del diario del viernes, para que no
    # lleguen los dos pisados y se lean en orden: primero el dia, luego la
    # semana.
    planificador.add_job(
        enviar_resumen_semanal,
        "cron",
        day_of_week="fri",
        hour=hora,
        minute=30,
        timezone=ZONA,
        id="resumen_semanal",
    )


def revisar_configuracion() -> None:
    """No arranca si falta algo obligatorio, y dice todo lo que falta junto.

    Arrancar a medias es peor que no arrancar: sin la base, los reportes se
    reciben, se confirman a Meta y se pierden; sin el token de WhatsApp, las
    alertas se evaluan y no le llegan a nadie. En los dos casos el servidor
    responde "ok" y nadie se entera hasta que falta un dato.
    """
    log = logging.getLogger("config")
    revision = config.revisar()
    if not revision.puede_arrancar:
        log.error("El agente no puede arrancar.\n%s", revision.informe())
        raise RuntimeError("Configuracion incompleta: " + ", ".join(revision.faltantes))
    for aviso in revision.avisos:
        log.warning(aviso)
    log.info("Modelo: %s", config.MODELO_IA)


@app.on_event("startup")
def iniciar_scheduler():
    revisar_configuracion()
    programar(scheduler, config.HORA_RESUMEN_DIARIO)
    scheduler.start()

    # Lo que quedo en la cola cuando murio el proceso anterior.
    recuperar_cola()

    log = logging.getLogger("main")
    log.info(
        "Jornada de campo %s a %s (hora de Colombia)",
        JORNADA_INICIO.strftime("%H:%M"),
        JORNADA_FIN.strftime("%H:%M"),
    )
    for identificador, que in (("resumen_diario", "diario"), ("resumen_semanal", "semanal")):
        log.info("Resumen %s: proximo envio %s", que, scheduler.get_job(identificador).next_run_time)


@app.on_event("shutdown")
def detener_scheduler():
    scheduler.shutdown()


@app.get("/")
def health():
    return {"status": "ok"}
