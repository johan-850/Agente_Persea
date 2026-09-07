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
    drive_file_id text,
    drive_url text,
    descripcion text
);

create index if not exists idx_fotos_fecha on fotos (fecha_hora);
create index if not exists idx_fotos_monitoreo on fotos (monitoreo_id);
create index if not exists idx_fotos_remitente on fotos (remitente);
