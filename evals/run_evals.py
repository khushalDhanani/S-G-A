"""Run the golden questions against the configured LLM and write a JSON report."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sap_agent.cli.main import build_agent

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = yaml.safe_load((ROOT / "evals/golden_set.yaml").read_text())
    agent, client = build_agent()
    results = []
    try:
        for case in cases:
            answer = agent.run(case["question"])
            missing = [
                fact for fact in case["expected_facts"] if fact.lower() not in answer.lower()
            ]
            results.append(
                {
                    "question": case["question"],
                    "answer": answer,
                    "expected_facts": case["expected_facts"],
                    "missing_facts": missing,
                    "passed": not missing,
                }
            )
    finally:
        client.close()
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "results": results,
    }
    output = ROOT / "evals/reports/latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
