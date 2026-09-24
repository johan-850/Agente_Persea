-- 004 · Que se le mando a los administradores, y si les llego.
--
-- El sistema existe para avisar, y no habia forma de saber si el aviso
-- llegaba: cuando fallaban la plantilla y el texto libre quedaba una linea de
-- log, y nadie revisa los logs de un servidor para enterarse de que no le
-- avisaron de un foco de Heilipus. Peor: con la tabla de administradores
-- vacia, el envio no hacia nada y la alerta no existia para nadie.
--
-- Meta devuelve un identificador al aceptar el mensaje y despues manda por el
-- webhook como le fue. Cruzando las dos cosas, el estado dice si el
-- administrador lo recibio de verdad, no solo si nosotros lo pusimos en la
-- cola de Meta.

create table if not exists envios (
    id bigint generated always as identity primary key,
    fecha_hora timestamptz not null default now(),
    -- alerta_reporte, alerta_foto, complemento_lote, resumen_diario,
    -- resumen_semanal
    tipo text not null,
    -- A que monitoreo o foto corresponde ("monitoreo:45"), para poder auditar
    -- un lote de punta a punta.
    referencia text,
    destinatario text not null,
    -- Null cuando salio como texto libre porque la plantilla fallo.
    plantilla text,
    -- El identificador de Meta. Es la llave contra la que se cruzan los acuses.
    wamid text,
    -- aceptado -> enviado -> entregado -> leido, o fallido.
    -- "aceptado" solo dice que Meta lo recibio; los demas los trae el webhook.
    estado text not null,
    detalle text
);

create index if not exists idx_envios_wamid on envios (wamid);
create index if not exists idx_envios_fecha on envios (fecha_hora);
create index if not exists idx_envios_estado on envios (estado);
