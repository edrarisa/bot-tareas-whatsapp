# Revisión de Ortografía en Imágenes — Diseño (Fase 2)

## Contexto

Segunda función del bot de WhatsApp, identificada en la misma conversación inicial que dio origen
al sistema de tareas (ver `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`), pero
deliberadamente separada de ese diseño por ser un subsistema técnicamente independiente (visión +
OCR vs. texto + Sheets).

El problema que resuelve: los diseñadores envían piezas gráficas (flyers, publicaciones, etc.) al
grupo, y a veces tienen errores de ortografía que pasan desapercibidos. La idea es que el equipo
pueda pedirle al bot que revise una imagen antes de publicarla, mandándola al grupo con una palabra
clave, y que el bot responda ahí mismo si encuentra algún error.

## Alcance

Detectar cuándo alguien manda una imagen pidiendo revisión de ortografía, analizarla con IA, y
responder en el grupo con el resultado. No incluye:
- Revisión de gramática, diseño, o cualquier otra cosa que no sea ortografía.
- Corrección automática de la imagen — el bot solo señala el error, no lo arregla.
- Enviar el resultado por mensaje directo a nadie — la respuesta siempre va al grupo, porque la
  persona ya vio el mensaje ahí (mandarle un aviso aparte se consideró innecesariamente invasivo).

## Arquitectura

Corre en paralelo al sistema de tareas, sobre el mismo webhook y el mismo grupo de WhatsApp — no
reemplaza ni modifica el flujo de tareas existente.

```
Mensaje con imagen + "ortografía" en el caption
      │
      ▼
services/evolution.py   ← extrae la imagen (base64) y el caption del payload
      │
      ▼
spelling_handler.py     ← filtra: ¿grupo correcto? ¿remitente en "Equipo"? ¿el caption
      │                     contiene "ortografía"? (si no, se ignora sin gastar IA)
      ▼
spelling_reviewer.py    ← OpenAI (GPT-4o mini, visión): revisa la ortografía en español
      │
      ▼
evolution.py             ← responde en el grupo, siempre (haya o no error)
```

## Componentes

- **`services/evolution.py`** (se extiende) — nueva función `parse_image_messages(payload)` que
  reconoce mensajes de tipo `imageMessage`, y extrae: imagen en base64, mimetype, caption,
  remitente, grupo, `from_me`. Requiere que la instancia de Evolution API tenga activada la opción
  **"Webhook Base64"** (ver Infraestructura) — sin eso, el webhook solo trae una referencia a la
  imagen, no su contenido.
- **`services/spelling_reviewer.py`** (nuevo) — `review_spelling(image_base64, mimetype) ->
  SpellingReviewResult`, con `SpellingReviewResult(has_errors: bool, details: str)`. Llama a
  OpenAI con la imagen y un prompt que pide revisar ortografía en español y describir cualquier
  error encontrado (qué palabra, y cuál sería la forma correcta).
- **`handlers/spelling_handler.py`** (nuevo) — `handle_webhook_payload(payload, roster,
  group_jid)`: filtra por grupo, remitente conocido en "Equipo", y presencia de la palabra clave
  en el caption (normalizada sin mayúsculas ni acentos, para que "Ortografia", "ORTOGRAFÍA", etc.
  también activen la función). Si pasa el filtro, llama al revisor y responde en el grupo.

## Por qué el filtro de "Equipo" también aplica aquí

Mismo principio que en el sistema de tareas: cualquier acción que dispare una llamada a IA
(pagada, por imagen) necesita este filtro, para evitar que alguien ajeno al equipo (un cliente en
el grupo, un proveedor externo) genere gasto sin control simplemente mandando imágenes con la
palabra clave. No es una restricción de acceso al bot en general — es control de costo y de ruido,
igual que en el resto del sistema.

## Palabra clave

Disparador: el caption de la imagen contiene la palabra "ortografía" (comparación insensible a
mayúsculas y acentos). No se requiere mención a nadie — cubre tanto *"@persona revisar ortografía
de la imagen"* como *"envío archivos para revisar ortografía"*.

## Flujo de una revisión

1. Alguien en "Equipo" manda una imagen al grupo con un caption que contiene "ortografía".
2. Se valida que el mensaje es del grupo correcto y que el remitente está en "Equipo". Si no, se
   ignora sin gastar IA.
3. Se manda la imagen a OpenAI (GPT-4o mini con visión) pidiendo que revise la ortografía en
   español y describa cualquier error.
4. El bot responde **siempre** en el grupo:
   - Sin errores: *"✅ Ortografía revisada, no encontré errores."*
   - Con errores: *"⚠️ Encontré posibles errores de ortografía: [detalle de cada palabra y su forma
     correcta]."* Si hay más de un error, se listan todos en la misma respuesta, no solo el
     primero.

## Manejo de errores

- **Falla la llamada a OpenAI** (red caída, imagen no procesable, etc.): se registra el error en
  logs del servidor; el bot **no responde** en el grupo. A diferencia de las tareas, aquí no hay
  ningún dato que se pierda silenciosamente si falla — la imagen sigue en el chat tal cual, así
  que no hace falta un aviso de error que solo generaría confusión.
- **Imagen sin la palabra clave, o palabra clave sin imagen**: se ignora silenciosamente, igual
  que cualquier mensaje de chat normal.

## Infraestructura

- Activar **"Webhook Base64"** en la configuración de Events → Webhook de la instancia
  `bot-tareas` en el manager de Evolution API, para que el contenido de las imágenes llegue
  directo en el payload del webhook.
- Sin cambios de infraestructura adicionales — usa el mismo despliegue, la misma API key de
  OpenAI, y el mismo grupo de WhatsApp que el sistema de tareas.

## Pruebas

- Unitarias para `spelling_reviewer.py` (fakes del cliente de OpenAI, sin llamadas reales),
  `parse_image_messages` en `evolution.py` (extracción de imagen/caption de distintas formas de
  payload), y el filtro de palabra clave/remitente en `spelling_handler.py`.

## Fuera de alcance

- Revisión de gramática o estilo, más allá de ortografía.
- Corrección automática de las piezas.
- Cualquier interacción por fuera del grupo de WhatsApp (mensajes directos, notificaciones).
