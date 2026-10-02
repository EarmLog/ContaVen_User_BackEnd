# ContaVen — Backend de usuarios

API en Flask para la aplicación de usuarios de ContaVen. Aquí viven el inventario, el punto de venta y los reportes que usa un comercio en su día a día.

## Qué es ContaVen

ContaVen es una aplicación para pequeños y medianos comercios que quieren llevar su inventario y sus ventas sin complicarse. El negocio trabaja en dos monedas a la vez, bolívares y dólares, y necesita ver cuánto gana de verdad en cada operación. Esta API es la mitad del sistema: el frontend de usuarios se apoya en ella para todo lo relacionado con productos, ventas, análisis y ajustes.

Supabase se encarga únicamente de la autenticación y de las licencias. Los datos del negocio (inventario, ventas, precios) no salen del equipo: se guardan en un archivo SQLite local.

## Qué resuelve

- Llevar el inventario con precios en VES y USD que se calculan entre sí con la tasa del día.
- Registrar ventas desde un punto de venta y descontar el stock en el momento.
- Conocer la ganancia real de cada venta y del período, no solo el ingreso.
- Ver reportes por día, mes, hora y método de pago.
- Mantener el precio del dólar actualizado automáticamente, con opción de escribirlo a mano.
- Resguardar los datos de cada cuenta: nadie ve el inventario ni las ventas de otro.
- Copiar la base de datos a Google Drive (opcional).

## Cómo está armado

- **Flask 3** con las rutas separadas por módulo (blueprints).
- **SQLite** para los datos del negocio, con una columna `usuario_id` en cada tabla.
- **Supabase** para registrar usuarios, iniciar sesión y revisar la licencia; el token se valida con las llaves públicas (JWKS).
- La tasa del dólar se consulta a **exchangerate-api** y se guarda un historial en `precios_dolar`.

El id del usuario sale del token de sesión y se mete en el `WHERE` de todas las consultas, así que el aislamiento entre cuentas no depende del frontend.

## Requisitos

- Python 3.10 o superior
- Una cuenta de Supabase con las tablas `perfiles` y `administradores` (ver la carpeta `supabase/` del proyecto general)

## Instalación

```bash
cd ContaVen_User_BackEnd
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.ejemplo .env
```

Después abre el `.env` y completa al menos `SUPABASE_SECRET_KEY` y, si quieres que la tasa se actualice sola, `EXCHANGERATE_API_KEY`.

## Variables de entorno

| Variable | Para qué sirve |
| --- | --- |
| `PUERTO` | Puerto del servidor (por defecto 5001) |
| `SUPABASE_URL` | Dirección del proyecto de Supabase |
| `SUPABASE_SECRET_KEY` | Llave secreta para las operaciones de servidor. No se comparte |
| `SUPABASE_PUBLISHABLE_KEY` | Llave pública, se puede usar en el navegador |
| `SUPABASE_JWKS_URL` | Dirección de las llaves públicas para validar los tokens |
| `RUTA_BASE_DATOS` | Nombre del archivo SQLite (por defecto `database.db`) |
| `DIAS_LICENCIA_INICIAL` | Días que recibe una cuenta nueva (30) |
| `PRECIO_DOLAR_POR_DEFECTO` | Tasa que se usa si todavía no hay una consultada |
| `EXCHANGERATE_API_KEY` | Llave de exchangerate-api para la tasa del dólar |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Credenciales de Google Drive (opcional) |

El `.env` está en `.gitignore`; no se sube nunca al repositorio.

## Cómo arrancarlo

```bash
.venv/bin/python run.py
```

El servidor queda en `http://localhost:5001`. Para comprobar que responde:

```bash
curl http://localhost:5001/api/salud
```

`run.py` carga el `.env` antes de importar la app, así que se puede arrancar desde cualquier carpeta. La primera vez crea las tablas y, si encuentra una base vieja sin `usuario_id`, la migra sola.

> El `.env` y `database.db` viven en la raíz de este backend, no dentro de `app/`. No los muevas: `app/config.py` los busca ahí.

## Endpoints

Todos salvo `/api/auth/registro` y `/api/salud` piden el encabezado `Authorization: Bearer <token>`.

**Autenticación y licencia**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| POST | `/api/auth/registro` | Crea la cuenta y le da los días de licencia |
| GET | `/api/auth/yo` | Devuelve el perfil, los días restantes y si está bloqueado |

**Inventario**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET | `/api/productos` | Lista los productos de la cuenta |
| POST | `/api/productos` | Agrega un producto |
| PUT | `/api/productos/<id>` | Edita un producto |
| DELETE | `/api/productos/<id>` | Elimina un producto |

**Ventas**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| POST | `/api/ventas` | Registra una venta y descuenta el stock |
| GET | `/api/ventas` | Lista las ventas con filtros por fecha y hora |
| GET | `/api/ventas/<id>` | Detalle de una venta con sus productos |

**Análisis**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET | `/api/analisis/resumen` | Totales, más vendidos y datos para las gráficas |
| GET | `/api/analisis/dia` | Lo vendido hoy, para la pantalla de inicio |

**Configuración y dólar**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET / PUT | `/api/configuracion` | Lee y guarda las preferencias |
| GET / PUT | `/api/dolar` | Lee y fija la tasa |
| POST | `/api/dolar/actualizar` | Busca la tasa por internet |
| POST | `/api/dolar/convertir` | Convierte entre VES y USD |
| GET | `/api/dolar/historico` | Historial de tasas |

**Copia de seguridad**

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET | `/api/drive/estado` | Si Drive está conectado |
| GET | `/api/drive/conectar` | Inicia la autorización con Google |
| GET | `/api/drive/callback` | Recibe la respuesta de Google |
| POST | `/api/drive/copia` | Sube una copia de la base |

## Estructura

```
ContaVen_User_BackEnd/
├── run.py                  # punto de entrada: python run.py
├── requirements.txt
├── .env / .env.ejemplo
├── database.db             # datos del negocio
├── app/
│   ├── __init__.py         # fábrica de la app Flask y CORS
│   ├── config.py           # lee el .env
│   ├── database.py         # SQLite, tablas y dueño de cada dato
│   ├── blueprints/         # rutas: auth, productos, ventas, analisis, configuracion, drive_backup
│   ├── services/           # supabase_service, drive_service, tipos_cambio
│   └── utils/              # security (validación y sanitización)
└── tests/
    ├── prueba_backend.py
    ├── prueba_aislamiento.py
    └── prueba_drive.py
```

Dentro de cada módulo los comentarios explican qué hace cada parte. En resumen: `blueprints/` tiene las rutas, `services/` habla con Supabase, Drive y exchangerate, y `utils/` guarda funciones de apoyo.

## Base de datos

Cinco tablas en SQLite: `productos`, `ventas`, `productos_vendidos`, `configuracion` y `precios_dolar`. Todas llevan `usuario_id`, salvo `configuracion`, que se separa por su llave compuesta.

La ganancia se guarda calculada en cada venta como `(precio de venta − precio de compra) × unidades`, en las dos monedas.

## Pruebas

Necesitan el backend corriendo en el puerto 5001.

```bash
.venv/bin/python tests/prueba_backend.py
.venv/bin/python tests/prueba_aislamiento.py
.venv/bin/python tests/prueba_drive.py
```

`prueba_aislamiento.py` registra dos cuentas y comprueba que una no puede ver ni tocar los datos de la otra.

## Notas

- Sin llaves de Google, el botón de copia de seguridad queda deshabilitado, pero todo lo demás funciona igual.
- Si la tasa guardada tiene más de `MINUTOS_ACTUALIZACION_DOLAR` minutos, se refresca sola cuando alguien abre la app.
- Si el puerto 5001 está ocupado, cambia `PUERTO` en el `.env`.
