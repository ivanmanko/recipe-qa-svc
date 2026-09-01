"""Run the golden set against a deployed (or local) instance.

    uv run python evals/run_evals.py --target https://<host> [--report path]

Every 200 response is validated against the AskResponse Pydantic model and
the SPEC §3.1 invariants; each case's expected properties from
golden_set.yaml are then asserted. Prints a pass/fail table, writes a JSON
report, exits non-zero on any failure.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recipe_qa.schemas import AskResponse  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_corpus_by_id() -> dict[str, dict]:
    corpus = json.loads((ROOT / "data" / "corpus.json").read_text())
    return {r["id"]: r for r in corpus}


def check_invariants(body: AskResponse, corpus: dict[str, dict]) -> list[str]:
    """SPEC §3.1 invariants 1–5. Returns a list of violations."""
    errors = []
    if body.refused:
        if body.refusal_reason is None:
            errors.append("refused=true but refusal_reason is null")
        elif body.refusal_reason.value in ("out_of_corpus", "out_of_domain") and body.citations:
            errors.append(f"{body.refusal_reason} refusal must have no citations")
    else:
        if body.refusal_reason is not None:
            errors.append("refused=false but refusal_reason is set")
        if not body.answer:
            errors.append("refused=false but answer is empty")
        if not body.citations:
            errors.append("refused=false but citations are empty")
    for citation in body.citations:
        entry = corpus.get(citation.recipe_id)
        if entry is None:
            errors.append(f"citation {citation.recipe_id!r} is not a corpus recipe")
        elif citation.title != entry["title"] or citation.url != entry["url"]:
            errors.append(f"citation {citation.recipe_id!r} title/url mismatch with corpus")
    if not body.request_id:
        errors.append("request_id missing")
    return errors


def check_expectations(expect: dict, body: AskResponse, corpus: dict[str, dict]) -> list[str]:
    errors = []
    cited = [c.recipe_id for c in body.citations]
    if "refused" in expect and body.refused != expect["refused"]:
        errors.append(f"expected refused={expect['refused']}, got {body.refused}")
    if "refusal_reason" in expect:
        actual = body.refusal_reason.value if body.refusal_reason else None
        if actual != expect["refusal_reason"]:
            errors.append(f"expected refusal_reason={expect['refusal_reason']}, got {actual}")
    if "cites_any" in expect and not set(expect["cites_any"]) & set(cited):
        errors.append(f"expected any of {expect['cites_any']} cited, got {cited}")
    if "cites_all" in expect:
        missing = set(expect["cites_all"]) - set(cited)
        if missing:
            errors.append(f"expected all of {expect['cites_all']} cited, missing {sorted(missing)}")
    if "citations_satisfy" in expect:
        rules = expect["citations_satisfy"]
        for recipe_id in cited:
            entry = corpus.get(recipe_id)
            if entry is None:
                continue  # already reported by invariants
            if "max_time_minutes" in rules:
                limit = rules["max_time_minutes"]
                if entry["time_minutes"] is None or entry["time_minutes"] > limit:
                    errors.append(
                        f"cited {recipe_id} violates max_time_minutes={rules['max_time_minutes']} "
                        f"(has {entry['time_minutes']})"
                    )
            if "diet" in rules and rules["diet"] not in entry["diet_tags"]:
                errors.append(f"cited {recipe_id} lacks diet tag {rules['diet']!r}")
    return errors


def run_case(client: httpx.Client, case: dict, corpus: dict[str, dict]) -> dict:
    expect = case["expect"]
    started = time.perf_counter()
    response = client.post("/ask", json={"question": case["question"]})
    latency_ms = round((time.perf_counter() - started) * 1000)

    errors: list[str] = []
    refused = None
    if "http_status" in expect:
        if response.status_code != expect["http_status"]:
            errors.append(f"expected HTTP {expect['http_status']}, got {response.status_code}")
    elif response.status_code != 200:
        errors.append(f"expected HTTP 200, got {response.status_code}: {response.text[:200]}")
    else:
        try:
            body = AskResponse.model_validate(response.json())
        except Exception as exc:
            errors.append(f"response violates AskResponse schema: {exc}")
        else:
            refused = body.refused
            errors += check_invariants(body, corpus)
            errors += check_expectations(expect, body, corpus)

    return {
        "id": case["id"],
        "question": case["question"],
        "passed": not errors,
        "errors": errors,
        "latency_ms": latency_ms,
        "refused": refused,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://localhost:8000", help="base URL")
    parser.add_argument("--report", default="evals/reports/latest.json")
    args = parser.parse_args()

    cases = yaml.safe_load((ROOT / "evals" / "golden_set.yaml").read_text())
    corpus = load_corpus_by_id()

    results = []
    with httpx.Client(base_url=args.target, timeout=60) as client:
        for case in cases:
            result = run_case(client, case, corpus)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status}  {result['id']:36} {result['latency_ms']:>6} ms")
            for error in result["errors"]:
                print(f"      - {error}")

    latencies = sorted(r["latency_ms"] for r in results)
    answered = sorted(
        r["latency_ms"] for r in results if r["refused"] is False
    )
    summary = {
        "target": args.target,
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
        "latency_ms": {
            "p50_all": latencies[len(latencies) // 2],
            "max_all": latencies[-1],
            "mean_llm_answered": round(statistics.mean(answered)) if answered else None,
            "max_llm_answered": answered[-1] if answered else None,
        },
        "results": results,
    }
    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{summary['passed']}/{summary['total']} passed; report: {args.report}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
