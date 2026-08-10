"""
Runs ReminderScanner.run_check() on a fixed interval in the background,
for as long as the app is running. Dispatches each check to a thread pool
(like the webhook handlers) since it does blocking I/O (Google Sheets,
Evolution API), so it never blocks the event loop. Any exception during a
single check is logged and the loop keeps going -- a bad check should
never stop future reminders from being evaluated.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 900  # 15 minutes


async def run_reminder_loop(
    scanner,
    interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
    sleep=asyncio.sleep,
    run_in_thread=asyncio.to_thread,
) -> None:
    while True:
        try:
            await run_in_thread(scanner.run_check)
        except Exception:
            logger.exception("Reminder check failed")
        await sleep(interval_seconds)
