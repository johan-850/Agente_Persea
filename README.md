# Agente de Monitoreo

Agente de WhatsApp que convierte los reportes de campo de las monitoras en datos estructurados, y avisa a los administradores cuando aparece algo crítico.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-Haiku%204.5-D97757?logo=anthropic&logoColor=white)
![WhatsApp](https://img.shields.io/badge/WhatsApp-Cloud%20API-25D366?logo=whatsapp&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-Postgres-3FCF8E?logo=supabase&logoColor=white)

---

## El problema

Las monitoras de campo reportan por WhatsApp en texto libre, cada una con su propio formato: emojis, viñetas improvisadas, abreviaturas, faltas de ortografía y hasta dos lotes distintos en un mismo mensaje.

```
Buenas tardes
Finca rivera
Se inicia jornada continuando con monitoreo específico en lote #13 donde se
evidencia poca población de ácaro, bruggmaniella, focos de pseudocercosphora.
Se finaliza lote
Se pasa a realizar esta misma labor al lote #14 donde se evidencia.
· Un foco de escamas ACTIVO
· Focos de Mosca blanca ACTIVO
No sé finaliza lote
Hasta finalizar jornada se contó con una monitora.
```

Ese volumen de mensajes no se lee ni se consolida a mano, y los hallazgos urgentes —un foco de plaga cuarentenaria activo— quedan enterrados entre reportes rutinarios.

## Qué hace

- **Extrae** finca, lote, tipo de labor, número de monitoras, estado del lote y plagas observadas, aunque el mensaje venga desordenado.
- **Separa por lote**: un mensaje que reporta dos lotes genera dos registros independientes.
- **Alerta en el momento** cuando detecta una plaga cuarentenaria, un foco marcado como `ACTIVO` o un accidente.
- **Archiva las fotos** de los daños, descritas y ligadas al reporte al que pertenecen.
- **Consolida el día** en un resumen que sale de lunes a sábado a las 18:00, al cierre de la jornada. Los viernes, media hora después, va además el resumen de la semana: la dispersión de cada cuarentenaria por lote y qué lotes vienen alertando varios días.
- **Guarda el histórico** en Postgres, consultable para reportes posteriores.

Del mensaje de arriba, el agente produce dos registros:

| finca | lote | labor | monitoras | finalizado | plagas | alerta |
|---|---|---|---|---|---|---|
| rivera | 13 | monitoreo específico | 1 | ✅ | ácaro (poca población), bruggmaniella, pseudocercosphora | 🚨 |
| rivera | 14 | monitoreo específico | 1 | ❌ | escamas (foco ACTIVO), mosca blanca (focos ACTIVO) | 🚨 |

## Arquitectura

```
Monitora (WhatsApp)
   texto + fotos
      │
      ▼
Meta WhatsApp Cloud API
      │  POST /meta/webhook
      ▼
   FastAPI ──────► Claude Haiku 4.5   texto → extracción estructurada
      │                               foto  → descripción de apoyo
      │
      ├──────────► Supabase   Postgres → histórico
      │                       Storage  → fotos (bucket privado)
      │
      └──────────► Plantillas WhatsApp ──► Administradores
                                            · alerta inmediata
                                            · resumen diario (lun-sab 18:00)
                                            · resumen semanal (vie 18:30)
```

La detección de alertas es **doble**: la IA clasifica, y además se aplican reglas deterministas sobre el texto crudo. Un falso negativo en una plaga cuarentenaria cuesta mucho más que un falso positivo, así que basta con que una de las dos capas dispare.

## Stack

| Componente | Tecnología |
|---|---|
| Backend | FastAPI + Uvicorn |
| IA | Claude Haiku 4.5 (Anthropic API) |
| Mensajería | Meta WhatsApp Cloud API |
| Base de datos y archivos | Supabase (PostgreSQL + Storage) |
| Scheduler | APScheduler |

## Estructura

```
app/
├── config.py                     # TODA la configuración: qué existe, defectos, revisión al arrancar
├── horario.py                    # el día de la finca (zona de Colombia, jornada)
├── api/
│   ├── routes_meta_whatsapp.py   # webhook de Meta (verificación + recepción)
│   ├── routes_monitoreo.py       # API REST de consulta
│   └── seguridad.py              # firma de Meta y clave de la API
├── services/
│   ├── modelo_ia.py                  # la ÚNICA puerta al modelo de lenguaje
│   ├── monitoreo_ia_service.py       # extracción de reportes (multi-lote)
│   ├── vision_service.py             # descripción de fotos
│   ├── consultas_service.py          # preguntas de los administradores
│   ├── monitoreo_service.py          # orquestación: extraer → guardar → alertar
│   ├── alertas_monitoreo_service.py  # reglas deterministas de alerta
│   ├── plan_mipe.py                  # catálogo del plan: cuarentenarias y grupos
│   ├── fotos_service.py              # foto → descripción → archivo → reporte
│   ├── storage_service.py            # bucket privado de Supabase Storage
│   ├── resumen_service.py            # resumen diario
│   ├── resumen_semanal_service.py    # resumen de la semana
│   ├── meta_whatsapp_service.py      # Cloud API: envío y descarga de media
│   ├── envios_service.py             # si cada aviso llegó o no
│   ├── cola_mensajes.py              # cola en segundo plano del webhook
│   ├── idempotencia_service.py       # descarta los reenvíos de Meta
│   └── admin_service.py              # destinatarios de las alertas
├── db/supabase_client.py
├── models/reporte.py
└── main.py
supabase/migraciones/               # SQL para dejar la base lista
scripts/levantar.ps1                # arranca servidor y túnel
scripts/crear_plantillas.py         # crea y revisa las plantillas en Meta
tests/
```

**Dos reglas que las pruebas vigilan** (`tests/test_configuracion.py`): solo `config.py` lee variables de entorno, y solo `modelo_ia.py` habla con el proveedor del modelo. Así, desplegar es llenar el `.env`, y cambiar de modelo es tocar un archivo.

## Puesta en marcha

### 1. Dependencias

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Base de datos

Ejecutar en orden las migraciones de [`supabase/migraciones/`](supabase/migraciones) en el SQL editor de Supabase. Son idempotentes: correrlas sobre una base que ya las tiene no cambia nada. Crean las cinco tablas y el bucket privado de fotos.

Después, cargar al menos un administrador. Sin esto el agente procesa todo y no avisa a nadie:

```sql
insert into administradores (nombre, numero, activo)
values ('Nombre Apellido', '+573001112233', true);
```

Los administradores son además los únicos que pueden consultarle datos al bot por WhatsApp.

El detalle de cada migración y lo que conviene saber de la base está en [`supabase/README.md`](supabase/README.md).

### 3. Variables de entorno

```bash
copy .env.example .env
```

| Variable | Notas |
|---|---|
| `SUPABASE_URL` | URL del proyecto. |
| `SUPABASE_KEY` | Usar la **`service_role`** key. Con la `anon`, RLS bloquea los inserts. |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `MODELO_IA` | Opcional. Default `claude-haiku-4-5-20251001`. Cambia el modelo de las tres tareas a la vez; antes, correr `tests/` contra el nuevo, sobre todo las de fotos. |
| `META_ACCESS_TOKEN` | Token de un **system user** sin expiración. Los del quickstart caducan en horas. |
| `META_PHONE_NUMBER_ID` | Meta → app → WhatsApp → configuración. |
| `META_VERIFY_TOKEN` | Cadena arbitraria; debe coincidir con la registrada en el webhook. |
| `META_APP_SECRET` | Meta → app → Configuración → Básica. Sin esto el webhook acepta eventos sin verificar que vengan de Meta. |
| `META_WABA_ID` | La cuenta de WhatsApp Business que contiene el número. Aparece en el log al llegar el primer mensaje. |
| `API_TOKEN` | Clave para la API REST. Sin ella, la API queda cerrada. |
| `SUPABASE_BUCKET_FOTOS` | Opcional. Bucket donde se archivan las fotos. Default `fotos-monitoreo`. |
| `HORA_RESUMEN_DIARIO` | Hora (0-23) del resumen, en hora de Colombia. Default `18`. El diario sale a esa hora de lunes a sábado; el semanal, los viernes media hora después. |

**Si falta algo obligatorio, el servidor no arranca** y dice en el log todo lo que falta de una vez. Arrancar a medias es peor: sin la base, los reportes se confirman a Meta y se pierden; sin el token de WhatsApp, las alertas se evalúan y no le llegan a nadie, y en los dos casos el servidor responde "ok". Lo recomendable (`META_APP_SECRET`, `API_TOKEN`, `META_WABA_ID`) no frena el arranque pero queda avisado.

El bucket de fotos lo crea la migración `005`, privado. Las fotos muestran trabajadores y detalles de las fincas, así que no quedan detrás de una URL pública: el enlace se firma en el momento y vence.

### 4. Ejecutar

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En desarrollo, exponer el puerto (`ngrok http 8000`) y registrar `https://<dominio>/meta/webhook` como callback en Meta → Webhooks → WhatsApp Business Account, **suscribiendo el campo `messages`**.

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` `POST` | `/meta/webhook` | Webhook de Meta: verificación y recepción de mensajes. |
| `POST` | `/monitoreos` | Procesa un reporte sin pasar por WhatsApp. Útil para pruebas. |
| `GET` | `/monitoreos?fecha=YYYY-MM-DD` | Monitoreos de un día. |
| `GET` | `/alertas-monitoreo` | Monitoreos marcados como alerta. |
| `GET` | `/fotos?monitoreo_id=&fecha=` | Fotos, filtrables por reporte o día. |
| `GET` | `/fotos/{id}/enlace` | Enlace firmado y temporal para ver la foto. |
| `GET` | `/envios` | Qué se le mandó a los administradores y si llegó. |
| `GET` | `/envios/sin-entregar` | Avisos aceptados por Meta que nunca confirmaron entrega. |
| `POST` | `/tareas/resumen-diario` | Dispara el resumen del día manualmente. |
| `POST` | `/tareas/resumen-semanal` | Dispara el resumen de la semana manualmente. |
| `GET` | `/` | Health check. |

Todo menos `/meta/webhook` y `/` va detrás de la cabecera `X-API-Key`. El webhook no puede llevarla —lo llama Meta, no nosotros— y se protege con la firma del evento.

```bash
curl -X POST http://127.0.0.1:8000/monitoreos \
  -H "Content-Type: application/json" \
  -d '{"texto":"Finca la linda, lote #5, mosca blanca y foco de acaro ACTIVO. Se finaliza lote. 1 monitora","remitente":"+573001112233"}'
```

## Fotos

Los reportes casi siempre traen fotos de daños, larvas u hojas afectadas. El agente las descarga de WhatsApp, las describe, las archiva en Drive y las liga al reporte correspondiente.

**Asociación con el reporte.** Las monitoras mandan la foto en un mensaje *aparte* del texto, así que no viene identificada. Se resuelve así:

1. Si la foto trae *caption*, el caption se procesa primero como reporte, y la foto se cuelga de él.
2. Si llega suelta, se asocia al **último reporte de esa misma monitora en las 2 horas previas**.
3. Si no hay ninguno, se guarda igual con `monitoreo_id` en null — mejor huérfana que colgada del lote equivocado.

Se guardan en `2026/09/2026-09-03_la-linda_lote-5_a1b2c3d4.jpg`: agrupadas por mes y con finca y lote en el nombre, para poder ubicar una foto sin consultar la base de datos.

**Observación e hipótesis van en campos separados.** El modelo devuelve dos cosas:

| Campo | Qué es |
|---|---|
| `descripcion` | Lo observable: parte de la planta, tipo de daño, extensión. Es lo único que se afirma. |
| `plagas_sugeridas` | Candidatas del catálogo del plan compatibles con ese daño. Son **hipótesis a confirmar**, y viven aparte de `plagas_observadas` (lo que reportó la monitora) para que nunca se mezclen al sacar estadísticas. |

La separación no es formalismo. El propio plan distingue *Pseudococcus jackbeardsleyi* de *P. longispinus* contando pares de filamentos de cera — una es cuarentenaria y la otra no, y esa diferencia no sale de una foto de WhatsApp comprimida. La monitora, en cambio, está ahí: puede voltear el fruto, abrirlo y usar la lupa de 20x que el plan menciona. Por eso el modelo propone y el agrónomo confirma.

**La foto puede levantar la mano**, con alerta de **prioridad media**. El orden de decisión es:

1. **Alguna candidata es cuarentenaria** → alerta.
2. **Hay candidatas y ninguna es cuarentenaria** → no alerta. El modelo miró la imagen completa y concluyó otra cosa; los patrones solo leen su prosa, así que su conclusión pesa más. El descarte queda en el log para poder auditarlo.
3. **No hay candidatas** → deciden los patrones de daño. Son la red de seguridad cuando el modelo no se pronuncia.

Perforaciones, galerías y larvas solo cuentan sobre **fruto, rama, tallo, corteza o semilla** — donde atacan los barrenadores del plan (*H. lauri* el fruto, *S. catenifer* fruto y ramas, *H. elegans* tallo y ramas). En hoja son comedores de follaje o minadores, hallazgos rutinarios.

Ambas reglas salieron de falsos positivos reales. Importan porque la fatiga de alertas es el modo en que fallan estos sistemas: si los avisos suelen ser ruido, dejan de leerse y también se pierde el verdadero. Bajar los falsos positivos protege las alertas que sí importan.

Esto cubre un hueco real: si la monitora fotografía un fruto perforado pero solo escribe *"mosca blanca"*, el reporte no dispara alerta y el hallazgo se pierde. Con esta regla, la foto avisa igual. Para no duplicar avisos, si el reporte escrito **ya** generó alerta en ese lote, la foto no vuelve a notificar.

**El bucket es privado.** Las fotos pueden mostrar trabajadores y detalles de las fincas, así que no quedan tras una URL pública: la base guarda solo la ruta y el enlace se firma en el momento (`GET /fotos/{id}/enlace`), con vencimiento.

**Capacidad.** Storage es una cuota aparte de la base de datos (1 GB vs 500 MB en el plan gratuito), así que las fotos no consumen espacio de las tablas. A ~200 KB por foto comprimida por WhatsApp, 1 GB alcanza para unas 5.000 fotos.

Cada paso está aislado: si el archivo falla no se pierde la descripción, y si la descripción falla la foto igual queda archivada.

## Reglas de alerta

Definidas en `app/services/alertas_monitoreo_service.py` y evaluadas sobre el texto original.

**Disparan alerta:**

| Señal | Prioridad | Origen |
|---|---|---|
| Plaga cuarentenaria del PLAN MIPE | alta | Umbral de daño **0%**: cualquier presencia obliga a actuar, se describa como se describa. |
| Accidente (`accidente`, `herido`, `lesión`…) | alta | — |
| La palabra **`activo`** | alta | Es el marcador que el propio equipo usa para señalar un foco urgente (*"Un foco de escamas ACTIVO"*). |
| Término de grupo sin especie (`escama`, `cochinilla`, `piojo harinoso`) | alta | **5 de las 8** cuarentenarias del plan son cochinillas o escamas, y el catálogo no tiene ninguna que *no* sea cuarentenaria en Hass. Lo que falta por confirmar es cuál de las cinco, no si lo es. |
| Daño visible en una foto, o candidata cuarentenaria sugerida por la imagen | media | Se evalúa sobre lo que devuelve el análisis de la foto, no sobre el reporte escrito. Ver [Fotos](#fotos). |

Las 8 plagas cuarentenarias del cultivo (aguacate Hass) son *Heilipus lauri*, *Heilipus elegans*, *Stenoma catenifer*, *Maconellicoccus hirsutus*, *Pseudococcus jackbeardsleyi*, *Pseudococcus landoi*, *Ceroplastes rubens* y *Saissetia batesi*. La comparación ignora mayúsculas y tildes, porque en campo se escribe indistintamente *ácaro*/*acaro* o *pseudocercóspora*/*pseudocercosphora*.

**No disparan:** `daño` / `daños`. En monitoreo de plagas es vocabulario rutinario (*"daño por comedores de follaje"*) y marcaría casi todos los reportes, volviendo la alerta inútil.

En mensajes multi-lote la regla se evalúa **por lote**, sobre el fragmento que habla de ese lote. Antes se evaluaba el mensaje completo y un `ACTIVO` del lote B marcaba también al lote A: el administrador recibía cinco lotes en alerta cuando el foco estaba en uno, y sin forma de saber en cuál. Queda una red de seguridad sobre el mensaje entero para lo que no se pudo repartir por lote, pero ya no contagia la prioridad.

## Restricciones de WhatsApp que condicionan el diseño

Estas no son decisiones del proyecto, son límites de la plataforma:

| Restricción | Consecuencia en el diseño |
|---|---|
| **Ventana de 24 h**: fuera de ella no se admiten mensajes libres | Alertas y resúmenes se envían con **plantillas aprobadas**, con respaldo a texto libre si la plantilla falla. |
| **Categoría de plantilla** | Deben quedar como `UTILITY`, no `MARKETING`: son más baratas, gratis dentro de la ventana y no dependen del opt-in de marketing. El texto debe leerse como seguimiento de una solicitud del usuario. |
| **Formato de plantilla** | Una variable no puede ir al inicio ni al final del cuerpo, ni contener saltos de línea (`limpiar_parametro()` lo resuelve). |
| **No hay acceso a grupos** | La API oficial solo permite conversaciones 1:1. Las monitoras escriben al bot, no al grupo. |

## Pruebas

Las reglas de alerta son la red de seguridad del sistema, así que tienen pruebas con casos tomados de reportes reales:

```bash
python tests/test_alertas_monitoreo.py
```

## Roadmap

- [ ] Despliegue 24/7 — actualmente corre en local y depende de un túnel.
- [ ] Panel web para consultar histórico y estadísticas.
- [ ] Reactivar el flujo de reportes de labores (fertilización, aplicaciones, drench), hoy en el repo pero desconectado del webhook.
