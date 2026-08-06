from services.image_batch import ImageBatchBuffer


def test_single_message_claims_its_own_batch():
    buffer = ImageBatchBuffer()

    snapshot = buffer.add("sender-1", "msg-1")

    assert snapshot == ["msg-1"]
    claimed = buffer.try_claim("sender-1", len(snapshot))
    assert claimed == ["msg-1"]


def test_second_message_before_claim_grows_the_batch():
    buffer = ImageBatchBuffer()

    first_snapshot = buffer.add("sender-1", "msg-1")
    second_snapshot = buffer.add("sender-1", "msg-2")

    assert first_snapshot == ["msg-1"]
    assert second_snapshot == ["msg-1", "msg-2"]


def test_earlier_snapshot_fails_to_claim_once_batch_grew():
    buffer = ImageBatchBuffer()

    first_snapshot = buffer.add("sender-1", "msg-1")
    buffer.add("sender-1", "msg-2")

    assert buffer.try_claim("sender-1", len(first_snapshot)) is None


def test_latest_snapshot_claims_the_full_batch():
    buffer = ImageBatchBuffer()

    buffer.add("sender-1", "msg-1")
    second_snapshot = buffer.add("sender-1", "msg-2")

    claimed = buffer.try_claim("sender-1", len(second_snapshot))

    assert claimed == ["msg-1", "msg-2"]


def test_claim_pops_the_batch_so_it_cannot_be_claimed_twice():
    buffer = ImageBatchBuffer()

    snapshot = buffer.add("sender-1", "msg-1")
    buffer.try_claim("sender-1", len(snapshot))

    assert buffer.try_claim("sender-1", len(snapshot)) is None


def test_claim_on_unknown_key_returns_none():
    buffer = ImageBatchBuffer()

    assert buffer.try_claim("no-such-sender", 1) is None


def test_different_senders_have_independent_batches():
    buffer = ImageBatchBuffer()

    buffer.add("sender-1", "a-msg-1")
    snapshot_b = buffer.add("sender-2", "b-msg-1")

    claimed_b = buffer.try_claim("sender-2", len(snapshot_b))

    assert claimed_b == ["b-msg-1"]
    # sender-1's batch is untouched
    assert buffer.try_claim("sender-1", 1) == ["a-msg-1"]
