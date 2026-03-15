import pytest
import time
from breadmind.network.protocol import (
    MessageEnvelope, MessageType, create_message,
    serialize_message, deserialize_message,
    MessageIntegrityError, MessageSequenceError,
)

def test_create_message_has_required_fields():
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"cpu": 0.5},
    )
    assert msg.protocol_version == 1
    assert msg.id is not None
    assert msg.type == MessageType.HEARTBEAT
    assert msg.source == "worker-1"
    assert msg.target == "commander"
    assert msg.payload == {"cpu": 0.5}
    assert msg.timestamp is not None
    assert msg.seq == 0  # initial seq

def test_serialize_deserialize_roundtrip():
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={"task": "check_pods"},
    )
    data = serialize_message(msg, session_key=b"test-key-32-bytes-long-enough!!")
    restored = deserialize_message(data, session_key=b"test-key-32-bytes-long-enough!!")
    assert restored.id == msg.id
    assert restored.type == msg.type
    assert restored.payload == msg.payload

def test_deserialize_tampered_message_raises():
    msg = create_message(
        type=MessageType.COMMAND,
        source="commander",
        target="worker-1",
        payload={"action": "restart"},
    )
    data = serialize_message(msg, session_key=b"test-key-32-bytes-long-enough!!")
    # Tamper with payload
    import json
    obj = json.loads(data)
    obj["payload"]["action"] = "delete"
    tampered = json.dumps(obj)
    with pytest.raises(MessageIntegrityError):
        deserialize_message(tampered, session_key=b"test-key-32-bytes-long-enough!!")

def test_message_types_complete():
    expected = {
        "task_assign", "task_result", "llm_request", "llm_response",
        "heartbeat", "sync", "role_update", "command",
    }
    actual = {t.value for t in MessageType}
    assert expected == actual

def test_create_message_with_trace_id():
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={},
        trace_id="trace-123",
        reply_to="msg-456",
    )
    assert msg.trace_id == "trace-123"
    assert msg.reply_to == "msg-456"


from breadmind.network.protocol import SequenceTracker

def test_sequence_tracker_increments():
    tracker = SequenceTracker()
    assert tracker.next_seq() == 1
    assert tracker.next_seq() == 2
    assert tracker.next_seq() == 3

def test_sequence_tracker_validates_incoming():
    tracker = SequenceTracker()
    tracker.validate_incoming(1)  # OK
    tracker.validate_incoming(2)  # OK
    with pytest.raises(MessageSequenceError):
        tracker.validate_incoming(5)  # Gap

def test_sequence_tracker_rejects_replay():
    tracker = SequenceTracker()
    tracker.validate_incoming(1)
    with pytest.raises(MessageSequenceError):
        tracker.validate_incoming(1)  # Replay
