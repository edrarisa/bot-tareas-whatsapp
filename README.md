# bot-tareas-whatsapp

Bot de WhatsApp con dos funciones:
1. Vigila un grupo, detecta cuándo alguien agenda una tarea (mencionando a alguien con `@`), y la
   registra en un Google Sheet con responsable, fecha límite y estado. Ver
   `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`.
2. Cuando alguien del equipo manda una imagen con la palabra "ortografía" en el texto, revisa la
   ortografía en español de la imagen con OpenAI y responde en el grupo. Ver
   `docs/superpowers/specs/2026-08-05-image-spelling-review-design.md`.

## Setup

1. `pip install -r requirements.txt`
2. Copiar `.env.example` a `.env` y completar las credenciales (Evolution API, Google Sheets,
   OpenAI).
3. Colocar el JSON de la service account de Google en la ruta indicada por
   `GOOGLE_CREDENTIALS_PATH` (por defecto `secrets/google-service-account.json`).
4. Crear el Google Sheet con dos pestañas:
   - **Equipo**: columnas `Nombre | Numero` (número sin `+` ni espacios, ej. `573001112233`).
   - **Tareas**: se llena automáticamente; columnas
     `Fecha creación | Reportado por | Tarea | Asignado a | Fecha límite | Estado`.
5. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio, con
   el evento `MESSAGES_UPSERT` activado.
6. Activar **"Webhook Base64"** en esa misma configuración del webhook -- sin esto, la revisión de
   ortografía en imágenes no puede funcionar, porque el contenido de la imagen no llega en el
   payload.

## Correr localmente

```bash
uvicorn main:app --reload --port 8000
```

## Tests

```bash
pytest -v
```
