"""
Tests for the v1.0.4 batch (FROM-HERMES-next):
- P1#3 multi-signal classification (system prompt signals)
- P2#7 offline evaluator (learning value quantification)
- Agent capability adapter layer, static declaration phase
"""

import pytest
from fastapi.testclient import TestClient

from model_router.app import create_app
from model_router.core.auth import key_manager
from model_router.core.capabilities import (
    CapabilityAdapter,
    CapabilityDeclaration,
    CapabilityRegistry,
    capability_registry,
)
from model_router.core.classifier import DomainClassifier
from model_router.core.evaluator import OfflineEvaluator
from model_router.core.memory import MemoryStore


# ------------------------------------------------------------------
# P1#3: multi-signal classification (system prompt scan)
# ------------------------------------------------------------------

def test_system_prompt_boosts_coding():
    clf = DomainClassifier()
    feats = clf.classify([
        {"role": "system", "content": "You are a coding assistant for debugging."},
        {"role": "user", "content": "ok"},
    ])
    assert feats.domain_scores["coding"] >= 0.4
    assert any(p.startswith("coding:sys_coding") for p in feats.matched_patterns)


def test_no_system_message_no_sys_patterns():
    clf = DomainClassifier()
    feats = clf.classify([{"role": "user", "content": "hi"}])
    assert not any("sys_" in p for p in feats.matched_patterns)


def test_system_vision_signal_enables_vision():
    clf = DomainClassifier()
    feats = clf.classify([
        {"role": "system", "content": "You analyze images with OCR."},
        {"role": "user", "content": "ok"},
    ])
    assert feats.requires_vision is True


def test_system_signal_fuses_with_user_patterns():
    clf = DomainClassifier()
    feats = clf.classify([
        {"role": "system", "content": "coding assistant"},
        {"role": "user", "content": "```python\nprint(1)\n```"},
    ])
    # code_block 0.8 + language_mention 0.4 + sys_coding 0.4
    assert feats.domain_scores["coding"] >= 1.6


# ------------------------------------------------------------------
# P2#7: offline evaluator
# ------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return MemoryStore(data_dir=str(tmp_path / "data"))


def _log(store, mode, fallback=False, model="m1", task="coding"):
    store.append_request_log({
        "request_id": f"r{store._stats['cost']['total_requests']}",
        "routing_mode": mode,
        "final_model": model,
        "failed_models": ["m0"] if fallback else [],
        "task": task,
    })


def test_evaluator_empty_history(store):
    rep = OfflineEvaluator(memory=store).evaluate()
    assert rep["sample_size"] == 0
    assert rep["conclusion"].startswith("insufficient_data")


def test_evaluator_learning_helps(store):
    for _ in range(8):
        _log(store, "static", fallback=True)
    for _ in range(8):
        _log(store, "learned", fallback=False)
    rep = OfflineEvaluator(memory=store).evaluate()
    assert rep["by_routing_mode"]["static"]["fallback_rate"] == 1.0
    assert rep["by_routing_mode"]["learned"]["fallback_rate"] == 0.0
    assert rep["conclusion"].startswith("learning_helps")


def test_evaluator_neutral_when_equal(store):
    for _ in range(4):
        _log(store, "static", fallback=False)
    for _ in range(4):
        _log(store, "learned", fallback=False)
    rep = OfflineEvaluator(memory=store).evaluate()
    assert rep["conclusion"].startswith("neutral")


def test_evaluator_learner_signals(store):
    store.update_model_stats("coding", "bad-model", {"mu": -0.8, "n": 50})
    store.update_model_stats("coding", "good-model", {"mu": 0.9, "n": 50})
    store.update_model_stats("chat", "neutral", {"mu": 0.1, "n": 50})
    store.update_model_stats("chat", "noisy", {"mu": -0.9, "n": 3})  # too few samples
    rep = OfflineEvaluator(memory=store).evaluate()
    verdicts = {s["model"]: s["verdict"] for s in rep["learner_signals"]}
    assert verdicts == {
        "bad-model": "learner_avoids",
        "good-model": "learner_prefers",
    }


def test_evaluator_counts_unique_models(store):
    _log(store, "learned", model="m1")
    _log(store, "learned", model="m2")
    _log(store, "learned", model="m1")
    rep = OfflineEvaluator(memory=store).evaluate()
    assert rep["by_routing_mode"]["learned"]["models_used"] == 2


# ------------------------------------------------------------------
# Capability adapter layer — static declaration
# ------------------------------------------------------------------

def test_registry_declare_and_status():
    reg = CapabilityRegistry()
    assert reg.enabled is False
    names = reg.declare({
        "vector_db": {
            "type": "chroma",
            "endpoint": "http://localhost:8000",
            "collection": "docs",
        },
        "memory": {"type": "markdown_files", "path": "F:/AI/knowledge"},
    })
    assert names == ["memory", "vector_db"]
    assert reg.enabled is True
    vec = reg.get("vector_db")
    assert vec.type == "chroma"
    assert vec.meta == {"collection": "docs"}
    status = reg.get_status()
    assert status["declared"]["memory"]["path"] == "F:/AI/knowledge"
    assert status["use_for"]["domain"] is False  # aggressive point stays off
    assert status["timeout_ms"] > 0


def test_registry_skips_invalid_declarations():
    reg = CapabilityRegistry()
    names = reg.declare({
        "broken": {"endpoint": "http://x"},  # missing type
        "not_a_dict": "chroma",
        "good": {"type": "mcp"},
    })
    assert names == ["good"]
    assert reg.list() == ["good"]


def test_registry_retract_all():
    reg = CapabilityRegistry()
    reg.declare({"memory": {"type": "markdown_files"}})
    assert reg.declare({}) == []
    assert reg.enabled is False


def test_registry_declare_replaces_previous():
    reg = CapabilityRegistry()
    reg.declare({"memory": {"type": "a"}})
    reg.declare({"vector_db": {"type": "b"}})
    assert reg.list() == ["vector_db"]


def test_adapter_placeholder_not_available():
    decl = CapabilityDeclaration(name="vector_db", type="chroma")
    assert CapabilityAdapter(decl).available() is False


# ------------------------------------------------------------------
# Admin API integration
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


def test_admin_evaluate_endpoint(client):
    r = client.get("/admin/evaluate")
    assert r.status_code == 200
    body = r.json()
    assert "by_routing_mode" in body
    assert "learner_signals" in body
    assert "conclusion" in body


def test_admin_capabilities_roundtrip(client):
    r = client.get("/admin/capabilities")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = client.put("/admin/capabilities", json={"capabilities": {
        "vector_db": {"type": "chroma", "endpoint": "http://localhost:8000"},
    }})
    assert r.status_code == 200
    assert r.json()["declared"] == ["vector_db"]

    r = client.get("/admin/capabilities")
    assert r.json()["enabled"] is True
    assert "vector_db" in r.json()["declared"]

    # retract everything
    r = client.put("/admin/capabilities", json={"capabilities": {}})
    assert r.json()["count"] == 0
    assert client.get("/admin/capabilities").json()["enabled"] is False
