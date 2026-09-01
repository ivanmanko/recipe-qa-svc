from fastapi.testclient import TestClient

from recipe_qa.app import app


def test_health_reports_ok_and_corpus_size():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["corpus_size"], int)
