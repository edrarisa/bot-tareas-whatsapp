# Bot de Tareas por WhatsApp — Diseño

## Contexto

Proyecto nuevo, sin relación con el bot anterior de monitoreo Brandwatch/Corferias (archivado en
`bot-corferias-brandwatch-archive`, fuera de este repositorio). Vive en su propio repo:
`github.com/edrarisa/bot-tareas-whatsapp`.

El bot participa en un grupo de WhatsApp de trabajo. El problema que resuelve: en la operación
diaria se agendan tareas dentro del chat ("pongo a Cristian a hacer tal cosa"), pero se pierden
entre el volumen de mensajes del grupo — nadie las relee todas. El bot debe vigilar el chat,
detectar cuándo un mensaje agenda una tarea, y dejarla registrada en un Google Sheet con quién la
pidió, qué es, para quién es, para cuándo, y su estado.

Una segunda función (revisión de piezas de diseño por errores de ortografía en imágenes) se
identificó en la misma conversación pero es un subsistema independiente sin relación técnica con
este (visión/OCR vs. texto+Sheets). Queda **fuera de alcance** de este documento; se diseñará por
separado en una Fase 2.

## Alcance de esta Fase 1 (MVP)

Detectar tareas mencionadas en el chat, extraerlas, asignarlas si corresponde, y registrarlas en
Sheets. No incluye (queda para fases futuras):
- Marcar tareas como completadas desde el chat.
- Consultar tareas pendientes desde el chat.
- Recordatorios o seguimiento de vencimiento.
- Confirmación en el chat cuando el registro es exitoso (solo se responde en caso de error al
  guardar, ver más abajo).

## Arquitectura

El bot es un servicio **siempre encendido** que recibe webhooks de Evolution API (a diferencia del
bot anterior, que corría por cron). No hay endpoint de salida programado — todo se dispara por
mensajes entrantes del grupo.

```
Grupo WhatsApp (instancia Evolution API nueva y dedicada)
      │  cualquier mensaje de alguien que esté en el roster "Equipo"
      ▼
Evolution API ──POST──▶ FastAPI /webhook
      │
      ▼
task_handler.py   ← filtra: ¿es el grupo correcto? ¿el remitente está en "Equipo"?
      │                (si no está en el roster, se ignora sin gastar IA)
      ▼
classifier.py     ← LLM (GPT-4o mini): ¿es una tarea? si sí, extrae descripción y fecha límite
      │
      ▼
roster.py         ← si el mensaje tiene una @mención real de WhatsApp, resuelve ese JID → nombre
      │              leyendo la pestaña "Equipo" del Google Sheet (con caché corta en memoria)
      ▼
sheets_client.py  ← escribe fila nueva en la pestaña "Tareas"
      │
      ▼ (solo si falla el paso anterior)
evolution.py      ← responde en el grupo avisando que no se pudo guardar la tarea
```

## Componentes

- **`main.py`** — app FastAPI, expone `POST /webhook`, valida configuración al arrancar.
- **`services/evolution.py`** — parsea el payload de Evolution API (texto, remitente, JIDs
  mencionados) y envía mensajes de vuelta al grupo (solo usado para avisos de error).
- **`services/classifier.py`** — llama a OpenAI (GPT-4o mini) con el texto del mensaje y la fecha
  actual como contexto; devuelve `es_tarea: bool`, `descripcion: str`, `fecha_limite: str | null`
  (resuelve expresiones relativas como "mañana" o "el viernes" a una fecha absoluta).
- **`services/roster.py`** — lee la pestaña "Equipo" (nombre + número), resuelve un JID a un
  nombre legible, y responde si un JID dado pertenece al roster (para el filtro de remitentes).
  Cachea en memoria un rato corto para no golpear la API de Sheets en cada mensaje.
- **`services/sheets_client.py`** — wrapper delgado sobre la API de Sheets para leer "Equipo" y
  escribir en "Tareas".
- **`config.py`** — variables de entorno: credenciales Evolution API, OpenAI, ID del Sheet,
  credenciales de service account de Google, JID del grupo monitoreado.

## Datos en Google Sheets

**Pestaña "Tareas"**: `Fecha creación | Reportado por | Tarea | Asignado a | Fecha límite | Estado`
`Estado` queda fijo en `"Pendiente"` al crearse — no hay lógica para cambiarlo en este MVP, pero se
deja la columna para no migrar el esquema cuando se agregue esa función más adelante.

**Pestaña "Equipo"**: `Nombre | Número`, mantenida a mano por el equipo. Sirve doble propósito:
lista de remitentes cuyos mensajes se analizan, y lista de posibles responsables a asignar.

## Flujo de una tarea

1. Alguien que está en el roster "Equipo" escribe en el grupo, ej: *"Cristian, revisa el stand
   mañana @Cristian"* (con @mención real de WhatsApp a la persona).
2. Se valida que el mensaje es del grupo correcto y que el remitente está en "Equipo". Si no lo
   está, se ignora — no se gasta llamada a IA.
3. El texto se manda al clasificador. Si determina que **no** es una tarea (ej. charla casual),
   no pasa nada más — no se registra ni se responde, para no generar ruido.
4. Si sí es una tarea: se busca en el mensaje una @mención real de WhatsApp que no sea el propio
   remitente. Si hay una o más, se toma la primera y se resuelve ese JID a un nombre vía "Equipo"
   — ese es el responsable. Si no hay ninguna mención, el responsable queda `"Sin asignar"`.
   - Nota: si en la práctica el equipo escribe el nombre en texto plano en vez de usar la mención
     real de WhatsApp, la tarea quedará "Sin asignar" hasta que se acostumbren a etiquetar. Es un
     tema de hábito de uso, no de código, y queda visible en el Sheet para corregirlo con el
     tiempo.
5. Se escribe la fila en "Tareas" con fecha de creación, remitente, descripción, responsable,
   fecha límite (si se mencionó) y estado `"Pendiente"`.

## Manejo de errores

- **Falla la escritura a Google Sheets** (API caída, permisos, etc.): el bot responde en el grupo
  avisando que no pudo guardar la tarea, para que no se pierda en silencio. Es la única situación
  en la que el bot habla sin que se lo pidan.
- **Falla la llamada al clasificador** (OpenAI caído/timeout): se registra el error en logs del
  servidor; no se reintenta indefinidamente ni se bloquea el procesamiento de mensajes
  siguientes.
- **Payload de webhook inesperado o no parseable**: se ignora silenciosamente y se registra en
  logs, sin afectar el procesamiento de otros mensajes.

## Infraestructura

- Instancia de Evolution API **nueva y dedicada** (número de WhatsApp propio para este bot,
  distinto del usado para Corferias), desplegada como su propio servicio en el mismo VPS
  administrado con Coolify.
- Lenguaje: Python + FastAPI, continuando el stack del proyecto anterior.
- Credenciales de Google (service account) y de OpenAI configuradas como variables de entorno en
  Coolify, igual que el proyecto anterior.

## Pruebas

- Unitarias para `classifier.py` (parsing de la respuesta del LLM ante distintos textos de
  ejemplo, incluyendo casos sin fecha límite y fechas relativas), `roster.py` (resolución
  JID → nombre, JID no encontrado en el roster) y el parseo del payload de Evolution API en
  `evolution.py`.
- Mocks para OpenAI y Google Sheets — nada de llamadas reales en tests.

## Fuera de alcance (Fase 2 y futuras)

- Revisión de piezas de diseño por errores de ortografía en imágenes (visión + OCR) — subsistema
  independiente, se diseñará aparte.
- Marcar tareas como completadas, consultar tareas pendientes desde el chat, recordatorios de
  vencimiento.
