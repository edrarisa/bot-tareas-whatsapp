from services.seen_messages import SeenMessageTracker


def test_mark_if_new_returns_true_first_time():
    tracker = SeenMessageTracker()

    assert tracker.mark_if_new("abc") is True


def test_mark_if_new_returns_false_on_repeat():
    tracker = SeenMessageTracker()
    tracker.mark_if_new("abc")

    assert tracker.mark_if_new("abc") is False


def test_mark_if_new_treats_different_ids_independently():
    tracker = SeenMessageTracker()

    assert tracker.mark_if_new("abc") is True
    assert tracker.mark_if_new("xyz") is True


def test_evicts_entries_older_than_ttl():
    clock = {"now": 0.0}
    tracker = SeenMessageTracker(ttl_seconds=60, time_func=lambda: clock["now"])
    tracker.mark_if_new("abc")

    clock["now"] += 61

    assert tracker.mark_if_new("abc") is True


def test_does_not_evict_entries_within_ttl():
    clock = {"now": 0.0}
    tracker = SeenMessageTracker(ttl_seconds=60, time_func=lambda: clock["now"])
    tracker.mark_if_new("abc")

    clock["now"] += 30

    assert tracker.mark_if_new("abc") is False
