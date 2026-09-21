import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

# Uvicorn configura sus propios loggers y deja los nuestros sin handler, asi
# que sin esto solo se veian los warnings. Se perdian justo las lineas que
# sirven para auditar por que el agente decidio algo: el reenvio que se
# descarto, el mensaje que no era un reporte, el patron de dano que se
# descarto porque el modelo propuso candidatas no cuarentenarias.
logging.basicConfig(
    level=os.environ.get("NIVEL_LOG", "INFO"),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

from app.api.routes_meta_whatsapp import router as meta_whatsapp_router  # noqa: E402
from app.api.routes_monitoreo import router as monitoreo_router  # noqa: E402
from app.api.routes_reportes import router as reportes_router  # noqa: E402
from app.api.routes_whatsapp import router as whatsapp_router  # noqa: E402
from app.services.resumen_service import enviar_resumen_diario  # noqa: E402

app = FastAPI(title="Agente de Monitoreo - Reportes de Campo")
app.include_router(reportes_router)
app.include_router(monitoreo_router)
app.include_router(whatsapp_router)
app.include_router(meta_whatsapp_router)

scheduler = BackgroundScheduler()


@app.on_event("startup")
def iniciar_scheduler():
    hora = int(os.environ.get("HORA_RESUMEN_DIARIO", "17"))
    scheduler.add_job(enviar_resumen_diario, "cron", hour=hora, minute=0, id="resumen_diario")
    scheduler.start()


@app.on_event("shutdown")
def detener_scheduler():
    scheduler.shutdown()


@app.get("/")
def health():
    return {"status": "ok"}
