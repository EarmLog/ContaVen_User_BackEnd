"""
Funciones para hablar con Supabase (nube).

Supabase se usa únicamente para:
  - crear el usuario en la autenticación (registro)
  - leer y escribir el perfil con los días de licencia
El inventario y las ventas NO se guardan aquí, van en SQLite local.
"""

import requests
import jwt

from ..config import config

# Cliente que descarga las llaves públicas de Supabase para validar los tokens
_cliente_jwks = jwt.PyJWKClient(config.SUPABASE_JWKS_URL)


def _cabeceras_con_llave_secreta(con_devolver_datos: bool = False) -> dict:
    """
    Arma las cabeceras HTTP usando la llave secreta de Supabase.
    Esa llave solo se usa en el backend, nunca en el navegador.
    Si con_devolver_datos es True, Supabase devuelve la fila insertada
    en el cuerpo de la respuesta en vez de una respuesta vacía.
    """
    cabeceras = {
        "apikey": config.SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    if con_devolver_datos:
        cabeceras["Prefer"] = "return=representation"

    return cabeceras


def registrar_usuario_supabase(correo: str, contrasena: str, nombre: str, telefono: str | None) -> str:
    """
    Crea un usuario nuevo en la autenticación de Supabase.
    Recibe los datos del formulario y devuelve el id del usuario creado.
    Si el correo ya existe devuelve un error con el mensaje correspondiente.
    """
    # Primero se revisa si el correo ya está registrado
    if correo_existe_en_supabase(correo):
        raise ValueError("Ese correo ya está registrado. Intenta iniciar sesión.")

    # Se llama a la API de administración de usuarios de Supabase
    respuesta = requests.post(
        f"{config.SUPABASE_URL}/auth/v1/admin/users",
        headers=_cabeceras_con_llave_secreta(),
        json={
            "email": correo,
            "password": contrasena,
            "email_confirm": True,  # se confirma el correo de una vez
            "user_metadata": {
                "nombre": nombre,
                "telefono": telefono or "",
            },
        },
        timeout=30,
    )

    # Si Supabase devuelve error se traduce el mensaje
    if respuesta.status_code not in (200, 201):
        raise ValueError(_extraer_error_supabase(respuesta))

    return respuesta.json()["id"]


def correo_existe_en_supabase(correo: str) -> bool:
    """
    Revisa si un correo ya existe en la autenticación de Supabase.
    Devuelve True si ya está registrado y False si está libre.
    """
    respuesta = requests.get(
        f"{config.SUPABASE_URL}/auth/v1/admin/users",
        headers=_cabeceras_con_llave_secreta(),
        params={"page": 1, "per_page": 1000},
        timeout=30,
    )

    if respuesta.status_code != 200:
        return False

    usuarios = respuesta.json().get("users", [])
    return any(u.get("email", "").lower() == correo.lower() for u in usuarios)


def crear_perfil(usuario_id: str, nombre: str, correo: str, telefono: str | None) -> dict:
    """
    Crea la fila del perfil en la tabla "perfiles" de Supabase.
    Aquí se asignan los 30 días de licencia gratis y el número de carpeta
    de Google Drive que le corresponde a ese usuario.
    """
    # Se pide el siguiente número de carpeta a la secuencia de Supabase
    respuesta = requests.post(
        f"{config.SUPABASE_URL}/rest/v1/rpc/siguiente_numero_carpeta",
        headers=_cabeceras_con_llave_secreta(),
        json={},
        timeout=30,
    )
    numero_carpeta = respuesta.json() if respuesta.status_code == 200 else 1

    # Se inserta el perfil con la licencia inicial
    respuesta = requests.post(
        f"{config.SUPABASE_URL}/rest/v1/perfiles",
        headers=_cabeceras_con_llave_secreta(con_devolver_datos=True),
        json={
            "id": usuario_id,
            "nombre": nombre,
            "correo": correo,
            "telefono": telefono,
            "numero_carpeta_drive": numero_carpeta,
            "dias_licencia": config.DIAS_LICENCIA_INICIAL,
        },
        params={"select": "*"},
        timeout=30,
    )

    # Si el insert falla se muestra el motivo que devuelve Supabase
    if respuesta.status_code not in (200, 201):
        raise ValueError(_extraer_error_supabase(respuesta))

    # Se devuelve la primera fila, que es el perfil recién creado
    return respuesta.json()[0]


def obtener_perfil(usuario_id: str) -> dict | None:
    """
    Trae el perfil de un usuario desde Supabase usando su id.
    Devuelve None si todavía no tiene perfil creado.
    """
    respuesta = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/perfiles",
        headers=_cabeceras_con_llave_secreta(),
        params={"id": f"eq.{usuario_id}", "select": "*"},
        timeout=30,
    )

    if respuesta.status_code != 200:
        return None

    filas = respuesta.json()
    return filas[0] if filas else None


def verificar_token(token: str) -> dict | None:
    """
    Valida el token de sesión que envía el navegador.
    Usa las llaves públicas de Supabase (JWKS) y devuelve los datos
    del usuario (id, correo, nombre). Devuelve None si el token es falso.
    """
    try:
        llave = _cliente_jwks.get_signing_key_from_jwt(token)
        datos = jwt.decode(
            token,
            llave.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
        return {
            "id": datos.get("sub"),
            "correo": datos.get("email"),
        }
    except Exception:
        return None


def _extraer_error_supabase(respuesta) -> str:
    """
    Saca un mensaje legible de los errores que devuelve Supabase.
    Sirve para poder mostrarle al usuario qué salió mal.
    """
    try:
        datos = respuesta.json()
        # Supabase a veces manda msg, message, error_description o error
        for clave in ("msg", "message", "error_description", "error"):
            if clave in datos:
                return str(datos[clave])
    except Exception:
        pass
    return "Ocurrió un error al conectar con Supabase."
