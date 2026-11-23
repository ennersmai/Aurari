"""P2-04: tier API routes."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aura import tiers
from aura.api.routes.tiers import router
from aura.config import settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "tier_overrides.json"
    monkeypatch.setattr(settings, "tier_overrides_path", str(path))
    monkeypatch.setattr(settings, "model_stack_index", 2)
    tiers.reset_tier_cache()
    app = FastAPI()
    app.include_router(router, prefix="/system")
    yield TestClient(app), path
    tiers.reset_tier_cache()


def test_round_trip(env):
    client, path = env
    data = client.get("/system/tiers").json()
    assert data["active_index"] == 2
    assert [t["name"] for t in data["tiers"]] == ["lean", "core", "titan"]
    assert data["tiers"][2]["overrides"] == {}
    assert set(data["tiers"][0]["models"]) == {"l1", "l2", "l3", "l4", "l5"}
    r = client.post("/system/tiers/2", json={"tools_offered_max": 12})
    assert r.status_code == 200
    again = client.get("/system/tiers").json()["tiers"][2]
    assert again["overrides"] == {"tools_offered_max": 12}
    assert again["profile"]["tools_offered_max"] == 12
    assert again["profile"]["name"] == "titan"
    assert json.loads(path.read_text()) == {"2": {"tools_offered_max": 12}}


def test_validation(env):
    client, path = env
    assert client.post("/system/tiers/1", json={"tools_offered_max": 999}).status_code == 422
    assert client.post("/system/tiers/1", json={"bogus": 1}).status_code == 422
    assert client.post("/system/tiers/7", json={"tools_offered_max": 2}).status_code == 404
    assert client.post("/system/tiers/7/reset").status_code == 404
    assert not path.exists()


def test_applies_at_once(env):
    client, _ = env
    before = tiers.active_profile().turn_budget_usd
    client.post("/system/tiers/2", json={"turn_budget_usd": 0.5})
    assert tiers.active_profile().turn_budget_usd == 0.5 != before
    client.post("/system/tiers/2", json={"turn_budget_usd": 0.6})
    assert tiers.active_profile().turn_budget_usd == 0.6
    client.post("/system/tiers/2/reset")
    assert tiers.active_profile().turn_budget_usd == before


def test_reset_and_file_deleted(env):
    client, path = env
    client.post("/system/tiers/0", json={"tools_offered_max": 2})
    client.post("/system/tiers/1", json={"tools_offered_max": 7})
    client.post("/system/tiers/0/reset")
    assert json.loads(path.read_text()) == {"1": {"tools_offered_max": 7}}
    client.post("/system/tiers/1/reset")
    assert not path.exists()
    client.post("/system/tiers/1/reset")  # resetting nothing is fine
    assert client.get("/system/tiers").status_code == 200


def test_other_tiers_and_keys_preserved(env):
    client, path = env
    client.post("/system/tiers/0", json={"tools_offered_max": 2})
    client.post("/system/tiers/2", json={"tools_offered_max": 12})
    client.post("/system/tiers/2", json={"turn_budget_usd": 0.5})
    assert json.loads(path.read_text()) == {
        "0": {"tools_offered_max": 2},
        "2": {"tools_offered_max": 12, "turn_budget_usd": 0.5},
    }


def test_no_temp_file_left(env):
    client, path = env
    client.post("/system/tiers/0", json={"tools_offered_max": 2})
    client.post("/system/tiers/0", json={"tools_offered_max": 3})
    client.post("/system/tiers/1", json={"tools_offered_max": 99999})
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_d3_titan_only_knobs_cannot_be_granted(env):
    client, path = env
    for index in (0, 1):
        for knob in ("allow_delegate", "allow_task_graph"):
            assert client.post(f"/system/tiers/{index}", json={knob: True}).status_code == 422
    assert client.post("/system/tiers/2", json={"allow_delegate": False}).status_code == 200
    assert client.post("/system/tiers/1", json={"name": "titan"}).status_code == 422


def test_d3_hand_edited_file_granting_delegate_is_ignored(env, monkeypatch):
    import json as _json
    from aura import tiers
    from aura.config import settings
    client, path = env
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"0": {"allow_delegate": True}}), encoding="utf-8")
    tiers.reset_tier_cache()
    monkeypatch.setattr(settings, "model_stack_index", 0)
    assert tiers.active_profile().allow_delegate is False
    assert tiers.tool_allowed(tiers.active_profile(), "delegate_work") is False


def test_snapshot_survives_invalid_file(env):
    import json as _json
    client, path = env
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"1": {"allow_delegate": True}}), encoding="utf-8")
    r = client.get("/system/tiers")
    assert r.status_code == 200
    assert r.json()["tiers"][1]["profile"]["allow_delegate"] is False
