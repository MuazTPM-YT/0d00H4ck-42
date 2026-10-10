def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_stream_rejects_unknown_topic(client_as):
    from app.modules.auth.models import Role

    res = client_as(Role.supervisor).get("/api/stream?topics=stock,bogus")
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "topics"
