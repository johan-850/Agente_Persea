create table if not exists reportes (
    id bigint generated always as identity primary key,
    fecha_hora timestamptz not null default now(),
    remitente text not null,
    texto_original text not null,
    lote text,
    tipo_labor text,
    supervisor text,
    personas jsonb not null default '[]',
    cantidad_personas integer,
    insumos jsonb not null default '[]',
    canecas numeric,
    litros_totales numeric,
    lanzas integer,
    hora_inicio text,
    hora_fin text,
    nota text,
    es_alerta boolean not null default false,
    tipo_alerta text,
    prioridad text
);

create index if not exists idx_reportes_fecha on reportes (fecha_hora);
create index if not exists idx_reportes_alerta on reportes (es_alerta);
create index if not exists idx_reportes_lote on reportes (lote);

create table if not exists administradores (
    id bigint generated always as identity primary key,
    nombre text not null,
    numero text not null unique,
    activo boolean not null default true
);

create table if not exists monitoreos (
    id bigint generated always as identity primary key,
    fecha_hora timestamptz not null default now(),
    remitente text not null,
    texto_original text not null,
    finca text,
    lote text,
    tipo_labor text,
    monitoras integer,
    lote_finalizado boolean,
    plagas_observadas jsonb not null default '[]',
    nota text,
    es_alerta boolean not null default false,
    tipo_alerta text,
    prioridad text
);

create index if not exists idx_monitoreos_fecha on monitoreos (fecha_hora);
create index if not exists idx_monitoreos_alerta on monitoreos (es_alerta);
create index if not exists idx_monitoreos_lote on monitoreos (lote);
create index if not exists idx_monitoreos_finca on monitoreos (finca);

-- Fotos que acompanan los reportes. Las monitoras suelen mandarlas en un
-- mensaje aparte del texto, por eso monitoreo_id puede quedar en null: se
-- guarda igual para no perder la evidencia.
create table if not exists fotos (
    id bigint generated always as identity primary key,
    fecha_hora timestamptz not null default now(),
    remitente text not null,
    media_id text not null,
    caption text,
    monitoreo_id bigint references monitoreos (id) on delete set null,
    storage_path text,
    descripcion text,
    -- Hipotesis del modelo sobre la foto. Aparte de plagas_observadas de la
    -- tabla monitoreos, que es lo que reporto la monitora.
    plagas_sugeridas jsonb not null default '[]',
    es_alerta boolean not null default false,
    motivo_alerta text
);

create index if not exists idx_fotos_fecha on fotos (fecha_hora);
create index if not exists idx_fotos_monitoreo on fotos (monitoreo_id);
create index if not exists idx_fotos_remitente on fotos (remitente);

-- Meta entrega cada evento "al menos una vez": reenvia lo que tarde en
-- confirmarse y lo que quedara pendiente durante un corte. Sin esta tabla un
-- mismo reporte se guarda varias veces, cada copia dispara su propia alerta y
-- cada foto se vuelve a pasar por el modelo de vision.
create table if not exists mensajes_procesados (
    wamid text primary key,
    recibido_en timestamptz not null default now()
);

create index if not exists idx_mensajes_procesados_fecha on mensajes_procesados (recibido_en);

-- La cola de procesamiento vivia solo en memoria: un reinicio con mensajes
-- encolados los perdia del todo, y encima con su wamid ya reclamado, asi que
-- ni un reenvio de Meta los habria recuperado. Con despliegue continuo un
-- reinicio es cada actualizacion.
--
-- payload guarda el mensaje crudo; procesado_en queda en null hasta que se
-- termina, asi al arrancar se sabe que quedo a medias. intentos evita que un
-- mensaje que tumba el proceso lo deje en un bucle de arranques.
alter table mensajes_procesados
    add column if not exists payload jsonb,
    add column if not exists procesado_en timestamptz,
    add column if not exists intentos integer not null default 0;

create index if not exists idx_mensajes_pendientes
    on mensajes_procesados (recibido_en)
    where procesado_en is null;
