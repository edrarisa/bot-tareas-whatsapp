"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler. Google Sheets / roster clients are created lazily on startup
so importing this module has no side effects (needed for testing).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from config import Config
from handlers.task_handler import handle_webhook_payload
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
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
        handle_webhook_payload(
            payload,
            request.app.state.roster,
            request.app.state.sheets_client,
            Config.WHATSAPP_GROUP_JID,
        )
    except Exception:
        logger.exception("Failed to process webhook payload")
    return {"status": "ok"}
