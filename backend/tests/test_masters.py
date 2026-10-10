from app.modules.auth.models import Role

FABRIC = {
    "code": "drill30",
    "name": "Cotton Drill",
    "width_cm": "152",
    "gsm": "220",
    "process_loss_pct": "8",
    "stages": [{"seq": 1, "stage": "spinning"}, {"seq": 2, "stage": "weaving"}],
    "recipe": [{"fibre": "Cotton", "count": "Ne 30/1", "share_pct": "100"}],
}


def test_create_and_replace_fabric_route(client_as):
    owner = client_as(Role.owner)
    res = owner.post("/api/masters/fabric-types", json=FABRIC)
    assert res.status_code == 201, res.text
    ft = res.json()
    assert [s["stage"] for s in ft["stages"]] == ["spinning", "weaving"]

    updated = owner.put(
        f"/api/masters/fabric-types/{ft['id']}",
        json={**FABRIC, "stages": [{"seq": 1, "stage": "weaving"}, {"seq": 2, "stage": "dyeing"}]},
    )
    assert updated.status_code == 200, updated.text
    assert [s["stage"] for s in updated.json()["stages"]] == ["weaving", "dyeing"]


def test_recipe_must_sum_to_100(client_as):
    bad = {**FABRIC, "recipe": [{"fibre": "Cotton", "count": "Ne 30/1", "share_pct": "90"}]}
    res = client_as(Role.owner).post("/api/masters/fabric-types", json=bad)
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "recipe"


def test_route_must_include_weaving(client_as):
    bad = {**FABRIC, "stages": [{"seq": 1, "stage": "spinning"}]}
    res = client_as(Role.owner).post("/api/masters/fabric-types", json=bad)
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "stages"


def test_worker_rate_must_match_wage_type(client_as):
    res = client_as(Role.owner).post(
        "/api/masters/workers",
        json={"code": "W-900", "name": "Ravi", "wage_type": "piece", "daily_rate_paise": 65000},
    )
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "piece_rate_paise_per_m"


def test_any_logged_in_role_can_read_masters(client_as):
    res = client_as(Role.qc).get("/api/masters/machines?limit=5")
    assert res.status_code == 200
    assert set(res.json()) == {"items", "total"}


def test_list_paginates_and_rejects_bad_limit(client_as):
    assert client_as(Role.owner).get("/api/masters/buyers?limit=0").status_code == 422
