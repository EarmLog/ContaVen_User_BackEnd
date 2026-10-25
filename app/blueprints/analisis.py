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

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from ..database import a_json, fila_limpia, obtener_conexion, usuario_actual
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
    texto_where, valores = _filtro_de_ventas(
        desde, hasta, hora_inicio, hora_fin
    )

    with obtener_conexion() as conexion:
        # --- 1. Totales generales del periodo ---
        # La ganancia ya está guardada en cada venta como
        # (precio de venta - precio de compra) * unidades
        totales = conexion.execute(
            f"""
            SELECT
                COUNT(*)                                   AS ventas,
                COALESCE(SUM(v.total_ves), 0)                AS ventas_ves,
                COALESCE(SUM(v.total_usd), 0)                AS ventas_usd,
                COALESCE(SUM(v.costo_total_ves), 0)          AS costo_ves,
                COALESCE(SUM(v.costo_total_usd), 0)          AS costo_usd,
                COALESCE(SUM(v.ganancia_ves), 0)             AS ganancia_ves,
                COALESCE(SUM(v.ganancia_usd), 0)             AS ganancia_usd
            FROM ventas v
            WHERE {texto_where}
            """,
            valores,
        ).fetchone()

        # --- 2. Productos más vendidos (por unidades) ---
        # Se agrupa por producto_id (no solo por nombre) para que dos
        # productos distintos con el mismo nombre no se mezclen. También
        # se traen las fechas del producto y su última venta histórica,
        # así el reporte puede decir desde cuándo no se vende.
        mas_vendidos = conexion.execute(
            f"""
            SELECT
                pv.producto_id,
                pv.producto_nombre,
                p.sku,
                p.creado_en,
                p.actualizado_en,
                p.descuento_unidad_porcentaje,
                p.descuento_unidad_desde,
                p.descuento_bulto_porcentaje,
                COALESCE(SUM(pv.unidades), 0)                AS unidades,
                COALESCE(SUM(pv.subtotal_ves), 0)            AS ingresos_ves,
                COALESCE(SUM(pv.subtotal_usd), 0)            AS ingresos_usd,
                COALESCE(SUM(pv.ganancia_ves), 0)            AS ganancia_ves,
                COALESCE(SUM(pv.ganancia_usd), 0)            AS ganancia_usd,
                (
                    SELECT MAX(v2.fecha)
                    FROM productos_vendidos pv2
                    JOIN ventas v2
                      ON v2.id = pv2.venta_id
                     AND v2.usuario_id = pv2.usuario_id
                    WHERE pv2.usuario_id = pv.usuario_id
                      AND pv2.producto_id = pv.producto_id
                ) AS ultima_venta
            FROM productos_vendidos pv
            JOIN ventas v ON v.id = pv.venta_id AND v.usuario_id = pv.usuario_id
            LEFT JOIN productos p
              ON p.id = pv.producto_id
             AND p.usuario_id = pv.usuario_id
            WHERE {texto_where}
            GROUP BY
                pv.usuario_id, pv.producto_id, pv.producto_nombre, p.id, p.sku,
                p.creado_en, p.actualizado_en,
                p.descuento_unidad_porcentaje, p.descuento_unidad_desde,
                p.descuento_bulto_porcentaje
            ORDER BY unidades DESC
            LIMIT 10
            """,
            valores,
        ).fetchall()

        # A cada fila se le agrega cuántos días lleva sin vender. Se hace en
        # Python porque es más claro que repetir la resta de fechas en SQL.
        for fila in mas_vendidos:
            fila["dias_sin_vender"] = _dias_sin_vender(
                fila["ultima_venta"], fila["creado_en"]
            )

        # --- 2b. Todos los productos, para el selector de análisis ---
        # El selector de la pantalla necesita el id y el nombre de todos los
        # productos, no solo de los 10 más vendidos.
        productos = conexion.execute(
            """
            SELECT
                p.id,
                p.nombre,
                p.sku,
                p.marca,
                p.variante,
                p.stock,
                p.precio_ves,
                p.precio_usd,
                p.descuento_unidad_porcentaje,
                p.descuento_unidad_desde,
                p.descuento_bulto_porcentaje,
                p.creado_en,
                p.actualizado_en,
                (
                    SELECT MAX(v.fecha)
                    FROM productos_vendidos pv
                    JOIN ventas v
                      ON v.id = pv.venta_id
                     AND v.usuario_id = pv.usuario_id
                    WHERE pv.usuario_id = p.usuario_id
                      AND pv.producto_id = p.id
                ) AS ultima_venta
            FROM productos p
            WHERE p.usuario_id = %s
            ORDER BY lower(p.nombre) ASC
            """,
            (usuario_actual(),),
        ).fetchall()

        for fila in productos:
            fila["dias_sin_vender"] = _dias_sin_vender(
                fila["ultima_venta"], fila["creado_en"]
            )
            fila["nunca_vendido"] = fila["ultima_venta"] is None

        # --- 3. Gráfica de ventas por día (últimos 30 días del filtro) ---
        por_dia = conexion.execute(
            f"""
            SELECT
                v.fecha                AS etiqueta,
                COUNT(*)               AS ventas,
                COALESCE(SUM(v.total_ves), 0)  AS ingresos_ves,
                COALESCE(SUM(v.total_usd), 0)  AS ingresos_usd,
                COALESCE(SUM(v.ganancia_ves), 0) AS ganancia_ves,
                COALESCE(SUM(v.ganancia_usd), 0) AS ganancia_usd
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
                to_char(v.fecha, 'YYYY-MM') AS etiqueta,
                COUNT(*)                    AS ventas,
                COALESCE(SUM(v.total_ves), 0)       AS ingresos_ves,
                COALESCE(SUM(v.total_usd), 0)       AS ingresos_usd,
                COALESCE(SUM(v.ganancia_ves), 0)    AS ganancia_ves,
                COALESCE(SUM(v.ganancia_usd), 0)    AS ganancia_usd
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
                to_char(v.hora, 'HH24') AS etiqueta,
                COUNT(*)               AS ventas,
                COALESCE(SUM(v.total_ves), 0)  AS ingresos_ves,
                COALESCE(SUM(v.ganancia_ves), 0) AS ganancia_ves
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
                COALESCE(SUM(v.total_ves), 0) AS ingresos_ves,
                COALESCE(SUM(v.total_usd), 0) AS ingresos_usd
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
            WHERE stock <= 5 AND usuario_id = %s
            ORDER BY stock ASC LIMIT 10
            """,
            (usuario_actual(),),
        ).fetchall()

        conexion.commit()

        return jsonify({
            "filtros": {
                "desde": desde,
                "hasta": hasta,
                "hora_inicio": hora_inicio,
                "hora_fin": hora_fin,
            },
            "totales": _redondear_filas(totales)[0],
            "mas_vendidos": _redondear_filas(mas_vendidos),
            "productos": _redondear_filas(productos),
            "por_dia": _redondear_filas(por_dia),
            "por_mes": _redondear_filas(por_mes),
            "por_hora": _redondear_filas(por_hora),
            "por_metodo_pago": _redondear_filas(por_metodo),
            "stock_bajo": [fila_limpia(fila) for fila in stock_bajo],
        })


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

    with obtener_conexion() as conexion:
        # Productos vendidos hoy, agrupados por producto
        productos_hoy = conexion.execute(
            """
            SELECT
                pv.producto_nombre,
                COALESCE(SUM(pv.unidades), 0)         AS unidades,
                pv.precio_unitario_ves,
                pv.precio_unitario_usd,
                COALESCE(SUM(pv.subtotal_ves), 0)     AS subtotal_ves,
                COALESCE(SUM(pv.subtotal_usd), 0)     AS subtotal_usd,
                COALESCE(SUM(pv.ganancia_ves), 0)     AS ganancia_ves,
                COALESCE(SUM(pv.ganancia_usd), 0)     AS ganancia_usd
            FROM productos_vendidos pv
            JOIN ventas v ON v.id = pv.venta_id AND v.usuario_id = pv.usuario_id
            WHERE v.fecha = %s::date AND v.usuario_id = %s
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
                COALESCE(SUM(total_ves), 0)      AS ingresos_ves,
                COALESCE(SUM(total_usd), 0)      AS ingresos_usd,
                COALESCE(SUM(ganancia_ves), 0)   AS ganancia_ves,
                COALESCE(SUM(ganancia_usd), 0)   AS ganancia_usd
            FROM ventas WHERE fecha = %s::date AND usuario_id = %s
            """,
            (hoy, duenio),
        ).fetchone()

        conexion.commit()

        return jsonify({
            "fecha": hoy,
            "productos": _redondear_filas(productos_hoy),
            "totales": _redondear_filas(totales_hoy)[0],
        })


# ------------------------------------------------------------
# GET /api/analisis/productos-sin-vender
# Lista productos que NO se han vendido en el periodo
# ------------------------------------------------------------
@rutas_analisis.get("/productos-sin-vender")
def productos_sin_vender():
    """
    Devuelve los productos que no han tenido ninguna venta
    en el periodo especificado (o desde el inicio).
    Permite aplicar descuento a estos productos desde el frontend.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    desde = request.args.get("desde")
    hasta = request.args.get("hasta")

    # Filtro de fechas para la subconsulta que decide qué productos SÍ se
    # vendieron. Los que queden fuera de esa lista son los "sin vender".
    filtro_fechas = ""
    valores_sub = [usuario_actual()]

    if desde:
        filtro_fechas += " AND v2.fecha >= %s::date"
        valores_sub.append(desde)

    if hasta:
        filtro_fechas += " AND v2.fecha <= %s::date"
        valores_sub.append(hasta)

    # El orden de los parámetros es: el del WHERE principal, luego los de
    # la subconsulta (usuario + fechas).
    parametros = [usuario_actual()] + valores_sub

    with obtener_conexion() as conexion:
        # Productos que NO aparecen en productos_vendidos para el periodo
        filas = conexion.execute(
            f"""
            SELECT
                p.id,
                p.nombre,
                p.tipo,
                p.marca,
                p.variante,
                p.sku,
                p.stock,
                p.precio_ves,
                p.precio_usd,
                p.precio_compra_ves,
                p.precio_compra_usd,
                p.unidades_por_bulto,
                p.cantidad_mayor,
                p.precio_mayor_ves,
                p.precio_mayor_usd,
                p.descuento_unidad_porcentaje,
                p.descuento_unidad_desde,
                p.descuento_bulto_porcentaje,
                p.creado_en,
                p.actualizado_en,
                (
                    SELECT MAX(v3.fecha)
                    FROM productos_vendidos pv3
                    JOIN ventas v3
                      ON v3.id = pv3.venta_id
                     AND v3.usuario_id = pv3.usuario_id
                    WHERE pv3.usuario_id = p.usuario_id
                      AND pv3.producto_id = p.id
                ) AS ultima_venta
            FROM productos p
            WHERE p.usuario_id = %s
            AND NOT EXISTS (
                SELECT 1
                FROM productos_vendidos pv2
                JOIN ventas v2 ON v2.id = pv2.venta_id
                WHERE pv2.usuario_id = %s
                  AND pv2.producto_id = p.id
                  {filtro_fechas}
            )
            ORDER BY p.nombre ASC
            """,
            parametros,
        ).fetchall()

        # Días desde la última venta (o desde el registro si nunca se vendió)
        for fila in filas:
            fila["dias_sin_vender"] = _dias_sin_vender(
                fila["ultima_venta"], fila["creado_en"]
            )
            fila["nunca_vendido"] = fila["ultima_venta"] is None

        conexion.commit()

        return jsonify({
            "productos": _redondear_filas(filas),
            "total": len(filas),
        })


# ------------------------------------------------------------
# GET /api/analisis/producto/<id>
# Análisis detallado de un solo producto
# ------------------------------------------------------------
@rutas_analisis.get("/producto/<int:id_producto>")
def analisis_de_producto(id_producto: int):
    """
    Devuelve las ventas de un producto para las gráficas de Análisis:
      - Totales del periodo filtrado (unidades, ingresos, descuentos)
      - Serie por día (con y sin descuento)
      - Comparación histórica antes/después del primer descuento
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    hora_inicio = request.args.get("hora_inicio")
    hora_fin = request.args.get("hora_fin")
    duenio = usuario_actual()

    with obtener_conexion() as conexion:
        producto = conexion.execute(
            "SELECT * FROM productos WHERE id = %s AND usuario_id = %s",
            (id_producto, duenio),
        ).fetchone()

        if producto is None:
            return jsonify({"error": "Ese producto no existe."}), 404

        # --- Historial completo del producto (sin filtros de fecha) ---
        # Se usa para saber cuándo se vendió por primera vez, cuándo se
        # aplicó el primer descuento y promediar antes/después.
        historico = conexion.execute(
            """
            SELECT
                MIN(v.fecha) AS primera_venta,
                MAX(v.fecha) AS ultima_venta,
                MIN(v.fecha) FILTER (WHERE pv.descuento_porcentaje > 0)
                    AS primera_con_descuento,
                COALESCE(
                    SUM(pv.unidades) FILTER (WHERE pv.descuento_porcentaje > 0), 0
                ) AS unidades_con_descuento,
                COALESCE(
                    SUM(pv.unidades) FILTER (WHERE pv.descuento_porcentaje = 0), 0
                ) AS unidades_sin_descuento,
                COUNT(DISTINCT pv.venta_id) FILTER (
                    WHERE pv.descuento_porcentaje > 0
                ) AS ventas_con_descuento
            FROM productos_vendidos pv
            JOIN ventas v
              ON v.id = pv.venta_id
             AND v.usuario_id = pv.usuario_id
            WHERE pv.producto_id = %s AND pv.usuario_id = %s
            """,
            (id_producto, duenio),
        ).fetchone()

        hoy = date.today()
        primera_con_descuento = historico["primera_con_descuento"]

        comparacion = {
            "aplica": primera_con_descuento is not None,
            "primera_venta": a_json(historico["primera_venta"]),
            "primera_con_descuento": a_json(primera_con_descuento),
            "unidades_con_descuento": int(historico["unidades_con_descuento"] or 0),
            "unidades_sin_descuento": int(historico["unidades_sin_descuento"] or 0),
            "ventas_con_descuento": int(historico["ventas_con_descuento"] or 0),
            "dias_antes": None,
            "unidades_antes": 0,
            "promedio_antes": None,
            "dias_despues": None,
            "unidades_despues": 0,
            "promedio_despues": None,
            "aumento_porcentaje": None,
        }

        # Solo se puede comparar si alguna venta tuvo descuento
        if primera_con_descuento:
            antes = conexion.execute(
                """
                SELECT COALESCE(SUM(pv.unidades), 0) AS unidades
                FROM productos_vendidos pv
                JOIN ventas v
                  ON v.id = pv.venta_id
                 AND v.usuario_id = pv.usuario_id
                WHERE pv.producto_id = %s
                  AND pv.usuario_id = %s
                  AND v.fecha < %s
                """,
                (id_producto, duenio, primera_con_descuento),
            ).fetchone()

            despues = conexion.execute(
                """
                SELECT COALESCE(SUM(pv.unidades), 0) AS unidades
                FROM productos_vendidos pv
                JOIN ventas v
                  ON v.id = pv.venta_id
                 AND v.usuario_id = pv.usuario_id
                WHERE pv.producto_id = %s
                  AND pv.usuario_id = %s
                  AND v.fecha >= %s
                """,
                (id_producto, duenio, primera_con_descuento),
            ).fetchone()

            primera_venta = historico["primera_venta"]
            # Se cuenta al menos 1 día para no dividir entre cero cuando la
            # primera venta y el primer descuento fueron el mismo día.
            dias_antes = (
                max((primera_con_descuento - primera_venta).days, 1)
                if primera_venta
                else 1
            )
            dias_despues = max((hoy - primera_con_descuento).days + 1, 1)
            unidades_antes = int(antes["unidades"] or 0)
            unidades_despues = int(despues["unidades"] or 0)
            promedio_antes = round(unidades_antes / dias_antes, 2)
            promedio_despues = round(unidades_despues / dias_despues, 2)

            aumento = None
            if promedio_antes > 0:
                aumento = round(
                    ((promedio_despues - promedio_antes) / promedio_antes) * 100, 2
                )

            comparacion.update({
                "dias_antes": dias_antes,
                "unidades_antes": unidades_antes,
                "promedio_antes": promedio_antes,
                "dias_despues": dias_despues,
                "unidades_despues": unidades_despues,
                "promedio_despues": promedio_despues,
                "aumento_porcentaje": aumento,
            })

        # --- Serie por día del periodo filtrado ---
        texto_where, valores = _filtro_de_ventas(
            desde, hasta, hora_inicio, hora_fin
        )
        filas_dia = conexion.execute(
            f"""
            SELECT
                v.fecha AS etiqueta,
                COALESCE(SUM(pv.unidades), 0) AS unidades,
                COALESCE(
                    SUM(pv.unidades) FILTER (WHERE pv.descuento_porcentaje > 0), 0
                ) AS unidades_con_descuento,
                COALESCE(
                    SUM(pv.unidades) FILTER (WHERE pv.descuento_porcentaje = 0), 0
                ) AS unidades_sin_descuento,
                COALESCE(SUM(pv.subtotal_ves), 0) AS ingresos_ves,
                COALESCE(SUM(pv.subtotal_usd), 0) AS ingresos_usd,
                COALESCE(SUM(pv.ganancia_ves), 0) AS ganancia_ves,
                COALESCE(SUM(pv.ganancia_usd), 0) AS ganancia_usd,
                COUNT(DISTINCT pv.venta_id) AS ventas
            FROM productos_vendidos pv
            JOIN ventas v
              ON v.id = pv.venta_id
             AND v.usuario_id = pv.usuario_id
            WHERE {texto_where} AND pv.producto_id = %s
            GROUP BY v.fecha
            ORDER BY v.fecha ASC
            """,
            valores + [id_producto],
        ).fetchall()

        # Se agregan los días sin ventas en cero para que la gráfica muestre
        # los huecos reales y no una línea que salta de un día a otro.
        por_dia = _completar_dias(filas_dia, desde, hasta)

        resumen = {
            "unidades": sum(int(fila["unidades"] or 0) for fila in por_dia),
            "unidades_con_descuento": sum(
                int(fila["unidades_con_descuento"] or 0) for fila in por_dia
            ),
            "unidades_sin_descuento": sum(
                int(fila["unidades_sin_descuento"] or 0) for fila in por_dia
            ),
            "ingresos_ves": round(
                sum(float(fila["ingresos_ves"] or 0) for fila in por_dia), 2
            ),
            "ingresos_usd": round(
                sum(float(fila["ingresos_usd"] or 0) for fila in por_dia), 2
            ),
            "ganancia_ves": round(
                sum(float(fila["ganancia_ves"] or 0) for fila in por_dia), 2
            ),
            "ganancia_usd": round(
                sum(float(fila["ganancia_usd"] or 0) for fila in por_dia), 2
            ),
            "ventas": sum(int(fila["ventas"] or 0) for fila in por_dia),
            "dias_con_ventas": sum(
                1 for fila in por_dia if int(fila["unidades"] or 0) > 0
            ),
            "primera_venta": a_json(historico["primera_venta"]),
            "ultima_venta": a_json(historico["ultima_venta"]),
            "primera_con_descuento": a_json(primera_con_descuento),
            "dias_sin_vender": _dias_sin_vender(
                historico["ultima_venta"], producto.get("creado_en")
            ),
            "nunca_vendido": historico["ultima_venta"] is None,
        }

        conexion.commit()

        return jsonify({
            "producto": fila_limpia(producto),
            "resumen": resumen,
            "comparacion": comparacion,
            "por_dia": _redondear_filas(por_dia),
        })


# ------------------------------------------------------------
# Utilidad: construir el filtro de ventas (usuario, fecha y hora)
# ------------------------------------------------------------
def _filtro_de_ventas(desde, hasta, hora_inicio, hora_fin):
    """
    Arma el WHERE que comparten todas las consultas de ventas.

    Siempre empieza por el usuario de la sesión. Las fechas y horas se
    comparan en la base con %s::date y %s::time, y no en Python.
    """
    condiciones = ["v.usuario_id = %s"]
    valores = [usuario_actual()]

    if desde:
        condiciones.append("v.fecha >= %s::date")
        valores.append(desde)

    if hasta:
        condiciones.append("v.fecha <= %s::date")
        valores.append(hasta)

    if hora_inicio:
        condiciones.append("v.hora >= %s::time")
        valores.append(hora_inicio)

    if hora_fin:
        condiciones.append("v.hora <= %s::time")
        valores.append(hora_fin)

    return " AND ".join(condiciones), valores


# ------------------------------------------------------------
# Utilidad: días transcurridos desde la última venta (o el registro)
# ------------------------------------------------------------
def _dias_sin_vender(ultima_venta, creado_en=None):
    """
    Devuelve cuántos días lleva un producto sin venderse.

    Si nunca se vendió, se cuenta desde que se registró en el inventario.
    Así una lista de productos sin vender puede decir "registrado hace X días".
    """
    hoy = date.today()

    if ultima_venta:
        return (hoy - ultima_venta).days

    if creado_en:
        base = creado_en.date() if isinstance(creado_en, datetime) else creado_en
        return (hoy - base).days

    return None


# ------------------------------------------------------------
# Utilidad: completar con cero los días sin ventas
# ------------------------------------------------------------
def _completar_dias(filas, desde, hasta):
    """
    Devuelve una fila por cada día del periodo, aunque no haya ventas.

    Se limita a periodos de hasta 366 días para no devolver listas enormes
    si alguien pide varios años en el filtro.
    """
    if not desde or not hasta:
        return filas

    try:
        inicio = date.fromisoformat(desde)
        fin = date.fromisoformat(hasta)
    except ValueError:
        return filas

    if fin < inicio or (fin - inicio).days > 366:
        return filas

    por_fecha = {fila["etiqueta"]: fila for fila in filas}
    resultado = []
    dia = inicio

    while dia <= fin:
        fila = por_fecha.get(dia)

        if fila is None:
            fila = {
                "etiqueta": dia,
                "unidades": 0,
                "unidades_con_descuento": 0,
                "unidades_sin_descuento": 0,
                "ingresos_ves": 0,
                "ingresos_usd": 0,
                "ganancia_ves": 0,
                "ganancia_usd": 0,
                "ventas": 0,
            }

        resultado.append(fila)
        dia += timedelta(days=1)

    return resultado


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
    Convierte las filas de Postgres en diccionarios y redondea a 2 decimales
    todos los números, para que las sumas no muestren muchos decimales
    (por ejemplo 13.879999999999999 en vez de 13.88).

    Postgres devuelve los "numeric" como Decimal y las fechas como date/time,
    así que también se pasan por a_json() para que jsonify pueda escribirlos.

    Acepta una sola fila (dict) o una lista de filas.
    """
    # Si es una sola fila, se devuelve una lista con esa fila
    if isinstance(filas, dict):
        filas = [filas]

    resultado = []

    for fila in filas:
        valores = {}

        for clave, valor in fila.items():
            # Los flotantes se redondean a 2 decimales; los Decimal (numeric)
            # y las fechas los resuelve a_json()
            if isinstance(valor, float):
                valores[clave] = round(valor, 2)
            else:
                valores[clave] = a_json(valor)

        resultado.append(valores)

    return resultado
