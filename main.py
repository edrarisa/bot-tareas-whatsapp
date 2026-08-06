"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler and the spelling-review handler. Google Sheets / roster clients
are created lazily on startup so importing this module has no side effects
(needed for testing).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from config import Config
from handlers.spelling_handler import handle_webhook_payload as handle_spelling_payload
from handlers.task_handler import handle_webhook_payload as handle_task_payload
from services.lid_resolver import LidResolver
from services.roster import Roster
from services.sheets_client import create_sheets_client

logging.basicConfig(level=Config.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    sheets_client = create_sheets_client(Config.GOOGLE_SHEETS_ID, Config.GOOGLE_CREDENTIALS_PATH)
    app.state.sheets_client = sheets_client
    app.state.roster = Roster(sheets_client)
    app.state.lid_resolver = LidResolver(Config.WHATSAPP_GROUP_JID)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Failed to parse webhook JSON body")
        return {"status": "ok"}

    try:
        handle_task_payload(
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.sheets_client,
            Config.WHATSAPP_GROUP_JID,
        )
    except Exception:
        logger.exception("Failed to process task webhook payload")

    try:
        handle_spelling_payload(
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            Config.WHATSAPP_GROUP_JID,
        )
    except Exception:
        logger.exception("Failed to process spelling webhook payload")

    return {"status": "ok"}
