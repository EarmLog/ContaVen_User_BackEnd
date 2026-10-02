"""
Rutas de la copia de seguridad en Google Drive.

Cada usuario conecta su propia cuenta de Google una vez y sus respaldos
se suben siempre a la carpeta "ContaVen - <id del usuario>" dentro de
su Drive. Para que funcione hacen falta las llaves OAuth en el archivo
.env (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y GOOGLE_REDIRECT_URI).

Endpoints:
  GET  /api/drive/estado    -> dice si Drive está configurado y conectado
  GET  /api/drive/conectar  -> devuelve la URL para autorizar a Google
  GET  /api/drive/callback  -> recibe la respuesta de Google
  POST /api/drive/copia     -> sube el archivo SQLite a la carpeta del usuario
"""

import json
import time
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from ..config import config
from ..database import obtener_conexion, usuario_actual
from ..services import drive_service
from .auth import cargar_usuario_autenticado

rutas_drive = Blueprint("drive", __name__, url_prefix="/api/drive")


def nombre_de_la_carpeta(usuario_id: str) -> str:
    """
    El nombre de la carpeta de Drive del usuario.

    Es "ContaVen - <id del usuario>", donde el id es el mismo UUID de la
    cuenta de Supabase. Cada persona tiene su carpeta propia y sus
    respaldos nunca se mezclan con los de otra.
    """
    return f"ContaVen - {usuario_id}"


# ------------------------------------------------------------
# GET /api/drive/estado
# ------------------------------------------------------------
@rutas_drive.get("/estado")
def estado_drive():
    """
    Le dice al frontend si la copia de seguridad está disponible y si el
    usuario ya conectó su cuenta de Google.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    usuario_id = usuario_actual()
    guardado = _leer_tokens(usuario_id)

    return jsonify({
        "configurado": drive_service.esta_configurado(),
        "conectado": bool(guardado.get("access_token")),
        "nombre_carpeta": nombre_de_la_carpeta(usuario_id),
    })


# ------------------------------------------------------------
# GET /api/drive/conectar
# Devuelve la URL donde el usuario autoriza a la app
# ------------------------------------------------------------
@rutas_drive.get("/conectar")
def conectar_drive():
    """Arma el enlace de autorización de Google para la cuenta del usuario."""
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    try:
        url = drive_service.armar_url_autorizacion(usuario_actual())
    except drive_service.ErrorDrive as error_drive:
        return jsonify({"error": error_drive.mensaje}), error_drive.estado

    return jsonify({"url": url})


# ------------------------------------------------------------
# GET /api/drive/callback
# Google devuelve aquí el código de autorización
# ------------------------------------------------------------
@rutas_drive.get("/callback")
def callback_drive():
    """
    Recibe el regreso de Google y guarda el token del usuario.

    IMPORTANTE: esta ruta NO pide token de sesión. Google redirige al
    navegador desde su propia página, así que no llega la cabecera
    Authorization. Por eso el usuario se identifica con el "state" que
    se mandó al pedir la autorización, y no con el token de la app.

    Como esta dirección se abre en una ventana aparte desde la app, al
    final se devuelve una paginita que se cierra sola.
    """
    # Si el usuario no autorizó o le dio cancelar
    if request.args.get("error"):
        return _pagina_final(
            False,
            "No se autorizó el acceso a Google Drive.",
            request.args.get("error_description", ""),
        )

    codigo_google = request.args.get("code")
    state = request.args.get("state")

    if not codigo_google or not state:
        return _pagina_final(
            False,
            "Google no devolvió los datos de autorización.",
        )

    # El state trae el id del usuario que pidió la conexión
    usuario_id = state.strip()
    if not usuario_id:
        return _pagina_final(
            False,
            "No se pudo identificar al usuario en la respuesta de Google.",
        )

    try:
        tokens = drive_service.canjear_codigo_por_tokens(codigo_google)
    except drive_service.ErrorDrive as error_drive:
        return _pagina_final(False, error_drive.mensaje)

    # Si ya había un token guardado se conserva el refresh_token anterior,
    # porque Google solo lo devuelve la primera vez que se autoriza.
    guardado = _leer_tokens(usuario_id)
    if not tokens.get("refresh_token"):
        tokens["refresh_token"] = guardado.get("refresh_token", "")

    _guardar_tokens(usuario_id, tokens)

    return _pagina_final(
        True,
        "Google Drive conectado correctamente.",
        f"Tus respaldos se guardarán en la carpeta {nombre_de_la_carpeta(usuario_id)}.",
    )


# ------------------------------------------------------------
# POST /api/drive/copia
# Sube una copia del archivo SQLite a la carpeta del usuario
# ------------------------------------------------------------
@rutas_drive.post("/copia")
def crear_copia():
    """
    Sube el archivo SQLite con el inventario y las ventas del usuario a
    su carpeta "ContaVen - <id del usuario>" en Google Drive.
    """
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    usuario_id = usuario_actual()
    nombre_carpeta = nombre_de_la_carpeta(usuario_id)

    try:
        token = _token_valido(usuario_id)
    except drive_service.ErrorDrive as error_drive:
        return jsonify({"error": error_drive.mensaje}), error_drive.estado

    # Se busca o se crea la carpeta del usuario en su Drive
    try:
        carpeta_id = drive_service.buscar_o_crear_carpeta(token, nombre_carpeta)
    except drive_service.ErrorDrive as error_drive:
        return jsonify({"error": error_drive.mensaje}), error_drive.estado

    # El nombre del archivo lleva la fecha y la hora
    marca_tiempo = time.strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"respaldo_contaven_{marca_tiempo}.db"

    try:
        id_archivo = drive_service.subir_archivo(
            token,
            carpeta_id,
            Path(config.RUTA_BASE_DATOS),
            nombre_archivo,
        )
    except drive_service.ErrorDrive as error_drive:
        return jsonify({"error": error_drive.mensaje}), error_drive.estado

    return jsonify({
        "mensaje": "Copia de seguridad guardada en Google Drive.",
        "carpeta": nombre_carpeta,
        "archivo": nombre_archivo,
        "id_archivo": id_archivo,
    })


# ============================================================
# Funciones de apoyo
# ============================================================
def _pagina_final(exito: bool, mensaje: str, detalle: str = "") -> str:
    """
    Devuelve la paginita que ve el usuario al volver de Google.

    Se muestra en una ventana aparte, así que avisa cómo le fue e intenta
    cerrarse sola para dejar al usuario de vuelta en la app.
    """
    color = "#16a34a" if exito else "#dc2626"
    icono = "✓" if exito else "✕"

    # Se cierra sola a los 2 segundos, dejando tiempo a leer el mensaje
    cierre = """
    <script>
      setTimeout(function () { window.close(); }, 2500);
    </script>
    """ if exito else ""

    html_extra = f"<p class='detalle'>{detalle}</p>" if detalle else ""
    subtitulo = (
        "Esta ventana se cerrará sola en unos segundos."
        if exito
        else "Cierra esta ventana y vuelve a intentar."
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Google Drive - ContaVen</title>
  <style>
    body {{
      margin: 0; min-height: 100vh; display: flex; align-items: center;
      justify-content: center; font-family: system-ui, -apple-system, sans-serif;
      background: #f8fafc; color: #0f172a;
    }}
    .caja {{
      max-width: 26rem; padding: 2rem; text-align: center;
      background: #fff; border-radius: .75rem; box-shadow: 0 4px 16px rgba(0,0,0,.08);
    }}
    .icono {{ font-size: 2.5rem; color: {color}; line-height: 1; }}
    h1 {{ font-size: 1.15rem; margin: .75rem 0 .35rem; }}
    .detalle {{ font-size: .85rem; color: #64748b; margin: .5rem 0 0; }}
    .sub {{ font-size: .85rem; color: #64748b; margin: .35rem 0 0; }}
  </style>
</head>
<body>
  <div class="caja">
    <div class="icono">{icono}</div>
    <h1>{mensaje}</h1>
    <p class="sub">{subtitulo}</p>
    {html_extra}
  </div>
  {cierre}
</body>
</html>"""


def _guardar_tokens(usuario_id: str, tokens: dict) -> None:
    """Guarda el token de Google Drive del usuario en la base local."""
    conexion = obtener_conexion()
    try:
        conexion.execute(
            """
            INSERT INTO configuracion (usuario_id, clave, valor)
            VALUES (?, ?, ?)
            ON CONFLICT(usuario_id, clave) DO UPDATE SET
                valor = excluded.valor,
                actualizado_en = datetime('now', 'localtime')
            """,
            (usuario_id, "token_drive", json.dumps(tokens)),
        )
        conexion.commit()
    finally:
        conexion.close()


def _leer_tokens(usuario_id: str) -> dict:
    """Lee los tokens de Google Drive guardados; si no hay, devuelve vacío."""
    conexion = obtener_conexion()
    try:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE usuario_id = ? AND clave = ?",
            (usuario_id, "token_drive"),
        ).fetchone()
    finally:
        conexion.close()

    if not fila or not fila["valor"]:
        return {}

    # Antes se guardaba el token solo como texto plano; se acepta para no
    # obligar a los usuarios que ya lo tenían a conectar de nuevo
    try:
        datos = json.loads(fila["valor"])
    except (ValueError, TypeError):
        return {"access_token": fila["valor"], "refresh_token": "", "expires_at": 0}

    return datos if isinstance(datos, dict) else {}


def _token_valido(usuario_id: str) -> str:
    """
    Devuelve un access_token vigente para el usuario.

    Si el token ya caducó pero hay refresh_token, se pide uno nuevo y se
    guarda, para que las copias sigan funcionando sin que el usuario
    tenga que autorizar otra vez.
    """
    tokens = _leer_tokens(usuario_id)

    if not tokens.get("access_token"):
        raise drive_service.ErrorDrive(
            "Primero debes conectar tu cuenta de Google Drive.",
            400,
        )

    # Un minuto de margen por si el token caduca en el camino
    margen = 60
    expira_en = float(tokens.get("expires_at") or 0)

    if expira_en - margen > time.time():
        return tokens["access_token"]

    # Caducó: se intenta renovar
    nuevos = drive_service.renovar_access_token(tokens.get("refresh_token", ""))
    tokens["access_token"] = nuevos["access_token"]
    tokens["expires_at"] = nuevos["expires_at"]
    _guardar_tokens(usuario_id, tokens)

    return tokens["access_token"]