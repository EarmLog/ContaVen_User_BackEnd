"""
Rutas de análisis y reportes.

Guarda los datos de cada venta (fecha, hora, unidades, precio, ganancia)
para poder mostrar:
  - Productos vendidos en el día
  - Productos más vendidos
  - Ganancia total en VES y en USD
  - Gráficas por día, mes y método de pago
  - Filtros por rango de horas, días o meses

Endpoints:
  GET /api/analisis/resumen   -> todos los datos del reporte con filtros
"""

import sqlite3

from flask import Blueprint, jsonify, request

from ..database import obtener_conexion, usuario_actual
from .auth import cargar_usuario_autenticado

rutas_analisis = Blueprint("analisis", __name__, url_prefix="/api/analisis")


# ------------------------------------------------------------
# GET /api/analisis/resumen
# Reúne todas las cifras del reporte aplicando los filtros
# ------------------------------------------------------------
@rutas_analisis.get("/resumen")
def resumen_analitico():
    """
    Devuelve todo lo que necesita la sección de Análisis.
    Filtros opcionales por rango de fechas y de horas:
      desde, hasta, hora_inicio, hora_fin
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    hora_inicio = request.args.get("hora_inicio")
    hora_fin = request.args.get("hora_fin")

    # Se construye el filtro de fechas y horas, que se usa en todas las consultas.
    # Lo primero siempre es el usuario_id, para que el reporte solo muestre
    # las ventas de quien tiene la sesión iniciada.
    condiciones = ["v.usuario_id = ?"]
    valores = [usuario_actual()]

    if desde:
        condiciones.append("v.fecha >= ?")
        valores.append(desde)

    if hasta:
        condiciones.append("v.fecha <= ?")
        valores.append(hasta)

    if hora_inicio:
        condiciones.append("v.hora >= ?")
        valores.append(hora_inicio)

    if hora_fin:
        condiciones.append("v.hora <= ?")
        valores.append(hora_fin)

    texto_where = " AND ".join(condiciones)

    conexion = obtener_conexion()
    try:
        # --- 1. Totales generales del periodo ---
        # La ganancia ya está guardada en cada venta como
        # (precio de venta - precio de compra) * unidades
        totales = conexion.execute(
            f"""
            SELECT
                COUNT(*)                                   AS ventas,
                IFNULL(SUM(v.total_ves), 0)                AS ventas_ves,
                IFNULL(SUM(v.total_usd), 0)                AS ventas_usd,
                IFNULL(SUM(v.costo_total_ves), 0)          AS costo_ves,
                IFNULL(SUM(v.costo_total_usd), 0)          AS costo_usd,
                IFNULL(SUM(v.ganancia_ves), 0)             AS ganancia_ves,
                IFNULL(SUM(v.ganancia_usd), 0)             AS ganancia_usd
            FROM ventas v
            WHERE {texto_where}
            """,
            valores,
        ).fetchone()

        # --- 2. Productos más vendidos (por unidades) ---
        mas_vendidos = conexion.execute(
            f"""
            SELECT
                pv.producto_nombre,
                IFNULL(SUM(pv.unidades), 0)                AS unidades,
                IFNULL(SUM(pv.subtotal_ves), 0)            AS ingresos_ves,
                IFNULL(SUM(pv.subtotal_usd), 0)            AS ingresos_usd,
                IFNULL(SUM(pv.ganancia_ves), 0)            AS ganancia_ves,
                IFNULL(SUM(pv.ganancia_usd), 0)            AS ganancia_usd
            FROM productos_vendidos pv
            JOIN ventas v ON v.id = pv.venta_id AND v.usuario_id = pv.usuario_id
            WHERE {texto_where}
            GROUP BY pv.producto_nombre
            ORDER BY unidades DESC
            LIMIT 10
            """,
            valores,
        ).fetchall()

        # --- 3. Gráfica de ventas por día (últimos 30 días del filtro) ---
        por_dia = conexion.execute(
            f"""
            SELECT
                v.fecha                AS etiqueta,
                COUNT(*)               AS ventas,
                IFNULL(SUM(v.total_ves), 0)  AS ingresos_ves,
                IFNULL(SUM(v.total_usd), 0)  AS ingresos_usd,
                IFNULL(SUM(v.ganancia_ves), 0) AS ganancia_ves,
                IFNULL(SUM(v.ganancia_usd), 0) AS ganancia_usd
            FROM ventas v
            WHERE {texto_where}
            GROUP BY v.fecha
            ORDER BY v.fecha ASC
            LIMIT 30
            """,
            valores,
        ).fetchall()

        # --- 4. Gráfica de ventas por mes ---
        por_mes = conexion.execute(
            f"""
            SELECT
                strftime('%Y-%m', v.fecha) AS etiqueta,
                COUNT(*)                    AS ventas,
                IFNULL(SUM(v.total_ves), 0)       AS ingresos_ves,
                IFNULL(SUM(v.total_usd), 0)       AS ingresos_usd,
                IFNULL(SUM(v.ganancia_ves), 0)    AS ganancia_ves,
                IFNULL(SUM(v.ganancia_usd), 0)    AS ganancia_usd
            FROM ventas v
            WHERE {texto_where}
            GROUP BY etiqueta
            ORDER BY etiqueta ASC
            LIMIT 12
            """,
            valores,
        ).fetchall()

        # --- 5. Gráfica por hora del día ---
        por_hora = conexion.execute(
            f"""
            SELECT
                strftime('%H', v.hora) AS etiqueta,
                COUNT(*)               AS ventas,
                IFNULL(SUM(v.total_ves), 0)  AS ingresos_ves,
                IFNULL(SUM(v.ganancia_ves), 0) AS ganancia_ves
            FROM ventas v
            WHERE {texto_where}
            GROUP BY etiqueta
            ORDER BY etiqueta ASC
            """,
            valores,
        ).fetchall()

        # --- 6. Gráfica por método de pago ---
        por_metodo = conexion.execute(
            f"""
            SELECT
                v.metodo_pago         AS etiqueta,
                COUNT(*)              AS ventas,
                IFNULL(SUM(v.total_ves), 0) AS ingresos_ves,
                IFNULL(SUM(v.total_usd), 0) AS ingresos_usd
            FROM ventas v
            WHERE {texto_where}
            GROUP BY v.metodo_pago
            ORDER BY ingresos_ves DESC
            """,
            valores,
        ).fetchall()

        # --- 7. Productos con poco stock (aviso en el dashboard) ---
        stock_bajo = conexion.execute(
            """
            SELECT id, nombre, stock FROM productos
            WHERE stock <= 5 AND usuario_id = ?
            ORDER BY stock ASC LIMIT 10
            """,
            (usuario_actual(),),
        ).fetchall()

        return jsonify({
            "filtros": {
                "desde": desde,
                "hasta": hasta,
                "hora_inicio": hora_inicio,
                "hora_fin": hora_fin,
            },
            "totales": _redondear_filas(totales)[0],
            "mas_vendidos": _redondear_filas(mas_vendidos),
            "por_dia": _redondear_filas(por_dia),
            "por_mes": _redondear_filas(por_mes),
            "por_hora": _redondear_filas(por_hora),
            "por_metodo_pago": _redondear_filas(por_metodo),
            "stock_bajo": [dict(fila) for fila in stock_bajo],
        })

    finally:
        conexion.close()


# ------------------------------------------------------------
# GET /api/analisis/dia
# Muestra únicamente lo vendido hoy
# ------------------------------------------------------------
@rutas_analisis.get("/dia")
def ventas_del_dia():
    """
    Devuelve los productos que se vendieron hoy con sus unidades,
    precio y ganancia. Se usa en la pantalla de Inicio.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    hoy = request.args.get("fecha") or _fecha_de_hoy()

    # Solo las ventas del usuario que tiene la sesión iniciada
    duenio = usuario_actual()

    conexion = obtener_conexion()
    try:
        # Productos vendidos hoy, agrupados por producto
        productos_hoy = conexion.execute(
            """
            SELECT
                pv.producto_nombre,
                IFNULL(SUM(pv.unidades), 0)         AS unidades,
                pv.precio_unitario_ves,
                pv.precio_unitario_usd,
                IFNULL(SUM(pv.subtotal_ves), 0)     AS subtotal_ves,
                IFNULL(SUM(pv.subtotal_usd), 0)     AS subtotal_usd,
                IFNULL(SUM(pv.ganancia_ves), 0)     AS ganancia_ves,
                IFNULL(SUM(pv.ganancia_usd), 0)     AS ganancia_usd
            FROM productos_vendidos pv
            JOIN ventas v ON v.id = pv.venta_id AND v.usuario_id = pv.usuario_id
            WHERE v.fecha = ? AND v.usuario_id = ?
            GROUP BY pv.producto_nombre, pv.precio_unitario_ves, pv.precio_unitario_usd
            ORDER BY unidades DESC
            """,
            (hoy, duenio),
        ).fetchall()

        # Totales de hoy
        totales_hoy = conexion.execute(
            """
            SELECT
                COUNT(*)                       AS ventas,
                IFNULL(SUM(total_ves), 0)      AS ingresos_ves,
                IFNULL(SUM(total_usd), 0)      AS ingresos_usd,
                IFNULL(SUM(ganancia_ves), 0)   AS ganancia_ves,
                IFNULL(SUM(ganancia_usd), 0)   AS ganancia_usd
            FROM ventas WHERE fecha = ? AND usuario_id = ?
            """,
            (hoy, duenio),
        ).fetchone()

        return jsonify({
            "fecha": hoy,
            "productos": _redondear_filas(productos_hoy),
            "totales": _redondear_filas(totales_hoy)[0],
        })

    finally:
        conexion.close()


# ------------------------------------------------------------
# Utilidad: fecha de hoy en formato AAAA-MM-DD
# ------------------------------------------------------------
def _fecha_de_hoy() -> str:
    """Devuelve la fecha de hoy en el formato que usa la base de datos."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


# ============================================================
# Utilidad: redondear los números de las consultas
# ============================================================
def _redondear_filas(filas) -> list:
    """
    Convierte las filas de SQLite en diccionarios y redondea a 2 decimales
    todos los números, para que las sumas no muestren muchos decimales
    (por ejemplo 13.879999999999999 en vez de 13.88).
    Acepta una sola fila o una lista de filas.
    """
    # Si es una sola fila, se devuelve una lista con esa fila
    if isinstance(filas, sqlite3.Row):
        filas = [filas]

    resultado = []

    for fila in filas:
        fila_limpia = {}

        for clave in fila.keys():
            valor = fila[clave]

            # Los flotantes se redondean, los demás valores se dejan igual
            if isinstance(valor, float):
                fila_limpia[clave] = round(valor, 2)
            else:
                fila_limpia[clave] = valor

        resultado.append(fila_limpia)

    return resultado
