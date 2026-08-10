"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler and the spelling-review handler. Google Sheets / roster clients
are created lazily on startup so importing this module has no side effects
(needed for testing). Handlers run in a thread pool (not directly on the
event loop) since they do blocking network I/O (OpenAI, Google Sheets,
Evolution API). A background loop also runs on a fixed interval to check
for urgent tasks that need a WhatsApp reminder.
"""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from config import Config
from handlers.spelling_handler import handle_webhook_payload as handle_spelling_payload
from handlers.task_handler import handle_webhook_payload as handle_task_payload
from services.group_registry import GroupRegistry
from services.image_batch import ImageBatchBuffer
from services.lid_resolver import LidResolver
from services.reminder_scanner import create_reminder_scanner
from services.reminder_scheduler import run_reminder_loop
from services.roster import Roster
from services.sheets_client import create_personal_task_writer, create_sheets_client

logging.basicConfig(level=Config.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    sheets_client = create_sheets_client(Config.GOOGLE_SHEETS_ID, Config.GOOGLE_CREDENTIALS_PATH)
    app.state.sheets_client = sheets_client
    app.state.roster = Roster(sheets_client)
    app.state.group_registry = GroupRegistry(sheets_client)
    app.state.lid_resolver = LidResolver()
    app.state.personal_task_writer = create_personal_task_writer(Config.GOOGLE_CREDENTIALS_PATH)
    app.state.image_batch_buffer = ImageBatchBuffer()

    reminder_scanner = create_reminder_scanner(sheets_client, Config.GOOGLE_CREDENTIALS_PATH)
    reminder_task = asyncio.create_task(run_reminder_loop(reminder_scanner))
    try:
        yield
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Failed to parse webhook JSON body")
        return {"status": "ok"}

    try:
        await run_in_threadpool(
            handle_task_payload,
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.group_registry,
            request.app.state.personal_task_writer,
        )
    except Exception:
        logger.exception("Failed to process task webhook payload")

    try:
        await run_in_threadpool(
            handle_spelling_payload,
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.group_registry,
            request.app.state.image_batch_buffer,
        )
    except Exception:
        logger.exception("Failed to process spelling webhook payload")

    return {"status": "ok"}
