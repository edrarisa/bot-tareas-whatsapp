# Multi-Grupo y Enrutamiento de Tareas por Cliente — Diseño (Fase 3)

## Contexto

Hasta ahora el bot vive en un solo grupo de WhatsApp (`Config.WHATSAPP_GROUP_JID`) y guarda todas
las tareas en una sola pestaña "Tareas" de un Google Sheet central compartido por todo el equipo.

El bot va a agregarse a **varios grupos de WhatsApp, uno por cliente** (ej. clinicachia,
optifalcon, megaopticas). Además, cada integrante del equipo va a tener su **propio Google Sheet
personal**, con una pestaña por cada cliente en el que trabaja. Cuando alguien asigna una tarea con
`@mención` en el grupo de un cliente, esa tarea debe quedar guardada en el Sheet personal de la
persona mencionada, en la pestaña correspondiente a ese cliente — no en un lugar central compartido.

Este diseño reemplaza el mecanismo de un solo grupo / un solo destino de guardado por uno dinámico,
basado en una hoja de configuración que el equipo puede editar sin tocar código.

## Alcance

Se cubren ambas funciones existentes del bot:

- **Tareas**: enrutar cada tarea al Sheet personal correcto, en la pestaña del cliente correcto,
  según en qué grupo se creó y a quién se asignó.
- **Ortografía**: la revisión de imágenes también pasa a funcionar en cualquier grupo configurado,
  no solo en el grupo original de pruebas.

No incluye:

- Migración de las tareas históricas que ya existen en la pestaña "Tareas" del Sheet central — esa
  pestaña deja de recibir tareas nuevas, pero no se toca ni se borra.
- Restricciones de equipo por cliente (quién puede ser mencionado en cada grupo) — la lista de
  "Equipo" sigue siendo una sola, global, para todos los grupos.
- Automatizar el paso de compartir cada Sheet personal con la cuenta de servicio — sigue siendo un
  paso manual, una sola vez por persona.

## Arquitectura

```
Mensaje (texto o imagen) en un grupo de WhatsApp
      │
      ▼
services/evolution.py        ← extrae remitente, grupo, texto/imagen (sin cambios)
      │
      ▼
GroupRegistry.get_client_name(group_jid)
      │                          │
      │ grupo no mapeado         │ grupo mapeado → nombre del cliente
      ▼                          ▼
   se ignora              LidResolver.resolve(jid, group_jid)  ← ahora cachea por grupo
                                  │
                                  ▼
                           Roster (Equipo, global)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                             ▼
             task_handler.py               spelling_handler.py
                    │                             │
                    ▼                             ▼
       resuelve destinatario              revisa con OpenAI y
       y su Sheet ID personal             responde en el grupo
                    │                        (sin cambios de fondo)
                    ▼
         PersonalTaskWriter.append_task(
             sheet_id, cliente, ...)
                    │
                    ▼
    Abre el Sheet de esa persona, crea la
    pestaña del cliente si no existe, y
    agrega la fila
```

## Componentes

- **`services/group_registry.py`** (nuevo) — `GroupRegistry`, mismo patrón que `Roster`: lee la
  pestaña "Grupos" del Sheet central, cachea en memoria con TTL y fallback a caché vieja si falla
  la relectura. Expone `get_client_name(group_jid) -> str | None`.

- **`services/roster.py`** (se extiende) — `Roster` gana un tercer campo por persona: el Sheet ID
  personal. Nuevo método `resolve_personal_sheet_id(jid) -> str | None`, que devuelve `None` si la
  persona existe en "Equipo" pero no tiene Sheet ID configurado todavía.

- **`services/sheets_client.py`** (se reestructura) —
  - `SheetsClient` (Sheet central): `read_team_roster()` pasa a devolver tuplas de 3 elementos
    (nombre, teléfono, sheet_id); nuevo método `read_group_mapping() -> list[tuple[str, str]]`
    (grupo, cliente), leyendo la pestaña "Grupos".
  - `PersonalTaskWriter` (nuevo): recibe el cliente `gspread` crudo (no un spreadsheet fijo).
    `append_task(sheet_id, client_tab, created_at, reporter, description, due_date, status)` abre
    el spreadsheet por `sheet_id`, intenta `spreadsheet.worksheet(client_tab)`, y si no existe
    (`WorksheetNotFound`) la crea con encabezados (`Fecha`, `Reportado por`, `Descripción`, `Fecha
    límite`, `Estado`) antes de agregar la fila.
  - `create_sheets_client(sheet_id, credentials_path)` se ajusta para también devolver (o exponer)
    el cliente `gspread` crudo, de forma que se pueda construir el `PersonalTaskWriter` con el
    mismo login de service account.

- **`services/lid_resolver.py`** (cambia la firma) — deja de recibir un `group_jid` fijo en el
  constructor. `resolve(jid, group_jid)` ahora recibe el grupo como parámetro, y cachea
  participantes por grupo internamente (un diccionario de cachés, uno por `group_jid`, cada uno con
  su propio TTL y fallback a caché vieja).

- **`handlers/task_handler.py`** (se ajusta) — antes de cualquier otra cosa, consulta
  `group_registry.get_client_name(message.group_jid)`; si es `None`, ignora el mensaje (mismo
  comportamiento silencioso que hoy con el "grupo equivocado"). El resto del flujo de clasificación
  y resolución de destinatario no cambia, salvo que al final:
  - Si no se resolvió ningún destinatario válido (sigue en "Sin asignar"): avisa en el grupo y no
    guarda nada.
  - Si se resolvió el destinatario pero no tiene Sheet ID: avisa en el grupo (mensaje específico
    con el nombre) y no guarda nada.
  - Si todo está bien: llama a `PersonalTaskWriter.append_task(...)` con el `sheet_id` del
    destinatario y el nombre del cliente (de `GroupRegistry`) como pestaña destino.

- **`handlers/spelling_handler.py`** (se ajusta) — mismo chequeo de `GroupRegistry` al inicio. El
  buffer de agrupamiento de imágenes (`ImageBatchBuffer`) pasa a indexarse por `(sender_jid,
  group_jid)` en vez de solo `sender_jid`, para no mezclar imágenes de la misma persona enviadas a
  dos grupos/clientes distintos casi al mismo tiempo.

- **`main.py`** — crea `GroupRegistry` y `PersonalTaskWriter` en el `lifespan`, junto a los
  componentes existentes, y los pasa a ambos handlers.

- **`config.py`** — se elimina `WHATSAPP_GROUP_JID` (ya no hay un solo grupo fijo); el resto de la
  configuración no cambia.

## Esquema de las hojas

**Pestaña "Equipo"** (Sheet central, se le agrega una columna):

| Nombre | Teléfono | Sheet ID personal |
|---|---|---|

**Pestaña "Grupos"** (Sheet central, nueva):

| Grupo (JID) | Cliente | Nombre del grupo |
|---|---|---|

La tercera columna ("Nombre del grupo") es solo para referencia humana — el bot no la lee, existe
para que quien edite la hoja sepa a qué grupo corresponde cada JID sin tener que adivinarlo.

**Pestaña por cliente, dentro del Sheet personal de cada persona** (creada automáticamente la
primera vez que se le asigna una tarea de ese cliente):

| Fecha | Reportado por | Descripción | Fecha límite | Estado |
|---|---|---|---|---|

No lleva columna "Asignado a" — el Sheet completo ya es de esa persona, así que sería redundante.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Grupo no está en la pestaña "Grupos" | Se ignora en silencio (tareas y ortografía). |
| Nadie mencionado se resuelve a un destinatario válido | Aviso en el grupo: *"⚠️ No pude identificar a quién asignar esta tarea, no la guardé."* No se guarda nada. |
| Destinatario válido pero sin Sheet ID en "Equipo" | Aviso en el grupo: *"⚠️ No encontré la hoja personal de {nombre}, avísenle para configurarla."* No se guarda nada. |
| Falla real al escribir (Sheet ID inválido, no compartido con la cuenta de servicio, error de red) | Aviso genérico existente: *"⚠️ No pude guardar esta tarea, avísenle a alguien."* |
| Falla al leer "Equipo" o "Grupos" | Igual que hoy: se usa la caché vieja si existe; si es la primera carga y falla, se propaga el error (se ve en logs, no se responde). |

## Infraestructura y pasos manuales

- Cada integrante del equipo debe **compartir su Sheet personal** con el correo de la cuenta de
  servicio de Google que ya usa el bot, con permiso de **Editor**. Sin esto, el bot no puede leer
  ni escribir en su hoja, y cualquier tarea asignada a esa persona fallará con el aviso genérico de
  guardado.
- Alguien con acceso al Sheet central debe llenar la pestaña "Grupos" con cada grupo nuevo al que
  se agregue el bot, y la columna de Sheet ID en "Equipo" para cada persona.
- El bot debe agregarse manualmente a cada grupo de WhatsApp nuevo (esto no cambia respecto a hoy).

## Pruebas

- **`GroupRegistry`**: mismo patrón de pruebas que `Roster` — carga, caché TTL, fallback a caché
  vieja, grupo desconocido devuelve `None`.
- **`Roster`**: tolera Sheet ID vacío o columna faltante (`resolve_personal_sheet_id` devuelve
  `None`), sigue resolviendo nombre y validando remitente conocido igual que antes.
- **`PersonalTaskWriter`**: abre el spreadsheet correcto por ID, crea la pestaña con encabezados si
  no existe (usando un doble/fake que simula `WorksheetNotFound`), reutiliza la pestaña si ya
  existe, agrega la fila con los valores correctos.
- **`LidResolver`**: `resolve(jid, group_jid)` cachea por grupo de forma aislada (la caché de un
  grupo no contamina la de otro), y sigue teniendo el mismo comportamiento de TTL/fallback que
  antes.
- **`task_handler`**: grupo no mapeado se ignora; los tres nuevos casos de aviso (sin destinatario,
  sin Sheet ID, falla de guardado); el caso feliz usa el `sheet_id` y el `cliente` correctos.
- **`spelling_handler`**: mismo filtro por `GroupRegistry`; el buffer de imágenes no mezcla lotes de
  distintos grupos para el mismo remitente.
- **`main.py` / `config.py`**: se elimina toda referencia a `WHATSAPP_GROUP_JID`; los componentes
  nuevos quedan conectados correctamente en el `lifespan`.

## Fuera de alcance

- Migración o consolidación de las tareas ya guardadas en la pestaña "Tareas" del Sheet central.
- Restricción de qué personas pueden ser mencionadas por grupo/cliente (la lista de "Equipo" sigue
  siendo global).
- Automatizar el paso de compartir cada Sheet personal con la cuenta de servicio.
- Crear o gestionar los Sheets personales por el usuario — se asume que cada quien ya tiene el suyo
  o lo crea manualmente antes de que le asignen su Sheet ID en "Equipo".
