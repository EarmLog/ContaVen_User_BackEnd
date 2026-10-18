-- ============================================================
-- ContaVen - Migración 007: Descuentos por cantidad y método BIOPAGO
-- ============================================================
-- Se agregan tres funciones nuevas:
--
-- 1) DESCUENTO POR UNIDAD: un producto puede ofrecer un % de rebaja
--    cuando el cliente se lleva una cantidad mínima de unidades.
--    "descuento_unidad_porcentaje" es el % (0 = sin descuento) y
--    "descuento_unidad_desde" es la cantidad mínima para que aplique.
--
-- 2) DESCUENTO POR BULTO: un producto vendido por bulto puede ofrecer
--    un % de rebaja cuando el cliente compra el bulto completo (es
--    decir, al menos "unidades_por_bulto" unidades).
--    "descuento_bulto_porcentaje" es el % (0 = sin descuento).
--
--    Si un producto tiene los dos descuentos y los dos aplican, en el
--    POS se usa el MAYOR de los dos (no se suman).
--
-- 3) MÉTODO DE PAGO: se cambia el método "app" por "biopago", que es
--    el nombre real que usa el negocio. Los registros viejos con "app"
--    se migran a "biopago" para no romper el historial.
--
-- Todo es aditivo y con valores por defecto, así que la base sigue
-- funcionando igual para los datos que ya existían.
-- ============================================================

-- ------------------------------------------------------------
-- productos: se agregan las columnas de descuento
-- ------------------------------------------------------------
alter table public.productos
    add column if not exists descuento_unidad_porcentaje numeric(5,2) not null default 0,
    add column if not exists descuento_unidad_desde      integer      not null default 1,
    add column if not exists descuento_bulto_porcentaje  numeric(5,2) not null default 0;

-- Reglas de integridad (se agregan solo si no existían)
do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'productos_descuento_unidad_rango') then
        alter table public.productos
            add constraint productos_descuento_unidad_rango
            check (descuento_unidad_porcentaje >= 0 and descuento_unidad_porcentaje <= 100);
    end if;

    if not exists (select 1 from pg_constraint where conname = 'productos_descuento_bulto_rango') then
        alter table public.productos
            add constraint productos_descuento_bulto_rango
            check (descuento_bulto_porcentaje >= 0 and descuento_bulto_porcentaje <= 100);
    end if;

    if not exists (select 1 from pg_constraint where conname = 'productos_descuento_unidad_desde_positivo') then
        alter table public.productos
            add constraint productos_descuento_unidad_desde_positivo
            check (descuento_unidad_desde >= 1);
    end if;
end $$;

comment on column public.productos.descuento_unidad_porcentaje is 'Porcentaje de descuento por unidad cuando se lleva la cantidad mínima. 0 = sin descuento.';
comment on column public.productos.descuento_unidad_desde is 'Cantidad mínima de unidades para que aplique el descuento por unidad.';
comment on column public.productos.descuento_bulto_porcentaje is 'Porcentaje de descuento al comprar el bulto completo. 0 = sin descuento.';

-- ------------------------------------------------------------
-- productos_vendidos: se deja constancia del descuento aplicado
-- ------------------------------------------------------------
alter table public.productos_vendidos
    add column if not exists descuento_porcentaje numeric(5,2) not null default 0;

comment on column public.productos_vendidos.descuento_porcentaje is 'Porcentaje de descuento que se aplicó a la línea (0 = sin descuento).';

-- ------------------------------------------------------------
-- ventas: el método "app" pasa a llamarse "biopago"
-- ------------------------------------------------------------

-- Primero se convierten los registros viejos, para que el nuevo check
-- no rechace filas que ya existían.
update public.ventas
set metodo_pago = 'biopago'
where metodo_pago = 'app';

-- Se reemplaza el check por la lista nueva de métodos permitidos
do $$
begin
    if exists (select 1 from pg_constraint where conname = 'ventas_metodo_pago') then
        alter table public.ventas drop constraint ventas_metodo_pago;
    end if;

    alter table public.ventas
        add constraint ventas_metodo_pago
        check (metodo_pago in ('efectivo', 'punto', 'pagomovil', 'biopago'));
end $$;
