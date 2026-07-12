import base64
from datetime import UTC, datetime

import httpx

from model_openness_tool.connectors.github import GitHubConnector, GitHubRestClient
from model_openness_tool.evidence import AccessStatus


def test_github_collection_pins_commit_and_collects_tree_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/repos/example/model":
            return httpx.Response(
                200,
                json={
                    "full_name": "example/model",
                    "default_branch": "main",
                    "private": False,
                    "archived": False,
                    "license": {"spdx_id": "MIT"},
                },
            )
        if request.url.path == "/repos/example/model/commits/main":
            return httpx.Response(200, json={"sha": "a" * 40})
        if request.url.path == f"/repos/example/model/git/trees/{'a' * 40}":
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {"path": "src/train.py", "type": "blob", "sha": "train", "size": 50},
                        {"path": "src", "type": "tree", "sha": "folder"},
                        {"path": "README.md", "type": "blob", "sha": "readme", "size": 10},
                        {"path": "LICENSE", "type": "blob", "sha": "license", "size": 12},
                    ],
                },
            )
        if request.url.path == "/repos/example/model/git/blobs/license":
            content = base64.b64encode(b"license text").decode()
            return httpx.Response(
                200,
                json={"encoding": "base64", "content": content, "size": 12},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    http = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    connector = GitHubConnector(
        GitHubRestClient(token="secret", client=http),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    result = connector.collect("https://github.com/example/model/tree/develop")

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.repository_url == "https://github.com/example/model"
    assert result.snapshot.requested_revision is None
    assert result.snapshot.resolved_revision == "a" * 40
    assert result.snapshot.declared_license == "MIT"
    assert result.evidence_report is not None
    assert [file.path for file in result.snapshot.files] == ["LICENSE", "README.md", "src/train.py"]
    assert result.snapshot.text_artifacts[0].path == "LICENSE"
    assert result.snapshot.text_artifacts[0].content == "license text"
    tree_request = next(request for request in requests if "/git/trees/" in request.url.path)
    assert tree_request.url.params["recursive"] == "1"
    assert all(request.headers["authorization"] == "Bearer secret" for request in requests)
    assert "secret" not in result.model_dump_json()


def test_github_collection_maps_missing_repository_to_structured_error() -> None:
    http = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={})),
    )

    result = GitHubConnector(GitHubRestClient(client=http)).collect(
        "https://github.com/example/missing"
    )

    assert result.access_status == AccessStatus.MISSING
    assert result.snapshot is None
    assert "not found" in (result.error or "")


def test_github_collection_rejects_truncated_tree() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/example/model":
            return httpx.Response(
                200,
                json={
                    "full_name": "example/model",
                    "default_branch": "main",
                    "private": False,
                    "archived": False,
                },
            )
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": "a" * 40})
        return httpx.Response(200, json={"truncated": True, "tree": []})

    http = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )

    result = GitHubConnector(GitHubRestClient(client=http)).collect(
        "https://github.com/example/model"
    )

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "GitHub returned a truncated repository tree"


def test_github_collection_rejects_non_repository_url() -> None:
    http = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    result = GitHubConnector(GitHubRestClient(client=http)).collect(
        "https://github.com/topics/models"
    )

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "Input is not a valid GitHub repository URL"
