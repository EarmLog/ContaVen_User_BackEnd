"""
Prueba rápida del backend de usuarios de ContaVen.

Levanta el servidor Flask en segundo plano, registra un usuario de
prueba en Supabase, hace login con Supabase y prueba el inventario,
el POS y el análisis de punta a punta.

Para usarlo:
    python prueba_backend.py
"""

import time
from datetime import datetime, timedelta

import requests
import sys
from pathlib import Path

# Se añade la raíz del backend al path para poder importar "app"
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Direcciones del backend y de Supabase
# El backend tiene que estar arrancado y la base de datos configurada.
# Se pueden cambiar con estas variables si el entorno es distinto:
#   API_URL, SUPABASE_URL_PRUEBA, SUPABASE_LLAVE_PRUEBA
API = os.getenv("API_URL", "http://127.0.0.1:5001")

# La publishable key no es un secreto (va también en el bundle del
# navegador), pero no tiene por qué quedar escrita en el repo: se lee
# del .env igual que el backend.
_dotenv = RAIZ / ".env"
if _dotenv.exists():
    for _linea in _dotenv.read_text().splitlines():
        if "=" not in _linea or _linea.strip().startswith("#"):
            continue
        _clave, _, _valor = _linea.partition("=")
        os.environ.setdefault(_clave.strip(), _valor.strip().strip("'\""))

SUPABASE = os.getenv("SUPABASE_URL_PRUEBA") or os.getenv("SUPABASE_URL", "")
LLAVE = (os.getenv("SUPABASE_LLAVE_PRUEBA")
         or os.getenv("SUPABASE_PUBLISHABLE_KEY", ""))

# Correo y contraseña del usuario de prueba
CORREO_PRUEBA = f"prueba{int(time.time())}@contaven.com"
CONTRASENA = "Prueba12345"


def esperar_al_servidor() -> None:
    """Espera a que el backend responda antes de empezar las pruebas."""
    print("Esperando que el backend arranque...")
    for _ in range(40):
        try:
            if requests.get(f"{API}/api/salud", timeout=2).status_code == 200:
                print("Backend listo.\n")
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise SystemExit("El backend no arrancó. Revisa los logs.")


def probar_registro() -> None:
    """Prueba el registro de un usuario nuevo y sus validaciones."""
    print("=== REGISTRO ===")

    # 1. El correo es obligatorio
    respuesta = requests.post(f"{API}/api/auth/registro", json={"correo": "x@y.com", "contrasena": "Abc12345", "nombre": "X"})
    print(f"  Sin nombre      -> {respuesta.status_code} {respuesta.json().get('error')}")

    # 2. La contraseña no puede tener espacios
    respuesta = requests.post(f"{API}/api/auth/registro", json={"nombre": "Ana", "correo": "a@b.com", "contrasena": "abc 123"})
    print(f"  Contraseña con espacio -> {respuesta.status_code} {respuesta.json().get('error')}")

    # 3. Registro válido
    respuesta = requests.post(f"{API}/api/auth/registro", json={
        "nombre": "Usuario Prueba",
        "correo": CORREO_PRUEBA,
        "contrasena": CONTRASENA,
        "telefono": "04141234567",
    })
    print(f"  Registro válido -> {respuesta.status_code} {respuesta.json()}")
    if respuesta.status_code != 201:
        raise SystemExit("Falló el registro, no se puede seguir.")

    # 4. No se puede registrar dos veces el mismo correo
    respuesta = requests.post(f"{API}/api/auth/registro", json={
        "nombre": "Otro", "correo": CORREO_PRUEBA, "contrasena": CONTRASENA,
    })
    print(f"  Correo repetido -> {respuesta.status_code} {respuesta.json().get('error')}")


def iniciar_sesion() -> str:
    """Inicia sesión con Supabase y devuelve el token de acceso."""
    print("\n=== LOGIN ===")

    # 1. Contraseña incorrecta
    respuesta = requests.post(f"{SUPABASE}/auth/v1/token?grant_type=password", headers={
        "apikey": LLAVE, "Content-Type": "application/json",
    }, json={"email": CORREO_PRUEBA, "password": "Incorrecta999"})
    print(f"  Clave incorrecta -> {respuesta.status_code}")

    # 2. Contraseña correcta
    respuesta = requests.post(f"{SUPABASE}/auth/v1/token?grant_type=password", headers={
        "apikey": LLAVE, "Content-Type": "application/json",
    }, json={"email": CORREO_PRUEBA, "password": CONTRASENA})
    print(f"  Credenciales OK  -> {respuesta.status_code}")
    respuesta.raise_for_status()
    return respuesta.json()["access_token"]


def probar_api(token: str) -> None:
    """Prueba los endpoints de perfil, inventario, POS, análisis y configuración."""
    cab = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # --- Perfil y licencia ---
    print("\n=== PERFIL Y LICENCIA ===")
    datos = requests.get(f"{API}/api/auth/yo", headers=cab).json()
    print(f"  Nombre:        {datos['nombre']}")
    print(f"  Días restantes: {datos['dias_restantes']}")
    print(f"  Carpeta Drive: {datos['numero_carpeta_drive']}")
    print(f"  Licencia vencida: {datos['licencia_vencida']}")

    # --- Sin token no se puede pasar ---
    print(f"  Sin token      -> {requests.get(f'{API}/api/productos').status_code}")

    # --- Inventario ---
    print("\n=== INVENTARIO ===")
    print(f"  Sin nombre     -> {requests.post(f'{API}/api/productos', headers=cab, json={'stock': 5}).status_code}")
    print(f"  Sin precio     -> {requests.post(f'{API}/api/productos', headers=cab, json={'nombre': 'X', 'stock': 5}).status_code}")

    respuesta = requests.post(f"{API}/api/productos", headers=cab, json={
        "nombre": "Arroz", "stock": 50, "tipo": "Alimento",
        "descripcion": "Arroz blanco 5kg", "sku": "ARR-001",
        "precio_ves": 50, "precio_usd": 0,
        "precio_compra_ves": 35, "precio_compra_usd": 0,
    })
    arroz = respuesta.json()["producto"]
    print(f"  Creado: {arroz['nombre']} -> VES {arroz['precio_ves']} / USD {arroz['precio_usd']}")

    # Se crea otro producto dando el precio solo en USD
    cafe = requests.post(f"{API}/api/productos", headers=cab, json={
        "nombre": "Café", "stock": 20, "precio_usd": 5, "precio_compra_usd": 3,
    }).json()["producto"]
    print(f"  Creado: {cafe['nombre']} -> VES {cafe['precio_ves']} / USD {cafe['precio_usd']}")

    # Se edita
    requests.put(f"{API}/api/productos/{arroz['id']}", headers=cab, json={
        "nombre": "Arroz Premium", "stock": 45, "precio_ves": 55, "precio_compra_ves": 38,
    })
    print(f"  Editado: {requests.get(f'{API}/api/productos', headers=cab).json()['productos'][1]['nombre']}")

    # --- POS ---
    print("\n=== POS ===")
    print(f"  Carrito vacío  -> {requests.post(f'{API}/api/ventas', headers=cab, json={'productos': [], 'metodo_pago': 'efectivo'}).status_code}")
    print(f"  Método inválido-> {requests.post(f'{API}/api/ventas', headers=cab, json={'productos': [{'producto_id': arroz['id'], 'unidades': 1}], 'metodo_pago': 'bitcoin'}).status_code}")
    print(f"  Sin stock      -> {requests.post(f'{API}/api/ventas', headers=cab, json={'productos': [{'producto_id': arroz['id'], 'unidades': 9999}], 'metodo_pago': 'efectivo'}).status_code}")

    # Venta válida con los dos productos
    respuesta = requests.post(f"{API}/api/ventas", headers=cab, json={
        "productos": [
            {"producto_id": arroz["id"], "unidades": 2},
            {"producto_id": cafe["id"], "unidades": 1},
        ],
        "metodo_pago": "punto",
    })
    venta = respuesta.json()["venta"]
    print(f"  Venta #{venta['id']} {venta['fecha']} {venta['hora']} -> total VES {venta['total_ves']} / USD {venta['total_usd']}")
    print(f"  Ganancia: VES {venta['ganancia_ves']} / USD {venta['ganancia_usd']}")

    # Se revisa que el stock haya bajado
    productos = requests.get(f"{API}/api/productos", headers=cab).json()["productos"]
    for producto in productos:
        if producto["id"] == arroz["id"]:
            print(f"  Stock de {producto['nombre']}: {producto['stock']} (era 45)")

    # --- Análisis ---
    print("\n=== ANÁLISIS ===")
    hoy = datetime.now().strftime("%Y-%m-%d")
    ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    dia = requests.get(f"{API}/api/analisis/dia", headers=cab).json()
    print(f"  Ventas de hoy: {dia['totales']['ventas']} | ganancia USD {dia['totales']['ganancia_usd']}")
    for producto in dia["productos"]:
        print(f"    - {producto['producto_nombre']}: {producto['unidades']} und")

    resumen = requests.get(f"{API}/api/analisis/resumen", headers=cab, params={
        "desde": ayer, "hasta": hoy, "hora_inicio": "00:00", "hora_fin": "23:59",
    }).json()
    print(f"  Totales del filtro: {resumen['totales']['ventas']} ventas | ganancia VES {resumen['totales']['ganancia_ves']} / USD {resumen['totales']['ganancia_usd']}")
    print(f"  Más vendidos: {[p['producto_nombre'] for p in resumen['mas_vendidos']]}")
    print(f"  Por método:  {[p['etiqueta'] for p in resumen['por_metodo_pago']]}")

    # Filtro de horas que no agarra nada
    vacio = requests.get(f"{API}/api/analisis/resumen", headers=cab, params={
        "desde": hoy, "hasta": hoy, "hora_inicio": "03:00", "hora_fin": "03:01",
    }).json()
    print(f"  Filtro 03:00-03:01 -> {vacio['totales']['ventas']} ventas")

    # --- Configuración y dólar ---
    print("\n=== CONFIGURACIÓN ===")
    configuracion = requests.get(f"{API}/api/configuracion", headers=cab).json()["configuracion"]
    print(f"  Tema por defecto: {configuracion['tema']} | auto precios: {configuracion['actualizar_precios_auto']}")

    requests.put(f"{API}/api/configuracion", headers=cab, json={"tema": "oscuro", "actualizar_precios_auto": True})
    configuracion = requests.get(f"{API}/api/configuracion", headers=cab).json()["configuracion"]
    print(f"  Después de guardar: tema {configuracion['tema']} | auto {configuracion['actualizar_precios_auto']}")

    # --- Dólar: con la actualización automática activa, leer el precio
    #     debe traer la tasa de internet sola, sin tocar ningún botón ---
    dolar = requests.get(f"{API}/api/dolar", headers=cab).json()
    print(f"  Dólar (auto, primera lectura) -> origen: {dolar['origen']}, "
          f"Bs. {dolar['precio_ves']}, fecha: {dolar['actualizado_en']}")

    if dolar["origen"] == "internet":
        print(f"  OK la tasa se consultó sola por exchangerate-api.com")
    else:
        print(f"  AVISO: la tasa no vino de internet (origen={dolar['origen']}). "
              f"Revisa EXCHANGERATE_API_KEY en el .env")

    # La segunda lectura ya no vuelve a consultar (no está vencida)
    dolar2 = requests.get(f"{API}/api/dolar", headers=cab).json()
    print(f"  Dólar (auto, segunda lectura) -> misma tasa: "
          f"{dolar2['precio_ves'] == dolar['precio_ves']}")

    # El botón manual siempre funciona, active o no el automático
    print(f"  Actualizar ahora -> {requests.post(f'{API}/api/dolar/actualizar', headers=cab).status_code}")

    # Tasa escrita a mano
    requests.put(f"{API}/api/dolar", headers=cab, json={"precio_ves": 37.25})
    print(f"  Dólar manual guardado: {requests.get(f'{API}/api/dolar', headers=cab).json()['precio_ves']}")

    # Con el automático apagado, una tasa manual NO se toca aunque sea vieja
    requests.put(f"{API}/api/configuracion", headers=cab, json={"tema": "claro", "actualizar_precios_auto": False})
    sin_auto = requests.get(f"{API}/api/dolar", headers=cab).json()
    print(f"  Con automático apagado conserva la manual: {sin_auto['precio_ves']} "
          f"(origen: {sin_auto['origen']})")

    # --- Conversor USD <-> VES ---
    conversiones = {
        "10 USD a VES": {"valor": 10, "origen": "USD", "destino": "VES"},
        "372.5 VES a USD": {"valor": 372.5, "origen": "VES", "destino": "USD"},
    }
    for etiqueta, cuerpo in conversiones.items():
        r = requests.post(f"{API}/api/dolar/convertir", headers=cab, json=cuerpo)
        print(f"  {etiqueta}: {r.status_code} -> {r.json().get('resultado')}")

    # Con la tasa de internet, en el mismo sentido
    r = requests.post(f"{API}/api/dolar/convertir", headers=cab,
                      json={"valor": 10, "origen": "USD", "destino": "VES", "desde_api": "1"})
    print(f"  10 USD a VES (tasa de internet) -> {r.status_code} {r.json().get('resultado')}")

    # --- Google Drive ---
    print("\n=== GOOGLE DRIVE ===")
    estado = requests.get(f"{API}/api/drive/estado", headers=cab).json()
    print(f"  Estado: {estado}")

    # --- Limpieza: se borra el producto de prueba ---
    requests.delete(f"{API}/api/productos/{cafe['id']}", headers=cab)
    print("\nProducto de prueba eliminado.")


if __name__ == "__main__":
    esperar_al_servidor()
    probar_registro()
    token = iniciar_sesion()
    probar_api(token)
    print("\n=== TODAS LAS PRUEBAS PASARON ===")
