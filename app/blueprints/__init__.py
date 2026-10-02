"""
Rutas de la API, divididas por módulo.

Cada archivo de esta carpeta es un "blueprint" de Flask: un grupo de
endpoints que se registra en la aplicación desde app/__init__.py.

    auth.py           -> registro, inicio de sesión y licencia
    productos.py      -> inventario (CRUD de productos)
    ventas.py         -> punto de venta y detalle de ventas
    analisis.py       -> reportes y gráficas
    configuracion.py  -> ajustes y precio del dólar
    drive_backup.py   -> copia de seguridad en Google Drive
"""

from .analisis import rutas_analisis
from .auth import cargar_usuario_autenticado, rutas_auth
from .configuracion import rutas_config
from .drive_backup import rutas_drive
from .productos import rutas_productos
from .ventas import rutas_ventas

# Se ordenan como se registran en la aplicación
TODAS_LAS_RUTAS = (
    rutas_auth,
    rutas_productos,
    rutas_ventas,
    rutas_analisis,
    rutas_config,
    rutas_drive,
)

__all__ = [
    "TODAS_LAS_RUTAS",
    "rutas_auth",
    "rutas_productos",
    "rutas_ventas",
    "rutas_analisis",
    "rutas_config",
    "rutas_drive",
    "cargar_usuario_autenticado",
]