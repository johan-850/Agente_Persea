# Base de datos

Todo lo que hace falta para dejar una instalación nueva lista, y para poner al
día una que venga de antes.

## Cómo aplicarlas

En el **SQL Editor** de Supabase, en orden. Se pegan y se ejecutan una por una.

```
migraciones/
  001_monitoreos.sql          administradores + monitoreos
  002_fotos.sql               fotos            (depende de 001)
  003_mensajes_procesados.sql descarte de reenvíos + cola persistente
  004_envios.sql              auditoría de lo que se le manda a los admins
  005_bucket_fotos.sql        el bucket privado donde se archivan las fotos
```

**Son idempotentes**: todo va con `if not exists`. Correrlas sobre una base que
ya las tiene no cambia nada ni borra datos, así que ante la duda se pueden
volver a pasar. El orden importa solo por una dependencia: `fotos` referencia
`monitoreos`.

Hay una más, aparte y fuera del orden:

```
  opcional_retirar_labores.sql   ⚠️ borra la tabla 'reportes'
```

No se corre en una instalación nueva —ninguna migración crea esa tabla— y
borra datos sin vuelta atrás. Es solo para bases que vienen de cuando el
proyecto abarcaba los reportes de labores.

## Después de las migraciones

### 1. Registrar al menos un administrador

Sin esto el agente procesa todo y no avisa a nadie. Desde la versión actual
eso queda registrado como un envío fallido, pero la alerta se pierde igual.

```sql
insert into administradores (nombre, numero, activo)
values ('Nombre Apellido', '+573001234567', true);
```

Los administradores son también los únicos que pueden consultarle datos al bot
por WhatsApp. El código compara solo los dígitos, así que da igual cómo se
escriba el número.

### 2. Comprobar que quedó todo

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
order by table_name;
```

Deben aparecer: `administradores`, `envios`, `fotos`, `mensajes_procesados`,
`monitoreos`.

```sql
select id, public from storage.buckets where id = 'fotos-monitoreo';
```

Tiene que existir y salir `public = false`. Si sale `true`, las fotos serían
accesibles con solo la URL.

## Variables de entorno relacionadas

| Variable | Para qué |
|---|---|
| `SUPABASE_URL` | La del proyecto |
| `SUPABASE_KEY` | La `service_role`, no la `anon`: la anon la bloquea RLS |
| `SUPABASE_BUCKET_FOTOS` | Tiene que coincidir con el bucket de `005` (`fotos-monitoreo`) |

## Cosas que conviene saber

**El plan gratuito se pausa** tras una semana sin actividad. El agente falla
con error de DNS hasta que se reactiva desde el panel.

**Storage se llena.** A unos 258 KB por foto y ~100 fotos al día, el giga del
plan gratuito alcanza para unos 40 días. No hay política de retención todavía.

**`mensajes_procesados` crece sin límite.** Una fila por mensaje recibido.
Hoy son cientos y no molesta, pero nada la limpia.

**Las fechas se guardan en UTC.** El día de la finca se calcula en
`app/horario.py`: Colombia es UTC-5, y comparar contra medianoche UTC corre el
día cinco horas. Cualquier consulta por fecha que se escriba a mano tiene que
tener eso en cuenta.
