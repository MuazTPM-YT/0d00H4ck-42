def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_stream_rejects_unknown_topic(client_as):
    from app.modules.auth.models import Role

    res = client_as(Role.supervisor).get("/api/stream?topics=stock,bogus")
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "topics"


# the login check's session is closed before streaming starts: an open tab pins no DB connection
def test_stream_closes_its_db_session_before_streaming(db, make_user, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import events
    from app.core.db import get_db
    from app.core.security import create_token
    from app.main import app
    from app.modules.auth.models import Role

    order = []

    def tracked():
        order.append("session open")
        try:
            yield db
        finally:
            order.append("session closed")

    # one message, then end: the test client waits for the whole body
    async def one_message(topics):
        order.append("streaming")
        yield "retry: 3000\n\n"

    monkeypatch.setattr(events, "stream", one_message)
    user = make_user(Role.supervisor)
    app.dependency_overrides[get_db] = tracked
    try:
        headers = {"Authorization": f"Bearer {create_token(user.id, user.role)}"}
        res = TestClient(app).get("/api/stream?topics=stock", headers=headers)
        assert res.status_code == 200
        assert order == ["session open", "session closed", "streaming"]
    finally:
        app.dependency_overrides.clear()
