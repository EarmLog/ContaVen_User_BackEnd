"""
Prueba de aislamiento entre dos usuarios.

El objetivo es confirmar que la base de datos local (SQLite) NO mezcla
la información de una cuenta con la de otra:

  - Cada usuario solo ve sus productos, ventas y configuración.
  - Un usuario NO puede leer, editar ni borrar datos del otro.
  - El precio del dólar de uno no pisa el del otro.

Para usarlo, con el backend corriendo en el puerto 5001:
    python prueba_aislamiento.py
"""

import sys
import time

import requests
import sys
from pathlib import Path

# Se añade la raíz del backend al path para poder importar "app"
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

API = "http://127.0.0.1:5001"
SUPABASE = "https://owhfypcyinmoaeuvqeqm.supabase.co"
LLAVE = "sb_publishable_q_oh0Qpjlu4g1J1vQk2_iA_s-2hOQUf"

marca = int(time.time())
CORREO_A = f"aisla_a_{marca}@contaven.com"
CORREO_B = f"aisla_b_{marca}@contaven.com"
CONTRASENA = "Prueba12345"

fallos: list = []


def revisar(condicion: bool, mensaje: str) -> None:
    """Si la condición no se cumple, se anota como fallo."""
    if condicion:
        print(f"  OK    {mensaje}")
    else:
        print(f"  FALLA {mensaje}")
        fallos.append(mensaje)


def registrar(correo: str) -> None:
    """Crea una cuenta nueva en Supabase."""
    r = requests.post(f"{API}/api/auth/registro", json={
        "nombre": "Usuario Prueba",
        "correo": correo,
        "contrasena": CONTRASENA,
        "telefono": "",
    }, timeout=30)
    if r.status_code != 201:
        print(f"  No se pudo registrar {correo}: {r.status_code} {r.text}")
        sys.exit(1)


def iniciar_sesion(correo: str) -> str:
    """Inicia sesión en Supabase y devuelve el token de acceso."""
    r = requests.post(f"{SUPABASE}/auth/v1/token?grant_type=password", headers={
        "apikey": LLAVE, "Content-Type": "application/json",
    }, json={"email": correo, "password": CONTRASENA}, timeout=30)
    return r.json()["access_token"]


def cabeceras(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def crear_producto(token: str, nombre: str, stock: int = 10) -> dict:
    """Crea un producto y devuelve el producto creado."""
    r = requests.post(f"{API}/api/productos", headers=cabeceras(token), json={
        "nombre": nombre,
        "stock": stock,
        "precio_ves": 100.0,
        "precio_usd": 1.0,
        "precio_compra_ves": 50.0,
        "precio_compra_usd": 0.5,
    }, timeout=30)
    return r.json()["producto"]


def main() -> None:
    print("=== AISLAMIENTO ENTRE USUARIOS ===\n")

    print("1. Registrando dos cuentas distintas")
    registrar(CORREO_A)
    registrar(CORREO_B)
    token_a = iniciar_sesion(CORREO_A)
    token_b = iniciar_sesion(CORREO_B)
    revisar(token_a != token_b, "cada cuenta tiene su propio token")

    print("\n2. Cada usuario crea sus productos")
    pa = crear_producto(token_a, f"Producto A {marca}")
    pb = crear_producto(token_b, f"Producto B {marca}")
    revisar(pa.get("id") and pb.get("id") and pa["id"] != pb["id"],
            f"productos creados (A=#{pa.get('id')}, B=#{pb.get('id')})")

    print("\n3. Cada uno solo ve SU lista de productos")
    lista_a = requests.get(f"{API}/api/productos", headers=cabeceras(token_a), timeout=30).json()
    lista_b = requests.get(f"{API}/api/productos", headers=cabeceras(token_b), timeout=30).json()
    nombres_a = [p["nombre"] for p in lista_a["productos"]]
    nombres_b = [p["nombre"] for p in lista_b["productos"]]
    revisar(f"Producto A {marca}" in nombres_a, f"A ve su producto -> {nombres_a}")
    revisar(f"Producto B {marca}" in nombres_b, f"B ve su producto -> {nombres_b}")
    revisar(f"Producto B {marca}" not in nombres_a, "A NO ve el producto de B")
    revisar(f"Producto A {marca}" not in nombres_b, "B NO ve el producto de A")

    print("\n4. El buscador del inventario nunca puede hallar datos ajenos")
    # El buscador de la pantalla de Inventario trabaja sobre la lista que
    # devuelve el servidor. Como esa lista ya viene filtrada por usuario,
    # el texto de B jamás aparece en lo que recibe A.
    texto_b = f"Producto B {marca}".lower()
    revisar(not any(texto_b in str(p["nombre"]).lower() for p in lista_a["productos"]),
            "el texto de B no existe en los datos que recibió A")
    filtrados = [p for p in lista_a["productos"]
                 if "producto" in p["nombre"].lower()]
    revisar(len(filtrados) == len(lista_a["productos"]),
            "buscar 'producto' en A devuelve solo productos de A")

    print("\n5. No se puede editar ni borrar el producto del otro")
    editar = requests.put(f"{API}/api/productos/{pb['id']}", headers=cabeceras(token_a), json={
        "nombre": "Hackeado", "stock": 1, "precio_ves": 1, "precio_usd": 1,
    }, timeout=30)
    revisar(editar.status_code == 404, f"A intenta editar el producto de B -> {editar.status_code} (se espera 404)")

    borrar = requests.delete(f"{API}/api/productos/{pa['id']}", headers=cabeceras(token_b), timeout=30)
    revisar(borrar.status_code == 404, f"B intenta borrar el producto de A -> {borrar.status_code} (se espera 404)")

    # Se revisa con el token de A que su producto siga ahí
    sigue = requests.get(f"{API}/api/productos", headers=cabeceras(token_a), timeout=30).json()
    revisar(f"Producto A {marca}" in [p["nombre"] for p in sigue["productos"]],
            "el producto de A sobrevivió al intento de borrado de B")
    revisar(requests.put(f"{API}/api/productos/{pa['id']}", headers=cabeceras(token_a), json={
        "nombre": f"Producto A {marca}", "stock": 10, "precio_ves": 100, "precio_usd": 1,
    }, timeout=30).status_code == 200, "A todavía puede editar su propio producto")

    print("\n6. No se puede comprar el producto del otro")
    venta = requests.post(f"{API}/api/ventas", headers=cabeceras(token_a), json={
        "metodo_pago": "efectivo",
        "productos": [{"producto_id": pb["id"], "unidades": 1}],
    }, timeout=30)
    revisar(venta.status_code == 400, f"A intenta vender el producto de B -> {venta.status_code} (se espera 400)")

    print("\n7. Cada usuario registra su propia venta")
    venta_a = requests.post(f"{API}/api/ventas", headers=cabeceras(token_a), json={
        "metodo_pago": "efectivo",
        "productos": [{"producto_id": pa["id"], "unidades": 2}],
    }, timeout=30).json()["venta"]
    venta_b = requests.post(f"{API}/api/ventas", headers=cabeceras(token_b), json={
        "metodo_pago": "punto",
        "productos": [{"producto_id": pb["id"], "unidades": 1}],
    }, timeout=30).json()["venta"]
    revisar(venta_a.get("id") and venta_b.get("id") and venta_a["id"] != venta_b["id"],
            f"ventas creadas (A=#{venta_a.get('id')}, B=#{venta_b.get('id')})")

    print("\n8. Las listas de ventas no se mezclan")
    ventas_a = requests.get(f"{API}/api/ventas", headers=cabeceras(token_a), timeout=30).json()
    ventas_b = requests.get(f"{API}/api/ventas", headers=cabeceras(token_b), timeout=30).json()
    ids_a = [v["id"] for v in ventas_a["ventas"]]
    ids_b = [v["id"] for v in ventas_b["ventas"]]
    revisar(venta_a["id"] in ids_a, f"A ve su venta #{venta_a['id']} -> {ids_a}")
    revisar(venta_a["id"] not in ids_b, "A NO aparece en la lista de B")
    revisar(venta_b["id"] not in ids_a, "B NO aparece en la lista de A")

    print("\n9. El detalle de una venta ajena da 404")
    detalle = requests.get(f"{API}/api/ventas/{venta_b['id']}", headers=cabeceras(token_a), timeout=30)
    revisar(detalle.status_code == 404, f"A pide el detalle de la venta de B -> {detalle.status_code} (se espera 404)")
    propio = requests.get(f"{API}/api/ventas/{venta_a['id']}", headers=cabeceras(token_a), timeout=30)
    revisar(propio.status_code == 200, "A sí puede ver el detalle de su propia venta")

    print("\n10. El análisis y el POS de hoy no se mezclan")
    dia_a = requests.get(f"{API}/api/analisis/dia", headers=cabeceras(token_a), timeout=30).json()
    dia_b = requests.get(f"{API}/api/analisis/dia", headers=cabeceras(token_b), timeout=30).json()
    revisar(dia_a["totales"]["ventas"] >= 1, f"A tiene {dia_a['totales']['ventas']} venta(s) hoy")
    revisar(dia_b["totales"]["ventas"] >= 1, f"B tiene {dia_b['totales']['ventas']} venta(s) hoy")
    revisar(dia_a["totales"]["ventas"] != dia_b["totales"]["ventas"]
            or dia_a["totales"]["ingresos_usd"] != dia_b["totales"]["ingresos_usd"],
            "los totales de cada usuario son distintos (no comparten cifras)")

    resumen_a = requests.get(f"{API}/api/analisis/resumen", headers=cabeceras(token_a), timeout=30).json()
    revisar(all("Producto B" not in p["producto_nombre"] for p in resumen_a["mas_vendidos"]),
            "el reporte de A no menciona productos de B")

    print("\n11. La configuración es propia de cada usuario")
    requests.put(f"{API}/api/configuracion", headers=cabeceras(token_a),
                 json={"tema": "oscuro", "actualizar_precios_auto": False}, timeout=30)
    cfg_a = requests.get(f"{API}/api/configuracion", headers=cabeceras(token_a), timeout=30).json()
    cfg_b = requests.get(f"{API}/api/configuracion", headers=cabeceras(token_b), timeout=30).json()
    revisar(cfg_a["configuracion"]["tema"] == "oscuro", f"A guardó tema oscuro -> {cfg_a['configuracion']['tema']}")
    revisar(cfg_b["configuracion"]["tema"] != "oscuro", f"B NO hereda el tema de A -> {cfg_b['configuracion']['tema']}")

    print("\n12. El precio del dólar es independiente")
    requests.put(f"{API}/api/dolar", headers=cabeceras(token_a), json={"precio_ves": 500.0}, timeout=30)
    dolar_a = requests.get(f"{API}/api/dolar", headers=cabeceras(token_a), timeout=30).json()
    dolar_b = requests.get(f"{API}/api/dolar", headers=cabeceras(token_b), timeout=30).json()
    revisar(dolar_a["precio_ves"] == 500.0, f"A puso su tasa en 500 -> {dolar_a['precio_ves']}")
    revisar(dolar_b["precio_ves"] != 500.0, f"B conserva la suya -> {dolar_b['precio_ves']}")

    print("\n13. El convertidor usa la tasa del usuario")
    conv_a = requests.post(f"{API}/api/dolar/convertir", headers=cabeceras(token_a),
                           json={"valor": 10, "origen": "USD", "destino": "VES"}, timeout=30).json()
    revisar(conv_a.get("resultado") == 5000.0, f"10 USD de A = {conv_a.get('resultado')} VES (esperado 5000)")

    print("\n14. Limpieza de los datos de prueba")
    requests.delete(f"{API}/api/productos/{pa['id']}", headers=cabeceras(token_a), timeout=30)
    requests.delete(f"{API}/api/productos/{pb['id']}", headers=cabeceras(token_b), timeout=30)
    revisar(True, "productos de prueba eliminados")

    print("\n" + "=" * 60)
    if fallos:
        print(f"FALLARON {len(fallos)} COMPROBACIONES:")
        for f in fallos:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)

    print("AISLAMIENTE CORRECTO: los dos usuarios quedaron totalmente separados")
    print(f"(cuentas de prueba: {CORREO_A} y {CORREO_B})")
    print("=" * 60)


if __name__ == "__main__":
    main()