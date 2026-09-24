-- 003 · Que mensajes ya se procesaron, y cuales quedaron a medias.
--
-- Dos problemas distintos, la misma tabla.
--
-- 1. Meta entrega cada evento "al menos una vez": reenvia lo que tarde en
--    confirmarse. Un dia eso guardo el mismo reporte seis veces, convirtio 26
--    fotos en 66 filas y disparo 31 alertas. El wamid es igual en todos los
--    reenvios, asi que sirve de llave para descartarlos.
--
-- 2. La cola de procesamiento vivia solo en memoria. Un reinicio con mensajes
--    encolados los perdia, y encima con su wamid ya reclamado: ni un reenvio
--    los habria recuperado. Guardando el mensaje crudo se reencolan al
--    arrancar.
--
-- El wamid se reclama ANTES de procesar, no despues: si no, los reenvios que
-- llegan mientras el mensaje aun se procesa lo duplican igual.

create table if not exists mensajes_procesados (
    wamid text primary key,
    recibido_en timestamptz not null default now(),
    -- El mensaje tal como llego, para reencolarlo si el proceso murio.
    payload jsonb,
    -- Null mientras esta pendiente. Al arrancar, lo que siga en null es lo que
    -- quedo a medias.
    procesado_en timestamptz,
    -- Tope de reintentos: un mensaje que tumbe el proceso no puede dejarlo en
    -- un bucle de arranques sin llegar a procesar nada mas.
    intentos integer not null default 0
);

-- Para bases creadas antes de que existiera la cola persistente, donde la
-- tabla ya existe con solo wamid y recibido_en.
alter table mensajes_procesados
    add column if not exists payload jsonb,
    add column if not exists procesado_en timestamptz,
    add column if not exists intentos integer not null default 0;

create index if not exists idx_mensajes_procesados_fecha
    on mensajes_procesados (recibido_en);

-- Parcial: lo unico que se consulta al arrancar son los pendientes, que son
-- muy pocos frente al total.
create index if not exists idx_mensajes_pendientes
    on mensajes_procesados (recibido_en)
    where procesado_en is null;
