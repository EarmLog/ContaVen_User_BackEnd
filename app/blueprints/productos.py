"""
Rutas del inventario de productos.

Endpoints:
  GET    /api/productos        -> lista todos los productos
  POST   /api/productos        -> crea un producto nuevo
  PUT    /api/productos/<id>   -> edita un producto
  DELETE /api/productos/<id>   -> elimina un producto
"""

import unicodedata

from flask import Blueprint, jsonify, request

from ..config import config
from ..database import fila_limpia, obtener_conexion, usuario_actual
from ..utils.security import a_numero, a_texto, entero_opcion
from .auth import cargar_usuario_autenticado

rutas_productos = Blueprint("productos", __name__, url_prefix="/api/productos")


# ------------------------------------------------------------
# GET /api/productos
# Devuelve la lista completa del inventario
# ------------------------------------------------------------
@rutas_productos.get("")
def listar_productos():
    """Trae todos los productos guardados en Postgres."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # Solo se traen los productos del usuario que tiene la sesión iniciada
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        filas = conexion.execute(
            """
            SELECT * FROM productos
            WHERE usuario_id = %s
            ORDER BY lower(nombre) ASC
            """,
            (duenio,),
        ).fetchall()

        productos = [fila_limpia(fila) for fila in filas]
        return jsonify({"productos": productos})


# ------------------------------------------------------------
# Generador de SKU automático
# ------------------------------------------------------------
def _limpiar_para_sku(texto):
    """Deja solo letras y números sin acentos, para armar el SKU."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "")
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return "".join(c for c in sin_acentos.upper() if c.isalnum())


def _generar_sku(conexion, nombre, tipo="", marca="", variante="", duenio=None):
    """
    Genera un SKU automático para un producto nuevo.

    El SKU se arma con:
      - las primeras 3 letras del nombre (sin espacios ni símbolos),
      - las primeras 3 letras de la marca, si existe,
      - las primeras 3 letras de la variante, si existe,
      - o las primeras 3 letras del tipo, si no hay marca/variante,
      - y un número consecutivo que crece con cada producto de la misma base.
    """
    # Se toman letras y números del nombre (se descartan espacios y símbolos)
    limpio = _limpiar_para_sku(nombre)
    base = limpio[:3] or "PRD"

    # Prioridad: marca -> variante -> tipo
    extra = _limpiar_para_sku(marca)
    if not extra:
        extra = _limpiar_para_sku(variante)
    if not extra:
        extra = _limpiar_para_sku(tipo)

    if extra:
        base += "-" + extra[:3]

    # Se buscan los SKU que ya existen para este usuario con esta misma base
    filas = conexion.execute(
        "SELECT sku FROM productos WHERE usuario_id = %s AND sku LIKE %s",
        (duenio, base + "-%"),
    ).fetchall()

    # Se guardan los números ya usados
    numeros_usados = set()
    for fila in filas:
        sku_existente = fila[0] if fila else ""
        if sku_existente and "-" in sku_existente:
            try:
                numeros_usados.add(int(sku_existente.rsplit("-", 1)[-1]))
            except (ValueError, IndexError):
                pass

    # Se busca el primer número libre
    contador = 1
    while contador in numeros_usados:
        contador += 1

    return f"{base}-{contador:03d}"


# ------------------------------------------------------------
# POST /api/productos
# Crea un producto nuevo en el inventario
# ------------------------------------------------------------
@rutas_productos.post("")
def crear_producto():
    """Recibe los datos del formulario de producto y lo guarda en Postgres."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}

    # --- Se leen y limpian los campos ---
    nombre = a_texto(datos.get("nombre")) or ""
    stock = datos.get("stock")
    tipo = a_texto(datos.get("tipo"))
    marca = a_texto(datos.get("marca"))
    variante = a_texto(datos.get("variante"))
    descripcion = a_texto(datos.get("descripcion"))
    sku = a_texto(datos.get("sku"))

    precio_ves = a_numero(datos.get("precio_ves"))
    precio_usd = a_numero(datos.get("precio_usd"))
    precio_compra_ves = a_numero(datos.get("precio_compra_ves"))
    precio_compra_usd = a_numero(datos.get("precio_compra_usd"))

    # --- Campos de bultos y precio al mayor (opcionales) ---
    unidades_por_bulto = entero_opcion(datos.get("unidades_por_bulto")) or 1
    cantidad_mayor = entero_opcion(datos.get("cantidad_mayor")) or 1
    precio_mayor_ves = a_numero(datos.get("precio_mayor_ves"))
    precio_mayor_usd = a_numero(datos.get("precio_mayor_usd"))

    # --- Campos de descuento (opcionales) ---
    descuento_unidad_porcentaje = round(a_numero(datos.get("descuento_unidad_porcentaje")), 2)
    descuento_unidad_desde = entero_opcion(datos.get("descuento_unidad_desde")) or 1
    descuento_bulto_porcentaje = round(a_numero(datos.get("descuento_bulto_porcentaje")), 2)

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

    if unidades_por_bulto < 1:
        return jsonify({"error": "Las unidades por bulto deben ser al menos 1."}), 400

    if cantidad_mayor < 1:
        return jsonify({"error": "La cantidad mínima al mayor debe ser al menos 1."}), 400

    if not 0 <= descuento_unidad_porcentaje <= 100:
        return jsonify({"error": "El descuento por unidad debe estar entre 0 y 100."}), 400

    if descuento_unidad_desde < 1:
        return jsonify(
            {"error": "La cantidad mínima para el descuento por unidad debe ser al menos 1."}
        ), 400

    if not 0 <= descuento_bulto_porcentaje <= 100:
        return jsonify({"error": "El descuento por bulto debe estar entre 0 y 100."}), 400

    # Si solo viene un precio, el otro se calcula con la tasa del dólar
    precio_ves, precio_usd = _completar_precios(precio_ves, precio_usd)
    precio_compra_ves, precio_compra_usd = _completar_precios(
        precio_compra_ves, precio_compra_usd
    )

    # El precio al mayor también se completa si se colocó al menos uno.
    # Si no se colocó ninguno, se queda en cero (no se vende al mayor).
    precio_mayor_ves, precio_mayor_usd = _completar_precios_mayor(
        precio_mayor_ves, precio_mayor_usd
    )

    # --- Se inserta el producto en Postgres ---
    # El usuario_id sale del token de sesión, nunca del cuerpo del pedido
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        # Generar SKU automático si no se proporciona
        if not sku:
            sku = _generar_sku(conexion, nombre, tipo, marca, variante, duenio)
        
        # RETURNING devuelve la fila ya guardada, sin necesidad de consultarla
        fila = conexion.execute(
            """
            INSERT INTO productos (
                usuario_id, nombre, stock, tipo, marca, variante, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd,
                unidades_por_bulto, cantidad_mayor, precio_mayor_ves, precio_mayor_usd,
                descuento_unidad_porcentaje, descuento_unidad_desde, descuento_bulto_porcentaje
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                duenio,
                nombre, stock_numero, tipo, marca, variante, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd,
                unidades_por_bulto, cantidad_mayor, precio_mayor_ves, precio_mayor_usd,
                descuento_unidad_porcentaje, descuento_unidad_desde, descuento_bulto_porcentaje,
            ),
        ).fetchone()

        conexion.commit()

        return jsonify({"mensaje": "Producto agregado.", "producto": fila_limpia(fila)}), 201


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
    marca = a_texto(datos.get("marca"))
    variante = a_texto(datos.get("variante"))
    descripcion = a_texto(datos.get("descripcion"))
    sku = a_texto(datos.get("sku"))  # Puede estar vacío, se generará automáticamente

    precio_ves = a_numero(datos.get("precio_ves"))
    precio_usd = a_numero(datos.get("precio_usd"))
    precio_compra_ves = a_numero(datos.get("precio_compra_ves"))
    precio_compra_usd = a_numero(datos.get("precio_compra_usd"))

    # --- Campos de bultos y precio al mayor (opcionales) ---
    unidades_por_bulto = entero_opcion(datos.get("unidades_por_bulto")) or 1
    cantidad_mayor = entero_opcion(datos.get("cantidad_mayor")) or 1
    precio_mayor_ves = a_numero(datos.get("precio_mayor_ves"))
    precio_mayor_usd = a_numero(datos.get("precio_mayor_usd"))

    # --- Campos de descuento (opcionales) ---
    descuento_unidad_porcentaje = round(a_numero(datos.get("descuento_unidad_porcentaje")), 2)
    descuento_unidad_desde = entero_opcion(datos.get("descuento_unidad_desde")) or 1
    descuento_bulto_porcentaje = round(a_numero(datos.get("descuento_bulto_porcentaje")), 2)

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

    if unidades_por_bulto < 1:
        return jsonify({"error": "Las unidades por bulto deben ser al menos 1."}), 400

    if cantidad_mayor < 1:
        return jsonify({"error": "La cantidad mínima al mayor debe ser al menos 1."}), 400

    if not 0 <= descuento_unidad_porcentaje <= 100:
        return jsonify({"error": "El porcentaje de descuento por unidad debe estar entre 0 y 100."}), 400

    if descuento_unidad_desde < 1:
        return jsonify({"error": "La cantidad mínima para el descuento por unidad debe ser al menos 1."}), 400

    if not 0 <= descuento_bulto_porcentaje <= 100:
        return jsonify({"error": "El porcentaje de descuento por bulto debe estar entre 0 y 100."}), 400

    precio_ves, precio_usd = _completar_precios(precio_ves, precio_usd)
    precio_compra_ves, precio_compra_usd = _completar_precios(
        precio_compra_ves, precio_compra_usd
    )
    precio_mayor_ves, precio_mayor_usd = _completar_precios_mayor(
        precio_mayor_ves, precio_mayor_usd
    )

    # --- Se actualiza el producto en Postgres ---
    # El WHERE incluye usuario_id para no poder editar productos ajenos.
    # "actualizado_en" lo pone un trigger de la base, no hace falta aquí.
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        if not sku:
            sku = _generar_sku(conexion, nombre, tipo, marca, variante, duenio)
        fila = conexion.execute(
            """
            UPDATE productos SET
                nombre = %s, stock = %s, tipo = %s, marca = %s, variante = %s,
                descripcion = %s, sku = %s,
                precio_ves = %s, precio_usd = %s,
                precio_compra_ves = %s, precio_compra_usd = %s,
                unidades_por_bulto = %s, cantidad_mayor = %s,
                precio_mayor_ves = %s, precio_mayor_usd = %s,
                descuento_unidad_porcentaje = %s, descuento_unidad_desde = %s,
                descuento_bulto_porcentaje = %s
            WHERE id = %s AND usuario_id = %s
            RETURNING *
            """,
            (
                nombre, stock_numero, tipo, marca, variante, descripcion, sku,
                precio_ves, precio_usd,
                precio_compra_ves, precio_compra_usd,
                unidades_por_bulto, cantidad_mayor,
                precio_mayor_ves, precio_mayor_usd,
                descuento_unidad_porcentaje, descuento_unidad_desde,
                descuento_bulto_porcentaje,
                id_producto, duenio,
            ),
        ).fetchone()

        conexion.commit()

        # Si no se actualizó nada, el producto no existe o no es de este usuario
        if fila is None:
            return jsonify({"error": "Ese producto no existe."}), 404

        return jsonify({"mensaje": "Producto actualizado.", "producto": fila_limpia(fila)})


# ------------------------------------------------------------
# DELETE /api/productos/<id>
# Borra un producto del inventario
# ------------------------------------------------------------
@rutas_productos.delete("/<int:id_producto>")
def eliminar_producto(id_producto: int):
    """
    Elimina un producto del inventario.

    Las ventas ya registradas NO se borran (el historial de ganancias se
    conserva). Lo que pasa es que en productos_vendidos el producto_id
    queda en NULL y el nombre que se guardó sigue ahí como respaldo.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # El WHERE incluye usuario_id para no poder borrar productos ajenos
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        cursor = conexion.execute(
            "DELETE FROM productos WHERE id = %s AND usuario_id = %s",
            (id_producto, duenio),
        )
        conexion.commit()

        if cursor.rowcount == 0:
            return jsonify({"error": "Ese producto no existe."}), 404

        return jsonify({"mensaje": "Producto eliminado."})


# ============================================================
# Funciones de ayuda
# ============================================================
def _completar_precios(ves: float, usd: float) -> tuple[float, float]:
    """
    Si viene un precio en una moneda y el de la otra está vacío,
    calcula el que falta usando la tasa actual del dólar guardada en la base.
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


def _completar_precios_mayor(ves: float, usd: float) -> tuple[float, float]:
    """
    Igual que _completar_precios, pero respetando que el precio al mayor
    es OPCIONAL: si no se colocó ninguno de los dos, se deja en cero para
    que quede claro que ese producto no se vende al mayor.
    """
    # Si no se colocó ningún precio al mayor, no se calcula nada
    if ves <= 0 and usd <= 0:
        return 0.0, 0.0

    return _completar_precios(ves, usd)


def obtener_tasa_dolar() -> float:
    """
    Lee la última tasa del dólar guardada en la tabla precios_dolar.
    Si no hay ninguna, usa la tasa por defecto del archivo .env.
    """
    # La tasa del dólar es la de este usuario, no la de cualquiera
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT precio_ves FROM precios_dolar WHERE usuario_id = %s ORDER BY id DESC LIMIT 1",
            (duenio,),
        ).fetchone()

        conexion.commit()

    if fila and fila["precio_ves"]:
        return float(fila["precio_ves"])

    return config.PRECIO_DOLAR_POR_DEFECTO