-- ============================================================
-- ContaVen - Migración 005: Tablas de negocio en Postgres
-- ============================================================
-- Estas tablas antes vivían en un SQLite dentro del backend (database.db).
-- Se movieron a Postgres porque Vercel no permite escribir en disco:
-- cada request corre en un contenedor nuevo y de solo lectura, así que
-- el inventario y las ventas se perdían en cada invocación.
--
-- Siguen siendo datos EXCLUSIVOS del backend Flask. El frontend nunca
-- las toca directo: siempre pasa por la API, que mete el usuario_id
-- que viene del token de sesión en el WHERE de cada consulta.
-- ============================================================

-- ------------------------------------------------------------
-- Tabla: productos (el inventario)
-- ------------------------------------------------------------
create table if not exists public.productos (
    id                  bigint generated always as identity primary key,
    usuario_id          uuid          not null references auth.users (id) on delete cascade,
    nombre              text          not null,
    stock               integer       not null default 0,
    tipo                text,
    descripcion         text,
    sku                 text,
    precio_ves          numeric(14,2) not null default 0,
    precio_usd          numeric(14,2) not null default 0,
    precio_compra_ves   numeric(14,2) not null default 0,
    precio_compra_usd   numeric(14,2) not null default 0,
    creado_en           timestamptz   not null default now(),
    actualizado_en      timestamptz   not null default now(),

    -- El stock nunca puede ser negativo (el POS valida antes, pero esto
    -- deja la base protegida aunque dos ventas lleguen al mismo tiempo)
    constraint productos_stock_no_negativo check (stock >= 0)
);

comment on table public.productos is 'Inventario del negocio. Cada fila tiene el usuario_id de su dueno.';

-- El inventario se ordena por nombre sin importar mayusculas,
-- como se hacia con COLLATE NOCASE en SQLite
create index if not exists idx_productos_usuario on public.productos (usuario_id);
create index if not exists idx_productos_usuario_nombre on public.productos (usuario_id, lower(nombre));

-- ------------------------------------------------------------
-- Tabla: ventas (una fila por venta registrada en el POS)
-- ------------------------------------------------------------
create table if not exists public.ventas (
    id                  bigint generated always as identity primary key,
    usuario_id          uuid          not null references auth.users (id) on delete cascade,

    -- fecha y hora van separadas porque los filtros de Análisis
    -- las usan por separado (rango de fechas, rango de horas).
    -- En SQLite eran TEXT; en Postgres son tipos de verdade para
    -- que se puedan comparar e indexar bien.
    fecha               date          not null,
    hora                time          not null,

    metodo_pago         text          not null,
    total_ves           numeric(14,2) not null default 0,
    total_usd           numeric(14,2) not null default 0,
    costo_total_ves     numeric(14,2) not null default 0,
    costo_total_usd     numeric(14,2) not null default 0,
    ganancia_ves        numeric(14,2) not null default 0,
    ganancia_usd        numeric(14,2) not null default 0,
    precio_dolar        numeric(14,2) not null default 0,
    creado_en           timestamptz   not null default now(),

    constraint ventas_metodo_pago check (metodo_pago in ('efectivo', 'punto', 'pagomovil', 'app'))
);

comment on table public.ventas is 'Cabecera de cada venta del punto de venta. Los totales y la ganancia se guardan ya calculados.';

create index if not exists idx_ventas_usuario on public.ventas (usuario_id);

-- Índice compuesto para los reportes de Análisis, que siempre
-- filtran por usuario y luego por rango de fechas
create index if not exists idx_ventas_usuario_fecha on public.ventas (usuario_id, fecha);

-- ------------------------------------------------------------
-- Tabla: productos_vendidos (el detalle de cada venta)
-- ------------------------------------------------------------
create table if not exists public.productos_vendidos (
    id                      bigint generated always as identity primary key,
    usuario_id              uuid          not null references auth.users (id) on delete cascade,
    venta_id                bigint        not null references public.ventas (id) on delete cascade,

    -- Si se borra un producto del inventario, las ventas ya registradas
    -- NO se borran (el historial no se pierde), pero producto_id queda
    -- en null y el nombre que se guardó sirve de respaldo
    producto_id             bigint        references public.productos (id) on delete set null,
    producto_nombre         text          not null,

    unidades                integer       not null,
    precio_unitario_ves     numeric(14,2) not null default 0,
    precio_unitario_usd     numeric(14,2) not null default 0,
    costo_unitario_ves      numeric(14,2) not null default 0,
    costo_unitario_usd      numeric(14,2) not null default 0,
    subtotal_ves            numeric(14,2) not null default 0,
    subtotal_usd            numeric(14,2) not null default 0,
    ganancia_ves            numeric(14,2) not null default 0,
    ganancia_usd            numeric(14,2) not null default 0,

    constraint productos_vendidos_unidades check (unidades > 0)
);

comment on table public.productos_vendidos is 'Que productos se vendieron en cada venta, con su precio, costo y ganancia.';

create index if not exists idx_productos_vendidos_usuario on public.productos_vendidos (usuario_id);
create index if not exists idx_productos_vendidos_venta on public.productos_vendidos (venta_id);

-- ------------------------------------------------------------
-- Tabla: configuracion (preferencias del usuario)
-- Una fila por ajuste. La clave primaria es compuesta para que
-- dos usuarios puedan tener el mismo ajuste con valores distintos.
-- ------------------------------------------------------------
create table if not exists public.configuracion (
    usuario_id      uuid        not null references auth.users (id) on delete cascade,
    clave           text        not null,
    valor           text,
    actualizado_en  timestamptz not null default now(),
    primary key (usuario_id, clave)
);

comment on table public.configuracion is 'Preferencias de cada usuario: tema, actualizacion automatica, token de Drive, etc.';

-- ------------------------------------------------------------
-- Tabla: precios_dolar (historial de tasas)
-- ------------------------------------------------------------
create table if not exists public.precios_dolar (
    id              bigint generated always as identity primary key,
    usuario_id      uuid          not null references auth.users (id) on delete cascade,
    precio_ves      numeric(14,2) not null,
    origen          text,
    actualizado_en  timestamptz   not null default now()
);

comment on table public.precios_dolar is 'Historial de precios del dolar (VES por 1 USD) que ha usado cada usuario.';

create index if not exists idx_precios_dolar_usuario on public.precios_dolar (usuario_id);

-- ------------------------------------------------------------
-- Seguridad: estas tablas son solo del backend
-- ------------------------------------------------------------
-- Se activa RLS en las 5 tablas y NO se crea ninguna política para
-- los roles "anon" ni "authenticated", así que el navegador no puede
-- leerlas ni escribirlas aunque tenga la publishable key.
-- El backend entra con la secret key (service_role), que sí pasa
-- RLS, y es el único que las usa.
--
-- El frontend nunca habla con estas tablas directamente: todo pasa
-- por la API Flask, que mete el usuario_id del token en el WHERE.
alter table public.productos           enable row level security;
alter table public.ventas              enable row level security;
alter table public.productos_vendidos  enable row level security;
alter table public.configuracion       enable row level security;
alter table public.precios_dolar       enable row level security;

-- ------------------------------------------------------------
-- Mantener actualizado_en solo (SQLite lo hacia en el codigo)
-- ------------------------------------------------------------
create or replace function public.tocar_actualizado_en() returns trigger
language plpgsql as $$
begin
    new.actualizado_en := now();
    return new;
end;
$$;

create trigger trg_productos_actualizado
    before update on public.productos
    for each row execute function public.tocar_actualizado_en();

create trigger trg_configuracion_actualizado
    before update on public.configuracion
    for each row execute function public.tocar_actualizado_en();