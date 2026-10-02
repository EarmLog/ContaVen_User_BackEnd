"""
Funciones de apoyo que se usan en varias rutas.

    security.py -> validación, sanitización y conversión de datos
"""

from .security import a_numero, a_texto, entero_opcion

__all__ = ["a_numero", "a_texto", "entero_opcion"]