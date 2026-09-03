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
