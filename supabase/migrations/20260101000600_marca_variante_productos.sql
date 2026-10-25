-- ============================================================
-- ContaVen - Migración 006: Marca y variante del producto
-- ============================================================
-- Se agregan dos columnas opcionales al inventario para poder armar
-- el SKU automático con el nombre, la marca y la variante.
--
-- Son opcionales: los productos que ya existen se quedan con NULL y
-- la app sigue funcionando igual.
-- ============================================================

alter table public.productos
    add column if not exists marca    text,
    add column if not exists variante text;

comment on column public.productos.marca is 'Marca del producto (ej. Polar, Mary).';
comment on column public.productos.variante is 'Variante o presentación (ej. 1kg, grano largo, rojo).';
