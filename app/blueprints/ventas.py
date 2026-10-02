"""
Rutas del punto de venta (POS).

Endpoints:
  POST /api/ventas            -> registra una venta y descuenta el stock
  GET  /api/ventas            -> lista las ventas con filtros por fecha
  GET  /api/ventas/<id>       -> muestra el detalle de una venta
"""

import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..database import obtener_conexion, usuario_actual
from .auth import cargar_usuario_autenticado
from .productos import obtener_tasa_dolar

rutas_ventas = Blueprint("ventas", __name__, url_prefix="/api/ventas")

# Métodos de pago permitidos en el POS
METODOS_PAGO = ("efectivo", "punto", "pagomovil", "app")


# ------------------------------------------------------------
# POST /api/ventas
# Registra la venta, guarda el detalle y resta el stock
# ------------------------------------------------------------
@rutas_ventas.post("")
def registrar_venta():
    """
    Recibe la lista de productos del carrito y el método de pago.
    Guarda la venta en la tabla ventas y el detalle en productos_vendidos,
    y descuenta el stock de cada producto en una sola transacción.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}
    items = datos.get("productos") or []
    metodo_pago = (datos.get("metodo_pago") or "").strip().lower()

    # --- Validaciones ---
    if not items:
        return jsonify({"error": "La venta está vacía. Agrega al menos un producto."}), 400

    if metodo_pago not in METODOS_PAGO:
        return jsonify(
            {"error": "El método de pago debe ser: efectivo, punto, pagomovil o app."}
        ), 400

    # La venta se guarda con el id del dueño, tomado del token de sesión
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        # Se empieza una transacción para que todo se guarde junto
        conexion.execute("BEGIN")

        ahora = datetime.now()
        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")
        tasa_dolar = obtener_tasa_dolar()

        # Primero se crea la cabecera de la venta vacía para tener su id,
        # y al final se le ponen los totales ya calculados.
        cursor = conexion.execute(
            """
            INSERT INTO ventas (usuario_id, fecha, hora, metodo_pago, precio_dolar)
            VALUES (?, ?, ?, ?, ?)
            """,
            (duenio, fecha, hora, metodo_pago, tasa_dolar),
        )
        venta_id = cursor.lastrowid

        # Se acumulan los totales de toda la venta
        total_ves = 0.0
        total_usd = 0.0
        costo_total_ves = 0.0
        costo_total_usd = 0.0

        # Se recorre cada producto del carrito
        for item in items:
            producto_id = item.get("producto_id")
            unidades = int(item.get("unidades") or 0)

            if unidades <= 0:
                raise ValueError("Las unidades deben ser mayores a cero.")

            # Se busca el producto para tomar sus precios del inventario.
            # El usuario_id va en el WHERE para no vender productos ajenos.
            producto = conexion.execute(
                "SELECT * FROM productos WHERE id = ? AND usuario_id = ?",
                (producto_id, duenio),
            ).fetchone()

            if not producto:
                raise ValueError("Uno de los productos ya no existe en el inventario.")

            if producto["stock"] < unidades:
                raise ValueError(
                    f"No hay stock suficiente de «{producto['nombre']}». "
                    f"Disponible: {producto['stock']}."
                )

            # Se calculan los valores de la línea de venta
            precio_unitario_ves = float(producto["precio_ves"])
            precio_unitario_usd = float(producto["precio_usd"])
            costo_unitario_ves = float(producto["precio_compra_ves"])
            costo_unitario_usd = float(producto["precio_compra_usd"])

            subtotal_ves = round(precio_unitario_ves * unidades, 2)
            subtotal_usd = round(precio_unitario_usd * unidades, 2)
            ganancia_ves = round((precio_unitario_ves - costo_unitario_ves) * unidades, 2)
            ganancia_usd = round((precio_unitario_usd - costo_unitario_usd) * unidades, 2)

            # Se guarda el detalle de la venta
            conexion.execute(
                """
                INSERT INTO productos_vendidos (
                    usuario_id, venta_id, producto_id, producto_nombre, unidades,
                    precio_unitario_ves, precio_unitario_usd,
                    costo_unitario_ves, costo_unitario_usd,
                    subtotal_ves, subtotal_usd, ganancia_ves, ganancia_usd
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    duenio, venta_id, producto_id, producto["nombre"], unidades,
                    precio_unitario_ves, precio_unitario_usd,
                    costo_unitario_ves, costo_unitario_usd,
                    subtotal_ves, subtotal_usd, ganancia_ves, ganancia_usd,
                ),
            )

            # Se descuenta el stock del producto
            conexion.execute(
                "UPDATE productos SET stock = stock - ?, actualizado_en = datetime('now', 'localtime') WHERE id = ? AND usuario_id = ?",
                (unidades, producto_id, duenio),
            )

            # Se suman los totales de la venta
            total_ves += subtotal_ves
            total_usd += subtotal_usd
            costo_total_ves += costo_unitario_ves * unidades
            costo_total_usd += costo_unitario_usd * unidades

        # Se guarda la cabecera de la venta
        total_ves = round(total_ves, 2)
        total_usd = round(total_usd, 2)
        costo_total_ves = round(costo_total_ves, 2)
        costo_total_usd = round(costo_total_usd, 2)

        # Se completan los totales en la cabecera de la venta ya creada
        conexion.execute(
            """
            UPDATE ventas SET
                total_ves = ?, total_usd = ?,
                costo_total_ves = ?, costo_total_usd = ?,
                ganancia_ves = ?, ganancia_usd = ?
            WHERE id = ? AND usuario_id = ?
            """,
            (
                total_ves, total_usd,
                costo_total_ves, costo_total_usd,
                round(total_ves - costo_total_ves, 2),
                round(total_usd - costo_total_usd, 2),
                venta_id, duenio,
            ),
        )

        # Se confirma la transacción
        conexion.commit()

        return jsonify({
            "mensaje": "¡Venta registrada!",
            "venta": {
                "id": venta_id,
                "fecha": fecha,
                "hora": hora,
                "metodo_pago": metodo_pago,
                "total_ves": total_ves,
                "total_usd": total_usd,
                "ganancia_ves": round(total_ves - costo_total_ves, 2),
                "ganancia_usd": round(total_usd - costo_total_usd, 2),
            },
        }), 201

    except ValueError as error_de_negocio:
        # Si algo sale mal se deshace la transacción y no queda nada a medias
        conexion.rollback()
        return jsonify({"error": str(error_de_negocio)}), 400

    finally:
        conexion.close()


# ------------------------------------------------------------
# GET /api/ventas
# Lista las ventas aplicando los filtros de fecha que envíe el frontend
# ------------------------------------------------------------
@rutas_ventas.get("")
def listar_ventas():
    """
    Devuelve la lista de ventas. Acepta filtros opcionales:
      desde, hasta  -> fechas en formato AAAA-MM-DD
      hora_inicio, hora_fin -> horas en formato HH:MM
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    hora_inicio = request.args.get("hora_inicio")
    hora_fin = request.args.get("hora_fin")

    # Se arma la parte del WHERE poco a poco según los filtros que vengan.
    # Lo primero siempre es el usuario_id, para ver solo sus ventas.
    condiciones = ["usuario_id = ?"]
    valores = [usuario_actual()]

    if desde:
        condiciones.append("fecha >= ?")
        valores.append(desde)

    if hasta:
        condiciones.append("fecha <= ?")
        valores.append(hasta)

    if hora_inicio:
        condiciones.append("hora >= ?")
        valores.append(hora_inicio)

    if hora_fin:
        condiciones.append("hora <= ?")
        valores.append(hora_fin)

    texto_where = " AND ".join(condiciones)

    conexion = obtener_conexion()
    try:
        filas = conexion.execute(
            f"SELECT * FROM ventas WHERE {texto_where} ORDER BY id DESC",
            valores,
        ).fetchall()

        ventas = [dict(fila) for fila in filas]
        return jsonify({"ventas": ventas})

    finally:
        conexion.close()


# ------------------------------------------------------------
# GET /api/ventas/<id>
# Muestra el detalle de una venta con los productos que se vendieron
# ------------------------------------------------------------
@rutas_ventas.get("/<int:id_venta>")
def detalle_venta(id_venta: int):
    """Devuelve una venta y la lista de productos incluidos en ella."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # El usuario_id va en el WHERE para no poder ver ventas ajenas
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        venta = conexion.execute(
            "SELECT * FROM ventas WHERE id = ? AND usuario_id = ?",
            (id_venta, duenio),
        ).fetchone()

        if not venta:
            return jsonify({"error": "Esa venta no existe."}), 404

        detalles = conexion.execute(
            """
            SELECT * FROM productos_vendidos
            WHERE venta_id = ? AND usuario_id = ?
            ORDER BY id ASC
            """,
            (id_venta, duenio),
        ).fetchall()

        return jsonify({
            "venta": dict(venta),
            "productos": [dict(fila) for fila in detalles],
        })

    finally:
        conexion.close()
