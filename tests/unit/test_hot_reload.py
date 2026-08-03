"""
Tests for agent capability hot sensing + declaration persistence
(FR-智能体能力变更热感知, in-band channel first).
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from model_router.app import create_app
from model_router.core.auth import key_manager
from model_router.core.capabilities import (
    CapabilityRegistry,
    canonical_fingerprint,
    capability_registry,
)

SPEC_A = {"vector_db": {"type": "chroma", "endpoint": "http://localhost:8000"}}
SPEC_B = {
    "vector_db": {"type": "chroma", "endpoint": "http://localhost:9000"},  # upgraded
    "memory": {"type": "markdown_files", "path": "F:/AI/knowledge"},        # added
}


def _b64(obj: dict) -> str:
    return base64.b64encode(
        json.dumps(obj).encode("utf-8")
    ).decode("ascii")


# ------------------------------------------------------------------
# Fingerprint
# ------------------------------------------------------------------

def test_fingerprint_deterministic_and_order_free():
    fp1 = canonical_fingerprint({"a": {"type": "x"}, "b": {"type": "y"}})
    fp2 = canonical_fingerprint({"b": {"type": "y"}, "a": {"type": "x"}})
    assert fp1 == fp2
    assert len(fp1) == 16
    assert fp1 != canonical_fingerprint({"a": {"type": "z"}})


# ------------------------------------------------------------------
# Diff (FR §2.4 bidirectional change detection)
# ------------------------------------------------------------------

def test_diff_added_upgraded_removed():
    reg = CapabilityRegistry()
    reg.declare({"vector_db": {"type": "chroma"}, "memory": {"type": "md"}})
    diff = reg.diff({
        "vector_db": {"type": "chroma"},                    # unchanged
        "knowledge_base": {"type": "qmind"},                # added
        # memory removed
    })
    assert diff["added"] == ["knowledge_base"]
    assert diff["upgraded"] == []
    assert diff["removed"] == ["memory"]

    diff = reg.diff({"vector_db": {"type": "chroma", "endpoint": "x"}})
    assert diff["upgraded"] == ["vector_db"]


# ------------------------------------------------------------------
# Persistence (capabilities.json, api_keys.json style)
# ------------------------------------------------------------------

def test_declare_persists_and_reload(tmp_path):
    data_dir = str(tmp_path / "data")
    reg = CapabilityRegistry(data_dir=data_dir)
    reg.declare(SPEC_A, agent_id="hermes")
    assert (tmp_path / "data" / "capabilities.json").exists()

    fresh = CapabilityRegistry()
    fresh.bind(data_dir)
    assert fresh.enabled is True
    assert fresh.agent_id == "hermes"
    assert fresh.fingerprint == canonical_fingerprint(SPEC_A)
    assert fresh.list() == ["vector_db"]


def test_retract_persists(tmp_path):
    data_dir = str(tmp_path / "data")
    reg = CapabilityRegistry(data_dir=data_dir)
    reg.declare(SPEC_A, agent_id="hermes")
    reg.declare({})

    fresh = CapabilityRegistry()
    fresh.bind(data_dir)
    assert fresh.enabled is False


# ------------------------------------------------------------------
# In-band hot sensing (observe)
# ------------------------------------------------------------------

def test_observe_empty_fingerprint_ignored():
    reg = CapabilityRegistry()
    assert reg.observe("hermes", "")["action"] == "ignored"


def test_observe_matching_fingerprint_unchanged():
    reg = CapabilityRegistry()
    reg.declare(SPEC_A, agent_id="hermes")
    fp = canonical_fingerprint(SPEC_A)
    assert reg.observe("hermes", fp)["action"] == "unchanged"


def test_observe_changed_without_full_needs_full():
    reg = CapabilityRegistry()
    reg.declare(SPEC_A, agent_id="hermes")
    result = reg.observe("hermes", "deadbeefdeadbeef", "")
    assert result["action"] == "needs_full"
    assert reg.list() == ["vector_db"]  # untouched


def test_observe_hot_update_with_full_declaration():
    reg = CapabilityRegistry()
    reg.declare(SPEC_A, agent_id="hermes")
    fp_new = canonical_fingerprint(SPEC_B)
    result = reg.observe("hermes", fp_new, _b64(SPEC_B))
    assert result["action"] == "hot_updated"
    assert result["diff"]["added"] == ["memory"]
    assert result["diff"]["upgraded"] == ["vector_db"]
    assert reg.list() == ["memory", "vector_db"]
    assert reg.get("vector_db").endpoint == "http://localhost:9000"
    assert reg.fingerprint == fp_new


def test_observe_invalid_payload_keeps_state():
    reg = CapabilityRegistry()
    reg.declare(SPEC_A, agent_id="hermes")
    result = reg.observe("hermes", "deadbeefdeadbeef", "!!not-base64!!")
    assert result["action"] == "invalid_payload"
    assert reg.list() == ["vector_db"]


def test_observe_can_retract():
    reg = CapabilityRegistry()
    reg.declare(SPEC_A, agent_id="hermes")
    fp_empty = canonical_fingerprint({})
    result = reg.observe("hermes", fp_empty, _b64({}))
    assert result["action"] == "hot_updated"
    assert reg.enabled is False
    assert result["diff"]["removed"] == ["vector_db"]


# ------------------------------------------------------------------
# Audit events
# ------------------------------------------------------------------

def test_events_recorded_and_bounded(tmp_path):
    reg = CapabilityRegistry(data_dir=str(tmp_path / "data"))
    reg.declare(SPEC_A, agent_id="hermes")
    reg.declare(SPEC_B, agent_id="hermes")
    status = reg.get_status()
    assert len(status["recent_events"]) == 2
    assert status["recent_events"][-1]["diff"]["added"] == ["memory"]
    events_file = tmp_path / "data" / "instances" / "hermes" / "capability_events.jsonl"
    assert events_file.exists()
    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


# ------------------------------------------------------------------
# Integration: chat endpoint carries sensing headers
# ------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    key_manager._keys = {}
    key_manager._data_dir = str(tmp_path / "data")
    capability_registry.declare({})
    with TestClient(create_app({"m": {"name": "M"}}, data_dir=str(tmp_path / "data"))) as c:
        yield c
    key_manager._keys = {}
    capability_registry.declare({})


def test_chat_endpoint_inband_sensing(client, tmp_path):
    fp = canonical_fingerprint(SPEC_A)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={
            "X-Agent-Id": "hermes",
            "X-Agent-Capabilities": fp,
            "X-Agent-Capabilities-Full": _b64(SPEC_A),
        },
    )
    assert r.status_code == 501  # provider forwarding still pending
    assert capability_registry.enabled is True
    assert capability_registry.agent_id == "hermes"
    assert capability_registry.fingerprint == fp
    # second request with same fingerprint: unchanged, no duplicate events
    before = len(capability_registry.get_status()["recent_events"])
    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Agent-Id": "hermes", "X-Agent-Capabilities": fp},
    )
    assert len(capability_registry.get_status()["recent_events"]) == before
