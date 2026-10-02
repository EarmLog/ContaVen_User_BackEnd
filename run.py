"""
Punto de entrada del backend de ContaVen.

Para arrancar el servidor:
    python run.py

Carga el .env antes de importar la aplicación, de modo que todas las
variables (puerto, llaves de Supabase, Google Drive) estén disponibles
aunque se ejecute desde otra carpeta.
"""

import sys
from pathlib import Path

# Se añade la raíz del proyecto al path para poder importar "app"
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import app  # noqa: E402
from app.config import config  # noqa: E402


def main() -> None:
    """Arranca el servidor de desarrollo."""
    print(f"\nContaVen User API en http://localhost:{config.PUERTO}\n")
    app.run(host="0.0.0.0", port=config.PUERTO, debug=True)


if __name__ == "__main__":
    main()