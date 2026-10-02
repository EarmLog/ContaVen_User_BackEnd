"""
Cliente de la API de tipos de cambio (exchangerate-api.com).

Devuelve la tasa de cambio del dólartoday, para poder convertir precios
entre USD y VES, en ambos sentidos.

Documentación: https://www.exchangerate-api.com/docs/free
"""

import requests

from ..config import config

# La API pública v6 pide la llave dentro de la dirección
URL_BASE = "https://v6.exchangerate-api.com/v6"

# Se espera este código de resultado para saber que la consulta salió bien
RESULTADO_EXITO = "success"


# ------------------------------------------------------------
# Obtener la tasa de un dólar en bolívares
# ------------------------------------------------------------
def consultar_tasa_dolar() -> dict:
    """
    Consulta la API y devuelve un diccionario con:
      precio_ves      -> cuántos bolívares vale 1 dólar
      precio_usd      -> cuántos dólares vale 1 bolívar
      fecha           -> fecha de la última actualización de la fuente
      fuente          -> nombre de la API usada

    Si la API falla o no trae la tasa, devuelve un diccionario con
    "error" y el motivo, para que el backend pueda avisarle al usuario.
    """
    # Si no hay llave configurada, se avisa para que la coloque en el .env
    if not config.LLAVE_EXCHANGERATE_API:
        return {"error": "Falta la llave de exchangerate-api en el archivo .env."}

    direccion = f"{URL_BASE}/{config.LLAVE_EXCHANGERATE_API}/latest/USD"

    try:
        respuesta = requests.get(direccion, timeout=15)

        # Si la API responde con error (llave mala, cuota, etc.)
        if respuesta.status_code != 200:
            return {
                "error": (
                    f"La API de exchangerate-api respondió con código "
                    f"{respuesta.status_code}."
                )
            }

        contenido = respuesta.json()

    except requests.exceptions.Timeout:
        return {"error": "La API del dólar tardó demasiado en responder."}

    except requests.exceptions.RequestException:
        return {"error": "No se pudo conectar con la API del dólar."}

    except ValueError:
        return {"error": "La API del dólar devolvió una respuesta que no se pudo leer."}

    # La API devuelve "result" con "success" o "error"
    if contenido.get("result") != RESULTADO_EXITO:
        # El mensaje exacto de error lo manda la propia API
        detalle = contenido.get("error-type") or contenido.get("documentation") or ""
        mensaje = contenido.get("error") or "la API no devolvió la tasa"

        return {
            "error": f"La API del dólar falló: {mensaje}. {detalle}".strip()
        }

    # Se saca la tasa de 1 USD en VES
    precio_ves = contenido.get("conversion_rates", {}).get("VES")

    if precio_ves is None:
        return {"error": "La API del dólar no devolvió la tasa de Venezuela."}

    precio_ves = float(precio_ves)

    if precio_ves <= 0:
        return {"error": "La API del dólar devolvió una tasa inválida."}

    # La tasa inversa se calcula para poder convertir de VES a USD
    return {
        "precio_ves": round(precio_ves, 4),
        "precio_usd": round(1 / precio_ves, 8),
        "fecha": contenido.get("time_last_update_utc"),
        "fuente": "exchangerate-api.com",
    }


# ------------------------------------------------------------
# Convertir un valor entre las dos monedas
# ------------------------------------------------------------
def convertir(valor: float, tasa: float, origen: str, destino: str) -> float:
    """
    Convierte un valor de una moneda a otra usando la tasa del dólar.

    Si origen y destino son la misma moneda, devuelve el valor sin cambios.
    Si el origen es el dólar, multiplica por la tasa.
    Si el destino es el dólar, divide entre la tasa.
    """
    # Si no hay tasa o no se va a cambiar de moneda, se devuelve igual
    if not tasa or origen == destino:
        return round(float(valor), 2)

    if origen == "USD":
        return round(float(valor) * float(tasa), 2)

    # Si no es USD, se asume que la moneda de origen es el bolívar
    return round(float(valor) / float(tasa), 2)