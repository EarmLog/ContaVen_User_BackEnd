"""
Utilidades de validación y sanitización.

Sirven para no repetir las mismas comprobaciones en cada ruta y para
que un dato sucio (con espacios de más, con tipos raros o con lo que
mandó el usuario a propósito) nunca llegue a la base de datos.
"""


def a_texto(valor) -> str | None:
    """
    Limpia un texto que viene del cuerpo de la petición.

    - Quita los espacios de los extremos.
    - Colapsa las repeticiones de espacios del medio.
    - Devuelve None si al final no queda nada (para guardar NULL en SQL).

    Ejemplo: "  hola   mundo  " -> "hola mundo"
    """
    if valor is None:
        return None

    limpio = " ".join(str(valor).split())

    return limpio or None


def a_numero(valor) -> float:
    """
    Convierte cualquier valor a número decimal.

    Si no es un número válido (o viene vacío), devuelve 0. Se usa para
    los precios, donde un valor mal escrito debe contar como cero y no
    romper la petición.
    """
    if valor is None or valor == "":
        return 0.0

    try:
        return float(valor)
    except (ValueError, TypeError):
        return 0.0


def entero_opcion(valor) -> int | None:
    """
    Convierte un valor a entero, o devuelve None si no se puede.

    A diferencia de a_numero, aquí un dato inválido se distingue del
    cero, porque en el inventario "sin stock" y "stock 0" no son lo
    mismo.
    """
    if valor is None or valor == "":
        return None

    try:
        return int(valor)
    except (ValueError, TypeError):
        return None