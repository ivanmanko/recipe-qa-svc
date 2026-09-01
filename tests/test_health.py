from conftest import build_client, make_recipe


def test_health_reports_ok_and_corpus_size():
    corpus = [make_recipe("soup", "Soup", "Soup. A soup.")]
    client, _ = build_client(corpus)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "corpus_size": 1}
