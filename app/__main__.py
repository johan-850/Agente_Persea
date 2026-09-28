"""Arranque en produccion:  python -m app

La plataforma asigna el puerto en la variable PORT. Se lee desde config y no
en el comando de arranque ("--port $PORT"), porque que ese $PORT se expanda
depende de si la plataforma pasa el comando por una shell, y si no lo hace el
servidor no arranca.

En local sigue sirviendo scripts/levantar.ps1, que escucha solo en 127.0.0.1.
"""

import uvicorn

from app import config

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        # Todas las interfaces: el trafico llega desde el proxy de la
        # plataforma, no desde la misma maquina.
        host="0.0.0.0",
        port=config.PUERTO,
    )
