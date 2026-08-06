# bot-tareas-whatsapp

Bot de WhatsApp con dos funciones, en varios grupos (uno por cliente):
1. Vigila cada grupo, detecta cuándo alguien agenda una tarea (mencionando a alguien con `@`), y la
   registra en el Google Sheet personal de esa persona, en la pestaña del cliente correspondiente.
   Ver `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md` y
   `docs/superpowers/specs/2026-08-06-multi-client-task-routing-design.md`.
2. Cuando alguien del equipo manda una imagen con la palabra "ortografía" (o el código "u56") en el
   texto, revisa la ortografía en español de la imagen con OpenAI y responde en el grupo. Ver
   `docs/superpowers/specs/2026-08-05-image-spelling-review-design.md`.

## Setup

1. `pip install -r requirements.txt`
2. Copiar `.env.example` a `.env` y completar las credenciales (Evolution API, Google Sheets,
   OpenAI).
3. Colocar el JSON de la service account de Google en la ruta indicada por
   `GOOGLE_CREDENTIALS_PATH` (por defecto `secrets/google-service-account.json`).
4. Crear el Google Sheet **central de configuración** (el que apunta `GOOGLE_SHEETS_ID`) con dos
   pestañas:
   - **Equipo**: columnas `Nombre | Numero | Sheet ID` (número sin `+` ni espacios, ej.
     `573001112233`; el Sheet ID es el de la hoja personal de esa persona -- se puede dejar vacío
     hasta que la tenga lista, el bot avisará en el grupo si falta).
   - **Grupos**: columnas `Grupo | Cliente | Nombre del grupo` (el JID del grupo de WhatsApp, el
     nombre del cliente que se usará como nombre de pestaña, y un tercer campo libre solo para tu
     referencia).
5. Por cada integrante del equipo: crear (o usar) su Google Sheet personal, **compartirlo con el
   correo de la cuenta de servicio** (el mismo JSON de `GOOGLE_CREDENTIALS_PATH`) con permiso de
   Editor, y poner su ID en la columna "Sheet ID" de "Equipo". Las pestañas por cliente se crean
   automáticamente la primera vez que se le asigna una tarea de ese cliente -- no hay que crearlas
   a mano.
6. Agregar el bot a cada grupo de WhatsApp de cliente, y agregar una fila en "Grupos" por cada uno.
7. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio, con
   el evento `MESSAGES_UPSERT` activado.
8. Activar **"Webhook Base64"** en esa misma configuración del webhook -- sin esto, la revisión de
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
