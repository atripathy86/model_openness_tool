from pathlib import Path

from fastapi.testclient import TestClient

from model_openness_tool.api import ApiSettings, create_app
from model_openness_tool.jobs import EvaluationJobRequest, JobQueue
from model_openness_tool.persistence import Base, Database


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


def test_job_submission_and_status_routes_use_durable_database(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(database.engine)
    app = create_app(ApiSettings(database_url="configured"), database=database)

    with TestClient(app) as client:
        first = client.post("/v1/jobs", json={"model_id": "example/first"})
        submitted = client.post("/v1/jobs", json={"model_id": "example/model"})
        job_id = submitted.json()["job_id"]
        fetched = client.get(f"/v1/jobs/{job_id}")
        listed = client.get("/v1/jobs", params={"job_status": "queued", "limit": 1})
        next_page = client.get(
            "/v1/jobs",
            params={"job_status": "queued", "limit": 1, "cursor": listed.json()["next_cursor"]},
        )
        invalid_cursor = client.get("/v1/jobs", params={"cursor": "invalid"})

    assert first.status_code == 201
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "queued"
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == job_id
    assert [item["job_id"] for item in listed.json()["items"]] == [job_id]
    assert listed.json()["next_cursor"] is not None
    assert [item["job_id"] for item in next_page.json()["items"]] == [first.json()["job_id"]]
    assert next_page.json()["next_cursor"] is None
    assert invalid_cursor.status_code == 422


def test_manual_retry_route_only_accepts_failed_jobs(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(database.engine)
    queue = JobQueue(database)
    failed = queue.submit(EvaluationJobRequest(model_id="example/model", max_attempts=1))
    claimed = queue.claim("worker")
    assert claimed is not None
    queue.fail(failed.job_id, "failed")
    queued = queue.submit(EvaluationJobRequest(model_id="example/queued"))
    app = create_app(ApiSettings(database_url="configured"), database=database)

    with TestClient(app) as client:
        retried = client.post(f"/v1/jobs/{failed.job_id}/retry")
        conflict = client.post(f"/v1/jobs/{queued.job_id}/retry")
        missing = client.post("/v1/jobs/missing/retry")

    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["max_attempts"] == 2
    assert conflict.status_code == 409
    assert missing.status_code == 404
