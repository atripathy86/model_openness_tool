from fastapi.testclient import TestClient

from model_openness_tool.api import ApiSettings, create_app


class FakeDatabase:
    def __init__(self, ready: bool) -> None:
        self._ready = ready
        self.disposed = False

    def ready(self) -> bool:
        return self._ready

    def dispose(self) -> None:
        self.disposed = True


def test_api_is_unauthenticated_when_token_is_not_configured() -> None:
    app = create_app(ApiSettings(), database=None)

    with TestClient(app) as client:
        health = client.get("/health")
        catalog = client.get("/v1/catalog")
        readiness = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert catalog.status_code == 200
    assert len(catalog.json()["components"]) == 17
    assert readiness.json() == {"ready": False, "database_configured": False}


def test_optional_bearer_authentication_protects_versioned_routes() -> None:
    app = create_app(ApiSettings(bearer_token="secret"), database=None)

    with TestClient(app) as client:
        missing = client.get("/v1/catalog")
        wrong = client.get("/v1/catalog", headers={"Authorization": "Bearer wrong"})
        accepted = client.get("/v1/catalog", headers={"Authorization": "Bearer secret"})
        health = client.get("/health")

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert health.status_code == 200


def test_readiness_uses_database_probe_and_disposes_engine() -> None:
    database = FakeDatabase(ready=True)
    app = create_app(ApiSettings(database_url="configured"), database=database)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.json() == {"ready": True, "database_configured": True}
    assert database.disposed is True
