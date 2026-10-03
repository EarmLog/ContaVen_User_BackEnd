"""
(api/index.py)
Punto de entrada del backend de usuarios en Vercel.

Vercel detecta este archivo y lo convierte en una función serverless.
Lo único que hace es exponer la aplicación Flask que ya existe en "app",
así que la misma aplicación sirve para desarrollo local y para producción.

Lo que NO se hace aquí es arrancar un servidor: en Vercel no existe un
proceso que se quede escuchando un puerto, y por eso tampoco tiene sentido
el app.run() de run.py.
"""

from app import app

# Vercel busca una variable llamada "app" (Flask) o "handler" (WSGI) en este
# archivo. "app" cumple las dos cosas: Flask es un callable compatible WSGI.
__all__ = ["app"]