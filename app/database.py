"""
Conexión y creación de la base de datos local (SQLite).

SQLite guarda SOLO lo del negocio:
  - productos (inventario)
  - ventas (transacciones)
  - productos_vendidos (detalle de cada venta)
  - configuracion (preferencias y tema)
  - precios_dolar (historial de tasas)
Supabase solo se usa para autenticación y licencias.

Todas las tablas de negocio llevan una columna "usuario_id" con el id del
dueño. El backend lo saca del token de sesión y lo usa en cada consulta,
para que un usuario nunca vea los datos de otro.
"""

import getpass
import os
import sqlite3
from pathlib import Path

from .config import config


def obtener_conexion() -> sqlite3.Connection:
    """
    Abre una conexión nueva a la base de datos local.

    La conexión se abre en modo lectura-escritura (rw_uri=False) para
    que SQLite cree el archivo si no existe, y se espera a que cualquier
    otra conexión que lo esté usando se cierre, en vez de fallar de
    inmediato. Eso evita el error "database is locked" cuando dos peticiones
    del servidor coinciden.
    """
    # Si el archivo está en un directorio que no existe, se crea
    Path(config.RUTA_BASE_DATOS).parent.mkdir(parents=True, exist_ok=True)

    conexion = sqlite3.connect(
        config.RUTA_BASE_DATOS,
        timeout=30,          # Espera hasta 30 segundos si la base está ocupada
    )

    # Permite leer los rows como diccionarios en vez de tuplas
    conexion.row_factory = sqlite3.Row

    # Activa las llaves foráneas para que SQLite respete las relaciones
    conexion.execute("PRAGMA foreign_keys = ON")

    return conexion


def verificar_archivo() -> None:
    """
    Revisa que el archivo de la base de datos exista y se pueda escribir.

    Si el archivo está bloqueado o el proceso no tiene permiso para
    escribirlo, se avisa con un mensaje claro. Esto pasa, por ejemplo,
    cuando el archivo quedó con permisos de otro usuario del sistema.

    Se llama al arrancar el servidor, antes de crear las tablas.
    """
    ruta = Path(config.RUTA_BASE_DATOS)

    # Se intenta crear el archivo vacío si todavía no existe
    if not ruta.exists():
        ruta.touch()

    if not os.access(ruta, os.W_OK):
        raise PermissionError(
            f"No se puede escribir en la base de datos:\n"
            f"  {ruta}\n\n"
            f"Tu usuario ({getpass.getuser()}) no tiene permiso de escritura sobre ese archivo.\n"
            f"Para arreglarlo, en una terminal ejecuta:\n"
            f"  sudo chown {getpass.getuser()}:{getpass.getuser()} {ruta}"
        )


def crear_tablas() -> None:
    """
    Crea las tablas del inventario y de las ventas si todavía no existen.
    Se llama una sola vez al arrancar el servidor.
    """
    conexion = obtener_conexion()
    try:
        # Tabla de productos del inventario
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS productos (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id          TEXT    NOT NULL,
                nombre              TEXT    NOT NULL,
                stock               INTEGER NOT NULL DEFAULT 0,
                tipo                TEXT,
                descripcion         TEXT,
                sku                 TEXT,
                precio_ves          REAL    NOT NULL DEFAULT 0,
                precio_usd          REAL    NOT NULL DEFAULT 0,
                precio_compra_ves   REAL    NOT NULL DEFAULT 0,
                precio_compra_usd   REAL    NOT NULL DEFAULT 0,
                creado_en           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                actualizado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )

        # Tabla de ventas (una fila por venta registrada)
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS ventas (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id          TEXT    NOT NULL,
                fecha               TEXT    NOT NULL,
                hora                TEXT    NOT NULL,
                metodo_pago         TEXT    NOT NULL,
                total_ves           REAL    NOT NULL DEFAULT 0,
                total_usd           REAL    NOT NULL DEFAULT 0,
                costo_total_ves     REAL    NOT NULL DEFAULT 0,
                costo_total_usd     REAL    NOT NULL DEFAULT 0,
                ganancia_ves        REAL    NOT NULL DEFAULT 0,
                ganancia_usd        REAL    NOT NULL DEFAULT 0,
                precio_dolar        REAL    NOT NULL DEFAULT 0,
                creado_en           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )

        # Tabla del detalle: qué productos se vendieron en cada venta
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS productos_vendidos (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id              TEXT    NOT NULL,
                venta_id                INTEGER NOT NULL,
                producto_id             INTEGER,
                producto_nombre         TEXT    NOT NULL,
                unidades                INTEGER NOT NULL,
                precio_unitario_ves     REAL    NOT NULL DEFAULT 0,
                precio_unitario_usd     REAL    NOT NULL DEFAULT 0,
                costo_unitario_ves      REAL    NOT NULL DEFAULT 0,
                costo_unitario_usd      REAL    NOT NULL DEFAULT 0,
                subtotal_ves            REAL    NOT NULL DEFAULT 0,
                subtotal_usd            REAL    NOT NULL DEFAULT 0,
                ganancia_ves            REAL    NOT NULL DEFAULT 0,
                ganancia_usd            REAL    NOT NULL DEFAULT 0,
                FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE,
                FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE SET NULL
            )
            """
        )

        # Tabla de preferencias del usuario (tema, auto precios, etc.)
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracion (
                usuario_id      TEXT NOT NULL,
                clave           TEXT NOT NULL,
                valor           TEXT,
                actualizado_en  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (usuario_id, clave)
            )
            """
        )

        # Tabla con el último precio del dólar conocido
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS precios_dolar (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id      TEXT NOT NULL,
                precio_ves      REAL NOT NULL,
                origen          TEXT,
                actualizado_en  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )

        conexion.commit()
    finally:
        conexion.close()


# ------------------------------------------------------------
# Migración de una base de datos vieja (sin usuario_id)
# ------------------------------------------------------------
def migrar_esquema_por_usuario() -> None:
    """
    Actualiza una base de datos creada antes de que las tablas tuvieran
    la columna "usuario_id".

    Qué hace:
      1. Revisa qué tablas existen y si ya tienen la columna "usuario_id".
      2. A las que no la tienen, les agrega la columna.
      3. Reconstruye la tabla "configuracion" para que su clave primaria
         sea (usuario_id, clave) en vez de solo "clave".

    Las filas viejas reciben usuario_id = "" (cadena vacía). No se ven en el
    uso normal de la app porque cada usuario busca con su propio id, así
    que conviene respaldar la base antes de migrar y, si hay datos viejos
    que quieras recuperar, editarlos a mano después.
    """
    conexion = obtener_conexion()
    try:
        tablas = {
            fila["name"]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        # --- 1. Agregar usuario_id donde falte ---
        tablas_con_duenio = [
            "productos",
            "ventas",
            "productos_vendidos",
            "precios_dolar",
        ]

        for tabla in tablas_con_duenio:
            if tabla not in tablas:
                continue

            columnas = {
                fila["name"]
                for fila in conexion.execute(f"PRAGMA table_info({tabla})").fetchall()
            }

            if "usuario_id" in columnas:
                continue

            print(f"[migración] Agregando columna usuario_id a la tabla {tabla}")
            conexion.execute(
                f"ALTER TABLE {tabla} ADD COLUMN usuario_id TEXT NOT NULL DEFAULT ''"
            )

        # --- 2. Reconstruir configuracion con clave (usuario_id, clave) ---
        if "configuracion" in tablas:
            columnas = {
                fila["name"]
                for fila in conexion.execute("PRAGMA table_info(configuracion)").fetchall()
            }

            necesita_reconstruir = "usuario_id" not in columnas

            if not necesita_reconstruir:
                # Ya tiene usuario_id, pero se revisa si la clave primaria
                # sigue siendo solo "clave"
                claves_primarias = [
                    fila["name"]
                    for fila in conexion.execute(
                        "PRAGMA table_info(configuracion)"
                    ).fetchall()
                    if fila["pk"]
                ]
                necesita_reconstruir = claves_primarias == ["clave"]

            if necesita_reconstruir:
                print("[migración] Reconstruyendo la tabla configuracion por usuario")

                conexion.execute("PRAGMA foreign_keys = OFF")
                conexion.execute("ALTER TABLE configuracion RENAME TO configuracion_vieja")
                conexion.execute(
                    """
                    CREATE TABLE configuracion (
                        usuario_id      TEXT NOT NULL,
                        clave           TEXT NOT NULL,
                        valor           TEXT,
                        actualizado_en  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                        PRIMARY KEY (usuario_id, clave)
                    )
                    """
                )
                # Se copia lo viejo a un usuario de relleno
                conexion.execute(
                    """
                    INSERT INTO configuracion (usuario_id, clave, valor, actualizado_en)
                    SELECT '', clave, valor, actualizado_en FROM configuracion_vieja
                    """
                )
                conexion.execute("DROP TABLE configuracion_vieja")
                conexion.execute("PRAGMA foreign_keys = ON")

        # Índices para que las consultas por usuario vaya rápido
        for tabla in ("productos", "ventas", "productos_vendidos", "precios_dolar"):
            if tabla in tablas or tabla in tablas_con_duenio:
                conexion.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{tabla}_usuario "
                    f"ON {tabla} (usuario_id)"
                )

        conexion.commit()
    finally:
        conexion.close()


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
