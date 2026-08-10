# Recordatorios de Tareas Urgentes — Diseño (Fase 4)

## Contexto

El bot ya clasifica mensajes como tareas, extrae descripción, fecha límite y hora límite, y las
guarda en el Sheet personal de la persona asignada, en la pestaña del cliente correspondiente (ver
`docs/superpowers/specs/2026-08-06-multi-client-task-routing-design.md`).

El problema que resuelve esta fase: una tarea urgente (con fecha límite hoy, o marcada como urgente
explícitamente) puede quedar sin hacer porque nadie la vuelve a mirar. Se necesita que el bot le
recuerde automáticamente a la persona asignada, por su número personal de WhatsApp, mientras la
tarea siga sin completarse -- sin que nadie tenga que revisarlo a mano.

## Alcance

- Detectar automáticamente, al crear la tarea, si es "urgente" (fecha límite el mismo día en que se
  crea, o lenguaje explícito de urgencia en el mensaje).
- Mandar un recordatorio por WhatsApp al número **personal** de la persona asignada (no al grupo) a
  las 12:00 m. y a las 5:00 p. m., de lunes a viernes, mientras la tarea siga urgente y sin
  completar.
- Respetar una brecha mínima de 2 horas entre el momento en que se asignó la tarea y el envío de
  cualquier alerta (las labores inician a las 8 a. m.).
- Repetir la alerta todos los días hábiles (ambas ventanas) hasta que la tarea se marque como
  "Completada" en el Sheet -- sin límite de días.
- Ser resistente a reinicios del bot: ninguna alerta debe perderse ni duplicarse aunque el proceso
  se caiga o se redeploye a media revisión.

No incluye:

- Alertas para tareas no urgentes.
- Alertas al grupo de WhatsApp -- siempre son al número personal.
- Cambiar o re-evaluar la urgencia de una tarea después de creada.
- Recordatorios en fin de semana.
- Un tercer horario de alerta más allá de las 12 m. y las 5 p. m.

## Arquitectura

```
Cada 15 min (bucle interno del bot, arranca con la app, corre en threadpool)
      │
      ▼
ReminderScanner.run_check()
      │
      ├─ ¿Hoy es sábado o domingo? -> no hace nada
      ├─ ¿Aún no pasó ni el mediodía ni las 5pm? -> no hace nada
      │
      ▼
Lee "Equipo" del Sheet central (nombre, teléfono, Sheet ID) vía SheetsClient
      │
      ▼
Por cada persona con Sheet ID configurado:
      │
      ├─ Abre su Sheet personal (gspread)
      ├─ Recorre TODAS sus pestañas de cliente
      │
      ▼
   Por cada fila de tarea:
      ├─ ¿Urgente = "Sí"? ¿Estado ≠ "Completada"?
      ├─ ¿Ya pasaron ≥2h desde que se creó?
      ├─ ¿Ya pasó la ventana (12pm / 5pm) y NO se mandó hoy?
      │       │ (si todo aplica)
      │       ▼
      │  send_text_message(numero_personal, mensaje)
      │       │ (solo si el envío fue exitoso)
      │       ▼
      │  worksheet.update_cell(...) -- escribe la fecha de hoy en
      │  "Alerta 12pm" o "Alerta 5pm"
      ▼
Si falla una persona (Sheet no compartida, ID inválido, etc.), se salta y se
sigue con las demás -- un error individual no detiene la revisión completa.
```

## Componentes

- **`services/classifier.py`** (se extiende) — `ClassificationResult` gana `es_urgente: bool`.
  El `SYSTEM_PROMPT` gana una regla: `es_urgente` es `true` si la fecha límite resuelta es el mismo
  día en que se creó la tarea, **o** si el mensaje usa lenguaje explícito de urgencia ("urgente",
  "ya", "necesito esto ahora"), lo que ocurra primero. Se decide una sola vez, al clasificar el
  mensaje; nunca se re-evalúa después.

- **`services/sheets_client.py`** (`PersonalTaskWriter` se extiende) — `_HEADERS` gana tres
  columnas: `Urgente`, `Alerta 12pm`, `Alerta 5pm`. `append_task(...)` gana el parámetro
  `is_urgent: bool`, y escribe `"Sí"`/`"No"` en la columna correspondiente; las dos columnas de
  alerta quedan vacías al crear la tarea. La columna "Estado" no cambia de posición (sigue en F),
  así que el desplegable de colores no se ve afectado.

- **`services/reminder_scanner.py`** (nuevo) — `ReminderScanner`, el motor de revisión:
  - Constructor: `sheets_client` (para leer "Equipo"), un cliente `gspread` crudo (para abrir
    Sheets personales, igual que `PersonalTaskWriter`), una función `send_message(phone_jid, text)`
    (reutiliza `services.evolution.send_text_message` -- el mismo endpoint de Evolution API sirve
    tanto para números individuales como para grupos), y una función `now_func` inyectable (para
    pruebas; por defecto `datetime.now(ZoneInfo(Config.TIMEZONE))`, la misma zona horaria
    -- `America/Bogota` -- que ya usa `task_handler.py`).
  - `run_check() -> None`: implementa el algoritmo completo descrito arriba. Cada fila de tarea se
    identifica por columnas fijas (Fecha, Reportado por, Descripción, Fecha límite, Hora, Estado,
    Urgente, Alerta 12pm, Alerta 5pm), sin depender de nombres de encabezado en tiempo de
    ejecución -- coincide con el orden fijo que ya escribe `PersonalTaskWriter`. La columna "Fecha"
    (creación) se interpreta con `strptime(..., "%Y-%m-%d %H:%M")`, el mismo formato que
    `task_handler.py` ya escribe, y se asume en la zona horaria configurada (`Config.TIMEZONE`).
  - Un fallo al abrir/leer la hoja de **una** persona se captura y se registra en logs; el escaneo
    continúa con las demás personas.
  - Un fallo al **enviar** el mensaje de WhatsApp se registra en logs y esa fila **no** se marca
    como enviada -- se reintenta en la siguiente revisión.

- **`services/reminder_scheduler.py`** (nuevo) — `run_reminder_loop(scanner, interval_seconds=900,
  ...)`: bucle asíncrono infinito que llama a `scanner.run_check()` (despachado a un threadpool,
  igual que los handlers de webhook, para no bloquear el event loop) y luego espera
  `interval_seconds` (15 minutos por defecto) antes de repetir. Corre una primera revisión
  inmediatamente al arrancar, sin esperar los 15 minutos iniciales. Cualquier excepción durante
  `run_check()` se registra y el bucle continúa -- nunca se detiene por un error de una sola
  revisión.

- **`main.py`** (se extiende) — en el `lifespan`, se crea el `ReminderScanner` y se lanza
  `run_reminder_loop(...)` como una tarea de `asyncio` en segundo plano; se cancela limpiamente al
  apagar la app.

## Mensaje de alerta

> ⏰ Recordatorio: tienes pendiente la tarea urgente de *{cliente}*: "{descripción}". Márcala como
> "Completada" en tu Sheet cuando la termines.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Hoy es fin de semana | La revisión completa se salta, no se leen Sheets. |
| Aún no ha pasado ninguna ventana (antes del mediodía) | La revisión se salta, no se leen Sheets. |
| Falla al abrir/leer la Sheet personal de una persona | Se registra en logs; se continúa con las demás personas. |
| Falla el envío del mensaje de WhatsApp | Se registra en logs; la fila **no** se marca como enviada, se reintenta en la próxima revisión (≤15 min después). |
| Una fila tiene una fecha de creación no interpretable | Se ignora esa fila (con log) y se continúa con las demás. |
| El bot estuvo caído y se levanta después de las 5pm | Puede mandar **ambas** alertas (12pm y 5pm) en la misma revisión si ninguna se había mandado -- se prefiere eso a perder una alerta. |

## Pruebas

- **`classifier.py`**: mismo patrón que `hora_limite` -- extracción y validación de `es_urgente`
  (bool o error si no lo es).
- **`sheets_client.py`**: `PersonalTaskWriter` escribe las tres columnas nuevas correctamente al
  crear una tarea.
- **`reminder_scanner.py`** (con fakes de `sheets_client`, cliente `gspread`, `send_message`, y
  `now_func` inyectado):
  - Se salta por completo en fin de semana.
  - Se salta antes del mediodía.
  - Ignora tareas no urgentes.
  - Ignora tareas ya completadas.
  - Ignora tareas con menos de 2h desde su creación.
  - Manda la alerta de mediodía cuando corresponde y marca la columna.
  - No vuelve a mandar la alerta de mediodía el mismo día si ya está marcada.
  - Sí la vuelve a mandar al día siguiente (la marca de ayer no coincide con hoy).
  - Mediodía y 5pm se evalúan y marcan de forma independiente.
  - Si falla la Sheet de una persona, continúa revisando a las demás.
  - Si falla el envío del mensaje, no marca la columna como enviada.
- **`reminder_scheduler.py`**: el bucle llama a `run_check()` en cada iteración, espera el
  intervalo configurado, y sigue corriendo aunque `run_check()` lance una excepción.

## Fuera de alcance

- Alertas para tareas sin marcar como urgentes.
- Cualquier alerta enviada al grupo de WhatsApp en vez de al número personal.
- Cambiar la urgencia de una tarea después de creada (por ejemplo, si alguien edita la fecha límite
  directamente en el Sheet).
- Recordatorios en fin de semana o en un tercer horario distinto a 12pm/5pm.
- Notificar a alguien más (por ejemplo, a quien reportó la tarea) si esta sigue sin completarse.
