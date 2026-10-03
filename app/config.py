"""
Configuración general del backend de usuarios de ContaVen.

Aquí se leen las variables de entorno del archivo ".env" y se
guardan en un objeto "config" que usan el resto de archivos.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Carpeta del paquete "app" (este archivo vive aquí dentro)
CARPETA_APP = Path(__file__).resolve().parent

# Carpeta del backend, que es un nivel arriba del paquete.
# Aquí, y no dentro de app/, viven el ".env" y la base de datos.
CARPETA_BACKEND = CARPETA_APP.parent

# Carga el archivo .env si existe
load_dotenv(CARPETA_BACKEND / ".env")


class Config:
    """Valores de configuración leídos del archivo .env."""

    # --- Servidor ---
    PUERTO = int(os.getenv("PUERTO", 5001))

    # --- Supabase (autenticación y licencias) ---
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    SUPABASE_JWKS_URL = os.getenv(
        "SUPABASE_JWKS_URL",
        SUPABASE_URL + "/auth/v1/.well-known/jwks.json",
    )

    # --- Base de datos (Postgres de Supabase) ---
    # Cadena de conexión directa a Postgres. Antes era un archivo SQLite
    # local (database.db), pero en Vercel el disco es de solo lectura y se
    # perdía en cada request, así que ahora todo vive en Postgres.
    # Se encuentra en Supabase > Project Settings > Database > Connection string
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # --- Licencia ---
    DIAS_LICENCIA_INICIAL = int(os.getenv("DIAS_LICENCIA_INICIAL", 30))

    # --- Dólar ---
    PRECIO_DOLAR_POR_DEFECTO = float(os.getenv("PRECIO_DOLAR_POR_DEFECTO", 36.50))

    # Llave de https://www.exchangerate-api.com (plan gratuito)
    LLAVE_EXCHANGERATE_API = os.getenv("EXCHANGERATE_API_KEY", "")

    # Cada cuánto tiempo se vuelve a consultar la tasa por internet.
    # Si la tasa guardada tiene más de estos minutos, se refresca sola
    # cuando alguien abre la app. Se deja en 0 para desactivar el refresco.
    MINUTOS_ACTUALIZACION_DOLAR = int(os.getenv("MINUTOS_ACTUALIZACION_DOLAR", 60))

    # --- Google Drive (opcional) ---
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")


# Objeto único de configuración que se importa en los demás archivos
config = Config()
