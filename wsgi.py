"""
(wsgi.py)
Punto de entrada del backend de usuarios en Vercel.

Con el preset "Flask" de Vercel, la aplicación se expone como UNA sola
función serverless. Vercel la encuentra buscando un objeto llamado "app"
en una entrada con nombre conocido:

    app.py, index.py, server.py, main.py, wsgi.py, asgi.py

Este archivo es ese punto de entrada. Solo reexporta la aplicación que ya
existe en el paquete "app", de modo que el mismo código sirve para
desarrollar en local con run.py y para producción.

OJO, dos detalles importantes de esta estructura:

  - No se escribe ningún "app.run()": en Vercel no hay ningún proceso que
    se quede escuchando un puerto.
  - No hay "rewrites" en vercel.json. Con el preset Flask la aplicación
    atiende en la raíz, así que las rutas /api/... llegan enteras a Flask.
    Si además se pusiera un rewrite que mandara todo a /api, Flask recibiría
    "/api" (que no existe) y respondería 404.

El paquete "app" se importa con el path absoluto de la raíz del proyecto ya
añadido, porque en un serverless Vercel el directorio de trabajo no siempre
es la raíz del repositorio.
"""

import sys
from pathlib import Path

# Se añade la raíz del proyecto al path para poder importar "app"
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import app  # noqa: E402

__all__ = ["app"]