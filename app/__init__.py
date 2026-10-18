"""
ContaVen - Backend de la app de USUARIOS (Flask + Supabase Postgres).

Este paquete junta el servidor y lo divide en piezas:

    app/
      __init__.py      -> fábrica de la aplicación (create_app) y CORS
      config.py        -> variables del archivo .env
      database.py      -> conexión a Postgres y dueño de cada dato
      blueprints/      -> las rutas de la API, divididas por módulo
      services/        -> lógica de terceros (Supabase, Drive, dólar)
      utils/           -> funciones de apoyo (validación, sanitización)

Para arrancarlo:
    pip install -r requirements.txt
    python run.py
"""

import os

from flask import Flask, jsonify
from flask_cors import CORS

from .blueprints.analisis import rutas_analisis
from .blueprints.auth import rutas_auth
from .blueprints.configuracion import rutas_config
from .blueprints.drive_backup import rutas_drive
from .blueprints.productos import rutas_productos
from .blueprints.ventas import rutas_ventas
from .config import config
from .database import comprobar_conexion

# Vercel inyecta estas variables en sus funciones. Se usan para distinguir
# "estoy en un servidor normal" de "estoy en una función de Vercel", donde
# la app se reconstruye en cada petición y no debe morir al importar.
VERCEL = bool(os.getenv("VERCEL"))


def crear_aplicacion() -> Flask:
    """Crea y configura la aplicación Flask con todas sus rutas."""
    app = Flask(__name__)

    # Se permite que el frontend React (distinto puerto) llame a la API
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Se registran los grupos de rutas
    app.register_blueprint(rutas_auth)
    app.register_blueprint(rutas_productos)
    app.register_blueprint(rutas_ventas)
    app.register_blueprint(rutas_analisis)
    app.register_blueprint(rutas_config)
    app.register_blueprint(rutas_drive)

    # Ruta rápida para comprobar que el servidor está vivo
    @app.get("/api/salud")
    def salud():
        """
        Comprueba que el backend responde bien.

        Incluye el estado de la base de datos porque en Vercel las funciones
        son efímeras: la app puede seguir viva aunque Postgres no responda
        en ese instante. Con solo el mensaje fijo no se distinguía un
        despliegue roto de una base temporalmente inalcanzable.
        """
        cuerpo = {"mensaje": "ContaVen User API está funcionando.", "base_de_datos": "sin_revisar"}

        try:
            comprobar_conexion()
            cuerpo["base_de_datos"] = "conectada"
        except Exception as error:  # noqa: BLE001 - aquí solo se informa
            cuerpo["base_de_datos"] = "sin_conexion"
            cuerpo["detalle_base_de_datos"] = str(error).splitlines()[0][:300]

        return jsonify(cuerpo), (200 if cuerpo["base_de_datos"] == "conectada" else 503)

    return app


def crear_app() -> Flask:
    """
    Punto único de arranque: comprueba que se pueda conectar a la base y
    devuelve la app.

    Se separa de crear_aplicacion() para que las pruebas puedan armar la
    aplicación sin tocar la base de datos real.

    Ya no hace falta crear tablas ni migrar el esquema: en Postgres el
    esquema se aplica con un archivo de migración versionado, y la base
    solo se abre para confirmar que responde.

    OJO con la diferencia entre local y Vercel:

    - En local (run.py) la app es un proceso que se queda vivo, así que si
      la base no responde se detiene todo con SystemExit: es más fácil de
      arreglar que una app que arranca a medias.
    - En Vercel la app se construye en cada petición dentro de una función
      fugaz. Si aquí se hiciera SystemExit, un hipo de red de Postgres
      devolvería FUNCTION_INVOCATION_FAILED (error 500) y se vería igual
      que un despliegue roto. Por eso en producción solo se avisa y se
      sigue: cada endpoint se encarga del error de la base por su cuenta,
      y /api/salud informa si la conexión está bien.
    """
    try:
        comprobar_conexion()
    except Exception as error_conexion:  # noqa: BLE001 - se avisa de cualquier fallo
        aviso = f"\n{'=' * 60}\n  No se pudo conectar con la base de datos\n{'=' * 60}\n{error_conexion}\n"

        if VERCEL:
            # En Vercel se registra el aviso y la app arranca igualmente
            print(aviso, flush=True)
        else:
            # En local se detiene el proceso para no fallar en cada consulta
            print(aviso)
            raise SystemExit(1) from error_conexion

    return crear_aplicacion()


# La aplicación que usa el servidor y las pruebas
app = crear_app()