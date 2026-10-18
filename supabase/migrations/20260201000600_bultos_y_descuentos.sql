-- ============================================================
-- ContaVen - Migración 006: Bultos y descuentos al tanto / al mayor
-- ============================================================
-- Se agregan dos funciones nuevas al inventario y al POS:
--
-- 1) BULTOS: un producto se puede comprar y vender por bulto (una caja
--    con varias unidades). "unidades_por_bulto" dice cuántas unidades
--    trae cada bulto. Si el producto se vende suelto, vale 1.
--
-- 2) DESCUENTOS "al tanto" y "al mayor": el negocio puede vender con
--    dos precios. "al tanto" es el precio de siempre (por unidad); "al
--    mayor" es un precio más bajo que se aplica cuando el cliente se
--    lleva una cantidad mínima ("cantidad_mayor"). Un precio al mayor
--    en cero significa que ese producto no se vende al mayor.
--
-- Todo es aditivo y con valores por defecto, así que la base sigue
-- funcionando igual para los datos que ya existían.
-- ============================================================

-- ------------------------------------------------------------
-- productos: se agregan las columnas nuevas
-- ------------------------------------------------------------
alter table public.productos
    add column if not exists unidades_por_bulto integer       not null default 1,
    add column if not exists precio_mayor_ves   numeric(14,2) not null default 0,
    add column if not exists precio_mayor_usd   numeric(14,2) not null default 0,
    add column if not exists cantidad_mayor     integer       not null default 1;

-- Reglas de integridad (se agregan solo si no existían)
do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'productos_unidades_por_bulto_positivo') then
        alter table public.productos
            add constraint productos_unidades_por_bulto_positivo check (unidades_por_bulto >= 1);
    end if;

    if not exists (select 1 from pg_constraint where conname = 'productos_cantidad_mayor_positiva') then
        alter table public.productos
            add constraint productos_cantidad_mayor_positiva check (cantidad_mayor >= 1);
    end if;

    if not exists (select 1 from pg_constraint where conname = 'productos_precios_mayor_no_negativos') then
        alter table public.productos
            add constraint productos_precios_mayor_no_negativos
            check (precio_mayor_ves >= 0 and precio_mayor_usd >= 0);
    end if;
end $$;

comment on column public.productos.unidades_por_bulto is 'Cantidad de unidades que trae un bulto de este producto. 1 = se vende suelto.';
comment on column public.productos.precio_mayor_ves is 'Precio al mayor en VES por unidad. 0 = no se vende al mayor.';
comment on column public.productos.precio_mayor_usd is 'Precio al mayor en USD por unidad. 0 = no se vende al mayor.';
comment on column public.productos.cantidad_mayor is 'Cantidad mínima de unidades para que aplique el precio al mayor.';

-- ------------------------------------------------------------
-- productos_vendidos: se deja constancia del tipo de precio usado
-- ------------------------------------------------------------
alter table public.productos_vendidos
    add column if not exists es_mayor          boolean not null default false,
    add column if not exists unidades_por_bulto integer not null default 1;

comment on column public.productos_vendidos.es_mayor is 'true si la línea se cobró con el precio al mayor.';
comment on column public.productos_vendidos.unidades_por_bulto is 'Cuántas unidades traía el bulto al momento de la venta (respaldo histórico).';
