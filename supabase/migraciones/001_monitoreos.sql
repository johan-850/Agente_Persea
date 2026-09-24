-- 001 · Los reportes de monitoreo y a quien se le avisa.
--
-- Es el nucleo del agente: cada mensaje que una monitora manda por WhatsApp
-- termina aqui como una fila por lote. Un mismo mensaje suele cubrir varios
-- ("termino el #10 y paso al #3"), y cada lote se guarda y se evalua por
-- separado: evaluarlos juntos contagiaba la alerta de uno a todos.

create table if not exists administradores (
    id bigint generated always as identity primary key,
    nombre text not null,
    -- Formato internacional, +57... El codigo compara solo los digitos, asi
    -- que da igual si se guarda con espacios o sin el signo.
    numero text not null unique,
    -- Se desactiva en vez de borrarse, para conservar el historial de envios.
    activo boolean not null default true
);

create table if not exists monitoreos (
    id bigint generated always as identity primary key,
    -- En UTC. El dia de la finca se calcula en app/horario.py: Colombia es
    -- UTC-5 y comparar contra medianoche UTC corre el dia cinco horas.
    fecha_hora timestamptz not null default now(),
    remitente text not null,
    -- Se conserva el mensaje tal cual llego. La extraccion puede mejorar y se
    -- puede volver a procesar; el texto original es el unico dato irrepetible.
    texto_original text not null,
    finca text,
    -- Solo el numero, sin '#'. Queda en null cuando la monitora no lo escribio;
    -- en ese caso el agente se lo pregunta.
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
