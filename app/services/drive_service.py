"""
Servicio de Google Drive.

Aquí vive toda la lógica "pura" para hablar con Google: armar la URL de
autorización, cambiar el código por tokens y subir el archivo de respaldo.
Las rutas (blueprints) solo se encargan de recibir la petición y responder.

Documentación: https://developers.google.com/drive/api/v3/guides/quickstart
"""

import time
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

from ..config import config

# --- Endpoints de Google ---
URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_ARCHIVOS = "https://www.googleapis.com/drive/v3/files"
URL_SUBIDA = "https://www.googleapis.com/upload/drive/v3/files"

# Solo se pide acceso a los archivos que crea la propia app (permiso más
# estrecho y seguro que "drive", que daría acceso a todo el Drive del usuario).
PERMISOS_GOOGLE = "https://www.googleapis.com/auth/drive.file"

# Tipo MIME que usa Google para las carpetas
TIPO_CARPETA = "application/vnd.google-apps.folder"


class ErrorDrive(Exception):
    """Error con un mensaje que ya se puede mostrar al usuario."""

    def __init__(self, mensaje: str, estado: int = 502):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado = estado


def esta_configurado() -> bool:
    """Dice si ya se pueden pedir las llaves OAuth en el archivo .env."""
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


# ------------------------------------------------------------
# Parte 1: la autorización (el usuario conecta su cuenta)
# ------------------------------------------------------------
def armar_url_autorizacion(usuario_id: str) -> str:
    """
    Arma la dirección a la que se manda al usuario para que autorice a la app.

    El "state" es la forma de saber a quién pertenece la respuesta que
    mande Google de vuelta en el callback: se manda el id del usuario
    y se compara al recibirla.
    """
    if not esta_configurado():
        raise ErrorDrive(
            "Google Drive no está configurado. Faltan las llaves en el archivo .env.",
            503,
        )

    parametros = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": PERMISOS_GOOGLE,
        # "offline" + "prompt=consent" son los que hacen que Google
        # devuelva un refresh_token, necesario para que las copias
        # sigan funcionando cuando el access_token caduque (1 hora).
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": usuario_id,
    }

    # urlencode se encarga de escapar los caracteres especiales (los : y /
    # de la redirect_uri, por ejemplo), que Google exige llevar codificados
    consulta = urlencode(parametros, quote_via=quote)
    return f"{URL_AUTORIZAR}?{consulta}"


def canjear_codigo_por_tokens(codigo: str) -> dict:
    """
    Cambia el código de autorización que devolvió Google por los tokens.

    Devuelve un diccionario con:
      access_token   -> token de acceso (dura 1 hora)
      refresh_token  -> token para renovar el anterior (dura meses)
      expires_at     -> fecha y hora (epoch) en que caduca el de acceso
    """
    try:
        respuesta = requests.post(
            URL_TOKEN,
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": codigo,
                "grant_type": "authorization_code",
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
            },
            timeout=30,
        )
    except requests.exceptions.Timeout:
        raise ErrorDrive("Google tardó demasiado en responder. Intenta de nuevo.")

    except requests.exceptions.RequestException:
        raise ErrorDrive("No se pudo conectar con Google.")

    if respuesta.status_code != 200:
        # Google explica el motivo (redirect_uri incorrecto, llave mala, etc.)
        try:
            detalle = respuesta.json().get("error_description", "")
        except ValueError:
            detalle = ""

        raise ErrorDrive(
            f"Google no autorizó la conexión. {detalle}".strip()
        )

    contenido = respuesta.json()

    if not contenido.get("access_token"):
        raise ErrorDrive("Google no devolvió el token de acceso.")

    return {
        "access_token": contenido["access_token"],
        # Google solo manda refresh_token la primera vez que se autoriza
        "refresh_token": contenido.get("refresh_token", ""),
        "expires_at": time.time() + int(contenido.get("expires_in", 3600)),
    }


def renovar_access_token(refresh_token: str) -> dict:
    """
    Pide un access_token nuevo usando el refresh_token guardado.

    Es lo que hace que la copia de seguridad siga funcionando días o meses
    después de la primera conexión, sin que el usuario tenga que autorizar
    otra vez.
    """
    if not refresh_token:
        raise ErrorDrive(
            "La conexión con Google Drive expiró. Conéctala de nuevo.",
            400,
        )

    try:
        respuesta = requests.post(
            URL_TOKEN,
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except requests.exceptions.RequestException:
        raise ErrorDrive("No se pudo renovar la conexión con Google Drive.")

    if respuesta.status_code != 200:
        raise ErrorDrive(
            "La conexión con Google Drive venció. Conéctala de nuevo.",
            400,
        )

    contenido = respuesta.json()

    if not contenido.get("access_token"):
        raise ErrorDrive("Google no devolvió un token nuevo.")

    return {
        "access_token": contenido["access_token"],
        "expires_at": time.time() + int(contenido.get("expires_in", 3600)),
    }


# ------------------------------------------------------------
# Parte 2: la copia de seguridad
# ------------------------------------------------------------
def _peticion(metodo: str, url: str, token: str, **extra) -> requests.Response:
    """Ejecuta una llamada al API de Drive y avisa si Google devuelve error."""
    cabeceras = {"Authorization": f"Bearer {token}"}
    cabeceras.update(extra.pop("cabeceras", {}))

    try:
        respuesta = requests.request(
            metodo,
            url,
            headers=cabeceras,
            timeout=extra.pop("timeout", 30),
            **extra,
        )
    except requests.exceptions.Timeout:
        raise ErrorDrive("Google Drive tardó demasiado en responder.")

    except requests.exceptions.RequestException:
        raise ErrorDrive("No se pudo conectar con Google Drive.")

    if respuesta.status_code == 401:
        raise ErrorDrive(
            "La conexión con Google Drive venció. Conéctala de nuevo.",
            400,
        )

    if respuesta.status_code >= 400:
        raise ErrorDrive(f"Google Drive devolvió el error {respuesta.status_code}.")

    return respuesta


def buscar_o_crear_carpeta(token: str, nombre_carpeta: str) -> str:
    """
    Busca en el Drive del usuario la carpeta con ese nombre y, si no
    existe, la crea. Devuelve el id de la carpeta.

    El nombre de la carpeta es "ContaVen - <id del usuario>", así que cada
    persona tiene la suya y nunca se mezclan los respaldos.
    """
    # Se busca por nombre exacto, ignorando la basura
    try:
        archivos = _peticion(
            "GET",
            URL_ARCHIVOS,
            token,
            params={
                "q": (
                    f"name = '{nombre_carpeta}' "
                    f"and mimeType = '{TIPO_CARPETA}' and trashed = false"
                ),
                "fields": "files(id, name)",
            },
        ).json().get("files", [])
    except ValueError:
        raise ErrorDrive("No se pudo leer la respuesta de Google Drive.")

    # Si ya existe, se devuelve su id
    if archivos:
        return archivos[0]["id"]

    # Si no, se crea
    try:
        nueva = _peticion(
            "POST",
            URL_ARCHIVOS,
            token,
            cabeceras={"Content-Type": "application/json"},
            json={"name": nombre_carpeta, "mimeType": TIPO_CARPETA},
        ).json()
    except ValueError:
        raise ErrorDrive("No se pudo leer la respuesta de Google Drive.")

    if not nueva.get("id"):
        raise ErrorDrive("No se pudo crear la carpeta en Google Drive.")

    return nueva["id"]


def subir_archivo(token: str, carpeta_id: str, archivo: Path, nombre_destino: str) -> str:
    """
    Sube el archivo a la carpeta indicada y devuelve el id del archivo.

    Se usa la subida "multipart" de Drive, que manda los metadatos y el
    contenido en una sola petición.
    """
    if not archivo.exists():
        raise ErrorDrive("Todavía no hay datos para respaldar.", 400)

    metadatos = (
        f'{{"name": "{nombre_destino}", "parents": ["{carpeta_id}"]}}'
    )

    try:
        with archivo.open("rb") as manejador:
            contenido = manejador.read()
    except OSError:
        raise ErrorDrive("No se pudo leer el archivo de la base de datos.")

    respuesta = _peticion(
        "POST",
        URL_SUBIDA,
        token,
        cabeceras={"Content-Type": "multipart/related; boundary=contaven_backup"},
        params={"uploadType": "multipart", "fields": "id"},
        data=(
            f"--contaven_backup\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadatos}\r\n"
            f"--contaven_backup\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + contenido + b"\r\n--contaven_backup--",
        timeout=180,
    )

    try:
        id_archivo = respuesta.json().get("id")
    except ValueError:
        raise ErrorDrive("No se pudo leer la respuesta de Google Drive.")

    if not id_archivo:
        raise ErrorDrive("No se pudo subir la copia de seguridad.")

    return id_archivo