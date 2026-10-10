from app.modules.auth.models import Role
from app.modules.production.models import WorkOrderStatus
from tests.mill import Mill

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


MACHINE_KEYS = ("code", "name", "type", "hourly_cost_paise", "rated_output_per_hour")


# a machine with jobs on it stays active and keeps its type; a rename is fine
def test_machine_with_open_jobs_keeps_type_and_stays_active(client_as, db):
    mill = Mill(db)
    mill.work_order(mill.order(), status=WorkOrderStatus.queued)
    db.commit()
    owner = client_as(Role.owner)
    url = f"/api/masters/machines/{mill.loom.id}"
    m = owner.get(url).json()
    body = {**{k: m[k] for k in MACHINE_KEYS}, "output_unit": m["output_unit"], "active": True}
    for change in ({"active": False}, {"type": "dyeing"}):
        res = owner.put(url, json={**body, **change})
        assert res.status_code == 409 and res.json()["error"]["code"] == "in_use", change
    assert owner.put(url, json={**body, "name": "Loom one"}).status_code == 200


# route, recipe and spec drive yarn needs and when rolls reach QC: frozen while orders are open
def test_fabric_spec_frozen_while_orders_are_open(client_as, db):
    mill = Mill(db)
    mill.order()
    db.commit()
    owner = client_as(Role.owner)
    url = f"/api/masters/fabric-types/{mill.fabric.id}"
    f = owner.get(url).json()
    body = {
        **{k: f[k] for k in ("code", "name", "width_cm", "gsm", "process_loss_pct", "active")},
        "stages": [{"seq": s["seq"], "stage": s["stage"]} for s in f["stages"]],
        "recipe": [{k: r[k] for k in ("fibre", "count", "share_pct")} for r in f["recipe"]],
    }
    res = owner.put(url, json={**body, "gsm": "130"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "in_use"
    dyed = [{"seq": 1, "stage": "weaving"}, {"seq": 2, "stage": "dyeing"}]
    assert owner.put(url, json={**body, "stages": dyed}).status_code == 409
    assert owner.put(url, json={**body, "name": "Renamed shirting"}).status_code == 200
