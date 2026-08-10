import asyncio

import pytest

from services.reminder_scheduler import run_reminder_loop


class StopLoop(Exception):
    pass


class FakeScanner:
    def __init__(self, fail_times=0):
        self.check_calls = 0
        self._fail_times = fail_times

    def run_check(self):
        self.check_calls += 1
        if self.check_calls <= self._fail_times:
            raise RuntimeError("boom")


def _run(coro):
    asyncio.run(coro)


def test_runs_check_immediately_before_first_sleep():
    scanner = FakeScanner()
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise StopLoop()

    with pytest.raises(StopLoop):
        _run(run_reminder_loop(scanner, interval_seconds=900, sleep=fake_sleep))

    assert scanner.check_calls == 1
    assert sleep_calls == [900]


def test_keeps_looping_after_check_raises():
    scanner = FakeScanner(fail_times=1)
    sleep_count = {"n": 0}

    async def fake_sleep(seconds):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            raise StopLoop()

    with pytest.raises(StopLoop):
        _run(run_reminder_loop(scanner, interval_seconds=1, sleep=fake_sleep))

    assert scanner.check_calls == 2


def test_dispatches_check_via_run_in_thread():
    scanner = FakeScanner()
    dispatched = []

    async def fake_run_in_thread(func):
        dispatched.append(func)
        return func()

    async def fake_sleep(seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        _run(
            run_reminder_loop(
                scanner, interval_seconds=900, sleep=fake_sleep, run_in_thread=fake_run_in_thread
            )
        )

    assert dispatched == [scanner.run_check]
