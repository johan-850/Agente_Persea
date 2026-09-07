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
- **Archiva las fotos** en Google Drive, descritas y ligadas al reporte al que pertenecen.
- **Consolida el día** en un resumen automático a la hora configurada.
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
      ├──────────► Supabase / Postgres (histórico)
      │
      ├──────────► Google Drive        (archivo de fotos)
      │
      └──────────► Plantillas WhatsApp ──► Administradores
                                            · alerta inmediata
                                            · resumen diario
```

La detección de alertas es **doble**: la IA clasifica, y además se aplican reglas deterministas sobre el texto crudo. Un falso negativo en una plaga cuarentenaria cuesta mucho más que un falso positivo, así que basta con que una de las dos capas dispare.

## Stack

| Componente | Tecnología |
|---|---|
| Backend | FastAPI + Uvicorn |
| IA | Claude Haiku 4.5 (Anthropic API) |
| Mensajería | Meta WhatsApp Cloud API |
| Base de datos | Supabase (PostgreSQL) |
| Archivo de fotos | Google Drive (OAuth de usuario) |
| Scheduler | APScheduler |

## Estructura

```
app/
├── api/
│   ├── routes_meta_whatsapp.py   # webhook de Meta (verificación + recepción)
│   ├── routes_monitoreo.py       # endpoints de monitoreo
│   ├── routes_reportes.py        # flujo de labores (pausado)
│   └── routes_whatsapp.py        # webhook de Twilio (legado)
├── services/
│   ├── monitoreo_ia_service.py       # extracción con Claude (multi-lote)
│   ├── monitoreo_service.py          # orquestación: extraer → guardar → alertar
│   ├── alertas_monitoreo_service.py  # reglas deterministas de alerta
│   ├── fotos_service.py              # foto → descripción → Drive → reporte
│   ├── vision_service.py             # descripción de imágenes
│   ├── drive_service.py              # subida a Google Drive
│   ├── resumen_service.py            # consolidado diario
│   ├── meta_whatsapp_service.py      # Cloud API: envío y descarga de media
│   └── admin_service.py              # destinatarios de las alertas
├── db/supabase_client.py
├── models/reporte.py
└── main.py
scripts/autorizar_drive.py            # OAuth de Drive, se corre una vez
supabase/schema.sql
tests/test_alertas_monitoreo.py
```

## Puesta en marcha

### 1. Dependencias

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Base de datos

Ejecutar `supabase/schema.sql` en el SQL editor de Supabase y cargar los destinatarios de las alertas:

```sql
insert into administradores (nombre, numero, activo)
values ('Nombre Apellido', '+573001112233', true);
```

### 3. Variables de entorno

```bash
copy .env.example .env
```

| Variable | Notas |
|---|---|
| `SUPABASE_URL` | URL del proyecto. |
| `SUPABASE_KEY` | Usar la **`service_role`** key. Con la `anon`, RLS bloquea los inserts. |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `META_ACCESS_TOKEN` | Token de un **system user** sin expiración. Los del quickstart caducan en horas. |
| `META_PHONE_NUMBER_ID` | Meta → app → WhatsApp → configuración. |
| `META_VERIFY_TOKEN` | Cadena arbitraria; debe coincidir con la registrada en el webhook. |
| `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` | Credencial OAuth de tipo *Aplicación de escritorio* en [console.cloud.google.com](https://console.cloud.google.com), con la Google Drive API habilitada. |
| `GOOGLE_REFRESH_TOKEN` | Lo entrega `scripts/autorizar_drive.py`. |
| `GOOGLE_DRIVE_FOLDER_ID` | Opcional. Id de la carpeta destino (aparece en la URL de Drive después de `/folders/`). |
| `HORA_RESUMEN_DIARIO` | Hora (0-23) del resumen. Default `17`. |

Para las fotos, autorizar Drive una sola vez:

```bash
python scripts/autorizar_drive.py
```

Abre el navegador, pides permiso sobre tu cuenta y el script imprime el `GOOGLE_REFRESH_TOKEN` para pegar en el `.env`. A partir de ahí el agente renueva sus credenciales solo.

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
| `POST` | `/tareas/resumen-diario` | Dispara el resumen manualmente. |
| `GET` | `/` | Health check. |

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

El archivo se nombra `2026-09-03_la-linda_lote-5_a1b2c3d4.jpg`, de modo que se ubica en Drive sin consultar la base de datos.

**La descripción es apoyo, no diagnóstico.** El prompt pide describir lo observable (parte de la planta, tipo de daño, extensión) y **prohíbe explícitamente afirmar especies**. Un modelo de propósito general no distingue de forma confiable un picudo de otro ni una escama de otra a partir de una foto, y una decisión fitosanitaria basada en eso sería un error. La identificación la hace el agrónomo.

**Autenticación con Drive.** Se usa OAuth de usuario y no una cuenta de servicio, porque las cuentas de servicio no tienen cuota propia en Drive: subir a "Mi unidad" falla, y las Unidades compartidas —que sí funcionarían— solo existen en Google Workspace. El scope es `drive.file`, que limita el acceso a los archivos que crea la propia app: el agente no puede ver el resto de tu Drive.

Cada paso está aislado: si Drive falla no se pierde la descripción, y si la descripción falla la foto igual queda archivada.

## Reglas de alerta

Definidas en `app/services/alertas_monitoreo_service.py` y evaluadas sobre el texto original.

**Disparan alerta:**

| Señal | Prioridad | Origen |
|---|---|---|
| Plaga cuarentenaria del PLAN MIPE | alta | Umbral de daño **0%**: cualquier presencia obliga a actuar, se describa como se describa. |
| Accidente (`accidente`, `herido`, `lesión`…) | alta | — |
| La palabra **`activo`** | alta | Es el marcador que el propio equipo usa para señalar un foco urgente (*"Un foco de escamas ACTIVO"*). |
| Término de grupo sin especie (`escama`, `cochinilla`) | media | Puede ser cuarentenaria o no, y del texto no hay forma de saberlo. Se avisa para verificar en campo. |

Las 8 plagas cuarentenarias del cultivo (aguacate Hass) son *Heilipus lauri*, *Heilipus elegans*, *Stenoma catenifer*, *Maconellicoccus hirsutus*, *Pseudococcus jackbeardsleyi*, *Pseudococcus landoi*, *Ceroplastes rubens* y *Saissetia batesi*. La comparación ignora mayúsculas y tildes, porque en campo se escribe indistintamente *ácaro*/*acaro* o *pseudocercóspora*/*pseudocercosphora*.

**No disparan:** `daño` / `daños`. En monitoreo de plagas es vocabulario rutinario (*"daño por comedores de follaje"*) y marcaría casi todos los reportes, volviendo la alerta inútil.

En mensajes multi-lote la regla se evalúa sobre el mensaje completo, de modo que un `ACTIVO` del lote B también marca al lote A. Es deliberado: se prefiere una alerta de más a una perdida, y el administrador recibe el contexto para distinguirlo.

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
