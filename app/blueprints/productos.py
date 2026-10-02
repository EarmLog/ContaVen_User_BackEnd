"""
Rutas del inventario de productos.

Endpoints:
  GET    /api/productos        -> lista todos los productos
  POST   /api/productos        -> crea un producto nuevo
  PUT    /api/productos/<id>   -> edita un producto
  DELETE /api/productos/<id>   -> elimina un producto
"""

import sqlite3

from flask import Blueprint, g, jsonify, request

from ..config import config
from ..database import obtener_conexion, usuario_actual
from ..utils.security import a_numero, a_texto
from .auth import cargar_usuario_autenticado

rutas_productos = Blueprint("productos", __name__, url_prefix="/api/productos")


# ------------------------------------------------------------
# GET /api/productos
# Devuelve la lista completa del inventario
# ------------------------------------------------------------
@rutas_productos.get("")
def listar_productos():
    """Trae todos los productos guardados en el SQLite local."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # Solo se traen los productos del usuario que tiene la sesión iniciada
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        filas = conexion.execute(
            """
            SELECT * FROM productos
            WHERE usuario_id = ?
            ORDER BY nombre COLLATE NOCASE ASC
            """,
            (duenio,),
        ).fetchall()

        # Se convierte cada fila de SQLite en un diccionario normal
        productos = [dict(fila) for fila in filas]
        return jsonify({"productos": productos})

    finally:
        conexion.close()


# ------------------------------------------------------------
# POST /api/productos
# Crea un producto nuevo en el inventario
# ------------------------------------------------------------
@rutas_productos.post("")
def crear_producto():
    """Recibe los datos del formulario de producto y lo guarda en SQLite."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}

    # --- Se leen y limpian los campos ---
    nombre = a_texto(datos.get("nombre")) or ""
    stock = datos.get("stock")
    tipo = a_texto(datos.get("tipo"))
    descripcion = a_texto(datos.get("descripcion"))
    sku = a_texto(datos.get("sku"))

    precio_ves = a_numero(datos.get("precio_ves"))
    precio_usd = a_numero(datos.get("precio_usd"))
    precio_compra_ves = a_numero(datos.get("precio_compra_ves"))
    precio_compra_usd = a_numero(datos.get("precio_compra_usd"))

    # --- Validaciones ---
    if not nombre:
        return jsonify({"error": "El nombre del producto es obligatorio."}), 400

    if stock is None or stock == "":
        return jsonify({"error": "El stock es obligatorio."}), 400

    try:
        stock_numero = int(stock)
        if stock_numero < 0:
            return jsonify({"error": "El stock no puede ser negativo."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "El stock debe ser un número entero."}), 400

    if precio_ves <= 0 and precio_usd <= 0:
        return jsonify({"error": "Debes colocar el precio de venta en VES o en USD."}), 400

    # Si solo viene un precio, el otro se calcula con la tasa del dólar
    precio_ves, precio_usd = _completar_precios(precio_ves, precio_usd)
    precio_compra_ves, precio_compra_usd = _completar_precios(
        precio_compra_ves, precio_compra_usd
    )

    # --- Se inserta el producto en SQLite ---
    # El usuario_id sale del token de sesión, nunca del cuerpo del pedido
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        cursor = conexion.execute(
            """
            INSERT INTO productos (
                usuario_id, nombre, stock, tipo, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                duenio,
                nombre, stock_numero, tipo, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd,
            ),
        )
        conexion.commit()

        # Se devuelve el producto recién creado
        fila = conexion.execute(
            "SELECT * FROM productos WHERE id = ? AND usuario_id = ?",
            (cursor.lastrowid, duenio),
        ).fetchone()

        return jsonify({"mensaje": "Producto agregado.", "producto": dict(fila)}), 201

    finally:
        conexion.close()


# ------------------------------------------------------------
# PUT /api/productos/<id>
# Edita un producto que ya existe
# ------------------------------------------------------------
@rutas_productos.put("/<int:id_producto>")
def editar_producto(id_producto: int):
    """Actualiza los datos de un producto existente."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}

    nombre = a_texto(datos.get("nombre")) or ""
    stock = datos.get("stock")
    tipo = a_texto(datos.get("tipo"))
    descripcion = a_texto(datos.get("descripcion"))
    sku = a_texto(datos.get("sku"))

    precio_ves = a_numero(datos.get("precio_ves"))
    precio_usd = a_numero(datos.get("precio_usd"))
    precio_compra_ves = a_numero(datos.get("precio_compra_ves"))
    precio_compra_usd = a_numero(datos.get("precio_compra_usd"))

    # --- Validaciones ---
    if not nombre:
        return jsonify({"error": "El nombre del producto es obligatorio."}), 400

    try:
        stock_numero = int(stock)
        if stock_numero < 0:
            return jsonify({"error": "El stock no puede ser negativo."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "El stock es obligatorio y debe ser un número."}), 400

    if precio_ves <= 0 and precio_usd <= 0:
        return jsonify({"error": "Debes colocar el precio de venta en VES o en USD."}), 400

    precio_ves, precio_usd = _completar_precios(precio_ves, precio_usd)
    precio_compra_ves, precio_compra_usd = _completar_precios(
        precio_compra_ves, precio_compra_usd
    )

    # --- Se actualiza el producto en SQLite ---
    # El WHERE incluye usuario_id para no poder editar productos ajenos
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        cursor = conexion.execute(
            """
            UPDATE productos SET
                nombre = ?, stock = ?, tipo = ?, descripcion = ?, sku = ?,
                precio_ves = ?, precio_usd = ?,
                precio_compra_ves = ?, precio_compra_usd = ?,
                actualizado_en = datetime('now', 'localtime')
            WHERE id = ? AND usuario_id = ?
            """,
            (
                nombre, stock_numero, tipo, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd,
                id_producto, duenio,
            ),
        )
        conexion.commit()

        # Si no se actualizó nada, el producto no existe o no es de este usuario
        if cursor.rowcount == 0:
            return jsonify({"error": "Ese producto no existe."}), 404

        fila = conexion.execute(
            "SELECT * FROM productos WHERE id = ? AND usuario_id = ?",
            (id_producto, duenio),
        ).fetchone()

        return jsonify({"mensaje": "Producto actualizado.", "producto": dict(fila)})

    finally:
        conexion.close()


# ------------------------------------------------------------
# DELETE /api/productos/<id>
# Borra un producto del inventario
# ------------------------------------------------------------
@rutas_productos.delete("/<int:id_producto>")
def eliminar_producto(id_producto: int):
    """Elimina un producto del inventario y también sus ventas ya registradas."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # El WHERE incluye usuario_id para no poder borrar productos ajenos
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        cursor = conexion.execute(
            "DELETE FROM productos WHERE id = ? AND usuario_id = ?",
            (id_producto, duenio),
        )
        conexion.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Ese producto no existe."}), 404

        return jsonify({"mensaje": "Producto eliminado."})

    finally:
        conexion.close()


# ============================================================
# Funciones de ayuda
# ============================================================
def _completar_precios(ves: float, usd: float) -> tuple[float, float]:
    """
    Si viene un precio en una moneda y el de la otra está vacío,
    calcula el que falta usando la tasa actual del dólar guardada en SQLite.
    Devuelve la pareja (precio_ves, precio_usd) ya completa.
    """
    # Si ya vienen los dos precios se devuelven tal cual
    if ves > 0 and usd > 0:
        return round(ves, 2), round(usd, 2)

    # Si solo viene VES se calcula el USD
    if ves > 0 and usd <= 0:
        tasa = obtener_tasa_dolar()
        if tasa > 0:
            return round(ves, 2), round(ves / tasa, 2)
        return round(ves, 2), 0.0

    # Si solo viene USD se calcula el VES
    if usd > 0 and ves <= 0:
        tasa = obtener_tasa_dolar()
        if tasa > 0:
            return round(usd * tasa, 2), round(usd, 2)
        return 0.0, round(usd, 2)

    # Si no vino ninguno se devuelven en cero
    return 0.0, 0.0


def obtener_tasa_dolar() -> float:
    """
    Lee la última tasa del dólar guardada en la tabla precios_dolar.
    Si no hay ninguna, usa la tasa por defecto del archivo .env.
    """
    # La tasa del dólar es la de este usuario, no la de cualquiera
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        fila = conexion.execute(
            "SELECT precio_ves FROM precios_dolar WHERE usuario_id = ? ORDER BY id DESC LIMIT 1",
            (duenio,),
        ).fetchone()

        if fila and fila["precio_ves"]:
            return float(fila["precio_ves"])

        return config.PRECIO_DOLAR_POR_DEFECTO

    finally:
        conexion.close()
