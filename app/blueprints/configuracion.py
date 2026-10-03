"""
Rutas de configuración y del precio del dólar.

Endpoints:
  GET  /api/configuracion          -> lee los ajustes guardados
  PUT  /api/configuracion          -> guarda los ajustes
  GET  /api/dolar                  -> devuelve el precio actual del dólar
  PUT  /api/dolar                  -> actualiza el precio del dólar
  POST /api/dolar/actualizar       -> consulta la tasa nueva por internet
  POST /api/dolar/convertir        -> convierte un monto entre USD y VES
  GET  /api/dolar/historico        -> historial de tasas guardadas
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from ..database import fila_limpia, obtener_conexion, usuario_actual
from ..config import config
from .auth import cargar_usuario_autenticado
from ..services.tipos_cambio import convertir, consultar_tasa_dolar

rutas_config = Blueprint("configuracion", __name__, url_prefix="/api")


# Valores por defecto de los ajustes de la app
AJUSTES_POR_DEFECTO = {
    "tema": "claro",                # "claro" u "oscuro"
    # La actualización automática del dólar empieza activada, para que la
    # app siempre muestre la tasa al día sin que el usuario tenga que hacer nada
    "actualizar_precios_auto": "1",  # "1" si se quiere actualizar solo
    "nombre_negocio": "Mi negocio",
}


# ------------------------------------------------------------
# Utilidades internas para manejo del precio del dólar
# ------------------------------------------------------------
def _guardar_tasa(precio_ves: float, origen: str) -> None:
    """Guarda una tasa nueva en el historial del usuario."""
    with obtener_conexion() as conexion:
        conexion.execute(
            "INSERT INTO precios_dolar (usuario_id, precio_ves, origen) VALUES (%s, %s, %s)",
            (usuario_actual(), precio_ves, origen),
        )
        conexion.commit()


def _ultima_tasa() -> dict | None:
    """Trae la última tasa guardada del usuario, con su fecha."""
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT precio_ves, origen, actualizado_en FROM precios_dolar WHERE usuario_id = %s ORDER BY id DESC LIMIT 1",
            (usuario_actual(),),
        ).fetchone()

        conexion.commit()

    return fila_limpia(fila) if fila else None


def _tasa_esta_vieja(fecha_guardada) -> bool:
    """
    Dice si la tasa guardada ya tiene la edad suficiente como para
    volver a consultarla por internet.

    Postgres devuelve "actualizado_en" como datetime, no como texto, así que
    se acepta cualquiera de los dos por si acaso.
    """
    if not fecha_guardada:
        return True

    minutos = config.MINUTOS_ACTUALIZACION_DOLAR
    if minutos <= 0:
        return False

    try:
        if isinstance(fecha_guardada, datetime):
            guardada = fecha_guardada.replace(tzinfo=None)
        else:
            # Por si viniera como texto "AAAA-MM-DD HH:MM:SS"
            guardada = datetime.strptime(str(fecha_guardada), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        # Si no se entiende la fecha, mejor refrescar antes que mostrar algo viejo
        return True

    return (datetime.now() - guardada).total_seconds() > minutos * 60


def _refrescar_tasa_si_hace_falta() -> None:
    """
    Si el usuario tiene activa la actualización automática y su tasa está
    vieja, se consulta la API y se guarda la nueva.

    Se llama al leer el precio del dólar, para que la app se actualice sola
    sin depender de que alguien pulse un botón.

    Si la API falla no se molesta al usuario: se queda con la tasa anterior,
    que siempre es mejor que mostrar un error.
    """
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE usuario_id = %s AND clave = 'actualizar_precios_auto'",
            (usuario_actual(),),
        ).fetchone()

        conexion.commit()

    activado = fila["valor"] if fila else AJUSTES_POR_DEFECTO["actualizar_precios_auto"]

    if activado != "1":
        return

    if not _tasa_esta_vieja((_ultima_tasa() or {}).get("actualizado_en")):
        return

    resultado = consultar_tasa_dolar()
    if "error" in resultado:
        return

    _guardar_tasa(resultado["precio_ves"], "internet")


# ------------------------------------------------------------
# GET /api/configuracion
# Devuelve todos los ajustes guardados del usuario
# ------------------------------------------------------------
@rutas_config.get("/configuracion")
def leer_configuracion():
    """Lee la tabla configuracion y devuelve los ajustes con sus valores por defecto."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    with obtener_conexion() as conexion:
        filas = conexion.execute(
            "SELECT clave, valor FROM configuracion WHERE usuario_id = %s",
            (usuario_actual(),),
        ).fetchall()

        conexion.commit()

    # Se empieza con los valores por defecto y se pisan con lo guardado
    ajustes = dict(AJUSTES_POR_DEFECTO)
    ajustes.update({fila["clave"]: fila["valor"] for fila in filas})

    return jsonify({"configuracion": ajustes})


# ------------------------------------------------------------
# PUT /api/configuracion
# Guarda los ajustes que el usuario cambió
# ------------------------------------------------------------
@rutas_config.put("/configuracion")
def guardar_configuracion():
    """Guarda el tema, la actualización automática de precios y el nombre del negocio."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}

    # El tema solo puede ser "claro" u "oscuro"
    tema = datos.get("tema", "claro")
    if tema not in ("claro", "oscuro"):
        return jsonify({"error": "El tema debe ser «claro» u «oscuro»."}), 400

    # La actualización automática se guarda como "1" o "0"
    actualizar_auto = datos.get("actualizar_precios_auto")
    if isinstance(actualizar_auto, bool):
        actualizar_auto = "1" if actualizar_auto else "0"

    valores = {
        "tema": tema,
        "actualizar_precios_auto": "1" if str(actualizar_auto) == "1" else "0",
        "nombre_negocio": (datos.get("nombre_negocio") or "Mi negocio").strip() or "Mi negocio",
    }

    with obtener_conexion() as conexion:
        # Se guardan o actualizan uno por uno los ajustes.
        # "actualizado_en" lo pone un trigger de la base.
        for clave, valor in valores.items():
            conexion.execute(
                """
                INSERT INTO configuracion (usuario_id, clave, valor)
                VALUES (%s, %s, %s)
                ON CONFLICT(usuario_id, clave) DO UPDATE SET
                    valor = excluded.valor
                """,
                (usuario_actual(), clave, valor),
            )
        conexion.commit()

    return jsonify({"mensaje": "Configuración guardada.", "configuracion": valores})


# ------------------------------------------------------------
# GET /api/dolar
# Devuelve el precio actual del dólar en bolívares
# ------------------------------------------------------------
@rutas_config.get("/dolar")
def leer_dolar():
    """
    Muestra el precio del dólar en bolívares.

    Si el usuario tiene la actualización automática activada y su tasa está
    vieja, se consulta la API antes de responder, así el precio que ve
    siempre está al día.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    _refrescar_tasa_si_hace_falta()

    fila = _ultima_tasa()

    # Si nunca se guardó una tasa se usa la del archivo .env
    if not fila:
        return jsonify({
            "precio_ves": config.PRECIO_DOLAR_POR_DEFECTO,
            "origen": "por defecto",
            "actualizado_en": None,
        })

    return jsonify({
        "precio_ves": float(fila["precio_ves"]),
        "origen": fila["origen"],
        "actualizado_en": fila["actualizado_en"],
    })


# ------------------------------------------------------------
# PUT /api/dolar
# El usuario puede colocar la tasa del dólar a mano
# ------------------------------------------------------------
@rutas_config.put("/dolar")
def guardar_dolar():
    """Guarda manualmente el precio del dólar que indique el usuario."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}
    precio = datos.get("precio_ves")

    try:
        precio = float(precio)
        if precio <= 0:
            return jsonify({"error": "El precio del dólar debe ser mayor a cero."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "El precio del dólar debe ser un número."}), 400

    _guardar_tasa(precio, "manual")

    return jsonify({"mensaje": "Precio del dólar actualizado.", "precio_ves": precio})


# ------------------------------------------------------------
# POST /api/dolar/actualizar
# Consulta la tasa por internet (se activa desde Configuración)
# ------------------------------------------------------------
@rutas_config.post("/dolar/actualizar")
def actualizar_dolar():
    """
    Consulta la tasa por internet y la guarda.
    Si no hay internet o la fuente falla, se avisa para usar la tasa manual.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    # Se consulta la API de exchangerate-api.com
    resultado = consultar_tasa_dolar()

    if "error" in resultado:
        return jsonify({"error": resultado["error"]}), 502

    # Se guarda la tasa consultada
    _guardar_tasa(resultado["precio_ves"], "internet")

    return jsonify({
        "mensaje": "Precio del dólar actualizado.",
        "precio_ves": resultado["precio_ves"],
        "precio_usd": resultado["precio_usd"],
        "fecha": resultado["fecha"],
        "fuente": resultado["fuente"],
    })


# ------------------------------------------------------------
# POST /api/dolar/convertir
# Convierte un valor entre USD y VES, en cualquier sentido
# ------------------------------------------------------------
@rutas_config.post("/dolar/convertir")
def convertir_dolar():
    """
    Convierte un monto entre dólares y bolívares usando la última tasa
    guardada (o la del .env si nunca se consultó). Si el usuario pide usar
    la tasa de internet, se consulta antes de convertir.

    Cuerpo esperado:
      valor     -> el monto a convertir (obligatorio)
      origen    -> "USD" o "VES" (obligatorio)
      destino   -> "USD" o "VES" (obligatorio)
      desde_api -> "1" para usar la tasa recién consultada (opcional)
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    datos = request.get_json(silent=True) or {}
    origen = str(datos.get("origen", "")).upper()
    destino = str(datos.get("destino", "")).upper()

    # Las dos monedas tienen que ser USD y VES, en cualquier orden
    if {origen, destino} != {"USD", "VES"}:
        return jsonify({
            "error": "Las monedas deben ser «USD» y «VES», en cualquier orden."
        }), 400

    try:
        valor = float(datos.get("valor"))
        if valor < 0:
            return jsonify({"error": "El monto no puede ser negativo."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "El monto debe ser un número."}), 400

    # Si se pidió usar la tasa de internet, se consulta primero
    if str(datos.get("desde_api")) == "1":
        resultado = consultar_tasa_dolar()
        if "error" in resultado:
            return jsonify({"error": resultado["error"]}), 502

        precio_ves = resultado["precio_ves"]
        _guardar_tasa(precio_ves, "internet")

    else:
        # Si no, se usa la última tasa guardada
        fila = _ultima_tasa()
        precio_ves = fila["precio_ves"] if fila else config.PRECIO_DOLAR_POR_DEFECTO

    return jsonify({
        "valor": valor,
        "origen": origen,
        "destino": destino,
        "resultado": convertir(valor, precio_ves, origen, destino),
        "tasa_usd_ves": precio_ves,
    })


# ------------------------------------------------------------
# GET /api/dolar/historico
# Muestra las últimas tasas guardadas
# ------------------------------------------------------------
@rutas_config.get("/dolar/historico")
def historico_dolar():
    """Devuelve las últimas 30 tasas del dólar guardadas en SQLite."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    with obtener_conexion() as conexion:
        filas = conexion.execute(
            "SELECT precio_ves, origen, actualizado_en FROM precios_dolar WHERE usuario_id = %s ORDER BY id DESC LIMIT 30",
            (usuario_actual(),),
        ).fetchall()

        conexion.commit()

    return jsonify({"historial": [fila_limpia(fila) for fila in filas]})
