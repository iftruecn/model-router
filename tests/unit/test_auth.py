"""
Unit + integration tests for virtual API keys (v1.0.3, P0 #3).

Covers: key lifecycle, hashing/persistence, middleware enforcement,
zero-config activation, and master-key guarded management.
"""

import pytest
from fastapi.testclient import TestClient

from model_router.app import create_app
from model_router.core.auth import KeyManager, key_manager


@pytest.fixture
def km(tmp_path):
    """Fresh isolated KeyManager."""
    return KeyManager(data_dir=str(tmp_path / "data"))


@pytest.fixture
def client(tmp_path):
    """App with a clean global key_manager state."""
    key_manager._keys = {}
    key_manager._data_dir = str(tmp_path / "data")
    with TestClient(create_app({"m": {"name": "M"}}, data_dir=str(tmp_path / "data"))) as c:
        yield c
    key_manager._keys = {}


# ------------------------------------------------------------------
# KeyManager unit tests
# ------------------------------------------------------------------

def test_create_and_verify(km):
    raw, record = km.create_key(label="hermes")
    assert raw.startswith("mr-sk-")
    assert record["label"] == "hermes"
    assert "..." in record["masked"]
    assert km.verify(raw) is not None
    assert km.verify("mr-sk-wrong") is None
    assert km.verify("") is None


def test_raw_key_never_persisted(km):
    raw, _ = km.create_key()
    records = km.list_keys()
    serialized = str(records)
    assert raw not in serialized  # only the mask is stored


def test_disable_key(km):
    raw, record = km.create_key()
    assert km.verify(raw) is not None
    assert km.set_enabled(record["key_id"], False)
    assert km.verify(raw) is None  # disabled -> rejected
    assert km.set_enabled(record["key_id"], True)
    assert km.verify(raw) is not None


def test_delete_key(km):
    raw, record = km.create_key()
    assert km.delete_key(record["key_id"])
    assert km.verify(raw) is None
    assert km.delete_key("k_missing") is False


def test_usage_tracking(km):
    raw, record = km.create_key()
    km.verify(raw)
    km.record_usage(record["key_id"], estimated_cost=0.01)
    km.record_usage(record["key_id"], estimated_cost=0.02)
    usage = km.list_keys()[0]["usage"]
    assert usage["requests"] == 2
    assert abs(usage["estimated_cost"] - 0.03) < 1e-9
    assert usage["last_used"] is not None


@pytest.mark.asyncio
async def test_persistence_roundtrip(km):
    raw, record = km.create_key(label="persist")
    await km.save()

    fresh = KeyManager(data_dir=km.data_dir)
    await fresh.load()
    assert fresh.verify(raw) is not None
    assert fresh.list_keys()[0]["label"] == "persist"


def test_master_key_env(km, monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_MASTER_KEY", "master-secret")
    assert km.auth_enabled  # master key alone activates auth
    record = km.verify("master-secret")
    assert record is not None and record["key_id"] == "__master__"
    assert km.is_master("master-secret")
    assert not km.is_master("nope")


def test_auth_kill_switch(km, monkeypatch):
    km.create_key()
    assert km.auth_enabled
    monkeypatch.setenv("MODEL_ROUTER_AUTH_DISABLED", "1")
    assert not km.auth_enabled


# ------------------------------------------------------------------
# Middleware integration tests
# ------------------------------------------------------------------

def test_open_access_without_keys(client):
    """Zero-config: everything stays open until the first key exists."""
    assert client.get("/v1/models").status_code == 200
    assert client.get("/admin/learning").status_code == 200


def test_auth_activates_on_first_key(client):
    # Create first key (open while auth inactive)
    r = client.post("/admin/keys", json={"label": "agent"})
    assert r.status_code == 200
    api_key = r.json()["api_key"]
    assert api_key.startswith("mr-sk-")

    # Protected paths now require a key
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer bad"}).status_code == 401

    # Valid key passes
    r = client.get("/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 200

    # Public paths stay open
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


def test_key_usage_counted(client):
    r = client.post("/admin/keys", json={"label": "metered"})
    api_key = r.json()["api_key"]
    key_id = r.json()["key_id"]

    headers = {"Authorization": f"Bearer {api_key}"}
    client.get("/v1/models", headers=headers)
    client.get("/v1/models", headers=headers)

    # Auth is now active, so listing keys needs a key too (no master set)
    listed = client.get("/admin/keys", headers=headers).json()["keys"]
    usage = next(k["usage"] for k in listed if k["key_id"] == key_id)
    assert usage["requests"] == 2


def test_management_requires_master_when_active(client, monkeypatch):
    r = client.post("/admin/keys", json={"label": "first"})  # activates auth
    virtual_key = r.json()["api_key"]
    monkeypatch.setenv("MODEL_ROUTER_MASTER_KEY", "m-secret")

    # No header -> middleware rejects with 401
    assert client.get("/admin/keys").status_code == 401
    # Plain virtual key -> master guard rejects with 403
    assert client.get(
        "/admin/keys", headers={"Authorization": f"Bearer {virtual_key}"}
    ).status_code == 403

    # With master key -> allowed
    headers = {"Authorization": "Bearer m-secret"}
    assert client.get("/admin/keys", headers=headers).status_code == 200
    r = client.post("/admin/keys", json={"label": "second"}, headers=headers)
    assert r.status_code == 200

    # Master key also passes protected API paths
    assert client.get("/v1/models", headers=headers).status_code == 200


def test_management_without_master_allows_valid_key(client):
    """No master configured: any valid virtual key can manage keys (no lockout)."""
    r = client.post("/admin/keys", json={"label": "self-service"})
    api_key = r.json()["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    assert client.get("/admin/keys", headers=headers).status_code == 200
    assert client.post("/admin/keys", json={"label": "more"}, headers=headers).status_code == 200


def test_revoke_key_via_api(client):
    r = client.post("/admin/keys", json={"label": "doomed"})
    api_key, key_id = r.json()["api_key"], r.json()["key_id"]
    headers = {"Authorization": f"Bearer {api_key}"}

    assert client.delete(f"/admin/keys/{key_id}", headers=headers).json()["deleted"]
    # Revoking the LAST key deactivates auth (zero-config symmetry) -> open again
    assert client.get("/v1/models", headers=headers).status_code == 200
    # A new key reactivates auth, and the revoked key stays dead
    r2 = client.post("/admin/keys", json={"label": "survivor"})
    assert r2.status_code == 200
    assert client.get("/v1/models").status_code == 401
