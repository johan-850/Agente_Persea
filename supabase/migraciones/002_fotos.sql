-- 002 · Las fotos que acompañan los reportes.
--
-- Las monitoras casi siempre las mandan en mensajes aparte del texto, asi que
-- monitoreo_id puede quedar en null: la foto se guarda igual antes que perder
-- la evidencia. La asociacion es una heuristica (ultimo reporte de esa persona
-- en las dos horas previas) y por eso la FK borra con set null, no en cascada.
--
-- Depende de 001: referencia monitoreos.

create table if not exists fotos (
    id bigint generated always as identity primary key,
    fecha_hora timestamptz not null default now(),
    remitente text not null,
    -- El id que da Meta. La imagen se descarga en dos pasos y caduca en ~30
    -- dias, asi que lo que vale a largo plazo es storage_path.
    media_id text not null,
    caption text,
    monitoreo_id bigint references monitoreos (id) on delete set null,
    -- Ruta dentro del bucket privado. Null si la subida fallo: la foto queda
    -- descrita aunque no se haya podido archivar.
    storage_path text,
    -- Lo que el modelo dice que SE VE, sin nombrar especies.
    descripcion text,
    -- Hipotesis del modelo sobre que plaga podria ser. Va en campo aparte de
    -- plagas_observadas (tabla monitoreos) para que nunca se confunda una
    -- conjetura sobre una imagen con lo que la monitora reporto haber visto.
    plagas_sugeridas jsonb not null default '[]',
    es_alerta boolean not null default false,
    motivo_alerta text
);

create index if not exists idx_fotos_fecha on fotos (fecha_hora);
create index if not exists idx_fotos_monitoreo on fotos (monitoreo_id);
create index if not exists idx_fotos_remitente on fotos (remitente);
