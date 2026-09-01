from conftest import build_client, make_recipe


def test_health_reports_ok_corpus_size_and_revision():
    corpus = [make_recipe("soup", "Soup", "Soup. A soup.")]
    client, _ = build_client(corpus)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["corpus_size"] == 1
    # The deployed commit, baked in at build time — CI waits for this to match
    # the revision it pushed before running evals against production.
    assert "git_sha" in body
