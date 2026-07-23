# bot-tareas-whatsapp

Bot de WhatsApp que vigila un grupo, detecta cuándo alguien agenda una tarea, y la registra en un
Google Sheet con responsable, fecha límite y estado. Ver el diseño completo en
`docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`.

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
5. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio.

## Correr localmente

```bash
uvicorn main:app --reload --port 8000
```

## Tests

```bash
pytest -v
```
