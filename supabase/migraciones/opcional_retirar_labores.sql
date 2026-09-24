-- OPCIONAL · Retira la tabla del flujo de reportes de labores.
--
-- NO se corre en una instalacion nueva: esa tabla ya no la crea ninguna
-- migracion. Esto es solo para bases que vienen de antes.
--
-- El proyecto empezo con los reportes de labores (fertilizacion, aplicaciones,
-- drench) y giro hacia el monitoreo de plagas, que es donde estaba el valor de
-- alertar. El codigo de labores se retiro del repo; la tabla quedo con los
-- datos de aquellas pruebas.
--
-- ⚠️ ESTO BORRA DATOS Y NO SE PUEDE DESHACER. Antes de correrlo, exporta lo
-- que haya si te sirve de algo:
--
--     select * from reportes order by fecha_hora;
--
-- Si no estas seguro, no lo corras: la tabla no molesta a nadie y no ocupa
-- espacio apreciable.

drop table if exists reportes;
