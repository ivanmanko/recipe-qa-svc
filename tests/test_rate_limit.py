"""Tests for the per-IP rate limiter (SPEC §7.15).

Deliberately in-process and dependency-free: the service is a single stateless
instance, so a sliding window in memory is the honest scope. Time is injected
so the tests never sleep.
"""

import pytest
from conftest import build_client, llm_json, make_recipe

from recipe_qa.rate_limit import SlidingWindowLimiter

CORPUS = [
    make_recipe(
        "soup",
        "Soup",
        "Soup. A soup.",
        ingredients=["water"],
        steps=["Boil."],
    )
]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock)
        assert [limiter.check("1.2.3.4").allowed for _ in range(3)] == [True] * 3

    def test_blocks_beyond_the_limit(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        assert limiter.check("1.2.3.4").allowed is False

    def test_retry_after_counts_until_the_oldest_call_expires(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")
        clock.advance(20)
        decision = limiter.check("1.2.3.4")
        assert decision.allowed is False
        assert decision.retry_after == 40

    def test_window_slides(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        assert limiter.check("1.2.3.4").allowed is False
        clock.advance(61)
        assert limiter.check("1.2.3.4").allowed is True

    def test_clients_are_independent(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=clock)
        assert limiter.check("1.1.1.1").allowed is True
        assert limiter.check("2.2.2.2").allowed is True
        assert limiter.check("1.1.1.1").allowed is False

    def test_idle_clients_are_forgotten(self):
        """Otherwise the map grows without bound on a public endpoint."""
        clock = FakeClock()
        limiter = SlidingWindowLimiter(limit=5, window_seconds=60, clock=clock)
        limiter.check("1.1.1.1")
        clock.advance(3600)
        limiter.check("2.2.2.2")
        assert limiter.tracked_clients() == 1


class TestAskIsLimited:
    def test_429_after_the_limit_with_retry_after(self):
        client, llm = build_client(CORPUS, rate_limit_per_minute=2)
        for _ in range(2):
            client.post("/ask", json={"question": "What is the capital of France?"})
        response = client.post("/ask", json={"question": "What is the capital of France?"})
        assert response.status_code == 429
        assert response.json()["detail"] == "rate_limited"
        assert int(response.headers["Retry-After"]) > 0

    def test_limit_is_not_spent_on_rejected_requests(self):
        """A 429 must not itself count, or a client hammering the endpoint
        could never recover within the window."""
        client, _ = build_client(CORPUS, rate_limit_per_minute=1)
        client.post("/ask", json={"question": "What is the capital of France?"})
        first = client.post("/ask", json={"question": "What is the capital of France?"})
        second = client.post("/ask", json={"question": "What is the capital of France?"})
        assert first.status_code == 429
        assert int(second.headers["Retry-After"]) <= int(first.headers["Retry-After"])

    def test_other_endpoints_are_not_limited(self):
        # /health is the deploy probe and must never be throttled.
        client, _ = build_client(CORPUS, rate_limit_per_minute=1)
        client.post("/ask", json={"question": "What is the capital of France?"})
        client.post("/ask", json={"question": "What is the capital of France?"})
        assert client.get("/health").status_code == 200
        assert client.get("/recipes/soup").status_code == 200

    def test_disabled_when_limit_is_zero(self):
        client, _ = build_client(CORPUS, rate_limit_per_minute=0)
        for _ in range(5):
            response = client.post(
                "/ask", json={"question": "What is the capital of France?"}
            )
            assert response.status_code == 200


class TestGenerationIsBounded:
    def test_max_tokens_is_sent(self):
        # SPEC §7.14 — a runaway generation must be bounded in cost and time.
        from conftest import MockLLM

        llm = MockLLM([llm_json(answer="ok", citation_ids=["soup"])])
        client, llm = build_client(CORPUS, llm)
        client.post("/ask", json={"question": "how do I make soup?"})
        (_, params), = llm.calls
        assert params["max_tokens"] == 1024


@pytest.mark.parametrize("limit", [1, 5, 20])
def test_limiter_never_allows_more_than_limit(limit: int):
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=limit, window_seconds=60, clock=clock)
    allowed = sum(limiter.check("1.2.3.4").allowed for _ in range(limit * 3))
    assert allowed == limit
