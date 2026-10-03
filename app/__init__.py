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
        """Comprueba que el backend responde bien."""
        return jsonify({"mensaje": "ContaVen User API está funcionando."})

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
    """
    try:
        comprobar_conexion()
    except RuntimeError as error_conexion:
        # Sin conexión no tiene sentido arrancar: se avisa con el motivo
        # exacto y se detiene, en vez de dejar que falle cada consulta
        print(f"\n{'=' * 60}")
        print("  No se pudo conectar con la base de datos")
        print(f"{'=' * 60}\n")
        print(error_conexion)
        print()
        raise SystemExit(1) from error_conexion

    return crear_aplicacion()


# La aplicación que usa el servidor y las pruebas
app = crear_app()