"""
Prueba de la copia de seguridad en Google Drive.

El flujo real de Google OAuth necesita un navegador y una cuenta de
Google de verdad, así que aquí se simula la respuesta de Google para
poder comprobar toda la lógica de nuestro lado:

  - que el backend diga que Drive está configurado
  - que la carpeta se llame "ContaVen - <id del usuario>"
  - que se arme bien la URL de autorización
  - que se guarde el token y se detecte la conexión
  - que se cree la carpeta y se suba el archivo
  - que el token se renueve solo cuando caduca
  - que los errores se manejen sin romperse

Esta prueba corre en el mismo proceso del backend (Flask test client),
así que no hace falta levantar el servidor. Para usarla:

    USUARIO_PRUEBA_ID=<uuid-de-un-usuario-real> python prueba_drive.py

Necesita un usuario que exista en Supabase, porque la tabla configuracion
tiene clave foránea a auth.users.
"""

import json
import os
import re
import sys
import time
import urllib.parse as up
import uuid
from unittest import mock

import requests
from pathlib import Path

# Se añade la raíz del backend al path para poder importar "app"
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import app
from app.database import obtener_conexion

# --- Datos del usuario falso con el que se hacen las pruebas ---
#
# La tabla configuracion tiene usuario_id como uuid con clave foránea a
# auth.users, así que la prueba necesita un usuario de verdad: no vale un
# texto inventado como antes con SQLite. Se indica con la variable de
# entorno USUARIO_PRUEBA_ID y tiene que existir en Supabase.
#
# Las pruebas borran sus propias filas de configuracion (solo la clave
# token_drive), así que no tocan el inventario ni las ventas del usuario.
USUARIO_ID = os.getenv("USUARIO_PRUEBA_ID", "").strip()
NOMBRE_CARPETA = f"ContaVen - {USUARIO_ID}"
FECHA_LICENCIA = "2099-12-31"

fallos: list = []


def revisar(condicion: bool, mensaje: str) -> None:
    if condicion:
        print(f"  OK    {mensaje}")
    else:
        print(f"  FALLA {mensaje}")
        fallos.append(mensaje)


def sesion_falsa() -> dict:
    """Crea un cliente de Flask que ya viene "conectado" como el usuario falso."""
    return {
        "Authorization": "Bearer token_falso_de_prueba",
    }


# ------------------------------------------------------------
# Respuestas falsas de Google
# ------------------------------------------------------------
class RespuestaFalsa:
    def __init__(self, contenido, status=200):
        self._contenido = contenido
        self.status_code = status

    def json(self):
        return self._contenido

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def google_simulado(llamadas):
    """
    Reemplaza las llamadas de red de drive_service por respuestas de Google.

    Cada llamada queda anotada en "llamadas" para poder revisarla después.
    """

    def request_falso(*args, **extra):
        # Se aceptan las dos formas en que se llama a requests:
        #   requests.post(url, ...)            -> ("POST", url)
        #   requests.request(metodo, url, ...) -> ("POST", url)
        metodos_validos = ("GET", "POST", "PUT", "PATCH", "DELETE")

        if args and str(args[0]).upper() in metodos_validos:
            metodo, url = str(args[0]).upper(), args[1]
        else:
            metodo, url = "POST", args[0]

        datos = extra.get("data") or {}

        # --- Canjear código por tokens / renovar token ---
        if url.endswith("/token"):
            if isinstance(datos, dict) and datos.get("grant_type") == "refresh_token":
                llamadas.append(("renovar_token", datos.get("refresh_token")))
                return RespuestaFalsa({
                    "access_token": "access_token_RENOVADO",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                })

            llamadas.append("canjear_codigo")
            return RespuestaFalsa({
                "access_token": "access_token_NUEVO",
                "refresh_token": "refresh_token_NUEVO",
                "expires_in": 3600,
                "token_type": "Bearer",
            })

        # --- Buscar archivo por nombre ---
        if metodo == "GET" and "files" in url:
            consulta = extra.get("params", {}).get("q", "")
            llamadas.append(("buscar", consulta))
            return RespuestaFalsa({"files": []})

        # --- Subir archivo ---
        if metodo == "POST" and "upload" in url:
            cuerpo = extra.get("data", b"")
            if isinstance(cuerpo, bytes):
                cuerpo = cuerpo.decode("utf-8", "ignore")
            llamadas.append(("subir", extra.get("params", {}), cuerpo))
            return RespuestaFalsa({"id": "ID_ARCHIVO_SUBIDO"})

        # --- Crear carpeta ---
        if metodo == "POST" and "files" in url:
            llamadas.append(("crear_carpeta", extra.get("json", {})))
            return RespuestaFalsa({"id": "ID_CARPETA_CREADA"})

        return RespuestaFalsa({}, 404)

    return request_falso


class parche_google:
    """
    Sustituye a Google por el simulado mientras dura el bloque "with".

    En el servicio se usan dos funciones distintas de requests:
    requests.post para el canje de tokens y requests.request para la
    API de Drive, así que hay que reemplazar las dos.
    """

    def __init__(self, llamadas):
        self.llamadas = llamadas
        self.simulado = google_simulado(llamadas)

    def __enter__(self):
        self.post = mock.patch("app.services.drive_service.requests.post",
                               side_effect=self.simulado)
        self.request = mock.patch("app.services.drive_service.requests.request",
                                  side_effect=self.simulado)
        self.post.start()
        self.request.start()
        return self

    def __exit__(self, *_):
        self.post.stop()
        self.request.stop()
        return False


def perfil_falso(_usuario_id):
    """Perfil de Supabase simulado, con licencia vigente."""
    return {
        "id": USUARIO_ID,
        "nombre": "Usuario Drive",
        "correo": "drive@prueba.local",
        "telefono": "",
        "bloqueado": False,
        "motivo_bloqueo": None,
        "fecha_fin_licencia": FECHA_LICENCIA,
        "numero_carpeta_drive": 1,
    }


def main() -> None:
    print("=== COPIA DE SEGURIDAD EN GOOGLE DRIVE ===\n")

    # Sin un usuario real la prueba no puede ni empezar: la base rechazaría
    # el id. Se avisa aquí con el motivo claro.
    if not USUARIO_ID:
        print("Falta la variable de entorno USUARIO_PRUEBA_ID.\n")
        print("Esta prueba escribe en la tabla configuracion, que exige un")
        print("usuario existente en Supabase. Usa uno de prueba, por ejemplo:\n")
        print("    USUARIO_PRUEBA_ID=<uuid> python prueba_drive.py\n")
        sys.exit(1)

    try:
        uuid.UUID(USUARIO_ID)
    except ValueError:
        print(f"USUARIO_PRUEBA_ID no es un uuid válido: {USUARIO_ID!r}")
        sys.exit(1)

    # Se limpia lo que haya quedado de pruebas anteriores de este usuario
    with obtener_conexion() as conexion:
        conexion.execute(
            "DELETE FROM configuracion WHERE usuario_id = %s AND clave = %s",
            (USUARIO_ID, "token_drive"),
        )
        conexion.commit()

    cliente = app.test_client()
    cab = sesion_falsa()

    # La autenticación se simula para poder revisar solo la parte de Drive
    contexto = [
        mock.patch("app.blueprints.auth.verificar_token",
                   return_value={"id": USUARIO_ID, "email": "drive@prueba.local"}),
        mock.patch("app.blueprints.auth.supabase_service.obtener_perfil", side_effect=perfil_falso),
    ]
    for parche in contexto:
        parche.start()

    try:
        # --- 1. Estado inicial ---
        print("1. Estado de la configuración")
        respuesta = cliente.get("/api/drive/estado", headers=cab)
        estado = respuesta.get_json()

        revisar(estado.get("configurado") is True,
                f"Drive configurado con las llaves del .env -> {estado.get('configurado')}")
        revisar(estado.get("conectado") is False, "el usuario todavía no conectó su cuenta")
        revisar(estado.get("nombre_carpeta") == NOMBRE_CARPETA,
                f"la carpeta se llama «ContaVen - [id del usuario]» -> {estado.get('nombre_carpeta')}")

        # --- 2. URL de autorización ---
        print("\n2. URL de autorización para Google")
        respuesta = cliente.get("/api/drive/conectar", headers=cab)
        revisar(respuesta.status_code == 200,
                f"/api/drive/conectar responde 200 -> {respuesta.status_code}")

        url = respuesta.get_json()["url"]
        parametros = up.parse_qs(up.urlparse(url).query)

        revisar(url.startswith("https://accounts.google.com/o/oauth2/v2/auth"),
                "apunta a la página de autorización de Google")
        revisar(parametros.get("access_type", [""])[0] == "offline",
                "pide acceso offline, para que Google dé refresh_token")
        revisar(parametros.get("prompt", [""])[0] == "consent",
                "fuerza el consentimiento para obtener el refresh_token")
        revisar(parametros.get("scope", [""])[0] == "https://www.googleapis.com/auth/drive.file",
                "solo pide permiso sobre los archivos que crea la app")
        revisar(parametros.get("state", [""])[0] == USUARIO_ID,
                "el state lleva el id del usuario para reconocerlo al volver")
        revisar(parametros.get("redirect_uri", [""])[0].endswith("/api/drive/callback"),
                f"la redirect_uri es la del .env -> {parametros.get('redirect_uri', [''])[0]}")

        # --- 3. Callback sin token de sesión ---
        print("\n3. Vuelta de Google (callback) y guardado del token")
        llamadas: list = []

        with parche_google(llamadas):
            respuesta = cliente.get("/api/drive/callback",
                                    query_string={"code": "CODIGO", "state": USUARIO_ID})

        revisar(respuesta.status_code == 200,
                f"el callback NO pide token de sesión y responde 200 -> {respuesta.status_code}")
        revisar("text/html" in respuesta.headers.get("Content-Type", ""),
                "devuelve una paginita para el usuario, no JSON")
        revisar("conectado" in respuesta.get_data(as_text=True).lower(),
                "la página le confirma que la conexión salió bien")
        revisar("canjear_codigo" in llamadas, "se canjeó el código por tokens en Google")

        # --- 4. Se detecta la conexión ---
        print("\n4. El backend detecta la conexión")
        estado = cliente.get("/api/drive/estado", headers=cab).get_json()
        revisar(estado.get("conectado") is True,
                f"el usuario aparece como conectado -> {estado.get('conectado')}")

        # --- 5. Crear la copia ---
        print("\n5. Crear la copia de seguridad")
        llamadas.clear()

        with parche_google(llamadas):
            respuesta = cliente.post("/api/drive/copia", headers=cab)

        revisar(respuesta.status_code == 200,
                f"/api/drive/copia responde 200 -> {respuesta.status_code}")
        copia = respuesta.get_json()

        revisar(copia.get("carpeta") == NOMBRE_CARPETA,
                f"la copia fue a la carpeta del usuario -> {copia.get('carpeta')}")
        revisar(bool(copia.get("archivo")), f"devuelve el nombre del archivo -> {copia.get('archivo')}")

        acciones = [c[0] if isinstance(c, tuple) else c for c in llamadas]
        revisar("crear_carpeta" in acciones, "se buscó la carpeta en el Drive del usuario")

        creada = [c for c in llamadas if isinstance(c, tuple) and c[0] == "crear_carpeta"]
        if creada:
            revisar(creada[0][1].get("name") == NOMBRE_CARPETA,
                    f"la carpeta se creó con el nombre correcto -> {creada[0][1].get('name')}")

        subida = [c for c in llamadas if isinstance(c, tuple) and c[0] == "subir"]
        revisar(len(subida) == 1, "se subió un archivo al Drive")

        if subida:
            cuerpo = subida[0][2]
            revisar("ID_CARPETA_CREADA" in cuerpo,
                    "el archivo se subió dentro de la carpeta del usuario")
            revisar(re.search(r"respaldo_contaven_\d{8}_\d{6}\.db", cuerpo) is not None,
                    "el archivo lleva la fecha y la hora en el nombre")
            revisar("SQLite format 3" in cuerpo,
                    "el archivo subido es la base de datos SQLite")

        # --- 6. Renovación del token ---
        print("\n6. El token se renueva solo cuando caduca")

        with obtener_conexion() as conexion:
            fila = conexion.execute(
                "SELECT valor FROM configuracion WHERE usuario_id = %s AND clave = %s",
                (USUARIO_ID, "token_drive"),
            ).fetchone()
            guardado = json.loads(fila["valor"]) if fila else {}

        revisar(guardado.get("refresh_token") == "refresh_token_NUEVO",
                "se guardó el refresh_token, que es lo que permite seguir respaldando")

        # Se marca el token como caducado
        caducado = dict(guardado)
        caducado["expires_at"] = time.time() - 10
        caducado["access_token"] = "access_token_VIEJO"

        with obtener_conexion() as conexion:
            conexion.execute(
                """
                INSERT INTO configuracion (usuario_id, clave, valor) VALUES (%s, %s, %s)
                ON CONFLICT(usuario_id, clave) DO UPDATE SET valor = excluded.valor
                """,
                (USUARIO_ID, "token_drive", json.dumps(caducado)),
            )
            conexion.commit()

        llamadas.clear()
        with parche_google(llamadas):
            respuesta = cliente.post("/api/drive/copia", headers=cab)

        revisar(respuesta.status_code == 200,
                f"la copia funciona aunque el token esté vencido -> {respuesta.status_code}")
        revisar("renovar_token" in acciones or any(
            (isinstance(c, tuple) and c[0] == "renovar_token") for c in llamadas),
            "se pidió un token nuevo a Google")

        with obtener_conexion() as conexion:
            fila = conexion.execute(
                "SELECT valor FROM configuracion WHERE usuario_id = %s AND clave = %s",
                (USUARIO_ID, "token_drive"),
            ).fetchone()
            renovar = json.loads(fila["valor"])

        revisar(renovar.get("access_token") == "access_token_RENOVADO",
                "el token vencido se guardó reemplazado, sin molestar al usuario")

        # --- 7. El refresh_token viejo se conserva ---
        print("\n7. Google solo da refresh_token la primera vez")
        # Se borra el refresh_token como si nunca se hubiera recibido,
        # y se comprueba que al reconectar no se pierda el que ya había
        with obtener_conexion() as conexion:
            fila = conexion.execute(
                "SELECT valor FROM configuracion WHERE usuario_id = %s AND clave = %s",
                (USUARIO_ID, "token_drive"),
            ).fetchone()
            sin_refresh = json.loads(fila["valor"])
            sin_refresh["refresh_token"] = ""
            conexion.execute(
                """
                INSERT INTO configuracion (usuario_id, clave, valor) VALUES (%s, %s, %s)
                ON CONFLICT(usuario_id, clave) DO UPDATE SET valor = excluded.valor
                """,
                (USUARIO_ID, "token_drive", json.dumps(sin_refresh)),
            )
            conexion.commit()

        with parche_google([]):
            cliente.get("/api/drive/callback",
                        query_string={"code": "OTRO_CODIGO", "state": USUARIO_ID})

        with obtener_conexion() as conexion:
            fila = conexion.execute(
                "SELECT valor FROM configuracion WHERE usuario_id = %s AND clave = %s",
                (USUARIO_ID, "token_drive"),
            ).fetchone()
            final = json.loads(fila["valor"])

        revisar(final.get("refresh_token") == "refresh_token_NUEVO",
                "al reconectar se conserva el refresh_token que ya se tenía")

    finally:
        for parche in contexto:
            parche.stop()

    # --- 8. Sin conexión previa el error es claro ---
    print("\n8. Un usuario que nunca conectó recibe un error claro")
    contexto2 = [
        mock.patch("app.blueprints.auth.verificar_token",
                   return_value={"id": "otro-usuario-9999", "email": "nuevo@prueba.local"}),
        mock.patch("app.blueprints.auth.supabase_service.obtener_perfil",
                   side_effect=lambda _id: dict(perfil_falso(None), id="otro-usuario-9999")),
    ]
    for parche in contexto2:
        parche.start()
    try:
        respuesta = cliente.post("/api/drive/copia", headers=cab)
        revisar(respuesta.status_code == 400,
                f"sin conectar devuelve 400 -> {respuesta.status_code}")
        revisar("conectar" in respuesta.get_json().get("error", "").lower(),
                f"el error dice qué hacer -> {respuesta.get_json().get('error')}")
    finally:
        for parche in contexto2:
            parche.stop()

    # --- 9. Google rechaza el código ---
    print("\n9. Si Google rechaza el código se avisa sin romperse")
    with parche_google([]), \
         mock.patch("app.blueprints.auth.supabase_service.obtener_perfil", side_effect=perfil_falso):
        # El usuario cancela la autorización en la pantalla de Google
        respuesta = cliente.get("/api/drive/callback", query_string={
            "error": "access_denied",
            "error_description": "El usuario denegó el acceso",
        })
        revisar(respuesta.status_code == 200,
                f"responde con la paginita aunque se cancele -> {respuesta.status_code}")
        revisar("No se autorizó" in respuesta.get_data(as_text=True),
                "aclara que no se autorizó el acceso")

        # Google responde con error al canjear el código
        with mock.patch("app.services.drive_service.requests.post",
                        return_value=RespuestaFalsa(
                            {"error": "invalid_grant",
                             "error_description": "Invalid authorization code"}, 400)):
            respuesta = cliente.get("/api/drive/callback", query_string={
                "code": "CODIGO_MALO", "state": USUARIO_ID,
            })
        revisar(respuesta.status_code == 200,
                f"un código inválido no rompe el backend -> {respuesta.status_code}")
        revisar("Google no autorizó" in respuesta.get_data(as_text=True),
                "muestra un mensaje entendible")

    # --- Limpieza ---
    with obtener_conexion() as conexion:
        conexion.execute(
            "DELETE FROM configuracion WHERE usuario_id = %s AND clave = %s",
            (USUARIO_ID, "token_drive"),
        )
        conexion.commit()

    print("\n" + "=" * 60)
    if fallos:
        print(f"FALLARON {len(fallos)} COMPROBACIONES:")
        for f in fallos:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)

    print("DRIVE CORRECTO: configuración, carpeta, copia y renovación de token")
    print("=" * 60)


if __name__ == "__main__":
    main()
