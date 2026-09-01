"""Contract tests for POST /ask (SPEC §3.1, §4, §6) with a mocked LLM.

Every refusal branch, the grounding guard and the invariants are asserted
here deterministically; the real model is only ever exercised by the eval
harness.
"""

from conftest import MockLLM, StubEmbedder, llm_json, make_recipe
from conftest import build_client as build_client_base
from fastapi.testclient import TestClient

CARBONARA = make_recipe(
    "carbonara",
    "Spaghetti alla Carbonara",
    "Spaghetti alla Carbonara. Italian pasta with eggs, pecorino and guanciale.",
    time_minutes=60,
    ingredients=["400 g spaghetti", "4 eggs", "100 g pecorino"],
    steps=["Boil pasta.", "Mix eggs and cheese.", "Combine."],
)
LENTIL_SOUP = make_recipe(
    "lentil-soup",
    "Lentil Soup",
    "Lentil Soup. A warming soup of red lentils and vegetables.",
    time_minutes=25,
    diet_tags=["vegetarian", "vegan"],
    ingredients=["1 cup red lentils", "1 onion"],
    steps=["Simmer lentils."],
)
CORPUS = [CARBONARA, LENTIL_SOUP]


def build_client(llm=None, embedder=None, **settings_overrides) -> tuple[TestClient, MockLLM]:
    return build_client_base(CORPUS, llm, embedder, **settings_overrides)


def assert_invariants(body: dict):
    """SPEC §3.1 invariants, checked on every response in these tests."""
    if body["refused"]:
        assert body["refusal_reason"] in ("out_of_corpus", "out_of_domain", "safety")
        if body["refusal_reason"] != "safety":
            assert body["citations"] == []
    else:
        assert body["refusal_reason"] is None
        assert body["answer"]
        assert body["citations"]
    assert body["request_id"]


class TestValidation:
    def test_empty_question_is_422(self):
        client, _ = build_client()
        assert client.post("/ask", json={"question": ""}).status_code == 422

    def test_whitespace_question_is_422(self):
        client, _ = build_client()
        assert client.post("/ask", json={"question": "   "}).status_code == 422

    def test_too_long_question_is_422(self):
        client, _ = build_client()
        assert client.post("/ask", json={"question": "x" * 501}).status_code == 422

    def test_missing_body_is_422(self):
        client, _ = build_client()
        assert client.post("/ask", json={}).status_code == 422


class TestSafetyGate:
    def test_allergy_question_refuses_without_llm(self):
        client, llm = build_client()
        response = client.post("/ask", json={"question": "Is the carbonara nut-free?"})
        assert response.status_code == 200
        body = response.json()
        assert_invariants(body)
        assert body["refused"] is True
        assert body["refusal_reason"] == "safety"
        assert body["citations"]  # points at the recipes whose ingredients are shown
        assert "eggs" in body["answer"]  # ingredient list is included
        assert llm.calls == []  # deterministic branch, $0

    def test_only_relevant_recipes_are_cited(self):
        # SPEC §7.3: weak top-k padding must not appear under a safety
        # question — listing an unrelated dish's ingredients misleads.
        question = "Is the carbonara nut-free?"
        embedder = StubEmbedder(
            {
                question: [1.0, 0.0, 0.0],
                CARBONARA.text: [1.0, 0.0, 0.0],  # cosine 1.0 — relevant
                LENTIL_SOUP.text: [0.0, 1.0, 0.0],  # cosine 0.0 — padding
            }
        )
        client, _ = build_client(
            embedder=embedder, vector_score_threshold=0.5, bm25_score_threshold=999.0
        )
        body = client.post("/ask", json={"question": question}).json()
        assert body["refusal_reason"] == "safety"
        assert [c["recipe_id"] for c in body["citations"]] == ["carbonara"]
        assert "lentil" not in body["answer"].lower()

    def test_no_relevant_recipe_still_refuses_without_ingredients(self):
        client, llm = build_client(bm25_score_threshold=999.0, vector_score_threshold=999.0)
        body = client.post("/ask", json={"question": "Is sushi safe for a nut allergy?"}).json()
        assert_invariants(body)
        assert body["refused"] is True
        assert body["refusal_reason"] == "safety"
        assert body["citations"] == []
        assert llm.calls == []

    def test_safe_for_phrasing_triggers(self):
        client, llm = build_client()
        body = client.post(
            "/ask", json={"question": "Is lentil soup safe for pregnant women?"}
        ).json()
        assert body["refusal_reason"] == "safety"
        assert llm.calls == []


class TestRelevanceGate:
    def test_below_threshold_refuses_out_of_domain_without_llm(self):
        # SPEC §4 stage 5: sub-threshold means "not even food-shaped";
        # dish-level absence is the model's call, not the gate's.
        client, llm = build_client(
            vector_score_threshold=999.0, bm25_score_threshold=999.0
        )
        body = client.post("/ask", json={"question": "what is the capital of France?"}).json()
        assert_invariants(body)
        assert body["refused"] is True
        assert body["refusal_reason"] == "out_of_domain"
        assert body["citations"] == []
        assert llm.calls == []

    def test_constraints_emptying_candidates_refuse_out_of_corpus(self):
        client, llm = build_client()
        body = client.post(
            "/ask", json={"question": "a vegan dinner in under 10 minutes"}
        ).json()
        assert body["refused"] is True
        assert body["refusal_reason"] == "out_of_corpus"
        assert llm.calls == []


class TestGeneration:
    def test_grounded_answer_maps_citations(self):
        llm = MockLLM([llm_json(answer="Boil the pasta, then mix.", citation_ids=["carbonara"])])
        client, llm = build_client(llm)
        response = client.post("/ask", json={"question": "how do I make carbonara?"})
        body = response.json()
        assert_invariants(body)
        assert body["refused"] is False
        assert body["citations"] == [
            {
                "title": "Spaghetti alla Carbonara",
                "url": "https://example.org/carbonara",
                "recipe_id": "carbonara",
            }
        ]
        assert response.headers["x-request-id"] == body["request_id"]

    def test_prompt_contains_only_retrieved_recipes_and_question(self):
        llm = MockLLM([llm_json(answer="ok", citation_ids=["carbonara"])])
        client, llm = build_client(llm)
        client.post("/ask", json={"question": "how do I make carbonara?"})
        (messages, params), = llm.calls
        user_message = messages[-1]["content"]
        assert "how do I make carbonara?" in user_message
        assert "carbonara" in user_message

    def test_hallucinated_citation_ids_are_dropped(self):
        llm = MockLLM([llm_json(answer="ok", citation_ids=["carbonara", "not-a-recipe"])])
        client, _ = build_client(llm)
        body = client.post("/ask", json={"question": "how do I make carbonara?"}).json()
        assert [c["recipe_id"] for c in body["citations"]] == ["carbonara"]

    def test_all_citations_invalid_becomes_out_of_corpus(self):
        llm = MockLLM([llm_json(answer="made up", citation_ids=["not-a-recipe"])])
        client, _ = build_client(llm)
        body = client.post("/ask", json={"question": "how do I make carbonara?"}).json()
        assert_invariants(body)
        assert body["refused"] is True
        assert body["refusal_reason"] == "out_of_corpus"

    def test_model_refusal_out_of_domain(self):
        llm = MockLLM([llm_json(refused=True, refusal_reason="out_of_domain")])
        client, _ = build_client(llm)
        body = client.post(
            "/ask", json={"question": "recipe for happiness in life generally"}
        ).json()
        assert_invariants(body)
        assert body["refused"] is True
        assert body["refusal_reason"] == "out_of_domain"
        assert body["citations"] == []

    def test_json_object_mode_is_default_response_format(self):
        # DeepSeek supports only json_object (SPEC §7.11); strict json_schema
        # is opt-in via llm_supports_json_schema for providers that have it.
        llm = MockLLM([llm_json(answer="ok", citation_ids=["carbonara"])])
        client, llm = build_client(llm)
        client.post("/ask", json={"question": "how do I make carbonara?"})
        (_, params), = llm.calls
        assert params["response_format"] == {"type": "json_object"}

    def test_invalid_output_retried_once_then_succeeds(self):
        llm = MockLLM(["this is not json", llm_json(answer="ok", citation_ids=["carbonara"])])
        client, llm = build_client(llm)
        body = client.post("/ask", json={"question": "how do I make carbonara?"}).json()
        assert body["refused"] is False
        assert len(llm.calls) == 2

    def test_llm_failure_is_503_not_a_refusal(self):
        llm = MockLLM(error=RuntimeError("provider down"))
        client, _ = build_client(llm)
        response = client.post("/ask", json={"question": "how do I make carbonara?"})
        assert response.status_code == 503
        assert response.json()["detail"] == "generation_unavailable"
