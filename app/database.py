"""
Conexión a la base de datos de Postgres (Supabase).

Estas tablas guardan SOLO lo del negocio:
  - productos (inventario)
  - ventas (transacciones)
  - productos_vendidos (detalle de cada venta)
  - configuracion (preferencias y tema)
  - precios_dolar (historial de tasas)

Supabase además se usa para la autenticación y las licencias (tablas
"perfiles" y "administradores"), pero eso lo maneja supabase_service.py
por la API REST.

ANTES estas tablas vivían en un SQLite local (database.db). Se movieron a
Postgres porque el backend ahora corre en Vercel, donde el disco es de solo
lectura y cada request arranca un contenedor nuevo: un archivo SQLite se
perdería en cada invocación.

Todas las tablas llevan una columna "usuario_id" con el id del dueño. El
backend lo saca del token de sesión y lo usa en cada consulta, para que un
usuario nunca vea los datos de otro.

El esquema lo crea la migración de Supabase, no el código: ver
supabase/migrations/20260101000500_tablas_negocio_postgres.sql
"""

from datetime import date, datetime, time
from decimal import Decimal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config

# El pool se crea una sola vez por proceso. En Vercel cada función es
# fugaz, así que se deja sin conexiones siempre abiertas y con un tope
# bajo: si abrimos muchas, la base se queda sin conexiones libres.
_pool: ConnectionPool | None = None


def obtener_pool() -> ConnectionPool:
    """
    Devuelve el pool de conexiones, creándolo la primera vez.

    Se usa el pool de transacciones de Supabase (el host aws-0-*.pooler.
    supabase.com), que es el que funciona por IPv4 y aguanta las
    conexiones cortas de Vercel.
    """
    global _pool

    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError(
                "Falta la variable DATABASE_URL.\n"
                "En el .env debe estar la cadena de conexión a Postgres de Supabase:\n"
                "  postgresql://postgres.TU_REF:TU_CONTRASENA@aws-0-REGION.pooler.supabase.com:5432/postgres\n"
                "La encuentras en Supabase > Project Settings > Database > Connection string."
            )

        _pool = ConnectionPool(
            conninfo=config.DATABASE_URL,
            min_size=0,
            max_size=3,
            timeout=15,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    return _pool


def obtener_conexion():
    """
    Abre una conexión del pool.

    Se usa como context manager, igual que en SQLite:

        with obtener_conexion() as conexion:
            filas = conexion.execute("SELECT ... WHERE id = %s", (algo,)).fetchall()

    Importante: a diferencia de SQLite, Postgres abre una transacción
    sola al empezar. Por eso NO se escribe "BEGIN": basta con calling
    commit() para confirmar y rollback() para deshacer.
    """
    return obtener_pool().connection()


def comprobar_conexion() -> None:
    """
    Revisa que se pueda conectar a Postgres y que las tablas existan.

    Se llama al arrancar el servidor. Si algo falla (falta el DATABASE_URL,
    la contraseña está mal, la migración no se aplicó) se detiene con un
    mensaje claro, en vez de dejar que cada consulta falle con un error
    que no dice nada.
    """
    with obtener_conexion() as conexion:
        # Un SELECT 1 que no necesita ninguna tabla
        conexion.execute("SELECT 1")

        # Se revisa que estén las 5 tablas de negocio
        esperadas = {
            "productos",
            "ventas",
            "productos_vendidos",
            "configuracion",
            "precios_dolar",
        }

        filas = conexion.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        ).fetchall()

        existentes = {fila["table_name"] for fila in filas}
        faltantes = esperadas - existentes

        if faltantes:
            faltantes_texto = ", ".join(sorted(faltantes))
            raise RuntimeError(
                "Faltan tablas en Postgres:\n"
                f"  {faltantes_texto}\n\n"
                "Aplícalas con:\n"
                "  supabase db push"
            )

        conexion.commit()


def a_json(valor):
    """
    Convierte un valor de Postgres a algo que jsonify pueda escribir.

    Postgres devuelve los "numeric" (los precios y las ganancias) como
    Decimal, y las fechas como date/datetime/time. jsonify no sabe
    ninguno de los dos, así que se convierten a float y a texto.
    """
    if isinstance(valor, Decimal):
        return float(valor)

    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ", timespec="seconds")

    if isinstance(valor, (date, time)):
        return valor.isoformat()

    return valor


def fila_limpia(fila: dict) -> dict:
    """
    Limpia una fila de Postgres para poder devolverla como JSON.

    Convierte los Decimal a float y las fechas a texto, y saca los
    "_row_id_" que psycopg agrega por dentro.
    """
    return {
        clave: a_json(valor)
        for clave, valor in fila.items()
        if not clave.startswith("_")
    }


def respaldo_de_usuario(usuario_id: str) -> dict:
    """
    Arma un diccionario con TODOS los datos de negocio de un usuario.

    Se usa para la copia de seguridad en Google Drive. Antes se subía el
    archivo SQLite entero; ahora que los datos viven en Postgres no hay
    archivo que subir, así que se genera este resumen en JSON.

    Solo incluye las filas de ese usuario: nadie más ve sus datos en la
    copia, ni aunque la carpeta de Drive se compartiera por error.
    """
    with obtener_conexion() as conexion:
        productos = conexion.execute(
            "SELECT * FROM productos WHERE usuario_id = %s ORDER BY id",
            (usuario_id,),
        ).fetchall()

        ventas = conexion.execute(
            "SELECT * FROM ventas WHERE usuario_id = %s ORDER BY id",
            (usuario_id,),
        ).fetchall()

        productos_vendidos = conexion.execute(
            "SELECT * FROM productos_vendidos WHERE usuario_id = %s ORDER BY id",
            (usuario_id,),
        ).fetchall()

        configuracion = conexion.execute(
            "SELECT clave, valor FROM configuracion WHERE usuario_id = %s ORDER BY clave",
            (usuario_id,),
        ).fetchall()

        precios_dolar = conexion.execute(
            "SELECT * FROM precios_dolar WHERE usuario_id = %s ORDER BY id",
            (usuario_id,),
        ).fetchall()

        conexion.commit()

    # El token de Google NO se incluye en la copia: es una credencial
    # y no hace falta para restaurar el inventario ni las ventas
    ajustes = {
        fila["clave"]: fila["valor"]
        for fila in configuracion
        if fila["clave"] != "token_drive"
    }

    return {
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "version": 1,
        "usuario_id": usuario_id,
        "productos": [fila_limpia(fila) for fila in productos],
        "ventas": [fila_limpia(fila) for fila in ventas],
        "productos_vendidos": [fila_limpia(fila) for fila in productos_vendidos],
        "configuracion": ajustes,
        "precios_dolar": [fila_limpia(fila) for fila in precios_dolar],
    }


# ------------------------------------------------------------
# Utilidad: sacar el id del usuario de la sesión
# ------------------------------------------------------------
def usuario_actual() -> str:
    """
    Devuelve el id del usuario que está con la sesión iniciada.

    Ese id es el que se guarda en la columna "usuario_id" de cada tabla, y es
    lo que hace que un usuario solo vea y modifique sus propios datos.

    Si por algún error no hay sesión, se devuelve una cadena vacía: como
    ninguna fila tiene esa cadena como usuario_id, el usuario no verá datos
    ajenos ni podrá escribir sobre ellos.
    """
    from flask import g

    perfil = getattr(g, "perfil", None)

    if not perfil:
        return ""

    return perfil.get("id") or ""