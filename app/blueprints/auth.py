"""
Rutas de autenticación y licencia.

Endpoints:
  POST /api/auth/registro   -> crea el usuario en Supabase con 30 días de licencia
  GET  /api/auth/yo         -> devuelve los datos del usuario y su licencia
"""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..services import supabase_service
from ..services.supabase_service import verificar_token

rutas_auth = Blueprint("auth", __name__, url_prefix="/api/auth")


# ------------------------------------------------------------
# Utilidad: tomar el usuario del token y revisar su licencia
# ------------------------------------------------------------
def cargar_usuario_autenticado() -> tuple:
    """
    Revisa el token que viene en la cabecera Authorization.
    Devuelve una tupla (respuesta_json, codigo_http).
    Si el token no es válido o el usuario está bloqueado, devuelve el error.
    """
    # Se saca el token de la cabecera "Authorization: Bearer <token>"
    cabecera = request.headers.get("Authorization", "")
    token = cabecera.replace("Bearer ", "").strip()

    # Sin token no se puede pasar
    if not token:
        return jsonify({"error": "No has iniciado sesión."}), 401

    # Se valida el token con Supabase
    datos_usuario = verificar_token(token)
    if not datos_usuario:
        return jsonify({"error": "Tu sesión expiró. Vuelve a iniciar sesión."}), 401

    # Se busca el perfil del usuario en Supabase
    perfil = supabase_service.obtener_perfil(datos_usuario["id"])
    if not perfil:
        return jsonify({"error": "Tu perfil no está creado. Regístrate de nuevo."}), 403

    # Si el administrador lo bloqueó, no puede usar la app
    if perfil.get("bloqueado"):
        motivo = perfil.get("motivo_bloqueo") or "Contacta al administrador para renovar tu licencia."
        return jsonify({"error": f"Acceso bloqueado. {motivo}", "bloqueado": True}), 403

    # Se guarda el perfil en "g" para que las otras rutas lo usen
    g.perfil = perfil
    return None, None


# ------------------------------------------------------------
# POST /api/auth/registro
# Crea el usuario y le asigna los 30 días de licencia
# ------------------------------------------------------------
@rutas_auth.post("/registro")
def registrar():
    """Recibe nombre, correo, contraseña y teléfono, y crea la cuenta en Supabase."""
    datos = request.get_json(silent=True) or {}

    nombre = (datos.get("nombre") or "").strip()
    correo = (datos.get("correo") or "").strip().lower()
    contrasena = datos.get("contrasena") or ""
    telefono = (datos.get("telefono") or "").strip()

    # --- Validaciones de los campos ---
    if not nombre:
        return jsonify({"error": "El nombre es obligatorio."}), 400

    if not correo:
        return jsonify({"error": "El correo es obligatorio."}), 400

    if not contrasena:
        return jsonify({"error": "La contraseña es obligatoria."}), 400

    # El nombre puede tener espacios, pero no puede tener espacios al principio o al final
    if nombre != nombre.strip() or "  " in nombre:
        return jsonify({"error": "El nombre no puede tener espacios dobles ni al final."}), 400

    # La contraseña no puede tener espacios
    if " " in contrasena:
        return jsonify({"error": "La contraseña no puede tener espacios."}), 400

    # El teléfono es opcional pero si viene no puede tener espacios
    if telefono and " " in telefono:
        return jsonify({"error": "El número de teléfono no puede tener espacios."}), 400

    try:
        # Se crea el usuario en la autenticación de Supabase
        usuario_id = supabase_service.registrar_usuario_supabase(correo, contrasena, nombre, telefono)

        # Se crea el perfil con los 30 días gratis y su número de carpeta de Drive
        supabase_service.crear_perfil(usuario_id, nombre, correo, telefono)

    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({
        "mensaje": "¡Cuenta creada! Ya puedes iniciar sesión.",
        "licencia": "Recibiste 30 días gratis.",
    }), 201


# ------------------------------------------------------------
# GET /api/auth/yo
# Devuelve los datos del usuario, su licencia y el precio del dólar
# ------------------------------------------------------------
@rutas_auth.get("/yo")
def yo():
    """Revisa el token, la licencia del usuario y devuelve su información."""
    # Se revisa el token y el bloqueo
    error, codigo = cargar_usuario_autenticado()
    if error:
        return error, codigo

    perfil = g.perfil

    # Se calculan los días que le quedan según la fecha de vencimiento
    dias_restantes = calcular_dias_restantes(perfil["fecha_fin_licencia"])

    return jsonify({
        "id": perfil["id"],
        "nombre": perfil["nombre"],
        "correo": perfil["correo"],
        "telefono": perfil.get("telefono"),
        "numero_carpeta_drive": perfil["numero_carpeta_drive"],
        "dias_licencia": perfil["dias_licencia"],
        "dias_restantes": dias_restantes,
        "fecha_fin_licencia": perfil["fecha_fin_licencia"],
        "licencia_vencida": dias_restantes <= 0,
        "bloqueado": perfil.get("bloqueado", False),
    })


# ------------------------------------------------------------
# Utilidad: calcular días restantes
# ------------------------------------------------------------
def calcular_dias_restantes(fecha_fin: str) -> int:
    """
    Cuenta cuántos días le faltan entre hoy y la fecha de fin de licencia.
    Si la fecha ya pasó devuelve 0. Nunca devuelve números negativos.
    """
    try:
        # Se pasa la fecha que viene de Supabase a formato datetime
        fin = datetime.fromisoformat(fecha_fin.replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        diferencia = fin - ahora

        # Se convierte a días y se redondea hacia arriba
        dias = int(-(-diferencia.total_seconds() // 86400))
        return max(dias, 0)
    except Exception:
        return 0
